"""Inner-loop exception types — extracted so worktree.py can raise
them without creating an import cycle with inner_loop.py (T24).

T24 split inner_loop.py into worktree / generator / reviewer_runner /
inner_loop orchestrator. The orchestrator still owns the iteration
state machine, but the worktree helpers need to raise on git errors.
A small shared exception module breaks the cycle without forcing
callers to catch two exception types.
"""

from __future__ import annotations


class InnerLoopError(Exception):
    """Base exception for inner loop failures."""


class EscalationError(InnerLoopError):
    """Raised when the loop has exhausted MAX_ITER without a gate pass."""

    def __init__(self, task_id: str, iter_count: int, cards: list) -> None:
        self.task_id = task_id
        self.iter_count = iter_count
        self.cards = cards
        super().__init__(
            f"Task {task_id} exhausted {iter_count} iterations without a gate pass."
        )
