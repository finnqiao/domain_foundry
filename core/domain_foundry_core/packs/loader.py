"""Load and validate Domain Packs from directories / entry points."""

from __future__ import annotations

import importlib.metadata
import json
import os
import re
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any

import yaml
from packaging.requirements import Requirement
from packaging.specifiers import SpecifierSet
from packaging.version import Version

from domain_foundry_core import __version__ as CORE_VERSION
from domain_foundry_core.packs.models import (
    AgentSpec,
    DomainPack,
    FieldSpec,
    ImportedObject,
    LinkSpec,
    ObjectSpec,
    PackCompatibility,
    PackManifest,
    PolicyRow,
    PolicySpec,
    ProjectionsSpec,
    RoutingExample,
    RoutingRule,
    RoutingSpec,
    UIActionSpec,
    link_column,
)
from domain_foundry_core.paths import default_home, overlay_pack_dirs

REQUIRED_FILES = (
    "pack.yaml",
    "schema.yaml",
    "routing.yaml",
    "operations.yaml",
    "policy.yaml",
)
OPTIONAL_FILES = ("projections.yaml", "agent.yaml")

# Files which are part of the declarative pack format.  Unknown data files are
# allowed (authors often ship README/license material), but executable-looking
# files and symlinks are never trusted by the pack boundary.
KNOWN_DATA_FILES = {
    *REQUIRED_FILES,
    *OPTIONAL_FILES,
    "capabilities.yaml",
    "README.md",
    "LICENSE",
    "LICENSE.txt",
}
KNOWN_DATA_SUFFIXES = {".yaml", ".yml", ".json", ".jsonl", ".md", ".j2", ".txt", ".sql"}
FORBIDDEN_PACK_SUFFIXES = {
    ".py",
    ".pyc",
    ".js",
    ".mjs",
    ".cjs",
    ".ts",
    ".tsx",
    ".jsx",
    ".sh",
    ".bash",
    ".zsh",
    ".so",
    ".dylib",
    ".dll",
    ".exe",
}
ALLOWED_PACK_PERMISSIONS = {
    "data:own_tables",
    "projection:app",
    "projection:markdown",
    "capability:compare",
    "capability:derived_metrics",
    "capability:imports",
    "capability:media",
    "capability:schedules",
    "capability:sessions",
}
ALLOWED_PROJECTION_BLOCKS = {
    "capture_feed",
    "compare",
    "detail",
    "gallery",
    "history",
    "list",
    "map",
    "planner",
    "review_queue",
    "search",
    "stats",
    "timeline",
    # Slice 3's session surface is a first-party global projection.
    "quiz_stats",
}
ALLOWED_OPERATIONS = {"create", "update", "correct", "merge", "delete"}
ALLOWED_AGENT_TOOLS = {
    "capture",
    "query",
    "correct",
    "review_list",
    "review_resolve",
    "new_domain",
    "wizard_reply",
    "quiz_next",
    "quiz_grade",
}

# Declarative capabilities are a deliberately small, versioned alphabet. A
# pack that asks for a newer capability must fail validation rather than load
# with a silently degraded shell.
CAPABILITY_VERSIONS = {
    "derived_metrics": "1",
    "media": "1",
    "compare": "1",
    "imports": "1",
    "sessions": "1",
    "schedules": "1",
}

_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{1,62}$")
_REFERENTIAL_ACTION_RE = re.compile(
    r"\bON\s+(?:DELETE|UPDATE)\s+(?:SET\s+NULL|SET\s+DEFAULT|CASCADE|RESTRICT|NO\s+ACTION)\b",
    re.IGNORECASE,
)


class PackValidationError(ValueError):
    def __init__(self, errors: list[str]) -> None:
        self.errors = errors
        super().__init__("; ".join(errors))


def _read_yaml(path: Path) -> Any:
    if not path.exists():
        raise PackValidationError([f"missing file: {path.name}"])
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise PackValidationError([f"cannot read {path.name}: {exc}"]) from exc
    return data if data is not None else {}


def _parse_field(raw: dict[str, Any]) -> FieldSpec:
    return FieldSpec.model_validate(raw)


PackDirResolver = Callable[[str], "Path | None"]


def load_pack(
    root: Path,
    *,
    validate: bool = True,
    resolver: PackDirResolver | None = None,
) -> DomainPack:
    """Load one declarative pack and normalize parser failures.

    A pack is an untrusted directory.  Keeping all parser/model failures under
    ``PackValidationError`` gives CLI, registry, and conformance callers one
    truthful error contract instead of leaking a YAML/Pydantic traceback.

    ``resolver`` maps a pack name to its directory.  It is only consulted when
    the pack declares ``extends`` or ``imports``; a pack that declares neither
    loads exactly as it did before composition existed.
    """
    raw_root = Path(root).expanduser()
    if raw_root.is_symlink():
        raise PackValidationError(["pack root must not be a symlink"])
    try:
        return _load_pack(root, validate=validate, resolver=resolver)
    except PackValidationError:
        raise
    except Exception as exc:  # noqa: BLE001 - convert hostile pack input
        raise PackValidationError([f"invalid pack: {type(exc).__name__}: {exc}"]) from exc


def default_pack_resolver(root: Path | None = None) -> PackDirResolver:
    """Find a named pack next to ``root``, in the workspace, or in the bundle.

    Search order: sibling directories of ``root``, the workspace packs
    directory, any DOMAIN_FOUNDRY_PACKS_PATH overlay, then the bundled packs.
    """

    def _search_paths() -> list[Path]:
        paths: list[Path] = []
        if root is not None:
            paths.append(Path(root).resolve().parent)
        paths.append(default_home() / "packs")
        paths.extend(overlay_pack_dirs())
        paths.append(bundled_packs_root())
        return paths

    def _resolve(name: str) -> Path | None:
        for base in _search_paths():
            try:
                candidate = base / name
            except (OSError, ValueError):
                continue
            if candidate.is_dir() and (candidate / "pack.yaml").is_file():
                return candidate
        return None

    return _resolve


def resolver_for_packs(packs: dict[str, Path]) -> PackDirResolver:
    """A resolver over an explicit ``{pack name: directory}`` map."""

    def _resolve(name: str) -> Path | None:
        return packs.get(name)

    return _resolve


