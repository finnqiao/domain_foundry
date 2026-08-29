"""`look`, `tokens`, and `vibe` driven the way a person drives them.

The lane registers its own module, so these tests attach it to a bare Typer
application. `cli.py` gets one line from the integrator; nothing here depends on
that line existing yet.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
import typer
import yaml
from typer.testing import CliRunner

from domain_foundry_core import cli_taste
from domain_foundry_core.foundry.loader import load_foundry_spec
from domain_foundry_core.review import MARKS_FILENAME, MARKS_VERSION

REPO_ROOT = Path(__file__).resolve().parents[2]
GOLDEN = REPO_ROOT / "examples" / "golden" / "sourdough-lab.foundry.yaml"
FIXTURES = REPO_ROOT / "tests" / "fixtures" / "review"


@pytest.fixture
def cli() -> CliRunner:
    return CliRunner()


@pytest.fixture
def app() -> typer.Typer:
    application = typer.Typer()
    cli_taste.register(application)
    return application


@pytest.fixture
def spec_path(tmp_path) -> Path:
    target = tmp_path / "sourdough-lab.foundry.yaml"
    shutil.copy(GOLDEN, target)
    return target


def run(cli: CliRunner, app: typer.Typer, *args: str):
    return cli.invoke(app, list(args))


def payload(result) -> dict:
    return json.loads(result.output)


# ---------------------------------------------------------------------------
# look
# ---------------------------------------------------------------------------


def test_look_writes_a_page_and_says_what_to_do_next(cli, app, spec_path) -> None:
    result = run(cli, app, "look", str(spec_path), "--no-previews")
    assert result.exit_code == 0, result.output
    said = payload(result)
    page = Path(said["page"])
    assert page.exists()
    assert page.name == "review.html"
    assert said["concepts"] == ["ritual", "lab", "bake_day"]
    assert said["already_chosen"] is None
    assert "mark it up, press Save" in said["next"]
    assert "look" in said["next"] and "--read" in said["next"]


def test_look_read_binds_the_marks_into_the_spec(cli, app, spec_path) -> None:
    run(cli, app, "look", str(spec_path), "--no-previews")
    marks_dir = spec_path.parent / f"{spec_path.stem}-review"
    (marks_dir / MARKS_FILENAME).write_text(
        json.dumps(
            {
                "marks_version": MARKS_VERSION,
                "look_id": "sourdough-lab-look",
                "chosen_concept": "lab",
                "concepts": {
                    "ritual": {"borrow": "the big Feed now button"},
                    "lab": {
                        "topology": "workflow",
                        "density_scale": "dense",
                        "token_overrides": {"accent": "#E39A2D"},
                    },
                },
                "notes": ["I open this one handed"],
            }
        ),
        encoding="utf-8",
    )
    result = run(cli, app, "look", str(spec_path), "--read")
    assert result.exit_code == 0, result.output
    said = payload(result)
    assert said["bound"] is True
    assert said["concept"] == "lab"
    assert said["colours_changed"] == ["accent"]
    assert said["borrowed"] == ["ritual"]

    spec = load_foundry_spec(spec_path)
    assert spec.look is not None
    assert spec.look.concept_id == "lab"
    assert spec.look.token_overrides == {"accent": "#E39A2D"}
    assert spec.look.borrowed_fragments[0].piece == "the big Feed now button"


def test_the_binding_stays_in_the_file_that_gets_dumped(cli, app, spec_path) -> None:
    run(cli, app, "look", str(spec_path), "--choose", "lab", "--set", "accent=#E39A2D")
    document = yaml.safe_load(spec_path.read_text(encoding="utf-8"))
    assert document["look"]["concept_id"] == "lab"
    assert document["look"]["token_overrides"] == {"accent": "#E39A2D"}


def test_a_second_run_starts_from_what_was_bound(cli, app, spec_path) -> None:
    run(cli, app, "look", str(spec_path), "--choose", "lab", "--set", "accent=#E39A2D")
    result = run(cli, app, "look", str(spec_path), "--no-previews")
    said = payload(result)
    assert said["already_chosen"] == "lab"
    page = Path(said["page"]).read_text(encoding="utf-8")
    assert 'id="lab-chosen" value="lab" checked' in page
    assert 'data-token="accent" value="#E39A2D"' in page


def test_the_no_browser_path_gives_the_identical_binding(cli, app, tmp_path) -> None:
    through_page = tmp_path / "page.foundry.yaml"
    through_flags = tmp_path / "flags.foundry.yaml"
    shutil.copy(GOLDEN, through_page)
    shutil.copy(GOLDEN, through_flags)

    marks = tmp_path / MARKS_FILENAME
    marks.write_text(
        json.dumps(
            {
                "marks_version": MARKS_VERSION,
                "look_id": "sourdough-lab-look",
                "chosen_concept": "lab",
                "concepts": {
                    "lab": {
                        "topology": "workflow",
                        "typography_stack": "data_sans",
                        "density_scale": "dense",
                        "token_overrides": {"accent": "#E39A2D"},
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    assert run(cli, app, "look", str(through_page), "--read", "--marks", str(marks)).exit_code == 0
    settings = tmp_path / "tokens.json"
    settings.write_text(json.dumps({"accent": "#E39A2D"}), encoding="utf-8")
    assert (
        run(
            cli,
            app,
            "look",
            str(through_flags),
            "--choose",
            "lab",
            "--tokens",
            str(settings),
            "--topology",
            "workflow",
            "--type",
            "data_sans",
            "--density",
            "dense",
        ).exit_code
        == 0
    )
    assert load_foundry_spec(through_page).look == load_foundry_spec(through_flags).look


def test_marks_that_choose_nothing_are_refused_in_plain_words(cli, app, spec_path) -> None:
    marks = spec_path.parent / MARKS_FILENAME
    marks.write_text(
        json.dumps(
            {
                "marks_version": MARKS_VERSION,
                "look_id": "sourdough-lab-look",
                "concepts": {"lab": {}},
            }
        ),
        encoding="utf-8",
    )
    result = run(cli, app, "look", str(spec_path), "--read", "--marks", str(marks))
    assert result.exit_code == 2
    assert "Nothing is chosen yet" in result.output
    assert load_foundry_spec(spec_path).look is None


def test_a_concept_this_spec_does_not_have_is_refused(cli, app, spec_path) -> None:
    result = run(cli, app, "look", str(spec_path), "--choose", "nonesuch")
    assert result.exit_code == 2
    assert "nonesuch" in result.output
    assert load_foundry_spec(spec_path).look is None


# ---------------------------------------------------------------------------
# tokens
# ---------------------------------------------------------------------------


def test_tokens_says_the_current_look_in_plain_words(cli, app, spec_path) -> None:
    result = run(cli, app, "tokens", str(spec_path))
    assert result.exit_code == 0, result.output
    said = payload(result)
    assert said["colours"]["accent"] == "#A9582F"
    assert said["moving_around"]["means"] == "one home screen with everything branching off it"
    # This spec has not picked a spacing scale, and the command says exactly that
    # rather than guessing one.
    assert said["room"]["name"] == "not set yet"
    assert said["room"]["means"] == "the spec has not picked one yet"
    run(cli, app, "tokens", str(spec_path), "--density", "bench")
    after = payload(run(cli, app, "tokens", str(spec_path)))
    assert after["room"]["means"] == "a working bench: room to read, room to act"


def test_tokens_edits_land_in_the_binding(cli, app, spec_path) -> None:
    result = run(
        cli,
        app,
        "tokens",
        str(spec_path),
        "--set",
        "accent=#123456",
        "--type",
        "reading_serif",
        "--density",
        "bench",
    )
    assert result.exit_code == 0, result.output
    spec = load_foundry_spec(spec_path)
    assert spec.look is not None
    assert spec.look.token_overrides == {"accent": "#123456"}
    assert spec.look.typography_stack == "reading_serif"
    assert spec.look.density_scale == "bench"
    # Reading it back shows the change, not the old value.
    assert payload(run(cli, app, "tokens", str(spec_path)))["colours"]["accent"] == "#123456"


def test_tokens_keeps_earlier_edits_when_you_change_one_more(cli, app, spec_path) -> None:
    run(cli, app, "tokens", str(spec_path), "--set", "accent=#123456")
    run(cli, app, "tokens", str(spec_path), "--set", "border=#654321")
    spec = load_foundry_spec(spec_path)
    assert spec.look is not None
    assert spec.look.token_overrides == {"accent": "#123456", "border": "#654321"}


def test_a_colour_that_is_not_a_colour_is_refused(cli, app, spec_path) -> None:
    result = run(cli, app, "tokens", str(spec_path), "--set", "accent=burnt orange")
    assert result.exit_code == 2
    assert "#E39A2D" in result.output
    assert "Traceback" not in result.output
    assert load_foundry_spec(spec_path).look is None


def test_a_colour_name_that_does_not_exist_is_refused(cli, app, spec_path) -> None:
    result = run(cli, app, "tokens", str(spec_path), "--set", "accent_colour=#123456")
    assert result.exit_code == 2
    assert "no colour called 'accent_colour'" in result.output


def test_tokens_page_writes_the_same_review_page(cli, app, spec_path) -> None:
    result = run(cli, app, "tokens", str(spec_path), "--page")
    assert result.exit_code == 0, result.output
    page = Path(payload(result)["page"])
    assert page.exists()
    assert 'data-token="accent"' in page.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# vibe
# ---------------------------------------------------------------------------


def test_vibe_reads_a_picture_and_saves_nothing_to_the_spec(cli, app, spec_path) -> None:
    result = run(cli, app, "vibe", str(FIXTURES / "reference.png"), "--spec", str(spec_path))
    assert result.exit_code == 0, result.output
    said = payload(result)
    assert said["kind"] == "png"
    assert said["colours"][0] == "#F4EEDF"
    assert said["proposed"]["accent"] == "#E39A2D"
    assert said["saved_nothing_yet"] is True
    assert "not sent anywhere" in said["note"]
    # The spec is untouched until the person approves.
    assert load_foundry_spec(spec_path).look is None
    # The proposal shows up on the page, marked as not saved.
    page = Path(said["page"]).read_text(encoding="utf-8")
    assert "nothing is saved yet" in page
    assert 'data-token="accent" value="#E39A2D"' in page


def test_vibe_reads_the_colours_an_html_file_declares(cli, app, tmp_path) -> None:
    result = run(cli, app, "vibe", str(FIXTURES / "reference.html"), "--out", str(tmp_path))
    assert result.exit_code == 0, result.output
    said = payload(result)
    assert said["kind"] == "html"
    assert said["colours"] == ["#F4EEDF", "#28251F", "#E39A2D", "#345A65"]
    assert said["type"] == "reading_serif"
    assert said["page"] is None
    assert Path(said["proposal"]).exists()


def test_what_vibe_proposes_is_only_kept_when_you_ask(cli, app, spec_path, tmp_path) -> None:
    proposal = json.loads(
        run(cli, app, "vibe", str(FIXTURES / "reference.html"), "--out", str(tmp_path)).output
    )["proposal"]
    assert load_foundry_spec(spec_path).look is None
    result = run(cli, app, "tokens", str(spec_path), "--from", proposal)
    assert result.exit_code == 0, result.output
    spec = load_foundry_spec(spec_path)
    assert spec.look is not None
    assert spec.look.token_overrides["accent"] == "#E39A2D"
    assert spec.look.typography_stack == "reading_serif"


def test_a_jpeg_is_turned_away_with_a_way_forward(cli, app, tmp_path) -> None:
    picture = tmp_path / "photo.jpg"
    picture.write_bytes(b"\xff\xd8\xff\xe0 not really a jpeg")
    result = run(cli, app, "vibe", str(picture))
    assert result.exit_code == 2
    assert "save it again as a PNG" in result.output
