"""Sanitized eval_case export for community contribution (plan §10.4).

`eval export --sanitize` strips PII/secrets from correction-derived cases and
emits a JSONL plus a human-reviewable redaction report (the "diff review" step),
so users can contribute regression cases upstream without leaking personal data.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from domain_foundry_core.paths import Workspace
from domain_foundry_core.security.redact import redact_secrets
from domain_foundry_core.security.store import connect_ro

# PII patterns applied on top of secret redaction. Conservative: err toward
# over-redaction since the output is meant for public contribution.
_PII_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("EMAIL", re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b")),
    ("URL", re.compile(r"\bhttps?://[^\s]+", re.IGNORECASE)),
    ("PHONE", re.compile(r"(?<!\d)(?:\+?\d[\d\-\s().]{7,}\d)(?!\d)")),
    ("HANDLE", re.compile(r"(?<![\w@])@[A-Za-z0-9_]{2,}\b")),
    ("IPV4", re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")),
    (
        "PATH",
        re.compile(r"(?:/Users/|/home/|[A-Za-z]:\\\\Users\\\\)[^\s\"']+"),
    ),
]


@dataclass
class Redaction:
    case_id: str
    field: str
    kind: str
    before: str
    after: str


@dataclass
class ExportReport:
    total: int = 0
    exported: int = 0
    redactions: list[Redaction] = field(default_factory=list)
    out_path: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "total": self.total,
            "exported": self.exported,
            "redaction_count": len(self.redactions),
            "out_path": self.out_path,
            "redactions": [
                {
                    "case_id": r.case_id,
                    "field": r.field,
                    "kind": r.kind,
                    "before": r.before,
                    "after": r.after,
                }
                for r in self.redactions
            ],
        }


def sanitize_text(text: str) -> tuple[str, list[str]]:
    """Return (sanitized, kinds_hit). Secrets first, then PII patterns."""
    kinds: list[str] = []
    out = redact_secrets(text)
    if out != text:
        kinds.append("SECRET")
    for kind, pattern in _PII_PATTERNS:
        if pattern.search(out):
            out = pattern.sub(f"[{kind}]", out)
            kinds.append(kind)
    return out, kinds


def _sanitize_value(value: Any) -> tuple[Any, list[str]]:
    if isinstance(value, str):
        return sanitize_text(value)
    if isinstance(value, dict):
        kinds: list[str] = []
        out: dict[str, Any] = {}
        for k, v in value.items():
            nv, khit = _sanitize_value(v)
            out[k] = nv
            kinds.extend(khit)
        return out, kinds
    if isinstance(value, list):
        kinds = []
        out_list: list[Any] = []
        for item in value:
            nv, khit = _sanitize_value(item)
            out_list.append(nv)
            kinds.extend(khit)
        return out_list, kinds
    return value, []


def export_cases(
    workspace: Workspace,
    *,
    out_path: Path,
    sanitize: bool = True,
    source: str | None = "correction",
    limit: int = 5000,
) -> ExportReport:
    report = ExportReport()
    conn = connect_ro(workspace.ledger_db)
    try:
        if source:
            rows = conn.execute(
                """
                SELECT id, source, raw_text, context_json, expected_json, created_at
                FROM eval_case WHERE source = ? ORDER BY created_at ASC LIMIT ?
                """,
                (source, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT id, source, raw_text, context_json, expected_json, created_at
                FROM eval_case ORDER BY created_at ASC LIMIT ?
                """,
                (limit,),
            ).fetchall()
    finally:
        conn.close()

    out_path.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    for row in rows:
        report.total += 1
        case_id = str(row["id"])
        raw_text = row["raw_text"]
        expected = json.loads(row["expected_json"]) if row["expected_json"] else {}
        context = json.loads(row["context_json"]) if row["context_json"] else {}

        if sanitize:
            new_raw, raw_kinds = sanitize_text(raw_text or "")
            for kind in raw_kinds:
                report.redactions.append(
                    Redaction(case_id, "raw_text", kind, raw_text or "", new_raw)
                )
            raw_text = new_raw
            expected, exp_kinds = _sanitize_value(expected)
            for kind in exp_kinds:
                report.redactions.append(
                    Redaction(case_id, "expected", kind, "", "[REDACTED]")
                )
            # Drop provenance/context that may carry local identifiers.
            context = {
                "packs": context.get("packs", []),
                "date": context.get("date"),
                "open_hints": context.get("open_hints", []),
            }

        record = {
            "id": case_id,
            "source": row["source"],
            "raw_text": raw_text,
            "context": context,
            "expected": expected,
        }
        lines.append(json.dumps(record, ensure_ascii=False, sort_keys=True))
        report.exported += 1

    out_path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
    report.out_path = str(out_path)
    return report
