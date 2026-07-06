"""Inner quality loop — generate → N reviewers → gate.

Per MASTER-PLAN §2: independent generator + parallel reviewers + gate → commit.

The loop runs per-task inside a git worktree.  On gate pass the worktree
is merged into the main branch and the task is marked done.  On failure
blockers are fed back to the generator (without exposing reviewer
transcripts) and the loop iterates.  After MAX_ITER iterations without
passing, the task is escalated for architect arbitration.
"""

from __future__ import annotations

import json
import os
import subprocess
import textwrap
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

from harness.adapters.base import AdapterBase, AgentResult
from harness.artifacts import (
    Task,
    TaskQueue,
    TaskStatus,
    complete_task,
    mark_task_in_progress,
    read_task_queue,
    write_task_queue,
)
from harness.logging_setup import get_logger

_log = get_logger(__name__)
from harness.router import ModelRouter, ModelSpec
from harness.score_card import (
    ScoreCard,
    gate_passed,
    load_all_cards,
    parse_score_card,
    save_score_card,
    summarize_cards,
)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class InnerLoopError(Exception):
    """Base exception for inner loop failures."""

    pass


class EscalationError(InnerLoopError):
    """Raised when the loop has exhausted MAX_ITER without a gate pass."""

    def __init__(self, task_id: str, iter_count: int, cards: list[ScoreCard]):
        self.task_id = task_id
        self.iter_count = iter_count
        self.cards = cards
        super().__init__(
            f"Task {task_id} exhausted {iter_count} iterations without a gate pass."
        )


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


@dataclass
class GeneratorOutput:
    """Output from the generator step."""

    stdout: str
    stderr: str
    exit_code: int
    usage: "AgentResult"


# ---------------------------------------------------------------------------
# Git / worktree helpers
# ---------------------------------------------------------------------------


def _run_git(
    *args: str,
    cwd: Path,
    timeout: int = 30,
) -> subprocess.CompletedProcess:
    """Run a git command and return the completed process."""
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
        raise InnerLoopError(f"git {' '.join(args)} timed out after {timeout}s") from exc


def get_current_branch(project_dir: Path) -> str:
    """Return the branch currently checked out in project_dir."""
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
        # Merge conflict — leave the worktree intact for debugging
        raise

    # Remove the worktree
    _run_git("worktree", "remove", str(worktree_path), cwd=project_dir)
    # Remove the branch
    _run_git("branch", "-d", branch_name, cwd=project_dir)


# ---------------------------------------------------------------------------
# Generator step
# ---------------------------------------------------------------------------


def run_generator(
    adapter: AdapterBase,
    router: ModelRouter,
    worktree_path: Path,
    spec_text: str,
    task_id: str,
    task_title: str,
    task_description: Optional[str],
    blockers_from_previous: list[str],
    suggestions_from_previous: list[str],
    iter_num: int,
) -> GeneratorOutput:
    """Run the generator in the task worktree using the worker-tier model.

    The generator prompt includes the spec and any feedback from previous
    iterations (blockers + suggestions).  Reviewer transcripts are NOT
    included — only structured feedback.

    T19 — propagates ``spec.base_url`` and the per-tier API key (read from
    ``AUTODEV_API_KEY_<TIER>``) to the subprocess so worker-tier calls
    reach the configured third-party endpoint instead of the default.
    """
    spec = router.resolve("generate")
    api_key = os.environ.get(f"AUTODEV_API_KEY_{spec.tier.upper()}")

    # Build the prompt with feedback from previous iterations
    feedback_block = ""
    if blockers_from_previous or suggestions_from_previous:
        feedback_block = textwrap.dedent(
            """
            ## Feedback from previous attempt (iter {iter})

            The following issues were identified.  Please address them in your next attempt.
            Do NOT include reviewer transcripts in your response — only fix the issues.

            ### Blockers (must fix)
            {blockers}

            ### Suggestions (consider fixing)
            {suggestions}
            """
        ).format(
            iter=iter_num,
            blockers="\n".join(f"- {b}" for b in blockers_from_previous) or "(none)",
            suggestions="\n".join(f"- {s}" for s in suggestions_from_previous) or "(none)",
        )

    prompt = textwrap.dedent(
        """\
        You are implementing task: {task_id} — {task_title}

        {task_description}

        ## Product Specification
        {spec}

        {feedback_block}
        ## Your job

        Implement the feature as specified.  Write clean, complete code.
        When done, output a brief summary of what you changed and confirm the implementation
        is complete.

        Important:
        - Do NOT run tests yourself (that is the reviewers' job).
        - Do NOT include reviewer feedback or score card content in your output.
        - Work only in the current directory (the worktree).
        """
    ).format(
        task_id=task_id,
        task_title=task_title,
        task_description=task_description or "(no description)",
        spec=spec_text,
        feedback_block=feedback_block,
    )

    result = adapter.run(
        prompt,
        model=spec.model,
        cwd=worktree_path,
        timeout=300,  # 5 min for generation
        base_url=spec.base_url,
        api_key=api_key,
        fallback_model=spec.fallback,
    )

    return GeneratorOutput(
        stdout=result.stdout,
        stderr=result.stderr,
        exit_code=result.exit_code,
        usage=result,
    )


