"""Tests for T20 error classification refactor.

The previous implementation in claude.py matched "429" / "5xx" / "rate limit"
as naked substrings in stderr — so any number in a file path, token count,
or line number produced false-positive retries. This module covers the
new structured-first / word-boundary fallback classifier and the
5xx-as-ServerError split.

Behavior under test
-------------------
1. ``claude._classify_error`` prefers JSON-structured ``--output-format json``
   errors and only falls back to word-bound substring matching when the
   structured form is absent.
2. 5xx HTTP responses raise ``ServerError`` (a separate ``AdapterError``
   subclass), never ``RateLimitError``.
3. Noise such as ``/tmp/file429.log`` or ``line 500: typo`` is *not*
   classified as a rate-limit / server error.
4. ``ConnectionError`` / ``BrokenPipeError`` raised by the subprocess
   layer surface as the retryable ``TransientError`` and the base
   ``run()`` loop retries them.

NOTE on imports: ``ServerError`` / ``TransientError`` do not exist yet
(that's the RED phase). Imports are deferred inside test functions so the
file is collectable; the tests fail at execution time with ImportError on
the missing symbols — which is the desired RED signal.
"""

from __future__ import annotations

import json
import subprocess
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


DUMMY_CLAUDE_JSON = json.dumps({
    "result": "Hello from Claude",
    "usage": {"input_tokens": 10, "output_tokens": 20, "total_tokens": 30},
})


def mock_proc(stdout: str = "", stderr: str = "", returncode: int = 0):
    """Create a mock subprocess.Popen object (mirrors test_adapters helper)."""
    proc = MagicMock()
    proc.returncode = returncode
    proc.communicate = MagicMock(return_value=(stdout, stderr))
    return proc


def _proc_with_communicate_error(exc: BaseException):
    """Return a mock Popen whose communicate() raises ``exc``."""
    proc = MagicMock()
    proc.communicate = MagicMock(side_effect=exc)
    proc.returncode = None
    return proc


# ---------------------------------------------------------------------------
# Group A: 5xx must surface as ServerError, not RateLimitError
# ---------------------------------------------------------------------------


def test_5xx_raises_server_error_not_rate_limit():
    """A 500 in stderr must classify as ServerError so call sites can split
    5xx vs 429 semantically."""
    from harness.adapters.base import ServerError  # late import (T20 RED)

    adapter = ClaudeAdapter()

    classified = adapter._classify_error(
        stderr="ERROR: HTTP 500 Internal Server Error",
        stdout="",
        exit_code=1,
    )

    assert isinstance(classified, ServerError), (
        f"expected ServerError, got {type(classified).__name__}"
    )
    assert not isinstance(classified, RateLimitError), (
        "5xx must NOT inherit from RateLimitError — that was the bug"
    )


def test_502_classifies_as_server_error():
    """Each 5xx code in RETRY_SERVER_ERROR_CODES should classify as ServerError."""
    from harness.adapters.base import ServerError  # late import (T20 RED)

    adapter = ClaudeAdapter()

    for code in (500, 502, 503, 504):
        result = adapter._classify_error(
            stderr=f"upstream returned HTTP {code}",
            stdout="",
            exit_code=1,
        )
        assert isinstance(result, ServerError), (
            f"HTTP {code} should classify as ServerError, got {type(result).__name__}"
        )


def test_5xx_triggers_retry_in_run_loop():
    """A 5xx in stderr must be retried by the base run() loop."""
    from harness.adapters.base import ServerError  # late import (T20 RED)

    adapter = ClaudeAdapter()

    responses = [
        mock_proc(stderr="ERROR: HTTP 503 Service Unavailable", returncode=1),
        mock_proc(stdout=DUMMY_CLAUDE_JSON, returncode=0),
    ]
    call_count = {"n": 0}

    def side_effect(*args, **kwargs):
        proc = responses[call_count["n"]]
        call_count["n"] += 1
        return proc

    with patch("subprocess.Popen", side_effect=side_effect):
        with patch("time.sleep"):
            result = adapter.run(
                "hi", model="haiku-4-5-20251001", cwd=Path("/tmp")
            )

    assert result.exit_code == 0
    assert result.retry_count == 1


