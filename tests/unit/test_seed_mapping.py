"""E2: the mapping the story describes, and honest gaps when it cannot tell."""

from __future__ import annotations

from pathlib import Path

import pytest

from domain_foundry_core.llm.provider import CompletionResult, LLMProvider, TokenUsage
from domain_foundry_core.seed.mapping import (
    MODEL_NOTE,
    SeedMappingError,
    infer_mapping,
    load_seed_mapping,
    save_seed_mapping,
)
from domain_foundry_core.seed.readers import read_seed

FIXTURES = Path(__file__).resolve().parents[2] / "examples" / "seed-fixtures"


def _tidepool_mapping(name: str = "tidepool-log.xlsx"):
    read = read_seed(FIXTURES / name)
    return read, infer_mapping(read, domain="tidepools", object_type="sighting")


class _RecordingProvider(LLMProvider):
    """Stands in for the user's model and records exactly what it was shown."""

    name = "recording"

    def __init__(self, answer: dict | None = None) -> None:
        self.calls: list[dict] = []
        self.answer = answer or {"columns": []}

    def complete_json(self, *, system, user, schema=None, model=None, tier=None):
        self.calls.append({"system": system, "user": user})
        return CompletionResult(data=self.answer, usage=TokenUsage())


def test_the_tidepool_log_maps_the_way_the_story_says():
    _, mapping = _tidepool_mapping()

    roles = {column.column: column.role for column in mapping.columns}
    assert roles == {
        "Date": "date",
        "Place": "place",
        "Species": "category",
        "Count": "quantity",
        "Notes": "free_text",
    }
    assert mapping.row_count == 214
    assert mapping.unmapped_columns == []


def test_the_repeated_values_become_lists_of_their_own():
    """Seven places and nine species are the shape of the practice, not free text."""

    _, mapping = _tidepool_mapping()

    lists = {item.column: item.distinct for item in mapping.lists}
    assert lists == {"Place": 7, "Species": 9}
    assert "Notes" not in lists


def test_the_mapping_says_what_it_will_do_in_a_sentence():
    _, mapping = _tidepool_mapping()

    assert mapping.sentence() == (
        "I will treat each row as one record for something you saw on a day, "
        "at a place, in a table called sighting."
    )


def test_the_same_log_saved_as_csv_maps_the_same():
    _, from_xlsx = _tidepool_mapping("tidepool-log.xlsx")
    _, from_csv = _tidepool_mapping("tidepool-log.csv")

    assert {c.column: c.role for c in from_csv.columns} == {
        c.column: c.role for c in from_xlsx.columns
    }
    assert [item.distinct for item in from_csv.lists] == [item.distinct for item in from_xlsx.lists]


def test_an_ambiguous_file_lists_what_it_could_not_work_out():
    read = read_seed(FIXTURES / "ambiguous.csv")
    mapping = infer_mapping(read, domain="whatever")

    assert mapping.unmapped_columns == ["b", "c", "d"]
    assert any("could not tell" in note for note in mapping.notes)
    # A guess dressed up as an answer is worse than saying nothing.
    assert all(column.confidence == 0.0 for column in mapping.columns if not column.mapped)


def test_the_mapping_turns_into_the_importer_shape_the_repo_already_reads():
    from domain_foundry_core.migrations.importers import MappingConfig

    read, mapping = _tidepool_mapping()
    config = MappingConfig.model_validate(mapping.to_importer_mapping())

    assert len(config.entities) == 1
    entity = config.entities[0]
    assert entity.object_type == "sighting"
    assert entity.timestamp_field == "Date"
    assert entity.field_map == {
        "date": "Date",
        "place": "Place",
        "species": "Species",
        "count": "Count",
        "notes": "Notes",
    }
    # Every seeded row can be traced back to the seed it came from.
    assert entity.source_ref_template.startswith(f"seed:{read.provenance.id}:")


def test_a_personal_upload_lands_on_a_channel_that_says_so():
    _, mapping = _tidepool_mapping()

    assert mapping.channel == "seed-personal"


def test_the_model_only_sees_column_names_and_a_few_rows():
    """The whole point of the one model call is how little it is given."""

    read = read_seed(FIXTURES / "ambiguous.csv")
    provider = _RecordingProvider()

    infer_mapping(read, domain="whatever", provider=provider)

    assert len(provider.calls) == 1
    sent = provider.calls[0]["user"]
    assert "sample_rows" in sent
    # Four rows in the file, five allowed through: the cap is what matters.
    assert sent.count('"a"') <= 6


def test_the_model_only_gets_to_fill_gaps():
    read = read_seed(FIXTURES / "tidepool-log.xlsx")
    provider = _RecordingProvider({"columns": [{"column": "Species", "role": "quantity"}]})

    mapping = infer_mapping(read, domain="tidepools", provider=provider)

    species = next(c for c in mapping.columns if c.column == "Species")
    assert species.role == "category"
    assert mapping.inferred_by == "rules+model"
    assert MODEL_NOTE in mapping.notes


def test_the_model_can_name_a_column_the_rules_left_open():
    read = read_seed(FIXTURES / "ambiguous.csv")
    provider = _RecordingProvider({"columns": [{"column": "d", "role": "category"}]})

    mapping = infer_mapping(read, domain="whatever", provider=provider)

    assert mapping.unmapped_columns == ["b", "c"]
    named = next(c for c in mapping.columns if c.column == "d")
    assert named.role == "category"
    assert named.confidence == 0.5


def test_a_model_that_will_not_answer_leaves_the_rules_standing():
    class _Broken(LLMProvider):
        name = "broken"

        def complete_json(self, *, system, user, schema=None, model=None, tier=None):
            raise RuntimeError("no key set")

    read = read_seed(FIXTURES / "tidepool-log.xlsx")
    mapping = infer_mapping(read, domain="tidepools", provider=_Broken())

    assert {c.column: c.role for c in mapping.columns}["Place"] == "place"
    assert any("did not answer" in note for note in mapping.notes)


def test_a_page_has_no_rows_to_map_and_says_so():
    read = read_seed(FIXTURES / "field-guide.html")

    with pytest.raises(SeedMappingError) as caught:
        infer_mapping(read, domain="tidepools")

    assert "no rows" in str(caught.value)


def test_a_mapping_can_be_saved_edited_and_handed_back(tmp_path: Path):
    _, mapping = _tidepool_mapping()
    path = save_seed_mapping(mapping, tmp_path / "mapping.yaml")

    text = path.read_text(encoding="utf-8")
    edited = text.replace("role: free_text", "role: category")
    path.write_text(edited, encoding="utf-8")

    reloaded = load_seed_mapping(path)
    assert {c.column: c.role for c in reloaded.columns}["Notes"] == "category"
    assert reloaded.seed_id == mapping.seed_id


def test_a_mapping_with_a_role_nobody_knows_says_which_roles_exist(tmp_path: Path):
    _, mapping = _tidepool_mapping()
    path = save_seed_mapping(mapping, tmp_path / "mapping.yaml")
    path.write_text(
        path.read_text(encoding="utf-8").replace("role: date", "role: vibes"),
        encoding="utf-8",
    )

    with pytest.raises(SeedMappingError) as caught:
        load_seed_mapping(path)

    assert "'vibes' is not a role I know" in str(caught.value)
    assert "quantity" in str(caught.value)
