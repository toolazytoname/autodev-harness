"""Tests for T30 — adapter provider decoupling + JSON envelope extraction.

Two bugs are addressed together:

Bug A — provider routing for quota classification
    ``ClaudeAdapter._classify_quota`` used to hardcode
    ``provider="anthropic"`` when calling ``classify_quota_error``. That
    meant the MiniMax / MiniMax-M2.7 "余额不足" / "insufficient balance"
    rules in ``config/quota.yaml`` never fired for worker-tier calls,
    so a MiniMax quota-exhausted response was mis-classified as a
    generic 429 and burned through the retry budget.

Bug B — is_error envelope eaten as empty stdout
    ``ClaudeAdapter._parse_json_output`` used to look only for
    ``result / content / text`` on a well-formed JSON envelope. A
    ``{"is_error": true, "error": "invalid_request: ...", ...,
    "exit_code": 0}`` response was silently turned into the empty
    string, so downstream code saw "" as if it were a successful empty
    response. The fix raises ``InvalidResponseError`` (non-retryable)
    carrying the error text in the exception message.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from harness.adapters.base import (
    InvalidResponseError,
    RateLimitError,
)
from harness.adapters.claude import ClaudeAdapter
from harness.quota import (
    ProviderRules,
    QuotaConfig,
    QuotaSignal,
    classify_quota_error,
)


# ---------------------------------------------------------------------------
# RED 1 — Bug A: MiniMax / MiniMax "余额不足" must match MiniMax provider
# ---------------------------------------------------------------------------


def test_worker_balance_message_matches_minimax_provider(monkeypatch):
    """A stderr containing '余额不足' (Chinese for "insufficient balance")
    must be classified as a MiniMax provider quota signal — not silently
    dropped because ``_classify_quota`` hardcoded provider="anthropic".

    ``config/quota.yaml`` carries MiniMax-specific patterns; if the
    classifier only ever asks the anthropic rules, those patterns are
    dead code and worker-tier quota events burn 3 retries as a generic
    rate-limit before propagating as AdapterError.
    """
    # Construct a config that mirrors config/quota.yaml's MiniMax block
    # without depending on disk.
    cfg = QuotaConfig(
        providers={
            "anthropic": ProviderRules(
                patterns=[r"\busage\s+limit\b"],
            ),
            "MiniMax": ProviderRules(
                patterns=[
                    r"insufficient\s+balance",
                    r"余额不足",
                ],
            ),
        },
    )

    # The classification primitive itself must match for MiniMax when
    # asked — this is the "regression" the adapter was missing.
    direct_signal = classify_quota_error(
        text="余额不足，请充值",
        provider="MiniMax",
        config=cfg,
    )
    assert direct_signal is not None, (
        "classify_quota_error itself failed to match 余额不足 against "
        "MiniMax provider rules"
    )
    assert direct_signal.provider == "MiniMax"

    # Now exercise the adapter method. Patch the module-level
    # ``_QUOTA_CONFIG`` so we don't depend on the on-disk file.
    import harness.adapters.claude as claude_mod

    monkeypatch.setattr(claude_mod, "_QUOTA_CONFIG", cfg)

    adapter = ClaudeAdapter()
    signal = adapter._classify_quota(
        stderr="余额不足，请充值",
        stdout="",
    )
    assert signal is not None, (
        "_classify_quota dropped the MiniMax signal — provider routing "
        "is still hardcoded somewhere"
    )
    assert signal.provider == "MiniMax"


def test_anthropic_usage_limit_still_matches_anthropic(monkeypatch):
    """Sanity: the anthropic rule must still match anthropic text after
    the provider-decoupling refactor. We didn't trade the MiniMax fix
    for a regression on the original anthropic case."""
    cfg = QuotaConfig(
        providers={
            "anthropic": ProviderRules(
                patterns=[r"\busage\s+limit\b"],
            ),
            "MiniMax": ProviderRules(
                patterns=[
                    r"insufficient\s+balance",
                    r"余额不足",
                ],
            ),
        },
    )

    import harness.adapters.claude as claude_mod

    monkeypatch.setattr(claude_mod, "_QUOTA_CONFIG", cfg)

    adapter = ClaudeAdapter()
    signal = adapter._classify_quota(
        stderr="Error: usage limit reached for this account",
        stdout="",
    )
    assert signal is not None
    assert signal.provider == "anthropic"


# ---------------------------------------------------------------------------
# RED 2 — Bug B: is_error envelope must raise InvalidResponseError
# ---------------------------------------------------------------------------


def test_structured_4xx_does_not_return_empty_string():
    """A ``--output-format json`` envelope with ``is_error: true``,
    ``status_code: 400``, ``exit_code: 0`` must NOT be silently
    turned into an empty string. The adapter must raise
    ``InvalidResponseError`` carrying the error text so the failure
    surfaces as a non-retryable adapter error instead of ""."""
    raw_envelope = json.dumps({
        "is_error": True,
        "error": "invalid_request: missing field 'prompt'",
        "status_code": 400,
        "exit_code": 0,
    })

    adapter = ClaudeAdapter()
    with pytest.raises(InvalidResponseError) as exc_info:
        adapter._parse_json_output(raw_envelope, duration_ms=100, attempt=0)
    # The error text from the envelope must be carried in the message
    # for diagnostics — the failure mode this test guards against is
    # silently returning "" instead of propagating the failure.
    assert "invalid_request" in str(exc_info.value)


def test_structured_error_via_subprocess_path_raises_invalid_response():
    """End-to-end: an is_error envelope returned by the subprocess
    (with exit code 0 and no rate-limit / quota signal) must surface
    as ``InvalidResponseError`` from the post-subprocess path."""
    raw_envelope = json.dumps({
        "is_error": True,
        "error": "invalid_request: missing field",
        "status_code": 400,
        "exit_code": 0,
    })

    proc = MagicMock()
    proc.communicate = MagicMock(return_value=(raw_envelope, ""))
    proc.returncode = 0

    with patch("subprocess.Popen", return_value=proc):
        adapter = ClaudeAdapter()
        with pytest.raises(InvalidResponseError):
            adapter._execute(
                "hello",
                model="haiku-4-5-20251001",
                cwd=Path("/tmp"),
                timeout=10,
                attempt=0,
            )


# ---------------------------------------------------------------------------
# RED 3 — defensive: well-formed success envelope still parses normally
# ---------------------------------------------------------------------------


def test_hard_error_exit_code_zero_with_no_is_error_still_parses():
    """Guard against the new is_error check being too aggressive: a
    well-formed success envelope (``result`` + ``usage``, exit 0) must
    parse normally and return the result text — no exception."""
    raw_envelope = json.dumps({
        "result": "all good",
        "usage": {
            "input_tokens": 5,
            "output_tokens": 7,
            "total_tokens": 12,
        },
    })

    adapter = ClaudeAdapter()
    usage, result_text = adapter._parse_json_output(
        raw_envelope, duration_ms=100, attempt=0,
    )
    assert result_text == "all good"
    assert usage.input_tokens == 5
    assert usage.output_tokens == 7