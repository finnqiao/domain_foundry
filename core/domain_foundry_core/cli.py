"""domain-foundry CLI: init, capture, query, search, health, serve, pack, eval."""

from __future__ import annotations

import json
import os
from pathlib import Path

import typer

from domain_foundry_core import __version__
from domain_foundry_core.api.app import run_server
from domain_foundry_core.api.harness import HarnessAPI
from domain_foundry_core.ingest import ingest as ingest_source
from domain_foundry_core.paths import ENV_HOME, default_home
from domain_foundry_core.wizard.release import field_label, job_label

app = typer.Typer(
    name="domain-foundry",
    help="Research an interest and compile an evidence-backed local application.",
    no_args_is_help=True,
)
pack_app = typer.Typer(help="Manage Domain Packs")
app.add_typer(pack_app, name="pack")
mesh_app = typer.Typer(help="[EXPERIMENTAL] Domain mesh (Concierge / Experts / Supervisor)")
app.add_typer(mesh_app, name="mesh")
foundry_app = typer.Typer(help="Compile evidence-backed FoundrySpec applications")
app.add_typer(foundry_app, name="foundry")


@mesh_app.callback()
def mesh_main() -> None:
    """Domain mesh commands — EXPERIMENTAL.

    The durable substrate (journal, inboxes, outbound, DLQ) is tested, but
    expert processes do not run under launchd (`mesh install` is stubbed) and
    registration persists config only. Behavior flags are default-conservative:
    see core/domain_foundry_core/mesh/flags.py.
    """
    typer.secho(
        "EXPERIMENTAL: mesh registration is config-only — expert processes are "
        "not running and launchd install is stubbed.",
        err=True,
        fg=typer.colors.YELLOW,
    )


def _home(home: Path | None) -> Path:
    return (home or default_home()).expanduser().resolve()


def _drain_quietly(api: HarnessAPI) -> None:
    """Best-effort projection drain so CLI writes show up in the app immediately."""
    try:
        api.drain_projections()
    except Exception:  # noqa: BLE001 — canonical commit already durable
        pass


def _heldout_suite_path() -> Path:
    """Locate the wizard acceptance corpus in a checkout or installed wheel."""
    relative = Path("examples") / "heldout" / "wizard_hobby_suite.jsonl"
    checkout = Path(__file__).resolve().parents[2] / relative
    packaged = Path(__file__).resolve().parent / relative
    return checkout if checkout.is_file() else packaged


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


@app.command("setup")
def setup_cmd(
    ctx: typer.Context,
    provider: str | None = typer.Option(
        None,
        "--provider",
        help="Provider id (anthropic, openai, deepseek, openrouter, local, none)",
    ),
    routine: str | None = typer.Option(
        None, "--routine", help="Model for the high-volume routing/extraction tier"
    ),
    sota: str | None = typer.Option(
        None, "--sota", help="Model for corrections / schema-affecting calls"
    ),
    api_key_env: str | None = typer.Option(
        None, "--api-key-env", help="Env var that holds your key (not the key itself)"
    ),
    store_key: bool = typer.Option(
        False,
        "--store-key",
        help="Write the key into config.toml (chmod 0600). Default: reference the env var only.",
    ),
    non_interactive: bool = typer.Option(
        False, "--non-interactive", "-y", help="Ask nothing; take flags and env as given"
    ),
    probe: bool = typer.Option(
        True, "--probe/--no-probe", help="Make one cheap live call per tier to verify"
    ),
    show: bool = typer.Option(
        False, "--show", help="Print the resolved config (keys redacted) and exit"
    ),
) -> None:
    """Bring your own key: pick a provider and models, then pick where to start.

    Run it bare for the guided path. Pass flags (or `--show`) if you already
    know what you want — environment variables keep overriding everything, so an
    expert setup that lives in a dotfile needs no config file at all.
    """
    from domain_foundry_core.config import save_llm_config
    from domain_foundry_core.llm.providers import all_providers, get_provider
    from domain_foundry_core.onboarding import (
        NEXT_STEPS,
        build_config,
        detect_env_keys,
        is_already_configured,
        probe_tier,
        resolved_status,
        suggest_provider,
    )

    home: Path = ctx.obj["home"]

    if show:
        typer.echo(json.dumps(resolved_status(home), indent=2))
        return

    interactive = not non_interactive
    detected = detect_env_keys()

    # ---- provider -------------------------------------------------------
    spec = get_provider(provider)
    if spec is None and provider:
        typer.secho(
            f"unknown provider {provider!r}; expected one of "
            f"{', '.join(p.id for p in all_providers())}",
            err=True,
            fg=typer.colors.RED,
        )
        raise typer.Exit(code=2)

    if spec is None and not interactive:
        spec = suggest_provider()
        if spec is None:
            typer.secho(
                "no provider given and no known API key in the environment. "
                "Pass --provider, or run `domain-foundry setup` interactively.",
                err=True,
                fg=typer.colors.RED,
            )
            raise typer.Exit(code=2)

    if spec is None:
        typer.echo("Domain Foundry needs a model to route captures. You bring the key.\n")
        if detected:
            for d in detected:
                typer.echo(f"  found {d.env_name} in your environment ({d.label})")
            typer.echo("")
        options = list(all_providers())
        for i, opt in enumerate(options, start=1):
            marker = "*" if any(d.provider_id == opt.id for d in detected) else " "
            typer.echo(f" {marker}{i}. {opt.label}")
            if opt.notes:
                typer.echo(f"      {opt.notes}")
        suggested = suggest_provider()
        default_idx = (
            next((i for i, o in enumerate(options, 1) if o.id == suggested.id), 1)
            if suggested
            else 1
        )
        choice = typer.prompt("\nWhich provider?", default=str(default_idx))
        picked = get_provider(choice)
        if picked is None:
            try:
                picked = options[int(choice) - 1]
            except (ValueError, IndexError):
                typer.secho(f"not a valid choice: {choice!r}", err=True, fg=typer.colors.RED)
                raise typer.Exit(code=2) from None
        spec = picked

    # ---- key ------------------------------------------------------------
    api_key: str | None = None
    if spec.needs_key:
        env_hit = next((d for d in detected if d.provider_id == spec.id), None)
        if api_key_env is None and env_hit is not None:
            api_key_env = env_hit.env_name
            if interactive:
                typer.echo(f"\nUsing the key in ${api_key_env}.")
        elif api_key_env is None and interactive:
            typer.echo(f"\nNo key found for {spec.label}.")
            if spec.signup_url:
                typer.echo(f"Get one at {spec.signup_url}")
            entered = typer.prompt(
                "Paste your key (or press enter to name an env var instead)",
                default="",
                hide_input=True,
                show_default=False,
            ).strip()
            if entered:
                api_key = entered
                api_key_env = spec.canonical_key_env or (
                    spec.api_key_envs[0] if spec.api_key_envs else None
                )
                if not store_key:
                    store_key = typer.confirm(
                        f"Store the key in {home / 'config.toml'} (chmod 0600)? "
                        "Otherwise export it yourself before capturing",
                        default=False,
                    )
            else:
                api_key_env = (
                    typer.prompt(
                        "Which env var holds it?",
                        default=spec.canonical_key_env
                        or (spec.api_key_envs[0] if spec.api_key_envs else ""),
                    ).strip()
                    or None
                )

    # ---- models ---------------------------------------------------------
    if interactive and spec.id != "none":
        typer.echo("")
        typer.echo("Two tiers. Routine handles every capture; sota handles the calls")
        typer.echo("that rewrite a record or change a schema.")
        routine = routine or (
            typer.prompt("  routine model", default=spec.routine_model or "").strip() or None
        )
        sota = sota or (typer.prompt("  sota model", default=spec.sota_model or "").strip() or None)

    cfg = build_config(
        provider_id=spec.id,
        routine_model=routine,
        sota_model=sota,
        api_key_env=api_key_env,
        api_key=api_key,
    )
    path = save_llm_config(cfg, home, store_keys=store_key and bool(api_key))
    typer.echo(f"\nWrote {path}")
    if api_key and not store_key:
        env_hint = api_key_env or "DOMAIN_FOUNDRY_SOTA_API_KEY"
        typer.secho(
            f"  key not stored — export {env_hint} before capturing",
            fg=typer.colors.YELLOW,
        )

    # ---- probe ----------------------------------------------------------
    if probe and spec.id != "none":
        # Put the key on the environment for this process so the probe sees it
        # even when the user chose not to persist it.
        if api_key and api_key_env:
            os.environ.setdefault(api_key_env, api_key)
        typer.echo("\nChecking each tier can reach its model:")
        failed = False
        for tier in ("routine", "sota"):
            result = probe_tier(tier, home=home, config=cfg)
            colour = typer.colors.GREEN if result.ok else typer.colors.RED
            typer.secho(
                f"  {tier:<8} {result.model or '(none)':<28} {result.symbol} — {result.detail}",
                fg=colour,
            )
            failed = failed or not result.ok
        if failed:
            typer.secho(
                "\nAt least one tier is not reachable. Captures will still be kept, but "
                "routing falls back to keyword rules until this is fixed.",
                fg=typer.colors.YELLOW,
            )

    # ---- workspace + what next -----------------------------------------
    api = HarnessAPI(home)
    api.init()
    typer.echo(f"\nWorkspace ready at {home}")

    if not interactive:
        if not is_already_configured(home):
            typer.secho(
                "note: no key resolved for at least one tier", err=True, fg=typer.colors.YELLOW
            )
        return

    typer.echo("\nWhere do you want to start?\n")
    for i, (_key, label, _cmd) in enumerate(NEXT_STEPS, start=1):
        typer.echo(f"  {i}. {label}")
    typer.echo(f"  {len(NEXT_STEPS) + 1}. Nothing — I'll take it from here")
    pick = typer.prompt("\nChoice", default="1").strip()
    try:
        index = int(pick) - 1
    except ValueError:
        index = len(NEXT_STEPS)
    if not 0 <= index < len(NEXT_STEPS):
        typer.echo("\nAll set.")
        return

    key, _label, command = NEXT_STEPS[index]
    if key == "pack":
        from domain_foundry_core.packs.loader import bundled_packs_root

        # Skip scaffolding like `_template` — it is for pack *authors*, and
        # offering it as a starting point to someone who just picked a provider
        # is a dead end.
        available = sorted(
            p.name
            for p in bundled_packs_root().glob("*")
            if (p / "pack.yaml").is_file() and not p.name.startswith("_")
        )
        typer.echo(f"\nBundled packs: {', '.join(available) or '(none)'}")
        name = typer.prompt("Which one?", default="food" if "food" in available else "")
        name = name.strip()
        if name:
            info = api.pack_add(_resolve_pack_source(name))
            typer.echo(json.dumps(info, indent=2))
            typer.echo(
                f'\nNow try:  domain-foundry capture "…"   '
                f"then  domain-foundry query --domain {name}"
            )
        return

    typer.echo(f"\nRun:\n  {command}")
    if key == "import":
        typer.echo(
            "\nMapping examples live in examples/importers/. "
            "`domain-foundry import --help` explains each field."
        )


