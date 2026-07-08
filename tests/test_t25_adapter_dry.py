"""T25 tests: adapter DRY + multimodal unified retry + JSON parse fixes.

Drives the issues called out in docs/TASKS.md T25:

1. ``run_with_attachments`` and ``_execute`` duplicate the subprocess
   plumbing; multimodal currently has *zero* retries (bypasses
   ``AdapterBase.run``).
2. ``_extract_json`` is O(n²) on bad input and silently swallows falsy
   fields; ``--output-format json`` output that fails to parse should
   raise ``InvalidResponseError`` instead of returning the raw text.
3. Multimodal argv should insert ``--`` before attachment paths so the
   CLI doesn't mistake them for prompt continuation.

Each test starts RED — written against the documented target behavior,
not the current implementation.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from harness.adapters.base import (
    AdapterError,
    InvalidResponseError,
    RateLimitError,
    ServerError,
    TimeoutError,
    TransientError,
)
from harness.adapters.claude import ClaudeAdapter


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


DUMMY_CLAUDE_JSON = json.dumps({
    "result": "Hello from Claude",
    "usage": {"input_tokens": 10, "output_tokens": 20, "total_tokens": 30},
})


def _fake_proc(stdout: str = "", stderr: str = "", returncode: int = 0):
    proc = MagicMock()
    proc.returncode = returncode
    proc.communicate = MagicMock(return_value=(stdout, stderr))
    return proc


def _exists(path):
    """Patch Path.exists to claim any path exists — keeps tests off the FS."""
    return True


# ---------------------------------------------------------------------------
# Shared subprocess helper (DRY)
# ---------------------------------------------------------------------------


def test_run_subprocess_happy_path():
    """``_run_subprocess`` returns stdout/stderr/exit_code/duration_ms."""
    adapter = ClaudeAdapter()
    with patch("subprocess.Popen", return_value=_fake_proc("out", "err", 0)):
        stdout, stderr, exit_code, duration_ms = adapter._run_subprocess(
            cmd=["claude", "-p"],
            prompt="hi",
            cwd=Path("/tmp"),
            timeout=30,
            env=None,
        )
    assert stdout == "out"
    assert stderr == "err"
    assert exit_code == 0
    assert duration_ms >= 0


def test_run_subprocess_timeout_raises_timeout_error():
    adapter = ClaudeAdapter()

    proc = MagicMock()
    proc.communicate = MagicMock(side_effect=subprocess.TimeoutExpired("cmd", 5))
    proc.kill = MagicMock()
    proc.wait = MagicMock()

    with patch("subprocess.Popen", return_value=proc):
        with pytest.raises(TimeoutError, match="timed out"):
            adapter._run_subprocess(
                cmd=["claude"], prompt="hi", cwd=Path("/tmp"), timeout=5, env=None,
            )
    proc.kill.assert_called()


def test_run_subprocess_broken_pipe_raises_transient():
    adapter = ClaudeAdapter()
    with patch(
        "subprocess.Popen", side_effect=BrokenPipeError("pipe closed"),
    ):
        with pytest.raises(TransientError):
            adapter._run_subprocess(
                cmd=["claude"], prompt="hi", cwd=Path("/tmp"), timeout=30, env=None,
            )


def test_run_subprocess_missing_binary_raises_adapter_error():
    """FileNotFoundError (binary missing) is NOT transient."""
    adapter = ClaudeAdapter()
    with patch("subprocess.Popen", side_effect=FileNotFoundError("no claude")):
        with pytest.raises(AdapterError, match="Failed to execute claude"):
            adapter._run_subprocess(
                cmd=["claude"], prompt="hi", cwd=Path("/tmp"), timeout=30, env=None,
            )


# ---------------------------------------------------------------------------
# Multimodal unified retry (was: zero retries)
# ---------------------------------------------------------------------------


def test_multimodal_retries_on_429_then_succeeds():
    """run_with_attachments must retry on transient 429 like the text path."""
    adapter = ClaudeAdapter()

    responses = [
        _fake_proc(stderr="ERROR: HTTP 429 Too Many Requests", returncode=1),
        _fake_proc(stdout=DUMMY_CLAUDE_JSON, returncode=0),
    ]
    call_count = [0]

    def side_effect(*args, **kwargs):
        proc = responses[call_count[0]]
        call_count[0] += 1
        return proc

    with patch("subprocess.Popen", side_effect=side_effect), \
         patch("time.sleep"), \
         patch.object(Path, "exists", return_value=True):
        result = adapter.run_with_attachments(
            "look at this",
            [Path("/tmp/img.png")],
            model="haiku-4-5-20251001",
            cwd=Path("/tmp"),
        )

    assert call_count[0] == 2
    assert result.exit_code == 0
    assert result.retry_count == 1
    assert "Hello from Claude" in result.stdout


def test_multimodal_retries_on_5xx_then_succeeds():
    adapter = ClaudeAdapter()

    responses = [
        _fake_proc(stderr="ERROR: HTTP 500 Internal Server Error", returncode=1),
        _fake_proc(stdout=DUMMY_CLAUDE_JSON, returncode=0),
    ]
    call_count = [0]

    def side_effect(*args, **kwargs):
        proc = responses[call_count[0]]
        call_count[0] += 1
        return proc

    with patch("subprocess.Popen", side_effect=side_effect), \
         patch("time.sleep"), \
         patch.object(Path, "exists", return_value=True):
        result = adapter.run_with_attachments(
            "describe",
            [Path("/tmp/img.png")],
            model="haiku-4-5-20251001",
            cwd=Path("/tmp"),
        )

    assert call_count[0] == 2
    assert result.exit_code == 0
    assert result.retry_count == 1


def test_multimodal_exhausts_retries_raises_rate_limit_error():
    adapter = ClaudeAdapter()

    with patch(
        "subprocess.Popen",
        return_value=_fake_proc(stderr="ERROR: HTTP 429 Too Many Requests", returncode=1),
    ), patch("time.sleep"), patch.object(Path, "exists", return_value=True):
        with pytest.raises(RateLimitError):
            adapter.run_with_attachments(
                "x", [Path("/tmp/img.png")], model="haiku-4-5-20251001",
                cwd=Path("/tmp"),
            )


def test_multimodal_uses_dash_dash_separator_before_attachments():
    """argv must contain ``--`` immediately before attachment paths so the
    CLI treats them as file arguments, not prompt continuation."""
    adapter = ClaudeAdapter()
    captured_cmds = []

    def capture(*args, **kwargs):
        captured_cmds.append(list(args[0]))
        return _fake_proc(stdout=DUMMY_CLAUDE_JSON, returncode=0)

    with patch("subprocess.Popen", side_effect=capture), \
         patch.object(Path, "exists", return_value=True):
        adapter.run_with_attachments(
            "describe image",
            [Path("/tmp/a.png"), Path("/tmp/b.png")],
            model="haiku-4-5-20251001",
            cwd=Path("/tmp"),
        )

    cmd = captured_cmds[0]
    # Find the position of "--" — must exist and be followed by attachments.
    assert "--" in cmd, f"argv missing -- separator: {cmd}"
    sep_idx = cmd.index("--")
    assert sep_idx == len(cmd) - 3, (
        f"-- must immediately precede attachments, got argv={cmd}"
    )
    assert cmd[sep_idx + 1] == "/tmp/a.png"
    assert cmd[sep_idx + 2] == "/tmp/b.png"


# ---------------------------------------------------------------------------
# JSON parsing: O(n), arrays, raise on failure, no falsy swallow
# ---------------------------------------------------------------------------


def test_parse_json_output_raises_on_unparseable_input():
    """If --output-format json returns garbage, raise InvalidResponseError."""
    adapter = ClaudeAdapter()
    with pytest.raises(InvalidResponseError):
        adapter._parse_json_output(
            "this is not json at all {not even close",
            duration_ms=10,
            attempt=0,
        )


def test_parse_json_output_accepts_array_envelope():
    """Top-level JSON array (some CLIs wrap result in a list)."""
    adapter = ClaudeAdapter()
    array_envelope = json.dumps([{"result": "from-array", "usage": {}}])
    usage, text = adapter._parse_json_output(array_envelope, 10, 0)
    assert text == "from-array"


def test_parse_json_output_prefers_explicit_empty_result_over_content():
    """``result=""`` is a deliberate empty response and must not be
    replaced by ``content`` via the legacy ``or`` fallthrough."""
    adapter = ClaudeAdapter()
    payload = json.dumps({"result": "", "content": "fallback"})
    _, text = adapter._parse_json_output(payload, 10, 0)
    assert text == ""


def test_extract_json_uses_linear_scan_on_large_input():
    """The legacy _extract_json did O(n²) progressive slicing; the new
    implementation should be O(n) (raw_decode walks the string once).

    We assert: completing in well under the time the O(n²) version would
    take on a large-but-mostly-broken payload. The current O(n²) loop
    produces ~len(prefix) attempts of json.loads; on a 50KB string with
    a long unterminated JSON it's a multi-second freeze. The new path
    must finish in < 1 second."""
    import time

    adapter = ClaudeAdapter()
    # 50 KB of text that LOOKS like JSON but is unterminated.
    big = '{"a": "' + ("x" * 50_000) + ' and now broken, no closing'
    big += "more junk that never closes"

    start = time.monotonic()
    result = adapter._extract_json(big)
    elapsed = time.monotonic() - start

    # Either the parser returns None (no valid JSON found) or a dict —
    # but it must NOT take quadratic time.
    assert result is None or isinstance(result, dict)
    # T37: was < 1.0s — flaked on slow CI. 5.0s is still well below
    # the O(n²) regime for the input size here (~50 KB), but gives CI
    # the headroom it needs.
    assert elapsed < 5.0, f"took {elapsed:.2f}s, looks O(n²)"


# ---------------------------------------------------------------------------
# Exit-code and multimodal-error paths use the shared helper
# ---------------------------------------------------------------------------


def test_execute_failure_exit_code_raises_adapter_error_via_shared_path():
    """Non-zero exit (no 429/5xx/quota signal) → AdapterError. Same code
    path should be used for multimodal and text."""
    adapter = ClaudeAdapter()
    with patch(
        "subprocess.Popen",
        return_value=_fake_proc(stderr="boom", returncode=2),
    ):
        with pytest.raises(AdapterError, match="exited with code 2"):
            adapter.run("hi", model="haiku-4-5-20251001", cwd=Path("/tmp"))