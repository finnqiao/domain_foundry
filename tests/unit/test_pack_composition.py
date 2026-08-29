"""Pack composition: extends, imports, and cross-pack foreign keys (Lane D)."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

import pytest
import yaml

from domain_foundry_core.packs.loader import (
    PackValidationError,
    default_pack_resolver,
    load_pack,
    resolver_for_packs,
)
from domain_foundry_core.packs.schema_compiler import (
    compile_ddl,
    link_columns,
    table_name,
    uninstall_blockers,
)

REPO = Path(__file__).resolve().parents[2]


def _routing(objects: list[str]) -> dict[str, Any]:
    rules = [{"match": name, "object": name} for name in objects]
    examples = [
        {"text": f"{name} number {i}", "expect": {"object": name}}
        for name in objects
        for i in range(4)
    ]
    return {
        "rules": rules,
        "examples": examples[:8] if len(examples) >= 8 else examples * 3,
        "negative_examples": [{"text": "nothing here"}, {"text": "also nothing"}],
    }


def write_pack(
    base: Path,
    name: str,
    *,
    objects: dict[str, Any] | None = None,
    manifest_extra: dict[str, Any] | None = None,
    routing: dict[str, Any] | None = None,
    policy: dict[str, Any] | None = None,
    projections: dict[str, Any] | None = None,
) -> Path:
    """Write a minimal but valid pack directory and return its root."""
    root = base / name
    root.mkdir(parents=True, exist_ok=True)
    objects = (
        objects
        if objects is not None
        else {
            "note": {
                "title_field": "title",
                "fields": {
                    "title": {"type": "text", "required": True},
                    "noted_at": {"type": "datetime", "required": True, "default": "capture_time"},
                },
            }
        }
    )
    manifest = {
        "name": name,
        "version": "0.1.0",
        "title": name.title(),
        "description": f"{name} pack for composition tests.",
        "core_compat": ">=0.1,<2",
    }
    manifest.update(manifest_extra or {})
    (root / "pack.yaml").write_text(yaml.safe_dump(manifest), encoding="utf-8")
    (root / "schema.yaml").write_text(yaml.safe_dump({"objects": objects}), encoding="utf-8")
    (root / "routing.yaml").write_text(
        yaml.safe_dump(routing if routing is not None else _routing(sorted(objects) or ["note"])),
        encoding="utf-8",
    )
    (root / "operations.yaml").write_text(
        yaml.safe_dump({name: ["create", "update"] for name in objects}), encoding="utf-8"
    )
    (root / "policy.yaml").write_text(
        yaml.safe_dump(
            policy if policy is not None else {"defaults": [], "fallback": "unfiled_card"}
        ),
        encoding="utf-8",
    )
    if projections is not None:
        (root / "projections.yaml").write_text(yaml.safe_dump(projections), encoding="utf-8")
    return root


# --- D1: the composition model ---------------------------------------------


def test_pack_without_composition_keys_is_unchanged(tmp_path: Path) -> None:
    write_pack(tmp_path, "plain")
    pack = load_pack(tmp_path / "plain", resolver=resolver_for_packs({}))
    assert pack.extends is None
    assert pack.imports == {}
    assert pack.inherits == []
    assert pack.soft_dependencies == []
    assert set(pack.objects) == {"note"}


def test_extends_merges_objects_routing_and_operations(tmp_path: Path) -> None:
    write_pack(
        tmp_path,
        "base",
        objects={
            "note": {
                "title_field": "title",
                "fields": {"title": {"type": "text", "required": True}, "body": {"type": "text"}},
            },
            "tag": {
                "title_field": "label",
                "fields": {"label": {"type": "text", "required": True}},
            },
        },
    )
    write_pack(
        tmp_path,
        "child",
        objects={
            "note": {
                "fields": {"body": {"type": "text", "long": True}, "rating": {"type": "integer"}}
            },
            "extra": {
                "title_field": "name",
                "fields": {"name": {"type": "text", "required": True}},
            },
        },
        manifest_extra={"extends": "base"},
    )
    pack = load_pack(tmp_path / "child", resolver=default_pack_resolver(tmp_path / "child"))

    assert pack.inherits == ["base"]
    # parent objects arrive, child objects stay, and both keep their own tables
    assert set(pack.objects) == {"note", "tag", "extra"}
    note = pack.objects["note"]
    # child wins per field; parent-only fields survive
    assert note.fields["body"].long is True
    assert "rating" in note.fields
    assert note.fields["title"].required is True
    # child keeps the parent's title_field when it declares none
    assert note.title_field == "title"
    # routing rules concatenate, child first
    assert [r.object for r in pack.routing.rules][:2] == ["extra", "note"]
    assert "tag" in [r.object for r in pack.routing.rules]
    # operations merge
    assert set(pack.operations) == {"note", "tag", "extra"}
    # the inherited object gets the child's table
    assert table_name(pack.name, "tag") == "child__tag"


def test_extends_unknown_pack_names_both_sides(tmp_path: Path) -> None:
    write_pack(tmp_path, "child", manifest_extra={"extends": "missing_pack"})
    with pytest.raises(PackValidationError) as excinfo:
        load_pack(tmp_path / "child", resolver=resolver_for_packs({}))
    message = str(excinfo.value)
    assert "child" in message and "missing_pack" in message


def test_extends_cycle_is_a_load_error(tmp_path: Path) -> None:
    write_pack(tmp_path, "alpha", manifest_extra={"extends": "beta"})
    write_pack(tmp_path, "beta", manifest_extra={"extends": "alpha"})
    with pytest.raises(PackValidationError) as excinfo:
        load_pack(tmp_path / "alpha", resolver=default_pack_resolver(tmp_path / "alpha"))
    message = str(excinfo.value)
    assert "circle" in message
    assert "alpha" in message and "beta" in message


def test_import_resolves_and_stays_owned_by_its_pack(tmp_path: Path) -> None:
    write_pack(
        tmp_path,
        "kitchen",
        objects={
            "dish": {"title_field": "name", "fields": {"name": {"type": "text", "required": True}}}
        },
    )
    write_pack(
        tmp_path,
        "diary",
        objects={
            "day": {
                "title_field": "label",
                "fields": {"label": {"type": "text", "required": True}},
                "links": {"dish": {"to": "kitchen.dish", "cardinality": "many_to_one"}},
            }
        },
        manifest_extra={"imports": [{"from": "kitchen", "object": "dish"}]},
    )
    pack = load_pack(tmp_path / "diary", resolver=default_pack_resolver(tmp_path / "diary"))

    assert set(pack.imports) == {"dish"}
    imported = pack.imports["dish"]
    assert imported.pack == "kitchen" and imported.object == "dish"
    # nothing is copied: the borrowed object is not a diary table
    assert "dish" not in pack.objects
    assert pack.link_target(pack.objects["day"].links["dish"]) == ("kitchen", "dish")


def test_import_can_be_renamed_and_used_by_shorthand(tmp_path: Path) -> None:
    write_pack(
        tmp_path,
        "kitchen",
        objects={
            "dish": {"title_field": "name", "fields": {"name": {"type": "text", "required": True}}}
        },
    )
    write_pack(
        tmp_path,
        "diary",
        objects={
            "day": {
                "title_field": "label",
                "fields": {"label": {"type": "text", "required": True}},
                "links": {"plate": {"to": "plate", "cardinality": "many_to_one"}},
            }
        },
        manifest_extra={"imports": [{"from": "kitchen", "object": "dish", "as": "plate"}]},
    )
    pack = load_pack(tmp_path / "diary", resolver=default_pack_resolver(tmp_path / "diary"))
    assert pack.link_target(pack.objects["day"].links["plate"]) == ("kitchen", "dish")


def test_import_name_collision_names_both_sides(tmp_path: Path) -> None:
    write_pack(
        tmp_path,
        "kitchen",
        objects={
            "note": {"title_field": "name", "fields": {"name": {"type": "text", "required": True}}}
        },
    )
    write_pack(
        tmp_path,
        "diary",
        manifest_extra={"imports": [{"from": "kitchen", "object": "note"}]},
    )
    with pytest.raises(PackValidationError) as excinfo:
        load_pack(tmp_path / "diary", resolver=default_pack_resolver(tmp_path / "diary"))
    message = str(excinfo.value)
    assert "diary" in message and "kitchen.note" in message and "note" in message


def test_import_of_unknown_object_lists_what_is_there(tmp_path: Path) -> None:
    write_pack(
        tmp_path,
        "kitchen",
        objects={
            "dish": {"title_field": "name", "fields": {"name": {"type": "text", "required": True}}}
        },
    )
    write_pack(
        tmp_path,
        "diary",
        manifest_extra={"imports": [{"from": "kitchen", "object": "pudding"}]},
    )
    with pytest.raises(PackValidationError) as excinfo:
        load_pack(tmp_path / "diary", resolver=default_pack_resolver(tmp_path / "diary"))
    message = str(excinfo.value)
    assert "pudding" in message and "dish" in message


def test_import_from_unknown_pack_is_a_load_error(tmp_path: Path) -> None:
    write_pack(tmp_path, "diary", manifest_extra={"imports": [{"from": "ghost", "object": "dish"}]})
    with pytest.raises(PackValidationError) as excinfo:
        load_pack(tmp_path / "diary", resolver=resolver_for_packs({}))
    message = str(excinfo.value)
    assert "ghost" in message and "diary" in message


def test_bundled_packs_still_load(tmp_path: Path) -> None:
    for name in ("travel", "food", "plants", "sourdough", "japanese", "health", "dev", "x_radar"):
        pack = load_pack(REPO / "packs" / name, validate=True)
        assert pack.name == name
        assert pack.extends is None


# --- D2: cross-pack links become foreign keys -------------------------------


def test_cross_pack_link_to_missing_object_is_a_load_error(tmp_path: Path) -> None:
    write_pack(
        tmp_path,
        "kitchen",
        objects={
            "dish": {"title_field": "name", "fields": {"name": {"type": "text", "required": True}}}
        },
    )
    write_pack(
        tmp_path,
        "diary",
        objects={
            "day": {
                "title_field": "label",
                "fields": {"label": {"type": "text", "required": True}},
                "links": {"pudding": {"to": "kitchen.pudding"}},
            }
        },
    )
    with pytest.raises(PackValidationError) as excinfo:
        load_pack(tmp_path / "diary", resolver=default_pack_resolver(tmp_path / "diary"))
    message = str(excinfo.value)
    assert "day.pudding" in message and "kitchen.pudding" in message and "dish" in message


def test_link_into_a_pack_that_is_not_here_is_recorded_not_rejected(tmp_path: Path) -> None:
    write_pack(
        tmp_path,
        "diary",
        objects={
            "day": {
                "title_field": "label",
                "fields": {"label": {"type": "text", "required": True}},
                "links": {"dish": {"to": "kitchen.dish"}},
            }
        },
    )
    pack = load_pack(tmp_path / "diary", resolver=resolver_for_packs({}))
    assert pack.soft_dependencies == ["kitchen.dish"]
    ddl = compile_ddl(pack)
    assert "dish_uid TEXT" in ddl
    assert "FOREIGN KEY (dish_uid)" not in ddl


def test_travel_to_food_compiles_to_a_real_foreign_key() -> None:
    travel = load_pack(REPO / "packs" / "travel", validate=True)
    ddl = compile_ddl(travel, available_packs={"food"})
    assert "FOREIGN KEY (dining_uid) REFERENCES food__dining(object_uid) ON DELETE SET NULL" in ddl
    assert "FOREIGN KEY (trip_uid) REFERENCES travel__trip(object_uid) ON DELETE SET NULL" in ddl
    rows = link_columns(travel, {"food"})["timeline_item"]
    dining = next(row for row in rows if row["link"] == "dining")
    assert dining == {
        "link": "dining",
        "column": "dining_uid",
        "target_pack": "food",
        "target_object": "dining",
        "target": "food.dining",
        "table": "food__dining",
    }


def test_a_dangling_reference_is_refused_by_the_database(tmp_path: Path) -> None:
    travel = load_pack(REPO / "packs" / "travel", validate=True)
    food = load_pack(REPO / "packs" / "food", validate=True)
    db = tmp_path / "domains.sqlite"
    conn = sqlite3.connect(db)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(compile_ddl(food))
    conn.executescript(compile_ddl(travel, available_packs={"food"}))

    conn.execute(
        "INSERT INTO food__dining (object_uid, created_at, updated_at, place, dined_at) "
        "VALUES ('food:dining:1', 'now', 'now', 'Kissa', 'now')"
    )
    conn.execute(
        "INSERT INTO travel__timeline_item "
        "(object_uid, created_at, updated_at, title, scheduled_at, dining_uid) "
        "VALUES ('travel:item:1', 'now', 'now', 'Lunch', 'now', 'food:dining:1')"
    )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO travel__timeline_item "
            "(object_uid, created_at, updated_at, title, scheduled_at, dining_uid) "
            "VALUES ('travel:item:2', 'now', 'now', 'Dinner', 'now', 'food:dining:missing')"
        )
    # deleting the target clears the reference instead of deleting the row
    conn.execute("DELETE FROM food__dining WHERE object_uid = 'food:dining:1'")
    row = conn.execute(
        "SELECT dining_uid FROM travel__timeline_item WHERE object_uid = 'travel:item:1'"
    ).fetchone()
    assert row[0] is None
    conn.close()


def test_removing_a_pack_is_blocked_while_records_point_at_it(tmp_path: Path) -> None:
    travel = load_pack(REPO / "packs" / "travel", validate=True)
    food = load_pack(REPO / "packs" / "food", validate=True)
    db = tmp_path / "domains.sqlite"
    conn = sqlite3.connect(db)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(compile_ddl(food))
    conn.executescript(compile_ddl(travel, available_packs={"food"}))
    conn.execute(
        "INSERT INTO food__dining (object_uid, created_at, updated_at, place, dined_at) "
        "VALUES ('food:dining:1', 'now', 'now', 'Kissa', 'now')"
    )
    conn.commit()
    conn.close()

    assert uninstall_blockers("food", [travel, food], db) == []

    conn = sqlite3.connect(db)
    conn.execute(
        "INSERT INTO travel__timeline_item "
        "(object_uid, created_at, updated_at, title, scheduled_at, dining_uid) "
        "VALUES ('travel:item:1', 'now', 'now', 'Lunch', 'now', 'food:dining:1')"
    )
    conn.commit()
    conn.close()

    blockers = uninstall_blockers("food", [travel, food], db)
    assert len(blockers) == 1
    assert "1 travel timeline_item record still point at food.dining" in blockers[0]
    assert "dining" in blockers[0]


def test_schema_apply_adds_missing_columns_without_dropping_rows(tmp_path: Path) -> None:
    from domain_foundry_core.ledger.migrate import ensure_migrated
    from domain_foundry_core.packs.schema_compiler import apply_pack_schema

    ledger = tmp_path / "ledger.sqlite"
    domains = tmp_path / "domains.sqlite"
    ensure_migrated(ledger, "ledger")
    ensure_migrated(domains, "domains")

    # an older database: the table exists without the link column
    conn = sqlite3.connect(domains)
    conn.executescript(
        "CREATE TABLE diary__day ("
        " id INTEGER PRIMARY KEY AUTOINCREMENT,"
        " object_uid TEXT UNIQUE,"
        " entry_id TEXT,"
        " created_at TEXT NOT NULL,"
        " updated_at TEXT NOT NULL,"
        " tombstoned INTEGER NOT NULL DEFAULT 0,"
        " label TEXT NOT NULL);"
    )
    conn.execute(
        "INSERT INTO diary__day (object_uid, created_at, updated_at, label) "
        "VALUES ('diary:day:1', 'now', 'now', 'Tuesday')"
    )
    conn.commit()
    conn.close()

    write_pack(
        tmp_path,
        "diary",
        objects={
            "day": {
                "title_field": "label",
                "fields": {
                    "label": {"type": "text", "required": True},
                    "weather": {"type": "text"},
                },
                "links": {"other": {"to": "diary.day"}},
            }
        },
    )
    pack = load_pack(tmp_path / "diary", resolver=resolver_for_packs({}))
    apply_pack_schema(pack, domains, ledger)

    conn = sqlite3.connect(domains)
    columns = {row[1] for row in conn.execute("PRAGMA table_info(diary__day)")}
    assert {"weather", "other_uid"} <= columns
    kept = conn.execute("SELECT label FROM diary__day WHERE object_uid = 'diary:day:1'").fetchone()
    assert kept[0] == "Tuesday"
    conn.close()


# --- D4: conformance over composed packs ------------------------------------


def test_conformance_reports_a_valid_composed_pack(tmp_path: Path) -> None:
    import scripts.pack_conformance as conformance

    write_pack(
        tmp_path,
        "kitchen",
        objects={
            "dish": {
                "title_field": "name",
                "fields": {
                    "name": {"type": "text", "required": True},
                    "made_at": {"type": "datetime", "required": True, "default": "capture_time"},
                },
            }
        },
    )
    write_pack(
        tmp_path,
        "diary",
        objects={
            "day": {
                "title_field": "label",
                "fields": {
                    "label": {"type": "text", "required": True},
                    "noted_at": {"type": "datetime", "required": True, "default": "capture_time"},
                },
            }
        },
    )
    write_pack(
        tmp_path,
        "diary_kitchen",
        objects={"day": {"links": {"dish": {"to": "kitchen.dish", "cardinality": "many_to_one"}}}},
        manifest_extra={
            "extends": "diary",
            "imports": [{"from": "kitchen", "object": "dish"}],
        },
        routing={},
    )

    report = conformance.run(tmp_path / "diary_kitchen")
    assert report["status"] == "pass", report
    composition = report["checks"]["composition"]
    assert composition["extends"] == "diary"
    assert composition["inherits"] == ["diary"]
    assert composition["imports"] == [{"name": "dish", "from": "kitchen", "object": "dish"}]
    assert sorted(composition["prerequisites"]) == ["diary", "kitchen"]
    assert {
        "object": "day",
        "column": "dish_uid",
        "references": "kitchen__dish(object_uid)",
    } in composition["foreign_keys"]
    assert composition["waiting_on"] == []


def test_conformance_fails_a_pack_that_borrows_something_that_is_not_there(
    tmp_path: Path,
) -> None:
    import scripts.pack_conformance as conformance

    write_pack(
        tmp_path,
        "kitchen",
        objects={
            "dish": {"title_field": "name", "fields": {"name": {"type": "text", "required": True}}}
        },
    )
    write_pack(
        tmp_path,
        "diary_kitchen",
        manifest_extra={"imports": [{"from": "kitchen", "object": "pudding"}]},
    )
    report = conformance.run(tmp_path / "diary_kitchen")
    assert report["status"] == "fail"
    error = report["checks"]["deep_validation"]["error"]
    assert "pudding" in error and "dish" in error


def test_conformance_fails_a_pack_whose_parent_is_missing(tmp_path: Path) -> None:
    import scripts.pack_conformance as conformance

    write_pack(tmp_path, "orphan", manifest_extra={"extends": "no_such_pack"})
    report = conformance.run(tmp_path / "orphan")
    assert report["status"] == "fail"
    assert "no_such_pack" in report["checks"]["deep_validation"]["error"]


def test_the_template_pack_documents_the_new_keys_and_still_loads() -> None:
    template = REPO / "packs" / "_template"
    manifest = (template / "pack.yaml").read_text(encoding="utf-8")
    schema = (template / "schema.yaml").read_text(encoding="utf-8")
    assert "# extends:" in manifest
    assert "# imports:" in manifest
    assert "# links:" in schema
    pack = load_pack(template, validate=True)
    assert pack.name == "example"
    assert pack.extends is None
    assert pack.imports == {}


def test_the_registry_refuses_to_uninstall_a_pack_records_still_point_at(
    workspace: Any,
) -> None:
    """The guard is wired into `uninstall`, not just available beside it.

    `uninstall_blockers` was proved at the function level by the test above, but
    nothing called it from the registry, so a real uninstall would still have
    broken the references. The integrator wired it in; this pins the wiring.
    """
    from domain_foundry_core.packs.registry import PackRegistry

    registry = PackRegistry(workspace)
    registry.install(REPO / "packs" / "food")
    registry.install(REPO / "packs" / "travel")

    # Nothing points anywhere yet, so the pack is free to go.
    assert uninstall_blockers("food", registry.list(), workspace.domains_db) == []

    conn = sqlite3.connect(workspace.domains_db)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute(
        "INSERT INTO food__dining (object_uid, created_at, updated_at, place, dined_at) "
        "VALUES ('food:dining:1', 'now', 'now', 'Kissa', 'now')"
    )
    conn.execute(
        "INSERT INTO travel__timeline_item "
        "(object_uid, created_at, updated_at, title, scheduled_at, dining_uid) "
        "VALUES ('travel:item:1', 'now', 'now', 'Lunch', 'now', 'food:dining:1')"
    )
    conn.commit()
    conn.close()

    with pytest.raises(ValueError, match="cannot be removed yet"):
        registry.uninstall("food")

    # Refused means refused: the pack and its table are both still there.
    assert (workspace.packs_dir / "food").exists()
    conn = sqlite3.connect(workspace.domains_db)
    table = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'food__dining'"
    ).fetchone()
    conn.close()
    assert table is not None
