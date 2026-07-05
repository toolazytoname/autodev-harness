"""Tests for the model routing and budget tracking layer.

Per MASTER-PLAN §4 — covers resolve / env-var override / fallback / budget.
"""

from __future__ import annotations

import os
import threading
from pathlib import Path
from unittest.mock import patch

import pydantic
import pytest
import yaml

from harness.router import (
    BudgetExceeded,
    ModelRouter,
    ModelSpec,
    Usage,
    _TierBudget,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_minimal_config(tmp_path: Path) -> Path:
    """Write a minimal models.yaml and return its path."""
    config = {
        "tiers": {
            "architect": {
                "model": "claude-opus-4-8",
                "fallback": "claude-sonnet-4-6",
            },
            "reviewer": {
                "model": "claude-sonnet-4-6",
                "fallback": "haiku-4-5",
            },
            "worker": {
                "model": "MiniMax-M2.7",
                "base_url": "https://api.minimaxi.com/anthropic",
                "fallback": "haiku-4-5",
            },
        },
        "budget": {
            "warn_at_percent": 80,
            "stop_at_percent": 100,
        },
        "assignments": {
            "research":           "worker",
            "plan":               "architect",
            "generate":           "worker",
            "review.correctness": "reviewer",
            "review.test":        "worker",
        },
    }
    p = tmp_path / "models.yaml"
    p.write_text(yaml.safe_dump(config))
    return p


# ---------------------------------------------------------------------------
# Test: ModelSpec
# ---------------------------------------------------------------------------

class TestModelSpec:
    def test_frozen_immutable(self):
        spec = ModelSpec(model="opus", tier="architect", fallback="sonnet")
        with pytest.raises(pydantic.ValidationError):
            spec.model = "sonnet"  # type: ignore

    def test_str_basic(self):
        spec = ModelSpec(model="claude-opus-4-8", tier="architect")
        assert "claude-opus-4-8" in str(spec)
        assert "[architect]" in str(spec)

    def test_str_with_base_url(self):
        spec = ModelSpec(
            model="MiniMax-M2.7",
            tier="worker",
            base_url="https://api.minimaxi.com/anthropic",
        )
        s = str(spec)
        assert "MiniMax-M2.7" in s
        assert "api.minimaxi.com" in s

    def test_str_with_fallback(self):
        spec = ModelSpec(
            model="claude-opus-4-8",
            tier="architect",
            fallback="claude-sonnet-4-6",
        )
        s = str(spec)
        assert "→ claude-sonnet-4-6" in s


# ---------------------------------------------------------------------------
# Test: _TierBudget
# ---------------------------------------------------------------------------

class TestTierBudget:
    def test_add_total_tokens(self):
        b = _TierBudget()
        b.add(Usage(total_tokens=100))
        assert b.total_tokens == 100

    def test_add_separate_tokens(self):
        b = _TierBudget()
        b.add(Usage(input_tokens=30, output_tokens=70))
        assert b.total_tokens == 100

    def test_add_ignores_none(self):
        b = _TierBudget()
        b.add(Usage())
        assert b.total_tokens == 0

    def test_accumulates(self):
        b = _TierBudget()
        b.add(Usage(total_tokens=50))
        b.add(Usage(total_tokens=30))
        assert b.total_tokens == 80


# ---------------------------------------------------------------------------
# Test: ModelRouter — basic resolve
# ---------------------------------------------------------------------------

class TestModelRouterResolve:
    def test_resolve_worker_stage(self, tmp_path):
        config_path = make_minimal_config(tmp_path)
        router = ModelRouter(config_path=config_path)
        spec = router.resolve("generate")
        assert spec.model == "MiniMax-M2.7"
        assert spec.tier == "worker"
        assert spec.base_url == "https://api.minimaxi.com/anthropic"
        assert spec.fallback == "haiku-4-5"

    def test_resolve_architect_stage(self, tmp_path):
        config_path = make_minimal_config(tmp_path)
        router = ModelRouter(config_path=config_path)
        spec = router.resolve("plan")
        assert spec.model == "claude-opus-4-8"
        assert spec.tier == "architect"
        assert spec.fallback == "claude-sonnet-4-6"

    def test_resolve_reviewer_stage(self, tmp_path):
        config_path = make_minimal_config(tmp_path)
        router = ModelRouter(config_path=config_path)
        spec = router.resolve("review.correctness")
        assert spec.model == "claude-sonnet-4-6"
        assert spec.tier == "reviewer"

    def test_resolve_unknown_stage_raises_key_error(self, tmp_path):
        config_path = make_minimal_config(tmp_path)
        router = ModelRouter(config_path=config_path)
        with pytest.raises(KeyError, match="not defined in assignments"):
            router.resolve("nonexistent")

    def test_resolve_worker_from_research(self, tmp_path):
        config_path = make_minimal_config(tmp_path)
        router = ModelRouter(config_path=config_path)
        spec = router.resolve("research")
        assert spec.tier == "worker"
        assert spec.model == "MiniMax-M2.7"


# ---------------------------------------------------------------------------
# Test: ModelRouter — environment variable overrides
# ---------------------------------------------------------------------------

class TestModelRouterEnvOverride:
    def test_env_model_override(self, tmp_path):
        config_path = make_minimal_config(tmp_path)
        with patch.dict(os.environ, {"AUTODEV_MODEL_ARCHITECT": "claude-opus-4-7"}, clear=False):
            router = ModelRouter(config_path=config_path)
            spec = router.resolve("plan")
            assert spec.model == "claude-opus-4-7"
            assert spec.tier == "architect"

    def test_env_base_url_override(self, tmp_path):
        config_path = make_minimal_config(tmp_path)
        with patch.dict(os.environ, {"AUTODEV_BASE_URL_WORKER": "https://custom.api.com"}, clear=False):
            router = ModelRouter(config_path=config_path)
            spec = router.resolve("generate")
            assert spec.base_url == "https://custom.api.com"
            assert spec.model == "MiniMax-M2.7"  # unchanged

    def test_env_fallback_override(self, tmp_path):
        config_path = make_minimal_config(tmp_path)
        with patch.dict(os.environ, {"AUTODEV_FALLBACK_REVIEWER": "haiku-4-6"}, clear=False):
            router = ModelRouter(config_path=config_path)
            spec = router.resolve("review.correctness")
            assert spec.fallback == "haiku-4-6"

    def test_env_all_override_at_once(self, tmp_path):
        config_path = make_minimal_config(tmp_path)
        env = {
            "AUTODEV_MODEL_WORKER": "claude-haiku-4-5",
            "AUTODEV_BASE_URL_WORKER": "https://override.com",
            "AUTODEV_FALLBACK_WORKER": "gpt-4o-mini",
        }
        with patch.dict(os.environ, env, clear=False):
            router = ModelRouter(config_path=config_path)
            spec = router.resolve("generate")
            assert spec.model == "claude-haiku-4-5"
            assert spec.base_url == "https://override.com"
            assert spec.fallback == "gpt-4o-mini"

    def test_env_case_insensitive_tier_name(self, tmp_path):
        config_path = make_minimal_config(tmp_path)
        with patch.dict(os.environ, {"AUTODEV_MODEL_REVIEWER": "sonnet-5"}, clear=False):
            router = ModelRouter(config_path=config_path)
            spec = router.resolve("review.correctness")
            assert spec.model == "sonnet-5"


# ---------------------------------------------------------------------------
# Test: ModelRouter — budget tracking
# ---------------------------------------------------------------------------

class TestModelRouterBudget:
    def test_record_accumulates_per_tier(self, tmp_path):
        config_path = make_minimal_config(tmp_path)
        router = ModelRouter(config_path=config_path)
        router.record("generate", Usage(total_tokens=100))
        router.record("research", Usage(total_tokens=50))
        router.record("review.test", Usage(total_tokens=200))  # also worker tier
        spent = router.spent_by_tier()
        assert spent["worker"] == 350
        assert spent["architect"] == 0
        assert spent["reviewer"] == 0

    def test_record_separate_input_output(self, tmp_path):
        config_path = make_minimal_config(tmp_path)
        router = ModelRouter(config_path=config_path)
        router.record("plan", Usage(input_tokens=1000, output_tokens=500))
        spent = router.spent_by_tier()
        assert spent["architect"] == 1500

    def test_spent_by_tier_returns_all_tiers(self, tmp_path):
        config_path = make_minimal_config(tmp_path)
        router = ModelRouter(config_path=config_path)
        spent = router.spent_by_tier()
        assert "architect" in spent
        assert "reviewer" in spent
        assert "worker" in spent

    def test_record_idempotent(self, tmp_path):
        config_path = make_minimal_config(tmp_path)
        router = ModelRouter(config_path=config_path)
        usage = Usage(total_tokens=100)
        router.record("generate", usage)
        router.record("generate", usage)
        router.record("generate", usage)
        assert router.spent_by_tier()["worker"] == 300


# ---------------------------------------------------------------------------
# Test: ModelRouter — pretty print
# ---------------------------------------------------------------------------

class TestModelRouterPrettyPrint:
    def test_pretty_print_contains_tiers(self, tmp_path):
        config_path = make_minimal_config(tmp_path)
        router = ModelRouter(config_path=config_path)
        output = router.pretty_print()
        assert "architect" in output
        assert "reviewer" in output
        assert "worker" in output
        assert "MiniMax-M2.7" in output
        assert "claude-opus-4-8" in output

    def test_pretty_print_shows_assigned_stages(self, tmp_path):
        config_path = make_minimal_config(tmp_path)
        router = ModelRouter(config_path=config_path)
        output = router.pretty_print()
        assert "plan" in output  # architect stage
        assert "generate" in output  # worker stage


# ---------------------------------------------------------------------------
# Test: ModelRouter — missing config
# ---------------------------------------------------------------------------

def test_missing_config_raises_file_not_found(tmp_path):
    fake = tmp_path / "nonexistent.yaml"
    with pytest.raises(FileNotFoundError, match="not found"):
        ModelRouter(config_path=fake)


# ---------------------------------------------------------------------------
# Test: thread safety on budget
# ---------------------------------------------------------------------------

def test_budget_thread_safety(tmp_path):
    """Simulate concurrent record() calls from multiple threads."""
    config_path = make_minimal_config(tmp_path)
    router = ModelRouter(config_path=config_path)
    usage = Usage(total_tokens=1)

    def add_many(n: int) -> None:
        for _ in range(n):
            router.record("generate", usage)

    threads = [threading.Thread(target=add_many, args=(1000,)) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert router.spent_by_tier()["worker"] == 10000
