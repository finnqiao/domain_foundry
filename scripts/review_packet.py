#!/usr/bin/env python3
"""Prepare and seal exact-candidate human-review receipts and reports."""

from __future__ import annotations

import argparse
import json
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import yaml

try:
    from release_evidence import ROOT, sha256_file, source_tree_sha256
except ModuleNotFoundError:  # imported as scripts.review_packet in tests
    from scripts.release_evidence import ROOT, sha256_file, source_tree_sha256

EVIDENCE_ROOT = ROOT / "release" / "evidence"
TEMPLATES_ROOT = ROOT / "release" / "templates"


def _load_mapping(path: Path) -> dict[str, Any]:
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise RuntimeError(f"{path} must contain one mapping")
    return document


def _write_text_atomic(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, delete=False
    ) as handle:
        handle.write(content)
        staged = Path(handle.name)
    staged.replace(path)


def _write_yaml_atomic(path: Path, document: dict[str, Any]) -> None:
    _write_text_atomic(path, yaml.safe_dump(document, sort_keys=False))


def _artifact_hashes(candidate: dict[str, Any]) -> dict[str, str]:
    artifacts = candidate.get("artifacts")
    if not isinstance(artifacts, dict):
        raise RuntimeError("candidate has no artifacts mapping")
    hashes: dict[str, str] = {}
    for name in ("wheel", "sdist", "sbom"):
        record = artifacts.get(name)
        digest = record.get("sha256") if isinstance(record, dict) else None
        if not isinstance(digest, str) or len(digest) != 64:
            raise RuntimeError(f"candidate artifact {name} has no SHA-256")
        hashes[name] = digest
    return hashes


