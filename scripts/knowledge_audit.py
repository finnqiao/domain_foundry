#!/usr/bin/env python3
"""Validate the reviewed knowledge corpus used by the Foundry pipeline."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import yaml

ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = ROOT / "knowledge" / "source-registry.yaml"
PRINCIPLES_DIR = ROOT / "knowledge" / "principles"

ALLOWED_SOURCE_STATUSES = {"approved", "reference_only", "review_required", "deprecated"}
USABLE_SOURCE_STATUSES = {"approved", "reference_only"}
REQUIRED_SOURCE_FIELDS = {
    "id",
    "title",
    "publisher",
    "url",
    "kind",
    "tier",
    "license",
    "allowed_uses",
    "status",
    "retrieved_at",
    "freshness_days",
    "topics",
}
REQUIRED_PRINCIPLE_FIELDS = {
    "id",
    "title",
    "rule",
    "sources",
    "required_evidence",
    "release_checks",
}


def _load(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path}: expected a mapping")
    return data


def audit() -> list[str]:
    errors: list[str] = []
    registry = _load(REGISTRY_PATH)
    sources = registry.get("sources")
    if registry.get("version") != 1 or not isinstance(sources, list):
        return ["source registry must be version 1 with a sources list"]

    source_by_id: dict[str, dict[str, Any]] = {}
    for index, source in enumerate(sources):
        label = f"source[{index}]"
        if not isinstance(source, dict):
            errors.append(f"{label}: expected a mapping")
            continue
        missing = REQUIRED_SOURCE_FIELDS - source.keys()
        if missing:
            errors.append(f"{label}: missing {sorted(missing)}")
            continue
        source_id = source["id"]
        if source_id in source_by_id:
            errors.append(f"{label}: duplicate id {source_id}")
        source_by_id[source_id] = source
        if source["status"] not in ALLOWED_SOURCE_STATUSES:
            errors.append(f"{source_id}: invalid status {source['status']}")
        parsed = urlparse(str(source["url"]))
        if parsed.scheme != "https" or not parsed.netloc:
            errors.append(f"{source_id}: url must be an absolute https URL")
        if not source["license"]:
            errors.append(f"{source_id}: license must be explicit")
        if not source["allowed_uses"]:
            errors.append(f"{source_id}: allowed_uses must not be empty")
        try:
            retrieved = date.fromisoformat(str(source["retrieved_at"]))
        except ValueError:
            errors.append(f"{source_id}: retrieved_at must be ISO YYYY-MM-DD")
        else:
            if retrieved > date.today():
                errors.append(f"{source_id}: retrieved_at is in the future")
            age_days = (date.today() - retrieved).days
            if source["status"] in USABLE_SOURCE_STATUSES and age_days > int(
                source["freshness_days"]
            ):
                errors.append(
                    f"{source_id}: stale by {age_days - int(source['freshness_days'])} days"
                )

    principle_ids: set[str] = set()
    for path in sorted(PRINCIPLES_DIR.glob("*.yaml")):
        document = _load(path)
        principles = document.get("principles")
        if document.get("version") != 1 or not isinstance(principles, list):
            errors.append(f"{path}: must be version 1 with a principles list")
            continue
        for index, principle in enumerate(principles):
            label = f"{path.name}:principle[{index}]"
            if not isinstance(principle, dict):
                errors.append(f"{label}: expected a mapping")
                continue
            missing = REQUIRED_PRINCIPLE_FIELDS - principle.keys()
            if missing:
                errors.append(f"{label}: missing {sorted(missing)}")
                continue
            principle_id = principle["id"]
            if principle_id in principle_ids:
                errors.append(f"{label}: duplicate id {principle_id}")
            principle_ids.add(principle_id)
            if not principle["required_evidence"] or not principle["release_checks"]:
                errors.append(f"{principle_id}: evidence and release checks are required")
            usable = 0
            for source_id in principle["sources"]:
                source = source_by_id.get(source_id)
                if source is None:
                    errors.append(f"{principle_id}: unknown source {source_id}")
                elif source["status"] in USABLE_SOURCE_STATUSES:
                    usable += 1
            if usable == 0:
                errors.append(f"{principle_id}: needs at least one usable source")

    if len(principle_ids) < 24:
        errors.append("corpus must contain at least 24 reviewed principles")
    return errors


def main() -> int:
    errors = audit()
    if errors:
        print("knowledge audit FAILED")
        for error in errors:
            print(f"- {error}")
        return 1
    print("knowledge audit OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
