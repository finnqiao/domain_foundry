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
        base = (existing or "").rstrip()
        rendered_only = "\n\n".join(m.group(0) for m in rendered_matches)
        if not base:
            return rendered_only + "\n"
        return f"{base}\n\n{rendered_only}\n"

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


class MarkdownAdapter:
    """Renders canonical objects into the generic vault as managed notes."""

    name = "markdown"

    def __init__(
        self, workspace: Workspace, *, registry: PackRegistry | None = None
    ) -> None:
        self.ws = workspace
        self.registry = registry or PackRegistry(workspace)
        self._env = Environment(  # noqa: S701 — output is markdown, not HTML
            autoescape=False,
            undefined=StrictUndefined,
            trim_blocks=True,
            lstrip_blocks=True,
        )

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
            fname = f"{_slug(str(row.get('_title') or row.get('object_uid')), 'note')}.md"
            rel = f"{folder}/{object_type}/{fname}"
            target = safe_join(self.ws.vault_dir, rel)
            write_managed_note(target, note)
            written.append(rel)
        return {"status": "rendered", "notes": len(written), "paths": written}

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
        body = redact_secrets(body).rstrip()
        return content_managed_section(section, body, object_uid=object_uid)

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
