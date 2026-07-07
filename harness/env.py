"""Central registry of every ``AUTODEV_*`` environment variable.

T27 — before this module, env-var names were scattered as string
literals across ``router.py`` / ``pipeline.py`` / ``generator.py`` /
``reviewer_runner.py`` / ``ui_phase.py``. A typo would silently read
``None`` at runtime; a rename would orphan callers with no central
source of truth. The :class:`EnvVars` dataclass below is the single
place these names live; new callers reference ``EnvVars.MODEL_PREFIX``
instead of re-typing the string.

The full table is also published in ``docs/ENV.md`` so operators have
a human-readable version to grep / point new contributors at.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class EnvVars:
    """Names of every ``AUTODEV_*`` environment variable.

    Prefixes are exposed as ``<NAME>_PREFIX`` and the caller formats
    them as ``f"{prefix}{TIER_NAME.upper()}"``. Standalone vars
    (feedback / choice / visual base url / test mode) are exposed as
    full constant strings.
    """

    # Per-tier overrides consumed by router.ModelRouter.resolve().
    # Format: ``AUTODEV_MODEL_<TIER>`` where <TIER> is one of
    # architect / reviewer / worker.
    MODEL_PREFIX: str = "AUTODEV_MODEL_"
    BASE_URL_PREFIX: str = "AUTODEV_BASE_URL_"
    FALLBACK_PREFIX: str = "AUTODEV_FALLBACK_"
    API_KEY_PREFIX: str = "AUTODEV_API_KEY_"

    # Plan-phase human feedback loop.
    PLAN_FEEDBACK: str = "AUTODEV_PLAN_FEEDBACK"

    # UI-phase human feedback loop.
    UI_CHOICE: str = "AUTODEV_UI_CHOICE"
    UI_FEEDBACK: str = "AUTODEV_UI_FEEDBACK"
    UI_DIRECTION: str = "AUTODEV_UI_DIRECTION"

    # Visual reviewer dev-server URL.
    VISUAL_BASE_URL: str = "AUTODEV_VISUAL_BASE_URL"

    # Test mode flag — disables slow-test skip in CI.
    TEST_MODE: str = "AUTODEV_TEST_MODE"


def model_for(tier: str) -> str:
    """Return the env var name that overrides the model for *tier*."""
    return f"{EnvVars.MODEL_PREFIX}{tier.upper()}"


def api_key_for(tier: str) -> str:
    """Return the env var name that overrides the API key for *tier*."""
    return f"{EnvVars.API_KEY_PREFIX}{tier.upper()}"


def base_url_for(tier: str) -> str:
    """Return the env var name that overrides base_url for *tier*."""
    return f"{EnvVars.BASE_URL_PREFIX}{tier.upper()}"


def fallback_for(tier: str) -> str:
    """Return the env var name that overrides fallback model for *tier*."""
    return f"{EnvVars.FALLBACK_PREFIX}{tier.upper()}"