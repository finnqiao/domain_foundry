"""Wizard engine: the goal → working-domain state machine (plan §6).

Channel-agnostic and resumable. Both ``new_domain`` and ``wizard_reply`` on
``HarnessAPI`` delegate here, so chat, CLI, and the app shell drive the same
engine. Generation runs the real pack system end to end:
generate → ``pack validate`` → dry-run routing → activate → test-drive →
hardening.
"""

from __future__ import annotations

import re
import shutil
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Any

from domain_foundry_core.evals.runner import score_case
from domain_foundry_core.llm.provider import HeuristicProvider
from domain_foundry_core.packs.loader import PackValidationError, load_pack
from domain_foundry_core.packs.registry import PackRegistry
from domain_foundry_core.paths import Workspace
from domain_foundry_core.routing.router import Router
from domain_foundry_core.security.store import connect_ro
from domain_foundry_core.wizard import blueprint as bp
from domain_foundry_core.wizard.hardening import apply_plan, build_plan, looks_like_edit
from domain_foundry_core.wizard.session import WizardSession, WizardSessionStore

if TYPE_CHECKING:
    from domain_foundry_core.api.harness import HarnessAPI

_CONFIRM_RE = re.compile(r"\b(yes|yep|confirm|apply|do it|ok|okay|looks good|go ahead)\b", re.IGNORECASE)
_CANCEL_RE = re.compile(r"\b(no|cancel|nevermind|never mind|stop|discard)\b", re.IGNORECASE)
_DONE_RE = re.compile(r"\b(done|finish(?:ed)?|that'?s all|all set|complete)\b", re.IGNORECASE)

DRY_RUN_THRESHOLD = 0.95
MAX_REGEN_ROUNDS = 3


