"""One-message correction parsing — including the forms the error copy suggests."""

from domain_foundry_core.corrections.intent import parse_correction_text


def test_field_equals_value():
    parsed = parse_correction_text("rating = 9")
    assert parsed.action == "amend"
    assert parsed.fields["rating"] == 9


def test_set_field_to_value():
    parsed = parse_correction_text("set rating to 9")
    assert parsed.fields["rating"] == 9


def test_hydration_was_not():
    parsed = parse_correction_text("hydration was 80 not 75")
    assert parsed.fields["hydration"] == 80
    assert parsed.fields["_wrong"] == 75


def test_proper_noun_is_identity_not_a_new_field():
    parsed = parse_correction_text("that Charizard was LP not NM")
    assert parsed.action == "amend"
    assert "charizard" not in {k.lower() for k in parsed.fields}
    assert parsed.fields.get("_identity") == "Charizard"
    assert str(parsed.fields.get("_value")).upper() == "LP"
    assert str(parsed.fields.get("_wrong")).upper() == "NM"


def test_notes_equals_still_targets_notes():
    parsed = parse_correction_text("notes = LP")
    assert parsed.fields["notes"] == "LP"
