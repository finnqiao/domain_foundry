#!/usr/bin/env python3
"""Fail when documented live-provider defaults drift or become stale."""

from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import yaml

from domain_foundry_core.llm.providers import all_providers

ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = ROOT / "release" / "provider-compatibility.yaml"
NETWORK_PROVIDERS = {"anthropic", "openai", "deepseek", "openrouter"}
OFFICIAL_HOSTS = {
    "anthropic": {"platform.claude.com"},
    "openai": {"developers.openai.com"},
    "deepseek": {"api-docs.deepseek.com"},
    "openrouter": {"openrouter.ai"},
}
REQUIRED_FIELDS = {
    "id",
    "base_url",
    "routine_model",
    "sota_model",
    "official_sources",
}


def _load(path: Path) -> dict[str, Any]:
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise ValueError(f"{path}: expected a mapping")
    return document


def audit(*, as_of: date | None = None, path: Path = REGISTRY_PATH) -> list[str]:
    """Compare time-bounded compatibility evidence with executable defaults."""
    today = as_of or date.today()
    errors: list[str] = []
    document = _load(path)
    if document.get("schema_version") != 1:
        errors.append("provider compatibility registry schema_version must be 1")
    try:
        reviewed_at = date.fromisoformat(str(document.get("reviewed_at")))
    except ValueError:
        errors.append("reviewed_at must be ISO YYYY-MM-DD")
        reviewed_at = today
    freshness = document.get("freshness_days")
    if isinstance(freshness, bool) or not isinstance(freshness, int) or freshness < 1:
        errors.append("freshness_days must be a positive integer")
    else:
        age = (today - reviewed_at).days
        if age < 0:
            errors.append("reviewed_at is in the future")
        elif age > freshness:
            errors.append(
                f"provider compatibility evidence is stale by {age - freshness} days"
            )

    rows = document.get("providers")
    if not isinstance(rows, list):
        return [*errors, "providers must be a list"]
    by_id: dict[str, dict[str, Any]] = {}
    for index, row in enumerate(rows):
        label = f"provider[{index}]"
        if not isinstance(row, dict):
            errors.append(f"{label}: expected a mapping")
            continue
        missing = REQUIRED_FIELDS - row.keys()
        if missing:
            errors.append(f"{label}: missing {sorted(missing)}")
            continue
        provider_id = row.get("id")
        if not isinstance(provider_id, str):
            errors.append(f"{label}: id must be a string")
            continue
        if provider_id in by_id:
            errors.append(f"{label}: duplicate id {provider_id}")
        by_id[provider_id] = row

        base = urlparse(str(row.get("base_url")))
        if base.scheme != "https" or not base.netloc:
            errors.append(f"{provider_id}: base_url must be an absolute HTTPS URL")
        sources = row.get("official_sources")
        if not isinstance(sources, list) or len(sources) < 2:
            errors.append(f"{provider_id}: at least two official sources are required")
        else:
            for source in sources:
                parsed = urlparse(str(source))
                if parsed.scheme != "https" or parsed.netloc not in OFFICIAL_HOSTS.get(
                    provider_id, set()
                ):
                    errors.append(
                        f"{provider_id}: non-official or invalid source URL {source!r}"
                    )

    if set(by_id) != NETWORK_PROVIDERS:
        errors.append(
            "provider compatibility registry must cover exactly "
            f"{sorted(NETWORK_PROVIDERS)}"
        )
    executable = {provider.id: provider for provider in all_providers()}
    for provider_id in sorted(NETWORK_PROVIDERS & set(by_id)):
        row = by_id[provider_id]
        spec = executable.get(provider_id)
        if spec is None:
            errors.append(f"{provider_id}: not present in executable provider registry")
            continue
        for field in ("base_url", "routine_model", "sota_model"):
            if row.get(field) != getattr(spec, field):
                errors.append(
                    f"{provider_id}.{field} documents {row.get(field)!r}; "
                    f"executable default is {getattr(spec, field)!r}"
                )
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--as-of", type=date.fromisoformat)
    parser.add_argument("--registry", type=Path, default=REGISTRY_PATH)
    args = parser.parse_args()
    try:
        errors = audit(as_of=args.as_of, path=args.registry.resolve())
    except (OSError, ValueError, yaml.YAMLError) as exc:
        print(f"provider compatibility audit ERROR: {exc}")
        return 2
    if errors:
        print("provider compatibility audit FAILED")
        for error in errors:
            print(f"- {error}")
        return 1
    print("provider compatibility audit OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
