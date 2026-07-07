"""Reviewer runner + gate check, extracted from inner_loop.

T24 — splitting inner_loop.py (was 1061 lines) so reviewers can be
exercised in isolation. Three responsibilities live here:

  1. ``run_single_reviewer``  — run one reviewer prompt + parse score
  2. ``run_reviewers_parallel`` — fan out across reviewers in a thread pool
  3. ``check_gate``           — aggregate cards into a pass/fail decision

The visual reviewer is a special case: it bypasses the prompt-only
path and calls ``harness.visual_reviewer.run_visual_review`` for the
multimodal flow. Screenshot capture (``capture_ui_screenshots``) also
lives here because it is co-located with the visual reviewer's
plumbing.
"""

from __future__ import annotations

import os
import textwrap
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Optional

from harness.adapters.base import AdapterBase, AdapterError, Usage
from harness.artifacts import ensure_dir
from harness.router import ModelRouter
from harness.score_card import (
    ScoreCard,
    gate_passed,
    parse_score_card,
    save_score_card,
)


# ---------------------------------------------------------------------------
# Named constants (T26 — replace bare magic numbers / literals)
# ---------------------------------------------------------------------------

# Default dev-server URL the visual reviewer targets when no override is
# supplied via AUTODEV_VISUAL_BASE_URL. Hoisted to a named constant so
# the port (``8765``) is searchable and configurable from one place.
DEFAULT_VISUAL_BASE_URL: str = "http://127.0.0.1:8765"
AUTODEV_VISUAL_BASE_URL_ENV: str = "AUTODEV_VISUAL_BASE_URL"


# 3-minute per-reviewer ceiling. Reviewer prompts are prompt-only
# (no file I/O, no dev server), so a healthy reviewer finishes in
# under a minute; 3 min gives us a generous buffer for slow networks
# while still surfacing a real hang before the orchestrator-level
# budget fires.
REVIEWER_TIMEOUT_SECONDS = 180


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
) -> tuple[ScoreCard, Usage]:
    """Run one reviewer and return (card, usage).

    The ``visual`` reviewer name routes to the multimodal path; all
    other reviewers follow the prompt → adapter → parse-score-card
    pipeline. We never raise from a reviewer — a crash becomes a
    0.0-score card with the exception in ``blockers``.
    """
    if reviewer_name == "visual":
        return _run_visual_reviewer(
            adapter=adapter, router=router,
            worktree_path=worktree_path, project_dir=project_dir,
            task_id=task_id, spec_text=spec_text,
            diff_text=diff_text, changed_files=changed_files,
            iter_num=iter_num, screenshots=screenshots or [],
            prompt_path=prompt_path,
        )
    prompt = _read_and_build_prompt(
        prompt_path, task_id=task_id, iter_num=iter_num,
        worktree_path=worktree_path, changed_files=changed_files,
        diff_text=diff_text, spec_text=spec_text, acceptance=acceptance,
    )
    raw_output, usage = _invoke_reviewer(adapter, router, prompt, worktree_path, iter_num, reviewer_name)
    if raw_output is None:
        return usage  # error card path
    card = _parse_or_error_card(raw_output=raw_output, iter_num=iter_num, reviewer_name=reviewer_name)
    save_score_card(project_dir, task_id, card)
    return card, usage


def _read_and_build_prompt(
    prompt_path: Path,
    *,
    task_id: str,
    iter_num: int,
    worktree_path: Path,
    changed_files: list[str],
    diff_text: str,
    spec_text: str,
    acceptance: Optional[list[str]],
) -> str:
    """Read the reviewer's prompt template from disk and inject context."""
    return _build_reviewer_prompt(
        prompt_template=prompt_path.read_text(),
        task_id=task_id, iter_num=iter_num,
        worktree_path=worktree_path, changed_files=changed_files,
        diff_text=diff_text, spec_text=spec_text, acceptance=acceptance,
    )


