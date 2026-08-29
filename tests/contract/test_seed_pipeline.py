"""E3: preview, apply, and the promise that applying twice writes nothing twice."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
import typer
from typer.testing import CliRunner

from domain_foundry_core.api.harness import HarnessAPI
from domain_foundry_core.cli_seed import register
from domain_foundry_core.packs.registry import PackRegistry
from domain_foundry_core.paths import Workspace
from domain_foundry_core.security.store import connect_ro
from domain_foundry_core.seed.apply import (
    SeedApplyError,
    apply_seed,
    load_seed_records,
    seed_provenances,
)
from domain_foundry_core.seed.mapping import infer_mapping
from domain_foundry_core.seed.preview import build_preview, render_preview, write_preview
from domain_foundry_core.seed.readers import read_seed

REPO = Path(__file__).resolve().parents[2]
FIXTURES = REPO / "examples" / "seed-fixtures"
TEMPLATE_PACK = REPO / "packs" / "_template"

TIDEPOOL_ROWS = 214

PACK_YAML = """name: tidepools
version: 0.1.0
title: "Tidepools"
description: "A log of what you saw in the pools at low tide."
author: "test"
license: MIT
core_compat: ">=0.1,<2"
interpretation: simple
aliases: [tidepool]
"""

SCHEMA_YAML = """objects:
  sighting:
    title_field: species
    fields:
      species: {type: text, required: true}
      place: {type: text}
      date: {type: date}
      count: {type: integer}
      notes: {type: text, long: true}
"""

ROUTING_YAML = """rules:
  - match: "(sighting|tidepool|anemone)\\\\b"
    object: sighting
    confidence_boost: 0.05

examples:
  - text: "sighting: three ochre sea stars at the reef"
    expect: {object: sighting, operation: create}
  - text: "tidepool visit, two anemones"
    expect: {object: sighting, operation: create}
  - text: "sighting of a purple urchin"
    expect: {object: sighting, operation: create}
  - text: "tidepool: gumboot chiton under the ledge"
    expect: {object: sighting, operation: create}
  - text: "sighting — bat star in the second pool"
    expect: {object: sighting, operation: create}
  - text: "anemone patch was bigger than last time"
    expect: {object: sighting, operation: create}
  - text: "sighting: hermit crab, lots of them"
    expect: {object: sighting, operation: create}
  - text: "tidepool notes, one sea star"
    expect: {object: sighting, operation: create}

negative_examples:
  - text: "remember to renew the parking permit"
  - text: "the tide of pull requests is rising"
"""

OPERATIONS_YAML = "sighting: [create, update, correct, delete]\n"

PROJECTIONS_YAML = """app:
  icon: "🐚"
  views:
    - {id: sightings, title: "Sightings", block: list, object: sighting, config: {sort: date}}
markdown:
  folder: "Tidepools"
  note_template: null
"""

AGENT_YAML = """agent:
  name: tidepools
  persona: >
    You keep the user's tidepool log.
  tools:
    - capture
    - query
    - correct
  autonomy:
    capture: auto
  sessions: []
  schedules: []
"""


@pytest.fixture
def seeded_workspace(workspace: Workspace, tmp_path: Path) -> Workspace:
    """A workspace with an app to seed into."""

    api = HarnessAPI(workspace.home)
    api.init()
    source = tmp_path / "tidepools-pack"
    shutil.copytree(TEMPLATE_PACK, source)
    (source / "pack.yaml").write_text(PACK_YAML, encoding="utf-8")
    (source / "schema.yaml").write_text(SCHEMA_YAML, encoding="utf-8")
    (source / "routing.yaml").write_text(ROUTING_YAML, encoding="utf-8")
    (source / "operations.yaml").write_text(OPERATIONS_YAML, encoding="utf-8")
    (source / "projections.yaml").write_text(PROJECTIONS_YAML, encoding="utf-8")
    (source / "agent.yaml").write_text(AGENT_YAML, encoding="utf-8")
    PackRegistry(workspace).add(source, force=True)
    return workspace


def _read_and_map(name: str = "tidepool-log.xlsx"):
    read = read_seed(FIXTURES / name)
    return read, infer_mapping(read, domain="tidepools", object_type="sighting")


def _cli() -> typer.Typer:
    """A bare app with only this lane's verb on it, the way cli.py will get it."""

    app = typer.Typer()

    @app.callback()
    def _root() -> None:
        """Stand-in for the real root callback, so `seed` stays a subcommand."""

    register(app)
    return app


def _rows(workspace: Workspace) -> int:
    conn = connect_ro(workspace.domains_db)
    try:
        return conn.execute("SELECT COUNT(*) FROM tidepools__sighting").fetchone()[0]
    finally:
        conn.close()


# ------------------------------------------------------------------- the preview


