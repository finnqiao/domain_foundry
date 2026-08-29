"""The `foundry fork` verb.

Lane G ships this as its own module. `cli.py` gets one registration line, added
by the integrator; nothing here reaches into `cli.py`.
"""

from __future__ import annotations

import json
from pathlib import Path

import typer


def _fork(
    spec_path: Path = typer.Argument(
        ...,
        exists=True,
        dir_okay=False,
        readable=True,
        help="The spec YAML to start from, or the foundry-spec.json inside a built bundle",
    ),
    new_id: str = typer.Argument(
        ...,
        help="The id for the new spec, like 'sourdough-rye'",
    ),
    output: Path = typer.Option(
        ...,
        "--output",
        "-o",
        help="Where to write the new spec YAML. The file must not exist yet.",
    ),
    title: str | None = typer.Option(
        None, "--title", help="A new title for the fork. Keeps the parent's title if you skip it."
    ),
    note: str | None = typer.Option(
        None,
        "--note",
        help="One line saying why you forked. Recorded with the spec.",
    ),
) -> None:
    """Copy a spec under a new id and record which spec it came from."""

    from domain_foundry_core.foundry.fork import ForkError, fork_spec
    from domain_foundry_core.foundry.loader import dump_foundry_spec, load_foundry_spec
    from domain_foundry_core.foundry.models import FoundrySpec

    resolved = spec_path.resolve()
    if resolved.suffix == ".json":
        spec = FoundrySpec.model_validate(json.loads(resolved.read_text(encoding="utf-8")))
    else:
        spec = load_foundry_spec(resolved)

    try:
        result = fork_spec(spec, new_id, title=title, note=note)
    except ForkError as error:
        typer.secho(str(error), err=True, fg=typer.colors.RED)
        raise typer.Exit(code=2) from error

    destination = output.resolve()
    try:
        dump_foundry_spec(result.spec, destination)
    except FileExistsError:
        typer.secho(
            f"There is already a file at {destination}. Pick a path that does not exist yet.",
            err=True,
            fg=typer.colors.RED,
        )
        raise typer.Exit(code=2) from None

    typer.echo(result.sentence)
    typer.echo(f"Written to {destination}")


def register(app: typer.Typer) -> None:
    """Attach `foundry fork` to the CLI.

    Joins the existing `foundry` group when there is one, and makes the group
    when there is not, so a bare `typer.Typer()` in a test gets the same verb
    the shipped CLI gets.
    """

    for group in app.registered_groups:
        if group.name == "foundry" and group.typer_instance is not None:
            group.typer_instance.command("fork")(_fork)
            return
    foundry_app = typer.Typer(help="Compile evidence-backed FoundrySpec applications")
    foundry_app.command("fork")(_fork)
    app.add_typer(foundry_app, name="foundry")


__all__ = ["register"]
