"""
Multi-Tenant Isolation and Boundary Enforcement.

Fail-closed security principle:
  - Every tenant-scoped query or operation MUST verify org_id
  - Cross-tenant data access raises TenantIsolationError immediately
  - Async context variable holds current tenant ID per request/task
"""
from __future__ import annotations

import logging
from contextvars import ContextVar, Token
from typing import Any

logger = logging.getLogger(__name__)

_current_tenant: ContextVar[str | None] = ContextVar("current_tenant", default=None)


class TenantIsolationError(PermissionError):
    """Raised when an operation attempts cross-tenant data access."""
    def __init__(self, message: str, *, org_id: str | None = None, expected_org_id: str | None = None):
        super().__init__(message)
        self.org_id = org_id
        self.expected_org_id = expected_org_id


def set_current_tenant(org_id: str | None) -> None:
    """Set the active organization/tenant ID for the current context."""
    _current_tenant.set(org_id)


def get_current_tenant() -> str | None:
    """Get the active organization/tenant ID for the current context."""
    return _current_tenant.get()


def assert_tenant_boundary(
    resource_org_id: str | None,
    expected_org_id: str | None = None,
    *,
    resource_type: str = "resource",
) -> None:
    """
    Enforce tenant boundary. Fail-closed.

    If expected_org_id is omitted, it is read from the current context variable.
    Raises TenantIsolationError on any mismatch or missing org_id.
    """
    target_org = expected_org_id if expected_org_id is not None else get_current_tenant()

    if not target_org:
        logger.error("Security violation: Tenant boundary check failed — no tenant context set for %s", resource_type)
        raise TenantIsolationError(f"No tenant context established for {resource_type}")

    if not resource_org_id:
        logger.error("Security violation: %s has no org_id assigned", resource_type)
        raise TenantIsolationError(f"Resource '{resource_type}' has no assigned tenant scope")

    if str(resource_org_id) != str(target_org):
        logger.warning(
            "TENANT BREACH ATTEMPT: User/context org=%s attempted access to %s owned by org=%s",
            target_org,
            resource_type,
            resource_org_id,
        )
        raise TenantIsolationError(
            f"Cross-tenant access forbidden for {resource_type}",
            org_id=str(resource_org_id),
            expected_org_id=str(target_org),
        )


class tenant_context:
    """Async/sync context manager to scope execution to a specific tenant."""

    def __init__(self, org_id: str):
        self.org_id = org_id
        self._token: Token[str | None] | None = None

    def __enter__(self) -> str:
        self._token = _current_tenant.set(self.org_id)
        return self.org_id

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        if self._token is not None:
            _current_tenant.reset(self._token)

    async def __aenter__(self) -> str:
        return self.__enter__()

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.__exit__(exc_type, exc_val, exc_tb)
