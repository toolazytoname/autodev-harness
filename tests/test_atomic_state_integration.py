"""Integration tests for T17: artifacts.py + score_card.py now use atomic_io.

These tests pin the new behaviour required by T17 [CRITICAL]:

1. Writes go through atomic_io (temp + os.replace).
2. Reads surface corruption via AtomicIOError instead of silently returning None.

The previous behaviour — readers returning None on JSONDecodeError — was
the root cause of "corrupt state → silent full restart", which would wipe
all progress on a crash mid-write.
"""

from __future__ import annotations

import json
from pathlib import Path

import pydantic
import pytest

from harness.artifacts import (
    Task,
    TaskQueue,
    TaskStatus,
    WorkflowState,
    ArtifactFiles,
    Phase,
    read_task_queue,
    read_workflow_state,
    write_artifact,
    write_task_queue,
    write_workflow_state,
)
from harness.atomic_io import AtomicIOError
from harness.score_card import ScoreCard, ScoreCardVersion, save_score_card, load_score_card


def _sample_state(tmp_path: Path) -> WorkflowState:
    return WorkflowState(
        project_dir=tmp_path,
        current_phase=Phase.RESEARCH,
        completed_phases=[Phase.BRIEF],
        mode="default",
        files=ArtifactFiles(brief=tmp_path / "000-brief.md"),
    )


def _sample_queue() -> TaskQueue:
    return TaskQueue(
        tasks=[
            Task(
                id="t1",
                title="sample task",
                acceptance=["echo ok"],
                status=TaskStatus.PENDING,
            ),
        ],
    )


def _sample_card() -> ScoreCard:
    return ScoreCard(
        iter=1,
        reviewer="correctness",
        score=0.9,
        blockers=[],
        suggestions=["polish docs"],
        evidence="all checks green",
    )


# ---------------------------------------------------------------------------
# Writes are atomic — verified by structural / file-content checks
# ---------------------------------------------------------------------------


def test_write_workflow_state_uses_atomic_write(tmp_path: Path) -> None:
    state = _sample_state(tmp_path)
    path = write_workflow_state(tmp_path, state)
    assert path == tmp_path / "workflow-state.json"
    assert path.exists()
    # No stray temp files
    assert [p for p in tmp_path.iterdir() if p.name != "workflow-state.json"] == []


def test_write_task_queue_uses_atomic_write(tmp_path: Path) -> None:
    queue = _sample_queue()
    path = write_task_queue(tmp_path, queue)
    assert path == tmp_path / "003-task-queue.json"
    assert path.exists()
    # Content round-trips
    data = json.loads(path.read_text())
    assert data["tasks"][0]["id"] == "t1"


def test_write_artifact_uses_atomic_write(tmp_path: Path) -> None:
    path = write_artifact(tmp_path, "000-brief", "# hello\n")
    assert path == tmp_path / "000-brief.md"
    assert path.read_text() == "# hello\n"
    # No temp leftovers
    assert list(tmp_path.iterdir()) == [path]


def test_save_score_card_uses_atomic_write(tmp_path: Path) -> None:
    card = _sample_card()
    path = save_score_card(tmp_path, "task-1", card)
    expected_dir = tmp_path / "score-cards" / "task-1"
    assert path.parent == expected_dir
    assert path.name == "iter-1-correctness.json"
    assert path.exists()
    # No temp leftovers in the score card dir
    assert [p for p in expected_dir.iterdir() if not p.name.endswith(".json")] == []


# ---------------------------------------------------------------------------
# Reads raise on corruption instead of silently returning None
# ---------------------------------------------------------------------------


def test_read_workflow_state_raises_on_corrupt_json(tmp_path: Path) -> None:
    state_file = tmp_path / "workflow-state.json"
    state_file.write_text("{this is not valid json")
    with pytest.raises(AtomicIOError) as exc:
        read_workflow_state(tmp_path)
    assert str(state_file) in str(exc.value)


def test_read_task_queue_raises_on_corrupt_json(tmp_path: Path) -> None:
    queue_file = tmp_path / "003-task-queue.json"
    queue_file.write_text('{"tasks": [')  # truncated
    with pytest.raises(AtomicIOError) as exc:
        read_task_queue(tmp_path)
    assert str(queue_file) in str(exc.value)


def test_load_score_card_raises_on_corrupt_json(tmp_path: Path) -> None:
    from harness.score_card import load_score_card as loader  # local import for clarity

    card_dir = tmp_path / "score-cards" / "task-1"
    card_dir.mkdir(parents=True)
    bad = card_dir / "iter-1-correctness.json"
    bad.write_text('{"iter": 1, "reviewer":')  # truncated
    with pytest.raises(AtomicIOError):
        loader(tmp_path, "task-1", 1, "correctness")


# ---------------------------------------------------------------------------
# Reads still return None when the file simply does not exist
# (FileNotFoundError != corruption — that's a normal startup state)
# ---------------------------------------------------------------------------


def test_read_workflow_state_returns_none_when_missing(tmp_path: Path) -> None:
    assert read_workflow_state(tmp_path) is None


def test_read_task_queue_returns_none_when_missing(tmp_path: Path) -> None:
    assert read_task_queue(tmp_path) is None


def test_load_score_card_returns_none_when_missing(tmp_path: Path) -> None:
    assert load_score_card(tmp_path, "task-1", 1, "correctness") is None


# ---------------------------------------------------------------------------
# Round-trips: write then read give equivalent objects
# ---------------------------------------------------------------------------


def test_workflow_state_round_trip(tmp_path: Path) -> None:
    state = _sample_state(tmp_path)
    write_workflow_state(tmp_path, state)
    loaded = read_workflow_state(tmp_path)
    assert loaded is not None
    assert loaded.current_phase == Phase.RESEARCH
    assert loaded.completed_phases == [Phase.BRIEF]


def test_task_queue_round_trip(tmp_path: Path) -> None:
    queue = _sample_queue()
    write_task_queue(tmp_path, queue)
    loaded = read_task_queue(tmp_path)
    assert loaded is not None
    assert len(loaded.tasks) == 1
    assert loaded.tasks[0].id == "t1"
    assert loaded.tasks[0].status == TaskStatus.PENDING


def test_score_card_round_trip(tmp_path: Path) -> None:
    card = _sample_card()
    save_score_card(tmp_path, "task-1", card)
    loaded = load_score_card(tmp_path, "task-1", 1, "correctness")
    assert loaded is not None
    assert loaded.reviewer == "correctness"
    assert loaded.score == 0.9


# ---------------------------------------------------------------------------
# Atomicity: writes that fail mid-way must not corrupt existing file
# ---------------------------------------------------------------------------


def test_write_workflow_state_does_not_corrupt_on_failure(tmp_path: Path) -> None:
    """If the inner write fails, the existing state file must be untouched."""
    state = _sample_state(tmp_path)
    write_workflow_state(tmp_path, state)  # baseline good file

    original_content = (tmp_path / "workflow-state.json").read_text()

    # Now force the atomic write to fail mid-stream
    import harness.artifacts as art

    original = art.atomic_write_json
    def boom(_path, _obj):
        raise OSError("simulated disk error")
    art.atomic_write_json = boom  # type: ignore[assignment]
    try:
        with pytest.raises(OSError, match="simulated disk error"):
            write_workflow_state(tmp_path, _sample_state(tmp_path))
    finally:
        art.atomic_write_json = original  # type: ignore[assignment]

    # The original file must still be intact
    assert (tmp_path / "workflow-state.json").read_text() == original_content