def _describe_search(root: Path) -> str:
    return (
        f"looked next to {root.parent}, in {default_home() / 'packs'}, "
        f"and in {bundled_packs_root()}"
    )


def _load_pack(
    root: Path,
    *,
    validate: bool = True,
    resolver: PackDirResolver | None = None,
    chain: tuple[str, ...] = (),
) -> DomainPack:
    root = root.resolve()
    if not root.is_dir():
        raise PackValidationError([f"pack directory not found: {root}"])
    errors: list[str] = []
    _validate_pack_tree(root, errors)
    for name in REQUIRED_FILES:
        if not (root / name).exists():
            errors.append(f"missing {name}")
    if errors:
        raise PackValidationError(errors)

    manifest = PackManifest.model_validate(_read_yaml(root / "pack.yaml"))
    schema_raw = _read_yaml(root / "schema.yaml")
    if not isinstance(schema_raw, dict):
        raise PackValidationError(["schema.yaml root must be a mapping"])
    objects_raw = schema_raw.get("objects") or {}
    if not isinstance(objects_raw, dict):
        raise PackValidationError(["schema.yaml objects must be a mapping"])
    objects: dict[str, ObjectSpec] = {}
    for obj_name, obj_body in objects_raw.items():
        if not isinstance(obj_name, str):
            raise PackValidationError(["schema object names must be strings"])
        if obj_body is not None and not isinstance(obj_body, dict):
            raise PackValidationError([f"schema object {obj_name!r} must be a mapping"])
        body = obj_body or {}
        raw_fields = body.get("fields") or {}
        raw_links = body.get("links") or {}
        if not isinstance(raw_fields, dict) or not isinstance(raw_links, dict):
            raise PackValidationError([f"schema object {obj_name!r} fields/links must be mappings"])
        fields = {
            fname: _parse_field(fbody if isinstance(fbody, dict) else {"type": "text"})
            for fname, fbody in raw_fields.items()
        }
        links = {lname: LinkSpec.model_validate(lbody) for lname, lbody in raw_links.items()}
        objects[obj_name] = ObjectSpec(
            title_field=body.get("title_field"),
            fields=fields,
            links=links,
        )

    routing_raw = _read_yaml(root / "routing.yaml")
    if not isinstance(routing_raw, dict):
        raise PackValidationError(["routing.yaml root must be a mapping"])
    examples = [
        RoutingExample.model_validate(e) if isinstance(e, dict) else RoutingExample(text=str(e))
        for e in (routing_raw.get("examples") or [])
    ]
    # Field type is list[RoutingExample | dict[str, Any]]; declare the union so
    # the list is not invariantly narrower than the parameter it feeds.
    negatives: list[RoutingExample | dict[str, Any]] = []
    for n in routing_raw.get("negative_examples") or []:
        if isinstance(n, dict):
            negatives.append(RoutingExample(text=n.get("text", ""), expect=n.get("expect") or {}))
        else:
            negatives.append(RoutingExample(text=str(n)))
    routing = RoutingSpec(
        rules=[RoutingRule.model_validate(r) for r in (routing_raw.get("rules") or [])],
        examples=examples,
        negative_examples=negatives,
        llm_hints=str(routing_raw.get("llm_hints") or ""),
    )

    operations_raw = _read_yaml(root / "operations.yaml")
    if not isinstance(operations_raw, dict):
        raise PackValidationError(["operations.yaml root must be a mapping"])
    operations = {str(k): list(v) for k, v in operations_raw.items()}

    policy_raw = _read_yaml(root / "policy.yaml")
    if not isinstance(policy_raw, dict):
        raise PackValidationError(["policy.yaml root must be a mapping"])
    policy = PolicySpec(
        defaults=[PolicyRow.model_validate(r) for r in (policy_raw.get("defaults") or [])],
        fallback=str(policy_raw.get("fallback") or "unfiled_card"),
        ui_actions=[UIActionSpec.model_validate(r) for r in (policy_raw.get("ui_actions") or [])],
    )

    proj_path = root / "projections.yaml"
    projections_raw = _read_yaml(proj_path) if proj_path.exists() else {}
    if not isinstance(projections_raw, dict):
        raise PackValidationError(["projections.yaml root must be a mapping"])
    projections = ProjectionsSpec.model_validate(projections_raw)

    capabilities_raw: dict[str, Any] = {}
    capabilities_path = root / "capabilities.yaml"
    if capabilities_path.exists():
        raw = _read_yaml(capabilities_path)
        if not isinstance(raw, dict):
            raise PackValidationError(["capabilities.yaml root must be a mapping"])
        capabilities_raw = raw
    capabilities = capabilities_raw.get("capabilities") or {}
    if not isinstance(capabilities, dict):
        raise PackValidationError(["capabilities must be a mapping"])
    compatibility = PackCompatibility.model_validate(capabilities_raw.get("compatibility") or {})

    agent: AgentSpec | None = None
    agent_path = root / "agent.yaml"
    if agent_path.exists():
        agent_raw = _read_yaml(agent_path)
        if not isinstance(agent_raw, dict):
            raise PackValidationError(["agent.yaml root must be a mapping"])
        # Accept either top-level `agent:` wrapper or a bare agent object.
        if isinstance(agent_raw, dict) and "agent" in agent_raw:
            agent_raw = agent_raw["agent"]
        agent = AgentSpec.model_validate(agent_raw or {})

    pack = DomainPack(
        root=root,
        manifest=manifest,
        objects=objects,
        routing=routing,
        operations=operations,
        policy=policy,
        projections=projections,
        capabilities={str(k): v for k, v in capabilities.items()},
        compatibility=compatibility,
        agent=agent,
    )
    pack = _compose(pack, resolver=resolver, chain=chain)
    _resolve_link_targets(pack, resolver=resolver)
    _add_link_columns(pack)
    if validate:
        validate_pack(pack)
    return pack


# ---------------------------------------------------------------------------
# Composition: extends and imports (docs/PACK_AUTHORING.md)
# ---------------------------------------------------------------------------


