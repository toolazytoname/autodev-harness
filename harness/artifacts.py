"""Artifacts module - numbered artifact I/O and workflow state management.

All data structures are immutable (frozen=True pydantic models).
Backward compatible with bash-generated state files.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Optional

import pydantic
import yaml


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class Phase(str, Enum):
    """Workflow phases in execution order."""

    BRIEF = "brief"
    RESEARCH = "research"
    PLAN = "plan"
    TASKS = "tasks"
    SPEC = "spec"
    RUBRIC = "rubric"
    UI = "ui"
    DEVELOP = "develop"


# ---------------------------------------------------------------------------
# Pydantic models (all frozen/immutable)
# ---------------------------------------------------------------------------


class ArtifactFiles(pydantic.BaseModel):
    """Paths to numbered artifact files."""

    model_config = pydantic.ConfigDict(frozen=True)

    brief: Optional[Path] = None
    research: Optional[Path] = None
    plan: Optional[Path] = None
    tasks: Optional[Path] = None
    spec: Optional[Path] = None
    rubric: Optional[Path] = None
    ui: Optional[Path] = None


class WorkflowState(pydantic.BaseModel):
    """Workflow state snapshot — written to workflow-state.json."""

    model_config = pydantic.ConfigDict(
        frozen=True,
        populate_by_name=True,  # allow both camelCase and snake_case
    )

    project_dir: Path = pydantic.Field(validation_alias="projectDir")
    current_phase: Optional[Phase] = pydantic.Field(default=None, validation_alias="currentPhase")
    previous_phase: Optional[Phase] = pydantic.Field(default=None, validation_alias="previousPhase")
    completed_phases: list[Phase] = pydantic.Field(default_factory=list, validation_alias="completedPhases")
    mode: str = "default"
    max_iterations: int = pydantic.Field(default=5, validation_alias="maxIterations")
    pass_threshold: float = pydantic.Field(default=0.8, validation_alias="passThreshold")
    iteration_count: int = pydantic.Field(default=0, validation_alias="iterationCount")
    last_error: Optional[str] = pydantic.Field(default=None, validation_alias="lastError")
    updated_at: datetime = pydantic.Field(default_factory=lambda: datetime.now(timezone.utc), validation_alias="updatedAt")
    files: ArtifactFiles = pydantic.Field(default_factory=ArtifactFiles)

    @pydantic.field_validator("project_dir", mode="before")
    @classmethod
    def _project_dir_from_camel(cls, v: Any) -> Any:
        if isinstance(v, str):
            return Path(v)
        return v

    @pydantic.field_validator("completed_phases", mode="before")
    @classmethod
    def _completed_phases_from_string(cls, v: Any) -> Any:
        """Handle bash's comma-separated string format for completed_phases."""
        if isinstance(v, str):
            return [Phase(p.strip()) for p in v.split(",") if p.strip()]
        if isinstance(v, list):
            return [Phase(p) if isinstance(p, str) else p for p in v]
        return v

    @pydantic.field_validator("current_phase", "previous_phase", mode="before")
    @classmethod
    def _phase_from_string(cls, v: Any) -> Any:
        """Handle string-to-Phase conversion for phase fields."""
        if isinstance(v, str):
            return Phase(v) if v else None
        return v

    @pydantic.model_validator(mode="before")
    @classmethod
    def _parse_phases_from_bash_state(cls, values: dict[str, Any]) -> dict[str, Any]:
        """Parse phases from bash state file format (comma-separated string or list)."""
        # completed_phases: handle "brief,research" string from bash
        raw = values.get("completedPhases") or values.get("completed_phases")
        if isinstance(raw, str):
            phases = [Phase(p.strip()) for p in raw.split(",") if p.strip()]
            values["completed_phases"] = phases
        elif isinstance(raw, list):
            values["completed_phases"] = [Phase(p) for p in raw]
        # current_phase / previous_phase: bash uses currentPhase/previousPhase
        cp = values.get("currentPhase") or values.get("current_phase")
        if isinstance(cp, str):
            values["current_phase"] = Phase(cp) if cp else None
        pp = values.get("previousPhase") or values.get("previous_phase")
        if isinstance(pp, str):
            values["previous_phase"] = Phase(pp) if pp else None
        return values