def test_the_preview_says_what_was_read_and_what_will_happen():
    read, mapping = _read_and_map()
    preview = build_preview(read, mapping, will_write=TIDEPOOL_ROWS)
    html = render_preview(preview)

    assert "214 rows" in html
    assert "214 records will be written" in html
    assert "I will treat each row as one record" in html
    assert "7 in Place" in html and "9 in Species" in html
    assert "2024-04-05" in html
    assert "not changed, moved, or renamed" in html


def test_the_preview_says_a_personal_upload_stays_here():
    read, mapping = _read_and_map()
    html = render_preview(build_preview(read, mapping))

    assert "stays on this machine" in html
    assert "Your records never do" in html


def test_the_preview_names_what_it_left_out():
    read = read_seed(FIXTURES / "ambiguous.csv")
    mapping = infer_mapping(read, domain="whatever")
    html = render_preview(build_preview(read, mapping))

    assert "What I left out" in html
    assert "<li>b</li>" in html


def test_the_preview_is_a_page_with_no_scripts_and_nothing_to_fetch():
    read, mapping = _read_and_map()
    html = render_preview(build_preview(read, mapping))

    assert "<script" not in html.casefold()
    assert "http://" not in html and "https://" not in html


def test_a_renderer_can_be_swapped_in():
    """Lane C's review renderer slots in here without touching the pipeline."""

    read, mapping = _read_and_map()
    preview = build_preview(read, mapping)

    def fake_renderer(payload) -> str:
        return f"<p>{payload.summary.row_count}</p>"

    assert render_preview(preview, renderer=fake_renderer) == "<p>214</p>"


def test_the_preview_is_written_where_it_was_asked_for(tmp_path: Path):
    read, mapping = _read_and_map()
    path = write_preview(build_preview(read, mapping), tmp_path / "out" / "page.html")

    assert path.exists()
    assert path.name == "page.html"


# --------------------------------------------------------------------- the apply


def test_a_dry_run_writes_nothing(seeded_workspace: Workspace):
    read, mapping = _read_and_map()
    result = apply_seed(seeded_workspace, read, mapping)

    assert result.dry_run is True
    assert result.would_write == TIDEPOOL_ROWS
    assert result.written == 0
    assert result.complete
    assert _rows(seeded_workspace) == 0


def test_apply_writes_every_row(seeded_workspace: Workspace):
    read, mapping = _read_and_map()
    result = apply_seed(seeded_workspace, read, mapping, dry_run=False)

    assert result.written == TIDEPOOL_ROWS
    assert result.failed == 0
    assert result.complete
    assert _rows(seeded_workspace) == TIDEPOOL_ROWS


def test_applying_the_same_seed_twice_writes_nothing_the_second_time(
    seeded_workspace: Workspace,
):
    """The floor: seeding is safe to repeat, so a person can re-run it."""

    read, mapping = _read_and_map()
    apply_seed(seeded_workspace, read, mapping, dry_run=False)
    after_first = _rows(seeded_workspace)

    second = apply_seed(seeded_workspace, read, mapping, dry_run=False)

    assert second.written == 0
    assert second.already_present == TIDEPOOL_ROWS
    assert second.complete
    assert _rows(seeded_workspace) == after_first == TIDEPOOL_ROWS


def test_every_seeded_row_carries_where_it_came_from(seeded_workspace: Workspace):
    read, mapping = _read_and_map()
    apply_seed(seeded_workspace, read, mapping, dry_run=False)

    conn = connect_ro(seeded_workspace.ledger_db)
    try:
        rows = conn.execute(
            "SELECT channel, source_ref FROM capture_event WHERE channel = ?",
            ("seed-personal",),
        ).fetchall()
    finally:
        conn.close()

    assert len(rows) == TIDEPOOL_ROWS
    prefix = f"seed:{read.provenance.id}:"
    assert all(row["source_ref"].startswith(prefix) for row in rows)


def test_the_seed_itself_is_recorded_and_stays_unshareable(seeded_workspace: Workspace):
    read, mapping = _read_and_map()
    apply_seed(seeded_workspace, read, mapping, dry_run=False)

    records = load_seed_records(seeded_workspace)
    assert len(records) == 1
    assert records[0]["shareable"] is False
    assert records[0]["channel"] == "seed-personal"

    provenances = seed_provenances(seeded_workspace)
    assert [p.kind for p in provenances] == ["personal_upload"]
    assert provenances[0].row_count == TIDEPOOL_ROWS


def test_the_values_land_in_the_right_fields(seeded_workspace: Workspace):
    read, mapping = _read_and_map()
    apply_seed(seeded_workspace, read, mapping, dry_run=False)

    conn = connect_ro(seeded_workspace.domains_db)
    try:
        row = conn.execute(
            "SELECT species, place, date, count FROM tidepools__sighting "
            "ORDER BY date ASC, id ASC LIMIT 1"
        ).fetchone()
        places = conn.execute("SELECT COUNT(DISTINCT place) FROM tidepools__sighting").fetchone()[0]
        species = conn.execute(
            "SELECT COUNT(DISTINCT species) FROM tidepools__sighting"
        ).fetchone()[0]
    finally:
        conn.close()

    assert row["date"] == "2024-04-05"
    assert row["place"]
    assert isinstance(row["count"], int)
    assert (places, species) == (7, 9)


