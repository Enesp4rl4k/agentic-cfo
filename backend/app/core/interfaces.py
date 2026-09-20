"""
Core Architectural Interfaces & Protocols — SOLID Principles.

ISP (Interface Segregation Principle): Granular, cohesive protocols.
DIP (Dependency Inversion Principle): High-level modules depend on abstractions.
OCP (Open/Closed Principle): Extensible via polymorphism.
LSP (Liskov Substitution Principle): Interchangeable implementations.
"""
from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

# ── 1. Cache Layer Protocols (ISP & LSP) ──────────────────────────────────────

@runtime_checkable
class ICacheReader(Protocol):
    """Read-only cache operations."""

    async def get(self, key: str) -> Any | None:
        ...


@runtime_checkable
class ICacheWriter(Protocol):
    """Write and invalidation cache operations."""

    async def set(self, key: str, value: Any, ttl: int = 3600) -> None:
        ...

    async def delete(self, key: str) -> None:
        ...

    async def invalidate_pattern(self, pattern: str) -> int:
        ...


@runtime_checkable
class ICacheProvider(ICacheReader, ICacheWriter, Protocol):
    """Full cache provider contract for Redis and In-Memory implementations (LSP)."""

    async def get_stats(self) -> dict[str, Any]:
        ...

    async def aclose(self) -> None:
        ...


# ── 2. Report Exporter Protocols (SRP & OCP) ──────────────────────────────────

@runtime_checkable
class IReportExporter(Protocol):
    """Contract for report export engines (Excel, Dashboard JSON, PDF, CSV)."""

    format_name: str

    def export(
        self,
        pnl: dict[str, Any],
        cashflow: dict[str, Any],
        forecast: dict[str, Any],
        output_path: str,
        **kwargs: Any,
    ) -> str:
        """Export financial statements to the target path and return the file path or URI."""
        ...


# ── 3. Transaction Parser Protocol (SRP & OCP) ────────────────────────────────

@runtime_checkable
class ITransactionParser(Protocol):
    """Contract for bank statement & structured file parsing."""

    parser_id: str

    def can_parse(self, raw_text: str, filename: str = "") -> bool:
        """Check if parser can process this text / format."""
        ...

    def parse(self, raw_text: str, **kwargs: Any) -> list[dict[str, Any]]:
        """Parse raw text into standardized transaction dictionaries."""
        ...


# ── 4. Narrative Generator Protocol (SRP & DIP) ──────────────────────────────

@runtime_checkable
class INarrativeGenerator(Protocol):
    """Contract for generating financial narratives and management commentary."""

    async def generate_commentary(
        self,
        context_type: str,
        data: dict[str, Any],
        fallback: str = "",
    ) -> str:
        ...


# ── 5. Agent Skill Protocol (OCP & DIP) ───────────────────────────────────────

@runtime_checkable
class IAgentSkill(Protocol):
    """Contract for modular Agentic CFO skills."""

    skill_name: str
    required_inputs: list[str]
    produced_outputs: list[str]

    async def execute(
        self,
        state: dict[str, Any],
        config: Any = None,
    ) -> Any:
        """Execute the skill logic and return a SkillResult patch."""
        ...


# ── 6. Memory Store Protocol (LSP & DIP) ──────────────────────────────────────

@runtime_checkable
class IMemoryStore(Protocol):
    """Contract for long-term agent memory storage and retrieval."""

    def save_episode(self, episode: Any) -> str:
        ...

    def get_recent_episodes(self, org_id: str, limit: int = 5) -> list[Any]:
        ...

    def clear(self) -> None:
        ...