@app.command("capture")
def capture_cmd(
    ctx: typer.Context,
    text: str = typer.Argument(..., help="Capture text"),
    channel: str = typer.Option("cli", "--channel", "-c"),
    source_ref: str | None = typer.Option(None, "--source-ref", "-s"),
    as_json: bool = typer.Option(
        False, "--json", help="Emit machine JSON instead of a plain receipt"
    ),
) -> None:
    """Save text first, then file it into a passion when confident."""
    from domain_foundry_core.receipts import describe_capture_receipt

    api = HarnessAPI(ctx.obj["home"])
    receipt = api.capture(text, channel=channel, source_ref=source_ref)
    _drain_quietly(api)
    payload = receipt.model_dump()
    if payload.get("llm_error") is None:
        payload.pop("llm_error", None)
    if as_json:
        typer.echo(json.dumps(payload, indent=2))
    else:
        titles = {p.name: p.manifest.title for p in api.packs.list()}
        typer.echo(describe_capture_receipt(receipt, pack_titles=titles))
    if receipt.llm_error:
        typer.secho(
            f"warning: model routing failed ({receipt.llm_error}) — captured with "
            "keyword rules only. Check DOMAIN_FOUNDRY_ROUTINE_/SOTA_ settings.",
            err=True,
            fg=typer.colors.YELLOW,
        )


@app.command("ingest")
def ingest_cmd(
    ctx: typer.Context,
    path: Path = typer.Argument(..., help="Existing file or folder of notes/logs to pull in"),
    channel: str = typer.Option("folder-import", "--channel", "-c"),
    glob: str | None = typer.Option(None, "--glob", help="Filter files, e.g. '*.md'"),
    split: str = typer.Option(
        "file", "--split", help="file (one capture per file) | lines (append-only logs)"
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Preview routing without writing anything"
    ),
    only: str | None = typer.Option(
        None, "--only", help="Pull ONLY notes that route to this foundry; leave the rest untouched"
    ),
    limit: int | None = typer.Option(None, "--limit", "-n", help="Cap number of records"),
    watch: bool = typer.Option(
        False, "--watch", help="Keep watching the folder and pull in new notes on an interval"
    ),
    interval: float = typer.Option(30.0, "--interval", help="Seconds between --watch scans"),
) -> None:
    """Bolt existing notes/logs onto your foundries — read-only, idempotent.

    Reads files you already have and runs each through capture → route. Nothing at
    the source is moved or modified; re-runs skip already-imported entries. Use
    --dry-run first to see where notes would land, --only <foundry> to pull a mixed
    folder into a single domain context, and --watch to keep pulling in new notes.
    """
    api = HarnessAPI(ctx.obj["home"])
    if watch:
        from domain_foundry_core.ingest import watch as watch_source

        typer.echo(f"Watching {path} every {interval:g}s — Ctrl-C to stop.")
        try:
            for report in watch_source(
                api, path, interval=interval, channel=channel, glob=glob, split=split, only=only
            ):
                d = report.as_dict()
                typer.echo(
                    f"scan: +{d['captured']} new, {d['skipped_existing']} unchanged, by_domain={d['by_domain']}"
                )
        except KeyboardInterrupt:
            typer.echo("stopped.")
        return
    report = ingest_source(
        api,
        path,
        channel=channel,
        glob=glob,
        split=split,
        dry_run=dry_run,
        only=only,
        limit=limit,
    )
    typer.echo(json.dumps(report.as_dict(), indent=2))


