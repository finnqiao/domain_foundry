#!/usr/bin/env python3
"""Guard the protected held-out interest set against being tuned into.

``examples/heldout/interest_suite.jsonl`` is a yardstick that was partly bent
into shape: its ``seed`` sentences were authored by someone who could see the
``jargon`` probes, and several newly passing cases hang on a single shared
content word. That is not fraud — it is how the mechanism genuinely works — but
it means the visible suite can be improved by writing better seeds instead of a
better compiler.

``examples/heldout/interest_suite_heldout.jsonl`` exists to close that loop. It
is authored from real hobbyist phrasing, never from the atlas, and nothing in
it may be fed back into the things it measures. This script is the mechanical
half of that promise: it fails when a held-out case's distinctive vocabulary has
appeared in ``atlas/*.yaml`` or in the visible suite.

Four classes of finding, all of them exit-non-zero:

``atlas_leak``
    A held-out probe word turned up in an atlas node's routing surface
    (``aliases``, ``jargon``, ``vocabulary``, ``routing_examples``, ``title``,
    ``example``). Somebody made a held-out case pass by teaching the atlas its
    answer. The fix is the compiler, not the atlas.

``suite_leak``
    A held-out probe word turned up in the visible suite. The two sets stop
    being independent the moment they share vocabulary.

``seed_overlap``
    Inside one held-out case, a ``seed`` shares a content word with the
    ``jargon`` probe. That single shared word is exactly the contamination this
    set exists to detect, so the held-out file may not reproduce it.

``goal_indexed``
    A held-out *goal* word newly appeared in the atlas. Goals are routing keys
    and legitimately overlap the atlas — that is what "indexed" and "collision"
    mean — so this one is a ratchet against ``KNOWN_GOAL_ECHOES`` rather than a
    ban, and it fires only on echoes that were not there at authoring time.

Deliberately *not* checked: ``negative_examples``. Text there teaches the
compiler to *reject* a routing, so a held-out word appearing in it cannot make a
held-out case pass. ``pitch`` is display copy and does not reach the router.

Usage::

    python scripts/heldout_leakcheck.py
    python scripts/heldout_leakcheck.py --json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ATLAS = ROOT / "atlas"
DEFAULT_HELDOUT = ROOT / "examples" / "heldout" / "interest_suite_heldout.jsonl"
DEFAULT_SUITE = ROOT / "examples" / "heldout" / "interest_suite.jsonl"

# A token has to be this long before it can carry hobby meaning. Shorter words
# ("v60", "rim", "nib", "F2", "pH") are either units or too common to attribute.
MIN_TOKEN_LEN = 5

# The atlas fields a leak could actually travel through: everything an author
# would edit to make a goal land somewhere or a sentence file.
ATLAS_TEXT_FIELDS = ("title", "example")
ATLAS_LIST_FIELDS = ("aliases", "jargon", "vocabulary")

# The case fields that carry the yardstick. ``goal`` is handled separately
# because a goal is a routing key: an *indexed* case is one the atlas is
# supposed to recognise, so a goal word appearing in the atlas is the design
# working, not a leak.
PROBE_FIELDS = ("jargon", "seed", "seed2")

# Common English with no hobby content. Filtered before anything is attributed,
# so a probe may be written in ordinary sentences without tripping the check.
STOPWORDS = frozenset(
    {
        "about", "above", "after", "again", "against", "along", "already", "although",
        "always", "among", "another", "anything", "around", "because", "before",
        "behind", "being", "below", "besides", "better", "between", "bring", "brought",
        "cannot", "certain", "could", "couple", "doing", "during", "either", "enough",
        "ever", "every", "everything", "except", "finally", "further", "getting",
        "going", "great", "having", "instead", "into", "itself", "least", "leave",
        "little", "maybe", "might", "mostly", "much", "myself", "nearly", "needs",
        "never", "nothing", "often", "only", "other", "ought", "outside", "over",
        "perhaps", "probably", "quite", "rather", "really", "same", "several",
        "should", "since", "slightly", "small", "some", "someone", "something",
        "still", "such", "than", "that", "their", "them", "then", "there", "these",
        "they", "thing", "things", "think", "this", "those", "though", "through",
        "took", "toward", "under", "until", "very", "want", "wants", "were", "what",
        "when", "where", "which", "while", "will", "with", "within", "without",
        "would", "yourself",
    }
)

# Legitimately shared terms: words every logging hobby writes, which therefore
# say nothing about whether a held-out case was tuned for.
#
# Every entry needs a reason, and the reason has to be "this word is generic
# across hobbies", never "this word made the check fail". Adding a hobby-bearing
# word here defeats the whole file: it is the same act as adding it to the atlas.
GENERIC_HOBBY_WORDS: dict[str, str] = {
    # Media and record-keeping nouns. Every hobby attaches a photo and a note.
    "photo": "every hobby attaches a photo; the atlas mentions photos on many nodes",
    "photos": "plural of the above",
    "notes": "the universal free-text field; also a GENERIC_FIELDS entry in the eval",
    "session": "the generic unit of a logged activity, not a hobby word",
    "sessions": "plural of the above",
    # Time. Shared by every log, carries no domain meaning.
    "today": "time-of-day word",
    "tonight": "time-of-day word",
    "morning": "time-of-day word",
    "evening": "time-of-day word",
    "yesterday": "time word",
    "weekend": "time word",
    "minute": "duration word",
    "minutes": "duration word",
    "hours": "duration word",
    "weeks": "duration word",
    "month": "duration word",
    "months": "duration word",
    # Generic log verbs and ordinals: what you did, not what you did it to.
    "added": "generic log verb",
    "tried": "generic log verb",
    "started": "generic log verb",
    "finished": "generic log verb",
    "first": "ordinal",
    "second": "ordinal (also a unit of time)",
    "third": "ordinal",
}

# Goal words that already echoed somewhere in the atlas when this held-out set
# was authored, keyed ``case:token:node``.
#
# A goal is a routing key, not a probe. An *indexed* held-out case is one the
# atlas is supposed to recognise, and a *collision* case only collides because
# its goal shares a word with the wrong neighbourhood — "calligraphy practice"
# against ``music.practice`` is the test, not a leak. Flagging those would drown
# the signal, so the goal check is a ratchet instead of a ban: everything true on
# the day the set was written is recorded here, and any *new* atlas echo of a
# held-out goal fails. Adding a node because a held-out goal missed is precisely
# the move this file exists to catch, and it produces a new entry every time.
#
# Probe fields (``jargon``/``seed``/``seed2``) get no such allowance. They are
# the yardstick, and a yardstick that has been shown to the compiler is over.
KNOWN_GOAL_ECHOES: dict[str, str] = {
    # h04: "board games" against climbing's project board and soccer's pickup
    # games. Both are the collision the case is built on.
    "h04_boardgames:board:sports.climbing.project_board": "climbing 'project board', not games",
    "h04_boardgames:games:sports.soccer.pickup_map": "'pickup games' — the wrong-sport collision",
    # h05/h13: craft words that the atlas happens to use in unrelated senses.
    "h05_quilting:projects:sports.climbing.project_board": "climbing projects, unrelated sense",
    "h13_embroidery:finish:food.drinks.tasting_notes": "whisky 'finish', unrelated sense",
    # h14: bike maintenance genuinely straddles sports.cycling and home.maintenance.
    "h14_bikemaint:maintenance:home": "the home-vs-cycling collision the case tests",
    "h14_bikemaint:maintenance:home.maintenance": "same collision, the node itself",
    # h16: "calligraphy practice" against instrument practice — the whole case.
    "h16_calligraphy:practice:music.practice": "the music collision the case tests",
    "h16_calligraphy:practice:music.practice.session": "same collision, child node",
    # h18: "collection" is the generic collecting verb; it also names a plant node.
    "h18_watches:collection:plants.houseplants.collection": "plant collection, unrelated sense",
    "h18_watches:collection:music.records": "record collection, unrelated sense",
    # h20: "dog training sessions" against sports training — the case's collision.
    "h20_dogtraining:training:sports": "the sports collision the case tests",
    "h20_dogtraining:training:sports.soccer.training_log": "same collision, child node",
    # Genuinely indexed goals. The atlas is *supposed* to know these three, and
    # knew them before this set was written; that is what bucket `indexed` claims.
    "h11_kombucha:kombucha:food.fermentation": "already a fermentation alias at authoring time",
    "h12_bigyear:birding:animals": "already an animals alias at authoring time",
    "h12_bigyear:birding:animals.wildlife": "same, on the practice node",
    "h12_bigyear:birding:animals.wildlife.dex": "same, on the idea node",
    "h18_watches:collection:collecting": "already a collecting alias at authoring time",
    "h18_watches:collection:collecting.catalog.dex": "'Collection dex' — the node's own title",
}

_WORD = re.compile(r"[a-z]+")


def distinctive_tokens(text: str) -> set[str]:
    """The words in ``text`` that could carry hobby meaning."""
    out: set[str] = set()
    for word in _WORD.findall(text.lower()):
        if len(word) < MIN_TOKEN_LEN:
            continue
        if word in STOPWORDS or word in GENERIC_HOBBY_WORDS:
            continue
        out.add(word)
    return out


class Finding(dict[str, Any]):
    """A leak, as a plain dict so ``--json`` is the same object the human sees."""


def _finding(kind: str, case: str, token: str, where: str, detail: str) -> Finding:
    return Finding(kind=kind, case=case, token=token, where=where, detail=detail)


def load_cases(path: Path) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            cases.append(json.loads(line))
    return cases


def index_atlas(atlas_dir: Path) -> dict[str, list[tuple[str, str, str]]]:
    """token -> [(file, node id, field)] over the atlas' routing surface."""
    index: dict[str, list[tuple[str, str, str]]] = {}

    def add(token: str, source: tuple[str, str, str]) -> None:
        index.setdefault(token, []).append(source)

    for path in sorted(atlas_dir.glob("*.yaml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        rel = f"atlas/{path.name}"
        for node in data.get("nodes") or []:
            node_id = str(node.get("id") or "?")
            for field in ATLAS_TEXT_FIELDS:
                for token in distinctive_tokens(str(node.get(field) or "")):
                    add(token, (rel, node_id, field))
            for field in ATLAS_LIST_FIELDS:
                for value in node.get(field) or []:
                    for token in distinctive_tokens(str(value)):
                        add(token, (rel, node_id, field))
            for example in node.get("routing_examples") or []:
                text = example.get("text") if isinstance(example, dict) else example
                for token in distinctive_tokens(str(text or "")):
                    add(token, (rel, node_id, "routing_examples"))
    return index


def index_suite(suite_path: Path) -> dict[str, list[tuple[str, str, str]]]:
    """token -> [(file, case id, field)] over the visible suite's own text."""
    index: dict[str, list[tuple[str, str, str]]] = {}
    rel = str(suite_path.relative_to(ROOT)) if suite_path.is_relative_to(ROOT) else str(suite_path)
    for case in load_cases(suite_path):
        case_id = str(case.get("id") or "?")
        for field in ("goal", *PROBE_FIELDS):
            for token in distinctive_tokens(str(case.get(field) or "")):
                index.setdefault(token, []).append((rel, case_id, field))
    return index


def check(
    heldout_path: Path = DEFAULT_HELDOUT,
    atlas_dir: Path = DEFAULT_ATLAS,
    suite_path: Path = DEFAULT_SUITE,
) -> list[Finding]:
    """Every way this held-out set could have stopped being held out."""
    cases = load_cases(heldout_path)
    atlas = index_atlas(atlas_dir)
    suite = index_suite(suite_path)
    findings: list[Finding] = []

    for case in cases:
        case_id = str(case.get("id") or "?")
        probes = {field: distinctive_tokens(str(case.get(field) or "")) for field in PROBE_FIELDS}

        # The probe fields: the yardstick. No allowance, anywhere.
        for field, tokens in sorted(probes.items()):
            for token in sorted(tokens):
                for rel, node_id, node_field in atlas.get(token, []):
                    findings.append(
                        _finding(
                            "atlas_leak",
                            case_id,
                            token,
                            f"{rel}:{node_id}.{node_field}",
                            f"{case_id}.{field} word {token!r} is in the atlas "
                            f"at {node_id}.{node_field} ({rel})",
                        )
                    )
                for rel, other_id, other_field in suite.get(token, []):
                    findings.append(
                        _finding(
                            "suite_leak",
                            case_id,
                            token,
                            f"{rel}:{other_id}.{other_field}",
                            f"{case_id}.{field} word {token!r} also appears in the "
                            f"visible suite at {other_id}.{other_field} ({rel})",
                        )
                    )

        # The goal: a ratchet, because deliberate collisions live here.
        for token in sorted(distinctive_tokens(str(case.get("goal") or ""))):
            for rel, node_id, node_field in atlas.get(token, []):
                if f"{case_id}:{token}:{node_id}" in KNOWN_GOAL_ECHOES:
                    continue
                findings.append(
                    _finding(
                        "goal_indexed",
                        case_id,
                        token,
                        f"{rel}:{node_id}.{node_field}",
                        f"{case_id}.goal word {token!r} newly appears in the atlas at "
                        f"{node_id}.{node_field} ({rel}) — was the atlas widened to "
                        f"cover a held-out goal?",
                    )
                )

        # The authoring rule, enforced rather than trusted: a seed the design
        # sees may not hand the design a word from the probe that scores it.
        # ``seed2`` is included because it is the wizard's own held-out check —
        # if it echoes ``jargon`` then ``held_out`` measures the same word
        # overlap that ``pass`` already does, and stops being the honest number.
        jargon_tokens = probes["jargon"]
        for field in ("seed", "seed2"):
            for token in sorted(probes[field] & jargon_tokens):
                findings.append(
                    _finding(
                        "seed_overlap",
                        case_id,
                        token,
                        f"{case_id}.{field}",
                        f"{case_id}.{field} shares the word {token!r} with its own "
                        f"jargon probe; write a genuinely different sentence",
                    )
                )

    return findings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--cases", type=Path, default=DEFAULT_HELDOUT, help="held-out JSONL")
    parser.add_argument("--atlas", type=Path, default=DEFAULT_ATLAS, help="atlas directory")
    parser.add_argument("--suite", type=Path, default=DEFAULT_SUITE, help="visible suite JSONL")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    args = parser.parse_args(argv)

    findings = check(args.cases, args.atlas, args.suite)

    if args.json:
        print(
            json.dumps(
                {
                    "ok": not findings,
                    "cases": len(load_cases(args.cases)),
                    "findings": [dict(f) for f in findings],
                },
                indent=2,
            )
        )
    elif findings:
        print(f"held-out leak check FAILED: {len(findings)} finding(s)", file=sys.stderr)
        for item in findings:
            print(f"  [{item['kind']}] {item['detail']}", file=sys.stderr)
        print(
            "\nA held-out miss is a compiler bug, not an atlas gap. Widening the "
            "atlas to cover one of these is the behaviour this check exists to catch.",
            file=sys.stderr,
        )
    else:
        print(f"held-out leak check ok: {len(load_cases(args.cases))} cases, no leaks")

    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
