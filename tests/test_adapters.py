"""Tests for the CLI adapter layer.

These tests mock subprocess to cover retry/fallback/timeout paths
without requiring real API calls.
"""

from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from harness.adapters.base import (
    AdapterError,
    AgentResult,
    RateLimitError,
    TimeoutError,
    Usage,
)
from harness.adapters.claude import ClaudeAdapter


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

DUMMY_CLAUDE_JSON = json.dumps({
    "result": "Hello from Claude",
    "usage": {"input_tokens": 10, "output_tokens": 20, "total_tokens": 30},
})


def mock_proc(stdout: str = "", stderr: str = "", returncode: int = 0):
    """Create a mock subprocess.Popen object."""
    proc = MagicMock()
    proc.returncode = returncode
    proc.communicate = MagicMock(return_value=(stdout, stderr))
    return proc


# ---------------------------------------------------------------------------
# Test: successful run returns correct fields
# ---------------------------------------------------------------------------

def test_claude_success():
    adapter = ClaudeAdapter()

    with patch("subprocess.Popen") as mock_popen:
        mock_popen.return_value = mock_proc(stdout=DUMMY_CLAUDE_JSON, returncode=0)

        result = adapter.run("say hello", model="haiku-4-5-20251001", cwd=Path("/tmp"))

    assert result.exit_code == 0
    assert result.stderr == ""
    assert result.success is True
    assert result.stdout == "Hello from Claude"
    assert result.usage.input_tokens == 10
    assert result.usage.output_tokens == 20
    assert result.usage.total_tokens == 30
    assert result.retry_count == 0
    assert result.duration_ms >= 0


# ---------------------------------------------------------------------------
# Test: rate-limit error triggers retry and succeeds on second attempt
# ---------------------------------------------------------------------------

def test_claude_rate_limit_retry_success():
    adapter = ClaudeAdapter()

    responses = [
        # First call: 429 rate limit
        mock_proc(stderr="ERROR: 429 Too Many Requests", returncode=1),
        # Second call: success
        mock_proc(stdout=DUMMY_CLAUDE_JSON, returncode=0),
    ]
    mock_popen = MagicMock(side_effect=responses)
    mock_popen.return_value.communicate = MagicMock(
        side_effect=lambda **kw: responses[len(mock_popen.call_args_list) - 1].communicate()
    )

    call_count = [0]

    def side_effect(*args, **kwargs):
        proc = responses[call_count[0]]
        call_count[0] += 1
        return proc

    mock_popen.side_effect = side_effect

    with patch("subprocess.Popen", mock_popen):
        with patch("time.sleep") as mock_sleep:
            result = adapter.run("say hello", model="haiku-4-5-20251001", cwd=Path("/tmp"))

    assert result.exit_code == 0
    assert result.retry_count == 1
    assert "Hello from Claude" in result.stdout
    # Verify backoff was called
    mock_sleep.assert_called()


# ---------------------------------------------------------------------------
# Test: all retries exhausted raises AdapterError
# ---------------------------------------------------------------------------

def test_claude_all_retries_exhausted():
    adapter = ClaudeAdapter()

    # All 3 attempts return 429
    mock_popen = MagicMock(
        side_effect=[
            mock_proc(stderr="ERROR: 429 Too Many Requests", returncode=1),
            mock_proc(stderr="ERROR: 429 Too Many Requests", returncode=1),
            mock_proc(stderr="ERROR: 429 Too Many Requests", returncode=1),
        ]
    )

    with patch("subprocess.Popen", mock_popen):
        with patch("time.sleep"):
            with pytest.raises(AdapterError, match="429"):
                adapter.run("say hello", model="haiku-4-5-20251001", cwd=Path("/tmp"))


# ---------------------------------------------------------------------------
# Test: timeout raises TimeoutError without retry
# ---------------------------------------------------------------------------

def test_claude_timeout_no_retry():
    adapter = ClaudeAdapter()

    def timeout_on_first(*args, **kwargs):
        proc = mock_proc()
        proc.communicate = MagicMock(side_effect=subprocess.TimeoutExpired("cmd", 30))
        return proc

    mock_popen = MagicMock(side_effect=timeout_on_first)

    with patch("subprocess.Popen", mock_popen):
        with pytest.raises(TimeoutError):
            adapter.run("say hello", model="haiku-4-5-20251001", cwd=Path("/tmp"), timeout=30)


# ---------------------------------------------------------------------------
# Test: 5xx server error triggers retry
# ---------------------------------------------------------------------------

def test_claude_server_error_retry():
    adapter = ClaudeAdapter()

    responses = [
        mock_proc(stderr="ERROR: 500 Internal Server Error", returncode=1),
        mock_proc(stdout=DUMMY_CLAUDE_JSON, returncode=0),
    ]

    call_count = [0]

    def side_effect(*args, **kwargs):
        proc = responses[call_count[0]]
        call_count[0] += 1
        return proc

    mock_popen = MagicMock(side_effect=side_effect)

    with patch("subprocess.Popen", mock_popen):
        with patch("time.sleep"):
            result = adapter.run("say hello", model="haiku-4-5-20251001", cwd=Path("/tmp"))

    assert result.exit_code == 0
    assert result.retry_count == 1


# ---------------------------------------------------------------------------
# Test: non-zero exit code without rate limit raises AdapterError immediately
# ---------------------------------------------------------------------------

