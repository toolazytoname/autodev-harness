"""Inner quality loop — generate → N reviewers → gate (orchestrator).

Per MASTER-PLAN §2: independent generator + parallel reviewers + gate → commit.

T24 — the bulk of the logic now lives in:

  - ``harness.worktree``         — git worktree + diff helpers
  - ``harness.generator``        — run_generator + GeneratorOutput
  - ``harness.reviewer_runner``  — run_single_reviewer / parallel / gate

This module is the orchestrator: it loads the task from the queue,
spins up a worktree, runs iterations of (generate + reviewers +
gate), and on a successful gate commits + merges the worktree
transactionally (T18). It also keeps the old public API surface
(re-exports) so existing imports from ``harness.inner_loop`` keep
working.

The loop runs per-task inside a git worktree.  On gate pass the
worktree is merged into the main branch and the task is marked done.
On failure blockers are fed back to the generator (without exposing
reviewer transcripts) and the loop iterates.  After ``MAX_ITER``
iterations without passing, the task is escalated for architect
arbitration.
"""

from __future__ import annotations

import textwrap
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from harness.adapters.base import AdapterBase, Usage
from harness.artifacts import (
    Task,
    complete_task,
    mark_task_in_progress,
    read_task_queue,
    write_task_queue,
)
from harness.generator import GeneratorOutput, run_generator
from harness.logging_setup import get_logger
from harness.loop_errors import EscalationError, InnerLoopError  # re-exported
from harness.reviewer_runner import (
    capture_ui_screenshots,
    check_gate,
    run_reviewers_parallel,
    run_single_reviewer,  # re-exported for backward compat
    _run_visual_reviewer,  # re-exported for backward compat (legacy tests)
)
from harness.router import ModelRouter
from harness.score_card import ScoreCard, summarize_cards
from harness.worktree import (
    create_worktree,  # re-exported
    get_current_branch,
    get_worktree_diff,  # re-exported
    get_worktree_files,  # re-exported
    merge_worktree,  # re-exported
)


_log = get_logger(__name__)


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class LoopConfig:
    """Configuration for a single inner loop run."""

    max_iterations: int = 5
    pass_threshold: float = 0.8
    # Base branch to create worktrees from (None = use current HEAD)
    base_branch: Optional[str] = None


# ---------------------------------------------------------------------------
# Escalation report
# ---------------------------------------------------------------------------


def write_escalation_report(
    project_dir: Path,
    task_id: str,
    iter_count: int,
    cards: list[ScoreCard],
    spec_text: str,
) -> Path:
    """Write an escalation report to disk for architect arbitration."""
    report_path = project_dir / ".runner" / "escalation" / f"{task_id}.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)

    diff_text = get_worktree_diff(project_dir, task_id)
    files = get_worktree_files(project_dir, task_id)
    summary = summarize_cards(cards)

    report_path.write_text(_ESCALATION_TEMPLATE.format(
        task_id=task_id,
        timestamp=datetime.now(timezone.utc).isoformat(),
        iter_count=iter_count,
        summary=summary,
        spec=spec_text,
        files="\n".join(f"- {f}" for f in files) if files else "(none)",
        diff=diff_text or "(no diff)",
        score_cards=summary,
    ))
    return report_path


_ESCALATION_TEMPLATE = textwrap.dedent(
    """\
    # Escalation Report: Task {task_id}

    > Generated: {timestamp}
    > Iterations exhausted: {iter_count} (max)

    ## Summary

    {summary}

    ## Product Specification

    {spec}

    ## Changed Files

    {files}

    ## Full Diff

    ```diff
    {diff}
    ```

    ## All Score Cards

    {score_cards}
    """
)


# ---------------------------------------------------------------------------
# Per-step helpers (T24 — per-iteration unit testability)
# ---------------------------------------------------------------------------


@dataclass
class TaskSetup:
    """Bundle of state captured at the start of a task's inner loop.

    Carries everything ``_run_iteration`` and ``_on_gate_pass`` need
    without re-reading the queue / re-creating the worktree.
    """

    project_dir: Path
    worktree_path: Path
    task: Task
    reviewer_names: list[str]
    base_branch: str
    # Per-task mutable context that the orchestrator maintains across
    # iterations; passed through so callers can build it before run.
    previous_blockers: list[str] = field(default_factory=list)
    previous_suggestions: list[str] = field(default_factory=list)


