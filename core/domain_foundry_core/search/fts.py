"""FTS5 search substrate (Phase 2 / G8)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from domain_foundry_core.security.store import connect_ro

SearchKind = Literal["entry", "canonical"]


class SearchHit(BaseModel):
    kind: SearchKind
    ref_id: str
    domain: str | None = None
    object_type: str | None = None
    raw_text: str | None = None
    canonical_text: str | None = None
    snippet: str | None = None
    rank: float | None = None


class SearchResult(BaseModel):
    query: str
    hits: list[SearchHit] = Field(default_factory=list)
    total: int = 0


_SKIP_FIELDS = frozenset(
    {
        "id",
        "object_uid",
        "entry_id",
        "created_at",
        "updated_at",
        "tombstoned",
        "merged_into_uid",
    }
)


def flatten_searchable_text(fields: dict[str, Any] | None) -> str:
    """Flatten object fields into a single searchable blob."""
    if not fields:
        return ""
    parts: list[str] = []
    for key in sorted(fields):
        if key in _SKIP_FIELDS or key.startswith("_"):
            continue
        value = fields[key]
        if value is None or value == "":
            continue
        if isinstance(value, (dict, list)):
            continue
        parts.append(str(value))
    return " ".join(parts)


def set_canonical_searchable_text(
    ledger_conn: Any,
    object_uid: str,
    fields: dict[str, Any] | None,
    *,
    now: str,
) -> str:
    """Write searchable_text on canonical_object (triggers sync search_document)."""
    text = flatten_searchable_text(fields)
    ledger_conn.execute(
        """
        UPDATE canonical_object
        SET searchable_text = ?, updated_at = ?
        WHERE uid = ?
        """,
        (text or None, now, object_uid),
    )
    return text


def _prepare_match_query(q: str) -> str:
    """Turn a user string into a safe FTS5 MATCH expression (AND of tokens)."""
    tokens: list[str] = []
    for raw in (q or "").split():
        cleaned = "".join(ch for ch in raw if ch.isalnum() or ch in {"_", "-", "'"})
        if not cleaned:
            continue
        # Quote tokens so FTS operators in user input cannot break MATCH.
        safe = cleaned.replace('"', "")
        if safe:
            tokens.append(f'"{safe}"')
    return " AND ".join(tokens)


def search_ledger(
    ledger_db: Any,
    q: str,
    *,
    domain: str | None = None,
    object_type: str | None = None,
    kind: SearchKind | None = None,
    limit: int = 50,
) -> SearchResult:
    """Full-text search over entry raw text and canonical searchable text."""
    query = (q or "").strip()
    limit = max(1, min(int(limit), 500))
    if not query:
        return SearchResult(query=query, hits=[], total=0)

    match = _prepare_match_query(query)
    if not match:
        return SearchResult(query=query, hits=[], total=0)

    sql = """
        SELECT
            sd.kind,
            sd.ref_id,
            sd.domain,
            sd.object_type,
            sd.raw_text,
            sd.canonical_text,
            bm25(search_fts) AS rank,
            snippet(search_fts, 0, '[', ']', '…', 12) AS raw_snippet,
            snippet(search_fts, 1, '[', ']', '…', 12) AS canonical_snippet
        FROM search_fts
        JOIN search_document sd ON sd.id = search_fts.rowid
        WHERE search_fts MATCH ?
    """
    params: list[Any] = [match]
    if domain:
        sql += " AND sd.domain = ?"
        params.append(domain)
    if object_type:
        sql += " AND sd.object_type = ?"
        params.append(object_type)
    if kind:
        sql += " AND sd.kind = ?"
        params.append(kind)
    sql += " ORDER BY rank ASC, sd.id DESC LIMIT ?"
    params.append(limit)

    conn = connect_ro(ledger_db)
    try:
        rows = conn.execute(sql, params).fetchall()
    finally:
        conn.close()

    hits: list[SearchHit] = []
    for row in rows:
        snippet = row["canonical_snippet"] or row["raw_snippet"]
        hits.append(
            SearchHit(
                kind=row["kind"],
                ref_id=row["ref_id"],
                domain=row["domain"],
                object_type=row["object_type"],
                raw_text=row["raw_text"],
                canonical_text=row["canonical_text"],
                snippet=snippet,
                rank=float(row["rank"]) if row["rank"] is not None else None,
            )
        )
    return SearchResult(query=query, hits=hits, total=len(hits))
