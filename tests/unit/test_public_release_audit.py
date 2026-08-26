from __future__ import annotations

import importlib.util
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
SHA = "a" * 64
COMMIT = "b" * 40


def _module():  # type: ignore[no-untyped-def]
    scripts = ROOT / "scripts"
    spec = importlib.util.spec_from_file_location(
        "public_release_audit", scripts / "public_release_audit.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(scripts))
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path.remove(str(scripts))
    return module


AUDIT = _module()
REQUIRED_GATES = AUDIT.REQUIRED_GATES
validate_receipt = AUDIT.validate_receipt


def _candidate() -> dict[str, Any]:
    return {
        "candidate_id": f"sha256:{SHA}",
        "generated_at": "2026-08-19T12:00:00+00:00",
        "git": {"head": COMMIT, "worktree_clean": True},
        "knowledge": {"sources": 29, "principles": 32},
        "licenses": {
            "python_runtime_dependencies": 33,
            "npm_bundled_occurrences": 42,
        },
        "naming": {
            "public_name": "Domain Foundry",
            "github": {
                "current_repository": {"full_name": "finnqiao/domain_foundry"}
            },
            "trademark": {
                "release_blocking": True,
                "disposition": "unresolved",
            },
        },
        "providers": {
            "defaults": [
                {
                    "id": "anthropic",
                    "routine_model": "claude-haiku-4-5",
                    "sota_model": "claude-opus-5",
                },
                {
                    "id": "openai",
                    "routine_model": "gpt-5.6-luna",
                    "sota_model": "gpt-5.6-sol",
                },
                {
                    "id": "deepseek",
                    "routine_model": "deepseek-v4-flash",
                    "sota_model": "deepseek-v4-pro",
                },
                {
                    "id": "openrouter",
                    "routine_model": "z-ai/glm-5.2",
                    "sota_model": "anthropic/claude-opus-5",
                },
            ]
        },
        "goldens": [
            {"id": "card-collector"},
            {"id": "japanese-study-coach"},
            {"id": "sourdough-lab"},
        ],
        "artifacts": {
            "wheel": {"sha256": SHA},
            "sdist": {"sha256": SHA},
            "sbom": {"sha256": SHA},
        },
    }


def _details(gate: str) -> dict[str, Any]:
    if gate == "knowledge_editorial":
        return {
            "sources_reviewed": 29,
            "principles_reviewed": 32,
            "unresolved_blocking_findings": 0,
        }
    if gate == "accessibility_manual":
        return {
            "goldens_reviewed": [
                "card-collector",
                "japanese-study-coach",
                "sourdough-lab",
            ],
            "screen_readers": ["VoiceOver 17 / Safari"],
            "keyboard_only": True,
            "zoom_200_percent": True,
            "reflow_320_css_px": True,
            "unresolved_blockers": 0,
        }
    if gate == "licensing_external":
        return {
            "surfaces_reviewed": [
                "knowledge_sources",
                "python_runtime_dependencies",
                "npm_bundled_dependencies",
                "generated_app_output",
                "release_artifacts",
            ],
            "python_dependencies_reviewed": 33,
            "npm_occurrences_reviewed": 42,
            "third_party_notices_reviewed": True,
            "sbom_reviewed": True,
            "unresolved_blocking_findings": 0,
        }
    if gate == "security_external":
        return {
            "surfaces_reviewed": [
                "foundry_pipeline",
                "local_http_api",
                "generated_app",
                "supply_chain",
            ],
            "unresolved_critical": 0,
            "unresolved_high": 0,
        }
    if gate == "provider_live":
        return {
            "providers": [
                {
                    "id": "anthropic",
                    "routine": {"model": "claude-haiku-4-5", "ok": True},
                    "sota": {"model": "claude-opus-5", "ok": True},
                },
                {
                    "id": "openai",
                    "routine": {"model": "gpt-5.6-luna", "ok": True},
                    "sota": {"model": "gpt-5.6-sol", "ok": True},
                },
                {
                    "id": "deepseek",
                    "routine": {"model": "deepseek-v4-flash", "ok": True},
                    "sota": {"model": "deepseek-v4-pro", "ok": True},
                },
                {
                    "id": "openrouter",
                    "routine": {"model": "z-ai/glm-5.2", "ok": True},
                    "sota": {"model": "anthropic/claude-opus-5", "ok": True},
                },
            ]
        }
    if gate == "external_user_validation":
        return {
            "sessions": [
                {
                    "participant_id": f"participant-{index}",
                    "interest": interest,
                    "tasks_attempted": 2,
                    "critical_tasks_passed": True,
                }
                for index, interest in enumerate(("orchids", "kayaks", "vinyl"), 1)
            ],
            "unresolved_blockers": 0,
        }
    if gate == "name_and_publish_authorization":
        return {
            "approved_public_name": "Domain Foundry",
            "availability_registry_reviewed": True,
            "pypi_names_checked": True,
            "trademark_checked": True,
            "collision_disposition": "qualified_counsel_clearance",
            "legal_reviewer": "qualified-reviewer",
            "repository_coordinates_checked": True,
            "approved_repository": "finnqiao/domain_foundry",
            "publish_authorized": True,
        }
    raise AssertionError(gate)


def _receipt(gate: str) -> dict[str, Any]:
    relationship = "independent"
    if gate == "provider_live":
        relationship = "operator"
    elif gate in {"external_user_validation", "name_and_publish_authorization"}:
        relationship = "maintainer"
    return {
        "schema_version": 1,
        "gate": gate,
        "candidate_id": f"sha256:{SHA}",
        "reviewed_commit": COMMIT,
        "reviewed_at": "2026-08-20T12:00:00+00:00",
        "outcome": "pass",
        "reviewer": {
            "identifier": "reviewer-handle",
            "relationship": relationship,
        },
        "scope": ["complete documented scope"],
        "evidence": [
            {"path": "release/evidence/reports/report.md", "sha256": SHA}
        ],
        "artifacts": {"wheel": SHA, "sdist": SHA, "sbom": SHA},
        "details": _details(gate),
        "attestation": "I reviewed the exact candidate and attest that this gate passed.",
    }


def test_complete_receipt_contract_accepts_every_required_gate() -> None:
    candidate = _candidate()
    for gate in REQUIRED_GATES:
        actual_gate, errors = validate_receipt(_receipt(gate), candidate)
        assert actual_gate == gate
        assert errors == [], f"{gate}: {errors}"


def test_receipt_cannot_float_between_candidate_or_artifact() -> None:
    receipt = _receipt("security_external")
    receipt["candidate_id"] = f"sha256:{'c' * 64}"
    receipt["artifacts"]["wheel"] = "d" * 64
    _gate, errors = validate_receipt(receipt, _candidate())
    assert "candidate_id does not match candidate.json" in errors
    assert "artifacts.wheel does not match candidate.json" in errors


def test_independent_gate_rejects_maintainer_self_review() -> None:
    receipt = _receipt("knowledge_editorial")
    receipt["reviewer"]["relationship"] = "maintainer"
    _gate, errors = validate_receipt(receipt, _candidate())
    assert "knowledge_editorial requires an independent reviewer" in errors


def test_provider_gate_requires_every_current_default_model() -> None:
    receipt = deepcopy(_receipt("provider_live"))
    receipt["details"]["providers"][1]["routine"]["model"] = "gpt-4o-mini"
    _gate, errors = validate_receipt(receipt, _candidate())
    assert any("gpt-5.6-luna" in error for error in errors)


def test_material_name_collision_cannot_pass_with_maintainer_sanity_check_only() -> None:
    receipt = _receipt("name_and_publish_authorization")
    receipt["details"]["collision_disposition"] = "unresolved"
    receipt["details"]["legal_reviewer"] = ""

    _gate, errors = validate_receipt(receipt, _candidate())
    assert any("qualified clearance" in error for error in errors)
    assert any("named legal reviewer" in error for error in errors)


def test_receipt_evidence_must_exist_and_match_its_digest(tmp_path) -> None:
    reports = tmp_path / "reports"
    reports.mkdir()
    report = reports / "report.md"
    report.write_text("independent review evidence\n", encoding="utf-8")
    receipt = _receipt("security_external")
    receipt["evidence"][0]["sha256"] = AUDIT.sha256_file(report)

    _gate, errors = validate_receipt(receipt, _candidate(), evidence_root=tmp_path)
    assert errors == []

    report.write_text("changed after receipt\n", encoding="utf-8")
    _gate, errors = validate_receipt(receipt, _candidate(), evidence_root=tmp_path)
    assert "evidence[1].sha256 does not match release/evidence/reports/report.md" in errors


def test_receipt_evidence_cannot_escape_the_evidence_directory(tmp_path) -> None:
    receipt = _receipt("security_external")
    receipt["evidence"][0]["path"] = "release/evidence/../candidate.json"

    _gate, errors = validate_receipt(receipt, _candidate(), evidence_root=tmp_path)
    assert "evidence[1].path escapes the evidence directory" in errors


def test_all_receipt_templates_are_pending_and_cover_required_gates() -> None:
    templates = ROOT / "release" / "templates"
    documents = [
        yaml.safe_load(path.read_text(encoding="utf-8"))
        for path in sorted(templates.glob("*.template.yaml"))
    ]
    assert {document["gate"] for document in documents} == REQUIRED_GATES
    assert all(document["outcome"] == "pending" for document in documents)
