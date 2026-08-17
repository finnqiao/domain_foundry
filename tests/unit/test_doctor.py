from __future__ import annotations

import json
import socket
from pathlib import Path

import pytest
from typer.testing import CliRunner

from domain_foundry_core import cli as cli_module
from domain_foundry_core.api import app as app_module
from domain_foundry_core.cli import app


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def release_surfaces(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    webapp = tmp_path / "webapp"
    (webapp / "assets").mkdir(parents=True)
    (webapp / "index.html").write_text("<!doctype html>", encoding="utf-8")
    suite = tmp_path / "wizard_hobby_suite.jsonl"
    suite.write_text('{"text": "test"}\n', encoding="utf-8")
    monkeypatch.setattr(app_module, "_app_dist", lambda: webapp)
    monkeypatch.setattr(cli_module, "_heldout_suite_path", lambda: suite)


def invoke(runner: CliRunner, home: Path, *args: str):
    return runner.invoke(app, ["--home", str(home), *args])


def checks_by_name(payload: dict[str, object]) -> dict[str, dict[str, str]]:
    checks = payload["checks"]
    assert isinstance(checks, list)
    return {check["name"]: check for check in checks}


def test_doctor_after_init_reports_all_seven_checks(
    runner: CliRunner,
    tmp_path: Path,
    release_surfaces: None,
) -> None:
    home = tmp_path / "home"
    init = invoke(runner, home, "init")
    assert init.exit_code == 0, init.stdout

    result = invoke(runner, home, "doctor", "--json", "--port", "0")

    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    checks = checks_by_name(payload)
    assert len(checks) == 7
    assert {
        "Home layout",
        "Database integrity",
        "Packs valid",
        "Web app present",
        "Providers",
        "Port availability",
        "Held-out suite",
    } == set(checks)
    assert all(set(check) == {"name", "status", "detail"} for check in checks.values())


def test_doctor_uninitialized_home_exits_with_init_hint(
    runner: CliRunner,
    tmp_path: Path,
    release_surfaces: None,
) -> None:
    result = invoke(runner, tmp_path / "missing-home", "doctor", "--json")

    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    checks = checks_by_name(payload)
    assert checks["Home layout"]["status"] == "FAIL"
    assert "run domain-foundry init" in checks["Home layout"]["detail"]


def test_doctor_reports_occupied_port(
    runner: CliRunner,
    tmp_path: Path,
    release_surfaces: None,
) -> None:
    home = tmp_path / "home"
    init = invoke(runner, home, "init")
    assert init.exit_code == 0, init.stdout

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as occupied:
        occupied.bind(("127.0.0.1", 0))
        port = occupied.getsockname()[1]
        result = invoke(runner, home, "doctor", "--json", "--port", str(port))

    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    checks = checks_by_name(payload)
    assert checks["Port availability"]["status"] == "FAIL"
