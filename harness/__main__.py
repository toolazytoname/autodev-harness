"""CLI entry point — `python -m harness [OPTIONS] [PROJECT_DIR] -- "描述"`.

Argument semantics mirror the legacy bash entry (autodev-harness.sh):

    python -m harness [--new|--iterate|--test] [--phase X] [-c|--continue]
                      [--max-iterations N] [--cancel-hold] [PROJECT_DIR]
                      [-- BRIEF...]
    python -m harness config           # print routing table
    python -m harness quota-status     # show pending quota-hold
    python -m harness --status [DIR]   # show project + quota status
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Top-level imports so tests can ``patch("harness.__main__.Pipeline")`` etc.
# without having to know the lazy-import dance that used to live here.
from harness.adapters.base import QuotaExhaustedError
from harness.adapters.claude import ClaudeAdapter
from harness.artifacts import Phase, get_artifact_path
from harness.pipeline import Pipeline, PipelineConfig, PipelineError
from harness.quota_hold import (
    MAX_AUTO_RESUME,
    QuotaResumeExhaustedError,
    begin_resume,
    cancel_pending_hold,
    enter_quota_hold,
    format_hold_status,
    read_hold,
)


# CLI phase names (bash-compatible) → Phase enum values handled by Phase._missing_
PHASE_CHOICES = ["research", "plan", "ui_design", "tasks", "develop"]

# Exit codes (sysexits.h-style). Distinct codes so cron / CI can tell
# "operator must intervene" apart from "this run failed normally".
EXIT_OK = 0
EXIT_PIPELINE_ERROR = 1
EXIT_QUOTA_ESCALATION = 2  # auto-resume cap hit — manual action required
EXIT_INTERRUPTED = 130


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="harness",
        description="AutoDevHarness v2 — AI development pipeline",
    )
    parser.add_argument("--new", action="store_true", help="New project mode (default)")
    parser.add_argument("--iterate", action="store_true", help="Iterate on existing project")
    parser.add_argument("--test", action="store_true", help="Test mode (quick validation)")
    parser.add_argument(
        "-c", "--continue", dest="resume", action="store_true",
        help="Continue from last checkpoint",
    )
    parser.add_argument(
        "--phase", choices=PHASE_CHOICES, help="Jump to a specific phase"
    )
    parser.add_argument("--status", action="store_true", help="Show project status")
    parser.add_argument(
        "--cancel-hold", dest="cancel_hold", action="store_true",
        help="Cancel any pending quota hold + exit (does not run the pipeline)",
    )
    parser.add_argument("--max-iterations", type=int, default=5)
    parser.add_argument(
        "project_dir", nargs="?", default=None,
        help="Project directory (default: cwd). Use 'config' / 'quota-status' "
             "to print the routing table or quota-hold status.",
    )
    parser.add_argument(
        "brief", nargs=argparse.REMAINDER,
        help="Project description after `--`",
    )
    return parser


def _print_status(project_dir: Path) -> int:
    from harness.artifacts import read_task_queue, read_workflow_state
    from harness.quota_hold import format_hold_status, read_hold

    hold = read_hold(project_dir)
    state = read_workflow_state(project_dir)

    if state is None and hold is None:
        print(f"No workflow state or quota hold found in {project_dir}")
        return EXIT_PIPELINE_ERROR

    print(f"📊 Project Status: {project_dir}")
    if state is not None:
        print(f"  Current phase:     {state.current_phase.value if state.current_phase else '-'}")
        print(f"  Completed phases:  {', '.join(p.value for p in state.completed_phases) or '-'}")
        print(f"  Mode:              {state.mode}")
        queue = read_task_queue(project_dir)
        if queue:
            by_status: dict[str, int] = {}
            for t in queue.tasks:
                by_status[t.status.value] = by_status.get(t.status.value, 0) + 1
            print(f"  Tasks:             {by_status}")
    else:
        print("  (no workflow state)")

    if hold is not None:
        print()
        print(format_hold_status(hold))
    return EXIT_OK


def _print_quota_status(project_dir: Path) -> int:
    from harness.quota_hold import format_hold_status, read_hold

    hold = read_hold(project_dir)
    if hold is None:
        print(f"No quota hold present in {project_dir}")
        return EXIT_PIPELINE_ERROR
    print(format_hold_status(hold))
    return EXIT_OK


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv

    # Back-compat subcommand: `python -m harness config`
    if argv and argv[0] == "config":
        from harness.router import ModelRouter

        print(ModelRouter().pretty_print())
        return EXIT_OK

    # Subcommand: `python -m harness quota-status [DIR]`
    if argv and argv[0] == "quota-status":
        sub_dir = Path(argv[1]) if len(argv) > 1 and argv[1] else Path.cwd()
        return _print_quota_status(sub_dir)

    parser = _build_parser()
    args = parser.parse_args(argv)

    project_dir = Path(args.project_dir) if args.project_dir else Path.cwd()

    if args.status:
        return _print_status(project_dir)

    # `--cancel-hold` short-circuits the pipeline: cancel the OS wake-up
    # and clear the on-disk hold, then exit. No brief, no ClaudeAdapter,
    # no side effects beyond the cancellation itself.
    if args.cancel_hold:
        cleared = cancel_pending_hold(project_dir)
        if cleared:
            print(f"🟢 Cancelled quota hold in {project_dir}")
        else:
            print(f"(no quota hold to cancel in {project_dir})")
        return EXIT_OK

    # T16e: enforce the auto-resume cap before we touch any LLM. A
    # `--continue` that would loop past MAX_AUTO_RESUME must escalate,
    # not silently burn another wake-up cycle.
    next_resume_count = 0
    if args.resume:
        try:
            next_resume_count = begin_resume(project_dir, max_auto_resume=MAX_AUTO_RESUME)
        except QuotaResumeExhaustedError as exc:
            hold = read_hold(project_dir)
            print(
                f"⛔️  Auto-resume cap hit ({MAX_AUTO_RESUME}). Quota has not "
                f"recovered after {MAX_AUTO_RESUME} retries.",
                file=sys.stderr,
            )
            if hold is not None:
                print(format_hold_status(hold), file=sys.stderr)
            print(
                "Manual action required: wait for quota reset, "
                "or run `python -m harness --cancel-hold "
                f"{project_dir}` to discard the hold.",
                file=sys.stderr,
            )
            return EXIT_QUOTA_ESCALATION

    mode = "test" if args.test else "iterate" if args.iterate else "new"
    max_iterations = 3 if args.test else args.max_iterations

    project_dir.mkdir(parents=True, exist_ok=True)

    # Brief from CLI (after `--`), matching bash create_brief_from_args
    brief_words = [w for w in args.brief if w != "--"]
    brief_path = get_artifact_path(project_dir, "000-brief")
    if brief_words and not brief_path.exists():
        brief_path.write_text(f"# 项目需求\n\n{' '.join(brief_words)}\n")
        print(f"Brief created: {brief_path}")

    config = PipelineConfig(
        project_dir=project_dir,
        mode=mode,
        max_iterations=max_iterations,
        next_resume_count=next_resume_count,
    )
    pipeline = Pipeline(config, adapter=ClaudeAdapter())

    start_phase = Phase(args.phase) if args.phase else None
    # --continue and the default both resume via state detection inside run()

    try:
        pipeline.run(start_phase=start_phase)
    except PipelineError as exc:
        print(f"Pipeline error: {exc}", file=sys.stderr)
        return EXIT_PIPELINE_ERROR
    except QuotaResumeExhaustedError as exc:
        # begin_resume() should have caught this already; this branch is a
        # safety net for any future caller that bypasses __main__.
        print(f"⛔️  Auto-resume cap hit: {exc}", file=sys.stderr)
        return EXIT_QUOTA_ESCALATION
    except QuotaExhaustedError as exc:
        # The pipeline already persisted the hold and registered an OS
        # wake-up. Tell the user clearly where things stand instead of
        # printing a stack trace.
        hold = read_hold(project_dir)
        print(
            f"🟡 Quota exhausted ({getattr(exc, 'tier', '?')} on "
            f"{getattr(exc, 'provider', '?')}). Suspending — the pipeline "
            f"will auto-resume when the quota resets.",
            file=sys.stderr,
        )
        if hold is not None:
            print(format_hold_status(hold), file=sys.stderr)
            print(
                f"To inspect:  python -m harness quota-status {project_dir}",
                file=sys.stderr,
            )
            print(
                f"To cancel:   python -m harness --cancel-hold {project_dir}",
                file=sys.stderr,
            )
        return EXIT_PIPELINE_ERROR
    except KeyboardInterrupt:
        print("\nInterrupted — state saved, resume with -c", file=sys.stderr)
        return EXIT_INTERRUPTED
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())