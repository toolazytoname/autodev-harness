"""T45 — Open Design probe + topic-aware direction generation.

Covers ``harness.open_design`` module: ``is_available()``, ``Direction``,
``parse_direction_list()``, ``project_name_for()``.

Adapter-level MCP / open_design adapters live in
``test_open_design_adapter.py``.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict
from unittest.mock import patch

import pytest

from harness import open_design as od


# ---------------------------------------------------------------------------
# is_available
# ---------------------------------------------------------------------------


class TestIsAvailable:
    def test_returns_false_when_daemon_command_missing(self):
        """FileNotFoundError at Popen = OD not installed."""
        with patch.object(od, "DEFAULT_COMMAND", ("/no/such/path",)):
            with patch.object(od.subprocess, "Popen", side_effect=FileNotFoundError):
                assert od.is_available() is False

    def test_returns_false_when_daemon_does_not_respond(self):
        """Daemon CLI exists but doesn't speak MCP JSON-RPC."""
        fake_proc = _FakePopen(responses=[], exit_code=0, stdout=b"hello\n")
        with patch.object(od, "_daemon_command_and_env", return_value=(["fake"], {})):
            with patch.object(od.subprocess, "Popen", return_value=fake_proc):
                assert od.is_available() is False

    def test_returns_true_on_valid_initialize(self):
        """Daemon returns a JSON-RPC reply with a 'result' field."""
        reply = json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "result": {
                    "protocolVersion": "2024-11-05",
                    "serverInfo": {"name": "open-design", "version": "0.2.0"},
                },
            }
        )
        fake_proc = _FakePopen(
            responses=[],
            exit_code=0,
            stdout=(reply + "\n").encode(),
        )
        with patch.object(od, "_daemon_command_and_env", return_value=(["fake"], {})):
            with patch.object(od.subprocess, "Popen", return_value=fake_proc):
                assert od.is_available() is True


# ---------------------------------------------------------------------------
# Direction parsing
# ---------------------------------------------------------------------------


VALID_DIRECTIONS_JSON = json.dumps(
    [
        {
            "slug": "student-growth-tracker",
            "label": "学生成长追踪看板",
            "module": "minimalist-ui",
            "intent": "Per-student trend lines across monthly tests",
            "sections": ["trend line", "score comparison", "PR badges"],
        },
        {
            "slug": "data-entry-grid",
            "label": "月度成绩批量录入",
            "module": "industrial-brutalist-ui",
            "intent": "Dense Excel-style score-entry grid",
            "sections": ["import button", "row editor", "validation summary"],
        },
        {
            "slug": "course-timeline",
            "label": "课程时间线",
            "module": "gpt-taste",
            "intent": "Shareable child progress reel / poster",
            "sections": ["timeline", "poster overlay", "share controls"],
        },
    ]
)


