"""What a marked-up page becomes, and what a broken one is told.

A marks file is the only thing that crosses from the browser back to the build,
so it has to say plainly what is wrong when it is wrong.
"""

from __future__ import annotations

import json

import pytest

from domain_foundry_core.review.marks import (
    MARKS_VERSION,
    MarksError,
    check_token_overrides,
    marks_from_choice,
    parse_marks,
    read_marks,
)


def a_marks_payload(**changes) -> dict:
    payload = {
        "marks_version": MARKS_VERSION,
        "look_id": "sourdough-lab-look",
        "chosen_concept": "lab",
        "concepts": {
            "ritual": {
                "topology": "hub",
                "borrow": "the big Feed now button",
                "borrow_reason": "it is the only thing I want at 6am",
            },
            "lab": {
                "topology": "workflow",
                "typography_stack": "data_sans",
                "density_scale": "dense",
                "token_overrides": {"accent": "#E39A2D"},
                "signature_elements": ["progress_bar"],
                "pins": [{"x": 8.0, "y": 12.0, "text": "the timer belongs first"}],
                "notes": ["keep the crumb photo big"],
            },
        },
        "notes": ["I open this one handed"],
        "saved_at": "2026-08-28T09:12:00Z",
    }
    payload.update(changes)
    return payload


def test_marks_become_the_binding_the_build_reads() -> None:
    binding = parse_marks(a_marks_payload()).to_binding()
    assert binding.look_id == "sourdough-lab-look"
    assert binding.concept_id == "lab"
    assert binding.topology == "workflow"
    assert binding.typography_stack == "data_sans"
    assert binding.density_scale == "dense"
    assert binding.token_overrides == {"accent": "#E39A2D"}
    assert binding.signature_elements == ["progress_bar"]
    assert binding.approved_at == "2026-08-28T09:12:00Z"


def test_a_piece_borrowed_from_another_concept_travels() -> None:
    binding = parse_marks(a_marks_payload()).to_binding()
    assert [item.from_concept for item in binding.borrowed_fragments] == ["ritual"]
    assert binding.borrowed_fragments[0].piece == "the big Feed now button"
    assert binding.borrowed_fragments[0].reason == "it is the only thing I want at 6am"


def test_a_pin_keeps_its_place_in_words() -> None:
    binding = parse_marks(a_marks_payload()).to_binding()
    assert "I open this one handed" in binding.notes
    assert "On lab: keep the crumb photo big" in binding.notes
    assert "On lab, top left: the timer belongs first" in binding.notes


def test_nothing_chosen_says_what_to_do() -> None:
    marks = parse_marks(a_marks_payload(chosen_concept=None))
    with pytest.raises(MarksError) as caught:
        marks.to_binding()
    message = str(caught.value)
    assert "Nothing is chosen yet" in message
    assert "press Save" in message


def test_a_concept_that_is_not_on_the_page_is_named() -> None:
    marks = parse_marks(a_marks_payload(chosen_concept="bake_day"))
    with pytest.raises(MarksError) as caught:
        marks.to_binding()
    assert "'bake_day' is not on this page" in str(caught.value)
    assert "lab" in str(caught.value)


def test_a_colour_that_is_not_a_colour_is_rejected_plainly() -> None:
    payload = a_marks_payload()
    payload["concepts"]["lab"]["token_overrides"] = {"accent": "burnt orange"}
    with pytest.raises(MarksError) as caught:
        parse_marks(payload).to_binding()
    message = str(caught.value)
    assert "#E39A2D" in message
    assert "Traceback" not in message


def test_a_field_nobody_writes_is_refused() -> None:
    with pytest.raises(MarksError):
        parse_marks(a_marks_payload(surprise="hello"))


def test_something_that_is_not_a_marks_object_is_refused() -> None:
    with pytest.raises(MarksError) as caught:
        parse_marks(["a list"])
    assert "one JSON object" in str(caught.value)


def test_a_missing_file_says_where_it_looked(tmp_path) -> None:
    with pytest.raises(MarksError) as caught:
        read_marks(tmp_path / "review-marks.json")
    assert str(tmp_path) in str(caught.value)
    assert "--marks" in str(caught.value)


def test_broken_json_says_which_line(tmp_path) -> None:
    path = tmp_path / "review-marks.json"
    path.write_text("{ not json", encoding="utf-8")
    with pytest.raises(MarksError) as caught:
        read_marks(path)
    assert "not valid JSON" in str(caught.value)


def test_a_good_file_round_trips_off_disk(tmp_path) -> None:
    path = tmp_path / "review-marks.json"
    path.write_text(json.dumps(a_marks_payload()), encoding="utf-8")
    assert read_marks(path).to_binding().concept_id == "lab"


def test_flags_and_the_page_end_in_the_same_binding() -> None:
    from_page = parse_marks(
        {
            "marks_version": MARKS_VERSION,
            "look_id": "sourdough-lab-look",
            "chosen_concept": "lab",
            "concepts": {
                "lab": {
                    "topology": "workflow",
                    "typography_stack": "data_sans",
                    "density_scale": "dense",
                    "token_overrides": {"accent": "#E39A2D"},
                }
            },
        }
    ).to_binding()
    from_flags = marks_from_choice(
        look_id="sourdough-lab-look",
        concept_id="lab",
        token_overrides={"accent": "#E39A2D"},
        topology="workflow",
        typography_stack="data_sans",
        density_scale="dense",
    ).to_binding()
    assert from_page == from_flags


def test_token_names_are_checked_before_anything_is_written() -> None:
    with pytest.raises(MarksError) as caught:
        check_token_overrides({"accent_colour": "#E39A2D"})
    assert "no colour called 'accent_colour'" in str(caught.value)
    with pytest.raises(MarksError) as caught:
        check_token_overrides({"radius_px": "99"})
    assert "0 to 24" in str(caught.value)
    check_token_overrides({"radius_px": "12", "accent": "#E39A2D"})