def _setup_task(
    project_dir: Path,
    task_id: str,
    config: Optional[LoopConfig],
) -> TaskSetup:
    """Load the task, create its worktree, and resolve the reviewer set.

    T18 — marks the task ``IN_PROGRESS`` on disk before doing any
    work, so a crash mid-task leaves the task ``IN_PROGRESS`` and
    ``--continue`` can pick it up cleanly.
    """
    if config is None:
        config = LoopConfig()

    task = _find_task(project_dir, task_id)
    platform = task.platform or "web"

    from harness.reviewers import ReviewerAssembly

    reviewer_names = ReviewerAssembly().get_reviewer_names(task.kind, platform=platform)

    # T18 — mark the task IN_PROGRESS on disk before doing any work.
    mark_task_in_progress(project_dir, task_id)
    _log.info(
        "task_started",
        extra={
            "stage": "develop",
            "task_id": task_id,
            "kind": task.kind,
            "platform": platform,
            "max_iterations": config.max_iterations,
        },
    )

    worktree_path = _create_task_worktree(
        project_dir=project_dir,
        task_id=task_id,
        base_branch=config.base_branch,
    )

    return TaskSetup(
        project_dir=project_dir,
        worktree_path=worktree_path,
        task=task,
        reviewer_names=reviewer_names,
        base_branch=config.base_branch or get_current_branch(project_dir),
    )


def _find_task(project_dir: Path, task_id: str) -> Task:
    """Read the task queue and return the task with the matching id.

    Raises ``InnerLoopError`` when the queue is missing or the task
    isn't in it. T18 — the queue is the only source of truth for
    "is this task already done / blocked", so the lookup is strict.
    """
    queue = read_task_queue(project_dir)
    if queue is None:
        raise InnerLoopError(f"No task queue found in {project_dir}")
    for t in queue.tasks:
        if t.id == task_id:
            return t
    raise InnerLoopError(f"Task {task_id} not found in task queue")


def _create_task_worktree(
    project_dir: Path, task_id: str, base_branch: Optional[str]
) -> Path:
    """Create the worktree (or reuse T18's idempotent path) and return it."""
    ref = base_branch or get_current_branch(project_dir)
    try:
        return create_worktree(project_dir, task_id, base_branch=ref)
    except Exception as exc:
        raise InnerLoopError(
            f"Failed to create worktree for task {task_id}: {exc}"
        ) from exc


@dataclass
class IterationResult:
    """Everything produced by one generate+reviewer pass."""

    cards: list[ScoreCard]
    reviewer_usages: list[Usage]
    generator_output: GeneratorOutput
    diff_text: str
    changed_files: list[str]
    screenshots: list[Path]


def _run_iteration(
    adapter: AdapterBase,
    router: ModelRouter,
    setup: TaskSetup,
    spec_text: str,
    iter_num: int,
) -> IterationResult:
    """Run one pass: generator → diff capture → parallel reviewers.

    T24 — extracted from the inlined body of ``run_inner_loop`` so a
    single iteration can be unit-tested without driving the full
    loop. Returns the per-iteration bookkeeping the orchestrator
    needs (cards, usage, diff) without performing the gate check or
    the merge.
    """
    generator_output = _run_generator_step(
        adapter=adapter, router=router, setup=setup,
        spec_text=spec_text, iter_num=iter_num,
    )
    diff_text, changed_files, screenshots = _collect_review_context(
        setup=setup, spec_text=spec_text,
    )
    cards, reviewer_usages = _run_reviewer_step(
        adapter=adapter, router=router, setup=setup, spec_text=spec_text,
        iter_num=iter_num, diff_text=diff_text, changed_files=changed_files,
        screenshots=screenshots,
    )
    return IterationResult(
        cards=cards,
        reviewer_usages=reviewer_usages,
        generator_output=generator_output,
        diff_text=diff_text,
        changed_files=changed_files,
        screenshots=screenshots,
    )


