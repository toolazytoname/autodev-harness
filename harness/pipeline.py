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
from typing import TYPE_CHECKING, Callable, Optional

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
from harness.env import EnvVars, api_key_for
from harness.inner_loop import EscalationError, InnerLoopError, LoopConfig, run_inner_loop
from harness.logging_setup import get_logger
from harness.quota_hold import enter_quota_hold  # T16e: wired through Pipeline._run_phase_with_quota_guard
from harness.router import ModelRouter
from harness.score_card import extract_json_from_fenced

_log = get_logger(__name__)

if TYPE_CHECKING:
    from harness.linear_sync import LinearSync

MAX_FEEDBACK_ITERATIONS = 5
PHASE_TIMEOUT_SECONDS = 600


def _summarize_cards_for_linear(cards: list) -> str:
    """Render score cards as a multi-line summary for the Linear comment.

    Format:
        iter=N: correctness=0.90 test=0.85 boundary=0.80
    plus a separate "blockers:" line if any card has blockers.
    """
    if not cards:
        return "(no score cards)"
    # Group by iteration so a multi-iter task shows the final state.
    last_iter = max(c.iter for c in cards)
    latest = [c for c in cards if c.iter == last_iter]
    lines = [f"iter={last_iter}"]
    parts: list[str] = []
    for c in sorted(latest, key=lambda c: c.reviewer):
        parts.append(f"{c.reviewer}={c.score:.2f}")
    lines.append("  " + " ".join(parts))
    blockers = [b for c in latest for b in c.blockers]
    if blockers:
        lines.append("blockers:")
        lines.extend(f"  - {b}" for b in blockers)
    return "\n".join(lines)


def _extract_blockers_from_cards(cards: list) -> list[str]:
    """Collect every blocker from every card into a flat list."""
    out: list[str] = []
    for c in cards:
        for b in c.blockers:
            out.append(f"[{c.reviewer}] {b}")
    return out

# Execution order of the outer pipeline (subset of Phase enum)
PIPELINE_PHASES: list[Phase] = [
    Phase.RESEARCH,
    Phase.PLAN,
    Phase.UI,
    Phase.TASKS,
    Phase.DEVELOP,
]


# T26 — ``PHASE_ARTIFACTS`` / ``PHASE_STAGES`` / ``PHASE_AGENTS`` used to
# be three parallel dicts in this module; adding a phase meant editing
# all three. Consolidate into a single ``PHASE_SPECS`` table keyed by
# ``Phase``. ``DEVELOP`` is not a model-driven phase so it is omitted
# (its "artifact" is the set of commits, not a single markdown file).


@dataclass(frozen=True)
class PhaseSpec:
    """One pipeline phase's metadata.

    Attributes
    ----------
    artifact
        Filename of the artifact this phase produces under
        ``artifacts/`` (no extension). ``DEVELOP`` is ``None`` because
        it commits code rather than emitting a single document.
    stage
        Router stage name used to resolve the model tier for this
        phase. ``DEVELOP`` is ``None`` because it dispatches per-task
        through the inner loop.
    agent
        Markdown prompt file (relative to ``agents/``) that drives the
        phase. ``DEVELOP`` is ``None`` because there is no single
        "develop" prompt.
    """

    artifact: Optional[str]
    stage: Optional[str]
    agent: Optional[str]


PHASE_SPECS: dict[Phase, PhaseSpec] = {
    Phase.RESEARCH: PhaseSpec(artifact="001-research-report", stage="research", agent="researcher"),
    Phase.PLAN: PhaseSpec(artifact="002-plan", stage="plan", agent="planner"),
    Phase.UI: PhaseSpec(artifact="006-ui-spec", stage="ui_design", agent="ui-design"),
    Phase.TASKS: PhaseSpec(artifact="003-task-queue", stage="taskgen", agent="taskgen"),
    Phase.DEVELOP: PhaseSpec(artifact=None, stage=None, agent=None),
}

