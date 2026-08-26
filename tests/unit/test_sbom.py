from __future__ import annotations

import importlib.util
from pathlib import Path


def _module():  # type: ignore[no-untyped-def]
    path = Path(__file__).resolve().parents[2] / "scripts" / "generate_sbom.py"
    spec = importlib.util.spec_from_file_location("generate_sbom", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_spdx_sbom_covers_the_shipped_runtime_with_resolved_licenses() -> None:
    payload = _module().generate(created="2026-08-19T12:00:00Z")
    assert payload["spdxVersion"] == "SPDX-2.3"
    assert payload["creationInfo"]["created"] == "2026-08-19T12:00:00Z"
    packages = {(item["name"], item["versionInfo"]) for item in payload["packages"]}
    assert ("domain-foundry-core", "0.1.0") in packages
    assert any(name == "fastapi" for name, _version in packages)
    assert any(name == "react" for name, _version in packages)
    assert any(name == "maplibre-gl" for name, _version in packages)
    assert not any(name == "pytest" for name, _version in packages)
    assert not any(name == "@axe-core/playwright" for name, _version in packages)
    assert all(
        item["licenseDeclared"] != "NOASSERTION"
        and item["licenseConcluded"] != "NOASSERTION"
        for item in payload["packages"]
    )
    assert len(payload["relationships"]) == len(payload["packages"]) - 1
