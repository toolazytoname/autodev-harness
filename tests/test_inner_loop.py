"""Tests for harness.inner_loop module.

Acceptance criteria (T06):
  MASTER-PLAN §6 第 3 条 — 埋 bug 的集成测试：
  给一个故意有 off-by-one 的 spec 样例，证明 test reviewer 拦截 → 回灌 → 第二轮通过。
  用 mock adapter 跑（不花真 token），另留一个真实 slow 测试。
"""

from __future__ import annotations

import json
import subprocess
import tempfile
import threading
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from harness.adapters.base import AgentResult, Usage
from harness.inner_loop import (
    LoopConfig,
    check_gate,
    create_worktree,
    get_worktree_diff,
    get_worktree_files,
    merge_worktree,
    run_generator,
    run_inner_loop,
    run_single_reviewer,
    write_escalation_report,
    EscalationError,
    InnerLoopError,
)
from harness.score_card import ScoreCard


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_project(tmp_path):
    """A minimal git repository to use as project_dir."""
    subprocess.run(["git", "init", "-b", "main"], cwd=tmp_path, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=tmp_path, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, capture_output=True)

    # Create initial commit on main
    (tmp_path / "README.md").write_text("test")
    subprocess.run(["git", "add", "."], cwd=tmp_path, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "init"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    return tmp_path


@pytest.fixture
def mock_adapter():
    """A mock adapter that returns configurable results."""
    adapter = MagicMock()
    return adapter


@pytest.fixture
def mock_router():
    """A mock router that resolves all stages to a dummy spec."""
    from harness.router import ModelSpec
    router = MagicMock()
    router.resolve.side_effect = lambda stage: ModelSpec(
        model="mock-model",
        tier="worker",
    )
    router.record = MagicMock()
    return router


# ---------------------------------------------------------------------------
# Worktree helper tests
# ---------------------------------------------------------------------------


class TestWorktreeHelpers:
    def test_create_worktree_creates_branch_and_dir(self, mock_project):
        wt_path = create_worktree(mock_project, "task-42")
        assert wt_path.exists()
        assert wt_path.is_dir()

        # Check branch exists
        result = subprocess.run(
            ["git", "branch", "--list", "task/task-42"],
            cwd=mock_project,
            capture_output=True,
            text=True,
        )
        assert "task/task-42" in result.stdout

    def test_create_worktree_idempotent_fails(self, mock_project):
        # Creating the same worktree twice should raise
        create_worktree(mock_project, "task-1")
        with pytest.raises(InnerLoopError):
            create_worktree(mock_project, "task-1")

    def test_get_worktree_diff(self, mock_project):
        create_worktree(mock_project, "task-10")
        wt_path = mock_project / ".worktrees" / "task" / "task-10"

        # Make a change in the worktree and commit it
        (wt_path / "foo.txt").write_text("hello")
        subprocess.run(["git", "add", "foo.txt"], cwd=wt_path, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "add foo"],
            cwd=wt_path,
            capture_output=True,
            text=True,
        )

        diff = get_worktree_diff(mock_project, "task-10")
        assert "foo.txt" in diff or "hello" in diff

    def test_get_worktree_files(self, mock_project):
        create_worktree(mock_project, "task-11")
        wt_path = mock_project / ".worktrees" / "task" / "task-11"
        (wt_path / "bar.txt").write_text("world")
        subprocess.run(["git", "add", "bar.txt"], cwd=wt_path, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "add bar"],
            cwd=wt_path,
            capture_output=True,
            text=True,
        )

        files = get_worktree_files(mock_project, "task-11")
        assert "bar.txt" in files


# ---------------------------------------------------------------------------
# Gate check tests
# ---------------------------------------------------------------------------


class TestGateCheck:
    def test_empty_cards_fails(self):
        passed, reason = check_gate([])
        assert passed is False
        assert "No score cards" in reason

    def test_all_pass_threshold_passes(self):
        cards = [
            ScoreCard(iter=1, reviewer="correctness", score=0.9),
            ScoreCard(iter=1, reviewer="test", score=0.85),
            ScoreCard(iter=1, reviewer="boundary", score=0.8),
        ]
        passed, reason = check_gate(cards)
        assert passed is True

    def test_one_low_score_fails(self):
        cards = [
            ScoreCard(iter=1, reviewer="correctness", score=0.9),
            ScoreCard(iter=1, reviewer="test", score=0.7, blockers=["coverage too low"]),
        ]
        passed, reason = check_gate(cards)
        assert passed is False
        assert "Gate not passed" in reason

    def test_one_with_blocker_fails(self):
        cards = [
            ScoreCard(iter=1, reviewer="correctness", score=0.9),
            ScoreCard(iter=1, reviewer="test", score=0.9, blockers=["flaky test"]),
        ]
        passed, reason = check_gate(cards)
        assert passed is False

    def test_exactly_threshold_passes(self):
        cards = [
            ScoreCard(iter=1, reviewer="correctness", score=0.8),
            ScoreCard(iter=1, reviewer="test", score=0.8),
        ]
        passed, reason = check_gate(cards)
        assert passed is True


