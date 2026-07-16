"""FastAPI application: capture/query/health (+ static SPA mount later)."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from domain_expert_core.api.harness import HarnessAPI
from domain_expert_core.paths import Workspace
from domain_expert_core.projections.coordinator import ProjectionDrainLoop

# core/domain_expert_core/api/app.py → repo root is parents[3]
_REPO_APP_DIST = Path(__file__).resolve().parents[3] / "app" / "dist"


class CaptureBody(BaseModel):
    text: str
    channel: str = "web"
    source_ref: str | None = None
    actor: str | None = None
    attachments: list[dict[str, Any]] | None = None


def create_app(
    home: Path | None = None,
    *,
    api_token: str | None = None,
    enable_drain_loop: bool = True,
) -> FastAPI:
    token = api_token if api_token is not None else os.environ.get("DOMAIN_EXPERT_API_TOKEN")
    api = HarnessAPI(home)

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        # Background projection drain loop (invariant 11): converges the outbox
        # outside the request path so canonical commits never wait on rendering.
        loop = ProjectionDrainLoop(api.projections) if enable_drain_loop else None
        if loop is not None:
            loop.start()
        try:
            yield
        finally:
            if loop is not None:
                loop.stop()

    app = FastAPI(title="domain_expert", version="0.1.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://127.0.0.1:8787", "http://localhost:8787"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    def _auth(authorization: str | None) -> None:
        if not token:
            return
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="bearer token required")
        if authorization.removeprefix("Bearer ").strip() != token:
            raise HTTPException(status_code=403, detail="invalid token")

    @app.get("/health")
    def health(authorization: str | None = Header(default=None)) -> dict[str, Any]:
        _auth(authorization)
        return api.health().model_dump()

    @app.post("/api/capture")
    def capture(
        body: CaptureBody,
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any]:
        _auth(authorization)
        receipt = api.capture(
            body.text,
            channel=body.channel,
            source_ref=body.source_ref,
            attachments=body.attachments,
            actor=body.actor,
        )
        return receipt.model_dump()

    @app.get("/api/query")
    def query(
        domain: str | None = None,
        object_type: str | None = None,
        status: str | None = None,
        q: str | None = None,
        limit: int = Query(default=50, ge=1, le=500),
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any]:
        _auth(authorization)
        rows = api.query(
            domain=domain,
            object_type=object_type,
            status=status,
            q=q,
            limit=limit,
        )
        return {"rows": [r.model_dump() for r in rows]}

    class CorrectBody(BaseModel):
        text: str | None = None
        entry_id: str | None = None
        object_uid: str | None = None
        action: str | None = None
        fields: dict[str, Any] | None = None
        merge_into_uid: str | None = None
        target_domain: str | None = None
        channel: str = "web"

    @app.post("/api/correct")
    def correct(
        body: CorrectBody,
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any]:
        _auth(authorization)
        return api.correct(
            text=body.text,
            entry_id=body.entry_id,
            object_uid=body.object_uid,
            action=body.action,
            fields=body.fields,
            merge_into_uid=body.merge_into_uid,
            target_domain=body.target_domain,
            channel=body.channel,
        )

    @app.get("/api/review")
    def review_list(
        status: str = "pending",
        domain: str | None = None,
        operation: str | None = None,
        object_type: str | None = None,
        overdue_only: bool = False,
        include_diff: bool = False,
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any]:
        _auth(authorization)
        return {
            "items": api.review_list(
                status=status,
                domain=domain,
                operation=operation,
                object_type=object_type,
                overdue_only=overdue_only,
                include_diff=include_diff,
            )
        }

    @app.get("/api/review/stats")
    def review_stats(
        domain: str | None = None,
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any]:
        _auth(authorization)
        return api.review_stats(domain=domain)

    @app.get("/api/review/{approval_id}/diff")
    def review_diff(
        approval_id: str,
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any]:
        _auth(authorization)
        return api.review_diff(approval_id)

    class BulkResolveBody(BaseModel):
        approval_ids: list[str]
        decision: str
        note: str | None = None
        resolver: str = "user"

    @app.post("/api/review/bulk-resolve")
    def review_bulk_resolve(
        body: BulkResolveBody,
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any]:
        _auth(authorization)
        return api.review_resolve_bulk(
            body.approval_ids,
            decision=body.decision,
            note=body.note,
            resolver=body.resolver,
        )

    @app.get("/api/blocks/{domain}/views")
    def block_views(
        domain: str,
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any]:
        _auth(authorization)
        return {"views": api.block_views(domain)}

    @app.get("/api/blocks/{domain}/{view_id}/data")
    def block_view_data(
        domain: str,
        view_id: str,
        limit: int = Query(default=100, ge=1, le=500),
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any]:
        _auth(authorization)
        return api.block_view_data(domain, view_id, limit=limit)

    @app.post("/api/projections/drain")
    def projections_drain(
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any]:
        _auth(authorization)
        return api.drain_projections()

    @app.get("/api/projections/status")
    def projections_status(
        entry_id: str | None = None,
        change_request_id: int | None = None,
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any]:
        _auth(authorization)
        return api.projection_status(
            entry_id=entry_id, change_request_id=change_request_id
        )

    class ResolveBody(BaseModel):
        decision: str
        note: str | None = None
        resolver: str = "user"

    @app.post("/api/review/{approval_id}/resolve")
    def review_resolve(
        approval_id: str,
        body: ResolveBody,
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any]:
        _auth(authorization)
        return api.review_resolve(
            approval_id,
            decision=body.decision,
            note=body.note,
            resolver=body.resolver,
        )

    spa_index = _REPO_APP_DIST / "index.html"
    if spa_index.is_file():
        app.mount("/assets", StaticFiles(directory=_REPO_APP_DIST / "assets"), name="assets")

        @app.get("/")
        def spa_root() -> FileResponse:
            return FileResponse(spa_index)
    else:

        @app.get("/")
        def root() -> dict[str, Any]:
            ws = api.workspace
            return {
                "name": "domain_expert",
                "version": "0.1.0",
                "home": str(ws.home),
                "docs": "/docs",
                "hint": "Build the SPA with `cd app && npm run build`, or use /api/capture.",
            }

    app.state.harness = api  # type: ignore[attr-defined]
    return app


def run_server(
    home: Path | None = None,
    *,
    host: str = "127.0.0.1",
    port: int = 8787,
    api_token: str | None = None,
) -> None:
    import uvicorn

    if host not in {"127.0.0.1", "localhost", "::1"} and not (
        api_token or os.environ.get("DOMAIN_EXPERT_API_TOKEN")
    ):
        raise SystemExit(
            "Refusing non-local bind without DOMAIN_EXPERT_API_TOKEN "
            "(or --token). Pass --host 127.0.0.1 for local-only mode."
        )
    # Ensure workspace exists before serving
    Workspace(home).ensure_layout()
    HarnessAPI(home).init()
    app = create_app(home, api_token=api_token)
    uvicorn.run(app, host=host, port=port, log_level="info")
