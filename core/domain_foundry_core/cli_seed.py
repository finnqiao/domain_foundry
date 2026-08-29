"""The ``seed`` verb: start the app full, from records you already keep.

This module is self-contained on purpose. It exposes ``register(app)``, and the
integrator adds one line to the command registry in ``cli.py``. No logic lives
there.
"""

from __future__ import annotations

import json
from pathlib import Path

import typer

from domain_foundry_core.paths import ENV_HOME, Workspace, default_home
from domain_foundry_core.seed.apply import SeedApplyError, apply_seed
from domain_foundry_core.seed.brief import SEED_ASK, seed_brief_inputs
from domain_foundry_core.seed.mapping import (
    SeedMappingError,
    infer_mapping,
    load_seed_mapping,
    save_seed_mapping,
)
from domain_foundry_core.seed.preview import PREVIEW_FILENAME, build_preview, write_preview
from domain_foundry_core.seed.readers import SeedReadError, read_seed

# One line, and it says what leaves the machine. Lane A's audit reads this.
SEED_HELP = (
    "Start an app from records you already keep. Only column names and a few "
    "sample rows are ever shown to a model, never the whole file."
)


def register(app: typer.Typer) -> None:
    """Attach the seed verbs to a Typer app."""

    app.command("seed", help=SEED_HELP)(seed_cmd)


def _resolve_home(ctx: typer.Context, home: Path | None) -> Path:
    if home is not None:
        return home.expanduser().resolve()
    obj = ctx.obj if isinstance(ctx.obj, dict) else None
    if obj and obj.get("home"):
        return Path(obj["home"]).expanduser().resolve()
    return default_home()


def seed_cmd(
    ctx: typer.Context,
    source: str = typer.Argument(
        ...,
        help="A spreadsheet, a csv, a JSON export, a mail export, a folder of notes, "
        "a saved page, or a web address",
    ),
    domain: str = typer.Option(..., "--domain", "-d", help="The app the records go into"),
    object_type: str | None = typer.Option(
        None,
        "--object-type",
        help="The table inside that app (default: worked out from the source)",
    ),
    mapping_file: Path | None = typer.Option(
        None, "--mapping", "-m", help="Use a mapping you edited instead of working one out"
    ),
    apply: bool = typer.Option(
        False, "--apply", help="Write the records (without this nothing is written)"
    ),
    out: Path | None = typer.Option(
        None, "--out", help=f"Where to put the preview page (default: ./{PREVIEW_FILENAME})"
    ),
    save_mapping: Path | None = typer.Option(
        None, "--save-mapping", help="Write the worked-out mapping here so you can edit it"
    ),
    use_model: bool = typer.Option(
        False,
        "--use-model",
        help="Let a model name the columns the rules could not. It sees column "
        "names and a few sample rows only.",
    ),
    fetch: bool = typer.Option(
        False, "--fetch", help="Allow reading a web address over the network"
    ),
    label: str | None = typer.Option(None, "--label", help="A name for this seed"),
    license_note: str | None = typer.Option(
        None, "--license", help="The licence of a page you pointed at, if you know it"
    ),
    as_json: bool = typer.Option(False, "--json", help="Print the result as JSON"),
    home: Path | None = typer.Option(
        None, "--home", envvar=ENV_HOME, help="Workspace root (default: ~/.domain_foundry)"
    ),
) -> None:
    """Read what you already keep, show you what it will become, then write it.

    \b
    The source is opened read only. It is never moved, renamed, or changed.
    Nothing is written until you add --apply, and running the same seed twice
    writes nothing the second time.

    \b
    What I can read:
      a spreadsheet (.xlsx), a csv or tsv, a JSON or JSONL export,
      a mail export (.mbox), a folder of notes, a page saved as .html,
      or a web address with --fetch

    \b
    Try it:
      domain-foundry seed ~/tidepools.xlsx --domain tidepools
      domain-foundry seed ~/tidepools.xlsx --domain tidepools --apply
    """

    workspace = Workspace(_resolve_home(ctx, home))

    try:
        read = read_seed(source, label=label, license_note=license_note, fetch=fetch)
    except SeedReadError as exc:
        typer.secho(str(exc), err=True, fg=typer.colors.RED)
        raise typer.Exit(code=2) from exc

    # A page you point at is reference material. It has no rows to map.
    if not read.tables and read.documents:
        _report_page(read, out, as_json=as_json)
        return

    try:
        if mapping_file is not None:
            mapping = load_seed_mapping(mapping_file.expanduser())
        else:
            provider = _provider(workspace) if use_model else None
            mapping = infer_mapping(read, domain=domain, object_type=object_type, provider=provider)
    except SeedMappingError as exc:
        typer.secho(str(exc), err=True, fg=typer.colors.RED)
        raise typer.Exit(code=2) from exc

    if save_mapping is not None:
        save_seed_mapping(mapping, save_mapping.expanduser())

    try:
        result = apply_seed(workspace, read, mapping, dry_run=not apply)
    except SeedApplyError as exc:
        typer.secho(str(exc), err=True, fg=typer.colors.RED)
        raise typer.Exit(code=2) from exc

    preview = build_preview(
        read,
        mapping,
        will_write=result.would_write if not apply else result.written,
        already_present=result.already_present,
    )
    preview_path = write_preview(preview, out or Path.cwd() / PREVIEW_FILENAME)

    payload = {
        **result.as_dict(),
        "preview": str(preview_path),
        "domain": mapping.domain,
        "object_type": mapping.object_type,
        "unmapped_columns": mapping.unmapped_columns,
        "lists": {item.column: item.distinct for item in mapping.lists},
    }
    if as_json:
        typer.echo(json.dumps(payload, indent=2, sort_keys=True))
    else:
        _report_table(mapping, result, preview_path, applied=apply)

    if not result.complete:
        raise typer.Exit(code=1)


