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

# Brief-keyword → direction-slug picker. First match wins; if no keyword
# matches, fall back to premium-default. The human can override via the
# AUTODEV_UI_DIRECTION env var (a single slug) at any time.
_DIRECTION_KEYWORDS: list[tuple[str, str]] = [
    (r"dashboard|metric|chart|log|admin|observab|trading|inventory",
     "data-dense-industrial"),
    (r"landing|launch|portfolio|marketing|hero|homepage|brand",
     "high-end-motion"),
    (r"docs?|wiki|blog|linear[-\s]?like|notion[-\s]?like|note|writing",
     "editorial-minimal"),
]
import re as _re_module  # local alias; re is stdlib so this is free
_DIRECTION_KEYWORD_PATTERNS = [
    (_re_module.compile(pattern, _re_module.IGNORECASE), slug)
    for pattern, slug in _DIRECTION_KEYWORDS
]


def pick_directions_for_brief(plan_text: str) -> list[dict[str, str]]:
    """Choose which set of 4 aesthetic directions to render this pass.

    Always returns all four. The first slot is the *recommended* one
    (based on brief keywords); the remaining three rotate in a fixed
    order so the human can compare. An explicit
    ``AUTODEV_UI_DIRECTION`` env var forces the recommended slot to a
    specific slug instead.
    """
    explicit = os.environ.get("AUTODEV_UI_DIRECTION", "").strip()
    recommended_slug = next(
        (d["slug"] for d in UI_DIRECTIONS if d["slug"] == explicit),
        None,
    )
    if recommended_slug is None:
        for pattern, slug in _DIRECTION_KEYWORD_PATTERNS:
            if pattern.search(plan_text):
                recommended_slug = slug
                break
    if recommended_slug is None:
        recommended_slug = "premium-default"

    by_slug = {d["slug"]: d for d in UI_DIRECTIONS}
    ordered: list[dict[str, str]] = [by_slug[recommended_slug]]
    for d in UI_DIRECTIONS:
        if d["slug"] != recommended_slug:
            ordered.append(d)
    return ordered


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


def extract_ui_output(raw: str) -> tuple[str, str]:
    """Split ui-design agent output into (spec_markdown, html).

    Supports the ---SPEC--- / ---HTML--- / ---END--- marker convention and
    falls back to ```html fences (same logic as the bash extract_html).
    Returns ("", raw) when no HTML section can be identified — the caller
    decides whether that is acceptable.
    """
    text = raw.strip()
    if not text:
        return "", ""

    lines = text.splitlines()

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

    return "", text


