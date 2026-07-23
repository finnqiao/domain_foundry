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


if __name__ == "__main__":
    app()
