"""Black-box drivers used by the Gate 1 conformance journey."""

from __future__ import annotations

import asyncio
import concurrent.futures
import json
import os
import queue
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from domain_foundry_hermes_agent import DomainExpertClient, DomainExpertError


class BackendSurfaceMissing(AssertionError):
    """The adapter reached a backend surface that has not landed yet."""


_CREDENTIAL_ENV_VARS = (
    "ANTHROPIC_API_KEY",
    "DEEPSEEK_API_KEY",
    "GEMINI_API_KEY",
    "GOOGLE_API_KEY",
    "MISTRAL_API_KEY",
    "OPENAI_API_KEY",
    "OPENROUTER_API_KEY",
    "DOMAIN_FOUNDRY_API_TOKEN",
    "DOMAIN_FOUNDRY_LLM_API_KEY",
    "DOMAIN_FOUNDRY_ROUTINE_API_KEY",
    "DOMAIN_FOUNDRY_SOTA_API_KEY",
)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _heuristic_env(home: Path) -> dict[str, str]:
    """Build a child environment with no credentials and no personal packs."""
    env = {key: value for key, value in os.environ.items()}
    env.update(
        {
            "DOMAIN_FOUNDRY_HOME": str(home),
            "DOMAIN_FOUNDRY_LLM": "heuristic",
        }
    )
    for key in _CREDENTIAL_ENV_VARS:
        env.pop(key, None)
    env.pop("DOMAIN_FOUNDRY_PACKS_PATH", None)
    env.pop("DOMAIN_FOUNDRY_PACKS", None)
    return env


def _domain_foundry_binary() -> str:
    """Resolve the installed console script without falling back in-process."""
    path = shutil.which("domain-foundry")
    if path:
        return path
    sibling = Path(sys.executable).with_name("domain-foundry")
    if sibling.is_file():
        return str(sibling)
    raise AssertionError(
        "Gate 1 CLI driver needs the installed `domain-foundry` console script; "
        f"looked on PATH and beside {sys.executable}"
    )


def _json_stdout(proc: subprocess.CompletedProcess[str], *, step: str) -> Any:
    output = proc.stdout.strip()
    if not output:
        raise AssertionError(
            f"CLI {step} produced no JSON on stdout (exit {proc.returncode}): "
            f"{proc.stderr.strip()}"
        )
    try:
        return json.loads(output)
    except json.JSONDecodeError as exc:
        raise AssertionError(
            f"CLI {step} produced non-JSON stdout: {output[:500]!r}; "
            f"stderr: {proc.stderr.strip()!r}"
        ) from exc


def _rows(payload: Any, *, key: str, step: str) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict) and isinstance(payload.get(key), list):
        return payload[key]
    raise AssertionError(f"{step} did not return a list or {{{key}: [...]}}: {payload!r}")


def _missing_export_message(interface: str, detail: Any) -> BackendSurfaceMissing:
    return BackendSurfaceMissing(
        f"Gate 1 {interface} export failed because the backend export surface is "
        "missing or unavailable. The backend owner must provide the specified "
        "domain-foundry export / GET /api/export / HarnessAPI.export_data surface; "
        f"received: {detail!r}"
    )


def _wait_for_health(url: str, process: subprocess.Popen[str], timeout: float = 15.0) -> None:
    deadline = time.monotonic() + timeout
    last_error: str | None = None
    while time.monotonic() < deadline:
        if process.poll() is not None:
            detail = ""
            if process.stderr is not None:
                detail = process.stderr.read().strip()
            raise AssertionError(
                f"HTTP server exited before health was ready (code {process.returncode}): "
                f"{detail}"
            )
        try:
            with urllib.request.urlopen(url, timeout=0.5) as response:
                if 200 <= response.status < 300:
                    return
        except (OSError, urllib.error.URLError) as exc:
            last_error = str(exc)
        time.sleep(0.1)
    raise AssertionError(f"HTTP server did not become healthy at {url}: {last_error}")