def _parse_kv_options(values: list[str] | None, *, flag: str) -> dict[str, str]:
    """Parse repeatable ``entity=value`` options into a dict."""
    out: dict[str, str] = {}
    for raw in values or []:
        if "=" not in raw:
            typer.secho(f"{flag} expects entity=value, got {raw!r}", err=True, fg=typer.colors.RED)
            raise typer.Exit(code=2)
        entity, _, value = raw.partition("=")
        entity, value = entity.strip(), value.strip()
        if not entity or not value:
            typer.secho(f"{flag} expects entity=value, got {raw!r}", err=True, fg=typer.colors.RED)
            raise typer.Exit(code=2)
        out[entity] = value
    return out


@app.command("import")
def import_cmd(
    ctx: typer.Context,
    mapping: Path = typer.Option(
        ..., "--mapping", "-m", help="Mapping YAML/JSON: source rows → domain objects"
    ),
    sqlite: Path | None = typer.Option(
        None, "--sqlite", help="SQLite database to read (always opened read-only)"
    ),
    source_json: Path | None = typer.Option(
        None, "--json", help="JSON/JSONL file, or a directory of {entity}.jsonl files"
    ),
    table: list[str] | None = typer.Option(
        None, "--table", help="Map an entity to a table name: entity=table (repeatable)"
    ),
    where: list[str] | None = typer.Option(
        None, "--where", help="SQL filter per entity: entity=clause (repeatable)"
    ),
    order_by: list[str] | None = typer.Option(
        None, "--order-by", help="Ordering per entity: entity=expr (repeatable)"
    ),
    apply: bool = typer.Option(
        False, "--apply", help="Write records (default: dry-run reconciliation only)"
    ),
    markdown: bool = typer.Option(
        False, "--markdown", help="Emit the reconciliation as markdown instead of JSON"
    ),
    detail: bool = typer.Option(
        False, "--detail", help="Include per-record outcomes in JSON output"
    ),
) -> None:
    """Import a structured source (SQLite table, JSON/JSONL export) by mapping.

    For data that already has a schema. Free-text notes and vaults go through
    `domain-foundry ingest` instead; this is the mapping-driven path, with the
    same guarantees: **sources are opened read-only and never mutated**, re-runs
    are idempotent on `source_ref`, and every source row is accounted for as
    imported / skipped / failed so a partial import cannot pass silently.

    Dry-run is the default — it reports where every row would land and writes
    nothing. Add `--apply` once the reconciliation looks right.

    \b
    Example (SQLite, two entities in one database):
      domain-foundry import -m my_mapping.yaml --sqlite ~/old-app.sqlite \\
          --table entries=journal_entries --where entries="deleted_at IS NULL"

    \b
    Example (a JSONL export):
      domain-foundry import -m my_mapping.yaml --json ~/export/

    Mapping examples: `examples/importers/*.yaml`.
    """
    from domain_foundry_core.migrations.importers import (
        FixtureSource,
        GenericImporter,
        SqliteTableSource,
        load_mapping,
    )
    from domain_foundry_core.paths import Workspace

    if (sqlite is None) == (source_json is None):
        typer.secho("provide exactly one source: --sqlite or --json", err=True, fg=typer.colors.RED)
        raise typer.Exit(code=2)

    mapping_path = mapping.expanduser()
    if not mapping_path.is_file():
        typer.secho(f"no mapping file at {mapping_path}", err=True, fg=typer.colors.RED)
        raise typer.Exit(code=2)
    try:
        mapping_config = load_mapping(mapping_path)
    except Exception as exc:
        typer.secho(f"invalid mapping: {exc}", err=True, fg=typer.colors.RED)
        raise typer.Exit(code=2) from exc

    try:
        if sqlite is not None:
            source = SqliteTableSource(
                sqlite.expanduser(),
                tables=_parse_kv_options(table, flag="--table"),
                where=_parse_kv_options(where, flag="--where"),
                order_by=_parse_kv_options(order_by, flag="--order-by"),
            )
        else:
            assert source_json is not None
            source = FixtureSource(source_json.expanduser())
    except FileNotFoundError as exc:
        typer.secho(str(exc), err=True, fg=typer.colors.RED)
        raise typer.Exit(code=2) from exc

    importer = GenericImporter(Workspace(ctx.obj["home"]), mapping_config, dry_run=not apply)
    report = importer.run(source)

    if markdown:
        typer.echo(report.to_markdown())
    else:
        payload = report.to_dict()
        if not detail:
            payload.pop("outcomes", None)
        typer.echo(json.dumps(payload, indent=2, default=str))

    if not report.complete:
        typer.secho(
            f"reconciliation incomplete: {report.accounted_for}/{report.source_total} "
            f"rows accounted for, {report.failed} failed",
            err=True,
            fg=typer.colors.RED,
        )
        raise typer.Exit(code=1)
    if not apply:
        typer.echo("\n(dry run — nothing written. Re-run with --apply to import.)")


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
    rows = api.query(domain=domain, object_type=object_type, status=status, q=q, limit=limit)
    typer.echo(json.dumps([r.model_dump() for r in rows], indent=2))


@app.command("ask")
def ask_cmd(
    ctx: typer.Context,
    question: str = typer.Argument(..., help="A question about what you've logged"),
    domain: str | None = typer.Option(None, "--domain", "-d"),
    limit: int = typer.Option(20, "--limit", "-n"),
) -> None:
    """Ask a question about your captured records (read-only)."""
    api = HarnessAPI(ctx.obj["home"])
    try:
        payload = api.ask(question, domain=domain, limit=limit)
    except ValueError as exc:
        typer.secho(str(exc), err=True, fg=typer.colors.RED)
        raise typer.Exit(code=1) from exc
    typer.echo(json.dumps(payload, indent=2, ensure_ascii=False))


@app.command("search")
def search_cmd(
    ctx: typer.Context,
    q: str = typer.Argument(..., help="FTS5 search query"),
    domain: str | None = typer.Option(None, "--domain", "-d"),
    object_type: str | None = typer.Option(None, "--object-type", "-t"),
    kind: str | None = typer.Option(None, "--kind", "-k", help="entry | canonical (default: both)"),
    limit: int = typer.Option(50, "--limit", "-n"),
) -> None:
    """Full-text search over entry raw text and canonical object text."""
    api = HarnessAPI(ctx.obj["home"])
    result = api.search(q, domain=domain, object_type=object_type, kind=kind, limit=limit)
    typer.echo(json.dumps(result, indent=2))


