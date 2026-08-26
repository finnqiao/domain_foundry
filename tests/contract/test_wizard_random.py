"""Held-out random-interest gate. No skip-as-install. No live LLM."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from domain_foundry_core.api.harness import HarnessAPI
from domain_foundry_core.atlas.query import query_neighborhood

SUITE = Path("examples/heldout/wizard_random_suite.jsonl")


def _load_suite() -> list[dict]:
    rows = []
    for line in SUITE.read_text(encoding="utf-8").splitlines():
        if line.strip() and not line.lstrip().startswith("#"):
            rows.append(json.loads(line))
    return rows


def _blob(nb: dict) -> str:
    parts = [nb.get("cursor") or ""]
    for key in ("refine", "expand", "ideas", "breadcrumb"):
        for card in nb.get(key) or []:
            parts.append(card.get("id") or "")
            parts.append(card.get("title") or "")
            parts.append(card.get("pitch") or "")
    return " ".join(parts).lower()


def _ideas_text(turn: dict) -> str:
    nb = turn.get("neighborhood") or {}
    return " ".join(
        f"{i.get('id', '')} {i.get('title', '')} {i.get('pitch', '')}"
        for i in (nb.get("ideas") or [])
    ).lower()


@pytest.mark.parametrize("case", _load_suite(), ids=lambda c: c["id"])
def test_random_suite_neighborhood_does_not_false_match(case):
    nb = query_neighborhood(case["goal"])
    cursor = (nb.get("cursor") or "").lower()
    blob = _blob(nb)
    for needle in case.get("forbid_cursor") or []:
        assert needle.lower() not in cursor, (case["id"], cursor, needle)
    if case.get("expect_cursor_blob"):
        assert any(n.lower() in blob for n in case["expect_cursor_blob"]), (case["id"], blob)
    if case.get("expect_ideas") and not case.get("expect_unindexed_or_invented"):
        for needle in case["expect_ideas"]:
            assert needle.lower() in blob, (case["id"], needle, blob)
    if case.get("expect_highlight"):
        highlighted = [i for i in (nb.get("ideas") or []) if i.get("highlighted")]
        titles = " ".join(i.get("title", "").lower() for i in highlighted) or blob
        for needle in case["expect_highlight"]:
            assert needle.lower() in titles, (case["id"], titles)
    if case.get("unindexed_or_not_dining"):
        assert "food.dining" not in cursor
    if case.get("expect_unindexed_or_invented"):
        assert nb.get("unindexed") is True or not cursor, (case["id"], cursor, nb.get("unindexed"))


@pytest.mark.parametrize(
    "case",
    [c for c in _load_suite() if c.get("pick")],
    ids=lambda c: c["id"],
)
def test_random_suite_looks_build_capture(workspace, monkeypatch, case):
    monkeypatch.setenv("DOMAIN_FOUNDRY_HOME", str(workspace.home))
    api = HarnessAPI(workspace.home)
    api.init()
    fork = api.new_domain(case["goal"])
    sid = fork["session_id"]
    assert fork["state"] == "fork", fork
    cursor = ((fork.get("neighborhood") or {}).get("cursor") or "").lower()
    for needle in case.get("forbid_cursor") or []:
        assert needle.lower() not in cursor, (case["id"], cursor)
    ideas = _ideas_text(fork)
    if case.get("expect_unindexed_or_invented"):
        assert (fork.get("neighborhood") or {}).get("ideas"), (
            case["id"],
            "unindexed fork must still offer invented ideas",
        )
        jobs = " ".join(
            " ".join(i.get("jobs") or [])
            for i in (fork.get("neighborhood") or {}).get("ideas") or []
        )
        assert "catalog" in jobs or "event_log" in jobs or "improvement" in jobs, jobs
    elif case.get("expect_ideas"):
        assert any(n.lower() in ideas for n in case["expect_ideas"]), (case["id"], ideas)

    looks = api.wizard_reply(sid, case["pick"])
    if looks["state"] == "fork":
        looks = api.wizard_reply(sid, "1")
    assert looks["state"] == "looks", looks
    live = api.wizard_reply(sid, case.get("then") or "build it")
    if live["state"] == "looks":
        live = api.wizard_reply(sid, "build it")
    # An invented neighbourhood asks for two sentences before it designs. These
    # cases probe with the scaffold's own vocabulary ("added ink to the shelf
    # with photos"), so they decline — the skip path is exactly what they pin.
    while live["state"] == "elicit":
        live = api.wizard_reply(sid, "skip")
    assert live["state"] in {"test_drive", "repair"}, live
    name = (live.get("pack") or {}).get("name") or live.get("domain")
    assert name, live
    assert name != "sourdough" or "sourdough" in case["goal"] or "bake" in case["goal"]

    cap = api.wizard_reply(sid, case["in_jargon"])
    routed = (cap.get("capture") or cap.get("routed") or [])
    if isinstance(routed, dict):
        routed = routed.get("routed") or []
    receipt = cap.get("capture") or cap
    if not routed and isinstance(receipt, dict):
        routed = receipt.get("routed") or []
    assert routed, cap
    assert routed[0].get("domain") == name
    assert routed[0].get("disposition") not in {"unfiled", "ledger_only"}

    idle = api.capture(case["idle"])
    data = idle.model_dump()
    idle_domains = {s.get("domain") for s in (data.get("routed") or [])}
    assert name not in idle_domains or data.get("status") in {
        "unfiled",
        "ledger_only",
    }, data

    if case.get("mismatch"):
        miss = api.capture(case["mismatch"])
        miss_data = miss.model_dump()
        assert miss_data.get("status") in {"unfiled", "ledger_only", "review", "applied"}
        if miss_data.get("status") == "applied":
            obj = ((miss_data.get("routed") or [{}])[0]).get("object_type")
            assert obj != "set", miss_data

    if case.get("correct"):
        fixed = api.correct(text=case["correct"])
        assert fixed.get("applied") is True, fixed
        details = json.dumps(fixed).lower()
        assert "charizard" not in (fixed.get("details") or {}).get("fields", {}) if isinstance(
            (fixed.get("details") or {}).get("fields"), dict
        ) else True
        assert "charizard" not in str((fixed.get("details") or {}).get("new_fields") or "")
        _ = details
