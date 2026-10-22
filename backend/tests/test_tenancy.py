"""
Unit tests for app.core.tenancy (Multi-tenant isolation and boundary guard).
"""
import pytest

from app.core.tenancy import (
    TenantIsolationError,
    assert_tenant_boundary,
    get_current_tenant,
    set_current_tenant,
    tenant_context,
)


def test_tenant_boundary_matching():
    # Explicit expected_org_id matches resource
    assert_tenant_boundary(resource_org_id="org-123", expected_org_id="org-123")


def test_tenant_boundary_mismatch_raises():
    with pytest.raises(TenantIsolationError) as exc_info:
        assert_tenant_boundary(
            resource_org_id="org-attacker",
            expected_org_id="org-victim",
            resource_type="analysis_job",
        )
    assert exc_info.value.org_id == "org-attacker"
    assert exc_info.value.expected_org_id == "org-victim"


def test_tenant_boundary_fail_closed_on_missing_context():
    set_current_tenant(None)
    with pytest.raises(TenantIsolationError):
        assert_tenant_boundary(resource_org_id="org-123")


def test_tenant_boundary_fail_closed_on_unscoped_resource():
    with pytest.raises(TenantIsolationError):
        assert_tenant_boundary(resource_org_id=None, expected_org_id="org-123")


def test_tenant_context_manager():
    set_current_tenant(None)
    assert get_current_tenant() is None

    with tenant_context("org-acme"):
        assert get_current_tenant() == "org-acme"
        # Context is active, so checking against org-acme resource succeeds
        assert_tenant_boundary(resource_org_id="org-acme")

        # Accessing another org fails
        with pytest.raises(TenantIsolationError):
            assert_tenant_boundary(resource_org_id="org-competitor")

    # Cleaned up automatically on exit
    assert get_current_tenant() is None


@pytest.mark.asyncio
async def test_async_tenant_context_manager():
    async with tenant_context("org-async-corp"):
        assert get_current_tenant() == "org-async-corp"
        assert_tenant_boundary(resource_org_id="org-async-corp")

    assert get_current_tenant() is None
