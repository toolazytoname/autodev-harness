"""Claude-specific error classification (T36 extract).

T20 made the classifier structured-first with word-boundary regex
fallback; T30 wired the per-provider quota loop. T36 hoists the
five functions + three regex/key constants out of ``claude.py``
into this module so the adapter file can focus on subprocess +
retry orchestration, not on error-pattern strings.

Backwards-compat: ``harness.adapters.claude`` re-exports the same
names (incl. private ``_RATE_LIMIT_RE`` etc.) so existing tests
and call-sites stay unbroken.
"""

from __future__ import annotations

import json
import re
from typing import Optional

from harness.adapters.base import (
    AdapterError,
    QuotaExhaustedError,
    RateLimitError,
    ServerError,
)
from harness.adapters.json_envelope import extract_json, strip_code_fence
from harness.quota import QuotaSignal, classify_quota_error, load_quota_config


# Cached for cheap access in the per-call classifier. Load once at
# import time so the quota loop is a pure regex sweep.
_QUOTA_CONFIG = load_quota_config()


# ---------------------------------------------------------------------------
# Regex / key constants
# ---------------------------------------------------------------------------


# Word-boundary matchers: ``\b429\b`` alone matches noise like
# ``/var/log/app-429/access.log`` because ``-`` and ``/`` are non-word
# chars and form a "boundary". So 429 / 5xx are anchored to *context*:
# an HTTP status line, a status field, or a known error phrase.
_RATE_LIMIT_RE = re.compile(
    r"\bHTTP[\s/][\d.]*\s*429\b"
    r"|\bstatus(?:\s+code)?\s*[:=]?\s*429\b"
    r"|\b429\s+Too\s+Many\s+Requests\b"
    r"|\brate[\s\-_]?limit\b"
    r"|\btoo\s+many\s+requests\b",
    re.IGNORECASE,
)

_5XX_RE = re.compile(
    r"\bHTTP[\s/][\d.]*\s*(?:500|502|503|504)\b"
    r"|\bstatus(?:\s+code)?\s*[:=]?\s*(?:500|502|503|504)\b"
    r"|\b(?:500|502|503|504)\s+"
    r"(?:Internal\s+Server\s+Error|Bad\s+Gateway|"
    r"Service\s+Unavailable|Gateway\s+Timeout)\b",
    re.IGNORECASE,
)

_STRUCTURED_ERROR_KEYS = ("is_error", "error", "status_code", "error_type")


# ---------------------------------------------------------------------------
# Classifier functions (extracted verbatim from claude.py)
# ---------------------------------------------------------------------------


def classify_error(
    stderr: str,
    stdout: str,
    exit_code: int,
    server_error_codes: set[int],
) -> Optional[AdapterError]:
    """Classify subprocess output into a retryable error type.

    Returns
    -------
    Optional[AdapterError]
        - ``QuotaExhaustedError`` for usage-limit / balance signals
          (T16a — NOT retried; T16c/T16d downgrade or suspend).
        - ``RateLimitError`` for 429 / rate-limit signals
        - ``ServerError`` for 5xx upstream signals
        - ``None`` if no retryable error is detected — caller should
          fall through to the normal exit_code / JSON parse path.

    Order of preference (T20):
    1. **Structured JSON** envelope from ``--output-format json`` —
       preferred because it carries a real ``status_code`` instead of
       guesswork from text.
    2. **Word-boundary substring** fallback on stderr — robust against
       "429" or "500" appearing in paths, token counts, or line numbers
       (the bug the old bare ``"429" in stderr`` matcher had).

    Quota check (T16a) runs first across stderr + structured error
    text — quota signals are terminal even when they share
    ``status_code == 429`` with transient rate-limit responses.
    """
    structured = extract_structured_error(stdout)
    if structured is not None:
        classified = classify_from_structured(structured, server_error_codes)
        if classified is not None:
            return classified

    # T16a — quota check comes before generic 429 detection so a
    # quota-exhausted 429 isn't mis-classified as a transient rate
    # limit and burned through retry budget.
    quota_signal = classify_quota(stderr, stdout)
    if quota_signal is not None:
        return quota_error(quota_signal, stderr)

    # Word-boundary substring fallback on stderr.
    if _RATE_LIMIT_RE.search(stderr):
        return RateLimitError(
            f"rate-limit signal in stderr: {stderr.strip()[:200]}"
        )
    if _5XX_RE.search(stderr):
        return ServerError(
            f"5xx signal in stderr: {stderr.strip()[:200]}"
        )

    return None


