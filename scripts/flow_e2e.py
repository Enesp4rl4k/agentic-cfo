#!/usr/bin/env python
"""Walk the governance chain the way a user walks it — through the browser.

Why this exists
---------------
`tr-governance-e2e.sh` proves the chain works over the API: upload, analysis,
THP journal, SMMM approval, sealed packet, institutionalisation index. What it
cannot prove is that any of it is reachable by clicking.

That gap has bitten already. The related-party register shipped correct and
unreachable — no UI, so no register, so a rule that could never fire. The board
deck came back blank for months behind an endpoint that answered 200. `page_
sweep.py` then proved every page renders, which is not the same as proving a
page does its job.

So this drives the real UI: the file picker on /upload, the "Otopilotu Başlat"
button on /tr-vertical, the approve control on /smmm-onay. It asserts on what
the user would see — a journal with entries, a queue that empties, a packet with
a hash — and it fails loudly when a step is present but inert.

Usage
-----
    FRONTEND_URL=http://localhost:3000 BACKEND_URL=http://localhost:8000 \\
        python scripts/flow_e2e.py

    ... --headed          watch it
    ... --screenshot-dir DIR   save a PNG at every step, and on failure
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Any

try:
    from playwright.sync_api import TimeoutError as PlaywrightTimeout
except ImportError:  # reported properly in main()
    PlaywrightTimeout = Exception  # type: ignore[misc,assignment]

ROOT = Path(__file__).resolve().parent.parent
CSV = ROOT / "scripts" / "fixtures" / "golden_path_sample_en_usd.csv"

NAV_TIMEOUT_MS = 45_000
ANALYSIS_TIMEOUT_S = 300
AUTOPILOT_TIMEOUT_MS = 240_000

GREEN, RED, CYAN, YELLOW, RESET = "\033[0;32m", "\033[0;31m", "\033[0;36m", "\033[1;33m", "\033[0m"


def ok(msg: str) -> None:
    print(f"{GREEN}OK{RESET}   {msg}")


def step(msg: str) -> None:
    print(f"{CYAN}->{RESET}   {msg}")


def warn(msg: str) -> None:
    print(f"{YELLOW}WARN{RESET} {msg}")


class Failure(Exception):
    """A step the user could not complete."""


# ── Backend helpers (setup only; the flow itself goes through the UI) ─────────

def _api(base: str, method: str, path: str, body: dict | None = None,
         token: str | None = None) -> dict:
    data = json.dumps(body or {}).encode() if method in {"POST", "PUT", "PATCH"} else None
    req = urllib.request.Request(f"{base.rstrip('/')}{path}", data=data, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read(500_000).decode("utf-8", "replace") or "{}")
    except urllib.error.HTTPError as exc:
        try:
            return json.loads(exc.read(50_000).decode("utf-8", "replace") or "{}")
        except ValueError:
            return {}
    except (urllib.error.URLError, OSError, TimeoutError):
        return {}


def seed_account(backend: str) -> tuple[str, str, str]:
    """Register, create the workspace, enable the TR pack. Returns creds + token.

    Account setup is not what this script is testing, and doing it over the API
    keeps a signup-form change from failing a run about the accounting chain.
    """
    email = f"flow-{uuid.uuid4().hex[:8]}@example.com"
    password = "FlowE2E1234!x"

    _api(backend, "POST", "/api/v1/auth/register",
         {"email": email, "password": password, "full_name": "Flow E2E"})

    def login() -> str:
        d = _api(backend, "POST", "/api/v1/auth/login",
                 {"email": email, "password": password})
        return ((d.get("data") or {}).get("access_token")) or ""

    token = login()
    if not token:
        raise Failure(f"could not authenticate as {email} — is the backend up?")

    _api(backend, "POST", "/api/v1/org/create", {"name": "Flow E2E A.Ş."}, token=token)
    token = login()  # creating the org promotes to owner
    _api(backend, "PATCH", "/api/v1/org/me", {
        "country_code": "TR", "base_currency": "TRY",
        "locale": "tr-TR", "regional_packs": ["tr"],
    }, token=token)
    return email, password, token


def wait_for_analysis(backend: str, token: str, timeout_s: int) -> str:
    """Poll until the newest job completes, and return its id.

    Polled over the API rather than by watching the UI: how the dashboard
    surfaces progress is a separate question from whether the pipeline ran, and
    conflating them makes a failure ambiguous.
    """
    deadline = time.monotonic() + timeout_s
    job_id = ""
    while time.monotonic() < deadline:
        data = _api(backend, "GET", "/api/v1/jobs", token=token).get("data")
        rows = data if isinstance(data, list) else (data or {}).get("jobs") or []
        if rows:
            job_id = str(rows[0].get("id") or rows[0].get("job_id") or "")
            status = str(rows[0].get("status") or "")
            if status == "completed":
                return job_id
            if status == "failed":
                raise Failure(f"analysis failed for job {job_id}")
        time.sleep(4)
    raise Failure(f"analysis did not complete within {timeout_s}s (job={job_id or '?'})")


# ── UI steps ──────────────────────────────────────────────────────────────────

class Flow:
    def __init__(self, page: Any, frontend: str, shots: Path | None) -> None:
        self.page = page
        self.frontend = frontend.rstrip("/")
        self.shots = shots
        self._n = 0

    def shot(self, name: str) -> None:
        if not self.shots:
            return
        self._n += 1
        self.page.screenshot(path=str(self.shots / f"{self._n:02d}-{name}.png"), full_page=True)

    def goto(self, path: str) -> None:
        self.page.goto(f"{self.frontend}{path}", wait_until="networkidle",
                       timeout=NAV_TIMEOUT_MS)
        self.dismiss_onboarding()

    def dismiss_onboarding(self) -> None:
        """Close the onboarding tour if it is up.

        The upload page marks the tour pending, so the dashboard opens it as a
        modal right after a first upload. That is the intended welcome, not a
        defect — but it is a full-screen overlay, and a script that does not
        close it spends sixty retries clicking through a backdrop. A first-time
        user closes it; so does this.
        """
        for label in ("Başlangıç rehberini kapat", "Rehberi kapat"):
            button = self.page.get_by_role("button", name=label)
            if button.count() and button.first.is_visible():
                button.first.click()
                self.page.wait_for_timeout(400)
                return

    def log_in(self, email: str, password: str) -> None:
        step("login form")
        self.goto("/auth/login")
        self.page.fill("#email", email)
        self.page.fill("#password", password)
        # The submit button is gated on React state; it enabling is the proof
        # that the framework saw the input rather than just the DOM.
        self.page.wait_for_selector('button[type="submit"]:not([disabled])', timeout=15_000)
        self.page.click('button[type="submit"]')
        # The page signs in with `redirect: false` and then `router.push`, which
        # is a client-side route change — there is no navigation event to wait
        # for, so `wait_for_url` times out or passes by luck depending on
        # timing. Wait for the app shell instead: the dashboard nav only exists
        # once the session is live.
        try:
            self.page.wait_for_function(
                "() => !location.pathname.startsWith('/auth/login')",
                timeout=NAV_TIMEOUT_MS,
            )
        except PlaywrightTimeout as exc:
            self.shot("login-stuck")
            body = (self.page.locator("body").inner_text() or "")[:200]
            raise Failure(f"login did not leave the form. Page said: {body!r}") from exc
        self.shot("logged-in")
        ok("signed in through the form")

    def upload(self, csv: Path) -> None:
        """Pick the file, then confirm the column mapping.

        Uploading is two steps, not one: the file goes to a data-quality check
        that proposes a date/amount column mapping, and nothing is uploaded
        until the user accepts it. A script that only set the file input
        produced a page full of parsed columns and no job — which is exactly
        what a user who walks away at the mapping screen produces.
        """
        step("upload page — file picker")
        self.goto("/upload")
        # The input is visually hidden behind a dropzone; that is styling, and
        # setting files on it is what the dropzone does too.
        self.page.set_input_files('input[type="file"]', str(csv))
        self.shot("file-picked")
        ok(f"picked {csv.name}")

        # The mapping step is conditional: when the date and amount columns are
        # detected confidently the file uploads straight away, and the button
        # never renders. Waiting unconditionally for it fails on exactly the
        # files that work best. So wait for whichever happens.
        step("upload page — mapping step, if the file needs one")
        confirm = self.page.get_by_role("button", name="Eşleştirmeyi Onayla & Yükle")
        deadline = time.monotonic() + NAV_TIMEOUT_MS / 1000
        while time.monotonic() < deadline:
            if "/upload" not in self.page.url:
                break  # already uploaded and moved on
            if confirm.count() and confirm.first.is_visible():
                if confirm.first.is_disabled():
                    self.shot("mapping-disabled")
                    raise Failure(
                        "'Eşleştirmeyi Onayla & Yükle' is disabled — the date and "
                        "amount columns were not detected, so the user is stuck"
                    )
                confirm.first.click()
                ok("column mapping confirmed")
                break
            self.page.wait_for_timeout(500)

        # Either path has to end somewhere other than the upload form. Landing
        # back on the marketing page counts as not arriving: that was the bug
        # this step caught first.
        try:
            self.page.wait_for_function(
                "() => !location.pathname.startsWith('/upload')",
                timeout=NAV_TIMEOUT_MS,
            )
        except PlaywrightTimeout as exc:
            self.shot("upload-stuck")
            body = (self.page.locator("body").inner_text() or "")[:200]
            raise Failure(
                f"upload never completed (url={self.page.url}, page said {body!r})"
            ) from exc

        landed = self.page.url
        if "?job=" not in landed:
            self.shot("no-job-in-url")
            raise Failure(f"upload finished but carried no job id: {landed}")
        self.shot("uploaded")
        ok(f"uploaded, landed on {landed.split('?')[0]}")

    def run_autopilot(self) -> None:
        step("tr-vertical — Otopilotu Başlat")
        self.goto("/tr-vertical")
        self.dismiss_onboarding()
        button = self.page.get_by_role("button", name="Otopilotu Başlat")
        if button.count() == 0:
            raise Failure("no 'Otopilotu Başlat' button on /tr-vertical")
        if button.first.is_disabled():
            raise Failure(
                "'Otopilotu Başlat' is disabled — the page did not pick up the "
                "completed analysis, so the user cannot start the journal"
            )
        button.first.click()
        # The button reads "Çalışıyor…" while it runs; wait for it to come back.
        try:
            self.page.wait_for_selector(
                'button:has-text("Otopilotu Başlat")', timeout=AUTOPILOT_TIMEOUT_MS
            )
        except PlaywrightTimeout as exc:
            self.shot("autopilot-stuck")
            raise Failure("autopilot never finished (button stayed in 'Çalışıyor…')") from exc
        self.shot("autopilot-done")
        ok("autopilot ran")

    def approve_queue(self) -> int:
        step("smmm-onay — approve every pending entry")
        self.goto("/smmm-onay")
        self.dismiss_onboarding()
        approved = 0
        for _ in range(50):  # bounded: a queue that never empties is a failure
            buttons = self.page.get_by_role("button", name="Onayla")
            if buttons.count() == 0:
                break
            buttons.first.click()
            self.page.wait_for_timeout(700)
            approved += 1
        self.shot("queue-approved")
        if approved == 0:
            raise Failure(
                "no 'Onayla' control on /smmm-onay — either the journal produced "
                "nothing to review, or the queue is not reachable"
            )
        ok(f"approved {approved} entries by clicking")
        return approved


def verify_outcome(backend: str, token: str, job_id: str) -> None:
    """The chain's own record, checked after the UI drove it.

    Asserted over the API on purpose: the point is that clicking through the
    interface produced the same durable artefacts the API path produces, not
    that some text appeared on a page.
    """
    step("verify the journal, the queue and the packet")

    queue = _api(backend, "GET", f"/api/v1/smmm/onay/queue/{job_id}", token=token).get("data") or {}
    pending = int(queue.get("bekleyen") or 0)
    if pending:
        raise Failure(f"{pending} entries still pending after approving through the UI")
    ok("review queue is empty")

    built = _api(backend, "POST", f"/api/v1/smmm/defensibility/{job_id}/build",
                 {}, token=token).get("data") or {}
    packet_id = str(built.get("id") or "")
    entry_count = int((built.get("summary") or {}).get("entry_count") or 0)
    if not packet_id or entry_count == 0:
        raise Failure(f"packet did not build over the UI-produced journal: {built}")
    ok(f"packet built over {entry_count} entries")

    sealed = _api(backend, "POST", f"/api/v1/smmm/defensibility/{packet_id}/finalize",
                  {"statement": "UI akışı ile onaylanmıştır."}, token=token).get("data") or {}
    if str(sealed.get("status")) != "finalized" or not sealed.get("content_hash"):
        raise Failure(f"packet did not seal: {sealed}")
    ok(f"packet sealed ({str(sealed['content_hash'])[:16]}…)")

    # Human review is what the index's oversight dimension measures, so a chain
    # driven by clicking has to move it exactly as the API path does.
    index = _api(backend, "POST", "/api/v1/institutionalization/compute",
                 {}, token=token).get("data") or {}
    score = int(index.get("overall_score") or 0)
    if score <= 0:
        raise Failure("institutionalisation index did not compute")
    ok(f"institutionalisation index: {score} ({index.get('grade')})")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--headed", action="store_true")
    ap.add_argument("--screenshot-dir", dest="shots")
    ap.add_argument("--channel", help="chrome, msedge, or bundled")
    args = ap.parse_args()

    frontend = os.environ.get("FRONTEND_URL", "http://localhost:3000").rstrip("/")
    backend = os.environ.get("BACKEND_URL", "http://localhost:8000").rstrip("/")

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("playwright is not installed — pip install -r backend/requirements.txt "
              "&& python -m playwright install chromium", file=sys.stderr)
        return 1

    if not CSV.exists():
        print(f"fixture missing: {CSV}", file=sys.stderr)
        return 1

    shots = Path(args.shots) if args.shots else None
    if shots:
        shots.mkdir(parents=True, exist_ok=True)

    started = time.monotonic()
    try:
        email, password, token = seed_account(backend)
        print(f"session ready ({email})")

        with sync_playwright() as pw:
            browser = _launch(pw, headless=not args.headed, channel=args.channel)
            context = browser.new_context(viewport={"width": 1440, "height": 900})
            page = context.new_page()
            flow = Flow(page, frontend, shots)

            flow.log_in(email, password)
            flow.upload(CSV)

            step(f"waiting for the analysis (timeout {ANALYSIS_TIMEOUT_S}s)")
            job_id = wait_for_analysis(backend, token, ANALYSIS_TIMEOUT_S)
            ok(f"analysis completed (job={job_id})")

            flow.run_autopilot()
            flow.approve_queue()

            context.close()
            browser.close()

        verify_outcome(backend, token, job_id)
    except Failure as exc:
        print(f"\n{RED}  FLOW E2E FAILED{RESET}: {exc}\n")
        return 1

    elapsed = int(time.monotonic() - started)
    print(f"\n{GREEN}  FLOW E2E PASSED ({elapsed}s){RESET}\n")
    return 0


def _launch(pw: Any, *, headless: bool, channel: str | None) -> Any:
    """Prefer a browser already on the machine.

    Playwright's bundled Chromium needs the MSVC runtime and dies with
    "spawn UNKNOWN" on a Windows box without it. Installing a system runtime to
    run a test is the wrong trade when Chrome or Edge is already there.
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
    raise Failure(
        "no usable browser (tried chrome, msedge, bundled chromium): "
        f"{str(last).splitlines()[0] if last else '?'}"
    )


if __name__ == "__main__":
    raise SystemExit(main())
