"""Operator-facing ops: what `/ready` shows whom, the backup report, the alert hook and its triggers,
the Sentry scrubber, and the preflight rules added for the pilot (APP_ENV, mail, worker).
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import select

import app.database as database
from app.api import ops
from app.config import Settings, get_settings
from app.core import preflight
from app.models.outbox_message import FAILED, OutboxMessage
from app.services import ops_watch
from app.services.operator_alerts import raise_alert
from tests.api_helpers import bellek_istemcisi, kullanici
from tests.test_preflight import CLEAN_ENV, NO_MAIL_NEEDED, codes, production_settings

P = "/api/v1"


@pytest_asyncio.fixture
async def client(monkeypatch):
    ops._reset_cache()
    settings = get_settings()
    monkeypatch.setattr(settings, "platform_operator_emails", "ops@tiphys.io")
    monkeypatch.setattr(settings, "email_verification_required", False)
    async with bellek_istemcisi() as c:
        monkeypatch.setattr(database, "engine", lambda: None)
        monkeypatch.setattr(database, "get_session_factory", lambda _e: c._maker)
        yield c


async def alert_rows(client) -> list[OutboxMessage]:
    async with client._maker() as db:
        return list((await db.execute(select(OutboxMessage).where(OutboxMessage.kind == "operator_alert"))).scalars().all())


# ── /ready ──────────────────────────────────────────────────────────────────────

async def test_anonymous_ready_shows_only_verdicts(client):
    data = (await client.get(f"{P}/ready")).json()["data"]
    assert set(data) == {"status", "checks"}
    assert set(data["checks"].values()) <= {"ok", "degraded", "fail", "skipped"}
    text = str(data)
    for leak in ("head", "current", "pending_overdue", "failed_24h", "analysis", "backup", "required"):
        assert leak not in text


async def test_a_bad_token_is_just_anonymous(client):
    r = await client.get(f"{P}/ready", headers={"Authorization": "Bearer nonsense"})
    assert r.status_code == 200 and set(r.json()["data"]) == {"status", "checks"}


async def test_operators_get_the_details_and_the_backup_state(client):
    ops_headers, _, _ = await kullanici(client, "ops@tiphys.io", role="analyst")
    other, _, _ = await kullanici(client, "uye@example.com", role="owner")
    detail = (await client.get(f"{P}/ready", headers=ops_headers)).json()["data"]
    assert detail["detail"] is True and "code" in detail["checks"]["database"] and "backup" in detail
    assert "detail" not in (await client.get(f"{P}/ready", headers=other)).json()["data"]  # a company owner is not an operator


async def test_a_failed_required_check_is_a_fail_verdict():
    assert ops._verdict({"ok": False, "required": True}) == "fail"
    assert ops._verdict({"ok": False, "required": False}) == "degraded"
    assert ops._verdict({"ok": None, "required": True}) == "skipped"


# ── backup report ───────────────────────────────────────────────────────────────

async def test_backup_report_is_404_without_a_configured_secret(client):
    assert (await client.post(f"{P}/platform/ops/backup-report", json={"ok": True})).status_code == 404


async def test_backup_report_needs_the_secret_and_stores_the_last_success(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "ops_report_token", "s3cret-" + "x" * 20)
    url = f"{P}/platform/ops/backup-report"
    assert (await client.post(url, json={"ok": True})).status_code == 401
    assert (await client.post(url, json={"ok": True}, headers={"X-Ops-Token": "wrong"})).status_code == 401
    good = {"X-Ops-Token": "s3cret-" + "x" * 20}
    assert (await client.post(url, json={"ok": True, "detail": "14 gün saklama"}, headers=good)).status_code == 200
    ops_headers, _, _ = await kullanici(client, "ops@tiphys.io", role="analyst")
    backup = (await client.get(f"{P}/ready", headers=ops_headers)).json()["data"]["backup"]
    assert backup["last_status"] == "ok" and backup["last_success_at"] and backup["reporting"] is True
    assert await alert_rows(client) == []


async def test_a_failed_backup_report_alerts_once_per_day(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "ops_report_token", "tok-" + "y" * 20)
    headers = {"X-Ops-Token": "tok-" + "y" * 20}
    for _ in range(3):
        await client.post(f"{P}/platform/ops/backup-report", json={"ok": False, "detail": "rclone exit 1"}, headers=headers)
    rows = await alert_rows(client)
    assert [r.recipient for r in rows] == ["ops@tiphys.io"] and "Yedekleme başarısız" in rows[0].subject


async def test_a_stale_backup_alerts_only_when_reporting_is_in_use(client, monkeypatch):
    # A fixed `now` one minute into an alert window: with the real clock, 31 h and 31 h 15 min later straddled
    # a window boundary about one run in twenty-four, and the "same window" check saw two mails.
    window = max(1, get_settings().operator_alert_cooldown_minutes) * 60
    now = datetime.fromtimestamp(1_800_000_000 // window * window + 60, tz=UTC)
    assert await ops_watch.watch(now) >= 0
    assert not [r for r in await alert_rows(client) if "Yedek raporu" in r.subject]  # no token: nothing claimed
    monkeypatch.setattr(get_settings(), "ops_report_token", "tok-" + "z" * 20)
    await ops_watch.watch(now)  # starts the clock
    assert not [r for r in await alert_rows(client) if "Yedek raporu" in r.subject]
    await ops_watch.watch(now + timedelta(hours=31))
    await ops_watch.watch(now + timedelta(hours=31, minutes=15))  # same window: deduplicated
    assert len([r for r in await alert_rows(client) if "Yedek raporu" in r.subject]) == 1


# ── the alert hook ──────────────────────────────────────────────────────────────

async def test_alerts_are_deduplicated_per_window_and_fixed_text(client):
    now = datetime(2026, 11, 23, 8, 0, tzinfo=UTC)
    async with client._maker() as db:
        for _ in range(3):
            await raise_alert(db, "outbox_failing", dedupe="d1", detail="org=o1 kanal=email", now=now)
        await raise_alert(db, "outbox_failing", dedupe="d2", now=now)  # another destination
        await raise_alert(db, "outbox_failing", dedupe="d1", now=now + timedelta(hours=7))  # next window
        await db.commit()
    assert len(await alert_rows(client)) == 3
    row = (await alert_rows(client))[0]
    assert (row.delivery_class, row.channel, row.org_id) == ("immediate", "email", "system")


async def test_alerts_go_only_to_operators_and_not_when_there_are_none(client, monkeypatch):
    from app.services import outbox_immediate

    async with client._maker() as db:
        with pytest.raises(outbox_immediate.ImmediateKindRefused):
            await outbox_immediate.enqueue_operator_alert(db, key="k", email="stranger@example.com", subject="s", body="b")
        monkeypatch.setattr(get_settings(), "platform_operator_emails", "")
        assert await raise_alert(db, "job_failed", dedupe="x") == 0


async def test_no_mail_sender_means_no_alert_row(client, monkeypatch):
    monkeypatch.setattr("app.services.mail_capability.delivery", lambda: "not_configured")
    async with client._maker() as db:
        assert await raise_alert(db, "job_failed", dedupe="x") == 0


async def test_a_failing_destination_alerts_without_the_address(client):
    async with client._maker() as db:
        for i in range(5):
            db.add(OutboxMessage(key=f"k{i}", org_id="org-1", channel="email", recipient="gizli@firma.com", subject="s",
                                 body="b", source="monday_briefing", source_ref="r", status=FAILED))
        db.add(OutboxMessage(key="other", org_id="org-2", channel="email", recipient="az@firma.com", subject="s", body="b",
                             source="x", source_ref="r", status=FAILED))
        await db.commit()
    await ops_watch.watch(datetime.now(UTC))
    mails = [r for r in await alert_rows(client) if "gitmiyor" in r.subject]
    assert len(mails) == 1 and "org=org-1" in mails[0].body and "gizli@firma.com" not in mails[0].body


async def test_preflight_warnings_are_sent_once_per_window(client, monkeypatch):
    # No real clock and no live preflight: a `now` that straddled a cool-down bucket, or a Redis
    # timeout that changed the set of warnings between the two calls, sent two mails.
    monkeypatch.setattr(
        preflight,
        "check_settings",
        lambda _settings, _environ=None: [preflight.Finding("no_llm_key", preflight.WARN, "stub")],
    )
    window = max(1, get_settings().operator_alert_cooldown_minutes) * 60
    now = datetime.fromtimestamp(1_800_000_000 // window * window + 60, tz=UTC)  # one minute into a window
    await ops_watch.watch(now)
    await ops_watch.watch(now + timedelta(minutes=15))
    mails = [r for r in await alert_rows(client) if "Başlangıç denetimi" in r.subject]
    assert len(mails) == 1 and "kodlar:" in mails[0].body


# ── Sentry ──────────────────────────────────────────────────────────────────────

def test_the_sentry_scrubber_removes_bodies_headers_and_personal_data():
    from app.services.sentry_monitoring import _filter_sensitive_data

    event = {
        "message": "gönderilemedi ayse@firma.com TR330006100519786457841326 Bearer abcdefghijklmnopqrstuvwxyz",
        "exception": {"values": [{"value": "password=hunter2hunter2 for mehmet@firma.com"}]},
        "request": {
            "url": "http://x/api/v1/auth/login", "data": {"password": "pw"}, "cookies": {"s": "c"}, "query_string": "token=abc",
            "headers": {"Authorization": "Bearer abc", "Cookie": "a=b", "X-Ops-Token": "t", "User-Agent": "curl"},
        },
        "user": {"id": "u1", "email": "ayse@firma.com", "ip_address": "1.2.3.4"},
        "breadcrumbs": {"values": [{"message": "to ayse@firma.com"}]},
        "extra": {"invite_token": "t" * 64, "note": "iban TR330006100519786457841326"},
    }
    out = _filter_sensitive_data(event, {})
    text = str(out)
    assert out is not None
    for secret in ("ayse@firma.com", "mehmet@firma.com", "TR330006100519786457841326", "hunter2", "abcdefghijklmnop", "tttt"):
        assert secret not in text, secret
    assert "data" not in out["request"] and "cookies" not in out["request"] and "query_string" not in out["request"]
    assert out["request"]["headers"]["Authorization"] == "[REDACTED]" and out["request"]["headers"]["User-Agent"] == "curl"
    assert out["user"] == {"id": "u1"}


def test_the_scrubber_drops_an_event_it_cannot_clean():
    from app.services.sentry_monitoring import _filter_sensitive_data

    class Hostile(dict):
        def get(self, *_a, **_k):
            raise RuntimeError("boom")

    assert _filter_sensitive_data(Hostile(), {}) is None


def test_sentry_is_configured_without_pii_or_bodies(monkeypatch):
    sentry_sdk = pytest.importorskip("sentry_sdk")
    seen: dict = {}
    monkeypatch.setattr(sentry_sdk, "init", lambda **kw: seen.update(kw))
    monkeypatch.setenv("SENTRY_DSN", "https://key@sentry.example.test/42")
    from types import SimpleNamespace

    from app.services.sentry_monitoring import init_sentry

    assert init_sentry(SimpleNamespace()) is True
    assert seen["send_default_pii"] is False and seen["max_request_body_size"] == "never"
    assert seen["include_local_variables"] is False and seen["before_send"] and seen["before_breadcrumb"]


# ── preflight additions ─────────────────────────────────────────────────────────

def test_postgres_without_app_env_is_fatal_and_names_the_values():
    env = {k: v for k, v in CLEAN_ENV.items() if k != "APP_ENV"}
    findings = preflight.check_settings(production_settings(), env)
    fatal = [f for f in findings if f.code == "app_env_missing"]
    assert fatal and "production" in fatal[0].message and "demo" in fatal[0].message
    assert "app_env_unknown" in codes(preflight.check_settings(production_settings(), {**env, "APP_ENV": "prodution"}))


@pytest.mark.parametrize("value", list(preflight.ALLOWED_APP_ENVS))
def test_every_allowed_app_env_passes_the_env_rule(value):
    assert not {"app_env_missing", "app_env_unknown"} & codes(preflight.check_settings(production_settings(), {**CLEAN_ENV, "APP_ENV": value}))


def test_sqlite_needs_no_app_env():
    s = Settings(_env_file=None, use_sqlite=True)
    assert "app_env_missing" not in codes(preflight.check_settings(s, {}))


def test_mail_dependent_features_with_no_sender_are_fatal_in_production():
    broken = {"smtp_user": "", "smtp_password": ""}
    for extra in ({"registration_mode": "invite_only", "email_verification_required": False},
                  {"registration_mode": "open", "email_verification_required": True}):
        findings = preflight.check_settings(production_settings(**broken, **extra), CLEAN_ENV)
        assert "mail_required_no_sender" in codes(findings, preflight.FATAL), extra
    s = production_settings(**broken, registration_mode="invite_only")
    with pytest.raises(preflight.PreflightError, match="mail_required_no_sender"):
        preflight.enforce(s, CLEAN_ENV)


def test_the_mail_rule_is_a_warning_for_the_demo_stack_and_silent_when_nothing_needs_mail():
    broken = {"smtp_user": "", "smtp_password": ""}
    demo = preflight.check_settings(production_settings(**broken), {**CLEAN_ENV, "APP_ENV": "demo"})
    assert "mail_required_no_sender" in codes(demo, preflight.WARN) and "mail_required_no_sender" not in codes(demo, preflight.FATAL)
    assert "mail_required_no_sender" not in codes(preflight.check_settings(production_settings(**broken, **NO_MAIL_NEEDED), CLEAN_ENV))
    noop = production_settings(outbox_transport="noop")
    assert "mail_required_no_sender" in codes(preflight.check_settings(noop, CLEAN_ENV), preflight.FATAL)


def test_enforce_or_exit_stops_a_process_on_a_fatal_finding(monkeypatch):
    monkeypatch.setattr(preflight, "_enforced", False)
    bad = production_settings(backend_secret_key="change-this-to-a-random-secret-32-chars")
    monkeypatch.setattr(preflight, "app_env", lambda environ=None: "production")
    with pytest.raises(SystemExit) as stop:
        preflight.enforce_or_exit(bad, process="worker")
    assert stop.value.code == 1
    monkeypatch.setattr(preflight, "_enforced", False)
    assert preflight.enforce_or_exit(production_settings(**NO_MAIL_NEEDED), process="worker") is not None
    assert preflight.enforce_or_exit(bad, process="worker") == [], "runs once per process"


def test_the_worker_module_runs_the_same_preflight():
    from pathlib import Path

    source = (Path(__file__).resolve().parents[1] / "app" / "worker.py").read_text(encoding="utf-8")
    # "worker" for the analysis worker; the maintenance worker (no uploads parsed) is named apart for the parser memory rule.
    assert "enforce_or_exit(get_settings(), process=" in source and 'else "worker")' in source
