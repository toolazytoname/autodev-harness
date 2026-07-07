"""Git worktree + diff helpers extracted from inner_loop.

T24 — splitting inner_loop.py (was 1061 lines) so each unit of work
can be reasoned about and unit-tested on its own. The functions in
this module are pure git plumbing: branch creation, worktree attach,
merge, diff and file-list extraction. They depend only on stdlib
subprocess and the project's own exceptions.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Optional

from harness.loop_errors import InnerLoopError

# ``_run_git`` and ``get_current_branch`` are the leaf primitives every
# other helper composes on top of. Keep them private to this module —
# callers in inner_loop should reach for create/merge/get_*_diff.


def _run_git(
    *args: str,
    cwd: Path,
    timeout: int = 30,
) -> subprocess.CompletedProcess:
    """Run a git command and return the completed process.

    Raises ``InnerLoopError`` on non-zero exit or timeout. Callers that
    need the raw ``CalledProcessError`` (e.g. to fall back to empty
    output) should bypass this helper and use ``subprocess.run``
    directly — see ``get_worktree_diff`` / ``get_worktree_files``.
    """
    try:
        return subprocess.run(
            ["git"] + list(args),
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=True,
        )
    except subprocess.CalledProcessError as exc:
        raise InnerLoopError(
            f"git {' '.join(args)} failed (exit {exc.returncode}): {exc.stderr}"
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise InnerLoopError(
            f"git {' '.join(args)} timed out after {timeout}s"
        ) from exc


def get_current_branch(project_dir: Path) -> str:
    """Return the branch currently checked out in ``project_dir``."""
    proc = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        cwd=project_dir,
        capture_output=True,
        text=True,
        timeout=10,
    )
    branch = proc.stdout.strip()
    if proc.returncode != 0 or not branch:
        raise InnerLoopError(
            f"Cannot determine current branch in {project_dir}: {proc.stderr.strip()}"
        )
    return branch


def create_worktree(
    project_dir: Path,
    task_id: str,
    base_branch: Optional[str] = None,
) -> Path:
    """Create a new git worktree for a task.

    Creates branch ``task/{task_id}`` from ``base_branch`` (or current HEAD).
    Returns the worktree directory path.

    T18 — idempotent. If the worktree (and branch) already exist because
    a previous run crashed mid-task, the existing worktree is reused
    instead of failing with ``fatal: a branch named 'task/{id}' already
    exists``. Resume can therefore safely call this multiple times for
    the same task. When neither the worktree nor the branch exist we
    create both; when the worktree exists but the branch was pruned
    (rare) we re-attach.
    """
    branch_name = f"task/{task_id}"
    worktree_path = project_dir / ".worktrees" / branch_name

    # Reuse path if the worktree directory is already there — the branch
    # reference is what matters, not the directory mtime.
    if worktree_path.exists():
        return worktree_path

    ref = base_branch or get_current_branch(project_dir)

    # If the branch exists but the worktree was pruned, attach without
    # ``-b`` so we don't ask git to create a duplicate branch.
    branch_proc = subprocess.run(
        ["git", "rev-parse", "--verify", f"refs/heads/{branch_name}"],
        cwd=project_dir,
        capture_output=True,
        text=True,
    )
    if branch_proc.returncode == 0:
        _run_git(
            "worktree", "add",
            str(worktree_path),
            branch_name,
            cwd=project_dir,
        )
    else:
        _run_git(
            "worktree", "add",
            "-b", branch_name,
            str(worktree_path),
            ref,
            cwd=project_dir,
        )
    return worktree_path


def merge_worktree(
    project_dir: Path,
    task_id: str,
    base_branch: Optional[str] = None,
) -> None:
    """Merge the task worktree branch into the base branch and remove the worktree.

    ``base_branch`` defaults to whatever branch is currently checked out in
    ``project_dir`` (the branch the worktree was created from). The branch
    named "main" is never assumed.
    """
    branch_name = f"task/{task_id}"
    worktree_path = project_dir / ".worktrees" / branch_name

    # Check if worktree exists
    worktree_root = project_dir / ".worktrees"
    if not worktree_root.exists():
        raise InnerLoopError(f"No worktree root found at {worktree_root}")

    target = base_branch or get_current_branch(project_dir)
    current = get_current_branch(project_dir)
    if current != target:
        _run_git("checkout", target, cwd=project_dir)
    try:
        _run_git("merge", "--no-ff", branch_name, cwd=project_dir)
    except InnerLoopError:
        # Best-effort: surface a clear error; orchestrator decides what to do.
        raise
    finally:
        # Always attempt to remove the worktree dir, even on merge failure
        try:
            _run_git("worktree", "remove", str(worktree_path), cwd=project_dir)
        except InnerLoopError:
            pass


def get_worktree_diff(
    project_dir: Path,
    task_id: str,
    base_branch: Optional[str] = None,
) -> str:
    """Return the diff of the task branch vs the base branch.

    Returns ``""`` on git error — callers treat empty diff as "no
    changes yet" (first iteration) rather than a hard failure.
    """
    branch_name = f"task/{task_id}"
    base = base_branch or get_current_branch(project_dir)
    try:
        proc = subprocess.run(
            ["git", "diff", base, branch_name, "--"],
            cwd=project_dir,
            capture_output=True,
            text=True,
            timeout=30,
        )
        return proc.stdout
    except subprocess.CalledProcessError:
        return ""


def get_worktree_files(
    project_dir: Path,
    task_id: str,
    base_branch: Optional[str] = None,
) -> list[str]:
    """Return the list of files changed in the task branch vs the base branch.

    Returns ``[]`` on git error — same rationale as ``get_worktree_diff``.
    """
    branch_name = f"task/{task_id}"
    base = base_branch or get_current_branch(project_dir)
    try:
        proc = subprocess.run(
            ["git", "diff", "--name-only", base, branch_name, "--"],
            cwd=project_dir,
            capture_output=True,
            text=True,
            timeout=30,
        )
        return [f for f in proc.stdout.splitlines() if f]
    except subprocess.CalledProcessError:
        return []
