"""Atomic file I/O utilities for state persistence (T17).

Why this module exists
----------------------
The pipeline writes state files (workflow-state.json, task queue, score cards)
from arbitrary points in the run. A naive ``path.write_text(...)`` is *not*
atomic — if the process dies mid-write, the file is truncated and the reader
sees a corrupt state file. Worse, the previous reader silently returned
``None`` on parse errors, which made the pipeline believe "no state yet" and
restart from scratch — destroying all progress.

This module provides:

- :func:`atomic_write_text` / :func:`atomic_write_json` — write to a temp file
  in the same directory, then ``os.replace()`` it into place. Same-directory
  rename is atomic on POSIX and on Windows (when the destination exists).
  Temp file is cleaned up on failure.

- :func:`read_json_or_raise` / :func:`read_text_or_raise` — surface corruption
  via :class:`AtomicIOError` instead of returning ``None``. Callers decide
  whether to fall back to a default or treat it as a hard failure.

All functions are pure I/O — no pydantic, no project-specific models. That
keeps this module easy to unit-test and reusable beyond state files.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any


class AtomicIOError(Exception):
    """Raised when a file is present but its content is unreadable / corrupt.

    Carries the offending path and (when applicable) the underlying cause so
    log lines are actionable. Distinct from :class:`FileNotFoundError`, which
    means "we have nothing yet, start fresh" — that case is still valid and
    handled by callers.
    """

    def __init__(
        self,
        message: str,
        *,
        path: Path,
        cause: BaseException | None = None,
    ) -> None:
        super().__init__(f"{message} [path={path}]")
        self.path = path
        self.cause = cause
        if cause is not None:
            self.__cause__ = cause


# ---------------------------------------------------------------------------
# Write helpers
# ---------------------------------------------------------------------------


def _write_to_temp(path: Path, content: str) -> None:
    """Write content to a temp file in the same directory as ``path``.

    Indirection so tests can monkey-patch the actual write step to simulate
    failures. The temp file's path is returned via a sentinel: callers use
    :func:`_swap_into_place` to do the atomic rename.
    """
    # Same-directory temp file is required for atomic rename.
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=str(path.parent),
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(content)
            fh.flush()
            # Best-effort durability: ask the OS to flush to disk before
            # we rename into place. fsync is advisory — failures here are
            # non-fatal (we still get atomicity from rename).
            try:
                os.fsync(fh.fileno())
            except OSError:
                pass
        os.replace(tmp_name, path)
    except BaseException:
        # On any failure, clean up the temp file before re-raising so
        # we never leave garbage next to the target.
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass
        raise


def atomic_write_text(path: Path, content: str) -> Path:
    """Write ``content`` to ``path`` atomically.

    Strategy: write to a same-directory temp file, fsync, then ``os.replace``
    into place. If anything fails, the temp file is cleaned up and the
    original (if any) is untouched.

    Parent directories are created as needed.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    _write_to_temp(path, content)
    return path


def atomic_write_json(path: Path, obj: Any) -> Path:
    """Atomically write ``obj`` as pretty-printed UTF-8 JSON.

    Convenience wrapper around :func:`atomic_write_text` that handles JSON
    encoding. Trailing newline matches the format the existing
    ``path.write_text(json.dumps(...)+"\\n")`` callers produce, so file
    diffs are minimised.
    """
    content = json.dumps(obj, indent=2, ensure_ascii=False) + "\n"
    return atomic_write_text(path, content)


# ---------------------------------------------------------------------------
# Read helpers
# ---------------------------------------------------------------------------


def read_text_or_raise(path: Path) -> str:
    """Return the contents of ``path``. Raises ``FileNotFoundError`` if absent.

    Distinguished from ``Path.read_text`` only by intent — the explicit name
    makes call sites self-documenting ("I expect this file to exist or it's
    a hard failure").
    """
    return path.read_text(encoding="utf-8")


def read_json_or_raise(path: Path) -> Any:
    """Read and parse a JSON file. Raises ``AtomicIOError`` on corrupt content.

    Unlike the previous behaviour (which returned ``None`` on parse errors
    and let callers silently restart the pipeline), this surfaces the
    problem so the operator can act on it: restore from backup, regenerate,
    or investigate why the file was truncated.

    ``FileNotFoundError`` is still propagated as-is — "no file" is a normal
    startup condition, not corruption.
    """
    text = read_text_or_raise(path)
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise AtomicIOError(
            f"Corrupt JSON at {path}: {exc.msg} (line {exc.lineno}, col {exc.colno})",
            path=path,
            cause=exc,
        ) from exc