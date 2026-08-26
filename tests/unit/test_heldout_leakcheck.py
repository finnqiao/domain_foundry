"""The guard on the protected held-out interest set.

Two things have to be true for ``scripts/heldout_leakcheck.py`` to be worth
running: it has to pass on the tree as committed, and it has to fail on a tree
where somebody has quietly taught the atlas a held-out case's answer. A check
that only ever prints "ok" proves nothing.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Any

import yaml

REPO = Path(__file__).resolve().parents[2]
HELDOUT = REPO / "examples" / "heldout" / "interest_suite_heldout.jsonl"


def _module() -> Any:
    """Load the script from its path. Untyped by nature — its module-level
    constants are not visible to a type checker through exec_module."""
    path = REPO / "scripts" / "heldout_leakcheck.py"
    spec = importlib.util.spec_from_file_location("heldout_leakcheck", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _cases() -> list[dict[str, Any]]:
    lines = HELDOUT.read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line.strip()]


def test_clean_tree_has_no_leaks() -> None:
    """The committed tree passes. This is the gate."""
    assert _module().check() == []


def test_cli_exits_zero_on_the_clean_tree() -> None:
    assert _module().main([]) == 0


def test_json_mode_is_machine_readable(capsys: Any) -> None:
    mod = _module()
    assert mod.main(["--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["cases"] == len(_cases())
    assert payload["findings"] == []


def test_planted_atlas_leak_is_caught(tmp_path: Path) -> None:
    """Teaching the atlas a held-out probe word is the exact move to catch."""
    mod = _module()
    atlas = tmp_path / "atlas"
    atlas.mkdir()
    # "pellicle" is h11_kombucha's jargon probe. Bolting it onto a fermentation
    # node is how a well-meaning author would "fix" that case.
    atlas.joinpath("food.yaml").write_text(
        yaml.safe_dump(
            {
                "nodes": [
                    {
                        "id": "food.fermentation",
                        "kind": "practice",
                        "title": "Fermentation",
                        "aliases": ["kombucha", "pellicle"],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    empty_suite = tmp_path / "suite.jsonl"
    empty_suite.write_text("", encoding="utf-8")

    findings = mod.check(HELDOUT, atlas, empty_suite)
    leaks = [f for f in findings if f["kind"] == "atlas_leak"]
    assert leaks, "planted atlas leak was not caught"
    assert {f["token"] for f in leaks} == {"pellicle"}
    assert leaks[0]["case"] == "h11_kombucha"
    assert "food.fermentation.aliases" in leaks[0]["where"]


def test_planted_leak_reports_the_node_and_field(tmp_path: Path) -> None:
    """Actionability: the failure names the token, the file, the node, the field."""
    mod = _module()
    atlas = tmp_path / "atlas"
    atlas.mkdir()
    atlas.joinpath("life.yaml").write_text(
        yaml.safe_dump(
            {
                "nodes": [
                    {
                        "id": "plants.orchids",
                        "kind": "practice",
                        "title": "Orchids",
                        "vocabulary": ["keiki"],
                        "routing_examples": [{"text": "the phal is silvery", "object": "event"}],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    empty_suite = tmp_path / "suite.jsonl"
    empty_suite.write_text("", encoding="utf-8")

    findings = mod.check(HELDOUT, atlas, empty_suite)
    where = {f["where"].split(":", 1)[1] for f in findings if f["kind"] == "atlas_leak"}
    assert "plants.orchids.vocabulary" in where
    assert "plants.orchids.routing_examples" in where
    detail = next(f["detail"] for f in findings if f["token"] == "keiki")
    assert "h08_orchids" in detail and "atlas/life.yaml" in detail


def test_visible_suite_leak_is_caught(tmp_path: Path) -> None:
    """The two suites stop being independent the moment they share a probe word."""
    mod = _module()
    atlas = tmp_path / "atlas"
    atlas.mkdir()
    suite = tmp_path / "suite.jsonl"
    suite.write_text(
        json.dumps(
            {
                "id": "99_planted",
                "bucket": "unindexed",
                "goal": "whatever",
                "jargon": "the springtails did their job",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    findings = mod.check(HELDOUT, atlas, suite)
    hits = [f for f in findings if f["kind"] == "suite_leak"]
    assert {f["token"] for f in hits} == {"springtails"}
    assert hits[0]["case"] == "h17_terrarium"


def test_new_atlas_node_for_a_heldout_goal_is_caught(tmp_path: Path) -> None:
    """Adding a node because a held-out goal missed trips the goal ratchet."""
    mod = _module()
    atlas = tmp_path / "atlas"
    atlas.mkdir()
    atlas.joinpath("life.yaml").write_text(
        yaml.safe_dump(
            {
                "nodes": [
                    {"id": "craft.bonsai", "kind": "practice", "title": "Bonsai", "aliases": []}
                ]
            }
        ),
        encoding="utf-8",
    )
    empty_suite = tmp_path / "suite.jsonl"
    empty_suite.write_text("", encoding="utf-8")

    findings = mod.check(HELDOUT, atlas, empty_suite)
    ratchet = [f for f in findings if f["kind"] == "goal_indexed"]
    assert [(f["case"], f["token"]) for f in ratchet] == [("h03_bonsai", "bonsai")]


def test_seed_sharing_a_word_with_its_jargon_is_caught(tmp_path: Path) -> None:
    """The authoring rule is enforced, not trusted: no seed/jargon content word."""
    mod = _module()
    cases = tmp_path / "planted.jsonl"
    cases.write_text(
        json.dumps(
            {
                "id": "z01_planted",
                "bucket": "unindexed",
                "goal": "whatever",
                "accept": [],
                "forbid": [],
                "unindexed_ok": True,
                "jargon": "racked the saison to secondary",
                "seed": "racked another carboy yesterday",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    atlas = tmp_path / "atlas"
    atlas.mkdir()
    empty_suite = tmp_path / "suite.jsonl"
    empty_suite.write_text("", encoding="utf-8")

    findings = mod.check(cases, atlas, empty_suite)
    overlaps = [f for f in findings if f["kind"] == "seed_overlap"]
    assert [f["token"] for f in overlaps] == ["racked"]
    argv = ["--cases", str(cases), "--atlas", str(atlas), "--suite", str(empty_suite)]
    assert mod.main(argv) == 1


def test_generic_words_do_not_trip_the_check(tmp_path: Path) -> None:
    """A shared 'photos' is not evidence of anything; the allowlist says so."""
    mod = _module()
    cases = tmp_path / "planted.jsonl"
    cases.write_text(
        json.dumps(
            {
                "id": "z02_planted",
                "bucket": "unindexed",
                "goal": "whatever",
                "jargon": "took photos this morning and wrote some notes",
                "seed": "more photos in the evening, notes as usual",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    atlas = tmp_path / "atlas"
    atlas.mkdir()
    atlas.joinpath("x.yaml").write_text(
        yaml.safe_dump(
            {"nodes": [{"id": "a.b", "kind": "idea", "title": "Photos", "jargon": ["notes"]}]}
        ),
        encoding="utf-8",
    )
    empty_suite = tmp_path / "suite.jsonl"
    empty_suite.write_text("", encoding="utf-8")

    assert mod.check(cases, atlas, empty_suite) == []


def test_heldout_cases_are_well_formed() -> None:
    """The file the guard protects has to be a suite the runner can load."""
    cases = _cases()
    assert len(cases) == 20
    assert len({c["id"] for c in cases}) == 20
    for case in cases:
        assert case["bucket"] in {"indexed", "collision", "unindexed"}
        assert case["goal"] and case["jargon"]
        assert isinstance(case["accept"], list) and isinstance(case["forbid"], list)
        assert isinstance(case["unindexed_ok"], bool)
        # An unindexed case claims the atlas has no home, so it cannot also
        # accept one; and a case with no accepted home must say a miss is honest.
        if case["bucket"] == "unindexed":
            assert case["accept"] == []
            assert case["forbid"], f"{case['id']} must name what it may not snap to"
        if not case["accept"]:
            assert case["unindexed_ok"] is True

    # An honest mix, not a set chosen to pass. The atlas genuinely covers some
    # of these; most of them it does not, and a few sit on a real collision.
    buckets: dict[str, int] = {}
    for case in cases:
        buckets[case["bucket"]] = buckets.get(case["bucket"], 0) + 1
    assert buckets == {"indexed": 7, "collision": 8, "unindexed": 5}


def test_allowlist_entries_carry_a_justification() -> None:
    """Every allowlisted word has to say why it is generic, not why it was
    convenient. An empty reason is how this file quietly stops meaning anything."""
    mod = _module()
    for word, reason in mod.GENERIC_HOBBY_WORDS.items():
        assert reason.strip(), f"{word} has no justification"
    for key, reason in mod.KNOWN_GOAL_ECHOES.items():
        assert reason.strip(), f"{key} has no justification"
        assert key.count(":") == 2, f"{key} is not case:token:node"
