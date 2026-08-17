#!/usr/bin/env python3
"""Run the deterministic pack-author conformance contract.

This is intentionally local and side-effect free for the author's checkout:
the lifecycle proof uses a temporary workspace, while validation and routing
read only the supplied pack directory.  The JSON shape is stable enough for CI
and human review.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import tempfile
from pathlib import Path
from typing import Any

from domain_foundry_core.packs.loader import load_pack
from domain_foundry_core.packs.models import RoutingExample
from domain_foundry_core.packs.registry import PackRegistry
from domain_foundry_core.paths import Workspace
from domain_foundry_core.routing.l1 import L1Matcher


def _routing_check(pack: Any) -> dict[str, Any]:
    matcher = L1Matcher([pack])
    cases: list[tuple[str, dict[str, Any], bool]] = []
    for example in pack.routing.examples:
        cases.append((example.text, example.expect or {}, True))
    for raw in pack.routing.negative_examples:
        example = raw if isinstance(raw, RoutingExample) else RoutingExample.model_validate(raw)
        cases.append((example.text, example.expect or {}, False))

    failures: list[dict[str, Any]] = []
    for text, expected, positive in cases:
        result = matcher.match(text)
        object_name = expected.get("object")
        matched = any(hit.object_type == object_name for hit in result.hits)
        passed = matched if positive and object_name else (not result.hits if not positive and expected.get("unmatched") else True)
        if object_name in pack.objects:
            operation = expected.get("operation", "create")
            passed = passed and operation in pack.operations.get(object_name, [])
        if not passed:
            failures.append(
                {
                    "text": text,
                    "expected": expected,
                    "hits": sorted({hit.object_type for hit in result.hits}),
                }
            )
    return {
        "total": len(cases),
        "passed": len(cases) - len(failures),
        "failures": failures,
    }


def _fixture_check(pack: Any) -> dict[str, Any]:
    fixture = pack.root / "evals" / "fixtures.jsonl"
    if not fixture.is_file():
        return {"available": False, "total": 0, "passed": 0, "failures": []}
    matcher = L1Matcher([pack])
    failures: list[dict[str, Any]] = []
    total = 0
    for line_number, line in enumerate(fixture.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        total += 1
        case = json.loads(line)
        expected = case.get("expected") or {}
        captures = expected.get("captures") or []
        for capture in captures:
            if capture.get("domain", pack.name) != pack.name:
                continue
            object_name = capture.get("object_type")
            if not object_name:
                continue
            result = matcher.match(str(case.get("raw_text") or ""))
            if not any(hit.object_type == object_name for hit in result.hits):
                failures.append(
                    {
                        "line": line_number,
                        "object": object_name,
                        "text": str(case.get("raw_text") or ""),
                    }
                )
    return {"available": True, "total": total, "passed": total - len(failures), "failures": failures}


def _lifecycle_check(source: Path, pack: Any) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="domain-foundry-pack-") as raw:
        home = Path(raw) / "home"
        registry = PackRegistry(Workspace(home))
        preview = registry.preview(source)
        installed = registry.install(source)
        activated = registry.activate(pack.name)
        export_dir = Path(raw) / "export"
        exported = registry.export(pack.name, export_dir)
        removed = registry.uninstall(pack.name)
        table_name = f"{pack.name}__{next(iter(pack.objects))}"
        with sqlite3.connect(home / "db" / "domains.sqlite") as connection:
            orphan = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
                (table_name,),
            ).fetchone()
        passed = (
            preview.get("valid") is True
            and installed.get("status") == "installed"
            and activated.name == pack.name
            and exported.get("status") == "exported"
            and export_dir.joinpath("pack.yaml").is_file()
            and removed.get("status") == "uninstalled"
            and orphan is None
        )
        return {
            "passed": passed,
            "steps": [
                preview.get("valid") is True,
                installed.get("status") == "installed",
                activated.name == pack.name,
                exported.get("status") == "exported",
                removed.get("status") == "uninstalled",
            ],
            "orphan_tables": [] if orphan is None else [table_name],
        }


def run(pack_dir: Path) -> dict[str, Any]:
    source = pack_dir.expanduser().resolve()
    report: dict[str, Any] = {
        "format": "domain-foundry-pack-conformance/1",
        "pack": source.name,
        "status": "fail",
        "checks": {},
    }
    try:
        pack = load_pack(source, validate=True)
        routing = _routing_check(pack)
        fixtures = _fixture_check(pack)
        lifecycle = _lifecycle_check(source, pack)
        report["pack"] = pack.name
        report["checks"] = {
            "deep_validation": {"passed": True},
            "routing": routing,
            "fixtures": fixtures,
            "lifecycle": lifecycle,
        }
        fixture_ok = not fixtures["available"] or not fixtures["failures"]
        report["status"] = "pass" if not routing["failures"] and fixture_ok and lifecycle["passed"] else "fail"
    except Exception as exc:  # noqa: BLE001 - report hostile author input as JSON
        report["checks"] = {
            "deep_validation": {
                "passed": False,
                "error": f"{type(exc).__name__}: {exc}",
            }
        }
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Conform a declarative Domain Pack")
    parser.add_argument("pack", type=Path, help="pack directory to validate")
    args = parser.parse_args()
    report = run(args.pack)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