def _compose(
    pack: DomainPack,
    *,
    resolver: PackDirResolver | None,
    chain: tuple[str, ...],
) -> DomainPack:
    """Resolve ``extends`` and ``imports`` against other packs on disk."""
    if pack.manifest.extends is None and not pack.manifest.imports:
        return pack
    if pack.name in chain:
        loop = " extends ".join([*chain, pack.name])
        raise PackValidationError([f"pack composition goes in a circle: {loop}"])
    resolve = resolver or default_pack_resolver(pack.root)
    next_chain = (*chain, pack.name)

    if pack.manifest.extends is not None:
        parent_name = pack.manifest.extends
        if parent_name == pack.name:
            raise PackValidationError([f"pack {pack.name} cannot extend itself"])
        parent_dir = resolve(parent_name)
        if parent_dir is None:
            raise PackValidationError(
                [
                    f"pack {pack.name} extends {parent_name}, but {parent_name} is not "
                    f"installed here; {_describe_search(pack.root)}"
                ]
            )
        parent = _load_pack(parent_dir, validate=False, resolver=resolve, chain=next_chain)
        pack = _merge_parent(parent, pack)

    for spec in pack.manifest.imports:
        local = spec.local_name
        if spec.from_pack == pack.name:
            raise PackValidationError([f"pack {pack.name} cannot import {spec.target} from itself"])
        if local in pack.objects:
            raise PackValidationError(
                [
                    f"pack {pack.name} imports {spec.target} as {local!r}, but "
                    f"{pack.name} already has an object called {local!r}; "
                    f"give the import a different name with `as`"
                ]
            )
        if local in pack.imports:
            other = pack.imports[local].target
            raise PackValidationError(
                [
                    f"pack {pack.name} imports two objects under the name {local!r}: "
                    f"{other} and {spec.target}"
                ]
            )
        source_dir = resolve(spec.from_pack)
        if source_dir is None:
            raise PackValidationError(
                [
                    f"pack {pack.name} imports {spec.target}, but pack "
                    f"{spec.from_pack} is not installed here; "
                    f"{_describe_search(pack.root)}"
                ]
            )
        source = _load_pack(source_dir, validate=False, resolver=resolve, chain=next_chain)
        if spec.object not in source.objects:
            known = ", ".join(sorted(source.objects)) or "nothing"
            raise PackValidationError(
                [
                    f"pack {pack.name} imports {spec.target}, but pack "
                    f"{spec.from_pack} has no object called {spec.object!r}; "
                    f"it has {known}"
                ]
            )
        pack.imports[local] = ImportedObject(
            local_name=local,
            pack=source.name,
            object=spec.object,
            spec=source.objects[spec.object],
        )
    return pack


def _resolve_link_targets(pack: DomainPack, *, resolver: PackDirResolver | None) -> None:
    """Check every cross-pack link and record the ones we cannot check yet.

    A link into a pack that is installed here must name an object that pack
    really has.  A link into a pack that is not installed is recorded as a soft
    dependency: the pack still loads, and the compiler leaves the foreign key
    off until the other pack arrives.
    """
    wanted: dict[str, list[tuple[str, str, str]]] = {}
    for object_name, obj in pack.objects.items():
        for link_name, link in obj.links.items():
            target_pack, target_object = pack.link_target(link)
            if target_pack == pack.name:
                continue
            wanted.setdefault(target_pack, []).append((object_name, link_name, target_object))
    if not wanted:
        return
    resolve = resolver or default_pack_resolver(pack.root)
    errors: list[str] = []
    soft: list[str] = []
    for target_pack, uses in sorted(wanted.items()):
        source_dir = resolve(target_pack)
        if source_dir is None:
            for _object_name, _link_name, target_object in uses:
                soft.append(f"{target_pack}.{target_object}")
            continue
        try:
            other = _load_pack(source_dir, validate=False, resolver=resolve, chain=(pack.name,))
        except PackValidationError:
            for _object_name, _link_name, target_object in uses:
                soft.append(f"{target_pack}.{target_object}")
            continue
        for object_name, link_name, target_object in uses:
            if target_object not in other.objects:
                known = ", ".join(sorted(other.objects)) or "nothing"
                errors.append(
                    f"{object_name}.{link_name} points at "
                    f"{target_pack}.{target_object}, but pack {target_pack} has no "
                    f"object called {target_object!r}; it has {known}"
                )
    if errors:
        raise PackValidationError(errors)
    pack.soft_dependencies = sorted(set([*pack.soft_dependencies, *soft]))


def _merge_parent(parent: DomainPack, child: DomainPack) -> DomainPack:
    """Fold a parent pack into its child. The child wins on every key."""
    objects: dict[str, ObjectSpec] = {}
    for name, obj in parent.objects.items():
        objects[name] = obj.model_copy(deep=True)
    for name, obj in child.objects.items():
        base = objects.get(name)
        if base is None:
            objects[name] = obj
            continue
        objects[name] = ObjectSpec(
            title_field=obj.title_field or base.title_field,
            fields={**base.fields, **obj.fields},
            links={**base.links, **obj.links},
        )

    # The parent's objects are the child's objects now, so a link the parent
    # wrote as "parent.thing" has to point at the child's copy of that table.
    ancestors = {parent.name, *parent.inherits}
    for obj in objects.values():
        for link_name, link in list(obj.links.items()):
            target_pack, target_object = link.target_pack, link.target_object
            if target_pack in ancestors and target_object in objects:
                obj.links[link_name] = link.model_copy(
                    update={"to": f"{child.name}.{target_object}"}
                )

    routing = RoutingSpec(
        rules=[*child.routing.rules, *parent.routing.rules],
        examples=[*child.routing.examples, *parent.routing.examples],
        negative_examples=[
            *child.routing.negative_examples,
            *parent.routing.negative_examples,
        ],
        llm_hints=child.routing.llm_hints or parent.routing.llm_hints,
    )

    operations = {**parent.operations, **child.operations}

    # Policy is the child's own when the child declares one; a child that
    # declares no policy keeps the parent's.
    policy = child.policy
    if not child.policy.defaults and not child.policy.ui_actions:
        policy = parent.policy.model_copy(deep=True)

    parent_app = dict(parent.projections.app or {})
    child_app = dict(child.projections.app or {})
    views = [*(child_app.get("views") or []), *(parent_app.get("views") or [])]
    seen_view_ids: set[str] = set()
    merged_views: list[Any] = []
    for view in views:
        view_id = str(view.get("id")) if isinstance(view, dict) else None
        if view_id is not None:
            if view_id in seen_view_ids:
                continue
            seen_view_ids.add(view_id)
        merged_views.append(view)
    app = {**parent_app, **child_app}
    if merged_views:
        app["views"] = merged_views
    projections = ProjectionsSpec(
        app=app,
        markdown={**(parent.projections.markdown or {}), **(child.projections.markdown or {})},
    )

    manifest = child.manifest.model_copy(deep=True)
    manifest.permissions = sorted(
        set(parent.manifest.permissions) | set(child.manifest.permissions)
    )

    # An inherited agent takes the child's name: the agent manifest belongs to
    # whichever pack is being loaded, and every pack's agent is named after it.
    agent = child.agent
    if agent is None and parent.agent is not None:
        agent = parent.agent.model_copy(deep=True)
        agent.name = child.name

    return DomainPack(
        root=child.root,
        manifest=manifest,
        objects=objects,
        routing=routing,
        operations=operations,
        policy=policy,
        projections=projections,
        capabilities={**parent.capabilities, **child.capabilities},
        compatibility=child.compatibility,
        agent=agent,
        inherits=[*parent.inherits, parent.name],
        imports=dict(parent.imports),
        soft_dependencies=list(parent.soft_dependencies),
    )