class TestParseDirectionList:
    def test_parses_json_array(self):
        result = od.parse_direction_list(VALID_DIRECTIONS_JSON)
        assert len(result) == 3
        assert all(isinstance(d, od.Direction) for d in result)

    def test_preserves_fields(self):
        result = od.parse_direction_list(VALID_DIRECTIONS_JSON)
        first = result[0]
        assert first.slug == "student-growth-tracker"
        assert first.label == "学生成长追踪看板"
        assert first.module == "minimalist-ui"
        assert first.intent.startswith("Per-student")
        assert first.sections == ["trend line", "score comparison", "PR badges"]

    def test_parses_json_in_fence(self):
        wrapped = "```json\n" + VALID_DIRECTIONS_JSON + "\n```"
        result = od.parse_direction_list(wrapped)
        assert len(result) == 3

    def test_dedupes_by_slug_keeping_first(self):
        dup = json.dumps(
            [
                {"slug": "a", "label": "A", "module": "minimalist-ui",
                 "intent": "...", "sections": ["x"]},
                {"slug": "a", "label": "A2", "module": "gpt-taste",
                 "intent": "other", "sections": ["y"]},
                {"slug": "b", "label": "B", "module": "industrial-brutalist-ui",
                 "intent": "...", "sections": ["z"]},
            ]
        )
        result = od.parse_direction_list(dup)
        slugs = [d.slug for d in result]
        assert slugs == ["a", "b"]

    def test_skips_rows_missing_required_fields(self):
        # Both rows are missing required keys — neither survives.
        body = json.dumps(
            [
                {"slug": "a", "label": "A", "module": "x", "intent": "..."},  # no sections
                {"slug": "b", "label": "B", "intent": "...", "sections": []},  # no module
            ]
        )
        with pytest.raises(ValueError):
            od.parse_direction_list(body)

    def test_partial_survivors_kept(self):
        # One bad row (missing sections), one valid row → keep the valid one.
        body = json.dumps(
            [
                {"slug": "a", "label": "A", "module": "(none)", "intent": "..."},  # no sections
                {"slug": "b", "label": "B", "module": "minimalist-ui", "intent": "...", "sections": ["x"]},
            ]
        )
        result = od.parse_direction_list(body)
        assert [d.slug for d in result] == ["b"]  # only the second survived

    def test_skips_rows_with_unknown_module(self):
        body = json.dumps(
            [
                {
                    "slug": "a", "label": "A", "module": "non-existent-style",
                    "intent": "...", "sections": ["x"],
                },
                {
                    "slug": "b", "label": "B", "module": "minimalist-ui",
                    "intent": "...", "sections": ["y"],
                },
            ]
        )
        result = od.parse_direction_list(body)
        slugs = [d.slug for d in result]
        assert slugs == ["b"]

    def test_empty_or_garbage_input_raises(self):
        with pytest.raises(ValueError):
            od.parse_direction_list("")
        with pytest.raises(ValueError):
            od.parse_direction_list("not json at all")
        with pytest.raises(ValueError):
            od.parse_direction_list(json.dumps({"not": "an array"}))

    def test_lowercases_slug(self):
        body = json.dumps(
            [
                {
                    "slug": "Mixed-Case_SLUG", "label": "X", "module": "minimalist-ui",
                    "intent": "...", "sections": ["x"],
                },
            ]
        )
        result = od.parse_direction_list(body)
        # slug normalization for filesystem safety
        assert result[0].slug == "mixed-case-slug"


# ---------------------------------------------------------------------------
# project_name_for
# ---------------------------------------------------------------------------


class TestProjectNameFor:
    def test_deterministic_on_same_seed(self):
        a = od.project_name_for("student-growth", "brief12345", when="2026-07-10")
        b = od.project_name_for("student-growth", "brief12345", when="2026-07-10")
        assert a == b

    def test_varies_with_slug(self):
        a = od.project_name_for("alpha", "brief", when="2026-07-10")
        b = od.project_name_for("beta", "brief", when="2026-07-10")
        assert a != b

    def test_contains_harness_prefix_and_short_seed(self):
        name = od.project_name_for("growth", "abc12345", when="2026-07-10")
        assert name.startswith("harness-ui-")
        assert "growth" in name
        assert "abc12345" in name  # short seed is included for uniqueness


# ---------------------------------------------------------------------------
# Direction dataclass
# ---------------------------------------------------------------------------


class TestDirectionDataclass:
    def test_round_trip_dict(self):
        d = od.Direction(
            slug="a", label="A", module="minimalist-ui",
            intent="...", sections=["x"],
        )
        d_dict = asdict(d)
        assert d_dict["slug"] == "a"
        assert d_dict["label"] == "A"

    def test_to_dict_for_harness_pipeline(self):
        """Direction.to_dict() shape must be `{slug,label,module,...}` so it
        can slot into the existing _build_ui_prompt path."""
        d = od.Direction(
            slug="a", label="A", module="minimalist-ui",
            intent="...", sections=["x", "y"],
        )
        out = d.to_dict()
        assert out.keys() >= {"slug", "label", "module"}
        assert out["intent"] == "..."
        assert out["sections"] == ["x", "y"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _FakePopen:
    """Minimal Popen lookalike for is_available() tests."""

    def __init__(self, *, responses, exit_code=0, stdout=b""):
        self.responses = responses
        self.returncode = exit_code
        self._stdout = stdout
        self.stdin = _FakeStdin()
        self.stderr = _FakeStderr()

    def communicate(self, input=None, timeout=None):  # noqa: A002
        # Drain stdin so the daemon doesn't block on close.
        if input is not None:
            self.stdin.buffer.append(input)
        return self._stdout, b""

    def terminate(self):
        pass

    def kill(self):
        pass


class _FakeStdin:
    def __init__(self):
        self.buffer = []

    def write(self, data):
        self.buffer.append(data)

    def flush(self):
        pass

    def close(self):
        pass


class _FakeStderr:
    def __init__(self):
        self.closed = False

    def read(self):
        return b""
