"""domain-foundry CLI: init, capture, query, search, health, serve, pack, eval."""

from __future__ import annotations

import json
from pathlib import Path

import typer

from domain_foundry_core import __version__
from domain_foundry_core.api.app import run_server
from domain_foundry_core.api.harness import HarnessAPI
from domain_foundry_core.paths import ENV_HOME, default_home

app = typer.Typer(
    name="domain-foundry",
    help="Local-first personal agent harness — capture → structured domain data.",
    no_args_is_help=True,
)
pack_app = typer.Typer(help="Manage Domain Packs")
app.add_typer(pack_app, name="pack")
mesh_app = typer.Typer(help="Domain mesh (Concierge / Experts / Supervisor)")
app.add_typer(mesh_app, name="mesh")


def _home(home: Path | None) -> Path:
    return (home or default_home()).expanduser().resolve()


@app.callback()
def main(
    ctx: typer.Context,
    home: Path | None = typer.Option(
        None,
        "--home",
        envvar=ENV_HOME,
        help="Workspace root (default: ~/.domain_foundry)",
    ),
) -> None:
    ctx.ensure_object(dict)
    ctx.obj["home"] = _home(home)


@app.command("version")
def version_cmd() -> None:
    """Print package version."""
    typer.echo(__version__)


@app.command("init")
def init_cmd(ctx: typer.Context) -> None:
    """Create workspace layout and apply substrate migrations."""
    home: Path = ctx.obj["home"]
    api = HarnessAPI(home)
    versions = api.init()
    typer.echo(f"Initialized {home}")
    typer.echo(f"  ledger.sqlite  schema_version={versions['ledger']}")
    typer.echo(f"  domains.sqlite schema_version={versions['domains']}")


@app.command("capture")
def capture_cmd(
    ctx: typer.Context,
    text: str = typer.Argument(..., help="Capture text"),
    channel: str = typer.Option("cli", "--channel", "-c"),
    source_ref: str | None = typer.Option(None, "--source-ref", "-s"),
) -> None:
    """Capture text into the ledger (capture-first, then route)."""
    api = HarnessAPI(ctx.obj["home"])
    receipt = api.capture(text, channel=channel, source_ref=source_ref)
    typer.echo(json.dumps(receipt.model_dump(), indent=2))


@app.command("query")
def query_cmd(
    ctx: typer.Context,
    domain: str | None = typer.Option(None, "--domain", "-d"),
    object_type: str | None = typer.Option(None, "--object-type", "-t"),
    status: str | None = typer.Option(None, "--status"),
    q: str | None = typer.Option(None, "--q", help="FTS5 query"),
    limit: int = typer.Option(50, "--limit", "-n"),
) -> None:
    """Query entries (read-only)."""
    api = HarnessAPI(ctx.obj["home"])
    rows = api.query(
        domain=domain, object_type=object_type, status=status, q=q, limit=limit
    )
    typer.echo(json.dumps([r.model_dump() for r in rows], indent=2))


@app.command("search")
def search_cmd(
    ctx: typer.Context,
    q: str = typer.Argument(..., help="FTS5 search query"),
    domain: str | None = typer.Option(None, "--domain", "-d"),
    object_type: str | None = typer.Option(None, "--object-type", "-t"),
    kind: str | None = typer.Option(
        None, "--kind", "-k", help="entry | canonical (default: both)"
    ),
    limit: int = typer.Option(50, "--limit", "-n"),
) -> None:
    """Full-text search over entry raw text and canonical object text."""
    api = HarnessAPI(ctx.obj["home"])
    result = api.search(
        q, domain=domain, object_type=object_type, kind=kind, limit=limit
    )
    typer.echo(json.dumps(result, indent=2))


@app.command("health")
def health_cmd(ctx: typer.Context) -> None:
    """Integrity + FK checks and entry counts."""
    api = HarnessAPI(ctx.obj["home"])
    report = api.health()
    typer.echo(json.dumps(report.model_dump(), indent=2))
    raise typer.Exit(code=0 if report.ok else 1)


@app.command("serve")
def serve_cmd(
    ctx: typer.Context,
    host: str = typer.Option("127.0.0.1", "--host"),
    port: int = typer.Option(8787, "--port", "-p"),
    token: str | None = typer.Option(
        None, "--token", envvar="DOMAIN_FOUNDRY_API_TOKEN"
    ),
) -> None:
    """Run local FastAPI daemon (API + future SPA)."""
    run_server(ctx.obj["home"], host=host, port=port, api_token=token)


