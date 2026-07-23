"""Generic provenance-preserving importer framework (Phase 2).

API sketch::

    from domain_foundry_core.migrations.importers import (
        FixtureSource,
        GenericImporter,
        load_mapping,
    )

    mapping = load_mapping("examples/importers/japanese_vocab.yaml")
    source = FixtureSource("tests/fixtures/importers/japanese/")
    importer = GenericImporter(workspace, mapping, dry_run=True)
    report = importer.run(source)          # dry-run: would_import counts
    assert report.complete

    importer = GenericImporter(workspace, mapping, dry_run=False)
    applied = importer.run(source)         # writes capture/entry/canonical
    noop = importer.run(source)            # idempotent: skipped_existing
    assert noop.imported == 0 and noop.skipped_existing == applied.imported

Private HermesWorkspace drivers implement :class:`SourceDriver` and live
outside this package (never mutate private DBs — open with ``mode=ro``).
"""

from domain_foundry_core.migrations.importers.config import (
    EntityMapping,
    MappingConfig,
    load_mapping,
    render_template,
)
from domain_foundry_core.migrations.importers.importer import GenericImporter
from domain_foundry_core.migrations.importers.models import (
    ReconciliationReport,
    RecordOutcome,
)
from domain_foundry_core.migrations.importers.source import (
    DictSource,
    FixtureSource,
    SourceDriver,
    SqliteTableSource,
)

__all__ = [
    "DictSource",
    "EntityMapping",
    "FixtureSource",
    "GenericImporter",
    "MappingConfig",
    "RecordOutcome",
    "ReconciliationReport",
    "SourceDriver",
    "SqliteTableSource",
    "load_mapping",
    "render_template",
]