class Pipeline:
    """Five-phase outer pipeline with breakpoint resume."""

    def __init__(
        self,
        config: PipelineConfig,
        adapter: AdapterBase,
        router: Optional[ModelRouter] = None,
        agents_dir: Optional[Path] = None,
        skills_bundle_dir: Optional[Path] = None,
    ) -> None:
        self._config = config
        self._adapter = adapter
        self._router = router or ModelRouter()
        repo_root = Path(__file__).parent.parent
        self._agents_dir = agents_dir or repo_root / "agents"
        self._skills_bundle_dir = skills_bundle_dir or repo_root / "skills-bundle"
        self._log = config.log

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

    def _call_ui_direction(
        self,
        direction: dict[str, str],
        plan_text: str,
        previous_spec: str = "",
        user_feedback: str = "",
    ) -> AgentResult:
        """Run the ui_design agent for one specific aesthetic direction."""
        stage = PHASE_STAGES[Phase.UI]
        spec = self._router.resolve(stage)
        agent_prompt = _read_agent_prompt(self._agents_dir, PHASE_AGENTS[Phase.UI])
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
        self._log("━━━ Phase: ui_design (4 aesthetic directions) ━━━")
        plan_text = read_artifact(self._config.project_dir, "002-plan")
        if plan_text is None:
            raise PipelineError("002-plan.md not found — run plan first")

        preview_dir = self._config.project_dir / "preview"
        versions_dir = preview_dir / "versions"
        versions_dir.mkdir(parents=True, exist_ok=True)

        ordered = pick_directions_for_brief(plan_text)
        self._log(f"Directions (recommended first): {[d['slug'] for d in ordered]}")

        # --- Iter 1: render all 4 directions ------------------------------
        versions = self._render_all_directions(
            ordered, plan_text, previous_spec="", user_feedback=""
        )
        # Automatic slop check on whatever the model shipped — surfaces
        # blockers visually but does not block the pipeline; that is the
        # visual reviewer's job (T09). We just print so the human sees it.
        self._run_slop_check(versions)

        # --- Human pick loop ---------------------------------------------
        for iteration in range(1, MAX_FEEDBACK_ITERATIONS + 1):
            self._log("━ UI versions ━")
            for idx, (direction, spec_md, html) in enumerate(versions, start=1):
                path = versions_dir / direction["slug"] / "index.html"
                self._log(f"  [{idx}] {direction['label']}  →  file://{path}")

            choice, feedback = self._ask_version_choice(len(versions))
            if choice == "accept_first":
                winner = versions[0]
                return self._finalize_version(winner, versions_dir)
            if choice.isdigit():
                idx = int(choice) - 1
                if not (0 <= idx < len(versions)):
                    feedback = choice  # treat as textual feedback
                else:
                    versions[idx] = self._refine_version(
                        versions[idx],
                        plan_text,
                        previous_spec=versions[idx][1],
                        user_feedback=feedback,
                    )
                    continue

            # Free-form feedback → regenerate all 4 with the feedback appended
            versions = self._render_all_directions(
                ordered,
                plan_text,
                previous_spec=versions[0][1],
                user_feedback=feedback,
            )

        self._log(
            f"Max feedback iterations ({MAX_FEEDBACK_ITERATIONS}) reached, "
            "falling back to recommended direction"
        )
        return self._finalize_version(versions[0], versions_dir)

    def _render_all_directions(
        self,
        directions: list[dict[str, str]],
        plan_text: str,
        previous_spec: str,
        user_feedback: str,
    ) -> list[tuple[dict[str, str], str, str]]:
        """Render every aesthetic direction in ``directions`` and persist them.

        Returns one tuple ``(direction, spec_md, html)`` per direction, in
        the same order. Each direction's spec and html are written to
        ``preview/versions/{slug}/`` regardless of whether the parse
        succeeds — failures still produce a dir + placeholder so the
        human sees "this direction failed" rather than "missing file".
        """
        rendered: list[tuple[dict[str, str], str, str]] = []
        for direction in directions:
            self._log(f"  rendering direction: {direction['slug']}")
            try:
                result = self._call_ui_direction(
                    direction,
                    plan_text,
                    previous_spec=previous_spec,
                    user_feedback=user_feedback,
                )
                spec_md, html = extract_ui_output(result.stdout)
            except PipelineError as exc:
                self._log(f"    direction {direction['slug']} failed: {exc}")
                spec_md, html = "", ""

            versions_dir = self._config.project_dir / "preview" / "versions"
            dir_path = versions_dir / direction["slug"]
            dir_path.mkdir(parents=True, exist_ok=True)
            (dir_path / "index.html").write_text(html or "<!DOCTYPE html><!-- empty -->\n")
            (dir_path / "spec.md").write_text(spec_md or "")
            rendered.append((direction, spec_md, html))
        return rendered

    def _refine_version(
        self,
        version: tuple[dict[str, str], str, str],
        plan_text: str,
        previous_spec: str,
        user_feedback: str,
    ) -> tuple[dict[str, str], str, str]:
        """Re-run one direction with feedback (no other directions affected)."""
        direction = version[0]
        result = self._call_ui_direction(
            direction,
            plan_text,
            previous_spec=previous_spec,
            user_feedback=user_feedback,
        )
        spec_md, html = extract_ui_output(result.stdout)
        versions_dir = self._config.project_dir / "preview" / "versions"
        dir_path = versions_dir / direction["slug"]
        dir_path.mkdir(parents=True, exist_ok=True)
        (dir_path / "index.html").write_text(html)
        (dir_path / "spec.md").write_text(spec_md)
        self._log(f"  regenerated: {direction['slug']}")
        return (direction, spec_md, html)

    def _finalize_version(
        self,
        winner: tuple[dict[str, str], str, str],
        versions_dir: Path,
    ) -> Path:
        """Copy the chosen version's spec+html into the canonical artifacts."""
        direction, spec_md, html = winner
        canonical_html = self._config.project_dir / "preview" / "index.html"
        canonical_html.parent.mkdir(parents=True, exist_ok=True)
        canonical_html.write_text(html)
        spec_path = write_artifact(
            self._config.project_dir, "006-ui-spec", spec_md
        )
        self._log(f"Picked {direction['label']} → {spec_path}")
        return spec_path

    def _run_slop_check(self, versions):
        """Print the slop check report for every rendered direction.

        Non-blocking: warnings/blockers are logged so the human sees the
        diagnostics, but we still let the pipeline proceed — T09
        ``visual`` reviewer will block in the inner loop if needed.
        """
        from harness.slop_check import SlopValidator, load_rules

        # config/ is at the repo root, not under the project dir
        repo_root = Path(__file__).parent.parent
        rules_path = repo_root / "config" / "slop_rules.yaml"
        validator = (
            SlopValidator(rules=load_rules(rules_path))
            if rules_path.exists()
            else SlopValidator()
        )
        versions_dir = self._config.project_dir / "preview" / "versions"
        for direction, _spec, _html in versions:
            self._log(f"  slop check: {direction['slug']}")
            for artifact_name in ("index.html", "spec.md"):
                artifact = versions_dir / direction["slug"] / artifact_name
                if not artifact.exists():
                    continue
                result = validator.validate_file(artifact)
                for line in result.render().splitlines():
                    self._log(f"    {line}")
                if not result.passed:
                    self._log(
                        f"    → {direction['slug']}/{artifact_name} has {len(result.blockers)} "
                        "slop blocker(s); T09 visual reviewer will gate."
                    )

    def _ask_version_choice(self, num_versions: int) -> tuple[str, str]:
        """Prompt the human for a version choice.

        Returns ``(choice, feedback)``. ``choice`` is one of:
          - ``"accept_first"`` — accept whichever is at position 1
          - ``"1"`` / ``"2"`` / ... — pick that version (feedback ignored)
          - any other string — treat as free-form feedback text
        In non-TTY runs reads ``AUTODEV_UI_CHOICE`` (1-4) or
        ``AUTODEV_UI_FEEDBACK`` (free-form text).
        """
        env_choice = os.environ.get("AUTODEV_UI_CHOICE", "").strip()
        env_feedback = os.environ.get("AUTODEV_UI_FEEDBACK", "")

        if not _is_interactive():
            if env_choice:
                os.environ["AUTODEV_UI_CHOICE"] = ""
                return env_choice, ""
            if env_feedback:
                os.environ["AUTODEV_UI_FEEDBACK"] = ""
                return "", env_feedback
            # No env set — auto-accept the recommended slot
            return "accept_first", ""

        prompt = (
            f"Choose 1-{num_versions}, type feedback to regenerate all, "
            "or press Enter to accept #1: "
        )
        try:
            raw = input(prompt).strip()
        except EOFError:
            return "accept_first", ""
        if not raw:
            return "accept_first", ""
        if raw in {str(i) for i in range(1, num_versions + 1)}:
            return raw, ""
        return "", raw

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
