"""Authenticated-server helpers for the Roamboard preview/commit shell seam."""

from __future__ import annotations

import hashlib
import json
import re
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock
from typing import Any

from domain_foundry_core.clock import now
from domain_foundry_core.paths import Workspace

TOKEN_TTL_SECONDS = 300


class RoamboardImportError(ValueError):
    def __init__(self, message: str, *, status_code: int = 422) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass
class _Preview:
    feed_path: str
    fingerprint: str
    expires_at: float
    report: dict[str, Any]
    consumed: bool = False


class RoamboardImportService:
    """Keep preview tokens process-local and bind them to the exact feed bytes."""

    def __init__(self, workspace: Workspace) -> None:
        self.workspace = workspace
        self._previews: dict[str, _Preview] = {}
        self._lock = Lock()

    def preview(self, feed_path: str) -> dict[str, Any]:
        path, fingerprint = _validated_feed(feed_path)
        raw = _sync(path, self.workspace.home, mode="dry_run")
        report = _stable_report(raw, path=path, fingerprint=fingerprint, phase="preview")
        token = secrets.token_urlsafe(32)
        expires_at = now().timestamp() + TOKEN_TTL_SECONDS
        with self._lock:
            self._prune()
            self._previews[token] = _Preview(
                feed_path=str(path),
                fingerprint=fingerprint,
                expires_at=expires_at,
                report=report,
            )
        report["preview_token"] = token
        report["preview_expires_at"] = _iso_timestamp(expires_at)
        return report

    def commit(self, feed_path: str, preview_token: str) -> dict[str, Any]:
        if not preview_token.strip():
            raise RoamboardImportError(
                "A preview token is required before importing.", status_code=409
            )
        path, fingerprint = _validated_feed(feed_path)
        with self._lock:
            preview = self._previews.get(preview_token)
            if preview is None or preview.expires_at <= now().timestamp():
                self._previews.pop(preview_token, None)
                raise RoamboardImportError(
                    "That preview has expired or is not valid. Preview the feed again.",
                    status_code=409,
                )
            if preview.consumed:
                raise RoamboardImportError(
                    "That preview token has already been used. Preview the feed again.",
                    status_code=409,
                )
            if preview.feed_path != str(path) or preview.fingerprint != fingerprint:
                raise RoamboardImportError(
                    "The feed changed after preview. Preview the current feed again.",
                    status_code=409,
                )
            # Consume before the write so concurrent requests cannot both apply.
            preview.consumed = True

        raw = _sync(path, self.workspace.home, mode="apply")
        return _stable_report(raw, path=path, fingerprint=fingerprint, phase="commit")

    def latest_shadow(self) -> dict[str, Any]:
        root = self.workspace.home / "shadow" / "roamboard"
        candidates = (
            [
                path / "diff.json"
                for path in root.iterdir()
                if path.is_dir() and (path / "diff.json").is_file()
            ]
            if root.is_dir()
            else []
        )
        latest = max(candidates, key=lambda path: (path.stat().st_mtime, path.name), default=None)
        report: dict[str, Any] | None = None
        if latest is not None:
            try:
                payload = json.loads(latest.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise RoamboardImportError(
                    f"The latest shadow report could not be read: {exc}", status_code=500
                ) from exc
            if not isinstance(payload, dict):
                raise RoamboardImportError(
                    "The latest shadow report is not a JSON object.", status_code=500
                )
            report = payload
            if not report.get("report_dir"):
                report["report_dir"] = str(latest.parent)
            report["zero_diff"] = _shadow_zero_diff(report)

        streak_path = root / "ZERO_DIFF_STREAK.txt"
        streak_days = _read_streak(streak_path)
        return {
            "available": report is not None,
            "report": report,
            "streak": {
                "days": streak_days,
                "target": 7,
                "complete": streak_days >= 7,
                "source": str(streak_path) if streak_path.is_file() else None,
                "human_gate": True,
            },
        }

    def _prune(self) -> None:
        now_epoch = now().timestamp()
        self._previews = {
            token: preview
            for token, preview in self._previews.items()
            if preview.expires_at > now_epoch and not preview.consumed
        }


def _sync(path: Path, home: Path, *, mode: str) -> dict[str, Any]:
    try:
        from domain_foundry_roamboard.sync import SyncMode, sync_roamboard
    except ImportError as exc:  # pragma: no cover - wheel without optional adapter
        raise RoamboardImportError(
            "Roamboard import is not installed in this server build.", status_code=501
        ) from exc
    try:
        report = sync_roamboard(home, mode=SyncMode(mode), feed=path)
    except ValueError as exc:
        raise RoamboardImportError(
            f"The Roamboard feed could not be reconciled: {exc}", status_code=422
        ) from exc
    return report.to_dict()


def _validated_feed(feed_path: str) -> tuple[Path, str]:
    raw_path = Path(feed_path).expanduser()
    try:
        path = raw_path.resolve(strict=True)
    except FileNotFoundError as exc:
        raise RoamboardImportError(
            "The Roamboard feed path does not exist.", status_code=422
        ) from exc
    if not path.is_file():
        raise RoamboardImportError(
            "The Roamboard feed path must point to a file.", status_code=422
        )
    try:
        content = path.read_bytes()
        payload = json.loads(content)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RoamboardImportError(
            "The Roamboard feed must be readable JSON.", status_code=422
        ) from exc
    if not isinstance(payload, dict) or payload.get("schemaVersion") != 2:
        raise RoamboardImportError(
            "The Roamboard feed must declare schemaVersion 2.", status_code=422
        )
    return path, hashlib.sha256(content).hexdigest()


def _stable_report(
    raw: dict[str, Any], *, path: Path, fingerprint: str, phase: str
) -> dict[str, Any]:
    import_report = raw.get("import_report") or {}
    records: list[dict[str, Any]] = []
    counts = {key: 0 for key in ("created", "updated", "skipped", "conflict", "error")}
    for outcome in import_report.get("outcomes") or []:
        kind = str(outcome.get("kind") or "failed")
        stable = {
            "imported": "created",
            "would_import": "created",
            "updated": "updated",
            "skipped_existing": "skipped",
            "skipped_invalid": "conflict",
            "conflict": "conflict",
            "failed": "error",
            "error": "error",
        }.get(kind, "error")
        counts[stable] += 1
        records.append(
            {
                "entity": outcome.get("entity"),
                "source_ref": outcome.get("source_ref"),
                "source_id": outcome.get("source_id"),
                "outcome": stable,
                "reason": outcome.get("reason"),
                "raw": outcome,
            }
        )
    return {
        "phase": phase,
        "feed_path": str(path),
        "content_fingerprint": fingerprint,
        "source_total": import_report.get("source_total", len(records)),
        "accounted_for": import_report.get("accounted_for", len(records)),
        "complete": import_report.get("complete", False),
        **counts,
        "records": records,
        # Keep the raw adapter shape available for diagnostics and future
        # adapter fields while the stable fields above remain the UI contract.
        "raw_adapter_payload": raw,
        "adapter_report": raw,
    }


def _iso_timestamp(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, UTC).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )


def _read_streak(path: Path) -> int:
    if not path.is_file():
        return 0
    lines = path.read_text(encoding="utf-8").splitlines()
    count = 0
    seen_dates: set[str] = set()
    for line in reversed(lines):
        match = re.match(r"^(\d{4}-\d{2}-\d{2}) zero-diff$", line.strip())
        if not match:
            break
        if match.group(1) in seen_dates:
            continue
        seen_dates.add(match.group(1))
        count += 1
    return count


def _shadow_zero_diff(report: dict[str, Any]) -> bool:
    """Mirror ``ShadowReport.zero_diff`` for the persisted JSON payload."""
    hard_diffs = [diff for diff in report.get("diffs") or [] if not diff.get("soft")]
    private = report.get("private") or {}
    foundry = report.get("foundry") or {}
    return (
        not hard_diffs
        and not report.get("trip_slug_only_private")
        and not report.get("trip_slug_only_foundry")
        and private.get("trips") == foundry.get("trips")
        and private.get("timeline_items") == foundry.get("timeline_items")
    )
