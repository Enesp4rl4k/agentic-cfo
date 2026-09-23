"""Atomic file writes: a reader either sees the old file or the new one,
never a half-written one (DDIA Ch.5 — no partial writes).

Every exporter, PDF builder and upload used to stream into the *final*
path; a crash mid-write published a truncated file that no reader could
distinguish from a complete one.
"""
from __future__ import annotations

import json
import os

import pytest

from app.core.atomic_io import atomic_binary_file, atomic_write_bytes, atomic_write_json


def _leftovers(directory) -> list[str]:
    return [p.name for p in os.scandir(directory) if not p.is_dir()]


def test_bytes_land_intact_and_no_temp_file_survives(tmp_path):
    target = tmp_path / "report.pdf"
    atomic_write_bytes(target, b"%PDF-1.4 payload")
    assert target.read_bytes() == b"%PDF-1.4 payload"
    assert _leftovers(tmp_path) == ["report.pdf"]  # the .part is gone


def test_writes_into_a_directory_that_does_not_exist_yet_raises_clean(tmp_path):
    # The helpers do not create directories (the callers already makedirs);
    # the contract is: on failure, nothing — not even a temp — is left.
    with pytest.raises(OSError):
        atomic_write_bytes(tmp_path / "missing" / "f.bin", b"x")
    assert _leftovers(tmp_path) == []


def test_failed_streaming_write_keeps_the_old_file(tmp_path):
    target = tmp_path / "dashboard.json"
    target.write_bytes(b'{"old": true}')

    with pytest.raises(RuntimeError, match="boom"):
        with atomic_binary_file(target) as fh:
            fh.write(b'{"new": tru')  # crash mid-write
            raise RuntimeError("boom")

    assert target.read_bytes() == b'{"old": true}'  # readers saw the old file
    assert _leftovers(tmp_path) == ["dashboard.json"]  # temp discarded


def test_failed_first_write_creates_nothing(tmp_path):
    target = tmp_path / "never.json"
    with pytest.raises(ValueError):
        with atomic_binary_file(target) as fh:
            fh.write(b"partial")
            raise ValueError("abort")
    assert not target.exists()
    assert _leftovers(tmp_path) == []


def test_clean_streaming_write_publishes(tmp_path):
    target = tmp_path / "deck.pdf"
    with atomic_binary_file(target) as fh:
        fh.write(b"page-1")
        fh.write(b"page-2")
    assert target.read_bytes() == b"page-1page-2"
    assert _leftovers(tmp_path) == ["deck.pdf"]


def test_json_keeps_turkish_readable_and_round_trips(tmp_path):
    target = tmp_path / "ozet.json"
    payload = {"not": "çalışan", "ofis": "Şişli", "kayıp": 42}
    atomic_write_json(target, payload)

    raw = target.read_bytes()
    assert "çalışan".encode() in raw  # ensure_ascii=False — no \u escapes
    assert json.loads(raw) == payload


def test_overwrite_is_replace_not_extend(tmp_path):
    # Same-length overwrite is trivial; the real risk is a SHORTER new
    # content leaving the old tail behind (truncation bugs readers see as
    # valid data). os.replace guarantees the length is exactly the new one.
    target = tmp_path / "state.json"
    atomic_write_json(target, {"a": "x" * 100})
    atomic_write_json(target, {"b": 1})
    assert json.loads(target.read_text(encoding="utf-8")) == {"b": 1}
