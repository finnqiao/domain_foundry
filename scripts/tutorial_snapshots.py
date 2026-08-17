#!/usr/bin/env python3
"""Regenerate the tutorial proof snapshots for every tested harness.

One story — a *bouldering* log — captured four ways: the CLI, the MCP server
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
GOAL = "track my bouldering climbing sessions"
CAP = "good bouldering session at the gym, felt strong"
CORR = "actually the rating was moderate not hard"
ENV = {**os.environ, "DOMAIN_FOUNDRY_LLM": "heuristic"}


def _fence(cmd: str, out: str) -> str:
    return f"```console\n$ {cmd}\n{out.rstrip()}\n```\n"


def snapshot_cli() -> tuple[str, dict]:
    home = tempfile.mkdtemp(prefix="df_snap_cli_")
    steps: list[tuple[str, list[str]]] = [
        ("domain-foundry init", [DF, "--home", home, "init"]),
        (f'domain-foundry new-domain "{GOAL}" --reply skip',
         [DF, "--home", home, "new-domain", GOAL, "--reply", "skip"]),
        (f'domain-foundry capture "{CAP}"', [DF, "--home", home, "capture", CAP]),
        ("domain-foundry query --domain bouldering",
         [DF, "--home", home, "query", "--domain", "bouldering"]),
        (f'domain-foundry correct "{CORR}"', [DF, "--home", home, "correct", CORR]),
    ]
    md = ["# CLI — snapshot\n", "_The developer track: one command per step._\n"]
    ok = True
    for pretty, argv in steps:
        p = subprocess.run(argv, capture_output=True, text=True, env=ENV)
        out = p.stdout.strip().replace(home, "~/.domain_foundry")
        if pretty.startswith("domain-foundry new-domain"):
            out = "\n".join(out.splitlines()[:6]) + "\n… (pack generated + activated)"
        if pretty.startswith("domain-foundry capture") or pretty.startswith("domain-foundry query"):
            try:
                out = json.dumps(json.loads(out), indent=2)
            except Exception:
                pass
        md.append(_fence(pretty, out))
        ok = ok and p.returncode == 0
    return "\n".join(md), {"harness": "cli", "ok": ok}


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
    ok = steps.get("capture", {}).get("domain") == "bouldering"
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
    return "\n".join(md), {"harness": "hermes", "ok": routed.get("domain") == "bouldering"}


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