def _add_link_columns(pack: DomainPack) -> None:
    """Give every link a real column so the schema can carry a foreign key.

    The column holds the target row's ``object_uid``.  It is a normal field
    from here on, so the apply engine writes it and the compiler emits it.
    """
    for object_name, obj in pack.objects.items():
        for link_name in list(obj.links):
            column = link_column(link_name)
            existing = obj.fields.get(column)
            if existing is not None and not getattr(existing, "_link_column", False):
                if existing.type != "text":
                    raise PackValidationError(
                        [
                            f"{object_name}.{link_name} needs a column called "
                            f"{column!r}, but {object_name} already declares a "
                            f"{existing.type} field with that name; rename one of them"
                        ]
                    )
                continue
            obj.fields[column] = FieldSpec(type="text")


def validate_pack(pack: DomainPack) -> None:
    errors: list[str] = []
    _validate_manifest(pack, errors)
    _validate_schema_relationships(pack, errors)
    if not _NAME_RE.match(pack.name):
        errors.append(f"invalid pack name {pack.name!r}")
    try:
        Version(pack.version)
    except Exception:
        errors.append(f"invalid semver version {pack.version!r}")
    try:
        req = Requirement(f"domain-foundry-core{pack.manifest.core_compat}")
        if not req.specifier.contains(CORE_VERSION, prereleases=True):
            errors.append(
                f"core {CORE_VERSION} does not satisfy core_compat {pack.manifest.core_compat}"
            )
    except Exception as exc:
        errors.append(f"invalid core_compat: {exc}")

    declared_core = pack.compatibility.core or pack.manifest.core_compat
    try:
        if not SpecifierSet(declared_core).contains(CORE_VERSION, prereleases=True):
            errors.append(
                f"core {CORE_VERSION} does not satisfy capability compatibility {declared_core}"
            )
    except Exception as exc:
        errors.append(f"invalid capability core compatibility: {exc}")

    for capability, spec in pack.capabilities.items():
        supported = CAPABILITY_VERSIONS.get(capability)
        if supported is None:
            errors.append(f"unsupported capability {capability!r}")
            continue
        if not isinstance(spec, dict):
            errors.append(f"capability {capability!r} must be a mapping")
            continue
        version = str(spec.get("version") or "1")
        try:
            if Version(version) > Version(supported):
                errors.append(
                    f"capability {capability!r} version {version} is newer than supported {supported}"
                )
        except Exception as exc:
            errors.append(f"capability {capability!r} has invalid version {version!r}: {exc}")
        requirement = pack.compatibility.capabilities.get(capability)
        if requirement:
            try:
                if not SpecifierSet(requirement).contains(Version(supported), prereleases=True):
                    errors.append(
                        f"capability {capability!r} compatibility {requirement!r} "
                        f"does not include supported version {supported}"
                    )
            except Exception as exc:
                errors.append(
                    f"capability {capability!r} has invalid compatibility {requirement!r}: {exc}"
                )

        if capability == "derived_metrics":
            _validate_derived_metrics(spec, pack, errors)
        elif capability == "media":
            _validate_media(spec, pack, errors)
        elif capability == "compare":
            _validate_compare(spec, pack, errors)
        elif capability == "imports":
            _validate_imports(spec, pack, errors)

    if len(pack.routing.examples) < 8:
        errors.append(f"need ≥8 routing examples, found {len(pack.routing.examples)}")
    if len(pack.routing.negative_examples) < 2:
        errors.append(f"need ≥2 negative examples, found {len(pack.routing.negative_examples)}")

    for i, rule in enumerate(pack.routing.rules):
        try:
            re.compile(rule.match)
        except re.error as exc:
            errors.append(f"rules[{i}] invalid regex: {exc}")
        if rule.object not in pack.objects:
            errors.append(f"rules[{i}] object {rule.object!r} not in schema")
        if rule.operation not in ALLOWED_OPERATIONS:
            errors.append(f"rules[{i}] unknown operation {rule.operation!r}")
        if rule.tier is not None and rule.tier not in {"routine", "sota"}:
            errors.append(f"rules[{i}] unknown model tier {rule.tier!r}")

    for obj_name, ops in pack.operations.items():
        if obj_name not in pack.objects:
            errors.append(f"operations key {obj_name!r} not in schema")
        if not isinstance(ops, list):
            errors.append(f"operations for {obj_name!r} must be a list")
            continue
        for op in ops:
            if op not in ALLOWED_OPERATIONS:
                errors.append(f"unknown operation {op!r} on {obj_name}")

    for i, action in enumerate(pack.policy.ui_actions):
        if action.object_type not in pack.objects:
            errors.append(
                f"policy.ui_actions[{i}] object_type {action.object_type!r} not in schema"
            )
            continue
        if action.operation not in pack.operations.get(action.object_type, []):
            errors.append(
                f"policy.ui_actions[{i}] operation {action.operation!r} not allowed "
                f"for {action.object_type}"
            )
        field_names = set(pack.objects[action.object_type].fields)
        for field in action.fields:
            if field not in field_names:
                errors.append(
                    f"policy.ui_actions[{i}] field {field!r} not in {action.object_type} schema"
                )
        if len(action.fields) != len(set(action.fields)):
            errors.append(f"policy.ui_actions[{i}] fields must be unique")

    for obj_name, obj in pack.objects.items():
        if obj_name not in pack.operations:
            errors.append(f"object {obj_name!r} missing from operations.yaml")
        for fname, fspec in obj.fields.items():
            if fspec.type == "enum" and not fspec.values:
                errors.append(f"{obj_name}.{fname}: enum requires values")

    if pack.agent is not None and pack.agent.name and pack.agent.name != pack.name:
        errors.append(f"agent.name {pack.agent.name!r} must match pack name {pack.name!r}")

    _validate_policy_relationships(pack, errors)
    _validate_projection_relationships(pack, errors)
    _validate_agent_relationships(pack, errors)
    _validate_migration_files(pack, errors)
    _validate_eval_files(pack, errors)
    _replay_routing_examples(pack, errors)

    if errors:
        raise PackValidationError(errors)


