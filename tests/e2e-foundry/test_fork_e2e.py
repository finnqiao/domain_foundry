"""Release proof #3: a real fork path end to end, parentage recorded.

Forks the sourdough golden, changes the accent token and one workload, builds
the fork, and checks that the parent is on the record and the change reached
the app.

Run: python -m pytest tests/e2e-foundry/test_fork_e2e.py -q
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import typer
from typer.testing import CliRunner

from domain_foundry_core.foundry.compiler import FoundryCompiler
from domain_foundry_core.foundry.fork import (
    FORK_MARKER,
    ForkError,
    fork_spec,
    parent_of,
    receipt_parent,
)
from domain_foundry_core.foundry.loader import (
    DEFAULT_GOLDENS,
    load_foundry_spec,
)
from domain_foundry_core.foundry.models import FoundrySpec

PARENT_ID = "sourdough-lab"
FORK_ID = "sourdough-rye"
NEW_ACCENT = "#3B5F3A"
NEW_QUESTION = "When does the rye starter peak after its latest feeding?"


@pytest.fixture
def parent_spec() -> FoundrySpec:
    return load_foundry_spec(DEFAULT_GOLDENS / f"{PARENT_ID}.foundry.yaml")


def _fork_with_changes(parent: FoundrySpec) -> FoundrySpec:
    """Fork, then make the two changes the proof asks for."""
    forked = fork_spec(parent, FORK_ID, title="Sourdough Rye").spec
    payload = forked.model_dump(mode="python")
    payload["experience"]["visual_world"]["tokens"]["accent"] = NEW_ACCENT
    payload["domain"]["workloads"][0]["question"] = NEW_QUESTION
    return FoundrySpec.model_validate(payload)


def test_fork_records_the_parent_on_the_spec(parent_spec: FoundrySpec) -> None:
    result = fork_spec(parent_spec, FORK_ID)

    assert result.spec.id == FORK_ID
    assert parent_of(result.spec) == PARENT_ID
    assert result.parent_id == PARENT_ID
    assert result.sentence == "Forked sourdough-lab into sourdough-rye."
    # The parent is untouched: forking never edits what it copies.
    assert parent_of(parent_spec) is None
    assert parent_spec.id == PARENT_ID


def test_fork_records_the_parent_as_a_derivation(parent_spec: FoundrySpec) -> None:
    result = fork_spec(parent_spec, FORK_ID)
    added = [item for item in result.spec.derivations if item.output_path == "remix.parent_spec"]
    assert len(added) == 1
    assert PARENT_ID in added[0].decision
    assert added[0].user_decision == f"Forked from {PARENT_ID}."
    assert f"Forked from {PARENT_ID}." in result.spec.remix.user_decisions


def test_fork_refuses_ids_it_cannot_record(parent_spec: FoundrySpec) -> None:
    with pytest.raises(ForkError, match="not a usable spec id"):
        fork_spec(parent_spec, "Sourdough Rye")
    with pytest.raises(ForkError, match="different from its parent"):
        fork_spec(parent_spec, PARENT_ID)


def test_forked_spec_still_validates(tmp_path: Path, parent_spec: FoundrySpec) -> None:
    """`foundry validate` accepts a forked spec."""
    from domain_foundry_core.foundry.loader import dump_foundry_spec

    forked = _fork_with_changes(parent_spec)
    written = tmp_path / "fork.foundry.yaml"
    dump_foundry_spec(forked, written)

    reloaded = load_foundry_spec(written)
    assert reloaded.id == FORK_ID
    assert parent_of(reloaded) == PARENT_ID
    assert reloaded.experience.visual_world.tokens.accent == NEW_ACCENT


def test_forked_build_receipt_names_the_parent(tmp_path: Path, parent_spec: FoundrySpec) -> None:
    forked = _fork_with_changes(parent_spec)
    artifact = FoundryCompiler().compile(forked, tmp_path / "bundle")

    receipt = json.loads(artifact.receipt.read_text(encoding="utf-8"))
    assert receipt["spec_id"] == FORK_ID
    assert FORK_MARKER in receipt["generation"]["pipeline_version"]
    assert receipt_parent(receipt["generation"]["pipeline_version"]) == PARENT_ID

    # The bundle's own copy of the spec carries the parent too.
    bundled = json.loads(artifact.spec.read_text(encoding="utf-8"))
    assert bundled["remix"]["parent_spec"] == PARENT_ID


def test_bundle_readme_states_the_parentage(tmp_path: Path, parent_spec: FoundrySpec) -> None:
    """RED until the README renderer names the parent.

    The lane doc asks the bundle README to state the parentage in one line.
    The README is written by `FoundryCompiler.render_readme`, which belongs to
    Lane B, so Lane G cannot add the line. Request filed in the Lane G resume
    notes. Everything else about the fork path is green.
    """
    forked = _fork_with_changes(parent_spec)
    artifact = FoundryCompiler().compile(forked, tmp_path / "bundle")
    readme = artifact.root.joinpath("README.md").read_text(encoding="utf-8")

    assert PARENT_ID in readme, (
        "The bundle README does not name the parent spec. "
        "Missing: one line in FoundryCompiler.render_readme "
        "(core/domain_foundry_core/foundry/compiler.py, Lane B) that prints "
        "spec.remix.parent_spec when it is set, for example "
        "'Forked from sourdough-lab.' The parentage is already on the spec and "
        "in build-receipt.json."
    )


def test_forked_app_reflects_the_change(tmp_path: Path, parent_spec: FoundrySpec) -> None:
    forked = _fork_with_changes(parent_spec)
    artifact = FoundryCompiler().compile(forked, tmp_path / "bundle")
    html = artifact.app.read_text(encoding="utf-8")

    assert NEW_QUESTION in html
    assert parent_spec.domain.workloads[0].question not in html
    # The accent token change is carried in the bundle. Whether the compiler
    # paints with it is measured by the difference gate (proof #2), which is
    # Lane B's to make true.
    bundled = json.loads(artifact.spec.read_text(encoding="utf-8"))
    assert bundled["experience"]["visual_world"]["tokens"]["accent"] == NEW_ACCENT


def test_fork_verb_prints_one_plain_sentence_naming_the_parent(tmp_path: Path) -> None:
    from domain_foundry_core.cli_fork import register

    cli = typer.Typer()
    register(cli)

    output = tmp_path / "rye.foundry.yaml"
    result = CliRunner().invoke(
        cli,
        [
            "foundry",
            "fork",
            str(DEFAULT_GOLDENS / f"{PARENT_ID}.foundry.yaml"),
            FORK_ID,
            "--output",
            str(output),
        ],
    )
    assert result.exit_code == 0, result.output
    assert "Forked sourdough-lab into sourdough-rye." in result.output
    assert "—" not in result.output
    assert output.is_file()
    assert parent_of(load_foundry_spec(output)) == PARENT_ID


def test_fork_verb_refuses_to_overwrite(tmp_path: Path) -> None:
    from domain_foundry_core.cli_fork import register

    cli = typer.Typer()
    register(cli)
    output = tmp_path / "taken.foundry.yaml"
    output.write_text("already here\n", encoding="utf-8")

    result = CliRunner().invoke(
        cli,
        [
            "foundry",
            "fork",
            str(DEFAULT_GOLDENS / f"{PARENT_ID}.foundry.yaml"),
            FORK_ID,
            "--output",
            str(output),
        ],
    )
    assert result.exit_code == 2
    assert "already a file" in result.output
