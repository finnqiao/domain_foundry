"""ApplyEngine + CanonicalChangeExecutor (P3)."""

from domain_foundry_core.apply.engine import ApplyEngine, ApplyResult, OperationSpec
from domain_foundry_core.apply.executor import CanonicalChangeExecutor, ExecutionReceipt
from domain_foundry_core.apply.pipeline import ApplyPipeline, list_approvals

__all__ = [
    "ApplyEngine",
    "ApplyResult",
    "OperationSpec",
    "CanonicalChangeExecutor",
    "ExecutionReceipt",
    "ApplyPipeline",
    "list_approvals",
]
