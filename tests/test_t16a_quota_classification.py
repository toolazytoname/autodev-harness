"""RED tests for T16a — quota-exhausted error classification.

Per TASKS.md T16a: distinguish "rate limit" (transient 429 → back-off)
from "quota exhausted" (usage limit / balance depleted → do NOT back
off; surface as ``QuotaExhaustedError`` with tier/provider/reset_hint
so T16c/T16d can downgrade or suspend).

Patterns are data-driven via ``config/quota.yaml`` — the regexes can
be tuned without code changes because providers love to tweak their
error strings.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

from harness.adapters.base import AdapterError
from harness.adapters.claude import ClaudeAdapter
from harness.quota import (
    QuotaExhaustedError,
    QuotaSignal,
    classify_quota_error,
    load_quota_config,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_minimal_quota_yaml(path: Path) -> Path:
    """Write a minimal quota.yaml for tests."""
    cfg = {
        "providers": {
            "anthropic": {
                "patterns": [
                    r"\busage\s+limit\b",
                    r"\binsufficient\s+(?:balance|quota|credits)\b",
                    r"rate_limit_error.*resets at",
                ],
                "reset_hint": {
                    "retry_after": r"retry[-_ ]after\s*[:=]?\s*(\d+)s?",
                    "resets_at": r"resets at ([0-9TZ:\-\.]+)",
                },
            },
            "MiniMax": {
                "patterns": [
                    r"insufficient balance",
                    r"余额不足",
                ],
                "reset_hint": {
                    "retry_after": r"retry[-_ ]after\s*[:=]?\s*(\d+)s?",
                },
            },
        }
    }
    path.write_text(yaml.safe_dump(cfg))
    return path


# ---------------------------------------------------------------------------
# Test: load_quota_config reads patterns from YAML
# ---------------------------------------------------------------------------


class TestLoadQuotaConfig:
    def test_loads_anthropic_patterns(self, tmp_path):
        path = _write_minimal_quota_yaml(tmp_path / "quota.yaml")
        cfg = load_quota_config(path)
        assert "anthropic" in cfg.providers
        assert "MiniMax" in cfg.providers
        joined = " ".join(cfg.providers["anthropic"].patterns).lower()
        assert "usage" in joined
        assert "insufficient" in joined

    def test_loads_minimax_patterns(self, tmp_path):
        path = _write_minimal_quota_yaml(tmp_path / "quota.yaml")
        cfg = load_quota_config(path)
        assert "MiniMax" in cfg.providers
        joined = " ".join(cfg.providers["MiniMax"].patterns)
        assert "balance" in joined or "余额" in joined


# ---------------------------------------------------------------------------
# Test: classify_quota_error distinguishes quota from rate-limit
# ---------------------------------------------------------------------------


class TestClassifyQuotaError:
    def test_anthropic_usage_limit_is_quota(self, tmp_path):
        path = _write_minimal_quota_yaml(tmp_path / "quota.yaml")
        cfg = load_quota_config(path)
        text = "Error: usage limit reached for claude-opus-4-8"
        signal = classify_quota_error(text, provider="anthropic", config=cfg)
        assert signal is not None
        assert signal.provider == "anthropic"

    def test_minimax_insufficient_balance_is_quota(self, tmp_path):
        path = _write_minimal_quota_yaml(tmp_path / "quota.yaml")
        cfg = load_quota_config(path)
        signal = classify_quota_error(
            "Error: insufficient balance. Please top up.",
            provider="MiniMax",
            config=cfg,
        )
        assert signal is not None
        assert signal.provider == "MiniMax"

    def test_chinese_balance_message_is_quota(self, tmp_path):
        path = _write_minimal_quota_yaml(tmp_path / "quota.yaml")
        cfg = load_quota_config(path)
        signal = classify_quota_error(
            "错误：账户余额不足，请充值", provider="MiniMax", config=cfg
        )
        assert signal is not None

    def test_transient_429_is_not_quota(self, tmp_path):
        path = _write_minimal_quota_yaml(tmp_path / "quota.yaml")
        cfg = load_quota_config(path)
        # Plain 429 Too Many Requests — must NOT match quota patterns.
        signal = classify_quota_error(
            "ERROR: 429 Too Many Requests — slow down",
            provider="anthropic",
            config=cfg,
        )
        assert signal is None

    def test_reset_hint_parsed_from_text(self, tmp_path):
        path = _write_minimal_quota_yaml(tmp_path / "quota.yaml")
        cfg = load_quota_config(path)
        text = (
            "rate_limit_error: usage limit reached, "
            "resets at 2026-07-08T00:00:00Z"
        )
        signal = classify_quota_error(text, provider="anthropic", config=cfg)
        assert signal is not None
        assert signal.reset_hint is not None
        assert "2026-07-08" in signal.reset_hint

    def test_retry_after_parsed_as_seconds(self, tmp_path):
        path = _write_minimal_quota_yaml(tmp_path / "quota.yaml")
        cfg = load_quota_config(path)
        signal = classify_quota_error(
            "insufficient balance (retry-after: 3600 seconds)",
            provider="MiniMax",
            config=cfg,
        )
        assert signal is not None
        # Either reset_hint carries the text or retry_after_seconds is set.
        assert signal.retry_after_seconds == 3600 or signal.reset_hint is not None


# ---------------------------------------------------------------------------
# Test: claude adapter raises QuotaExhaustedError on quota signal
# ---------------------------------------------------------------------------


class TestClaudeAdapterQuota:
    def test_quota_error_raises_quota_exhausted_not_rate_limit(self, tmp_path):
        quota_yaml = tmp_path / "quota.yaml"
        _write_minimal_quota_yaml(quota_yaml)

        adapter = ClaudeAdapter()
        quota_proc = MagicMock(
            return_value=MagicMock(
                returncode=1,
                communicate=MagicMock(
                    return_value=("", "Error: usage limit reached for claude-opus-4-8")
                ),
            )
        )

        with patch("subprocess.Popen", quota_proc):
            with patch(
                "harness.adapters.claude.load_quota_config",
                return_value=load_quota_config(quota_yaml),
            ):
                with pytest.raises(QuotaExhaustedError) as exc_info:
                    adapter.run(
                        "say hi", model="claude-opus-4-8", cwd=Path("/tmp")
                    )

        assert exc_info.value.tier or exc_info.value.provider

    def test_transient_429_still_raises_after_retries(self, tmp_path):
        # T16a must NOT break T20's transient-429 → retry → AdapterError path.
        adapter = ClaudeAdapter()
        proc = MagicMock(
            return_value=MagicMock(
                returncode=1,
                communicate=MagicMock(
                    return_value=("", "ERROR: 429 Too Many Requests")
                ),
            )
        )
        with patch("subprocess.Popen", proc):
            with patch("time.sleep"):
                with pytest.raises(AdapterError):
                    adapter.run(
                        "say hi",
                        model="haiku-4-5",
                        cwd=Path("/tmp"),
                        timeout=5,
                    )