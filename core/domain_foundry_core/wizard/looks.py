"""HTML looks for wizard ideas: job templates always, sota HTML when keyed.

Looks are generated from idea + jobs + optional samples, never from a hobby
name in core. Templates are keyed by job id.
"""

from __future__ import annotations

import html
import json
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from domain_foundry_core.wizard.fork import JOB_PITCH, hinted_jobs

LOOK_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"html": {"type": "string"}},
    "required": ["html"],
}

_JOB_PRIORITY = (
    "improvement",
    "media_dex",
    "lab",
    "atlas",
    "catalog",
    "event_log",
    "practice",
    "graph",
    "plan",
)

_SAFE_ID = re.compile(r"[^a-zA-Z0-9._-]+")


def hero_job(jobs: list[str] | None, *, hints: list[str] | None = None) -> str:
    job_set = [j for j in (jobs or []) if j]
    hint_set = [j for j in (hints or []) if j in job_set]
    if hint_set:
        for job in _JOB_PRIORITY:
            if job in hint_set:
                return job
        return hint_set[0]
    for job in _JOB_PRIORITY:
        if job in job_set:
            return job
    return "event_log"


def generate_look(
    idea: dict[str, Any],
    *,
    samples: str = "",
    critique: str = "",
    previous_html: str = "",
    round: int = 1,
    job_hints: list[str] | None = None,
    llm: Any | None = None,
) -> dict[str, Any]:
    """Return ``{idea_id, title, html, round, jobs, model, fallback_reason}``.

    ``fallback_reason`` is None on the ordinary template path (no designer
    configured) and carries the exception or ``empty_llm_html`` when a designer
    *was* configured and did not deliver. Swallowing that made a broken designer
    endpoint look exactly like having no key at all.
    """
    jobs = list(idea.get("jobs") or ["event_log"])
    hints = list(job_hints or [])
    if critique:
        hints = list(dict.fromkeys(hints + hinted_jobs(critique)))
    hero = hero_job(jobs, hints=hints)
    model = "template"
    html_page = ""
    fallback_reason: str | None = None
    if llm is not None:
        try:
            html_page = _sota_html(
                idea,
                samples=samples,
                critique=critique,
                previous_html=previous_html,
                hero=hero,
                llm=llm,
            )
            model = getattr(llm, "name", None) or "sota"
        except Exception as exc:  # noqa: BLE001 - degrade to template, but say why
            html_page = ""
            fallback_reason = f"{type(exc).__name__}: {exc}"
    if not html_page or "<" not in html_page:
        if llm is not None and fallback_reason is None:
            fallback_reason = "empty_llm_html"
        html_page = template_html(
            idea,
            hero=hero,
            samples=samples,
            critique=critique,
            round=round,
        )
        model = "template"
    return {
        "idea_id": idea.get("id") or "",
        "title": idea.get("title") or "Look",
        "html": html_page,
        "round": int(round),
        "jobs": jobs,
        "hero_job": hero,
        "model": model,
        "fallback_reason": fallback_reason,
    }