@app.command("export")
def export_cmd(
    ctx: typer.Context,
    domain: str | None = typer.Option(None, "--domain", "-d"),
    out: Path | None = typer.Option(
        None, "--out", "-o", help="Write JSON to a file (default: stdout)"
    ),
    json_output: bool = typer.Option(
        False,
        "--json",
        help="Emit compact JSON (export is JSON by default as well).",
    ),
) -> None:
    """Export your passion data as portable JSON (secrets-free)."""
    api = HarnessAPI(ctx.obj["home"])
    try:
        payload = api.export_data(domain=domain)
    except ValueError as exc:
        typer.secho(str(exc), err=True, fg=typer.colors.RED)
        raise typer.Exit(code=1) from exc
    text = json.dumps(payload, ensure_ascii=False, indent=None if json_output else 2)
    if out is not None:
        out = out.expanduser()
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text + "\n", encoding="utf-8")
        typer.echo(json.dumps({"wrote": str(out), "counts": payload["counts"]}))
    else:
        typer.echo(text)


@app.command("health")
def health_cmd(ctx: typer.Context) -> None:
    """Integrity + FK checks and entry counts."""
    api = HarnessAPI(ctx.obj["home"])
    report = api.health()
    typer.echo(json.dumps(report.model_dump(), indent=2))
    raise typer.Exit(code=0 if report.ok else 1)


@app.command("doctor")
def doctor_cmd(
    ctx: typer.Context,
    port: int = typer.Option(8787, "--port", help="Port to check for availability"),
    json_out: bool = typer.Option(False, "--json", help="Machine-readable output"),
) -> None:
    """One-glance install health: PASS/FAIL table + non-zero on any FAIL."""
    import socket

    from domain_foundry_core.api.app import _app_dist
    from domain_foundry_core.onboarding import resolved_status
    from domain_foundry_core.packs.loader import bundled_packs_root
    from domain_foundry_core.paths import Workspace

    home: Path = ctx.obj["home"]
    workspace = Workspace(home)
    checks: list[dict[str, str]] = []

    def add_check(name: str, status: str, detail: str) -> None:
        checks.append({"name": name, "status": status, "detail": detail})

    layout_paths = (
        workspace.db_dir,
        workspace.packs_dir,
        workspace.attachments_dir,
        workspace.vault_dir,
        workspace.blocks_dir,
    )
    layout_ok = workspace.home.is_dir() and all(path.is_dir() for path in layout_paths)
    if layout_ok:
        add_check("Home layout", "PASS", str(workspace.home))
    else:
        missing = [str(path.relative_to(home)) for path in layout_paths if not path.is_dir()]
        if not workspace.home.is_dir():
            missing.insert(0, str(workspace.home))
        add_check(
            "Home layout",
            "FAIL",
            f"missing {', '.join(missing)}; run domain-foundry init",
        )

    initialized = layout_ok and workspace.ledger_db.is_file() and workspace.domains_db.is_file()
    api: HarnessAPI | None = None
    api_error: str | None = None
    if initialized:
        try:
            api = HarnessAPI(home)
        except Exception as exc:  # noqa: BLE001 - doctor reports broken installs
            api_error = f"{type(exc).__name__}: {exc}"

    if api is None:
        detail = "run domain-foundry init"
        if api_error:
            detail = f"{api_error}; run domain-foundry init"
        add_check("Database integrity", "FAIL", detail)
    else:
        try:
            report = api.health()
        except Exception as exc:  # noqa: BLE001 - doctor reports broken installs
            add_check("Database integrity", "FAIL", f"{type(exc).__name__}: {exc}")
        else:
            if not report.ok:
                detail = f"ledger={report.ledger.integrity}, domains={report.domains.integrity}"
                add_check("Database integrity", "FAIL", detail)
            elif report.failed_change_requests:
                detail = "; ".join(report.warnings) or (
                    f"{report.failed_change_requests} change request(s) failed to apply"
                )
                add_check("Database integrity", "WARN", detail)
            else:
                add_check("Database integrity", "PASS", "ledger and domains are healthy")

    try:
        bundled_root = bundled_packs_root()
        bundled = sorted(
            path
            for path in bundled_root.iterdir()
            if path.is_dir() and path.name != "_template" and (path / "pack.yaml").is_file()
        )
    except OSError:
        bundled = []

    if api is None:
        if bundled:
            add_check(
                "Packs valid",
                "WARN",
                f"{len(bundled)} bundled pack(s) available; workspace is not initialized",
            )
        else:
            add_check("Packs valid", "FAIL", "no installed or bundled packs found")
    else:
        try:
            pack_errors = api.pack_validate(None)
            installed = api.pack_list()
        except Exception as exc:  # noqa: BLE001 - doctor reports broken installs
            add_check("Packs valid", "FAIL", f"{type(exc).__name__}: {exc}")
        else:
            if pack_errors:
                add_check("Packs valid", "FAIL", "; ".join(pack_errors))
            elif installed:
                add_check(
                    "Packs valid",
                    "PASS",
                    f"{len(installed)} installed pack(s) validate",
                )
            elif bundled:
                add_check(
                    "Packs valid",
                    "PASS",
                    f"{len(bundled)} bundled pack(s) available",
                )
            else:
                add_check("Packs valid", "FAIL", "no installed or bundled packs found")

    app_index = _app_dist() / "index.html"
    if app_index.is_file():
        add_check("Web app present", "PASS", str(app_index))
    else:
        add_check(
            "Web app present",
            "FAIL",
            "serve will return JSON — reinstall from a staged wheel",
        )

    try:
        provider = resolved_status(home)
        mode = str(provider.get("mode") or "unset")
        provider_name = str(provider.get("provider") or "none")
        routine_info = provider.get("routine")
        sota_info = provider.get("sota")
        routine = isinstance(routine_info, dict) and bool(routine_info.get("live"))
        sota = isinstance(sota_info, dict) and bool(sota_info.get("live"))
        detail = f"provider={provider_name}, mode={mode}, routine.live={routine}, sota.live={sota}"
        if mode == "live" and not (routine or sota):
            add_check("Providers", "FAIL", f"{detail}; no configured tier is live")
        else:
            add_check("Providers", "INFO", detail)
    except Exception as exc:  # noqa: BLE001 - doctor reports broken config
        add_check("Providers", "FAIL", f"{type(exc).__name__}: {exc}")

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.bind(("127.0.0.1", port))
    except (OSError, OverflowError, ValueError) as exc:
        add_check(
            "Port availability",
            "FAIL",
            f"port {port} unavailable — is serve already running? ({exc})",
        )
    else:
        add_check("Port availability", "PASS", f"127.0.0.1:{port} is available")

    suite = _heldout_suite_path()
    if suite.is_file():
        add_check("Held-out suite", "PASS", str(suite))
    else:
        add_check(
            "Held-out suite",
            "FAIL",
            f"missing {suite}; wizard acceptance cannot run",
        )

    ok = not any(check["status"] == "FAIL" for check in checks)
    if json_out:
        typer.echo(json.dumps({"checks": checks, "ok": ok}, indent=2))
    else:
        typer.echo(f"{'check':<22} {'status':<5} detail")
        for check in checks:
            typer.echo(f"{check['name']:<22} {check['status']:<5} {check['detail']}")
        typer.echo(f"{'overall':<22} {'PASS' if ok else 'FAIL'}")
    raise typer.Exit(code=0 if ok else 1)


