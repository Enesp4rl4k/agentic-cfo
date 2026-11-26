"""The two guards around a parser child: the OOM-victim preference and the resident-memory watchdog.

`/proc` is mocked with a directory of `stat` files; the Linux-only tests start real children and run in CI.
"""
from __future__ import annotations

import os
import sys
import time

import pytest

from app.config import get_settings
from app.services import parser_guard, pdf_isolation, sheet_child, sheet_isolation

LINUX = sys.platform.startswith("linux")
PAGE_KB = (os.sysconf("SC_PAGE_SIZE") // 1024) if hasattr(os, "sysconf") else 4


def fake_proc(root, processes: dict[int, tuple[int, int, int]], name: str = "py (thon)") -> str:
    """processes: pid -> (ppid, pgrp, resident pages), written as /proc/<pid>/stat."""
    for pid, (ppid, pgrp, rss) in processes.items():
        (root / str(pid)).mkdir(parents=True)
        rest = ["S", str(ppid), str(pgrp)] + ["0"] * 18 + [str(rss)] + ["0"] * 30    # rss is the 22nd field after the name
        (root / str(pid) / "stat").write_text(f"{pid} ({name}) " + " ".join(rest))
    (root / "self").mkdir()      # not a pid: ignored
    return str(root)


def test_the_child_writes_a_high_oom_score_to_the_file_it_is_given(tmp_path):
    target = tmp_path / "oom_score_adj"
    assert parser_guard.prefer_oom_victim(str(target)) is True
    assert target.read_text() == str(parser_guard.OOM_SCORE_ADJ) and parser_guard.OOM_SCORE_ADJ >= 800
    assert parser_guard.prefer_oom_victim(str(tmp_path)) is False             # unwritable: said by the return value, never raised


def test_without_a_path_it_is_linux_only(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    assert parser_guard.prefer_oom_victim() is False


def test_the_limits_step_sets_the_score_before_anything_else(monkeypatch):
    seen = []
    monkeypatch.setattr(parser_guard, "prefer_oom_victim", lambda *a, **k: seen.append("oom") or True)
    monkeypatch.setitem(sys.modules, "resource", None)   # `import resource` fails: _apply_limits stops right after the score
    pdf_isolation._apply_limits(1536, 100)
    assert seen == ["oom"]


def test_the_group_resident_set_is_the_child_its_descendants_and_its_orphans_only(tmp_path):
    root = fake_proc(tmp_path, {
        1: (0, 1, 9999),            # init: not ours
        100: (1, 100, 1000),        # the child (its own group leader)
        101: (100, 100, 500),       # Tesseract
        102: (101, 100, 25),        # a grandchild
        103: (1, 100, 10),          # reparented orphan still in the group
        200: (1, 200, 7777),        # unrelated
    })
    assert parser_guard.group_rss_kb(100, root) == (1000 + 500 + 25 + 10) * PAGE_KB
    assert parser_guard.group_rss_kb(555, root) is None                      # no such process
    assert parser_guard.group_rss_kb(100, str(tmp_path / "absent")) is None  # not Linux


def test_over_budget_names_the_use_only_when_it_is_over(tmp_path):
    root = fake_proc(tmp_path, {100: (1, 100, 100 * 1024 // PAGE_KB), 101: (100, 100, 60 * 1024 // PAGE_KB)})   # 160 MB
    assert parser_guard.over_budget(100, 100, root) == 160
    assert parser_guard.over_budget(100, 200, root) is None
    assert parser_guard.over_budget(100, 0, root) is None
    assert parser_guard.over_budget(999, 100, root) is None


def test_a_child_over_its_resident_budget_is_killed_and_is_the_memory_refusal(monkeypatch):
    monkeypatch.setattr(parser_guard, "over_budget", lambda pid, budget, root=parser_guard.PROC_ROOT: 999)
    started = time.monotonic()
    outcome = pdf_isolation.run_worker([sys.executable, "-c", "import time; time.sleep(60)"], timeout_s=30, label="t")
    assert outcome.status == "memory" and time.monotonic() - started < 10


def test_a_child_under_budget_is_left_alone(monkeypatch):
    monkeypatch.setattr(parser_guard, "over_budget", lambda pid, budget, root=parser_guard.PROC_ROOT: None)
    outcome = pdf_isolation.run_worker([sys.executable, "-c", "print('{}')"], timeout_s=30, label="t")
    assert outcome.status == "ok"


@pytest.mark.skipif(not LINUX, reason="/proc and oom_score_adj are Linux")
def test_a_started_child_and_its_own_child_really_have_the_oom_score():
    code = (
        "import subprocess, sys; sys.path.insert(0, '.')\n"
        "from app.services import pdf_isolation\n"
        "pdf_isolation._apply_limits(1536, 100)\n"
        "print(open('/proc/self/oom_score_adj').read().strip())\n"
        "print(subprocess.run(['cat', '/proc/self/oom_score_adj'], capture_output=True, text=True).stdout.strip())\n"
    )
    outcome = pdf_isolation.run_worker([sys.executable, "-c", code], timeout_s=60, label="oom")
    assert outcome.status == "ok", outcome
    assert outcome.out.decode().split() == [str(parser_guard.OOM_SCORE_ADJ)] * 2     # the child, and what it started (Tesseract's case)


@pytest.mark.skipif(not LINUX, reason="/proc is Linux")
def test_the_watchdog_really_kills_a_child_that_grows_past_the_budget(monkeypatch):
    monkeypatch.setattr(get_settings(), "parse_child_rss_mb", 80)
    code = "import time\nb = b'x' * (300 * 1024 * 1024)\ntime.sleep(60)\n"
    started = time.monotonic()
    outcome = pdf_isolation.run_worker([sys.executable, "-c", code], timeout_s=50, label="grow")
    assert outcome.status == "memory" and time.monotonic() - started < 20


# ── A spreadsheet child that runs out of memory says so, specifically ──────────────────────

@pytest.mark.parametrize("how", ["killed", "memoryerror"])
def test_a_spreadsheet_that_exceeds_memory_is_the_split_the_file_refusal(monkeypatch, how):
    if how == "killed":
        monkeypatch.setattr(pdf_isolation, "run_worker", lambda *a, **k: pdf_isolation.ChildOutcome("memory"))
        with pytest.raises(sheet_isolation.SheetOkunamadi) as caught:
            sheet_isolation.read_sheets(b"a;b\n1;2\n", "csv")
        error = caught.value
    else:
        def boom(*a, **k):
            raise MemoryError
        monkeypatch.setattr(sheet_child, "read_csv", boom)
        refusal = sheet_child.parse(b"a;b\n1;2\n", "csv", sheet_isolation.limits_from_settings())["refusal"]
        error = sheet_isolation.SheetOkunamadi(refusal["code"], **refusal["params"])
    assert error.code == "sheet_memory"
    assert "bellek sınırını aştı" in error.tr and "bölüp yükleyin" in error.tr
    assert "memory limit" in error.en and "split the file" in error.en
