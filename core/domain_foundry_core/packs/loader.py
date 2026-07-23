"""Load and validate Domain Packs from directories / entry points."""

from __future__ import annotations

import importlib.metadata
import re
import shutil
from pathlib import Path
from typing import Any

import yaml
from packaging.requirements import Requirement
from packaging.version import Version

from domain_foundry_core import __version__ as CORE_VERSION
from domain_foundry_core.packs.models import (
    AgentSpec,
    DomainPack,
    FieldSpec,
    LinkSpec,
    ObjectSpec,
    PackManifest,
    PolicyRow,
    PolicySpec,
    ProjectionsSpec,
    RoutingExample,
    RoutingRule,
    RoutingSpec,
)

REQUIRED_FILES = (
    "pack.yaml",
    "schema.yaml",
    "routing.yaml",
    "operations.yaml",
    "policy.yaml",
)
OPTIONAL_FILES = ("projections.yaml", "agent.yaml")

_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{1,62}$")


class PackValidationError(ValueError):
    def __init__(self, errors: list[str]) -> None:
        self.errors = errors
        super().__init__("; ".join(errors))


def _read_yaml(path: Path) -> Any:
    if not path.exists():
        raise PackValidationError([f"missing file: {path.name}"])
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return data if data is not None else {}


def _parse_field(raw: dict[str, Any]) -> FieldSpec:
    return FieldSpec.model_validate(raw)


def load_pack(root: Path, *, validate: bool = True) -> DomainPack:
    root = root.resolve()
    errors: list[str] = []
    for name in REQUIRED_FILES:
        if not (root / name).exists():
            errors.append(f"missing {name}")
    if errors:
        raise PackValidationError(errors)

    manifest = PackManifest.model_validate(_read_yaml(root / "pack.yaml"))
    schema_raw = _read_yaml(root / "schema.yaml")
    objects_raw = schema_raw.get("objects") or {}
    objects: dict[str, ObjectSpec] = {}
    for obj_name, obj_body in objects_raw.items():
        body = obj_body or {}
        fields = {
            fname: _parse_field(fbody if isinstance(fbody, dict) else {"type": "text"})
            for fname, fbody in (body.get("fields") or {}).items()
        }
        links = {
            lname: LinkSpec.model_validate(lbody)
            for lname, lbody in (body.get("links") or {}).items()
        }
        objects[obj_name] = ObjectSpec(
            title_field=body.get("title_field"),
            fields=fields,
            links=links,
        )

    routing_raw = _read_yaml(root / "routing.yaml")
    examples = [
        RoutingExample.model_validate(e) if isinstance(e, dict) else RoutingExample(text=str(e))
        for e in (routing_raw.get("examples") or [])
    ]
    negatives: list[RoutingExample] = []
    for n in routing_raw.get("negative_examples") or []:
        if isinstance(n, dict):
            negatives.append(
                RoutingExample(text=n.get("text", ""), expect=n.get("expect") or {})
            )
        else:
            negatives.append(RoutingExample(text=str(n)))
    routing = RoutingSpec(
        rules=[RoutingRule.model_validate(r) for r in (routing_raw.get("rules") or [])],
        examples=examples,
        negative_examples=negatives,
        llm_hints=str(routing_raw.get("llm_hints") or ""),
    )

    operations_raw = _read_yaml(root / "operations.yaml")
    operations = {str(k): list(v) for k, v in operations_raw.items()}

    policy_raw = _read_yaml(root / "policy.yaml")
    policy = PolicySpec(
        defaults=[PolicyRow.model_validate(r) for r in (policy_raw.get("defaults") or [])],
        fallback=str(policy_raw.get("fallback") or "unfiled_card"),
    )

    proj_path = root / "projections.yaml"
    projections = (
        ProjectionsSpec.model_validate(_read_yaml(proj_path))
        if proj_path.exists()
        else ProjectionsSpec()
    )

    agent: AgentSpec | None = None
    agent_path = root / "agent.yaml"
    if agent_path.exists():
        agent_raw = _read_yaml(agent_path)
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
        agent=agent,
    )
    if validate:
        validate_pack(pack)
    return pack


def validate_pack(pack: DomainPack) -> None:
    errors: list[str] = []
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

    if len(pack.routing.examples) < 8:
        errors.append(f"need ≥8 routing examples, found {len(pack.routing.examples)}")
    if len(pack.routing.negative_examples) < 2:
        errors.append(
            f"need ≥2 negative examples, found {len(pack.routing.negative_examples)}"
        )

    for i, rule in enumerate(pack.routing.rules):
        try:
            re.compile(rule.match)
        except re.error as exc:
            errors.append(f"rules[{i}] invalid regex: {exc}")
        if rule.object not in pack.objects:
            errors.append(f"rules[{i}] object {rule.object!r} not in schema")

    for obj_name, ops in pack.operations.items():
        if obj_name not in pack.objects:
            errors.append(f"operations key {obj_name!r} not in schema")
        for op in ops:
            if op not in {"create", "update", "correct", "merge", "delete"}:
                errors.append(f"unknown operation {op!r} on {obj_name}")

    for obj_name, obj in pack.objects.items():
        if obj_name not in pack.operations:
            errors.append(f"object {obj_name!r} missing from operations.yaml")
        for fname, fspec in obj.fields.items():
            if fspec.type == "enum" and not fspec.values:
                errors.append(f"{obj_name}.{fname}: enum requires values")

    if pack.agent is not None and pack.agent.name and pack.agent.name != pack.name:
        errors.append(
            f"agent.name {pack.agent.name!r} must match pack name {pack.name!r}"
        )

    if errors:
        raise PackValidationError(errors)


def discover_pack_dirs(search_paths: list[Path]) -> list[Path]:
    found: list[Path] = []
    seen: set[Path] = set()
    for base in search_paths:
        if not base.is_dir():
            continue
        for child in sorted(base.iterdir()):
            if not child.is_dir() or child.name.startswith(("_", ".")):
                continue
            if (child / "pack.yaml").exists():
                resolved = child.resolve()
                if resolved not in seen:
                    seen.add(resolved)
                    found.append(resolved)
    return found


def discover_entry_point_packs() -> list[Path]:
    paths: list[Path] = []
    try:
        eps = importlib.metadata.entry_points(group="domain_foundry.packs")
    except Exception:
        return paths
    for ep in eps:
        try:
            target = ep.load()
            path = Path(target) if not callable(target) else Path(target())
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
