"""Managed-region markdown adapter.

The *only* markdown write path in core (invariant 8, §3.4). Renders one note per
canonical object into a generic vault under the workspace (Obsidian just opens
it). Content lives inside `%%managed:start ... %%` / `%%managed:end ... %%`
markers; any user free-text *outside* the markers survives re-render verbatim.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

from jinja2 import Environment, StrictUndefined

from domain_foundry_core.clock import now_iso
from domain_foundry_core.packs.models import DomainPack
from domain_foundry_core.packs.registry import PackRegistry
from domain_foundry_core.packs.schema_compiler import table_name
from domain_foundry_core.paths import Workspace
from domain_foundry_core.security.paths import safe_join
from domain_foundry_core.security.redact import redact_secrets
from domain_foundry_core.security.store import connect_ro

MANAGED_SECTION_RE = re.compile(
    r"%%managed:start (?P<section>[^\n%]+)%%\n(?P<body>.*?)\n%%managed:end (?P=section)%%",
    re.S,
)
UID_RE = re.compile(r"%%uid:(?P<uid>[^%\n]+)%%")

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def content_managed_section(
    section: str, body: str, *, object_uid: str | None = None
) -> str:
    lines = [f"%%managed:start {section}%%"]
    if object_uid:
        lines.append(f"%%uid:{object_uid}%%")
    lines.extend(str(line).rstrip() for line in body.splitlines())
    lines.append(f"%%managed:end {section}%%")
    return "\n".join(lines)


def parse_managed_sections(text: str) -> dict[str, str]:
    return {
        m.group("section").strip(): m.group(0)
        for m in MANAGED_SECTION_RE.finditer(text or "")
    }


def unmanaged_text(text: str) -> str:
    """Return bytes outside managed markers (free zones). Used for invariants."""
    return MANAGED_SECTION_RE.sub("", text or "")


def unmanaged_preserved(existing: str, merged: str) -> bool:
    """True when free-zone bytes from ``existing`` survive in ``merged``.

    Exact equality is required when managed regions already existed. When managed
    content is appended to a free-only file, only whitespace separators may be
    added after the original free text.
    """
    before = unmanaged_text(existing)
    after = unmanaged_text(merged)
    if before == after:
        return True
    if parse_managed_sections(existing):
        return False
    # First managed inject: original free bytes are an exact prefix; suffix is
    # whitespace-only (blank-line separator before the new managed block).
    if after.startswith(before):
        return after[len(before) :].strip("\n") == ""
    # Merge may normalize a missing trailing newline on the free zone.
    trimmed = before.rstrip("\n")
    if after.startswith(trimmed):
        return after[len(trimmed) :].strip("\n") == ""
    return False


def preview_managed_write(existing: str | None, rendered: str) -> dict[str, Any]:
    """Compute merge outcome without writing. Reports unmanaged-byte identity."""
    before = existing if existing is not None else ""
    if not before:
        after = rendered or ""
        if after and not after.endswith("\n"):
            after += "\n"
    else:
        after = merge_managed_markdown(before, rendered)
    u_before = unmanaged_text(before)
    u_after = unmanaged_text(after)
    preserved = True if existing is None else unmanaged_preserved(before, after)
    return {
        "existing": before,
        "merged": after,
        "unmanaged_before": u_before,
        "unmanaged_after": u_after,
        "unmanaged_unchanged": preserved,
        "would_create": existing is None,
        "content_changed": before != after,
    }


def merge_managed_markdown(existing: str, rendered: str) -> str:
    """Replace managed regions in `existing` with `rendered`, preserving free zones.

    Free zones = everything *outside* the markers. They are never touched. A
    managed section present in `rendered` but not in `existing` is appended after
    the last existing managed block (or at end of file).
    """
    existing_blocks = parse_managed_sections(existing)
    rendered_matches = list(MANAGED_SECTION_RE.finditer(rendered or ""))
    if not rendered_matches:
        return existing
    if not existing_blocks:
        # No managed regions yet: keep the user's file and append managed content.
        # Do not rstrip free-zone bytes — only add a separator if needed.
        base = existing or ""
        rendered_only = "\n\n".join(m.group(0) for m in rendered_matches)
        if not base.strip():
            return rendered_only + ("\n" if not rendered_only.endswith("\n") else "")
        if base.endswith("\n\n"):
            sep = ""
        elif base.endswith("\n"):
            sep = "\n"
        else:
            sep = "\n\n"
        out = base + sep + rendered_only
        return out if out.endswith("\n") else out + "\n"

    rendered_blocks = {
        m.group("section").strip(): m.group(0) for m in rendered_matches
    }

    def _replace(match: re.Match[str]) -> str:
        section = match.group("section").strip()
        # Keep the existing block verbatim if the render dropped this section.
        return rendered_blocks.get(section, match.group(0))

    merged = MANAGED_SECTION_RE.sub(_replace, existing)

    # Append sections that are new (present in render, absent from existing).
    new_sections = [
        m.group("section").strip()
        for m in rendered_matches
        if m.group("section").strip() not in existing_blocks
    ]
    if new_sections:
        last_end = None
        for m in MANAGED_SECTION_RE.finditer(merged):
            last_end = m.end()
        additions = "\n\n".join(rendered_blocks[s] for s in new_sections)
        if last_end is None:
            merged = merged.rstrip() + "\n\n" + additions + "\n"
        else:
            merged = merged[:last_end] + "\n\n" + additions + merged[last_end:]
    return merged


def atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.parent / f".{path.name}.{os.getpid()}.tmp"
    tmp.write_text(content, encoding="utf-8")
    os.replace(tmp, path)


def write_managed_note(path: Path, rendered: str) -> None:
    """Write a note, merging managed regions and preserving user free zones."""
    final = rendered
    if path.exists():
        existing = path.read_text(encoding="utf-8", errors="replace")
        final = merge_managed_markdown(existing, rendered)
    atomic_write_text(path, final)


def _slug(value: str, fallback: str) -> str:
    slug = _SLUG_RE.sub("-", str(value or "").strip().lower()).strip("-")
    return slug or fallback


def _note_filename(row: dict[str, Any]) -> str:
    """Stable unique note name: title slug + short object_uid suffix."""
    uid = str(row.get("object_uid") or "")
    # Prefer the trailing ULID segment when present (pack:type:ULID).
    short = uid.rsplit(":", 1)[-1] if uid else ""
    short = (short or "note")[-8:].lower()
    title_slug = _slug(str(row.get("_title") or short), short)
    return f"{title_slug}_{short}.md"


class MarkdownAdapter:
    """Renders canonical objects into the generic vault as managed notes."""

    name = "markdown"

    def __init__(
        self,
        workspace: Workspace,
        *,
        registry: PackRegistry | None = None,
        vault_root: Path | None = None,
    ) -> None:
        self.ws = workspace
        self.registry = registry or PackRegistry(workspace)
        self.vault_root = Path(vault_root) if vault_root else workspace.vault_dir
        self._env = Environment(  # noqa: S701 — output is markdown, not HTML
            autoescape=False,
            undefined=StrictUndefined,
            trim_blocks=True,
            lstrip_blocks=True,
        )
        self._entry_aliases: dict[str, list[str]] | None = None

    def render(self, object_key: str, outbox_row: dict[str, Any]) -> dict[str, Any]:
        domain, _, object_type = object_key.partition(":")
        if not domain or not object_type:
            return {"status": "skipped", "reason": f"bad object_key {object_key!r}"}
        pack = self.registry.get(domain)
        if pack is None or object_type not in pack.objects:
            return {"status": "skipped", "reason": f"unknown object {object_key!r}"}

        folder = str(pack.projections.markdown.get("folder") or pack.name)
        template = self._load_template(pack, object_type)
        rows = self._load_rows(pack, object_type)

        written: list[str] = []
        for row in rows:
            note = self._render_note(pack, object_type, row, template)
            fname = _note_filename(row)
            rel = f"{folder}/{object_type}/{fname}"
            target = safe_join(self.vault_root, rel)
            write_managed_note(target, note)
            written.append(rel)
        return {"status": "rendered", "notes": len(written), "paths": written}

    def plan_notes(
        self, object_key: str
    ) -> list[dict[str, Any]]:
        """Return planned note paths + rendered bodies (no writes)."""
        domain, _, object_type = object_key.partition(":")
        if not domain or not object_type:
            return []
        pack = self.registry.get(domain)
        if pack is None or object_type not in pack.objects:
            return []
        folder = str(pack.projections.markdown.get("folder") or pack.name)
        template = self._load_template(pack, object_type)
        planned: list[dict[str, Any]] = []
        for row in self._load_rows(pack, object_type):
            note = self._render_note(pack, object_type, row, template)
            fname = _note_filename(row)
            rel = f"{folder}/{object_type}/{fname}"
            planned.append(
                {
                    "rel_path": rel,
                    "object_uid": str(row.get("object_uid") or ""),
                    "entry_id": str(row.get("entry_id") or ""),
                    "rendered": note,
                }
            )
        return planned

    def _load_rows(self, pack: DomainPack, object_type: str) -> list[dict[str, Any]]:
        tname = table_name(pack.name, object_type)
        if not self.ws.domains_db.exists():
            return []
        conn = connect_ro(self.ws.domains_db)
        try:
            rows = conn.execute(
                f"SELECT * FROM {tname} WHERE tombstoned = 0 ORDER BY created_at ASC"
            ).fetchall()
        except Exception:
            return []
        finally:
            conn.close()
        obj = pack.objects[object_type]
        out: list[dict[str, Any]] = []
        for r in rows:
            d = {k: r[k] for k in r.keys()}
            title_field = obj.title_field
            d["_title"] = d.get(title_field) if title_field else d.get("object_uid")
            out.append(d)
        return out

    def _load_template(self, pack: DomainPack, object_type: str):
        spec = pack.projections.markdown.get("note_template")
        if isinstance(spec, dict):
            name = spec.get(object_type)
        else:
            name = spec  # a bare string applies to every object type
        if not name:
            return None
        try:
            path = safe_join(pack.root, str(name))
        except Exception:
            return None
        if not path.is_file():
            return None
        return self._env.from_string(path.read_text(encoding="utf-8"))

    def _render_note(
        self, pack: DomainPack, object_type: str, row: dict[str, Any], template
    ) -> str:
        object_uid = str(row.get("object_uid") or "")
        section = f"{object_type}:{object_uid}"
        if template is not None:
            body = template.render(
                fields=row,
                object_type=object_type,
                object_uid=object_uid,
                pack=pack.name,
            )
        else:
            body = self._default_body(pack, object_type, row)
        body = self._append_entry_backlinks(body, row)
        body = redact_secrets(body).rstrip()
        # Vocab/grammar: YAML frontmatter inside managed body so next_review/reps
        # re-project without touching unmanaged free zones.
        if object_type in {"jp_vocab", "jp_grammar"}:
            body = self._with_srs_frontmatter(body, row)
        return content_managed_section(section, body, object_uid=object_uid)

    def _with_srs_frontmatter(self, body: str, row: dict[str, Any]) -> str:
        """Prepend YAML frontmatter with next_review + reps for vault SRS visibility."""
        # Strip a prior managed frontmatter block if the body already has one.
        stripped = body
        if stripped.lstrip().startswith("---"):
            parts = stripped.split("---", 2)
            if len(parts) >= 3:
                stripped = parts[2].lstrip("\n")
        reps = row.get("reps")
        next_review = row.get("next_review")
        fm_lines = [
            "---",
            f"next_review: {next_review if next_review not in (None, '') else ''}",
            f"reps: {0 if reps is None else int(reps)}",
            "---",
            "",
        ]
        return "\n".join(fm_lines) + stripped.lstrip("\n")

    def _default_body(
        self, pack: DomainPack, object_type: str, row: dict[str, Any]
    ) -> str:
        obj = pack.objects[object_type]
        title = str(row.get("_title") or object_type)
        lines = [f"# {title}", ""]
        for fname, fspec in obj.fields.items():
            value = row.get(fname)
            if value is None or value == "":
                continue
            label = fname.replace("_", " ").title()
            suffix = f" {fspec.unit}" if fspec.unit else ""
            lines.append(f"- **{label}:** {value}{suffix}")
        lines.append("")
        lines.append(f"_updated {row.get('updated_at') or now_iso()}_")
        return "\n".join(lines)

    def render_due_dashboard(
        self,
        domain: str = "japanese",
        *,
        as_of: str | None = None,
        title: str = "Japanese — Due today",
    ) -> dict[str, Any] | None:
        """Managed dashboard note listing cards due on ``as_of`` (UTC date)."""
        from domain_foundry_core.clock import today_utc

        pack = self.registry.get(domain)
        if pack is None or "jp_vocab" not in pack.objects:
            return None
        day = as_of or today_utc()
        folder = str(pack.projections.markdown.get("folder") or pack.name)
        rel = f"{folder}/{title}.md"
        rows = self._load_due_rows(pack, day)
        lines = [
            f"# {title}",
            "",
            f"_as of {day} — {len(rows)} due_",
            "",
        ]
        if not rows:
            lines.append("_Nothing due. Nice._")
            lines.append("")
        else:
            for row in rows:
                word = str(row.get("word") or row.get("_title") or row.get("object_uid"))
                meaning = row.get("meaning") or ""
                next_review = row.get("next_review") or day
                reps = int(row.get("reps") or 0)
                uid = str(row.get("object_uid") or "")
                lines.append(
                    f"- **{word}** — {meaning} _(next_review={next_review}, reps={reps})_"
                )
                if uid:
                    lines.append(f"  - `%%uid:{uid}%%`")
            lines.append("")
        body = "\n".join(lines).rstrip()
        section = f"due_dashboard:{domain}"
        rendered = content_managed_section(section, body, object_uid=f"{domain}:due_today")
        return {
            "rel_path": rel,
            "object_uid": f"{domain}:due_today",
            "entry_id": "",
            "rendered": rendered,
            "due_count": len(rows),
            "as_of": day,
        }

    def _load_due_rows(self, pack: DomainPack, as_of: str) -> list[dict[str, Any]]:
        tname = table_name(pack.name, "jp_vocab")
        if not self.ws.domains_db.exists():
            return []
        conn = connect_ro(self.ws.domains_db)
        try:
            exists = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                (tname,),
            ).fetchone()
            if not exists:
                return []
            rows = conn.execute(
                f"""
                SELECT * FROM {tname}
                WHERE tombstoned = 0
                  AND next_review IS NOT NULL
                  AND next_review <= ?
                ORDER BY next_review ASC, id ASC
                """,
                (as_of,),
            ).fetchall()
        except Exception:
            return []
        finally:
            conn.close()
        obj = pack.objects["jp_vocab"]
        out: list[dict[str, Any]] = []
        for r in rows:
            d = {k: r[k] for k in r.keys()}
            title_field = obj.title_field
            d["_title"] = d.get(title_field) if title_field else d.get("object_uid")
            out.append(d)
        return out

    def _append_entry_backlinks(self, body: str, row: dict[str, Any]) -> str:
        """Emit [[entry:<id>]] for DF entry_id plus Hermes lb_* aliases when known."""
        entry_id = str(row.get("entry_id") or "").strip()
        if not entry_id:
            return body
        ids = [entry_id]
        for alias in self._aliases_for_entry(entry_id):
            if alias not in ids:
                ids.append(alias)
        links = "\n".join(f"[[entry:{eid}]]" for eid in ids)
        if any(f"[[entry:{eid}]]" in body for eid in ids):
            return body
        return f"{body.rstrip()}\n\n{links}\n"

    def _aliases_for_entry(self, entry_id: str) -> list[str]:
        table = self._ensure_entry_aliases()
        return list(table.get(entry_id, []))

    def _ensure_entry_aliases(self) -> dict[str, list[str]]:
        if self._entry_aliases is not None:
            return self._entry_aliases
        aliases: dict[str, list[str]] = {}
        if not self.ws.ledger_db.exists():
            self._entry_aliases = aliases
            return aliases
        conn = connect_ro(self.ws.ledger_db)
        try:
            rows = conn.execute(
                """
                SELECT e.id AS entry_id, c.source_ref
                FROM capture_event c
                JOIN source_link sl
                  ON sl.source_type = 'capture_event'
                 AND sl.source_id = c.id
                 AND sl.target_type = 'entry'
                JOIN entry e ON e.id = sl.target_id
                WHERE c.source_ref LIKE 'hermes:logbook:entry:%'
                """
            ).fetchall()
            prefix = "hermes:logbook:entry:"
            for r in rows:
                ref = str(r["source_ref"] or "")
                if not ref.startswith(prefix):
                    continue
                lb = ref[len(prefix) :].strip()
                if not lb:
                    continue
                eid = str(r["entry_id"])
                bucket = aliases.setdefault(eid, [])
                if lb not in bucket:
                    bucket.append(lb)
        except Exception:
            aliases = {}
        finally:
            conn.close()
        self._entry_aliases = aliases
        return aliases
