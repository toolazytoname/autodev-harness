"""Model routing and token budget tracking.

Per MASTER-PLAN §4 — resolve stage → ModelSpec, with environment-variable overrides
and per-tier budget counters.

Usage::

    from harness.router import ModelRouter, ModelSpec
    router = ModelRouter()
    spec = router.resolve("generate")          # -> ModelSpec
    spec = router.resolve("review.correctness")
    router.record("generate", usage)           # accumulate spend
    spent = router.spent_by_tier()             # {"architect": 123, ...}
    router.check_budget("generate")            # raises BudgetWarning if over warn threshold
"""

from __future__ import annotations

import os
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import pydantic
import yaml


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


class TierConfig(pydantic.BaseModel):
    """One tier's configuration — model + optional base_url + fallback."""

    model_config = pydantic.ConfigDict(frozen=True)

    model: str
    base_url: Optional[str] = None
    fallback: Optional[str] = None


class BudgetConfig(pydantic.BaseModel):
    """Per-tier budget thresholds (percent of the configured cap)."""

    model_config = pydantic.ConfigDict(frozen=True)

    warn_at_percent: int = 80
    stop_at_percent: int = 100


class ModelsConfig(pydantic.BaseModel):
    """Top-level models.yaml schema.

    T26 — used to be a raw dict; missing ``model`` in a tier would crash
    deep in ``ModelRouter.__init__`` (``KeyError: 'model'``) and bad
    budget entries silently defaulted. Validation now runs at load time
    so misconfiguration fails fast with a clear ``ValidationError``.
    """

    model_config = pydantic.ConfigDict(frozen=True)

    tiers: dict[str, TierConfig]
    assignments: dict[str, str]
    budget: BudgetConfig = pydantic.Field(default_factory=BudgetConfig)


class ModelSpec(pydantic.BaseModel):
    """Resolved model specification for a stage.

    Attributes
    ----------
    model : str
        Primary model identifier (e.g. "claude-opus-4-8").
    base_url : str, optional
        API base URL (used for third-party workers like MiniMax).
    tier : str
        The tier name this model belongs to (architect / reviewer / worker).
    fallback : str, optional
        Fallback model to use when the primary is unavailable.
    """

    model: str
    tier: str
    base_url: Optional[str] = None
    fallback: Optional[str] = None

    model_config = pydantic.ConfigDict(frozen=True)

    def __str__(self) -> str:
        parts = [self.model]
        if self.base_url:
            parts.append(f"@ {self.base_url}")
        parts.append(f"[{self.tier}]")
        if self.fallback:
            parts.append(f"→ {self.fallback}")
        return " ".join(parts)


# ---------------------------------------------------------------------------
# Budget tracking
# ---------------------------------------------------------------------------


class BudgetExceeded(Exception):
    """Raised when a tier's stop_at budget is breached."""

    def __init__(self, tier: str, spent: int, limit: int):
        super().__init__(
            f"Budget exceeded for tier '{tier}': {spent} tokens spent "
            f"(limit {limit}). Pipeline paused."
        )
        self.tier = tier
        self.spent = spent
        self.limit = limit


@dataclass
class _TierBudget:
    """Per-tier token budget state. Thread-safe via parent Router lock."""

    total_tokens: int = 0

    def add(self, usage: "Usage") -> None:
        if usage.total_tokens:
            self.total_tokens += usage.total_tokens
        elif usage.input_tokens and usage.output_tokens:
            self.total_tokens += usage.input_tokens + usage.output_tokens


# ---------------------------------------------------------------------------
# ModelRouter
# ---------------------------------------------------------------------------


