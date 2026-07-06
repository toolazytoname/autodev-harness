"""Tests for harness.pipeline — outer five-phase orchestration (T07).

All tests use a mock adapter (no real tokens). The T07 acceptance smoke
(--test mode with a real model) is marked slow and skipped by default.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from harness.adapters.base import AgentResult, Usage
from harness.artifacts import Phase, TaskStatus, read_task_queue, read_workflow_state
from harness.pipeline import (
    Pipeline,
    PipelineConfig,
    PipelineError,
    extract_ui_output,
)
from harness.router import ModelSpec


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _agent_result(text: str) -> AgentResult:
    return AgentResult(
        stdout=text,
        stderr="",
        exit_code=0,
        usage=Usage(input_tokens=10, output_tokens=20, total_tokens=30),
        duration_ms=5,
    )


@pytest.fixture
def mock_router():
    router = MagicMock()
    router.resolve.side_effect = lambda stage: ModelSpec(model="mock-model", tier="worker")
    router.record = MagicMock()
    return router


@pytest.fixture
def agents_dir(tmp_path):
    d = tmp_path / "agents"
    d.mkdir()
    for name in ["researcher", "planner", "ui-design", "taskgen"]:
        (d / f"{name}.md").write_text(f"# {name} agent prompt")
    return d


@pytest.fixture
def project_dir(tmp_path):
    d = tmp_path / "project"
    d.mkdir()
    (d / "000-brief.md").write_text("# 项目需求\n\n做一个 TODO app\n")
    return d


def make_pipeline(project_dir, adapter, router, agents_dir, **config_kwargs):
    # Extract kwargs that belong to Pipeline.__init__ rather than PipelineConfig
    # so callers can pass linear_sync=... through this helper.
    pipeline_kwargs = {}
    if "linear_sync" in config_kwargs:
        pipeline_kwargs["linear_sync"] = config_kwargs.pop("linear_sync")
    config = PipelineConfig(project_dir=project_dir, log=lambda _msg: None, **config_kwargs)
    return Pipeline(
        config,
        adapter=adapter,
        router=router,
        agents_dir=agents_dir,
        **pipeline_kwargs,
    )


TASK_QUEUE_JSON = json.dumps(
    {
        "tasks": [
            {
                "id": "task-1",
                "name": "实现数据层",
                "description": "SQLite storage",
                "status": "pending",
                "dependencies": [],
                "kind": "logic",
            },
            {
                "id": "task-2",
                "name": "实现 UI",
                "description": "Todo list page",
                "status": "pending",
                "dependencies": ["task-1"],
                "kind": "ui",
            },
        ]
    }
)


# ---------------------------------------------------------------------------
# extract_ui_output
# ---------------------------------------------------------------------------


class TestExtractUiOutput:
    def test_marker_format(self):
        raw = "---SPEC---\nspec text\n---HTML---\n<html>x</html>\n---END---"
        spec, html = extract_ui_output(raw)
        assert spec == "spec text"
        assert html == "<html>x</html>"

    def test_marker_without_end(self):
        raw = "---HTML---\n<html>y</html>"
        spec, html = extract_ui_output(raw)
        assert spec == ""
        assert html == "<html>y</html>"

    def test_fenced_html_fallback(self):
        raw = "some spec\n```html\n<html>z</html>\n```"
        spec, html = extract_ui_output(raw)
        assert spec == "some spec"
        assert html == "<html>z</html>"

    def test_no_html_returns_raw(self):
        raw = "just prose, no html"
        spec, html = extract_ui_output(raw)
        assert spec == ""
        assert html == raw


# ---------------------------------------------------------------------------
# Individual phases
# ---------------------------------------------------------------------------


class TestPhases:
    def test_research_writes_artifact(self, project_dir, mock_router, agents_dir):
        adapter = MagicMock()
        adapter.run.return_value = _agent_result(
            "# 研究报告\n\n## 复用决策表\n\n"
            "| 候选 | URL | 成熟度 | 覆盖% | 决策 | 理由 |\n"
            "|------|-----|--------|-------|------|------|\n"
            "| foo/bar | https://github.com/foo/bar | active | 50 | wrap | 包装而非自研 |\n"
        )
        p = make_pipeline(project_dir, adapter, mock_router, agents_dir)

        path = p.phase_research()
        assert path.exists()
        assert "研究报告" in path.read_text()
        # Prompt should include the brief after ---INPUT---
        prompt_sent = adapter.run.call_args[0][0]
        assert "---INPUT---" in prompt_sent
        assert "TODO app" in prompt_sent
        mock_router.record.assert_called_with("research", adapter.run.return_value.usage)

    def test_research_requires_brief(self, tmp_path, mock_router, agents_dir):
        empty = tmp_path / "empty"
        empty.mkdir()
        p = make_pipeline(empty, MagicMock(), mock_router, agents_dir)
        with pytest.raises(PipelineError, match="000-brief"):
            p.phase_research()

    def test_research_rejects_report_without_table(self, project_dir, mock_router, agents_dir):
        # A report that lacks the 复用决策表 section must be rejected by
        # the gate, not silently advanced to plan.
        adapter = MagicMock()
        adapter.run.return_value = _agent_result("# 研究报告\n\n只是普通文字\n")
        p = make_pipeline(project_dir, adapter, mock_router, agents_dir)

        with pytest.raises(PipelineError, match="reuse-table gate"):
            p.phase_research()

    def test_research_rejects_empty_decision_table(self, project_dir, mock_router, agents_dir):
        # The header is present but no decision rows — also rejected.
        adapter = MagicMock()
        adapter.run.return_value = _agent_result(
            "# 研究报告\n\n## 复用决策表\n\n| 候选 | URL | 成熟度 | 覆盖% | 决策 | 理由 |\n|------|-----|--------|-------|------|------|\n"
        )
        p = make_pipeline(project_dir, adapter, mock_router, agents_dir)

        with pytest.raises(PipelineError, match="reuse-table gate"):
            p.phase_research()

    def test_research_rejects_header_without_table(self, project_dir, mock_router, agents_dir):
        # CRITICAL edge case (found in code review): the section header is
        # present so has_reuse_table() returns True, but the body is just
        # prose with no markdown table. parse_reuse_table raises
        # MissingReuseTableError; the gate must catch it and produce a
        # clean PipelineError instead of letting it propagate.
        adapter = MagicMock()
        adapter.run.return_value = _agent_result(
            "# 研究报告\n\n## 复用决策表\n\n只是一段普通说明文字，没有表格。\n"
        )
        p = make_pipeline(project_dir, adapter, mock_router, agents_dir)

        with pytest.raises(PipelineError, match="reuse-table gate"):
            p.phase_research()

    def test_research_accepts_well_formed_table(self, project_dir, mock_router, agents_dir):
        adapter = MagicMock()
        adapter.run.return_value = _agent_result(
            "# 研究报告\n\n"
            "## 复用决策表\n\n"
            "| 候选 | URL | 成熟度 | 覆盖% | 决策 | 理由 |\n"
            "|------|-----|--------|-------|------|------|\n"
            "| acme/widget | https://github.com/acme/widget | active | 80 | wrap | 覆盖核心功能 |\n"
        )
        p = make_pipeline(project_dir, adapter, mock_router, agents_dir)
        path = p.phase_research()
        assert path.exists()
        # The decision should have been recorded in usage.
        mock_router.record.assert_called_with("research", adapter.run.return_value.usage)
        # T12: phase_tasks must call LinearSync.sync_tasks_phase with
        # the parsed task queue and then print the progress link.
        from harness.linear_sync import LinearProject

        (project_dir / "002-plan.md").write_text("# 计划")
        adapter = MagicMock()
        adapter.run.return_value = _agent_result(TASK_QUEUE_JSON)
        fake_sync = MagicMock()
        fake_sync.sync_tasks_phase.return_value = LinearProject(
            id="proj-1", name="P", url="https://linear.app/x"
        )
        p = make_pipeline(project_dir, adapter, mock_router, agents_dir, linear_sync=fake_sync)
        p.phase_tasks()
        fake_sync.sync_tasks_phase.assert_called_once()
        fake_sync.print_progress_link.assert_called_once()
        adapter = MagicMock()
        adapter.run.return_value = _agent_result(
            "# 研究报告\n\n"
            "## 复用决策表\n\n"
            "| 候选 | URL | 成熟度 | 覆盖% | 决策 | 理由 |\n"
            "|------|-----|--------|-------|------|------|\n"
            "| acme/widget | https://github.com/acme/widget | active | 80 | wrap | 覆盖核心功能 |\n"
        )
        p = make_pipeline(project_dir, adapter, mock_router, agents_dir)
        path = p.phase_research()
        assert path.exists()
        # The decision should have been recorded in usage.
        mock_router.record.assert_called_with("research", adapter.run.return_value.usage)

    def test_plan_auto_approves_non_tty(self, project_dir, mock_router, agents_dir):
        (project_dir / "001-research-report.md").write_text("# 研究报告")
        adapter = MagicMock()
        adapter.run.return_value = _agent_result("# 计划")
        p = make_pipeline(project_dir, adapter, mock_router, agents_dir)

        with patch("harness.pipeline._is_interactive", return_value=False):
            path = p.phase_plan()
        assert path.exists()
        assert adapter.run.call_count == 1  # no feedback loop

    def test_plan_feedback_via_env(self, project_dir, mock_router, agents_dir, monkeypatch):
        (project_dir / "001-research-report.md").write_text("# 研究报告")
        adapter = MagicMock()
        adapter.run.return_value = _agent_result("# 计划")
        p = make_pipeline(project_dir, adapter, mock_router, agents_dir)

        monkeypatch.setenv("AUTODEV_PLAN_FEEDBACK", "简化数据库设计")
        with patch("harness.pipeline._is_interactive", return_value=False):
            p.phase_plan()

        # One initial call + one regeneration after env feedback
        assert adapter.run.call_count == 2
        second_prompt = adapter.run.call_args_list[1][0][0]
        assert "简化数据库设计" in second_prompt
        assert "---USER FEEDBACK---" in second_prompt

    def test_ui_writes_spec_and_preview(self, project_dir, mock_router, agents_dir):
        (project_dir / "002-plan.md").write_text("# 计划")
        adapter = MagicMock()
        adapter.run.return_value = _agent_result(
            "---SPEC---\nUI 规格\n---HTML---\n<html>ok</html>\n---END---"
        )
        p = make_pipeline(project_dir, adapter, mock_router, agents_dir)

        with patch("harness.pipeline._is_interactive", return_value=False):
            spec_path = p.phase_ui()

        assert "UI 规格" in spec_path.read_text()
        assert (project_dir / "preview" / "index.html").read_text() == "<html>ok</html>"

    def test_tasks_validates_and_persists_queue(self, project_dir, mock_router, agents_dir):
        (project_dir / "002-plan.md").write_text("# 计划")
        adapter = MagicMock()
        adapter.run.return_value = _agent_result(TASK_QUEUE_JSON)
        p = make_pipeline(project_dir, adapter, mock_router, agents_dir)

        path = p.phase_tasks()
        queue = read_task_queue(project_dir)
        assert path.exists()
        assert len(queue.tasks) == 2
        assert queue.tasks[0].title == "实现数据层"  # taskgen "name" alias

    def test_phase_tasks_creates_linear_issues(self, project_dir, mock_router, agents_dir):
        # T12: phase_tasks must call LinearSync.sync_tasks_phase with
        # the parsed task queue and then print the progress link.
        from harness.linear_sync import LinearProject

        (project_dir / "002-plan.md").write_text("# 计划")
        adapter = MagicMock()
        adapter.run.return_value = _agent_result(TASK_QUEUE_JSON)
        fake_sync = MagicMock()
        fake_sync.sync_tasks_phase.return_value = LinearProject(
            id="proj-1", name="P", url="https://linear.app/x"
        )
        p = make_pipeline(project_dir, adapter, mock_router, agents_dir, linear_sync=fake_sync)
        p.phase_tasks()
        fake_sync.sync_tasks_phase.assert_called_once()
        fake_sync.print_progress_link.assert_called_once()

    def test_tasks_rejects_queue_without_acceptance(self, project_dir, mock_router, agents_dir):
        # T11: a queue with empty acceptance must be rejected before
        # being persisted. Pipeline surfaces this as a clean
        # PipelineError so the user knows what to fix.
        (project_dir / "002-plan.md").write_text("# 计划")
        bad_queue = json.dumps({
            "tasks": [
                {
                    "id": "task-1",
                    "name": "X",
                    "description": "no acceptance",
                    "kind": "logic",
                    "status": "pending",
                    "dependencies": [],
                    "acceptance": [],
                }
            ]
        })
        adapter = MagicMock()
        adapter.run.return_value = _agent_result(bad_queue)
        p = make_pipeline(project_dir, adapter, mock_router, agents_dir)
        with pytest.raises(PipelineError, match="invalid task queue"):
            p.phase_tasks()

    def test_tasks_rejects_queue_with_unknown_kind(self, project_dir, mock_router, agents_dir):
        # T11: a queue with an unknown kind must also be rejected.
        (project_dir / "002-plan.md").write_text("# 计划")
        bad_queue = json.dumps({
            "tasks": [
                {
                    "id": "task-1",
                    "name": "X",
                    "kind": "frontend",  # not in whitelist
                    "status": "pending",
                    "dependencies": [],
                    "acceptance": ["$ pytest -q"],
                }
            ]
        })
        adapter = MagicMock()
        adapter.run.return_value = _agent_result(bad_queue)
        p = make_pipeline(project_dir, adapter, mock_router, agents_dir)
        with pytest.raises(PipelineError, match="invalid task queue"):
            p.phase_tasks()

    def test_tasks_rejects_invalid_json(self, project_dir, mock_router, agents_dir):
        (project_dir / "002-plan.md").write_text("# 计划")
        adapter = MagicMock()
        adapter.run.return_value = _agent_result("这不是 JSON")
        p = make_pipeline(project_dir, adapter, mock_router, agents_dir)

        with pytest.raises(PipelineError, match="invalid task queue"):
            p.phase_tasks()


# ---------------------------------------------------------------------------
# Develop phase — inner loop wiring
# ---------------------------------------------------------------------------


class TestDevelopPhase:
    def _prepare(self, project_dir):
        (project_dir / "002-plan.md").write_text("# 计划")
        (project_dir / "006-ui-spec.md").write_text("# UI spec")
        (project_dir / "003-task-queue.json").write_text(TASK_QUEUE_JSON)

    def test_runs_tasks_in_dependency_order(self, project_dir, mock_router, agents_dir):
        self._prepare(project_dir)
        p = make_pipeline(project_dir, MagicMock(), mock_router, agents_dir)

        executed = []

        def fake_inner_loop(*, project_dir, task_id, **_kw):
            executed.append(task_id)
            # Simulate the inner loop marking the task completed
            from harness.artifacts import TaskQueue, complete_task, write_task_queue

            queue = read_task_queue(project_dir)
            write_task_queue(project_dir, complete_task(queue, task_id))
            return []

        with patch("harness.pipeline.run_inner_loop", side_effect=fake_inner_loop):
            p.phase_develop()

        assert executed == ["task-1", "task-2"]
        queue = read_task_queue(project_dir)
        assert all(t.status == TaskStatus.COMPLETED for t in queue.tasks)

    def test_escalation_marks_blocked_and_skips_dependents(
        self, project_dir, mock_router, agents_dir
    ):
        self._prepare(project_dir)
        p = make_pipeline(project_dir, MagicMock(), mock_router, agents_dir)

        from harness.inner_loop import EscalationError

        def fail_first(*, project_dir, task_id, **_kw):
            raise EscalationError(task_id, 5, [])

        with patch("harness.pipeline.run_inner_loop", side_effect=fail_first):
            p.phase_develop()

        queue = read_task_queue(project_dir)
        statuses = {t.id: t.status for t in queue.tasks}
        assert statuses["task-1"] == TaskStatus.BLOCKED
        # task-2 depends on the blocked task-1 → left pending, not attempted
        assert statuses["task-2"] == TaskStatus.PENDING

    def test_develop_requires_queue(self, project_dir, mock_router, agents_dir):
        (project_dir / "002-plan.md").write_text("# 计划")
        p = make_pipeline(project_dir, MagicMock(), mock_router, agents_dir)
        with pytest.raises(PipelineError, match="003-task-queue"):
            p.phase_develop()


# ---------------------------------------------------------------------------
# Full-run orchestration + resume
# ---------------------------------------------------------------------------


class TestPipelineRun:
    def _adapter_for_full_run(self):
        """Adapter returning phase-appropriate output based on the prompt."""

        def run(prompt, *, model, cwd, timeout):
            if "# taskgen agent prompt" in prompt:
                return _agent_result(TASK_QUEUE_JSON)
            if "# ui-design agent prompt" in prompt:
                return _agent_result(
                    "---SPEC---\nspec\n---HTML---\n<html></html>\n---END---"
                )
            if "# researcher agent prompt" in prompt:
                return _agent_result(
                    "# 研究报告\n\n"
                    "## 复用决策表\n\n"
                    "| 候选 | URL | 成熟度 | 覆盖% | 决策 | 理由 |\n"
                    "|------|-----|--------|-------|------|------|\n"
                    "| foo/bar | https://github.com/foo/bar | active | 50 | wrap | 包装而非自研 |\n"
                )
            return _agent_result("# 输出")

        adapter = MagicMock()
        adapter.run.side_effect = run
        return adapter

    @staticmethod
    def _complete_all_inner_loop(*, project_dir, task_id, **_kw):
        """Fake run_inner_loop that just marks the task completed."""
        from harness.artifacts import complete_task, write_task_queue

        queue = read_task_queue(project_dir)
        write_task_queue(project_dir, complete_task(queue, task_id))
        return []

    def test_full_run_saves_state_and_completes(self, project_dir, mock_router, agents_dir):
        adapter = self._adapter_for_full_run()
        p = make_pipeline(project_dir, adapter, mock_router, agents_dir)

        with patch("harness.pipeline._is_interactive", return_value=False), patch(
            "harness.pipeline.run_inner_loop", side_effect=self._complete_all_inner_loop
        ):
            p.run()

        state = read_workflow_state(project_dir)
        assert state.current_phase == Phase.DEVELOP
        assert set(state.completed_phases) == {
            Phase.RESEARCH, Phase.PLAN, Phase.UI, Phase.TASKS, Phase.DEVELOP,
        }

    def test_resume_skips_completed_phases(self, project_dir, mock_router, agents_dir):
        # Artifacts already exist for research + plan → resume should start at ui
        (project_dir / "001-research-report.md").write_text("# 研究报告")
        (project_dir / "002-plan.md").write_text("# 计划")

        adapter = self._adapter_for_full_run()
        p = make_pipeline(project_dir, adapter, mock_router, agents_dir)

        with patch("harness.pipeline._is_interactive", return_value=False), patch(
            "harness.pipeline.run_inner_loop", side_effect=self._complete_all_inner_loop
        ):
            p.run()

        # researcher/planner prompts never sent
        prompts = [c[0][0] for c in adapter.run.call_args_list]
        assert not any("# researcher agent prompt" in pr for pr in prompts)
        assert not any("# planner agent prompt" in pr for pr in prompts)
        assert any("# ui-design agent prompt" in pr for pr in prompts)

    def test_explicit_start_phase(self, project_dir, mock_router, agents_dir):
        (project_dir / "002-plan.md").write_text("# 计划")
        adapter = self._adapter_for_full_run()
        p = make_pipeline(project_dir, adapter, mock_router, agents_dir)

        with patch("harness.pipeline._is_interactive", return_value=False), patch(
            "harness.pipeline.run_inner_loop", side_effect=self._complete_all_inner_loop
        ):
            p.run(start_phase=Phase.TASKS)

        prompts = [c[0][0] for c in adapter.run.call_args_list]
        assert not any("# ui-design agent prompt" in pr for pr in prompts)
        assert any("# taskgen agent prompt" in pr for pr in prompts)


# ---------------------------------------------------------------------------
# CLI (python -m harness)
# ---------------------------------------------------------------------------


class TestCli:
    def test_config_subcommand(self, capsys):
        from harness.__main__ import main

        assert main(["config"]) == 0
        assert "Model Routing Table" in capsys.readouterr().out

    def test_status_without_state(self, tmp_path, capsys):
        from harness.__main__ import main

        assert main(["--status", str(tmp_path)]) == 1

    def test_brief_created_from_args(self, tmp_path):
        from harness.__main__ import main

        with patch("harness.pipeline.Pipeline.run"):
            rc = main([str(tmp_path), "--", "做一个", "笔记 app"])
        assert rc == 0
        brief = (tmp_path / "000-brief.md").read_text()
        assert "做一个 笔记 app" in brief


# ---------------------------------------------------------------------------
# Slow acceptance smoke (T07 验收 — real model, run manually)
# ---------------------------------------------------------------------------


class TestPipelineSmoke:
    @pytest.mark.slow
    @pytest.mark.skip(reason="T07 acceptance smoke — needs real claude CLI; run manually")
    def test_test_mode_todo_app(self, tmp_path):
        """`python -m harness --test tmp -- '做一个 TODO web app'` full run."""
        from harness.__main__ import main

        rc = main(["--test", str(tmp_path), "--", "做一个 TODO web app"])
        assert rc == 0
