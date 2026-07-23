"""Vault re-projection — dry-run diff then managed-region-only apply.

Projects every pack object type into a target Obsidian vault using the
MarkdownAdapter managed-note contract. Unmanaged free-zone bytes must remain
identical (invariant). Default mode is dry-run; writes require ``apply=True``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from domain_foundry_core.packs.registry import PackRegistry
from domain_foundry_core.paths import Workspace
from domain_foundry_core.projections.markdown import (
    MarkdownAdapter,
    preview_managed_write,
)
from domain_foundry_core.security.paths import safe_join

# Hermes Obsidian numbered-folder layout (same vault, same top-level folders).
HERMES_FOLDER_MAP: dict[str, str] = {
    "japanese": "06_Japanese",
    "food": "05_Food_Drink",
    "health": "07_Health",
    "dev": "12_Dev",
    "travel": "04_Travel",
}


@dataclass
class NoteDiff:
    rel_path: str
    object_uid: str
    entry_id: str
    would_create: bool
    content_changed: bool
    unmanaged_unchanged: bool
    action: str  # create | update | noop | blocked

    def to_dict(self) -> dict[str, Any]:
        return {
            "rel_path": self.rel_path,
            "object_uid": self.object_uid,
            "entry_id": self.entry_id,
            "would_create": self.would_create,
            "content_changed": self.content_changed,
            "unmanaged_unchanged": self.unmanaged_unchanged,
            "action": self.action,
        }


@dataclass
class ReprojectReport:
    vault: str
    dry_run: bool
    applied: bool
    notes: list[NoteDiff] = field(default_factory=list)
    domains: list[str] = field(default_factory=list)
    object_keys: list[str] = field(default_factory=list)

    @property
    def create_count(self) -> int:
        return sum(1 for n in self.notes if n.action == "create" or (n.would_create and n.content_changed))

    @property
    def update_count(self) -> int:
        return sum(1 for n in self.notes if n.action == "update")

    @property
    def noop_count(self) -> int:
        return sum(1 for n in self.notes if n.action == "noop")

    @property
    def blocked_count(self) -> int:
        return sum(1 for n in self.notes if n.action == "blocked")

    @property
    def unmanaged_ok(self) -> bool:
        return all(n.unmanaged_unchanged for n in self.notes)

    def to_dict(self) -> dict[str, Any]:
        paths = [n.rel_path for n in self.notes]
        unique_paths = len(set(paths))
        return {
            "vault": self.vault,
            "dry_run": self.dry_run,
            "applied": self.applied,
            "domains": self.domains,
            "object_keys": self.object_keys,
            "totals": {
                "planned": len(self.notes),
                "unique_paths": unique_paths,
                "path_collisions": len(self.notes) - unique_paths,
                "create": sum(1 for n in self.notes if n.would_create),
                "update": sum(
                    1 for n in self.notes if (not n.would_create) and n.content_changed
                ),
                "noop": self.noop_count,
                "blocked": self.blocked_count,
                "unmanaged_ok": self.unmanaged_ok,
            },
            "notes": [n.to_dict() for n in self.notes],
        }

    def to_markdown(self) -> str:
        t = self.to_dict()["totals"]
        lines = [
            "# Vault re-projection report",
            "",
            f"- vault: `{self.vault}`",
            f"- dry_run: {self.dry_run}",
            f"- applied: {self.applied}",
            f"- domains: {', '.join(self.domains) or '(none)'}",
            f"- object_keys: {len(self.object_keys)}",
            f"- planned notes: {t['planned']}",
            f"- unique paths: {t['unique_paths']}",
            f"- path collisions: {t['path_collisions']}",
            f"- would create: {t['create']}",
            f"- would update: {t['update']}",
            f"- noop: {t['noop']}",
            f"- blocked (unmanaged drift): {t['blocked']}",
            f"- unmanaged regions unchanged: {t['unmanaged_ok']}",
            "",
        ]
        if self.notes:
            lines.append("## Sample paths (first 25)")
            lines.append("")
            for n in self.notes[:25]:
                lines.append(
                    f"- `{n.rel_path}` — {n.action}"
                    f"{'' if n.unmanaged_unchanged else ' **UNMANAGED DRIFT**'}"
                )
            if len(self.notes) > 25:
                lines.append(f"- … +{len(self.notes) - 25} more")
            lines.append("")
        return "\n".join(lines)


class VaultReprojector:
    """Bulk re-project canonical objects into an Obsidian vault."""

    def __init__(
        self,
        workspace: Workspace,
        *,
        vault: Path,
        registry: PackRegistry | None = None,
        folder_map: dict[str, str] | None = None,
        domains: list[str] | None = None,
    ) -> None:
        self.ws = workspace
        self.vault = Path(vault).expanduser().resolve()
        self.registry = registry or PackRegistry(workspace)
        self.folder_map = folder_map if folder_map is not None else dict(HERMES_FOLDER_MAP)
        self.domains = domains
        self._apply_folder_overrides()
        self.adapter = MarkdownAdapter(
            workspace, registry=self.registry, vault_root=self.vault
        )

    def _apply_folder_overrides(self) -> None:
        """Force pack markdown.folder to Hermes numbered folders when mapped."""
        for pack in self.registry.list():
            if self.domains is not None and pack.name not in self.domains:
                continue
            mapped = self.folder_map.get(pack.name)
            if mapped:
                pack.projections.markdown["folder"] = mapped

    def object_keys(self) -> list[str]:
        keys: list[str] = []
        for pack in self.registry.list():
            if self.domains is not None and pack.name not in self.domains:
                continue
            if pack.name.startswith("_"):
                continue
            for object_type in pack.objects:
                keys.append(f"{pack.name}:{object_type}")
        return sorted(keys)

    def run(self, *, apply: bool = False) -> ReprojectReport:
        """Dry-run by default. ``apply=True`` writes only when unmanaged bytes match."""
        keys = self.object_keys()
        report = ReprojectReport(
            vault=str(self.vault),
            dry_run=not apply,
            applied=False,
            domains=sorted(
                {
                    k.split(":", 1)[0]
                    for k in keys
                }
            ),
            object_keys=keys,
        )

        planned_writes: list[tuple[NoteDiff, str, Path]] = []
        for key in keys:
            for plan in self.adapter.plan_notes(key):
                rel = plan["rel_path"]
                target = safe_join(self.vault, rel)
                existing: str | None
                if target.is_file():
                    existing = target.read_text(encoding="utf-8", errors="replace")
                else:
                    existing = None
                preview = preview_managed_write(existing, plan["rendered"])
                if not preview["content_changed"]:
                    action = "noop"
                elif not preview["unmanaged_unchanged"]:
                    action = "blocked"
                elif preview["would_create"]:
                    action = "create"
                else:
                    action = "update"
                diff = NoteDiff(
                    rel_path=rel,
                    object_uid=plan["object_uid"],
                    entry_id=plan["entry_id"],
                    would_create=bool(preview["would_create"]),
                    content_changed=bool(preview["content_changed"]),
                    unmanaged_unchanged=bool(preview["unmanaged_unchanged"]),
                    action=action,
                )
                report.notes.append(diff)
                if action in {"create", "update"}:
                    planned_writes.append((diff, preview["merged"], target))

        if apply:
            if not report.unmanaged_ok:
                # Refuse to write when any planned merge would touch free zones.
                return report
            for _diff, merged, target in planned_writes:
                target.parent.mkdir(parents=True, exist_ok=True)
                from domain_foundry_core.projections.markdown import atomic_write_text

                atomic_write_text(target, merged)
            report.applied = True
            report.dry_run = False
        return report
