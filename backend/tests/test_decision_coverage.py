"""Every route that decides something writes the decision record.

The product's rule is "the system proposes, humans decide, and every decision has a record of who,
what, when and on which evidence" (`app.services.decisions.record_decision`, table `decisions`).
A decision point that forgets to record is a hole in that log, and nothing noticed: the category
correction and the plan-change approval both shipped without a record.

This walks the same inventory as `tests/test_route_authorisation.py` (every POST / PUT / PATCH /
DELETE route that is not public and not open to any member) and requires each one to reach
`record_decision` from its handler, or to be listed here with the reason it is not a decision, or
as a KNOWN GAP (a decision point whose record is still owed, with who owes it). A new
route that is none of these fails by name. The gap list is a debt: a route that starts recording
must leave it (the last test), so it can only shrink.
"""
from __future__ import annotations

import pytest

from app.api.access import OPEN_ROUTES, PUBLIC_ROUTES
from app.services.decisions import record_decision
from tests.test_route_authorisation import _changing, _reachable

Route = tuple[str, str]

_COMPUTES = [
    ("POST", "/api/v1/advanced/proactive-scan"),
    ("POST", "/api/v1/advanced/temporal/auto-record"),
    ("POST", "/api/v1/agent-jobs/{agent_type}"),
    ("POST", "/api/v1/analysis/{job_id}/domains/{domain}"),
    ("POST", "/api/v1/anomalies/scan/{job_id}"),
    ("POST", "/api/v1/audit/analyze"),
    ("POST", "/api/v1/brief/morning/generate"),
    ("POST", "/api/v1/ceo/analyze-async"),
    ("POST", "/api/v1/ceo/synthesize"),
    ("POST", "/api/v1/chro/analyze"),
    ("POST", "/api/v1/cmo/analyze"),
    ("POST", "/api/v1/compliance/analyze"),
    ("POST", "/api/v1/coo/analyze"),
    ("POST", "/api/v1/institutionalization/compute"),
    ("POST", "/api/v1/muhasebe/analiz"),
    ("POST", "/api/v1/muhasebe/tr-vertical"),
    ("POST", "/api/v1/negotiation/boardroom/debate"),
    ("POST", "/api/v1/risk/analyze"),
    ("POST", "/api/v1/runs/{run_id}/resume"),
    ("POST", "/api/v1/semantic/me/rebuild"),
    ("POST", "/api/v1/smmm/defensibility/{job_id}/build"),
    ("POST", "/api/v1/temporal/record"),
]

_WORKING_INPUTS = [
    ("DELETE", "/api/v1/agent-jobs/{job_id}"),
    ("DELETE", "/api/v1/datasource/{job_id}/{source_id}"),
]

_NOTICES = [
    ("POST", "/api/v1/alerts/acknowledge/{job_id}/{alert_fingerprint}"),
    ("POST", "/api/v1/alerts/rules"),
    ("DELETE", "/api/v1/alerts/rules/{rule_id}"),
    ("PATCH", "/api/v1/alerts/{alert_id}/acknowledge"),
    ("PATCH", "/api/v1/anomalies/{anomaly_id}/acknowledge"),
    ("PUT", "/api/v1/notifications/preferences"),
    ("PATCH", "/api/v1/notifications/read-all"),
    ("DELETE", "/api/v1/notifications/{notification_id}"),
    ("PATCH", "/api/v1/notifications/{notification_id}/read"),
]

_INTEGRATION_CONFIG = [
    ("POST", "/api/v1/alerts/channels/test"),
    ("DELETE", "/api/v1/connectors/{name}"),
    ("POST", "/api/v1/connectors/{name}/connect"),
    ("POST", "/api/v1/email/ingest-address/yenile"),
    ("DELETE", "/api/v1/erp/integrations/{integration_id}"),
    ("POST", "/api/v1/erp/logo-tiger/connect"),
    ("POST", "/api/v1/erp/parasut/baglan"),
    ("POST", "/api/v1/erp/parasut/disconnect"),
    ("POST", "/api/v1/erp/parasut/firma"),
    ("PATCH", "/api/v1/erp/parasut/otomatik"),
    ("POST", "/api/v1/integrations/github/connect"),
    ("DELETE", "/api/v1/integrations/github/disconnect"),
    ("POST", "/api/v1/integrations/webhook/test"),
    ("POST", "/api/v1/notifications/test-slack"),
    ("POST", "/api/v1/open-banking/connect/{bank_id}"),
]

