"""FastAPI application: the local daemon serving the SPA and the harness contract.

ADR-006 (re-affirming ADR-001): this daemon is the canonical mutation seam for
the SPA and for any adapter that does not embed ``HarnessAPI`` in-process.
Reads and writes share one auth posture: open on localhost by default,
bearer-token gated on every API endpoint once a token is configured, and
non-local binds refuse to start without a token (see ``run_server``). Static
HTML shells bootstrap that token for their own API calls.
"""

from __future__ import annotations

import json
import mimetypes
import os
import re
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import Body, FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from domain_foundry_core.api.harness import HarnessAPI
from domain_foundry_core.api.pack_import import PackImportError, PackImportService
from domain_foundry_core.api.roamboard_import import (
    RoamboardImportError,
    RoamboardImportService,
)
from domain_foundry_core.api.schemas import (
    ActivateBody,
    ApplyBody,
    AtlasSearchBody,
    BulkResolveBody,
    CaptureBody,
    CorrectBody,
    DrainBody,
    FoundryCompleteBody,
    FoundryProposeBody,
    HardeningBody,
    PackEditBody,
    PackExportBody,
    PackImportCommitBody,
    PackImportPreviewBody,
    PackInstallBody,
    PackNameBody,
    PackRollbackBody,
    PackSourceBody,
    QuizGradeBody,
    QuizStartBody,
    ResolveBody,
    RoamboardCommitBody,
    RoamboardPreviewBody,
    ScheduleStatusBody,
    WizardBody,
    WizardReplyBody,
)
from domain_foundry_core.paths import Workspace
from domain_foundry_core.projections.coordinator import ProjectionDrainLoop

# Where the built SPA lives. From a checkout it is app/dist (repo root is
# parents[3]); from an installed wheel there is no repo, so the release build
# stages the same files inside the package as _webapp/ — otherwise `pipx install
# domain-foundry-core && domain-foundry serve` serves JSON instead of the app the
# quickstart promises. See scripts/stage_webapp.sh.
_PACKAGED_APP_DIST = Path(__file__).resolve().parent.parent / "_webapp"
_REPO_APP_DIST = Path(__file__).resolve().parents[3] / "app" / "dist"


def _app_dist() -> Path:
    """The SPA build to serve — checkout first, then the packaged copy."""
    if (_REPO_APP_DIST / "index.html").is_file():
        return _REPO_APP_DIST
    return _PACKAGED_APP_DIST


