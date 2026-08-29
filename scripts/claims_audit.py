#!/usr/bin/env python3
"""Claims audit: the repo may only say what the code can keep.

Lane A of docs/rebuild-plan-2026-08-28. Three checks, each of which can be run
on its own with ``--check``:

1. ``fields``  Every field on ``VisualWorld``, ``ExperienceSpec`` and
   ``ImplementationSpec`` either has a reader in ``foundry/compiler.py`` or
   ``foundry/runtime.js``, or is listed in the allowlist with a reason.
2. ``copy``    User-facing pages and strings follow the copy rules: no em
   dashes, no cost words.
3. ``claims``  Every feature sentence in the README carries a marker naming the
   test or script that proves it, and that file exists. Claims that are not
   true yet are marked pending instead, with the lane that will make them true.

The allowlist is ``scripts/claims_audit_allowlist.yaml``. It is meant to shrink:
each entry names a reason, and most reasons name the lane that will delete the
entry.

Honest limits of check 1: a reader is detected by a qualified access such as
``visual_world.density`` or ``world["density"]``, including one level of local
alias. It proves a field is mentioned where the app is built, not that the
value changes a pixel. The difference gate in Lane G is what proves that.

Exit code 0 means clean.
"""

from __future__ import annotations

import argparse
import ast
import re
import sys
from collections.abc import Iterable
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
ALLOWLIST_PATH = ROOT / "scripts" / "claims_audit_allowlist.yaml"

# --------------------------------------------------------------------------
# check 1: spec fields have readers
# --------------------------------------------------------------------------

READER_FILES = (
    "core/domain_foundry_core/foundry/compiler.py",
    "core/domain_foundry_core/foundry/runtime.js",
)

# Class name -> the names the built app calls that object by.
RECEIVERS: dict[str, tuple[str, ...]] = {
    "VisualWorld": ("visual_world", "world"),
    "ExperienceSpec": ("experience",),
    "ImplementationSpec": ("implementation",),
}


def _reader_text(root: Path) -> str:
    parts = []
    for rel in READER_FILES:
        path = root / rel
        if path.exists():
            parts.append(path.read_text(encoding="utf-8"))
    return "\n".join(parts)


def _aliases(text: str, receivers: Iterable[str]) -> set[str]:
    """Local names bound to one of the receivers, one level deep.

    Catches ``const tokens = spec.experience.visual_world.tokens`` only as a
    read of ``tokens``; catches ``const world = spec.experience.visual_world``
    as a new receiver name.
    """
    found: set[str] = set()
    for receiver in receivers:
        pattern = re.compile(
            r"(?:const|let|var)?\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*[A-Za-z0-9_.]*\."
            + re.escape(receiver)
            + r"\s*[;\n]"
        )
        found.update(match.group(1) for match in pattern.finditer(text))
    return found


def _is_read(field: str, text: str, receivers: tuple[str, ...]) -> bool:
    names = set(receivers) | _aliases(text, receivers)
    for name in names:
        escaped = re.escape(name)
        patterns = (
            rf"{escaped}\s*\.\s*{re.escape(field)}(?![A-Za-z0-9_])",
            rf"{escaped}\s*\[\s*[\"']{re.escape(field)}[\"']\s*\]",
            rf"{escaped}\s*\.\s*get\(\s*[\"']{re.escape(field)}[\"']",
        )
        if any(re.search(pattern, text) for pattern in patterns):
            return True
    return False


def stale_allowlist_entries(root: Path, allowlist: dict) -> list[str]:
    """Fields that gained a reader while their allowlist entry is still there.

    Not a failure by default. The repo is under-claiming, not lying, and while
    the lanes run in parallel a lane landing a reader would otherwise turn the
    audit red for everybody. ``--strict-allowlist`` makes these fail, which is
    what the integrator runs at a sync point and before a release.
    """

    sys.path.insert(0, str(root / "core"))
    from domain_foundry_core.foundry import models  # noqa: PLC0415

    allowed = allowlist.get("spec_fields", {}) or {}
    text = _reader_text(root)
    stale: list[str] = []
    for class_name, receivers in RECEIVERS.items():
        model = getattr(models, class_name)
        for field in model.model_fields:
            key = f"{class_name}.{field}"
            if key in allowed and _is_read(field, text, receivers):
                stale.append(
                    f"allowlist: {key} now has a reader; delete its entry "
                    f"({allowed[key]}) from {ALLOWLIST_PATH.name}"
                )
    return stale