# Aesthetic directions the ui_design phase generates (T08 step 4).
# Each direction specifies which style module to inject (or "(none)" for
# the baseline-only direction) and a URL-friendly slug for the output dir.
UI_DIRECTIONS: list[dict[str, str]] = [
    {
        "slug": "editorial-minimal",
        "label": "Editorial minimal",
        "module": "minimalist-ui",
    },
    {
        "slug": "high-end-motion",
        "label": "High-end motion",
        "module": "gpt-taste",
    },
    {
        "slug": "data-dense-industrial",
        "label": "Data-dense industrial",
        "module": "industrial-brutalist-ui",
    },
    {
        "slug": "premium-default",
        "label": "Premium default (baseline only)",
        "module": "(none)",
    },
]

# ``pick_directions_for_brief`` and ``extract_ui_output`` moved to
# harness.ui_phase (T24). Re-exported below — safe at module level
# because the cycle was broken by moving PipelineError / _is_interactive
# to harness.pipeline_base.
from harness.ui_phase import (  # noqa: E402,F401  (T24 re-export)
    extract_ui_output,
    pick_directions_for_brief,
)
# T24 — PipelineError and _is_interactive moved to pipeline_base so
# harness.ui_phase can import them without creating a circular import
# with harness.pipeline.
from harness.pipeline_base import PipelineError, _is_interactive  # noqa: E402,F401


@dataclass
class PipelineConfig:
    """Configuration for a pipeline run."""

    project_dir: Path
    mode: str = "new"  # new | iterate | test
    max_iterations: int = 5
    pass_threshold: float = 0.8
    # T16e: populated by `begin_resume()` in __main__ before pipeline.run()
    # so a re-entrant quota-hold can carry the incremented resume_count.
    next_resume_count: int = 0
    # Injected for testability; defaults are created lazily in Pipeline
    log: Callable[[str], None] = print


def _read_agent_prompt(agents_dir: Path, agent_name: str) -> str:
    """Load an agent's markdown prompt, failing clearly when missing."""
    path = agents_dir / f"{agent_name}.md"
    if not path.exists():
        raise PipelineError(f"Agent prompt not found: {path}")
    return path.read_text()


def _read_bundle_skill(bundle_path: Path, *relative_parts: str) -> str:
    """Load one skill from skills-bundle; raises PipelineError if missing."""
    path = bundle_path.joinpath(*relative_parts, "SKILL.md")
    if not path.exists():
        raise PipelineError(f"Bundled skill missing: {path}")
    return path.read_text()


def _build_prompt(agent_prompt: str, input_text: str) -> str:
    """Append input context to an agent prompt, matching the bash convention."""
    return f"{agent_prompt}\n\n---INPUT---\n{input_text}\n"


def _build_ui_prompt(
    base_prompt: str,
    plan_text: str,
    direction: dict[str, str],
    three_piece_text: str,
    style_module_text: str,
) -> str:
    """Assemble a per-direction ui_design prompt.

    The base prompt lives in agents/ui-design.md and tells the model how
    to respond (markers, structure, rules). The directional context
    (PLAN + DIRECTION + STYLE MODULE + 3-PIECE BASELINE) is appended in
    the order ui-design.md expects in its 'Input' section.
    """
    module_block = (
        "---STYLE MODULE PROMPT---\n(none — use only the three-piece baseline)"
        if direction["module"] == "(none)"
        else f"---STYLE MODULE PROMPT---\n{style_module_text}"
    )
    context = (
        f"---PLAN---\n{plan_text}\n\n"
        f"---AESTHETIC DIRECTION---\n{direction['slug']}\n\n"
        f"{module_block}\n\n"
        f"---THREE-PIECE BASELINE---\n{three_piece_text}\n"
    )
    return _build_prompt(base_prompt, context)


# ``extract_ui_output`` moved to harness.ui_phase (T24); re-exported above.