_BILLING = [
    ("POST", "/api/v1/billing/cancel"),
    ("POST", "/api/v1/billing/checkout"),
    ("POST", "/api/v1/billing/portal"),
]

_ERASURE = [
    ("POST", "/api/v1/compliance/org-erasure/request"),
    ("POST", "/api/v1/compliance/org-erasure/{request_id}/confirm"),
]

_SYNCS = [
    ("POST", "/api/v1/connectors/{name}/sync"),
    ("POST", "/api/v1/erp/logo-tiger/sync"),
    ("POST", "/api/v1/erp/mikro/sync"),
    ("POST", "/api/v1/erp/parasut/sync"),
    ("POST", "/api/v1/integrations/ecommerce/sync"),
    ("POST", "/api/v1/integrations/github/sync"),
    ("POST", "/api/v1/integrations/sheets/export"),
    ("POST", "/api/v1/integrations/sheets/import"),
    ("POST", "/api/v1/open-banking/connections/{connection_id}/sync"),
    ("POST", "/api/v1/sync/schedules"),
    ("PUT", "/api/v1/sync/schedules/{schedule_id}"),
    ("DELETE", "/api/v1/sync/schedules/{schedule_id}"),
    ("POST", "/api/v1/sync/schedules/{schedule_id}/run"),
]

_BRINGS_DATA_IN = [
    ("POST", "/api/v1/datasource/{job_id}/{domain}/{source_type}"),
    ("POST", "/api/v1/veri/ekle"),
]

_OTHER_REGISTER = [
    ("POST", "/api/v1/decisions"),
    ("POST", "/api/v1/decisions/{decision_id}/outcome"),
]

_PLATFORM_OPERATOR = [
    ("DELETE", "/api/v1/demo/reset"),
    ("POST", "/api/v1/pilot/invite/generate"),
    ("DELETE", "/api/v1/pilot/invite/{invite_id}"),
]



NOT_A_DECISION: dict[Route, str] = {}
for _routes, _why in (
    (_COMPUTES, "starts or repeats a computation on data already in the company; the system proposes a result, nobody decides anything"),
    (_BRINGS_DATA_IN, "brings a document or rows in; what the system could not read alone is held and decided by a person on its own routes (held rows, duplicates)"),
    (_SYNCS, "pulls from or pushes to a connection (or its schedule) that a decider already set up; no figure is decided"),
    (_INTEGRATION_CONFIG, "connects, disconnects or tests an integration or address; the connection row is the record and no book entry changes"),
    (_NOTICES, "notices, alert rules and notification preferences: acknowledging or muting a message decides nothing about money"),
    (_BILLING, "the payment provider holds the subscription and its history; no company record is decided"),
    (_OTHER_REGISTER, "the management-recommendation register (DecisionLog, outcome tracking): a different, older register than the decision record"),
    (_PLATFORM_OPERATOR, "platform administration or demo data, not a company's decision"),
    (_ERASURE, "organisation erasure keeps its own hash-chained, organisation-independent proof (`OrgErasureRequest`, `ErasureRecord`); a decisions row would be erased with the organisation"),
    (_WORKING_INPUTS, "removes a queued run or an input the same writer added; nothing in the books changes"),
):
    for _route in _routes:
        NOT_A_DECISION[_route] = _why

