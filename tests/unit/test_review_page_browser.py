"""The whole loop through a real browser: open the page, mark it, press Save.

The page is opened from disk with no server anywhere. Save hands back a file,
and that file has to be exactly what the command line then reads. This is the
only test that proves the browser half, so when the browser is missing it skips
loudly rather than passing quietly.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from domain_foundry_core.foundry.loader import load_golden_specs
from domain_foundry_core.review import (
    proposal_from_spec,
    read_marks,
    render_review_page,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
DRIVER = REPO_ROOT / "tests" / "browser" / "review_marks_roundtrip.cjs"
NODE_MODULES = REPO_ROOT / "app" / "node_modules"


def _node() -> str:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed, so the browser leg cannot run")
    if not (NODE_MODULES / "playwright").exists():
        pytest.skip("playwright is not installed in app/node_modules")
    return node


@pytest.mark.slow
def test_marks_round_trip_through_a_headless_browser(tmp_path) -> None:
    node = _node()
    spec = next(item for item in load_golden_specs() if item.id == "sourdough-lab")
    page = tmp_path / "review.html"
    page.write_text(render_review_page(proposal_from_spec(spec, previews=False)), encoding="utf-8")

    finished = subprocess.run(
        [node, str(DRIVER), str(page), str(tmp_path / "downloads")],
        capture_output=True,
        text=True,
        timeout=180,
        env={
            "NODE_PATH": str(NODE_MODULES),
            "PATH": "/usr/bin:/bin:/usr/local/bin",
            "HOME": str(Path.home()),
        },
    )
    if finished.returncode != 0:
        pytest.fail(f"the browser leg failed:\n{finished.stderr}")
    report = json.loads(finished.stdout.strip().splitlines()[-1])

    assert report["page_errors"] == []
    assert report["suggested"] == "review-marks.json"
    assert "Saved review-marks.json" in (report["status"] or "")
    # Focus is visible on whatever you tabbed to.
    assert "none" not in report["focus_outline"]
    # Nothing spills sideways at 320 pixels.
    assert report["overflows_at_320"] is False

    marks = read_marks(Path(report["saved"]))
    binding = marks.to_binding()
    assert binding.concept_id == report["chosen"]
    assert binding.token_overrides["accent"] == "#E39A2D"
    assert binding.density_scale == "dense"
    assert binding.topology == "workflow"
    assert [item.from_concept for item in binding.borrowed_fragments] == [report["other"]]
    assert binding.borrowed_fragments[0].piece == "the big Feed now button"
    assert any("the timer belongs first" in note for note in binding.notes)
    assert "I open this one handed" in binding.notes
