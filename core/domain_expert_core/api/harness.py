"""HarnessAPI — the adapter contract (plan §4.4)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from domain_expert_core.apply.executor import CanonicalChangeExecutor
from domain_expert_core.apply.pipeline import ApplyPipeline, list_approvals
from domain_expert_core.corrections.service import CorrectionService
from domain_expert_core.evals.runner import run_eval
from domain_expert_core.ledger.capture import CaptureService
from domain_expert_core.ledger.migrate import init_workspace
from domain_expert_core.ledger.models import CaptureReceipt, EntryRow, HealthReport, RoutedSpan
from domain_expert_core.packs.loader import load_pack
from domain_expert_core.packs.registry import PackRegistry
from domain_expert_core.paths import Workspace
from domain_expert_core.routing.router import Router


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
        from domain_expert_core.packs.loader import bundled_packs_root

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

    def eval_routing(self, cases_path: Path | None = None) -> dict[str, Any]:
        from domain_expert_core.packs.loader import bundled_packs_root

        path = cases_path or (
            bundled_packs_root().parent / "examples" / "synthetic" / "routing_eval.jsonl"
        )
        # bundled_packs_root is .../packs; parent is repo root
        if not path.exists():
            path = Path(__file__).resolve().parents[3] / "examples" / "synthetic" / "routing_eval.jsonl"
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
        self, status: str = "pending", domain: str | None = None
    ) -> list[dict[str, Any]]:
        return list_approvals(self.workspace, status=status, domain=domain)

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
        # Refresh entry status after resolve
        conn_entry = None
        try:
            from domain_expert_core.security.store import connect_rw

            conn = connect_rw(self.workspace.ledger_db)
            conn_entry = conn.execute(
                "SELECT entry_id FROM change_request WHERE id = ?",
                (receipt.change_request_id,),
            ).fetchone()
            conn.close()
        except Exception:
            conn_entry = None
        if conn_entry and conn_entry["entry_id"]:
            self.pipeline.process_entry(str(conn_entry["entry_id"]))
        return receipt.to_dict()

    def new_domain(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        raise NotImplementedError("new_domain() arrives in P6")

    def wizard_reply(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        raise NotImplementedError("wizard_reply() arrives in P6")
