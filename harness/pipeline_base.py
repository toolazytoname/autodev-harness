"""Tiny shared module for pipeline-level types and helpers.

T24 — extracted so ``harness.ui_phase`` can import ``PipelineError``
and ``_is_interactive`` without creating a circular import with
``harness.pipeline``. The previous arrangement (ui_phase → pipeline
→ ui_phase) broke the moment pipeline re-exported symbols from
ui_phase at module level.
"""

from __future__ import annotations

import sys


class PipelineError(Exception):
    """Irrecoverable pipeline failure."""


def _is_interactive() -> bool:
    """True when a human can answer prompts on stdin."""
    return sys.stdin.isatty()
