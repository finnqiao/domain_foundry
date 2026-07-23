"""Source drivers for the generic importer.

The private HermesWorkspace driver lives outside this package and should
implement :class:`SourceDriver`. Fixture + generic SQLite table readers are
provided for tests and dry-runs without touching private DBs.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class SourceDriver(Protocol):
    """Yields dict records for one mapped entity."""

    def iter_records(self, entity: str) -> Iterator[dict[str, Any]]:
        """Iterate source rows for ``entity`` (mapping entity name)."""
        ...


class FixtureSource:
    """JSON / JSONL fixture driver keyed by entity name.

    Layout options:
    - directory of ``{entity}.jsonl`` / ``{entity}.json`` files
    - single JSON object ``{ "jp_vocab": [ {...}, ... ], ... }``
    """

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        if not self.path.exists():
            raise FileNotFoundError(f"fixture source not found: {self.path}")
        self._cache: dict[str, list[dict[str, Any]]] | None = None

    def _load_all(self) -> dict[str, list[dict[str, Any]]]:
        if self._cache is not None:
            return self._cache
        if self.path.is_dir():
            data: dict[str, list[dict[str, Any]]] = {}
            for child in sorted(self.path.iterdir()):
                if child.suffix.lower() not in {".json", ".jsonl"}:
                    continue
                data[child.stem] = _load_records_file(child)
            self._cache = data
            return data
        text = self.path.read_text(encoding="utf-8")
        if self.path.suffix.lower() == ".jsonl":
            records = [_parse_json_line(line) for line in text.splitlines() if line.strip()]
            # single-entity file: entity name = stem
            self._cache = {self.path.stem: records}
            return self._cache
        payload = json.loads(text)
        if isinstance(payload, list):
            self._cache = {self.path.stem: [dict(r) for r in payload]}
        elif isinstance(payload, dict):
            out: dict[str, list[dict[str, Any]]] = {}
            for key, value in payload.items():
                if not isinstance(value, list):
                    raise ValueError(
                        f"fixture entity {key!r} must be a list, got {type(value).__name__}"
                    )
                out[str(key)] = [dict(r) for r in value]
            self._cache = out
        else:
            raise ValueError(f"unsupported fixture root type: {type(payload).__name__}")
        return self._cache

    def iter_records(self, entity: str) -> Iterator[dict[str, Any]]:
        yield from self._load_all().get(entity, [])

    def entities(self) -> list[str]:
        return sorted(self._load_all())


class SqliteTableSource:
    """Read-only SQLite table source (generic; not Hermes-specific).

    Always opens with ``mode=ro`` URI. Mapping: entity name → table name
    (default identity). Optional ``where`` / ``order_by`` per entity.
    """

    def __init__(
        self,
        db_path: Path | str,
        *,
        tables: dict[str, str] | None = None,
        where: dict[str, str] | None = None,
        order_by: dict[str, str] | None = None,
    ) -> None:
        self.db_path = Path(db_path)
        if not self.db_path.exists():
            raise FileNotFoundError(f"sqlite source not found: {self.db_path}")
        self.tables = dict(tables or {})
        self.where = dict(where or {})
        self.order_by = dict(order_by or {})

    def iter_records(self, entity: str) -> Iterator[dict[str, Any]]:
        table = self.tables.get(entity, entity)
        # Strict identifier check — never interpolate untrusted names.
        if not _safe_ident(table):
            raise ValueError(f"unsafe table name for entity {entity!r}: {table!r}")
        sql = f"SELECT * FROM {table}"
        clause = self.where.get(entity)
        if clause:
            sql += f" WHERE {clause}"
        order = self.order_by.get(entity)
        if order:
            sql += f" ORDER BY {order}"
        uri = f"file:{self.db_path.resolve()}?mode=ro"
        conn = sqlite3.connect(uri, uri=True)
        conn.row_factory = sqlite3.Row
        try:
            for row in conn.execute(sql):
                yield {k: row[k] for k in row.keys()}
        finally:
            conn.close()


class DictSource:
    """In-memory source for unit tests."""

    def __init__(self, records: dict[str, Sequence[dict[str, Any]]]) -> None:
        self._records = {k: [dict(r) for r in v] for k, v in records.items()}

    def iter_records(self, entity: str) -> Iterator[dict[str, Any]]:
        yield from self._records.get(entity, [])


def _safe_ident(name: str) -> bool:
    return bool(name) and name.replace("_", "").isalnum() and not name[0].isdigit()


def _parse_json_line(line: str) -> dict[str, Any]:
    obj = json.loads(line)
    if not isinstance(obj, dict):
        raise ValueError(f"JSONL row must be object, got {type(obj).__name__}")
    return obj


def _load_records_file(path: Path) -> list[dict[str, Any]]:
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".jsonl":
        return [_parse_json_line(line) for line in text.splitlines() if line.strip()]
    payload = json.loads(text)
    if isinstance(payload, list):
        return [dict(r) for r in payload]
    raise ValueError(f"{path}: expected JSON array")
