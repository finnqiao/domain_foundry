#!/usr/bin/env python3
"""Regenerate the tutorial proof snapshots for every tested harness.

One story — a *card binder* — captured four ways: the CLI, the MCP server
(Claude Desktop / Cursor), the Telegram bot, and the hermes-agent adapter. Each
run is live against a throwaway home and writes a markdown transcript under
``docs/tutorial/snapshots/`` plus a machine-readable ``proof.json``. Deterministic
(heuristic router) so anyone can reproduce identical snapshots offline:

    python scripts/tutorial_snapshots.py
"""

from __future__ import annotations

import asyncio
import io
import json
import os
import subprocess
import sys
import tempfile
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "tutorial" / "snapshots"
DF = str(ROOT / ".venv" / "bin" / "domain-foundry")
GOAL = "i collect pokemon cards"
PICK = "a dex of the cards i own with photos"
BUILD = "build it"
CAP = "pulled a holographic Charizard from a 151 booster, NM"
CORR = "that Charizard was LP not NM"
ENV = {**os.environ, "DOMAIN_FOUNDRY_LLM": "heuristic"}


def _fence(cmd: str, out: str) -> str:
    return f"```console\n$ {cmd}\n{out.rstrip()}\n```\n"


def _is_cards_domain(name: str | None) -> bool:
    token = (name or "").lower()
    return "pokemon" in token or "card" in token


def _scrub(text: str, home: str) -> str:
    resolved = str(Path(home).resolve())
    candidates = {home, resolved, "/private" + home, "/private" + resolved}
    for candidate in sorted(candidates, key=len, reverse=True):
        text = text.replace(candidate, "~/.domain_foundry")
    return text


def _trim(out: str, *, lines: int = 8) -> str:
    parts = out.splitlines()
    if len(parts) <= lines:
        return out
    return "\n".join(parts[:lines]) + "\n…"


def snapshot_cli() -> tuple[str, dict]:
    home = tempfile.mkdtemp(prefix="df_snap_cli_")
    md = ["# CLI — snapshot\n", "_The developer track: one command per step._\n"]
    ok = True

    def run(pretty: str, argv: list[str], *, trim: bool = False, pretty_json: bool = False) -> str:
        nonlocal ok
        p = subprocess.run(argv, capture_output=True, text=True, env=ENV)
        out = _scrub(p.stdout.strip(), home)
        if pretty_json:
            try:
                out = json.dumps(json.loads(out), indent=2)
            except Exception:
                pass
        if trim:
            out = _trim(out)
        md.append(_fence(pretty, out))
        ok = ok and p.returncode == 0
        return p.stdout.strip()

    run("domain-foundry init", [DF, "--home", home, "init"])
    fork_raw = run(
        f'domain-foundry new-domain "{GOAL}"',
        [DF, "--home", home, "new-domain", GOAL],
        trim=True,
    )
    fork = json.loads(fork_raw)
    sid = fork["session_id"]
    run(
        f'domain-foundry wizard reply {sid} "{PICK}"',
        [DF, "--home", home, "wizard", "reply", sid, PICK],
        trim=True,
    )
    build_raw = run(
        f'domain-foundry wizard reply {sid} "{BUILD}"',
        [DF, "--home", home, "wizard", "reply", sid, BUILD],
        trim=True,
    )
    built = json.loads(build_raw)
    domain = built.get("domain") or ((built.get("pack") or {}).get("name")) or "pokemon"
    run(
        f'domain-foundry capture "{CAP}"',
        [DF, "--home", home, "capture", CAP],
        pretty_json=True,
    )
    run(
        f"domain-foundry query --domain {domain}",
        [DF, "--home", home, "query", "--domain", domain],
        pretty_json=True,
    )
    run(
        f'domain-foundry correct "{CORR}"',
        [DF, "--home", home, "correct", CORR],
    )
    ok = ok and _is_cards_domain(domain)
    return "\n".join(md), {"harness": "cli", "ok": ok, "domain": domain}


def snapshot_mcp() -> tuple[str, dict]:
    sys.path.insert(0, str(ROOT / "adapters" / "mcp" / "tests"))
    import test_mcp_e2e as t  # type: ignore

    home = tempfile.mkdtemp(prefix="df_snap_mcp_")
    buf = io.StringIO()
    with redirect_stdout(buf):
        transcript = asyncio.run(t._run(home, echo=True))
    md = ["# MCP (Claude Desktop / Cursor) — snapshot\n",
          "_Driven over real stdio MCP `tools/call`, exactly as an MCP client does._\n",
          "```json\n" + buf.getvalue().strip() + "\n```\n"]
    steps = dict(transcript)
    ok = _is_cards_domain(steps.get("capture", {}).get("domain"))
    return "\n".join(md), {"harness": "mcp", "ok": ok, "steps": [k for k, _ in transcript]}


def snapshot_telegram() -> tuple[str, dict]:
    sys.path.insert(0, str(ROOT / "adapters" / "telegram" / "tests"))
    import test_telegram_bridge as t  # type: ignore

    buf = io.StringIO()
    with redirect_stdout(buf):
        sent, bridge = t._run(echo=True)
    md = ["# Telegram — snapshot\n",
          "_The no-terminal track: text a bot, get structured data back._\n",
          "```text\n" + buf.getvalue().strip() + "\n```\n"]
    ok = any("Logged to" in m["text"] for m in sent)
    return "\n".join(md), {"harness": "telegram", "ok": ok, "replies": len(sent)}


def snapshot_hermes() -> tuple[str, dict]:
    sys.path.insert(0, str(ROOT / "adapters" / "hermes_agent" / "tests"))
    import test_hermes_e2e as t  # type: ignore

    buf = io.StringIO()
    with redirect_stdout(buf):
        r = t._run(echo=True)
    md = ["# hermes-agent — snapshot\n",
          "_The adapter's real tool surface (`build_tools` over the in-process client)._\n",
          "```json\n" + buf.getvalue().strip() + "\n```\n"]
    routed = (r["capture"].get("routed") or [{}])[0]
    return "\n".join(md), {"harness": "hermes", "ok": _is_cards_domain(routed.get("domain"))}


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    results = []
    for name, fn in [("cli", snapshot_cli), ("mcp", snapshot_mcp),
                     ("telegram", snapshot_telegram), ("hermes", snapshot_hermes)]:
        md, meta = fn()
        (OUT / f"{name}.md").write_text(md, encoding="utf-8")
        results.append(meta)
        print(f"  {'✅' if meta.get('ok') else '❌'} {name:9} -> docs/tutorial/snapshots/{name}.md")
    (OUT / "proof.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    all_ok = all(r.get("ok") for r in results)
    print(f"\n{'ALL HARNESSES PROVEN ✅' if all_ok else 'SOME FAILED ❌'} — snapshots in docs/tutorial/snapshots/")
    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
