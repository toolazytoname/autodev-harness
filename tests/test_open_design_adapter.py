"""T45 — OpenDesignAdapter unit tests.

Covers ``harness.adapters.open_design``:
  - ``OpenDesignAdapter.run`` (UI brief → OD project → run → HTML envelope)
  - failure modes (daemon unreachable, run failed/canceled, polling timeout)
  - the ``---SPEC---/---HTML---/---END---`` envelope that lets
    ``UIPhase.extract_ui_output`` reuse the existing extraction path.

MCP protocol tests live alongside (no subprocess shell-out) by
injecting a fake ``OpenDesignMCPClient`` via monkeypatch.
"""

from __future__ import annotations

import time
from typing import Any
from unittest.mock import MagicMock

import pytest

from harness.adapters import open_design as od_adapter
from harness.adapters.base import AdapterError, AgentResult


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_client(monkeypatch):
    """Return a MagicMock standing in for ``OpenDesignMCPClient``.

    Tests configure ``.create_project/.start_run/.get_run/.get_artifact``
    return values, then call ``adapter.run(...)`` and assert on output.
    """
    instance = MagicMock()
    instance.__enter__ = lambda self: self
    instance.__exit__ = lambda self, *a: None
    monkeypatch.setattr(
        od_adapter, "OpenDesignMCPClient", lambda *a, **kw: instance
    )
    return instance


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


class TestOpenDesignAdapterHappyPath:
    def test_emits_spec_html_envelope_in_stdout(self, fake_client, monkeypatch):
        fake_client.create_project.return_value = {
            "project_id": "proj-1", "name": "harness-ui-test"
        }
        fake_client.start_run.return_value = {"run_id": "run-1"}
        fake_client.get_run.return_value = {
            "status": "succeeded",
            "previewUrl": "http://localhost:8888",
        }
        fake_client.get_artifact.return_value = {
            "entry": "index.html",
            "files": {
                "index.html": "<!DOCTYPE html><h1>growth dashboard</h1>\n",
                "spec.md": "# UI Spec\n学生成长追踪看板\n",
            },
        }
        # Crop the poll-loop sleeps so tests stay quick.
        monkeypatch.setattr(od_adapter.time, "sleep", lambda *_: None)

        adapter = od_adapter.OpenDesignAdapter()
        result = adapter.run(
            "make a growing dashboard",
            model="haiku-4-5",
            cwd=None,
            timeout=60,
        )

        assert isinstance(result, AgentResult)
        assert "---SPEC---" in result.stdout
        assert "---HTML---" in result.stdout
        assert "---END---" in result.stdout
        # Spec body should be the spec.md content; HTML body the index.html.
        spec = result.stdout.split("---SPEC---", 1)[1].split("---HTML---", 1)[0]
        body = result.stdout.split("---HTML---", 1)[1].split("---END---", 1)[0]
        assert "学生成长追踪看板" in spec
        assert "DOCTYPE html" in body
        assert "growth dashboard" in body

    def test_creates_one_project_per_run(self, fake_client, monkeypatch):
        fake_client.create_project.return_value = {"project_id": "p"}
        fake_client.start_run.return_value = {"run_id": "r"}
        fake_client.get_run.return_value = {"status": "succeeded"}
        fake_client.get_artifact.return_value = {
            "files": {"index.html": "<!doctype html>", "spec.md": "spec"}
        }
        monkeypatch.setattr(od_adapter.time, "sleep", lambda *_: None)

        adapter = od_adapter.OpenDesignAdapter()
        adapter.run("brief", model="haiku-4-5", cwd=None, timeout=60)

        # Sequence: create_project → start_run → ... → get_artifact.
        order = [c[0] for c in fake_client.method_calls]
        assert "create_project" in order
        assert "start_run" in order
        assert "get_artifact" in order
        # And create_project comes before start_run.
        assert order.index("create_project") < order.index("start_run")

    def test_polls_get_run_until_succeeded(self, fake_client, monkeypatch):
        fake_client.create_project.return_value = {"project_id": "p"}
        fake_client.start_run.return_value = {"run_id": "r"}
        # Three "running" then "succeeded".
        fake_client.get_run.side_effect = [
            {"status": "running"},
            {"status": "running"},
            {"status": "running"},
            {"status": "succeeded"},
        ]
        fake_client.get_artifact.return_value = {
            "files": {"index.html": "<!doctype html>", "spec.md": "spec"}
        }
        monkeypatch.setattr(od_adapter.time, "sleep", lambda *_: None)

        adapter = od_adapter.OpenDesignAdapter()
        adapter.run("brief", model="haiku-4-5", cwd=None, timeout=60)

        # 4 polls (3 running + 1 succeeded).
        assert fake_client.get_run.call_count == 4

    def test_passes_prompt_to_start_run(self, fake_client, monkeypatch):
        fake_client.create_project.return_value = {"project_id": "p"}
        fake_client.start_run.return_value = {"run_id": "r"}
        fake_client.get_run.return_value = {"status": "succeeded"}
        fake_client.get_artifact.return_value = {
            "files": {"index.html": "x", "spec.md": "y"}
        }
        monkeypatch.setattr(od_adapter.time, "sleep", lambda *_: None)

        adapter = od_adapter.OpenDesignAdapter()
        adapter.run("make a data-entry grid", model="haiku-4-5", cwd=None, timeout=60)

        # The prompt string itself is forwarded to start_run.
        start_args = fake_client.start_run.call_args
        assert "make a data-entry grid" in str(start_args)


