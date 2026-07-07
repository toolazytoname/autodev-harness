"""Tests for harness.atomic_io — atomic file write + corruption detection.

Per T17 [CRITICAL]: state files must be written atomically (temp file + os.replace)
and readers must surface corruption rather than silently returning None.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from harness.atomic_io import (
    AtomicIOError,
    atomic_write_json,
    atomic_write_text,
    read_json_or_raise,
    read_text_or_raise,
)


# ---------------------------------------------------------------------------
# atomic_write_text — must be atomic: no partially-written file on crash
# ---------------------------------------------------------------------------


def test_atomic_write_text_creates_file(tmp_path: Path) -> None:
    target = tmp_path / "out.txt"
    atomic_write_text(target, "hello")
    assert target.read_text() == "hello"


def test_atomic_write_text_overwrites_existing(tmp_path: Path) -> None:
    target = tmp_path / "out.txt"
    target.write_text("old")
    atomic_write_text(target, "new")
    assert target.read_text() == "new"


def test_atomic_write_text_uses_temp_file_in_same_dir(tmp_path: Path) -> None:
    """Temp file must live in same directory so os.replace is atomic across FS."""
    target = tmp_path / "out.txt"
    # Spy: monkeypatch os.replace to record the source path's parent.
    import os as _os

    calls: list[tuple[str, str]] = []
    original_replace = _os.replace

    def spy_replace(src: str, dst: str) -> None:
        calls.append((src, dst))
        original_replace(src, dst)

    _os.replace = spy_replace  # type: ignore[attr-defined]
    try:
        atomic_write_text(target, "content")
    finally:
        _os.replace = original_replace  # type: ignore[attr-defined]

    assert len(calls) == 1
    src_parent = Path(calls[0][0]).parent
    dst_parent = Path(calls[0][1]).parent
    assert src_parent == dst_parent == tmp_path


def test_atomic_write_text_no_temp_files_left_on_success(tmp_path: Path) -> None:
    """After a successful write, no stray temp files should remain."""
    target = tmp_path / "out.txt"
    atomic_write_text(target, "hello")
    remaining = [p for p in tmp_path.iterdir() if p.name != "out.txt"]
    assert remaining == [], f"Stray temp files left behind: {remaining}"


def test_atomic_write_text_cleans_up_temp_on_failure(tmp_path: Path) -> None:
    """If writing the temp file fails, no garbage temp file is left behind."""
    target = tmp_path / "out.txt"

    def boom(_path: str, _content: str) -> None:
        raise OSError("disk full")

    import harness.atomic_io as aio

    original = aio._write_to_temp
    aio._write_to_temp = boom  # type: ignore[assignment]
    try:
        with pytest.raises(OSError, match="disk full"):
            atomic_write_text(target, "hello")
    finally:
        aio._write_to_temp = original  # type: ignore[assignment]

    # No target written, no stray temps
    assert not target.exists()
    remaining = list(tmp_path.iterdir())
    assert remaining == [], f"Stray files after failed write: {remaining}"


def test_atomic_write_text_creates_parent_dirs(tmp_path: Path) -> None:
    target = tmp_path / "deep" / "nested" / "out.txt"
    atomic_write_text(target, "hi")
    assert target.read_text() == "hi"


# ---------------------------------------------------------------------------
# atomic_write_json — JSON variant with identical atomicity guarantees
# ---------------------------------------------------------------------------


def test_atomic_write_json_round_trips(tmp_path: Path) -> None:
    target = tmp_path / "data.json"
    payload = {"a": 1, "b": [1, 2, 3], "c": {"nested": True}}
    atomic_write_json(target, payload)
    assert json.loads(target.read_text()) == payload


def test_atomic_write_json_with_unicode(tmp_path: Path) -> None:
    target = tmp_path / "data.json"
    atomic_write_json(target, {"greeting": "你好", "emoji": "🚀"})
    assert json.loads(target.read_text()) == {"greeting": "你好", "emoji": "🚀"}


# ---------------------------------------------------------------------------
# read_json_or_raise — corrupted files must surface, not silently return None
# ---------------------------------------------------------------------------


def test_read_json_or_raise_returns_parsed_value(tmp_path: Path) -> None:
    target = tmp_path / "ok.json"
    target.write_text(json.dumps({"a": 1}))
    assert read_json_or_raise(target) == {"a": 1}


def test_read_json_or_raise_on_truncated_file(tmp_path: Path) -> None:
    """Simulate 'crash mid-write': target contains invalid JSON."""
    target = tmp_path / "broken.json"
    target.write_text('{"a": 1, "b":')  # truncated
    with pytest.raises(AtomicIOError) as exc:
        read_json_or_raise(target)
    assert "corrupt" in str(exc.value).lower()
    assert str(target) in str(exc.value)


def test_read_json_or_raise_on_garbage(tmp_path: Path) -> None:
    target = tmp_path / "garbage.json"
    target.write_text("not json at all")
    with pytest.raises(AtomicIOError):
        read_json_or_raise(target)


def test_read_text_or_raise_returns_content(tmp_path: Path) -> None:
    target = tmp_path / "ok.txt"
    target.write_text("plain text content")
    assert read_text_or_raise(target) == "plain text content"


def test_read_text_or_raise_on_missing_file(tmp_path: Path) -> None:
    target = tmp_path / "absent.txt"
    with pytest.raises(FileNotFoundError):
        read_text_or_raise(target)


# ---------------------------------------------------------------------------
# AtomicIOError — must carry enough info to debug
# ---------------------------------------------------------------------------


def test_atomic_io_error_carries_path() -> None:
    err = AtomicIOError("oops", path=Path("/tmp/foo"))
    assert err.path == Path("/tmp/foo")
    assert "/tmp/foo" in str(err)


def test_atomic_io_error_carries_cause() -> None:
    cause = json.JSONDecodeError("bad", "x", 0)
    err = AtomicIOError("corrupt", path=Path("/tmp/foo"), cause=cause)
    assert err.__cause__ is cause