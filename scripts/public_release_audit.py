#!/usr/bin/env python3
"""Fail closed until machine evidence and every independent release receipt agree."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

try:
    from release_evidence import ROOT, sha256_file, source_tree_sha256
except ModuleNotFoundError:  # imported as scripts.public_release_audit in tests
    from scripts.release_evidence import ROOT, sha256_file, source_tree_sha256

EVIDENCE_ROOT = ROOT / "release" / "evidence"
REQUIRED_GATES = {
    "knowledge_editorial",
    "licensing_external",
    "accessibility_manual",
    "security_external",
    "provider_live",
    "external_user_validation",
    "name_and_publish_authorization",
}
INDEPENDENT_GATES = {
    "knowledge_editorial",
    "licensing_external",
    "accessibility_manual",
    "security_external",
}
NETWORK_PROVIDERS = {"anthropic", "openai", "deepseek", "openrouter"}
HEX_64 = re.compile(r"^[0-9a-f]{64}$")


def _git(*args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=ROOT, check=True, capture_output=True, text=True
    )
    return result.stdout.strip()


def _mapping(value: Any, label: str, errors: list[str]) -> dict[str, Any]:
    if not isinstance(value, dict):
        errors.append(f"{label} must be a mapping")
        return {}
    return value


def _integer(value: Any, label: str, errors: list[str]) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        errors.append(f"{label} must be an integer")
        return -1
    return value


def _review_time(value: Any, label: str, errors: list[str]) -> datetime | None:
    if not isinstance(value, str):
        errors.append(f"{label} must be an ISO-8601 string")
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        errors.append(f"{label} must be an ISO-8601 string")
        return None


def _validate_evidence(
    value: Any,
    errors: list[str],
    *,
    evidence_root: Path | None,
) -> None:
    if not isinstance(value, list) or not value:
        errors.append("at least one hashed local evidence report is required")
        return
    root = evidence_root.resolve() if evidence_root is not None else None
    for index, raw in enumerate(value, 1):
        label = f"evidence[{index}]"
        record = _mapping(raw, label, errors)
        path_value = record.get("path")
        digest = record.get("sha256")
        if not isinstance(path_value, str) or not path_value.strip():
            errors.append(f"{label}.path is required")
            continue
        relative = Path(path_value)
        if relative.is_absolute() or relative.parts[:2] != ("release", "evidence"):
            errors.append(f"{label}.path must be below release/evidence")
            continue
        if not isinstance(digest, str) or not HEX_64.fullmatch(digest):
            errors.append(f"{label}.sha256 must be a SHA-256 digest")
            continue
        if root is None:
            continue
        target = root.joinpath(*relative.parts[2:])
        resolved = target.resolve()
        if not resolved.is_relative_to(root) or target.is_symlink():
            errors.append(f"{label}.path escapes the evidence directory")
        elif not target.is_file() or target.stat().st_size == 0:
            errors.append(f"{label}.path is missing or empty: {path_value}")
        elif sha256_file(target) != digest:
            errors.append(f"{label}.sha256 does not match {path_value}")


def _validate_editorial(
    details: dict[str, Any], candidate: dict[str, Any], errors: list[str]
) -> None:
    knowledge = _mapping(candidate.get("knowledge"), "candidate.knowledge", errors)
    if _integer(details.get("sources_reviewed"), "sources_reviewed", errors) < int(
        knowledge.get("sources", 0)
    ):
        errors.append("editorial review does not cover every candidate source")
    if _integer(
        details.get("principles_reviewed"), "principles_reviewed", errors
    ) < int(knowledge.get("principles", 0)):
        errors.append("editorial review does not cover every candidate principle")
    if details.get("unresolved_blocking_findings") != 0:
        errors.append("editorial review has unresolved blocking findings")


def _validate_accessibility(
    details: dict[str, Any], candidate: dict[str, Any], errors: list[str]
) -> None:
    expected: set[str] = {
        row["id"]
        for row in candidate.get("goldens", [])
        if isinstance(row, dict) and isinstance(row.get("id"), str)
    }
    actual = set(details.get("goldens_reviewed") or [])
    if actual != expected:
        errors.append(f"accessibility review must cover goldens {sorted(expected)}")
    readers = details.get("screen_readers")
    if not isinstance(readers, list) or not readers:
        errors.append("accessibility review requires at least one named screen reader")
    for field in ("keyboard_only", "zoom_200_percent", "reflow_320_css_px"):
        if details.get(field) is not True:
            errors.append(f"accessibility review requires {field}=true")
    if details.get("unresolved_blockers") != 0:
        errors.append("accessibility review has unresolved blockers")


def _validate_licensing(
    details: dict[str, Any], candidate: dict[str, Any], errors: list[str]
) -> None:
    required = {
        "knowledge_sources",
        "python_runtime_dependencies",
        "npm_bundled_dependencies",
        "generated_app_output",
        "release_artifacts",
    }
    surfaces = set(details.get("surfaces_reviewed") or [])
    missing = required - surfaces
    if missing:
        errors.append(f"license review misses surfaces {sorted(missing)}")
    licenses = _mapping(candidate.get("licenses"), "candidate.licenses", errors)
    if _integer(
        details.get("python_dependencies_reviewed"),
        "python_dependencies_reviewed",
        errors,
    ) < int(licenses.get("python_runtime_dependencies", 0)):
        errors.append("license review does not cover every Python runtime dependency")
    if _integer(
        details.get("npm_occurrences_reviewed"),
        "npm_occurrences_reviewed",
        errors,
    ) < int(licenses.get("npm_bundled_occurrences", 0)):
        errors.append("license review does not cover every bundled npm occurrence")
    if details.get("third_party_notices_reviewed") is not True:
        errors.append("license review must cover THIRD_PARTY_NOTICES.txt")
    if details.get("sbom_reviewed") is not True:
        errors.append("license review must cover the candidate SBOM")
    if details.get("unresolved_blocking_findings") != 0:
        errors.append("license review has unresolved blocking findings")


def _validate_security(details: dict[str, Any], errors: list[str]) -> None:
    required = {
        "foundry_pipeline",
        "local_http_api",
        "generated_app",
        "supply_chain",
    }
    surfaces = set(details.get("surfaces_reviewed") or [])
    missing = required - surfaces
    if missing:
        errors.append(f"security review misses surfaces {sorted(missing)}")
    for severity in ("critical", "high"):
        if details.get(f"unresolved_{severity}") != 0:
            errors.append(f"security review has unresolved {severity} findings")


def _validate_providers(
    details: dict[str, Any], candidate: dict[str, Any], errors: list[str]
) -> None:
    rows = details.get("providers")
    if not isinstance(rows, list):
        errors.append("provider review requires a providers list")
        return
    by_id = {
        row.get("id"): row
        for row in rows
        if isinstance(row, dict) and isinstance(row.get("id"), str)
    }
    if set(by_id) != NETWORK_PROVIDERS:
        errors.append(f"provider review must cover {sorted(NETWORK_PROVIDERS)}")
        return
    provider_manifest = _mapping(
        candidate.get("providers"), "candidate.providers", errors
    )
    candidate_defaults = provider_manifest.get("defaults")
    if not isinstance(candidate_defaults, list):
        errors.append("candidate does not declare its provider defaults")
        return
    registry = {
        row.get("id"): row
        for row in candidate_defaults
        if isinstance(row, dict) and isinstance(row.get("id"), str)
    }
    for provider_id in sorted(NETWORK_PROVIDERS):
        row = by_id[provider_id]
        spec = registry.get(provider_id)
        if not isinstance(spec, dict):
            errors.append(f"candidate provider defaults omit {provider_id}")
            continue
        for tier, expected_model in (
            ("routine", spec.get("routine_model")),
            ("sota", spec.get("sota_model")),
        ):
            result = row.get(tier)
            if not isinstance(result, dict):
                errors.append(f"{provider_id}.{tier} probe result is missing")
                continue
            if result.get("ok") is not True:
                errors.append(f"{provider_id}.{tier} live probe did not pass")
            if result.get("model") != expected_model:
                errors.append(
                    f"{provider_id}.{tier} probed {result.get('model')!r}; "
                    f"candidate defaults to {expected_model!r}"
                )


def _validate_users(details: dict[str, Any], errors: list[str]) -> None:
    sessions = details.get("sessions")
    if not isinstance(sessions, list) or len(sessions) < 3:
        errors.append("external validation requires at least three sessions")
        return
    participants: set[str] = set()
    interests: set[str] = set()
    for index, session in enumerate(sessions):
        if not isinstance(session, dict):
            errors.append(f"external session {index + 1} must be a mapping")
            continue
        participant = session.get("participant_id")
        interest = session.get("interest")
        if isinstance(participant, str) and participant.strip():
            participants.add(participant.strip())
        if isinstance(interest, str) and interest.strip():
            interests.add(interest.strip().lower())
        if _integer(
            session.get("tasks_attempted"),
            f"session {index + 1}.tasks_attempted",
            errors,
        ) < 2:
            errors.append(f"external session {index + 1} attempted fewer than two tasks")
        if session.get("critical_tasks_passed") is not True:
            errors.append(f"external session {index + 1} did not pass its critical tasks")
    if len(participants) < 3:
        errors.append("external validation requires three distinct participants")
    if len(interests) < 3:
        errors.append("external validation requires three distinct interests")
    if details.get("unresolved_blockers") != 0:
        errors.append("external validation has unresolved blockers")


def _validate_name(
    details: dict[str, Any], candidate: dict[str, Any], errors: list[str]
) -> None:
    naming = _mapping(candidate.get("naming"), "candidate.naming", errors)
    public_name = naming.get("public_name")
    if details.get("approved_public_name") != public_name:
        errors.append("approved public name does not match the candidate name evidence")
    if details.get("availability_registry_reviewed") is not True:
        errors.append("maintainer has not reviewed the current name availability evidence")
    if details.get("pypi_names_checked") is not True:
        errors.append("PyPI distribution names were not rechecked")
    if details.get("trademark_checked") is not True:
        errors.append("trademark sanity check is not recorded")
    if details.get("repository_coordinates_checked") is not True:
        errors.append("repository coordinates are not approved")
    github = _mapping(naming.get("github"), "candidate.naming.github", errors)
    repository = _mapping(
        github.get("current_repository"),
        "candidate.naming.github.current_repository",
        errors,
    )
    if details.get("approved_repository") != repository.get("full_name"):
        errors.append("approved repository does not match the candidate name evidence")
    trademark = _mapping(naming.get("trademark"), "candidate.naming.trademark", errors)
    if trademark.get("release_blocking") is True:
        disposition = details.get("collision_disposition")
        if disposition not in {"qualified_counsel_clearance", "rights_agreement"}:
            errors.append(
                "material exact-mark collision requires qualified clearance or a rights agreement"
            )
        legal_reviewer = details.get("legal_reviewer")
        if not isinstance(legal_reviewer, str) or len(legal_reviewer.strip()) < 3:
            errors.append("material name collision requires a named legal reviewer")
    if details.get("publish_authorized") is not True:
        errors.append("irreversible publication is not authorized")


def validate_receipt(
    receipt: dict[str, Any],
    candidate: dict[str, Any],
    *,
    evidence_root: Path | None = None,
) -> tuple[str, list[str]]:
    errors: list[str] = []
    gate = receipt.get("gate")
    if not isinstance(gate, str):
        return "unknown", ["gate must be a string"]
    if receipt.get("schema_version") != 1:
        errors.append("schema_version must be 1")
    if gate not in REQUIRED_GATES:
        errors.append(f"unknown gate {gate!r}")
    if receipt.get("candidate_id") != candidate.get("candidate_id"):
        errors.append("candidate_id does not match candidate.json")
    git = _mapping(candidate.get("git"), "candidate.git", errors)
    if receipt.get("reviewed_commit") != git.get("head"):
        errors.append("reviewed_commit does not match the candidate commit")
    if receipt.get("outcome") != "pass":
        errors.append("outcome must be pass")

    reviewer = _mapping(receipt.get("reviewer"), "reviewer", errors)
    if not isinstance(reviewer.get("identifier"), str) or not reviewer.get(
        "identifier", ""
    ).strip():
        errors.append("reviewer.identifier is required")
    relationship = reviewer.get("relationship")
    if gate in INDEPENDENT_GATES and relationship != "independent":
        errors.append(f"{gate} requires an independent reviewer")
    if relationship not in {"independent", "maintainer", "operator"}:
        errors.append("reviewer.relationship is invalid")

    reviewed_at = _review_time(receipt.get("reviewed_at"), "reviewed_at", errors)
    generated_at = _review_time(
        candidate.get("generated_at"), "candidate.generated_at", errors
    )
    if reviewed_at and generated_at and reviewed_at < generated_at:
        errors.append("review predates the candidate evidence")

    _validate_evidence(receipt.get("evidence"), errors, evidence_root=evidence_root)
    scope = receipt.get("scope")
    if not isinstance(scope, list) or not scope:
        errors.append("scope must list what was actually reviewed")
    attestation = receipt.get("attestation")
    if not isinstance(attestation, str) or len(attestation.strip()) < 40:
        errors.append("attestation must be a substantive human statement")

    artifacts = _mapping(receipt.get("artifacts"), "artifacts", errors)
    candidate_artifacts = _mapping(candidate.get("artifacts"), "candidate.artifacts", errors)
    for name in ("wheel", "sdist", "sbom"):
        expected = _mapping(
            candidate_artifacts.get(name), f"candidate.artifacts.{name}", errors
        ).get("sha256")
        actual = artifacts.get(name)
        if not isinstance(actual, str) or not HEX_64.fullmatch(actual):
            errors.append(f"artifacts.{name} must be a SHA-256 digest")
        elif actual != expected:
            errors.append(f"artifacts.{name} does not match candidate.json")

    details = _mapping(receipt.get("details"), "details", errors)
    if gate == "knowledge_editorial":
        _validate_editorial(details, candidate, errors)
    elif gate == "licensing_external":
        _validate_licensing(details, candidate, errors)
    elif gate == "accessibility_manual":
        _validate_accessibility(details, candidate, errors)
    elif gate == "security_external":
        _validate_security(details, errors)
    elif gate == "provider_live":
        _validate_providers(details, candidate, errors)
    elif gate == "external_user_validation":
        _validate_users(details, errors)
    elif gate == "name_and_publish_authorization":
        _validate_name(details, candidate, errors)
    return gate, errors


def load_receipts(evidence_root: Path) -> list[dict[str, Any]]:
    receipts: list[dict[str, Any]] = []
    for path in sorted(evidence_root.glob("*.yaml")):
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(document, dict):
            raise RuntimeError(f"{path} must contain one YAML mapping")
        document["_path"] = path.name
        receipts.append(document)
    return receipts


def audit(evidence_root: Path) -> tuple[dict[str, list[str]], list[str]]:
    errors: list[str] = []
    candidate_path = evidence_root / "candidate.json"
    if not candidate_path.is_file():
        return {}, [f"missing {candidate_path}; run scripts/candidate_gate.sh"]
    candidate = json.loads(candidate_path.read_text(encoding="utf-8"))
    if not isinstance(candidate, dict):
        return {}, ["candidate.json must contain one JSON object"]

    git = _mapping(candidate.get("git"), "candidate.git", errors)
    current_head = _git("rev-parse", "HEAD")
    current_status = _git("status", "--porcelain=v1", "--untracked-files=all")
    if git.get("head") != current_head:
        errors.append("candidate commit is not the current HEAD")
    if git.get("worktree_clean") is not True:
        errors.append("candidate was generated from a dirty worktree")
    if current_status:
        errors.append("current worktree is dirty")
    current_tree = source_tree_sha256()
    if candidate.get("source_tree_sha256") != current_tree:
        errors.append("candidate source-tree hash does not match the current checkout")

    for name, record_value in _mapping(
        candidate.get("artifacts"), "candidate.artifacts", errors
    ).items():
        record = _mapping(record_value, f"candidate.artifacts.{name}", errors)
        path_value = record.get("path")
        if not isinstance(path_value, str):
            errors.append(f"candidate artifact {name} has no path")
            continue
        path = ROOT / path_value
        if not path.is_file():
            errors.append(f"candidate artifact {name} is missing: {path}")
        elif sha256_file(path) != record.get("sha256"):
            errors.append(f"candidate artifact {name} hash changed")

    results: dict[str, list[str]] = {}
    for receipt in load_receipts(evidence_root):
        gate, receipt_errors = validate_receipt(
            receipt, candidate, evidence_root=evidence_root
        )
        if gate in results:
            receipt_errors.append(f"duplicate receipt for gate {gate}")
        results[gate] = receipt_errors
    for gate in sorted(REQUIRED_GATES - set(results)):
        results[gate] = ["missing receipt"]
    return results, errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence-dir", type=Path, default=EVIDENCE_ROOT)
    args = parser.parse_args()
    try:
        results, candidate_errors = audit(args.evidence_dir.resolve())
    except (OSError, RuntimeError, subprocess.CalledProcessError, json.JSONDecodeError) as exc:
        print(f"public release audit ERROR: {exc}")
        return 2

    for gate in sorted(REQUIRED_GATES):
        gate_errors = results.get(gate, ["missing receipt"])
        status = "PASS" if not gate_errors else "FAIL"
        print(f"{status:4} {gate}")
        for error in gate_errors:
            print(f"     - {error}")
    for error in candidate_errors:
        print(f"FAIL candidate: {error}")
    if candidate_errors or any(results.values()):
        print("public release audit FAILED")
        return 1
    print("public release audit OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
