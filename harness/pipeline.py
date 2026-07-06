"""Outer pipeline — five-phase orchestration (research → plan → ui → tasks → develop).

Per MASTER-PLAN §2 and T07: the phases previously implemented in bash
(autodev-harness.sh) now live here, wired to ModelRouter + CLI adapters +
the artifacts module.

Human feedback loops (plan / ui phases) read from stdin when a TTY is
attached; in non-interactive runs they auto-approve (or read the
AUTODEV_PLAN_FEEDBACK / AUTODEV_UI_CHOICE environment variables).
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from harness.adapters.base import AdapterBase, AgentResult
from harness.artifacts import (
    Phase,
    Task,
    TaskQueue,
    TaskStatus,
    WorkflowState,
    get_artifact_path,
    read_artifact,
    read_task_queue,
    read_workflow_state,
    write_artifact,
    write_task_queue,
    write_workflow_state,
)
from harness.inner_loop import EscalationError, InnerLoopError, LoopConfig, run_inner_loop
from harness.router import ModelRouter
from harness.score_card import extract_json_from_fenced

MAX_FEEDBACK_ITERATIONS = 5
PHASE_TIMEOUT_SECONDS = 600

# Execution order of the outer pipeline (subset of Phase enum)
PIPELINE_PHASES: list[Phase] = [
    Phase.RESEARCH,
    Phase.PLAN,
    Phase.UI,
    Phase.TASKS,
    Phase.DEVELOP,
]

# Artifact name each phase produces (develop produces commits, not an artifact)
PHASE_ARTIFACTS: dict[Phase, str] = {
    Phase.RESEARCH: "001-research-report",
    Phase.PLAN: "002-plan",
    Phase.UI: "006-ui-spec",
    Phase.TASKS: "003-task-queue",
}

# Router stage name per phase
PHASE_STAGES: dict[Phase, str] = {
    Phase.RESEARCH: "research",
    Phase.PLAN: "plan",
    Phase.UI: "ui_design",
    Phase.TASKS: "taskgen",
}

# Agent prompt file per phase (relative to agents/)
PHASE_AGENTS: dict[Phase, str] = {
    Phase.RESEARCH: "researcher",
    Phase.PLAN: "planner",
    Phase.UI: "ui-design",
    Phase.TASKS: "taskgen",
}


class PipelineError(Exception):
    """Irrecoverable pipeline failure."""


@dataclass
class PipelineConfig:
    """Configuration for a pipeline run."""

    project_dir: Path
    mode: str = "new"  # new | iterate | test
    max_iterations: int = 5
    pass_threshold: float = 0.8
    # Injected for testability; defaults are created lazily in Pipeline
    log: Callable[[str], None] = print


def _is_interactive() -> bool:
    """True when a human can answer prompts on stdin."""
    return sys.stdin.isatty()


def _read_agent_prompt(agents_dir: Path, agent_name: str) -> str:
    """Load an agent's markdown prompt, failing clearly when missing."""
    path = agents_dir / f"{agent_name}.md"
    if not path.exists():
        raise PipelineError(f"Agent prompt not found: {path}")
    return path.read_text()


def _build_prompt(agent_prompt: str, input_text: str) -> str:
    """Append input context to an agent prompt, matching the bash convention."""
    return f"{agent_prompt}\n\n---INPUT---\n{input_text}\n"


def extract_ui_output(raw: str) -> tuple[str, str]:
    """Split ui-design agent output into (spec_markdown, html).

    Supports the ---SPEC--- / ---HTML--- / ---END--- marker convention and
    falls back to ```html fences (same logic as the bash extract_html).
    Returns ("", raw) when no HTML section can be identified — the caller
    decides whether that is acceptable.
    """
    lines = raw.splitlines()

    def _find(marker: str) -> Optional[int]:
        for i, line in enumerate(lines):
            if line.strip() == marker:
                return i
        return None

    spec_i = _find("---SPEC---")
    html_i = _find("---HTML---")
    end_i = _find("---END---")

    if html_i is not None:
        spec = "\n".join(lines[spec_i + 1 : html_i]) if spec_i is not None else ""
        html_end = end_i if end_i is not None and end_i > html_i else len(lines)
        html = "\n".join(lines[html_i + 1 : html_end])
        return spec.strip(), html.strip()

    # Fallback: fenced html block
    fence_start = None
    for i, line in enumerate(lines):
        if line.strip().startswith("```html"):
            fence_start = i
            break
    if fence_start is not None:
        for j in range(fence_start + 1, len(lines)):
            if lines[j].strip() == "```":
                spec = "\n".join(lines[:fence_start]).strip()
                html = "\n".join(lines[fence_start + 1 : j]).strip()
                return spec, html

    return "", raw.strip()


