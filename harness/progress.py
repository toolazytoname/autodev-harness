"""Stream-friendly progress + failure summary (T40).

The previous UX problem: when a phase hung on the upstream proxy, the
user saw nothing for 10+ minutes and had to keep asking "进展顺利不？".
This module adds two cheap, dependency-free helpers that fix the two
parts of that pain:

- ``log_attempt(phase, attempt, total, target=None)`` prints a single
  one-liner to stdout *before* each model call. The user always knows
  whether the harness is alive, which phase is running, and which
  attempt it is on.

- ``print_failure_summary(project_dir, last_errors=None)`` prints a
  concise block to stdout (not stderr — it is the headline, not a
  side-channel) when the pipeline bails. The block points the user at
  the files they need: brief, task queue, workflow state. No new
  artifact is created — everything it references already exists.

Both helpers are intentionally side-effect-light so they are safe to
call from any layer (outer pipeline, inner generator, reviewer runner).
"""

from __future__ import annotations

import datetime
import sys
import traceback
from pathlib import Path
from typing import Optional, Sequence


def _now_tag() -> str:
    """Return ``[HH:MM:SS]`` for stdout-line prefixes."""
    return datetime.datetime.now().strftime("[%H:%M:%S]")


def log_attempt(
    phase: str,
    attempt: int,
    total: int,
    target: Optional[str] = None,
    extra: Optional[str] = None,
) -> None:
    """Emit one line to stdout: ``[HH:MM:SS] phase=X attempt N/M target=...``.

    Cheap, no-op if the line is empty, and tolerates any input. The
    ``target`` field is the file or task id the agent is about to act
    on (e.g. ``src/core/excelReader.ts`` or ``T-001``). ``extra`` is a
    free-form tail (e.g. ``reason=reviewer-mismatch``) used by callers
    that need a hint beyond the default fields.
    """
    parts = [
        _now_tag(),
        f"phase={phase}",
        f"attempt={attempt}/{total}",
    ]
    if target:
        parts.append(f"target={target}")
    if extra:
        parts.append(extra)
    line = " ".join(parts)
    print(line, flush=True)


def print_failure_summary(
    project_dir: Path,
    last_errors: Optional[Sequence[str]] = None,
    exception: Optional[BaseException] = None,
) -> None:
    """Print a single block summarizing why the pipeline bailed.

    Designed to be called from ``__main__.py`` in the catch-all
    branches (PipelineError / BudgetExceeded). The output is plain
    text, human-first, and points the user at the artefacts they
    already have on disk — no new file is created.
    """
    sep = "=" * 60
    print(sep)
    print("⚠️  Harness 在某个阶段卡住了，没法继续")
    print("-" * 60)
    print(f"项目目录: {project_dir}")

    brief = project_dir / "artifacts" / "000-brief.md"
    tasks = project_dir / "artifacts" / "003-task-queue.json"
    state = project_dir / "artifacts" / "workflow-state.json"
    print()
    print("你需要看的东西:")
    print(f"  • brief:        {brief}{'  ✓ 存在' if brief.exists() else '  ✗ 不存在'}")
    print(f"  • 任务清单:     {tasks}{'  ✓ 存在' if tasks.exists() else '  ✗ 不存在'}")
    print(f"  • 进度状态:     {state}{'  ✓ 存在' if state.exists() else '  ✗ 不存在'}")

    errs = list(last_errors or [])
    if exception is not None:
        # Last line of the traceback is the most informative; full
        # trace is recoverable from the harness log.
        tb = traceback.format_exception_only(type(exception), exception)
        errs.append("".join(tb).strip())
    if errs:
        print()
        print("最后几条错误（最新在最后）:")
        for line in errs[-5:]:
            # Strip very long single lines; the harness log has the
            # full stack. Keep first 200 chars.
            short = line.strip()
            if len(short) > 200:
                short = short[:197] + "..."
            print(f"  • {short}")

    print()
    print("接下来你可以:")
    print("  • 自己接着干: cd 进项目，照着 003-task-queue.json 写")
    print("  • 等代理恢复重跑: python -m harness --continue " + str(project_dir))
    print("  • 调高 timeout 再跑: AUTODEV_PHASE_TIMEOUT=300 python -m harness ...")
    print(sep)
