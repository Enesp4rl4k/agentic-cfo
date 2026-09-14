"""
Dependency Injection Container — Dependency Inversion Principle (DIP).

Decouples high-level components from concrete service implementations,
allowing seamless substitution of mocks/stubs in tests and runtime configuration.
"""
from __future__ import annotations

from typing import Any, TypeVar

from app.core.interfaces import ICacheProvider, IMemoryStore

T = TypeVar("T")


class ServiceContainer:
    """Lightweight application dependency injection container."""

    def __init__(self) -> None:
        self._singletons: dict[str, Any] = {}
        self._factories: dict[str, Any] = {}

    def register_singleton(self, interface_name: str, instance: Any) -> None:
        """Register a pre-instantiated singleton instance."""
        self._singletons[interface_name] = instance

    def register_factory(self, interface_name: str, factory_fn: Any) -> None:
        """Register a factory callable to lazily produce an instance."""
        self._factories[interface_name] = factory_fn

    def resolve(self, interface_name: str, default: Any = None) -> Any:
        """Resolve a service instance by interface name."""
        if interface_name in self._singletons:
            return self._singletons[interface_name]
        if interface_name in self._factories:
            instance = self._factories[interface_name]()
            self._singletons[interface_name] = instance
            return instance
        return default

    def override(self, interface_name: str, instance: Any) -> None:
        """Override an implementation for testing."""
        self._singletons[interface_name] = instance

    def clear(self) -> None:
        """Clear all registered singletons and factories."""
        self._singletons.clear()
        self._factories.clear()


# Global application container instance
container = ServiceContainer()


# ── Built-in Factory Resolvers ────────────────────────────────────────────────

def get_cache_provider() -> ICacheProvider:
    """Resolve the active cache provider (Redis or In-Memory fallback)."""
    from app.services.cache_service import get_cache_service
    resolved = container.resolve("ICacheProvider")
    if resolved is None:
        resolved = get_cache_service()
        container.register_singleton("ICacheProvider", resolved)
    return resolved  # type: ignore[return-value]


def get_memory_store_instance() -> IMemoryStore:
    """Resolve the active memory store."""
    from app.services.agent_memory import get_memory_store
    resolved = container.resolve("IMemoryStore")
    if resolved is None:
        resolved = get_memory_store()
        container.register_singleton("IMemoryStore", resolved)
    return resolved  # type: ignore[return-value]


def get_report_exporter():
    """Resolve the active Excel report exporter (IReportExporter)."""
    from app.services.exporters import ExcelReportExporter
    resolved = container.resolve("IReportExporter")
    if resolved is None:
        resolved = ExcelReportExporter()
        container.register_singleton("IReportExporter", resolved)
    return resolved