@app.command("serve")
def serve_cmd(
    ctx: typer.Context,
    host: str = typer.Option("127.0.0.1", "--host"),
    port: int = typer.Option(8787, "--port", "-p"),
    token: str | None = typer.Option(None, "--token", envvar="DOMAIN_FOUNDRY_API_TOKEN"),
) -> None:
    """Run the local app and API (http://127.0.0.1:8787)."""
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


@eval_app.command("ask")
def eval_ask_cmd(
    ctx: typer.Context,
    cases: Path | None = typer.Option(
        None, "--cases", help="JSONL Ask cases (default: synthetic Ask set)"
    ),
    min_accuracy: float = typer.Option(0.9, "--min-accuracy"),
    live_llm: bool = typer.Option(
        False, "--live-llm", help="Re-record Ask cassettes against the live model"
    ),
) -> None:
    """Replay the grounded, read-only Ask corpus."""
    from domain_foundry_core.evals.ask import default_ask_cases_path, run_ask_eval

    path = cases or default_ask_cases_path()
    report = run_ask_eval(
        path,
        live_llm=live_llm,
        cassette_dir=Path(ctx.obj["home"]) / "cassettes",
    )
    typer.echo(json.dumps(report, indent=2))
    if report["accuracy"] < min_accuracy:
        raise typer.Exit(code=1)


@eval_app.command("interest-suite")
def eval_interest_suite_cmd(
    ctx: typer.Context,
    cases: Path | None = typer.Option(
        None, "--cases", help="JSONL interest cases (default: committed 50-interest suite)"
    ),
    baseline: Path | None = typer.Option(
        None, "--baseline", help="Baseline snapshot to ratchet against"
    ),
    bucket: str | None = typer.Option(
        None, "--bucket", help="Only run one bucket (indexed, collision, unindexed)"
    ),
    update_baseline: bool = typer.Option(
        False, "--update-baseline", help="Rewrite the committed baseline and exit"
    ),
    min_pass: int | None = typer.Option(
        None, "--min-pass", help="Fail if fewer than this many cases fully pass"
    ),
    report: Path | None = typer.Option(
        None, "--report", help="Write the full per-case JSON report here"
    ),
) -> None:
    """Run the end-to-end interest suite: type a passion, get an app that files.

    Offline and deterministic. Fails on any case that ends worse than the
    committed baseline, because aggregate counts hide trades where a fix for one
    goal quietly breaks another.
    """
    from domain_foundry_core.evals import interest as suite

    os.environ.setdefault("DOMAIN_FOUNDRY_LLM", "heuristic")
    selected = suite.load_cases(cases)
    if bucket:
        selected = [case for case in selected if case.get("bucket") == bucket]
    if not selected:
        typer.echo("no cases selected", err=True)
        raise typer.Exit(code=1)

    results = suite.run_suite(selected)
    summary = suite.summarise(results)

    if report is not None:
        report.write_text(
            json.dumps([item.to_json() for item in results], indent=2),
            encoding="utf-8",
        )

    baseline_path = baseline or suite.DEFAULT_BASELINE
    if update_baseline:
        baseline_path.write_text(
            json.dumps(suite.build_baseline(results), indent=2) + "\n", encoding="utf-8"
        )
        typer.echo(json.dumps(summary, indent=2))
        typer.echo(f"baseline written: {baseline_path}", err=True)
        return

    typer.echo(json.dumps(summary, indent=2))

    failed = False
    errored = [item.id for item in results if item.error]
    if errored:
        typer.echo(f"cases crashed: {', '.join(errored)}", err=True)
        failed = True

    if baseline_path.is_file() and not bucket:
        snapshot = json.loads(baseline_path.read_text(encoding="utf-8"))
        regressions = suite.compare_to_baseline(results, snapshot)
        if regressions:
            typer.echo("interest-suite regression vs baseline:", err=True)
            for line in regressions:
                typer.echo(f"  {line}", err=True)
            failed = True

    if min_pass is not None and summary["pass"] < min_pass:
        typer.echo(f"pass {summary['pass']} < required {min_pass}", err=True)
        failed = True

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
    action: str | None = typer.Option(None, "--action", help="amend|move|merge|undo|mark_wrong"),
    merge_into: str | None = typer.Option(None, "--merge-into"),
    domain: str | None = typer.Option(None, "--domain", help="Target domain for move"),
    as_json: bool = typer.Option(False, "--json", help="Emit machine JSON"),
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
    _drain_quietly(api)
    if as_json:
        typer.echo(json.dumps(receipt, indent=2))
    else:
        if receipt.get("error"):
            typer.echo(f"Couldn't apply that fix: {receipt['error']}")
        else:
            typer.echo(receipt.get("summary") or receipt.get("message") or "Fixed.")
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
    # Accept the natural verb forms people actually type; reject the rest with a
    # message rather than a traceback.
    decision = {"approve": "approved", "deny": "denied", "expire": "expired"}.get(
        decision.strip().lower(), decision.strip().lower()
    )
    if decision not in {"approved", "denied", "expired"}:
        typer.secho(
            f"invalid --decision {decision!r}; expected approved|denied|expired",
            err=True,
            fg=typer.colors.RED,
        )
        raise typer.Exit(code=2)
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
            api.projection_status(entry_id=entry_id, change_request_id=change_request_id),
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
    src: str = typer.Argument(..., help="Pack directory, or a bundled pack name (e.g. food)"),
    force: bool = typer.Option(False, "--force"),
) -> None:
    api = HarnessAPI(ctx.obj["home"])
    info = api.pack_add(_resolve_pack_source(src), force=force)
    typer.echo(json.dumps(info, indent=2))


def _pack_error_detail(exc: Exception) -> str:
    if isinstance(exc, KeyError) and exc.args:
        return str(exc.args[0])
    return str(exc)


def _emit_pack_lifecycle(operation: object, *, as_json: bool = True) -> None:
    from domain_foundry_core.receipts import pack_install_summary

    try:
        result = operation()  # type: ignore[operator]
    except (FileExistsError, FileNotFoundError, KeyError, ValueError) as exc:
        typer.secho(_pack_error_detail(exc), err=True, fg=typer.colors.RED)
        raise typer.Exit(code=2) from exc
    if isinstance(result, dict) and result.get("expert") is not None:
        # Hobby install receipts stay quiet about mesh stubs.
        payload = {**result}
        payload.pop("expert", None)
        if as_json and payload.get("status") == "activated":
            typer.echo(json.dumps(pack_install_summary(payload), indent=2, default=str))
            return
        typer.echo(json.dumps(payload, indent=2, default=str))
        return
    typer.echo(json.dumps(result, indent=2, default=str))


@pack_app.command("inspect")
def pack_inspect_cmd(
    ctx: typer.Context,
    target: str = typer.Argument(..., help="Pack directory or installed pack name"),
) -> None:
    api = HarnessAPI(ctx.obj["home"])
    _emit_pack_lifecycle(lambda: api.pack_inspect(target))


