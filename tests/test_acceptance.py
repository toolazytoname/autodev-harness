"""Tests for harness.acceptance — the bridge between task acceptance
strings and the test reviewer's execution plan.

Per TASKS T11 / MASTER-PLAN §3 (P3): the test reviewer should be able to
turn a task's acceptance list into a list of executable steps. These
tests pin the classification contract.
"""

from __future__ import annotations

import pytest

from harness.acceptance import (
    AcceptanceStep,
    StepKind,
    classify_all,
    classify_step,
    has_legacy_acceptance,
    http_targets,
    shell_commands,
    summarize,
)


class TestClassifyStepShell:
    def test_dollar_prefix(self):
        s = classify_step("$ pytest -q")
        assert s.kind is StepKind.SHELL
        assert s.payload == "pytest -q"

    def test_bang_prefix(self):
        s = classify_step("! npm test")
        assert s.kind is StepKind.SHELL
        assert s.payload == "npm test"

    def test_run_prefix(self):
        s = classify_step("run curl -fsS http://localhost:3000/health")
        assert s.kind is StepKind.SHELL
        assert s.payload == "curl -fsS http://localhost:3000/health"


class TestClassifyStepHttp:
    def test_get_verb(self):
        s = classify_step("GET /api/tasks returns 200")
        assert s.kind is StepKind.HTTP

    def test_post_verb(self):
        s = classify_step("POST /api/tasks with {title: 'foo'} returns 201")
        assert s.kind is StepKind.HTTP

    def test_url_prefix(self):
        s = classify_step("https://example.com/health responds with 200")
        assert s.kind is StepKind.HTTP
        assert s.payload == "https://example.com/health"


class TestClassifyStepPytest:
    def test_pytest_prefix(self):
        s = classify_step("pytest tests/test_billing.py::test_invoice")
        assert s.kind is StepKind.PYTEST
        assert s.payload == "pytest tests/test_billing.py::test_invoice"

    def test_test_path_prefix(self):
        s = classify_step("tests/test_models.py runs green")
        assert s.kind is StepKind.PYTEST


class TestClassifyStepBrowser:
    def test_english_click(self):
        s = classify_step("Click the 'Add' button and see a new row appear")
        assert s.kind is StepKind.BROWSER

    def test_chinese_login_flow(self):
        s = classify_step("登录后看到欢迎语")
        assert s.kind is StepKind.BROWSER

    def test_visit_keyword(self):
        s = classify_step("Visit /login and submit empty form")
        assert s.kind is StepKind.BROWSER

    def test_expect_keyword(self):
        s = classify_step("Should see 'Welcome' on the dashboard")
        assert s.kind is StepKind.BROWSER


class TestClassifyStepAssert:
    def test_plain_english(self):
        s = classify_step("Documentation updated to mention the new env var")
        assert s.kind is StepKind.ASSERT

    def test_plain_chinese(self):
        s = classify_step("代码符合 PEP 8 规范")
        assert s.kind is StepKind.ASSERT


class TestClassifyStepValidation:
    def test_empty_string_raises(self):
        with pytest.raises(ValueError):
            classify_step("")

    def test_whitespace_only_raises(self):
        with pytest.raises(ValueError):
            classify_step("   \t\n  ")

    def test_raw_preserved(self):
        s = classify_step("  $ npm test  ")
        # The raw field keeps the original text (with surrounding spaces)
        assert s.raw == "  $ npm test  "


class TestClassifyAll:
    def test_classify_mixed_list(self):
        steps = [
            "$ npm test",
            "GET /api/health returns 200",
            "Click the 'Save' button",
            "Documentation mentions the new flag",
        ]
        classified = classify_all(steps)
        assert [c.kind for c in classified] == [
            StepKind.SHELL,
            StepKind.HTTP,
            StepKind.BROWSER,
            StepKind.ASSERT,
        ]
        # Original order preserved
        assert [c.raw for c in classified] == steps


class TestHasLegacyAcceptance:
    def test_detects_legacy_sentinel(self):
        assert has_legacy_acceptance(["(legacy) — please add acceptance"]) is True

    def test_returns_false_for_real_acceptance(self):
        assert has_legacy_acceptance(["$ npm test", "Click the button"]) is False

    def test_empty_list_is_not_legacy(self):
        # An empty list is not a legacy sentinel — it's just empty
        # (and the schema now forbids that anyway).
        assert has_legacy_acceptance([]) is False


class TestSummarize:
    def test_summarize_counts(self):
        steps = classify_all([
            "$ npm test",
            "$ pytest",
            "GET /api/foo",
            "Click the button",
            "Updated docs",
        ])
        counts = summarize(steps)
        assert counts == {
            "shell": 2,
            "http": 1,
            "browser": 1,
            "assert": 1,
            "pytest": 0,
        }


class TestShellCommands:
    def test_extracts_shell_only(self):
        steps = classify_all([
            "$ npm test",
            "GET /api/foo",
            "$ pytest -q",
            "Click the button",
        ])
        assert shell_commands(steps) == ["npm test", "pytest -q"]


class TestHttpTargets:
    def test_extracts_urls_only(self):
        steps = classify_all([
            "$ npm test",
            "GET /api/foo returns 200",
            "POST https://example.com/api with body",
            "Click button",
        ])
        urls = http_targets(steps)
        assert "https://example.com/api" in urls
        # Pure-verb HTTP steps have the path in the payload
        assert "/api/foo" in urls
        # Non-HTTP steps are not included
        assert "npm test" not in urls
        assert "Click button" not in urls


class TestAcceptanceStepImmutability:
    def test_frozen(self):
        s = classify_step("$ npm test")
        with pytest.raises((AttributeError, TypeError, ValueError)):
            s.kind = StepKind.ASSERT  # type: ignore[misc]
