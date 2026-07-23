"""hermes-agent adapter for the domain_foundry harness.

Exposes the harness runtime surface (capture / query / correct / review /
new_domain) as hermes-agent tools. Writes are in-process by default
(``LocalHarnessClient`` embedding ``HarnessAPI`` — mesh P0: no server on the
write path); HTTP mode (``DomainExpertClient``) remains available by setting
``DOMAIN_FOUNDRY_URL``. See ``plugin.py:register`` for the entry point.
"""

from __future__ import annotations

from domain_foundry_hermes_agent.client import DomainExpertClient, DomainExpertError
from domain_foundry_hermes_agent.local import LocalHarnessClient
from domain_foundry_hermes_agent.plugin import (
    SUPPORTED_HERMES_AGENT,
    Tool,
    build_tools,
    register,
)

__all__ = [
    "DomainExpertClient",
    "DomainExpertError",
    "LocalHarnessClient",
    "Tool",
    "build_tools",
    "register",
    "SUPPORTED_HERMES_AGENT",
]

__version__ = "0.2.0"