# ---------------------------------------------------------------------------
# Diff extraction
# ---------------------------------------------------------------------------


def get_worktree_diff(
    project_dir: Path,
    task_id: str,
    base_branch: Optional[str] = None,
) -> str:
    """Return the diff of the task branch vs the base branch."""
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
    """Return the list of files changed in the task branch vs the base branch."""
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


# ---------------------------------------------------------------------------
# Reviewer step
# ---------------------------------------------------------------------------


def run_single_reviewer(
    adapter: AdapterBase,
    router: ModelRouter,
    worktree_path: Path,
    project_dir: Path,
    task_id: str,
    reviewer_name: str,
    prompt_path: Path,
    spec_text: str,
    diff_text: str,
    changed_files: list[str],
    iter_num: int,
    screenshots: Optional[list[Path]] = None,
    acceptance: Optional[list[str]] = None,
) -> tuple[ScoreCard, "Usage"]:
    """Run a single reviewer and return its score card and token usage.

    Each reviewer:
    1. Reads its prompt template from agents/reviewers/{name}.md
    2. Receives: spec, diff, changed files, iteration number
    3. Runs the adapter (reviewer-tier model)
    4. Parses the score card JSON from the output
    5. Saves the score card to disk

    For the special reviewer named ``"visual"`` the prompt-only path is
    bypassed entirely; instead ``harness.visual_reviewer.run_visual_review``
    is invoked which captures screenshots and feeds them to a multimodal
    model. ``screenshots`` is ignored for non-visual reviewers so the
    rest of the registry stays uniform.
    """
    from harness.adapters.base import Usage  # noqa: PLC0415

    if reviewer_name == "visual":
        return _run_visual_reviewer(
            adapter=adapter,
            router=router,
            worktree_path=worktree_path,
            project_dir=project_dir,
            task_id=task_id,
            spec_text=spec_text,
            diff_text=diff_text,
            changed_files=changed_files,
            iter_num=iter_num,
            screenshots=screenshots or [],
            prompt_path=prompt_path,
        )

    stage = f"review.{reviewer_name}"
    spec = router.resolve(stage)

    prompt_template = prompt_path.read_text()

    # Inject context into the prompt. ``acceptance`` is a list of
    # human-readable steps the test reviewer is expected to convert
    # into executable commands; other reviewers use it as a checklist
    # that the spec was met.
    acceptance_block = ""
    if acceptance:
        numbered = "\n".join(f"{i+1}. {step}" for i, step in enumerate(acceptance))
        acceptance_block = (
            "\n## Task Acceptance Criteria (from taskgen)\n"
            "The author of this task committed to these acceptance steps.\n"
            "For each step, decide if the diff/spec proves it's met.\n"
            f"{numbered}\n"
        )

    prompt = textwrap.dedent(
        """\
        {prompt_template}

        ## Context

        Task ID: {task_id}
        Iteration: {iter_num}
        Worktree path: {worktree_path}

        ## Changed files this iteration
        {changed_files}

        ## Diff (changes since last iteration)
        {diff}

        ## Product Specification
        {spec}
        {acceptance_block}
        Output your score card as JSON at the end of your response.
        """
    ).format(
        prompt_template=prompt_template,
        task_id=task_id,
        iter_num=iter_num,
        worktree_path=str(worktree_path),
        changed_files="\n".join(f"- {f}" for f in changed_files) if changed_files else "(no files changed yet)",
        diff=diff_text or "(no diff yet — this is the first iteration)",
        spec=spec_text,
        acceptance_block=acceptance_block,
    )

    try:
        # T19 — propagate the resolved spec's base_url/api_key/fallback so
        # reviewer calls also ride the third-party chain correctly.
        review_api_key = os.environ.get(
            f"AUTODEV_API_KEY_{spec.tier.upper()}"
        )
        result = adapter.run(
            prompt,
            model=spec.model,
            cwd=worktree_path,
            timeout=180,  # 3 min per reviewer
            base_url=spec.base_url,
            api_key=review_api_key,
            fallback_model=spec.fallback,
        )
        raw_output = result.stdout
        usage: Usage = result.usage
    except Exception as exc:
        # Reviewer failure — score 0 with the error as blocker
        return (
            ScoreCard(
                iter=iter_num,
                reviewer=reviewer_name,
                score=0.0,
                blockers=[f"Reviewer crashed: {exc}"],
                suggestions=[],
                evidence=f"Exception: {exc}",
            ),
            Usage(),
        )

    # Parse the score card from the output
    try:
        card = parse_score_card(raw_output)
        card = ScoreCard(
            iter=iter_num,
            reviewer=reviewer_name,
            score=card.score,
            blockers=card.blockers,
            suggestions=card.suggestions,
            evidence=card.evidence,
        )
    except Exception:
        # Try extracting JSON from fenced output
        from harness.score_card import extract_json_from_fenced  # noqa: PLC0415

        cleaned = extract_json_from_fenced(raw_output)
        try:
            card = parse_score_card(cleaned)
            card = ScoreCard(
                iter=iter_num,
                reviewer=reviewer_name,
                score=card.score,
                blockers=card.blockers,
                suggestions=card.suggestions,
                evidence=card.evidence,
            )
        except Exception as inner_exc:
            card = ScoreCard(
                iter=iter_num,
                reviewer=reviewer_name,
                score=0.0,
                blockers=[f"Failed to parse score card: {inner_exc}"],
                suggestions=[],
                evidence=raw_output[:500],
            )

    # Save the score card
    save_score_card(project_dir, task_id, card)
    return card, usage


