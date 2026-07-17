"""hermes-agent adapter for the domain_foundry harness.

Exposes the harness runtime surface (capture / query / correct / review /
new_domain) as hermes-agent tools that talk to a running ``domain-foundry serve``
process over HTTP. See ``plugin.py:register`` for the entry point and
``client.py`` for the thin HTTP client.
"""

from __future__ import annotations

from domain_foundry_hermes_agent.client import DomainExpertClient, DomainExpertError
from domain_foundry_hermes_agent.plugin import (
    SUPPORTED_HERMES_AGENT,
    Tool,
    build_tools,
    register,
)

__all__ = [
    "DomainExpertClient",
    "DomainExpertError",
    "Tool",
    "build_tools",
    "register",
    "SUPPORTED_HERMES_AGENT",
]

__version__ = "0.1.0"
