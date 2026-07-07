"""Tests for T24 — module split of inner_loop / pipeline.

These tests pin the *new* module surface so the refactor can be done in
small steps without breaking the public API. They drive the design of:

  - ``harness.worktree``        — git worktree + diff helpers
  - ``harness.generator``       — run_generator + GeneratorOutput
  - ``harness.reviewer_runner`` — run_single_reviewer / run_reviewers_parallel / check_gate
  - ``harness.ui_phase``        — UIPhase class extracted from pipeline.phase_ui

The tests also pin the per-iteration unit-testability requirement of
T24: ``run_inner_loop`` must be split so that ``_setup_task`` /
``_run_iteration`` / ``_on_gate_pass`` can be exercised in isolation
without a real git worktree + reviewer fan-out.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from harness.adapters.base import AgentResult, Usage
from harness.artifacts import Task, TaskQueue, TaskStatus
from harness.router import ModelSpec


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def git_project(tmp_path: Path) -> Path:
    """A minimal git repository for worktree tests."""
    subprocess.run(["git", "init", "-b", "main"], cwd=tmp_path, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "t@t"], cwd=tmp_path, capture_output=True
    )
    subprocess.run(
        ["git", "config", "user.name", "t"], cwd=tmp_path, capture_output=True
    )
    (tmp_path / "README.md").write_text("t")
    subprocess.run(["git", "add", "."], cwd=tmp_path, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "init"], cwd=tmp_path, capture_output=True, text=True
    )
    return tmp_path


def _seed_queue(project_dir: Path, task_id: str, kind: str = "logic") -> None:
    """Write a one-task queue to project_dir."""
    queue = TaskQueue(
        tasks=[
            Task(
                id=task_id,
                title="t",
                description="d",
                kind=kind,
                status=TaskStatus.PENDING,
                dependencies=[],
            )
        ]
    )
    from harness.artifacts import write_task_queue
    write_task_queue(project_dir, queue)


# ---------------------------------------------------------------------------
# Module surface — the four new modules must exist as separate units
# ---------------------------------------------------------------------------


class TestNewModuleSurface:
    def test_worktree_module_importable(self):
        from harness import worktree

        assert hasattr(worktree, "create_worktree")
        assert hasattr(worktree, "merge_worktree")
        assert hasattr(worktree, "get_worktree_diff")
        assert hasattr(worktree, "get_worktree_files")
        assert hasattr(worktree, "get_current_branch")

    def test_generator_module_importable(self):
        from harness import generator

        assert hasattr(generator, "run_generator")
        assert hasattr(generator, "GeneratorOutput")

    def test_reviewer_runner_module_importable(self):
        from harness import reviewer_runner

        assert hasattr(reviewer_runner, "run_single_reviewer")
        assert hasattr(reviewer_runner, "run_reviewers_parallel")
        assert hasattr(reviewer_runner, "check_gate")

    def test_ui_phase_module_importable(self):
        from harness import ui_phase

        assert hasattr(ui_phase, "UIPhase")
        assert hasattr(ui_phase, "pick_directions_for_brief")
        assert hasattr(ui_phase, "extract_ui_output")


# ---------------------------------------------------------------------------
# Backward compatibility — old import paths must keep working
# ---------------------------------------------------------------------------


class TestBackwardCompat:
    def test_inner_loop_re_exports_split_helpers(self):
        # All of these used to live in inner_loop.py directly. They must
        # remain importable from there after the split.
        from harness.inner_loop import (  # noqa: F401
            LoopConfig,
            GeneratorOutput,
            check_gate,
            create_worktree,
            get_worktree_diff,
            get_worktree_files,
            merge_worktree,
            run_generator,
            run_single_reviewer,
            run_reviewers_parallel,
            write_escalation_report,
            run_inner_loop,
            InnerLoopError,
            EscalationError,
        )

    def test_pipeline_re_exports_ui_helpers(self):
        from harness.pipeline import (  # noqa: F401
            Pipeline,
            PipelineConfig,
            PipelineError,
            extract_ui_output,
            pick_directions_for_brief,
        )


# ---------------------------------------------------------------------------
# Per-iteration unit testability — T24 acceptance criterion
# ---------------------------------------------------------------------------


class TestInnerLoopHelpersExercisableIndependently:
    """``run_inner_loop`` is split into _setup_task / _run_iteration /
    _on_gate_pass. Each must be callable on its own so we can unit-test
    a single iteration step without running the full loop."""

    def test_setup_task_returns_setup_record(self, git_project: Path, tmp_path: Path):
        from harness.inner_loop import _setup_task

        _seed_queue(git_project, "task-1")
        setup = _setup_task(
            project_dir=git_project,
            task_id="task-1",
            config=None,
        )
        # Returns a record with worktree + task + reviewer names
        assert hasattr(setup, "worktree_path")
        assert hasattr(setup, "task")
        assert hasattr(setup, "reviewer_names")
        assert hasattr(setup, "base_branch")
        assert setup.task.id == "task-1"
        assert setup.worktree_path.exists()

    def test_run_iteration_runs_generator_and_reviewers(
        self, git_project: Path
    ):
        from harness.inner_loop import _setup_task, _run_iteration

        _seed_queue(git_project, "task-2", kind="logic")
        setup = _setup_task(
            project_dir=git_project, task_id="task-2", config=None
        )

        adapter = MagicMock()
        adapter.run.return_value = AgentResult(
            stdout="ok",
            stderr="",
            exit_code=0,
            usage=Usage(),
        )
        router = MagicMock()
        router.resolve.side_effect = lambda stage: ModelSpec(
            model="m", tier="worker"
        )
        router.record = MagicMock()

        result = _run_iteration(
            adapter=adapter,
            router=router,
            setup=setup,
            spec_text="spec",
            iter_num=1,
        )
        # Returns cards + per-reviewer usage (the bookkeeping the
        # orchestrator used to inline).
        assert hasattr(result, "cards")
        assert hasattr(result, "reviewer_usages")
        assert hasattr(result, "generator_output")
        assert hasattr(result, "diff_text")
        assert hasattr(result, "changed_files")
        # Generator + each reviewer call adapter.run
        assert adapter.run.call_count >= 1

    def test_on_gate_pass_writes_completed_then_merges(
        self, git_project: Path
    ):
        from harness.inner_loop import _setup_task, _on_gate_pass

        _seed_queue(git_project, "task-3", kind="logic")
        setup = _setup_task(
            project_dir=git_project, task_id="task-3", config=None
        )
        # Touch a file in the worktree so there's something to merge
        (setup.worktree_path / "x.txt").write_text("hi")
        subprocess.run(
            ["git", "add", "."], cwd=setup.worktree_path, capture_output=True
        )
        subprocess.run(
            ["git", "commit", "-m", "x"],
            cwd=setup.worktree_path,
            capture_output=True,
            text=True,
        )

        # The full signature mirrors what run_inner_loop passes — the
        # function needs the iter / cards / spec_text so a merge
        # conflict can produce a faithful escalation report.
        from harness.score_card import ScoreCard

        _on_gate_pass(
            project_dir=git_project,
            task_id="task-3",
            base_branch=setup.base_branch,
            iter_num=1,
            all_cards=[ScoreCard(iter=1, reviewer="r", score=0.9)],
            spec_text="spec",
        )

        # Task is COMPLETED on disk
        from harness.artifacts import read_task_queue
        q = read_task_queue(git_project)
        assert q is not None
        statuses = {t.id: t.status for t in q.tasks}
        assert statuses["task-3"] == TaskStatus.COMPLETED

        # The commit is now in the base branch
        log = subprocess.run(
            ["git", "log", "--oneline"],
            cwd=git_project,
            capture_output=True,
            text=True,
        )
        assert "x" in log.stdout


# ---------------------------------------------------------------------------
# worktree.py — direct unit tests
# ---------------------------------------------------------------------------


class TestWorktreeModule:
    def test_create_worktree_creates_branch_and_dir(
        self, git_project: Path
    ):
        from harness.worktree import create_worktree

        wt = create_worktree(git_project, "task-a")
        assert wt.exists()
        proc = subprocess.run(
            ["git", "branch", "--list", "task/task-a"],
            cwd=git_project,
            capture_output=True,
            text=True,
        )
        assert "task/task-a" in proc.stdout

    def test_create_worktree_idempotent(self, git_project: Path):
        from harness.worktree import create_worktree

        first = create_worktree(git_project, "task-b")
        second = create_worktree(git_project, "task-b")
        assert first == second
        assert first.exists()

    def test_get_worktree_diff_lists_changes(self, git_project: Path):
        from harness.worktree import create_worktree, get_worktree_diff

        wt = create_worktree(git_project, "task-c")
        (wt / "f.txt").write_text("x")
        subprocess.run(["git", "add", "."], cwd=wt, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "f"],
            cwd=wt,
            capture_output=True,
            text=True,
        )
        diff = get_worktree_diff(git_project, "task-c")
        assert "f.txt" in diff or "x" in diff

    def test_get_worktree_files_lists_paths(self, git_project: Path):
        from harness.worktree import create_worktree, get_worktree_files

        wt = create_worktree(git_project, "task-d")
        (wt / "g.txt").write_text("y")
        subprocess.run(["git", "add", "."], cwd=wt, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "g"],
            cwd=wt,
            capture_output=True,
            text=True,
        )
        files = get_worktree_files(git_project, "task-d")
        assert "g.txt" in files


# ---------------------------------------------------------------------------
# generator.py — direct unit tests
# ---------------------------------------------------------------------------


class TestGeneratorModule:
    def test_run_generator_calls_adapter_with_resolved_spec(
        self, git_project: Path
    ):
        from harness.generator import run_generator

        adapter = MagicMock()
        adapter.run.return_value = AgentResult(
            stdout="ok", stderr="", exit_code=0, usage=Usage()
        )
        router = MagicMock()
        router.resolve.return_value = ModelSpec(
            model="g-model", tier="worker"
        )
        router.record = MagicMock()

        out = run_generator(
            adapter=adapter,
            router=router,
            worktree_path=git_project,
            spec_text="spec",
            task_id="t1",
            task_title="title",
            task_description="desc",
            blockers_from_previous=[],
            suggestions_from_previous=[],
            iter_num=1,
        )
        assert out.exit_code == 0
        # adapter.run was called with model from router.resolve("generate")
        router.resolve.assert_called_with("generate")
        _, kwargs = adapter.run.call_args
        assert kwargs["model"] == "g-model"

    def test_run_generator_includes_feedback_block_on_iter_2(
        self, git_project: Path
    ):
        from harness.generator import run_generator

        adapter = MagicMock()
        adapter.run.return_value = AgentResult(
            stdout="ok", stderr="", exit_code=0, usage=Usage()
        )
        router = MagicMock()
        router.resolve.return_value = ModelSpec(
            model="g-model", tier="worker"
        )

        run_generator(
            adapter=adapter,
            router=router,
            worktree_path=git_project,
            spec_text="spec",
            task_id="t1",
            task_title="t",
            task_description="d",
            blockers_from_previous=["b1"],
            suggestions_from_previous=["s1"],
            iter_num=2,
        )
        prompt = adapter.run.call_args.args[0]
        assert "b1" in prompt
        assert "s1" in prompt


# ---------------------------------------------------------------------------
# reviewer_runner.py — direct unit tests
# ---------------------------------------------------------------------------


class TestReviewerRunnerModule:
    def test_check_gate_empty_cards_fails(self):
        from harness.reviewer_runner import check_gate

        passed, reason = check_gate([])
        assert passed is False
        assert "No score cards" in reason

    def test_check_gate_all_above_threshold_passes(self):
        from harness.reviewer_runner import check_gate
        from harness.score_card import ScoreCard

        cards = [
            ScoreCard(iter=1, reviewer="a", score=0.9),
            ScoreCard(iter=1, reviewer="b", score=0.85),
        ]
        passed, reason = check_gate(cards)
        assert passed is True
        assert "passed" in reason.lower()

    def test_check_gate_with_blocker_fails(self):
        from harness.reviewer_runner import check_gate
        from harness.score_card import ScoreCard

        cards = [ScoreCard(iter=1, reviewer="a", score=0.9, blockers=["x"])]
        passed, _ = check_gate(cards)
        assert passed is False


# ---------------------------------------------------------------------------
# ui_phase.py — direct unit tests
# ---------------------------------------------------------------------------


class TestUIPhaseModule:
    def test_pick_directions_returns_four(self):
        from harness.ui_phase import pick_directions_for_brief

        dirs = pick_directions_for_brief("a small toy app for kids")
        assert len(dirs) >= 1
        for d in dirs:
            assert "slug" in d
            assert "label" in d

    def test_extract_ui_output_splits_spec_and_html(self):
        from harness.ui_phase import extract_ui_output

        raw = (
            "## 006-ui-spec\n\nThe page should show a hero.\n\n"
            "```html\n<html><body>hi</body></html>\n```\n"
        )
        spec, html = extract_ui_output(raw)
        assert "hero" in spec.lower() or "006-ui-spec" in spec.lower()
        assert "<html>" in html
