"""The quickstart promises a web app from `pipx install domain-foundry-core`.

A wheel has no repo checkout, so the SPA has to be found inside the package
(staged there by scripts/stage_webapp.sh) or the promise silently degrades to a
JSON blob telling the user to `cd app`, in a directory they do not have.
"""

from __future__ import annotations

import subprocess
import sys
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from domain_foundry_core.api import app as app_mod


def _write_spa(root: Path) -> Path:
    (root / "assets").mkdir(parents=True)
    (root / "index.html").write_text("<!doctype html><title>DF</title>", encoding="utf-8")
    (root / "assets" / "index.js").write_text("//", encoding="utf-8")
    (root / "THIRD_PARTY_NOTICES.txt").write_text(
        "DOMAIN FOUNDRY THIRD-PARTY NOTICES\n", encoding="utf-8"
    )
    return root


def test_app_dist_prefers_the_checkout(tmp_path, monkeypatch):
    checkout = _write_spa(tmp_path / "app" / "dist")
    packaged = _write_spa(tmp_path / "pkg" / "_webapp")
    monkeypatch.setattr(app_mod, "_REPO_APP_DIST", checkout)
    monkeypatch.setattr(app_mod, "_PACKAGED_APP_DIST", packaged)

    assert app_mod._app_dist() == checkout


def test_app_dist_falls_back_to_the_packaged_copy(tmp_path, monkeypatch):
    packaged = _write_spa(tmp_path / "pkg" / "_webapp")
    monkeypatch.setattr(app_mod, "_REPO_APP_DIST", tmp_path / "nope" / "dist")
    monkeypatch.setattr(app_mod, "_PACKAGED_APP_DIST", packaged)

    assert app_mod._app_dist() == packaged


def test_spa_serves_bundled_dependency_notices(tmp_path, monkeypatch):
    checkout = _write_spa(tmp_path / "app" / "dist")
    monkeypatch.setattr(app_mod, "_REPO_APP_DIST", checkout)
    monkeypatch.setattr(app_mod, "_PACKAGED_APP_DIST", tmp_path / "nope" / "_webapp")

    client = TestClient(app_mod.create_app(tmp_path / "home", enable_drain_loop=False))
    response = client.get("/THIRD_PARTY_NOTICES.txt")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    assert response.text.startswith("DOMAIN FOUNDRY THIRD-PARTY NOTICES")


def test_wheel_config_ships_the_staged_webapp():
    """Both build targets must declare the staged SPA as an artifact.

    This asserts the *config*, which is cheap enough to run every time. It is not
    sufficient on its own: the wheel target declared the artifact and the wheel
    still shipped without a SPA, because ``python -m build`` builds the wheel
    from the **sdist** and the sdist target did not declare it. The real proof is
    ``test_built_wheel_actually_contains_the_spa`` below.
    """
    pyproject = (Path(__file__).resolve().parents[2] / "pyproject.toml").read_text(
        encoding="utf-8"
    )
    wheel_cfg = pyproject.split("[tool.hatch.build.targets.wheel]", 1)[1].split(
        "[tool.hatch.build.targets.sdist]", 1
    )
    assert "core/domain_foundry_core/_webapp/**" in wheel_cfg[0], "wheel target"
    assert "core/domain_foundry_core/_webapp/**" in wheel_cfg[1], "sdist target"


def test_built_wheel_actually_contains_the_spa(tmp_path):
    """Build the real distributions and look inside them.

    Regression for a wheel that shipped with no web app despite a staged SPA and
    a declared artifact: ``python -m build`` builds the wheel from the sdist, so
    an sdist omission silently emptied the wheel. A config-string assertion could
    not catch that — only opening the archive can.

    Skipped unless the SPA has been staged (``scripts/stage_webapp.sh``), since a
    plain dev checkout legitimately has no built app.
    """
    repo = Path(__file__).resolve().parents[2]
    staged = repo / "core" / "domain_foundry_core" / "_webapp" / "index.html"
    if not staged.is_file():
        pytest.skip("SPA not staged; run scripts/stage_webapp.sh (release-only step)")

    proc = subprocess.run(
        [sys.executable, "-m", "build", "--outdir", str(tmp_path)],
        cwd=repo,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        pytest.skip(f"build backend unavailable: {proc.stderr.strip()[-200:]}")

    wheels = sorted(tmp_path.glob("*.whl"))
    assert wheels, "no wheel produced"
    names = zipfile.ZipFile(wheels[-1]).namelist()
    assert any("_webapp/index.html" in n for n in names), (
        "wheel has no SPA — `domain-foundry serve` would return JSON telling the "
        "user to `cd app`, in a directory a pipx install does not have"
    )
    assert any("_webapp/THIRD_PARTY_NOTICES.txt" in n for n in names), (
        "wheel has no bundled JavaScript license notices"
    )
    assert any("_bundled/food/pack.yaml" in n for n in names), "wheel has no packs"
    assert any("foundry/_knowledge/source-registry.yaml" in n for n in names), (
        "wheel has no foundry knowledge registry"
    )
    assert any("foundry/_golden/sourdough-lab.foundry.yaml" in n for n in names), (
        "wheel has no foundry golden specs"
    )


def test_pack_add_resolves_a_bundled_name(tmp_path):
    """Installed from a wheel there is no ``packs/`` dir to point at, so the
    documented `pack add packs/food` has to resolve as a name."""
    from domain_foundry_core.cli import _resolve_pack_source

    assert _resolve_pack_source("food").name == "food"
    assert _resolve_pack_source("packs/food").name == "food"

    explicit = tmp_path / "mypack"
    explicit.mkdir()
    assert _resolve_pack_source(str(explicit)) == explicit
