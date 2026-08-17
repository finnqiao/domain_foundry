"""HTTP contract for the authenticated Roamboard import shell seam."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from fastapi.testclient import TestClient

from domain_foundry_core.api.app import create_app
from domain_foundry_core.api.harness import HarnessAPI

REPO = Path(__file__).resolve().parents[1]
FEED = REPO / "fixtures" / "roamboard" / "feed.json"


def _client(home: Path, *, token: str = "roamboard-secret") -> TestClient:
    HarnessAPI(home).init()
    return TestClient(create_app(home, api_token=token, enable_drain_loop=False))


def _auth(token: str = "roamboard-secret") -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_preview_commit_is_bound_to_feed_and_token_and_is_idempotent(tmp_path: Path):
    home = tmp_path / "home"
    client = _client(home)

    unauthenticated = client.post("/api/import/roamboard/preview", json={"feed_path": str(FEED)})
    assert unauthenticated.status_code == 401

    preview_response = client.post(
        "/api/import/roamboard/preview",
        json={"feed_path": str(FEED)},
        headers=_auth(),
    )
    assert preview_response.status_code == 200
    preview = preview_response.json()
    assert preview["feed_path"] == str(FEED.resolve())
    assert len(preview["content_fingerprint"]) == 64
    assert preview["preview_token"]
    assert {key: preview[key] for key in ("created", "updated", "skipped", "conflict", "error")} == {
        "created": 7,
        "updated": 0,
        "skipped": 0,
        "conflict": 0,
        "error": 0,
    }
    assert len(preview["records"]) == 7
    assert preview["raw_adapter_payload"]["mode"] == "dry_run"

    changed = tmp_path / "changed.json"
    changed.write_bytes(FEED.read_bytes())
    changed.write_text(
        json.dumps({"schemaVersion": 2, "trips": []}) + "\n", encoding="utf-8"
    )
    mismatch = client.post(
        "/api/import/roamboard/commit",
        json={"feed_path": str(changed), "preview_token": preview["preview_token"]},
        headers=_auth(),
    )
    assert mismatch.status_code == 409
    assert "changed" in mismatch.json()["detail"]

    committed_response = client.post(
        "/api/import/roamboard/commit",
        json={"feed_path": str(FEED), "preview_token": preview["preview_token"]},
        headers=_auth(),
    )
    assert committed_response.status_code == 200
    committed = committed_response.json()
    assert committed["phase"] == "commit"
    assert committed["created"] == 7
    assert committed["raw_adapter_payload"]["applied"] is True

    consumed = client.post(
        "/api/import/roamboard/commit",
        json={"feed_path": str(FEED), "preview_token": preview["preview_token"]},
        headers=_auth(),
    )
    assert consumed.status_code == 409
    assert "already been used" in consumed.json()["detail"]

    second_preview = client.post(
        "/api/import/roamboard/preview",
        json={"feed_path": str(FEED)},
        headers=_auth(),
    ).json()
    second_commit = client.post(
        "/api/import/roamboard/commit",
        json={"feed_path": str(FEED), "preview_token": second_preview["preview_token"]},
        headers=_auth(),
    )
    assert second_commit.status_code == 200
    assert second_commit.json()["created"] == 0
    assert second_commit.json()["skipped"] == 7


def test_preview_rejects_non_schema_v2_feed_and_expired_token(tmp_path: Path, monkeypatch):
    home = tmp_path / "home"
    client = _client(home)
    invalid = tmp_path / "invalid.json"
    invalid.write_text(json.dumps({"schemaVersion": 1, "trips": []}), encoding="utf-8")

    response = client.post(
        "/api/import/roamboard/preview",
        json={"feed_path": str(invalid)},
        headers=_auth(),
    )
    assert response.status_code == 422
    assert "schemaVersion 2" in response.json()["detail"]

    preview = client.post(
        "/api/import/roamboard/preview",
        json={"feed_path": str(FEED)},
        headers=_auth(),
    ).json()
    monkeypatch.setattr(
        "domain_foundry_core.api.roamboard_import.now",
        lambda: datetime(9999, 1, 1, tzinfo=UTC),
    )
    expired = client.post(
        "/api/import/roamboard/commit",
        json={"feed_path": str(FEED), "preview_token": preview["preview_token"]},
        headers=_auth(),
    )
    assert expired.status_code == 409
    assert "expired" in expired.json()["detail"]


def test_shadow_get_reads_latest_report_and_streak_without_fabricating_gate(tmp_path: Path):
    home = tmp_path / "home"
    client = _client(home)
    root = home / "shadow" / "roamboard" / "20260810T000000Z"
    root.mkdir(parents=True)
    (root / "diff.json").write_text(
        json.dumps(
            {
                "private": {"trips": 1, "timeline_items": 2},
                "foundry": {"trips": 1, "timeline_items": 2},
                "diffs": [{"kind": "count_mismatch", "soft": True}],
                "trip_slug_only_private": [],
                "trip_slug_only_foundry": [],
                "report_dir": None,
            }
        ),
        encoding="utf-8",
    )
    (home / "shadow" / "roamboard" / "ZERO_DIFF_STREAK.txt").write_text(
        "2026-08-08 zero-diff\n2026-08-09 zero-diff\n", encoding="utf-8"
    )

    response = client.get("/api/import/roamboard/shadow", headers=_auth())
    assert response.status_code == 200
    payload = response.json()
    assert payload["available"] is True
    assert payload["report"]["report_dir"] == str(root)
    assert payload["report"]["zero_diff"] is True
    assert payload["streak"] == {
        "days": 2,
        "target": 7,
        "complete": False,
        "source": str(home / "shadow" / "roamboard" / "ZERO_DIFF_STREAK.txt"),
        "human_gate": True,
    }
