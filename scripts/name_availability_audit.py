#!/usr/bin/env python3
"""Fail when preliminary public-name evidence is stale, incomplete, or misleading."""

from __future__ import annotations

import argparse
import re
import subprocess
from datetime import date
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import yaml

ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = ROOT / "release" / "name-availability.yaml"
EXPECTED_PYPI = {
    "domain-foundry",
    "domain-foundry-core",
    "domain-foundry-mcp",
    "domain-foundry-telegram",
    "domain-foundry-hermes-agent",
}
EXPECTED_REPOSITORY = "finnqiao/domain_foundry"


def _load(path: Path) -> dict[str, Any]:
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise ValueError(f"{path}: expected a mapping")
    return document


def _origin_url() -> str:
    result = subprocess.run(
        ["git", "remote", "get-url", "origin"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _github_full_name(origin: str) -> str | None:
    match = re.search(r"github\.com[/:]([^/]+/[^/]+?)(?:\.git)?$", origin)
    return match.group(1) if match else None


def audit(
    *,
    as_of: date | None = None,
    path: Path = REGISTRY_PATH,
    origin_url: str | None = None,
) -> list[str]:
    today = as_of or date.today()
    errors: list[str] = []
    document = _load(path)
    if document.get("schema_version") != 1:
        errors.append("name availability registry schema_version must be 1")
    if document.get("public_name") != "Domain Foundry":
        errors.append("name registry must describe the provisional name Domain Foundry")
    try:
        checked_at = date.fromisoformat(str(document.get("checked_at")))
    except ValueError:
        errors.append("checked_at must be ISO YYYY-MM-DD")
        checked_at = today
    freshness = document.get("freshness_days")
    if isinstance(freshness, bool) or not isinstance(freshness, int) or freshness < 1:
        errors.append("freshness_days must be a positive integer")
    else:
        age = (today - checked_at).days
        if age < 0:
            errors.append("checked_at is in the future")
        elif age > freshness:
            errors.append(f"name availability evidence is stale by {age - freshness} days")

    pypi = document.get("pypi")
    rows = pypi.get("distributions") if isinstance(pypi, dict) else None
    if not isinstance(rows, list):
        errors.append("pypi.distributions must be a list")
    else:
        by_name: dict[str, dict[str, Any]] = {}
        for index, row in enumerate(rows):
            if not isinstance(row, dict) or not isinstance(row.get("name"), str):
                errors.append(f"pypi.distributions[{index}] must name a distribution")
                continue
            name = row["name"]
            if name in by_name:
                errors.append(f"duplicate PyPI distribution {name}")
            by_name[name] = row
            expected_url = f"https://pypi.org/pypi/{name}/json"
            if row.get("official_source") != expected_url:
                errors.append(f"{name}: official PyPI endpoint is incorrect")
            if row.get("status") != "no_public_project" or row.get("http_status") != 404:
                errors.append(
                    f"{name}: 404 evidence must be recorded as no_public_project"
                )
        if set(by_name) != EXPECTED_PYPI:
            errors.append(
                f"PyPI evidence must cover exactly {sorted(EXPECTED_PYPI)}"
            )
        interpretation = pypi.get("interpretation") if isinstance(pypi, dict) else None
        if not isinstance(interpretation, str) or "does not reserve" not in interpretation:
            errors.append("PyPI 404 limitations must explicitly say names are not reserved")

    github = document.get("github")
    organization = (
        github.get("requested_organization") if isinstance(github, dict) else None
    )
    if not isinstance(organization, dict):
        errors.append("github.requested_organization must be a mapping")
    else:
        if organization.get("handle") != "Domain-Foundry":
            errors.append("requested GitHub organization handle is incorrect")
        if organization.get("status") != "occupied" or organization.get(
            "http_status"
        ) != 200:
            errors.append("Domain-Foundry GitHub organization must be recorded as occupied")
        if organization.get("ownership") != "unverified":
            errors.append("GitHub organization ownership must remain unverified")
        source = urlparse(str(organization.get("official_source")))
        if source.scheme != "https" or source.netloc != "api.github.com":
            errors.append("GitHub organization evidence must use the official API")

    repository = github.get("current_repository") if isinstance(github, dict) else None
    if not isinstance(repository, dict):
        errors.append("github.current_repository must be a mapping")
    elif repository.get("full_name") != EXPECTED_REPOSITORY:
        errors.append(f"current repository must be {EXPECTED_REPOSITORY}")
    resolved_origin = _github_full_name(origin_url if origin_url is not None else _origin_url())
    if resolved_origin != EXPECTED_REPOSITORY:
        errors.append(
            f"Git origin resolves to {resolved_origin!r}; expected {EXPECTED_REPOSITORY!r}"
        )

    trademark = document.get("trademark")
    if not isinstance(trademark, dict):
        errors.append("trademark collision evidence must be a mapping")
    else:
        findings = trademark.get("findings")
        if not isinstance(findings, list) or not findings:
            errors.append("trademark evidence must record the exact-mark finding")
        else:
            finding = findings[0]
            if not isinstance(finding, dict):
                errors.append("trademark finding must be a mapping")
            else:
                expected = {
                    "mark": "DOMAIN FOUNDRY",
                    "jurisdiction": "US",
                    "serial_number": "99880503",
                    "owner": "Semantic Foundry LLC",
                    "filing_date": "2026-06-11",
                    "status": "live_application_awaiting_examination",
                    "service_overlap": "direct",
                    "official_status_source": (
                        "https://tsdr.uspto.gov/statusview/sn99880503"
                    ),
                }
                for field, value in expected.items():
                    if finding.get(field) != value:
                        errors.append(f"trademark finding has incorrect {field}")
        if trademark.get("release_risk") != "material_exact_mark_and_service_overlap":
            errors.append("trademark evidence must record the material overlap")
        if trademark.get("disposition") != "unresolved":
            errors.append("unresolved trademark collision cannot be marked resolved")
        if trademark.get("release_blocking") is not True:
            errors.append("exact-mark service overlap must remain release-blocking")

    limitations = document.get("limitations")
    joined = " ".join(str(item).lower() for item in limitations or [])
    for required in ("not reserved", "trademark", "recheck"):
        if required not in joined:
            errors.append(f"name evidence limitations must mention {required!r}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--as-of", type=date.fromisoformat)
    parser.add_argument("--registry", type=Path, default=REGISTRY_PATH)
    args = parser.parse_args()
    try:
        errors = audit(as_of=args.as_of, path=args.registry.resolve())
    except (OSError, ValueError, yaml.YAMLError, subprocess.CalledProcessError) as exc:
        print(f"name availability audit ERROR: {exc}")
        return 2
    if errors:
        print("name availability audit FAILED")
        for error in errors:
            print(f"- {error}")
        return 1
    print("name availability audit OK (material trademark collision remains release-blocking)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
