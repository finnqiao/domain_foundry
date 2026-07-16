"""HarnessAPI — the adapter contract (plan §4.4)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

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
        return CaptureReceipt(
            entry_id=receipt.entry_id,
            capture_event_id=receipt.capture_event_id,
            status=routed.status,  # type: ignore[arg-type]
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
            projection_status="n/a",
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

    # --- stubs for later phases ---------------------------------------------
    def correct(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        raise NotImplementedError("correct() arrives in P3")

    def review_list(self, *args: Any, **kwargs: Any) -> list[dict[str, Any]]:
        raise NotImplementedError("review_list() arrives in P3/P4")

    def review_resolve(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        raise NotImplementedError("review_resolve() arrives in P3")

    def new_domain(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        raise NotImplementedError("new_domain() arrives in P6")

    def wizard_reply(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        raise NotImplementedError("wizard_reply() arrives in P6")
