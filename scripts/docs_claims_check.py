#!/usr/bin/env python3
"""Docs claims checker (Slice 0, S0.6) — release_audit check 10.

Fails (exit 1) when public-facing docs contain hardcoded pytest counts, a
known-false claim from the regression denylist, or (on the product track)
harness jargon a first-time user should never see.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

EXCLUDE_PREFIXES = (
    "docs/adr/",
    "docs/build-plan-2026-08/",
    "docs/launch/",
    "docs/tutorial/snapshots/",
    "docs/concepts/",
)
EXCLUDE_FILES = {
    "docs/LEAK_AUDIT.md",
    "docs/LEAKSCAN_PHASE9.md",
    "docs/PRIVATE_OVERLAY.md",
    "docs/MESH_AS_BUILT.md",
    "docs/OPEN_GATES.md",
    "docs/RETIREMENT_RUNBOOK.md",
    "docs/PHASE_STATUS.md",
    "docs/FOUNDER_VALIDATION.md",
    "docs/HANDOFF.md",
    "docs/PER_DOMAIN_AGENT_MESH_2026-07-20.md",
    "docs/VISION_GAP_REVIEW_2026-08-08.md",
    "docs/OPEN_SOURCE_HARNESS_PLAN.md",
    # Builder-track pages may use precise internal nouns.
    "docs/architecture.md",
    "docs/adapter-guide.md",
    "docs/PACK_AUTHORING.md",
    "docs/CUSTOM_BLOCKS.md",
    "docs/USER_STORIES.md",
    "docs/security.md",
    "docs/tutorial/howto-technical.md",
    "docs/tutorial/testing-runbook.md",
    "docs/QUICKSTART.md",
}

HARDCODED_COUNT = re.compile(r"\b\d+\s+passed\b")
DENYLIST: list[tuple[str, str]] = [
    ("MCP later", "MCP ships now (S0.6)"),
    ("path-or-git-url", "pack add takes a directory or bundled name; Git sources are not shipped"),
    ("pack upgrade", "no such CLI command exists (S0.6)"),
    ("personal.sqlite", "internal migration vocabulary must not reach public copy (S0.5)"),
    ("Phase 0 alias", "internal migration vocabulary must not reach public copy (S0.5)"),
    ("write endpoints were removed", "the HTTP write seam is restored (ADR-006)"),
    ("410 Gone", "no advertised endpoint returns 410 anymore (ADR-006)"),
    ("read-only viewer", "the daemon serves the full read/write contract (ADR-006)"),
]

# Product-track files: everyday English only.
PRODUCT_TRACK = {
    "README.md",
    "docs/index.md",
    "docs/gallery.md",
    "docs/tutorial/getting-started.md",
    "docs/tutorial/howto-non-technical.md",
    "docs/tutorial/connect-your-agent.md",
    "docs/tutorial/adopt-in-place.md",
    "docs/tutorial/end-to-end.html",
}
PRODUCT_DENYLIST: list[tuple[str, str]] = [
    ("agent harness", "product track markets a personal app, not a harness"),
    ("structured-life data layer", "product track leads with user outcomes"),
    ("HarnessAPI", "internal type name must not reach product copy"),
    ("personal agent harness", "product track markets a personal app, not a harness"),
    ("Routed →", "product track files notes in plain language"),
    ("eval_case", "internal eval vocabulary must not reach product copy"),
    ("analog pack", "product track talks about interests and looks, not analog packs"),
    ("two case studies", "there are three weekend stories: bake, dive, cards"),
    # PyPI is unpublished. Product pages must lead with checkout (`pip install -e .`).
    (
        "pipx install domain-foundry-core",
        "PyPI is unpublished; product track leads with checkout install",
    ),
]


def public_files() -> list[Path]:
    files = [ROOT / "README.md"]
    for path in sorted((ROOT / "docs").rglob("*")):
        if path.suffix not in {".md", ".html"}:
            continue
        rel = path.relative_to(ROOT).as_posix()
        if rel in EXCLUDE_FILES or any(rel.startswith(p) for p in EXCLUDE_PREFIXES):
            continue
        files.append(path)
    return files


def main() -> int:
    failures: list[str] = []
    scanned = public_files()
    for path in scanned:
        rel = path.relative_to(ROOT).as_posix()
        text = path.read_text(encoding="utf-8")
        for lineno, line in enumerate(text.splitlines(), 1):
            if HARDCODED_COUNT.search(line):
                failures.append(
                    f"{rel}:{lineno}: hardcoded test count ({line.strip()[:80]!r}) — "
                    "say 'full suite green' instead"
                )
            for needle, why in DENYLIST:
                if needle.lower() in line.lower():
                    failures.append(f"{rel}:{lineno}: known-false claim {needle!r} — {why}")
            if rel in PRODUCT_TRACK:
                for needle, why in PRODUCT_DENYLIST:
                    if needle.lower() in line.lower():
                        failures.append(f"{rel}:{lineno}: product-voice {needle!r} — {why}")
    if failures:
        print(f"docs_claims_check: {len(failures)} failure(s)")
        for failure in failures:
            print(f"  {failure}")
        return 1
    print(f"docs_claims_check: OK ({len(scanned)} files scanned)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
