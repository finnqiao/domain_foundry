"""The `stack` verb: put two packs together into one pack with a real join.

Lane D of docs/rebuild-plan-2026-08-28. `stack travel food` writes a new pack
that builds on travel, borrows the dining object from food, and gives one travel
record a pointer to a food record that the database enforces.

The generated pack is plain declarative data, like every other pack (ADR-004).
"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path
from typing import Any

import typer
import yaml

from domain_foundry_core.packs.loader import (
    PackValidationError,
    default_pack_resolver,
    load_pack,
)
from domain_foundry_core.packs.models import DomainPack, link_column
from domain_foundry_core.packs.registry import PackRegistry
from domain_foundry_core.packs.schema_compiler import compile_ddl, table_name
from domain_foundry_core.paths import Workspace

MAX_OBJECTS_WITHOUT_ASKING = 3


class StackError(ValueError):
    """A stack request we cannot carry out, with a message the user can act on."""


def anchor_object(base: DomainPack, other: str) -> str:
    """The object in ``base`` that should hold the pointer to the other pack.

    First choice is an object that already points at the other pack, because the
    author already said that is where the two domains meet. Otherwise it is the
    object the most routing rules send records to, and ties go to whichever
    object the schema declares first.
    """
    for name, obj in base.objects.items():
        for link in obj.links.values():
            if base.link_target(link)[0] == other:
                return name
    counts = {name: 0 for name in base.objects}
    for rule in base.routing.rules:
        if rule.object in counts:
            counts[rule.object] += 1
    best = max(counts.items(), key=lambda item: (item[1], -list(base.objects).index(item[0])))
    return best[0]


def default_objects(base: DomainPack, other: DomainPack) -> list[str]:
    """The objects of ``other`` to borrow when the user names none."""
    already = [
        base.link_target(link)[1]
        for obj in base.objects.values()
        for link in obj.links.values()
        if base.link_target(link)[0] == other.name
    ]
    picked = [name for name in other.objects if name in set(already)]
    if picked:
        return picked
    if len(other.objects) <= MAX_OBJECTS_WITHOUT_ASKING:
        return list(other.objects)
    return []


def _link_name_for(anchor: Any, object_name: str) -> str:
    """Reuse the existing link name when there is one, otherwise use the object."""
    for link_name, link in anchor.links.items():
        if link.to.endswith(f".{object_name}") or link.to == object_name:
            return link_name
    return object_name


def build_pack_files(
    base: DomainPack,
    other: DomainPack,
    *,
    name: str,
    objects: list[str],
) -> dict[str, Any]:
    """The YAML documents that make up the stacked pack."""
    anchor_name = anchor_object(base, other.name)
    anchor = base.objects[anchor_name]
    links = {
        _link_name_for(anchor, object_name): {
            "to": f"{other.name}.{object_name}",
            "cardinality": "many_to_one",
        }
        for object_name in objects
    }
    borrowed = ", ".join(objects)
    manifest = {
        "name": name,
        "version": "0.1.0",
        "title": f"{base.manifest.title} and {other.manifest.title}",
        "description": (
            f"Everything {base.name} keeps, plus a pointer from each "
            f"{anchor_name} record to a {other.name} {borrowed} record."
        ),
        "author": "you",
        "license": "MIT",
        "core_compat": base.manifest.core_compat,
        "interpretation": base.manifest.interpretation,
        "extends": base.name,
        "imports": [{"from": other.name, "object": object_name} for object_name in objects],
    }
    schema = {"objects": {anchor_name: {"links": links}}}
    title_field = anchor.title_field
    columns = [title_field] if title_field else []
    columns.extend(link_column(link_name) for link_name in links)
    view = {
        "id": f"{anchor_name}_with_{other.name}",
        "title": f"{anchor_name.replace('_', ' ').title()} and {other.manifest.title}",
        "block": "list",
        "object": anchor_name,
        "config": {"columns": columns},
    }
    return {
        "pack.yaml": manifest,
        "schema.yaml": schema,
        "routing.yaml": {},
        "operations.yaml": {},
        "policy.yaml": {},
        "projections.yaml": {"app": {"views": [view]}},
        "_anchor": anchor_name,
        "_links": links,
        "_view": view,
    }


def write_pack_dir(files: dict[str, Any], root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    for filename, body in files.items():
        if filename.startswith("_"):
            continue
        text = yaml.safe_dump(body, sort_keys=False, allow_unicode=True) if body else "{}\n"
        (root / filename).write_text(text, encoding="utf-8")
    return root


def example_capture(pack: DomainPack, object_name: str) -> str:
    """A capture line from the pack's own routing examples, or a plain fallback."""
    for example in pack.routing.examples:
        if example.expect.get("object") == object_name:
            return example.text
    return f"a new {object_name.replace('_', ' ')}"


