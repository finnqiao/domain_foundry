#!/usr/bin/env python3
"""Regenerate the showcase apps through the real Foundry pipeline.

`examples/showcase/*/spec.yaml` are hand-authored targets: what the pipeline
*should* produce for five interests. This script asks the live pipeline to
produce them for real, writes the result beside the target, and leaves the two
readable side by side. The diff is the acceptance test for the whole create-path
programme, so it must never be faked.

Fails closed without a configured reasoning model. A keyword scaffold labelled as
research would defeat the point of the artifact, so there is no offline mode and
no placeholder output.

    python scripts/build_showcase.py --list
    python scripts/build_showcase.py --interest whisky-tasting
    python scripts/build_showcase.py --all --out-dir examples/showcase

Each generated bundle carries its own build receipt. Regeneration is deliberate:
commit the result as a reviewed diff, never as an automatic refresh.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
SHOWCASE_ROOT = REPO_ROOT / "examples" / "showcase"


def discover() -> list[str]:
    if not SHOWCASE_ROOT.is_dir():
        return []
    return sorted(
        entry.name
        for entry in SHOWCASE_ROOT.iterdir()
        if entry.is_dir() and (entry / "spec.yaml").is_file()
    )


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


def _live_provider(home: Path) -> Any:
    """Same gate the `foundry propose` CLI enforces, for the same reason."""
    from domain_foundry_core.llm.provider import build_tiered_provider

    provider = build_tiered_provider(home)
    if not provider.has_live_keys():
        raise SystemExit(
            "build_showcase requires a configured reasoning model.\n"
            "The showcase exists to prove the live pipeline produces researched "
            "specifications; generating it from the offline keyword scaffold would "
            "put an unresearched artifact under a 'generated' label.\n"
            "Run `domain-foundry setup` first."
        )
    return provider


def build_one(
    interest: str, out_dir: Path, *, home: Path, keep_temp: bool = False
) -> dict[str, Any]:
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

    provider = _live_provider(home)
    pipeline = FoundryPipeline(provider=provider)

    proposal = pipeline.propose(
        goal=target.research.interest,
        artifacts=list(target.research.existing_artifacts),
        constraints=list(target.research.constraints),
        tasks=tasks,
    )
    spec = pipeline.complete(proposal, selected_concept=None)

    staging = Path(tempfile.mkdtemp(prefix=f"showcase_{interest}_"))
    bundle = staging / "bundle"
    try:
        from domain_foundry_core.foundry.compiler import FoundryCompiler

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
        "spec_id": spec.id,
        "entities": len(spec.domain.entities),
        "views": len(spec.experience.views),
        "evidence": len(spec.evidence),
        "sources": len(spec.source_ids),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
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
        "--home", type=Path, default=None, help="Workspace home holding provider config"
    )
    args = parser.parse_args()

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
    reports = []
    for name in selected:
        print(f"building {name} ...", file=sys.stderr)
        reports.append(build_one(name, args.out_dir, home=home, keep_temp=args.keep_temp))

    print(json.dumps({"built": reports}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