def _invoke_reviewer(
    adapter: AdapterBase,
    router: ModelRouter,
    prompt: str,
    worktree_path: Path,
    iter_num: int,
    reviewer_name: str,
) -> tuple[Optional[str], object]:
    """Call the adapter for one reviewer; return (raw_output, usage).

    On adapter failure, returns ``(None, error_card)`` so the
    caller can short-circuit. The error card has score 0.0 and the
    exception in ``blockers``. We never raise from a reviewer
    failure — that would tank the parallel batch and leave other
    reviewers' results stranded.
    """
    from harness.reviewer_runner import REVIEWER_TIMEOUT_SECONDS

    spec = router.resolve(f"review.{reviewer_name}")
    try:
        # T19 — propagate the resolved spec's base_url/api_key/fallback
        # so reviewer calls ride the third-party chain correctly.
        review_api_key = os.environ.get(f"AUTODEV_API_KEY_{spec.tier.upper()}")
        result = adapter.run(
            prompt,
            model=spec.model,
            cwd=worktree_path,
            timeout=REVIEWER_TIMEOUT_SECONDS,
            base_url=spec.base_url,
            api_key=review_api_key,
            fallback_model=spec.fallback,
        )
        return result.stdout, result.usage
    except Exception as exc:
        error_card = ScoreCard(
            iter=iter_num,
            reviewer=reviewer_name,
            score=0.0,
            blockers=[f"Reviewer crashed: {exc}"],
            suggestions=[],
            evidence=f"Exception: {exc}",
        )
        return None, (error_card, Usage())


_REVIEWER_PROMPT_TEMPLATE = textwrap.dedent(
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
)


def _build_reviewer_prompt(
    prompt_template: str,
    task_id: str,
    iter_num: int,
    worktree_path: Path,
    changed_files: list[str],
    diff_text: str,
    spec_text: str,
    acceptance: Optional[list[str]],
) -> str:
    """Assemble the reviewer prompt with all context blocks.

    Extracted as a pure function so prompt content can be asserted
    in unit tests without running the whole reviewer. The template
    body lives in ``_REVIEWER_PROMPT_TEMPLATE`` (T24) so this
    function stays under 50 lines.
    """
    acceptance_block = _format_acceptance_block(acceptance) if acceptance else ""
    return _REVIEWER_PROMPT_TEMPLATE.format(
        prompt_template=prompt_template,
        task_id=task_id, iter_num=iter_num,
        worktree_path=str(worktree_path),
        changed_files=_format_changed_files(changed_files),
        diff=diff_text or "(no diff yet — this is the first iteration)",
        spec=spec_text, acceptance_block=acceptance_block,
    )


def _format_acceptance_block(acceptance: list[str]) -> str:
    """Render the acceptance-criteria block injected into the reviewer prompt."""
    numbered = "\n".join(f"{i+1}. {step}" for i, step in enumerate(acceptance))
    return (
        "\n## Task Acceptance Criteria (from taskgen)\n"
        "The author of this task committed to these acceptance steps.\n"
        "For each step, decide if the diff/spec proves it's met.\n"
        f"{numbered}\n"
    )


def _format_changed_files(changed_files: list[str]) -> str:
    """Render the changed-files list for the reviewer prompt."""
    return "\n".join(f"- {f}" for f in changed_files) if changed_files else "(no files changed yet)"