def _run_generator_step(
    adapter: AdapterBase,
    router: ModelRouter,
    setup: TaskSetup,
    spec_text: str,
    iter_num: int,
) -> GeneratorOutput:
    """Generate code in the worktree + record token usage.

    T24 — extracted from ``_run_iteration`` to keep it under 50 lines.
    Reads the previous iteration's feedback from ``setup`` (immutable
    snapshot) and passes it to the generator as structured blockers /
    suggestions. Reviewer transcripts are never forwarded (per
    MASTER-PLAN §2).
    """
    generator_output = run_generator(
        adapter=adapter,
        router=router,
        worktree_path=setup.worktree_path,
        spec_text=spec_text,
        task_id=setup.task.id,
        task_title=setup.task.title,
        task_description=setup.task.description,
        blockers_from_previous=list(setup.previous_blockers),
        suggestions_from_previous=list(setup.previous_suggestions),
        iter_num=iter_num,
    )
    router.record("generate", generator_output.usage.usage)
    return generator_output


def _collect_review_context(
    setup: TaskSetup,
    spec_text: str,
) -> tuple[str, list[str], list[Path]]:
    """Snapshot the diff, changed files, and (for UI tasks) screenshots.

    Returns (diff_text, changed_files, screenshots). Screenshots are
    only captured for UI tasks that include the ``visual`` reviewer;
    other tasks get an empty list. The screenshot pass is best-effort
    — failures return ``[]`` rather than blocking the loop.
    """
    diff_text = get_worktree_diff(
        setup.project_dir,
        setup.task.id,
        base_branch=setup.base_branch,
    )
    changed_files = get_worktree_files(
        setup.project_dir,
        setup.task.id,
        base_branch=setup.base_branch,
    )
    screenshots: list[Path] = []
    if setup.task.kind == "ui" and "visual" in setup.reviewer_names:
        screenshots = capture_ui_screenshots(
            project_dir=setup.project_dir,
            task_id=setup.task.id,
            spec_text=spec_text,
        )
    return diff_text, changed_files, screenshots


def _run_reviewer_step(
    adapter: AdapterBase,
    router: ModelRouter,
    setup: TaskSetup,
    spec_text: str,
    iter_num: int,
    diff_text: str,
    changed_files: list[str],
    screenshots: list[Path],
) -> tuple[list[ScoreCard], list[Usage]]:
    """Run the reviewer fan-out + record per-reviewer token usage.

    Reviewers execute in parallel via ``run_reviewers_parallel``; each
    reviewer's usage is recorded under its own stage key
    (``review.<name>``) so the budget tracker attributes tokens to
    the right bucket.
    """
    from harness.reviewers import ReviewerAssembly

    cards, reviewer_usages = run_reviewers_parallel(
        adapter=adapter,
        router=router,
        worktree_path=setup.worktree_path,
        project_dir=setup.project_dir,
        task_id=setup.task.id,
        reviewer_names=setup.reviewer_names,
        agents_dir=ReviewerAssembly().agents_dir,
        spec_text=spec_text,
        diff_text=diff_text,
        changed_files=changed_files,
        iter_num=iter_num,
        screenshots=screenshots,
        acceptance=list(setup.task.acceptance) if setup.task.acceptance else None,
    )
    for card, usage in zip(cards, reviewer_usages):
        stage = f"review.{card.reviewer}"
        router.record(stage, usage)
    return cards, reviewer_usages


def _on_gate_pass(
    project_dir: Path,
    task_id: str,
    base_branch: str,
    iter_num: int,
    all_cards: list[ScoreCard],
    spec_text: str,
) -> None:
    """Write COMPLETED to disk, then merge the worktree branch.

    T18 transaction order:
      1. Write COMPLETED to disk FIRST so a crash mid-merge leaves
         the task marked done and resume skips it.
      2. Then merge. A merge conflict raises ``EscalationError``
         with the on-disk COMPLETED state preserved (architect
         arbitrates the discrepancy).
    """
    _mark_task_completed(project_dir, task_id)
    try:
        merge_worktree(project_dir, task_id, base_branch=base_branch)
    except InnerLoopError as exc:
        _escalate_on_merge_conflict(
            project_dir=project_dir,
            task_id=task_id,
            iter_num=iter_num,
            all_cards=all_cards,
            spec_text=spec_text,
            exc=exc,
        )
        raise
    _log.info(
        "merge_complete",
        extra={"stage": "develop", "task_id": task_id, "iter": iter_num},
    )


def _mark_task_completed(project_dir: Path, task_id: str) -> None:
    """Persist the task's COMPLETED status before merging (T18)."""
    queue = read_task_queue(project_dir)
    if queue:
        queue = complete_task(queue, task_id)
        write_task_queue(project_dir, queue)


