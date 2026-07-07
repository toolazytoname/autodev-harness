"""Structured logging setup for the Python pipeline.

Per TASKS.md T22 — the harness previously relied on ad-hoc ``print()``
and left no persistent log of unattended runs. M4's quota-aware
auto-resume needs ``logs/harness.log`` to outlive a crash so the
operator can find the failing ``stage``/``task_id``/``iter``.

Public API::

    from harness.logging_setup import configure_logging, get_logger

    configure_logging(Path("logs"))     # idempotent
    log = get_logger(__name__)
    log.info("task_started", extra={"stage": "develop",
                                    "task_id": "task-42",
                                    "iter": 1})

The formatter renders ``extra=...`` fields as ``key=value`` so the
trailing line carries the structured context needed to triage a
mid-run failure without grepping source code.
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Optional


# Marker we attach to our FileHandler so ``configure_logging`` can
# detect (and avoid stacking) duplicate handlers on repeated calls.
_HANDLER_MARKER = "harness-file"


class _StructuredFormatter(logging.Formatter):
    """Append ``extra=...`` fields as ``k=v`` pairs at the end of the record.

    Standard ``LogRecord`` attributes are rendered by the base format
    string; everything else passed via ``extra=`` lands here so the
    log line stays grep-friendly without forcing callers to pre-format
    structured fields into the message.
    """

    _RESERVED = {
        "name", "msg", "args", "levelname", "levelno", "pathname",
        "filename", "module", "exc_info", "exc_text", "stack_info",
        "lineno", "funcName", "created", "msecs", "relativeCreated",
        "thread", "threadName", "processName", "process", "message",
        "asctime", "taskName",
    }

    def format(self, record: logging.LogRecord) -> str:
        base = super().format(record)
        extras = [
            f"{k}={record.__dict__[k]}"
            for k in sorted(record.__dict__)
            if k not in self._RESERVED and not k.startswith("_")
        ]
        if extras:
            return base + " " + " ".join(extras)
        return base


_lock = threading.Lock()
_configured_dir: Optional[Path] = None
_log_file: Optional[Path] = None


def configure_logging(log_dir: Path, level: int = logging.INFO) -> Path:
    """Attach a file handler to the harness root logger.

    Idempotent for the same ``log_dir``: repeated calls do not stack
    duplicate handlers (which would multiply every log line by the
    number of imports). When called with a different ``log_dir`` —
    e.g. between unit tests using fresh tmp paths — the previous
    handler is detached and a fresh one attached.

    Parameters
    ----------
    log_dir
        Directory that will receive ``harness.log``. Created if missing.
    level
        Minimum log level (default ``INFO``; ``DEBUG`` shows extra
        adapter / retry noise).

    Returns
    -------
    Path
        The log file path (``log_dir / "harness.log"``).
    """
    global _configured_dir, _log_file

    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "harness.log"

    with _lock:
        root = logging.getLogger("harness")
        root.setLevel(level)

        # Same directory — leave the existing handler in place.
        if _configured_dir == log_dir:
            _log_file = log_path
            return log_path

        # Different directory (or first call) — detach any previous
        # harness handlers so we don't double-log, then attach fresh.
        for handler in list(root.handlers):
            if getattr(handler, _HANDLER_MARKER, False):
                root.removeHandler(handler)
                try:
                    handler.close()
                except Exception:
                    pass

        handler = logging.FileHandler(log_path, encoding="utf-8")
        handler.setLevel(level)
        handler.setFormatter(
            _StructuredFormatter(
                fmt="%(asctime)s %(levelname)s %(name)s %(message)s",
                datefmt="%Y-%m-%dT%H:%M:%S",
            )
        )
        setattr(handler, _HANDLER_MARKER, True)
        root.addHandler(handler)

        # Don't double-log through the root logger if the user also has
        # basicConfig / propagation set up — but we *do* want our own
        # loggers (harness.*) to reach us.
        root.propagate = False

        _configured_dir = log_dir
        _log_file = log_path

    return log_path


def get_logger(name: str) -> logging.Logger:
    """Return a logger under the ``harness`` namespace.

    Safe to call before :func:`configure_logging` — the returned logger
    will simply emit to the default (stderr) handler until logging is
    configured, which is fine for unit tests and one-off scripts.
    """
    if not name.startswith("harness"):
        name = f"harness.{name}"
    return logging.getLogger(name)


def log_file_path() -> Optional[Path]:
    """Return the configured log file path, or ``None`` if not configured."""
    return _log_file