@pack_app.command("preview")
def pack_preview_cmd(
    ctx: typer.Context,
    src: str = typer.Argument(..., help="Pack directory or bundled pack name"),
) -> None:
    api = HarnessAPI(ctx.obj["home"])
    _emit_pack_lifecycle(lambda: api.pack_preview(_resolve_pack_source(src)))


@pack_app.command("install")
def pack_install_cmd(
    ctx: typer.Context,
    src: str = typer.Argument(..., help="Pack directory or bundled pack name"),
    force: bool = typer.Option(False, "--force", help="Replace an installed pack explicitly"),
) -> None:
    api = HarnessAPI(ctx.obj["home"])
    _emit_pack_lifecycle(lambda: api.pack_install(_resolve_pack_source(src), force=force))


@pack_app.command("activate")
def pack_activate_cmd(
    ctx: typer.Context,
    name: str = typer.Argument(..., help="Installed pack name or alias"),
) -> None:
    api = HarnessAPI(ctx.obj["home"])
    _emit_pack_lifecycle(lambda: api.pack_activate(name))


@pack_app.command("upgrade")
def pack_upgrade_cmd(
    ctx: typer.Context,
    src: str = typer.Argument(..., help="Updated pack directory or bundled pack name"),
) -> None:
    api = HarnessAPI(ctx.obj["home"])
    _emit_pack_lifecycle(lambda: api.pack_upgrade(_resolve_pack_source(src)))


@pack_app.command("rollback")
def pack_rollback_cmd(
    ctx: typer.Context,
    name: str = typer.Argument(..., help="Installed pack name or alias"),
    backup: Path | None = typer.Option(None, "--backup", help="Specific pack backup directory"),
) -> None:
    api = HarnessAPI(ctx.obj["home"])
    _emit_pack_lifecycle(lambda: api.pack_rollback(name, backup))


@pack_app.command("export")
def pack_export_cmd(
    ctx: typer.Context,
    name: str = typer.Argument(..., help="Installed pack name or alias"),
    destination: Path | None = typer.Argument(None, help="New destination directory (required)"),
    destination_option: Path | None = typer.Option(
        None, "--destination", "-d", help="New destination directory (required)"
    ),
) -> None:
    if destination is not None and destination_option is not None:
        typer.secho(
            "provide the export destination once, either as an argument or --destination",
            err=True,
            fg=typer.colors.RED,
        )
        raise typer.Exit(code=2)
    target = destination or destination_option
    if target is None:
        typer.secho(
            "export destination is required; pass it as an argument or --destination",
            err=True,
            fg=typer.colors.RED,
        )
        raise typer.Exit(code=2)
    api = HarnessAPI(ctx.obj["home"])
    _emit_pack_lifecycle(lambda: api.pack_export(name, target))


@pack_app.command("uninstall")
def pack_uninstall_cmd(
    ctx: typer.Context,
    name: str = typer.Argument(..., help="Installed pack name or alias (explicitly required)"),
) -> None:
    api = HarnessAPI(ctx.obj["home"])
    _emit_pack_lifecycle(lambda: api.pack_uninstall(name))


def _resolve_pack_source(src: str) -> Path:
    """Accept a path *or* a bundled pack name.

    Installed from a wheel there is no `packs/` directory to point at, so the
    documented `pack add packs/food` can only work as a name lookup.
    """
    from domain_foundry_core.packs.loader import bundled_packs_root

    candidate = Path(src)
    if candidate.is_dir():
        return candidate

    root = bundled_packs_root()
    # Tolerate "packs/food" as well as "food".
    named = root / candidate.name
    if named.is_dir():
        return named

    available = sorted(p.name for p in root.glob("*") if (p / "pack.yaml").is_file())
    typer.secho(
        f"no pack at {src!r}. Bundled packs: {', '.join(available) or '(none)'}",
        err=True,
        fg=typer.colors.RED,
    )
    raise typer.Exit(code=2)


@foundry_app.command("goldens")
def foundry_goldens_cmd() -> None:
    """List the reviewed golden specifications shipped with Domain Foundry."""
    from domain_foundry_core.foundry import load_golden_specs

    payload = [
        {
            "id": spec.id,
            "title": spec.title,
            "interest": spec.research.interest,
            "selected_concept": spec.remix.selected_concept,
            "visual_world": spec.experience.visual_world.id,
        }
        for spec in load_golden_specs()
    ]
    typer.echo(json.dumps(payload, indent=2, ensure_ascii=False))


@foundry_app.command("validate")
def foundry_validate_cmd(
    spec_path: Path = typer.Argument(..., exists=True, dir_okay=False, readable=True),
) -> None:
    """Validate a FoundrySpec and every source/principle reference it uses."""
    from domain_foundry_core.foundry import load_foundry_spec

    spec = load_foundry_spec(spec_path.resolve())
    typer.echo(
        json.dumps(
            {
                "valid": True,
                "id": spec.id,
                "spec_version": spec.spec_version,
                "sources": len(spec.source_ids),
                "principles": len(spec.principle_ids),
                "entities": len(spec.domain.entities),
                "views": len(spec.experience.views),
                "evaluation_cases": len(spec.evaluation.cases),
            },
            indent=2,
        )
    )


def _foundry_acceptance_task(value: str):  # type: ignore[no-untyped-def]
    from domain_foundry_core.foundry import AcceptanceTask

    if "=>" not in value:
        raise typer.BadParameter("tasks use 'what the user does => observable expected outcome'")
    action, expected = (part.strip() for part in value.split("=>", 1))
    if not action or not expected:
        raise typer.BadParameter("both sides of a task must be non-empty")
    return AcceptanceTask(input=action, expected=expected)


def _live_foundry_provider(home: Path):  # type: ignore[no-untyped-def]
    from domain_foundry_core.llm.provider import build_tiered_provider

    provider = build_tiered_provider(home)
    if not provider.has_live_keys():
        typer.secho(
            "Foundry design requires a configured reasoning model; it will not replace "
            "research and schema design with the offline keyword scaffold. Run "
            "`domain-foundry setup` first.",
            err=True,
            fg=typer.colors.RED,
        )
        raise typer.Exit(code=2)
    return provider


def _foundry_meter(home: Path, *, spec_id: str | None = None):  # type: ignore[no-untyped-def]
    """Meter Foundry sota calls against the same daily cap capture uses.

    A propose plus a complete is six sota calls. They used to be invisible to
    the guard that exists to bound spend; now every one writes a ``cost_ledger``
    row under the ``foundry`` tier and the cap is checked before each call.
    """
    from domain_foundry_core.foundry.cost import LedgerCostMeter

    return LedgerCostMeter.for_home(home, spec_id=spec_id)


