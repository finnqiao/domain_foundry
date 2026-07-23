"""HarnessAPI — the adapter contract (plan §4.4)."""

from __future__ import annotations

import json
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
from domain_foundry_core.security.store import connect_ro


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
    ) -> CaptureReceipt:
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
        routed = self.router.route_entry(receipt.entry_id, text, channel=channel)
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
        return {"name": pack.name, "version": pack.version, "path": str(pack.root)}

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
        report = self.projections.drain_until_empty(limit=limit)
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

    # -------------------------------------------------------- app shell (P5)
    def pack_cards(self) -> list[dict[str, Any]]:
        """Installed packs as home cards: icon, title, views, live object counts."""
        self.packs.reload()
        cards: list[dict[str, Any]] = []
        counts = self._object_counts_by_domain()
        for pack in self.packs.list():
            app_cfg = pack.projections.app or {}
            views = self.block_data.views(pack.name)
            cards.append(
                {
                    "name": pack.name,
                    "title": pack.manifest.title,
                    "description": pack.manifest.description,
                    "icon": app_cfg.get("icon") or "📦",
                    "version": pack.version,
                    "objects": list(pack.objects),
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
            app_cfg = pack.projections.app or {}
            out.append(
                {
                    "name": pack.name,
                    "title": pack.manifest.title,
                    "description": pack.manifest.description,
                    "icon": app_cfg.get("icon") or "📦",
                    "version": pack.version,
                    "installed": pack.name in installed,
                }
            )
        return sorted(out, key=lambda c: c["name"])

    def activate_pack(self, name: str) -> dict[str, Any]:
        pack = self.packs.activate_bundled(name)
        return {"name": pack.name, "version": pack.version, "title": pack.manifest.title}

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

    def new_domain(self, goal_text: str, *, test_drive: int = 5) -> dict[str, Any]:
        """Start the guided domain-creation wizard from a plain-language goal."""
        return self.wizard.new_domain(goal_text, test_drive=test_drive)

    def wizard_reply(self, session_id: str, text: str) -> dict[str, Any]:
        """Continue a wizard session (interview answer, capture, or edit)."""
        return self.wizard.wizard_reply(session_id, text)

    def wizard_suggest(self, domain: str) -> dict[str, Any] | None:
        """Suggest a hardening edit when a domain has repeated corrections (§8.4)."""
        return self.wizard.suggest_hardening(domain)

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
