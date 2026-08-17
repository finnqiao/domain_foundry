"""Supervisor skeleton — spawn/monitor Domain Experts with backoff."""

from __future__ import annotations

import json
import subprocess
import sys
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from domain_foundry_core.clock import now
from domain_foundry_core.mesh.inbox import DomainInbox
from domain_foundry_core.mesh.journal import InboxJournal
from domain_foundry_core.mesh.observability import MeshObservability
from domain_foundry_core.mesh.outbound import OutboundQueue
from domain_foundry_core.paths import Workspace

DEFAULT_EXPERT_DOMAINS = ("japanese", "food")


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
    domains: dict[str, dict[str, Any]] = field(default_factory=dict)
    queue_depths: dict[str, int] = field(default_factory=dict)
    dlq: dict[str, int] = field(default_factory=dict)
    alerts: dict[str, Any] = field(default_factory=dict)
    children: list[dict[str, Any]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    registered: list[str] = field(default_factory=list)


class Supervisor:
    """Monitors Expert child processes with exponential backoff restarts.

    Foundation skeleton: spawns `python -m domain_foundry_core.mesh.expert_main`
    per domain. launchd install is stubbed (see mesh install CLI).

    ``register(domain)`` hot-adds Expert child config (persisted under
    ``<home>/mesh/registered_experts.json``) without requiring launchd apply.
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
        self.ws.ensure_layout()
        (self.ws.home / "mesh").mkdir(parents=True, exist_ok=True)
        persisted = self.list_registered()
        if domains is None:
            merged = list(dict.fromkeys([*DEFAULT_EXPERT_DOMAINS, *persisted]))
        else:
            merged = list(dict.fromkeys([*domains, *persisted]))
        self.domains = merged
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
        self.obs = MeshObservability(self.ws)

    def _registry_path(self) -> Path:
        return self.ws.home / "mesh" / "registered_experts.json"

    def list_registered(self) -> list[str]:
        path = self._registry_path()
        if not path.exists():
            return []
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        if isinstance(raw, dict):
            domains = raw.get("domains") or []
        elif isinstance(raw, list):
            domains = raw
        else:
            return []
        return [str(d) for d in domains if str(d).strip()]

    def _save_registered(self, domains: list[str]) -> None:
        path = self._registry_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({"domains": list(domains)}, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    def register(self, domain: str, *, spawn: bool = False) -> dict[str, Any]:
        """Hot-register an Expert child config for ``domain``.

        Persists the domain so subsequent Supervisor instances include it.
        Does **not** apply launchd (stub). Optionally spawns the Expert process
        when the supervise loop is already running.
        """
        domain = str(domain).strip()
        if not domain:
            return {
                "domain": domain,
                "registered": False,
                "error": "empty domain",
                "launchd": "stubbed",
            }
        registered = self.list_registered()
        if domain not in registered:
            registered.append(domain)
            self._save_registered(registered)
        if domain not in self.domains:
            self.domains.append(domain)
        if domain not in self._children:
            self._children[domain] = ChildState(domain=domain)

        running = False
        if spawn:
            monitor_alive = (
                self._monitor_thread is not None and self._monitor_thread.is_alive()
            )
            proc = self._procs.get(domain)
            if monitor_alive and (proc is None or proc.poll() is not None):
                self._spawn(domain)
            proc = self._procs.get(domain)
            running = proc is not None and proc.poll() is None
            self._children[domain].running = running

        return {
            "domain": domain,
            "registered": "running" if running else "config_only",
            "running": running,
            "launchd": "stubbed",
            "note": (
                "expert process is NOT running; launchd install is stubbed. "
                "Config persisted so a supervise loop will include this domain."
                if not running
                else "expert process spawned under the current supervise loop; "
                "launchd install is stubbed."
            ),
        }

    def status(self) -> SupervisorStatus:
        health = self.obs.health()
        children = []
        for domain, state in self._children.items():
            proc = self._procs.get(domain)
            running = proc is not None and proc.poll() is None
            state.running = running
            state.pid = proc.pid if proc and running else None
            domain_health = dict(health.domains.get(domain) or {})
            children.append(
                {
                    "domain": domain,
                    "running": running,
                    "pid": state.pid,
                    "restarts": state.restarts,
                    "last_exit": state.last_exit,
                    "last_error": state.last_error,
                    "inbox": self.inbox.depth(domain),
                    "last_processed_at": domain_health.get("last_processed_at"),
                    "error_rate": domain_health.get("error_rate", 0.0),
                    "pending_depth": domain_health.get("pending_depth", 0),
                }
            )
        return SupervisorStatus(
            home=str(self.ws.home),
            journal=health.journal,
            inbox_by_domain=health.inbox_by_domain,
            outbound=health.outbound,
            domains=health.domains,
            queue_depths=health.queue_depths,
            dlq=health.dlq,
            alerts=health.alerts,
            children=children,
            registered=self.list_registered(),
            notes=list(health.notes)
            + [
                "launchd install stubbed — use `domain-foundry mesh install` TODO",
                "gateway fast path: private logbook plugin (HERMES_MESH_FAST_PATH)",
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
