"""Dependency pins: the backend installs the same versions everywhere, and a
change to them is a reviewed diff, not whatever the index served that day.

requirements.txt is the human-edited list of direct dependencies and every line
is an exact pin. constraints.txt pins every package, direct and transitive, and
is applied to each install (pip install -r requirements.txt -c constraints.txt).
Update procedure: docs/ops/dependency-pinning.md.

The installed-environment checks run only when CHECK_INSTALLED_PINS=1 (the
Backend CI job sets it right after its install): a developer's own environment
holds other tools, and those must not fail the suite.
"""

from __future__ import annotations

import os
import re
from importlib import metadata
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
BACKEND = REPO / "backend"
REQUIREMENTS = BACKEND / "requirements.txt"
CONSTRAINTS = BACKEND / "constraints.txt"

_PIN = re.compile(r"^(?P<name>[A-Za-z0-9][A-Za-z0-9._-]*)(?P<extras>\[[^\]]+\])?==(?P<version>[^\s;,<>=!~]+)$")
# Installed alongside Python itself, not by requirements.txt.
_TOOLING = {"pip", "setuptools", "wheel", "pkg-resources"}


def _canon(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _lines(path: Path) -> list[tuple[int, str]]:
    out = []
    for no, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.split(" #", 1)[0].strip()
        if line and not line.startswith("#"):
            out.append((no, line))
    return out


def _parse(path: Path) -> tuple[dict[str, str], list[str]]:
    pins: dict[str, str] = {}
    bad: list[str] = []
    for no, line in _lines(path):
        m = _PIN.match(line)
        if m is None:
            bad.append(f"{path.name}:{no}: {line!r}")
        else:
            pins[_canon(m["name"])] = m["version"]
    return pins, bad


def test_every_direct_dependency_is_an_exact_pin() -> None:
    _, bad = _parse(REQUIREMENTS)
    assert not bad, "requirements.txt must hold only name==version lines (no >=, ~=, ranges, URLs, -r):\n" + "\n".join(bad)


def test_every_constraint_is_an_exact_pin() -> None:
    _, bad = _parse(CONSTRAINTS)
    assert not bad, "constraints.txt must hold only name==version lines:\n" + "\n".join(bad)


def test_the_lock_covers_every_direct_dependency_at_the_same_version() -> None:
    direct, _ = _parse(REQUIREMENTS)
    locked, _ = _parse(CONSTRAINTS)
    missing = sorted(set(direct) - set(locked))
    differ = sorted(f"{n}: requirements {direct[n]} != constraints {locked[n]}" for n in set(direct) & set(locked) if direct[n] != locked[n])
    assert not missing, f"constraints.txt lacks direct dependencies {missing}; regenerate it (docs/ops/dependency-pinning.md)"
    assert not differ, "requirements.txt and constraints.txt disagree:\n" + "\n".join(differ)


def test_every_install_applies_the_constraints() -> None:
    files = [REPO / ".github" / "workflows" / "ci.yml", REPO / ".github" / "workflows" / "e2e.yml", BACKEND / "Dockerfile"]
    offenders = []
    for f in files:
        for no, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            if re.search(r"pip install\b", line) and "--upgrade pip" not in line and "-c constraints.txt" not in line:
                offenders.append(f"{f.name}:{no}: {line.strip()}")
    assert not offenders, "pip install without -c constraints.txt:\n" + "\n".join(offenders)


@pytest.mark.skipif(os.environ.get("CHECK_INSTALLED_PINS") != "1", reason="CHECK_INSTALLED_PINS=1 is set by the Backend CI job")
def test_the_installed_environment_is_exactly_the_lock() -> None:
    locked, _ = _parse(CONSTRAINTS)
    installed = {_canon(d.metadata["Name"]): d.version for d in metadata.distributions() if d.metadata["Name"]}
    for tool in _TOOLING:
        installed.pop(tool, None)
    unlocked = sorted(f"{n}=={v}" for n, v in installed.items() if n not in locked)
    wrong = sorted(f"{n}: installed {v}, locked {locked[n]}" for n, v in installed.items() if n in locked and locked[n] != v)
    stale = sorted(n for n in locked if n not in installed)
    assert not unlocked, "installed but missing from constraints.txt (the lock has rotted):\n" + "\n".join(unlocked)
    assert not wrong, "installed version differs from constraints.txt:\n" + "\n".join(wrong)
    assert not stale, "in constraints.txt but not installed (stale entry):\n" + "\n".join(stale)