@foundry_app.command("propose")
def foundry_propose_cmd(
    ctx: typer.Context,
    goal: str = typer.Argument(..., help="Interest and desired outcome in plain language"),
    output: Path = typer.Option(..., "--output", "-o", help="New proposal YAML path"),
    task: list[str] = typer.Option(
        [],
        "--task",
        help="User-authored acceptance task: 'action => observable outcome' (repeat twice)",
    ),
    artifact: list[str] = typer.Option(
        [], "--artifact", help="Existing notebook, export, folder, or practice artifact"
    ),
    constraint: list[str] = typer.Option(
        [], "--constraint", help="Privacy, device, workflow, or scope constraint"
    ),
    web_research: bool = typer.Option(
        True,
        "--web-research/--registry-only",
        help="Use Brave discovery when BRAVE_SEARCH_API_KEY is configured",
    ),
) -> None:
    """Research an interest and produce three evidence-backed product concepts."""
    from domain_foundry_core.foundry import FoundryPipeline
    from domain_foundry_core.foundry.pipeline import PipelineError
    from domain_foundry_core.foundry.research import BraveSearchProvider, ResearchUnavailable

    tasks = [_foundry_acceptance_task(value) for value in task]
    if len(tasks) < 2:
        raise typer.BadParameter(
            "repeat --task at least twice; the generator cannot author its judge"
        )
    provider = _live_foundry_provider(ctx.obj["home"])
    search = (
        BraveSearchProvider() if web_research and os.environ.get("BRAVE_SEARCH_API_KEY") else None
    )
    try:
        # No allow_model_knowledge here, deliberately: a user who ran
        # `foundry propose` asked for a researched specification and gets one or
        # gets nothing (ADR-010).
        proposed = FoundryPipeline(
            provider, search=search, meter=_foundry_meter(ctx.obj["home"])
        ).propose(
            goal,
            artifacts=artifact,
            constraints=constraint,
            acceptance_tasks=tasks,
        )
        proposed.proposal.dump(output.resolve())
    except (ResearchUnavailable, PipelineError, FileExistsError) as exc:
        typer.secho(str(exc), err=True, fg=typer.colors.RED)
        raise typer.Exit(code=2) from exc
    typer.echo(
        json.dumps(
            {
                "proposed": True,
                "id": proposed.proposal.id,
                "title": proposed.proposal.title,
                "output": str(output.resolve()),
                "candidate_sources": proposed.candidate_count,
                "evidence_tier": proposed.proposal.receipt.evidence_tier,
                "concepts": [
                    {
                        "id": concept.id,
                        "title": concept.title,
                        "thesis": concept.thesis,
                        "primary_loop": concept.primary_loop,
                        "tradeoffs": concept.tradeoffs,
                    }
                    for concept in proposed.proposal.concepts
                ],
            },
            indent=2,
            ensure_ascii=False,
        )
    )


@foundry_app.command("complete")
def foundry_complete_cmd(
    ctx: typer.Context,
    proposal_path: Path = typer.Argument(..., exists=True, dir_okay=False, readable=True),
    selected_concept: str = typer.Option(..., "--select", help="Concept id to use as the base"),
    output: Path = typer.Option(..., "--output", "-o", help="New FoundrySpec YAML path"),
    decision: list[str] = typer.Option(
        [], "--decision", help="Explicit user decision retained in remix lineage"
    ),
    fragment_json: list[str] = typer.Option(
        [],
        "--fragment-json",
        help="JSON RemixFragment to borrow workflow/schema/interaction/visual pieces",
    ),
) -> None:
    """Turn an approved concept/remix into a complete validated FoundrySpec."""
    from domain_foundry_core.foundry import (
        FoundryPipeline,
        FoundryProposal,
        dump_foundry_spec,
    )
    from domain_foundry_core.foundry.models import RemixFragment, RemixSelection
    from domain_foundry_core.foundry.pipeline import PipelineError

    if not decision:
        raise typer.BadParameter("at least one --decision is required for remix lineage")
    try:
        fragments = [RemixFragment.model_validate_json(value) for value in fragment_json]
    except Exception as exc:
        raise typer.BadParameter(f"invalid --fragment-json: {exc}") from exc
    proposal = FoundryProposal.load(proposal_path.resolve())
    provider = _live_foundry_provider(ctx.obj["home"])
    remix = RemixSelection(
        selected_concept=selected_concept,
        fragments=fragments,
        user_decisions=decision,
    )
    try:
        meter = _foundry_meter(ctx.obj["home"], spec_id=proposal.id)
        spec = FoundryPipeline(provider, meter=meter).complete(proposal, remix)
        dump_foundry_spec(spec, output.resolve())
    except (PipelineError, FileExistsError) as exc:
        typer.secho(str(exc), err=True, fg=typer.colors.RED)
        raise typer.Exit(code=2) from exc
    typer.echo(
        json.dumps(
            {
                "completed": True,
                "id": spec.id,
                "output": str(output.resolve()),
                "entities": len(spec.domain.entities),
                "views": len(spec.experience.views),
                "evaluation_cases": len(spec.evaluation.cases),
                "evidence_tier": spec.evidence_tier,
                "evidence_label": spec.evidence_tier_label,
            },
            indent=2,
        )
    )


@foundry_app.command("build")
def foundry_build_cmd(
    spec_path: Path = typer.Argument(..., exists=True, dir_okay=False, readable=True),
    output: Path = typer.Option(..., "--output", "-o", help="New or empty output directory"),
) -> None:
    """Compile a validated spec into an inspectable, owned application bundle."""
    from domain_foundry_core.foundry import FoundryCompiler, load_foundry_spec

    spec = load_foundry_spec(spec_path.resolve())
    artifact = FoundryCompiler().compile(spec, output)
    typer.echo(
        json.dumps(
            {
                "built": True,
                "id": spec.id,
                "root": str(artifact.root),
                "app": str(artifact.app),
                "schema": str(artifact.schema),
                "spec": str(artifact.spec),
                "evidence": str(artifact.evidence),
                "receipt": str(artifact.receipt),
            },
            indent=2,
        )
    )


@pack_app.command("new")
def pack_new_cmd(
    ctx: typer.Context,
    name: str = typer.Argument(...),
) -> None:
    api = HarnessAPI(ctx.obj["home"])
    info = api.pack_new(name)
    typer.echo(json.dumps(info, indent=2))


def _creation_progress_text(turn: dict) -> str:
    """Render only the useful part of the release progress rail."""
    items = turn.get("progress") or []
    labels = []
    for item in items:
        status = item.get("status")
        mark = "✓" if status == "done" else "→" if status == "active" else "·"
        labels.append(f"{mark} {item.get('label', '')}")
    return "  " + "   ".join(labels) if labels else ""


def _creation_schema_text(preview: dict) -> list[str]:
    fields = preview.get("fields") or []
    grouped: dict[str, list[str]] = {}
    for field in fields:
        if not isinstance(field, dict):
            continue
        obj = field_label(str(field.get("object") or "details"))
        grouped.setdefault(obj, []).append(field_label(str(field.get("name") or "details")))
    return [f"  {obj}  {', '.join(dict.fromkeys(names))}" for obj, names in grouped.items()]


