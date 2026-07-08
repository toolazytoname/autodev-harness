"""Develop phase orchestration (T36 extract from pipeline).

T24 originally moved this out of :mod:`harness.inner_loop` into
:mod:`harness.pipeline` as ``Pipeline.phase_develop`` plus two
helpers. T36 hoists those three methods into a standalone class
``DevelopPhase`` so the outer Pipeline is purely an orchestrator
that wires phases together.

Backwards-compat: the three methods stay on ``Pipeline`` as thin
delegates (preserved for any test that patches them by name).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from harness.artifacts import (
    TaskQueue,
    TaskStatus,
    read_artifact,
    read_task_queue,
    write_task_queue,
)
from harness.inner_loop import EscalationError, InnerLoopError, LoopConfig
from harness.pipeline import (
    PipelineError,
    _extract_blockers_from_cards,
    _summarize_cards_for_linear,
)
# T36: import the module rather than the function so the
# ``patch("harness.pipeline.run_inner_loop", ...)`` tests still
# see the patched version. Attribute lookup at call time →
# mock-friendly.
import harness.pipeline as _pipeline_mod

if TYPE_CHECKING:
    from harness.linear_sync import LinearSync
    from harness.pipeline import Pipeline


class DevelopPhase:
    """Owns the develop phase: walk the task queue, run inner loop,
    report status to Linear.  Constructed by ``Pipeline.phase_develop``
    and given a reference to the parent pipeline for log/Linear access.
    """

    def __init__(self, pipeline: "Pipeline") -> None:
        self._p = pipeline

    # ------------------------------------------------------------------
    # Public phase entry point
    # ------------------------------------------------------------------

    def run(self) -> None:
        """Drive the develop phase: read 003-task-queue.json, run each
        task through ``run_inner_loop`` until queue is exhausted or all
        remaining tasks are blocked / waiting on blocked deps."""
        self._p._log("━━━ Phase: develop ━━━")
        project_dir = self._p._config.project_dir

        spec_text = read_artifact(project_dir, "006-ui-spec") or ""
        plan_text = read_artifact(project_dir, "002-plan") or ""
        full_spec = f"{plan_text}\n\n{spec_text}".strip()
        if not full_spec:
            raise PipelineError("No plan/spec artifacts found — cannot develop")

        loop_config = LoopConfig(
            max_iterations=self._p._config.max_iterations,
            pass_threshold=self._p._config.pass_threshold,
        )

        while True:
            queue = read_task_queue(project_dir)
            if queue is None:
                raise PipelineError("003-task-queue.json not found — run tasks first")

            task = self._next_runnable_task(queue)
            if task is None:
                break

            self._p._log(f"▶ Task {task.id}: {task.title}")
            self._linear_sync().mark_in_progress(task.id)
            try:
                cards = _pipeline_mod.run_inner_loop(
                    project_dir=project_dir,
                    task_id=task.id,
                    spec_text=full_spec,
                    task_kind=task.kind,
                    adapter=self._p._adapter,
                    router=self._p._router,
                    config=loop_config,
                )
                self._p._log(f"✅ Task {task.id} passed gate and merged")
                self._safe_linear(
                    "mark_done",
                    lambda: self._linear_sync().mark_done(
                        task.id, _summarize_cards_for_linear(cards)
                    ),
                )
            except EscalationError as exc:
                self._p._log(
                    f"🛑 Task {task.id} escalated after {exc.iter_count} iterations"
                )
                self._mark_task_blocked(task.id)
                self._safe_linear(
                    "mark_blocked",
                    lambda: self._linear_sync().mark_blocked(
                        task.id, _extract_blockers_from_cards(exc.cards)
                    ),
                )
            except InnerLoopError as exc:
                self._p._log(f"🛑 Task {task.id} failed: {exc}")
                self._mark_task_blocked(task.id)
                self._safe_linear(
                    "mark_blocked",
                    lambda: self._linear_sync().mark_blocked(
                        task.id, [f"inner loop error: {exc}"]
                    ),
                )

        queue = read_task_queue(project_dir)
        blocked = [
            t.id for t in (queue.tasks if queue else []) if t.status == TaskStatus.BLOCKED
        ]
        if blocked:
            self._p._log(
                f"Develop finished with blocked tasks awaiting arbitration: {blocked}"
            )
        else:
            self._p._log("All tasks completed ✅")

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _next_runnable_task(self, queue) -> Optional[object]:
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
        queue = read_task_queue(self._p._config.project_dir)
        if queue is None:
            return
        new_tasks = [
            t.model_copy(update={"status": TaskStatus.BLOCKED}) if t.id == task_id else t
            for t in queue.tasks
        ]
        write_task_queue(self._p._config.project_dir, TaskQueue(tasks=new_tasks))

    def _linear_sync(self) -> "LinearSync":
        return self._p._linear_sync

    def _safe_linear(self, action_name: str, fn) -> None:
        """T36: collapse the three try/except Linear blocks in the
        original phase_develop. The harness never blocks on a failing
        Linear side-effect — log + continue."""
        try:
            fn()
        except Exception as e:  # defensive
            self._p._log(f"[Linear] {action_name} failed: {e}")