# ---------------------------------------------------------------------------
# Escalation report
# ---------------------------------------------------------------------------


class TestEscalationReport:
    def test_write_escalation_report_creates_file(self, mock_project):
        cards = [
            ScoreCard(iter=1, reviewer="correctness", score=0.6, blockers=["off-by-one"]),
            ScoreCard(iter=1, reviewer="test", score=0.7, blockers=["coverage 65%"]),
        ]
        report_path = write_escalation_report(
            mock_project, "task-99", 5, cards, "# Spec\nA test spec"
        )
        assert report_path.exists()
        content = report_path.read_text()
        assert "task-99" in content
        assert "off-by-one" in content
        assert "Iterations exhausted: 5" in content


# ---------------------------------------------------------------------------
# Integration test: bug injection → reviewer intercepts → feedback → second iter passes
#
# This is the key acceptance test from MASTER-PLAN §6 第 3 条.
# A spec with an off-by-one error is submitted. The mock reviewer returns
# a failing score card on iter 1, the loop feeds the blocker back to the
# generator, and on iter 2 the generator "fixes" the bug and the reviewer passes.
# ---------------------------------------------------------------------------


class TestBugInjectionLoop:
    """Integration test: off-by-one bug is caught and fixed in second iteration."""

    def _write_spec_and_queue(self, project_dir: Path):
        """Write a minimal 004-spec.md and 003-task-queue.json."""
        spec_path = project_dir / "004-spec.md"
        spec_path.write_text(
            "# Spec: Counter\n\n"
            "Implement a counter that starts at 0. Increment it 5 times.\n"
            "Expected final value: 5\n"
        )

        queue_path = project_dir / "003-task-queue.json"
        queue_path.write_text(
            json.dumps(
                {
                    "tasks": [
                        {
                            "id": "task-1",
                            "title": "Counter implementation",
                            "description": "Implement a counter per the spec",
                            "status": "pending",
                            "dependencies": [],
                            "acceptance": ["counter reaches 5 after 5 increments"],
                            "kind": "logic",
                            "iteration_count": 0,
                        }
                    ]
                }
            )
        )

    def test_bug_caught_and_fixed_second_iter(self, mock_project, mock_router):
        """Mock reviewers fail on iter 1 (off-by-one), pass on iter 2 (fixed).

        This test verifies:
        1. All reviewers intercept the bug on iter 1 → score < 0.8 or blocker present
        2. Blockers are fed back to generator (no reviewer transcript)
        3. Generator "fixes" on iter 2 → all reviewers pass
        4. Gate passes → no escalation → returns all cards
        """
        self._write_spec_and_queue(mock_project)

        # Iter 1: all reviewers report the off-by-one bug
        iter1_card = json.dumps(
            {
                "reviewer": "test",
                "iter": 1,
                "score": 0.5,
                "blockers": ["Counter reaches 4 instead of 5 after 5 increments (off-by-one)"],
                "suggestions": ["Check the loop termination condition"],
                "evidence": "ran `pytest` — 1 failed: test_counter_reaches_5: expected 5, got 4",
            }
        )

        # Iter 2: all reviewers pass (bug fixed)
        iter2_card = json.dumps(
            {
                "reviewer": "test",
                "iter": 2,
                "score": 0.95,
                "blockers": [],
                "suggestions": [],
                "evidence": "ran `pytest` — all tests passed",
            }
        )

        # Generator responses
        iter1_gen_response = (
            "I'll implement the counter. "
            "Here's my code that has a bug: loop runs while i < 5 (should be <= 5)."
        )
        iter2_gen_response = "I've fixed the off-by-one: loop now runs while i <= 5."

        # Use a simple counter to cycle through responses:
        # Call 0 = gen1, calls 1-3 = reviewer iter1, call 4 = gen2, calls 5-7 = reviewer iter2
        call_list = [
            iter1_gen_response,  # 0: gen iter 1
            iter1_card,          # 1: reviewer 1 iter 1
            iter1_card,          # 2: reviewer 2 iter 1
            iter1_card,          # 3: reviewer 3 iter 1
            iter2_gen_response,  # 4: gen iter 2
            iter2_card,          # 5: reviewer 1 iter 2
            iter2_card,          # 6: reviewer 2 iter 2
            iter2_card,          # 7: reviewer 3 iter 2
        ]
        call_idx = [0]  # mutable container for closure

        def mock_run(prompt, *, model, cwd, timeout):
            idx = call_idx[0]
            call_idx[0] = idx + 1
            response = call_list[idx]

            return AgentResult(
                stdout=response,
                stderr="",
                exit_code=0,
                usage=Usage(input_tokens=100, output_tokens=200, total_tokens=300),
                duration_ms=1000,
                retry_count=0,
            )

        adapter = MagicMock()
        adapter.run = mock_run

        spec_text = (
            (mock_project / "004-spec.md").read_text()
            if (mock_project / "004-spec.md").exists()
            else "# Counter Spec\n"
        )

        with patch(
            "harness.inner_loop.create_worktree",
            return_value=mock_project / ".worktrees" / "task" / "task-1",
        ):
            with patch(
                "harness.inner_loop.merge_worktree",
                return_value=None,
            ):
                cards = run_inner_loop(
                    project_dir=mock_project,
                    task_id="task-1",
                    spec_text=spec_text,
                    task_kind="logic",
                    adapter=adapter,
                    router=mock_router,
                    config=LoopConfig(max_iterations=5),
                )

        # logic task has 3 reviewers (correctness, test, boundary)
        # Iter 1: all 3 fail → iter 2 → all 3 pass → gate passes
        # Total: 6 cards
        assert len(cards) == 6, f"Expected 6 cards (3 reviewers × 2 iters), got {len(cards)}: {cards}"

        # Iter 1 cards should all be failing
        iter1_cards = [c for c in cards if c.iter == 1]
        assert len(iter1_cards) == 3
        for c in iter1_cards:
            assert c.score < 0.8, f"{c.reviewer} iter1 should fail but score={c.score}"
            assert c.blockers, f"{c.reviewer} iter1 should have blockers"

        # Iter 2 cards should all pass
        iter2_cards = [c for c in cards if c.iter == 2]
        assert len(iter2_cards) == 3
        for c in iter2_cards:
            assert c.score >= 0.8, f"{c.reviewer} iter2 should pass but score={c.score}"
            assert not c.blockers, f"{c.reviewer} iter2 should have no blockers"