eval_app = typer.Typer(
    help="Replay eval corpus, scorecards, baselines, backfill, export",
    invoke_without_command=True,
    no_args_is_help=False,
)
app.add_typer(eval_app, name="eval")


@eval_app.callback()
def eval_main(
    ctx: typer.Context,
    cases: Path | None = typer.Option(
        None, "--cases", help="JSONL eval cases (default: synthetic routing set)"
    ),
    min_accuracy: float = typer.Option(0.9, "--min-accuracy"),
    full: bool = typer.Option(
        False, "--full", help="Full scorecards + regression diff vs baseline"
    ),
    live_llm: bool = typer.Option(
        False, "--live-llm", help="Re-record cassettes against the live model + report drift"
    ),
    update_baseline: bool = typer.Option(
        False, "--update-baseline", help="Rewrite the committed baseline snapshot and exit"
    ),
    no_baseline: bool = typer.Option(
        False, "--no-baseline", help="Skip the regression diff (report scores only)"
    ),
) -> None:
    """Replay the eval corpus (cassette replay by default).

    With no subcommand this runs the corpus. `--full` prints per-pack
    scorecards and fails on any regression vs the committed baseline.
    """
    if ctx.invoked_subcommand is not None:
        return
    api = HarnessAPI(ctx.obj["home"])

    if update_baseline:
        result = api.eval_update_baseline(cases)
        typer.echo(json.dumps(result, indent=2))
        return

    if not full and not live_llm:
        report = api.eval_routing(cases)
        typer.echo(json.dumps(report, indent=2))
        if report["accuracy"] < min_accuracy:
            raise typer.Exit(code=1)
        return

    report = api.eval_full(
        cases,
        live_llm=live_llm,
        use_baseline=not no_baseline,
    )
    typer.echo(json.dumps(report, indent=2))
    failed = False
    if report["accuracy"] < min_accuracy:
        typer.echo(f"accuracy {report['accuracy']:.3f} < {min_accuracy}", err=True)
        failed = True
    if not no_baseline and report.get("regression", {}).get("has_regression"):
        typer.echo("eval regression vs baseline detected", err=True)
        failed = True
    if report["cassette"].get("drift_count"):
        typer.echo(
            f"cassette drift: {report['cassette']['drift_count']} prompt(s) changed",
            err=True,
        )
    if failed:
        raise typer.Exit(code=1)


@eval_app.command("backfill")
def eval_backfill_cmd(
    ctx: typer.Context,
    dry_run: bool = typer.Option(False, "--dry-run", help="Report without writing"),
) -> None:
    """Backfill eval_case rows from pre-P3 corrections (plan §10.1)."""
    api = HarnessAPI(ctx.obj["home"])
    typer.echo(json.dumps(api.eval_backfill(dry_run=dry_run), indent=2))


@eval_app.command("export")
def eval_export_cmd(
    ctx: typer.Context,
    out: Path = typer.Option(..., "--out", "-o", help="Destination JSONL path"),
    sanitize: bool = typer.Option(
        True, "--sanitize/--no-sanitize", help="Strip PII/secrets for contribution"
    ),
    source: str | None = typer.Option(
        "correction", "--source", help="eval_case source filter (blank = all)"
    ),
) -> None:
    """Export sanitized eval cases for community contribution (plan §10.4)."""
    api = HarnessAPI(ctx.obj["home"])
    report = api.eval_export(out, sanitize=sanitize, source=source or None)
    typer.echo(json.dumps(report, indent=2))


@app.command("correct")
def correct_cmd(
    ctx: typer.Context,
    text: str | None = typer.Argument(None, help="Natural-language correction"),
    entry_id: str | None = typer.Option(None, "--entry-id"),
    object_uid: str | None = typer.Option(None, "--object-uid"),
    action: str | None = typer.Option(
        None, "--action", help="amend|move|merge|undo|mark_wrong"
    ),
    merge_into: str | None = typer.Option(None, "--merge-into"),
    domain: str | None = typer.Option(None, "--domain", help="Target domain for move"),
) -> None:
    """Apply a one-message correction (NL or explicit)."""
    api = HarnessAPI(ctx.obj["home"])
    receipt = api.correct(
        text=text,
        entry_id=entry_id,
        object_uid=object_uid,
        action=action,
        merge_into_uid=merge_into,
        target_domain=domain,
    )
    typer.echo(json.dumps(receipt, indent=2))
    if receipt.get("error"):
        raise typer.Exit(code=1)