def test_seeding_an_app_that_does_not_exist_says_so(workspace: Workspace):
    HarnessAPI(workspace.home).init()
    read, mapping = _read_and_map()

    with pytest.raises(SeedApplyError) as caught:
        apply_seed(workspace, read, mapping, dry_run=False)

    assert "no app called 'tidepools'" in str(caught.value)


def test_seeding_a_table_that_does_not_exist_lists_the_ones_that_do(
    seeded_workspace: Workspace,
):
    read = read_seed(FIXTURES / "tidepool-log.xlsx")
    mapping = infer_mapping(read, domain="tidepools", object_type="nonsense")

    with pytest.raises(SeedApplyError) as caught:
        apply_seed(seeded_workspace, read, mapping, dry_run=False)

    assert "no table called 'nonsense'" in str(caught.value)
    assert "sighting" in str(caught.value)


# ----------------------------------------------------------------------- the cli


def test_the_verb_runs_a_dry_run_by_default(seeded_workspace: Workspace, tmp_path: Path):
    out = tmp_path / "seed-preview.html"
    result = CliRunner().invoke(
        _cli(),
        [
            "seed",
            str(FIXTURES / "tidepool-log.xlsx"),
            "--domain",
            "tidepools",
            "--object-type",
            "sighting",
            "--out",
            str(out),
            "--home",
            str(seeded_workspace.home),
        ],
    )

    assert result.exit_code == 0, result.output
    assert "Nothing was written" in result.output
    assert "214 records are ready to go" in result.output
    assert out.exists()
    assert _rows(seeded_workspace) == 0


def test_the_verb_writes_only_with_apply(seeded_workspace: Workspace, tmp_path: Path):
    args = [
        "seed",
        str(FIXTURES / "tidepool-log.xlsx"),
        "--domain",
        "tidepools",
        "--object-type",
        "sighting",
        "--out",
        str(tmp_path / "page.html"),
        "--home",
        str(seeded_workspace.home),
        "--apply",
        "--json",
    ]
    result = CliRunner().invoke(_cli(), args)

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["written"] == TIDEPOOL_ROWS
    assert payload["complete"] is True
    assert payload["lists"] == {"Place": 7, "Species": 9}

    again = CliRunner().invoke(_cli(), args)
    assert again.exit_code == 0, again.output
    assert json.loads(again.output)["written"] == 0
    assert _rows(seeded_workspace) == TIDEPOOL_ROWS


def test_the_verb_can_save_a_mapping_and_take_it_back(seeded_workspace: Workspace, tmp_path: Path):
    mapping_path = tmp_path / "mapping.yaml"
    first = CliRunner().invoke(
        _cli(),
        [
            "seed",
            str(FIXTURES / "tidepool-log.csv"),
            "--domain",
            "tidepools",
            "--object-type",
            "sighting",
            "--save-mapping",
            str(mapping_path),
            "--out",
            str(tmp_path / "a.html"),
            "--home",
            str(seeded_workspace.home),
        ],
    )
    assert first.exit_code == 0, first.output
    assert mapping_path.exists()

    second = CliRunner().invoke(
        _cli(),
        [
            "seed",
            str(FIXTURES / "tidepool-log.csv"),
            "--domain",
            "tidepools",
            "--mapping",
            str(mapping_path),
            "--out",
            str(tmp_path / "b.html"),
            "--home",
            str(seeded_workspace.home),
            "--json",
        ],
    )
    assert second.exit_code == 0, second.output
    assert json.loads(second.output)["would_write"] == TIDEPOOL_ROWS


def test_the_verb_reads_a_page_as_reference(seeded_workspace: Workspace, tmp_path: Path):
    result = CliRunner().invoke(
        _cli(),
        [
            "seed",
            str(FIXTURES / "field-guide.html"),
            "--domain",
            "tidepools",
            "--out",
            str(tmp_path / "guide.html"),
            "--home",
            str(seeded_workspace.home),
        ],
    )

    assert result.exit_code == 0, result.output
    assert "Read the page: Rocky shore field guide" in result.output
    assert "licence is unknown until someone checks" in result.output
    assert _rows(seeded_workspace) == 0


def test_the_verb_fails_plainly_on_a_source_it_cannot_read(
    seeded_workspace: Workspace, tmp_path: Path
):
    result = CliRunner().invoke(
        _cli(),
        [
            "seed",
            str(tmp_path / "missing.xlsx"),
            "--domain",
            "tidepools",
            "--home",
            str(seeded_workspace.home),
        ],
    )

    assert result.exit_code == 2
    assert "could not find" in result.output


def test_the_one_line_help_says_what_leaves_the_machine():
    result = CliRunner().invoke(_cli(), ["seed", "--help"])

    assert result.exit_code == 0
    assert "never the whole file" in " ".join(result.output.split())