class WizardEngine:
    def __init__(self, harness: HarnessAPI) -> None:
        self.harness = harness
        self.ws = harness.workspace
        self.store = WizardSessionStore(self.ws)

    # ------------------------------------------------------------- public API
    def new_domain(self, goal_text: str, *, test_drive: int = 5) -> dict[str, Any]:
        session = self.store.new(goal_text, test_drive=test_drive)
        blueprint = bp.build_blueprint(goal_text)
        blueprint["domain"] = self._unique_domain(blueprint["domain"])
        agent = blueprint.get("agent")
        if isinstance(agent, dict):
            agent["name"] = blueprint["domain"]
        else:
            blueprint["agent"] = bp.build_agent_spec(blueprint)
        session.blueprint = blueprint
        session.domain = blueprint["domain"]
        session.questions = blueprint.get("questions", [])
        session.history.append({"role": "user", "text": goal_text})
        self.store.save(session)
        return self._proposal_turn(session)

    def wizard_reply(self, session_id: str, text: str) -> dict[str, Any]:
        session = self.store.load(session_id)
        if session is None:
            return {"error": f"unknown wizard session: {session_id}", "session_id": session_id}
        session.history.append({"role": "user", "text": text})

        if session.state == "interview":
            return self._handle_interview(session, text)
        if session.state == "test_drive":
            return self._handle_test_drive(session, text)
        if session.state == "hardening_confirm":
            return self._handle_hardening_confirm(session, text)
        if session.state in {"done", "failed"}:
            return self._turn(session, message="This wizard session is closed. Start a new domain to continue.")
        return self._turn(session, message="Unexpected wizard state.")

    def suggest_hardening(self, domain: str, *, threshold: int = 3) -> dict[str, Any] | None:
        """§8.4 hook: repeated corrections of one field → suggested pack edit."""
        conn = connect_ro(self.ws.ledger_db)
        try:
            rows = conn.execute(
                """
                SELECT reason_code, COUNT(*) AS n
                FROM correction_event
                WHERE entry_id IN (
                    SELECT id FROM entry WHERE domain = ?
                )
                GROUP BY reason_code
                ORDER BY n DESC
                """,
                (domain,),
            ).fetchall()
        except Exception:
            return None
        finally:
            conn.close()
        for r in rows:
            if int(r["n"]) >= threshold and r["reason_code"] not in {"undo", "mark_wrong"}:
                return {
                    "domain": domain,
                    "reason_code": r["reason_code"],
                    "count": int(r["n"]),
                    "suggestion": (
                        f"You've corrected '{r['reason_code']}' {r['n']}× in {domain}. "
                        "Want to harden the pack (e.g. fix a unit or add a field)?"
                    ),
                }
        return None

    # ------------------------------------------------------------- interview
    def _handle_interview(self, session: WizardSession, text: str) -> dict[str, Any]:
        answers = bp.parse_answers(text, session.questions)
        session.answers.update(answers)
        session.blueprint = bp.apply_answer(session.blueprint, session.answers)
        self.store.save(session)
        return self._generate(session)

    # ------------------------------------------------------------- generate
    def _generate(self, session: WizardSession) -> dict[str, Any]:
        draft_dir = self.store.draft_dir(session.session_id)
        if draft_dir.exists():
            shutil.rmtree(draft_dir)
        blueprint = session.blueprint

        report: dict[str, Any] = {}
        for _round in range(MAX_REGEN_ROUNDS + 1):
            bp.write_pack(blueprint, draft_dir, version=session.pack_version)
            try:
                load_pack(draft_dir, validate=True)
            except PackValidationError as exc:
                session.state = "failed"
                self.store.save(session)
                return self._turn(session, message=f"Generated pack failed validation: {exc}")

            report = self._dry_run(draft_dir)
            if report["accuracy"] >= DRY_RUN_THRESHOLD:
                break
            # Failures regenerate with feedback: add targeted rules (plan §6.1).
            if not self._add_feedback_rules(blueprint, report["failures"]):
                break

        session.dry_run = report
        if report["accuracy"] < DRY_RUN_THRESHOLD:
            session.state = "failed"
            self.store.save(session)
            return self._turn(
                session,
                message=(
                    f"Dry-run routing only reached {report['accuracy']:.0%} "
                    f"({report['routed']}/{report['total']}); needs ≥{DRY_RUN_THRESHOLD:.0%}."
                ),
            )

        # Activate: install the validated pack into the live workspace.
        installed = self.harness.packs.add(draft_dir, force=True)
        session.domain = installed.name
        session.pack_version = installed.version
        session.pack_path = str(installed.root)
        session.activated = True
        session.state = "test_drive"
        # Hot-register Expert child config with Supervisor (launchd stubbed).
        expert = self.harness.register_expert(installed.name)
        self.store.save(session)
        turn = self._activated_turn(session)
        turn["expert"] = expert
        turn["agent"] = (
            installed.agent.model_dump() if installed.agent is not None else None
        )
        return turn

    def _dry_run(self, draft_dir: Path) -> dict[str, Any]:
        pack = load_pack(draft_dir, validate=True)
        cases = []
        for ex in pack.routing.examples:
            expect = {
                "domain": pack.name,
                "object_type": ex.expect.get("object"),
                "operation": ex.expect.get("operation", "create"),
            }
            cases.append({"raw_text": ex.text, "expected": {"captures": [expect]}})

        tmp = Path(tempfile.mkdtemp(prefix="wiz_dry_"))
        try:
            tmp_ws = Workspace(tmp)
            reg = PackRegistry(tmp_ws)
            reg.add(draft_dir, force=True)
            router = Router(tmp_ws, registry=reg, llm=HeuristicProvider(), cost_cap=999)
            total = 0
            correct = 0
            failures: list[dict[str, Any]] = []
            for case in cases:
                result = router.route_text(case["raw_text"], channel="wizard")
                spans = [
                    {
                        "domain": s.domain,
                        "object_type": s.object_type,
                        "operation": s.operation,
                        "fields": s.fields,
                    }
                    for s in result.spans
                ]
                scored = score_case(case, spans)
                total += 1
                if scored.ok:
                    correct += 1
                else:
                    want = case["expected"]["captures"][0]
                    failures.append({"text": case["raw_text"], "expected_object": want["object_type"]})
            accuracy = correct / total if total else 0.0
            return {"total": total, "routed": correct, "accuracy": accuracy, "failures": failures}
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def _add_feedback_rules(self, blueprint: dict[str, Any], failures: list[dict[str, Any]]) -> bool:
        added = False
        for fail in failures:
            token = _distinctive_token(fail["text"])
            obj = fail["expected_object"]
            if not token or not obj:
                continue
            blueprint["rules"].append({
                "match": re.escape(token),
                "object": obj,
                "confidence_boost": 0.15,
                "operation": "create",
            })
            added = True
        return added

    # ------------------------------------------------------------ test-drive
    def _handle_test_drive(self, session: WizardSession, text: str) -> dict[str, Any]:
        stripped = text.strip()
        if _DONE_RE.search(stripped) and not looks_like_edit(stripped):
            session.state = "done"
            self.store.save(session)
            return self._turn(session, message=f"Domain '{session.domain}' is ready. Happy tracking!", done=True)

        if looks_like_edit(stripped):
            return self._start_hardening(session, stripped)

        receipt = self.harness.capture(text, channel="wizard")
        entry_id = receipt.entry_id
        session.captured_entries.append(entry_id)
        session.test_drive_remaining = max(0, session.test_drive_remaining - 1)
        self.store.save(session)
        return self._capture_turn(session, receipt)

    # -------------------------------------------------------------- hardening
    def _start_hardening(self, session: WizardSession, text: str) -> dict[str, Any]:
        self.harness.packs.reload()
        pack = self.harness.packs.get(str(session.domain))
        if pack is None:
            return self._turn(session, message="Cannot harden: the domain is not installed.")
        plan = build_plan(text, pack)
        if not plan.ok:
            return self._turn(
                session,
                message=f"I couldn't turn that into a schema change: {plan.error}",
            )
        session.pending_edit = {"text": text, "plan": plan.to_dict()}
        session.state = "hardening_confirm"
        self.store.save(session)
        return self._diff_turn(session, plan.to_dict())

    def _handle_hardening_confirm(self, session: WizardSession, text: str) -> dict[str, Any]:
        if looks_like_edit(text):
            # A new edit supersedes the pending one.
            session.state = "test_drive"
            return self._start_hardening(session, text.strip())
        if _CANCEL_RE.search(text) and not _CONFIRM_RE.search(text):
            session.pending_edit = {}
            session.state = "test_drive"
            self.store.save(session)
            return self._turn(session, message="Edit discarded. Keep test-driving or describe another change.")
        if not _CONFIRM_RE.search(text):
            return self._diff_turn(
                session, session.pending_edit.get("plan", {}),
                message="Reply 'confirm' to apply this edit, or 'cancel' to discard.",
            )

        pack = self.harness.packs.get(str(session.domain))
        if pack is None:
            return self._turn(session, message="Cannot apply: the domain is not installed.")
        edit_text = session.pending_edit.get("text", "")
        plan = build_plan(edit_text, pack)
        result = apply_plan(self.ws, pack, plan, edit_text=edit_text)
        self.harness.packs.reload()
        session.pending_edit = {}
        session.pack_version = result.get("version", session.pack_version)
        session.state = "test_drive"
        self.store.save(session)
        msg = (
            f"Applied. Migration {result.get('migration')} added "
            f"{', '.join(result.get('added') or []) or 'changes'} to "
            f"{session.domain}.{plan.object} (v{result.get('version')}). "
            "Keep capturing, edit again, or say 'done'."
        )
        turn = self._turn(session, message=msg)
        turn["hardening"] = result
        return turn

    # ------------------------------------------------------------------ views
    def _proposal_turn(self, session: WizardSession) -> dict[str, Any]:
        b = session.blueprint
        objects = [
            {
                "name": name,
                "title_field": obj["title_field"],
                "fields": list(obj["fields"]),
            }
            for name, obj in b["objects"].items()
        ]
        message = (
            f"Here's a proposal for '{b['title']}' ({b['domain']}): "
            f"{len(objects)} object(s), {len(b['examples'])} example utterances. "
            f"I have {len(session.questions)} quick question(s) — answer any, or reply 'skip' to accept defaults."
        )
        turn = self._turn(session, message=message, awaiting="answers")
        turn["proposal"] = {
            "domain": b["domain"],
            "title": b["title"],
            "description": b["description"],
            "interpretation": b["interpretation"],
            "objects": objects,
            "example_count": len(b["examples"]),
            "archetype": b.get("archetype"),
        }
        turn["questions"] = session.questions
        return turn

    def _activated_turn(self, session: WizardSession) -> dict[str, Any]:
        message = (
            f"'{session.domain}' is live (v{session.pack_version}). "
            f"Dry-run routed {session.dry_run['routed']}/{session.dry_run['total']} "
            f"examples ({session.dry_run['accuracy']:.0%}). "
            f"Send me {session.test_drive_remaining} sample messages to test-drive it — "
            "I'll explain each routing decision. You can also describe a schema edit anytime."
        )
        turn = self._turn(session, message=message, awaiting="capture")
        turn["pack"] = {
            "name": session.domain,
            "version": session.pack_version,
            "path": session.pack_path,
        }
        turn["dry_run"] = session.dry_run
        return turn

    def _capture_turn(self, session: WizardSession, receipt: Any) -> dict[str, Any]:
        routed = [
            {
                "domain": s.domain,
                "object_type": s.object_type,
                "operation": s.operation,
                "disposition": s.disposition,
                "confidence": s.confidence,
            }
            for s in receipt.routed
        ]
        explanation = self._explain(receipt, routed)
        turn = self._turn(session, message=explanation, awaiting="capture")
        turn["capture"] = {
            "entry_id": receipt.entry_id,
            "status": receipt.status,
            "routed": routed,
            "test_drive_remaining": session.test_drive_remaining,
            "correct_hint": (
                "If that's wrong, reply e.g. \"no, that was <domain>\" or "
                "\"actually it was 80 not 75\" — I'll correct it in one message."
            ),
        }
        return turn

    def _explain(self, receipt: Any, routed: list[dict[str, Any]]) -> str:
        if not routed or receipt.status in {"ledger_only", "unfiled"}:
            return (
                f"Captured (status: {receipt.status}). I couldn't confidently route that "
                "into your new domain — it's safely stored. Try phrasing closer to your examples."
            )
        parts = []
        for r in routed:
            parts.append(
                f"→ {r['domain']}.{r['object_type']} ({r['operation']}, "
                f"confidence {float(r['confidence']):.0%}, {r['disposition']})"
            )
        return "Routed: " + "; ".join(parts) + "."

    def _diff_turn(self, session: WizardSession, plan: dict[str, Any], *, message: str | None = None) -> dict[str, Any]:
        summary = "; ".join(plan.get("summary") or []) or "no changes"
        msg = message or (
            f"Proposed edit to {plan.get('domain')}.{plan.get('object')}: {summary}. "
            "Reply 'confirm' to apply (writes a migration), or 'cancel'."
        )
        turn = self._turn(session, message=msg, awaiting="confirm")
        turn["diff"] = plan
        return turn

    def _turn(
        self,
        session: WizardSession,
        *,
        message: str,
        awaiting: str | None = None,
        done: bool = False,
    ) -> dict[str, Any]:
        session.history.append({"role": "assistant", "text": message})
        self.store.save(session)
        return {
            "session_id": session.session_id,
            "state": session.state,
            "message": message,
            "awaiting": awaiting,
            "done": done or session.state == "done",
            "domain": session.domain,
        }

    # ------------------------------------------------------------------ util
    def _unique_domain(self, name: str) -> str:
        self.harness.packs.reload()
        existing = {p.name for p in self.harness.packs.list()}
        if name not in existing:
            return name
        for i in range(2, 100):
            candidate = f"{name}_{i}"
            if candidate not in existing:
                return candidate
        return f"{name}_{__import__('secrets').token_hex(2)}"


def _distinctive_token(text: str) -> str | None:
    words = [w for w in re.findall(r"[a-zA-Z]{4,}", text.lower()) if w not in bp._STOPWORDS]
    if not words:
        return None
    return max(words, key=len)