review_app = typer.Typer(help="Approval queue")
app.add_typer(review_app, name="review")


@review_app.command("list")
def review_list_cmd(
    ctx: typer.Context,
    status: str = typer.Option("pending", "--status"),
    domain: str | None = typer.Option(None, "--domain"),
) -> None:
    api = HarnessAPI(ctx.obj["home"])
    typer.echo(json.dumps(api.review_list(status=status, domain=domain), indent=2))


@review_app.command("resolve")
def review_resolve_cmd(
    ctx: typer.Context,
    approval_id: str = typer.Argument(...),
    decision: str = typer.Option(..., "--decision", "-d", help="approved|denied|expired"),
    note: str | None = typer.Option(None, "--note"),
) -> None:
    api = HarnessAPI(ctx.obj["home"])
    receipt = api.review_resolve(approval_id, decision=decision, note=note)
    typer.echo(json.dumps(receipt, indent=2))
    if receipt.get("error"):
        raise typer.Exit(code=1)


@review_app.command("stats")
def review_stats_cmd(
    ctx: typer.Context,
    domain: str | None = typer.Option(None, "--domain"),
) -> None:
    """SLO counters: pending, overdue, oldest pending age."""
    api = HarnessAPI(ctx.obj["home"])
    typer.echo(json.dumps(api.review_stats(domain=domain), indent=2))


projections_app = typer.Typer(help="Projection coordinator (outbox drain)")
app.add_typer(projections_app, name="projections")


@projections_app.command("drain")
def projections_drain_cmd(ctx: typer.Context) -> None:
    """Drain the projection outbox until convergence (markdown + app feeds)."""
    api = HarnessAPI(ctx.obj["home"])
    typer.echo(json.dumps(api.drain_projections(), indent=2))


@projections_app.command("status")
def projections_status_cmd(
    ctx: typer.Context,
    entry_id: str | None = typer.Option(None, "--entry-id"),
    change_request_id: int | None = typer.Option(None, "--change-request-id"),
) -> None:
    """Report projection convergence (pending|refreshed) for an entry / CR."""
    api = HarnessAPI(ctx.obj["home"])
    typer.echo(
        json.dumps(
            api.projection_status(
                entry_id=entry_id, change_request_id=change_request_id
            ),
            indent=2,
        )
    )


@projections_app.command("reproject")
def projections_reproject_cmd(
    ctx: typer.Context,
    vault: Path = typer.Option(
        ...,
        "--vault",
        help="Target Obsidian vault root (use a snapshot/copy; never clobber live without review)",
    ),
    apply: bool = typer.Option(
        False,
        "--apply",
        help="Write managed regions (default: dry-run diff only)",
    ),
    domain: list[str] | None = typer.Option(
        None,
        "--domain",
        "-d",
        help="Limit to domain(s); repeatable. Default: all installed packs.",
    ),
    markdown: bool = typer.Option(
        False,
        "--markdown",
        help="Emit markdown summary instead of JSON",
    ),
) -> None:
    """Re-project vault notes (managed regions only). Dry-run by default."""
    api = HarnessAPI(ctx.obj["home"])
    report = api.reproject_vault(
        vault,
        apply=apply,
        domains=list(domain) if domain else None,
    )
    if markdown:
        typer.echo(report.get("_markdown") or "")
        payload = {k: v for k, v in report.items() if k != "_markdown"}
        if not payload.get("totals", {}).get("unmanaged_ok", True):
            raise typer.Exit(code=2)
        if apply and not payload.get("applied"):
            raise typer.Exit(code=2)
        return
    typer.echo(json.dumps({k: v for k, v in report.items() if k != "_markdown"}, indent=2))
    if not report.get("totals", {}).get("unmanaged_ok", True):
        raise typer.Exit(code=2)
    if apply and not report.get("applied"):
        raise typer.Exit(code=2)


@pack_app.command("list")
def pack_list_cmd(ctx: typer.Context) -> None:
    api = HarnessAPI(ctx.obj["home"])
    typer.echo(json.dumps(api.pack_list(), indent=2))


