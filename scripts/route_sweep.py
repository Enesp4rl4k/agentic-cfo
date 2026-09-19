#!/usr/bin/env python
"""Call every registered route once against a live instance and report the 5xx.

Why this exists
---------------
Seven real bugs in this codebase were found by running it, not by the 1765-test
suite, and every one had the same shape: a route nobody had ever called. A
board deck that came back blank, a workspace nobody could create, a demo button
that created a job and never ran it. None of them were type errors or logic the
tests could see — they were code paths that had simply never executed.

So: hit each route once and look only for 500s. A 401/403/404/422 means the
route is alive and rejecting input properly, which is all this sweep claims to
check. It is a liveness probe, not a functional test.

Usage
-----
    BACKEND_URL=http://127.0.0.1:8000 python scripts/route_sweep.py
    ... --json report.json      write the full result table
    ... --module ceo,org        sweep only these routers
    ... --include-delete        also call DELETE routes (off by default)

Exit code is the number of routes that returned 5xx, capped at 1.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
import uuid
from typing import Any

TIMEOUT = 60

# Routes we do not call, and why. Anything that reaches outside the process, or
# that would destroy state the rest of the sweep depends on, stays on this list.
SKIP: dict[str, str] = {
    "/api/v1/auth/logout": "invalidates the sweep's own session",
    "/api/v1/org/leave": "would drop the org the TR routes are gated on",
    "/api/v1/bot-webhooks/whatsapp": "inbound webhook — may trigger an outbound reply",
    "/api/v1/bot-webhooks/slack": "inbound webhook — may trigger an outbound reply",
    "/api/v1/email/ingest": "may send mail",
    "/api/v1/org/invite": "sends an invitation email",
    "/api/v1/billing/checkout": "creates a Stripe session",
    "/api/v1/billing/portal": "creates a Stripe session",
}

# Path-parameter values. Anything not listed gets a random UUID, which should
# produce a clean 404 rather than a crash — that is itself part of the check.
PARAM_DEFAULTS: dict[str, str] = {
    "org_id": "",           # filled from the session
    "job_id": "",           # filled from the seeded analysis job
    "period": "2026-09",
    "domain": "cfo",
    "agent": "cfo",
    "role": "cfo",
    "provider": "parasut",
    "connector": "github",
    "name": "github",
    "task_name": "rag_backfill",
    "format": "json",
}


class Session:
    def __init__(self, base: str) -> None:
        self.base = base.rstrip("/")
        self.token: str | None = None

    def call(
        self,
        method: str,
        path: str,
        body: dict[str, Any] | None = None,
        *,
        max_bytes: int = 2000,
    ) -> tuple[int, str]:
        url = f"{self.base}{path}"
        data = json.dumps(body or {}).encode() if method in {"POST", "PUT", "PATCH"} else None
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("Content-Type", "application/json")
        if self.token:
            req.add_header("Authorization", f"Bearer {self.token}")
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                return resp.status, resp.read(max_bytes).decode("utf-8", "replace")
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read(max_bytes).decode("utf-8", "replace")
        except (urllib.error.URLError, OSError, TimeoutError) as exc:
            # Status 0 means the request never got an answer — a refused
            # connection, a reset, a DNS failure. Reported like a crash.
            return 0, f"{type(exc).__name__}: {exc}"

    def json_call(
        self, method: str, path: str, body: dict | None = None, *, max_bytes: int = 2000
    ) -> dict:
        _, text = self.call(method, path, body, max_bytes=max_bytes)
        try:
            return json.loads(text)
        except (ValueError, TypeError):  # a non-JSON body is a valid answer
            return {}


def bootstrap(s: Session) -> dict[str, str]:
    """Register, create a workspace, enable the TR pack, seed one analysis job.

    Gated routes are the ones most worth sweeping — without an org and the TR
    pack, a third of the surface answers 400 and the sweep proves nothing.
    """
    email = f"sweep-{uuid.uuid4().hex[:8]}@example.com"
    password = "Sweep1234!x"
    s.call("POST", "/api/v1/auth/register", {
        "email": email, "password": password, "full_name": "Route Sweep",
    })

    def login() -> str:
        d = s.json_call("POST", "/api/v1/auth/login", {"email": email, "password": password})
        return ((d.get("data") or {}).get("access_token")) or ""

    s.token = login()
    if not s.token:
        raise SystemExit(f"could not authenticate as {email}")

    s.call("POST", "/api/v1/org/create", {"name": "Route Sweep A.Ş."})
    s.token = login()  # org creation promotes to owner; refresh the claim
    s.call("PATCH", "/api/v1/org/me", {
        "country_code": "TR", "base_currency": "TRY",
        "locale": "tr-TR", "regional_packs": ["tr"],
    })

    me = s.json_call("GET", "/api/v1/org/me")
    org_id = str((me.get("data") or {}).get("id") or "")

    job_id = ""
    jobs = s.json_call("GET", "/api/v1/analysis")
    items = (jobs.get("data") or {})
    if isinstance(items, dict):
        rows = items.get("jobs") or items.get("items") or []
    else:
        rows = items or []
    if rows:
        job_id = str(rows[0].get("id") or rows[0].get("job_id") or "")

    return {"org_id": org_id, "job_id": job_id}


def fill(path: str, values: dict[str, str]) -> str:
    out = path
    while "{" in out:
        start = out.index("{")
        end = out.index("}", start)
        name = out[start + 1:end]
        val = values.get(name) or PARAM_DEFAULTS.get(name) or ""
        if not val:
            val = str(uuid.uuid4())
        out = out[:start] + val + out[end + 1:]
    return out


def load_routes(s: Session, modules: set[str] | None) -> list[dict[str, Any]]:
    # The schema is a few hundred KB — read it whole, not the 2 KB the sweep
    # keeps for error bodies.
    spec = s.json_call("GET", "/openapi.json", max_bytes=32 * 1024 * 1024)
    paths = spec.get("paths") or {}
    if not paths:
        raise SystemExit("could not read /openapi.json from the running instance")
    routes: list[dict[str, Any]] = []
    for path, ops in paths.items():
        if not path.startswith("/api/v1"):
            continue
        for method, op in ops.items():
            m = method.upper()
            if m not in {"GET", "POST", "PUT", "PATCH", "DELETE"}:
                continue
            tags = op.get("tags") or []
            tag = str(tags[0]) if tags else "?"
            if modules and tag not in modules:
                continue
            routes.append({"method": m, "path": path, "tag": tag})
    return sorted(routes, key=lambda r: (r["tag"], r["path"], r["method"]))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", dest="json_out")
    ap.add_argument("--module", dest="modules")
    ap.add_argument("--include-delete", action="store_true")
    args = ap.parse_args()

    base = os.environ.get("BACKEND_URL", "").strip()
    if not base:
        print("BACKEND_URL is required", file=sys.stderr)
        return 1

    s = Session(base)
    values = bootstrap(s)
    print(f"session ready (org={values['org_id'][:8] or '-'} job={values['job_id'][:8] or '-'})")

    modules = {m.strip() for m in args.modules.split(",")} if args.modules else None
    routes = load_routes(s, modules)

    results: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    degraded: list[dict[str, Any]] = []
    skipped = 0

    for r in routes:
        if r["path"] in SKIP or (r["method"] == "DELETE" and not args.include_delete):
            skipped += 1
            continue
        concrete = fill(r["path"], values)
        status, body = s.call(r["method"], concrete)
        row = {**r, "status": status, "body": body[:300]}
        results.append(row)
        # 500 (or a dead connection) means nobody handled it. 502/503 are
        # declared answers — an unconfigured integration, an absent upstream —
        # so they are reported but do not fail the sweep.
        # No retry, and no "probably just contention" bucket. Every
        # "database is locked" this sweep produced turned out to be one missing
        # commit in the semantic rebuild, which held a write transaction open
        # for the life of the process. A tolerance for flakiness would have
        # hidden it.
        if status in (500, 0):
            failures.append(row)
            print(f"  {status:>3}  {r['method']:<6} {r['path']}")
            print(f"       {body[:200].strip()}")
        elif status in (502, 503):
            degraded.append(row)

    print(
        f"\nswept {len(results)} routes, skipped {skipped}, "
        f"{len(failures)} crashed (500), {len(degraded)} degraded (502/503)"
    )
    for d in degraded:
        print(f"  {d['status']}  {d['method']:<6} {d['path']}  {d['body'][:90].strip()}")
    by_tag: dict[str, int] = {}
    for f in failures:
        by_tag[f["tag"]] = by_tag.get(f["tag"], 0) + 1
    for tag, n in sorted(by_tag.items(), key=lambda kv: -kv[1]):
        print(f"  {tag:<28} {n}")

    if args.json_out:
        with open(args.json_out, "w", encoding="utf-8") as fh:
            json.dump(results, fh, indent=1, ensure_ascii=False)
        print(f"full table written to {args.json_out}")

    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
