#!/usr/bin/env python3
"""Release-blocking audit for the evidence-backed Foundry product path."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import subprocess
import tempfile
from pathlib import Path

from domain_foundry_core.foundry import FoundryCompiler, load_golden_specs

ROOT = Path(__file__).resolve().parents[1]
PROTOTYPES = ROOT / "docs" / "prototypes"
REQUIRED_BUNDLE = {
    "README.md",
    "app.html",
    "evidence.json",
    "foundry-spec.json",
    "schema.sql",
}


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def audit() -> list[str]:
    failures: list[str] = []
    specs = load_golden_specs()
    if len(specs) != 3:
        failures.append(f"expected exactly three golden specs, found {len(specs)}")
        return failures

    distinct_contracts = {
        "visual worlds": {spec.experience.visual_world.id for spec in specs},
        "navigation topologies": {spec.experience.navigation.topology for spec in specs},
        "primary views": {spec.experience.navigation.primary_view for spec in specs},
        "entity graphs": {
            tuple((entity.id, entity.kind) for entity in spec.domain.entities)
            for spec in specs
        },
        "region compositions": {
            tuple(region.kind for view in spec.experience.views for region in view.regions)
            for spec in specs
        },
    }
    for label, values in distinct_contracts.items():
        if len(values) != 3:
            failures.append(f"goldens do not have three distinct {label}")

    compiler = FoundryCompiler()
    with tempfile.TemporaryDirectory(prefix="foundry-audit-") as raw_tmp:
        tmp = Path(raw_tmp)
        for spec in specs:
            for source in spec.source_snapshots:
                if source.status not in {"approved", "reference_only"}:
                    failures.append(f"{spec.id}: unusable source snapshot {source.id}")
                if not source.license or not source.allowed_uses:
                    failures.append(f"{spec.id}: incomplete license posture for {source.id}")

            if any(case.authored_by not in {"user", "domain_expert", "independent_reviewer", "standard"} for case in spec.evaluation.cases):
                failures.append(f"{spec.id}: generator-authored evaluation case")
            if not {"schema", "task", "accessibility", "security"} <= {
                case.kind for case in spec.evaluation.cases
            }:
                failures.append(f"{spec.id}: evaluation lacks an independent discipline")

            first = compiler.compile(
                spec,
                tmp / f"{spec.id}-one",
                generated_at="2026-08-19T12:00:00Z",
            )
            second = compiler.compile(
                spec,
                tmp / f"{spec.id}-two",
                generated_at="2026-08-19T12:00:00Z",
            )
            first_hashes = {path.name: _digest(path) for path in first.root.iterdir()}
            second_hashes = {path.name: _digest(path) for path in second.root.iterdir()}
            if first_hashes != second_hashes:
                failures.append(f"{spec.id}: same spec did not produce identical artifacts")

            receipt = json.loads(first.receipt.read_text(encoding="utf-8"))
            if set(receipt.get("artifacts", {})) != REQUIRED_BUNDLE:
                failures.append(f"{spec.id}: receipt does not cover the owned bundle")
            for name, expected in receipt.get("artifacts", {}).items():
                if _digest(first.root / name) != expected:
                    failures.append(f"{spec.id}: receipt hash mismatch for {name}")

            connection = sqlite3.connect(":memory:")
            try:
                connection.executescript(first.schema.read_text(encoding="utf-8"))
                if connection.execute("PRAGMA foreign_keys").fetchone() != (1,):
                    failures.append(f"{spec.id}: generated schema did not enable foreign keys")
                integrity = connection.execute("PRAGMA integrity_check").fetchone()
                if integrity != ("ok",):
                    failures.append(f"{spec.id}: generated schema failed integrity_check")
                foreign_keys = sum(
                    len(connection.execute(f"PRAGMA foreign_key_list('{table}')").fetchall())
                    for (table,) in connection.execute(
                        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
                    )
                )
                if foreign_keys < len(spec.domain.relationships):
                    failures.append(
                        f"{spec.id}: {foreign_keys} stored foreign keys for "
                        f"{len(spec.domain.relationships)} relationships"
                    )
            finally:
                connection.close()

            html = first.app.read_text(encoding="utf-8")
            required_html = {
                '<html lang="en">': "document language",
                'class="skip"': "skip link",
                'id="main"': "main landmark target",
                'aria-live="polite"': "status announcement",
                "prefers-reduced-motion": "reduced-motion behavior",
                "Why this app": "decision explanation",
                "Export backup": "owned-data exit",
                "Restore backup": "validated owned-data restore",
                "localStorage": "offline local persistence",
                'case "chart"': "typed chart renderer",
                'case "comparison"': "typed comparison renderer",
                'operation === "reveal"': "typed action dispatch",
                "_superseded_by": "immutable revision history",
                "Content-Security-Policy": "content security policy",
                "connect-src 'none'": "offline network boundary",
                "_source_records": "inspectable source provenance",
            }
            for needle, label in required_html.items():
                if needle not in html:
                    failures.append(f"{spec.id}: app lacks {label}")
            snapshot = json.loads(first.evidence.read_text(encoding="utf-8"))
            if not any(
                isinstance(source.get("url"), str) and source["url"] in html
                for source in snapshot["sources"]
            ):
                failures.append(f"{spec.id}: app does not link frozen source provenance")

    prototype_paths = [
        PROTOTYPES / "foundry-flow.html",
        PROTOTYPES / "knowledge-fabric.html",
    ]
    before = {path: _digest(path) if path.is_file() else None for path in prototype_paths}
    process = subprocess.run(
        [str(ROOT / ".venv" / "bin" / "python"), "scripts/build_foundry_prototypes.py"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    if process.returncode != 0:
        failures.append(f"prototype build failed: {process.stderr.strip()[-300:]}")
    else:
        after = {path: _digest(path) if path.is_file() else None for path in prototype_paths}
        if before != after:
            failures.append("committed prototypes were stale; rebuild and commit them")
        for path in prototype_paths:
            text = path.read_text(encoding="utf-8") if path.is_file() else ""
            for spec in specs:
                if spec.id not in text:
                    failures.append(f"{path.name}: missing golden {spec.id}")
    return failures


def main() -> int:
    failures = audit()
    if failures:
        print("foundry audit FAILED")
        for failure in failures:
            print(f"- {failure}")
        return 1
    print("foundry audit OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
