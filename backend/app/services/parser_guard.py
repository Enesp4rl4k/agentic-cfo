"""Two guards around a parser child (PDF, spreadsheet), both Linux-only and silent elsewhere.

* `prefer_oom_victim` (child side, before any untrusted byte is parsed): raise the child's own
  `/proc/self/oom_score_adj`, so if the container ever hits its memory wall the kernel's OOM killer picks the
  parser (and its Tesseract, which inherits the value) and not an API worker. Raising one's own score needs no
  privilege.
* `over_budget` (parent side): the resident memory of the child and every descendant, read from `/proc`, against
  `PARSE_CHILD_RSS_MB`. `RLIMIT_AS` counts address space and is only a backstop; this is the limit on what the
  child really uses. The supervisor polls it a few times a second and kills the child's process group.

Pure functions over `/proc`-shaped paths, so tests point them at a fake directory.
"""
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

logger = logging.getLogger(__name__)
_warned = False

OOM_SCORE_ADJ = 900            # 1000 is "kill first, always"; 900 is far above an API worker's 0 without being a special case
DEFAULT_OOM_PATH = "/proc/self/oom_score_adj"
PROC_ROOT = "/proc"


def prefer_oom_victim(path: str | None = None, score: int = OOM_SCORE_ADJ) -> bool:
    """Write `score` to the OOM score file. True when written. Without `path` only on Linux; never raises."""
    if path is None:
        if not sys.platform.startswith("linux"):
            return False
        path = DEFAULT_OOM_PATH
    try:
        with open(path, "w", encoding="ascii") as handle:
            handle.write(str(score))
    except OSError as exc:
        global _warned
        if not _warned:   # once: every child would say the same
            _warned = True
            logger.warning("Could not write oom_score_adj (%s): a parser child is not the preferred OOM victim in this container", exc)
        return False
    return True


def group_rss_kb(root_pid: int, proc_root: str = PROC_ROOT) -> int | None:
    """Resident set in kB of `root_pid` and everything it started (its process group and its descendants).
    None where `/proc` cannot be read (not Linux, or the child is already gone)."""
    root = Path(proc_root)
    try:
        entries = [p for p in root.iterdir() if p.name.isdigit()]
    except OSError:
        return None
    page_kb = (os.sysconf("SC_PAGE_SIZE") // 1024) if hasattr(os, "sysconf") else 4
    table: dict[int, tuple[int, int, int]] = {}      # pid -> (ppid, pgrp, resident pages)
    for entry in entries:
        try:
            raw = (entry / "stat").read_text(encoding="ascii", errors="replace")
            after = raw[raw.rindex(")") + 2:].split()   # the command name may contain spaces and ")"
            table[int(entry.name)] = (int(after[1]), int(after[2]), int(after[21]))
        except (OSError, ValueError, IndexError):
            continue                                    # a process that exited while we looked
    members = {pid for pid, (_ppid, pgrp, _rss) in table.items() if pid == root_pid or pgrp == root_pid}
    if root_pid not in table:
        return None
    grew = True
    while grew:
        grew = False
        for pid, (ppid, _pgrp, _rss) in table.items():
            if pid not in members and ppid in members:
                members.add(pid)
                grew = True
    return sum(table[pid][2] for pid in members) * page_kb


def over_budget(root_pid: int, budget_mb: int, proc_root: str = PROC_ROOT) -> int | None:
    """The resident MB used when it is over `budget_mb`, else None (also None when it cannot be measured)."""
    if budget_mb <= 0:
        return None
    used_kb = group_rss_kb(root_pid, proc_root)
    if used_kb is not None and used_kb > budget_mb * 1024:
        return used_kb // 1024
    return None
