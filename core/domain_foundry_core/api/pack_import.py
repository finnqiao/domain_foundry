"""Preview/commit service for pack-declared structured imports."""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from typing import Any

from domain_foundry_core.clock import now
from domain_foundry_core.migrations.importers import (
    FixtureSource,
    GenericImporter,
    MappingConfig,
)
from domain_foundry_core.packs.registry import PackRegistry
from domain_foundry_core.paths import Workspace

TOKEN_TTL_SECONDS = 300


class PackImportError(ValueError):
    def __init__(self, message: str, *, status_code: int = 422) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass
class _Preview:
    domain: str
    mapping_id: str
    source_path: str
    fingerprint: str
    expires_at: float
    consumed: bool = False


class PackImportService:
    """Keep structured import previews local, expiring, and source-bound."""

    def __init__(self, workspace: Workspace, *, registry: PackRegistry | None = None) -> None:
        self.workspace = workspace
        self.registry = registry or PackRegistry(workspace)
        self._previews: dict[str, _Preview] = {}
        self._lock = Lock()

    def preview(self, domain: str, mapping_id: str, source_path: str | None = None) -> dict[str, Any]:
        pack, mapping, path, fingerprint = self._inputs(domain, mapping_id, source_path)
        report = GenericImporter(
            self.workspace,
            _mapping_config(pack.name, mapping),
            registry=self.registry,
            dry_run=True,
        ).run(FixtureSource(path))
        token = secrets.token_urlsafe(32)
        expires_at = now().timestamp() + TOKEN_TTL_SECONDS
        with self._lock:
            self._prune()
            self._previews[token] = _Preview(
                domain=domain,
                mapping_id=mapping_id,
                source_path=str(path),
                fingerprint=fingerprint,
                expires_at=expires_at,
            )
        return _report(
            report.to_dict(),
            phase="preview",
            domain=domain,
            mapping_id=mapping_id,
            source_path=path,
            fingerprint=fingerprint,
            token=token,
            expires_at=expires_at,
        )

    def commit(self, domain: str, mapping_id: str, source_path: str | None, token: str) -> dict[str, Any]:
        if not token.strip():
            raise PackImportError("A preview token is required before importing.", status_code=409)
        pack, mapping, path, fingerprint = self._inputs(domain, mapping_id, source_path)
        with self._lock:
            preview = self._previews.get(token)
            if preview is None or preview.expires_at <= now().timestamp():
                self._previews.pop(token, None)
                raise PackImportError(
                    "That preview has expired or is not valid. Preview the source again.",
                    status_code=409,
                )
            if preview.consumed:
                raise PackImportError(
                    "That preview token has already been used. Preview the source again.",
                    status_code=409,
                )
            if (
                preview.domain != domain
                or preview.mapping_id != mapping_id
                or preview.source_path != str(path)
                or preview.fingerprint != fingerprint
            ):
                raise PackImportError(
                    "The source changed after preview. Preview the current source again.",
                    status_code=409,
                )
            preview.consumed = True

        report = GenericImporter(
            self.workspace,
            _mapping_config(pack.name, mapping),
            registry=self.registry,
            dry_run=False,
        ).run(FixtureSource(path))
        return _report(
            report.to_dict(),
            phase="commit",
            domain=domain,
            mapping_id=mapping_id,
            source_path=path,
            fingerprint=fingerprint,
        )

    def declarations(self, domain: str) -> list[dict[str, Any]]:
        self.registry.reload()
        pack = self.registry.get(domain)
        if pack is None:
            return []
        declaration = pack.capabilities.get("imports") or {}
        return [dict(mapping) for mapping in declaration.get("mappings") or [] if isinstance(mapping, dict)]

    def _inputs(
        self, domain: str, mapping_id: str, source_path: str | None
    ) -> tuple[Any, dict[str, Any], Path, str]:
        self.registry.reload()
        pack = self.registry.get(domain)
        if pack is None:
            raise PackImportError(f"No installed pack for domain {domain!r}", status_code=404)
        declaration = pack.capabilities.get("imports") or {}
        mapping = next(
            (item for item in declaration.get("mappings") or [] if item.get("id") == mapping_id),
            None,
        )
        if not isinstance(mapping, dict):
            raise PackImportError(f"No import mapping {mapping_id!r} is declared by {domain!r}", status_code=404)
        raw_path = Path(source_path).expanduser() if source_path else pack.root / str(mapping.get("fixture") or "")
        try:
            path = raw_path.resolve(strict=True)
        except FileNotFoundError as exc:
            raise PackImportError("The import source path does not exist.") from exc
        if not path.is_file() and not path.is_dir():
            raise PackImportError("The import source path must be a JSON/JSONL file or directory.")
        return pack, mapping, path, _fingerprint(path)

    def _prune(self) -> None:
        now_epoch = now().timestamp()
        self._previews = {
            token: preview
            for token, preview in self._previews.items()
            if preview.expires_at > now_epoch and not preview.consumed
        }


def _mapping_config(domain: str, declaration: dict[str, Any]) -> MappingConfig:
    entities = []
    for entity in declaration.get("entities") or []:
        normalized = dict(entity)
        normalized.setdefault("domain", domain)
        entities.append(normalized)
    return MappingConfig(
        name=str(declaration.get("id") or "pack-import"),
        channel=str(declaration.get("channel") or f"{domain}-import"),
        entities=entities,
        notes=str(declaration.get("title") or "pack-declared import"),
    )


def _fingerprint(path: Path) -> str:
    digest = hashlib.sha256()
    if path.is_file():
        digest.update(path.read_bytes())
        return digest.hexdigest()
    for child in sorted(item for item in path.rglob("*") if item.is_file()):
        digest.update(str(child.relative_to(path)).encode("utf-8"))
        digest.update(child.read_bytes())
    return digest.hexdigest()


def _report(
    raw: dict[str, Any],
    *,
    phase: str,
    domain: str,
    mapping_id: str,
    source_path: Path,
    fingerprint: str,
    token: str | None = None,
    expires_at: float | None = None,
) -> dict[str, Any]:
    payload = {
        "phase": phase,
        "domain": domain,
        "mapping_id": mapping_id,
        "source_path": str(source_path),
        "content_fingerprint": fingerprint,
        "source_total": raw.get("source_total", 0),
        "accounted_for": raw.get("accounted_for", 0),
        "complete": raw.get("complete", False),
        "imported": raw.get("imported", 0),
        "would_import": raw.get("would_import", 0),
        "skipped_existing": raw.get("skipped_existing", 0),
        "skipped_invalid": raw.get("skipped_invalid", 0),
        "failed": raw.get("failed", 0),
        "by_entity": raw.get("by_entity", {}),
        "outcomes": raw.get("outcomes", []),
    }
    if token:
        payload["preview_token"] = token
    if expires_at is not None:
        from datetime import UTC, datetime

        payload["preview_expires_at"] = datetime.fromtimestamp(expires_at, UTC).replace(
            microsecond=0
        ).isoformat().replace("+00:00", "Z")
    return payload