def _validate_pack_tree(root: Path, errors: list[str]) -> None:
    """Reject symlinks and executable-looking content before parsing a pack."""
    if root.is_symlink():
        errors.append("pack root must not be a symlink")
        return
    try:
        for current, dirs, files in os.walk(root, followlinks=False):
            current_path = Path(current)
            for name in [*dirs, *files]:
                path = current_path / name
                if path.is_symlink():
                    errors.append(f"symlinks are not allowed: {path.relative_to(root)}")
            for name in files:
                path = current_path / name
                suffix = path.suffix.lower()
                if suffix in FORBIDDEN_PACK_SUFFIXES:
                    errors.append(
                        f"executable pack content is not allowed: {path.relative_to(root)}"
                    )
                if (
                    suffix
                    and suffix not in KNOWN_DATA_SUFFIXES
                    and path.name not in KNOWN_DATA_FILES
                ):
                    # Binary media may be useful as a gallery fixture, so this
                    # is a warning-level omission rather than a rejection. The
                    # executable suffix deny-list above remains strict.
                    continue
                try:
                    if path.stat().st_size > 10 * 1024 * 1024:
                        errors.append(f"pack file is too large (>10 MiB): {path.relative_to(root)}")
                except OSError as exc:
                    errors.append(f"cannot inspect pack file {path.relative_to(root)}: {exc}")
    except OSError as exc:
        errors.append(f"cannot inspect pack tree: {exc}")


def _validate_manifest(pack: DomainPack, errors: list[str]) -> None:
    aliases = pack.manifest.aliases
    if len(aliases) != len(set(aliases)):
        errors.append("manifest aliases must be unique")
    for alias in aliases:
        if not isinstance(alias, str) or not alias.strip() or any(ord(c) < 32 for c in alias):
            errors.append(f"invalid manifest alias {alias!r}")
    permissions = pack.manifest.permissions
    for permission in permissions:
        if permission not in ALLOWED_PACK_PERMISSIONS:
            errors.append(
                f"unsupported permission {permission!r}; packs cannot request network, code, or ambient credentials"
            )
    if permissions:
        required = {"data:own_tables"}
        if pack.projections.app:
            required.add("projection:app")
        if pack.projections.markdown:
            required.add("projection:markdown")
        required.update(f"capability:{name}" for name in pack.capabilities)
        missing = sorted(required - set(permissions))
        if missing:
            errors.append(f"manifest permissions omit declared surfaces: {', '.join(missing)}")


def _validate_schema_relationships(pack: DomainPack, errors: list[str]) -> None:
    if not pack.objects:
        errors.append("schema must declare at least one object")
    for object_name, obj in pack.objects.items():
        if not _NAME_RE.match(object_name):
            errors.append(f"invalid object name {object_name!r}")
        if obj.title_field is not None and obj.title_field not in obj.fields:
            errors.append(f"{object_name}.title_field {obj.title_field!r} not in fields")
        for field_name, field in obj.fields.items():
            if not isinstance(field_name, str) or not _NAME_RE.match(field_name):
                errors.append(f"invalid field name {object_name}.{field_name!r}")
            if field.min is not None and field.max is not None and field.min > field.max:
                errors.append(f"{object_name}.{field_name}: min must not exceed max")
            if (
                field.type == "enum"
                and field.values
                and len(field.values) != len(set(field.values))
            ):
                errors.append(f"{object_name}.{field_name}: enum values must be unique")
        for link_name, link in obj.links.items():
            if not _NAME_RE.match(link_name):
                errors.append(f"invalid link name {object_name}.{link_name!r}")
            target_domain, target_object = pack.link_target(link)
            if target_domain != pack.name:
                # Cross-pack links are resolved at load time against the packs
                # installed here (see _resolve_link_targets); a target pack that
                # is not installed is a recorded soft dependency, not an error.
                pass
            elif target_object not in pack.objects:
                errors.append(f"{object_name}.{link_name}: link target {link.to!r} not in schema")
            if link.cardinality not in {"one_to_one", "one_to_many", "many_to_one", "many_to_many"}:
                errors.append(
                    f"{object_name}.{link_name}: invalid cardinality {link.cardinality!r}"
                )


def _validate_policy_relationships(pack: DomainPack, errors: list[str]) -> None:
    allowed_actions = {"auto_apply", "review", "confirm", "reject"}
    if pack.policy.fallback not in {"unfiled_card", "ledger_only", "review"}:
        errors.append(f"unsupported policy fallback {pack.policy.fallback!r}")
    for index, row in enumerate(pack.policy.defaults):
        if row.action not in allowed_actions:
            errors.append(f"policy.defaults[{index}] has unknown action {row.action!r}")
        if (
            row.operation is not None
            and row.operation not in ALLOWED_OPERATIONS
            and row.operation != "*"
        ):
            errors.append(f"policy.defaults[{index}] has unknown operation {row.operation!r}")
        if (
            row.object_type is not None
            and row.object_type not in pack.objects
            and row.object_type != "*"
        ):
            errors.append(f"policy.defaults[{index}] object {row.object_type!r} not in schema")
        if row.min_confidence is not None and not 0 <= row.min_confidence <= 1:
            errors.append(f"policy.defaults[{index}] min_confidence must be between 0 and 1")