def test_5xx_exhaustion_raises_adapter_error_with_server_context():
    """After 3 failed 5xx attempts, base.run() must raise AdapterError and
    the message must still reference the server error (not 'rate limit').

    We also assert that no RateLimitError appears anywhere in the cause
    chain — that's the semantic split the refactor is meant to enforce.
    """
    adapter = ClaudeAdapter()

    responses = [
        mock_proc(stderr="ERROR: HTTP 500", returncode=1),
        mock_proc(stderr="ERROR: HTTP 500", returncode=1),
        mock_proc(stderr="ERROR: HTTP 500", returncode=1),
    ]

    with patch("subprocess.Popen", side_effect=responses):
        with patch("time.sleep"):
            with pytest.raises(AdapterError) as exc_info:
                adapter.run("hi", model="haiku-4-5-20251001", cwd=Path("/tmp"))

    # The final AdapterError must mention 500 AND its cause chain must not
    # contain RateLimitError (5xx is semantically distinct from rate-limit).
    assert "500" in str(exc_info.value)
    chain = exc_info.value
    while chain is not None:
        assert not isinstance(chain, RateLimitError), (
            f"5xx exhaustion must not propagate via RateLimitError; chain: {chain!r}"
        )
        chain = chain.__cause__ or chain.__context__


# ---------------------------------------------------------------------------
# Group B: noise that mentions 429 must not be misclassified
# ---------------------------------------------------------------------------


def test_429_in_path_does_not_trigger_rate_limit():
    """A path or token containing '429' must not be classified as a rate
    limit. Previous behaviour: 'Read /var/log/429-access.log' would falsely
    raise RateLimitError and waste a retry budget."""
    adapter = ClaudeAdapter()

    classified = adapter._classify_error(
        stderr="Read 429 files from /var/log/app-429/access.log successfully",
        stdout="",
        exit_code=0,
    )

    assert classified is None, (
        f"noise string should not classify as any error, got {classified!r}"
    )


def test_429_alone_is_rate_limit():
    """The word-boundary matcher still triggers on a real 429 signal like
    'HTTP 429' or 'error: 429'."""
    adapter = ClaudeAdapter()

    classified = adapter._classify_error(
        stderr="upstream returned HTTP 429 Too Many Requests",
        stdout="",
        exit_code=1,
    )
    assert isinstance(classified, RateLimitError)


# ---------------------------------------------------------------------------
# Group C: noise that mentions 5xx must not be misclassified
# ---------------------------------------------------------------------------


def test_500_in_line_number_does_not_trigger_server_error():
    """stderr = 'line 500: unexpected token' must not classify as 5xx.
    Previous behaviour: '500' as a substring anywhere fired the loop."""
    from harness.adapters.base import ServerError  # late import (T20 RED)

    adapter = ClaudeAdapter()

    classified = adapter._classify_error(
        stderr="parse error: line 500: unexpected token in foo bar",
        stdout="",
        exit_code=0,
    )
    assert classified is None


def test_5xx_alone_is_server_error():
    """A genuine 'HTTP 500' / '502 Bad Gateway' signal still classifies."""
    from harness.adapters.base import ServerError  # late import (T20 RED)

    adapter = ClaudeAdapter()

    for body in (
        "upstream returned HTTP 500",
        "502 Bad Gateway",
        "service unavailable (HTTP 503)",
    ):
        result = adapter._classify_error(
            stderr=body, stdout="", exit_code=1
        )
        assert isinstance(result, ServerError), (
            f"body={body!r} should classify as ServerError, got {type(result).__name__}"
        )


# ---------------------------------------------------------------------------
# Group D: structured JSON errors are detected even when stderr is empty
# ---------------------------------------------------------------------------


def test_structured_json_error_with_empty_stderr_triggers_retry():
    """claude --output-format json may emit error envelopes on stdout with
    empty stderr. The classifier must read them.

    Example shape (representative): {"is_error": true, "error": "...429..."}
    """
    adapter = ClaudeAdapter()

    error_json = json.dumps({
        "is_error": True,
        "error": "rate_limit_error: usage limit exceeded",
        "status_code": 429,
    })

    classified = adapter._classify_error(
        stderr="",
        stdout=error_json,
        exit_code=0,  # exit code can be 0 even when result is an error envelope
    )
    assert isinstance(classified, RateLimitError), (
        f"structured JSON error must classify as RateLimitError, got "
        f"{type(classified).__name__}"
    )


def test_structured_json_5xx_triggers_server_error():
    """Structured JSON with status_code 502 must classify as ServerError."""
    from harness.adapters.base import ServerError  # late import (T20 RED)

    adapter = ClaudeAdapter()

    error_json = json.dumps({
        "is_error": True,
        "error": "bad gateway from upstream",
        "status_code": 502,
    })

    classified = adapter._classify_error(
        stderr="",
        stdout=error_json,
        exit_code=0,
    )
    assert isinstance(classified, ServerError)


