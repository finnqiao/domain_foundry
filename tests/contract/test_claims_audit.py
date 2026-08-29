"""The claims audit is green on this tree, and red on a tree that lies.

Lane A of docs/rebuild-plan-2026-08-28. Release proof #5 rests on this file:
if the audit cannot fail, it cannot keep the README honest.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

from domain_foundry_core.foundry import models  # noqa: F401  (warms the import cache)

ROOT = Path(__file__).resolve().parents[2]


def _load_audit():
    spec = importlib.util.spec_from_file_location(
        "claims_audit_under_test", ROOT / "scripts" / "claims_audit.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


audit = _load_audit()


# --------------------------------------------------------------------------
# the whole audit, on the real tree
# --------------------------------------------------------------------------


def test_the_audit_is_clean_on_this_checkout() -> None:
    assert audit.run(ROOT) == []


def test_the_audit_exits_zero_on_this_checkout() -> None:
    assert audit.main(["--root", str(ROOT)]) == 0


def test_every_allowlist_entry_gives_a_reason() -> None:
    allowlist = audit.load_allowlist(ROOT / "scripts" / "claims_audit_allowlist.yaml")
    assert allowlist, "the allowlist file must exist and be readable"
    assert audit.check_allowlist_reasons(allowlist) == []


def test_a_reason_without_a_shape_is_rejected() -> None:
    failures = audit.check_allowlist_reasons({"spec_fields": {"VisualWorld.avoid": "because"}})
    assert len(failures) == 1
    assert "needs a reason" in failures[0]


# --------------------------------------------------------------------------
# check 1: spec fields
# --------------------------------------------------------------------------


def _tree_with_readers(tmp_path: Path, compiler: str = "", runtime: str = "") -> Path:
    foundry = tmp_path / "core" / "domain_foundry_core" / "foundry"
    foundry.mkdir(parents=True)
    (foundry / "compiler.py").write_text(compiler, encoding="utf-8")
    (foundry / "runtime.js").write_text(runtime, encoding="utf-8")
    return tmp_path


def test_a_field_with_no_reader_and_no_allowlist_entry_fails(tmp_path: Path) -> None:
    root = _tree_with_readers(tmp_path)
    failures = audit.check_spec_fields(root, {})
    assert any("VisualWorld.avoid" in failure for failure in failures)
    assert any("ImplementationSpec.targets" in failure for failure in failures)


def test_a_qualified_read_counts_as_a_reader(tmp_path: Path) -> None:
    root = _tree_with_readers(tmp_path, runtime="const a = spec.experience.visual_world.avoid;\n")
    failures = audit.check_spec_fields(root, {})
    assert not any("VisualWorld.avoid" in failure for failure in failures)


def test_a_local_alias_counts_as_a_reader(tmp_path: Path) -> None:
    root = _tree_with_readers(
        tmp_path,
        runtime="const world = spec.experience.visual_world;\nrender(world.density_scale);\n",
    )
    failures = audit.check_spec_fields(root, {})
    assert not any("VisualWorld.density_scale" in failure for failure in failures)


def test_an_allowlisted_field_that_gained_a_reader_is_a_notice_not_a_failure(
    tmp_path: Path,
) -> None:
    root = _tree_with_readers(tmp_path, runtime="spec.experience.visual_world.avoid;\n")
    allowlist = {"spec_fields": {"VisualWorld.avoid": "not yet: B"}}
    assert not any(
        "now has a reader" in failure for failure in audit.check_spec_fields(root, allowlist)
    )
    stale = audit.stale_allowlist_entries(root, allowlist)
    assert any("now has a reader" in notice for notice in stale)


def test_strict_allowlist_turns_a_stale_entry_into_a_failure() -> None:
    # The real tree, strictly: whatever the lanes have landed, an entry that is
    # no longer needed must be visible to the integrator.
    strict = audit.run(ROOT, ("fields",), strict_allowlist=True)
    loose = audit.run(ROOT, ("fields",))
    assert len(strict) >= len(loose)


def test_an_allowlist_entry_for_an_unknown_field_fails(tmp_path: Path) -> None:
    root = _tree_with_readers(tmp_path)
    failures = audit.check_spec_fields(root, {"spec_fields": {"Nonsense.field": "not yet: B"}})
    assert any("names no field" in failure for failure in failures)


# --------------------------------------------------------------------------
# check 2: copy rules
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("line", "needle"),
    [
        ("Pick a look — then build it.", "em dash"),
        ("The starter pack is free.", "cost word"),
        ("Upgrade for $9 a month.", "a price"),
    ],
)
def test_the_copy_check_catches_a_broken_rule(line: str, needle: str) -> None:
    failures = audit.scan_copy_text("docs/example.md", line)
    assert any(needle in failure for failure in failures)


@pytest.mark.parametrize(
    "line",
    [
        "Free-text notes go in as they are.",
        "The export is secrets-free.",
        "Pick a look, then say build it.",
    ],
)
def test_the_copy_check_leaves_honest_lines_alone(line: str) -> None:
    assert audit.scan_copy_text("docs/example.md", line) == []


def test_the_copy_check_reads_python_string_literals(tmp_path: Path) -> None:
    module = tmp_path / "core" / "domain_foundry_core"
    module.mkdir(parents=True)
    (module / "cli.py").write_text(
        'def go() -> None:\n    """Build an app — quickly."""\n    print("all set")\n',
        encoding="utf-8",
    )
    failures = audit.check_copy(tmp_path, {})
    assert any("cli.py:2" in failure and "em dash" in failure for failure in failures)


def test_a_page_another_lane_has_not_landed_yet_is_not_a_violation(tmp_path: Path) -> None:
    assert audit.check_copy(tmp_path, {}) == []


def test_an_allowlisted_page_is_skipped(tmp_path: Path) -> None:
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "index.md").write_text("A look — and a build.\n", encoding="utf-8")
    assert audit.check_copy(tmp_path, {}) != []
    assert audit.check_copy(tmp_path, {"copy_files": {"docs/index.md": "not yet: Lane A"}}) == []


def test_an_allowlisted_page_the_audit_never_scans_is_flagged(tmp_path: Path) -> None:
    failures = audit.check_copy(tmp_path, {"copy_files": {"docs/nowhere.md": "not yet: Lane A"}})
    assert any("does not scan" in failure for failure in failures)


# --------------------------------------------------------------------------
# check 3: README claims carry their proof
# --------------------------------------------------------------------------

GOOD_README = """# Title

