"""Supervisor skeleton — spawn/monitor Domain Experts with backoff."""

from __future__ import annotations

import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from domain_foundry_core.clock import now
from domain_foundry_core.mesh.inbox import DomainInbox
from domain_foundry_core.mesh.journal import InboxJournal
from domain_foundry_core.mesh.outbound import OutboundQueue
from domain_foundry_core.paths import Workspace


@dataclass
class ChildState:
    domain: str
    pid: int | None = None
    restarts: int = 0
    last_exit: int | None = None
    last_started_at: float | None = None
    last_error: str | None = None
    running: bool = False


@dataclass
class SupervisorStatus:
    home: str
    journal: dict[str, int]
    inbox_by_domain: dict[str, dict[str, int]]
    outbound: dict[str, int] = field(default_factory=dict)
    children: list[dict[str, Any]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


class Supervisor:
    """Monitors Expert child processes with exponential backoff restarts.

    Foundation skeleton: spawns `python -m domain_foundry_core.mesh.expert_main`
    per domain. launchd install is stubbed (see mesh install CLI).
    """

    def __init__(
        self,
        workspace: Workspace | None = None,
        *,
        domains: list[str] | None = None,
        min_backoff_s: float = 0.5,
        max_backoff_s: float = 30.0,
    ) -> None:
        self.ws = workspace or Workspace()
        self.domains = list(domains or ["japanese", "food"])
        self.min_backoff_s = min_backoff_s
        self.max_backoff_s = max_backoff_s
        self._children: dict[str, ChildState] = {
            d: ChildState(domain=d) for d in self.domains
        }
        self._procs: dict[str, subprocess.Popen[Any]] = {}
        self._stop = threading.Event()
        self._monitor_thread: threading.Thread | None = None
        self.journal = InboxJournal(self.ws)
        self.inbox = DomainInbox(self.ws)
        self.outbound = OutboundQueue(self.ws)

    def status(self) -> SupervisorStatus:
        children = []
        for domain, state in self._children.items():
            proc = self._procs.get(domain)
            running = proc is not None and proc.poll() is None
            state.running = running
            state.pid = proc.pid if proc and running else None
            children.append(
                {
                    "domain": domain,
                    "running": running,
                    "pid": state.pid,
                    "restarts": state.restarts,
                    "last_exit": state.last_exit,
                    "last_error": state.last_error,
                    "inbox": self.inbox.depth(domain),
                }
            )
        return SupervisorStatus(
            home=str(self.ws.home),
            journal=self.journal.counts(),
            inbox_by_domain=self.inbox.depths_by_domain(),
            outbound=self.outbound.depth(),
            children=children,
            notes=[
                "launchd install stubbed — use `domain-foundry mesh install` TODO",
                "gateway fast path: private logbook plugin (HERMES_MESH_FAST_PATH)",
                "outbound_queue: ledger-backed; private poller adopts DF claim/ack/fail",
            ],
        )

    def start_all(self) -> None:
        for domain in self.domains:
            self._spawn(domain)
        if self._monitor_thread is None or not self._monitor_thread.is_alive():
            self._stop.clear()
            self._monitor_thread = threading.Thread(
                target=self._monitor_loop, name="mesh-supervisor", daemon=True
            )
            self._monitor_thread.start()

    def stop_all(self) -> None:
        self._stop.set()
        for domain, proc in list(self._procs.items()):
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    proc.kill()
            self._children[domain].running = False
        self._procs.clear()

    def _spawn(self, domain: str) -> None:
        import os

        env = {
            **os.environ,
            "DOMAIN_FOUNDRY_HOME": str(self.ws.home),
            "DOMAIN_FOUNDRY_MESH_DOMAIN": domain,
        }
        proc = subprocess.Popen(
            [sys.executable, "-m", "domain_foundry_core.mesh.expert_main", domain],
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        self._procs[domain] = proc
        state = self._children[domain]
        state.pid = proc.pid
        state.running = True
        state.last_started_at = now().timestamp()
        state.last_error = None

    def _monitor_loop(self) -> None:
        while not self._stop.is_set():
            for domain, proc in list(self._procs.items()):
                code = proc.poll()
                if code is None:
                    continue
                state = self._children[domain]
                state.running = False
                state.last_exit = code
                state.restarts += 1
                backoff = min(
                    self.max_backoff_s,
                    self.min_backoff_s * (2 ** min(state.restarts - 1, 6)),
                )
                err = None
                if proc.stderr is not None:
                    try:
                        err = proc.stderr.read().decode("utf-8", errors="replace")[:500]
                    except Exception:  # noqa: BLE001
                        err = None
                state.last_error = err or f"exit {code}"
                if self._stop.wait(backoff):
                    return
                if not self._stop.is_set():
                    self._spawn(domain)
            self._stop.wait(0.2)


def generate_launchd_plist_stub(
    *,
    label: str,
    program_args: list[str],
    home: Path,
) -> str:
    """Return a launchd plist body. Install wiring is TODO (mesh install)."""
    args_xml = "\n".join(f"        <string>{a}</string>" for a in program_args)
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<!-- TODO(mesh install): write to ~/Library/LaunchAgents/{label}.plist and launchctl load -->
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>{label}</string>
    <key>ProgramArguments</key>
    <array>
{args_xml}
    </array>
    <key>EnvironmentVariables</key>
    <dict>
        <key>DOMAIN_FOUNDRY_HOME</key>
        <string>{home}</string>
    </dict>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
</dict>
</plist>
"""
