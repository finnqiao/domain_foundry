"""Search surface: FTS5 over ledger entry + canonical text."""

from domain_foundry_core.search.fts import (
    SearchHit,
    SearchResult,
    flatten_searchable_text,
    search_ledger,
    set_canonical_searchable_text,
)

__all__ = [
    "SearchHit",
    "SearchResult",
    "flatten_searchable_text",
    "search_ledger",
    "set_canonical_searchable_text",
]