def _run_visual_reviewer(
    adapter: AdapterBase,
    router: ModelRouter,
    worktree_path: Path,
    project_dir: Path,
    task_id: str,
    spec_text: str,
    diff_text: str,
    changed_files: list[str],
    iter_num: int,
    screenshots: list[Path],
    prompt_path: Path,
) -> tuple[ScoreCard, "Usage"]:
    """Dispatch path for the multimodal visual reviewer.

    For UI tasks the inner loop pre-captures screenshots once per
    iteration into ``score-cards/task-{id}/screenshots/``; this helper
    receives the already-captured paths, hands them to
    ``harness.visual_reviewer.run_visual_review``, and persists the
    resulting score card like every other reviewer.
    """
    from harness.adapters.base import Usage  # noqa: PLC0415
    from harness.visual_reviewer import run_visual_review

    stage = "review.visual"
    spec = router.resolve(stage)
    card = run_visual_review(
        adapter=adapter,
        model=spec.model,
        spec_text=spec_text,
        diff_text=diff_text,
        changed_files=changed_files,
        screenshots=screenshots,
        worktree_path=worktree_path,
        iter_num=iter_num,
        reviewer_prompt=prompt_path,
    )
    save_score_card(project_dir, task_id, card)
    # The visual reviewer's token usage is harder to recover through the
    # multimodal return path — record an empty Usage so the budget
    # tracker does not get out of sync. Tighter accounting can land later
    # if budget turns out to be a problem in real runs.
    return card, Usage()


