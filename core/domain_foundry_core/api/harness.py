"""HarnessAPI — the adapter contract (plan §4.4)."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from domain_foundry_core.apply.executor import CanonicalChangeExecutor
from domain_foundry_core.apply.pipeline import ApplyPipeline, list_approvals
from domain_foundry_core.apply.review import (
    resolve_bulk,
    review_diff,
    review_items,
    review_stats,
)
from domain_foundry_core.corrections.service import CorrectionService
from domain_foundry_core.evals.runner import run_eval
from domain_foundry_core.ledger.capture import CaptureService
from domain_foundry_core.ledger.migrate import init_workspace
from domain_foundry_core.ledger.models import CaptureReceipt, EntryRow, HealthReport, RoutedSpan
from domain_foundry_core.packs.loader import load_pack
from domain_foundry_core.packs.registry import PackRegistry
from domain_foundry_core.paths import Workspace
from domain_foundry_core.projections.blockdata import BlockDataError, BlockDataService
from domain_foundry_core.projections.coordinator import (
    ProjectionCoordinator,
    projection_status_for_change_request,
)
from domain_foundry_core.routing.router import Router
from domain_foundry_core.security.store import connect_ro, connect_rw

_APP_ACCENT_RE = re.compile(r"^#[0-9a-fA-F]{3,8}$")


def _constrained_app_config(raw: dict[str, Any]) -> dict[str, str]:
    """Expose only the two pack-level visual tokens the shell supports."""
    icon = raw.get("icon")
    if (
        not isinstance(icon, str)
        or not icon.strip()
        or len(icon) > 8
        or any(char in icon for char in "<>&")
        or any(ord(char) < 32 for char in icon)
    ):
        icon = "📦"
    accent = raw.get("accent")
    if not isinstance(accent, str) or not _APP_ACCENT_RE.fullmatch(accent):
        accent = ""
    return {"icon": icon, "accent": accent}


class HarnessAPI:
    """
    Runtime-facing façade. Adapters translate tool calls into these methods.
    Mutating calls return receipts (PRD reliability requirement).
    """

    def __init__(self, home: Path | None = None) -> None:
        self.workspace = Workspace(home)
        self.captures = CaptureService(self.workspace)
        self.packs = PackRegistry(self.workspace)
        self.router = Router(self.workspace, registry=self.packs)
        self.executor = CanonicalChangeExecutor(self.workspace, registry=self.packs)
        self.pipeline = ApplyPipeline(
            self.workspace, registry=self.packs, executor=self.executor
        )
        self.corrections = CorrectionService(
            self.workspace, registry=self.packs, executor=self.executor
        )
        self.projections = ProjectionCoordinator(self.workspace, registry=self.packs)
        self.block_data = BlockDataService(self.workspace, registry=self.packs)

    def init(self) -> dict[str, int]:
        versions = init_workspace(self.workspace.home)
        # Discover bundled packs and apply schemas when present
        self.packs.reload()
        try:
            self.packs.ensure_schemas_applied()
        except Exception:
            pass
        return versions

    def capture(
        self,
        text: str,
        channel: str = "cli",
        source_ref: str | None = None,
        attachments: list[dict[str, Any]] | None = None,
        actor: str | None = None,
        domain_hint: str | None = None,
    ) -> CaptureReceipt:
        domain_hint = (domain_hint or "").strip() or None
        receipt = self.captures.capture(
            text,
            channel=channel,
            source_ref=source_ref,
            attachments=attachments,
            actor=actor,
        )
        if receipt.idempotent_replay:
            return receipt

        self.packs.reload()
        try:
            self.packs.ensure_schemas_applied()
        except Exception:
            pass

        # Invariant 1: interpretation is staged *after* durable capture insert
        routed = self.router.route_entry(
            receipt.entry_id,
            text,
            channel=channel,
            only_domains=[domain_hint] if domain_hint else None,
        )
        # P3: auto_apply dispositions execute exactly once; review stays queued
        pipe = self.pipeline.process_entry(receipt.entry_id, channel=channel)

        # Refresh routed dispositions/status from DB after apply
        status = pipe.status  # type: ignore[assignment]
        projection = "pending" if pipe.receipts else "n/a"
        if pipe.receipts and all(r.applied or r.replayed for r in pipe.receipts):
            if not pipe.pending_approvals:
                projection = "pending"  # outbox stub until P4 drain

        return CaptureReceipt(
            entry_id=receipt.entry_id,
            capture_event_id=receipt.capture_event_id,
            status=status,  # type: ignore[arg-type]
            routed=[
                RoutedSpan(
                    domain=s.domain,
                    object_type=s.object_type,
                    operation=s.operation,
                    disposition=s.disposition,
                    confidence=s.confidence,
                )
                for s in routed.spans
            ],
            projection_status=projection,  # type: ignore[arg-type]
            idempotent_replay=False,
            summary=receipt.summary,
            llm_error=routed.llm_error,
            domain_hint=domain_hint,
        )

    def query(
        self,
        domain: str | None = None,
        object_type: str | None = None,
        status: str | None = None,
        q: str | None = None,
        limit: int = 50,
    ) -> list[EntryRow]:
        return self.captures.query(
            domain=domain,
            object_type=object_type,
            status=status,
            q=q,
            limit=limit,
        )

    def search(
        self,
        q: str,
        *,
        domain: str | None = None,
        object_type: str | None = None,
        kind: str | None = None,
        limit: int = 50,
    ) -> dict[str, Any]:
        """Full-text search over entry raw text and canonical object text (FTS5)."""
        from domain_foundry_core.search.fts import SearchKind, search_ledger

        kind_arg: SearchKind | None = None
        if kind is not None:
            if kind not in {"entry", "canonical"}:
                raise ValueError("kind must be 'entry' or 'canonical'")
            kind_arg = kind  # type: ignore[assignment]
        result = search_ledger(
            self.workspace.ledger_db,
            q,
            domain=domain,
            object_type=object_type,
            kind=kind_arg,
            limit=limit,
        )
        return result.model_dump()

    def ask(
        self,
        question: str,
        *,
        domain: str | None = None,
        limit: int = 20,
        _llm: Any | None = None,
    ) -> dict[str, Any]:
        """Answer a grounded, read-only question under the daily cost cap."""
        from domain_foundry_core.ask.answerer import compose_answer, extractive_answer
        from domain_foundry_core.ask.executor import execute
        from domain_foundry_core.ask.planner import fallback_plan, plan_ask
        from domain_foundry_core.ask.schema import build_catalog
        from domain_foundry_core.llm.pricing import estimate_cost_usd
        from domain_foundry_core.llm.provider import (
            get_default_provider,
            is_heuristic_provider,
        )
        from domain_foundry_core.routing.cost import CostGuard

        question = question.strip()
        if not question:
            raise ValueError("question is required")
        domain = (domain or "").strip() or None
        bounded_limit = max(1, min(int(limit), 100))

        guard = CostGuard(self.workspace.ledger_db)
        llm = _llm or get_default_provider(
            cassette_dir=self.workspace.home / "cassettes",
            home=self.workspace.home,
        )
        self.packs.reload()
        catalog = build_catalog(self.packs)
        no_model = is_heuristic_provider(llm)
        cap_hit = False
        usages: list[Any] = []
        total_cost = 0.0
        model: str | None = None

        def record_usage(usage: Any, *, default_tier: str) -> None:
            nonlocal total_cost, model
            if usage is None:
                return
            cost = estimate_cost_usd(
                model=usage.model,
                input_tokens=usage.input_tokens,
                output_tokens=usage.output_tokens,
            )
            if cost > 0:
                guard.record(
                    provider=usage.provider or getattr(llm, "name", "llm"),
                    model=usage.model,
                    input_tokens=usage.input_tokens,
                    output_tokens=usage.output_tokens,
                    cost_usd=cost,
                    entry_id=None,
                    tier=usage.tier or default_tier,
                )
            total_cost += cost
            model = usage.model or model
            usages.append(usage)

        routine_allowed = guard.allow_llm(tier="routine")
        use_llm = not no_model and routine_allowed
        cap_hit = not routine_allowed

        if use_llm:
            try:
                plan, usage = plan_ask(
                    question, catalog, llm, tier="routine", domain=domain
                )
                record_usage(usage, default_tier="routine")
            except Exception:
                plan = None
                # A planner repair is the only sota escalation, and it is
                # independently gated so the retry cannot bypass the cap.
                if guard.allow_llm(tier="sota"):
                    try:
                        plan, usage = plan_ask(
                            question, catalog, llm, tier="sota", domain=domain
                        )
                        record_usage(usage, default_tier="sota")
                    except Exception:
                        plan = None
                if plan is None:
                    plan = fallback_plan(question, domain=domain)
        else:
            plan = fallback_plan(question, domain=domain)

        if plan.limit != bounded_limit:
            plan = plan.model_copy(update={"limit": bounded_limit})
        result = execute(plan, self.workspace, self.packs)

        answer = None
        if use_llm and guard.allow_llm(tier="routine"):
            try:
                answer, usage = compose_answer(question, result, llm, tier="routine")
                record_usage(usage, default_tier="routine")
            except Exception:
                # A read-only extractive response is safer than surfacing a
                # provider error after the query has already been executed.
                answer = None
        elif use_llm:
            cap_hit = True
        if answer is None:
            answer = extractive_answer(result)

        return {
            "question": question,
            "answer": answer.text,
            "citations": [citation.model_dump() for citation in answer.citations],
            "mode": answer.mode,
            "plan": plan.model_dump(),
            "model": model,
            "cost_usd": round(total_cost, 6),
            "spend_today_usd": guard.spent_today(),
            "daily_cap_usd": guard.config.daily_usd_cap,
            "cap_hit": cap_hit,
        }

    def health(self) -> HealthReport:
        return self.captures.health()

    def pack_list(self) -> list[dict[str, Any]]:
        self.packs.reload()
        return [
            {
                "name": p.name,
                "version": p.version,
                "title": p.manifest.title,
                "path": str(p.root),
                "objects": list(p.objects),
            }
            for p in self.packs.list()
        ]

    def pack_validate(self, name: str | None = None) -> list[str]:
        self.packs.reload()
        if name:
            pack = self.packs.get(name)
            if not pack:
                return [f"pack not found: {name}"]
            try:
                load_pack(pack.root, validate=True)
                return []
            except Exception as exc:
                return [str(exc)]
        return self.packs.validate()

    def pack_add(self, src: Path, *, force: bool = False) -> dict[str, Any]:
        pack = self.packs.add(Path(src), force=force)
        if pack.agent is not None:
            # Register for mesh honesty; hobby CLI receipts omit the stub.
            self.register_expert(pack.name)
        return {
            "name": pack.name,
            "version": pack.version,
            "title": pack.manifest.title,
            "path": str(pack.root),
        }

    def pack_inspect(self, name_or_source: str | Path) -> dict[str, Any]:
        """Inspect a pack source or installed name without changing the workspace."""
        return self.packs.inspect(name_or_source)

    def pack_preview(self, source: Path) -> dict[str, Any]:
        """Validate a source and expose its declared permissions before install."""
        return self.packs.preview(Path(source))

    def pack_install(self, source: Path, *, force: bool = False) -> dict[str, Any]:
        """Install a pack source through the registry lifecycle contract."""
        return self.packs.install(Path(source), force=force)

    def pack_activate(self, name: str) -> dict[str, Any]:
        """Activate an already-installed pack through the registry lifecycle."""
        pack = self.packs.activate(name)
        summary = {
            "name": pack.name,
            "version": pack.version,
            "title": pack.manifest.title,
            "description": pack.manifest.description,
            "permissions": list(pack.manifest.permissions),
            "objects": sorted(pack.objects),
            "capabilities": sorted(pack.capabilities),
            "path": str(pack.root),
        }
        out: dict[str, Any] = {
            "status": "activated",
            "name": pack.name,
            "version": pack.version,
            "title": pack.manifest.title,
            "pack": summary,
        }
        if pack.agent is not None:
            out["agent"] = pack.agent.model_dump()
            out["expert"] = self.register_expert(pack.name)
        return out

    def pack_upgrade(self, source: Path) -> dict[str, Any]:
        """Upgrade a pack source through the registry snapshot lifecycle."""
        return self.packs.upgrade(Path(source))

    def pack_rollback(self, name: str, backup: Path | None = None) -> dict[str, Any]:
        """Restore the selected pack backup through the registry lifecycle."""
        return self.packs.rollback(name, Path(backup) if backup is not None else None)

    def pack_export(self, name: str, destination: Path) -> dict[str, Any]:
        """Export an installed pack to an explicitly supplied destination."""
        return self.packs.export(name, Path(destination))

    def pack_uninstall(self, name: str) -> dict[str, Any]:
        """Explicitly remove an installed pack through the registry lifecycle."""
        return self.packs.uninstall(name)

    def pack_new(self, name: str) -> dict[str, Any]:
        """Scaffold a new pack from _template into the workspace packs dir."""
        from domain_foundry_core.packs.loader import bundled_packs_root

        template = bundled_packs_root() / "_template"
        dest = self.workspace.packs_dir / name
        if dest.exists():
            raise FileExistsError(f"pack already exists: {dest}")
        import shutil

        shutil.copytree(template, dest)
        # rewrite pack.yaml name/title
        pack_yaml = dest / "pack.yaml"
        text = pack_yaml.read_text(encoding="utf-8")
        text = text.replace("name: example", f"name: {name}", 1)
        text = text.replace('title: "Example Domain"', f'title: "{name}"', 1)
        pack_yaml.write_text(text, encoding="utf-8")
        agent_yaml = dest / "agent.yaml"
        if agent_yaml.exists():
            agent_text = agent_yaml.read_text(encoding="utf-8")
            agent_text = agent_text.replace("name: example", f"name: {name}", 1)
            agent_yaml.write_text(agent_text, encoding="utf-8")
        return {
            "name": name,
            "path": str(dest),
            "note": "run pack validate after editing examples",
        }

    def _default_cases_path(self, cases_path: Path | None) -> Path:
        from domain_foundry_core.packs.loader import bundled_packs_root

        path = cases_path or (
            bundled_packs_root().parent / "examples" / "synthetic" / "routing_eval.jsonl"
        )
        # bundled_packs_root is .../packs; parent is repo root
        if not path.exists():
            path = (
                Path(__file__).resolve().parents[3]
                / "examples"
                / "synthetic"
                / "routing_eval.jsonl"
            )
        return path

    def eval_routing(self, cases_path: Path | None = None) -> dict[str, Any]:
        path = self._default_cases_path(cases_path)
        report = run_eval(path, workspace=self.workspace)
        return {
            "total": report.total,
            "correct": report.correct,
            "accuracy": report.accuracy,
            "by_tag": {k: {"correct": v[0], "total": v[1]} for k, v in report.by_tag().items()},
            "failures": [
                {"id": s.case_id, "detail": s.detail, "actual": s.actual}
                for s in report.scores
                if not s.ok
            ][:20],
        }

    def eval_full(
        self,
        cases_path: Path | None = None,
        *,
        packs: list[str] | None = None,
        live_llm: bool = False,
        use_baseline: bool = True,
        baseline_path: Path | None = None,
    ) -> dict[str, Any]:
        """Full replay: routing/field/disposition/calibration scorecards +
        regression diff vs the committed baseline snapshot (plan §10.2/§10.3)."""
        from domain_foundry_core.evals.baseline import diff_baseline, load_baseline
        from domain_foundry_core.evals.scoring import score_report
        from domain_foundry_core.llm.provider import build_eval_provider

        path = self._default_cases_path(cases_path)
        provider = build_eval_provider(
            self.workspace.home / "cassettes", live_llm=live_llm
        )
        report = run_eval(path, workspace=self.workspace, packs=packs, llm=provider)
        score = score_report(report)
        out: dict[str, Any] = {
            "cases": str(path),
            "accuracy": report.accuracy,
            "scorecard": score.to_dict(),
            "cassette": provider.drift_report(),
            "failures": [
                {"id": s.case_id, "detail": s.detail}
                for s in report.scores
                if not s.ok
            ][:20],
        }
        if not use_baseline:
            out["regression"] = {"has_regression": False, "note": "baseline diff skipped"}
            return out
        baseline = load_baseline(baseline_path)
        if baseline is not None:
            out["regression"] = diff_baseline(score, baseline).to_dict()
        else:
            out["regression"] = {"has_regression": False, "note": "no baseline committed"}
        return out

    def eval_update_baseline(
        self,
        cases_path: Path | None = None,
        *,
        packs: list[str] | None = None,
        baseline_path: Path | None = None,
    ) -> dict[str, Any]:
        from domain_foundry_core.evals.baseline import save_baseline
        from domain_foundry_core.evals.scoring import score_report

        path = self._default_cases_path(cases_path)
        report = run_eval(path, workspace=self.workspace, packs=packs)
        score = score_report(report)
        written = save_baseline(score, baseline_path)
        return {"baseline_path": str(written), "snapshot": score.to_baseline()}

    def eval_backfill(self, *, dry_run: bool = False) -> dict[str, Any]:
        from domain_foundry_core.evals.backfill import backfill_corrections

        return backfill_corrections(self.workspace, dry_run=dry_run).to_dict()

    def eval_export(
        self,
        out_path: Path,
        *,
        sanitize: bool = True,
        source: str | None = "correction",
    ) -> dict[str, Any]:
        from domain_foundry_core.evals.export import export_cases

        return export_cases(
            self.workspace, out_path=out_path, sanitize=sanitize, source=source
        ).to_dict()

    def correct(
        self,
        text: str | None = None,
        entry_id: str | None = None,
        object_uid: str | None = None,
        action: str | None = None,
        fields: dict[str, Any] | None = None,
        merge_into_uid: str | None = None,
        target_domain: str | None = None,
        channel: str = "cli",
    ) -> dict[str, Any]:
        receipt = self.corrections.correct(
            text=text,
            entry_id=entry_id,
            object_uid=object_uid,
            action=action,
            fields=fields,
            merge_into_uid=merge_into_uid,
            target_domain=target_domain,
            channel=channel,
        )
        return receipt.to_dict()

    def refile_entry(self, entry_id: str, domain: str) -> dict[str, Any]:
        """Re-route an entry into a named pack through the normal apply path."""
        from domain_foundry_core.clock import now_iso

        domain = domain.strip()
        self.packs.reload()
        if self.packs.get(domain) is None:
            return {
                "applied": False,
                "entry_id": entry_id,
                "error": f"pack not installed: {domain}",
            }

        conn = connect_rw(self.workspace.ledger_db)
        try:
            row = conn.execute(
                """
                SELECT e.id, e.status, e.domain, c.raw_text, c.channel
                FROM entry e
                JOIN capture_event c ON c.id = e.capture_event_id
                WHERE e.id = ?
                """,
                (entry_id,),
            ).fetchone()
            if row is None:
                return {
                    "applied": False,
                    "entry_id": entry_id,
                    "error": "entry not found",
                }
            if row["status"] == "applied" and row["domain"] == domain:
                return {
                    "applied": True,
                    "entry_id": entry_id,
                    "domain": domain,
                    "status": "applied",
                    "idempotent_replay": True,
                }
            conn.execute(
                "UPDATE interpretation SET status = 'superseded' WHERE entry_id = ?",
                (entry_id,),
            )
            conn.commit()
        finally:
            conn.close()

        routed = self.router.route_entry(
            entry_id,
            str(row["raw_text"] or ""),
            channel="refile",
            only_domains=[domain],
        )
        pipe = self.pipeline.process_entry(entry_id, channel="refile")
        status = pipe.status

        if status in {"unfiled", "ledger_only"}:
            # The explicit destination is authoritative even when the scoped
            # heuristic cannot infer a pack rule. Create through apply_operation
            # so canonical journaling and provenance remain intact.
            pack = self.packs.get(domain)
            assert pack is not None
            object_type = next(iter(pack.objects))
            obj = pack.objects[object_type]
            fields: dict[str, Any] = {}
            title_field = obj.title_field or next(iter(obj.fields), None)
            if title_field:
                fields[title_field] = str(row["raw_text"] or "")[:80]
            if "notes" in obj.fields:
                fields["notes"] = str(row["raw_text"] or "")
            applied = self.apply_operation(
                domain=domain,
                operation="create",
                object_type=object_type,
                fields=fields,
                entry_id=entry_id,
                channel="refile",
                actor="user",
            )
            if not applied.get("ok"):
                return {
                    "applied": False,
                    "entry_id": entry_id,
                    "domain": domain,
                    "error": applied.get("error") or "refile failed",
                }
            status = "applied"

        conn = connect_rw(self.workspace.ledger_db)
        try:
            conn.execute(
                "UPDATE unfiled_card SET status = 'filed', updated_at = ? "
                "WHERE entry_id = ? AND status = 'open'",
                (now_iso(), entry_id),
            )
            conn.execute(
                "UPDATE entry SET status = ?, domain = ?, updated_at = ? WHERE id = ?",
                (status, domain, now_iso(), entry_id),
            )
            conn.commit()
        finally:
            conn.close()

        return {
            "applied": status == "applied",
            "entry_id": entry_id,
            "domain": domain,
            "status": status,
            "routed": [
                {
                    "domain": span.domain,
                    "object_type": span.object_type,
                    "operation": span.operation,
                    "disposition": span.disposition,
                }
                for span in routed.spans
            ],
            "idempotent_replay": False,
        }

    def review_list(
        self,
        status: str = "pending",
        domain: str | None = None,
        *,
        operation: str | None = None,
        object_type: str | None = None,
        overdue_only: bool = False,
        include_diff: bool = False,
    ) -> list[dict[str, Any]]:
        # `include_diff=False` keeps the P3 shape (basic list); pass any of the
        # extra filters or include_diff to get the enriched P4 view.
        if not (operation or object_type or overdue_only or include_diff):
            return list_approvals(self.workspace, status=status, domain=domain)
        return review_items(
            self.workspace,
            status=status,
            domain=domain,
            operation=operation,
            object_type=object_type,
            overdue_only=overdue_only,
            include_diff=include_diff,
        )

    def review_stats(self, domain: str | None = None) -> dict[str, Any]:
        return review_stats(self.workspace, domain=domain)

    def review_diff(self, approval_id: str) -> dict[str, Any]:
        return review_diff(self.workspace, approval_id)

    def review_resolve_bulk(
        self,
        approval_ids: list[str],
        decision: str,
        note: str | None = None,
        resolver: str = "user",
    ) -> dict[str, Any]:
        result = resolve_bulk(
            self.executor,
            approval_ids,
            decision=decision,
            note=note,
            resolver=resolver,
        )
        for item in result["results"]:
            self._refresh_entry_after_resolve(item.get("change_request_id"))
        return result

    def review_resolve(
        self,
        approval_id: str,
        decision: str,
        note: str | None = None,
        resolver: str = "user",
    ) -> dict[str, Any]:
        receipt = self.executor.resolve_approval(
            approval_id, decision=decision, note=note, resolver=resolver
        )
        self._refresh_entry_after_resolve(receipt.change_request_id)
        return receipt.to_dict()

    def _refresh_entry_after_resolve(self, change_request_id: int | None) -> None:
        if not change_request_id:
            return
        from domain_foundry_core.security.store import connect_rw

        try:
            conn = connect_rw(self.workspace.ledger_db)
            row = conn.execute(
                "SELECT entry_id FROM change_request WHERE id = ?",
                (change_request_id,),
            ).fetchone()
            conn.close()
        except Exception:
            row = None
        if row and row["entry_id"]:
            self.pipeline.process_entry(str(row["entry_id"]))

    # ------------------------------------------------------------- projections
    def drain_projections(
        self, *, adapters: list[str] | None = None, limit: int = 100
    ) -> dict[str, Any]:
        report = self.projections.drain_until_empty(adapters=adapters, limit=limit)
        return report.to_dict()

    def reproject_vault(
        self,
        vault: Path | str,
        *,
        apply: bool = False,
        domains: list[str] | None = None,
        folder_map: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Dry-run (default) or apply managed-region vault re-projection."""
        from domain_foundry_core.projections.reproject import VaultReprojector

        report = VaultReprojector(
            self.workspace,
            vault=Path(vault),
            registry=self.packs,
            folder_map=folder_map,
            domains=domains,
        ).run(apply=apply)
        out = report.to_dict()
        out["_markdown"] = report.to_markdown()
        return out

    def projection_status(
        self,
        *,
        entry_id: str | None = None,
        change_request_id: int | None = None,
    ) -> dict[str, Any]:
        """Report projection convergence for an entry or change request."""
        conn = connect_ro(self.workspace.ledger_db)
        try:
            cr_ids: list[int] = []
            if change_request_id is not None:
                cr_ids = [int(change_request_id)]
            elif entry_id is not None:
                cr_ids = [
                    int(r["id"])
                    for r in conn.execute(
                        "SELECT id FROM change_request WHERE entry_id = ?",
                        (entry_id,),
                    ).fetchall()
                ]
            statuses = [
                projection_status_for_change_request(conn, cr) for cr in cr_ids
            ]
        finally:
            conn.close()
        if not statuses:
            return {"projection_status": "n/a", "change_requests": []}
        if any(s == "pending" for s in statuses):
            overall = "pending"
        elif all(s == "refreshed" for s in statuses):
            overall = "refreshed"
        else:
            overall = "n/a"
        return {
            "projection_status": overall,
            "change_requests": list(zip(cr_ids, statuses, strict=False)),
        }

    def block_views(self, domain: str) -> list[dict[str, Any]]:
        return self.block_data.views(domain)

    def block_view_data(
        self, domain: str, view_id: str, limit: int = 100
    ) -> dict[str, Any]:
        try:
            return self.block_data.view_data(domain, view_id, limit=limit)
        except BlockDataError as exc:
            return {"error": str(exc)}

    def export_data(self, *, domain: str | None = None) -> dict[str, Any]:
        """Return a secrets-free JSON export of live canonical objects."""
        from domain_foundry_core.clock import now_iso
        from domain_foundry_core.security.redact import redact_secrets
        from domain_foundry_core.security.store import connect_ro

        def redact_value(value: Any) -> Any:
            if isinstance(value, str):
                return redact_secrets(value)
            if isinstance(value, dict):
                return {key: redact_value(item) for key, item in value.items()}
            if isinstance(value, list):
                return [redact_value(item) for item in value]
            return value

        # Map entry_id → (raw_text, residue) from ledger for never-drop export.
        residue_by_entry: dict[str, dict[str, Any]] = {}
        raw_by_entry: dict[str, str] = {}
        ledger = connect_ro(self.workspace.ledger_db)
        try:
            for row in ledger.execute(
                """
                SELECT e.id AS entry_id, c.raw_text,
                       (
                         SELECT cr.payload_json FROM change_request cr
                         WHERE cr.entry_id = e.id
                         ORDER BY cr.id DESC LIMIT 1
                       ) AS payload_json
                FROM entry e
                JOIN capture_event c ON c.id = e.capture_event_id
                """
            ).fetchall():
                eid = str(row["entry_id"])
                raw_by_entry[eid] = str(row["raw_text"] or "")
                payload = {}
                if row["payload_json"]:
                    try:
                        payload = json.loads(row["payload_json"])
                    except Exception:
                        payload = {}
                residue_by_entry[eid] = payload.get("residue") or {}
        finally:
            ledger.close()

        self.packs.reload()
        names = [domain] if domain else [pack.name for pack in self.packs.list()]
        domains: dict[str, Any] = {}
        counts: dict[str, dict[str, int]] = {}
        for name in names:
            pack = self.packs.get(name)
            if pack is None:
                raise ValueError(f"pack not installed: {name}")
            objects: dict[str, list[dict[str, Any]]] = {}
            counts[name] = {}
            for object_type, object_spec in pack.objects.items():
                rows = self.block_data.export_rows(name, object_type)
                exported: list[dict[str, Any]] = []
                field_names = set(object_spec.fields)
                for row in rows:
                    fields = {
                        key: redact_value(row[key])
                        for key in field_names
                        if key in row
                    }
                    entry_id = row.get("entry_id")
                    item: dict[str, Any] = {
                        "object_uid": row.get("object_uid"),
                        "entry_id": entry_id,
                        "created_at": row.get("created_at"),
                        "updated_at": row.get("updated_at"),
                        "fields": fields,
                    }
                    if entry_id:
                        eid = str(entry_id)
                        if eid in raw_by_entry and raw_by_entry[eid]:
                            item["raw_text"] = redact_value(raw_by_entry[eid])
                        res = residue_by_entry.get(eid) or {}
                        if res:
                            item["residue"] = redact_value(res)
                    exported.append(item)
                objects[object_type] = exported
                counts[name][object_type] = len(exported)
            domains[name] = {
                "pack_version": pack.version,
                "objects": objects,
            }
        return {
            "format": "domain-foundry-export/1",
            "exported_at": now_iso(),
            "domains": domains,
            "counts": counts,
        }

    # -------------------------------------------------------- app shell (P5)
    def pack_cards(self) -> list[dict[str, Any]]:
        """Installed packs as home cards: icon, title, views, live object counts."""
        self.packs.reload()
        cards: list[dict[str, Any]] = []
        counts = self._object_counts_by_domain()
        for pack in self.packs.list():
            app_cfg = _constrained_app_config(pack.projections.app or {})
            views = self.block_data.views(pack.name)
            cards.append(
                {
                    "name": pack.name,
                    "title": pack.manifest.title,
                    "description": pack.manifest.description,
                    "icon": app_cfg.get("icon") or "📦",
                    "accent": app_cfg.get("accent") or None,
                    "version": pack.version,
                    "objects": list(pack.objects),
                    "capabilities": pack.capabilities,
                    "compatibility": pack.compatibility.model_dump(),
                    "views": [
                        {"id": v.get("id"), "title": v.get("title"), "block": v.get("block")}
                        for v in views
                    ],
                    "object_count": sum(
                        counts.get((pack.name, ot), 0) for ot in pack.objects
                    ),
                }
            )
        return cards

    def pack_catalog(self) -> list[dict[str, Any]]:
        """Bundled packs available to install (for the home 'add domain' picker)."""
        from domain_foundry_core.packs.loader import load_pack

        self.packs.reload()
        installed = {p.name for p in self.packs.list()}
        out: list[dict[str, Any]] = []
        for path in self.packs.bundled_catalog():
            try:
                pack = load_pack(path, validate=False)
            except Exception:
                continue
            if pack.name.startswith("_"):
                continue
            app_cfg = _constrained_app_config(pack.projections.app or {})
            out.append(
                {
                    "name": pack.name,
                    "title": pack.manifest.title,
                    "description": pack.manifest.description,
                    "icon": app_cfg.get("icon") or "📦",
                    "accent": app_cfg.get("accent") or None,
                    "version": pack.version,
                    "installed": pack.name in installed,
                }
            )
        return sorted(out, key=lambda c: c["name"])

    def activate_pack(self, name: str) -> dict[str, Any]:
        if self.packs.get_by_alias(name) is not None:
            return self.pack_activate(name)
        pack = self.packs.activate_bundled(name)
        out: dict[str, Any] = {
            "name": pack.name,
            "version": pack.version,
            "title": pack.manifest.title,
        }
        if pack.agent is not None:
            out["agent"] = pack.agent.model_dump()
            out["expert"] = self.register_expert(pack.name)
        return out

    def register_expert(self, domain: str, *, spawn: bool = False) -> dict[str, Any]:
        """Hot-register a domain Expert with the Supervisor (launchd stubbed)."""
        from domain_foundry_core.mesh.supervisor import Supervisor

        pack = self.packs.get(domain)
        if pack is None:
            return {
                "domain": domain,
                "registered": False,
                "error": f"pack not installed: {domain}",
                "launchd": "stubbed",
            }
        if pack.agent is None:
            return {
                "domain": domain,
                "registered": False,
                "error": f"no agent.yaml for {domain}",
                "launchd": "stubbed",
            }
        return Supervisor(self.workspace).register(domain, spawn=spawn)

    def _object_counts_by_domain(self) -> dict[tuple[str, str], int]:
        counts: dict[tuple[str, str], int] = {}
        conn = connect_ro(self.workspace.ledger_db)
        try:
            rows = conn.execute(
                """
                SELECT domain, object_type, COUNT(*) AS n
                FROM canonical_object
                WHERE status = 'active'
                GROUP BY domain, object_type
                """
            ).fetchall()
            for r in rows:
                counts[(str(r["domain"]), str(r["object_type"]))] = int(r["n"])
        finally:
            conn.close()
        return counts

    def object_detail(
        self, domain: str, object_type: str, object_uid: str
    ) -> dict[str, Any]:
        """Detail view payload: fields + revision history + provenance chain + links.

        Provenance chain (plan §5, §9.4): capture text → interpretation
        (confidence) → revisions. Read-only; the app is a client with no
        privileged write path.
        """
        from domain_foundry_core.apply.engine import load_domain_row

        row = load_domain_row(
            self.workspace.domains_db, domain, object_type, object_uid
        )
        if row is None:
            return {"error": f"object not found: {object_uid}"}
        fields = {
            k: v
            for k, v in row.items()
            if k not in {"id", "object_uid", "entry_id", "tombstoned"}
        }
        conn = connect_ro(self.workspace.ledger_db)
        try:
            co = conn.execute(
                "SELECT uid, domain, object_type, status, natural_key, "
                "created_at, updated_at FROM canonical_object WHERE uid = ?",
                (object_uid,),
            ).fetchone()
            revisions = [
                {
                    "revision": r["revision"],
                    "changed_fields": json.loads(r["changed_fields_json"] or "{}"),
                    "actor": r["actor"],
                    "actor_channel": r["actor_channel"],
                    "created_at": r["created_at"],
                }
                for r in conn.execute(
                    "SELECT revision, changed_fields_json, actor, actor_channel, "
                    "created_at FROM object_revision WHERE object_uid = ? "
                    "ORDER BY revision ASC",
                    (object_uid,),
                ).fetchall()
            ]
            entry_id = row.get("entry_id")
            capture: dict[str, Any] | None = None
            interpretations: list[dict[str, Any]] = []
            if entry_id:
                cap = conn.execute(
                    """
                    SELECT c.raw_text, c.channel, c.captured_at, e.status,
                           e.routing_confidence, e.domain, e.object_type
                    FROM entry e
                    JOIN capture_event c ON c.id = e.capture_event_id
                    WHERE e.id = ?
                    """,
                    (entry_id,),
                ).fetchone()
                if cap:
                    capture = {
                        "entry_id": entry_id,
                        "raw_text": cap["raw_text"],
                        "channel": cap["channel"],
                        "captured_at": cap["captured_at"],
                        "status": cap["status"],
                        "routing_confidence": cap["routing_confidence"],
                    }
                interpretations = [
                    {
                        "version": i["version"],
                        "interpreter": i["interpreter"],
                        "confidence": i["confidence"],
                        "status": i["status"],
                        "payload": json.loads(i["payload_json"] or "{}"),
                        "created_at": i["created_at"],
                    }
                    for i in conn.execute(
                        "SELECT version, interpreter, confidence, status, "
                        "payload_json, created_at FROM interpretation "
                        "WHERE entry_id = ? ORDER BY version ASC",
                        (entry_id,),
                    ).fetchall()
                ]
            links = [
                {
                    "relation": ln["relationship"],
                    "to_uid": ln["target_id"],
                    "confidence": ln["confidence"],
                }
                for ln in conn.execute(
                    """
                    SELECT relationship, target_id, confidence
                    FROM source_link
                    WHERE source_type = 'canonical_object' AND source_id = ?
                      AND target_type = 'canonical_object'
                    """,
                    (object_uid,),
                ).fetchall()
            ]
        finally:
            conn.close()
        return {
            "object_uid": object_uid,
            "domain": domain,
            "object_type": object_type,
            "status": co["status"] if co else "active",
            "created_at": co["created_at"] if co else None,
            "updated_at": co["updated_at"] if co else None,
            "fields": fields,
            "revisions": revisions,
            "capture": capture,
            "interpretations": interpretations,
            "links": links,
        }

    def health_panel(self) -> dict[str, Any]:
        """Health report enriched for the app panel: + LLM spend today."""
        from domain_foundry_core.routing.cost import CostGuard

        report = self.health().model_dump()
        guard = CostGuard(self.workspace.ledger_db)
        report["llm_spend"] = {
            "today_usd": guard.spent_today(),
            "daily_cap_usd": guard.config.daily_usd_cap,
        }
        return report

    # -------------------------------------------------------- wizard (P6, §6)
    @property
    def wizard(self):  # type: ignore[no-untyped-def]
        wiz = getattr(self, "_wizard", None)
        if wiz is None:
            from domain_foundry_core.wizard.engine import WizardEngine

            wiz = WizardEngine(self)
            self._wizard = wiz
        return wiz

    def new_domain(
        self,
        goal_text: str,
        *,
        test_drive: int = 5,
        release_mode: bool = False,
    ) -> dict[str, Any]:
        """Start the guided domain-creation wizard from a plain-language goal."""
        return self.wizard.new_domain(
            goal_text,
            test_drive=test_drive,
            release_mode=release_mode,
        )

    def create_domain(self, goal_text: str, *, test_drive: int = 5) -> dict[str, Any]:
        """Start the release creation journey."""
        return self.new_domain(goal_text, test_drive=test_drive, release_mode=True)

    def create_resume(self, session_id: str) -> dict[str, Any]:
        """Resume a release creation journey without changing its state."""
        return self.wizard.resume(session_id)

    def create_cancel(self, session_id: str) -> dict[str, Any]:
        """Cancel future creation work while keeping the saved session."""
        return self.wizard.cancel(session_id)

    def wizard_reply(self, session_id: str, text: str) -> dict[str, Any]:
        """Continue a wizard session (interview answer, capture, or edit)."""
        return self.wizard.wizard_reply(session_id, text)

    def wizard_suggest(self, domain: str) -> dict[str, Any] | None:
        """Suggest a neighbor idea or hardening edit for a live domain."""
        return self.wizard.suggest_hardening(domain)

    def atlas_search(self, goal: str, cursor_id: str | None = None) -> dict[str, Any]:
        """Return an idea-atlas neighborhood for a goal (no install)."""
        overlay = self.workspace.home / "atlas"
        from domain_foundry_core.atlas.query import query_neighborhood

        return query_neighborhood(
            goal,
            overlay=overlay if overlay.is_dir() else None,
            cursor_id=cursor_id,
        )

    def inspect_pack(self, name: str) -> dict[str, Any]:
        """Return pack YAML (and atlas hint) for an installed or bundled pack."""
        self.packs.reload()
        pack = self.packs.get(name)
        if pack is None:
            from domain_foundry_core.packs.loader import bundled_packs_root, load_pack

            bundled = bundled_packs_root() / name
            if not (bundled / "pack.yaml").is_file():
                raise ValueError(f"pack not found: {name}")
            pack = load_pack(bundled, validate=False)
        files: dict[str, str] = {}
        for fname in (
            "pack.yaml",
            "schema.yaml",
            "routing.yaml",
            "operations.yaml",
            "policy.yaml",
            "projections.yaml",
            "capabilities.yaml",
            "agent.yaml",
        ):
            path = pack.root / fname
            if path.is_file():
                files[fname] = path.read_text(encoding="utf-8")
        status = None
        status_path = pack.root / "foundry_status.json"
        if status_path.is_file():
            import json as _json

            try:
                status = _json.loads(status_path.read_text(encoding="utf-8"))
            except Exception:
                status = None
        return {
            "name": pack.name,
            "title": pack.manifest.title,
            "objects": list(pack.objects),
            "files": files,
            "status": status,
        }

    def apply_pack_edit(self, domain: str, edit_text: str, *, confirm: bool = False) -> dict[str, Any]:
        """Preview a pack edit, or apply it when ``confirm`` is true."""
        if not confirm:
            preview = self.hardening_preview(domain, edit_text)
            preview["confirm"] = False
            return preview
        return self.hardening_apply(domain, edit_text)

    def atlas_validate(self) -> dict[str, Any]:
        from domain_foundry_core.atlas.loader import graph_stats, load_atlas, validate_atlas

        overlay = self.workspace.home / "atlas"
        graph = load_atlas(overlay if overlay.is_dir() else None)
        return {"errors": validate_atlas(graph), "stats": graph_stats(graph)}

    def hardening_preview(self, domain: str, edit_text: str) -> dict[str, Any]:
        from domain_foundry_core.wizard.hardening import build_plan

        self.packs.reload()
        pack = self.packs.get(domain)
        if pack is None:
            raise ValueError(f"pack not installed: {domain}")
        plan = build_plan(edit_text, pack)
        if not plan.ok:
            raise ValueError(plan.error or "could not build a hardening plan")
        return {"domain": domain, "edit_text": edit_text, "plan": plan.to_dict()}

    def hardening_apply(self, domain: str, edit_text: str) -> dict[str, Any]:
        from domain_foundry_core.wizard.hardening import apply_plan, build_plan

        self.packs.reload()
        pack = self.packs.get(domain)
        if pack is None:
            raise ValueError(f"pack not installed: {domain}")
        plan = build_plan(edit_text, pack)
        if not plan.ok:
            raise ValueError(plan.error or "could not build a hardening plan")
        result = apply_plan(self.workspace, pack, plan, edit_text=edit_text)
        self.packs.reload()
        return result

    def hardening_rollback(self, domain: str) -> dict[str, Any]:
        from domain_foundry_core.wizard.hardening_safety import restore_latest_snapshot

        result = restore_latest_snapshot(self.workspace, domain, registry=self.packs)
        self.packs.reload()
        self.packs.ensure_schemas_applied()
        return result

    # -------------------------------------------------------- quiz / SRS (mesh P2)
    def apply_operation(
        self,
        *,
        domain: str,
        operation: str,
        object_type: str,
        fields: dict[str, Any] | None = None,
        object_uid: str | None = None,
        entry_id: str | None = None,
        channel: str = "cli",
        actor: str = "system",
    ) -> dict[str, Any]:
        """Direct apply-path write (quiz grades, programmatic updates)."""
        from domain_foundry_core.apply.engine import OperationSpec

        self.packs.reload()
        try:
            self.packs.ensure_schemas_applied()
        except Exception:
            pass
        result = self.executor.engine.apply_spec(
            OperationSpec(
                domain=domain,
                operation=operation,
                object_type=object_type,
                object_uid=object_uid,
                payload=dict(fields or {}),
                entry_id=entry_id,
                channel=channel,
            ),
            actor=actor,
            actor_channel=channel,
        )
        return {
            "ok": result.ok,
            "object_uid": result.object_uid,
            "row_id": result.row_id,
            "revision": result.revision,
            "created": result.created,
            "operation": result.operation,
            "error": result.error,
            "details": result.details,
        }

    def apply_ui_action(
        self,
        *,
        domain: str,
        operation: str,
        object_type: str,
        fields: dict[str, Any] | None = None,
        object_uid: str | None = None,
        entry_id: str | None = None,
    ) -> dict[str, Any]:
        """Apply only an exact field combination declared UI-safe by the pack."""
        self.packs.reload()
        pack = self.packs.get(domain)
        if pack is None:
            raise ValueError(f"pack not installed: {domain}")
        if not pack.policy.allows_ui_action(
            object_type=object_type, operation=operation, fields=fields
        ):
            raise PermissionError("That action is not available from the app.")
        return self.apply_operation(
            domain=domain,
            operation=operation,
            object_type=object_type,
            fields=fields,
            object_uid=object_uid,
            entry_id=entry_id,
            channel="web",
            actor="web-ui",
        )

    def quiz_start(
        self,
        *,
        user_id: str = "default",
        limit: int | None = None,
        include_grammar: bool = True,
        filter_text: str | None = None,
        new_card_limit: int | None = None,
    ) -> dict[str, Any]:
        from domain_foundry_core.mesh.quiz import QuizSession

        self.packs.reload()
        try:
            self.packs.ensure_schemas_applied()
        except Exception:
            pass
        quiz = QuizSession(self.workspace, registry=self.packs)
        session = quiz.start(
            user_id=user_id,
            limit=limit,
            include_grammar=include_grammar,
            filter_text=filter_text,
            new_card_limit=new_card_limit,
        )
        card = quiz.current_card(session)
        return {
            "session_id": session.id,
            "status": session.status,
            "total": len(session.state.get("cards") or []),
            "index": int(session.state.get("index") or 0),
            "prompt": card.prompt if card else None,
            "card_uid": card.object_uid if card else None,
            "object_type": card.object_type if card else None,
            "new_card_limit": int(session.state.get("new_card_limit") or 0),
            "due_count": int(session.state.get("due_count") or 0),
            "new_count": int(session.state.get("new_count") or 0),
        }

    def quiz_grade(
        self,
        grade: str,
        *,
        session_id: str | None = None,
        user_id: str = "default",
    ) -> dict[str, Any]:
        from domain_foundry_core.mesh.quiz import QuizSession

        self.packs.reload()
        try:
            self.packs.ensure_schemas_applied()
        except Exception:
            pass
        quiz = QuizSession(self.workspace, registry=self.packs)
        receipt = quiz.grade(grade, session_id=session_id, user_id=user_id)
        card = receipt.next_card
        return {
            "session_id": receipt.session_id,
            "grade": receipt.grade,
            "review_event_uid": receipt.review_event_uid,
            "card_uid": receipt.card_uid,
            "card_updated": receipt.card_updated,
            "done": receipt.done,
            "correct": receipt.correct,
            "index": receipt.index,
            "total": receipt.total,
            "prompt": card.prompt if card else None,
            "next_card_uid": card.object_uid if card else None,
            "details": receipt.details,
        }

    def quiz_next(self, *, user_id: str = "default") -> dict[str, Any]:
        """Return the current card for an active quiz (resume hook)."""
        from domain_foundry_core.mesh.quiz import QuizSession

        quiz = QuizSession(self.workspace, registry=self.packs)
        card = quiz.current_card(user_id=user_id)
        active = quiz.sessions.get_active(
            "japanese", user_id=user_id, session_type=QuizSession.SESSION_TYPE
        )
        if active is None:
            return {"active": False, "prompt": None}
        return {
            "active": True,
            "session_id": active.id,
            "index": int(active.state.get("index") or 0),
            "total": len(active.state.get("cards") or []),
            "prompt": card.prompt if card else None,
            "card_uid": card.object_uid if card else None,
            "done": card is None,
        }

    def quiz_stats(self, *, domain: str = "japanese") -> dict[str, Any]:
        """Read-only review_event aggregates + due/new counts (SPA stats stub)."""
        from domain_foundry_core.mesh.quiz import quiz_stats as _quiz_stats

        self.packs.reload()
        try:
            self.packs.ensure_schemas_applied()
        except Exception:
            pass
        return _quiz_stats(self.workspace, domain=domain)

    def quiz_activity(
        self, *, domain: str = "japanese", user_id: str = "default", limit: int = 20
    ) -> dict[str, Any]:
        """Recent session lifecycle rows for a pack-declared session surface."""
        from dataclasses import asdict

        from domain_foundry_core.mesh.sessions import DomainSessionStore

        sessions = DomainSessionStore(self.workspace).list(
            domain, user_id=user_id, session_type="quiz", limit=limit
        )
        return {
            "domain": domain,
            "sessions": [asdict(session) for session in sessions],
        }

    def schedule_status(self, *, domain: str = "japanese") -> dict[str, Any]:
        """Visible declaration + durable control state; no live calendar claim."""
        from domain_foundry_core.mesh.schedules import ScheduleRunStore

        self.packs.reload()
        pack = self.packs.get(domain)
        if pack is None or pack.agent is None:
            return {"domain": domain, "schedules": []}
        store = ScheduleRunStore(self.workspace)
        schedules: list[dict[str, Any]] = []
        for spec in pack.agent.schedules:
            run = store.get(domain, spec.id)
            schedules.append(
                {
                    "id": spec.id,
                    "cron": spec.cron,
                    "message": spec.message,
                    "status": store.status(domain, spec.id),
                    "last_fired_at": run.last_fired_at if run else None,
                    "next_due_at": run.next_due_at if run else None,
                    "fire_count": run.fire_count if run else 0,
                    "timezone": (pack.capabilities.get("schedules") or {}).get("timezone"),
                    "missed_run_policy": (pack.capabilities.get("schedules") or {}).get(
                        "missed_run_policy"
                    ),
                    "human_gate": True,
                }
            )
        return {"domain": domain, "schedules": schedules}

    def set_schedule_status(self, domain: str, schedule_id: str, status: str) -> dict[str, Any]:
        from domain_foundry_core.mesh.schedules import ScheduleRunStore

        self.packs.reload()
        pack = self.packs.get(domain)
        if pack is None or pack.agent is None:
            raise ValueError(f"no scheduled pack installed for {domain!r}")
        if not any(spec.id == schedule_id for spec in pack.agent.schedules):
            raise ValueError(f"unknown schedule {schedule_id!r} for {domain!r}")
        next_status = ScheduleRunStore(self.workspace).set_status(domain, schedule_id, status)
        return {"domain": domain, "schedule_id": schedule_id, "status": next_status}

    def evaluate_schedules(
        self,
        *,
        domain: str | None = "japanese",
        fire: bool = True,
        user_id: str = "default",
        channel: str = "telegram",
    ) -> list[dict[str, Any]]:
        """Evaluate pack cron schedules (daily 09:00); idempotent via schedule_run."""
        from domain_foundry_core.mesh.schedules import ScheduleEvaluator

        self.packs.reload()
        try:
            self.packs.ensure_schemas_applied()
        except Exception:
            pass
        evaluator = ScheduleEvaluator(self.workspace, registry=self.packs)
        if domain:
            results = evaluator.evaluate_domain(
                domain, fire=fire, user_id=user_id, channel=channel
            )
        else:
            results = evaluator.evaluate_all(fire=fire)
        return [
            {
                "domain": r.domain,
                "schedule_id": r.schedule_id,
                "fired": r.fired,
                "skipped_reason": r.skipped_reason,
                "window_id": r.window_id,
                "next_due_at": r.next_due_at,
                "result": r.result,
            }
            for r in results
        ]

    # -------------------------------------------------------- mesh observability (P8)
    def mesh_status(self) -> dict[str, Any]:
        """Read-only mesh health: per-domain depths, last processed, error rate, DLQ."""
        from dataclasses import asdict

        from domain_foundry_core.mesh.supervisor import Supervisor

        return asdict(Supervisor(self.workspace).status())

    def mesh_dlq_list(
        self,
        *,
        domain: str | None = None,
        queue: str | None = None,
        limit: int = 100,
        include_failed: bool = True,
    ) -> dict[str, Any]:
        """Read-only dead-letter listing for the mesh dashboard stub."""
        from domain_foundry_core.mesh.observability import DeadLetterQueue

        if queue is not None and queue not in {"inbox", "outbound"}:
            return {"error": "queue must be inbox or outbound", "entries": []}
        entries = DeadLetterQueue(self.workspace).list(
            domain=domain,
            queue=queue,  # type: ignore[arg-type]
            limit=limit,
            include_failed=include_failed,
        )
        return {"entries": [e.to_dict() for e in entries]}

    def mesh_dlq_retry(self, msg_id: str) -> dict[str, Any]:
        """Requeue a DLQ row (CLI / operator path; not exposed as HTTP write)."""
        from domain_foundry_core.mesh.observability import DeadLetterQueue

        entry = DeadLetterQueue(self.workspace).retry(msg_id)
        if entry is None:
            return {"error": "not found or not retryable", "id": msg_id}
        return entry.to_dict()

    def mesh_check_depth_alerts(
        self,
        *,
        flags: Any | None = None,
        channel: str | None = None,
        destination: str | None = None,
    ) -> list[dict[str, Any]]:
        """Evaluate queue-depth threshold and enqueue Concierge outbound alerts."""
        from domain_foundry_core.mesh.flags import MeshObservabilityFlags
        from domain_foundry_core.mesh.observability import MeshObservability

        obs_flags = flags if flags is not None else MeshObservabilityFlags.from_env()
        msgs = MeshObservability(self.workspace, flags=obs_flags).maybe_enqueue_depth_alert(
            channel=channel, destination=destination
        )
        return [
            {
                "id": m.id,
                "origin_domain": m.origin_domain,
                "text": m.text,
                "status": m.status,
                "channel": m.channel,
                "destination": m.destination,
            }
            for m in msgs
        ]
