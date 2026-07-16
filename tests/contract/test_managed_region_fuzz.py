"""P4 gate: managed-region fuzz — user edits outside markers always survive."""

from __future__ import annotations

import random

from domain_expert_core.projections.markdown import (
    content_managed_section,
    merge_managed_markdown,
    parse_managed_sections,
    write_managed_note,
)

_SAFE_WORDS = [
    "note", "todo", "idea", "TODO:", "remember", "the crumb was open",
    "tasted sour", "###", "- bullet", "> quote", "next time less salt", "",
    "https://example.test/x", "café notes", "石窯で焼いた",
]


def _random_free_text(rng: random.Random) -> str:
    lines = [rng.choice(_SAFE_WORDS) for _ in range(rng.randint(0, 6))]
    text = "\n".join(lines)
    # Free text must never contain managed markers (guaranteed by the corpus).
    assert "%%managed" not in text
    return text


def test_managed_region_fuzz_preserves_free_zones():
    section = "bake:01ABC"
    for seed in range(300):
        rng = random.Random(seed)

        v1 = content_managed_section(
            section, "# Loaf v1\n- Hydration: 75%", object_uid="01ABC"
        )
        free_before = _random_free_text(rng)
        free_after = _random_free_text(rng)
        marker_before = f"USER_BEFORE_{seed}"
        marker_after = f"USER_AFTER_{seed}"

        # Compose a user-owned document: free zones surround the managed block.
        existing = (
            f"{marker_before}\n{free_before}\n\n{v1}\n\n{free_after}\n{marker_after}\n"
        )

        v2 = content_managed_section(
            section, "# Loaf v2\n- Hydration: 80%\n- Result: great", object_uid="01ABC"
        )
        merged = merge_managed_markdown(existing, v2)

        # Free zones survive verbatim.
        assert marker_before in merged
        assert marker_after in merged
        for line in (free_before + "\n" + free_after).splitlines():
            if line.strip():
                assert line in merged, f"lost user line {line!r} (seed={seed})"

        # Managed region updated to v2, exactly one managed block for the section.
        sections = parse_managed_sections(merged)
        assert set(sections) == {section}
        assert "Loaf v2" in merged
        assert "80%" in merged
        assert "Loaf v1" not in merged
        assert "75%" not in merged


def test_managed_region_new_section_appended_free_zones_intact():
    existing = (
        "MY HEADER\n\n"
        + content_managed_section("bake:A", "# A", object_uid="A")
        + "\n\nMY FOOTER\n"
    )
    rendered = (
        content_managed_section("bake:A", "# A updated", object_uid="A")
        + "\n\n"
        + content_managed_section("bake:B", "# B new", object_uid="B")
    )
    merged = merge_managed_markdown(existing, rendered)
    assert "MY HEADER" in merged
    assert "MY FOOTER" in merged
    assert "# A updated" in merged
    assert "# B new" in merged
    assert set(parse_managed_sections(merged)) == {"bake:A", "bake:B"}


def test_write_managed_note_roundtrip_on_disk(tmp_path):
    note = tmp_path / "vault" / "Sourdough" / "bake" / "loaf.md"
    v1 = content_managed_section("bake:X", "# Loaf\n- Hydration: 70%", object_uid="X")
    write_managed_note(note, v1)

    # User hand-edits the file, adding free text outside the markers.
    text = note.read_text(encoding="utf-8")
    note.write_text(text + "\nMY PRIVATE TASTING NOTES\n", encoding="utf-8")

    # Re-render (projection refresh): managed region updates, free text survives.
    v2 = content_managed_section("bake:X", "# Loaf\n- Hydration: 85%", object_uid="X")
    write_managed_note(note, v2)

    final = note.read_text(encoding="utf-8")
    assert "MY PRIVATE TASTING NOTES" in final
    assert "85%" in final
    assert "70%" not in final
