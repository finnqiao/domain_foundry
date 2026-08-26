from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
import yaml
from scripts.review_packet import prepare_packet, seal_reports

SHA = "a" * 64
COMMIT = "b" * 40


def _candidate(path: Path) -> Path:
    document = {
        "candidate_id": f"sha256:{SHA}",
        "git": {"head": COMMIT, "worktree_clean": True},
        "artifacts": {
            name: {"path": f"dist/{name}", "sha256": SHA}
            for name in ("wheel", "sdist", "sbom")
        },
        "knowledge": {"sources": 39, "principles": 32},
        "licenses": {
            "python_runtime_dependencies": 33,
            "npm_bundled_occurrences": 42,
        },
        "goldens": [
            {"id": "sourdough-lab"},
            {"id": "card-collector"},
            {"id": "japanese-study-coach"},
        ],
        "providers": {
            "defaults": [
                {
                    "id": "openai",
                    "routine_model": "gpt-5.6-luna",
                    "sota_model": "gpt-5.6-sol",
                }
            ]
        },
        "naming": {
            "registry_sha256": SHA,
            "checked_at": "2026-08-19",
            "public_name": "Domain Foundry",
            "pypi": {"domain-foundry-core": "no_public_project"},
            "github": {
                "requested_organization": {
                    "handle": "Domain-Foundry",
                    "status": "occupied",
                },
                "current_repository": {
                    "full_name": "finnqiao/domain_foundry",
                    "status": "active",
                },
            },
        },
    }
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


def test_prepare_packet_prefills_candidate_bound_fields(tmp_path) -> None:
    evidence = tmp_path / "evidence"
    written = prepare_packet(
        candidate_path=_candidate(tmp_path / "candidate.json"),
        evidence_root=evidence,
        templates_root=Path(__file__).resolve().parents[2] / "release" / "templates",
    )

    assert len(written) == 15
    editorial = yaml.safe_load(
        (evidence / "knowledge_editorial.yaml").read_text(encoding="utf-8")
    )
    assert editorial["candidate_id"] == f"sha256:{SHA}"
    assert editorial["reviewed_commit"] == COMMIT
    assert editorial["artifacts"] == {"wheel": SHA, "sdist": SHA, "sbom": SHA}
    assert editorial["candidate_requirements"]["knowledge_sources"] == 39
    assert editorial["candidate_requirements"]["principles"] == 32
    assert editorial["details"]["sources_reviewed"] == 0
    assert editorial["details"]["principles_reviewed"] == 0
    assert editorial["outcome"] == "pending"


def test_seal_reports_hashes_final_report_content(tmp_path) -> None:
    evidence = tmp_path / "evidence"
    prepare_packet(
        candidate_path=_candidate(tmp_path / "candidate.json"),
        evidence_root=evidence,
        templates_root=Path(__file__).resolve().parents[2] / "release" / "templates",
    )
    report = evidence / "reports" / "security-external-report.md"
    report.write_text("Final independent security report.\n", encoding="utf-8")

    sealed = seal_reports(evidence)

    assert len(sealed) == 7
    receipt = yaml.safe_load((evidence / "security_external.yaml").read_text())
    assert receipt["evidence"][0]["sha256"] == hashlib.sha256(
        report.read_bytes()
    ).hexdigest()


def test_prepare_packet_refuses_to_overwrite_review_work(tmp_path) -> None:
    evidence = tmp_path / "evidence"
    candidate = _candidate(tmp_path / "candidate.json")
    templates = Path(__file__).resolve().parents[2] / "release" / "templates"
    prepare_packet(
        candidate_path=candidate, evidence_root=evidence, templates_root=templates
    )

    with pytest.raises(RuntimeError, match="refusing to overwrite"):
        prepare_packet(
            candidate_path=candidate, evidence_root=evidence, templates_root=templates
        )
