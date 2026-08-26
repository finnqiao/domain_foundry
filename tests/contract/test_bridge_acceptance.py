"""Given a researched spec, does the resulting pack file the user's real sentence?

This is the end-to-end claim the wizard-foundry bridge exists to make, and the
one number the offline path cannot move. Elicitation got the interest suite to
50/50 against its `jargon` probe, but the wizard's own held-out sentence still
files 0/10: one user sentence teaches a pack the words in that sentence and
nothing else. Research is what supplies the rest of the vocabulary.

So this walks the whole real path — `FoundrySpec` -> `spec_to_shortlist` ->
`compile_shortlist` -> `write_pack` -> install -> capture — and asserts that each
showcase interest files the exact sentence its README promises, and still ignores
idle chatter.

The specs are hand-authored targets rather than live pipeline output (see
`docs/create-path-bar.md`); that is the labelled part. Everything downstream of
them here is production code, so a regression in the projection, the compiler, or
the router breaks this test.
"""

from __future__ import annotations

import pytest

from domain_foundry_core.foundry.loader import load_foundry_spec
from domain_foundry_core.wizard import blueprint as bp
from domain_foundry_core.wizard.bridge import spec_to_shortlist
from domain_foundry_core.wizard.shortlist import compile_shortlist

IDLE_CHATTER = "nice afternoon, weather was good"

# (showcase dir, the goal a user would type, the sentence its README promises,
#  the object the sentence should become)
ACCEPTANCE = [
    (
        "lifting-log",
        "log my gym lifting program",
        "squat 5x5 at 100kg, last set was a grind",
        "set_entry",
    ),
    (
        "whisky-tasting",
        "whisky tasting notes",
        "peated dram, iodine and orchard fruit, 12 year, neat",
        "dram",
    ),
    (
        "ham-radio",
        "ham radio contacts",
        "worked JA1RQK on 20 meters, RST 59, QSL via bureau",
        "qso",
    ),
    (
        "aquarium",
        "fish in my aquarium tank",
        "added a neon tetra, parameters 6.8 pH, 78F, new plant",
        "water_test",
    ),
    (
        "lego-builds",
        "track my lego builds",
        "finished the Millennium Falcon MOC, 3800 pieces, missing 2 tiles",
        "build_project",
    ),
]


def _install_from_spec(api, workspace, showcase: str, goal: str) -> str:
    from pathlib import Path

    repo = Path(__file__).resolve().parents[2]
    spec = load_foundry_spec(repo / "examples" / "showcase" / showcase / "spec.yaml")
    blueprint = compile_shortlist(spec_to_shortlist(spec), goal=goal)
    draft = Path(workspace.home) / f"draft_{showcase}"
    bp.write_pack(blueprint, draft, version="0.1.0")
    api.packs.add(draft, force=True)
    return str(blueprint["domain"])


def _filed_spans(receipt, pack: str) -> list:
    return [
        span
        for span in receipt.routed
        if span.domain == pack and span.disposition not in {"unfiled", "ledger_only"}
    ]


@pytest.mark.parametrize(("showcase", "goal", "sentence", "expected_object"), ACCEPTANCE)
def test_a_researched_spec_files_its_own_acceptance_sentence(
    showcase: str, goal: str, sentence: str, expected_object: str, workspace
) -> None:
    from domain_foundry_core.api.harness import HarnessAPI

    api = HarnessAPI(workspace.home)
    api.init()
    pack = _install_from_spec(api, workspace, showcase, goal)

    filed = _filed_spans(api.capture(sentence), pack)

    assert filed, (
        f"{showcase}: {sentence!r} did not file into {pack!r}. This is the sentence "
        "its README promises the finished app will handle."
    )
    assert filed[0].object_type == expected_object, (
        f"{showcase}: filed as {filed[0].object_type!r}, expected {expected_object!r}"
    )


@pytest.mark.parametrize(("showcase", "goal", "sentence", "expected_object"), ACCEPTANCE)
def test_a_researched_pack_still_ignores_idle_chatter(
    showcase: str, goal: str, sentence: str, expected_object: str, workspace
) -> None:
    """Richer vocabulary is exactly how a router starts over-capturing."""
    from domain_foundry_core.api.harness import HarnessAPI

    api = HarnessAPI(workspace.home)
    api.init()
    pack = _install_from_spec(api, workspace, showcase, goal)

    assert not _filed_spans(api.capture(IDLE_CHATTER), pack), (
        f"{showcase}: filed idle chatter into {pack!r}"
    )


def test_the_projection_carries_domain_vocabulary_not_logging_vocabulary(workspace) -> None:
    """The whole point: words a keyword scaffold could never have invented."""
    from pathlib import Path

    repo = Path(__file__).resolve().parents[2]
    expected = {
        "lifting-log": {"squat", "5x5", "deload"},
        "whisky-tasting": {"peated", "iodine", "neat"},
        "ham-radio": {"ft8", "lotw"},
        "aquarium": {"nitrite", "nitrate"},
        "lego-builds": {"moc"},
    }
    for showcase, needed in expected.items():
        spec = load_foundry_spec(repo / "examples" / "showcase" / showcase / "spec.yaml")
        jargon = {term.lower() for term in spec_to_shortlist(spec).jargon}
        missing = needed - jargon
        assert not missing, f"{showcase}: projection lost {sorted(missing)}"
