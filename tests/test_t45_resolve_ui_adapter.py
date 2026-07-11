"""T45 — ``__main__._resolve_ui_adapter`` smoke tests."""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from harness.__main__ import _resolve_ui_adapter


class TestResolveUIAdapter:
    def setup_method(self) -> None:
        # Always start each test from a clean env.
        for key in ("AUTODEV_UI_OD",):
            os.environ.pop(key, None)

    def test_force_off_returns_none(self, capsys):
        os.environ["AUTODEV_UI_OD"] = "0"
        result = _resolve_ui_adapter()
        assert result is None
        captured = capsys.readouterr()
        assert "skipped" in captured.out.lower()

    def test_force_on_returns_open_design_adapter(self, capsys):
        os.environ["AUTODEV_UI_OD"] = "1"
        # Avoid touching the real daemon — the auto-detect path would
        # otherwise try to spawn it. We force the override branch.
        with patch("harness.open_design.is_available", return_value=True):
            from harness.adapters.open_design import OpenDesignAdapter

            result = _resolve_ui_adapter()
        assert isinstance(result, OpenDesignAdapter)
        captured = capsys.readouterr()
        assert "enabled" in captured.out.lower()

    def test_force_on_does_not_probe_when_no_override(self, capsys):
        # The "1" override should NOT consult is_available()
        # (we trust the user). Make is_available explode to assert.
        os.environ["AUTODEV_UI_OD"] = "1"
        with patch(
            "harness.open_design.is_available",
            side_effect=AssertionError("is_available should not be called"),
        ):
            from harness.adapters.open_design import OpenDesignAdapter

            result = _resolve_ui_adapter()
        assert isinstance(result, OpenDesignAdapter)

    def test_auto_detect_falls_back_when_unavailable(self, capsys):
        os.environ.pop("AUTODEV_UI_OD", None)
        with patch("harness.open_design.is_available", return_value=False):
            result = _resolve_ui_adapter()
        assert result is None
        captured = capsys.readouterr()
        assert "probe failed" in captured.out.lower() or "fallback" in captured.out.lower()

    def test_auto_detect_enables_when_available(self, capsys):
        os.environ.pop("AUTODEV_UI_OD", None)
        with patch("harness.open_design.is_available", return_value=True):
            from harness.adapters.open_design import OpenDesignAdapter

            result = _resolve_ui_adapter()
        assert isinstance(result, OpenDesignAdapter)

    def test_invalid_value_falls_back(self, capsys):
        os.environ["AUTODEV_UI_OD"] = "garbage"
        with patch("harness.open_design.is_available", return_value=False):
            result = _resolve_ui_adapter()
        assert result is None
        captured = capsys.readouterr()
        # Both the "invalid" and "probe failed" messages appear.
        assert "invalid" in captured.out.lower()

    def test_adapter_construction_failure_falls_back(self, capsys):
        os.environ["AUTODEV_UI_OD"] = "1"
        with patch(
            "harness.adapters.open_design.OpenDesignAdapter",
            side_effect=RuntimeError("daemon timeout"),
        ):
            result = _resolve_ui_adapter()
        assert result is None
        captured = capsys.readouterr()
        assert "falling back" in captured.out.lower() or "failed" in captured.out.lower()
