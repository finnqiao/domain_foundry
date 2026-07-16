"""FastAPI application: capture/query/health (+ static SPA mount later)."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from domain_expert_core.api.harness import HarnessAPI
from domain_expert_core.paths import Workspace

# core/domain_expert_core/api/app.py → repo root is parents[3]
_REPO_APP_DIST = Path(__file__).resolve().parents[3] / "app" / "dist"


class CaptureBody(BaseModel):
    text: str
    channel: str = "web"
    source_ref: str | None = None
    actor: str | None = None
    attachments: list[dict[str, Any]] | None = None


def create_app(home: Path | None = None, *, api_token: str | None = None) -> FastAPI:
    token = api_token if api_token is not None else os.environ.get("DOMAIN_EXPERT_API_TOKEN")
    api = HarnessAPI(home)
    app = FastAPI(title="domain_expert", version="0.1.0")
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
