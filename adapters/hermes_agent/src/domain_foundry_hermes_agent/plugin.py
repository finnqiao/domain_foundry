"""hermes-agent plugin registration for the domain_foundry harness.

`register(ctx)` is the published entry point (group ``hermes_agent.plugins``).
It builds a :class:`DomainExpertClient` from the host context / environment and
registers the harness tools with the agent runtime.

Because hermes-agent's exact registration API has evolved, ``register`` is
defensive: it discovers the host's tool-registration hook by name and falls back
to stashing the tool list on the context so a host can pick it up. The tools
themselves are plain, host-agnostic :class:`Tool` records (name + JSON-schema
parameters + handler), which is why the same objects drive the conformance test.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from domain_foundry_hermes_agent.client import DomainExpertClient

# Pinned, tested hermes-agent compatibility range. Bumping the upper bound is a
# reviewed change gated by the conformance test in this repo.
# Upper bound kept loose so `hermes update` does not silently break discovery;
# conformance tests pin the actually-tested host range.
SUPPORTED_HERMES_AGENT = ">=0.4,<1"

# Capture-first behavioral guidance. Hosts should inject this into the agent's
# system prompt / skill so the model uses the harness the way it is designed to
# be used. Mirrors adapters/hermes_agent/SKILL.md.
CAPTURE_FIRST_GUIDANCE = """\
You have a domain_foundry harness attached. Follow capture-first discipline:

1. When the user reports something that happened in one of their tracked life
   domains (a bake, a plant watered, a meal, a trip plan, a cooking idea),
   call `domain_foundry_capture` with their words *verbatim*. Do not paraphrase,
   pre-structure, or drop details — the harness parses and stores it durably.
