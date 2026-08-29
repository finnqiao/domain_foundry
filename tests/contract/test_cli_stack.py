"""The `stack` verb: two packs in, one pack out, with a join the database holds."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest
import typer
from typer.testing import CliRunner

from domain_foundry_core.api.harness import HarnessAPI
from domain_foundry_core.cli_stack import (
    StackError,
    anchor_object,
    default_objects,
    describe,
    register,
    stack_packs,
)
from domain_foundry_core.packs.loader import bundled_packs_root, load_pack
from domain_foundry_core.packs.registry import PackRegistry
from domain_foundry_core.paths import Workspace
from domain_foundry_core.routing.l1 import L1Matcher


@pytest.fixture
def home(tmp_path: Path) -> Path:
    workspace = tmp_path / "home"
    api = HarnessAPI(workspace)
    api.init()
    api.pack_add(bundled_packs_root() / "food", force=True)
    api.pack_add(bundled_packs_root() / "travel", force=True)
    return workspace


def _cli_app() -> typer.Typer:
    app = typer.Typer()
    register(app)

    # A second command keeps typer in subcommand mode, the way cli.py runs it.
    @app.command("noop")
    def _noop() -> None:
        """Placeholder so `stack` stays a named subcommand."""

    return app


def test_anchor_and_default_objects_follow_the_existing_relationship(home: Path) -> None:
    registry = PackRegistry(Workspace(home))
    travel = registry.get("travel")
    food = registry.get("food")
    assert travel is not None and food is not None
    assert anchor_object(travel, "food") == "timeline_item"
    assert default_objects(travel, food) == ["dining"]


def test_stack_travel_food_produces_a_loadable_pack_with_a_real_foreign_key(home: Path) -> None:
    result = stack_packs("travel", "food", home=home)

    assert result["name"] == "travel_food"
    assert result["installed"] is True
    assert result["anchor"] == "timeline_item"
    assert result["objects"] == ["dining"]
    assert result["links"] == [
        {
            "link": "dining",
            "column": "dining_uid",
            "target": "food.dining",
            "target_table": "food__dining",
            "enforced": True,
        }
    ]

    pack = load_pack(Path(result["path"]), validate=True)
    assert pack.name == "travel_food"
    assert pack.inherits == ["travel"]
    assert set(pack.imports) == {"dining"}
    # it kept everything travel had, under its own tables
    assert {"trip", "timeline_item", "booking", "packing_item", "event_log"} <= set(pack.objects)
    assert "dining" not in pack.objects

    ddl = "\n".join(line for line in result["ddl"].splitlines() if "FOREIGN KEY" in line)
    assert "FOREIGN KEY (dining_uid) REFERENCES food__dining(object_uid) ON DELETE SET NULL" in ddl
    # inherited links point at the new pack's own tables, not the parent's
    assert (
        "FOREIGN KEY (trip_uid) REFERENCES travel_food__trip(object_uid) ON DELETE SET NULL" in ddl
    )


def test_the_join_is_enforced_in_the_installed_database(home: Path) -> None:
    stack_packs("travel", "food", home=home)
    domains = home / "db" / "domains.sqlite"
    conn = sqlite3.connect(domains)
    conn.execute("PRAGMA foreign_keys = ON")
    table_sql = conn.execute(
        "SELECT sql FROM sqlite_master WHERE name = 'travel_food__timeline_item'"
    ).fetchone()[0]
    assert "FOREIGN KEY (dining_uid) REFERENCES food__dining(object_uid)" in table_sql

    conn.execute(
        "INSERT INTO food__dining (object_uid, created_at, updated_at, place, dined_at) "
        "VALUES ('food:dining:1', 'now', 'now', 'River Station Grill', 'now')"
    )
    conn.execute(
        "INSERT INTO travel_food__timeline_item "
        "(object_uid, created_at, updated_at, title, scheduled_at, dining_uid) "
        "VALUES ('tf:1', 'now', 'now', 'Dinner', 'now', 'food:dining:1')"
    )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO travel_food__timeline_item "
            "(object_uid, created_at, updated_at, title, scheduled_at, dining_uid) "
            "VALUES ('tf:2', 'now', 'now', 'Dinner', 'now', 'food:dining:gone')"
        )
    conn.close()


def test_the_printed_example_captures_route_and_apply(home: Path) -> None:
    result = stack_packs("travel", "food", home=home)
    registry = PackRegistry(Workspace(home))
    stacked = registry.get("travel_food")
    food = registry.get("food")
    assert stacked is not None and food is not None

    anchor_text = result["example_capture"]["anchor"]
    target_text = result["example_capture"]["target"]
    assert any(
        hit.object_type == result["anchor"] for hit in L1Matcher([stacked]).match(anchor_text).hits
    )
    assert any(hit.object_type == "dining" for hit in L1Matcher([food]).match(target_text).hits)

    api = HarnessAPI(home)
    api.capture(target_text, domain_hint="food")
    api.capture(anchor_text, domain_hint="travel_food")

    # the anchor record landed in the stacked pack's own table
    conn = sqlite3.connect(home / "db" / "domains.sqlite")
    count = conn.execute("SELECT COUNT(*) FROM travel_food__timeline_item").fetchone()[0]
    conn.close()
    assert count >= 1


def test_apply_writes_the_link_column_and_the_database_holds_it(home: Path) -> None:
    stack_packs("travel", "food", home=home)
    conn = sqlite3.connect(home / "db" / "domains.sqlite")
    conn.execute(
        "INSERT INTO food__dining (object_uid, created_at, updated_at, place, dined_at) "
        "VALUES ('food:dining:7', 'now', 'now', 'River Station Grill', 'now')"
    )
    conn.commit()
    conn.close()

    registry = PackRegistry(Workspace(home))
    stacked = registry.get("travel_food")
    assert stacked is not None
    assert "dining_uid" in stacked.objects["timeline_item"].fields

    from domain_foundry_core.apply.engine import ApplyEngine, OperationSpec

    engine = ApplyEngine(Workspace(home), registry=registry)
    result = engine.apply_spec(
        OperationSpec(
            domain="travel_food",
            object_type="timeline_item",
            operation="create",
            payload={
                "title": "Dinner at River Station Grill",
                "dining_uid": "food:dining:7",
            },
        ),
        actor="test",
    )
    assert result.ok, result.error

    conn = sqlite3.connect(home / "db" / "domains.sqlite")
    row = conn.execute(
        "SELECT dining_uid FROM travel_food__timeline_item WHERE title = ?",
        ("Dinner at River Station Grill",),
    ).fetchone()
    conn.close()
    assert row[0] == "food:dining:7"


def test_stack_refuses_a_pack_that_is_not_here(tmp_path: Path) -> None:
    workspace = tmp_path / "home"
    HarnessAPI(workspace).init()
    with pytest.raises(StackError) as excinfo:
        stack_packs("travel", "food", home=workspace)
    assert "travel" in str(excinfo.value)
    assert "pack add" in str(excinfo.value)


def test_stack_asks_which_objects_when_there_is_no_existing_relationship(home: Path) -> None:
    api = HarnessAPI(home)
    api.pack_add(bundled_packs_root() / "plants", force=True)
    with pytest.raises(StackError) as excinfo:
        stack_packs("plants", "food", home=home)
    message = str(excinfo.value)
    assert "--objects" in message
    assert "dining" in message


def test_stack_names_the_objects_a_pack_does_not_have(home: Path) -> None:
    with pytest.raises(StackError) as excinfo:
        stack_packs("travel", "food", objects=["pudding"], home=home)
    assert "pudding" in str(excinfo.value)
    assert "dining" in str(excinfo.value)


def test_out_writes_the_pack_without_turning_it_on(home: Path, tmp_path: Path) -> None:
    destination = tmp_path / "scaffold"
    result = stack_packs("travel", "food", home=home, out=destination)
    assert result["installed"] is False
    assert (destination / "pack.yaml").is_file()
    assert (destination / "schema.yaml").is_file()
    assert not (home / "packs" / "travel_food").exists()


def test_cli_stack_prints_plain_words_and_one_example(home: Path) -> None:
    runner = CliRunner()
    outcome = runner.invoke(
        _cli_app(), ["stack", "travel", "food", "--home", str(home), "--objects", "dining"]
    )
    assert outcome.exit_code == 0, outcome.output
    output = outcome.output
    assert "Made the pack travel_food" in output
    assert "borrows dining from food" in output
    assert "dining_uid" in output
    assert "foreign key into food__dining" in output
    assert "domain-foundry capture" in output
    # copy rules: no em dashes, nothing about money
    assert "—" not in output
    for banned in ("free", "price", "cost", "upgrade", "$"):
        assert banned not in output.lower()


def test_cli_stack_reports_a_missing_pack_and_exits_nonzero(tmp_path: Path) -> None:
    workspace = tmp_path / "home"
    HarnessAPI(workspace).init()
    runner = CliRunner()
    outcome = runner.invoke(_cli_app(), ["stack", "travel", "food", "--home", str(workspace)])
    assert outcome.exit_code == 1
    assert "not turned on here" in outcome.output


def test_cli_stack_json_shape(home: Path) -> None:
    runner = CliRunner()
    outcome = runner.invoke(_cli_app(), ["stack", "travel", "food", "--home", str(home), "--json"])
    assert outcome.exit_code == 0, outcome.output
    payload = json.loads(outcome.output)
    assert payload["name"] == "travel_food"
    assert payload["links"][0]["enforced"] is True


def test_describe_reads_as_sentences(home: Path) -> None:
    text = describe(stack_packs("travel", "food", home=home, out=home.parent / "scaffold2"))
    assert text.startswith("Made the pack travel_food on disk.")
    assert "—" not in text
