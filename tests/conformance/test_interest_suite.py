"""Guards on the interest suite itself, not on the create path it measures.

The suite is a gate, so the gate needs its own gate: the cases must load, the
judge must be deterministic and ordered correctly, and the committed baseline
must cover every case. A ratchet with a missing entry silently stops ratcheting.

Running all fifty goals is slow and lives in CI (`domain-foundry eval
interest-suite`); these tests only prove the machinery is sound.
"""

from __future__ import annotations

import json

import pytest

from domain_foundry_core.evals import interest as suite


def test_suite_loads_with_the_expected_shape() -> None:
    cases = suite.load_cases()
    assert len(cases) == 50

    ids = [case["id"] for case in cases]
    assert len(set(ids)) == len(ids), "case ids must be unique"

    buckets: dict[str, int] = {}
    for case in cases:
        assert case["goal"].strip(), f"{case['id']} has no goal"
        assert case["jargon"].strip(), f"{case['id']} has no jargon probe"
        buckets[case["bucket"]] = buckets.get(case["bucket"], 0) + 1
    assert buckets == {"indexed": 30, "collision": 10, "unindexed": 10}


def test_unindexed_cases_forbid_snapping_but_accept_nothing() -> None:
    """An unindexed goal has no right answer, only wrong ones."""
    for case in suite.load_cases():
        if case["bucket"] != "unindexed":
            continue
        assert case["unindexed_ok"] is True
        assert case["accept"] == []
        assert case["forbid"], f"{case['id']} must name the neighbourhoods it may not snap to"


def test_verdict_order_runs_worst_to_best() -> None:
    ranked = [suite.verdict_rank(v) for v in suite.VERDICT_ORDER]
    assert ranked == sorted(ranked)
    assert suite.verdict_rank("fail_snap") < suite.verdict_rank("fail_loop")
    assert suite.verdict_rank("pass_with_gap") < suite.verdict_rank("pass")


@pytest.mark.parametrize(
    ("cursor", "unindexed", "expected"),
    [
        ("food.fermentation", False, "hit"),
        ("food.fermentation.bake_lab", False, "hit"),
        ("making.dev", False, "false_snap"),
        ("making.dev.scratch", False, "false_snap"),
        ("sports.soccer", False, "wrong_neighborhood"),
        (None, True, "coverage_miss"),
    ],
)
def test_judge_fork_classifies_an_indexed_case(
    cursor: str | None, unindexed: bool, expected: str
) -> None:
    case = {
        "id": "probe",
        "accept": ["food.fermentation"],
        "forbid": ["making.dev"],
        "unindexed_ok": False,
    }
    assert suite.judge_fork(case, cursor, unindexed) == expected


def test_forbid_beats_accept_when_a_prefix_matches_both() -> None:
    """A false snap is the worst outcome, so it is judged first.

    A confidently wrong app misleads more than an honest miss, and a case that
    both accepts and forbids a prefix must resolve to the failure.
    """
    case = {"id": "probe", "accept": ["food"], "forbid": ["food.dining"], "unindexed_ok": False}
    assert suite.judge_fork(case, "food.dining", False) == "false_snap"
    assert suite.judge_fork(case, "food.fermentation", False) == "hit"


def test_unindexed_goal_is_honest_only_when_that_was_expected() -> None:
    unknown = {"id": "probe", "accept": [], "forbid": [], "unindexed_ok": True}
    indexed = {"id": "probe", "accept": ["music"], "forbid": [], "unindexed_ok": False}
    assert suite.judge_fork(unknown, None, True) == "honest_miss"
    assert suite.judge_fork(indexed, None, True) == "coverage_miss"


def test_baseline_pins_every_case() -> None:
    assert suite.DEFAULT_BASELINE.is_file(), (
        "run: domain-foundry eval interest-suite --update-baseline"
    )
    snapshot = json.loads(suite.DEFAULT_BASELINE.read_text(encoding="utf-8"))
    pinned = set(snapshot.get("cases") or {})
    assert pinned == {case["id"] for case in suite.load_cases()}
    assert all(verdict in suite.VERDICT_ORDER for verdict in snapshot["cases"].values())


def test_ratchet_flags_a_regression_and_allows_an_improvement() -> None:
    snapshot = {"cases": {"a": "pass", "b": "fail_loop"}}

    def result(case_id: str, overall: str) -> suite.CaseResult:
        return suite.CaseResult(id=case_id, bucket="indexed", goal="g", overall=overall)

    worse = suite.compare_to_baseline([result("a", "fail_loop")], snapshot)
    assert worse == ["a: pass -> fail_loop"]

    better = suite.compare_to_baseline([result("a", "pass"), result("b", "pass")], snapshot)
    assert better == []


def test_generic_field_set_rejects_the_wizard_default_shape() -> None:
    """The shape every failing pack in the audit compiled to scores zero."""
    generic = {
        "objects": [
            {
                "fields": [
                    {"name": "session_name"},
                    {"name": "noted_at"},
                    {"name": "value"},
                    {"name": "notes"},
                ]
            }
        ]
    }
    ratio, has_domain = suite._score_fields(generic)
    assert ratio == 0.0
    assert has_domain is False

    domain = {
        "objects": [{"fields": [{"name": "hydration"}, {"name": "crumb"}, {"name": "notes"}]}]
    }
    ratio, has_domain = suite._score_fields(domain)
    assert ratio == pytest.approx(2 / 3)
    assert has_domain is True
