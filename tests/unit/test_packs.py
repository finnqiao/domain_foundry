from __future__ import annotations

from pathlib import Path

import pytest

from domain_foundry_core.packs.loader import PackValidationError, load_pack
from domain_foundry_core.packs.schema_compiler import compile_ddl, field_contract

REPO = Path(__file__).resolve().parents[2]


def test_load_plants_and_sourdough():
    for name in ("plants", "sourdough"):
        pack = load_pack(REPO / "packs" / name, validate=True)
        assert pack.name == name
        assert len(pack.routing.examples) >= 8
        ddl = compile_ddl(pack)
        assert f"{name}__" in ddl
        contract = field_contract(pack)
        assert contract


def test_template_fails_until_renamed_examples_ok():
    # template is valid as-is (≥8 examples)
    pack = load_pack(REPO / "packs" / "_template", validate=True)
    assert pack.name == "example"


def test_invalid_pack_too_few_examples(tmp_path: Path):
    src = REPO / "packs" / "_template"
    dest = tmp_path / "bad"
    import shutil

    shutil.copytree(src, dest)
    routing = dest / "routing.yaml"
    text = routing.read_text(encoding="utf-8")
    # wipe examples
    routing.write_text(
        "rules: []\nexamples:\n  - text: only one\n    expect: {}\nnegative_examples: []\n",
        encoding="utf-8",
    )
    with pytest.raises(PackValidationError):
        load_pack(dest, validate=True)
    _ = text
