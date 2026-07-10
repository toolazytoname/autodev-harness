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
from harness.preflight import run_preflight
from harness.progress import print_failure_summary
from harness.quota_hold import (
    MAX_AUTO_RESUME,
    QuotaResumeExhaustedError,
    begin_resume,
    cancel_pending_hold,
    enter_quota_hold,
    format_hold_status,
    read_hold,
)
from harness.router import BudgetExceeded


# CLI phase names (bash-compatible) → Phase enum values handled by Phase._missing_
PHASE_CHOICES = ["research", "plan", "ui_design", "tasks", "develop"]

# Exit codes (sysexits.h-style). Distinct codes so cron / CI can tell
# "operator must intervene" apart from "this run failed normally".
EXIT_OK = 0
EXIT_PIPELINE_ERROR = 1
EXIT_QUOTA_ESCALATION = 2  # auto-resume cap hit — manual action required
EXIT_BUDGET_EXCEEDED = 137  # T29 — per-tier token cap hit; operator review needed
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
        "--validate-config", dest="validate_config", action="store_true",
        help="T32: load + validate config/models.yaml (and adapter registry) "
             "and exit. Returns 0 on success, non-zero with a clear error "
             "message on misconfig. Useful as a CI gate.",
    )
    parser.add_argument(
        "--cancel-hold", dest="cancel_hold", action="store_true",
        help="Cancel any pending quota hold + exit (does not run the pipeline)",
    )
    parser.add_argument("--max-iterations", type=int, default=5)
    parser.add_argument(
        "--skip-ui-review", dest="skip_ui_review", action="store_true",
        help="T42: skip the UI design phase entirely. No 4-direction "
             "preview HTML, no human picker. Develop phase will pull the "
             "visual direction from artifacts/preflight-answers.json. "
             "Also auto-enabled when the brief contains keywords like "
             "'POC', '原型', 'UI 不 review', or 'taste 把关'.",
    )
    parser.add_argument(
        "--no-preflight", dest="no_preflight", action="store_true",
        help="T41: skip the pre-flight brief interrogation and use "
             "harness defaults. Useful for repeat runs in the same "
             "project where preflight-answers.json is already filled in.",
    )
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

    # T32: `--validate-config` is the cheap CI gate. Loads the YAML,
    # validates every tier's `adapter` against the central registry,
    # and exits 0/1 with a clear message. Never touches the network
    # or spawns a subprocess.
    if args.validate_config:
        from harness.router import ModelRouter
        try:
            ModelRouter()
        except (FileNotFoundError, ValueError) as exc:
            print(f"❌ Config validation failed: {exc}", file=sys.stderr)
            return EXIT_PIPELINE_ERROR
        print("✅ config/models.yaml is valid (all tier adapters registered).")
        return EXIT_OK

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

    # T42: --skip-ui-review can be set explicitly via flag, OR
    # auto-detected from brief keywords. The auto path matters
    # because the user's exact words ("UI 我不 review 了") are a
    # strong signal that the 4-direction picker would be wasted.
    skip_ui = args.skip_ui_review
    if not skip_ui and brief_words:
        # brief_words only set when this is a new run (not --continue)
        joined_brief = " ".join(brief_words)
        skip_keywords = [
            "POC", "poc", "原型", "prototype", "MVP", "mvp",
            "UI 不 review", "UI 不 review", "taste 把关", "taste 来把关",
            "内部用", "自己用", "自己能跑",
        ]
        if any(k in joined_brief for k in skip_keywords):
            skip_ui = True
            print(
                f"⏭  --skip-ui-review auto-enabled (brief matched: "
                f"{[k for k in skip_keywords if k in joined_brief][0]})"
            )

    config = PipelineConfig(
        project_dir=project_dir,
        mode=mode,
        max_iterations=max_iterations,
        next_resume_count=next_resume_count,
        skip_ui_review=skip_ui,
    )
    pipeline = Pipeline(config, adapter=ClaudeAdapter())

    # T41: grill the user with a fixed set of questions before any
    # model call. Skippable via --no-preflight or via the
    # preflight-answers.json file already existing on a --continue.
    # Status / validate / cancel / config subcommands skip preflight
    # so they remain cheap.
    if not args.no_preflight and not args.status and not args.validate_config \
            and not args.cancel_hold and not brief_words:
        # ``brief_words`` empty means this is a --continue (no new
        # brief text). In that case the preflight file is expected
        # to already exist on disk from the original run.
        answers_path = project_dir / "artifacts" / "preflight-answers.json"
        if not answers_path.exists():
            brief_for_preflight = ""
            bp = get_artifact_path(project_dir, "000-brief")
            if bp.exists():
                brief_for_preflight = bp.read_text()
            run_preflight(project_dir, brief_for_preflight)

    start_phase = Phase(args.phase) if args.phase else None
    # --continue and the default both resume via state detection inside run()

    try:
        pipeline.run(start_phase=start_phase)
    except PipelineError as exc:
        # T40 — surface a clean summary block so the user knows what
        # the harness was doing and where to look next, instead of a
        # bare traceback. The exception is still included in the
        # summary so the original error is preserved.
        print_failure_summary(project_dir, exception=exc)
        return EXIT_PIPELINE_ERROR
    except BudgetExceeded as exc:
        # T29 — per-tier token cap hit. Distinct exit code (137) so
        # cron / CI can tell "budget circuit tripped" apart from a
        # generic pipeline error. Print where the cap tripped so the
        # operator can adjust ``max_tokens`` in config/models.yaml (or
        # the per-tier env override) and re-run.
        print(
            f"🛑 Budget exceeded for tier '{exc.tier}': "
            f"{exc.spent} tokens spent against a cap of {exc.limit}. "
            "Pipeline paused — bump max_tokens in config/models.yaml "
            "(or via AUTODEV_BUDGET_<TIER>) and re-run.",
            file=sys.stderr,
        )
        return EXIT_BUDGET_EXCEEDED
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