class Pipeline:
    """Five-phase outer pipeline with breakpoint resume."""

    def __init__(
        self,
        config: PipelineConfig,
        adapter: AdapterBase,
        router: Optional[ModelRouter] = None,
        agents_dir: Optional[Path] = None,
    ) -> None:
        self._config = config
        self._adapter = adapter
        self._router = router or ModelRouter()
        if agents_dir is None:
            agents_dir = Path(__file__).parent.parent / "agents"
        self._agents_dir = agents_dir
        self._log = config.log

    # ------------------------------------------------------------------
    # Phase primitives
    # ------------------------------------------------------------------

    def _call_agent(self, phase: Phase, input_text: str) -> AgentResult:
        """Run the agent for a phase through the router-selected model."""
        stage = PHASE_STAGES[phase]
        spec = self._router.resolve(stage)
        agent_prompt = _read_agent_prompt(self._agents_dir, PHASE_AGENTS[phase])
        prompt = _build_prompt(agent_prompt, input_text)

        result = self._adapter.run(
            prompt,
            model=spec.model,
            cwd=self._config.project_dir,
            timeout=PHASE_TIMEOUT_SECONDS,
        )
        self._router.record(stage, result.usage)
        return result

    def _save_state(self, current: Phase, completed: list[Phase]) -> None:
        state = WorkflowState(
            project_dir=self._config.project_dir,
            current_phase=current,
            completed_phases=completed,
            mode=self._config.mode,
            max_iterations=self._config.max_iterations,
            pass_threshold=self._config.pass_threshold,
        )
        write_workflow_state(self._config.project_dir, state)

    # ------------------------------------------------------------------
    # Human feedback helpers
    # ------------------------------------------------------------------

    def _ask_feedback(self, question: str, env_var: str) -> str:
        """Ask the human for feedback; auto-approve when non-interactive.

        Returns the feedback string; empty string means "accepted".
        Non-TTY runs read the environment variable once, then approve.
        """
        env_value = os.environ.get(env_var, "")
        if not _is_interactive():
            if env_value:
                # Consume the env feedback exactly once per run
                os.environ[env_var] = ""
            return env_value
        try:
            return input(question).strip()
        except EOFError:
            return ""

    # ------------------------------------------------------------------
    # Phases
    # ------------------------------------------------------------------

    def phase_research(self) -> Path:
        self._log("━━━ Phase: research ━━━")
        brief = read_artifact(self._config.project_dir, "000-brief")
        if brief is None:
            raise PipelineError("000-brief.md not found — provide a brief first")

        result = self._call_agent(Phase.RESEARCH, brief)
        path = write_artifact(self._config.project_dir, "001-research-report", result.stdout)
        self._log(f"Research report saved: {path}")
        return path

    def phase_plan(self) -> Path:
        self._log("━━━ Phase: plan ━━━")
        research = read_artifact(self._config.project_dir, "001-research-report")
        if research is None:
            raise PipelineError("001-research-report.md not found — run research first")

        context = research
        for iteration in range(1, MAX_FEEDBACK_ITERATIONS + 1):
            self._log(f"Plan iteration {iteration}")
            result = self._call_agent(Phase.PLAN, context)
            path = write_artifact(self._config.project_dir, "002-plan", result.stdout)
            self._log(f"Plan saved: {path}")

            feedback = self._ask_feedback(
                "修改意见（或直接回车接受当前计划）: ", "AUTODEV_PLAN_FEEDBACK"
            )
            if not feedback:
                return path

            context = (
                f"{research}\n\n---PREVIOUS PLAN---\n{result.stdout}"
                f"\n\n---USER FEEDBACK---\n{feedback}"
            )

        self._log(f"Max feedback iterations ({MAX_FEEDBACK_ITERATIONS}) reached, using current plan")
        return get_artifact_path(self._config.project_dir, "002-plan")

    def phase_ui(self) -> Path:
        self._log("━━━ Phase: ui_design ━━━")
        plan = read_artifact(self._config.project_dir, "002-plan")
        if plan is None:
            raise PipelineError("002-plan.md not found — run plan first")

        preview_dir = self._config.project_dir / "preview"
        preview_dir.mkdir(parents=True, exist_ok=True)

        context = plan
        for iteration in range(1, MAX_FEEDBACK_ITERATIONS + 1):
            self._log(f"UI design iteration {iteration}")
            result = self._call_agent(Phase.UI, context)
            spec_md, html = extract_ui_output(result.stdout)

            html_path = preview_dir / "index.html"
            html_path.write_text(html)
            spec_path = write_artifact(
                self._config.project_dir, "006-ui-spec", spec_md or result.stdout
            )
            self._log(f"UI spec saved: {spec_path}")
            self._log(f"Preview: file://{html_path}")

            feedback = self._ask_feedback(
                "修改意见（或直接回车接受当前设计）: ", "AUTODEV_UI_FEEDBACK"
            )
            if not feedback:
                return spec_path

            context = f"{plan}\n\n---PREVIOUS SPEC---\n{spec_md}\n\n---USER FEEDBACK---\n{feedback}"

        self._log(f"Max feedback iterations ({MAX_FEEDBACK_ITERATIONS}) reached, using current design")
        return get_artifact_path(self._config.project_dir, "006-ui-spec")

    def phase_tasks(self) -> Path:
        self._log("━━━ Phase: tasks ━━━")
        plan = read_artifact(self._config.project_dir, "002-plan")
        if plan is None:
            raise PipelineError("002-plan.md not found — run plan first")

        result = self._call_agent(Phase.TASKS, plan)

        # Validate the JSON through the TaskQueue schema before persisting
        cleaned = extract_json_from_fenced(result.stdout)
        try:
            queue = TaskQueue.from_json(json.loads(cleaned))
        except Exception as exc:
            raise PipelineError(f"taskgen produced invalid task queue JSON: {exc}") from exc

        path = write_task_queue(self._config.project_dir, queue)
        self._log(f"Task queue saved: {path} ({len(queue.tasks)} tasks)")
        return path

    def phase_develop(self) -> None:
        self._log("━━━ Phase: develop ━━━")
        project_dir = self._config.project_dir

        spec_text = read_artifact(project_dir, "006-ui-spec") or ""
        plan_text = read_artifact(project_dir, "002-plan") or ""
        full_spec = f"{plan_text}\n\n{spec_text}".strip()
        if not full_spec:
            raise PipelineError("No plan/spec artifacts found — cannot develop")

        loop_config = LoopConfig(
            max_iterations=self._config.max_iterations,
            pass_threshold=self._config.pass_threshold,
        )

        while True:
            queue = read_task_queue(project_dir)
            if queue is None:
                raise PipelineError("003-task-queue.json not found — run tasks first")

            task = self._next_runnable_task(queue)
            if task is None:
                break

            self._log(f"▶ Task {task.id}: {task.title}")
            try:
                run_inner_loop(
                    project_dir=project_dir,
                    task_id=task.id,
                    spec_text=full_spec,
                    task_kind=task.kind,
                    adapter=self._adapter,
                    router=self._router,
                    config=loop_config,
                )
                self._log(f"✅ Task {task.id} passed gate and merged")
            except EscalationError as exc:
                self._log(f"🛑 Task {task.id} escalated after {exc.iter_count} iterations")
                self._mark_task_blocked(task.id)
            except InnerLoopError as exc:
                self._log(f"🛑 Task {task.id} failed: {exc}")
                self._mark_task_blocked(task.id)

        queue = read_task_queue(project_dir)
        blocked = [t.id for t in (queue.tasks if queue else []) if t.status == TaskStatus.BLOCKED]
        if blocked:
            self._log(f"Develop finished with blocked tasks awaiting arbitration: {blocked}")
        else:
            self._log("All tasks completed ✅")

    def _next_runnable_task(self, queue) -> Optional[Task]:
        """First pending task whose dependencies are completed and not blocked."""
        completed = {t.id for t in queue.tasks if t.status == TaskStatus.COMPLETED}
        blocked = {t.id for t in queue.tasks if t.status == TaskStatus.BLOCKED}
        for task in queue.tasks:
            if task.status != TaskStatus.PENDING:
                continue
            deps = task.dependencies or []
            if any(d in blocked for d in deps):
                continue  # dependent on a blocked task — skip
            if all(d in completed for d in deps):
                return task
        return None

    def _mark_task_blocked(self, task_id: str) -> None:
        queue = read_task_queue(self._config.project_dir)
        if queue is None:
            return
        new_tasks = [
            t.model_copy(update={"status": TaskStatus.BLOCKED}) if t.id == task_id else t
            for t in queue.tasks
        ]
        write_task_queue(self._config.project_dir, TaskQueue(tasks=new_tasks))

    # ------------------------------------------------------------------
    # Orchestration
    # ------------------------------------------------------------------

    def run(self, start_phase: Optional[Phase] = None) -> None:
        """Run all phases from ``start_phase`` (default: resume or start fresh)."""
        if start_phase is None:
            start_phase = self._detect_start_phase()

        start_idx = PIPELINE_PHASES.index(start_phase)
        completed: list[Phase] = list(PIPELINE_PHASES[:start_idx])

        runners: dict[Phase, Callable[[], object]] = {
            Phase.RESEARCH: self.phase_research,
            Phase.PLAN: self.phase_plan,
            Phase.UI: self.phase_ui,
            Phase.TASKS: self.phase_tasks,
            Phase.DEVELOP: self.phase_develop,
        }

        for phase in PIPELINE_PHASES[start_idx:]:
            self._save_state(phase, completed)
            runners[phase]()
            completed = completed + [phase]
            self._save_state(phase, completed)

        self._log("Pipeline complete ✅")

    def _detect_start_phase(self) -> Phase:
        """Resume from saved state, or from the first phase missing its artifact."""
        state = read_workflow_state(self._config.project_dir)
        if state and state.current_phase in PIPELINE_PHASES:
            done = set(state.completed_phases)
            if state.current_phase not in done:
                return state.current_phase
            # current_phase already completed — advance to the next one
            idx = PIPELINE_PHASES.index(state.current_phase)
            if idx + 1 < len(PIPELINE_PHASES):
                return PIPELINE_PHASES[idx + 1]
            return Phase.DEVELOP

        for phase in PIPELINE_PHASES:
            artifact = PHASE_ARTIFACTS.get(phase)
            if artifact is None:
                return phase  # develop
            if not get_artifact_path(self._config.project_dir, artifact).exists():
                return phase
        return Phase.DEVELOP