def _parse_or_error_card(
    raw_output: str, iter_num: int, reviewer_name: str
) -> ScoreCard:
    """Parse the score card JSON, returning an error card on failure.

    Tries the raw output first; on failure strips fenced JSON and
    retries. After both attempts fail, returns a 0.0-score card with
    the failure as a blocker — never raises, so a single bad reviewer
    cannot tank the whole parallel batch.
    """
    try:
        card = parse_score_card(raw_output)
        return ScoreCard(
            iter=iter_num,
            reviewer=reviewer_name,
            score=card.score,
            blockers=card.blockers,
            suggestions=card.suggestions,
            evidence=card.evidence,
        )
    except Exception:
        from harness.score_card import extract_json_from_fenced  # noqa: PLC0415

        cleaned = extract_json_from_fenced(raw_output)
        try:
            card = parse_score_card(cleaned)
            return ScoreCard(
                iter=iter_num,
                reviewer=reviewer_name,
                score=card.score,
                blockers=card.blockers,
                suggestions=card.suggestions,
                evidence=card.evidence,
            )
        except Exception as inner_exc:
            return ScoreCard(
                iter=iter_num,
                reviewer=reviewer_name,
                score=0.0,
                blockers=[f"Failed to parse score card: {inner_exc}"],
                suggestions=[],
                evidence=raw_output[:500],
            )


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
) -> tuple[ScoreCard, Usage]:
    """Dispatch path for the multimodal visual reviewer.

    For UI tasks the inner loop pre-captures screenshots once per
    iteration into ``score-cards/task-{id}/screenshots/``; this helper
    receives the already-captured paths, hands them to
    ``harness.visual_reviewer.run_visual_review``, and persists the
    resulting score card like every other reviewer.
    """
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
    from harness.visual_reviewer import (  # noqa: PLC0415
        capture_with_fallback,
        extract_pages_from_spec,
        screenshots_dir_for,
    )

    base_url = base_url or os.environ.get(
        AUTODEV_VISUAL_BASE_URL_ENV, DEFAULT_VISUAL_BASE_URL
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
) -> tuple[list[ScoreCard], list[Usage]]:
    """Run all reviewers in parallel via ThreadPoolExecutor.

    Each reviewer runs in its own thread with its own adapter call;
    a reviewer timeout does not affect the others. Returns
    ``(cards, usages)`` — order is not guaranteed.

    ``screenshots`` is passed through to the visual reviewer only;
    other reviewers ignore it. ``acceptance`` is forwarded to every
    reviewer (the test reviewer converts it into commands, others
    use it as a checklist).
    """
    cards: list[ScoreCard] = []
    usages: list[Usage] = []
    lock = threading.Lock()

    # T26 — fail fast on an empty reviewer list instead of silently
    # passing through ThreadPoolExecutor with max_workers=1 and zero
    # actual review work. The legacy behaviour would let a
    # misconfigured task kind sneak through every gate and burn an
    # iteration without any quality check.
    if not reviewer_names:
        raise AdapterError(
            "run_reviewers_parallel called with no reviewers — "
            "check ReviewerAssembly.get_reviewer_names() for this "
            "task kind / platform"
        )

    def _record(card: ScoreCard, usage: Usage) -> None:
        with lock:
            cards.append(card)
            usages.append(usage)

    def _invoke(name: str, prompt_path: Path) -> tuple[ScoreCard, Usage]:
        return run_single_reviewer(
            adapter=adapter, router=router,
            worktree_path=worktree_path, project_dir=project_dir,
            task_id=task_id, reviewer_name=name, prompt_path=prompt_path,
            spec_text=spec_text, diff_text=diff_text,
            changed_files=changed_files, iter_num=iter_num,
            screenshots=screenshots, acceptance=acceptance,
        )

    _fan_out_reviewers(
        reviewer_names=reviewer_names,
        agents_dir=agents_dir,
        iter_num=iter_num,
        project_dir=project_dir,
        task_id=task_id,
        invoke=_invoke,
        record=_record,
    )
    return cards, usages


def _fan_out_reviewers(
    *,
    reviewer_names: list[str],
    agents_dir: Path,
    iter_num: int,
    project_dir: Path,
    task_id: str,
    invoke,
    record,
) -> None:
    """Run each reviewer in a thread + record results.

    Extracted from ``run_reviewers_parallel`` so the public
    function stays under 50 lines. Mutates the caller's ``cards``
    / ``usages`` lists via ``record``; the caller is responsible
    for owning those lists and returning them.
    """
    with ThreadPoolExecutor(max_workers=max(1, len(reviewer_names))) as executor:
        futures = {
            executor.submit(_run_one, invoke, record, name, agents_dir / f"{name}.md"): name
            for name in reviewer_names
        }
        for future in as_completed(futures):
            name = futures[future]
            try:
                future.result()
            except Exception as exc:
                # ``invoke`` (run_single_reviewer) catches
                # exceptions and returns an error card, so this
                # branch is defense in depth.
                error_card = ScoreCard(
                    iter=iter_num, reviewer=name, score=0.0,
                    blockers=[f"Unexpected reviewer error: {exc}"],
                    suggestions=[], evidence="",
                )
                record(error_card, Usage())
                save_score_card(project_dir, task_id, error_card)


def _run_one(invoke, record, name: str, prompt_path: Path) -> tuple[ScoreCard, Usage]:
    """Per-reviewer worker: invoke the reviewer, record its result."""
    card, usage = invoke(name, prompt_path)
    record(card, usage)
    return card, usage


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
