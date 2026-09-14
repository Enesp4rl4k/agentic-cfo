"""Canonical semantic types — period, money, metrics, decision brief."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

SCHEMA_VERSION = "1.0.0"

Severity = Literal["critical", "high", "medium", "low", "info"]
MetricUnit = Literal[
    "cents",
    "ratio",
    "months",
    "count",
    "score",
    "percent",
    "string",
    "boolean",
]


def _utcnow_iso() -> str:
    return datetime.now(UTC).isoformat()


@dataclass
class Period:
    key: str  # e.g. "2025-Q2" or "2025-06"
    start: str | None = None  # ISO date
    end: str | None = None
    grain: str = "month"  # month | quarter | year | custom

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Money:
    amount_cents: int
    currency: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class EvidenceRef:
    source_type: str
    source_id: str | None = None
    job_id: str | None = None
    preview: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class MetricPoint:
    metric_id: str
    value: float | int | str | bool | None
    unit: MetricUnit
    confidence: float = 1.0
    currency: str | None = None
    as_of: str | None = None
    source_agent: str | None = None
    source_job_id: str | None = None
    evidence_refs: list[EvidenceRef] = field(default_factory=list)
    data_source: str = "agent"  # agent | canonical | kernel | derived

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        return d

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> MetricPoint:
        refs = [
            EvidenceRef(**r) if isinstance(r, dict) else r
            for r in (raw.get("evidence_refs") or [])
        ]
        return cls(
            metric_id=str(raw["metric_id"]),
            value=raw.get("value"),
            unit=raw.get("unit") or "count",
            confidence=float(raw.get("confidence") or 1.0),
            currency=raw.get("currency"),
            as_of=raw.get("as_of"),
            source_agent=raw.get("source_agent"),
            source_job_id=raw.get("source_job_id"),
            evidence_refs=refs,
            data_source=str(raw.get("data_source") or "agent"),
        )


@dataclass
class DriverLink:
    from_metric_id: str
    to_metric_id: str
    relationship: str = "influences"  # influences | composed_of | correlates
    weight: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class BriefFinding:
    severity: Severity
    domain: str
    statement: str
    metric_ids: list[str] = field(default_factory=list)
    evidence_refs: list[EvidenceRef] = field(default_factory=list)
    confidence: float = 0.8

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class BriefOption:
    title: str
    impact_summary: str
    linked_cf_action: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class BriefRecommendation:
    title: str
    rationale: str
    option_index: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class DecisionBrief:
    period: str
    currency: str
    locale: str
    headline: str
    health_score: int
    findings: list[BriefFinding] = field(default_factory=list)
    options: list[BriefOption] = field(default_factory=list)
    recommendation: BriefRecommendation | None = None
    conflicts: list[dict[str, Any]] = field(default_factory=list)
    awaiting_review: bool = False
    generated_at: str = field(default_factory=_utcnow_iso)
    schema_version: str = SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "period": self.period,
            "currency": self.currency,
            "locale": self.locale,
            "headline": self.headline,
            "health_score": self.health_score,
            "findings": [f.to_dict() for f in self.findings],
            "options": [o.to_dict() for o in self.options],
            "recommendation": self.recommendation.to_dict() if self.recommendation else None,
            "conflicts": self.conflicts,
            "awaiting_review": self.awaiting_review,
            "generated_at": self.generated_at,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> DecisionBrief:
        findings = []
        for f in raw.get("findings") or []:
            if not isinstance(f, dict):
                continue
            refs = [
                EvidenceRef(**r) if isinstance(r, dict) else r
                for r in (f.get("evidence_refs") or [])
            ]
            findings.append(
                BriefFinding(
                    severity=f.get("severity") or "info",
                    domain=str(f.get("domain") or "general"),
                    statement=str(f.get("statement") or ""),
                    metric_ids=list(f.get("metric_ids") or []),
                    evidence_refs=refs,
                    confidence=float(f.get("confidence") or 0.8),
                )
            )
        options = [
            BriefOption(**o) if isinstance(o, dict) else o
            for o in (raw.get("options") or [])
            if isinstance(o, dict)
        ]
        rec_raw = raw.get("recommendation")
        rec = BriefRecommendation(**rec_raw) if isinstance(rec_raw, dict) else None
        return cls(
            period=str(raw.get("period") or ""),
            currency=str(raw.get("currency") or "USD"),
            locale=str(raw.get("locale") or "en-US"),
            headline=str(raw.get("headline") or ""),
            health_score=int(raw.get("health_score") or 0),
            findings=findings,
            options=options,
            recommendation=rec,
            conflicts=list(raw.get("conflicts") or []),
            awaiting_review=bool(raw.get("awaiting_review")),
            generated_at=str(raw.get("generated_at") or _utcnow_iso()),
            schema_version=str(raw.get("schema_version") or SCHEMA_VERSION),
        )


@dataclass
class CompanySemanticSnapshot:
    org_id: str
    period: Period
    currency: str
    locale: str
    metrics: list[MetricPoint] = field(default_factory=list)
    drivers: list[DriverLink] = field(default_factory=list)
    evidence: list[EvidenceRef] = field(default_factory=list)
    brief: DecisionBrief | None = None
    source_job_ids: list[str] = field(default_factory=list)
    schema_version: str = SCHEMA_VERSION
    updated_at: str = field(default_factory=_utcnow_iso)

    def metric_map(self) -> dict[str, MetricPoint]:
        return {m.metric_id: m for m in self.metrics}

    def values(self) -> dict[str, Any]:
        return {m.metric_id: m.value for m in self.metrics}

    def to_dict(self) -> dict[str, Any]:
        return {
            "org_id": self.org_id,
            "period": self.period.to_dict(),
            "currency": self.currency,
            "locale": self.locale,
            "metrics": [m.to_dict() for m in self.metrics],
            "drivers": [d.to_dict() for d in self.drivers],
            "evidence": [e.to_dict() for e in self.evidence],
            "brief": self.brief.to_dict() if self.brief else None,
            "source_job_ids": self.source_job_ids,
            "schema_version": self.schema_version,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> CompanySemanticSnapshot:
        period_raw = raw.get("period") or {}
        if isinstance(period_raw, str):
            period = Period(key=period_raw)
        else:
            period = Period(
                key=str(period_raw.get("key") or "unknown"),
                start=period_raw.get("start"),
                end=period_raw.get("end"),
                grain=str(period_raw.get("grain") or "month"),
            )
        brief_raw = raw.get("brief")
        brief = DecisionBrief.from_dict(brief_raw) if isinstance(brief_raw, dict) else None
        return cls(
            org_id=str(raw.get("org_id") or ""),
            period=period,
            currency=str(raw.get("currency") or "USD"),
            locale=str(raw.get("locale") or "en-US"),
            metrics=[MetricPoint.from_dict(m) for m in (raw.get("metrics") or []) if isinstance(m, dict)],
            drivers=[
                DriverLink(**d) for d in (raw.get("drivers") or []) if isinstance(d, dict)
            ],
            evidence=[
                EvidenceRef(**e) for e in (raw.get("evidence") or []) if isinstance(e, dict)
            ],
            brief=brief,
            source_job_ids=list(raw.get("source_job_ids") or []),
            schema_version=str(raw.get("schema_version") or SCHEMA_VERSION),
            updated_at=str(raw.get("updated_at") or _utcnow_iso()),
        )
