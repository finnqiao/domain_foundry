#!/usr/bin/env python3
"""Run the real Foundry pipeline for the showcase interests, then score it.

`examples/showcase/*/spec.yaml` are hand-authored targets: what the pipeline
*should* produce for five interests. This asks the pipeline to produce them for
real, writes the result beside the target, scores the two against each other
with `scripts/showcase_score.py`, and exits non-zero when a score is under
threshold. That scored run is release proof #1.

    python scripts/build_showcase.py --list
    python scripts/build_showcase.py --interest whisky-tasting
    python scripts/build_showcase.py --all --gate

Two ways to run, and only two:

  replay (the default, and what CI uses)
      Every model call is served from a recorded cassette under
      `tests/e2e-foundry/cassettes/showcase/<interest>`. Deterministic. A call
      with no cassette is a named failure, never a skip and never a fallback to
      the offline keyword scaffold.

  live (`DOMAIN_FOUNDRY_LIVE_GATE=1`, or `--live`)
      Calls the configured reasoning model and records the cassettes. Run by a
      person before a release; commit the cassettes as evidence.

There is no third mode. A keyword scaffold labelled as research would defeat the
point of the artifact.

Regeneration is deliberate: commit the result as a reviewed diff, never as an
automatic refresh.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
SHOWCASE_ROOT = REPO_ROOT / "examples" / "showcase"
CASSETTE_ROOT = REPO_ROOT / "tests" / "e2e-foundry" / "cassettes" / "showcase"

if str(REPO_ROOT / "core") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "core"))
if str(REPO_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "scripts"))

LIVE_ENV = "DOMAIN_FOUNDRY_LIVE_GATE"


def discover() -> list[str]:
    if not SHOWCASE_ROOT.is_dir():
        return []
    return sorted(
        entry.name
        for entry in SHOWCASE_ROOT.iterdir()
        if entry.is_dir() and (entry / "spec.yaml").is_file()
    )


def live_requested(flag: bool = False) -> bool:
    return bool(flag) or os.environ.get(LIVE_ENV, "").strip().lower() in {"1", "true", "on", "yes"}


class MissingCassette(RuntimeError):
    """Replay hit a prompt nobody recorded."""


def _no_live_calls_provider(interest: str) -> Any:
    """The inner provider for replay: every miss is a loud, named failure."""
    from domain_foundry_core.llm.provider import CompletionResult, LLMProvider

    class _Refuse(LLMProvider):
        name = "replay-only"

        def complete_json(
            self,
            *,
            system: str,
            user: str,
            schema: dict[str, Any] | None = None,
            model: str | None = None,
            tier: str | None = None,
        ) -> CompletionResult:
            raise MissingCassette(
                f"{interest}: this run needs a model answer that is not recorded.\n"
                f"Missing: a cassette under {CASSETTE_ROOT / interest}.\n"
                "To record it, set a reasoning model with `domain-foundry setup`, "
                f"then run: {LIVE_ENV}=1 python scripts/build_showcase.py "
                f"--interest {interest}\n"
                "Nothing here falls back to the offline keyword scaffold, because "
                "that would put an unresearched spec under a generated label."
            )

    return _Refuse()


def missing_cassette_message(error: BaseException) -> str | None:
    """Dig a replay miss out of whatever the pipeline wrapped it in."""
    seen: BaseException | None = error
    while seen is not None:
        if isinstance(seen, MissingCassette):
            return str(seen)
        seen = seen.__cause__ or seen.__context__
    # The pipeline turns a stage exception into a PipelineError carrying the
    # text, so match on the text as well as the type.
    text = str(error)
    return text if "is not recorded" in text else None


def build_provider(interest: str, *, live: bool, home: Path) -> Any:
    """Cassette replay by default; the live model when a person asks for it."""
    from domain_foundry_core.llm.provider import CassetteProvider, build_tiered_provider

    store = CASSETTE_ROOT / interest
    if not live:
        store.mkdir(parents=True, exist_ok=True)
        return CassetteProvider(_no_live_calls_provider(interest), store, mode="replay")

    tiered = build_tiered_provider(home)
    if not tiered.has_live_keys():
        raise SystemExit(
            f"{LIVE_ENV} is set, but no reasoning model is configured.\n"
            "Run `domain-foundry setup` and give it a model and a key, then run this again."
        )
    store.mkdir(parents=True, exist_ok=True)
    return CassetteProvider(tiered, store, mode="live")


def _acceptance_tasks(spec: Any) -> list[Any]:
    """Reuse the target spec's user-authored cases as the generated run's judge.

    The pipeline refuses to author its own acceptance criteria, and rightly so.
    The showcase targets already carry cases marked `authored_by: user`, which is
    exactly the independent evidence the pipeline asks for.
    """
    from domain_foundry_core.foundry.pipeline import AcceptanceTask

    tasks: list[AcceptanceTask] = []
    for case in spec.evaluation.cases:
        if case.authored_by != "user":
            continue
        tasks.append(AcceptanceTask(input=case.input, expected=case.expected))
    return tasks


def _remix_from(proposal: Any, target: Any) -> Any:
    """Pick a concept the way a person would, and say so on the record.

    A generated run still needs a human decision recorded, so the target spec's
    own decisions stand in, and the concept is the first one the pipeline
    proposed. The scorer never reads this choice, so it cannot flatter the run.
    """
    from domain_foundry_core.foundry.models import RemixSelection

    decisions = list(target.remix.user_decisions) or ["Chose the first proposed concept."]
    return RemixSelection(
        selected_concept=proposal.concepts[0].id,
        user_decisions=decisions,
    )


def build_one(
    interest: str,
    out_dir: Path,
    *,
    home: Path,
    live: bool = False,
    keep_temp: bool = False,
) -> dict[str, Any]:
    from domain_foundry_core.foundry.compiler import FoundryCompiler
    from domain_foundry_core.foundry.loader import load_foundry_spec
    from domain_foundry_core.foundry.pipeline import FoundryPipeline

    target_dir = SHOWCASE_ROOT / interest
    spec_path = target_dir / "spec.yaml"
    if not spec_path.is_file():
        raise SystemExit(f"no target spec: {spec_path}")

    target = load_foundry_spec(spec_path)
    tasks = _acceptance_tasks(target)
    if len(tasks) < 2:
        raise SystemExit(
            f"{interest}: the target spec carries {len(tasks)} user-authored "
            "acceptance case(s); the pipeline requires at least two so the "
            "generator cannot author its own judge."
        )

    provider = build_provider(interest, live=live, home=home)
    pipeline = FoundryPipeline(provider)

    proposed = pipeline.propose(
        target.research.interest,
        artifacts=list(target.research.existing_artifacts),
        constraints=list(target.research.constraints),
        acceptance_tasks=tasks,
    )
    spec = pipeline.complete(proposed.proposal, _remix_from(proposed.proposal, target))

    staging = Path(tempfile.mkdtemp(prefix=f"showcase_{interest}_"))
    bundle = staging / "bundle"
    try:
        FoundryCompiler().compile(spec, bundle)
        destination = out_dir / interest / "generated"
        # The compiler refuses to overwrite, and so does this: a regenerated
        # showcase replaces a reviewed artifact, so removal is explicit.
        if destination.exists():
            shutil.rmtree(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(bundle, destination)
    finally:
        if not keep_temp:
            shutil.rmtree(staging, ignore_errors=True)

    return {
        "interest": interest,
        "generated": str(destination),
        "mode": "live" if live else "replay",
        "spec_id": spec.id,
        "entities": len(spec.domain.entities),
        "views": len(spec.experience.views),
        "evidence": len(spec.evidence),
        "sources": len(spec.source_ids),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build and score the showcase specs")
    parser.add_argument("--interest", help="Single showcase directory name")
    parser.add_argument("--all", action="store_true", help="Rebuild every showcase")
    parser.add_argument("--list", action="store_true", help="List showcase targets and exit")
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=SHOWCASE_ROOT,
        help="Where to write <interest>/generated (default: examples/showcase)",
    )
    parser.add_argument("--keep-temp", action="store_true", help="Leave the staging dir")
    parser.add_argument(
        "--live",
        action="store_true",
        help=f"Call the configured model and record cassettes (same as {LIVE_ENV}=1)",
    )
    parser.add_argument(
        "--gate",
        action="store_true",
        help="Score every built spec against its target and fail under threshold",
    )
    parser.add_argument(
        "--home", type=Path, default=None, help="Workspace home holding provider config"
    )
    args = parser.parse_args(argv)

    targets = discover()
    if args.list:
        for name in targets:
            print(name)
        return 0

    if args.interest:
        selected = [args.interest]
    elif args.all:
        selected = targets
    else:
        parser.error("pass --interest <name>, --all, or --list")
        return 2

    from domain_foundry_core.paths import default_home

    home = args.home or default_home()
    live = live_requested(args.live)
    reports = []
    failures: list[str] = []
    for name in selected:
        print(f"building {name} ({'live' if live else 'replay'}) ...", file=sys.stderr)
        try:
            reports.append(
                build_one(name, args.out_dir, home=home, live=live, keep_temp=args.keep_temp)
            )
        except Exception as error:  # noqa: BLE001 - reported, then turned into an exit code
            message = missing_cassette_message(error)
            print(message or f"{name}: {type(error).__name__}: {error}", file=sys.stderr)
            failures.append(name)

    print(json.dumps({"built": reports}, indent=2))

    if not args.gate:
        return 1 if failures else 0

    from showcase_score import score_interest

    green = True
    for name in selected:
        if name in failures:
            green = False
            continue
        card = score_interest(name, args.out_dir)
        print(card.render())
        green = green and card.passed
    if not green:
        print(
            "\nShowcase gate failed. Either the pipeline did not reach the target, "
            "or the cassettes for this run are not recorded yet.",
            file=sys.stderr,
        )
    return 0 if green else 1


if __name__ == "__main__":
    raise SystemExit(main())
