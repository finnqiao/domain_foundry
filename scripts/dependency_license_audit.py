#!/usr/bin/env python3
"""Audit shipped dependency licenses and deterministic third-party notices."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import tomllib
from datetime import date
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = ROOT / "release" / "dependency-licenses.yaml"
UV_LOCK = ROOT / "uv.lock"
NPM_LOCK = ROOT / "app" / "package-lock.json"
NOTICES_PATH = ROOT / "app" / "public" / "THIRD_PARTY_NOTICES.txt"
LICENSE_FILENAMES = {"license", "license.md", "license.txt", "copying", "copyright"}


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_yaml(path: Path) -> dict[str, Any]:
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise ValueError(f"{path}: expected a mapping")
    return document


def _extras(dependency: dict[str, Any]) -> tuple[str, ...]:
    value = dependency.get("extra", dependency.get("extras", []))
    if isinstance(value, str):
        return (value,)
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return tuple(value)
    return ()


def python_runtime_packages(path: Path = UV_LOCK) -> list[dict[str, str]]:
    """Return the cross-platform union shipped by the root runtime + extras."""
    lock = tomllib.loads(path.read_text(encoding="utf-8"))
    rows = lock.get("package")
    if not isinstance(rows, list):
        raise ValueError("uv.lock has no package list")
    by_name = {
        row.get("name"): row
        for row in rows
        if isinstance(row, dict) and isinstance(row.get("name"), str)
    }
    root = by_name.get("domain-foundry-core")
    if not isinstance(root, dict):
        raise ValueError("uv.lock does not contain domain-foundry-core")
    todo = [
        (dependency["name"], _extras(dependency))
        for dependency in root.get("dependencies", [])
        if isinstance(dependency, dict) and isinstance(dependency.get("name"), str)
    ]
    seen: set[str] = set()
    while todo:
        name, extras = todo.pop()
        if name in seen:
            continue
        package = by_name.get(name)
        if not isinstance(package, dict):
            raise ValueError(f"uv.lock dependency {name!r} has no package record")
        seen.add(name)
        dependencies = list(package.get("dependencies", []))
        optional = package.get("optional-dependencies", {})
        if isinstance(optional, dict):
            for extra in extras:
                dependencies.extend(optional.get(extra, []))
        for dependency in dependencies:
            if isinstance(dependency, dict) and isinstance(dependency.get("name"), str):
                todo.append((dependency["name"], _extras(dependency)))
    result: list[dict[str, str]] = []
    for name in sorted(seen):
        version = by_name[name].get("version")
        if not isinstance(version, str):
            raise ValueError(f"uv.lock runtime dependency {name!r} has no version")
        result.append({"name": name, "version": version})
    return result


def _npm_name(location: str) -> str:
    return location.rsplit("node_modules/", 1)[-1]


def npm_runtime_packages(path: Path = NPM_LOCK) -> list[dict[str, str]]:
    lock = json.loads(path.read_text(encoding="utf-8"))
    rows = lock.get("packages")
    if not isinstance(rows, dict):
        raise ValueError("package-lock.json has no packages mapping")
    result: list[dict[str, str]] = []
    for location, package in sorted(rows.items()):
        if (
            not location
            or "node_modules/" not in location
            or not isinstance(package, dict)
            or package.get("dev") is True
        ):
            continue
        result.append(
            {
                "location": location,
                "name": _npm_name(location),
                "version": str(package.get("version") or ""),
                "license": str(package.get("license") or "NOASSERTION"),
            }
        )
    return result


def load_policy(path: Path = POLICY_PATH) -> dict[str, Any]:
    return _load_yaml(path)


def _license_text(location: str) -> str:
    package_root = ROOT / "app" / location
    if not package_root.is_dir():
        raise FileNotFoundError(f"npm package directory is missing: {package_root}")
    candidates = sorted(
        path
        for path in package_root.iterdir()
        if path.is_file() and path.name.lower() in LICENSE_FILENAMES
    )
    if candidates:
        return candidates[0].read_text(encoding="utf-8", errors="replace").strip()
    readme = package_root / "README.md"
    if readme.is_file():
        text = readme.read_text(encoding="utf-8", errors="replace")
        match = re.search(r"(?im)^##+\s+License(?:\s+\([^\n]+\))?\s*$", text)
        if match:
            return text[match.end() :].strip()
    raise ValueError(f"{location}: no distributable license text found")


def render_notices(*, npm_lock: Path = NPM_LOCK) -> str:
    packages = npm_runtime_packages(npm_lock)
    grouped: dict[tuple[str, str, str, str], list[str]] = {}
    for package in packages:
        license_text = _license_text(package["location"])
        key = (
            package["name"],
            package["version"],
            package["license"],
            license_text,
        )
        grouped.setdefault(key, []).append(package["location"])
    lock_hash = sha256_file(npm_lock)
    sections = [
        "DOMAIN FOUNDRY THIRD-PARTY NOTICES",
        "==================================",
        "",
        "This file contains license notices for JavaScript dependencies bundled",
        "into the shipped web application. It is generated from the production",
        "dependency closure in app/package-lock.json.",
        "",
        f"package-lock.json SHA-256: {lock_hash}",
        f"Package occurrences: {len(packages)}",
        f"Unique notice records: {len(grouped)}",
    ]
    for (name, version, license_id, license_text), locations in sorted(grouped.items()):
        sections.extend(
            [
                "",
                "-" * 78,
                f"{name} {version} — {license_id}",
                f"Installed paths: {', '.join(sorted(locations))}",
                "-" * 78,
                license_text,
            ]
        )
    return "\n".join(sections).rstrip() + "\n"


def audit(
    *,
    as_of: date | None = None,
    policy_path: Path = POLICY_PATH,
    verify_source_texts: bool = False,
) -> tuple[list[str], dict[str, int]]:
    today = as_of or date.today()
    errors: list[str] = []
    policy = load_policy(policy_path)
    if policy.get("schema_version") != 1:
        errors.append("dependency license policy schema_version must be 1")
    try:
        reviewed_at = date.fromisoformat(str(policy.get("reviewed_at")))
    except ValueError:
        errors.append("dependency license reviewed_at must be ISO YYYY-MM-DD")
        reviewed_at = today
    freshness = policy.get("freshness_days")
    if isinstance(freshness, bool) or not isinstance(freshness, int) or freshness < 1:
        errors.append("dependency license freshness_days must be a positive integer")
    else:
        age = (today - reviewed_at).days
        if age < 0:
            errors.append("dependency license reviewed_at is in the future")
        elif age > freshness:
            errors.append(f"dependency license review is stale by {age - freshness} days")

    policy_rules = policy.get("policy")
    if not isinstance(policy_rules, dict):
        errors.append("dependency license policy rules must be a mapping")
        policy_rules = {}
    allowed = set(policy_rules.get("allowed_expressions") or [])
    denied = tuple(str(item).upper() for item in policy_rules.get("denied_tokens") or [])

    expected_python = {
        (row["name"], row["version"]) for row in python_runtime_packages()
    }
    reviewed_rows = policy.get("python_runtime")
    reviewed: dict[tuple[str, str], dict[str, Any]] = {}
    if not isinstance(reviewed_rows, list):
        errors.append("python_runtime must be a list")
        reviewed_rows = []
    for index, row in enumerate(reviewed_rows):
        if not isinstance(row, dict):
            errors.append(f"python_runtime[{index}] must be a mapping")
            continue
        name, version = row.get("name"), str(row.get("version") or "")
        if not isinstance(name, str) or not version:
            errors.append(f"python_runtime[{index}] requires name and version")
            continue
        key = (name, version)
        if key in reviewed:
            errors.append(f"duplicate Python license record {name}=={version}")
        reviewed[key] = row
        expression = str(row.get("license") or "NOASSERTION")
        if expression not in allowed:
            errors.append(f"{name}=={version}: license {expression!r} is not allowed")
        if any(token in expression.upper() for token in denied):
            errors.append(f"{name}=={version}: license {expression!r} matches deny policy")
        if not str(row.get("evidence") or "").strip():
            errors.append(f"{name}=={version}: license evidence is required")
    if set(reviewed) != expected_python:
        for name, version in sorted(expected_python - set(reviewed)):
            errors.append(f"unreviewed Python runtime dependency {name}=={version}")
        for name, version in sorted(set(reviewed) - expected_python):
            errors.append(f"stale Python license record {name}=={version}")

    npm_packages = npm_runtime_packages()
    for package in npm_packages:
        expression = package["license"]
        label = f"{package['name']}@{package['version']} ({package['location']})"
        if not package["version"]:
            errors.append(f"{label}: version is missing")
        if expression not in allowed:
            errors.append(f"{label}: license {expression!r} is not allowed")
        if any(token in expression.upper() for token in denied):
            errors.append(f"{label}: license {expression!r} matches deny policy")

    if not NOTICES_PATH.is_file():
        errors.append(f"missing {NOTICES_PATH.relative_to(ROOT)}")
    else:
        notices = NOTICES_PATH.read_text(encoding="utf-8")
        lock_marker = f"package-lock.json SHA-256: {sha256_file(NPM_LOCK)}"
        if lock_marker not in notices:
            errors.append("third-party notices do not match package-lock.json")
        for package in npm_packages:
            marker = f"{package['name']} {package['version']} — {package['license']}"
            if marker not in notices:
                errors.append(f"third-party notices omit {marker}")
        if verify_source_texts:
            expected_notices = render_notices()
            if notices != expected_notices:
                errors.append(
                    "third-party notices differ from installed production license texts; "
                    "run scripts/dependency_license_audit.py --write-notices"
                )

    project_metadata = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    if not (ROOT / "LICENSE").is_file() or 'license = "MIT"' not in project_metadata:
        errors.append("project MIT license declaration or LICENSE file is missing")
    return errors, {
        "python_runtime": len(expected_python),
        "npm_runtime_occurrences": len(npm_packages),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--as-of", type=date.fromisoformat)
    parser.add_argument("--policy", type=Path, default=POLICY_PATH)
    parser.add_argument("--verify-source-texts", action="store_true")
    parser.add_argument("--write-notices", action="store_true")
    args = parser.parse_args()
    try:
        if args.write_notices:
            NOTICES_PATH.parent.mkdir(parents=True, exist_ok=True)
            NOTICES_PATH.write_text(render_notices(), encoding="utf-8")
            print(f"wrote {NOTICES_PATH.relative_to(ROOT)}")
        errors, counts = audit(
            as_of=args.as_of,
            policy_path=args.policy.resolve(),
            verify_source_texts=args.verify_source_texts or args.write_notices,
        )
    except (OSError, ValueError, json.JSONDecodeError, tomllib.TOMLDecodeError) as exc:
        print(f"dependency license audit ERROR: {exc}")
        return 2
    if errors:
        print("dependency license audit FAILED")
        for error in errors:
            print(f"- {error}")
        return 1
    print(
        "dependency license audit OK "
        f"({counts['python_runtime']} Python runtime; "
        f"{counts['npm_runtime_occurrences']} npm bundled occurrences)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
