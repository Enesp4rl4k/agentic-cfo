#!/usr/bin/env python
"""Render every page once against a live app and report the ones that broke.

Why this exists
---------------
The backend equivalent, `scripts/route_sweep.py`, called all 309 routes once and
found ten crashes — a board deck that had always come back blank, a workspace
endpoint no user could call twice, a demo button that created a job and never
ran it. Every one was a code path nobody had executed.

The frontend has had none of that treatment: 47 pages, 45 unit tests, and no
check that any page actually renders. This closes that gap the same way — visit
each page as a logged-in user and look for two unambiguous failures:

  * a rendered error boundary (marked with data-error-boundary)
  * an uncaught exception on the page

Console errors and failed API calls are reported separately. A page with no data
behind it will log a failed fetch and still be working correctly, so those are
information, not a verdict.

Usage
-----
    FRONTEND_URL=http://localhost:3000 BACKEND_URL=http://localhost:8000 \\
        python scripts/page_sweep.py

    ... --json report.json   write the full result table
    ... --path /cfo,/ceo     sweep only these paths
    ... --headed             watch it run
    ... --screenshot-dir DIR save a PNG for every failing page
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Any

try:
    from playwright.sync_api import Error as PlaywrightError
    from playwright.sync_api import TimeoutError as PlaywrightTimeout
except ImportError:  # reported properly in main()
    PlaywrightError = PlaywrightTimeout = Exception  # type: ignore[misc,assignment]

ROOT = Path(__file__).resolve().parent.parent
APP_DIR = ROOT / "frontend" / "src" / "app"

NAV_TIMEOUT_MS = 45_000
SETTLE_TIMEOUT_MS = 15_000

# More calls than this to one endpoint on a single page load is a runaway
# effect, not legitimate traffic: a self-inflicted denial of service, and a
# bill when the endpoint costs money.
CHATTY_THRESHOLD = 12

# Pages the sweep does not visit, and why.
SKIP: dict[str, str] = {
    "/auth/sso-callback": "expects an OAuth code in the query string",
    "/billing/success": "expects a Stripe session id in the query string",
}


def discover_paths() -> list[str]:
    """Route paths from the filesystem, so a new page is swept automatically.

    Next route groups — the `(dashboard)` / `(landing)` directories — are not URL
    segments and are stripped.
    """
    paths: list[str] = []
    for page in APP_DIR.rglob("page.tsx"):
        rel = page.relative_to(APP_DIR).parent
        segments = [p for p in rel.parts if not (p.startswith("(") and p.endswith(")"))]
        if any(s.startswith("[") for s in segments):
            continue  # dynamic segment: no id to fill in
        paths.append("/" + "/".join(segments))
    return sorted(set(paths))


# ── Backend session bootstrap ─────────────────────────────────────────────────

def _api(base: str, method: str, path: str, body: dict | None = None,
         token: str | None = None) -> dict:
    data = json.dumps(body or {}).encode() if method in {"POST", "PUT", "PATCH"} else None
    req = urllib.request.Request(f"{base.rstrip('/')}{path}", data=data, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read(200_000).decode("utf-8", "replace") or "{}")
    except urllib.error.HTTPError as exc:
        try:
            return json.loads(exc.read(20_000).decode("utf-8", "replace") or "{}")
        except ValueError:
            return {}
    except (urllib.error.URLError, OSError, TimeoutError):
        return {}


def seed_account(backend: str) -> tuple[str, str]:
    """Create a user with a workspace and the TR pack, and return its credentials.

    Done over the API rather than the UI: the point of the sweep is the pages,
    not the signup form, and the TR-gated pages are the ones most worth seeing.
    """
    email = f"pagesweep-{uuid.uuid4().hex[:8]}@example.com"
    password = "PageSweep1234!x"

    _api(backend, "POST", "/api/v1/auth/register",
         {"email": email, "password": password, "full_name": "Page Sweep"})

    def login() -> str:
        d = _api(backend, "POST", "/api/v1/auth/login",
                 {"email": email, "password": password})
        return ((d.get("data") or {}).get("access_token")) or ""

    token = login()
    if not token:
        raise SystemExit(f"could not authenticate as {email} — is the backend up?")

    _api(backend, "POST", "/api/v1/org/create", {"name": "Page Sweep A.Ş."}, token=token)
    token = login()  # creating the org promotes the user to owner
    _api(backend, "PATCH", "/api/v1/org/me", {
        "country_code": "TR", "base_currency": "TRY",
        "locale": "tr-TR", "regional_packs": ["tr"],
    }, token=token)
    return email, password


# ── Sweep ─────────────────────────────────────────────────────────────────────

def log_in(page: Any, frontend: str, email: str, password: str) -> None:
    # networkidle, not domcontentloaded: the submit button is gated on React
    # state (`disabled={!email || !password}`), so filling the inputs before
    # hydration writes to the DOM, fires no onChange, and is then wiped by the
    # first render — leaving the button disabled forever.
    page.goto(f"{frontend}/auth/login", wait_until="networkidle",
              timeout=NAV_TIMEOUT_MS)
    page.fill("#email", email)
    page.fill("#password", password)
    # The button enabling is the proof that React saw the input.
    page.wait_for_selector('button[type="submit"]:not([disabled])',
                           timeout=SETTLE_TIMEOUT_MS)
    page.click('button[type="submit"]')
    # NextAuth posts, then redirects. Wait for the login form to go away rather
    # than for a specific destination, which differs by onboarding state.
    page.wait_for_url(lambda url: "/auth/login" not in url, timeout=NAV_TIMEOUT_MS)


def visit(page: Any, url: str) -> dict[str, Any]:
    console_errors: list[str] = []
    page_errors: list[str] = []
    failed_requests: list[str] = []

    def on_console(msg: Any) -> None:
        if msg.type == "error":
            console_errors.append(msg.text[:200])

    def on_pageerror(exc: Any) -> None:
        page_errors.append(str(exc)[:300])

    api_calls: dict[str, int] = {}

    def on_response(resp: Any) -> None:
        if resp.status >= 500:
            failed_requests.append(f"{resp.status} {resp.url[:120]}")
        # Count API calls per endpoint. A page that fetches the same thing
        # hundreds of times is broken even when every response is a 200 — a
        # runaway effect is a self-inflicted denial of service and, against a
        # metered LLM, a bill.
        if "/api/v1/" in resp.url:
            key = resp.url.split("/api/v1/", 1)[1].split("?")[0][:60]
            api_calls[key] = api_calls.get(key, 0) + 1

    page.on("console", on_console)
    page.on("pageerror", on_pageerror)
    page.on("response", on_response)
    try:
        resp = page.goto(url, wait_until="domcontentloaded", timeout=NAV_TIMEOUT_MS)
        status = resp.status if resp else 0
        try:
            page.wait_for_load_state("networkidle", timeout=SETTLE_TIMEOUT_MS)
        except PlaywrightTimeout:
            # A page holding an SSE stream open never reaches networkidle. That
            # is the page working, not failing — carry on and inspect what
            # rendered.
            pass
        boundary = page.locator("[data-error-boundary]").count() > 0
        body_text = (page.locator("body").inner_text() or "").strip()
    except (PlaywrightError, PlaywrightTimeout) as exc:  # navigation itself failed
        return {
            "status": 0, "boundary": False, "text_len": 0,
            "page_errors": [f"{type(exc).__name__}: {exc}"[:300]],
            "console_errors": console_errors, "failed_requests": failed_requests,
            "api_calls": api_calls,
        }
    finally:
        page.remove_listener("console", on_console)
        page.remove_listener("pageerror", on_pageerror)
        page.remove_listener("response", on_response)

    return {
        "status": status,
        "boundary": boundary,
        "text_len": len(body_text),
        "page_errors": page_errors,
        "console_errors": console_errors,
        "failed_requests": failed_requests,
        "api_calls": api_calls,
    }


def _launch(pw: Any, *, headless: bool, channel: str | None) -> Any:
    """Launch a browser, preferring one already installed on the machine.

    Playwright's bundled Chromium needs the MSVC runtime and dies with
    "spawn UNKNOWN" (side-by-side configuration is incorrect) on a Windows box
    without it. Installing a system runtime to run a test sweep is the wrong
    trade, and every such machine already has Chrome or Edge — so try those
    first and fall back to the bundled build.
    """
    order = [channel] if channel else ["chrome", "msedge", None]
    if channel == "bundled":
        order = [None]
    last: Exception | None = None
    for ch in order:
        try:
            return pw.chromium.launch(headless=headless, **({"channel": ch} if ch else {}))
        except Exception as exc:  # noqa: BLE001 - try the next channel
            last = exc
    raise SystemExit(
        "no usable browser found (tried chrome, msedge, bundled chromium): "
        f"{str(last).splitlines()[0] if last else '?'}"
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", dest="json_out")
    ap.add_argument("--path", dest="only")
    ap.add_argument("--headed", action="store_true")
    ap.add_argument("--screenshot-dir", dest="shots")
    ap.add_argument("--channel", help="force a browser channel: chrome, msedge, or bundled")
    args = ap.parse_args()

    frontend = os.environ.get("FRONTEND_URL", "http://localhost:3000").rstrip("/")
    backend = os.environ.get("BACKEND_URL", "http://localhost:8000").rstrip("/")

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("playwright is not installed — pip install -r backend/requirements.txt "
              "&& python -m playwright install chromium", file=sys.stderr)
        return 1

    paths = discover_paths()
    if args.only:
        wanted = {p.strip() for p in args.only.split(",")}
        paths = [p for p in paths if p in wanted]
    if not paths:
        print("no pages matched", file=sys.stderr)
        return 1

    email, password = seed_account(backend)
    print(f"session ready ({email})")

    shots = Path(args.shots) if args.shots else None
    if shots:
        shots.mkdir(parents=True, exist_ok=True)

    results: list[dict[str, Any]] = []
    broken: list[dict[str, Any]] = []
    noisy: list[dict[str, Any]] = []
    chatty: list[dict[str, Any]] = []
    skipped = 0

    with sync_playwright() as pw:
        browser = _launch(pw, headless=not args.headed, channel=args.channel)
        context = browser.new_context(viewport={"width": 1440, "height": 900})
        page = context.new_page()
        log_in(page, frontend, email, password)

        for path in paths:
            if path in SKIP:
                skipped += 1
                continue
            row = {"path": path, **visit(page, f"{frontend}{path}")}
            results.append(row)

            # An error boundary or an uncaught exception is unambiguous. A page
            # that rendered almost nothing is the third shape — blank is how the
            # board deck failed on the backend for months.
            failed = (
                row["boundary"]
                or bool(row["page_errors"])
                or row["status"] >= 500
                or row["text_len"] < 40
            )
            if failed:
                broken.append(row)
                why = (
                    "error boundary" if row["boundary"]
                    else "uncaught exception" if row["page_errors"]
                    else f"HTTP {row['status']}" if row["status"] >= 500
                    else f"rendered {row['text_len']} chars"
                )
                print(f"  FAIL  {path:<34} {why}")
                for e in row["page_errors"][:2]:
                    print(f"        {e}")
                if shots:
                    page.screenshot(path=str(shots / f"{path.strip('/').replace('/', '_') or 'root'}.png"),
                                    full_page=True)
            elif row["console_errors"] or row["failed_requests"]:
                noisy.append(row)

            worst = max(row["api_calls"].items(), key=lambda kv: kv[1], default=("", 0))
            if worst[1] > CHATTY_THRESHOLD:
                chatty.append({"path": path, "endpoint": worst[0], "calls": worst[1]})
                print(f"  CHATTY {path:<32} {worst[1]}x /{worst[0]}")

        context.close()
        browser.close()

    print(f"\nswept {len(results)} pages, skipped {skipped}, "
          f"{len(broken)} broken, {len(chatty)} chatty, "
          f"{len(noisy)} with console/API errors")
    for row in noisy:
        first = (row["failed_requests"] or row["console_errors"])[0]
        print(f"  note  {row['path']:<34} {first[:90]}")

    if args.json_out:
        Path(args.json_out).write_text(
            json.dumps(results, indent=1, ensure_ascii=False), encoding="utf-8"
        )
        print(f"full table written to {args.json_out}")

    return 1 if (broken or chatty) else 0


if __name__ == "__main__":
    raise SystemExit(main())
