"""RED tests for T18 — resume precision fixes.

Per TASKS.md T18: three places make ``--continue`` unreliable.

1. ``TaskStatus.IN_PROGRESS`` is never persisted. After a crash mid-task,
   the task is still PENDING on disk but the ``task/{id}`` worktree (and
   branch) exist. ``--continue`` therefore picks up the task as fresh
   work, calls ``create_worktree`` which fails because the branch
   already exists, and the task gets mis-blocked.
2. ``write_task_queue`` drops the ``platform`` field on serialize. Mobile
   and miniprogram tasks therefore lose their dedicated reviewer when
   the queue is re-read after a resume.
3. ``merge_worktree`` runs before ``complete_task`` commits to disk. A
   crash between them leaves code merged into the base branch but the
   task still PENDING on disk, so the next run duplicates the work.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from harness.artifacts import (
    Kind,
    Task,
    TaskQueue,
    TaskStatus,
    complete_task,
    mark_task_in_progress,
    read_task_queue,
    write_task_queue,
)
from harness.inner_loop import create_worktree, merge_worktree


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _init_git_repo(path: Path) -> None:
    """Initialise a real git repo on a fresh tmp dir."""
    subprocess.run(["git", "init", "-b", "main"], cwd=path, capture_output=True, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"], cwd=path, capture_output=True, check=True
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"], cwd=path, capture_output=True, check=True
    )
    (path / "README.md").write_text("# Project\n")
    subprocess.run(["git", "add", "."], cwd=path, capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "-m", "init"], cwd=path, capture_output=True, check=True
    )


def _make_queue(task_id: str = "1", platform: str = "web") -> TaskQueue:
    return TaskQueue(
        tasks=[
            Task(
                id=task_id,
                title="task one",
                description="desc",
                kind=Kind.LOGIC.value,
                platform=platform,
                acceptance=["run tests"],
            )
        ]
    )


# ---------------------------------------------------------------------------
# Test: mark_task_in_progress writes the status to disk
# ---------------------------------------------------------------------------


class TestMarkTaskInProgress:
    def test_marks_task_as_in_progress_on_disk(self, tmp_path):
        write_task_queue(tmp_path, _make_queue())
        result = mark_task_in_progress(tmp_path, "1")
        assert result is not None, "mark_task_in_progress should return the updated task"
        queue = read_task_queue(tmp_path)
        task = next(t for t in queue.tasks if t.id == "1")
        assert task.status == TaskStatus.IN_PROGRESS

    def test_returns_none_for_unknown_task(self, tmp_path):
        write_task_queue(tmp_path, _make_queue())
        result = mark_task_in_progress(tmp_path, "does-not-exist")
        assert result is None
        # Original task must remain PENDING (not corrupted).
        queue = read_task_queue(tmp_path)
        task = next(t for t in queue.tasks if t.id == "1")
        assert task.status == TaskStatus.PENDING

    def test_other_tasks_unchanged(self, tmp_path):
        queue = TaskQueue(
            tasks=[
                Task(id="1", title="first", kind="logic", platform="web", acceptance=["x"]),
                Task(id="2", title="second", kind="logic", platform="web", acceptance=["x"]),
            ]
        )
        write_task_queue(tmp_path, queue)
        mark_task_in_progress(tmp_path, "1")
        queue = read_task_queue(tmp_path)
        by_id = {t.id: t for t in queue.tasks}
        assert by_id["1"].status == TaskStatus.IN_PROGRESS
        assert by_id["2"].status == TaskStatus.PENDING


# ---------------------------------------------------------------------------
# Test: write_task_queue preserves the platform field
# ---------------------------------------------------------------------------


class TestWriteTaskQueuePlatform:
    def test_platform_persisted_on_round_trip_web(self, tmp_path):
        write_task_queue(tmp_path, _make_queue(platform="web"))
        queue = read_task_queue(tmp_path)
        assert queue.tasks[0].platform == "web"

    def test_platform_persisted_on_round_trip_mobile(self, tmp_path):
        write_task_queue(tmp_path, _make_queue(platform="mobile"))
        queue = read_task_queue(tmp_path)
        assert queue.tasks[0].platform == "mobile"

    def test_platform_persisted_on_round_trip_miniprogram(self, tmp_path):
        write_task_queue(tmp_path, _make_queue(platform="miniprogram"))
        queue = read_task_queue(tmp_path)
        assert queue.tasks[0].platform == "miniprogram"


# ---------------------------------------------------------------------------
# Test: create_worktree is idempotent on existing branch/worktree
# ---------------------------------------------------------------------------


class TestCreateWorktreeIdempotent:
    def test_second_call_with_existing_branch_does_not_raise(self, tmp_path):
        _init_git_repo(tmp_path)
        first = create_worktree(tmp_path, "1")
        assert first.exists()

        # Second invocation must succeed (reuse the existing branch/worktree).
        second = create_worktree(tmp_path, "1")
        assert second.exists()
        # Path should be the same — it's the same worktree.
        assert first.resolve() == second.resolve()


# ---------------------------------------------------------------------------
# Test: merge + complete is a single recoverable transaction
# ---------------------------------------------------------------------------


class TestMergeAndCompleteTransaction:
    def test_complete_task_persists_status_before_merge(self, tmp_path):
        """After gate passes, the COMPLETED status must already be on disk
        by the time we attempt the merge — so a crash mid-merge does not
        leave the task in PENDING with code already merged.
        """
        _init_git_repo(tmp_path)
        write_task_queue(tmp_path, _make_queue())

        # Simulate the gate-pass branch of run_inner_loop: write COMPLETED
        # first, then merge. The on-disk state must reflect COMPLETED
        # before we touch git.
        queue = complete_task(read_task_queue(tmp_path), "1")
        write_task_queue(tmp_path, queue)

        on_disk = read_task_queue(tmp_path)
        assert on_disk.tasks[0].status == TaskStatus.COMPLETED

    def test_merge_into_main_branch_then_status_already_complete(self, tmp_path):
        """Full happy path: complete_task first (durable), then merge.
        After both, status remains COMPLETED on disk."""
        _init_git_repo(tmp_path)
        write_task_queue(tmp_path, _make_queue())

        # Create a worktree, do some work, commit
        worktree = create_worktree(tmp_path, "1")
        (worktree / "feature.txt").write_text("hello\n")
        subprocess.run(["git", "add", "."], cwd=worktree, capture_output=True, check=True)
        subprocess.run(
            ["git", "commit", "-m", "add feature"], cwd=worktree, capture_output=True, check=True
        )

        # Complete first, then merge
        queue = complete_task(read_task_queue(tmp_path), "1")
        write_task_queue(tmp_path, queue)
        merge_worktree(tmp_path, "1")

        on_disk = read_task_queue(tmp_path)
        assert on_disk.tasks[0].status == TaskStatus.COMPLETED