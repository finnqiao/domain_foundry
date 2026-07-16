"""Security primitives: path safety, secret redaction, RO/RW connections."""

from domain_expert_core.security.paths import PathSafetyError, safe_join
from domain_expert_core.security.redact import redact_secrets
from domain_expert_core.security.store import (
    connect_ro,
    connect_rw,
    integrity_check,
    is_readonly_sql,
)

__all__ = [
    "PathSafetyError",
    "safe_join",
    "redact_secrets",
    "connect_ro",
    "connect_rw",
    "integrity_check",
    "is_readonly_sql",
]
