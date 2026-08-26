"""End-to-end interest suite: does typing a passion produce an app that works?

Every other eval in this package scores a pack that already exists. This one
scores the act of creation: fork the goal, take the offered idea, build it, then
say one real domain sentence and check it lands. A pack that compiles cleanly and
cannot file its owner's first sentence has not created anything.

The suite runs each case in its own workspace against the heuristic provider, so
it is deterministic and needs no key. Judgement is rule-based for the same
reason: the point is a gate that fails the same way twice, not a second model's
opinion.

Reconstructed 2026-08-23 from the 50-interest audit report after the original
scratch harness was lost with its ``/tmp`` directory. The goals, buckets, and
jargon probes come from that report; ``accept``/``forbid`` encode the report's
own verdicts, so a neighbourhood it judged wrong is forbidden here rather than
blessed.

The protected held-out set
--------------------------

``examples/heldout/interest_suite_heldout.jsonl`` is twenty more cases in this
same schema, authored from real hobbyist phrasing and never from the atlas. The
committed fifty were partly fitted — their ``seed`` sentences were written by
someone who could see the ``jargon`` probes — so the held-out twenty exist to
measure the create path rather than the seed-writing. Run them through the same
runner, which needs no special support because the CLI already takes a path::

    domain-foundry eval interest-suite --cases examples/heldout/interest_suite_heldout.jsonl

The ratchet ignores them: :func:`compare_to_baseline` skips ids the baseline
does not pin, so a held-out run reports without gating. That is deliberate. The
held-out pass rate is a diagnostic (0/20 at authoring), and pinning it would
either be free or block on the exact gap it exists to reveal. The gate is
``scripts/heldout_leakcheck.py``, which fails when held-out vocabulary appears
in ``atlas/*.yaml`` or in the visible suite. A held-out miss is a compiler bug;
widening the atlas to cover one is what that check catches.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_SUITE = REPO_ROOT / "examples" / "heldout" / "interest_suite.jsonl"
DEFAULT_BASELINE = REPO_ROOT / "examples" / "heldout" / "interest_suite_baseline.json"

# Chatter that must never be filed into the freshly built pack. If a suite run
# starts filing this, the router has become credulous rather than capable.
IDLE_PROBE = "nice afternoon, weather was good"

# Verdicts, worst first. A run's overall verdict is the worst thing that happened
# to it, so ordering is the comparison operator for the ratchet.
VERDICT_ORDER = (
    "error",
    "fail_snap",
    "fail_wrong_place",
    "fail_loop",
    "pass_with_gap",
    "pass",
)

# Field names that carry no domain meaning. A pack whose every field is drawn
# from this set has been compiled from the shape of the wizard rather than from
# the shape of the interest.
GENERIC_FIELDS = frozenset(
    {
        "value",
        "notes",
        "note",
        "noted_at",
        "name",
        "title",
        "location",
        "photos",
        "session",
        "session_name",
        "record",
        "record_name",
        "entry",
        "amount",
        "rating",
    }
)


def verdict_rank(verdict: str) -> int:
    try:
        return VERDICT_ORDER.index(verdict)
    except ValueError:
        return 0


def load_cases(path: Path | None = None) -> list[dict[str, Any]]:
    source = path or DEFAULT_SUITE
    cases: list[dict[str, Any]] = []
    for line in source.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            cases.append(json.loads(line))
    return cases


@dataclass
class CaseResult:
    id: str
    bucket: str
    goal: str
    cursor: str | None = None
    unindexed: bool = False
    pack: str | None = None
    fork_verdict: str = "error"
    jargon_ok: bool = False
    idle_ok: bool = False
    overall: str = "error"
    field_specificity: float = 0.0
    has_domain_field: bool = False
    look_model: str | None = None
    look_fallback_reason: str | None = None
    # True when the wizard routed nothing at all for the user's sentence, as
    # opposed to routing it and filing it badly. Distinct failures, distinct fixes.
    jargon_swallowed: bool = False
    # Elicitation (ADR-010): how many sentences the wizard asked for, what the
    # case answered, and where the held-out one landed once the pack existed.
    elicit_prompts: int = 0
    elicited: list[str] = field(default_factory=list)
    held_out: dict[str, Any] | None = None
    routed: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None

    def to_json(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "bucket": self.bucket,
            "goal": self.goal,
            "cursor": self.cursor,
            "unindexed": self.unindexed,
            "pack": self.pack,
            "fork_verdict": self.fork_verdict,
            "jargon_ok": self.jargon_ok,
            "idle_ok": self.idle_ok,
            "overall": self.overall,
            "quality": {
                "field_specificity": round(self.field_specificity, 3),
                "has_domain_field": self.has_domain_field,
                "look_model": self.look_model,
                "look_fallback_reason": self.look_fallback_reason,
                "jargon_swallowed": self.jargon_swallowed,
            },
            "elicit": {
                "prompts": self.elicit_prompts,
                "answered": list(self.elicited),
                "held_out": self.held_out,
            },
            "routed": self.routed,
            "error": self.error,
        }


def judge_fork(case: dict[str, Any], cursor: str | None, unindexed: bool) -> str:
    """Where did the goal land, and was that honest?

    ``forbid`` is checked before ``accept`` because a false snap is the failure
    that most misleads a user: they are handed a confident, wrong app.
    """
    blob = cursor or ""
    for bad in case.get("forbid") or []:
        if blob == bad or blob.startswith(f"{bad}."):
            return "false_snap"
    if unindexed or not blob:
        # Honest only where the atlas genuinely has no home for the goal.
        return "honest_miss" if case.get("unindexed_ok") else "coverage_miss"
    for good in case.get("accept") or []:
        if blob == good or blob.startswith(f"{good}."):
            return "hit"
    return "wrong_neighborhood"


def _score_fields(schema: dict[str, Any] | None) -> tuple[float, bool]:
    """How much of the built pack is about the interest rather than about logging?"""
    if not schema:
        return 0.0, False
    names: list[str] = []
    objects = schema.get("objects")
    if isinstance(objects, list):
        for obj in objects:
            for fld in obj.get("fields", []) or []:
                name = str(fld.get("name") or "").strip().lower()
                if name:
                    names.append(name)
    if not names:
        return 0.0, False
    specific = [n for n in names if n not in GENERIC_FIELDS]
    return len(specific) / len(names), bool(specific)


def _filed_into(routed: list[dict[str, Any]], pack: str | None) -> bool:
    if not pack or not routed:
        return False
    for span in routed:
        if str(span.get("domain")) != pack:
            continue
        if str(span.get("disposition")) in {"unfiled", "ledger_only"}:
            continue
        return True
    return False


def run_case(case: dict[str, Any]) -> CaseResult:
    """Drive one goal through fork, looks, build, a real sentence, and chatter."""
    from domain_foundry_core.api.harness import HarnessAPI
    from domain_foundry_core.atlas.query import query_neighborhood
    from domain_foundry_core.paths import Workspace

    result = CaseResult(id=case["id"], bucket=case["bucket"], goal=case["goal"])
    previous_home = os.environ.get("DOMAIN_FOUNDRY_HOME")
    home = Path(tempfile.mkdtemp(prefix=f"interest_{case['id']}_"))
    try:
        os.environ["DOMAIN_FOUNDRY_HOME"] = str(home)
        Workspace(home).ensure_layout()
        api = HarnessAPI(home)
        api.init()

        probe = query_neighborhood(case["goal"])
        result.cursor = probe.get("cursor")
        result.unindexed = bool(probe.get("unindexed"))
        result.fork_verdict = judge_fork(case, result.cursor, result.unindexed)

        # Exercise the shipped release journey.  ``new_domain`` remains the
        # compatibility contract for adapters, but the universal promise is
        # made by ``create_domain`` and its plain-language renderer.
        turn = api.create_domain(case["goal"])
        sid = str(turn.get("session_id") or "")
        if not sid:
            raise RuntimeError("wizard returned no session id")
        if turn.get("state") == "fork":
            turn = api.wizard_reply(sid, "1")
        if turn.get("state") == "fork":
            # Some neighbourhoods answer a bare ordinal with a refinement rather
            # than a commitment; accepting the suggestion is the same user intent.
            turn = api.wizard_reply(sid, "yes")
        for look in turn.get("looks") or []:
            result.look_model = look.get("model")
            result.look_fallback_reason = look.get("fallback_reason")
        if turn.get("state") == "looks":
            turn = api.wizard_reply(sid, "build it")

        # Elicitation (ADR-010). An unindexed goal is asked for two sentences in
        # the user's own words before anything is designed. A case answers with
        # its ``seed``/``seed2``; a case with no seed says "skip", which is the
        # honest fallback and must keep working. ``seed2`` is the wizard's own
        # held-out check and is deliberately *not* the suite's ``jargon`` probe:
        # the yardstick has to stay outside everything the create loop touches.
        answers = [str(case.get(key) or "").strip() for key in ("seed", "seed2")]
        for _guard in range(4):
            if turn.get("state") != "elicit":
                break
            index = int((turn.get("elicit") or {}).get("index") or 1)
            result.elicit_prompts = max(result.elicit_prompts, index)
            reply = answers[index - 1] if index <= len(answers) else ""
            if reply:
                result.elicited.append(reply)
            turn = api.wizard_reply(sid, reply or "skip")
        result.held_out = turn.get("held_out")

        result.pack = turn.get("pack_name") or turn.get("domain")
        result.field_specificity, result.has_domain_field = _score_fields(turn.get("schema"))

        # Whatever the wizard does with the sentence is the verdict. Re-capturing
        # outside the session would file it and hide the real failure: some goals
        # (knitting, books) make the wizard read a domain sentence as "I'm done",
        # answer "Happy tracking!", and route nothing at all. The user typed their
        # first real note and watched it vanish, which is worse than an unfiled card.
        jargon_turn = api.wizard_reply(sid, case["jargon"])
        capture = jargon_turn.get("capture") or {}
        result.routed = list(capture.get("routed") or [])
        result.jargon_swallowed = not result.routed
        result.jargon_ok = _filed_into(result.routed, result.pack)

        idle = api.capture(IDLE_PROBE)
        idle_routed = [span.model_dump() for span in idle.routed]
        result.idle_ok = not _filed_into(idle_routed, result.pack)

        result.overall = _overall(result)
    except Exception as exc:  # noqa: BLE001 - a crashed case is a suite result
        result.error = f"{type(exc).__name__}: {exc}"
        result.overall = "error"
    finally:
        if previous_home is None:
            os.environ.pop("DOMAIN_FOUNDRY_HOME", None)
        else:
            os.environ["DOMAIN_FOUNDRY_HOME"] = previous_home
    return result


def _overall(result: CaseResult) -> str:
    if result.fork_verdict == "false_snap":
        return "fail_snap"
    if result.fork_verdict in {"wrong_neighborhood", "coverage_miss"}:
        return "fail_wrong_place"
    if not result.pack:
        return "fail_loop"
    if not result.jargon_ok:
        return "fail_loop"
    if not result.idle_ok:
        return "pass_with_gap"
    return "pass"


def run_suite(cases: list[dict[str, Any]]) -> list[CaseResult]:
    return [run_case(case) for case in cases]


def summarise(results: list[CaseResult]) -> dict[str, Any]:
    overall: dict[str, int] = {}
    fork: dict[str, int] = {}
    buckets: dict[str, dict[str, int]] = {}
    for item in results:
        overall[item.overall] = overall.get(item.overall, 0) + 1
        fork[item.fork_verdict] = fork.get(item.fork_verdict, 0) + 1
        slot = buckets.setdefault(item.bucket, {})
        slot[item.overall] = slot.get(item.overall, 0) + 1
    # The unbiased companion to `pass`. The `jargon` probe is a sentence a human
    # wrote knowing the hobby; a seed authored later, with that probe visible, can
    # share a word with it and carry the case on that one word. The held-out
    # sentence is the wizard's own second utterance, replayed after activation and
    # never seen by the design, so it measures whether the pack understands the
    # domain rather than whether two sentences happen to overlap.
    #
    # Offline this sits at zero and should: no keyword scaffold learns a hobby from
    # one sentence. It is the number research-backed generation has to move, and
    # reporting it beside `pass` keeps `pass` from being read as more than it is.
    replayed = [item for item in results if item.held_out]
    held_out_filed = [item for item in replayed if (item.held_out or {}).get("filed")]
    return {
        "n": len(results),
        "pass": overall.get("pass", 0),
        "overall": overall,
        "fork": fork,
        "buckets": buckets,
        "held_out": {
            "replayed": len(replayed),
            "filed": len(held_out_filed),
            "filed_ids": sorted(item.id for item in held_out_filed),
        },
        "failing_ids": sorted(r.id for r in results if r.overall not in {"pass", "pass_with_gap"}),
    }


def compare_to_baseline(results: list[CaseResult], baseline: dict[str, Any]) -> list[str]:
    """Per-case ratchet: no case may end up worse than it was pinned at.

    Aggregate counts hide trades, where a fix for one goal quietly breaks
    another. Comparing case by case makes that visible and blocks it.
    """
    pinned: dict[str, str] = dict(baseline.get("cases") or {})
    regressions: list[str] = []
    for item in results:
        was = pinned.get(item.id)
        if was is None:
            continue
        if verdict_rank(item.overall) < verdict_rank(was):
            regressions.append(f"{item.id}: {was} -> {item.overall}")
    return regressions


def build_baseline(results: list[CaseResult]) -> dict[str, Any]:
    summary = summarise(results)
    return {
        "n": summary["n"],
        "pass": summary["pass"],
        "overall": summary["overall"],
        "fork": summary["fork"],
        "buckets": summary["buckets"],
        "cases": {item.id: item.overall for item in sorted(results, key=lambda r: r.id)},
    }