def check_spec_fields(root: Path, allowlist: dict) -> list[str]:
    sys.path.insert(0, str(root / "core"))
    from domain_foundry_core.foundry import models  # noqa: PLC0415

    allowed = allowlist.get("spec_fields", {}) or {}
    text = _reader_text(root)
    failures: list[str] = []
    known: set[str] = set()
    for class_name, receivers in RECEIVERS.items():
        model = getattr(models, class_name)
        for field in model.model_fields:
            key = f"{class_name}.{field}"
            known.add(key)
            if _is_read(field, text, receivers) or key in allowed:
                continue
            failures.append(
                f"spec field {key} has no reader in the compiler or the runtime. "
                f"Give it one, or add it to {ALLOWLIST_PATH.name} with a reason."
            )
    for key in allowed:
        if key not in known:
            failures.append(f"allowlist: {key} names no field on a class the audit checks")
    return failures


# --------------------------------------------------------------------------
# check 2: copy rules
# --------------------------------------------------------------------------

EM_DASH = "—"

COST_WORDS = re.compile(
    r"(?<![\w-])(free|paid|pricing|premium|subscription|billing|per seat|per-seat)(?![\w-])",
    re.IGNORECASE,
)
PRICE_TAG = re.compile(r"\$\s?\d")

# Pages and modules a user reads. Everything else under docs/ is an internal
# record: plan kits, ADRs, launch notes, status pages.
COPY_TEXT_FILES = (
    "README.md",
    "docs/index.md",
    "docs/gallery.md",
    "docs/QUICKSTART.md",
    "docs/COPY_RULES.md",
    "docs/tutorial/getting-started.md",
    "docs/tutorial/howto-non-technical.md",
    "docs/tutorial/howto-technical.md",
    "docs/tutorial/connect-your-agent.md",
    "docs/tutorial/adopt-in-place.md",
    "docs/tutorial/testing-runbook.md",
    "docs/concepts/index.md",
    "docs/concepts/ledger.md",
    "docs/concepts/packs.md",
    "docs/concepts/routing.md",
    "docs/concepts/corrections.md",
    "docs/concepts/replay.md",
    "docs/concepts/capabilities.md",
    "docs/concepts/idea-atlas.md",
    "app/src/components/FoundryStudio.tsx",
    "app/src/components/CreateDomain.tsx",
)

# Python modules whose string literals reach a person: CLI help, prompts,
# status lines, wizard turns.
COPY_PYTHON_FILES = (
    "core/domain_foundry_core/cli.py",
    "core/domain_foundry_core/cli_setup.py",
)

COPY_PYTHON_GLOBS = ("core/domain_foundry_core/wizard/*.py",)


