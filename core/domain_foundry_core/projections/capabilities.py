"""Safe, pack-declared experience capabilities.

This module is intentionally domain-neutral. Packs describe which derived
values, media galleries, and comparisons they need; the shell asks this module
to evaluate those declarations without importing a domain name or executing
pack-provided Python.
"""

from __future__ import annotations

import ast
import json
import math
from collections.abc import Iterable, Mapping
from typing import Any

from domain_foundry_core.packs.models import DomainPack


class CapabilityEvaluationError(ValueError):
    """Raised when a declarative capability is malformed or unsafe."""


def derived_metric_specs(pack: DomainPack, object_type: str) -> list[dict[str, Any]]:
    declaration = pack.capabilities.get("derived_metrics") or {}
    if declaration.get("object") != object_type:
        return []
    return [
        dict(metric)
        for metric in declaration.get("metrics") or []
        if isinstance(metric, dict)
    ]


def annotate_derived(
    pack: DomainPack,
    object_type: str,
    rows: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Attach ``derived`` values to rows in the order supplied.

    ``previous`` in a metric expression means the preceding row in the
    projection's declared order. Missing values and zero denominators produce
    ``None`` rather than a fabricated number.
    """

    specs = derived_metric_specs(pack, object_type)
    if not specs:
        return [dict(row) for row in rows]

    out: list[dict[str, Any]] = []
    previous: dict[str, Any] | None = None
    previous_derived: dict[str, Any] = {}
    for raw_row in rows:
        row = dict(raw_row)
        values: dict[str, Any] = {}
        for metric in specs:
            metric_id = str(metric.get("id") or "")
            try:
                value = _evaluate_metric(
                    metric,
                    current={**row, **values},
                    previous={**(previous or {}), **previous_derived},
                )
            except (CapabilityEvaluationError, ZeroDivisionError, ValueError, TypeError):
                value = None
            values[metric_id] = _round_value(value, metric.get("precision"))
        row["derived"] = values
        out.append(row)
        previous = row
        previous_derived = values
    return out


def metric_value(row: Mapping[str, Any], field: str) -> Any:
    derived = row.get("derived")
    if isinstance(derived, Mapping) and field in derived:
        return derived[field]
    return row.get(field)


def capability_for_gallery(
    pack: DomainPack, object_type: str, gallery_id_or_field: str | None
) -> dict[str, Any] | None:
    declaration = pack.capabilities.get("media") or {}
    for gallery in declaration.get("galleries") or []:
        if not isinstance(gallery, dict) or gallery.get("object") != object_type:
            continue
        if gallery_id_or_field in {gallery.get("id"), gallery.get("field")}:
            return dict(gallery)
    return None


def comparison_spec(
    pack: DomainPack, object_type: str, comparison_id: str | None
) -> dict[str, Any] | None:
    declaration = pack.capabilities.get("compare") or {}
    for comparison in declaration.get("comparisons") or []:
        if not isinstance(comparison, dict) or comparison.get("object") != object_type:
            continue
        if comparison_id in {None, comparison.get("id")}:
            return dict(comparison)
    return None


def _evaluate_metric(
    metric: Mapping[str, Any],
    *,
    current: Mapping[str, Any],
    previous: Mapping[str, Any],
) -> Any:
    operation = metric.get("operation")
    if operation:
        if operation == "ratio":
            numerator_field = str(metric.get("numerator") or "")
            denominator_field = str(metric.get("denominator") or "")
            numerator = current.get(numerator_field) if numerator_field else None
            denominator = current.get(denominator_field) if denominator_field else None
            if numerator is None or denominator in (None, 0):
                return None
            return float(numerator) / float(denominator) * float(metric.get("multiplier") or 1)
        if operation == "delta_previous":
            field = str(metric.get("field") or "")
            value = current.get(field)
            before = previous.get(field)
            if value is None or before is None:
                return None
            return float(value) - float(before)
        raise CapabilityEvaluationError(f"unsupported metric operation {operation!r}")

    expression = str(metric.get("expression") or "")
    return _safe_eval(expression, current=current, previous=previous)


def _safe_eval(
    expression: str, *, current: Mapping[str, Any], previous: Mapping[str, Any]
) -> Any:
    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError as exc:
        raise CapabilityEvaluationError(f"invalid metric expression: {exc}") from exc
    return _eval_node(tree.body, current=current, previous=previous)


def _eval_node(
    node: ast.AST,
    *,
    current: Mapping[str, Any],
    previous: Mapping[str, Any],
) -> Any:
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.Name):
        if node.id in current:
            return current[node.id]
        raise CapabilityEvaluationError(f"unknown metric field {node.id!r}")
    if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
        if node.value.id == "previous":
            return previous.get(node.attr)
        if node.value.id == "current":
            return current.get(node.attr)
        raise CapabilityEvaluationError("only current.<field> and previous.<field> are allowed")
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
        value = _eval_node(node.operand, current=current, previous=previous)
        return +value if isinstance(node.op, ast.UAdd) else -value
    if isinstance(node, ast.BinOp) and isinstance(
        node.op, (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Mod, ast.Pow)
    ):
        left = _eval_node(node.left, current=current, previous=previous)
        right = _eval_node(node.right, current=current, previous=previous)
        if left is None or right is None:
            return None
        if isinstance(node.op, ast.Add):
            return left + right
        if isinstance(node.op, ast.Sub):
            return left - right
        if isinstance(node.op, ast.Mult):
            return left * right
        if isinstance(node.op, ast.Div):
            return left / right
        if isinstance(node.op, ast.Mod):
            return left % right
        return left**right
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
        if node.func.id not in {"abs", "round", "min", "max"} or node.keywords:
            raise CapabilityEvaluationError("metric function is not allowed")
        args = [_eval_node(arg, current=current, previous=previous) for arg in node.args]
        if any(arg is None for arg in args):
            return None
        return {"abs": abs, "round": round, "min": min, "max": max}[node.func.id](*args)
    raise CapabilityEvaluationError(f"metric syntax {type(node).__name__} is not allowed")


def _round_value(value: Any, precision: Any) -> Any:
    if value is None or precision is None:
        return value
    try:
        return round(float(value), int(precision))
    except (TypeError, ValueError):
        return value


def parse_attachment_value(value: Any) -> list[dict[str, Any]]:
    if value is None or value == "":
        return []
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            return []
    if isinstance(value, Mapping):
        value = [value]
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, Mapping)]


def safe_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None