2. Never invent structured fields. Capture the raw text; the harness routes it.
3. When the user amends or contradicts something ("actually it was 80% not
   75%"), call `domain_foundry_correct` with their correction sentence. One
   message, one correction — do not re-capture.
4. To answer "what did I…" questions, call `domain_foundry_query` (read-only).
5. Surface pending approvals with `domain_foundry_review_list`; only resolve one
   after the user explicitly approves or rejects it.
6. To stand up a brand-new tracking domain from a plain-language goal, call
   `domain_foundry_new_domain` and relay the wizard's questions to the user.

The harness is local-first and authoritative. You are a courier for the user's
words, not the source of truth.
"""


@dataclass
class Tool:
    """Host-agnostic tool description the adapter registers with hermes-agent."""

    name: str
    description: str
    parameters: dict[str, Any]
    handler: Callable[..., dict[str, Any]]

    def __call__(self, **kwargs: Any) -> dict[str, Any]:
        return self.handler(**kwargs)

    def to_spec(self) -> dict[str, Any]:
        """JSON-schema tool spec (OpenAI/hermes-agent function-tool shape)."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


def _string(desc: str) -> dict[str, Any]:
    return {"type": "string", "description": desc}


def build_tools(client: Any) -> list[Tool]:
    """Construct the harness tool set bound to a client.

    ``client`` is duck-typed: LocalHarnessClient (in-process, default) and
    DomainExpertClient (HTTP, opt-in) expose the same nine methods.
    """

    return [
        Tool(
            name="domain_foundry_capture",
            description=(
                "Capture the user's verbatim message into the harness ledger; it "
                "is routed to the right domain and stored durably. Use for anything "
                "the user did/observed in a tracked domain."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "text": _string("The user's message, verbatim."),
                    "channel": _string("Origin channel (default: hermes-agent)."),
                    "source_ref": _string("Optional idempotency / source key."),
                },
                "required": ["text"],
            },
            handler=lambda text, channel="hermes-agent", source_ref=None: client.capture(
                text, channel=channel, source_ref=source_ref
            ),
        ),
        Tool(
            name="domain_foundry_query",
            description="Read-only query over captured entries (by domain / type / text).",
            parameters={
                "type": "object",
                "properties": {
                    "domain": _string("Restrict to a domain, e.g. 'sourdough'."),
                    "object_type": _string("Restrict to an object type."),
                    "status": _string("Entry status filter."),
                    "q": _string("Full-text search string."),
                    "limit": {"type": "integer", "description": "Max rows (default 50)."},
                },
            },
            handler=lambda domain=None, object_type=None, status=None, q=None, limit=50: client.query(
                domain=domain, object_type=object_type, status=status, q=q, limit=limit
            ),
        ),
        Tool(
            name="domain_foundry_correct",
            description=(
                "Apply a one-message correction (natural language, or an explicit "
                "amend/move/merge/undo/mark_wrong action) to an existing capture."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "text": _string("Natural-language correction sentence."),
                    "entry_id": _string("Target entry id (optional)."),
                    "object_uid": _string("Target canonical object uid (optional)."),
                    "action": _string("amend|move|merge|undo|mark_wrong (optional)."),
                    "target_domain": _string("Destination domain for a move."),
                    "merge_into_uid": _string("Merge target uid."),
                },
            },
            handler=lambda text=None, entry_id=None, object_uid=None, action=None, target_domain=None, merge_into_uid=None: client.correct(
                text=text,
                entry_id=entry_id,
                object_uid=object_uid,
                action=action,
                target_domain=target_domain,
                merge_into_uid=merge_into_uid,
            ),
        ),
        Tool(
            name="domain_foundry_review_list",
            description="List approval-queue items awaiting a human decision.",
            parameters={
                "type": "object",
                "properties": {
                    "status": _string("Queue status (default: pending)."),
                    "domain": _string("Restrict to a domain."),
                    "include_diff": {
                        "type": "boolean",
                        "description": "Include proposed-vs-canonical diffs.",
                    },
                },
            },
            handler=lambda status="pending", domain=None, include_diff=False: client.review_list(
                status=status, domain=domain, include_diff=include_diff
            ),
        ),
        Tool(
            name="domain_foundry_review_resolve",
            description="Resolve one approval-queue item after the user decides.",
            parameters={
                "type": "object",
                "properties": {
                    "approval_id": _string("The approval id to resolve."),
                    "decision": _string("approved|denied|expired."),
                    "note": _string("Optional resolution note."),
                },
                "required": ["approval_id", "decision"],
            },
            handler=lambda approval_id, decision, note=None: client.review_resolve(
                approval_id, decision=decision, note=note
            ),
        ),
        Tool(
            name="domain_foundry_new_domain",
            description=(
                "Start the guided domain-creation wizard from a plain-language goal; "
                "returns the session id and the next interview turn to relay."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "goal_text": _string("Plain-language goal, e.g. 'track my dive log'."),
                    "test_drive": {"type": "integer", "description": "Test-drive budget."},
                },
                "required": ["goal_text"],
            },
            handler=lambda goal_text, test_drive=5: client.new_domain(
                goal_text, test_drive=test_drive
            ),
        ),
        Tool(
            name="domain_foundry_wizard_reply",
            description="Send one reply (interview answer / sample capture / edit) to a wizard session.",
            parameters={
                "type": "object",
                "properties": {
                    "session_id": _string("Wizard session id."),
                    "text": _string("The reply text."),
                },
                "required": ["session_id", "text"],
            },
            handler=lambda session_id, text: client.wizard_reply(session_id, text),
        ),
    ]


@dataclass
class RegistrationResult:
    """What `register` wired up — returned for host inspection and testing."""

    tools: list[Tool] = field(default_factory=list)
    client: DomainExpertClient | None = None
    guidance: str = CAPTURE_FIRST_GUIDANCE
    supported_hermes_agent: str = SUPPORTED_HERMES_AGENT

    @property
    def tool_names(self) -> list[str]:
        return [t.name for t in self.tools]


def _ctx_get(ctx: Any, key: str) -> Any:
    """Best-effort config lookup across plausible hermes-agent context shapes."""
    if ctx is None:
        return None
    for attr in (key, "config", "settings", "options"):
        val = getattr(ctx, attr, None)
        if attr == key and val is not None:
            return val
        if isinstance(val, dict) and key in val:
            return val[key]
    getter = getattr(ctx, "get_config", None) or getattr(ctx, "get", None)
    if callable(getter):
        try:
            return getter(key)
        except Exception:
            return None
    return None


