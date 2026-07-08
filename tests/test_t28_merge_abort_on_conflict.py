"""RED tests for T28 — merge conflict must abort + TimeoutExpired must not crash.

Per ``docs/TASKS.md`` T28 two real-bug fixes:

1. ``merge_worktree()`` raises ``InnerLoopError`` on merge conflict but
   leaves the main repo in ``MERGING`` state — no ``git merge --abort``
   ever runs. The next call to ``_on_gate_pass`` will fail at
   ``git checkout target`` because git refuses to switch branches with
   unmerged entries present. From that moment on, **every** subsequent
   task's merge in develop phase is poisoned.
   Fix: call ``git merge --abort`` (check=False) in project_dir cwd
   before re-raising.

2. ``get_worktree_diff`` / ``get_worktree_files`` use
   ``subprocess.run(..., check=False)`` but their ``except`` clause
   only catches ``CalledProcessError`` — dead code (no error to catch).
   The real ``subprocess.TimeoutExpired`` from the 30s timeout bubbles
   all the way up through ``_collect_review_context`` →
   ``_run_iteration`` and crashes the whole inner loop.
   Fix: broaden the except to also catch ``TimeoutExpired``.

These tests are RED until the worktree module is patched — both will
fail with the current implementation.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from harness.inner_loop import create_worktree, merge_worktree
from harness.loop_errors import InnerLoopError
from harness.worktree import get_worktree_diff, get_worktree_files


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _init_git_repo(path: Path) -> None:
    """Initialise a real git repo on a fresh tmp dir with main + 1 commit."""
    subprocess.run(["git", "init", "-b", "main"], cwd=path, capture_output=True, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=path,
        capture_output=True,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=path,
        capture_output=True,
        check=True,
    )
    (path / "README.md").write_text("# Project\n")
    subprocess.run(["git", "add", "."], cwd=path, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=path, capture_output=True, check=True)


def _make_conflict_setup(project_dir: Path, task_id: str = "1") -> Path:
    """Create a real merge-conflict setup against ``project_dir``.

    Steps (real git):
    - On ``main``: write a.txt = "main version", commit.
    - Branch off ``task/{task_id}`` via worktree, change a.txt to a
      different string, commit.
    - On ``main`` again: change a.txt to yet another different string,
      commit.

    Both branches changed the same line relative to the common
    ancestor, so ``git merge --no-ff task/{task_id}`` from main
    conflicts. Returns the worktree path for completeness.
    """
    # First divergent base on main: a.txt = "main version"
    (project_dir / "a.txt").write_text("line 1 from main\n")
    subprocess.run(["git", "add", "."], cwd=project_dir, capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "-m", "main version"], cwd=project_dir, capture_output=True, check=True
    )

    # Create worktree branched off main's current HEAD
    wt_path = create_worktree(project_dir, task_id)

    # In worktree branch: change a.txt to a different string
    (wt_path / "a.txt").write_text("line 1 from worktree\n")
    subprocess.run(["git", "add", "."], cwd=wt_path, capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "-m", "worktree version"],
        cwd=wt_path,
        capture_output=True,
        check=True,
    )

    # Back on main: change a.txt AGAIN (different from both prior lines)
    (project_dir / "a.txt").write_text("line 1 from main second\n")
    subprocess.run(["git", "add", "."], cwd=project_dir, capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "-m", "main second version"],
        cwd=project_dir,
        capture_output=True,
        check=True,
    )

    return wt_path


# ---------------------------------------------------------------------------
# RED A — merge conflict must trigger ``git merge --abort`` + leave clean repo
# ---------------------------------------------------------------------------


def test_conflict_aborts_and_cleans_repo(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A real merge conflict must trigger ``git merge --abort`` in the main
    repo cwd before ``InnerLoopError`` is re-raised, AND the main repo
    must end up with a clean ``git status`` (no ``UU`` markers, no
    ``MERGE_HEAD``).

    Without the abort, every subsequent ``merge_worktree`` call fails
    because ``git checkout target`` refuses to switch branches with
    unmerged entries present.
    """
    project_dir = tmp_path
    _init_git_repo(project_dir)
    task_id = _make_conflict_setup(project_dir)

    # Pre-condition: repo is clean before merge attempt
    pre_status = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=project_dir,
        capture_output=True,
        text=True,
        check=True,
    )
    assert pre_status.stdout.strip() == "", (
        f"repo dirty before merge attempt:\n{pre_status.stdout}"
    )

    # Spy on subprocess.run so we can prove ``git merge --abort`` was invoked.
    abort_calls: list[tuple[list[str], dict]] = []
    real_run = subprocess.run

    def spy_run(*args, **kwargs):
        cmd = args[0] if args else kwargs.get("args")
        if isinstance(cmd, list) and "merge" in cmd and "--abort" in cmd:
            abort_calls.append((list(cmd), dict(kwargs)))
        return real_run(*args, **kwargs)

    monkeypatch.setattr("harness.worktree.subprocess.run", spy_run)

    # Act: merge_worktree must raise InnerLoopError on real conflict
    with pytest.raises(InnerLoopError):
        merge_worktree(project_dir, task_id)

    # Assert: --abort was called at least once, in the main repo cwd
    assert abort_calls, (
        "merge_worktree did not invoke 'git merge --abort' before re-raising"
    )
    for cmd, kwargs in abort_calls:
        assert "merge" in cmd and "--abort" in cmd, (
            f"unexpected abort call shape: {cmd}"
        )
        assert kwargs.get("cwd") == project_dir, (
            f"--abort must run in main repo cwd, got cwd={kwargs.get('cwd')}"
        )
        # --abort must NOT use check=True — abort returns 1 when there
        # is nothing to abort (e.g. caller invents an error)
        assert kwargs.get("check", True) is False, (
            "merge --abort must use check=False so abort's own non-zero "
            "exit cannot mask the original merge error"
        )

    # Assert: main repo is clean — no UU, no MERGE_HEAD
    post_status = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=project_dir,
        capture_output=True,
        text=True,
        check=True,
    )
    assert post_status.stdout.strip() == "", (
        f"main repo not clean after aborted merge:\n{post_status.stdout}"
    )
    merge_head = project_dir / ".git" / "MERGE_HEAD"
    assert not merge_head.exists(), f"MERGE_HEAD still present at {merge_head}"


# ---------------------------------------------------------------------------
# RED B — TimeoutExpired in diff / files must return empty, not bubble
# ---------------------------------------------------------------------------


def test_diff_timeout_returns_empty(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """``subprocess.TimeoutExpired`` raised by ``get_worktree_diff`` must be
    swallowed and return ``""`` per docstring; the inner loop depends on
    this never crashing on slow git.

    Pass ``base_branch`` explicitly to bypass ``get_current_branch`` (which
    also calls subprocess.run and is not what we are testing here).
    """

    def boom(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd="git diff", timeout=30)

    monkeypatch.setattr("harness.worktree.subprocess.run", boom)

    result = get_worktree_diff(tmp_path, "1", base_branch="main")
    assert result == "", (
        f"get_worktree_diff must return '' on TimeoutExpired, got {result!r}"
    )


def test_files_timeout_returns_empty(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """``subprocess.TimeoutExpired`` raised by ``get_worktree_files`` must be
    swallowed and return ``[]`` per docstring; same rationale as diff."""

    def boom(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd="git diff", timeout=30)

    monkeypatch.setattr("harness.worktree.subprocess.run", boom)

    result = get_worktree_files(tmp_path, "1", base_branch="main")
    assert result == [], (
        f"get_worktree_files must return [] on TimeoutExpired, got {result!r}"
    )