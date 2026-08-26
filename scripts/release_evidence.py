#!/usr/bin/env python3
"""Create a machine-readable receipt for an exact release-candidate run."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import subprocess
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from domain_foundry_core.llm.providers import all_providers

try:
    from dependency_license_audit import (
        NOTICES_PATH,
        POLICY_PATH,
        npm_runtime_packages,
        python_runtime_packages,
    )
except ModuleNotFoundError:  # imported as scripts.release_evidence in tests
    from scripts.dependency_license_audit import (
        NOTICES_PATH,
        POLICY_PATH,
        npm_runtime_packages,
        python_runtime_packages,
    )

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE_ROOT = ROOT / "release" / "evidence"
DIST = ROOT / "dist"

EXPECTED_LOG_MARKERS = {
    "release_audit": "release audit OK",
    "build_release": "release artifacts ready in dist/",
    "clean_machine": "CLEAN MACHINE GATE: PASS",
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def display_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return str(path.resolve())


def _git(*args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def repository_files() -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    )
    paths: list[Path] = []
    for raw in result.stdout.split(b"\0"):
        if not raw:
            continue
        relative = Path(raw.decode("utf-8"))
        if relative.parts[:2] == ("release", "evidence"):
            continue
        path = ROOT / relative
        if path.is_file() and not path.is_symlink():
            paths.append(relative)
    return sorted(paths, key=lambda path: path.as_posix())


def source_tree_sha256() -> str:
    """Hash every tracked or unignored source file, independent of Git metadata."""
    digest = hashlib.sha256()
    for relative in repository_files():
        encoded = relative.as_posix().encode("utf-8")
        digest.update(len(encoded).to_bytes(8, "big"))
        digest.update(encoded)
        content = (ROOT / relative).read_bytes()
        digest.update(len(content).to_bytes(8, "big"))
        digest.update(content)
    return digest.hexdigest()


def _one(pattern: str, *, root: Path = DIST) -> Path:
    matches = sorted(root.glob(pattern))
    if len(matches) != 1:
        raise RuntimeError(f"expected exactly one {pattern!r} in {root}, found {len(matches)}")
    return matches[0]


def artifact_record(path: Path) -> dict[str, Any]:
    return {
        "path": display_path(path),
        "sha256": sha256_file(path),
        "bytes": path.stat().st_size,
    }


def _version(command: list[str]) -> str:
    try:
        result = subprocess.run(command, check=True, capture_output=True, text=True)
    except (OSError, subprocess.CalledProcessError):
        return "unavailable"
    return (result.stdout or result.stderr).strip().splitlines()[0]


def _log_record(path: Path, marker: str) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8", errors="replace")
    if marker not in text:
        raise RuntimeError(f"{path} does not contain required success marker {marker!r}")
    return {
        "path": display_path(path),
        "sha256": sha256_file(path),
        "success_marker": marker,
    }


def _corpus_counts() -> tuple[int, int]:
    registry = yaml.safe_load((ROOT / "knowledge" / "source-registry.yaml").read_text())
    sources = registry.get("sources") if isinstance(registry, dict) else None
    if not isinstance(sources, list):
        raise RuntimeError("knowledge registry has no source list")
    principles = 0
    for path in sorted((ROOT / "knowledge" / "principles").glob("*.yaml")):
        document = yaml.safe_load(path.read_text())
        rows = document.get("principles") if isinstance(document, dict) else None
        if not isinstance(rows, list):
            raise RuntimeError(f"{path} has no principle list")
        principles += len(rows)
    return len(sources), principles


def _goldens() -> list[dict[str, str]]:
    records: list[dict[str, str]] = []
    for path in sorted((ROOT / "examples" / "golden").glob("*.foundry.yaml")):
        document = yaml.safe_load(path.read_text())
        if not isinstance(document, dict) or not isinstance(document.get("id"), str):
            raise RuntimeError(f"{path} has no id")
        records.append(
            {
                "id": document["id"],
                "path": path.relative_to(ROOT).as_posix(),
                "sha256": sha256_file(path),
            }
        )
    if len(records) != 3:
        raise RuntimeError(f"expected three golden specs, found {len(records)}")
    return records


def _provider_defaults() -> dict[str, Any]:
    network_ids = {"anthropic", "openai", "deepseek", "openrouter"}
    registry_path = ROOT / "release" / "provider-compatibility.yaml"
    return {
        "registry_sha256": sha256_file(registry_path),
        "defaults": [
            {
                "id": provider.id,
                "base_url": provider.base_url,
                "routine_model": provider.routine_model,
                "sota_model": provider.sota_model,
            }
            for provider in all_providers()
            if provider.id in network_ids
        ],
    }


def _license_evidence() -> dict[str, Any]:
    return {
        "policy_sha256": sha256_file(POLICY_PATH),
        "third_party_notices_sha256": sha256_file(NOTICES_PATH),
        "python_runtime_dependencies": len(python_runtime_packages()),
        "npm_bundled_occurrences": len(npm_runtime_packages()),
    }


def _naming_evidence() -> dict[str, Any]:
    path = ROOT / "release" / "name-availability.yaml"
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise RuntimeError("name availability registry must contain one mapping")
    pypi = document.get("pypi")
    distributions = pypi.get("distributions") if isinstance(pypi, dict) else None
    github = document.get("github")
    if not isinstance(distributions, list) or not isinstance(github, dict):
        raise RuntimeError("name availability registry is incomplete")
    return {
        "registry_sha256": sha256_file(path),
        "checked_at": document.get("checked_at"),
        "public_name": document.get("public_name"),
        "pypi": {
            row["name"]: row["status"]
            for row in distributions
            if isinstance(row, dict)
            and isinstance(row.get("name"), str)
            and isinstance(row.get("status"), str)
        },
        "github": {
            "requested_organization": github.get("requested_organization"),
            "current_repository": github.get("current_repository"),
        },
        "trademark": document.get("trademark"),
    }


def build_manifest(*, output: Path, logs: dict[str, Path]) -> dict[str, Any]:
    sources, principles = _corpus_counts()
    wheel = _one("*.whl")
    sdist = _one("*.tar.gz")
    sbom = _one("*.spdx.json")
    tree_hash = source_tree_sha256()
    status = _git("status", "--porcelain=v1", "--untracked-files=all")
    manifest: dict[str, Any] = {
        "schema_version": 1,
        "candidate_id": f"sha256:{tree_hash}",
        "generated_at": datetime.now(UTC).isoformat(),
        "product": "domain-foundry-core",
        "version": "0.1.0",
        "git": {
            "head": _git("rev-parse", "HEAD"),
            "branch": _git("branch", "--show-current"),
            "worktree_clean": not bool(status),
        },
        "source_tree_sha256": tree_hash,
        "artifacts": {
            "wheel": artifact_record(wheel),
            "sdist": artifact_record(sdist),
            "sbom": artifact_record(sbom),
        },
        "machine_gates": {
            name: _log_record(logs[name], marker)
            for name, marker in EXPECTED_LOG_MARKERS.items()
        },
        "knowledge": {
            "sources": sources,
            "principles": principles,
            "registry_sha256": sha256_file(ROOT / "knowledge" / "source-registry.yaml"),
        },
        "providers": _provider_defaults(),
        "licenses": _license_evidence(),
        "naming": _naming_evidence(),
        "goldens": _goldens(),
        "prototypes": {
            path.stem: artifact_record(path)
            for path in sorted((ROOT / "docs" / "prototypes").glob("*.html"))
        },
        "environment": {
            "platform": platform.platform(),
            "python": platform.python_version(),
            "node": _version(["node", "--version"]),
            "npm": _version(["npm", "--version"]),
        },
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=output.parent, delete=False
    ) as handle:
        json.dump(manifest, handle, indent=2, sort_keys=True)
        handle.write("\n")
        staged = Path(handle.name)
    staged.replace(output)
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=EVIDENCE_ROOT / "candidate.json")
    for name in EXPECTED_LOG_MARKERS:
        parser.add_argument(
            f"--{name.replace('_', '-')}-log",
            type=Path,
            default=EVIDENCE_ROOT / f"{name}.log",
        )
    args = parser.parse_args()
    logs = {
        name: getattr(args, f"{name}_log").resolve() for name in EXPECTED_LOG_MARKERS
    }
    manifest = build_manifest(output=args.output.resolve(), logs=logs)
    print(
        json.dumps(
            {
                "candidate_id": manifest["candidate_id"],
                "worktree_clean": manifest["git"]["worktree_clean"],
                "output": str(args.output.resolve()),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