def test_clean_json_with_empty_stderr_returns_none():
    """A normal claude JSON envelope with no error fields must NOT classify
    as anything — that's the success path."""
    adapter = ClaudeAdapter()

    classified = adapter._classify_error(
        stderr="",
        stdout=DUMMY_CLAUDE_JSON,
        exit_code=0,
    )
    assert classified is None


# ---------------------------------------------------------------------------
# Group D2: exit code 1 with empty stderr must retry regardless of stdout
# ---------------------------------------------------------------------------


def test_exit_1_empty_stderr_with_nonempty_stdout_triggers_retry():
    """Real-world crash signature: a long-running generator call prints
    partial, non-JSON output to stdout (e.g. an interrupted stream) then
    the CLI exits 1 with no stderr diagnostic. This must still be
    retried — requiring stdout to *also* be empty let this fall through
    to a non-retried generic AdapterError and aborted the whole pipeline
    on what was the same opaque, transient failure."""
    from harness.adapters.base import TransientError

    adapter = ClaudeAdapter()

    responses = [
        mock_proc(stdout="partial output before the CLI died", stderr="", returncode=1),
        mock_proc(stdout=DUMMY_CLAUDE_JSON, returncode=0),
    ]

    with patch("subprocess.Popen", side_effect=responses):
        with patch("time.sleep"):
            result = adapter.run("hi", model="haiku-4-5-20251001", cwd=Path("/tmp"))

    assert result.exit_code == 0
    assert result.retry_count == 1


def test_exit_1_empty_stderr_and_stdout_still_classifies_as_transient():
    """Original no-output proxy-flake signature must still be covered."""
    from harness.adapters.base import TransientError

    adapter = ClaudeAdapter()
    with pytest.raises(TransientError):
        adapter._post_subprocess(stdout="", stderr="", exit_code=1, duration_ms=10, attempt=0)


def test_exit_1_with_nonempty_stderr_still_raises_plain_adapter_error():
    """A genuine, diagnosable exit-1 failure (real stderr message, not a
    recognized 429/5xx/quota pattern) must NOT be swallowed into a
    silent retry — it should still surface as a plain AdapterError."""
    adapter = ClaudeAdapter()

    with pytest.raises(AdapterError) as exc_info:
        adapter._post_subprocess(
            stdout="", stderr="permission denied: /root/.ssh", exit_code=1,
            duration_ms=10, attempt=0,
        )
    from harness.adapters.base import TransientError
    assert not isinstance(exc_info.value, TransientError)


# ---------------------------------------------------------------------------
# Group E: transient OS errors (ConnectionError / BrokenPipeError) must retry
# ---------------------------------------------------------------------------


def test_connection_error_triggers_retry_in_run_loop():
    """ConnectionError raised by Popen.communicate must be retried by the
    base run() loop (previous behaviour: it was swallowed and wrapped in
    AdapterError immediately, burning no retry budget)."""
    adapter = ClaudeAdapter()

    responses = [
        # First attempt: Popen.communicate raises ConnectionError
        _proc_with_communicate_error(ConnectionError("peer reset")),
        # Second attempt: success
        mock_proc(stdout=DUMMY_CLAUDE_JSON, returncode=0),
    ]

    call_count = {"n": 0}

    def side_effect(*args, **kwargs):
        proc = responses[call_count["n"]]
        call_count["n"] += 1
        return proc

    with patch("subprocess.Popen", side_effect=side_effect):
        with patch("time.sleep"):
            result = adapter.run(
                "hi", model="haiku-4-5-20251001", cwd=Path("/tmp")
            )

    assert result.exit_code == 0
    assert result.retry_count == 1


def test_broken_pipe_triggers_retry():
    """BrokenPipeError on stdout write must also be retried."""
    adapter = ClaudeAdapter()

    responses = [
        _proc_with_communicate_error(BrokenPipeError("pipe closed")),
        mock_proc(stdout=DUMMY_CLAUDE_JSON, returncode=0),
    ]

    call_count = {"n": 0}

    def side_effect(*args, **kwargs):
        proc = responses[call_count["n"]]
        call_count["n"] += 1
        return proc

    with patch("subprocess.Popen", side_effect=side_effect):
        with patch("time.sleep"):
            result = adapter.run(
                "hi", model="haiku-4-5-20251001", cwd=Path("/tmp")
            )

    assert result.exit_code == 0
    assert result.retry_count == 1


