from __future__ import annotations

import importlib.util
from copy import deepcopy
from datetime import date
from pathlib import Path

import yaml


def _module():  # type: ignore[no-untyped-def]
    path = Path(__file__).resolve().parents[2] / "scripts" / "name_availability_audit.py"
    spec = importlib.util.spec_from_file_location("name_availability_audit", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


AUDIT = _module()
ORIGIN = "https://github.com/finnqiao/domain_foundry.git"


def test_current_name_evidence_is_honest_and_current() -> None:
    assert AUDIT.audit(as_of=date(2026, 8, 19), origin_url=ORIGIN) == []


def test_name_evidence_expires_quickly() -> None:
    errors = AUDIT.audit(as_of=date(2026, 8, 27), origin_url=ORIGIN)
    assert any("stale" in error for error in errors)


def test_pypi_404_cannot_be_described_as_reserved_or_claimable(tmp_path: Path) -> None:
    document = yaml.safe_load(AUDIT.REGISTRY_PATH.read_text(encoding="utf-8"))
    changed = deepcopy(document)
    changed["pypi"]["distributions"][0]["status"] = "available_and_reserved"
    path = tmp_path / "names.yaml"
    path.write_text(yaml.safe_dump(changed, sort_keys=False), encoding="utf-8")

    errors = AUDIT.audit(
        as_of=date(2026, 8, 19), path=path, origin_url=ORIGIN
    )
    assert any("no_public_project" in error for error in errors)


def test_existing_github_organization_cannot_be_recorded_as_available(
    tmp_path: Path,
) -> None:
    document = yaml.safe_load(AUDIT.REGISTRY_PATH.read_text(encoding="utf-8"))
    changed = deepcopy(document)
    changed["github"]["requested_organization"]["status"] = "available"
    path = tmp_path / "names.yaml"
    path.write_text(yaml.safe_dump(changed, sort_keys=False), encoding="utf-8")

    errors = AUDIT.audit(
        as_of=date(2026, 8, 19), path=path, origin_url=ORIGIN
    )
    assert any("recorded as occupied" in error for error in errors)


def test_exact_mark_collision_cannot_be_silently_cleared(tmp_path: Path) -> None:
    document = yaml.safe_load(AUDIT.REGISTRY_PATH.read_text(encoding="utf-8"))
    changed = deepcopy(document)
    changed["trademark"]["release_blocking"] = False
    changed["trademark"]["disposition"] = "clear"
    path = tmp_path / "names.yaml"
    path.write_text(yaml.safe_dump(changed, sort_keys=False), encoding="utf-8")

    errors = AUDIT.audit(
        as_of=date(2026, 8, 19), path=path, origin_url=ORIGIN
    )
    assert any("cannot be marked resolved" in error for error in errors)
    assert any("must remain release-blocking" in error for error in errors)


def test_registry_must_match_the_real_git_origin() -> None:
    errors = AUDIT.audit(
        as_of=date(2026, 8, 19),
        origin_url="git@github.com:someone-else/domain_foundry.git",
    )
    assert any("Git origin resolves" in error for error in errors)
