"""RED tests for T22 — structured logging for the Python pipeline.

Per TASKS.md T22: ``harness/`` has zero ``import logging`` and only 18
``print()`` calls; the real running pipeline leaves no persistent trail.
M4's unattended quota-resume specifically needs it: when a run falls
over at 3am, the operator must be able to open ``logs/harness.log``
and locate the failing ``stage``/``task_id``/``iter``.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from harness.logging_setup import configure_logging, get_logger


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def log_dir(tmp_path: Path) -> Path:
    return tmp_path / "logs"


# ---------------------------------------------------------------------------
# Test: configure_logging creates the log file
# ---------------------------------------------------------------------------


class TestConfigureLogging:
    def test_creates_log_file(self, log_dir):
        configure_logging(log_dir)
        log = get_logger("harness.test")
        log.info("hello world")
        log_path = log_dir / "harness.log"
        assert log_path.exists()

    def test_log_records_written_to_file(self, log_dir):
        configure_logging(log_dir)
        log = get_logger("harness.test.records")
        log.info("event one")
        log.warning("event two")
        log_path = log_dir / "harness.log"
        content = log_path.read_text()
        assert "event one" in content
        assert "event two" in content

    def test_idempotent_when_called_twice(self, log_dir):
        """Calling configure_logging twice must NOT attach duplicate
        handlers (otherwise log lines get duplicated on every import)."""
        configure_logging(log_dir)
        configure_logging(log_dir)
        log = get_logger("harness.test.idempotent")
        log.info("only-once")
        log_path = log_dir / "harness.log"
        occurrences = log_path.read_text().count("only-once")
        assert occurrences == 1


# ---------------------------------------------------------------------------
# Test: structured fields via extra={...}
# ---------------------------------------------------------------------------


class TestStructuredFields:
    def test_extra_fields_appear_in_log_output(self, log_dir):
        configure_logging(log_dir)
        log = get_logger("harness.test.struct")
        log.info(
            "task_started",
            extra={"stage": "develop", "task_id": "task-42", "iter": 1},
        )
        log_path = log_dir / "harness.log"
        content = log_path.read_text()
        assert "stage=develop" in content
        assert "task_id=task-42" in content
        assert "iter=1" in content

    def test_log_level_filtering(self, log_dir):
        """DEBUG records are filtered at INFO level by default — T22's
        accept criterion is that operators can find the failing stage
        at INFO; DEBUG noise stays out."""
        configure_logging(log_dir)
        log = get_logger("harness.test.level")
        log.debug("invisible-at-info")
        log.info("visible")
        log_path = log_dir / "harness.log"
        content = log_path.read_text()
        assert "visible" in content
        assert "invisible-at-info" not in content


# ---------------------------------------------------------------------------
# Test: get_logger is safe to call before configure_logging
# ---------------------------------------------------------------------------


def test_get_logger_returns_logger_without_configure():
    log = get_logger("harness.no.configure")
    assert isinstance(log, logging.Logger)
    # Should not raise even though configure_logging was never called.
    log.info("nothing-to-do")