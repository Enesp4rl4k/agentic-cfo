"""APScheduler runs in exactly one kind of process.

Before: ``main.py`` started APScheduler in every API process and the arq
worker never did, so on a box with 2 uvicorn workers every cron ran twice
(held off only by the Redis NX lock, and not at all when Redis blinked) — and
the API, the process that should answer users, did the nightly batch work.

``SCHEDULER_PROCESS`` names the process type that owns the crons:
``api`` (default — dev without a worker keeps working) or ``worker``
(staging/prod: the arq analysis worker starts it, API processes never do).
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

import app.config as app_config
import app.scheduler as scheduler_mod
from app.config import Settings

REPO_ROOT = Path(__file__).resolve().parents[2]


class _FakeScheduler:
    def __init__(self) -> None:
        self.running = False
        self.starts = 0

    def start(self) -> None:
        self.running = True
        self.starts += 1

    def shutdown(self, wait: bool = False) -> None:
        self.running = False


@pytest.fixture
def fake(monkeypatch: pytest.MonkeyPatch):
    sched = _FakeScheduler()
    monkeypatch.setattr(scheduler_mod, "_scheduler", None)

    def _get() -> _FakeScheduler:
        # Like the real get_scheduler: the singleton stop_scheduler() reads.
        scheduler_mod._scheduler = sched  # type: ignore[assignment]
        return sched

    monkeypatch.setattr(scheduler_mod, "get_scheduler", _get)

    def _with(**overrides: Any) -> _FakeScheduler:
        s = Settings(**overrides)
        monkeypatch.setattr(app_config, "get_settings", lambda: s)
        return sched

    return _with


def test_default_owner_is_api_so_dev_without_worker_keeps_crons(fake) -> None:
    sched = fake()
    scheduler_mod.start_scheduler("api")
    assert sched.starts == 1


def test_api_process_does_not_start_when_worker_owns_crons(fake) -> None:
    sched = fake(scheduler_process="worker")
    scheduler_mod.start_scheduler("api")
    assert sched.starts == 0


def test_worker_process_starts_when_it_owns_crons(fake) -> None:
    sched = fake(scheduler_process="worker")
    scheduler_mod.start_scheduler("worker")
    assert sched.starts == 1


def test_worker_process_does_not_start_in_default_dev_mode(fake) -> None:
    sched = fake()
    scheduler_mod.start_scheduler("worker")
    assert sched.starts == 0


def test_kill_switch_still_wins(fake) -> None:
    sched = fake(scheduler_process="worker", scheduler_enabled=False)
    scheduler_mod.start_scheduler("worker")
    assert sched.starts == 0


def test_unknown_owner_is_refused_at_config_load() -> None:
    with pytest.raises(ValueError):
        Settings(scheduler_process="both")


async def test_analysis_worker_starts_and_stops_scheduler(fake) -> None:
    from app.worker import WorkerSettings

    sched = fake(scheduler_process="worker")
    await WorkerSettings.on_startup({})
    assert sched.starts == 1 and sched.running
    await WorkerSettings.on_shutdown({})
    assert not sched.running


def test_maintenance_worker_never_runs_crons() -> None:
    # One worker type owns the crons; a second scheduler would only be
    # stopped by the Redis lock.
    from app.worker import MaintenanceWorkerSettings

    assert getattr(MaintenanceWorkerSettings, "on_startup", None) is None


def test_main_lifespan_starts_scheduler_as_api() -> None:
    src = (REPO_ROOT / "backend" / "app" / "main.py").read_text(encoding="utf-8")
    assert 'start_scheduler("api")' in src


# ── docker-compose.prod.yml: the wiring the flag depends on ──────────────────

def _prod_compose() -> dict[str, Any]:
    return yaml.safe_load(
        (REPO_ROOT / "docker-compose.prod.yml").read_text(encoding="utf-8")
    )


def _env(service: dict[str, Any]) -> dict[str, str]:
    env = service.get("environment") or {}
    if isinstance(env, list):
        env = dict(item.split("=", 1) for item in env)
    return {k: str(v) for k, v in env.items()}


def test_prod_compose_hands_crons_to_the_worker() -> None:
    services = _prod_compose()["services"]
    for name in ("backend", "worker", "worker-maintenance"):
        assert _env(services[name]).get("SCHEDULER_PROCESS") == "worker", name


def test_prod_compose_publishes_only_80_and_443() -> None:
    services = _prod_compose()["services"]
    published: list[str] = []
    for name, svc in services.items():
        for port in svc.get("ports") or []:
            published.append(f"{name}:{port}")
    assert sorted(published) == sorted(
        ["caddy:80:80", "caddy:443:443", "caddy:443:443/udp"]
    ), published


def test_prod_compose_keeps_data_stores_off_the_edge_network() -> None:
    services = _prod_compose()["services"]
    for name in ("postgres", "redis"):
        assert services[name].get("networks") == ["internal"], name
    networks = _prod_compose()["networks"]
    assert networks["internal"].get("internal") is True
