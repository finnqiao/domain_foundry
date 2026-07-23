from __future__ import annotations

from domain_foundry_core.ledger.migrate import (
    ensure_migrated,
    init_workspace,
    migration_files,
    read_schema_version,
)
from domain_foundry_core.paths import Workspace
from domain_foundry_core.security.store import connect_ro


def test_migration_files_discovered():
    ledger = migration_files("ledger")
    domains = migration_files("domains")
    assert ledger and ledger[0][0] == 1
    assert domains and domains[0][0] == 1
    assert any(version == 3 for version, _ in ledger)
    assert any(version == 4 for version, _ in ledger)
    assert any(version == 5 for version, _ in ledger)
    assert any(version == 6 for version, _ in ledger)
    assert any(version == 7 for version, _ in ledger)


def test_init_workspace_applies_migrations(workspace: Workspace):
    versions = init_workspace(workspace.home)
    assert versions["ledger"] >= 7
    assert versions["domains"] >= 1
    assert workspace.ledger_db.exists()
    assert workspace.domains_db.exists()
    assert read_schema_version(workspace.ledger_db) == versions["ledger"]

    # Idempotent re-run
    again = init_workspace(workspace.home)
    assert again == versions


def test_substrate_tables_exist(workspace: Workspace):
    ensure_migrated(workspace.ledger_db, "ledger")
    conn = connect_ro(workspace.ledger_db)
    try:
        names = {
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
    finally:
        conn.close()
    required = {
        "capture_event",
        "entry",
        "source_link",
        "interpretation",
        "change_request",
        "approval_queue",
        "canonical_object",
        "object_revision",
        "correction_event",
        "projection_outbox",
        "projection_watermark",
        "apply_policy",
        "schema_registry",
        "eval_case",
        "cost_ledger",
        "unfiled_card",
        "schema_version",
        "search_document",
        "entry_fts",
        "search_fts",
        "inbox_journal",
        "domain_inbox",
        "outbound_queue",
        "domain_session",
        "schedule_run",
    }
    assert required.issubset(names)