class CLIDriver:
    """Drive the installed ``domain-foundry`` console script per step."""

    name = "cli"

    def __init__(self, home: Path) -> None:
        self.home = home
        self._binary = _domain_foundry_binary()
        self.env = _heuristic_env(home)
        self._run("init", expect_json=False)

    def _run(self, *args: str, expect_json: bool = True) -> Any:
        proc = subprocess.run(
            [self._binary, "--home", str(self.home), *args],
            capture_output=True,
            text=True,
            env=self.env,
            timeout=120,
            check=False,
        )
        if args and args[0] == "export" and proc.returncode != 0:
            raise _missing_export_message(
                "CLI", f"exit {proc.returncode}; {proc.stderr.strip()}"
            )
        if proc.returncode not in (0, 1):
            raise AssertionError(
                f"CLI {' '.join(args)} failed with {proc.returncode}: "
                f"{proc.stderr.strip()}"
            )
        if not expect_json:
            return proc.stdout.strip()
        return _json_stdout(proc, step=" ".join(args))

    def new_domain(self, goal: str) -> dict[str, Any]:
        return self._run("new-domain", goal)

    def wizard_reply(self, session_id: str, text: str) -> dict[str, Any]:
        return self._run("wizard", "reply", session_id, text)

    def activate_pack(self, name: str) -> dict[str, Any]:
        return self._run("pack", "add", name)

    def capture(self, text: str) -> dict[str, Any]:
        return self._run("capture", "--json", text)

    def query(self, *, domain: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        args = ["query", "--limit", str(limit)]
        if domain:
            args.extend(["--domain", domain])
        return _rows(self._run(*args), key="rows", step="CLI query")

    def correct(
        self,
        *,
        text: str | None = None,
        object_uid: str | None = None,
        action: str | None = None,
        target_domain: str | None = None,
    ) -> dict[str, Any]:
        args = ["correct", "--json"]
        if text is not None:
            args.append(text)
        if object_uid is not None:
            args.extend(["--object-uid", object_uid])
        if action is not None:
            args.extend(["--action", action])
        if target_domain is not None:
            args.extend(["--domain", target_domain])
        return self._run(*args)

    def review_list(self) -> list[dict[str, Any]]:
        return _rows(self._run("review", "list"), key="items", step="CLI review list")

    def review_resolve(self, approval_id: str, decision: str) -> dict[str, Any]:
        return self._run(
            "review", "resolve", approval_id, "--decision", decision
        )

    def export(self, *, domain: str | None = None) -> dict[str, Any]:
        args = ["export"]
        if domain:
            args.extend(["--domain", domain])
        return self._run(*args)

    def restart(self) -> None:
        # Each CLI operation is already a new process.
        return None

    def close(self) -> None:
        return None


class HTTPDriver:
    """Drive ``DomainExpertClient`` against a real local server process."""

    name = "http"

    def __init__(self, home: Path, port: int) -> None:
        self.home = home
        self.port = port
        self.env = _heuristic_env(home)
        self.process: subprocess.Popen[str] | None = None
        self.client: DomainExpertClient | None = None
        self._start()

    def _start(self) -> None:
        process = subprocess.Popen(
            [
                _domain_foundry_binary(),
                "--home",
                str(self.home),
                "serve",
                "--host",
                "127.0.0.1",
                "--port",
                str(self.port),
            ],
            env=self.env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
        )
        self.process = process
        try:
            _wait_for_health(
                f"http://127.0.0.1:{self.port}/api/health", process
            )
        except Exception:
            self._stop_process()
            raise
        self.client = DomainExpertClient(f"http://127.0.0.1:{self.port}")

    def _stop_process(self) -> None:
        process = self.process
        self.process = None
        if process is None:
            return
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=15)
        if process.stderr is not None:
            process.stderr.close()

    def new_domain(self, goal: str) -> dict[str, Any]:
        assert self.client is not None
        return self.client.new_domain(goal)

    def wizard_reply(self, session_id: str, text: str) -> dict[str, Any]:
        assert self.client is not None
        return self.client.wizard_reply(session_id, text)

    def activate_pack(self, name: str) -> dict[str, Any]:
        assert self.client is not None
        return self.client.activate_pack(name)

    def capture(self, text: str) -> dict[str, Any]:
        assert self.client is not None
        return self.client.capture(text)

    def query(self, *, domain: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        assert self.client is not None
        return _rows(
            self.client.query(domain=domain, limit=limit),
            key="rows",
            step="HTTP query",
        )

    def correct(
        self,
        *,
        text: str | None = None,
        object_uid: str | None = None,
        action: str | None = None,
        target_domain: str | None = None,
    ) -> dict[str, Any]:
        assert self.client is not None
        return self.client.correct(
            text=text,
            object_uid=object_uid,
            action=action,
            target_domain=target_domain,
        )

    def review_list(self) -> list[dict[str, Any]]:
        assert self.client is not None
        return _rows(
            self.client.review_list(), key="items", step="HTTP review list"
        )

    def review_resolve(self, approval_id: str, decision: str) -> dict[str, Any]:
        assert self.client is not None
        return self.client.review_resolve(approval_id, decision=decision)

    def export(self, *, domain: str | None = None) -> dict[str, Any]:
        assert self.client is not None
        try:
            return self.client.export(domain=domain)
        except DomainExpertError as exc:
            raise _missing_export_message("HTTP", f"status {exc.status}: {exc.detail}") from exc

    def restart(self) -> None:
        if self.client is not None:
            self.client.close()
        self.client = None
        self._stop_process()
        self._start()

    def close(self) -> None:
        if self.client is not None:
            self.client.close()
            self.client = None
        self._stop_process()


def _mcp_payload(result: Any, *, tool_name: str) -> Any:
    """Unwrap a FastMCP result and turn tool errors into useful assertions."""
    content = getattr(result, "content", None) or []
    content_text: list[str] = []
    for block in content:
        block_text = getattr(block, "text", None)
        if block_text:
            content_text.append(str(block_text))
    if getattr(result, "isError", False):
        detail = " ".join(content_text) or repr(result)
        if tool_name == "domain_foundry_export":
            raise _missing_export_message("MCP", detail)
        raise AssertionError(f"MCP tool {tool_name} failed: {detail}")

    structured = getattr(result, "structuredContent", None)
    if isinstance(structured, dict):
        return structured.get("result", structured)
    for text in content_text:
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            continue
    raise AssertionError(f"MCP tool {tool_name} returned no structured JSON payload")


class MCPDriver:
    """Drive the actual MCP stdio server in a persistent subprocess session.

    The MCP SDK uses AnyIO cancel scopes whose enter/exit must be owned by the
    same asyncio task.  A dedicated loop thread keeps one worker task alive for
    the entire session, while the synchronous driver API submits commands to
    that task.  This also makes restart a real stdio-server restart.
    """

    name = "mcp"

    def __init__(self, home: Path) -> None:
        try:
            from mcp import ClientSession, StdioServerParameters
            from mcp.client.stdio import stdio_client
        except ImportError as exc:
            raise RuntimeError(
                "MCPDriver requires the optional `mcp` dependency "
                "(pip install 'mcp>=1.2.0')"
            ) from exc

        self.home = home
        self.env = _heuristic_env(home)
        self.env["PYTHONPATH"] = os.pathsep.join(
            [
                str(_repo_root() / "core"),
                str(_repo_root() / "adapters" / "mcp" / "src"),
                self.env.get("PYTHONPATH", ""),
            ]
        ).rstrip(os.pathsep)
        self._client_session_type = ClientSession
        self._server_parameters_type = StdioServerParameters
        self._stdio_client = stdio_client
        self._loop = asyncio.new_event_loop()
        self._commands: queue.Queue[tuple[str, Any, concurrent.futures.Future[Any]]] = queue.Queue()
        self._startup: concurrent.futures.Future[None] = concurrent.futures.Future()
        self._thread = threading.Thread(
            target=self._thread_main,
            name="domain-foundry-mcp-conformance",
            daemon=True,
        )
        self.tool_names: set[str] = set()
        self._closed = False
        self._thread.start()
        try:
            self._startup.result(timeout=30)
        except Exception:
            self._closed = True
            self._thread.join(timeout=15)
            raise

    def _thread_main(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._loop.create_task(self._worker())
        try:
            self._loop.run_forever()
        finally:
            if not self._loop.is_closed():
                self._loop.close()

    async def _worker(self) -> None:
        restart_future: concurrent.futures.Future[Any] | None = None
        try:
            while True:
                params = self._server_parameters_type(
                    command=sys.executable,
                    args=["-m", "domain_foundry_mcp.server", "--home", str(self.home)],
                    env=self.env,
                )
                try:
                    async with self._stdio_client(params) as (read, write):
                        async with self._client_session_type(read, write) as session:
                            await session.initialize()
                            listed = await session.list_tools()
                            self.tool_names = {tool.name for tool in listed.tools}
                            required = {
                                "domain_foundry_activate_pack",
                                "domain_foundry_export",
                            }
                            missing = required - self.tool_names
                            if missing:
                                raise AssertionError(
                                    "MCP tools/list is missing Gate 1 tools: "
                                    f"{sorted(missing)}"
                                )
                            if restart_future is not None:
                                restart_future.set_result(None)
                                restart_future = None
                            elif not self._startup.done():
                                self._startup.set_result(None)

                            while True:
                                command, payload, future = await asyncio.to_thread(
                                    self._commands.get
                                )
                                if command == "call":
                                    tool_name, arguments = payload
                                    try:
                                        result = await session.call_tool(
                                            tool_name, arguments
                                        )
                                    except Exception as exc:  # noqa: BLE001
                                        future.set_exception(exc)
                                    else:
                                        future.set_result(result)
                                elif command == "restart":
                                    restart_future = future
                                    break
                                elif command == "close":
                                    future.set_result(None)
                                    return
                except Exception as exc:
                    if restart_future is not None:
                        restart_future.set_exception(exc)
                        restart_future = None
                    if not self._startup.done():
                        self._startup.set_exception(exc)
                    return
        finally:
            if not self._startup.done():
                self._startup.set_exception(
                    RuntimeError("MCP conformance worker stopped before startup")
                )
            self._loop.call_soon_threadsafe(self._loop.stop)

    def _request(self, command: str, payload: Any = None, *, timeout: float = 120) -> Any:
        if self._closed:
            raise RuntimeError("MCPDriver is closed")
        future: concurrent.futures.Future[Any] = concurrent.futures.Future()
        self._commands.put((command, payload, future))
        return future.result(timeout=timeout)

    def _call(self, tool_name: str, arguments: dict[str, Any]) -> Any:
        if tool_name not in self.tool_names:
            raise AssertionError(f"MCP tools/list does not advertise {tool_name}")
        result = self._request("call", (tool_name, arguments))
        return _mcp_payload(result, tool_name=tool_name)

    def new_domain(self, goal: str) -> dict[str, Any]:
        return self._call("domain_foundry_new_domain", {"goal": goal})

    def wizard_reply(self, session_id: str, text: str) -> dict[str, Any]:
        return self._call(
            "domain_foundry_wizard_reply",
            {"session_id": session_id, "text": text},
        )

    def activate_pack(self, name: str) -> dict[str, Any]:
        return self._call("domain_foundry_activate_pack", {"name": name})

    def capture(self, text: str) -> dict[str, Any]:
        return self._call("domain_foundry_capture", {"text": text})

    def query(self, *, domain: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        arguments: dict[str, Any] = {"limit": limit}
        if domain is not None:
            arguments["domain"] = domain
        return _rows(
            self._call("domain_foundry_query", arguments),
            key="rows",
            step="MCP query",
        )

    def correct(
        self,
        *,
        text: str | None = None,
        object_uid: str | None = None,
        action: str | None = None,
        target_domain: str | None = None,
    ) -> dict[str, Any]:
        arguments = {
            key: value
            for key, value in {
                "text": text,
                "object_uid": object_uid,
                "action": action,
                "target_domain": target_domain,
            }.items()
            if value is not None
        }
        return self._call("domain_foundry_correct", arguments)

    def review_list(self) -> list[dict[str, Any]]:
        return _rows(
            self._call("domain_foundry_review_list", {}),
            key="items",
            step="MCP review list",
        )

    def review_resolve(self, approval_id: str, decision: str) -> dict[str, Any]:
        return self._call(
            "domain_foundry_review_resolve",
            {"approval_id": approval_id, "decision": decision},
        )

    def export(self, *, domain: str | None = None) -> dict[str, Any]:
        arguments = {"domain": domain} if domain is not None else {}
        return self._call("domain_foundry_export", arguments)

    def restart(self) -> None:
        self._request("restart")

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            future: concurrent.futures.Future[Any] = concurrent.futures.Future()
            self._commands.put(("close", None, future))
            future.result(timeout=30)
        finally:
            self._thread.join(timeout=30)