@pack_app.command("validate")
def pack_validate_cmd(
    ctx: typer.Context,
    name: str | None = typer.Argument(None),
) -> None:
    api = HarnessAPI(ctx.obj["home"])
    errors = api.pack_validate(name)
    if errors:
        for e in errors:
            typer.echo(e, err=True)
        raise typer.Exit(code=1)
    typer.echo("OK")


@pack_app.command("add")
def pack_add_cmd(
    ctx: typer.Context,
    src: Path = typer.Argument(..., exists=True, file_okay=False),
    force: bool = typer.Option(False, "--force"),
) -> None:
    api = HarnessAPI(ctx.obj["home"])
    info = api.pack_add(src, force=force)
    typer.echo(json.dumps(info, indent=2))


@pack_app.command("new")
def pack_new_cmd(
    ctx: typer.Context,
    name: str = typer.Argument(...),
) -> None:
    api = HarnessAPI(ctx.obj["home"])
    info = api.pack_new(name)
    typer.echo(json.dumps(info, indent=2))


@app.command("new-domain")
def new_domain_cmd(
    ctx: typer.Context,
    goal: str = typer.Argument(..., help="Plain-language goal, e.g. 'track my sourdough journey'"),
    reply: list[str] = typer.Option(
        [], "--reply", "-r", help="Scripted wizard replies (repeatable): interview answers, sample captures, edits"
    ),
    test_drive: int = typer.Option(5, "--test-drive", help="Test-drive capture budget"),
) -> None:
    """Guided domain creation (plan §6). Prints each wizard turn as JSON.

    With no --reply, prints the proposal + interview questions and pauses. Pass
    --reply 'skip' to accept defaults and generate, then more --reply values to
    test-drive or harden the domain.
    """
    api = HarnessAPI(ctx.obj["home"])
    turn = api.new_domain(goal, test_drive=test_drive)
    typer.echo(json.dumps(turn, indent=2, ensure_ascii=False))
    session_id = turn["session_id"]
    for text in reply:
        turn = api.wizard_reply(session_id, text)
        typer.echo(json.dumps(turn, indent=2, ensure_ascii=False))


wizard_app = typer.Typer(help="Resume / drive domain-creation wizard sessions")
app.add_typer(wizard_app, name="wizard")


@wizard_app.command("reply")
def wizard_reply_cmd(
    ctx: typer.Context,
    session_id: str = typer.Argument(...),
    text: str = typer.Argument(...),
) -> None:
    """Send one reply to an existing wizard session."""
    api = HarnessAPI(ctx.obj["home"])
    turn = api.wizard_reply(session_id, text)
    typer.echo(json.dumps(turn, indent=2, ensure_ascii=False))


@wizard_app.command("suggest")
def wizard_suggest_cmd(
    ctx: typer.Context,
    domain: str = typer.Argument(...),
) -> None:
    """Show a repeated-correction hardening suggestion for a domain (§8.4)."""
    api = HarnessAPI(ctx.obj["home"])
    typer.echo(json.dumps(api.wizard_suggest(domain), indent=2, ensure_ascii=False))


@mesh_app.command("register")
def mesh_register_cmd(
    ctx: typer.Context,
    domain: str = typer.Argument(..., help="Installed pack/domain to register as Expert"),
    spawn: bool = typer.Option(
        False, "--spawn", help="Also spawn Expert if supervise loop is running"
    ),
) -> None:
    """Hot-register an Expert child config with the Supervisor (launchd stubbed)."""
    api = HarnessAPI(ctx.obj["home"])
    api.init()
    result = api.register_expert(domain, spawn=spawn)
    typer.echo(json.dumps(result, indent=2, ensure_ascii=False))
    if not result.get("registered"):
        raise typer.Exit(code=1)


@mesh_app.command("status")
def mesh_status_cmd(ctx: typer.Context) -> None:
    """One-glance mesh health: journal counts, inbox depths, child state."""
    from dataclasses import asdict

    from domain_foundry_core.mesh.supervisor import Supervisor
    from domain_foundry_core.paths import Workspace

    supervisor = Supervisor(Workspace(ctx.obj["home"]))
    status = supervisor.status()
    typer.echo(json.dumps(asdict(status), indent=2))


dlq_app = typer.Typer(help="Dead-letter queue: list / retry poisoned mesh messages")
mesh_app.add_typer(dlq_app, name="dlq")