def _validate_projection_relationships(pack: DomainPack, errors: list[str]) -> None:
    app = pack.projections.app or {}
    views = app.get("views") or []
    if not isinstance(views, list):
        errors.append("projections.app.views must be a list")
        views = []
    view_ids: set[str] = set()
    derived_ids = {
        str(metric.get("id"))
        for metric in (pack.capabilities.get("derived_metrics", {}).get("metrics") or [])
        if isinstance(metric, dict)
    }
    compare_ids = {
        str(comparison.get("id"))
        for comparison in (pack.capabilities.get("compare", {}).get("comparisons") or [])
        if isinstance(comparison, dict)
    }
    gallery_ids = {
        str(gallery.get("id"))
        for gallery in (pack.capabilities.get("media", {}).get("galleries") or [])
        if isinstance(gallery, dict)
    }
    for index, view in enumerate(views):
        if not isinstance(view, dict):
            errors.append(f"projections.app.views[{index}] must be a mapping")
            continue
        view_id = str(view.get("id") or "")
        if not view_id or view_id in view_ids:
            errors.append(f"projections.app.views[{index}] id must be non-empty and unique")
        view_ids.add(view_id)
        block = str(view.get("block") or "list")
        if block not in ALLOWED_PROJECTION_BLOCKS:
            errors.append(f"projections.app.views[{index}] block {block!r} is not a core block")
        targets = view.get("objects") or (
            [] if view.get("object") is None else [view.get("object")]
        )
        global_block = block in {"capture_feed", "review_queue", "quiz_stats"}
        if not isinstance(targets, list) or (not targets and not global_block):
            errors.append(f"projections.app.views[{index}] must declare object or objects")
            targets = []
        for target in targets:
            if target not in pack.objects:
                errors.append(f"projections.app.views[{index}] object {target!r} not in schema")
        config = view.get("config") or {}
        if not isinstance(config, dict):
            errors.append(f"projections.app.views[{index}] config must be a mapping")
            config = {}
        if block == "gallery" and str(config.get("gallery") or "") not in gallery_ids:
            errors.append(
                f"projections.app.views[{index}] gallery is not declared by media capability"
            )
        if block == "compare" and str(config.get("comparison") or "") not in compare_ids:
            errors.append(
                f"projections.app.views[{index}] comparison is not declared by compare capability"
            )
        if len(targets) == 1 and targets[0] in pack.objects:
            fields = set(pack.objects[targets[0]].fields)
            for key in ("date_field", "group_by", "media_field", "status_field"):
                value = config.get(key)
                if value is not None and value not in fields:
                    errors.append(
                        f"projections.app.views[{index}] {key} {value!r} not in {targets[0]} schema"
                    )
            for key in ("columns", "facets"):
                values = config.get(key) or []
                if not isinstance(values, list):
                    errors.append(f"projections.app.views[{index}] {key} must be a list")
                else:
                    for value in values:
                        if value not in fields and value not in derived_ids:
                            errors.append(
                                f"projections.app.views[{index}] {key} field {value!r} not declared"
                            )
            for measure_index, measure in enumerate(config.get("measures") or []):
                if not isinstance(measure, dict):
                    errors.append(
                        f"projections.app.views[{index}] measures[{measure_index}] must be a mapping"
                    )
                    continue
                field = measure.get("field")
                if field not in fields and field not in derived_ids:
                    errors.append(
                        f"projections.app.views[{index}] measure field {field!r} not declared"
                    )
            for action_index, action in enumerate(config.get("actions") or []):
                if not isinstance(action, dict):
                    errors.append(
                        f"projections.app.views[{index}] actions[{action_index}] must be a mapping"
                    )
                    continue
                operation = action.get("operation")
                action_fields = action.get("fields") or []
                if not pack.policy.allows_ui_action(
                    object_type=targets[0],
                    operation=str(operation),
                    fields={str(f): None for f in action_fields},
                ):
                    errors.append(
                        f"projections.app.views[{index}] action {operation!r}/{action_fields!r} is not policy-declared"
                    )

    markdown = pack.projections.markdown or {}
    folder = markdown.get("folder")
    if folder is not None and not _safe_relative_path(str(folder)):
        errors.append(f"markdown.folder is unsafe: {folder!r}")
    templates = markdown.get("note_template") or {}
    if isinstance(templates, dict):
        for object_type, template in templates.items():
            if object_type not in pack.objects:
                errors.append(f"markdown template object {object_type!r} not in schema")
            if not isinstance(template, str) or not _safe_relative_path(template):
                errors.append(f"markdown template for {object_type!r} has unsafe path")
            elif not (pack.root / template).is_file():
                errors.append(f"markdown template missing: {template}")


def _validate_agent_relationships(pack: DomainPack, errors: list[str]) -> None:
    if pack.agent is None:
        return
    for tool in pack.agent.tools:
        if tool not in ALLOWED_AGENT_TOOLS:
            errors.append(f"agent tool {tool!r} is not a core adapter tool")
    session_ids = {session.id for session in pack.agent.sessions}
    schedule_ids = {schedule.id for schedule in pack.agent.schedules}
    if len(session_ids) != len(pack.agent.sessions):
        errors.append("agent session ids must be unique")
    if len(schedule_ids) != len(pack.agent.schedules):
        errors.append("agent schedule ids must be unique")
    for schedule in pack.agent.schedules:
        if not _NAME_RE.match(schedule.id):
            errors.append(f"invalid agent schedule id {schedule.id!r}")
    for session in pack.agent.sessions:
        if not _NAME_RE.match(session.id):
            errors.append(f"invalid agent session id {session.id!r}")
    for capability_name, key, ids in (
        ("sessions", "agent_session", session_ids),
        ("schedules", "agent_schedule", schedule_ids),
    ):
        declaration = pack.capabilities.get(capability_name) or {}
        if declaration and declaration.get(key) and declaration[key] not in ids:
            errors.append(
                f"{capability_name} capability references unknown {key} {declaration[key]!r}"
            )


