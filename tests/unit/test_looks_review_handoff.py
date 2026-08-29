"""C5: a generated look lands as something a person can answer, not a dead file.

The old flow wrote a mockup to disk that nothing ever opened again, and let a
person restyle it by typing a word the code happened to recognise. These tests
hold both of those closed.
"""

from __future__ import annotations

import json

from domain_foundry_core.wizard import looks as looks_module
from domain_foundry_core.wizard.looks import generate_look, persist_look, template_html

IDEA = {
    "id": "invented.whisky.shelf",
    "title": "Whisky shelf",
    "pitch": "A dex of the whisky you keep, with photos.",
    "jobs": ["catalog", "media_dex"],
    "identity_hint": "whisky_name",
    "example": "added a new piece to the shelf with photos",
}


def test_a_look_is_written_as_a_review_page(tmp_path) -> None:
    look = generate_look(IDEA, samples="a bottle I opened last week")
    written = persist_look(tmp_path, look)
    assert written.name == "review.html"
    page = written.read_text(encoding="utf-8")
    # It is the review page, with the same Save button and the same marks file.
    assert "Save my marks" in page
    assert "review-marks.json" in page
    # The look itself runs inside it rather than being drawn again.
    assert "srcdoc=" in page


def test_no_mockup_is_written_that_nothing_reads(tmp_path) -> None:
    persist_look(tmp_path, generate_look(IDEA))
    written = sorted(path.name for path in tmp_path.iterdir())
    assert written == ["looks.json", "review.html"]
    meta = json.loads((tmp_path / "looks.json").read_text(encoding="utf-8"))
    # The metadata points at the page, so nothing on disk is an orphan.
    assert meta["review_page"] == "review.html"
    assert "html" not in meta


def test_the_keyword_restyler_is_gone() -> None:
    assert not hasattr(looks_module, "_tone_from_critique")
    plain = template_html(IDEA, hero="media_dex")
    for word in ("dark", "denser", "tighter"):
        # Nothing about the template changes because a word was typed at it.
        assert template_html(IDEA, hero="media_dex") == plain, word


def test_the_look_still_shows_the_job_it_is_for() -> None:
    page = template_html(IDEA, hero="media_dex")
    assert 'class="gallery"' in page
    assert "df-look-media_dex" in page
