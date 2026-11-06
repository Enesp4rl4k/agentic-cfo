"""Plan v10 §O1 — the managed-Postgres overlay drops the in-cluster database and points at a host.

Built with `kubectl kustomize`, which renders offline; skipped where kubectl is absent.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
K8S = ROOT / "k8s"
OVERLAY = ROOT / "k8s-overlays" / "managed-postgres"

pytestmark = pytest.mark.skipif(shutil.which("kubectl") is None, reason="kubectl is not installed")


def _render(path: Path) -> list[dict]:
    out = subprocess.run(
        ["kubectl", "kustomize", str(path)], capture_output=True, text=True, check=True, timeout=60,
    ).stdout
    return [doc for doc in yaml.safe_load_all(out) if doc]


def _named(docs: list[dict], kind: str, name: str) -> dict | None:
    return next((d for d in docs if d["kind"] == kind and d["metadata"]["name"] == name), None)


def test_the_base_still_runs_its_own_postgres():
    docs = _render(K8S)
    assert _named(docs, "StatefulSet", "postgres") is not None
    assert _named(docs, "Service", "postgres") is not None
    assert "POSTGRES_SSLMODE" not in _named(docs, "ConfigMap", "aicfo-config")["data"]


def test_the_overlay_has_no_database_pod_or_service():
    docs = _render(OVERLAY)
    assert _named(docs, "StatefulSet", "postgres") is None
    assert _named(docs, "Service", "postgres") is None


def test_the_overlay_keeps_everything_else():
    base = {(d["kind"], d["metadata"]["name"]) for d in _render(K8S)}
    overlay = {(d["kind"], d["metadata"]["name"]) for d in _render(OVERLAY)}
    assert base - overlay == {("StatefulSet", "postgres"), ("Service", "postgres")}
    assert overlay <= base


def test_the_overlay_asks_for_tls_and_a_host_that_must_be_edited():
    config = _named(_render(OVERLAY), "ConfigMap", "aicfo-config")["data"]
    assert config["POSTGRES_SSLMODE"] == "require"
    assert config["POSTGRES_HOST"].endswith(".invalid")
    # What the base set is still there to be edited from.
    assert config["POSTGRES_DB"] == "aicfo" and config["POSTGRES_USER"] == "aicfo"


def test_every_pod_that_needs_the_database_reads_the_same_config():
    docs = _render(OVERLAY)
    for kind, name in (("Deployment", "backend"), ("Deployment", "worker"),
                       ("Deployment", "worker-maintenance"), ("Job", "db-migration")):
        workload = next((d for d in docs if d["kind"] == kind and d["metadata"]["name"].endswith(name)), None)
        assert workload is not None, (kind, name)
        containers = workload["spec"]["template"]["spec"]["containers"]
        refs = {e["configMapRef"]["name"] for c in containers for e in c.get("envFrom", []) if "configMapRef" in e}
        assert "aicfo-config" in refs, (kind, name)
