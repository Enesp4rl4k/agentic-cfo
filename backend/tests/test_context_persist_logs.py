"""Context persist — log girdisi paritesi (DEMO_PLAN §D2).

``job.result_json`` ``_jsonable`` (derin) ile, ``company_context`` ise
``_serialize_result`` (eski: yalnız ``.step``/dict girdileri) ile yazılır;
AuditStepLog/RiskStepLog gibi ``node/status/message`` dataclass'leri context'e
sessizce atılırdı → her koşuda job≠context "drift" ve context'te ``logs: []``.

Kapı: context'in log çıktısı job'ınkiyle birebir aynı biçimde olmalı.
"""
from __future__ import annotations

import dataclasses

from app.api.agent_jobs import _jsonable
from app.services.context_persist import _serialize_result


@dataclasses.dataclass
class _StepLog:
    node: str
    status: str
    message: str
    metrics: dict


def test_dataclass_log_entries_match_job_serializer():
    state = {
        "logs": [
            _StepLog("findings_agent", "completed", "Processed 5 findings", {"open_critical": 1}),
            {"node": "dict_entry", "status": "completed"},
            "plain-string-log",
        ],
        "summary": {"score": 91},
    }
    ctx_shape = _serialize_result(state)
    job_shape = _jsonable(state)

    assert ctx_shape["logs"] == job_shape["logs"]
    assert ctx_shape["logs"][0] == {
        "node": "findings_agent",
        "status": "completed",
        "message": "Processed 5 findings",
        "metrics": {"open_critical": 1},
    }


def test_step_style_and_non_log_keys_unchanged():
    state = {
        "logs": [{"step": "infra", "ok": True, "detail": "d", "confidence": 0.9}],
        "narrative": "text",
        "count": 3,
    }
    out = _serialize_result(state)
    assert out["logs"] == state["logs"]
    assert out["narrative"] == "text"
    assert out["count"] == 3
    assert out["logs"] == _jsonable(state["logs"])