def _validate_migration_files(pack: DomainPack, errors: list[str]) -> None:
    migration_dir = pack.root / "migrations"
    if not migration_dir.exists():
        return
    if not migration_dir.is_dir():
        errors.append("migrations must be a directory")
        return
    for path in sorted(migration_dir.rglob("*")):
        if path.is_symlink():
            errors.append(f"migration symlink is not allowed: {path.relative_to(pack.root)}")
            continue
        if not path.is_file() or path.suffix.lower() != ".sql":
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            errors.append(f"cannot read migration {path.name}: {exc}")
            continue
        for statement in _sql_statements(text):
            normalized = re.sub(
                r"^\s*(?:--[^\n]*\n|/\*.*?\*/\s*)*", "", statement, flags=re.DOTALL
            ).strip()
            if not normalized:
                continue
            # The compiler prefixes generated migrations with this harmless
            # connection-local guard.  Keep the migration boundary strict
            # while allowing the compiler's own output to round-trip.
            if re.fullmatch(r"PRAGMA\s+foreign_keys\s*=\s*ON", normalized, re.IGNORECASE):
                continue
            if not re.match(
                r"^(?:CREATE\s+(?:TABLE|INDEX)|ALTER\s+TABLE)\b", normalized, re.IGNORECASE
            ):
                errors.append(f"migration {path.name} contains a non-declarative statement")
            # A foreign key's referential action spells out what happens when
            # the row it points at goes away.  Those fixed phrases are part of
            # the constraint, not a statement that deletes or updates anything,
            # so take them out before looking for destructive verbs.
            scanned = _REFERENTIAL_ACTION_RE.sub(" ", normalized)
            if re.search(
                r"\b(DROP|DELETE|UPDATE|INSERT|REPLACE|ATTACH|DETACH|VACUUM)\b",
                scanned,
                re.IGNORECASE,
            ):
                errors.append(f"migration {path.name} contains a destructive or external SQL verb")


def _validate_eval_files(pack: DomainPack, errors: list[str]) -> None:
    fixture = pack.root / "evals" / "fixtures.jsonl"
    if fixture.is_symlink():
        errors.append("eval fixture must not be a symlink")
    if fixture.exists():
        try:
            lines = fixture.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeError) as exc:
            errors.append(f"cannot read eval fixture: {exc}")
            lines = []
        for index, line in enumerate(lines, start=1):
            if not line.strip():
                continue
            try:
                case = json.loads(line)
            except json.JSONDecodeError as exc:
                errors.append(f"evals/fixtures.jsonl:{index}: invalid JSON: {exc.msg}")
                continue
            if not isinstance(case, dict) or not isinstance(case.get("raw_text"), str):
                errors.append(f"evals/fixtures.jsonl:{index}: case needs string raw_text")
                continue
            expected = case.get("expected") or {}
            for capture in expected.get("captures") or []:
                if not isinstance(capture, dict):
                    errors.append(f"evals/fixtures.jsonl:{index}: capture must be a mapping")
                    continue
                capture_domain = capture.get("domain", pack.name)
                if not isinstance(capture_domain, str) or not capture_domain:
                    errors.append(f"evals/fixtures.jsonl:{index}: capture domain must be a string")
                object_type = capture.get("object_type")
                # Cross-domain fixture cases intentionally leave the object
                # type to the receiving pack and assert the relationship at
                # the fixture level (e.g. travel ↔ food).
                if object_type is None:
                    continue
                if capture_domain != pack.name:
                    continue
                if object_type not in pack.objects:
                    errors.append(f"evals/fixtures.jsonl:{index}: unknown object {object_type!r}")
                if capture.get("operation", "create") not in ALLOWED_OPERATIONS:
                    errors.append(f"evals/fixtures.jsonl:{index}: unknown operation")

    for capability in (pack.capabilities.get("imports") or {}).get("mappings") or []:
        fixture_ref = capability.get("fixture") if isinstance(capability, dict) else None
        if not fixture_ref or not _safe_relative_path(str(fixture_ref)):
            errors.append("imports fixture path must be relative and safe")
        elif not (pack.root / str(fixture_ref)).exists():
            errors.append(f"imports fixture missing: {fixture_ref}")


def _replay_routing_examples(pack: DomainPack, errors: list[str]) -> None:
    """Replay the deterministic L1 routing contract without touching a DB.

    Structured packs intentionally escalate to the bounded interpreter, so a
    negative may contain a domain keyword as long as it cannot auto-apply at
    L1. Simple packs must keep negatives completely outside their rule set.
    """
    from domain_foundry_core.routing.l1 import L1Matcher

    matcher = L1Matcher([pack])
    for index, example in enumerate(pack.routing.examples):
        result = matcher.match(example.text)
        expected = example.expect or {}
        expected_object = expected.get("object")
        expected_operation = expected.get("operation", "create")
        matching = [hit for hit in result.hits if hit.object_type == expected_object]
        if expected_object and not matching:
            errors.append(f"routing.examples[{index}] does not route to {expected_object!r}")
        if expected_object in pack.objects and expected_operation not in pack.operations.get(
            expected_object, []
        ):
            errors.append(
                f"routing.examples[{index}] operation {expected_operation!r} is not allowed for {expected_object!r}"
            )
        if expected_object in pack.objects:
            for field in expected.get("fields") or {}:
                if field not in pack.objects[expected_object].fields:
                    errors.append(
                        f"routing.examples[{index}] field {field!r} not in {expected_object} schema"
                    )

    for index, raw in enumerate(pack.routing.negative_examples):
        example = raw if isinstance(raw, RoutingExample) else RoutingExample.model_validate(raw)
        result = matcher.match(example.text)
        expected = example.expect or {}
        if expected.get("unmatched") is True and result.hits:
            errors.append(f"routing.negative_examples[{index}] unexpectedly matches a rule")
        # Legacy packs contain semantic negatives without an explicit replay
        # assertion. New author packs should use ``expect: {unmatched: true}``
        # when the negative is required to stay outside the rule set.


def _safe_relative_path(value: str) -> bool:
    if not value or "\x00" in value or "\\" in value:
        return False
    path = Path(value)
    return not path.is_absolute() and ".." not in path.parts