# Decision points whose record is still owed. Each names who owes it. The test below makes this list shrink only.
KNOWN_GAPS: dict[Route, str] = {
    ("POST", "/api/v1/ledger/settlements/{match_id}/resolve"):
        "settlement match confirm / reject lives in api/ledger.py (PR #114/#115); `undo` already records, and so must this",
    ("POST", "/api/v1/data-quality/accept-mapping"): "a person's acceptance of the proposed column mapping, before the analysis starts",
    ("PATCH", "/api/v1/org/me"): "organisation profile; the base-currency rule is PR #116's (the currency decision itself records via /org/base-currency)",
    ("POST", "/api/v1/related-parties"): "a related-party flag changes how transactions are treated: should be an automation_rule_change",
    ("PATCH", "/api/v1/related-parties/{party_id}"): "same",
    ("DELETE", "/api/v1/related-parties/{party_id}"): "same",
    ("PUT", "/api/v1/security/ip-whitelist"): "a security setting changed by an owner or admin",
    ("POST", "/api/v1/tetikler"): "a standing trigger is an automation: automation_rule_change",
    ("PATCH", "/api/v1/tetikler/{trigger_id}"): "same",
    ("DELETE", "/api/v1/tetikler/{trigger_id}"): "same",
    ("DELETE", "/api/v1/context/{org_id}"): "a decider resets the company context",
    ("POST", "/api/v1/compliance/gdpr/breach-notification"): "a decider files a breach notification",
    ("POST", "/api/v1/compliance/gdpr/breach/{breach_id}/notify"): "a decider marks a breach as notified",
    ("POST", "/api/v1/compliance/sox/certify"): "a decider certifies",
}


def _inventory() -> dict[Route, object]:
    return {
        key: route for key, route in _changing()
        if key not in PUBLIC_ROUTES and key not in OPEN_ROUTES
    }


def _records(route: object) -> bool:
    return record_decision in _reachable(route.endpoint)  # type: ignore[attr-defined]


def test_every_deciding_route_records_the_decision() -> None:
    offenders = [
        f"{m} {p}" for (m, p), r in _inventory().items()
        if not _records(r) and (m, p) not in NOT_A_DECISION and (m, p) not in KNOWN_GAPS
    ]
    assert not offenders, (
        "bu rota karar kaydı yazmıyor: handler'dan `record_decision(...)` çağırın (aynı işlemde), "
        "ya da tests/test_decision_coverage.py'de NOT_A_DECISION'a gerekçesiyle yazın: " + ", ".join(offenders)
    )


def test_the_lists_name_routes_that_exist_and_do_not_overlap() -> None:
    keys = set(_inventory())
    for name, table in (("NOT_A_DECISION", NOT_A_DECISION), ("KNOWN_GAPS", KNOWN_GAPS)):
        assert not [k for k in table if k not in keys], f"{name}: artık olmayan rota"
    assert not set(NOT_A_DECISION) & set(KNOWN_GAPS)


def test_a_route_that_records_is_not_excused() -> None:
    inventory = _inventory()
    excused_but_recording = [
        f"{m} {p}" for (m, p) in (*NOT_A_DECISION, *KNOWN_GAPS) if _records(inventory[(m, p)])
    ]
    assert not excused_but_recording, (
        "zaten kayıt yazan rota istisna listesinde; listeden çıkarın: " + ", ".join(excused_but_recording)
    )


@pytest.mark.parametrize(
    "route",
    [
        ("PATCH", "/api/v1/transactions/{transaction_id}/category"),
        ("POST", "/api/v1/ledger/plan-changes"),
        ("POST", "/api/v1/ledger/plan-changes/{change_id}/approve"),
        ("POST", "/api/v1/ledger/plan-changes/{change_id}/reject"),
        ("POST", "/api/v1/ledger/plan-changes/{change_id}/withdraw"),
        ("POST", "/api/v1/analysis/{job_id}/approve"),
        ("POST", "/api/v1/smmm/onay/{kayit_id}/onayla"),
        ("POST", "/api/v1/smmm/onay/{kayit_id}/duzeltle"),
        ("POST", "/api/v1/smmm/onay/{kayit_id}/reddet"),
        ("POST", "/api/v1/smmm/onay/toplu-onayla"),
        ("POST", "/api/v1/smmm/donem-kilitleri"),
        ("PUT", "/api/v1/authority/policy"),
        ("POST", "/api/v1/org/invite"),
        ("DELETE", "/api/v1/org/members/{user_id}"),
        ("POST", "/api/v1/actions/{action_id}/approve"),
        ("POST", "/api/v1/actions/{action_id}/reject"),
    ],
)
def test_the_named_decision_points_record(route: Route) -> None:
    """The ones the pilot flow depends on, named, so an allow-list edit cannot quietly drop one."""
    assert _records(_inventory()[route])