# ---------------------------------------------------------------------------
# Failure modes
# ---------------------------------------------------------------------------


class TestOpenDesignAdapterFailureModes:
    def test_daemon_spawn_failure_raises_adapter_error(self, monkeypatch):
        def boom(*a, **kw):
            return _BrokenClient()

        monkeypatch.setattr(od_adapter, "OpenDesignMCPClient", boom)
        adapter = od_adapter.OpenDesignAdapter()
        with pytest.raises(AdapterError):
            adapter.run("anything", model="haiku-4-5", cwd=None, timeout=60)

    def test_run_status_failed_raises_adapter_error(self, fake_client, monkeypatch):
        fake_client.create_project.return_value = {"project_id": "p"}
        fake_client.start_run.return_value = {"run_id": "r"}
        fake_client.get_run.return_value = {
            "status": "failed", "error": "agent crashed"
        }
        adapter = od_adapter.OpenDesignAdapter()
        with pytest.raises(AdapterError) as exc_info:
            adapter.run("anything", model="haiku-4-5", cwd=None, timeout=60)
        assert "agent crashed" in str(exc_info.value) or "failed" in str(exc_info.value).lower()

    def test_run_status_canceled_raises_adapter_error(self, fake_client, monkeypatch):
        fake_client.create_project.return_value = {"project_id": "p"}
        fake_client.start_run.return_value = {"run_id": "r"}
        fake_client.get_run.return_value = {"status": "canceled"}
        adapter = od_adapter.OpenDesignAdapter()
        with pytest.raises(AdapterError):
            adapter.run("anything", model="haiku-4-5", cwd=None, timeout=60)

    def test_poll_budget_exhausted_raises_adapter_error(self, fake_client, monkeypatch):
        """Stuck in 'running' beyond the adapter's poll budget ⇒ AdapterError."""
        # Always running; the adapter must time out and raise.
        fake_client.create_project.return_value = {"project_id": "p"}
        fake_client.start_run.return_value = {"run_id": "r"}
        fake_client.get_run.return_value = {"status": "running"}
        # Force a tiny run budget so the test exits fast.
        monkeypatch.setattr(od_adapter, "_POLL_BUDGET_SECONDS", 0.05)
        monkeypatch.setattr(od_adapter, "_POLL_INTERVAL_SECONDS", 0.01)

        adapter = od_adapter.OpenDesignAdapter()
        with pytest.raises(AdapterError) as exc_info:
            adapter.run("anything", model="haiku-4-5", cwd=None, timeout=60)
        msg = str(exc_info.value).lower()
        assert "budget exhausted" in msg or "exhausted" in msg or "timeout" in msg


# ---------------------------------------------------------------------------
# Convenience helpers
# ---------------------------------------------------------------------------


class TestConvenienceHelpers:
    def test_project_name_for_round_trip(self):
        from harness.open_design import project_name_for
        a = project_name_for("growth", "brief12345", when="2026-07-10")
        assert "growth" in a
        assert "20260710" in a


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _BrokenClient:
    """Stands in for OpenDesignMCPClient but raises on every attribute access."""

    def __enter__(self):
        raise FileNotFoundError("Open Design not installed")

    def __exit__(self, *a):
        return False

    def __getattr__(self, name):
        raise AdapterError(f"daemon unavailable: {name}")