def stack_packs(
    base_name: str,
    other_name: str,
    *,
    name: str | None = None,
    objects: list[str] | None = None,
    home: Path | None = None,
    out: Path | None = None,
) -> dict[str, Any]:
    """Write the stacked pack, and turn it on unless ``out`` says otherwise."""
    workspace = Workspace(home)
    workspace.ensure_layout()
    registry = PackRegistry(workspace)
    base = registry.get_by_alias(base_name)
    other = registry.get_by_alias(other_name)
    for wanted, found in ((base_name, base), (other_name, other)):
        if found is None:
            raise StackError(
                f"Pack {wanted} is not turned on here. Run "
                f"`domain-foundry pack add packs/{wanted}` first, then try again."
            )
    assert base is not None and other is not None
    if base.name == other.name:
        raise StackError("Give two different packs to stack.")

    chosen = list(objects) if objects else default_objects(base, other)
    if not chosen:
        raise StackError(
            f"Pack {other.name} has {len(other.objects)} objects, so say which ones "
            f"to borrow with --objects. It has: {', '.join(sorted(other.objects))}."
        )
    unknown = [object_name for object_name in chosen if object_name not in other.objects]
    if unknown:
        raise StackError(
            f"Pack {other.name} has no object called {', '.join(unknown)}. "
            f"It has: {', '.join(sorted(other.objects))}."
        )

    stacked_name = name or f"{base.name}_{other.name}"
    files = build_pack_files(base, other, name=stacked_name, objects=chosen)

    if out is not None:
        destination = Path(out).expanduser()
        if destination.exists() and any(destination.iterdir()):
            raise StackError(f"{destination} already has files in it. Pick an empty folder.")
        write_pack_dir(files, destination)
        pack = load_pack(destination, resolver=default_pack_resolver(base.root))
        installed = False
    else:
        staging = Path(tempfile.mkdtemp(prefix="domain-foundry-stack-"))
        try:
            write_pack_dir(files, staging / stacked_name)
            pack = registry.add(staging / stacked_name, force=True)
            destination = pack.root
            installed = True
        finally:
            shutil.rmtree(staging, ignore_errors=True)

    anchor_name = str(files["_anchor"])
    link_rows = []
    ddl = compile_ddl(pack, available_packs={other.name})
    for link_name, link in files["_links"].items():
        column = link_column(link_name)
        target_object = str(link["to"]).split(".", 1)[1]
        target_table = table_name(other.name, target_object)
        link_rows.append(
            {
                "link": link_name,
                "column": column,
                "target": link["to"],
                "target_table": target_table,
                "enforced": f"FOREIGN KEY ({column}) REFERENCES {target_table}(object_uid)" in ddl,
            }
        )
    return {
        "name": pack.name,
        "path": str(destination),
        "installed": installed,
        "builds_on": base.name,
        "borrows_from": other.name,
        "anchor": anchor_name,
        "objects": chosen,
        "links": link_rows,
        "view": files["_view"],
        "example_capture": {
            "target": example_capture(other, chosen[0]),
            "anchor": example_capture(base, anchor_name),
        },
        "ddl": ddl,
    }


