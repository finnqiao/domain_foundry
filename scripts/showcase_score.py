#!/usr/bin/env python3
"""Score a generated FoundrySpec against its hand-authored showcase target.

Release proof #1 asks whether the pipeline can produce a showcase-caliber spec
on its own. That question needs a number, not an opinion, so this scores a
generated spec against the target sitting next to it on five axes.

    python scripts/showcase_score.py --interest whisky-tasting
    python scripts/showcase_score.py --all
    python scripts/showcase_score.py --generated path/spec.json --target path/spec.yaml

Axes and thresholds (change these here, and say why in the commit):

  entity_coverage    0.70  Target entities that the generated spec also models,
                           matched by id or by name. An entity the generated
                           spec drops is only forgiven if a derivation names it.
  workload_naming    0.85  Generated workloads that trace back to the brief: a
                           real question, evidence behind it, and at least one
                           view that uses it.
  region_variety     1.00  Pass or fail. More than one region kind across the
                           views, and at least two views, so the app is not one
                           list in a frame.
  evidence_discipline 1.00 Pass or fail. Every citation names a declared source
                           and how it is used, every derivation is justified,
                           and the generation receipt carries an evidence tier.
  reference_closure  1.00  Pass or fail. Sources and principles all resolve.
                           The loader enforces this; scoring it keeps the row
                           visible on the scorecard.

A run is green when every axis is at or above its threshold.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
SHOWCASE_ROOT = REPO_ROOT / "examples" / "showcase"

if str(REPO_ROOT / "core") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "core"))

THRESHOLDS: dict[str, float] = {
    "entity_coverage": 0.70,
    "workload_naming": 0.85,
    "region_variety": 1.0,
    "evidence_discipline": 1.0,
    "reference_closure": 1.0,
}


@dataclass
class AxisScore:
    name: str
    score: float
    threshold: float
    detail: str
    notes: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return self.score >= self.threshold

    def as_dict(self) -> dict[str, Any]:
        return {
            "axis": self.name,
            "score": round(self.score, 3),
            "threshold": self.threshold,
            "passed": self.passed,
            "detail": self.detail,
            "notes": self.notes,
        }


@dataclass
class Scorecard:
    interest: str
    axes: list[AxisScore]

    @property
    def passed(self) -> bool:
        return all(axis.passed for axis in self.axes)

    def as_dict(self) -> dict[str, Any]:
        return {
            "interest": self.interest,
            "passed": self.passed,
            "axes": [axis.as_dict() for axis in self.axes],
        }

    def render(self) -> str:
        lines = [f"{self.interest}: {'pass' if self.passed else 'fail'}"]
        for axis in self.axes:
            mark = "ok  " if axis.passed else "FAIL"
            lines.append(
                f"  {mark} {axis.name:<20} {axis.score:.2f} (needs {axis.threshold:.2f})  "
                f"{axis.detail}"
            )
            lines.extend(f"       {note}" for note in axis.notes)
        return "\n".join(lines)


def _norm(value: str) -> str:
    return "".join(ch for ch in value.lower() if ch.isalnum())


def score_entity_coverage(generated: Any, target: Any) -> AxisScore:
    made = {_norm(item.id) for item in generated.domain.entities}
    made |= {_norm(item.title) for item in generated.domain.entities}
    justified = " ".join(
        [item.decision for item in generated.derivations]
        + [item.user_decision or "" for item in generated.derivations]
    ).lower()

    wanted = [(item.id, item.title) for item in target.domain.entities]
    hits = 0
    missing: list[str] = []
    for entity_id, name in wanted:
        if _norm(entity_id) in made or _norm(name) in made:
            hits += 1
        elif entity_id.replace("_", " ").lower() in justified or name.lower() in justified:
            hits += 1
        else:
            missing.append(entity_id)
    score = hits / len(wanted) if wanted else 0.0
    notes = [f"not modelled and not explained: {', '.join(sorted(missing))}"] if missing else []
    return AxisScore(
        "entity_coverage",
        score,
        THRESHOLDS["entity_coverage"],
        f"{hits} of {len(wanted)} target entities",
        notes,
    )


def score_workload_naming(generated: Any, _target: Any) -> AxisScore:
    workloads = generated.domain.workloads
    used = {workload_id for view in generated.experience.views for workload_id in view.workload_ids}
    good = 0
    notes: list[str] = []
    for workload in workloads:
        problems = []
        if not workload.question.strip().endswith("?"):
            problems.append("the question is not a question")
        if not workload.evidence_ids:
            problems.append("no evidence behind it")
        if workload.id not in used:
            problems.append("no view uses it")
        if problems:
            notes.append(f"{workload.id}: {'; '.join(problems)}")
        else:
            good += 1
    score = good / len(workloads) if workloads else 0.0
    return AxisScore(
        "workload_naming",
        score,
        THRESHOLDS["workload_naming"],
        f"{good} of {len(workloads)} workloads trace to the brief",
        notes,
    )


def score_region_variety(generated: Any, _target: Any) -> AxisScore:
    kinds = {region.kind for view in generated.experience.views for region in view.regions}
    views = len(generated.experience.views)
    ok = len(kinds) > 1 and views >= 2
    notes = []
    if not ok:
        notes.append(
            f"only {len(kinds)} region kind(s) across {views} view(s); "
            "an app with one kind of region in one view is the generic shape"
        )
    return AxisScore(
        "region_variety",
        1.0 if ok else 0.0,
        THRESHOLDS["region_variety"],
        f"{len(kinds)} region kinds across {views} views",
        notes,
    )


def score_evidence_discipline(generated: Any, _target: Any) -> AxisScore:
    notes: list[str] = []
    declared = set(generated.source_ids)
    for citation in generated.evidence:
        if citation.source_id not in declared:
            notes.append(f"{citation.id} cites a source the spec does not declare")
        if not citation.claim.strip():
            notes.append(f"{citation.id} has no claim")
    for derivation in generated.derivations:
        if not derivation.evidence_ids and not derivation.user_decision:
            notes.append(f"{derivation.output_path} is justified by nothing")
    if generated.evidence_tier is None:
        notes.append(
            "the generation receipt carries no evidence tier, so a reader cannot "
            "tell researched claims from model knowledge"
        )
    return AxisScore(
        "evidence_discipline",
        1.0 if not notes else 0.0,
        THRESHOLDS["evidence_discipline"],
        f"{len(generated.evidence)} citations, tier {generated.evidence_tier or 'unstamped'}",
        notes,
    )


def score_reference_closure(generated: Any, _target: Any) -> AxisScore:
    from domain_foundry_core.foundry.loader import knowledge_ids

    known_sources, known_principles = knowledge_ids()
    known_sources |= {item.id for item in generated.source_snapshots}
    missing_sources = sorted(set(generated.source_ids) - known_sources)
    missing_principles = sorted(set(generated.principle_ids) - known_principles)
    notes = []
    if missing_sources:
        notes.append(f"sources that do not resolve: {', '.join(missing_sources)}")
    if missing_principles:
        notes.append(f"principles that do not resolve: {', '.join(missing_principles)}")
    return AxisScore(
        "reference_closure",
        1.0 if not notes else 0.0,
        THRESHOLDS["reference_closure"],
        f"{len(generated.source_ids)} sources, {len(generated.principle_ids)} principles",
        notes,
    )


SCORERS = (
    score_entity_coverage,
    score_workload_naming,
    score_region_variety,
    score_evidence_discipline,
    score_reference_closure,
)


def score(generated: Any, target: Any, *, interest: str) -> Scorecard:
    return Scorecard(interest=interest, axes=[fn(generated, target) for fn in SCORERS])


def load_spec(path: Path) -> Any:
    from domain_foundry_core.foundry.loader import load_foundry_spec
    from domain_foundry_core.foundry.models import FoundrySpec

    if path.suffix == ".json":
        return FoundrySpec.model_validate(json.loads(path.read_text(encoding="utf-8")))
    return load_foundry_spec(path)


def generated_spec_path(interest: str, root: Path = SHOWCASE_ROOT) -> Path:
    return root / interest / "generated" / "foundry-spec.json"


def target_spec_path(interest: str, root: Path = SHOWCASE_ROOT) -> Path:
    return root / interest / "spec.yaml"


def discover(root: Path = SHOWCASE_ROOT) -> list[str]:
    if not root.is_dir():
        return []
    return sorted(
        entry.name for entry in root.iterdir() if entry.is_dir() and (entry / "spec.yaml").is_file()
    )


def score_interest(interest: str, root: Path = SHOWCASE_ROOT) -> Scorecard:
    generated = generated_spec_path(interest, root)
    if not generated.is_file():
        raise FileNotFoundError(
            f"{interest}: there is no generated spec to score at {generated}.\n"
            "Run `python scripts/build_showcase.py --interest "
            f"{interest}` first. That needs either a recorded cassette under "
            "tests/e2e-foundry/cassettes/showcase or a configured reasoning "
            "model with DOMAIN_FOUNDRY_LIVE_GATE=1."
        )
    return score(
        load_spec(generated), load_spec(target_spec_path(interest, root)), interest=interest
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Score generated showcase specs")
    parser.add_argument("--interest", help="One showcase directory name")
    parser.add_argument("--all", action="store_true", help="Score every showcase")
    parser.add_argument("--generated", type=Path, help="Explicit generated spec path")
    parser.add_argument("--target", type=Path, help="Explicit target spec path")
    parser.add_argument("--json", action="store_true", help="Print JSON instead of a scorecard")
    parser.add_argument("--root", type=Path, default=SHOWCASE_ROOT)
    args = parser.parse_args(argv)

    cards: list[Scorecard] = []
    if args.generated and args.target:
        cards.append(
            score(
                load_spec(args.generated),
                load_spec(args.target),
                interest=args.generated.parent.name,
            )
        )
    else:
        names = [args.interest] if args.interest else discover(args.root) if args.all else []
        if not names:
            parser.error("pass --interest <name>, --all, or --generated with --target")
            return 2
        for name in names:
            try:
                cards.append(score_interest(name, args.root))
            except FileNotFoundError as error:
                print(str(error), file=sys.stderr)
                return 1

    if args.json:
        print(json.dumps({"scorecards": [card.as_dict() for card in cards]}, indent=2))
    else:
        for card in cards:
            print(card.render())

    return 0 if all(card.passed for card in cards) else 1


if __name__ == "__main__":
    raise SystemExit(main())