def create_app(
    home: Path | None = None,
    *,
    api_token: str | None = None,
    enable_drain_loop: bool = True,
) -> FastAPI:
    token = api_token if api_token is not None else os.environ.get("DOMAIN_FOUNDRY_API_TOKEN")
    api = HarnessAPI(home)
    from domain_foundry_core.foundry.service import FoundryService

    foundry = FoundryService(api.workspace.home)
    roamboard_import = RoamboardImportService(api.workspace)
    pack_import = PackImportService(api.workspace, registry=api.packs)

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
        allow_origins=[
            "http://127.0.0.1:8787",
            "http://localhost:8787",
            # Vite dev server (app/vite.config.ts). `npm run dev` proxies /api
            # and /health to :8787, but direct browser calls (and websocket-free
            # tools) hit this origin — allow both spellings.
            "http://127.0.0.1:5173",
            "http://localhost:5173",
        ],
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

    @app.get("/api/foundry/goldens")
    def foundry_goldens(
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any]:
        _auth(authorization)
        return {"goldens": foundry.list_goldens()}

    @app.get("/api/foundry/goldens/{spec_id}")
    def foundry_golden(
        spec_id: str,
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any]:
        _auth(authorization)
        try:
            return foundry.get_golden(spec_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/api/foundry/proposals")
    def foundry_propose(
        body: FoundryProposeBody,
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any]:
        from domain_foundry_core.foundry.pipeline import AcceptanceTask, PipelineError
        from domain_foundry_core.foundry.research import ResearchUnavailable

        _auth(authorization)
        try:
            proposal_id, result = foundry.propose(
                body.goal,
                artifacts=body.artifacts,
                constraints=body.constraints,
                acceptance_tasks=[
                    AcceptanceTask(input=item.input, expected=item.expected)
                    for item in body.acceptance_tasks
                ],
                use_web_research=body.web_research,
            )
        except (ResearchUnavailable, PipelineError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {
            "proposal_id": proposal_id,
            "candidate_sources": result.candidate_count,
            "proposal": result.proposal.model_dump(mode="json"),
            "sources": foundry.proposal_sources(result.proposal),
        }

    @app.post("/api/foundry/proposals/{proposal_id}/complete")
    def foundry_complete(
        proposal_id: str,
        body: FoundryCompleteBody,
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any]:
        from domain_foundry_core.foundry.models import RemixSelection
        from domain_foundry_core.foundry.pipeline import PipelineError

        _auth(authorization)
        try:
            return foundry.complete(
                proposal_id,
                RemixSelection(
                    selected_concept=body.selected_concept,
                    fragments=body.fragments,
                    user_decisions=body.user_decisions,
                ),
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except (ValueError, PipelineError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except (RuntimeError, FileExistsError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get("/api/foundry/apps/{proposal_id}", response_class=HTMLResponse)
    def foundry_app(
        proposal_id: str,
        authorization: str | None = Header(default=None),
    ) -> FileResponse:
        _auth(authorization)
        try:
            return FileResponse(foundry.app_path(proposal_id), media_type="text/html")
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    def _pack_operation(operation: Callable[[], dict[str, Any]]) -> dict[str, Any]:
        """Run one registry lifecycle operation with truthful HTTP failures."""
        try:
            return operation()
        except FileExistsError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except (FileNotFoundError, KeyError) as exc:
            detail = str(exc.args[0]) if isinstance(exc, KeyError) and exc.args else str(exc)
            raise HTTPException(status_code=404, detail=detail) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

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

    @app.get("/api/settings/providers")
    def provider_settings(
        authorization: str | None = Header(default=None),
    ) -> dict[str, object]:
        """Return the redacted provider status used by the SPA settings view."""
        _auth(authorization)
        from domain_foundry_core.onboarding import resolved_status

        return resolved_status(api.workspace.home)

    @app.post("/api/capture")
    def capture(
        body: CaptureBody,
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any]:
        _auth(authorization)
        try:
            receipt = api.capture(
                body.text,
                channel=body.channel,
                domain_hint=body.domain_hint,
                source_ref=body.source_ref,
                attachments=body.attachments,
                actor=body.actor,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return receipt.model_dump()

    # Ingest is a *local, server-side* operation: this process reads local files
    # and drives its own in-process HarnessAPI. Unlike the JSON write endpoints
    # above, the request carries a filesystem path, so it only makes sense
    # against the daemon's own machine.
    @app.post("/api/ingest/preview")
    def ingest_preview(
        body: dict[str, Any] = Body(...),
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any]:
        _auth(authorization)
        from domain_foundry_core.ingest import ingest as _ingest

        report = _ingest(
            api,
            body["path"],
            channel=str(body.get("channel") or "folder-import"),
            glob=body.get("glob"),
            split=str(body.get("split") or "file"),
            only=body.get("only"),
            limit=body.get("limit"),
            dry_run=True,
        )
        return report.as_dict()

    @app.post("/api/ingest")
    def ingest_commit(
        body: dict[str, Any] = Body(...),
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any]:
        _auth(authorization)
        from domain_foundry_core.ingest import ingest as _ingest

        report = _ingest(
            api,
            body["path"],
            channel=str(body.get("channel") or "folder-import"),
            glob=body.get("glob"),
            split=str(body.get("split") or "file"),
            only=body.get("only"),
            limit=body.get("limit"),
            dry_run=False,
        )
        return report.as_dict()

    @app.post("/api/import/roamboard/preview")
    def roamboard_preview(
        body: RoamboardPreviewBody,
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any]:
        _auth(authorization)
        try:
            return roamboard_import.preview(body.feed_path)
        except RoamboardImportError as exc:
            raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

    @app.post("/api/import/roamboard/commit")
    def roamboard_commit(
        body: RoamboardCommitBody,
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any]:
        _auth(authorization)
        try:
            return roamboard_import.commit(body.feed_path, body.preview_token)
        except RoamboardImportError as exc:
            raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

    @app.get("/api/import/roamboard/shadow")
    def roamboard_shadow(
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any]:
        _auth(authorization)
        try:
            return roamboard_import.latest_shadow()
        except RoamboardImportError as exc:
            raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

    @app.post("/api/import/pack/preview")
    def pack_import_preview(
        body: PackImportPreviewBody,
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any]:
        _auth(authorization)
        try:
            return pack_import.preview(body.domain, body.mapping_id, body.source_path)
        except PackImportError as exc:
            raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

    @app.post("/api/import/pack/commit")
    def pack_import_commit(
        body: PackImportCommitBody,
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any]:
        _auth(authorization)
        try:
            return pack_import.commit(
                body.domain, body.mapping_id, body.source_path, body.preview_token
            )
        except PackImportError as exc:
            raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

    @app.get("/api/import/pack/{domain}/mappings")
    def pack_import_mappings(
        domain: str,
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any]:
        _auth(authorization)
        return {"mappings": pack_import.declarations(domain)}

    @app.get("/sources", response_class=HTMLResponse)
    def sources_page() -> HTMLResponse:
        """No-terminal 'Add a source' page (bolt existing notes onto foundries)."""
        from domain_foundry_core.api.sources_page import SOURCES_HTML

        if not token:
            return HTMLResponse(SOURCES_HTML)
        serialized_token = json.dumps(token).replace("<", "\\u003c")
        html = SOURCES_HTML.replace(
            "</head>",
            f'<script>window.__DE_TOKEN__ = {serialized_token};</script></head>',
            1,
        )
        return HTMLResponse(html)

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

    @app.post("/api/ask")
    def ask_endpoint(
        body: dict[str, Any] = Body(...),
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any]:
        """Read-only grounded natural-language question over captured data."""
        _auth(authorization)
        question = str(body.get("question") or "").strip()
        if not question:
            raise HTTPException(status_code=422, detail="question is required")
        try:
            limit = int(body.get("limit") or 20)
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=422, detail="limit must be an integer") from exc
        try:
            return api.ask(
                question,
                domain=body.get("domain"),
                limit=limit,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/api/search")
    def search_endpoint(
        q: str,
        domain: str | None = None,
        object_type: str | None = None,
        kind: str | None = None,
        limit: int = Query(default=50, ge=1, le=500),
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any]:
        """FTS5 over raw captures and canonical object text."""
        _auth(authorization)
        try:
            return api.search(
                q,
                domain=domain,
                object_type=object_type,
                kind=kind,
                limit=limit,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/api/correct")
    def correct(
        body: CorrectBody,
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any]:
        _auth(authorization)
        try:
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
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/apply")
    def apply_ui_action(
        body: ApplyBody,
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any]:
        _auth(authorization)
        try:
            result = api.apply_ui_action(
                domain=body.domain,
                operation=body.operation,
                object_type=body.object_type,
                fields=body.fields,
                object_uid=body.object_uid,
                entry_id=body.entry_id,
            )
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if not result.get("ok"):
            raise HTTPException(status_code=400, detail=result.get("error") or "The action could not be applied.")
        return result

    @app.post("/api/entries/{entry_id}/refile")
    def refile_entry_endpoint(
        entry_id: str,
        body: dict[str, Any] = Body(...),
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any]:
        """File an unfiled entry into an installed domain."""
        _auth(authorization)
        domain = str(body.get("domain") or "").strip()
        if not domain:
            raise HTTPException(status_code=422, detail="domain is required")
        return api.refile_entry(entry_id, domain)

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
    def review_bulk_resolve(
        body: BulkResolveBody,
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any]:
        _auth(authorization)
        try:
            return api.review_resolve_bulk(
                body.approval_ids,
                decision=body.normalized_decision(),
                note=body.note,
                resolver=body.resolver,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

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

    @app.post("/api/packs/inspect")
    def packs_inspect(
        body: PackSourceBody,
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any]:
        _auth(authorization)
        return _pack_operation(lambda: api.pack_inspect(body.source))

    @app.post("/api/packs/preview")
    def packs_preview(
        body: PackSourceBody,
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any]:
        _auth(authorization)
        return _pack_operation(lambda: api.pack_preview(Path(body.source)))

    @app.post("/api/packs/install")
    def packs_install(
        body: PackInstallBody,
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any]:
        _auth(authorization)
        return _pack_operation(
            lambda: api.pack_install(Path(body.source), force=body.force)
        )

    @app.post("/api/packs/upgrade")
    def packs_upgrade(
        body: PackSourceBody,
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any]:
        _auth(authorization)
        return _pack_operation(lambda: api.pack_upgrade(Path(body.source)))

    @app.post("/api/packs/rollback")
    def packs_rollback(
        body: PackRollbackBody,
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any]:
        _auth(authorization)
        backup = Path(body.backup) if body.backup is not None else None
        return _pack_operation(lambda: api.pack_rollback(body.name, backup))

    @app.post("/api/packs/export")
    def packs_export(
        body: PackExportBody,
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any]:
        _auth(authorization)
        return _pack_operation(
            lambda: api.pack_export(body.name, Path(body.destination))
        )

    @app.post("/api/packs/uninstall")
    def packs_uninstall(
        body: PackNameBody,
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any]:
        _auth(authorization)
        return _pack_operation(lambda: api.pack_uninstall(body.name))

    @app.get("/api/export")
    def export_endpoint(
        domain: str | None = None,
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any]:
        """Secrets-free canonical data export."""
        _auth(authorization)
        try:
            return api.export_data(domain=domain)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/api/packs/activate")
    def packs_activate(
        body: ActivateBody,
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any]:
        _auth(authorization)
        return _pack_operation(lambda: api.activate_pack(body.name))

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

    @app.get("/api/attachments/{digest}")
    def attachment(
        digest: str,
        content_type: str | None = Query(default=None),
        authorization: str | None = Header(default=None),
    ) -> FileResponse:
        """Serve only content-addressed attachments referenced by a receipt."""
        _auth(authorization)
        if not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise HTTPException(status_code=404, detail="attachment not found")
        path = api.workspace.attachments_dir / digest[:2] / digest
        if not path.is_file():
            raise HTTPException(status_code=404, detail="attachment not found")
        media_type = content_type if content_type and re.fullmatch(r"[\w.+-]+/[\w.+-]+", content_type) else None
        media_type = media_type or mimetypes.guess_type(digest)[0] or "application/octet-stream"
        return FileResponse(path, media_type=media_type)

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
    def projections_drain(
        body: DrainBody | None = None,
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any]:
        _auth(authorization)
        spec = body or DrainBody()
        return api.drain_projections(adapters=spec.adapters, limit=spec.limit)

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

    @app.post("/api/quiz/start")
    def quiz_start_endpoint(
        body: QuizStartBody,
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any]:
        _auth(authorization)
        try:
            return api.quiz_start(
                user_id=body.user_id,
                limit=body.limit,
                include_grammar=body.include_grammar,
                filter_text=body.filter_text,
                new_card_limit=body.new_card_limit,
            )
        except (RuntimeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/quiz/next")
    def quiz_next_endpoint(
        domain: str = Query(default="japanese"),
        user_id: str = Query(default="default"),
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any]:
        _auth(authorization)
        if domain != "japanese":
            raise HTTPException(status_code=400, detail="This session shell has no implementation for that pack yet.")
        return api.quiz_next(user_id=user_id)

    @app.post("/api/quiz/grade")
    def quiz_grade_endpoint(
        body: QuizGradeBody,
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any]:
        _auth(authorization)
        if body.domain != "japanese":
            raise HTTPException(status_code=400, detail="This session shell has no implementation for that pack yet.")
        try:
            return api.quiz_grade(body.grade, session_id=body.session_id, user_id=body.user_id)
        except (RuntimeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/quiz/activity")
    def quiz_activity_endpoint(
        domain: str = Query(default="japanese"),
        user_id: str = Query(default="default"),
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any]:
        _auth(authorization)
        return api.quiz_activity(domain=domain, user_id=user_id)

    @app.get("/api/schedules")
    def schedules_endpoint(
        domain: str = Query(default="japanese"),
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any]:
        _auth(authorization)
        return api.schedule_status(domain=domain)

    @app.post("/api/schedules/{domain}/{schedule_id}/status")
    def schedule_status_endpoint(
        domain: str,
        schedule_id: str,
        body: ScheduleStatusBody,
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any]:
        _auth(authorization)
        try:
            return api.set_schedule_status(domain, schedule_id, body.status)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/review/{approval_id}/resolve")
    def review_resolve(
        approval_id: str,
        body: ResolveBody,
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any]:
        _auth(authorization)
        try:
            result = api.review_resolve(
                approval_id,
                decision=body.normalized_decision(),
                note=body.note,
                resolver=body.resolver,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        # resolve_approval reports an unknown id inside the receipt
        # (apply/executor.py L270–276) rather than raising — surface it as 404.
        if result.get("error") and "not found" in str(result["error"]):
            raise HTTPException(status_code=404, detail=str(result["error"]))
        return result

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
    def wizard_new_domain(
        body: WizardBody,
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any]:
        _auth(authorization)
        try:
            return api.new_domain(
                body.goal_text,
                test_drive=body.test_drive,
                release_mode=body.release,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/wizard/{session_id}/reply")
    def wizard_reply(
        session_id: str,
        body: WizardReplyBody,
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any]:
        _auth(authorization)
        try:
            result = api.wizard_reply(session_id, body.text)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        # WizardEngine.wizard_reply reports an unknown session inside the dict
        # (wizard/engine.py L63–66) — surface it as 404.
        if str(result.get("error", "")).startswith("unknown wizard session"):
            raise HTTPException(status_code=404, detail=str(result["error"]))
        return result

    # Release creation seam.  The older /api/wizard contract remains available
    # to existing adapters; the app uses this path so its copy and topic policy
    # can evolve without changing automation payloads.
    @app.post("/api/create")
    def create_start(
        body: WizardBody,
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any]:
        _auth(authorization)
        try:
            return api.create_domain(body.goal_text, test_drive=body.test_drive)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/create/{session_id}")
    def create_resume(
        session_id: str,
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any]:
        _auth(authorization)
        result = api.create_resume(session_id)
        if str(result.get("error", "")).startswith("unknown wizard session"):
            raise HTTPException(status_code=404, detail=str(result["error"]))
        return result

    @app.post("/api/create/{session_id}/reply")
    def create_reply(
        session_id: str,
        body: WizardReplyBody,
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any]:
        _auth(authorization)
        try:
            result = api.wizard_reply(session_id, body.text)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if str(result.get("error", "")).startswith("unknown wizard session"):
            raise HTTPException(status_code=404, detail=str(result["error"]))
        return result

    @app.post("/api/create/{session_id}/cancel")
    def create_cancel(
        session_id: str,
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any]:
        _auth(authorization)
        result = api.create_cancel(session_id)
        if str(result.get("error", "")).startswith("unknown wizard session"):
            raise HTTPException(status_code=404, detail=str(result["error"]))
        return result

    @app.get("/api/create/{session_id}/preview", response_model=None)
    def create_preview(
        session_id: str,
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any] | HTMLResponse:
        _auth(authorization)
        result = api.create_resume(session_id)
        if str(result.get("error", "")).startswith("unknown wizard session"):
            raise HTTPException(status_code=404, detail=str(result["error"]))
        pack = result.get("pack") or {}
        path = Path(str(pack.get("path") or "")) / "app.html"
        if path.is_file():
            return HTMLResponse(path.read_text(encoding="utf-8"))
        return {
            "available": False,
            "message": "The preview is not available yet. Your choices are saved.",
            "session_id": session_id,
        }

    @app.post("/api/domains/{domain}/hardening/preview")
    def hardening_preview(
        domain: str,
        body: HardeningBody,
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any]:
        _auth(authorization)
        try:
            return api.hardening_preview(domain, body.text)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/domains/{domain}/hardening/apply")
    def hardening_apply(
        domain: str,
        body: HardeningBody,
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any]:
        _auth(authorization)
        try:
            return api.hardening_apply(domain, body.text)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/domains/{domain}/rollback")
    def hardening_rollback(
        domain: str,
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any]:
        _auth(authorization)
        try:
            return api.hardening_rollback(domain)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/wizard/{domain}/suggest")
    def wizard_suggest(
        domain: str,
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any]:
        _auth(authorization)
        return {"suggestion": api.wizard_suggest(domain)}

    @app.post("/api/atlas/search")
    def atlas_search(
        body: AtlasSearchBody,
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any]:
        _auth(authorization)
        return api.atlas_search(body.goal, cursor_id=body.cursor_id)

    @app.get("/api/atlas/validate")
    def atlas_validate(
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any]:
        _auth(authorization)
        return api.atlas_validate()

    @app.get("/api/packs/{name}/inspect")
    def inspect_pack(
        name: str,
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any]:
        _auth(authorization)
        try:
            return api.inspect_pack(name)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/api/packs/{name}/edit")
    def apply_pack_edit(
        name: str,
        body: PackEditBody,
        authorization: str | None = Header(default=None),
    ) -> dict[str, Any]:
        _auth(authorization)
        try:
            return api.apply_pack_edit(name, body.text, confirm=body.confirm)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    dist = _app_dist()
    spa_index = dist / "index.html"
    if spa_index.is_file():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")
        notices = dist / "THIRD_PARTY_NOTICES.txt"

        @app.get("/THIRD_PARTY_NOTICES.txt", include_in_schema=False)
        def third_party_notices() -> FileResponse:
            """Expose the redistribution notices shipped beside the SPA."""
            if not notices.is_file():
                raise HTTPException(status_code=404, detail="third-party notices unavailable")
            return FileResponse(notices, media_type="text/plain; charset=utf-8")

        @app.get("/", response_model=None)
        def spa_root() -> FileResponse | HTMLResponse:
            if not token:
                return FileResponse(spa_index)
            # The browser client needs the same bearer token when the daemon
            # is deliberately exposed beyond localhost. Keep the bootstrap
            # JSON-safe even if an operator chooses an unusual token value.
            serialized_token = json.dumps(token).replace("<", "\\u003c")
            html = spa_index.read_text(encoding="utf-8")
            html = html.replace(
                "</head>",
                f'<script>window.__DE_TOKEN__ = {serialized_token};</script></head>',
                1,
            )
            return HTMLResponse(html)

        _NON_SPA_PREFIXES = {
            "api",
            "assets",
            "custom-blocks",
            "health",
            "sources",
            "docs",
            "redoc",
            "openapi.json",
            "THIRD_PARTY_NOTICES.txt",
        }

        @app.get("/{full_path:path}")
        def spa_catch_all(full_path: str) -> FileResponse:
            """Serve the SPA shell for history-API deep links."""
            head = full_path.split("/", 1)[0]
            if head in _NON_SPA_PREFIXES:
                raise HTTPException(status_code=404, detail=f"unknown path: /{full_path}")
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
                "hint": (
                    "No web app bundled with this install. Use the API and CLI, or "
                    "run from a checkout: `cd app && npm install && npm run build`. "
                    "The full read/write harness contract is served here "
                    "(ADR-006); interactive API docs at /docs."
                ),
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