def classify_quota(stderr: str, stdout: str) -> Optional[QuotaSignal]:
    """Run the T16a quota matchers across both stderr and stdout.

    Some providers write the error text into the structured JSON
    envelope (``stdout``) and a free-form description into ``stderr``;
    checking both means we don't depend on which side it lands on.

    T30 — provider is no longer hardcoded. We iterate every provider
    declared in ``_QUOTA_CONFIG`` (anthropic, MiniMax, ...) and use
    the first match. The previous hardcoded ``provider="anthropic"``
    meant the worker-tier (MiniMax) rules in ``config/quota.yaml``
    never fired and MiniMax quota events were mis-classified as
    generic 429s that burned the retry budget.
    """
    for text in (stderr, stdout):
        if not text:
            continue
        for provider_name in _QUOTA_CONFIG.providers:
            signal = classify_quota_error(
                text,
                provider=provider_name,
                config=_QUOTA_CONFIG,
            )
            if signal is not None:
                return signal
    return None


def quota_error(signal: QuotaSignal, stderr: str) -> QuotaExhaustedError:
    """Build a QuotaExhaustedError from a matched signal.

    ``tier`` is filled in by the outer pipeline (the adapter does
    not know which tier triggered the call) — see
    ``AdapterBase.run`` for the post-creation tier attachment.
    """
    return QuotaExhaustedError(
        f"quota exhausted for provider '{signal.provider}': "
        f"{stderr.strip()[:200]}",
        provider=signal.provider,
        reset_hint=signal.reset_hint,
        retry_after_seconds=signal.retry_after_seconds,
    )


def classify_from_structured(
    data: dict,
    server_error_codes: set[int],
) -> Optional[AdapterError]:
    """Build a retryable error from a parsed JSON error envelope."""
    status = data.get("status_code")
    is_error = data.get("is_error", False)
    error_text = str(data.get("error") or data.get("error_type") or "")

    if not (is_error or error_text):
        return None

    # Numeric status code is the strongest signal.
    if isinstance(status, int):
        if status == 429 or (
            400 <= status < 500 and _RATE_LIMIT_RE.search(error_text)
        ):
            return RateLimitError(
                f"rate limit from structured output: {error_text[:200]}"
            )
        if status in server_error_codes or 500 <= status < 600:
            return ServerError(
                f"server error {status} from structured output: "
                f"{error_text[:200]}"
            )
        # Other 4xx are non-retryable — let the caller decide.
        return None

    # No numeric status; fall back to text matching.
    if _RATE_LIMIT_RE.search(error_text) or "rate_limit" in error_text.lower():
        return RateLimitError(
            f"rate limit from structured output: {error_text[:200]}"
        )
    if _5XX_RE.search(error_text):
        return ServerError(
            f"5xx signal in structured error: {error_text[:200]}"
        )
    return None


def extract_structured_error(stdout: str) -> Optional[dict]:
    """Return the error-relevant fields of a JSON envelope, or None.

    A "structured error envelope" is a JSON object containing at least
    one of ``is_error / error / status_code / error_type``. Plain
    success envelopes (``{"result": "...", "usage": {...}}``) return
    None so the caller skips the structured-error branch.
    """
    text = stdout.strip()
    if not text:
        return None
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        text = strip_code_fence(text)
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            data = extract_json(text)
            if data is None:
                return None
    if not isinstance(data, dict):
        return None
    if not any(k in data for k in _STRUCTURED_ERROR_KEYS):
        return None
    return data