# ---------------------------------------------------------------------------
# Slow / smoke test (marked as slow — skipped in unit test runs)
# ---------------------------------------------------------------------------


class TestInnerLoopSmoke:
    @pytest.mark.slow
    @pytest.mark.skip(reason="Requires real claude CLI and API key — run manually")
    def test_real_inner_loop_smoke(self, tmp_path):
        """Real smoke test — runs the full loop with a real model.

        Skipped by default. Run with: pytest -m slow tests/test_inner_loop.py
        """
        from harness.adapters.claude import ClaudeAdapter

        subprocess.run(["git", "init", "-b", "main"], cwd=tmp_path, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=tmp_path, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, capture_output=True)
        (tmp_path / "README.md").write_text("test")
        subprocess.run(["git", "add", "."], cwd=tmp_path, capture_output=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=tmp_path, capture_output=True)

        spec_text = "# Counter Spec\n\nImplement a counter. Start at 0, increment 5 times, expect 5."
        (tmp_path / "004-spec.md").write_text(spec_text)
        (tmp_path / "003-task-queue.json").write_text(
            json.dumps(
                {
                    "tasks": [
                        {
                            "id": "task-1",
                            "title": "Counter",
                            "description": "Implement counter",
                            "status": "pending",
                            "dependencies": [],
                            "acceptance": [],
                            "kind": "logic",
                            "iteration_count": 0,
                        }
                    ]
                }
            )
        )

        adapter = ClaudeAdapter()
        from harness.router import ModelRouter

        router = ModelRouter()

        try:
            cards = run_inner_loop(
                project_dir=tmp_path,
                task_id="task-1",
                spec_text=spec_text,
                task_kind="logic",
                adapter=adapter,
                router=router,
                config=LoopConfig(max_iterations=2),
            )
            assert len(cards) >= 2
            assert all(c.score >= 0.8 for c in cards if c.iter == cards[-1].iter)
        except EscalationError:
            # Acceptable if the real model can't fix it in 2 iters
            pass
