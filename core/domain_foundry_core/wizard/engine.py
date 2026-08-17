"""Wizard engine: the goal → working-domain state machine (plan §6).

Channel-agnostic and resumable. Both ``new_domain`` and ``wizard_reply`` on
``HarnessAPI`` delegate here, so chat, CLI, and the app shell drive the same
engine. Generation runs the real pack system end to end:
generate → ``pack validate`` → dry-run routing → activate → test-drive →
hardening.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Any

from domain_foundry_core.atlas.loader import load_atlas
from domain_foundry_core.atlas.query import query_neighborhood
from domain_foundry_core.clock import now_iso
from domain_foundry_core.config import load_llm_config
from domain_foundry_core.evals.runner import score_case
from domain_foundry_core.llm.provider import (
    CassetteProvider,
    HeuristicProvider,
    LLMProvider,
    build_tiered_provider,
    resolve_tier_settings,
)
from domain_foundry_core.packs.loader import PackValidationError, load_pack
from domain_foundry_core.packs.registry import PackRegistry
from domain_foundry_core.paths import Workspace
from domain_foundry_core.routing.router import Router
from domain_foundry_core.security.store import connect_ro
from domain_foundry_core.wizard import blueprint as bp
from domain_foundry_core.wizard.acceptance import (
    ACCEPTANCE_THRESHOLD,
    acceptance_run,
    load_suite,
    select_cases,
)
from domain_foundry_core.wizard.design import DesignError, LLMBlueprintDesigner
from domain_foundry_core.wizard.fork import parse_fork_reply
from domain_foundry_core.wizard.hardening import apply_plan, build_plan, looks_like_edit
from domain_foundry_core.wizard.jobs import compile_jobs, shortlist_for_ideas
from domain_foundry_core.wizard.models import validate_blueprint
from domain_foundry_core.wizard.session import WizardSession, WizardSessionStore

if TYPE_CHECKING:
    from domain_foundry_core.api.harness import HarnessAPI

_CONFIRM_RE = re.compile(r"\b(yes|yep|confirm|apply|do it|ok|okay|looks good|go ahead)\b", re.IGNORECASE)
_CANCEL_RE = re.compile(r"\b(no|cancel|nevermind|never mind|stop|discard)\b", re.IGNORECASE)
_DONE_RE = re.compile(r"\b(done|finish(?:ed)?|that'?s all|all set|complete)\b", re.IGNORECASE)
_KEEP_SCAFFOLD_RE = re.compile(r"\bkeep(?:\s+it)?\s+(?:as\s+)?a?\s*scaffold\b", re.IGNORECASE)

DRY_RUN_THRESHOLD = 0.95
MAX_REGEN_ROUNDS = 3
MAX_REPAIR_ROUNDS = 3
_DESIGN_INPUT_TOKENS = 6_000
_DESIGN_OUTPUT_TOKENS = 2_500
_HELDOUT_FILENAME = "wizard_hobby_suite.jsonl"


class WizardEngine:
    def __init__(self, harness: HarnessAPI) -> None:
        self.harness = harness
        self.ws = harness.workspace
        self.store = WizardSessionStore(self.ws)

    # ------------------------------------------------------------- public API
    def new_domain(self, goal_text: str, *, test_drive: int = 5) -> dict[str, Any]:
        session = self.store.new(goal_text, test_drive=test_drive)
        session.history.append({"role": "user", "text": goal_text})
        return self._open_fork(session)

    def _atlas_overlay(self) -> Any:
        overlay = self.ws.home / "atlas"
        return overlay if overlay.is_dir() else None

    def _open_fork(self, session: WizardSession, *, cursor_id: str | None = None) -> dict[str, Any]:
        nb = query_neighborhood(
            session.goal,
            overlay=self._atlas_overlay(),
            cursor_id=cursor_id or session.atlas_cursor,
        )
        session.state = "fork"
        session.atlas_cursor = nb.get("cursor")
        session.neighborhood = nb
        self.store.save(session)
        return self._fork_turn(session)

    def _fork_turn(self, session: WizardSession) -> dict[str, Any]:
        nb = session.neighborhood or {}
        crumb = " → ".join(b["title"] for b in nb.get("breadcrumb") or []) or "Ideas"
        refine = " · ".join(c["title"] for c in nb.get("refine") or []) or "—"
        expand = " · ".join(c["title"] for c in nb.get("expand") or []) or "—"
        ideas = nb.get("ideas") or []
        lines = []
        for i, idea in enumerate(ideas, start=1):
            mark = " (suggested)" if idea.get("highlighted") else ""
            analog = ""
            worlds = idea.get("world_analogs") or []
            if worlds:
                analog = f" — like {worlds[0]['name']}"
            elif idea.get("provenance") == "foundry":
                analog = " — fresh"
            lines.append(f"{i}. {idea.get('title')}{mark}{analog}: {idea.get('pitch') or ''}")
        idea_block = "\n".join(lines) if lines else "No catalogued ideas here yet — pick a simple log, or describe it."
        message = (
            f"{crumb}. Refine: {refine}. Also nearby: {expand}.\n"
            f"{idea_block}\n"
            "Pick an idea (or mix), go deeper, expand, ask to show schema, or say 'just a simple log'."
        )
        turn = self._turn(session, message=message, awaiting="fork")
        turn["neighborhood"] = nb
        turn["simple_log"] = True
        return turn

    def _handle_fork(self, session: WizardSession, text: str) -> dict[str, Any]:
        intent = parse_fork_reply(text, session.neighborhood or {})
        kind = intent.get("kind")
        if kind == "cancel":
            session.state = "failed"
            self.store.save(session)
            return self._turn(session, message="Cancelled. Start a new domain when you're ready.")
        if kind == "navigate":
            return self._open_fork(session, cursor_id=str(intent.get("node_id")))
        if kind == "something_else":
            session.neighborhood = session.neighborhood or {}
            turn = self._fork_turn(session)
            turn["message"] = (
                "Describe what you actually do, or the app you wish existed. "
                "I'll match a nearby idea or start a simple log."
            )
            return turn
        if kind == "simple_log":
            return self._design_and_activate(session, use_llm=False, tier="sota")
        if kind == "show_schema":
            ids = list(intent.get("idea_ids") or [])
            if not ids:
                ids = [i["id"] for i in (session.neighborhood or {}).get("ideas") or []][:1]
            return self._schema_preview(session, ids)
        if kind == "skip":
            ids = self._skip_idea_ids(session)
            if not ids:
                return self._design_and_activate(session, use_llm=False, tier="sota")
            return self._commit_ideas(session, ids)
        if kind == "commit":
            return self._commit_ideas(session, list(intent.get("idea_ids") or []))
        # Unknown: if it looks like a new goal, rematch; else repeat the neighborhood.
        if len(text.split()) >= 4:
            session.goal = text
            session.atlas_cursor = None
            return self._open_fork(session)
        turn = self._fork_turn(session)
        turn["message"] = "I didn't catch that. Pick an idea by name or number, refine a topic, or say 'just a simple log'."
        return turn

    def _skip_idea_ids(self, session: WizardSession) -> list[str]:
        ideas = list((session.neighborhood or {}).get("ideas") or [])
        highlighted = [i for i in ideas if i.get("highlighted")]
        pool = highlighted or ideas[:1]
        starter = bp.match_starter_pack(session.goal)
        if starter:
            want = str(starter.get("name") or "")
            for idea in pool:
                if idea.get("analog_pack") == want and self._bundled_pack_exists(want):
                    return [idea["id"]]
        if pool:
            return [pool[0]["id"]]
        return []

    def _bundled_pack_exists(self, name: str) -> bool:
        from domain_foundry_core.packs.loader import bundled_packs_root

        root = bundled_packs_root() / name
        return root.is_dir() and (root / "pack.yaml").is_file()

    def _commit_ideas(self, session: WizardSession, idea_ids: list[str]) -> dict[str, Any]:
        graph = load_atlas(self._atlas_overlay())
        ideas = [graph.get(i) for i in idea_ids]
        ideas = [i for i in ideas if i is not None]
        if not ideas:
            return self._design_and_activate(session, use_llm=False, tier="sota")
        session.selected_ideas = [i.id for i in ideas]
        session.selected_jobs = []
        for idea in ideas:
            for job in idea.jobs:
                if job not in session.selected_jobs:
                    session.selected_jobs.append(job)
        analog = ideas[0].analog_pack if len(ideas) == 1 else None
        if analog and self._bundled_pack_exists(analog):
            starter = {"name": analog, "title": ideas[0].title, "description": ideas[0].pitch}
            return self._install_starter(session, starter)
        provider = self._tiered_provider()
        return self._design_and_activate_from_ideas(
            session, ideas, use_llm=provider.has_live_keys(), tier="sota"
        )

    def _schema_preview(self, session: WizardSession, idea_ids: list[str]) -> dict[str, Any]:
        graph = load_atlas(self._atlas_overlay())
        ideas = [graph.get(i) for i in idea_ids]
        ideas = [i for i in ideas if i is not None]
        if not ideas:
            return self._fork_turn(session)
        session.selected_ideas = [i.id for i in ideas]
        session.selected_jobs = []
        for idea in ideas:
            for job in idea.jobs:
                if job not in session.selected_jobs:
                    session.selected_jobs.append(job)
        shortlist = shortlist_for_ideas(ideas, goal=session.goal)
        preview = {
            "ideas": [i.id for i in ideas],
            "jobs": list(session.selected_jobs),
            "objects": list(shortlist.objects),
            "fields": [f.model_dump(exclude_none=True) for f in shortlist.fields],
            "analog_pack": ideas[0].analog_pack if len(ideas) == 1 else None,
            "identity_hint": ideas[0].identity_hint,
        }
        session.schema_preview = preview
        session.state = "schema_preview"
        self.store.save(session)
        message = (
            f"Schema for {', '.join(i.title for i in ideas)}: "
            f"objects {', '.join(shortlist.objects)}; "
            f"jobs {', '.join(session.selected_jobs) or 'event_log'}. "
            "Reply 'yes' to build it, or 'back' to pick again."
        )
        turn = self._turn(session, message=message, awaiting="schema_confirm")
        turn["schema_preview"] = preview
        turn["neighborhood"] = session.neighborhood
        return turn

    def _handle_schema_preview(self, session: WizardSession, text: str) -> dict[str, Any]:
        low = text.strip().lower()
        if re.search(r"\b(back|no|cancel|nevermind)\b", low):
            session.state = "fork"
            session.schema_preview = {}
            return self._fork_turn(session)
        if _CONFIRM_RE.search(low) or low in {"build", "activate", "go"}:
            return self._commit_ideas(session, list(session.selected_ideas))
        return self._schema_preview(session, list(session.selected_ideas))

    def _design_and_activate_from_ideas(
        self,
        session: WizardSession,
        ideas: list[Any],
        *,
        use_llm: bool,
        tier: str,
    ) -> dict[str, Any]:
        jobs = list(session.selected_jobs)
        kws = bp.keywords(session.goal)
        domain_hint = ideas[0].domain_slug if ideas else None
        if kws:
            kw = bp.slugify(kws[0])
            # First-word of the goal names the pack unless it's a bucket
            # ("food", "diving") — those are too coarse; keep the idea slug.
            graph = load_atlas(self._atlas_overlay())
            named = graph.get(kw)
            if domain_hint is None or named is None or named.kind != "bucket":
                domain_hint = kw
        blueprint: dict[str, Any] | None = None
        if use_llm:
            try:
                raw = LLMBlueprintDesigner().design(
                    session.goal,
                    llm=self._provider_with_cassette(self._tiered_provider()),
                    tier=tier,
                    jobs=jobs,
                )
                session.design_mode = "llm"
                settings = resolve_tier_settings(tier, home=self.ws.home)
                session.designer_model = settings.model
                meta_sl = (raw.get("meta") or {}).get("shortlist")
                if isinstance(meta_sl, list) and meta_sl:
                    from domain_foundry_core.wizard.shortlist import ShortlistModel

                    fallback = shortlist_for_ideas(ideas, goal=session.goal)
                    sl = ShortlistModel.model_validate(
                        {
                            "domain": raw.get("domain") or domain_hint or fallback.domain,
                            "title": raw.get("title") or fallback.title,
                            "description": raw.get("description") or fallback.description,
                            "objects": list((raw.get("objects") or {}).keys()) or fallback.objects,
                            "fields": meta_sl,
                            "jargon": fallback.jargon,
                            "examples": raw.get("examples") or fallback.model_dump()["examples"],
                            "negatives": raw.get("negatives") or fallback.negatives,
                        }
                    )
                    blueprint = compile_jobs(
                        sl, goal=session.goal, jobs=jobs, domain_hint=domain_hint
                    )
                else:
                    blueprint = compile_jobs(
                        shortlist_for_ideas(ideas, goal=session.goal),
                        goal=session.goal,
                        jobs=jobs,
                        domain_hint=domain_hint,
                    )
            except Exception as exc:
                session.design_fallback_reason = str(exc)
                blueprint = None
        if blueprint is None:
            try:
                blueprint = compile_jobs(
                    shortlist_for_ideas(ideas, goal=session.goal),
                    goal=session.goal,
                    jobs=jobs,
                    domain_hint=domain_hint,
                )
                if session.design_mode != "llm":
                    session.design_mode = "atlas"
            except Exception:
                return self._design_and_activate(session, use_llm=False, tier=tier)
        blueprint["domain"] = self._unique_domain(blueprint["domain"])
        agent = blueprint.get("agent")
        if isinstance(agent, dict):
            agent["name"] = blueprint["domain"]
        meta = blueprint.setdefault("meta", {})
        meta["atlas_ideas"] = [i.id for i in ideas]
        meta["atlas_cursor"] = session.atlas_cursor
        meta["jobs"] = jobs
        session.blueprint = blueprint
        session.domain = blueprint["domain"]
        session.questions = []
        session.state = "interview"
        self.store.save(session)
        return self._generate(session)

    def _install_starter(
        self, session: WizardSession, starter: dict[str, Any]
    ) -> dict[str, Any]:
        name = str(starter["name"])
        title = str(starter.get("title") or name)
        already = self.harness.packs.get(name) is not None
        if not already:
            installed = self.harness.activate_pack(name)
            # Prefer the activated pack's name/title (aliases resolve).
            name = str(installed.get("name") or name)
            title = str(installed.get("title") or title)
            pack = self.harness.packs.get(name)
        else:
            pack = self.harness.packs.get(name)
        if pack is None:
            # Fall through to scaffold if activate somehow failed.
            return self._design_and_activate(session, use_llm=False, tier="sota")

        session.design_mode = "starter"
        session.domain = pack.name
        session.pack_version = pack.version
        session.pack_path = str(pack.root)
        session.activated = True
        session.state = "test_drive"
        session.blueprint = {
            "domain": pack.name,
            "title": pack.manifest.title,
            "description": pack.manifest.description,
            "objects": {
                oname: {
                    "title_field": obj.title_field,
                    "fields": list(obj.fields.keys()),
                }
                for oname, obj in pack.objects.items()
            },
        }
        shortlist = [
            f.replace("_", " ")
            for obj in pack.objects.values()
            for f in list(obj.fields.keys())[:8]
        ]
        verb = "already here" if already else "Installed"
        chips = " · ".join(list(dict.fromkeys(shortlist))[:6]) if shortlist else ""
        message = (
            f"{verb} {title}. Talk about it and we'll file it"
            + (f" — {chips}." if chips else ".")
        )
        turn = self._turn(session, message=message, awaiting="capture")
        turn["pack"] = {
            "name": pack.name,
            "version": pack.version,
            "title": pack.manifest.title,
            "path": str(pack.root),
        }
        turn["status"] = "live"
        turn["shortlist"] = shortlist[:8]
        turn["proposal"] = {
            "domain": pack.name,
            "title": pack.manifest.title,
            "description": pack.manifest.description,
            "design_mode": "starter",
            "objects": [
                {"name": oname, "fields": list(obj.fields.keys())}
                for oname, obj in pack.objects.items()
            ],
        }
        return turn

    def _design_and_activate(
        self,
        session: WizardSession,
        *,
        use_llm: bool,
        tier: str,
    ) -> dict[str, Any]:
        """Design (or scaffold), skip interview, install, return ready-to-capture turn."""
        turn = self._design_and_propose(session, use_llm=use_llm, tier=tier)
        if session.state == "failed":
            return turn
        # Skip interview — apply defaults and generate/activate in one shot.
        if session.state == "interview":
            turn = self._generate(session)
            # A model pack that fails dry-run must not leave the user with
            # nothing installed — fall back to the labeled keyword scaffold.
            if (
                use_llm
                and session.state == "failed"
                and session.design_mode == "llm"
            ):
                reason = turn.get("message") or "model pack failed dry-run"
                return self._scaffold_after_llm_failure(session, reason=reason, tier=tier)
            return turn
        return turn

    def _scaffold_after_llm_failure(
        self,
        session: WizardSession,
        *,
        reason: str,
        tier: str,
    ) -> dict[str, Any]:
        """Install the deterministic scaffold after an LLM design could not activate."""
        session.design_fallback_reason = reason
        session.design_mode = "scaffold"
        session.designer_model = None
        session.state = "interview"
        session.activated = False
        session.pack_path = None
        session.domain = None
        session.dry_run = {}
        session.acceptance = {}
        session.blueprint = {}
        session.questions = []
        session.answers = {}
        turn = self._design_and_propose(session, use_llm=False, tier=tier)
        # Preserve the LLM failure reason (propose clears it only when design_error set).
        session.design_fallback_reason = reason
        if session.state == "failed":
            return turn
        if session.state == "interview":
            return self._generate(session)
        return turn

    def wizard_reply(self, session_id: str, text: str) -> dict[str, Any]:
        session = self.store.load(session_id)
        if session is None:
            return {"error": f"unknown wizard session: {session_id}", "session_id": session_id}
        session.history.append({"role": "user", "text": text})

        if session.state == "fork":
            return self._handle_fork(session, text)
        if session.state == "schema_preview":
            return self._handle_schema_preview(session, text)
        if session.state == "model_confirm":
            return self._handle_model_confirm(session, text)
        if session.state == "interview":
            return self._handle_interview(session, text)
        if session.state == "test_drive":
            return self._handle_test_drive(session, text)
        if session.state == "repair":
            return self._handle_repair(session, text)
        if session.state == "hardening_confirm":
            return self._handle_hardening_confirm(session, text)
        if session.state in {"done", "failed"}:
            return self._turn(session, message="This wizard session is closed. Start a new domain to continue.")
        return self._turn(session, message="Unexpected wizard state.")

    def _model_confirm_turn(self, session: WizardSession) -> dict[str, Any]:
        from domain_foundry_core.llm.pricing import estimate_cost_usd

        settings = resolve_tier_settings("sota", home=self.ws.home)
        routine = resolve_tier_settings("routine", home=self.ws.home)
        estimate = round(
            estimate_cost_usd(
                model=settings.model,
                input_tokens=_DESIGN_INPUT_TOKENS,
                output_tokens=_DESIGN_OUTPUT_TOKENS,
            ),
            4,
        )
        message = (
            "Designing a domain is one deliberate call to a stronger reasoning "
            "model than your everyday chat model — domain design benefits from "
            f"it. I'd use {settings.model} (your sota tier), estimated "
            f"~${estimate:.2f} for this design. Reply 'yes' to go ahead, "
            f"'use routine' to design with {routine.model} instead, or "
            "'no model' to build a keyword scaffold without any model call."
        )
        turn = self._turn(session, message=message, awaiting="model_confirm")
        cfg = load_llm_config(self.ws.home)
        turn["designer"] = {
            "provider": cfg.provider or "tiered",
            "tier": "sota",
            "model": settings.model,
            "est_cost_usd": float(estimate),
            "routine_model": routine.model,
        }
        return turn

    def _handle_model_confirm(self, session: WizardSession, text: str) -> dict[str, Any]:
        low = text.strip().lower()
        if "routine" in low:
            return self._design_and_propose(session, use_llm=True, tier="routine")
        if re.search(r"\bno\s+model\b", low) or (
            _CANCEL_RE.search(low) and not _CONFIRM_RE.search(low)
        ):
            return self._design_and_propose(session, use_llm=False, tier="sota")
        if _CONFIRM_RE.search(low):
            return self._design_and_propose(session, use_llm=True, tier="sota")
        return self._model_confirm_turn(session)

    def _design_and_propose(
        self,
        session: WizardSession,
        *,
        use_llm: bool,
        tier: str,
    ) -> dict[str, Any]:
        blueprint: dict[str, Any] | None = None
        design_error: str | None = None
        if use_llm:
            settings = resolve_tier_settings(tier, home=self.ws.home)
            try:
                blueprint = LLMBlueprintDesigner().design(
                    session.goal,
                    llm=self._provider_with_cassette(self._tiered_provider()),
                    tier=tier,
                )
                session.design_mode = "llm"
                session.designer_model = settings.model
            except DesignError as exc:
                # A bad response, unavailable endpoint, or invalid rendered pack
                # must never install anything.  The user gets a deterministic,
                # explicitly labelled scaffold instead.
                design_error = str(exc)
                blueprint = None

        if blueprint is None:
            blueprint = bp.build_blueprint(session.goal)
            session.design_mode = "scaffold"
            session.designer_model = None
            if design_error is not None:
                session.design_fallback_reason = design_error
            # else: keep any prior design_fallback_reason (dry-run fallback path)

        try:
            blueprint = validate_blueprint(blueprint)
        except Exception as exc:
            session.state = "failed"
            self.store.save(session)
            return self._turn(session, message=f"Could not validate the domain blueprint: {exc}")

        blueprint["domain"] = self._unique_domain(blueprint["domain"])
        agent = blueprint.get("agent")
        if isinstance(agent, dict):
            agent["name"] = blueprint["domain"]
        else:
            blueprint["agent"] = bp.build_agent_spec(blueprint)
        session.blueprint = blueprint
        session.domain = blueprint["domain"]
        session.questions = blueprint.get("questions", [])
        session.state = "interview"
        self.store.save(session)

        turn = self._proposal_turn(session)
        if design_error is not None:
            turn["message"] = (
                "Couldn't shape this interest area with the model "
                f"({design_error}). Using a simple log for now — add detail "
                "later, or try again with a clearer description. "
            ) + turn["message"]
            turn["design_fallback"] = "scaffold"
        return turn

    def suggest_hardening(self, domain: str, *, threshold: int = 3) -> dict[str, Any] | None:
        """Neighbor idea from residue, else repeated corrections / leftover fields."""
        from domain_foundry_core.wizard.cobuild import suggest_neighbor

        neighbor = suggest_neighbor(
            self.ws,
            domain,
            overlay=self._atlas_overlay(),
            threshold=threshold,
        )
        if neighbor:
            return neighbor

        import json as _json

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

            residue_counts: dict[str, int] = {}
            cr_rows = conn.execute(
                """
                SELECT payload_json FROM change_request
                WHERE domain = ?
                ORDER BY created_at DESC
                LIMIT 200
                """,
                (domain,),
            ).fetchall()
            for row in cr_rows:
                try:
                    payload = _json.loads(row["payload_json"] or "{}")
                except Exception:
                    continue
                residue = payload.get("residue") or {}
                if isinstance(residue, dict):
                    inner = residue.get("residue") if "residue" in residue else residue
                    if isinstance(inner, dict):
                        for key in inner:
                            if key and key not in {"unparsed", "notes"}:
                                residue_counts[str(key)] = residue_counts.get(str(key), 0) + 1
            for key, n in sorted(residue_counts.items(), key=lambda kv: -kv[1]):
                if n >= threshold:
                    return {
                        "domain": domain,
                        "reason_code": f"residue:{key}",
                        "count": n,
                        "suggestion": (
                            f"'{key}' showed up as leftover fact {n}× in {domain}. "
                            "Want to add it as a field?"
                        ),
                    }
        except Exception:
            return None
        finally:
            conn.close()
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
        try:
            blueprint = validate_blueprint(session.blueprint)
        except Exception as exc:
            session.state = "failed"
            self.store.save(session)
            return self._turn(session, message=f"Generated blueprint failed validation: {exc}")
        session.blueprint = blueprint

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

        # Held-out acceptance is independent of the generated examples.  A
        # missing suite is an explicit uncovered result, never an implicit pass.
        suite_path = self._heldout_suite_path()
        try:
            suite = load_suite(suite_path) if suite_path.exists() else []
        except Exception as exc:
            suite = []
            session.acceptance = {
                "total": 0,
                "passed": 0,
                "accuracy": 0.0,
                "failures": [],
                "heuristic": None,
                "provider": None,
                "provider_live": False,
                "covered": False,
                "error": f"held-out suite unavailable: {exc}",
            }
        else:
            cases = select_cases(session.goal, suite)
            tiered = self._tiered_provider()
            provider = (
                self._provider_with_cassette(tiered)
                if tiered.has_live_keys()
                else None
            )
            session.acceptance = acceptance_run(draft_dir, cases, llm=provider)

        # Activate: install the validated pack into the live workspace.
        installed = self.harness.packs.add(draft_dir, force=True)
        session.domain = installed.name
        session.pack_version = installed.version
        session.pack_path = str(installed.root)
        session.activated = True
        # Hot-register Expert child config with Supervisor (launchd stubbed).
        # Honesty stays on activate_pack / mesh tests — omit from hobby turns.
        self.harness.register_expert(installed.name)
        _write_status(installed.root, session, live=False)

        # Install anyway — held-out misses become a banner, not a blocking gate.
        # (Plan: repair stays as Inbox/banner after they can already log.)
        session.state = "test_drive"
        self.store.save(session)
        turn = self._activated_turn(session)
        if (
            session.design_mode == "llm"
            and session.acceptance.get("covered")
            and session.acceptance.get("accuracy", 0.0) < ACCEPTANCE_THRESHOLD
        ):
            misses = len(session.acceptance.get("failures") or [])
            turn["message"] = (
                f"{turn['message']} Note: {misses} held-out phrase(s) missed — "
                "you can teach them later; the place is ready to use now."
            )
            turn["needs_repair"] = True
        # Hobby install receipts omit mesh expert stub noise.
        turn["pack"] = {
            "name": session.domain,
            "version": session.pack_version,
            "title": (session.blueprint or {}).get("title"),
            "path": session.pack_path,
        }
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
                "confidence_boost": 0.25,
                "operation": "create",
            })
            added = True
        return added

    # ------------------------------------------------------------ test-drive
    def _handle_test_drive(self, session: WizardSession, text: str) -> dict[str, Any]:
        stripped = text.strip()
        # Legacy clients still send "skip" after create; seamless path already
        # activated, so treat skip as a no-op ready turn.
        if re.fullmatch(r"skip(?:\s+(?:it|questions?|defaults?))?", stripped, re.IGNORECASE):
            turn = self._activated_turn(session)
            turn["pack"] = {
                "name": session.domain,
                "version": session.pack_version,
                "title": (session.blueprint or {}).get("title"),
                "path": session.pack_path,
            }
            return turn

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
        applied_to_domain = receipt.status == "applied" and any(
            span.domain == session.domain and span.disposition not in {"unfiled", "ledger_only"}
            for span in receipt.routed
        )
        if applied_to_domain:
            session.real_captures += 1
            if session.pack_path:
                _write_status(Path(session.pack_path), session, live=_eligible_live(session))
        self.store.save(session)
        turn = self._capture_turn(session, receipt)
        if applied_to_domain and _status_of(session) == "live":
            turn["message"] += " This applied real capture cleared the activation gate; the domain is now live."
        turn["status"] = _status_of(session)
        turn["real_captures"] = session.real_captures
        return turn

    # --------------------------------------------------------------- repair
    def _repair_turn(
        self,
        session: WizardSession,
        *,
        message: str | None = None,
    ) -> dict[str, Any]:
        failures = (session.acceptance or {}).get("failures") or []
        listing = "; ".join(
            f"“{failure['capture']}” → {failure.get('routed_domain', '_unfiled')}"
            for failure in failures[:5]
        )
        object_name = next(iter(session.blueprint.get("objects") or {"entry": {}}))
        if message is None:
            if failures:
                first = failures[0].get("capture", "the missed phrase")
                hint = f'“{first[:40]}…” is a {object_name}'
                message = (
                    f"Honest check: {len(failures)} of {session.acceptance.get('total', 0)} "
                    f"realistic phrases missed ({listing}). Let's repair it — reply with "
                    f'example "{hint}" to teach a phrase, describe a schema change '
                    '("add a grade field"), or say "keep it as a scaffold".'
                )
            else:
                message = (
                    "The held-out check needs more coverage. Teach a phrase, describe a "
                    'schema change, or say "keep it as a scaffold".'
                )
        turn = self._turn(session, message=message, awaiting="repair")
        turn["acceptance"] = session.acceptance
        turn["repair_round"] = min(session.repair_rounds + 1, MAX_REPAIR_ROUNDS)
        turn["repair_rounds"] = session.repair_rounds
        turn["repair_limit"] = MAX_REPAIR_ROUNDS
        turn["dry_run"] = session.dry_run
        turn["pack"] = {
            "name": session.domain,
            "version": session.pack_version,
            "path": session.pack_path,
        }
        return turn

    def _handle_repair(self, session: WizardSession, text: str) -> dict[str, Any]:
        stripped = text.strip()
        low = stripped.lower()
        if _KEEP_SCAFFOLD_RE.search(low) or _DONE_RE.search(stripped):
            session.state = "test_drive"
            if session.pack_path:
                _write_status(Path(session.pack_path), session, live=False)
            self.store.save(session)
            turn = self._turn(
                session,
                message=(
                    f"Kept as a scaffold — {len(session.acceptance.get('failures') or [])} "
                    "held-out phrases still miss. Corrections you make while using it "
                    "keep teaching it."
                ),
                awaiting="capture",
            )
            turn["acceptance"] = session.acceptance
            return turn
        if session.repair_rounds >= MAX_REPAIR_ROUNDS:
            session.state = "test_drive"
            if session.pack_path:
                _write_status(Path(session.pack_path), session, live=False)
            self.store.save(session)
            turn = self._turn(
                session,
                message=(
                    f"{MAX_REPAIR_ROUNDS} repair rounds done — keeping it as an honest "
                    "scaffold. Use it; your corrections continue to improve routing."
                ),
                awaiting="capture",
            )
            turn["acceptance"] = session.acceptance
            return turn

        self.harness.packs.reload()
        pack = self.harness.packs.get(str(session.domain))
        if pack is None:
            return self._repair_turn(session, message="Cannot repair: the domain is not installed.")

        if looks_like_edit(stripped):
            plan = build_plan(stripped, pack)
            if not plan.ok:
                return self._repair_turn(session, message=f"I couldn't apply that repair: {plan.error}")
            result = apply_plan(self.ws, pack, plan, edit_text=stripped)
            self.harness.packs.reload()
            session.pack_version = result.get("version", session.pack_version)
        else:
            failures = (session.acceptance or {}).get("failures") or []
            feedback = [
                {
                    "text": failure.get("capture", ""),
                    "expected_object": failure.get("expected_object")
                    or next(iter(session.blueprint.get("objects") or {"entry": {}})),
                }
                for failure in failures
            ]
            if not self._add_feedback_rules(session.blueprint, feedback):
                return self._repair_turn(
                    session,
                    message=(
                        "I couldn't find a teachable phrase in that feedback. Give me a "
                        'specific held-out phrase or say "keep it as a scaffold".'
                    ),
                )
            try:
                validate_blueprint(session.blueprint)
                bp.write_pack(
                    session.blueprint,
                    Path(session.pack_path or pack.root),
                    version=session.pack_version,
                )
            except Exception as exc:
                return self._repair_turn(session, message=f"I couldn't write that repair safely: {exc}")
            self.harness.packs.reload()

        session.repair_rounds += 1
        session.acceptance = self._acceptance_for_session(session)
        if session.pack_path:
            _write_status(Path(session.pack_path), session, live=False)
        self.store.save(session)

        if session.acceptance.get("accuracy", 0.0) >= ACCEPTANCE_THRESHOLD:
            session.state = "test_drive"
            self.store.save(session)
            turn = self._turn(
                session,
                message=(
                    f"Repaired — held-out is now {session.acceptance['accuracy']:.0%}. "
                    "One real applied capture from you and it can become live. Try it."
                ),
                awaiting="capture",
            )
            turn["acceptance"] = session.acceptance
            return turn

        if session.repair_rounds >= MAX_REPAIR_ROUNDS:
            session.state = "test_drive"
            self.store.save(session)
            turn = self._turn(
                session,
                message=(
                    f"{MAX_REPAIR_ROUNDS} repair rounds done — keeping it as an honest "
                    f"scaffold. {len(session.acceptance.get('failures') or [])} "
                    "held-out phrases still miss."
                ),
                awaiting="capture",
            )
            turn["acceptance"] = session.acceptance
            return turn
        session.state = "repair"
        self.store.save(session)
        return self._repair_turn(session)

    def _acceptance_for_session(self, session: WizardSession) -> dict[str, Any]:
        suite_path = self._heldout_suite_path()
        if not suite_path.exists():
            return acceptance_run(Path(session.pack_path or "."), [], llm=None)
        suite = load_suite(suite_path)
        cases = select_cases(session.goal, suite)
        tiered = self._tiered_provider()
        provider = (
            self._provider_with_cassette(tiered) if tiered.has_live_keys() else None
        )
        return acceptance_run(Path(session.pack_path or "."), cases, llm=provider)

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
        design_label = "LLM-designed" if session.design_mode == "llm" else "scaffold"
        objects = [
            {
                "name": name,
                "title_field": obj["title_field"],
                "fields": list(obj["fields"]),
            }
            for name, obj in b["objects"].items()
        ]
        message = (
            f"Here's a {design_label} proposal for '{b['title']}' ({b['domain']}): "
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
            "design_mode": session.design_mode,
            "designer_model": session.designer_model,
        }
        turn["questions"] = session.questions
        return turn

    def _activated_turn(self, session: WizardSession) -> dict[str, Any]:
        acceptance = session.acceptance or {}
        shortlist = []
        meta = (session.blueprint or {}).get("meta") or {}
        if isinstance(meta.get("shortlist"), list):
            shortlist = [
                str(f.get("name") if isinstance(f, dict) else f).replace("_", " ")
                for f in meta["shortlist"]
            ]
        elif session.blueprint.get("objects"):
            for obj in (session.blueprint.get("objects") or {}).values():
                if isinstance(obj, dict):
                    fields = obj.get("fields")
                    if isinstance(fields, dict):
                        shortlist.extend(k.replace("_", " ") for k in fields)
                    elif isinstance(fields, list):
                        shortlist.extend(str(k).replace("_", " ") for k in fields)
        chips = " · ".join(list(dict.fromkeys(shortlist))[:8])
        title = (session.blueprint or {}).get("title") or session.domain
        if session.design_mode == "scaffold":
            if session.design_fallback_reason:
                message = (
                    f"Couldn't shape {title} with the model, so it's a simple "
                    "log for now. Log one real note and we'll file it."
                )
            else:
                message = (
                    f"{title} is ready as a simple log. "
                    "Add a key in Settings to shape this interest area later. "
                    "Log one real note and we'll file it."
                )
        else:
            message = (
                f"{title} is ready to try"
                + (f" — we'll file {chips}." if chips else ".")
                + " Log one real note and we'll file it."
            )
        if acceptance.get("covered") and acceptance.get("accuracy", 1.0) < 0.9:
            message += (
                f" ({acceptance.get('passed', 0)}/{acceptance.get('total', 0)} "
                "held-out phrases matched — you can teach more later.)"
            )
        turn = self._turn(session, message=message, awaiting="capture")
        turn["pack"] = {
            "name": session.domain,
            "version": session.pack_version,
            "title": title,
            "path": session.pack_path,
        }
        turn["dry_run"] = session.dry_run
        turn["acceptance"] = session.acceptance
        turn["status"] = _status_of(session)
        turn["real_captures"] = session.real_captures
        turn["shortlist"] = shortlist[:8]
        turn["proposal"] = {
            "domain": session.domain,
            "title": title,
            "description": (session.blueprint or {}).get("description"),
            "design_mode": session.design_mode,
            "objects": [
                {
                    "name": name,
                    "fields": list(obj["fields"])
                    if isinstance(obj.get("fields"), (list, dict))
                    else [],
                }
                for name, obj in ((session.blueprint or {}).get("objects") or {}).items()
                if isinstance(obj, dict)
            ],
        }
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
        turn = {
            "session_id": session.session_id,
            "state": session.state,
            "message": message,
            "awaiting": awaiting,
            "done": done or session.state == "done",
            "domain": session.domain,
            "design_mode": session.design_mode,
            "designer_model": session.designer_model,
            "status": _status_of(session),
        }
        if session.design_fallback_reason:
            turn["design_fallback"] = "scaffold"
            turn["design_fallback_reason"] = session.design_fallback_reason
        return turn

    # ------------------------------------------------------------------ util
    def _tiered_provider(self) -> Any:
        return build_tiered_provider(self.ws.home)

    def _provider_with_cassette(self, provider: LLMProvider) -> LLMProvider:
        mode = os.environ.get("DOMAIN_FOUNDRY_CASSETTE")
        if not mode:
            return provider
        return CassetteProvider(provider, self.ws.home / "cassettes", mode=mode)

    def _heldout_suite_path(self) -> Path:
        """Find the committed suite in a checkout or a package-adjacent tree."""

        repo_root = Path(__file__).resolve().parents[3]
        candidates = (
            repo_root / "examples" / "heldout" / _HELDOUT_FILENAME,
            Path(__file__).resolve().parent / "heldout" / _HELDOUT_FILENAME,
            Path.cwd() / "examples" / "heldout" / _HELDOUT_FILENAME,
        )
        return next((candidate for candidate in candidates if candidate.exists()), candidates[0])

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


def _eligible_live(session: WizardSession) -> bool:
    acceptance = session.acceptance or {}
    provider_live = acceptance.get("provider_live")
    if provider_live is None:
        provider_live = acceptance.get("provider") not in {None, "heuristic"}
    return bool(
        session.design_mode == "llm"
        and provider_live
        and acceptance.get("covered")
        and float(acceptance.get("accuracy") or 0.0) >= ACCEPTANCE_THRESHOLD
        and session.real_captures >= 1
    )


def _status_of(session: WizardSession) -> str:
    """Return the status fact used by wizard turns and the sidecar."""

    if _eligible_live(session):
        return "live"
    if session.pack_path:
        path = Path(session.pack_path) / "foundry_status.json"
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
        else:
            if data.get("status") == "live":
                return "live"
    return "scaffold"


def _write_status(pack_root: Path, session: WizardSession, *, live: bool) -> None:
    """Persist the wizard-owned activation fact beside an installed pack."""

    if not pack_root or not pack_root.is_dir():
        return
    acceptance = session.acceptance or {}
    at = now_iso()
    payload = {
        "status": "live" if live and _eligible_live(session) else "scaffold",
        "design_mode": session.design_mode,
        "designer_model": session.designer_model,
        "heldout": {
            "covered": bool(acceptance.get("covered")),
            "passed": int(acceptance.get("passed") or 0),
            "accuracy": float(acceptance.get("accuracy") or 0.0),
            "total": int(acceptance.get("total") or 0),
            "provider": acceptance.get("provider"),
            "provider_live": bool(acceptance.get("provider_live")),
            "at": at,
        },
        "real_captures": session.real_captures,
        "updated_at": at,
        "atlas_cursor": session.atlas_cursor,
        "atlas_ideas": list(session.selected_ideas),
        "jobs": list(session.selected_jobs),
    }
    target = pack_root / "foundry_status.json"
    temporary = pack_root / ".foundry_status.json.tmp"
    temporary.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(target)


def _distinctive_token(text: str) -> str | None:
    words = [w for w in re.findall(r"[a-zA-Z]{4,}", text.lower()) if w not in bp._STOPWORDS]
    if not words:
        return None
    return max(words, key=len)