def test_claude_nonzero_exit_no_retry():
    adapter = ClaudeAdapter()

    mock_popen = MagicMock(
        return_value=mock_proc(stderr="Unknown error", returncode=2)
    )

    with patch("subprocess.Popen", mock_popen):
        with pytest.raises(AdapterError, match="exited with code 2"):
            adapter.run("say hello", model="haiku-4-5-20251001", cwd=Path("/tmp"))


# ---------------------------------------------------------------------------
# Test: markdown code fence is stripped from JSON output
# ---------------------------------------------------------------------------

def test_claude_strips_code_fence():
    adapter = ClaudeAdapter()

    fenced_json = "```json\n" + DUMMY_CLAUDE_JSON + "\n```"
    mock_popen = MagicMock(return_value=mock_proc(stdout=fenced_json, returncode=0))

    with patch("subprocess.Popen", mock_popen):
        result = adapter.run("say hello", model="haiku-4-5-20251001", cwd=Path("/tmp"))

    assert result.stdout == "Hello from Claude"
    assert result.usage.total_tokens == 30


# ---------------------------------------------------------------------------
# Test: usage missing fields handled gracefully
# ---------------------------------------------------------------------------

def test_claude_missing_usage_fields():
    adapter = ClaudeAdapter()

    partial_json = json.dumps({"result": "partial", "usage": {"input_tokens": 5}})
    mock_popen = MagicMock(return_value=mock_proc(stdout=partial_json, returncode=0))

    with patch("subprocess.Popen", mock_popen):
        result = adapter.run("say hello", model="haiku-4-5-20251001", cwd=Path("/tmp"))

    assert result.stdout == "partial"
    assert result.usage.input_tokens == 5
    assert result.usage.output_tokens is None
    assert result.usage.total_tokens is None


# ---------------------------------------------------------------------------
# Test: non-JSON stdout now raises InvalidResponseError (T25)
# ---------------------------------------------------------------------------

def test_claude_non_json_raises_invalid_response():
    """T25 — ``--output-format json`` is a contract: garbage stdout must
    raise ``InvalidResponseError`` instead of being silently passed
    through as the agent's "result" text. The legacy silent fallback
    bug is what allowed downstream consumers to mistake protocol
    violations for legitimate text."""
    from harness.adapters.base import InvalidResponseError

    adapter = ClaudeAdapter()

    mock_popen = MagicMock(return_value=mock_proc(stdout="plain text response", returncode=0))

    with patch("subprocess.Popen", mock_popen):
        with pytest.raises(InvalidResponseError, match="unparseable output"):
            adapter.run("say hello", model="haiku-4-5-20251001", cwd=Path("/tmp"))


# ---------------------------------------------------------------------------
# Test: cwd defaults to Path.cwd()
# ---------------------------------------------------------------------------

def test_claude_default_cwd():
    adapter = ClaudeAdapter()

    captured_cwd = []

    def capture_cwd(*args, **kwargs):
        captured_cwd.append(kwargs.get("cwd"))
        return mock_proc(stdout=DUMMY_CLAUDE_JSON, returncode=0)

    mock_popen = MagicMock(side_effect=capture_cwd)

    with patch("subprocess.Popen", mock_popen):
        adapter.run("say hello", model="haiku-4-5-20251001")

    assert captured_cwd[0] == Path.cwd()


# ---------------------------------------------------------------------------
# Test: opencode stub raises NotImplementedError
# ---------------------------------------------------------------------------

def test_opencode_not_implemented():
    from harness.adapters.opencode import OpenCodeAdapter

    adapter = OpenCodeAdapter()
    with pytest.raises(NotImplementedError, match="not yet implemented"):
        # Call _execute directly to bypass base.run() retry wrapper
        adapter._execute("test", model="gpt-4o", cwd=Path("/tmp"), timeout=30, attempt=0)


# ---------------------------------------------------------------------------
# Test: codex stub raises NotImplementedError
# ---------------------------------------------------------------------------

def test_codex_not_implemented():
    from harness.adapters.codex import CodexAdapter

    adapter = CodexAdapter()
    with pytest.raises(NotImplementedError, match="not yet implemented"):
        # Call _execute directly to bypass base.run() retry wrapper
        adapter._execute("test", model="gpt-4o", cwd=Path("/tmp"), timeout=30, attempt=0)


# ---------------------------------------------------------------------------
# Test: AgentResult.success property
# ---------------------------------------------------------------------------

def test_agent_result_success():
    """T27 — ``success`` is now exit-code-only. stderr can carry
    harmless warnings / debug logs from a healthy run, so the
    ``not stderr`` clause that used to flip success to False has been
    removed."""
    ok = AgentResult(exit_code=0, stderr="")
    assert ok.success is True

    non_zero = AgentResult(exit_code=1, stderr="")
    assert non_zero.success is False

    # Clean exit + noisy stderr — still success.
    noisy_ok = AgentResult(exit_code=0, stderr="warning: deprecated flag")
    assert noisy_ok.success is True


# ---------------------------------------------------------------------------
# Test: Usage model fields
# ---------------------------------------------------------------------------

def test_usage_model():
    u = Usage(input_tokens=100, output_tokens=200, total_tokens=300, duration_ms=1500)
    assert u.input_tokens == 100
    assert u.output_tokens == 200
    assert u.total_tokens == 300
    assert u.duration_ms == 1500