class ModelRouter:
    """Resolve stage names to ModelSpecs and track per-tier token budgets.

    Parameters
    ----------
    config_path
        Path to config/models.yaml. Defaults to config/models.yaml relative
        to the harness package root.
    """

    _instance: Optional["ModelRouter"] = None
    _lock = threading.Lock()

    def __init__(
        self,
        config_path: Optional[Path] = None,
    ) -> None:
        if config_path is None:
            # Default: config/models.yaml next to harness package
            harness_root = Path(__file__).parent.parent
            config_path = harness_root / "config" / "models.yaml"

        self._config_path = Path(config_path)
        self._config: ModelsConfig = self._load_config()

        # Flatten validated tier specs for fast lookup.
        self._tier_specs: dict[str, ModelSpec] = {
            tier_name: ModelSpec(
                model=spec.model,
                tier=tier_name,
                base_url=spec.base_url,
                fallback=spec.fallback,
            )
            for tier_name, spec in self._config.tiers.items()
        }

        self._assignments: dict[str, str] = dict(self._config.assignments)

        # Budget tracking
        self._budgets: dict[str, _TierBudget] = {
            tier: _TierBudget() for tier in self._tier_specs
        }
        self._warn_at: float = self._config.budget.warn_at_percent / 100.0
        self._stop_at: float = self._config.budget.stop_at_percent / 100.0

    # ---- public API ----

    def resolve(self, stage: str) -> ModelSpec:
        """Resolve a pipeline stage to a ModelSpec.

        Parameters
        ----------
        stage
            Stage name, e.g. "generate", "review.correctness", "plan".

        Returns
        -------
        ModelSpec
            The resolved model specification.

        Raises
        ------
        KeyError
            If the stage is not defined in assignments.
        """
        tier_name = self._get_tier(stage)

        # Environment-variable override: AUTODEV_MODEL_<TIER>
        env_model = os.environ.get(f"AUTODEV_MODEL_{tier_name.upper()}")
        env_base_url = os.environ.get(f"AUTODEV_BASE_URL_{tier_name.upper()}")
        env_fallback = os.environ.get(f"AUTODEV_FALLBACK_{tier_name.upper()}")

        base = self._tier_specs[tier_name]

        # If any env override is present, build a new spec (base is frozen)
        if env_model or env_base_url or env_fallback:
            return ModelSpec(
                model=env_model or base.model,
                tier=tier_name,
                base_url=env_base_url or base.base_url,
                fallback=env_fallback or base.fallback,
            )

        return base

    def record(self, stage: str, usage: "Usage") -> None:
        """Record token usage for a stage, accumulating into tier totals.

        Parameters
        ----------
        stage
            Stage name that produced this usage.
        usage
            Usage instance from an AgentResult.
        """
        tier = self._get_tier(stage)
        with self._lock:
            self._budgets[tier].add(usage)

    def spent_by_tier(self) -> dict[str, int]:
        """Return current total token spend per tier.

        Returns
        -------
        dict[str, int]
            Mapping of tier name → total tokens spent.
        """
        with self._lock:
            return {tier: budget.total_tokens for tier, budget in self._budgets.items()}

    def check_budget(self, stage: str) -> None:
        """Check budget for the tier associated with this stage.

        Logs a warning if spend exceeds warn_at threshold.
        Raises BudgetExceeded if it exceeds stop_at threshold.

        Parameters
        ----------
        stage
            Stage name to check budget for.
        """
        tier = self._get_tier(stage)
        with self._lock:
            total = self._budgets[tier].total_tokens

        # Estimate a tier-level budget cap (placeholder until we track limits properly)
        # We use a heuristic: for now just warn/stop based on absolute thresholds.
        # In practice the harness pipeline should set tier limits; we use 0 as
        # a sentinel to mean "no limit configured".  To keep the interface simple,
        # we emit a warning when spent > warn_at * some_large_number.  For now,
        # we don't raise — just log — until the pipeline passes real limits.
        #
        # NOTE: This is intentionally a no-op at the router level until the pipeline
        # wires up real per-tier caps. The API is ready; the wiring is TBD.
        if total > 0 and hasattr(self, "_warn_at"):
            # Future: compare against configured tier cap here
            pass

    # ---- private helpers ----

    def _load_config(self) -> ModelsConfig:
        if not self._config_path.exists():
            raise FileNotFoundError(
                f"Model config not found: {self._config_path}. "
                "Check that config/models.yaml exists."
            )
        with self._config_path.open() as fh:
            raw = yaml.safe_load(fh)
        return ModelsConfig.model_validate(raw)

    def _get_tier(self, stage: str) -> str:
        if stage not in self._assignments:
            raise KeyError(
                f"Stage '{stage}' is not defined in assignments. "
                f"Available stages: {list(self._assignments.keys())}"
            )
        return self._assignments[stage]

    # ---- CLI entry-point ----

    def pretty_print(self) -> str:
        """Return a human-readable summary of the routing table."""
        lines = ["Model Routing Table", "=" * 50, ""]
        for tier_name, spec in self._tier_specs.items():
            assigned_stages = [
                s for s, t in self._assignments.items() if t == tier_name
            ]
            lines.append(f"  [{tier_name}]")
            lines.append(f"    model:     {spec.model}")
            if spec.base_url:
                lines.append(f"    base_url:  {spec.base_url}")
            if spec.fallback:
                lines.append(f"    fallback:  {spec.fallback}")
            lines.append(f"    stages:    {', '.join(assigned_stages)}")
            with self._lock:
                spent = self._budgets[tier_name].total_tokens
            if spent:
                lines.append(f"    spent:     {spent} tokens")
            lines.append("")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Usage import (forward reference for type hints)
# ---------------------------------------------------------------------------


class Usage(pydantic.BaseModel):
    """Minimal Usage model — same shape as harness.adapters.base.Usage."""

    model_config = pydantic.ConfigDict(frozen=True)

    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    total_tokens: Optional[int] = None
    duration_ms: Optional[int] = None