def _python_string_lines(source: str) -> list[tuple[int, str]]:
    """Every string literal in a module, with the line it starts on.

    Docstrings count: Typer turns a command docstring into its help text.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    out: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            out.append((node.lineno, node.value))
    return out


def scan_copy_text(rel: str, text: str) -> list[str]:
    """Copy violations in a whole-text file (Markdown, TSX)."""
    failures: list[str] = []
    for lineno, line in enumerate(text.splitlines(), 1):
        failures.extend(_copy_violations(rel, lineno, line))
    return failures


def _copy_violations(rel: str, lineno: int, line: str) -> list[str]:
    failures: list[str] = []
    if EM_DASH in line:
        failures.append(f"{rel}:{lineno}: em dash. Use a full stop, a comma, or two sentences.")
    match = COST_WORDS.search(line)
    if match:
        failures.append(
            f"{rel}:{lineno}: cost word {match.group(0)!r}. User-facing copy never mentions money."
        )
    if PRICE_TAG.search(line):
        failures.append(f"{rel}:{lineno}: a price. User-facing copy never mentions money.")
    return failures


def _copy_files(root: Path) -> list[str]:
    rels = list(COPY_TEXT_FILES) + list(COPY_PYTHON_FILES)
    for pattern in COPY_PYTHON_GLOBS:
        parent, _, glob = pattern.rpartition("/")
        for path in sorted((root / parent).glob(glob)):
            rels.append(path.relative_to(root).as_posix())
    return sorted(dict.fromkeys(rels))


def check_copy(root: Path, allowlist: dict) -> list[str]:
    skipped_files = allowlist.get("copy_files", {}) or {}
    failures: list[str] = []
    seen_files: set[str] = set()
    for rel in _copy_files(root):
        path = root / rel
        # Other lanes are still landing files. A page that is not here yet is
        # not a violation; a page that is here is checked.
        if not path.exists():
            continue
        seen_files.add(rel)
        if rel in skipped_files:
            continue
        text = path.read_text(encoding="utf-8")
        if rel.endswith(".py"):
            for lineno, value in _python_string_lines(text):
                failures.extend(_copy_violations(rel, lineno, value))
        else:
            failures.extend(scan_copy_text(rel, text))
    for rel in skipped_files:
        if rel not in seen_files:
            failures.append(f"allowlist: copy_files names {rel}, which the audit does not scan")
    return failures


# --------------------------------------------------------------------------
# check 3: README claims carry their proof
# --------------------------------------------------------------------------

CLAIM_SECTION = "## What you get"
PENDING_SECTION = "## Not true yet"
PROOF_MARKER = re.compile(r"<!--\s*proof:\s*(?P<path>[^\s>]+)\s*-->")
PENDING_MARKER = re.compile(r"<!--\s*pending:\s*(?P<reason>[^>]+?)\s*-->")
LIST_ITEM = re.compile(r"^(?:\d+\.|[-*])\s+\S")


def _sections(text: str) -> dict[str, list[str]]:
    sections: dict[str, list[str]] = {}
    current: str | None = None
    for line in text.splitlines():
        if line.startswith("## "):
            current = line.rstrip()
            sections[current] = []
        elif current is not None:
            sections[current].append(line)
    return sections


def check_readme_claims(text: str, exists: callable, rel: str = "README.md") -> list[str]:
    """Each claim in the claim section names a proof; each pending claim names a lane."""
    failures: list[str] = []
    sections = _sections(text)
    if CLAIM_SECTION not in sections:
        return [f"{rel}: no '{CLAIM_SECTION}' section, so no claims can be checked"]

    for section, marker, label in (
        (CLAIM_SECTION, PROOF_MARKER, "proof"),
        (PENDING_SECTION, PENDING_MARKER, "pending"),
    ):
        lines = sections.get(section)
        if lines is None:
            continue
        blocks: list[tuple[int, list[str]]] = []
        for offset, line in enumerate(lines):
            if LIST_ITEM.match(line):
                blocks.append((offset, [line]))
            elif blocks:
                blocks[-1][1].append(line)
        if not blocks:
            failures.append(f"{rel}: '{section}' lists no claims")
        for _, block in blocks:
            body = "\n".join(block)
            found = marker.search(body)
            headline = block[0].strip()[:70]
            if not found:
                failures.append(
                    f"{rel}: claim {headline!r} carries no <!-- {label}: ... --> marker"
                )
                continue
            if label == "proof":
                proof = found.group("path")
                if not exists(proof):
                    failures.append(
                        f"{rel}: claim {headline!r} names proof {proof}, which does not exist"
                    )

    # A proof marker anywhere else in the README is checked too.
    for match in PROOF_MARKER.finditer(text):
        proof = match.group("path")
        if not exists(proof):
            failures.append(f"{rel}: proof marker names {proof}, which does not exist")
    return failures


def check_claims(root: Path, allowlist: dict) -> list[str]:
    readme = root / "README.md"
    if not readme.exists():
        return ["README.md is missing"]
    return check_readme_claims(
        readme.read_text(encoding="utf-8"),
        exists=lambda rel: (root / rel).exists(),
    )


# --------------------------------------------------------------------------
# driver
# --------------------------------------------------------------------------

REASON_SHAPE = re.compile(r"^(not yet: .+|read by .+|allowed: .+)$")

CHECKS = {
    "fields": check_spec_fields,
    "copy": check_copy,
    "claims": check_claims,
}


def load_allowlist(path: Path) -> dict:
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError(f"{path} must hold a mapping")
    return data


def check_allowlist_reasons(allowlist: dict) -> list[str]:
    failures: list[str] = []
    for section, entries in allowlist.items():
        if not isinstance(entries, dict):
            failures.append(f"allowlist: section {section} must be a mapping of key to reason")
            continue
        for key, reason in entries.items():
            if not isinstance(reason, str) or not REASON_SHAPE.match(reason.strip()):
                failures.append(
                    f"allowlist: {section}.{key} needs a reason starting with "
                    "'not yet: ', 'read by ' or 'allowed: '"
                )
    return failures


def run(
    root: Path = ROOT,
    checks: Iterable[str] = tuple(CHECKS),
    *,
    strict_allowlist: bool = False,
) -> list[str]:
    allowlist = load_allowlist(root / "scripts" / "claims_audit_allowlist.yaml")
    failures = check_allowlist_reasons(allowlist)
    for name in checks:
        failures.extend(CHECKS[name](root, allowlist))
    if strict_allowlist and "fields" in checks:
        failures.extend(stale_allowlist_entries(root, allowlist))
    return failures


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check that the repo only claims what it keeps.")
    parser.add_argument("--check", choices=sorted(CHECKS), action="append", default=None)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument(
        "--strict-allowlist",
        action="store_true",
        help="Also fail on an allowlist entry whose field has gained a reader. "
        "Run this at a sync point and before a release.",
    )
    args = parser.parse_args(argv)
    checks = args.check or sorted(CHECKS)
    failures = run(args.root, checks, strict_allowlist=args.strict_allowlist)
    notices: list[str] = []
    if not args.strict_allowlist and "fields" in checks:
        allowlist = load_allowlist(args.root / "scripts" / "claims_audit_allowlist.yaml")
        notices = stale_allowlist_entries(args.root, allowlist)
    if failures:
        print(f"claims_audit: {len(failures)} failure(s)")
        for failure in failures:
            print(f"  {failure}")
        return 1
    print(f"claims_audit: OK ({', '.join(sorted(checks))})")
    for notice in notices:
        print(f"  note: {notice}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