def capture_ui_screenshots(
    project_dir: Path,
    task_id: str,
    spec_text: str,
    *,
    base_url: Optional[str] = None,
    capture_kwargs: Optional[dict] = None,
) -> list[Path]:
    """Capture screenshots for a UI task and return their paths.

    ``base_url`` defaults to the ``AUTODEV_VISUAL_BASE_URL`` env var so
    callers can run the harness against a project running on a free
    port in tests, or against a known dev-server URL in production.
    """
    import os  # local; stdlib so cheap
    from harness.visual_reviewer import (
        capture_with_fallback,
        extract_pages_from_spec,
        screenshots_dir_for,
    )

    base_url = base_url or os.environ.get(
        "AUTODEV_VISUAL_BASE_URL", "http://127.0.0.1:8765"
    )
    pages = extract_pages_from_spec(spec_text)
    out_dir = screenshots_dir_for(project_dir, task_id)
    ensure_dir(out_dir)

    capture_kwargs = capture_kwargs or {}
    try:
        report = capture_with_fallback(
            base_url=base_url,
            pages=pages,
            out_dir=out_dir,
            **capture_kwargs,
        )
    except Exception:
        return []

    return [c.path for c in report.captures]


def run_reviewers_parallel(
    adapter: AdapterBase,
    router: ModelRouter,
    worktree_path: Path,
    project_dir: Path,
    task_id: str,
    reviewer_names: list[str],
    agents_dir: Path,
    spec_text: str,
    diff_text: str,
    changed_files: list[str],
    iter_num: int,
    screenshots: Optional[list[Path]] = None,
    acceptance: Optional[list[str]] = None,
) -> tuple[list[ScoreCard], list["Usage"]]:
    """Run all reviewers in parallel via ThreadPoolExecutor.

    Each reviewer runs in its own thread with its own adapter call.
    A reviewer timeout does not affect the others.
    Returns (list of score cards, list of usage objects) — order not guaranteed.

    ``screenshots`` (a list of PNG/PDF paths) is passed through to the
    visual reviewer only; other reviewers ignore it.

    ``acceptance`` (a list of human-readable test steps) is passed to
    every reviewer. The test reviewer is expected to convert each
    step into an executable command; other reviewers use it as
    evidence the spec was met.
    """
    from harness.adapters.base import Usage  # noqa: PLC0415

    cards: list[ScoreCard] = []
    usages: list[Usage] = []
    lock = threading.Lock()

    def _run(name: str, prompt_path: Path) -> tuple[ScoreCard, Usage]:
        card, usage = run_single_reviewer(
            adapter=adapter,
            router=router,
            worktree_path=worktree_path,
            project_dir=project_dir,
            task_id=task_id,
            reviewer_name=name,
            prompt_path=prompt_path,
            spec_text=spec_text,
            diff_text=diff_text,
            changed_files=changed_files,
            iter_num=iter_num,
            screenshots=screenshots,
            acceptance=acceptance,
        )
        with lock:
            cards.append(card)
            usages.append(usage)
        return card, usage

    with ThreadPoolExecutor(max_workers=len(reviewer_names)) as executor:
        futures = {
            executor.submit(
                _run, name, agents_dir / f"{name}.md"
            ): name
            for name in reviewer_names
        }
        for future in as_completed(futures):
            name = futures[future]
            try:
                future.result()  # re-raise any exception from _run
            except Exception as exc:
                # This shouldn't normally happen since _run catches exceptions
                # and returns an error card — but handle it just in case
                error_card = ScoreCard(
                    iter=iter_num,
                    reviewer=name,
                    score=0.0,
                    blockers=[f"Unexpected reviewer error: {exc}"],
                    suggestions=[],
                    evidence="",
                )
                with lock:
                    cards.append(error_card)
                    usages.append(Usage())
                save_score_card(project_dir, task_id, error_card)

    return cards, usages


# ---------------------------------------------------------------------------
# Gate check
# ---------------------------------------------------------------------------