## What you get

1. **It works offline.** Nothing is sent anywhere.
   <!-- proof: tests/contract/test_export.py -->

## Not true yet

- **Two apps look structurally different.**
  <!-- pending: Lane B, the experience compiler -->
"""


def test_a_readme_with_proof_markers_passes() -> None:
    assert audit.check_readme_claims(GOOD_README, exists=lambda rel: True) == []


def test_a_claim_without_a_marker_fails() -> None:
    text = "# Title\n\n## What you get\n\n1. **It works offline.** Nothing is sent.\n"
    failures = audit.check_readme_claims(text, exists=lambda rel: True)
    assert any("carries no <!-- proof:" in failure for failure in failures)


def test_a_claim_whose_proof_is_missing_fails() -> None:
    failures = audit.check_readme_claims(GOOD_README, exists=lambda rel: False)
    assert any("does not exist" in failure for failure in failures)


def test_a_pending_claim_without_a_lane_fails() -> None:
    text = GOOD_README.replace("  <!-- pending: Lane B, the experience compiler -->\n", "")
    failures = audit.check_readme_claims(text, exists=lambda rel: True)
    assert any("carries no <!-- pending:" in failure for failure in failures)


def test_a_readme_with_no_claim_section_fails() -> None:
    failures = audit.check_readme_claims("# Title\n\nNothing here.\n", exists=lambda rel: True)
    assert any("no '## What you get' section" in failure for failure in failures)


# --------------------------------------------------------------------------
# dead surface (Lane A phase A2)
# --------------------------------------------------------------------------


def test_a_spec_that_can_only_be_built_as_react_stops_with_a_plain_sentence() -> None:
    from domain_foundry_core.foundry.loader import (
        DEFAULT_GOLDENS,
        check_targets_are_buildable,
        load_foundry_spec,
    )

    spec = load_foundry_spec(DEFAULT_GOLDENS / "sourdough-lab.foundry.yaml")
    spec.implementation.targets = ["standalone_react"]
    with pytest.raises(ValueError) as caught:
        check_targets_are_buildable(spec, "my-app.foundry.yaml")
    message = str(caught.value)
    assert "not available yet" in message
    assert "foundry_runtime" in message


def test_a_golden_spec_still_loads_while_it_lists_the_react_target() -> None:
    from domain_foundry_core.foundry.loader import DEFAULT_GOLDENS, load_foundry_spec

    spec = load_foundry_spec(DEFAULT_GOLDENS / "sourdough-lab.foundry.yaml")
    assert "foundry_runtime" in spec.implementation.targets


def test_the_unused_progress_stream_is_gone() -> None:
    source = (ROOT / "core" / "domain_foundry_core" / "api" / "app.py").read_text(encoding="utf-8")
    assert "text/event-stream" not in source
    assert "/events" not in source
