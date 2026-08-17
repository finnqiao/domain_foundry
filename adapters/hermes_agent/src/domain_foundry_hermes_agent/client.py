"""Thin HTTP client for a running ``domain-foundry serve`` instance.

The client is intentionally dependency-light: it wraps either an ``httpx.Client``
(production) or any object exposing ``get``/``post`` that accepts a relative URL
and a ``json=`` kwarg (e.g. Starlette's ``TestClient``), so the conformance test
can drive the exact same code path against an in-process FastAPI app.
"""

from __future__ import annotations

from typing import Any, Protocol, cast, runtime_checkable


class DomainExpertError(RuntimeError):
    """Raised when the harness returns a non-2xx response."""

    def __init__(self, status: int, detail: Any) -> None:
        self.status = status
        self.detail = detail
        super().__init__(f"domain_foundry HTTP {status}: {detail}")


@runtime_checkable
class HttpSession(Protocol):
    def get(self, url: str, **kwargs: Any) -> Any: ...
    def post(self, url: str, **kwargs: Any) -> Any: ...


class DomainExpertClient:
    """Maps harness operations onto the ``domain-foundry serve`` HTTP surface."""

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:8787",
        *,
        token: str | None = None,
        session: HttpSession | None = None,
        timeout: float = 30.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token
        self._owns_session = session is None
        if session is None:
            import httpx

            session = cast(
                HttpSession, httpx.Client(base_url=self.base_url, timeout=timeout)
            )
        self._session = session

    # ------------------------------------------------------------------ infra
    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"} if self.token else {}

    def _handle(self, resp: Any) -> dict[str, Any]:
        status = getattr(resp, "status_code", 200)
        try:
            body = resp.json()
        except Exception:
            body = getattr(resp, "text", "")
        if status >= 400:
            raise DomainExpertError(status, body)
        return cast(dict[str, Any], body)

    def _get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        clean = {k: v for k, v in (params or {}).items() if v is not None}
        return self._handle(self._session.get(path, params=clean, headers=self._headers()))

    def _post(self, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        return self._handle(
            self._session.post(path, json=payload or {}, headers=self._headers())
        )

    def close(self) -> None:
        if self._owns_session:
            close = getattr(self._session, "close", None)
            if callable(close):
                close()

    def __enter__(self) -> DomainExpertClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # --------------------------------------------------------------- harness ops
    def health(self) -> dict[str, Any]:
        return self._get("/api/health")

    def capture(
        self,
        text: str,
        *,
        channel: str = "hermes-agent",
        source_ref: str | None = None,
        attachments: list[dict[str, Any]] | None = None,
        actor: str | None = None,
    ) -> dict[str, Any]:
        return self._post(
            "/api/capture",
            {
                "text": text,
                "channel": channel,
                "source_ref": source_ref,
                "attachments": attachments,
                "actor": actor,
            },
        )

    def query(
        self,
        *,
        domain: str | None = None,
        object_type: str | None = None,
        status: str | None = None,
        q: str | None = None,
        limit: int = 50,
    ) -> dict[str, Any]:
        return self._get(
            "/api/query",
            {
                "domain": domain,
                "object_type": object_type,
                "status": status,
                "q": q,
                "limit": limit,
            },
        )

    def ask(
        self,
        question: str,
        *,
        domain: str | None = None,
        limit: int = 20,
    ) -> dict[str, Any]:
        return self._post(
            "/api/ask",
            {"question": question, "domain": domain, "limit": limit},
        )

    def correct(
        self,
        *,
        text: str | None = None,
        entry_id: str | None = None,
        object_uid: str | None = None,
        action: str | None = None,
        fields: dict[str, Any] | None = None,
        merge_into_uid: str | None = None,
        target_domain: str | None = None,
        channel: str = "hermes-agent",
    ) -> dict[str, Any]:
        return self._post(
            "/api/correct",
            {
                "text": text,
                "entry_id": entry_id,
                "object_uid": object_uid,
                "action": action,
                "fields": fields,
                "merge_into_uid": merge_into_uid,
                "target_domain": target_domain,
                "channel": channel,
            },
        )

    def review_list(
        self,
        *,
        status: str = "pending",
        domain: str | None = None,
        include_diff: bool = False,
    ) -> dict[str, Any]:
        return self._get(
            "/api/review",
            {"status": status, "domain": domain, "include_diff": include_diff},
        )

    def review_stats(self, *, domain: str | None = None) -> dict[str, Any]:
        return self._get("/api/review/stats", {"domain": domain})

    def review_resolve(
        self,
        approval_id: str,
        *,
        decision: str,
        note: str | None = None,
        resolver: str = "hermes-agent",
    ) -> dict[str, Any]:
        return self._post(
            f"/api/review/{approval_id}/resolve",
            {"decision": decision, "note": note, "resolver": resolver},
        )

    def new_domain(self, goal_text: str, *, test_drive: int = 5) -> dict[str, Any]:
        return self._post(
            "/api/wizard", {"goal_text": goal_text, "test_drive": test_drive}
        )

    def wizard_reply(self, session_id: str, text: str) -> dict[str, Any]:
        return self._post(f"/api/wizard/{session_id}/reply", {"text": text})

    def atlas_search(self, goal: str, cursor_id: str | None = None) -> dict[str, Any]:
        return self._post("/api/atlas/search", {"goal": goal, "cursor_id": cursor_id})

    def inspect_pack(self, name: str) -> dict[str, Any]:
        return self._get(f"/api/packs/{name}/inspect")

    def suggest(self, domain: str) -> dict[str, Any]:
        return self._get(f"/api/wizard/{domain}/suggest")

    def apply_pack_edit(self, domain: str, text: str, *, confirm: bool = False) -> dict[str, Any]:
        return self._post(f"/api/packs/{domain}/edit", {"text": text, "confirm": confirm})

    def activate_pack(self, name: str) -> dict[str, Any]:
        """Install a bundled Domain Pack through the HTTP contract."""
        return self._post("/api/packs/activate", {"name": name})

    def export(self, *, domain: str | None = None) -> dict[str, Any]:
        """Export canonical data as secrets-free JSON through the HTTP contract."""
        return self._get("/api/export", {"domain": domain})