@dlq_app.command("list")
def mesh_dlq_list_cmd(
    ctx: typer.Context,
    domain: str | None = typer.Option(None, "--domain", "-d"),
    queue: str | None = typer.Option(
        None, "--queue", "-q", help="inbox | outbound (default: both)"
    ),
    limit: int = typer.Option(100, "--limit", "-n"),
    include_failed: bool = typer.Option(
        True, "--include-failed/--dead-only", help="Include inbox failed rows"
    ),
) -> None:
    """List dead-letter (and optionally failed) inbox/outbound messages."""
    from domain_foundry_core.mesh.observability import DeadLetterQueue
    from domain_foundry_core.paths import Workspace

    if queue is not None and queue not in {"inbox", "outbound"}:
        typer.echo("queue must be inbox or outbound", err=True)
        raise typer.Exit(code=2)
    dlq = DeadLetterQueue(Workspace(ctx.obj["home"]))
    entries = dlq.list(
        domain=domain,
        queue=queue,  # type: ignore[arg-type]
        limit=limit,
        include_failed=include_failed,
    )
    typer.echo(json.dumps([e.to_dict() for e in entries], indent=2))


@dlq_app.command("retry")
def mesh_dlq_retry_cmd(
    ctx: typer.Context,
    msg_id: str = typer.Argument(..., help="Dead-letter message id"),
) -> None:
    """Requeue a dead/failed inbox or dead outbound message as pending."""
    from domain_foundry_core.mesh.observability import DeadLetterQueue
    from domain_foundry_core.paths import Workspace

    dlq = DeadLetterQueue(Workspace(ctx.obj["home"]))
    entry = dlq.retry(msg_id)
    if entry is None:
        typer.echo(json.dumps({"error": "not found or not retryable", "id": msg_id}))
        raise typer.Exit(code=1)
    typer.echo(json.dumps(entry.to_dict(), indent=2))


@mesh_app.command("install")
def mesh_install_cmd(
    ctx: typer.Context,
    dry_run: bool = typer.Option(
        True, "--dry-run/--apply", help="Print plist stubs (default); apply is TODO"
    ),
) -> None:
    """Generate launchd plists for Concierge + Supervisor (max 2).

    TODO(mesh): write plists under ~/Library/LaunchAgents and launchctl load.
    Foundation only prints stubs.
    """
    from domain_foundry_core.mesh.supervisor import generate_launchd_plist_stub
    from domain_foundry_core.paths import Workspace

    home = ctx.obj["home"]
    ws = Workspace(home)
    concierge = generate_launchd_plist_stub(
        label="ai.domainfoundry.mesh.concierge",
        program_args=["domain-foundry", "--home", str(ws.home), "mesh", "concierge"],
        home=ws.home,
    )
    supervisor = generate_launchd_plist_stub(
        label="ai.domainfoundry.mesh.supervisor",
        program_args=["domain-foundry", "--home", str(ws.home), "mesh", "supervise"],
        home=ws.home,
    )
    typer.echo("# TODO: mesh install — launchd write/load not implemented yet")
    typer.echo("# --- concierge.plist ---")
    typer.echo(concierge)
    typer.echo("# --- supervisor.plist ---")
    typer.echo(supervisor)
    if not dry_run:
        typer.echo(
            "apply requested but install wiring is stubbed; use --dry-run",
            err=True,
        )
        raise typer.Exit(code=1)


@mesh_app.command("concierge")
def mesh_concierge_cmd(
    ctx: typer.Context,
    once: bool = typer.Option(False, "--once", help="Drain pending journal once and exit"),
) -> None:
    """Run the Concierge drain loop (foundation: one-shot or poll)."""
    import time

    from domain_foundry_core.mesh.concierge import Concierge
    from domain_foundry_core.paths import Workspace

    concierge = Concierge(Workspace(ctx.obj["home"]))
    if once:
        results = concierge.drain()
        typer.echo(json.dumps([r.__dict__ for r in results], indent=2))
        return
    typer.echo("concierge polling (Ctrl-C to stop)")
    try:
        while True:
            concierge.drain()
            time.sleep(0.2)
    except KeyboardInterrupt:
        typer.echo("stopped")


