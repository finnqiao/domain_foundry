"""Release creation contract: calm copy and topic-shaped fallbacks."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from domain_foundry_core.api.app import create_app
from domain_foundry_core.api.harness import HarnessAPI
from domain_foundry_core.cli import app as cli_app


@pytest.mark.parametrize(
    ("goal", "wrong_direction"),
    [
        ("homebrew beer at home", "sourdough"),
        ("kombucha brewing log", "sourdough"),
        ("quilting projects and fabric", "climbing"),
        ("dog training sessions", "soccer"),
        ("watch collection and service history", "collecting"),
    ],
)
def test_release_broad_topics_do_not_show_a_neighboring_category(
    workspace, monkeypatch, goal: str, wrong_direction: str
) -> None:
    monkeypatch.setenv("DOMAIN_FOUNDRY_LLM", "heuristic")
    api = HarnessAPI(workspace.home)
    api.init()

    turn = api.create_domain(goal)
    ideas = (turn.get("neighborhood") or {}).get("ideas") or []
    visible_copy = " ".join(
        f"{idea.get('title', '')} {idea.get('pitch', '')}" for idea in ideas
    ).lower()

    assert goal.split()[0] in visible_copy
    assert wrong_direction not in visible_copy
    assert (turn.get("neighborhood") or {}).get("refine") == []
    assert (turn.get("neighborhood") or {}).get("expand") == []


def _choose_first_look(api: HarnessAPI, turn: dict) -> dict:
    session_id = turn["session_id"]
    ideas = (turn.get("neighborhood") or {}).get("ideas") or []
    turn = api.wizard_reply(session_id, ideas[0]["id"])
    assert turn["state"] == "looks"
    return api.wizard_reply(session_id, "1")


def test_release_unknown_interest_stays_topic_shaped(workspace, monkeypatch) -> None:
    monkeypatch.setenv("DOMAIN_FOUNDRY_LLM", "heuristic")
    api = HarnessAPI(workspace.home)
    api.init()

    turn = api.create_domain("track my lego builds")
    ideas = (turn.get("neighborhood") or {}).get("ideas") or []
    titles = " ".join(str(idea.get("title") or "") for idea in ideas).lower()

    assert turn["release_mode"] is True
    assert "lego" in titles
    assert "shelf" not in titles
    assert "timeline" not in titles
    assert "chart" not in titles
    assert (turn.get("neighborhood") or {}).get("refine") == []
    assert "catalogued" not in turn["user_message"].lower()

    chess = api.create_domain("I want to get better at chess")
    chess_titles = " ".join(
        str(idea.get("title") or "")
        for idea in (chess.get("neighborhood") or {}).get("ideas") or []
    ).lower()
    assert "chess" in chess_titles
    assert "better chess" not in chess_titles


def test_release_unknown_interest_uses_both_notes_before_first_use(workspace, monkeypatch) -> None:
    monkeypatch.setenv("DOMAIN_FOUNDRY_LLM", "heuristic")
    api = HarnessAPI(workspace.home)
    api.init()

    turn = _choose_first_look(api, api.create_domain("track my lego builds"))
    session_id = turn["session_id"]
    assert turn["state"] == "elicit"
    assert "Add a note" in turn["user_message"]

    turn = api.wizard_reply(session_id, "built the Hogwarts Castle set today, 6020 pieces")
    assert turn["state"] == "elicit"
    assert "different kind of note" in turn["user_message"]

    turn = api.wizard_reply(session_id, "sorted the loose bricks into the parts bins")
    assert turn["state"] == "test_drive"
    assert turn["pack"]["name"]
    assert "second note" in turn["user_message"].lower()
    assert "held-out" not in turn["user_message"].lower()

    captured = api.wizard_reply(session_id, "built the Hogwarts Castle set today, 6020 pieces")
    assert captured["capture"]["routed"][0]["domain"] == turn["pack"]["name"]
    assert captured["user_message"].startswith("Went to the right place")

    done = api.wizard_reply(session_id, "done")
    assert done["state"] == "done"
    assert done["user_message"] == "Your app is ready to use."


def test_release_does_not_call_an_unfiled_first_note_ready(workspace, monkeypatch) -> None:
    monkeypatch.setenv("DOMAIN_FOUNDRY_LLM", "heuristic")
    api = HarnessAPI(workspace.home)
    api.init()

    turn = _choose_first_look(api, api.create_domain("track my lego builds"))
    session_id = turn["session_id"]
    turn = api.wizard_reply(session_id, "skip for now")
    assert turn["state"] == "test_drive"

    blocked = api.wizard_reply(session_id, "done for now")
    assert blocked["state"] == "test_drive"
    assert blocked["done"] is False
    assert blocked["first_use_blocked"] is True
    assert "before calling it ready" in blocked["user_message"]


def test_release_api_supports_resume_events_and_cancel(workspace, monkeypatch) -> None:
    monkeypatch.setenv("DOMAIN_FOUNDRY_LLM", "heuristic")
    client = TestClient(create_app(workspace.home, enable_drain_loop=False))

    started = client.post("/api/create", json={"goal_text": "fish in my aquarium tank"})
    assert started.status_code == 200
    turn = started.json()
    session_id = turn["session_id"]
    assert turn["release_mode"] is True

    resumed = client.get(f"/api/create/{session_id}")
    assert resumed.status_code == 200
    assert resumed.json()["session_id"] == session_id

    events = client.get(f"/api/create/{session_id}/events")
    assert events.status_code == 200
    assert events.headers["content-type"].startswith("text/event-stream")
    assert "event: progress" in events.text
    assert "event: state" in events.text

    cancelled = client.post(f"/api/create/{session_id}/cancel")
    assert cancelled.status_code == 200
    assert cancelled.json()["state"] == "failed"
    assert cancelled.json()["done"] is True
    assert "Creation stopped" in cancelled.json()["user_message"]


def test_release_cli_is_conversational_and_scriptable(workspace, monkeypatch) -> None:
    monkeypatch.setenv("DOMAIN_FOUNDRY_LLM", "heuristic")
    result = CliRunner().invoke(
        cli_app,
        [
            "--home",
            str(workspace.home),
            "create",
            "track my lego builds",
            "--reply",
            "1",
            "--reply",
            "1",
            "--reply",
            "built the Hogwarts Castle set today, 6020 pieces",
            "--reply",
            "sorted the loose bricks into the parts bins",
        ],
    )

    assert result.exit_code == 0, result.stdout
    assert "What would you like to do with track my lego builds?" in result.stdout
    assert "Your app is ready to try" in result.stdout
    assert "Aborted" not in result.stdout
    assert "shelf" not in result.stdout.lower()
    assert "timeline" not in result.stdout.lower()
    assert "chart" not in result.stdout.lower()


def test_release_legacy_json_remains_available(workspace, monkeypatch) -> None:
    monkeypatch.setenv("DOMAIN_FOUNDRY_LLM", "heuristic")
    client = TestClient(create_app(workspace.home, enable_drain_loop=False))
    response = client.post("/api/wizard", json={"goal_text": "track my lego builds"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["release_mode"] is False
    assert payload["message"]
    json.dumps(payload)
