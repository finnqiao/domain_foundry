"""The quickstart promises a web app from `pipx install domain-foundry-core`.

A wheel has no repo checkout, so the SPA has to be found inside the package
(staged there by scripts/stage_webapp.sh) or the promise silently degrades to a
JSON blob telling the user to `cd app`, in a directory they do not have.
"""

from __future__ import annotations

from pathlib import Path

from domain_foundry_core.api import app as app_mod


def _write_spa(root: Path) -> Path:
    (root / "assets").mkdir(parents=True)
    (root / "index.html").write_text("<!doctype html><title>DF</title>", encoding="utf-8")
    (root / "assets" / "index.js").write_text("//", encoding="utf-8")
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


def test_wheel_config_ships_the_staged_webapp():
    """hatchling excludes gitignored paths unless they are declared artifacts."""
    pyproject = Path(__file__).resolve().parents[2] / "pyproject.toml"
    assert "core/domain_foundry_core/_webapp/**" in pyproject.read_text(encoding="utf-8")


def test_pack_add_resolves_a_bundled_name(tmp_path):
    """Installed from a wheel there is no ``packs/`` dir to point at, so the
    documented `pack add packs/food` has to resolve as a name."""
    from domain_foundry_core.cli import _resolve_pack_source

    assert _resolve_pack_source("food").name == "food"
    assert _resolve_pack_source("packs/food").name == "food"

    explicit = tmp_path / "mypack"
    explicit.mkdir()
    assert _resolve_pack_source(str(explicit)) == explicit
