"""SP2: what a person marks on the review page is what the built app is.

This is the whole point of the loop. A look that gets generated, admired, and
thrown away is the problem this replaces, so this test follows one mark all the
way from the page to the pixels of the owned app:

1. `look` writes a review page for a golden spec.
2. The marks that page saves choose a concept, a layout, type, spacing, one
   colour, and a piece borrowed from another concept.
3. `look --read` binds them into the spec.
4. The compiler builds the app.
5. The built app carries every one of those choices.

Lane C owns this test. The reading side lives in Lane B's compiler, which this
test never touches, only builds through.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
import typer
from typer.testing import CliRunner

from domain_foundry_core import cli_taste
from domain_foundry_core.foundry.compiler import FoundryCompiler
from domain_foundry_core.foundry.loader import load_foundry_spec
from domain_foundry_core.review import MARKS_FILENAME, MARKS_VERSION

REPO_ROOT = Path(__file__).resolve().parents[2]
GOLDEN = REPO_ROOT / "examples" / "golden" / "sourdough-lab.foundry.yaml"

# What the person marks. The spec's own layout is "hub", so choosing "workflow"
# proves the choice travelled rather than the default surviving.
CHOSEN_CONCEPT = "lab"
BORROWED_FROM = "ritual"
BORROWED_PIECE = "the big Feed now button"
ACCENT = "#E39A2D"


@pytest.fixture
def taste_cli() -> tuple[CliRunner, typer.Typer]:
    application = typer.Typer()
    cli_taste.register(application)
    return CliRunner(), application


@pytest.fixture
def marked_up_spec(tmp_path, taste_cli) -> Path:
    runner, application = taste_cli
    spec_path = tmp_path / "sourdough-lab.foundry.yaml"
    shutil.copy(GOLDEN, spec_path)

    page_result = runner.invoke(
        application, ["look", str(spec_path), "--no-previews", "--out", str(tmp_path / "review")]
    )
    assert page_result.exit_code == 0, page_result.output
    page = Path(json.loads(page_result.output)["page"]).read_text(encoding="utf-8")
    # The controls we are about to mark are really on the page.
    assert f'value="{CHOSEN_CONCEPT}"' in page
    assert f'data-concept="{BORROWED_FROM}"' in page
    assert 'data-token="accent"' in page

    marks = tmp_path / "review" / MARKS_FILENAME
    marks.write_text(
        json.dumps(
            {
                "marks_version": MARKS_VERSION,
                "look_id": "sourdough-lab-look",
                "chosen_concept": CHOSEN_CONCEPT,
                "concepts": {
                    BORROWED_FROM: {
                        "borrow": BORROWED_PIECE,
                        "borrow_reason": "it is the only thing I want at 6am",
                    },
                    CHOSEN_CONCEPT: {
                        "topology": "workflow",
                        "typography_stack": "data_sans",
                        "density_scale": "dense",
                        "token_overrides": {"accent": ACCENT},
                        "signature_elements": ["progress_bar"],
                        "pins": [{"x": 6.0, "y": 9.0, "text": "the timer belongs first"}],
                    },
                },
                "notes": ["I open this one handed"],
                "saved_at": "2026-08-28T09:12:00Z",
            }
        ),
        encoding="utf-8",
    )
    read_result = runner.invoke(
        application, ["look", str(spec_path), "--read", "--marks", str(marks)]
    )
    assert read_result.exit_code == 0, read_result.output
    return spec_path


def test_the_marks_reach_the_spec(marked_up_spec) -> None:
    spec = load_foundry_spec(marked_up_spec)
    assert spec.look is not None
    assert spec.look.concept_id == CHOSEN_CONCEPT
    assert spec.look.topology == "workflow"
    assert spec.look.token_overrides == {"accent": ACCENT}
    assert spec.look.borrowed_fragments[0].from_concept == BORROWED_FROM
    # The spec's own layout is still what it always was, so the build has to be
    # reading the binding rather than the spec's default.
    assert spec.experience.navigation.topology == "hub"


def test_the_built_app_carries_the_chosen_topology(marked_up_spec, tmp_path) -> None:
    app = _build(marked_up_spec, tmp_path / "app-topology")
    assert 'data-topology="workflow"' in app
    assert 'data-topology="hub"' not in app.split("<body", 1)[1][:400]


def test_the_built_app_carries_the_token_overrides(marked_up_spec, tmp_path) -> None:
    app = _build(marked_up_spec, tmp_path / "app-tokens")
    assert f"--accent: {ACCENT};" in app
    # The colour the spec shipped with is gone from the palette it renders.
    assert "--accent: #A9582F;" not in app


def test_the_built_app_carries_the_type_and_spacing_choices(marked_up_spec, tmp_path) -> None:
    app = _build(marked_up_spec, tmp_path / "app-type")
    assert 'data-density="dense"' in app
    assert 'data-type-stack="data_sans"' in app


def test_the_built_app_carries_the_borrowed_fragment(marked_up_spec, tmp_path) -> None:
    root = tmp_path / "app-borrowed"
    artifact = FoundryCompiler().compile(load_foundry_spec(marked_up_spec), root)
    app = artifact.app.read_text(encoding="utf-8")
    spec_file = json.loads(artifact.spec.read_text(encoding="utf-8"))
    assert BORROWED_PIECE in app
    fragments = spec_file["look"]["borrowed_fragments"]
    assert [item["from_concept"] for item in fragments] == [BORROWED_FROM]
    assert fragments[0]["piece"] == BORROWED_PIECE


def test_the_pinned_note_travels_into_the_owned_bundle(marked_up_spec, tmp_path) -> None:
    root = tmp_path / "app-notes"
    artifact = FoundryCompiler().compile(load_foundry_spec(marked_up_spec), root)
    spec_file = json.loads(artifact.spec.read_text(encoding="utf-8"))
    notes = spec_file["look"]["notes"]
    assert "I open this one handed" in notes
    assert any("the timer belongs first" in note for note in notes)


def _build(spec_path: Path, root: Path) -> str:
    artifact = FoundryCompiler().compile(load_foundry_spec(spec_path), root)
    return artifact.app.read_text(encoding="utf-8")
