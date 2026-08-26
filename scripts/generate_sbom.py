#!/usr/bin/env python3
"""Generate an SPDX 2.3 JSON inventory from the committed Python and npm locks."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import tomllib
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

try:
    from dependency_license_audit import (
        NOTICES_PATH,
        NPM_LOCK,
        POLICY_PATH,
        UV_LOCK,
        load_policy,
        npm_runtime_packages,
        python_runtime_packages,
    )
except ModuleNotFoundError:  # imported as scripts.generate_sbom in tests
    from scripts.dependency_license_audit import (
        NOTICES_PATH,
        NPM_LOCK,
        POLICY_PATH,
        UV_LOCK,
        load_policy,
        npm_runtime_packages,
        python_runtime_packages,
    )

ROOT = Path(__file__).resolve().parents[1]
_SPDX_SAFE = re.compile(r"[^A-Za-z0-9.-]+")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _spdx_id(ecosystem: str, name: str, version: str, suffix: str = "") -> str:
    raw = f"{ecosystem}-{name}-{version}-{suffix}".strip("-")
    return "SPDXRef-" + _SPDX_SAFE.sub("-", raw).strip("-")


def _python_packages(path: Path, policy_path: Path) -> list[dict[str, Any]]:
    lock = tomllib.loads(path.read_text(encoding="utf-8"))
    by_name = {
        item.get("name"): item
        for item in lock.get("package", [])
        if isinstance(item, dict) and isinstance(item.get("name"), str)
    }
    policy = load_policy(policy_path)
    reviewed = {
        (str(item.get("name")), str(item.get("version"))): str(item.get("license"))
        for item in policy.get("python_runtime", [])
        if isinstance(item, dict)
    }
    packages: list[dict[str, Any]] = []
    for runtime in python_runtime_packages(path):
        name = runtime["name"]
        version = runtime["version"]
        item = by_name[name]
        license_id = reviewed.get((name, version))
        if not license_id:
            raise ValueError(f"no reviewed license for Python runtime {name}=={version}")
        package = {
            "SPDXID": _spdx_id("pypi", name, version),
            "name": name,
            "versionInfo": version,
            "downloadLocation": f"https://pypi.org/project/{name}/{version}/",
            "filesAnalyzed": False,
            "licenseConcluded": license_id,
            "licenseDeclared": license_id,
            "copyrightText": "NOASSERTION",
            "externalRefs": [
                {
                    "referenceCategory": "PACKAGE-MANAGER",
                    "referenceType": "purl",
                    "referenceLocator": f"pkg:pypi/{name}@{version}",
                }
            ],
            "comment": "Runtime closure from uv.lock; license resolved by release/dependency-licenses.yaml.",
        }
        hashes: list[str] = []
        for wheel in item.get("wheels", []):
            value = str(wheel.get("hash") or "")
            if value.startswith("sha256:"):
                hashes.append(value.removeprefix("sha256:"))
                break
        if not hashes:
            value = str((item.get("sdist") or {}).get("hash") or "")
            if value.startswith("sha256:"):
                hashes.append(value.removeprefix("sha256:"))
        if hashes:
            package["checksums"] = [{"algorithm": "SHA256", "checksumValue": hashes[0]}]
        packages.append(package)
    return packages


def _npm_packages(path: Path) -> list[dict[str, Any]]:
    lock = json.loads(path.read_text(encoding="utf-8"))
    runtime = {row["location"]: row for row in npm_runtime_packages(path)}
    packages: list[dict[str, Any]] = []
    for location, item in sorted(lock.get("packages", {}).items()):
        if location not in runtime:
            continue
        record = runtime[location]
        name = record["name"]
        version = record["version"]
        license_id = record["license"]
        suffix = hashlib.sha256(location.encode("utf-8")).hexdigest()[:8]
        package = {
            "SPDXID": _spdx_id("npm", name, version, suffix),
            "name": name,
            "versionInfo": version,
            "downloadLocation": str(item.get("resolved") or "NOASSERTION"),
            "filesAnalyzed": False,
            "licenseConcluded": license_id,
            "licenseDeclared": license_id,
            "copyrightText": "NOASSERTION",
            "externalRefs": [
                {
                    "referenceCategory": "PACKAGE-MANAGER",
                    "referenceType": "purl",
                    "referenceLocator": f"pkg:npm/{name}@{version}",
                }
            ],
            "primaryPackagePurpose": "LIBRARY",
        }
        integrity = str(item.get("integrity") or "")
        if integrity.startswith("sha512-"):
            package["comment"] = f"npm integrity: {integrity}"
        packages.append(package)
    return packages


def generate(
    *,
    uv_lock: Path = UV_LOCK,
    npm_lock: Path = NPM_LOCK,
    policy_path: Path = POLICY_PATH,
    notices_path: Path = NOTICES_PATH,
    created: str | None = None,
) -> dict[str, Any]:
    inputs = (uv_lock, npm_lock, policy_path, notices_path)
    if not all(path.is_file() for path in inputs):
        missing = [str(path) for path in inputs if not path.is_file()]
        raise FileNotFoundError(f"missing release locks: {', '.join(missing)}")
    inputs_digest = hashlib.sha256(
        ":".join(_sha256(path) for path in inputs).encode()
    ).hexdigest()
    created = created or datetime.now(UTC).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )
    root_id = "SPDXRef-domain-foundry-core"
    packages = [
        {
            "SPDXID": root_id,
            "name": "domain-foundry-core",
            "versionInfo": "0.1.0",
            "downloadLocation": "https://github.com/finnqiao/domain_foundry",
            "filesAnalyzed": False,
            "licenseConcluded": "MIT",
            "licenseDeclared": "MIT",
            "copyrightText": "NOASSERTION",
            "primaryPackagePurpose": "APPLICATION",
        },
        *_python_packages(uv_lock, policy_path),
        *_npm_packages(npm_lock),
    ]
    dependency_ids = [item["SPDXID"] for item in packages if item["SPDXID"] != root_id]
    return {
        "spdxVersion": "SPDX-2.3",
        "dataLicense": "CC0-1.0",
        "SPDXID": "SPDXRef-DOCUMENT",
        "name": "domain-foundry-core-0.1.0-sbom",
        "documentNamespace": f"https://github.com/finnqiao/domain_foundry/sbom/{inputs_digest}",
        "creationInfo": {"created": created, "creators": ["Tool: scripts/generate_sbom.py"]},
        "documentDescribes": [root_id],
        "packages": packages,
        "relationships": [
            {
                "spdxElementId": root_id,
                "relationshipType": "DEPENDS_ON",
                "relatedSpdxElement": dependency_id,
            }
            for dependency_id in dependency_ids
        ],
        "annotations": [
            {
                "annotationDate": created,
                "annotationType": "OTHER",
                "annotator": "Tool: scripts/generate_sbom.py",
                "comment": (
                    "Runtime inventory is lock-derived. License expressions are resolved by "
                    "release/dependency-licenses.yaml; bundled JavaScript license text is in "
                    "THIRD_PARTY_NOTICES.txt. Independent license review remains a release gate."
                ),
            }
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--created")
    args = parser.parse_args()
    payload = generate(created=args.created)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"wrote SPDX SBOM with {len(payload['packages'])} packages to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