def _report_table(mapping, result, preview_path: Path, *, applied: bool) -> None:
    typer.echo(f"Read {result.source_total} rows from {mapping.label}.")
    typer.echo(mapping.sentence())
    for item in mapping.lists:
        typer.echo(f"Found {item.distinct} different values in {item.column}.")
    if mapping.unmapped_columns:
        typer.echo(
            "Left out, because I could not tell what they are: "
            + ", ".join(mapping.unmapped_columns)
        )
    if applied:
        typer.echo(f"Wrote {result.written} records. {result.already_present} were already here.")
    else:
        typer.echo(f"Nothing was written. {result.would_write} records are ready to go.")
        typer.echo("Run it again with --apply when the preview looks right.")
    typer.echo(f"Preview: {preview_path}")


def _report_page(read, out: Path | None, *, as_json: bool) -> None:
    preview = build_preview(read, None, will_write=0)
    preview_path = write_preview(preview, out or Path.cwd() / PREVIEW_FILENAME)
    inputs = seed_brief_inputs([read])
    if as_json:
        typer.echo(
            json.dumps(
                {
                    "seed_id": read.provenance.id,
                    "kind": read.provenance.kind,
                    "shareable": read.provenance.shareable,
                    "documents": [doc.title for doc in read.documents],
                    "artifacts": inputs.artifacts,
                    "preview": str(preview_path),
                },
                indent=2,
                sort_keys=True,
            )
        )
        return
    for doc in read.documents:
        typer.echo(f"Read the page: {doc.title}")
    typer.echo(
        "Kept as something to cite, not as records. The licence is unknown until someone checks it."
    )
    typer.echo(f"Preview: {preview_path}")


def _provider(workspace: Workspace):
    """The user's own model, if one is set up. Otherwise the rules alone."""

    from domain_foundry_core.llm import build_tiered_provider

    try:
        return build_tiered_provider(workspace.home)
    except Exception:  # noqa: BLE001 - no key set is a normal state, not an error
        return None


__all__ = ["SEED_ASK", "SEED_HELP", "register", "seed_cmd"]
