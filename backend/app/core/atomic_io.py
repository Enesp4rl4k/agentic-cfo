"""Atomic file writes — write to a temp file in the same directory, then
`os.replace` (DDIA Ch.5/Ch.8 — readers must never see a partial write).

Every exporter, PDF builder and upload used to open the *final* path and
write into it. A crash (or a full disk, or a Ctrl-C) mid-write left a
half-written file that nothing could distinguish from a complete one: the
report store served truncated JSON, the parser ingested a cut CSV.

`os.replace` is atomic on POSIX and on Windows (MoveFileEx). Readers see
either the previous complete file or the new complete file — never an
intermediate. The temp lives in the destination directory, so the rename
stays within one filesystem (a cross-device replace is not atomic).
"""
from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from typing import IO, Any


def _open_temp(target: str) -> tuple[int, str]:
    """Create a temp file beside `target`; returns (fd, temp path)."""
    directory = os.path.dirname(os.path.abspath(target))
    fd, tmp = tempfile.mkstemp(
        dir=directory,
        prefix=f".{os.path.basename(target)}.",
        suffix=".part",
    )
    return fd, tmp


def _discard(tmp: str) -> None:
    """Best-effort temp cleanup — never mask the original error."""
    try:
        os.unlink(tmp)
    except OSError:
        pass


def atomic_write_bytes(path: str | os.PathLike[str], data: bytes) -> None:
    """Write `data` to `path` all-or-nothing."""
    target = os.fspath(path)
    fd, tmp = _open_temp(target)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        os.replace(tmp, target)
    except BaseException:
        _discard(tmp)
        raise


def atomic_write_text(
    path: str | os.PathLike[str], text: str, encoding: str = "utf-8"
) -> None:
    """Write `text` to `path` all-or-nothing."""
    atomic_write_bytes(path, text.encode(encoding))


def atomic_write_json(
    path: str | os.PathLike[str], payload: Any, *, indent: int | None = 2
) -> None:
    """Serialize `payload` and write it all-or-nothing.

    Matches the project's JSON house style (Turkish strings must stay
    readable): ensure_ascii=False.
    """
    atomic_write_text(path, json.dumps(payload, ensure_ascii=False, indent=indent))


@contextmanager
def atomic_binary_file(path: str | os.PathLike[str]) -> Iterator[IO[bytes]]:
    """Streaming variant: yields a temp file handle and publishes it with
    `os.replace` only on clean exit.

    Any exception — including the process dying mid-`yield` — discards the
    temp; the destination keeps whatever it held before (or stays absent).
    """
    target = os.fspath(path)
    fd, tmp = _open_temp(target)
    try:
        with os.fdopen(fd, "wb") as fh:
            yield fh
        os.replace(tmp, target)
    except BaseException:
        _discard(tmp)
        raise
