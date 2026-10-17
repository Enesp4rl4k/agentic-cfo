"""
D2 gate — demo_prefill CTO örnek girdileri (DEMO_PLAN §D2).

Golden org'un CTO vitrini bu dört girdiye bağlı; parser şeması değişirse örnek
veri sessizce boş sonuca düşer ("0.0/10, 0 risk"). İki kilit:

1. Dört girdi dört parser'dan geçer ve anlamlı sinyaller üretir
   (billing satırı + hotspot, tek-yazarlı/bus-factor dosya, SLA ihlali +
   tekrarlayan servis, bottleneck sprint).
2. Frontend SAMPLE_CTO_INPUTS ↔ backend _CTO_INPUTS byte-for-byte aynı kalır
   (formun "Örnek veriyle doldur" düğmesi ile prefill aynı veriyi yollar).
"""
from __future__ import annotations

import importlib.util
import re
from collections import Counter
from pathlib import Path

from app.agents.cto.incident_agent import SLA_TARGETS_HOURS, _parse_incident_csv
from app.agents.cto.infra_agent import _parse_billing_csv
from app.agents.cto.tech_debt_agent import _compute_debt_metrics, _parse_git_log
from app.agents.cto.velocity_agent import _parse_sprint_csv

_BACKEND = Path(__file__).resolve().parents[1]
_PREFILL = _BACKEND / "scripts" / "demo_prefill.py"
_CTO_PAGE = _BACKEND.parent / "frontend" / "src" / "app" / "(dashboard)" / "cto" / "page.tsx"


def _load_prefill_inputs() -> dict[str, str]:
    """Import the script by path (scripts/ is not a package)."""
    spec = importlib.util.spec_from_file_location("demo_prefill", _PREFILL)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return dict(mod._CTO_INPUTS)


def test_cto_sample_inputs_parse_into_signals() -> None:
    inputs = _load_prefill_inputs()
    assert set(inputs) == {"cloud_billing_csv", "git_log_text", "incident_csv", "sprint_csv"}

    # billing → infra rows with positive cost + prod environment
    rows = _parse_billing_csv(inputs["cloud_billing_csv"])
    assert len(rows) >= 6
    assert all(r["cost_cents"] > 0 for r in rows)
    assert any(r["environment"] == "prod" for r in rows)

    # git log → commits, a hotspot (>=5 touches) and a bus-factor file
    # (>=3 commits from a single author)
    parsed = _parse_git_log(inputs["git_log_text"])
    assert len(parsed["commits"]) >= 10
    file_changes = parsed["file_changes"]
    assert any(v["count"] >= 5 for v in file_changes.values()), "no hotspot"
    assert any(
        v["count"] >= 3 and len(v["authors"]) == 1 for v in file_changes.values()
    ), "no bus-factor file"
    assert _compute_debt_metrics(parsed)["debt_score"] > 0

    # incidents → SLA breach + recurring service
    incidents = _parse_incident_csv(inputs["incident_csv"])
    assert len(incidents) >= 6
    assert any(
        r["ttr_hours"] is not None
        and r["ttr_hours"] > SLA_TARGETS_HOURS.get(r["severity"], 24.0)
        for r in incidents
    ), "no SLA breach"
    assert Counter(r["service"] for r in incidents).most_common(1)[0][1] >= 3

    # sprints → one bottleneck sprint (<70% completion)
    sprints = _parse_sprint_csv(inputs["sprint_csv"])
    assert len(sprints) >= 6
    assert all(s["planned"] > 0 for s in sprints)
    assert any(s["completion_rate"] < 0.70 for s in sprints), "no bottleneck sprint"


def test_cto_sample_inputs_mirror_frontend_byte_for_byte() -> None:
    backend = _load_prefill_inputs()
    src = _CTO_PAGE.read_text(encoding="utf-8")
    block = src.split("const SAMPLE_CTO_INPUTS", 1)[1].split("};", 1)[0]
    frontend = dict(re.findall(r"(\w+): `([^`]*)`", block))
    assert frontend == backend, "SAMPLE_CTO_INPUTS drifted from demo_prefill._CTO_INPUTS"