def _prefill(document: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    document["candidate_id"] = candidate["candidate_id"]
    git = candidate.get("git")
    if not isinstance(git, dict) or not isinstance(git.get("head"), str):
        raise RuntimeError("candidate has no reviewed Git commit")
    document["reviewed_commit"] = git["head"]
    document["artifacts"] = _artifact_hashes(candidate)
    details = document.get("details")
    if not isinstance(details, dict):
        raise RuntimeError(f"{document.get('gate', 'receipt')} has no details mapping")

    gate = document.get("gate")
    requirements: dict[str, Any] = {}
    if gate == "knowledge_editorial":
        knowledge = candidate.get("knowledge")
        if not isinstance(knowledge, dict):
            raise RuntimeError("candidate has no knowledge counts")
        requirements["knowledge_sources"] = knowledge.get("sources", 0)
        requirements["principles"] = knowledge.get("principles", 0)
    elif gate == "licensing_external":
        licenses = candidate.get("licenses")
        if not isinstance(licenses, dict):
            raise RuntimeError("candidate has no license counts")
        requirements["python_runtime_dependencies"] = licenses.get(
            "python_runtime_dependencies", 0
        )
        requirements["npm_bundled_occurrences"] = licenses.get(
            "npm_bundled_occurrences", 0
        )
    elif gate == "accessibility_manual":
        goldens = candidate.get("goldens")
        if not isinstance(goldens, list):
            raise RuntimeError("candidate has no golden list")
        requirements["goldens"] = sorted(
            row["id"]
            for row in goldens
            if isinstance(row, dict) and isinstance(row.get("id"), str)
        )
    elif gate == "provider_live":
        providers = candidate.get("providers")
        defaults = providers.get("defaults") if isinstance(providers, dict) else None
        if not isinstance(defaults, list):
            raise RuntimeError("candidate has no provider defaults")
        details["providers"] = [
            {
                "id": row["id"],
                "routine": {"model": row["routine_model"], "ok": False},
                "sota": {"model": row["sota_model"], "ok": False},
            }
            for row in sorted(defaults, key=lambda item: item["id"])
        ]
        requirements["network_providers"] = [
            row["id"] for row in sorted(defaults, key=lambda item: item["id"])
        ]
    elif gate == "name_and_publish_authorization":
        naming = candidate.get("naming")
        if not isinstance(naming, dict):
            raise RuntimeError("candidate has no naming evidence")
        requirements["name_availability"] = naming
    if requirements:
        document["candidate_requirements"] = requirements
    return document


def _report_text(document: dict[str, Any], candidate: dict[str, Any]) -> str:
    gate = str(document["gate"])
    title = gate.replace("_", " ").title()
    scope = document.get("scope") or []
    scope_lines = "\n".join(f"- [ ] {item}" for item in scope)
    artifacts = _artifact_hashes(candidate)
    return f"""# {title} report

Candidate: `{candidate['candidate_id']}`<br>
Commit: `{candidate['git']['head']}`<br>
Wheel SHA-256: `{artifacts['wheel']}`<br>
sdist SHA-256: `{artifacts['sdist']}`<br>
SBOM SHA-256: `{artifacts['sbom']}`

## Reviewer and environment

Record reviewer identity/qualification, date, operating system, tool versions,
and any constraints that affect reproducibility. Do not include credentials,
private participant data, or undisclosed exploit details.

## Scope completed

{scope_lines}

## Method and observations

Describe what was exercised, the evidence inspected, and the observed result.

## Findings and remediation

List every finding with severity, disposition, and retest evidence. State
explicitly when there are no findings rather than leaving this section blank.

## Conclusion

State pass or fail and explain whether any release-blocking issue remains.
"""


def prepare_packet(
    *,
    candidate_path: Path,
    evidence_root: Path,
    templates_root: Path,
) -> list[Path]:
    candidate = json.loads(candidate_path.read_text(encoding="utf-8"))
    if not isinstance(candidate, dict):
        raise RuntimeError("candidate.json must contain one object")
    templates = sorted(templates_root.glob("*.template.yaml"))
    if not templates:
        raise RuntimeError(f"no receipt templates found in {templates_root}")

    outputs: list[tuple[Path, Path, dict[str, Any]]] = []
    for template in templates:
        document = _prefill(_load_mapping(template), candidate)
        receipt = evidence_root / template.name.replace(".template", "")
        evidence = document.get("evidence")
        if not isinstance(evidence, list) or len(evidence) != 1:
            raise RuntimeError(f"{template} must declare exactly one evidence report")
        record = evidence[0]
        path_value = record.get("path") if isinstance(record, dict) else None
        if not isinstance(path_value, str):
            raise RuntimeError(f"{template} has no evidence report path")
        relative = Path(path_value)
        if relative.parts[:2] != ("release", "evidence"):
            raise RuntimeError(f"{template} evidence must be under release/evidence")
        report = evidence_root.joinpath(*relative.parts[2:])
        outputs.append((receipt, report, document))

    packet_index = evidence_root / "REVIEW_PACKET.md"
    collisions = [
        path for receipt, report, _document in outputs for path in (receipt, report) if path.exists()
    ]
    if packet_index.exists():
        collisions.append(packet_index)
    if collisions:
        joined = ", ".join(str(path) for path in collisions)
        raise RuntimeError(f"review packet already exists; refusing to overwrite: {joined}")

    written: list[Path] = []
    for receipt, report, document in outputs:
        _write_yaml_atomic(receipt, document)
        _write_text_atomic(report, _report_text(document, candidate))
        written.extend((receipt, report))
    index = f"""# Exact-candidate review packet

Candidate: `{candidate['candidate_id']}`<br>
Commit: `{candidate['git']['head']}`

The receipt identities, artifact hashes, candidate requirements, and expected
provider models were copied from `candidate.json`. Actual-review fields remain
pending, false, zero, empty, or placeholder values. Reviewers must complete the
reports and receipt fields themselves; generated requirements are not evidence.

1. Follow `docs/release-review-guide.md` for the applicable gate.
2. Complete the report under `release/evidence/reports/`.
3. Complete the corresponding receipt, including reviewer, time, result,
   measured details, and substantive attestation.
4. Run `python scripts/review_packet.py seal` to hash the final reports.
5. Run `python scripts/public_release_audit.py`; do not edit a sealed report.
"""
    _write_text_atomic(packet_index, index)
    written.append(packet_index)
    return written


def _evidence_target(path_value: str, evidence_root: Path) -> Path:
    relative = Path(path_value)
    if relative.is_absolute() or relative.parts[:2] != ("release", "evidence"):
        raise RuntimeError(f"evidence path must be below release/evidence: {path_value}")
    target = evidence_root.joinpath(*relative.parts[2:])
    root = evidence_root.resolve()
    if not target.resolve().is_relative_to(root) or target.is_symlink():
        raise RuntimeError(f"evidence path escapes the evidence directory: {path_value}")
    if not target.is_file() or target.stat().st_size == 0:
        raise RuntimeError(f"evidence report is missing or empty: {path_value}")
    return target


def seal_reports(evidence_root: Path) -> list[Path]:
    receipts = sorted(evidence_root.glob("*.yaml"))
    if not receipts:
        raise RuntimeError(f"no review receipts found in {evidence_root}")
    documents: list[tuple[Path, dict[str, Any]]] = []
    for receipt in receipts:
        document = _load_mapping(receipt)
        evidence = document.get("evidence")
        if not isinstance(evidence, list) or not evidence:
            raise RuntimeError(f"{receipt} has no evidence records")
        for record in evidence:
            if not isinstance(record, dict) or not isinstance(record.get("path"), str):
                raise RuntimeError(f"{receipt} has an invalid evidence record")
            target = _evidence_target(record["path"], evidence_root)
            record["sha256"] = sha256_file(target)
        documents.append((receipt, document))
    for receipt, document in documents:
        _write_yaml_atomic(receipt, document)
    return [path for path, _document in documents]


def _git(*args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=ROOT, check=True, capture_output=True, text=True
    )
    return result.stdout.strip()


def validate_current_clean_candidate(candidate_path: Path) -> None:
    candidate = json.loads(candidate_path.read_text(encoding="utf-8"))
    if not isinstance(candidate, dict):
        raise RuntimeError("candidate.json must contain one object")
    git = candidate.get("git")
    if not isinstance(git, dict) or git.get("worktree_clean") is not True:
        raise RuntimeError("review packets require a candidate generated from a clean worktree")
    if git.get("head") != _git("rev-parse", "HEAD"):
        raise RuntimeError("candidate commit is not current HEAD")
    if _git("status", "--porcelain=v1", "--untracked-files=all"):
        raise RuntimeError("current worktree is dirty")
    if candidate.get("source_tree_sha256") != source_tree_sha256():
        raise RuntimeError("candidate source-tree hash is stale")
    artifacts = candidate.get("artifacts")
    if not isinstance(artifacts, dict):
        raise RuntimeError("candidate has no artifacts")
    for name, raw in artifacts.items():
        if not isinstance(raw, dict) or not isinstance(raw.get("path"), str):
            raise RuntimeError(f"candidate artifact {name} is invalid")
        path = ROOT / raw["path"]
        if not path.is_file() or sha256_file(path) != raw.get("sha256"):
            raise RuntimeError(f"candidate artifact {name} is missing or changed")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    prepare = subparsers.add_parser("prepare", help="create pre-bound pending receipts")
    prepare.add_argument("--candidate", type=Path, default=EVIDENCE_ROOT / "candidate.json")
    prepare.add_argument("--evidence-dir", type=Path, default=EVIDENCE_ROOT)
    seal = subparsers.add_parser("seal", help="hash final reports into their receipts")
    seal.add_argument("--evidence-dir", type=Path, default=EVIDENCE_ROOT)
    args = parser.parse_args()
    try:
        evidence_root = args.evidence_dir.resolve()
        if args.command == "prepare":
            candidate_path = args.candidate.resolve()
            validate_current_clean_candidate(candidate_path)
            written = prepare_packet(
                candidate_path=candidate_path,
                evidence_root=evidence_root,
                templates_root=TEMPLATES_ROOT,
            )
        else:
            written = seal_reports(evidence_root)
    except (OSError, RuntimeError, subprocess.CalledProcessError, json.JSONDecodeError) as exc:
        print(f"review packet ERROR: {exc}")
        return 1
    print(f"review packet {args.command} OK ({len(written)} files)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
