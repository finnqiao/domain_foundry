from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from domain_foundry_core.cli import app
from domain_foundry_core.foundry.loader import DEFAULT_GOLDENS


def test_foundry_lists_three_distinct_goldens() -> None:
    result = CliRunner().invoke(app, ["foundry", "goldens"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert {item["id"] for item in payload} == {
        "card-collector",
        "japanese-study-coach",
        "sourdough-lab",
    }
    assert len({item["visual_world"] for item in payload}) == 3


def test_foundry_validates_and_builds_an_owned_bundle(tmp_path: Path) -> None:
    spec_path = DEFAULT_GOLDENS / "sourdough-lab.foundry.yaml"
    runner = CliRunner()

    validated = runner.invoke(app, ["foundry", "validate", str(spec_path)])
    assert validated.exit_code == 0, validated.output
    assert json.loads(validated.output)["entities"] >= 4

    output = tmp_path / "sourdough"
    built = runner.invoke(
        app,
        ["foundry", "build", str(spec_path), "--output", str(output)],
    )
    assert built.exit_code == 0, built.output
    payload = json.loads(built.output)
    assert payload["built"] is True
    assert Path(payload["app"]).is_file()
    assert Path(payload["schema"]).is_file()
    assert Path(payload["receipt"]).is_file()


def test_foundry_propose_requires_user_authored_acceptance_tasks(tmp_path: Path) -> None:
    result = CliRunner().invoke(
        app,
        [
            "foundry",
            "propose",
            "track something",
            "--output",
            str(tmp_path / "proposal.yaml"),
            "--task",
            "Record one thing => See it",
        ],
    )
    assert result.exit_code == 2
    assert "repeat --task at least twice" in result.output


def test_foundry_complete_requires_an_explicit_user_decision(tmp_path: Path) -> None:
    result = CliRunner().invoke(
        app,
        [
            "foundry",
            "complete",
            str(DEFAULT_GOLDENS / "sourdough-lab.foundry.yaml"),
            "--select",
            "experiment-ledger",
            "--output",
            str(tmp_path / "spec.yaml"),
        ],
    )
    assert result.exit_code == 2
    assert "at least one --decision" in result.output
