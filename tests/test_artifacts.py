"""Tests for harness.artifacts module."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import pydantic
import pytest

from harness.artifacts import (
    ARTIFACT_EXTENSIONS,
    ARTIFACT_NAMES,
    Phase,
    Task,
    TaskQueue,
    TaskStatus,
    WorkflowState,
    ArtifactFiles,
    artifact_exists,
    complete_task,
    get_artifact_path,
    get_next_task,
    get_resume_phase,
    is_phase_complete,
    read_artifact,
    read_task_queue,
    read_workflow_state,
    resolve_artifact,
    write_artifact,
    write_task_queue,
    write_workflow_state,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def tmp_project(tmp_path):
    """A temporary project directory."""
    return tmp_path


@pytest.fixture
def bash_state_file(tmp_path):
    """A state file written by the original bash script (for backward compat)."""
    state = {
        "projectDir": str(tmp_path),
        "currentPhase": "research",
        "previousPhase": "brief",
        "completedPhases": "brief,research",
        "mode": "default",
        "maxIterations": 5,
        "passThreshold": 0.8,
        "iterationCount": 2,
        "lastError": "some error",
        "updatedAt": "2025-01-01T00:00:00Z",
        "files": {
            "brief": str(tmp_path / "000-brief.md"),
            "research": str(tmp_path / "001-research-report.md"),
            "plan": "",
            "tasks": "",
            "spec": "",
            "rubric": "",
        },
    }
    path = tmp_path / "workflow-state.json"
    path.write_text(json.dumps(state, indent=2) + "\n")
    return path


# ---------------------------------------------------------------------------
# Artifact paths
# ---------------------------------------------------------------------------


class TestArtifactPaths:
    def test_get_artifact_path_md(self, tmp_project):
        assert get_artifact_path(tmp_project, "000-brief") == tmp_project / "000-brief.md"
        assert get_artifact_path(tmp_project, "001-research-report") == tmp_project / "001-research-report.md"
        assert get_artifact_path(tmp_project, "002-plan") == tmp_project / "002-plan.md"

    def test_get_artifact_path_json(self, tmp_project):
        assert get_artifact_path(tmp_project, "003-task-queue") == tmp_project / "003-task-queue.json"

    def test_artifact_exists_false_when_missing(self, tmp_project):
        assert artifact_exists(tmp_project, "000-brief") is False

    def test_artifact_exists_true_when_present(self, tmp_project):
        (tmp_project / "000-brief.md").write_text("# Brief")
        assert artifact_exists(tmp_project, "000-brief") is True


# ---------------------------------------------------------------------------
# Artifact read/write
# ---------------------------------------------------------------------------


class TestArtifactReadWrite:
    def test_write_then_read_artifact(self, tmp_project):
        path = write_artifact(tmp_project, "000-brief", "# Hello World")
        assert path == tmp_project / "000-brief.md"
        assert read_artifact(tmp_project, "000-brief") == "# Hello World"

    def test_read_artifact_missing_returns_none(self, tmp_project):
        assert read_artifact(tmp_project, "000-brief") is None

    def test_write_artifact_creates_parent_dirs(self, tmp_project):
        sub = tmp_project / "subdir"
        write_artifact(tmp_project, "000-brief", "content")
        assert (tmp_project / "000-brief.md").exists()

    def test_resolve_artifact_returns_path_when_exists(self, tmp_project):
        (tmp_project / "000-brief.md").write_text("brief")
        result = resolve_artifact(tmp_project, Phase.BRIEF)
        assert result == tmp_project / "000-brief.md"

    def test_resolve_artifact_returns_none_when_missing(self, tmp_project):
        result = resolve_artifact(tmp_project, Phase.BRIEF)
        assert result is None


# ---------------------------------------------------------------------------
# WorkflowState model
# ---------------------------------------------------------------------------


class TestWorkflowState:
    def test_workflow_state_basic(self, tmp_project):
        state = WorkflowState(
            project_dir=tmp_project,
            current_phase=Phase.BRIEF,
            completed_phases=[],
            mode="default",
        )
        assert state.project_dir == tmp_project
        assert state.current_phase == Phase.BRIEF
        assert state.iteration_count == 0

    def test_workflow_state_frozen(self, tmp_project):
        state = WorkflowState(project_dir=tmp_project, current_phase=Phase.BRIEF)
        with pytest.raises(pydantic.ValidationError):
            state.current_phase = Phase.RESEARCH  # type: ignore

    def test_workflow_state_from_bash_compat(self, bash_state_file):
        state = read_workflow_state(bash_state_file.parent)
        assert state is not None
        assert state.current_phase == Phase.RESEARCH
        assert state.previous_phase == Phase.BRIEF
        assert Phase.BRIEF in state.completed_phases
        assert Phase.RESEARCH in state.completed_phases
        assert state.iteration_count == 2
        assert state.last_error == "some error"


class TestWorkflowStateReadWrite:
    def test_write_then_read_roundtrip(self, tmp_project):
        state = WorkflowState(
            project_dir=tmp_project,
            current_phase=Phase.PLAN,
            completed_phases=[Phase.BRIEF, Phase.RESEARCH],
            iteration_count=1,
            files=ArtifactFiles(
                brief=tmp_project / "000-brief.md",
                research=tmp_project / "001-research-report.md",
            ),
        )
        write_workflow_state(tmp_project, state)
        loaded = read_workflow_state(tmp_project)
        assert loaded is not None
        assert loaded.current_phase == Phase.PLAN
        assert loaded.completed_phases == [Phase.BRIEF, Phase.RESEARCH]
        assert loaded.iteration_count == 1


# ---------------------------------------------------------------------------
# Task / TaskQueue model
# ---------------------------------------------------------------------------


class TestTaskModel:
    def test_task_basic(self):
        task = Task(id="task-001", title="Do thing", description="A task")
        assert task.id == "task-001"
        assert task.status == TaskStatus.PENDING
        assert task.dependencies == []
        assert task.iteration_count == 0

    def test_task_with_dependencies(self):
        task = Task(id="task-002", title="After", dependencies=["task-001"])
        assert task.dependencies == ["task-001"]

    def test_task_frozen(self):
        task = Task(id="task-001", title="Do thing")
        with pytest.raises(pydantic.ValidationError):
            task.status = TaskStatus.COMPLETED  # type: ignore


class TestTaskQueueModel:
    def test_task_queue_from_json_normalizes_done(self):
        raw = {
            "tasks": [
                {"id": "task-001", "title": "A", "status": "completed"},
                {"id": "task-002", "title": "B", "status": "done"},
                {"id": "task-003", "title": "C", "status": "pending"},
            ]
        }
        queue = TaskQueue.from_json(raw)
        statuses = [t.status for t in queue.tasks]
        assert statuses == [TaskStatus.COMPLETED, TaskStatus.COMPLETED, TaskStatus.PENDING]


# ---------------------------------------------------------------------------
# Task queue helpers
# ---------------------------------------------------------------------------


class TestTaskQueueReadWrite:
    def test_write_then_read_task_queue(self, tmp_project):
        queue = TaskQueue(
            tasks=[
                Task(id="task-001", title="First"),
                Task(id="task-002", title="Second", dependencies=["task-001"]),
            ]
        )
        write_task_queue(tmp_project, queue)
        loaded = read_task_queue(tmp_project)
        assert loaded is not None
        assert len(loaded.tasks) == 2
        assert loaded.tasks[0].id == "task-001"
        assert loaded.tasks[1].dependencies == ["task-001"]


class TestGetNextTask:
    def test_returns_first_pending_with_met_deps(self, tmp_project):
        queue = TaskQueue(
            tasks=[
                Task(id="task-001", title="First"),
                Task(id="task-002", title="Second", dependencies=["task-001"]),
                Task(id="task-003", title="Third", dependencies=["task-001"]),
            ]
        )
        write_task_queue(tmp_project, queue)

        # Initially task-001 is pending — should return it
        loaded = read_task_queue(tmp_project)
        assert get_next_task(loaded) == loaded.tasks[0]

    def test_skips_task_with_unmet_deps(self, tmp_project):
        queue = TaskQueue(
            tasks=[
                Task(id="task-001", title="First"),
                Task(id="task-002", title="Second", dependencies=["task-001"]),
            ]
        )
        # Mark task-001 as in_progress (not completed)
        queue.tasks[0] = queue.tasks[0].model_copy(update={"status": TaskStatus.IN_PROGRESS})
        write_task_queue(tmp_project, queue)

        loaded = read_task_queue(tmp_project)
        assert get_next_task(loaded) is None

    def test_respects_dependency_order(self, tmp_project):
        queue = TaskQueue(
            tasks=[
                Task(id="a", title="A"),
                Task(id="b", title="B", dependencies=["a"]),
                Task(id="c", title="C", dependencies=["b"]),
            ]
        )
        write_task_queue(tmp_project, queue)
        loaded = read_task_queue(tmp_project)

        # First: a
        assert get_next_task(loaded).id == "a"

        # Complete a, then b should be next
        loaded = complete_task(loaded, "a")
        write_task_queue(tmp_project, loaded)
        loaded = read_task_queue(tmp_project)
        assert get_next_task(loaded).id == "b"

        # Complete b, then c should be next
        loaded = complete_task(loaded, "b")
        write_task_queue(tmp_project, loaded)
        loaded = read_task_queue(tmp_project)
        assert get_next_task(loaded).id == "c"

    def test_skips_non_pending_tasks(self, tmp_project):
        queue = TaskQueue(
            tasks=[
                Task(id="task-001", title="First"),
                Task(id="task-002", title="Second"),
            ]
        )
        # task-001 is already completed
        queue.tasks[0] = queue.tasks[0].model_copy(update={"status": TaskStatus.COMPLETED})
        write_task_queue(tmp_project, queue)

        loaded = read_task_queue(tmp_project)
        assert get_next_task(loaded).id == "task-002"


class TestCompleteTask:
    def test_complete_task_returns_new_queue(self, tmp_project):
        queue = TaskQueue(tasks=[Task(id="task-001", title="First")])
        new_queue = complete_task(queue, "task-001")
        # Original queue is unchanged (immutability)
        assert queue.tasks[0].status == TaskStatus.PENDING
        assert new_queue.tasks[0].status == TaskStatus.COMPLETED

    def test_complete_task_preserves_other_tasks(self, tmp_project):
        queue = TaskQueue(
            tasks=[
                Task(id="task-001", title="First"),
                Task(id="task-002", title="Second"),
            ]
        )
        new_queue = complete_task(queue, "task-001")
        assert new_queue.tasks[1].status == TaskStatus.PENDING

    def test_complete_task_nonexistent_is_noop(self, tmp_project):
        queue = TaskQueue(tasks=[Task(id="task-001", title="First")])
        new_queue = complete_task(queue, "nonexistent")
        assert new_queue.tasks[0].status == TaskStatus.PENDING


# ---------------------------------------------------------------------------
# Phase helpers
# ---------------------------------------------------------------------------


class TestIsPhaseComplete:
    def test_true_when_artifact_exists(self, tmp_project):
        (tmp_project / "000-brief.md").write_text("# Brief")
        assert is_phase_complete(tmp_project, Phase.BRIEF) is True

    def test_false_when_artifact_missing(self, tmp_project):
        assert is_phase_complete(tmp_project, Phase.BRIEF) is False


class TestGetResumePhase:
    def test_returns_current_phase_when_set(self, tmp_project):
        state = WorkflowState(
            project_dir=tmp_project,
            current_phase=Phase.RESEARCH,
            completed_phases=[Phase.BRIEF],
        )
        assert get_resume_phase(state) == Phase.RESEARCH

    def test_returns_first_missing_artifact_phase(self, tmp_project):
        # State has no current_phase but brief exists
        (tmp_project / "000-brief.md").write_text("# Brief")
        state = WorkflowState(
            project_dir=tmp_project,
            completed_phases=[],
        )
        assert get_resume_phase(state) == Phase.RESEARCH

    def test_skips_develop_phase(self, tmp_project):
        # All other artifacts exist, only develop is missing
        for name in ["000-brief", "001-research-report", "002-plan", "003-task-queue"]:
            ext = ".json" if name == "003-task-queue" else ".md"
            (tmp_project / f"{name}{ext}").write_text("x")
        state = WorkflowState(
            project_dir=tmp_project,
            completed_phases=[Phase.BRIEF, Phase.RESEARCH, Phase.PLAN, Phase.TASKS],
        )
        # get_resume_phase should not return DEVELOP
        result = get_resume_phase(state)
        assert result != Phase.DEVELOP