class Pipeline:
    """Five-phase outer pipeline with breakpoint resume."""

    def __init__(
        self,
        config: PipelineConfig,
        adapter: AdapterBase,
        router: Optional[ModelRouter] = None,
        agents_dir: Optional[Path] = None,
        skills_bundle_dir: Optional[Path] = None,
        linear_sync: Optional["LinearSync"] = None,
    ) -> None:
        self._config = config
        self._adapter = adapter
        self._router = router or ModelRouter()
        repo_root = Path(__file__).parent.parent
        self._agents_dir = agents_dir or repo_root / "agents"
        self._skills_bundle_dir = skills_bundle_dir or repo_root / "skills-bundle"
        # Linear sync: defaults to a LocalLinearClient (in-memory, no
        # network) when not provided. The pipeline never blocks on a
        # missing Linear backend.
        if linear_sync is None:
            from harness.linear_sync import LinearSync, get_linear_client

            self._linear_sync = LinearSync(
                client=get_linear_client(),
                project_dir=config.project_dir,
            )
        else:
            self._linear_sync = linear_sync
        self._log = config.log
        # T23 — instance-level set of env-var names that this run has
        # already consumed. Replaces the old ``os.environ[env_var] = ""``
        # pattern, which mutated process-global state and leaked across
        # tests / Pipeline instances. Per-instance ⇒ two Pipelines in
        # the same process never see each other's consumption.
        self._consumed_feedback: set[str] = set()

    # ------------------------------------------------------------------
    # Phase primitives
    # ------------------------------------------------------------------

    def _load_three_piece_baseline(self) -> str:
        """Concatenate the three SKILL.md files that form the anti-slop baseline."""
        parts = []
        for name in ("design-taste-frontend", "high-end-visual-design", "frontend-design"):
            parts.append(_read_bundle_skill(self._skills_bundle_dir, "3-piece", name))
        return "\n\n---\n\n".join(parts)

    def _load_style_module(self, module_name: str) -> str:
        """Load one style module; empty string when the direction uses none."""
        if module_name == "(none)":
            return ""
        return _read_bundle_skill(self._skills_bundle_dir, "styles", module_name)

    def _api_key_for(self, tier: str) -> Optional[str]:
        """Resolve the per-tier API key from the environment.

        T19 — different backends (Anthropic, MiniMax, …) issue their own
        keys; piping the wrong one to a worker call leaks the credential
        or hits the wrong account. We only read the env (never mutate it),
        and return ``None`` when nothing is configured so the subprocess
        inherits the parent process's default key.
        """
        return os.environ.get(api_key_for(tier))

    def _call_agent(self, phase: Phase, input_text: str) -> AgentResult:
        """Run the agent for a phase through the router-selected model."""
        phase_spec = PHASE_SPECS[phase]
        # DEVELOP is dispatched per-task through the inner loop; no
        # model-driven call exists for it here.
        if phase_spec.stage is None or phase_spec.agent is None:
            raise PipelineError(
                f"Phase '{phase.name}' is not a model-driven phase and "
                "has no agent prompt to call"
            )
        stage = phase_spec.stage
        spec = self._router.resolve(stage)
        agent_prompt = _read_agent_prompt(self._agents_dir, phase_spec.agent)
        prompt = _build_prompt(agent_prompt, input_text)

        result = self._adapter.run(
            prompt,
            model=spec.model,
            cwd=self._config.project_dir,
            timeout=PHASE_TIMEOUT_SECONDS,
            base_url=spec.base_url,
            api_key=self._api_key_for(spec.tier),
            fallback_model=spec.fallback,
        )
        self._router.record(stage, result.usage)
        return result

    def _call_ui_direction(
        self,
        direction: dict[str, str],
        plan_text: str,
        previous_spec: str = "",
        user_feedback: str = "",
    ) -> AgentResult:
        """Run the ui_design agent for one specific aesthetic direction."""
        ui_spec = PHASE_SPECS[Phase.UI]
        if ui_spec.stage is None or ui_spec.agent is None:
            raise PipelineError("UI phase spec is missing stage/agent metadata")
        stage = ui_spec.stage
        spec = self._router.resolve(stage)
        agent_prompt = _read_agent_prompt(self._agents_dir, ui_spec.agent)
        three_piece = self._load_three_piece_baseline()
        style_module = self._load_style_module(direction["module"])

        context_extra = ""
        if previous_spec:
            context_extra += f"\n\n---PREVIOUS SPEC---\n{previous_spec}"
        if user_feedback:
            context_extra += f"\n\n---USER FEEDBACK---\n{user_feedback}"

        prompt = _build_ui_prompt(
            base_prompt=agent_prompt,
            plan_text=plan_text + context_extra,
            direction=direction,
            three_piece_text=three_piece,
            style_module_text=style_module,
        )

        result = self._adapter.run(
            prompt,
            model=spec.model,
            cwd=self._config.project_dir,
            timeout=PHASE_TIMEOUT_SECONDS,
            base_url=spec.base_url,
            api_key=self._api_key_for(spec.tier),
            fallback_model=spec.fallback,
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

        Consumption is tracked on the Pipeline instance via
        ``_consumed_feedback`` (T23) — the env var itself is never
        mutated, so two Pipelines in the same process don't see each
        other's "consumed" state and tests can't leak into each other.
        """
        env_value = os.environ.get(env_var, "")
        if not _is_interactive():
            if env_value and env_var not in self._consumed_feedback:
                self._consumed_feedback.add(env_var)
                return env_value
            return ""
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

        # Per MASTER-PLAN P4 / TASKS T10: a research report without a
        # reuse decision table is not allowed to advance into the plan
        # phase. Refuse explicitly with a one-line diagnostic so the
        # researcher (or a human) can fix it without re-running the
        # whole pipeline.
        from harness.research_validation import validate_research_report

        validation = validate_research_report(result.stdout)
        if not validation.is_valid:
            raise PipelineError(
                f"research report rejected by reuse-table gate: {validation.error}"
            )
        if validation.table is not None:
            self._log(
                f"Reuse decision table: {len(validation.table.decisions)} decision(s) parsed"
            )
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
                "修改意见（或直接回车接受当前计划）: ", EnvVars.PLAN_FEEDBACK
            )
            if not feedback:
                return path

            context = (
                f"{research}\n\n---PREVIOUS PLAN---\n{result.stdout}"
                f"\n\n---USER FEEDBACK---\n{feedback}"
            )

        self._log(f"Max feedback iterations ({MAX_FEEDBACK_ITERATIONS}) reached, using current plan")
        return get_artifact_path(self._config.project_dir, "002-plan")

    def _call_ui_direction(
        self,
        direction: dict[str, str],
        plan_text: str,
        previous_spec: str = "",
        user_feedback: str = "",
    ) -> AgentResult:
        """T24 — thin delegate. Implementation lives in UIPhase.

        Kept on ``Pipeline`` so the public surface of the phase_ui
        helper stays intact for any caller that imports it from
        ``harness.pipeline``. The body delegates to a freshly
        constructed ``UIPhase`` instance, which owns the prompt
        assembly + the slop check / version-choice prompts.
        """
        from harness.ui_phase import UIPhase  # local import avoids cycle

        return UIPhase(self)._call_ui_direction(
            direction,
            plan_text,
            previous_spec=previous_spec,
            user_feedback=user_feedback,
        )

    def _run_slop_check(self, versions):
        """T24 — thin delegate. Implementation lives in UIPhase."""
        from harness.ui_phase import UIPhase  # local import avoids cycle

        return UIPhase(self)._run_slop_check(versions)

    def _ask_version_choice(self, num_versions: int) -> tuple[str, str]:
        """T24 — thin delegate. Implementation lives in UIPhase.

        Kept on ``Pipeline`` for the T23 no-mutation probes in
        ``tests/test_t23_no_environ_mutation.py`` that call this
        method directly on a Pipeline instance to assert the
        consumed-feedback set lives on the Pipeline.
        """
        from harness.ui_phase import UIPhase  # local import avoids cycle

        return UIPhase(self)._ask_version_choice(num_versions)

    def phase_ui(self) -> Path:
        """Run the ui_design phase (T24 — delegated to UIPhase).

        The render / refine / finalize / human-pick loop, the
        per-direction call, the slop check, and the version-choice
        prompt all live in ``harness.ui_phase.UIPhase``. ``phase_ui``
        is a thin adapter that loads the plan and forwards to it.
        """
        from harness.ui_phase import UIPhase  # T24 — local import to dodge cycle

        plan_text = read_artifact(self._config.project_dir, "002-plan")
        if plan_text is None:
            raise PipelineError("002-plan.md not found — run plan first")
        return UIPhase(self).run(plan_text)

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

        # Mirror tasks to Linear (or local fallback). Failures here
        # must NOT block the pipeline — Linear is a best-effort
        # progress surface, not a source of truth.
        try:
            brief = read_artifact(self._config.project_dir, "000-brief") or ""
            self._linear_sync.sync_tasks_phase(
                brief=brief,
                tasks=[t.model_dump(mode="json") for t in queue.tasks],
            )
            self._linear_sync.print_progress_link()
        except Exception as e:  # defensive
            self._log(f"[Linear] sync_tasks_phase failed: {e}")
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
            # Mirror the start to Linear (no-op for unknown keys).
            self._linear_sync.mark_in_progress(task.id)
            try:
                cards = run_inner_loop(
                    project_dir=project_dir,
                    task_id=task.id,
                    spec_text=full_spec,
                    task_kind=task.kind,
                    adapter=self._adapter,
                    router=self._router,
                    config=loop_config,
                )
                self._log(f"✅ Task {task.id} passed gate and merged")
                # Gate pass → DONE with score card summary in the comment.
                try:
                    summary = _summarize_cards_for_linear(cards)
                    self._linear_sync.mark_done(task.id, summary)
                except Exception as e:
                    self._log(f"[Linear] mark_done failed: {e}")
            except EscalationError as exc:
                self._log(f"🛑 Task {task.id} escalated after {exc.iter_count} iterations")
                self._mark_task_blocked(task.id)
                # Escalation → BLOCKED with the blockers in the comment.
                try:
                    blockers = _extract_blockers_from_cards(exc.cards)
                    self._linear_sync.mark_blocked(task.id, blockers)
                except Exception as e:
                    self._log(f"[Linear] mark_blocked failed: {e}")
            except InnerLoopError as exc:
                self._log(f"🛑 Task {task.id} failed: {exc}")
                self._mark_task_blocked(task.id)
                try:
                    self._linear_sync.mark_blocked(
                        task.id, [f"inner loop error: {exc}"]
                    )
                except Exception as e:
                    self._log(f"[Linear] mark_blocked failed: {e}")

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
            mode_str = (
                self._config.mode.value
                if hasattr(self._config.mode, "value")
                else str(self._config.mode)
            )
            _log.info(
                "phase_started",
                extra={"stage": phase.value, "mode": mode_str},
            )
            try:
                self._run_phase_with_quota_guard(phase, runners[phase])
            except Exception as exc:
                _log.exception(
                    "phase_failed",
                    extra={
                        "stage": phase.value,
                        "mode": mode_str,
                        "error": str(exc),
                    },
                )
                raise
            completed = completed + [phase]
            self._save_state(phase, completed)
            _log.info("phase_complete", extra={"stage": phase.value})

        self._log("Pipeline complete ✅")

    def _run_phase_with_quota_guard(
        self,
        phase: "Phase",
        runner: Callable[[], object],
    ) -> None:
        """Run a single phase; on ``QuotaExhaustedError`` write a hold + re-raise.

        T16e — the hold is the single source of truth for what is
        waiting, so we persist it here (where we know the phase /
        current task) before propagating to the CLI layer, which
        then decides what to print and what exit code to return.
        """
        from harness.adapters.base import QuotaExhaustedError

        try:
            runner()
        except QuotaExhaustedError as exc:
            task_id = self._current_task_id()
            hold_path = enter_quota_hold(
                self._config.project_dir,
                exc,
                resume_count=self._config.next_resume_count,
                phase=phase.value,
                task_id=task_id,
            )
            _log.warning(
                "quota_exhausted_suspended",
                extra={
                    "stage": phase.value,
                    "task_id": task_id,
                    "hold_path": str(hold_path),
                    "tier": getattr(exc, "tier", None),
                    "provider": getattr(exc, "provider", None),
                },
            )
            # Re-raise so __main__ can produce the user-facing message
            # and pick the right exit code.
            raise

    def _current_task_id(self) -> Optional[str]:
        """Return the in-progress task id, if any (used to enrich quota-hold).

        T16e — when a phase suspends on quota, we want the hold to record
        which task was being worked so a human (or the next auto-resume)
        can pick up exactly where we left off. Read-only — never mutates
        the queue.
        """
        from harness.artifacts import TaskStatus, read_task_queue

        queue = read_task_queue(self._config.project_dir)
        if queue is None:
            return None
        for t in queue.tasks:
            if t.status == TaskStatus.IN_PROGRESS:
                return t.id
        return None

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
            artifact = PHASE_SPECS[phase].artifact
            if artifact is None:
                return phase  # develop
            if not get_artifact_path(self._config.project_dir, artifact).exists():
                return phase
        return Phase.DEVELOP
