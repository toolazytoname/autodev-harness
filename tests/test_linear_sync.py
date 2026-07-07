"""Tests for harness.linear_sync — Linear MCP integration + local fallback.

Per MASTER-PLAN §3 (P6) and TASKS T12: tasks phase creates project+issues
via Linear; inner loop status transitions are mirrored; without an
API key the harness degrades to a local in-memory store so the
pipeline never blocks on missing credentials.

These tests pin down:
- The ``LinearClient`` protocol surface (used by both MCP and Local impls)
- Project + issue lifecycle in the Local impl
- Graceful degradation: ``get_linear_client()`` returns Local when
  no key is set
- The ``LinearSync`` orchestrator's state transitions
- Pipeline integration: tasks phase creates issues; develop updates
  them; gate pass marks DONE; escalation marks BLOCKED
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from harness.linear_sync import (
    LocalLinearClient,
    LinearClient,
    LinearIssue,
    LinearProject,
    LinearState,
    LinearSync,
    get_linear_client,
    is_linear_configured,
)


# ---------------------------------------------------------------------------
# LocalLinearClient — the in-memory + JSON-on-disk implementation
# ---------------------------------------------------------------------------


class TestLocalLinearClient:
    def test_starts_empty(self):
        client = LocalLinearClient()
        assert client.projects == []
        assert client.all_issues() == []

    def test_create_project(self):
        client = LocalLinearClient()
        project = client.create_project("Test project")
        assert project.name == "Test project"
        assert project.id  # non-empty
        assert project in client.projects

    def test_create_issue_in_project(self):
        client = LocalLinearClient()
        project = client.create_project("P")
        issue = client.create_issue(
            project_id=project.id,
            title="T1",
            body="do the thing",
        )
        assert issue.title == "T1"
        assert issue.state is LinearState.BACKLOG
        assert issue.project_id == project.id

    def test_update_issue_state(self):
        client = LocalLinearClient()
        project = client.create_project("P")
        issue = client.create_issue(project_id=project.id, title="T1")
        client.update_issue_state(issue.id, LinearState.IN_PROGRESS)
        assert client.get_issue(issue.id).state is LinearState.IN_PROGRESS

    def test_add_comment(self):
        client = LocalLinearClient()
        project = client.create_project("P")
        issue = client.create_issue(project_id=project.id, title="T1")
        client.add_comment(issue.id, "Looks good")
        comments = client.get_issue(issue.id).comments
        assert len(comments) == 1
        assert comments[0].body == "Looks good"

    def test_persists_to_disk(self, tmp_path):
        path = tmp_path / "linear.json"
        client = LocalLinearClient(path=path)
        project = client.create_project("P")
        client.create_issue(project_id=project.id, title="T1")
        client.flush()

        # Reload from disk
        client2 = LocalLinearClient(path=path)
        assert len(client2.projects) == 1
        assert len(client2.all_issues()) == 1

    def test_dependencies_linked(self):
        client = LocalLinearClient()
        project = client.create_project("P")
        a = client.create_issue(project_id=project.id, title="A")
        b = client.create_issue(
            project_id=project.id, title="B", blocked_by=[a.id]
        )
        assert b.blocked_by == [a.id]

    def test_unknown_issue_raises(self):
        client = LocalLinearClient()
        with pytest.raises(KeyError):
            client.update_issue_state("ghost-id", LinearState.DONE)


# ---------------------------------------------------------------------------
# Factory: get_linear_client picks the right backend
# ---------------------------------------------------------------------------


class TestGetLinearClient:
    def test_no_api_key_returns_local(self, monkeypatch):
        monkeypatch.delenv("LINEAR_API_KEY", raising=False)
        client = get_linear_client()
        assert isinstance(client, LocalLinearClient)

    def test_explicit_no_key_returns_local(self):
        client = get_linear_client(api_key=None)
        assert isinstance(client, LocalLinearClient)

    def test_api_key_returns_mcp_client(self, monkeypatch):
        # When a key is provided AND an MCP backend is available,
        # we get the MCP client. We don't need a real MCP server in
        # tests — the factory is allowed to import the class and
        # instantiate it; later operations would fail without one.
        monkeypatch.setenv("LINEAR_API_KEY", "lin_api_xxx")
        with patch("harness.linear_sync._McpLinearClient") as mcp_cls:
            mcp_cls.return_value = "fake-mcp-client"
            client = get_linear_client()
            assert client == "fake-mcp-client"
            mcp_cls.assert_called_once_with("lin_api_xxx")

    def test_is_linear_configured(self, monkeypatch):
        monkeypatch.delenv("LINEAR_API_KEY", raising=False)
        assert is_linear_configured() is False
        monkeypatch.setenv("LINEAR_API_KEY", "x")
        assert is_linear_configured() is True


# ---------------------------------------------------------------------------
# LinearSync — high-level orchestrator
# ---------------------------------------------------------------------------


class TestLinearSync:
    def test_sync_tasks_creates_project_and_issues(self, tmp_path):
        client = LocalLinearClient()
        sync = LinearSync(client=client, project_dir=tmp_path)
        project = sync.sync_tasks_phase(
            brief="Make a TODO app",
            tasks=[
                {"id": "task-1", "title": "Init", "kind": "infra", "acceptance": ["$ npm init"]},
                {"id": "task-2", "title": "UI",   "kind": "ui",    "acceptance": ["Visit /"]},
            ],
        )
        assert project.name  # was created
        issues = client.all_issues()
        assert len(issues) == 2
        # The IDs returned by taskgen must be preserved so downstream
        # status updates can find them.
        assert {i.linear_key for i in issues} == {"task-1", "task-2"}
        # Dependencies are propagated when present
        sync_2 = LinearSync(client=client, project_dir=tmp_path)
        sync_2.sync_tasks_phase(
            brief="x",
            tasks=[
                {"id": "task-1", "title": "Init", "kind": "infra",
                 "acceptance": ["$ npm init"]},
                {"id": "task-2", "title": "Build", "kind": "logic",
                 "acceptance": ["$ pytest"],
                 "dependencies": ["task-1"]},
            ],
        )
        all_issues = {i.linear_key: i for i in client.all_issues()}
        # The MCP client uses the second sync (with deps), so we re-check
        # only that the second-pass deps got applied to the surviving issue.
        # (LocalLinearClient keeps history, so there are 4 issues total.)
        build_issues = [i for k, i in all_issues.items() if k == "task-2"]
        assert any(b.blocked_by for b in build_issues)

    def test_mark_in_progress(self, tmp_path):
        client = LocalLinearClient()
        sync = LinearSync(client=client, project_dir=tmp_path)
        sync.sync_tasks_phase(brief="b", tasks=[{"id": "task-1", "title": "X", "kind": "logic", "acceptance": ["$ pytest"]}])
        sync.mark_in_progress("task-1")
        issue = client.get_issue("task-1")
        assert issue.state is LinearState.IN_PROGRESS

    def test_mark_done_with_score_card_summary(self, tmp_path):
        client = LocalLinearClient()
        sync = LinearSync(client=client, project_dir=tmp_path)
        sync.sync_tasks_phase(brief="b", tasks=[{"id": "task-1", "title": "X", "kind": "logic", "acceptance": ["$ pytest"]}])
        sync.mark_done(
            "task-1",
            score_card_summary="correctness:0.9 test:0.85 boundary:0.8",
        )
        issue = client.get_issue("task-1")
        assert issue.state is LinearState.DONE
        assert any("correctness:0.9" in c.body for c in issue.comments)

    def test_mark_blocked_with_blockers(self, tmp_path):
        client = LocalLinearClient()
        sync = LinearSync(client=client, project_dir=tmp_path)
        sync.sync_tasks_phase(brief="b", tasks=[{"id": "task-1", "title": "X", "kind": "logic", "acceptance": ["$ pytest"]}])
        sync.mark_blocked("task-1", blockers=["coverage 65% < 80%", "flaky test"])
        issue = client.get_issue("task-1")
        assert issue.state is LinearState.BLOCKED
        comment_text = "\n".join(c.body for c in issue.comments)
        assert "coverage 65%" in comment_text
        assert "flaky test" in comment_text

    def test_mark_done_unknown_issue_is_noop(self, tmp_path):
        client = LocalLinearClient()
        sync = LinearSync(client=client, project_dir=tmp_path)
        # Should NOT raise — unknown ids are silently ignored so the
        # inner loop can complete a gate pass even if the sync
        # backend missed a creation event.
        sync.mark_done("never-existed", score_card_summary="x")
        # And mark_in_progress is the same
        sync.mark_in_progress("never-existed")
        sync.mark_blocked("never-existed", blockers=["x"])

    def test_progress_link_printed(self, tmp_path, capsys):
        client = LocalLinearClient()
        sync = LinearSync(client=client, project_dir=tmp_path)
        sync.print_progress_link()
        captured = capsys.readouterr()
        # In local mode there's no URL, but the link banner is still
        # printed so the human sees the sync status.
        assert "Linear" in captured.out
        assert "local" in captured.out.lower()

    def test_progress_link_uses_mcp_url_when_mcp(self, tmp_path, capsys):
        # Fake MCP client that returns a real-looking URL
        class FakeMcp:
            def __init__(self):
                self._projects = {}
                self._issues = []

            def create_project(self, name):
                p = LinearProject(id="proj-1", name=name, url="https://linear.app/x/proj-1")
                self._projects[p.id] = p
                return p

            def create_issue(self, **kw):
                issue = LinearIssue(
                    id="iss-1", linear_key=kw.get("linear_key", "iss-1"),
                    project_id=kw["project_id"], title=kw.get("title", "x"),
                    body=kw.get("body", ""),
                )
                self._issues.append(issue)
                return issue

            def update_issue_state(self, *a, **kw): pass
            def add_comment(self, *a, **kw): pass
            def get_issue(self, *a, **kw): raise KeyError
            def all_issues(self): return self._issues
            def projects(self): return list(self._projects.values())
            def get_project_url(self, project_id):
                return f"https://linear.app/test/proj/{project_id}"

        sync = LinearSync(client=FakeMcp(), project_dir=tmp_path)
        sync.sync_tasks_phase(brief="b", tasks=[{"id": "task-1", "title": "X", "kind": "logic", "acceptance": ["$ pytest"]}])
        sync.print_progress_link()
        captured = capsys.readouterr()
        assert "https://linear.app" in captured.out


# ---------------------------------------------------------------------------
# Pipeline integration
# ---------------------------------------------------------------------------


class TestPipelineIntegration:
    def test_phase_tasks_creates_linear_issues(self, tmp_path):
        # The pipeline's phase_tasks must call LinearSync.sync_tasks_phase
        # with the parsed task queue. We verify by spying on the
        # sync object.
        from unittest.mock import MagicMock
        from harness.adapters.base import AgentResult, Usage
        from harness.pipeline import Pipeline, PipelineConfig
        from harness.router import ModelSpec

        project_dir = tmp_path / "proj"
        project_dir.mkdir()
        (project_dir / "002-plan.md").write_text("# plan")

        adapter = MagicMock()
        adapter.run.return_value = _agent_result_with_acceptance()

        mock_router = MagicMock()
        mock_router.resolve.side_effect = lambda stage: ModelSpec(model="mock", tier="worker")

        agents_dir = tmp_path / "agents"
        agents_dir.mkdir()
        for name in ["researcher", "planner", "ui-design", "taskgen"]:
            (agents_dir / f"{name}.md").write_text(f"# {name}")

        fake_sync = MagicMock()
        fake_project = LinearProject(id="proj-1", name="P", url="https://linear.app/x")
        fake_sync.sync_tasks_phase.return_value = fake_project

        p = Pipeline(
            config=PipelineConfig(project_dir=project_dir, log=lambda m: None),
            adapter=adapter,
            router=mock_router,
            agents_dir=agents_dir,
            linear_sync=fake_sync,
        )
        p.phase_tasks()
        # Linear was called with the parsed task queue
        fake_sync.sync_tasks_phase.assert_called_once()
        # Progress link was printed
        fake_sync.print_progress_link.assert_called_once()


def _agent_result_with_acceptance() -> "AgentResult":
    """Return an AgentResult whose stdout is a valid task queue JSON."""
    from harness.adapters.base import AgentResult, Usage

    body = json.dumps({
        "tasks": [
            {
                "id": "task-1",
                "name": "Init",
                "description": "init",
                "status": "pending",
                "kind": "infra",
                "dependencies": [],
                "acceptance": ["$ npm init"],
            }
        ]
    })
    return AgentResult(
        stdout=body,
        stderr="",
        exit_code=0,
        usage=Usage(input_tokens=1, output_tokens=1, total_tokens=2),
        duration_ms=1,
    )