def _resolve_client(ctx: Any, client: Any | None) -> Any:
    """Pick the harness client. In-process is the default (mesh P0).

    Priority:
      1. An explicitly injected ``client``.
      2. HTTP, when the host explicitly configured a URL (ctx ``base_url`` or
         ``DOMAIN_FOUNDRY_URL``) — the opt-in remote mode.
      3. In-process :class:`LocalHarnessClient` when ``domain-foundry-core`` is
         importable — writes go straight to SQLite; no server on the write path.
      4. HTTP to the default local port, as the last-resort fallback.
    """
    if client is not None:
        return client
    base_url = _ctx_get(ctx, "base_url") or os.environ.get("DOMAIN_FOUNDRY_URL")
    token = _ctx_get(ctx, "token") or os.environ.get("DOMAIN_FOUNDRY_API_TOKEN")
    if base_url:
        return DomainExpertClient(str(base_url), token=token)
    try:
        from domain_foundry_hermes_agent.local import LocalHarnessClient

        return LocalHarnessClient(
            _ctx_get(ctx, "home") or os.environ.get("DOMAIN_FOUNDRY_HOME")
        )
    except ImportError:
        return DomainExpertClient("http://127.0.0.1:8787", token=token)


def _param_names(func: Callable[..., Any]) -> set[str]:
    import inspect

    try:
        return set(inspect.signature(func).parameters)
    except (TypeError, ValueError):
        return set()


def _hermes_tool_handler(tool: Tool) -> Callable[..., str]:
    """Adapt a Tool to Hermes 0.14+ handler shape: ``(args: dict, **kwargs) -> str``."""
    import json

    def handler(args: dict | None = None, **_kwargs: Any) -> str:
        payload = {k: v for k, v in dict(args or {}).items() if v is not None}
        try:
            result = tool(**payload)
            return json.dumps(result, ensure_ascii=False, default=str)
        except Exception as exc:  # noqa: BLE001 — never raise into the host loop
            return json.dumps({"error": str(exc)}, ensure_ascii=False)

    return handler


def _tool_schema(tool: Tool) -> dict[str, Any]:
    return {
        "name": tool.name,
        "description": tool.description,
        "parameters": tool.parameters,
    }


def _register_with_host(ctx: Any, tools: list[Tool]) -> bool:
    """Try the host's registration hook; return True if one was found."""
    if ctx is None:
        return False
    # Try a per-tool registration hook first.
    for method in ("register_tool", "add_tool", "tool"):
        hook = getattr(ctx, method, None)
        if not callable(hook):
            continue
        params = _param_names(hook)
        # Hermes 0.14+ PluginContext: name + toolset + schema + handler.
        if "toolset" in params and "schema" in params:
            for t in tools:
                hook(
                    name=t.name,
                    toolset="domain_foundry",
                    schema=_tool_schema(t),
                    handler=_hermes_tool_handler(t),
                    description=t.description,
                )
            return True
        # Legacy / test fakes: name + description + parameters + handler.
        if "name" in params or "parameters" in params:
            for t in tools:
                hook(
                    name=t.name,
                    description=t.description,
                    parameters=t.parameters,
                    handler=t.handler,
                )
            return True
        for t in tools:
            hook(t)
        return True
    # Try a bulk registration hook.
    for method in ("register_tools", "add_tools"):
        hook = getattr(ctx, method, None)
        if callable(hook):
            hook(tools)
            return True
    return False


def _publish_guidance(ctx: Any) -> None:
    """Inject capture-first guidance via whichever host API is available."""
    if ctx is None:
        return
    for method in ("add_system_prompt", "register_guidance", "add_guidance"):
        hook = getattr(ctx, method, None)
        if callable(hook):
            try:
                hook(CAPTURE_FIRST_GUIDANCE)
            except Exception:
                pass
            return
    # Hermes 0.14+: no system-prompt helper; use pre_llm_call context injection.
    register_hook = getattr(ctx, "register_hook", None)
    if callable(register_hook):

        def _inject_guidance(**_kwargs: Any) -> dict[str, str]:
            return {"context": CAPTURE_FIRST_GUIDANCE}

        try:
            register_hook("pre_llm_call", _inject_guidance)
        except Exception:
            pass


def register(ctx: Any = None, *, client: DomainExpertClient | None = None) -> RegistrationResult:
    """hermes-agent plugin entry point.

    Builds the harness client + tools and registers them with the host context
    if a known registration hook is present. Always returns a
    :class:`RegistrationResult` so hosts (and the conformance test) can inspect
    what was wired up, including the capture-first behavioral guidance to inject.
    """
    de_client = _resolve_client(ctx, client)
    tools = build_tools(de_client)
    registered = _register_with_host(ctx, tools)
    _publish_guidance(ctx)

    # Fall back to stashing the tool list on the context for host pickup.
    if not registered and ctx is not None:
        try:
            ctx.domain_foundry_tools = tools
        except Exception:
            pass

    return RegistrationResult(tools=tools, client=de_client)
