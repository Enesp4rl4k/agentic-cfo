#!/usr/bin/env python3
"""
verify.py — Deterministic CI gate (Windows-friendly mirror of verify.sh).

Usage:
  python scripts/verify.py
  python scripts/verify.py --fast
  python scripts/verify.py --fast --backend
  python scripts/verify.py --frontend

Exit 0 = all checks passed. Non-zero = do not proceed.

Install backend deps first: pip install -r backend/requirements.txt
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass


def _ok(msg: str) -> None:
    print(f"✓ {msg}")


def _fail(msg: str) -> None:
    print(f"✗ FAILED: {msg}")


def _info(msg: str) -> None:
    print(f"→ {msg}")


def _warn(msg: str) -> None:
    print(f"⚠ {msg}")


def _run(name: str, argv: list[str], *, cwd: Path | None = None) -> bool:
    _info(f"Running: {name}")
    try:
        result = subprocess.run(argv, cwd=str(cwd or ROOT), check=False)
    except FileNotFoundError:
        _fail(f"{name} (executable not found: {argv[0]})")
        return False
    if result.returncode == 0:
        _ok(name)
        print()
        return True
    _fail(name)
    print()
    return False


def main() -> int:
    parser = argparse.ArgumentParser(description="Agentic CFO verify gate")
    parser.add_argument("--fast", action="store_true", help="Skip mypy")
    parser.add_argument("--backend", action="store_true", help="Backend checks only")
    parser.add_argument("--frontend", action="store_true", help="Frontend checks only")
    args = parser.parse_args()

    run_backend = True
    run_frontend = True
    if args.backend and not args.frontend:
        run_frontend = False
    if args.frontend and not args.backend:
        run_backend = False

    failures = 0
    checks = 0
    py = sys.executable

    if run_backend:
        print("\n════════════════════════════════════════")
        print("  BACKEND CHECKS")
        print("════════════════════════════════════════\n")
        _info(f"Using: {sys.version.split()[0]} ({py})")

        checks += 1
        if not _run(
            "pytest (unit tests)",
            [
                py,
                "-m",
                "pytest",
                str(ROOT / "backend" / "tests"),
                "-q",
                "--tb=short",
                "--no-header",
            ],
        ):
            failures += 1

        checks += 1
        if _run("ruff (lint)", [py, "-m", "ruff", "check", str(ROOT / "backend" / "app"), "--output-format=concise"]):
            pass
        else:
            # ruff missing is a warning in verify.sh, not a hard fail
            ruff_mod = subprocess.run([py, "-m", "ruff", "--version"], check=False, capture_output=True)
            if ruff_mod.returncode != 0:
                _warn("ruff not installed — install with: pip install ruff")
                checks -= 1
            else:
                failures += 1

        if args.fast:
            _warn("mypy skipped (--fast mode)")
        else:
            checks += 1
            mypy = subprocess.run([py, "-m", "mypy", "--version"], check=False, capture_output=True)
            if mypy.returncode != 0:
                _warn("mypy not installed — install with: pip install mypy")
                checks -= 1
            else:
                # 3a. Strict allowlist — BLOCKING (module-by-module paydown ratchet).
                if not _run(
                    "mypy (strict allowlist)",
                    [py, "-m", "mypy", "--config-file", "mypy_strict.ini"],
                    cwd=ROOT / "backend",
                ):
                    failures += 1
                # 3b. Full tree — NON-BLOCKING advisory (~590 legacy errors).
                _info("Running: mypy (full tree, advisory)")
                full = subprocess.run(
                    [
                        py, "-m", "mypy", str(ROOT / "backend" / "app"),
                        "--ignore-missing-imports", "--no-error-summary", "--pretty",
                    ],
                    cwd=str(ROOT), check=False,
                )
                if full.returncode == 0:
                    _ok("mypy (full tree, advisory) — clean")
                else:
                    _warn("mypy (full tree, advisory) — legacy errors remain (not blocking)")
                print()

    if run_frontend:
        print("\n════════════════════════════════════════")
        print("  FRONTEND CHECKS")
        print("════════════════════════════════════════\n")
        node = shutil.which("node")
        npm = shutil.which("npm")
        if not node or not npm:
            _warn("Node.js/npm not found in PATH — skipping frontend checks")
            failures += 1
        else:
            _info(f"Using: Node ({node})")
            frontend = ROOT / "frontend"
            if not (frontend / "node_modules").is_dir():
                _info("node_modules not found — running npm install...")
                subprocess.run([npm, "install", "--prefix", str(frontend), "--silent"], check=False)
            checks += 1
            if not _run("tsc (type check)", [npm, "run", "--prefix", str(frontend), "typecheck"]):
                failures += 1

    print()
    print("════════════════════════════════════════")
    if failures == 0:
        print(f"  ✓ ALL CHECKS PASSED ({checks} checks)")
        print("════════════════════════════════════════\n")
        return 0
    print(f"  ✗ {failures} CHECK(S) FAILED (of {checks})")
    print("════════════════════════════════════════\n")
    return 1


if __name__ == "__main__":
    sys.exit(main())
