"""domain-expert CLI: init, capture, query, health, serve, pack, eval."""

from __future__ import annotations

import json
from pathlib import Path

import typer

from domain_expert_core import __version__
from domain_expert_core.api.app import run_server
from domain_expert_core.api.harness import HarnessAPI
from domain_expert_core.paths import ENV_HOME, default_home

app = typer.Typer(
    name="domain-expert",
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
        help="Workspace root (default: ~/.domain_expert)",
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
        None, "--token", envvar="DOMAIN_EXPERT_API_TOKEN"
    ),
) -> None:
    """Run local FastAPI daemon (API + future SPA)."""
    run_server(ctx.obj["home"], host=host, port=port, api_token=token)


@app.command("eval")
def eval_cmd(
    ctx: typer.Context,
    cases: Path | None = typer.Option(
        None, "--cases", help="JSONL eval cases (default: synthetic routing set)"
    ),
    min_accuracy: float = typer.Option(0.9, "--min-accuracy"),
) -> None:
    """Replay routing eval fixtures (cassette/heuristic)."""
    api = HarnessAPI(ctx.obj["home"])
    report = api.eval_routing(cases)
    typer.echo(json.dumps(report, indent=2))
    if report["accuracy"] < min_accuracy:
        raise typer.Exit(code=1)


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


if __name__ == "__main__":
    app()
