"""CLI entry point — `python -m harness [OPTIONS] [PROJECT_DIR] -- "描述"`.

Argument semantics mirror the legacy bash entry (autodev-harness.sh):

    python -m harness [--new|--iterate|--test] [--phase X] [-c|--continue]
                      [--max-iterations N] [PROJECT_DIR] [-- BRIEF...]
    python -m harness config     # print routing table
    python -m harness --status [PROJECT_DIR]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


# CLI phase names (bash-compatible) → Phase enum values handled by Phase._missing_
PHASE_CHOICES = ["research", "plan", "ui_design", "tasks", "develop"]


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
    parser.add_argument("--max-iterations", type=int, default=5)
    parser.add_argument(
        "project_dir", nargs="?", default=None,
        help="Project directory (default: cwd). Use 'config' to print the routing table.",
    )
    parser.add_argument(
        "brief", nargs=argparse.REMAINDER,
        help="Project description after `--`",
    )
    return parser


def _print_status(project_dir: Path) -> int:
    from harness.artifacts import read_task_queue, read_workflow_state

    state = read_workflow_state(project_dir)
    if state is None:
        print(f"No workflow state found in {project_dir}")
        return 1
    print(f"📊 Project Status: {project_dir}")
    print(f"  Current phase:     {state.current_phase.value if state.current_phase else '-'}")
    print(f"  Completed phases:  {', '.join(p.value for p in state.completed_phases) or '-'}")
    print(f"  Mode:              {state.mode}")
    queue = read_task_queue(project_dir)
    if queue:
        by_status: dict[str, int] = {}
        for t in queue.tasks:
            by_status[t.status.value] = by_status.get(t.status.value, 0) + 1
        print(f"  Tasks:             {by_status}")
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv

    # Back-compat subcommand: `python -m harness config`
    if argv and argv[0] == "config":
        from harness.router import ModelRouter

        print(ModelRouter().pretty_print())
        return 0

    parser = _build_parser()
    args = parser.parse_args(argv)

    project_dir = Path(args.project_dir) if args.project_dir else Path.cwd()

    if args.status:
        return _print_status(project_dir)

    from harness.adapters.claude import ClaudeAdapter
    from harness.artifacts import Phase, get_artifact_path
    from harness.pipeline import Pipeline, PipelineConfig, PipelineError

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
    )
    pipeline = Pipeline(config, adapter=ClaudeAdapter())

    start_phase = Phase(args.phase) if args.phase else None
    # --continue and the default both resume via state detection inside run()

    try:
        pipeline.run(start_phase=start_phase)
    except PipelineError as exc:
        print(f"Pipeline error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nInterrupted — state saved, resume with -c", file=sys.stderr)
        return 130
    return 0


if __name__ == "__main__":
    sys.exit(main())