class TaskStatus(str, Enum):
    """Task execution status."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    BLOCKED = "blocked"
    DONE = "done"


class Task(pydantic.BaseModel):
    """Single task in the task queue."""

    model_config = pydantic.ConfigDict(frozen=True)

    id: str
    title: str
    description: Optional[str] = None
    status: TaskStatus = TaskStatus.PENDING
    dependencies: list[str] = pydantic.Field(default_factory=list)
    acceptance: list[str] = pydantic.Field(default_factory=list)
    kind: str = "logic"  # ui | api | logic | infra
    iteration_count: int = 0


class TaskQueue(pydantic.BaseModel):
    """Task queue container (003-task-queue.json)."""

    model_config = pydantic.ConfigDict(frozen=True)

    tasks: list[Task] = pydantic.Field(default_factory=list)

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> TaskQueue:
        """Parse from raw JSON dict, handling status field variations."""
        if "tasks" in data:
            for t in data["tasks"]:
                # Normalize status: handle both "done" and "completed"
                if t.get("status") in ("done", "completed"):
                    t["status"] = "completed"
                elif t.get("status") == "pending":
                    t["status"] = "pending"
        return cls.model_validate(data)


# ---------------------------------------------------------------------------
# Artifact paths
# ---------------------------------------------------------------------------

ARTIFACT_NAMES = [
    "000-brief",
    "001-research-report",
    "002-plan",
    "003-task-queue",
    "004-spec",
    "005-eval-rubric",
    "006-ui-spec",
]

ARTIFACT_EXTENSIONS = {
    "000-brief": ".md",
    "001-research-report": ".md",
    "002-plan": ".md",
    "003-task-queue": ".json",
    "004-spec": ".md",
    "005-eval-rubric": ".md",
    "006-ui-spec": ".md",
}


def get_artifact_path(project_dir: Path, name: str) -> Path:
    """Return the full path for a numbered artifact."""
    ext = ARTIFACT_EXTENSIONS.get(name, ".md")
    return project_dir / f"{name}{ext}"


def resolve_artifact(project_dir: Path, phase: Phase) -> Optional[Path]:
    """Resolve artifact path for a given phase."""
    mapping = {
        Phase.BRIEF: "000-brief",
        Phase.RESEARCH: "001-research-report",
        Phase.PLAN: "002-plan",
        Phase.TASKS: "003-task-queue",
        Phase.SPEC: "004-spec",
        Phase.RUBRIC: "005-eval-rubric",
        Phase.UI: "006-ui-spec",
    }
    name = mapping.get(phase)
    if not name:
        return None
    path = get_artifact_path(project_dir, name)
    return path if path.exists() else None


# ---------------------------------------------------------------------------
# Artifact read/write
# ---------------------------------------------------------------------------


def read_artifact(project_dir: Path, name: str) -> Optional[str]:
    """Read artifact content by name (e.g. '000-brief'). Returns None if not found."""
    path = get_artifact_path(project_dir, name)
    if not path.exists():
        return None
    return path.read_text()


def write_artifact(project_dir: Path, name: str, content: str) -> Path:
    """Write artifact content. Creates parent directories if needed."""
    path = get_artifact_path(project_dir, name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    return path


def artifact_exists(project_dir: Path, name: str) -> bool:
    """Check if an artifact file exists."""
    return get_artifact_path(project_dir, name).exists()


# ---------------------------------------------------------------------------
# Workflow state read/write
# ---------------------------------------------------------------------------


STATE_FILE = "workflow-state.json"


def read_workflow_state(project_dir: Path) -> Optional[WorkflowState]:
    """Read workflow state. Returns None if no state file exists."""
    state_file = project_dir / STATE_FILE
    if not state_file.exists():
        return None
    try:
        raw = json.loads(state_file.read_text())
        # Handle Path serialization from bash (strings instead of Path objects)
        if "project_dir" in raw:
            raw["project_dir"] = Path(raw["project_dir"])
        if "files" in raw and raw["files"]:
            for k, v in raw["files"].items():
                if v and isinstance(v, str):
                    raw["files"][k] = Path(v)
        return WorkflowState.model_validate(raw)
    except (json.JSONDecodeError, pydantic.ValidationError) as e:
        # Backward compat: if state file is malformed, return None
        return None


def write_workflow_state(project_dir: Path, state: WorkflowState) -> Path:
    """Write workflow state to disk."""
    ensure_dir(project_dir)
    state_file = project_dir / STATE_FILE
    # Serialize to JSON with Path objects as strings
    raw = state.model_dump(mode="json")
    # Convert Path objects to strings for JSON serialization
    raw["project_dir"] = str(raw["project_dir"])
    files_raw = raw.get("files") or {}
    raw["files"] = {k: str(v) if v else None for k, v in files_raw.items()}
    state_file.write_text(json.dumps(raw, indent=2) + "\n")
    return state_file


def ensure_dir(path: Path) -> None:
    """Ensure directory exists."""
    path.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# Breakpoint / resume helpers
# ---------------------------------------------------------------------------


def get_resume_phase(state: WorkflowState) -> Optional[Phase]:
    """Determine the phase to resume from given state.

    Logic:
    - If current_phase is set and not the last phase, resume there
    - Otherwise find the first missing artifact and return its phase
    """
    if state.current_phase:
        return state.current_phase

    # Find first missing artifact
    for phase in Phase:
        if phase == Phase.DEVELOP:
            continue  # develop is special — tasks drive it
        name = {
            Phase.BRIEF: "000-brief",
            Phase.RESEARCH: "001-research-report",
            Phase.PLAN: "002-plan",
            Phase.TASKS: "003-task-queue",
            Phase.SPEC: "004-spec",
            Phase.RUBRIC: "005-eval-rubric",
            Phase.UI: "006-ui-spec",
        }.get(phase)
        if not name:
            continue
        if not artifact_exists(state.project_dir, name):
            return phase
    return None


def is_phase_complete(project_dir: Path, phase: Phase) -> bool:
    """Check if a phase has produced its artifact."""
    name = {
        Phase.BRIEF: "000-brief",
        Phase.RESEARCH: "001-research-report",
        Phase.PLAN: "002-plan",
        Phase.TASKS: "003-task-queue",
        Phase.SPEC: "004-spec",
        Phase.RUBRIC: "005-eval-rubric",
        Phase.UI: "006-ui-spec",
    }.get(phase)
    if not name:
        return False
    return artifact_exists(project_dir, name)


# ---------------------------------------------------------------------------
# Task queue helpers
# ---------------------------------------------------------------------------


def read_task_queue(project_dir: Path) -> Optional[TaskQueue]:
    """Read task queue from 003-task-queue.json."""
    path = get_artifact_path(project_dir, "003-task-queue")
    if not path.exists():
        return None
    try:
        raw = json.loads(path.read_text())
        return TaskQueue.from_json(raw)
    except (json.JSONDecodeError, pydantic.ValidationError):
        return None


def write_task_queue(project_dir: Path, queue: TaskQueue) -> Path:
    """Write task queue to disk."""
    ensure_dir(project_dir)
    path = get_artifact_path(project_dir, "003-task-queue")
    # Serialize with TaskStatus as string values
    data = {
        "tasks": [
            {
                "id": t.id,
                "title": t.title,
                "description": t.description,
                "status": t.status.value if isinstance(t.status, TaskStatus) else t.status,
                "dependencies": t.dependencies,
                "acceptance": t.acceptance,
                "kind": t.kind,
                "iteration_count": t.iteration_count,
            }
            for t in queue.tasks
        ]
    }
    path.write_text(json.dumps(data, indent=2) + "\n")
    return path


def get_next_task(queue: TaskQueue) -> Optional[Task]:
    """Return the first pending task whose dependencies are all completed."""
    completed_ids = {t.id for t in queue.tasks if t.status == TaskStatus.COMPLETED}
    for task in queue.tasks:
        if task.status != TaskStatus.PENDING:
            continue
        deps = task.dependencies or []
        if all(d in completed_ids for d in deps):
            return task
    return None


def complete_task(queue: TaskQueue, task_id: str) -> TaskQueue:
    """Return a new TaskQueue with the given task marked completed."""
    new_tasks = [
        task.model_copy(update={"status": TaskStatus.COMPLETED}) if task.id == task_id else task
        for task in queue.tasks
    ]
    return TaskQueue(tasks=new_tasks)