def persist_look(root: Path, look: dict[str, Any]) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    idea_id = _SAFE_ID.sub("_", str(look.get("idea_id") or "look"))
    path = root / f"{idea_id}.html"
    path.write_text(str(look.get("html") or ""), encoding="utf-8")
    meta = {k: v for k, v in look.items() if k != "html"}
    (root / "looks.json").write_text(
        json.dumps({"latest": idea_id, **meta}, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return path


def template_html(
    idea: dict[str, Any],
    *,
    hero: str,
    samples: str = "",
    critique: str = "",
    round: int = 1,
) -> str:
    title = html.escape(str(idea.get("title") or "Look"))
    pitch = html.escape(str(idea.get("pitch") or ""))
    analog = ""
    worlds = idea.get("world_analogs") or []
    if worlds:
        analog = html.escape(str(worlds[0].get("name") or ""))
    example = str(idea.get("example") or "")
    rows = _sample_rows(example, samples, idea)
    tone = _tone_from_critique(critique)
    body = _hero_body(hero, title, rows, tone)
    analog_line = f'<p class="analog">Oriented like {analog}</p>' if analog else ""
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
  :root {{ color-scheme: {tone["scheme"]}; --ink:{tone["ink"]}; --muted:{tone["muted"]};
    --paper:{tone["paper"]}; --line:{tone["line"]}; --accent:{tone["accent"]}; }}
  * {{ box-sizing: border-box; }}
  body {{ margin: 0; font: 15px/1.45 ui-sans-serif, system-ui, sans-serif;
    color: var(--ink); background: var(--paper); padding: 18px; }}
  h1 {{ margin: 0 0 6px; font-size: 1.25rem; letter-spacing: -.03em; }}
  .pitch, .analog {{ color: var(--muted); margin: 0 0 12px; font-size: .9rem; }}
  .df-look-{hero} {{ border: 1px solid var(--line); border-radius: 14px; padding: 14px; }}
  table {{ width: 100%; border-collapse: collapse; font-size: .85rem; }}
  th, td {{ text-align: left; padding: 6px 8px; border-bottom: 1px solid var(--line); }}
  .chart {{ height: {tone["chart_h"]}; position: relative; background:
    linear-gradient(to top, rgba(8,127,114,.08), transparent); border-radius: 10px; }}
  .dot {{ position: absolute; width: 9px; height: 9px; border-radius: 50%; background: var(--accent); }}
  .gallery {{ display: grid; grid-template-columns: repeat({tone["gallery_cols"]}, 1fr); gap: {tone["gallery_gap"]}; }}
  .tile {{ aspect-ratio: 1; border-radius: 10px; background: #d9f1e9; display: grid; place-items: end start; padding: 8px; font-size: .75rem; }}
  .map {{ height: 140px; border-radius: 10px; background:
    radial-gradient(circle at 30% 40%, #8dcbbc, #d9f1e9 42%, #eef3ef); position: relative; }}
  .pin {{ position: absolute; width: 10px; height: 10px; background: #b65b21; border-radius: 50%; }}
  .mix {{ display: grid; gap: 8px; }}
  .mix article {{ border: 1px solid var(--line); border-radius: 10px; padding: 10px; }}
  .timeline {{ border-left: 2px solid var(--accent); margin-left: 8px; padding-left: 14px; }}
  .timeline div {{ margin: 0 0 10px; }}
  .axis {{ display: flex; justify-content: space-between; color: var(--muted); font-size: .75rem; margin-top: 6px; }}
</style>
</head>
<body>
  <header>
    <h1>{title}</h1>
    <p class="pitch">{pitch}</p>
    {analog_line}
  </header>
  <section class="df-look-{hero}" data-hero="{hero}" data-round="{int(round)}">
    {body}
  </section>
</body>
</html>
"""


def _tone_from_critique(critique: str) -> dict[str, str | int]:
    low = (critique or "").lower()
    dark = any(w in low for w in ("dark", "darker", "dim"))
    dense = any(w in low for w in ("dense", "denser", "tighter", "more chart"))
    if dark:
        return {
            "scheme": "dark",
            "ink": "#e7edea",
            "muted": "#93a69e",
            "paper": "#0e1512",
            "line": "#24322d",
            "accent": "#3fbe99",
            "chart_h": "190px" if dense else "150px",
            "gallery_cols": "4" if dense else "3",
            "gallery_gap": "4px" if dense else "8px",
            "tile_n": 8 if dense else 6,
        }
    return {
        "scheme": "light",
        "ink": "#18211f",
        "muted": "#64706b",
        "paper": "#f7f7f1",
        "line": "#d9dfd7",
        "accent": "#087f72",
        "chart_h": "190px" if dense else "150px",
        "gallery_cols": "4" if dense else "3",
        "gallery_gap": "4px" if dense else "8px",
        "tile_n": 8 if dense else 6,
    }


def _sample_rows(example: str, blob: str, idea: dict[str, Any]) -> list[str]:
    rows: list[str] = []
    if example.strip():
        rows.append(example.strip().split("\n")[0][:120])
    for line in (blob or "").splitlines():
        s = line.strip()
        if s and s not in rows:
            rows.append(s[:120])
        if len(rows) >= 5:
            break
    identity = str(idea.get("identity_hint") or "item").replace("_", " ")
    fillers = [
        f"{identity} alpha — keeper",
        f"{identity} beta — worth repeating",
        f"{identity} gamma — notes for next time",
    ]
    for filler in fillers:
        if len(rows) >= 4:
            break
        rows.append(filler)
    return rows[:5]


def _hero_body(hero: str, title: str, rows: list[str], tone: Mapping[str, str | int]) -> str:
    items = "".join(f"<li>{html.escape(r)}</li>" for r in rows)
    if hero == "improvement":
        dots = [
            (12, 70),
            (24, 58),
            (38, 62),
            (48, 40),
            (61, 34),
            (74, 22),
            (86, 30),
        ]
        marks = "".join(f'<i class="dot" style="left:{x}%; top:{y}%"></i>' for x, y in dots)
        return (
            f"<p>Scatter of inputs → outcomes</p>"
            f'<div class="chart" aria-label="scatter chart">{marks}</div>'
            f'<div class="axis"><span>input</span><span>outcome</span></div>'
            f"<ul>{items}</ul>"
        )
    if hero == "media_dex":
        n = int(tone.get("tile_n") or 6)
        display = list(rows)
        while len(display) < n:
            display.append(f"slot {len(display) + 1}")
        tiles = "".join(f'<div class="tile">{html.escape(r[:40])}</div>' for r in display[:n])
        dense = "1" if n >= 8 else "0"
        return f'<p>Photo gallery</p><div class="gallery" data-dense="{dense}">{tiles}</div>'
    if hero == "atlas":
        pins = "".join(
            f'<i class="pin" style="left:{20 + i * 12}%; top:{30 + (i % 3) * 18}%"></i>'
            for i in range(min(5, len(rows)))
        )
        return f'<p>Map of where it happened</p><div class="map">{pins}</div><ul>{items}</ul>'
    if hero == "lab":
        cards = "".join(
            f"<article><strong>Mix {i + 1}</strong><p>{html.escape(r)}</p></article>"
            for i, r in enumerate(rows)
        )
        return f'<p>Mix board of what worked</p><div class="mix">{cards}</div>'
    if hero == "catalog":
        return (
            "<p>Field guide / catalog</p>"
            "<table><thead><tr><th>Entry</th><th>Note</th></tr></thead>"
            "<tbody>"
            + "".join(
                f"<tr><td>{html.escape(title)}</td><td>{html.escape(r)}</td></tr>" for r in rows
            )
            + "</tbody></table>"
        )
    # event_log and the rest
    stamps = "".join(f"<div><strong>Logged</strong><p>{html.escape(r)}</p></div>" for r in rows)
    return f'<p>Timeline</p><div class="timeline">{stamps}</div>'


def _sota_html(
    idea: dict[str, Any],
    *,
    samples: str,
    critique: str,
    previous_html: str,
    hero: str,
    llm: Any,
) -> str:
    analog = ""
    worlds = idea.get("world_analogs") or []
    if worlds:
        analog = f"{worlds[0].get('name')}: {worlds[0].get('one_liner')}"
    sample_lines = "\n".join((samples or "").splitlines()[:8])
    payload = {
        "IDEA": {
            "title": idea.get("title"),
            "pitch": idea.get("pitch"),
            "jobs": idea.get("jobs"),
            "example": idea.get("example"),
            "hero_job": hero,
            "hero_means": JOB_PITCH.get(hero, hero),
        },
        "ORIENTATION": analog,
        "SAMPLE_LINES": sample_lines,
        "CRITIQUE": critique,
        "PREVIOUS_HTML_PRESENT": bool(previous_html),
        "REQUIREMENTS": [
            "Return one self-contained HTML page in the html field.",
            "Inline CSS only. No external scripts, fonts, or images.",
            f"The page must clearly be a {hero} view ({JOB_PITCH.get(hero, hero)}).",
            "Use the samples if present; otherwise invent 4 plausible rows from the example.",
            "Do not mention Domain Foundry internals or taxonomy paths.",
        ],
    }
    result = llm.complete_json(
        system=(
            "You design a single-page HTML mockup of a personal app. "
            'Output ONLY JSON {"html": "<!doctype html>..."}. '
            "Have design sense: type, spacing, one accent, no stock dashboard chrome."
        ),
        user=json.dumps(payload, ensure_ascii=False)[:12_000],
        schema=LOOK_SCHEMA,
        tier="sota",
    )
    data = result.data if hasattr(result, "data") else result
    html_page = str((data or {}).get("html") or "")
    if "<html" not in html_page.lower() and "<div" in html_page.lower():
        html_page = (
            "<!doctype html><html><head><meta charset='utf-8'>"
            "<style>body{font-family:system-ui;padding:16px}</style></head><body>"
            f"{html_page}</body></html>"
        )
    if "<" not in html_page:
        raise ValueError("sota look returned no HTML")
    return html_page
