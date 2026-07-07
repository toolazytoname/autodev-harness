"""RED tests for T16c — fallback downgrade on quota exhaustion.

Per TASKS.md T16c: when ``QuotaExhaustedError`` is raised by the
primary model, the adapter (or its caller) should automatically
swap to ``spec.fallback`` and continue — but only once. If both the
primary tier and the fallback tier are exhausted, the error
propagates so T16d can suspend the run with a quota-hold and an
OS-level wake-up.

T16c sits ABOVE T19's generic ``fallback_model`` retry path —
generic retry kicks in on any retryable failure, but T16c is the
quota-specific "tier X is drained, skip to the cheaper model"
behaviour.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from harness.adapters.base import QuotaExhaustedError
from harness.adapters.claude import ClaudeAdapter


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


DUMMY_JSON = '{"result": "ok", "usage": {"input_tokens": 1, "output_tokens": 2, "total_tokens": 3}}'


def _mock_proc(stdout: str = "", stderr: str = "", returncode: int = 0):
    proc = MagicMock()
    proc.returncode = returncode
    proc.communicate = MagicMock(return_value=(stdout, stderr))
    return proc


# ---------------------------------------------------------------------------
# Test: QuotaExhaustedError triggers fallback model
# ---------------------------------------------------------------------------


class TestQuotaTriggersFallback:
    def test_quota_exhausted_on_primary_falls_back_to_secondary(self):
        """Primary call raises QuotaExhaustedError → fallback_model used."""
        adapter = ClaudeAdapter()

        # Primary returns quota-exhausted stderr; fallback returns success.
        primary_proc = _mock_proc(
            stderr="Error: usage limit reached for claude-opus-4-8",
            returncode=1,
        )
        fallback_proc = _mock_proc(stdout=DUMMY_JSON, returncode=0)

        # The retryable-exception mechanism in base.run() will raise the
        # QuotaExhaustedError; with fallback_model set, run() should
        # catch it and try the fallback. The fallback's success
        # returns an AgentResult.
        with patch("subprocess.Popen") as mock_popen:
            mock_popen.side_effect = [primary_proc, fallback_proc]
            with patch("time.sleep"):
                result = adapter.run(
                    "say hi",
                    model="claude-opus-4-8",
                    cwd=Path("/tmp"),
                    fallback_model="claude-haiku-4-5-20251001",
                )

        assert result.exit_code == 0
        # The second Popen call must have used the fallback model name.
        last_cmd = mock_popen.call_args_list[-1][0][0]
        assert "claude-haiku-4-5-20251001" in last_cmd

    def test_quota_exhausted_propagates_when_no_fallback(self):
        """No fallback_model → QuotaExhaustedError propagates to caller."""
        adapter = ClaudeAdapter()
        quota_proc = _mock_proc(
            stderr="Error: usage limit reached for claude-opus-4-8",
            returncode=1,
        )
        with patch("subprocess.Popen", return_value=quota_proc):
            with pytest.raises(QuotaExhaustedError):
                adapter.run(
                    "say hi", model="claude-opus-4-8", cwd=Path("/tmp")
                )

    def test_quota_exhausted_does_not_retry_same_model(self):
        """T16c must NOT retry the primary on quota — the whole point of
        T16a was to keep quota signals from burning the retry budget."""
        adapter = ClaudeAdapter()
        quota_proc = _mock_proc(
            stderr="Error: usage limit reached",
            returncode=1,
        )
        call_count = [0]

        def counting_popen(*args, **kwargs):
            call_count[0] += 1
            return quota_proc

        with patch("subprocess.Popen", side_effect=counting_popen):
            with pytest.raises(QuotaExhaustedError):
                adapter.run(
                    "say hi", model="claude-opus-4-8", cwd=Path("/tmp")
                )

        # Primary attempted exactly once — no retries.
        assert call_count[0] == 1


# ---------------------------------------------------------------------------
# Test: when both tiers exhausted, error propagates (T16d's entry point)
# ---------------------------------------------------------------------------


class TestBothTiersExhausted:
    def test_fallback_also_exhausted_propagates(self):
        """If the fallback ALSO raises QuotaExhaustedError, the call
        surfaces that error so T16d can suspend."""
        adapter = ClaudeAdapter()
        quota_proc = _mock_proc(
            stderr="Error: usage limit reached",
            returncode=1,
        )
        with patch("subprocess.Popen", return_value=quota_proc):
            with pytest.raises(QuotaExhaustedError):
                adapter.run(
                    "say hi",
                    model="claude-opus-4-8",
                    cwd=Path("/tmp"),
                    fallback_model="claude-haiku-4-5-20251001",
                )