@mesh_app.command("supervise")
def mesh_supervise_cmd(
    ctx: typer.Context,
    domain: list[str] = typer.Option(
        ["japanese", "food"], "--domain", "-d", help="Expert domains to supervise"
    ),
) -> None:
    """Start Supervisor monitoring Expert children (foundation skeleton)."""
    import time

    from domain_foundry_core.mesh.supervisor import Supervisor
    from domain_foundry_core.paths import Workspace

    supervisor = Supervisor(Workspace(ctx.obj["home"]), domains=list(domain))
    supervisor.start_all()
    typer.echo(json.dumps({"started": list(domain), "home": str(ctx.obj["home"])}))
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        supervisor.stop_all()
        typer.echo("stopped")


# ---------------------------------------------------------------------------
# Roamboard sync (Phase 7 — shadow-ready; no production cutover)
# ---------------------------------------------------------------------------
roamboard_app = typer.Typer(
    help="Roamboard sync adapter (import feed/patches; shadow vs travel.sqlite RO)",
)
app.add_typer(roamboard_app, name="roamboard")


@roamboard_app.command("sync")
def roamboard_sync_cmd(
    ctx: typer.Context,
    dry_run: bool = typer.Option(
        True,
        "--dry-run/--no-dry-run",
        help="Reconcile without writing (default). Superseded by --apply / --shadow.",
    ),
    apply: bool = typer.Option(
        False,
        "--apply",
        help="Write Roamboard-shaped records into DF travel (idempotent source_ref).",
    ),
    shadow: bool = typer.Option(
        False,
        "--shadow",
        help="Dry-run import accounting + write shadow/roamboard/ diff vs travel.sqlite RO.",
    ),
    feed: Path | None = typer.Option(
        None, "--feed", help="Roamboard feed JSON (schemaVersion 2)"
    ),
    patch_bundle: Path | None = typer.Option(
        None, "--patch-bundle", help="Pending-patch bundle JSON (drain shape)"
    ),
    travel_db: Path | None = typer.Option(
        None,
        "--travel-db",
        help="Private travel.sqlite for shadow (opened RO; default HermesWorkspace path)",
    ),
) -> None:
    """Import Roamboard shapes into DomainFoundry travel (shadow-ready).

    Default is --dry-run. --apply writes. --shadow writes a report under
    ``{DF_HOME}/shadow/roamboard/`` comparing private travel.sqlite (RO) to DF.
    Does not mutate travel.sqlite or flip launchd sync jobs.
    """
    from domain_foundry_roamboard.sync import SyncMode, sync_roamboard

    if apply and shadow:
        typer.echo("use either --apply or --shadow (not both)", err=True)
        raise typer.Exit(code=2)
    if apply:
        mode = SyncMode.APPLY
    elif shadow:
        mode = SyncMode.SHADOW
    else:
        mode = SyncMode.DRY_RUN
        if not dry_run:
            # --no-dry-run without --apply is ambiguous; require --apply.
            typer.echo("pass --apply to write (dry-run is the default)", err=True)
            raise typer.Exit(code=2)

    if feed is None and patch_bundle is None:
        typer.echo("provide --feed and/or --patch-bundle", err=True)
        raise typer.Exit(code=2)

    # Prefer feed when both given (patch can be run as a second invocation).
    report = sync_roamboard(
        ctx.obj["home"],
        mode=mode,
        feed=feed,
        patch_bundle=None if feed is not None else patch_bundle,
        travel_db=travel_db,
    )
    typer.echo(json.dumps(report.to_dict(), indent=2, default=str))
    import_report = report.import_report or {}
    if not import_report.get("complete", True):
        raise typer.Exit(code=1)


@roamboard_app.command("export-feed")
def roamboard_export_feed_cmd(
    ctx: typer.Context,
    out: Path | None = typer.Option(
        None, "--out", "-o", help="Write JSON feed preview (default: stdout)"
    ),
) -> None:
    """Build a Roamboard-shaped feed from DF travel (push preview; does not POST)."""
    from domain_foundry_roamboard.sync import export_df_feed

    feed_payload = export_df_feed(ctx.obj["home"])
    text = json.dumps(feed_payload, indent=2) + "\n"
    if out is not None:
        out = out.expanduser()
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")
        typer.echo(json.dumps({"wrote": str(out), "trips": len(feed_payload.get("trips") or [])}))
    else:
        typer.echo(text)


if __name__ == "__main__":
    app()