def describe(result: dict[str, Any]) -> str:
    """What happened, in plain words, with one capture to try."""
    lines: list[str] = []
    verb = "and turned it on" if result["installed"] else "on disk"
    lines.append(f"Made the pack {result['name']} {verb}.")
    lines.append(f"It is at {result['path']}.")
    lines.append("")
    lines.append(
        f"It keeps everything {result['builds_on']} already had, and it borrows "
        f"{', '.join(result['objects'])} from {result['borrows_from']}."
    )
    for row in result["links"]:
        lines.append("")
        lines.append(
            f"A {result['anchor']} record can now point at a {row['target']} record. "
            f"The pointer is called {row['link']} and it lives in the column "
            f"{row['column']}."
        )
        if row["enforced"]:
            lines.append(
                f"The database holds it: the column has a foreign key into "
                f"{row['target_table']}, so a pointer to a record that is not there "
                f"is refused, and deleting the {row['target']} record clears the "
                f"pointer instead of taking the {result['anchor']} record with it."
            )
        else:
            lines.append(
                f"Turn on {result['borrows_from']} to have the database hold this pointer for you."
            )
    lines.append("")
    lines.append(
        f"New view {result['view']['title']!r}: a list of {result['anchor']} records "
        f"showing the {result['borrows_from']} record each one points at."
    )
    lines.append("")
    lines.append("Try the join. Capture the two halves, then link them in the app:")
    lines.append(f'  domain-foundry capture "{result["example_capture"]["target"]}"')
    lines.append(f'  domain-foundry capture "{result["example_capture"]["anchor"]}"')
    return "\n".join(lines)


def register(app: typer.Typer) -> None:
    """Attach the `stack` verb. Called once by cli.py's lane registry."""

    @app.command("stack")
    def stack_cmd(
        base: str = typer.Argument(..., help="The pack to build on"),
        other: str = typer.Argument(..., help="The pack to borrow records from"),
        name: str | None = typer.Argument(None, help="Name for the new pack"),
        objects: str | None = typer.Option(
            None, "--objects", help="Comma-separated objects to borrow from the second pack"
        ),
        out: Path | None = typer.Option(
            None, "--out", help="Write the pack here instead of turning it on"
        ),
        home: Path | None = typer.Option(None, "--home", help="Workspace directory"),
        as_json: bool = typer.Option(False, "--json", help="Print the result as JSON"),
    ) -> None:
        """Put two packs together so records in one can point at records in the other."""
        picked = [part.strip() for part in objects.split(",") if part.strip()] if objects else None
        workspace = Workspace(home)
        if picked is None and out is None:
            picked = _ask_for_objects(workspace, base, other)
        try:
            result = stack_packs(base, other, name=name, objects=picked, home=home, out=out)
        except (StackError, PackValidationError) as exc:
            typer.secho(str(exc), err=True, fg=typer.colors.RED)
            raise typer.Exit(code=1) from exc
        if as_json:
            import json

            typer.echo(json.dumps(result, indent=2, sort_keys=True))
        else:
            typer.echo(describe(result))


def _ask_for_objects(workspace: Workspace, base_name: str, other_name: str) -> list[str] | None:
    """Ask which objects to borrow when the second pack has a lot of them."""
    registry = PackRegistry(workspace)
    base = registry.get_by_alias(base_name)
    other = registry.get_by_alias(other_name)
    if base is None or other is None:
        return None
    if default_objects(base, other):
        return None
    if len(other.objects) <= MAX_OBJECTS_WITHOUT_ASKING:
        return None
    names = sorted(other.objects)
    typer.echo(f"Pack {other.name} keeps {len(names)} kinds of record:")
    for object_name in names:
        typer.echo(f"  {object_name}")
    answer = typer.prompt("Which ones should the new pack point at? Separate them with commas")
    return [part.strip() for part in answer.split(",") if part.strip()] or None