def _render_creation_turn(turn: dict, *, details: bool = False) -> None:
    """Print the release conversation in the same order as the web journey."""
    typer.echo(turn.get("user_message") or turn.get("message") or "")
    progress = _creation_progress_text(turn)
    if progress:
        typer.echo(progress)

    neighborhood = turn.get("neighborhood") or {}
    ideas = neighborhood.get("ideas") or []
    if ideas and turn.get("state") == "fork":
        typer.echo("\nChoose a direction:")
        for index, idea in enumerate(ideas, start=1):
            marker = " — closest to what you described" if idea.get("highlighted") else ""
            typer.echo(f"  {index}  {idea.get('title', 'This direction')}{marker}")
            if idea.get("pitch"):
                typer.echo(f"     {idea['pitch']}")
        for heading, key in (("You might also want", "expand"), ("More directions", "refine")):
            cards = neighborhood.get(key) or []
            if cards:
                typer.echo(f"\n{heading}: " + ", ".join(str(card.get("title")) for card in cards[:8]))

    looks = turn.get("looks") or []
    if looks and turn.get("state") == "looks":
        typer.echo("\nStarting points:")
        for index, look in enumerate(looks, start=1):
            pitch = job_label(look.get("hero_job"))
            typer.echo(f"  {index}  {look.get('title', 'Starting point')} — {pitch}")

    preview = turn.get("schema_preview")
    if isinstance(preview, dict):
        typer.echo("\nThe app will keep track of:")
        for line in _creation_schema_text(preview):
            typer.echo(line)

    capture = turn.get("capture") or {}
    routed = capture.get("routed") or []
    if routed:
        first = routed[0]
        disposition = str(first.get("disposition") or "")
        if disposition not in {"unfiled", "ledger_only"}:
            typer.echo(
                "\nWent to the right place: "
                f"{field_label(str(first.get('object_type') or 'note'))}."
            )
        else:
            typer.echo("\nYour note is safe, but it did not go to the right place yet.")

    if turn.get("based_on") and turn.get("state") in {"test_drive", "done"}:
        typer.echo(f"Based on {turn['based_on']}.")
    if details and turn.get("technical_details"):
        raw = turn["technical_details"].get("message")
        if raw:
            typer.echo(f"\nTechnical details: {raw}")


def _run_creation(
    home: Path,
    goal: str | None,
    replies: list[str],
    *,
    test_drive: int,
    json_output: bool,
    details: bool,
) -> None:
    if json_output and not goal:
        raise typer.BadParameter("a goal is required with --json")
    if not goal:
        goal = typer.prompt("What would you like an app for?")
    goal_text = str(goal).strip()
    if not goal_text:
        raise typer.BadParameter("tell us what you want the app for")

    api = HarnessAPI(home)
    turn = api.create_domain(goal_text, test_drive=test_drive)
    session_id = str(turn["session_id"])
    if json_output:
        typer.echo(json.dumps(turn, indent=2, ensure_ascii=False))
    else:
        _render_creation_turn(turn, details=details)

    scripted = list(replies)
    scripted_mode = bool(scripted)
    while True:
        if scripted:
            text = scripted.pop(0)
        elif json_output or scripted_mode or turn.get("state") in {"done", "failed"}:
            break
        else:
            prompt = "\n> "
            try:
                text = typer.prompt(prompt, prompt_suffix="")
            except (EOFError, KeyboardInterrupt):
                typer.echo("\nYour choices are saved. You can continue this session later.")
                break
        turn = api.wizard_reply(session_id, text)
        if json_output:
            typer.echo(json.dumps(turn, indent=2, ensure_ascii=False))
        else:
            _render_creation_turn(turn, details=details)
        if turn.get("state") in {"done", "failed"} and not scripted:
            break


@app.command("create")
def create_cmd(
    ctx: typer.Context,
    goal: str | None = typer.Argument(None, help="A topic or practice, such as 'whisky'"),
    reply: list[str] = typer.Option(
        [],
        "--reply",
        "-r",
        help="Scripted replies for automation or a recorded conversation (repeatable)",
    ),
    test_drive: int = typer.Option(5, "--test-drive", help="First-use note budget"),
    json_output: bool = typer.Option(False, "--json", help="Print machine-readable turns"),
    details: bool = typer.Option(False, "--details", help="Show technical detail below the conversation"),
) -> None:
    """Create a personal app through the release conversation."""
    _run_creation(
        ctx.obj["home"],
        goal,
        reply,
        test_drive=test_drive,
        json_output=json_output,
        details=details,
    )


@app.command("new-domain")
def new_domain_cmd(
    ctx: typer.Context,
    goal: str = typer.Argument(..., help="Plain-language goal, e.g. 'track my sourdough journey'"),
    reply: list[str] = typer.Option(
        [],
        "--reply",
        "-r",
        help="Scripted wizard replies (repeatable): idea pick, skip, sample captures, edits",
    ),
    test_drive: int = typer.Option(5, "--test-drive", help="Test-drive capture budget"),
) -> None:
    """Deprecated legacy JSON wizard; use ``domain-foundry create`` instead.

    Use ``create`` for the calm, interactive release conversation.
    """
    typer.secho("new-domain is deprecated; use `domain-foundry create`.", err=True, fg=typer.colors.YELLOW)
    api = HarnessAPI(ctx.obj["home"])
    turn = api.new_domain(goal, test_drive=test_drive)
    typer.echo(json.dumps(turn, indent=2, ensure_ascii=False))
    session_id = turn["session_id"]
    for text in reply:
        turn = api.wizard_reply(session_id, text)
        typer.echo(json.dumps(turn, indent=2, ensure_ascii=False))


wizard_app = typer.Typer(help="Resume / drive domain-creation wizard sessions")
app.add_typer(wizard_app, name="wizard")

atlas_app = typer.Typer(help="Browse and lint the idea atlas")
app.add_typer(atlas_app, name="atlas")


@atlas_app.command("search")
def atlas_search_cmd(
    ctx: typer.Context,
    goal: str = typer.Argument(..., help="A topic, practice, or app idea in plain language"),
    cursor: str | None = typer.Option(None, "--cursor", help="Stay at this atlas node id"),
) -> None:
    """Print the matched neighborhood (refine / expand / ideas)."""
    api = HarnessAPI(ctx.obj["home"])
    typer.echo(json.dumps(api.atlas_search(goal, cursor_id=cursor), indent=2, ensure_ascii=False))


@atlas_app.command("validate")
def atlas_validate_cmd(ctx: typer.Context) -> None:
    """Lint shipped atlas YAML plus ~/.domain_foundry/atlas overlay."""
    api = HarnessAPI(ctx.obj["home"])
    report = api.atlas_validate()
    typer.echo(json.dumps(report, indent=2, ensure_ascii=False))
    if report.get("errors"):
        raise typer.Exit(code=1)


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


@mesh_app.command("weekly-triage")
def mesh_weekly_triage_cmd(
    ctx: typer.Context,
    force: bool = typer.Option(
        False, "--force", help="Enqueue even if already fired this ISO week"
    ),
) -> None:
    """Enqueue the Concierge weekly triage nudge (idempotent per UTC week)."""
    from domain_foundry_core.mesh.triage_nudge import maybe_fire_weekly_triage
    from domain_foundry_core.paths import Workspace

    result = maybe_fire_weekly_triage(Workspace(ctx.obj["home"]), force=force)
    typer.echo(json.dumps(result, indent=2))


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
    feed: Path | None = typer.Option(None, "--feed", help="Roamboard feed JSON (schemaVersion 2)"),
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