def _sql_statements(text: str) -> list[str]:
    # Pack migrations are generated/simple SQL; reject NULs and split on the
    # only statement separator supported by that format.
    if "\x00" in text:
        return [text]
    return text.split(";")


def _validate_derived_metrics(spec: dict[str, Any], pack: DomainPack, errors: list[str]) -> None:
    object_type = spec.get("object")
    if object_type not in pack.objects:
        errors.append(f"derived_metrics object {object_type!r} not in schema")
        return
    metrics = spec.get("metrics") or []
    if not isinstance(metrics, list) or not metrics:
        errors.append("derived_metrics requires a non-empty metrics list")
        return
    ids: set[str] = set()
    fields = set(pack.objects[object_type].fields)
    for index, metric in enumerate(metrics):
        if not isinstance(metric, dict):
            errors.append(f"derived_metrics.metrics[{index}] must be a mapping")
            continue
        metric_id = str(metric.get("id") or "")
        if not metric_id or not _NAME_RE.match(metric_id):
            errors.append(f"derived_metrics.metrics[{index}] has invalid id {metric_id!r}")
        if metric_id in ids:
            errors.append(f"derived_metrics metric id {metric_id!r} is duplicated")
        ids.add(metric_id)
        if not metric.get("expression") and not metric.get("operation"):
            errors.append(f"derived_metrics metric {metric_id!r} needs expression or operation")
        for field in metric.get("fields") or []:
            if field not in fields:
                errors.append(f"derived_metrics metric {metric_id!r} field {field!r} not in schema")


def _validate_media(spec: dict[str, Any], pack: DomainPack, errors: list[str]) -> None:
    galleries = spec.get("galleries") or []
    if not isinstance(galleries, list) or not galleries:
        errors.append("media requires a non-empty galleries list")
        return
    for index, gallery in enumerate(galleries):
        if not isinstance(gallery, dict):
            errors.append(f"media.galleries[{index}] must be a mapping")
            continue
        object_type = gallery.get("object")
        if object_type not in pack.objects:
            errors.append(f"media gallery object {object_type!r} not in schema")
            continue
        field = gallery.get("field")
        if field and field not in pack.objects[object_type].fields:
            errors.append(f"media gallery field {field!r} not in {object_type} schema")


def _validate_compare(spec: dict[str, Any], pack: DomainPack, errors: list[str]) -> None:
    comparisons = spec.get("comparisons") or []
    if not isinstance(comparisons, list) or not comparisons:
        errors.append("compare requires a non-empty comparisons list")
        return
    metric_ids = {
        str(metric.get("id"))
        for metric in (pack.capabilities.get("derived_metrics", {}).get("metrics") or [])
        if isinstance(metric, dict)
    }
    for index, comparison in enumerate(comparisons):
        if not isinstance(comparison, dict):
            errors.append(f"compare.comparisons[{index}] must be a mapping")
            continue
        object_type = comparison.get("object")
        if object_type not in pack.objects:
            errors.append(f"compare comparison object {object_type!r} not in schema")
        for metric in comparison.get("metrics") or []:
            if metric not in metric_ids:
                errors.append(f"compare metric {metric!r} is not a declared derived metric")


def _validate_imports(spec: dict[str, Any], pack: DomainPack, errors: list[str]) -> None:
    mappings = spec.get("mappings") or []
    if not isinstance(mappings, list) or not mappings:
        errors.append("imports requires a non-empty mappings list")
        return
    for index, mapping in enumerate(mappings):
        if not isinstance(mapping, dict):
            errors.append(f"imports.mappings[{index}] must be a mapping")
            continue
        for entity in mapping.get("entities") or []:
            if not isinstance(entity, dict):
                errors.append(f"imports.mappings[{index}] entity must be a mapping")
                continue
            object_type = entity.get("object_type")
            if entity.get("domain", pack.name) != pack.name:
                errors.append(f"imports entity domain must be {pack.name!r}")
            if object_type not in pack.objects:
                errors.append(f"imports entity object_type {object_type!r} not in schema")


def discover_pack_dirs(search_paths: list[Path]) -> list[Path]:
    """Find pack roots under each search path.

    A search path may be:
    - a catalog directory whose immediate children are packs (have pack.yaml), or
    - a single pack directory that itself contains pack.yaml.
    """
    found: list[Path] = []
    seen: set[Path] = set()

    def _add(candidate: Path) -> None:
        resolved = candidate.resolve()
        if resolved not in seen:
            seen.add(resolved)
            found.append(resolved)

    for base in search_paths:
        if not base.is_dir():
            continue
        if (base / "pack.yaml").exists():
            _add(base)
            continue
        for child in sorted(base.iterdir()):
            if not child.is_dir() or child.name.startswith(("_", ".")):
                continue
            if (child / "pack.yaml").exists():
                _add(child)
    return found


def discover_entry_point_packs() -> list[Path]:
    """Packs registered via the ``domain_foundry.packs`` entry-point group."""
    paths: list[Path] = []
    try:
        eps = importlib.metadata.entry_points(group="domain_foundry.packs")
    except Exception:
        return paths
    for ep in eps:
        try:
            target = ep.load()
            # ep.load() is typed `object`: an entry point may resolve to a path
            # string or to a callable returning one. Stringify either way.
            path = Path(str(target() if callable(target) else target))
            if path.is_dir() and (path / "pack.yaml").exists():
                paths.append(path.resolve())
        except Exception:
            continue
    return paths


def install_pack(src: Path, dest_dir: Path, *, force: bool = False) -> DomainPack:
    """Copy a pack directory into dest_dir/<name>/ after validation."""
    pack = load_pack(src, validate=True)
    dest = dest_dir / pack.name
    if dest.exists():
        if not force:
            raise FileExistsError(f"pack already installed: {dest}")
        shutil.rmtree(dest)
    dest_dir.mkdir(parents=True, exist_ok=True)
    shutil.copytree(src, dest)
    return load_pack(dest, validate=True)


def bundled_packs_root() -> Path:
    """Repo/bundled packs shipped with the checkout (dev) or wheel data."""
    # core/domain_foundry_core/packs/loader.py → repo packs/ is parents[3]/packs
    repo_packs = Path(__file__).resolve().parents[3] / "packs"
    if repo_packs.is_dir():
        return repo_packs
    return Path(__file__).resolve().parent / "_bundled"
