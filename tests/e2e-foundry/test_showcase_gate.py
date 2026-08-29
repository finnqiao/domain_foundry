"""Release proof #1: the pipeline generates a showcase-caliber spec unaided, in CI.

The gate itself is `python scripts/build_showcase.py --all --gate`. This file
checks the pieces it is built from, and holds the two things currently in its
way so they stay visible and named.

    python -m pytest tests/e2e-foundry/test_showcase_gate.py -q
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

import build_showcase
import showcase_score

REPO_ROOT = Path(__file__).resolve().parents[2]
SHOWCASE_ROOT = REPO_ROOT / "examples" / "showcase"
CASSETTES = REPO_ROOT / "tests" / "e2e-foundry" / "cassettes" / "showcase"


def test_there_are_five_showcase_targets() -> None:
    assert len(showcase_score.discover()) == 5


def test_the_scorer_reads_a_hand_authored_target() -> None:
    """A target spec scores well on shape and honestly badly on generation."""
    target = showcase_score.load_spec(SHOWCASE_ROOT / "whisky-tasting" / "spec.yaml")
    card = showcase_score.score(target, target, interest="whisky-tasting")
    axes = {axis.name: axis for axis in card.axes}

    assert axes["entity_coverage"].score == 1.0
    assert axes["workload_naming"].score == 1.0
    assert axes["region_variety"].passed
    assert axes["reference_closure"].passed
    # The targets were written by hand, so they carry no generation receipt and
    # no evidence tier. A generated spec that scored this way would be hiding
    # where its claims came from, so the axis fails and says so.
    assert not axes["evidence_discipline"].passed
    assert any("evidence tier" in note for note in axes["evidence_discipline"].notes)
    assert not card.passed


def test_the_scorer_catches_the_generic_five_field_shape() -> None:
    """One view of one region kind is the shape this whole programme exists to kill."""
    # The spec model refuses to hold this shape, which is the point: it can
    # only reach the scorer from something that is not a validated FoundrySpec.
    # So the axis is fed the shape directly.
    flat = SimpleNamespace(
        experience=SimpleNamespace(views=[SimpleNamespace(regions=[SimpleNamespace(kind="table")])])
    )

    axis = showcase_score.score_region_variety(flat, None)
    assert not axis.passed
    assert "generic shape" in " ".join(axis.notes)


def test_replay_is_the_default_and_live_is_opt_in(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(build_showcase.LIVE_ENV, raising=False)
    assert build_showcase.live_requested() is False
    monkeypatch.setenv(build_showcase.LIVE_ENV, "1")
    assert build_showcase.live_requested() is True


def test_replay_refuses_to_invent_answers(tmp_path: Path) -> None:
    """A prompt with no cassette is a named failure, never a quiet fallback."""
    provider = build_showcase.build_provider("whisky-tasting", live=False, home=tmp_path)
    with pytest.raises(build_showcase.MissingCassette) as caught:
        provider.complete_json(system="s", user="u", schema=None, model=None, tier="sota")
    message = str(caught.value)
    assert "is not recorded" in message
    assert "DOMAIN_FOUNDRY_LIVE_GATE=1" in message
    assert "keyword scaffold" in message


def test_showcase_targets_are_buildable() -> None:
    """Every showcase target must load and name a target the repo can build.

    This was red on 2026-08-28: all five specs listed only `standalone_react`,
    which the loader refuses. They now also list `foundry_runtime`.
    """
    from domain_foundry_core.foundry.loader import load_foundry_spec

    broken: list[str] = []
    for name in showcase_score.discover():
        try:
            load_foundry_spec(SHOWCASE_ROOT / name / "spec.yaml")
        except ValueError as error:
            broken.append(f"{name}: {error}")
    assert not broken, (
        "The showcase gate cannot load its own targets:\n"
        + "\n".join(broken)
        + "\nMissing: each examples/showcase/*/spec.yaml lists only "
        "`standalone_react` under implementation.targets, and the loader now "
        "refuses that (Lane A2 added check_targets_are_buildable). Either the "
        "targets gain `foundry_runtime` or the showcase set is retired. "
        "Owner: whoever owns the showcase target specs; filed from Lane G."
    )


def test_showcase_cassettes_are_recorded() -> None:
    """RED: nobody has recorded a live showcase run yet."""
    recorded = sorted(CASSETTES.rglob("*.json")) if CASSETTES.is_dir() else []
    assert recorded, (
        f"There are no cassettes under {CASSETTES}, so the showcase gate has "
        "nothing to replay. To record them: set a reasoning model with "
        "`domain-foundry setup`, then run "
        "`DOMAIN_FOUNDRY_LIVE_GATE=1 python scripts/build_showcase.py --all`. "
        "Commit the cassettes and the generated bundles as the evidence for "
        "proof #1."
    )