def check_gate(
    cards: list[ScoreCard],
    pass_threshold: float = 0.8,
) -> tuple[bool, str]:
    """Check whether the gate has passed.

    Returns (passed, reason).
    """
    if not cards:
        return False, "No score cards produced"

    if not gate_passed(cards, pass_threshold=pass_threshold):
        failing = [
            f"{c.reviewer}={c.score:.2f} blockers={c.blockers}"
            for c in cards
            if c.score < pass_threshold or c.blockers
        ]
        return False, "Gate not passed: " + "; ".join(failing)

    # All pass
    return True, "Gate passed"


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

    content = textwrap.dedent(
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
    ).format(
        task_id=task_id,
        timestamp=datetime.now(timezone.utc).isoformat(),
        iter_count=iter_count,
        summary=summarize_cards(cards),
        spec=spec_text,
        files="\n".join(f"- {f}" for f in files) if files else "(none)",
        diff=diff_text or "(no diff)",
        score_cards=summarize_cards(cards),
    )

    report_path.write_text(content)
    return report_path


# ---------------------------------------------------------------------------
# Main inner loop
# ---------------------------------------------------------------------------


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

    Parameters
    ----------
    project_dir
        The project root (where git main branch lives).
    task_id
        Unique task identifier.
    spec_text
        The product specification text (004-spec.md content).
    task_kind
        Task kind (logic / api / ui / infra) determining reviewer组合.
    adapter
        The CLI adapter to use (claude / opencode / codex).
    router
        Model router for resolving stage → ModelSpec.
    config
        Loop configuration (defaults to LoopConfig()).

    Returns
    -------
    list[ScoreCard]
        All score cards produced across all iterations.

    Raises
    ------
    EscalationError
        When MAX_ITER is reached without a gate pass.
    InnerLoopError
        For irrecoverable setup errors (worktree creation, etc.).
    """
    if config is None:
        config = LoopConfig()

    from harness.reviewers import ReviewerAssembly

    assembly = ReviewerAssembly()
    # T13: pass the task's `platform` (web / mobile / miniprogram) so
    # the assembly can add the cross-platform reviewer on top of the
    # kind's default set. `task` is loaded below; for the first call
    # we don't know it yet, so default to web (no extra reviewer).
    platform: Optional[str] = "web"
    queue = read_task_queue(project_dir)
    if queue is None:
        raise InnerLoopError(f"No task queue found in {project_dir}")
    task: Optional[Task] = None
    for t in queue.tasks:
        if t.id == task_id:
            task = t
            break
    if task is None:
        raise InnerLoopError(f"Task {task_id} not found in task queue")
    if task.platform:
        platform = task.platform
    reviewer_names = assembly.get_reviewer_names(task_kind, platform=platform)

    # T18 — mark the task IN_PROGRESS on disk before doing any work.
    # Without this, a crash mid-task leaves the task PENDING while the
    # ``task/{id}`` branch and worktree already exist; ``--continue``
    # then mis-routes the task through the fresh-work path and
    # ``create_worktree`` fails because the branch is taken.
    mark_task_in_progress(project_dir, task_id)
    _log.info(
        "task_started",
        extra={
            "stage": "develop",
            "task_id": task_id,
            "kind": task_kind,
            "platform": platform,
            "max_iterations": config.max_iterations,
        },
    )

    # ---------------------------------------------------------------------------
    # Create worktree for this task
    # ---------------------------------------------------------------------------
    base_branch = config.base_branch or get_current_branch(project_dir)
    try:
        worktree_path = create_worktree(project_dir, task_id, base_branch=base_branch)
    except Exception as exc:
        raise InnerLoopError(f"Failed to create worktree for task {task_id}: {exc}") from exc

    all_cards: list[ScoreCard] = []
    iter_num = 1

    try:
        while iter_num <= config.max_iterations:
            # -------------------------------------------------------------------
            # Step 1: Generator
            # -------------------------------------------------------------------
            # Collect feedback from previous iteration
            prev_blockers: list[str] = []
            prev_suggestions: list[str] = []
            if iter_num > 1:
                # Get the latest iteration's cards for feedback
                latest_cards = [c for c in all_cards if c.iter == iter_num - 1]
                for card in latest_cards:
                    prev_blockers.extend(card.blockers)
                    prev_suggestions.extend(card.suggestions)

            generator_output = run_generator(
                adapter=adapter,
                router=router,
                worktree_path=worktree_path,
                spec_text=spec_text,
                task_id=task_id,
                task_title=task.title,
                task_description=task.description,
                blockers_from_previous=prev_blockers,
                suggestions_from_previous=prev_suggestions,
                iter_num=iter_num,
            )

            # Record generator token usage
            router.record("generate", generator_output.usage.usage)

            # -------------------------------------------------------------------
            # Step 2: Reviewers (parallel)
            # -------------------------------------------------------------------
            diff_text = get_worktree_diff(project_dir, task_id, base_branch=base_branch)
            changed_files = get_worktree_files(project_dir, task_id, base_branch=base_branch)

            # For UI tasks, pre-capture screenshots once per iteration and
            # pass them through to the visual reviewer only. Other reviewers
            # ignore the list.
            screenshots: list[Path] = []
            if task_kind == "ui" and "visual" in reviewer_names:
                screenshots = capture_ui_screenshots(
                    project_dir=project_dir,
                    task_id=task_id,
                    spec_text=spec_text,
                )

            cards, reviewer_usages = run_reviewers_parallel(
                adapter=adapter,
                router=router,
                worktree_path=worktree_path,
                project_dir=project_dir,
                task_id=task_id,
                reviewer_names=reviewer_names,
                agents_dir=assembly._agents_dir,
                spec_text=spec_text,
                diff_text=diff_text,
                changed_files=changed_files,
                iter_num=iter_num,
                screenshots=screenshots,
                acceptance=list(task.acceptance) if task and task.acceptance else None,
            )

            # Record reviewer token usage
            for card, usage in zip(cards, reviewer_usages):
                stage = f"review.{card.reviewer}"
                router.record(stage, usage)

            all_cards.extend(cards)

            # -------------------------------------------------------------------
            # Step 3: Gate check
            # -------------------------------------------------------------------
            passed, reason = check_gate(cards, pass_threshold=config.pass_threshold)
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
                # Gate passed — T18 transaction order:
                # 1. Write COMPLETED to disk FIRST so a crash mid-merge
                #    leaves the task marked done and resume skips it
                #    instead of re-running the iteration.
                # 2. Then merge the worktree branch into the base branch.
                #    A merge conflict surfaces as an escalation; we
                #    intentionally do NOT roll the disk state back to
                #    PENDING (the architect sees the discrepancy in the
                #    escalation report and decides).
                queue = read_task_queue(project_dir)
                if queue:
                    queue = complete_task(queue, task_id)
                    write_task_queue(project_dir, queue)

                try:
                    merge_worktree(project_dir, task_id, base_branch=base_branch)
                except InnerLoopError as exc:
                    # Merge conflict — escalate with the diff between
                    # on-disk state (COMPLETED) and actual repo state
                    # (still on the task branch).
                    _log.error(
                        "merge_failed",
                        extra={
                            "stage": "develop",
                            "task_id": task_id,
                            "iter": iter_num,
                            "error": str(exc),
                        },
                    )
                    write_escalation_report(
                        project_dir, task_id, iter_num, all_cards, spec_text
                    )
                    raise EscalationError(task_id, iter_num, all_cards) from exc

                _log.info(
                    "merge_complete",
                    extra={
                        "stage": "develop",
                        "task_id": task_id,
                        "iter": iter_num,
                    },
                )
                return all_cards

            # -------------------------------------------------------------------
            # Gate not passed — iterate
            # -------------------------------------------------------------------
            iter_num += 1

            if iter_num > config.max_iterations:
                break

    finally:
        # If we exit without a gate pass (escalation), preserve the worktree
        # The escalation report already references the worktree path
        pass

    # MAX_ITER exhausted without gate pass
    write_escalation_report(project_dir, task_id, config.max_iterations, all_cards, spec_text)
    raise EscalationError(task_id, config.max_iterations, all_cards)
