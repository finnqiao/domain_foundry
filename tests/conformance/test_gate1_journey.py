"""Gate 1 contract parity through CLI, HTTP, and MCP ingress paths."""

from __future__ import annotations

import socket
from collections.abc import Iterator
from pathlib import Path

import pytest

from .drivers import CLIDriver, HTTPDriver, MCPDriver
from .journey import run_journey


@pytest.fixture
def free_tcp_port() -> Iterator[int]:
    """Reserve an ephemeral port long enough to hand it to the HTTP driver."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        port = int(sock.getsockname()[1])
    yield port


@pytest.mark.parametrize("driver_kind", ["cli", "http", "mcp"], ids=["cli", "http", "mcp"])
def test_gate1_journey(
    driver_kind: str,
    tmp_path: Path,
    free_tcp_port: int,
) -> None:
    if driver_kind == "mcp":
        pytest.importorskip("mcp", reason="pip install 'mcp>=1.2.0' to run the MCP conformance leg")

    home = tmp_path / "home"
    if driver_kind == "cli":
        driver = CLIDriver(home)
    elif driver_kind == "http":
        driver = HTTPDriver(home, free_tcp_port)
    else:
        driver = MCPDriver(home)

    try:
        run_journey(driver)
    finally:
        close = getattr(driver, "close", None)
        if callable(close):
            close()
