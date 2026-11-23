"""No preflight rule may brick a default deploy: the parser-memory rule is run against EVERY service of
`docker-compose.prod.yml`, every Kubernetes workload and the Helm values, each with its declared memory limit
as the cgroup limit and the process it really starts (the `--db` check every entrypoint runs, plus the process
role from its command), with the shipped default settings.

The first version of the rule counted `RLIMIT_AS` against the container and was FATAL for the 512 MB `migrate`
service, which parses nothing: a default production deploy would have stopped. This matrix is the guard.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

from app.config import get_settings
from app.core import preflight

REPO = Path(__file__).resolve().parents[2]
MB = 1024 * 1024


def megabytes(value: str | int) -> int:
    text = str(value).strip()
    match = re.fullmatch(r"([0-9.]+)\s*([A-Za-z]*)", text)
    assert match, text
    number, unit = float(match.group(1)), match.group(2).lower()
    scale = {"": 1 / MB, "b": 1 / MB, "k": 1 / 1024, "ki": 1 / 1024, "m": 1, "mi": 1, "g": 1024, "gi": 1024}
    return int(number * scale[unit])


def role_of(command: str, container: str = "") -> str | None:
    """The process role a command starts, the way the app names it to the preflight (`enforce_or_exit(process=...)`)."""
    if "uvicorn" in command or (not command and "backend" in container):   # backend/Dockerfile's CMD is uvicorn
        return "api"
    if "MaintenanceWorkerSettings" in command:
        return "worker-maintenance"
    if "WorkerSettings" in command:
        return "worker"
    return None


def parser_findings(monkeypatch, tmp_path, limit_mb: int, process: str | None):
    limit = tmp_path / f"memory-{limit_mb}-{process}"
    limit.write_text(str(limit_mb * MB))
    monkeypatch.setattr(preflight, "_CGROUP_LIMIT_FILES", (limit,))
    settings = get_settings()
    return [f for f in preflight.check_settings(settings, {}, process) if f.code.startswith("parser_memory")]


def compose_services() -> dict[str, dict]:
    doc = yaml.safe_load((REPO / "docker-compose.prod.yml").read_text(encoding="utf-8"))
    return {name: svc for name, svc in doc["services"].items() if svc.get("mem_limit")}


def command_text(service: dict) -> str:
    command = service.get("command") or []
    return " ".join(command) if isinstance(command, list) else str(command)


def test_the_compose_matrix_is_not_empty_and_names_the_services_that_matter():
    services = compose_services()
    assert {"migrate", "backend", "worker", "worker-maintenance"} <= set(services), sorted(services)


@pytest.mark.parametrize("name", sorted(compose_services()))
def test_no_parser_rule_fires_for_any_prod_compose_service_at_its_declared_limit(monkeypatch, tmp_path, name):
    service = compose_services()[name]
    limit = megabytes(service["mem_limit"])
    processes: list[str | None] = [None]   # `python -m app.core.preflight --db`: the entrypoint of every backend service, and migrate's command
    role = role_of(command_text(service), name)
    if role:
        processes.append(role)
    for process in processes:
        assert parser_findings(monkeypatch, tmp_path, limit, process) == [], (name, process, limit)


def test_the_migrate_service_is_small_and_parses_nothing(monkeypatch, tmp_path):
    service = compose_services()["migrate"]
    assert role_of(command_text(service), "migrate") is None and "preflight --db" in command_text(service)
    assert megabytes(service["mem_limit"]) <= 512
    assert parser_findings(monkeypatch, tmp_path, 512, None) == []


def test_the_api_and_worker_containers_hold_the_children_the_defaults_allow():
    s = get_settings()
    services = compose_services()
    api_need = s.parse_child_rss_mb * s.pdf_parse_concurrency * s.parse_process_count
    assert megabytes(services["backend"]["mem_limit"]) > api_need, "the api container must hold its children"
    assert megabytes(services["worker"]["mem_limit"]) > s.parse_child_rss_mb * s.pdf_parse_concurrency


def k8s_workloads() -> list[tuple[str, int, str | None]]:
    """(name, memory limit in MB, role) for every container with a memory limit in k8s/*.yaml."""
    out = []
    for path in sorted((REPO / "k8s").glob("*.yaml")):
        for doc in yaml.safe_load_all(path.read_text(encoding="utf-8")):
            if not isinstance(doc, dict):
                continue
            pod = ((doc.get("spec") or {}).get("template") or {}).get("spec") or {}
            pod = pod or (((doc.get("spec") or {}).get("jobTemplate") or {}).get("spec") or {}).get("template", {}).get("spec", {})
            for container in pod.get("containers") or []:
                limit = ((container.get("resources") or {}).get("limits") or {}).get("memory")
                if limit:
                    command = " ".join(container.get("command") or []) + " " + " ".join(container.get("args") or [])
                    out.append((f"{path.name}:{container.get('name')}", megabytes(limit), role_of(command.strip(), container.get("name", ""))))
    return out


def test_the_k8s_matrix_is_not_empty():
    assert len(k8s_workloads()) >= 4


@pytest.mark.parametrize(("name", "limit", "role"), k8s_workloads())
def test_no_parser_rule_fires_for_any_k8s_workload(monkeypatch, tmp_path, name, limit, role):
    for process in (None, role):
        assert parser_findings(monkeypatch, tmp_path, limit, process) == [], (name, process, limit)


def test_the_helm_values_match_the_k8s_limits_the_rule_is_checked_against(monkeypatch, tmp_path):
    values = yaml.safe_load((REPO / "helm" / "agentic-cfo" / "values.yaml").read_text(encoding="utf-8"))
    roles = {"backend": "api", "worker": "worker", "workerMaintenance": "worker-maintenance"}
    found = 0
    for key, role in roles.items():
        limit = ((values.get(key) or {}).get("resources") or {}).get("limits", {}).get("memory")
        if limit:
            found += 1
            assert parser_findings(monkeypatch, tmp_path, megabytes(limit), role) == [], (key, limit)
    assert found >= 2
