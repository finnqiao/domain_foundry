from __future__ import annotations

import json
import sqlite3

import pytest

from domain_foundry_core.foundry.compiler import FoundryCompiler
from domain_foundry_core.foundry.loader import load_golden_specs


@pytest.mark.parametrize("spec", load_golden_specs(), ids=lambda spec: spec.id)
def test_golden_spec_compiles_to_owned_bundle(spec, tmp_path) -> None:
    artifact = FoundryCompiler().compile(
        spec,
        tmp_path / spec.id,
        generated_at="2026-08-19T12:00:00Z",
    )

    assert artifact.app == artifact.root / "app.html"
    assert "FoundrySpec 1.0" in artifact.schema.read_text(encoding="utf-8")
    html = artifact.app.read_text(encoding="utf-8")
    assert spec.id in html
    assert spec.experience.visual_world.id in html
    assert "localStorage" in html
    assert "Export backup" in html
    assert "Restore backup" in html
    assert "Why this app" in html
    assert 'case "chart"' in html
    assert 'case "comparison"' in html
    assert 'operation === "reveal"' in html
    assert "sample_overrides" in html
    assert "_superseded_by" in html
    assert 'backup_format: "foundry-owned-app"' in html
    assert "Content-Security-Policy" in html
    assert "connect-src 'none'" in html
    assert "_source_records" in html

    evidence = json.loads(artifact.evidence.read_text(encoding="utf-8"))
    assert any(source["url"] in html for source in evidence["sources"])
    assert {source["id"] for source in evidence["sources"]} == set(spec.source_ids)
    assert {item["id"] for item in evidence["principles"]} == set(spec.principle_ids)

    receipt = json.loads(artifact.receipt.read_text(encoding="utf-8"))
    assert receipt["generated_at"] == "2026-08-19T12:00:00Z"
    assert set(receipt["artifacts"]) == {
        "README.md",
        "app.html",
        "evidence.json",
        "foundry-spec.json",
        "schema.sql",
    }


@pytest.mark.parametrize("spec", load_golden_specs(), ids=lambda spec: spec.id)
def test_compiled_schema_is_executable_and_enforces_foreign_keys(spec) -> None:
    ddl = FoundryCompiler().compile_ddl(spec)
    connection = sqlite3.connect(":memory:")
    connection.executescript(ddl)
    assert connection.execute("PRAGMA foreign_keys").fetchone() == (1,)
    foreign_keys = sum(
        len(connection.execute(f"PRAGMA foreign_key_list('{table}')").fetchall())
        for (table,) in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
        )
    )
    assert foreign_keys >= 4


def test_compiler_refuses_to_overwrite_an_owned_bundle(tmp_path) -> None:
    spec = load_golden_specs()[0]
    destination = tmp_path / "owned"
    compiler = FoundryCompiler()
    compiler.compile(spec, destination)
    with pytest.raises(FileExistsError, match="refusing to overwrite existing"):
        compiler.compile(spec, destination)


def test_compiler_does_not_publish_a_partial_bundle(tmp_path, monkeypatch) -> None:
    spec = load_golden_specs()[0]
    destination = tmp_path / "never-visible-partial"
    compiler = FoundryCompiler()

    def fail_readme(_spec):  # type: ignore[no-untyped-def]
        raise RuntimeError("synthetic compiler failure")

    monkeypatch.setattr(compiler, "render_readme", fail_readme)
    with pytest.raises(RuntimeError, match="synthetic compiler failure"):
        compiler.compile(spec, destination)

    assert not destination.exists()
    assert not list(tmp_path.glob(".never-visible-partial.staging-*"))


def test_compiler_runtime_is_a_packaged_source_not_an_inline_second_implementation() -> None:
    from domain_foundry_core.foundry.compiler import DEFAULT_RUNTIME

    runtime = DEFAULT_RUNTIME.read_text(encoding="utf-8")
    assert "__RUNTIME_NEXT__" not in runtime
    assert 'case "chart"' in runtime
    assert "sanitizeStore" in runtime
    assert "sample_overrides" in runtime
