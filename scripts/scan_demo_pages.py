"""
Live honesty scan — drives the guest demo in a real browser and checks every
role page for honesty violations (DEMO_PLAN §4 / Faz A canlı taraması).

Flow: landing → "Demoyu Dene" (D1 guest session) → upload → "Örnek Şirket
Analizini Başlat" (idempotent seed on the cloned job) → /cfo → scan pages.

Servers must already be running:
  backend  :8000  (DEMO_MODE=true, prefill'den dolu golden org)
  frontend :3000

Usage:
  python scripts/scan_demo_pages.py

Exit 0 = every scanned page is clean (no undefined / NaN / $ / null-ish
artifacts, no auth bounce). Violations print with the offending excerpt.
"""
from __future__ import annotations

import os
import re
import sys

from playwright.sync_api import sync_playwright

BASE = "http://localhost:3000"

# The D2 gate pages (6 role dashboards + command center + cfo) plus the
# main secondary views a tour would visit.
PAGES = [
    "/command-center",
    "/cfo",
    "/ceo",
    "/cto",
    "/cmo",
    "/coo",
    "/chro",
    "/risk",
    "/audit",
    "/pnl",
]

# Honesty violations — any match on the visible body text fails the page.
VIOLATIONS: list[tuple[str, re.Pattern[str]]] = [
    ("undefined", re.compile(r"\bundefined\b")),
    ("NaN", re.compile(r"\bNaN\b")),
    ("dollar-sign", re.compile(r"\$")),
    ("object-Object", re.compile(r"\[object Object\]")),
    ("String(undefined)", re.compile(r"String\(undefined\)")),
    ("null", re.compile(r"\bnull\b")),
]

SHOT_DIR = os.path.join(os.environ.get("TEMP", "."), "agentic_cfo_scan")


def excerpt(text: str, match: re.Match[str]) -> str:
    lo = max(0, match.start() - 60)
    hi = min(len(text), match.end() + 60)
    return " ".join(text[lo:hi].split())


def main() -> int:
    os.makedirs(SHOT_DIR, exist_ok=True)
    failures: dict[str, list[str]] = {}
    console_errors: dict[str, list[str]] = {}

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(locale="tr-TR")
        page = ctx.new_page()

        current = {"route": "landing"}
        page.on(
            "console",
            lambda m: console_errors.setdefault(current["route"], []).append(m.text)
            if m.type == "error"
            else None,
        )

        # ── D1: one-click guest entry ────────────────────────────────────────
        page.goto(BASE + "/", timeout=60000)
        page.wait_for_load_state("networkidle", timeout=60000)
        page.get_by_role("button", name="Demoyu Dene").first.click()
        page.wait_for_url("**/upload", timeout=60000)
        page.wait_for_load_state("networkidle", timeout=60000)
        print("[d1] guest session established — landed on /upload")

        # ── D2: instant dashboard via idempotent seed on the cloned job ─────
        page.get_by_role(
            "button", name=re.compile("Örnek Şirket Analizini Başlat")
        ).first.click()
        page.wait_for_url(re.compile(r"/cfo"), timeout=60000)
        page.wait_for_load_state("networkidle", timeout=60000)
        page.wait_for_timeout(1500)
        print(f"[d2] quick demo seeded — now at {page.url}")

        # ── Scan every page ─────────────────────────────────────────────────
        for route in PAGES:
            current["route"] = route
            console_errors.setdefault(route, [])
            page.goto(BASE + route, timeout=60000)
            page.wait_for_load_state("networkidle", timeout=60000)
            page.wait_for_timeout(4500)  # hydration + context fetch (dev compile)

            final_url = page.url
            if "/auth/login" in final_url or "/auth/register" in final_url:
                failures.setdefault(route, []).append(
                    f"auth bounce → {final_url} (session lost)"
                )

            text = page.inner_text("body")
            hits = []
            for name, pat in VIOLATIONS:
                m = pat.search(text)
                if m:
                    hits.append(f"{name}: …{excerpt(text, m)}…")
            if hits:
                failures[route] = hits

            page.screenshot(
                path=os.path.join(SHOT_DIR, route.strip("/").replace("/", "_") + ".png"),
                full_page=False,
            )
            mark = "FAIL" if hits else "ok"
            errs = len(console_errors[route])
            print(f"[{mark}] {route:20} ({len(text):6} chars, {errs} console errors)")
            for hit in hits:
                print(f"        - {hit}")

        browser.close()

    print(f"\nScreenshots: {SHOT_DIR}")
    total_errs = sum(len(v) for v in console_errors.values())
    print(f"Console errors across pages: {total_errs}")
    for route, errs in console_errors.items():
        if errs:
            print(f"  {route}: {errs[0][:160]}")

    if failures:
        print(f"\nFAILED pages: {len(failures)} / {len(PAGES)}")
        return 1
    print(f"\nALL PAGES CLEAN ({len(PAGES)}/{len(PAGES)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