def test_transient_exhaustion_raises_adapter_error():
    """After 3 transient errors, base.run() must raise AdapterError AND
    must have actually attempted all 3 (i.e. retried). The previous code
    raised AdapterError after the first attempt and burned no retries —
    we catch that by asserting subprocess.Popen was called 3 times."""
    adapter = ClaudeAdapter()

    responses = [
        _proc_with_communicate_error(ConnectionError("peer reset")),
        _proc_with_communicate_error(ConnectionError("peer reset")),
        _proc_with_communicate_error(ConnectionError("peer reset")),
    ]

    with patch("subprocess.Popen", side_effect=responses) as mock_popen:
        with patch("time.sleep"):
            with pytest.raises(AdapterError):
                adapter.run(
                    "hi", model="haiku-4-5-20251001", cwd=Path("/tmp")
                )

    assert mock_popen.call_count == 3, (
        f"expected 3 retry attempts (transient is retryable), got "
        f"{mock_popen.call_count}"
    )


def test_adapters_module_exposes_server_error_and_transient_error():
    """Public API: ServerError and TransientError must be importable from
    harness.adapters so call sites (T19, T16a) can catch them by name."""
    from harness.adapters import ServerError, TransientError  # late import (T20 RED)

    assert issubclass(ServerError, AdapterError)
    assert issubclass(TransientError, AdapterError)
    # And neither must be the same as RateLimitError — semantic split.
    assert ServerError is not RateLimitError
    assert TransientError is not RateLimitError


# ---------------------------------------------------------------------------
# Group F: coverage of new helper methods / multimodal path consistency
# ---------------------------------------------------------------------------


def test_classify_from_structured_skips_non_error_envelope():
    """A structured envelope without ``is_error``/``error``/``error_type``
    (e.g. a success body) must short-circuit to None — not get
    re-classified by the text-match fallback on its own content."""
    adapter = ClaudeAdapter()

    success_like = {"result": "ok", "usage": {"input_tokens": 1}}
    assert adapter._classify_from_structured(success_like) is None


def test_classify_from_structured_non_retryable_4xx_returns_none():
    """4xx codes that aren't 429 (e.g. 401, 403, 404) are caller errors,
    not transient — must return None so the caller doesn't retry."""
    adapter = ClaudeAdapter()

    envelope = {"is_error": True, "error": "unauthorized", "status_code": 401}
    assert adapter._classify_from_structured(envelope) is None


def test_classify_from_structured_text_only_rate_limit():
    """Without a numeric status_code, structured text 'rate_limit_error'
    must still classify as RateLimitError."""
    adapter = ClaudeAdapter()

    envelope = {"is_error": True, "error_type": "rate_limit_error"}
    classified = adapter._classify_from_structured(envelope)
    assert isinstance(classified, RateLimitError)


def test_extract_structured_error_returns_none_for_non_dict_json():
    """A JSON array or scalar (e.g. ``["a", "b"]`` or ``"plain string"``)
    must not be treated as an error envelope — return None."""
    adapter = ClaudeAdapter()

    assert adapter._extract_structured_error(json.dumps(["a", "b"])) is None
    assert adapter._extract_structured_error(json.dumps("plain string")) is None
    assert adapter._extract_structured_error("123") is None


def test_extract_structured_error_returns_none_for_unparseable_text():
    """Plain garbage text (not JSON at all) returns None."""
    adapter = ClaudeAdapter()

    assert adapter._extract_structured_error("") is None
    assert adapter._extract_structured_error("not json at all") is None
    assert adapter._extract_structured_error("totally garbled {[]}}}") is None


def test_run_with_attachments_uses_classify_error_for_429():
    """The multimodal path (run_with_attachments) must use the same
    classifier as _execute — a 'HTTP 429' in stderr must surface as
    RateLimitError, not get swallowed by the multimodal code path."""
    adapter = ClaudeAdapter()

    proc = MagicMock()
    proc.communicate = MagicMock(
        return_value=("", "ERROR: HTTP 429 Too Many Requests")
    )
    proc.returncode = 1

    with patch("subprocess.Popen", return_value=proc):
        with pytest.raises(RateLimitError):
            adapter.run_with_attachments(
                "look at this",
                [Path("/dev/null")],  # exists, won't trigger missing-attachment
                model="haiku-4-5-20251001",
                cwd=Path("/tmp"),
            )


def test_execute_non_transient_subprocess_error_raises_adapter_error():
    """A non-ConnectionError/BrokenPipeError subprocess failure (e.g.
    FileNotFoundError when claude binary missing) must surface as
    AdapterError, not TransientError — binary missing is not retryable."""
    adapter = ClaudeAdapter()

    with patch("subprocess.Popen") as mock_popen:
        mock_popen.side_effect = FileNotFoundError("claude: command not found")

        with pytest.raises(AdapterError, match="Failed to execute claude"):
            adapter.run("hi", model="haiku-4-5-20251001", cwd=Path("/tmp"))