def _escalate_on_merge_conflict(
    *,
    project_dir: Path,
    task_id: str,
    iter_num: int,
    all_cards: list[ScoreCard],
    spec_text: str,
    exc: InnerLoopError,
) -> None:
    """Log a merge conflict + write the escalation report.

    The COMPLETED status on disk is left intact; the architect sees
    the discrepancy (COMPLETED on disk vs task branch un-merged in
    the repo) in the escalation report and decides.
    """
    _log.error(
        "merge_failed",
        extra={
            "stage": "develop",
            "task_id": task_id,
            "iter": iter_num,
            "error": str(exc),
        },
    )
    write_escalation_report(project_dir, task_id, iter_num, all_cards, spec_text)
    raise EscalationError(task_id, iter_num, all_cards) from exc


# ---------------------------------------------------------------------------
# Main inner loop — orchestrator
# ---------------------------------------------------------------------------


def _gate_after_iteration(
    *,
    result: IterationResult,
    setup: TaskSetup,
    config: LoopConfig,
    project_dir: Path,
    task_id: str,
    spec_text: str,
    all_cards: list[ScoreCard],
    iter_num: int,
) -> tuple[bool, TaskSetup]:
    """Apply the gate, commit on pass, or return feedback for next iter.

    Returns ``(passed, next_setup)``. When ``passed=True`` the
    orchestrator stops; when ``passed=False`` the next iteration
    runs with the rebuilt ``next_setup`` (carrying the latest
    blockers / suggestions).
    """
    passed, reason = check_gate(result.cards, pass_threshold=config.pass_threshold)
    _log.info(
        "gate_evaluated",
        extra={
            "stage": "develop",
            "task_id": task_id,
            "iter": iter_num,
            "passed": passed,
            "reason": reason,
        },
    )
    if passed:
        _on_gate_pass(
            project_dir=project_dir,
            task_id=task_id,
            base_branch=setup.base_branch,
            iter_num=iter_num,
            all_cards=all_cards,
            spec_text=spec_text,
        )
        return True, setup
    return False, _carry_feedback_forward(setup, result)


def _carry_feedback_forward(
    setup: TaskSetup, result: IterationResult
) -> TaskSetup:
    """Build a fresh TaskSetup with the latest iteration's feedback.

    Immutable update — the previous iteration's setup is not
    mutated in place. The fresh copy is what the next generator
    prompt reads from.
    """
    return TaskSetup(
        project_dir=setup.project_dir,
        worktree_path=setup.worktree_path,
        task=setup.task,
        reviewer_names=setup.reviewer_names,
        base_branch=setup.base_branch,
        previous_blockers=[b for c in result.cards for b in c.blockers],
        previous_suggestions=[s for c in result.cards for s in c.suggestions],
    )


def run_inner_loop(
    project_dir: Path,
    task_id: str,
    spec_text: str,
    task_kind: str,
    adapter: AdapterBase,
    router: ModelRouter,
    config: Optional[LoopConfig] = None,
) -> list[ScoreCard]:
    """Run the full inner quality loop for a single task.

    Orchestrates: setup → iteration loop → commit on gate pass →
    escalate on MAX_ITER. Iteration, gate, and commit steps are
    delegated; this function is the only place the loop is wired
    together.
    """
    if config is None:
        config = LoopConfig()
    setup = _setup_task(project_dir, task_id, config)

    all_cards: list[ScoreCard] = []
    iter_num = 1
    try:
        while iter_num <= config.max_iterations:
            result = _run_iteration(
                adapter=adapter, router=router, setup=setup,
                spec_text=spec_text, iter_num=iter_num,
            )
            all_cards.extend(result.cards)
            passed, setup = _gate_after_iteration(
                result=result, setup=setup, config=config,
                project_dir=project_dir, task_id=task_id,
                spec_text=spec_text, all_cards=all_cards, iter_num=iter_num,
            )
            if passed:
                return all_cards
            iter_num += 1
    finally:
        # Preserve the worktree on escalation; the escalation
        # report already references its path.
        pass

    # MAX_ITER exhausted without gate pass
    write_escalation_report(
        project_dir, task_id, config.max_iterations, all_cards, spec_text
    )
    raise EscalationError(task_id, config.max_iterations, all_cards)
