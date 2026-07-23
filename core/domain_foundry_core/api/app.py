"""FastAPI application: read-only SPA surface (query/health/blocks).

Mesh P0: mutating routes return 410 Gone. Writes go in-process via the CLI
or the hermes-agent ``LocalHarnessClient`` (embedded ``HarnessAPI``).
"""

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

from domain_foundry_core.api.harness import HarnessAPI
from domain_foundry_core.paths import Workspace
from domain_foundry_core.projections.coordinator import ProjectionDrainLoop

# core/domain_foundry_core/api/app.py → repo root is parents[3]
_REPO_APP_DIST = Path(__file__).resolve().parents[3] / "app" / "dist"


# Mesh P0: the HTTP surface is READ-ONLY. Every mutating endpoint returns
# 410 Gone — writes go in-process through the CLI or the hermes-agent
# adapter's LocalHarnessClient (embedded HarnessAPI). A dead server can no
# longer block capture. The background projection drain loop stays until
# Domain Experts own draining (mesh P1/P2).
_WRITE_PATH_GONE = (
    "write endpoints were removed (mesh P0): the HTTP server is a read-only "
    "viewer. Use the domain-foundry CLI or the hermes-agent adapter, which "
    "embed the harness in-process."
)


def create_app(
    home: Path | None = None,
    *,
    api_token: str | None = None,
    enable_drain_loop: bool = True,
) -> FastAPI:
    token = api_token if api_token is not None else os.environ.get("DOMAIN_FOUNDRY_API_TOKEN")
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

    app = FastAPI(title="domain_foundry", version="0.1.0", lifespan=lifespan)
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

    @app.get("/api/health")
    def health_panel(
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any]:
        _auth(authorization)
        return api.health_panel()

    def _gone() -> None:
        raise HTTPException(status_code=410, detail=_WRITE_PATH_GONE)

    @app.post("/api/capture")
    def capture() -> dict[str, Any]:
        _gone()
        return {}

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

    @app.post("/api/correct")
    def correct() -> dict[str, Any]:
        _gone()
        return {}

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

    @app.post("/api/review/bulk-resolve")
    def review_bulk_resolve() -> dict[str, Any]:
        _gone()
        return {}

    @app.get("/api/packs")
    def packs_list(
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any]:
        _auth(authorization)
        return {"packs": api.pack_cards()}

    @app.get("/api/packs/catalog")
    def packs_catalog(
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any]:
        _auth(authorization)
        return {"catalog": api.pack_catalog()}

    @app.post("/api/packs/activate")
    def packs_activate() -> dict[str, Any]:
        _gone()
        return {}

    @app.get("/api/objects/{domain}/{object_type}/{object_uid}")
    def object_detail(
        domain: str,
        object_type: str,
        object_uid: str,
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any]:
        _auth(authorization)
        result = api.object_detail(domain, object_type, object_uid)
        if "error" in result:
            raise HTTPException(status_code=404, detail=result["error"])
        return result

    @app.get("/api/eval")
    def eval_routing(
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any]:
        _auth(authorization)
        return api.eval_routing()

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
    def projections_drain() -> dict[str, Any]:
        _gone()
        return {}

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

    @app.get("/api/mesh/status")
    def mesh_status(
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any]:
        """Read-only mesh dashboard stub: per-domain health + queue depths + DLQ counts."""
        _auth(authorization)
        return api.mesh_status()

    @app.get("/api/mesh/dlq")
    def mesh_dlq(
        domain: str | None = None,
        queue: str | None = None,
        limit: int = Query(default=100, ge=1, le=500),
        include_failed: bool = True,
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any]:
        """Read-only dead-letter listing for the future SPA mesh dashboard."""
        _auth(authorization)
        return api.mesh_dlq_list(
            domain=domain,
            queue=queue,
            limit=limit,
            include_failed=include_failed,
        )

    @app.get("/api/quiz/stats")
    def quiz_stats_endpoint(
        domain: str = Query(default="japanese"),
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any]:
        """Read-only SRS quiz aggregates for the QuizStats SPA block."""
        _auth(authorization)
        return api.quiz_stats(domain=domain)

    @app.post("/api/review/{approval_id}/resolve")
    def review_resolve(approval_id: str) -> dict[str, Any]:
        _gone()
        return {}

    # Side-loaded custom blocks (dev path, plan §9.3): built ESM dropped into
    # ~/.domain_foundry/blocks/ is served read-only; the SPA imports its index at
    # startup. Custom blocks are trusted code (documented in docs/custom-blocks.md).
    blocks_dir = api.workspace.blocks_dir
    if blocks_dir.is_dir():
        app.mount(
            "/custom-blocks",
            StaticFiles(directory=blocks_dir, check_dir=False),
            name="custom-blocks",
        )

    @app.post("/api/wizard")
    def wizard_new_domain() -> dict[str, Any]:
        _gone()
        return {}

    @app.post("/api/wizard/{session_id}/reply")
    def wizard_reply(session_id: str) -> dict[str, Any]:
        _gone()
        return {}

    @app.get("/api/wizard/{domain}/suggest")
    def wizard_suggest(
        domain: str,
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any]:
        _auth(authorization)
        return {"suggestion": api.wizard_suggest(domain)}

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
                "name": "domain_foundry",
                "version": "0.1.0",
                "home": str(ws.home),
                "docs": "/docs",
                "hint": "Build the SPA with `cd app && npm run build`. Writes go in-process (CLI / hermes-agent); this HTTP surface is read-only.",
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
        api_token or os.environ.get("DOMAIN_FOUNDRY_API_TOKEN")
    ):
        raise SystemExit(
            "Refusing non-local bind without DOMAIN_FOUNDRY_API_TOKEN "
            "(or --token). Pass --host 127.0.0.1 for local-only mode."
        )
    # Ensure workspace exists before serving
    Workspace(home).ensure_layout()
    HarnessAPI(home).init()
    app = create_app(home, api_token=api_token)
    uvicorn.run(app, host=host, port=port, log_level="info")
