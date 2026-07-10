"""Base adapter interface and shared types.

All adapters must implement the `run()` method with the same signature,
regardless of the underlying CLI tool (claude, opencode, codex).
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import pydantic


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------


class Usage(pydantic.BaseModel):
    """Token usage for a single agent run.

    All fields are optional because different CLIs report different metrics.
    """

    model_config = pydantic.ConfigDict(frozen=True)

    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    total_tokens: Optional[int] = None
    duration_ms: Optional[int] = None  # wall-clock time in ms


@dataclass
class AgentResult:
    """Result of an agent run via an adapter.

    Attributes
    ----------
    stdout : str
        The raw stdout from the agent. For JSON-mode adapters this should
        contain the parsed JSON body (not wrapped in markdown fences).
    stderr : str
        Any stderr output captured from the underlying process.
    exit_code : int
        Process exit code. 0 = success.
    usage : Usage
        Token usage information (may be partially populated).
    duration_ms : int
        Total wall-clock time in milliseconds for the run.
    retry_count : int
        Number of retries performed before this result (0 = first attempt).
    """

    stdout: str = ""
    stderr: str = ""
    exit_code: int = 0
    usage: Usage = field(default_factory=Usage)
    duration_ms: int = 0
    retry_count: int = 0

    @property
    def success(self) -> bool:
        """Return True iff the subprocess exited with code 0.

        T27 — the legacy implementation also required ``not stderr``,
        which was wrong: CLIs routinely write warnings / debug logs to
        stderr while still exiting cleanly. Smoke tests still called
        ``result.success`` and got a misleading False on those runs.
        Callers that need "no stderr noise" should check ``result.stderr``
        directly.
        """
        return self.exit_code == 0


# ---------------------------------------------------------------------------
# Adapter error types
# ---------------------------------------------------------------------------


class AdapterError(Exception):
    """Base exception for adapter failures."""

    pass


class RateLimitError(AdapterError):
    """Raised when the remote API returns 429 Too Many Requests.

    This is a *transient* rate-limit — the retry loop in ``run()`` will
    back off and try again. For "quota exhausted" / "usage limit" errors
    that should *not* be retried (and that should fall back to a cheaper
    tier), see T16a's ``QuotaExhaustedError``.
    """

    pass


class ServerError(AdapterError):
    """Raised when the remote API returns a 5xx response.

    Semantically distinct from ``RateLimitError``: 5xx means "upstream is
    broken", not "you sent too many requests". Call sites that care
    about the difference (T19, T16a) can split on the exception type.
    The retry loop in ``run()`` treats both as retryable with the same
    exponential back-off.
    """

    pass


class TransientError(AdapterError):
    """Raised for transient OS-level subprocess failures.

    Examples: ``ConnectionError`` (peer reset), ``BrokenPipeError`` (CLI
    closed stdout), DNS hiccups. These were previously wrapped in plain
    ``AdapterError`` by ``claude._execute`` and the retry loop skipped
    them entirely — burning the retry budget on the first failure.

    Surfacing as a dedicated retryable type lets ``run()`` back off and
    try again, the same as ``RateLimitError`` / ``ServerError``.
    """

    pass


class TimeoutError(AdapterError):
    """Raised when the agent run exceeds the configured timeout."""

    pass


class QuotaExhaustedError(AdapterError):
    """Raised when the remote API reports a quota / usage-limit signal.

    Distinct from :class:`RateLimitError`: a 429 Too Many Requests is
    *transient* and the retry loop in :meth:`AdapterBase.run` will
    back off and try again. A quota-exhausted error is *terminal* until
    the provider resets the quota — retrying just wastes the budget.
    T16c/T16d catch this exception to downgrade to a cheaper tier or
    hand off to the OS-level scheduler.

    The structured-data fields (``tier`` / ``provider`` / ``reset_hint``
    / ``retry_after_seconds``) are filled in by the adapter and consumed
    by the M4 auto-resume machinery.
    """

    def __init__(
        self,
        message: str,
        *,
        tier: Optional[str] = None,
        provider: Optional[str] = None,
        reset_hint: Optional[str] = None,
        retry_after_seconds: Optional[int] = None,
    ) -> None:
        super().__init__(message)
        self.tier = tier
        self.provider = provider
        self.reset_hint = reset_hint
        self.retry_after_seconds = retry_after_seconds


class InvalidResponseError(AdapterError):
    """Raised when the agent returns unparseable or unexpected output."""

    pass


# Exceptions that ``AdapterBase.run()`` retries with exponential back-off.
# TimeoutError was previously excluded ("not transient") but in practice
# the most common cause is the upstream provider hanging (proxy flake,
# API overload), which IS transient — and the harness currently has no
# other safety net for this case. Including it here costs ~30s of
# back-off sleep per failure but lets a brief provider outage heal
# without aborting the whole pipeline run. A separate, longer
# ``RETRY_TIMEOUT_BASE_DELAY`` (below) keeps the first retry quiet
# enough that we don't hammer a still-dead endpoint.
RETRYABLE_EXCEPTIONS: tuple[type[AdapterError], ...] = (
    RateLimitError,
    ServerError,
    TransientError,
    TimeoutError,
)

# Known non-retryable errors that should propagate as-is, without being
# wrapped in a generic "Unexpected adapter error" AdapterError.
NON_RETRYABLE_EXCEPTIONS: tuple[type[AdapterError], ...] = (
    QuotaExhaustedError,
    InvalidResponseError,
)


# ---------------------------------------------------------------------------
# Base adapter class
# ---------------------------------------------------------------------------


class AdapterBase(ABC):
    """Abstract base class for all CLI adapters.

    Subclasses must implement `._execute()` and may override `._build_cmd()`.
    The public `run()` method handles retry logic, timeout, and error mapping
    consistently across all adapters.
    """

    # Exponential back-off configuration
    RETRY_BASE_DELAY: float = 1.0  # seconds
    RETRY_MAX_DELAY: float = 32.0
    # TimeoutError retry uses a longer base (10s vs 1s): when the
    # subprocess times out, the upstream is almost certainly still
    # unhealthy; hammering it at 1s intervals just wastes the budget.
    # 10s → 20s gives the provider ~30s to recover before we give up.
    RETRY_TIMEOUT_BASE_DELAY: float = 10.0
    RETRY_MAX_ATTEMPTS: int = 3
    RETRY_RATELIMIT_CODES: set[int] = {429}
    RETRY_SERVER_ERROR_CODES: set[int] = {500, 502, 503, 504}

    def run(
        self,
        prompt: str,
        *,
        model: str,
        cwd: Path | str | None = None,
        timeout: int = 120,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        fallback_model: Optional[str] = None,
        allowed_tools: Optional[list[str]] = None,
    ) -> AgentResult:
        """Run the agent with the given prompt.

        Parameters
        ----------
        prompt
            The prompt (and optional system message) to send to the agent.
        model
            Model identifier to pass to the CLI (e.g. "haiku-4-5").
        cwd
            Working directory for the subprocess. Defaults to current dir.
        timeout
            Per-attempt timeout in seconds. After each retry the full timeout
            is available again (timeout is per attempt, not total).
        base_url
            T19 — API base URL. When provided, the adapter exports
            ``ANTHROPIC_BASE_URL`` into the subprocess environment so worker
            calls hit the third-party endpoint instead of the default.
        api_key
            T19 — API key for this run. Injected as ``ANTHROPIC_API_KEY`` so
            different tiers can target different backends without leaking
            the wrong credential.
        fallback_model
            T19 — model to use when ``model`` exhausts all retries. Wired in
            so ``spec.fallback`` (currently only displayed by
            ``router.pretty_print``) actually does something. The fallback
            gets its own retry budget. Quota-specific downgrade logic is
            T16c and sits on top of this generic fallback.

        Returns
        -------
        AgentResult
            The result of the run including stdout, exit code, and usage.

        Raises
        ------
        AdapterError
            If all retries (primary + fallback) are exhausted or an
            unexpected error occurs.
        TimeoutError
            If the timeout is exceeded on every attempt.
        """
        if isinstance(cwd, str):
            cwd = Path(cwd)
        cwd = cwd or Path.cwd()

        # First attempt: primary model.
        try:
            return self._run_with_retry(
                prompt=prompt,
                model=model,
                cwd=cwd,
                timeout=timeout,
                base_url=base_url,
                api_key=api_key,
                allowed_tools=allowed_tools,
            )
        except RETRYABLE_EXCEPTIONS as primary_exc:
            # Primary exhausted all retries. If a fallback model is wired
            # in, give it one full retry budget. Anything else (timeout,
            # hard failure) propagates unchanged.
            if fallback_model and fallback_model != model:
                return self._run_with_retry(
                    prompt=prompt,
                    model=fallback_model,
                    cwd=cwd,
                    timeout=timeout,
                    base_url=base_url,
                    api_key=api_key,
                    allowed_tools=allowed_tools,
                )
            raise
        except QuotaExhaustedError as primary_exc:
            # T16c — quota on the primary is a "skip to fallback" signal,
            # not a "back off and retry the same model" signal. The
            # primary never gets a second look; if the fallback is also
            # drained the exception propagates so T16d can suspend.
            if fallback_model and fallback_model != model:
                return self._run_with_retry(
                    prompt=prompt,
                    model=fallback_model,
                    cwd=cwd,
                    timeout=timeout,
                    base_url=base_url,
                    api_key=api_key,
                    allowed_tools=allowed_tools,
                )
            raise

    def _run_with_retry(
        self,
        *,
        prompt: str,
        model: str,
        cwd: Path,
        timeout: int,
        base_url: Optional[str],
        api_key: Optional[str],
        allowed_tools: Optional[list[str]],
    ) -> AgentResult:
        """Internal: run a single ``model`` with the standard retry loop.

        Extracted from :meth:`run` so the fallback path can reuse the same
        retry/timeout/classification machinery without duplicating it.

        On retry exhaustion we re-raise the *original* retryable exception
        (RateLimitError / ServerError / TransientError) instead of wrapping
        it in ``AdapterError``. The outer ``run()`` needs the typed
        exception to decide whether to fall back to the configured
        ``fallback_model``; a bare ``AdapterError`` would defeat that
        branching. ``TimeoutError`` and unexpected errors still propagate
        immediately as before.
        """
        attempt = 0
        last_retryable: BaseException | None = None
        last_result: AgentResult | None = None

        while attempt < self.RETRY_MAX_ATTEMPTS:
            try:
                result = self._execute(
                    prompt=prompt,
                    model=model,
                    cwd=cwd,
                    timeout=timeout,
                    attempt=attempt,
                    base_url=base_url,
                    api_key=api_key,
                    allowed_tools=allowed_tools,
                )
                # Success — return immediately
                return result

            except RETRYABLE_EXCEPTIONS as exc:
                # RateLimit / ServerError / TransientError — all back off
                # and retry. Hold the original exception so we can re-raise
                # it on exhaustion (the fallback layer branches on type).
                last_retryable = exc
                last_result = getattr(exc, "_result", None)
                # T34: honor the provider's ``retry_after_seconds`` hint
                # (populated by RateLimitError when the upstream sends
                # ``Retry-After``). Other retryable errors don't carry a
                # hint, so retry_after_seconds is None and the schedule
                # wins.
                retry_after = getattr(exc, "retry_after_seconds", None)
                # TimeoutError gets its own longer base — upstream is
                # usually still unhealthy; the 10s base gives it room.
                base_delay = (
                    self.RETRY_TIMEOUT_BASE_DELAY
                    if isinstance(exc, TimeoutError)
                    else None
                )
                delay = self._backoff_delay(
                    attempt,
                    retry_after_seconds=retry_after,
                    base_delay=base_delay,
                )
                attempt += 1
                if attempt >= self.RETRY_MAX_ATTEMPTS:
                    break
                time.sleep(delay)

            except NON_RETRYABLE_EXCEPTIONS:
                # Timeout / QuotaExhausted — propagate as-is, no retry.
                raise

            except Exception as exc:
                # Unexpected error — do not retry, propagate immediately
                raise AdapterError(f"Unexpected adapter error: {exc}") from exc

        # All retries exhausted. Re-raise the original retryable exception
        # (preserved with its ``_result`` attribute) so callers / the
        # fallback layer can introspect. Fall back to AdapterError when
        # no retryable was ever captured.
        if last_retryable is not None:
            raise last_retryable
        if last_result is not None:
            raise AdapterError(
                f"All {self.RETRY_MAX_ATTEMPTS} attempts failed for model '{model}'. "
                f"Last error: exit={last_result.exit_code}, "
                f"stderr={last_result.stderr!r}"
            )
        raise AdapterError(
            f"All {self.RETRY_MAX_ATTEMPTS} attempts failed for model '{model}' "
            f"without a usable result"
        )

    def _backoff_delay(
        self,
        attempt: int,
        *,
        retry_after_seconds: Optional[int] = None,
        base_delay: Optional[float] = None,
        max_delay: Optional[float] = None,
        jitter_ratio: Optional[float] = None,
    ) -> float:
        """Compute back-off delay for a given attempt number.

        T34 changes:

        1. ``retry_after_seconds`` — when the upstream error carries a
           provider hint (e.g. ``Retry-After: 10``), prefer that value
           over the raw exponential schedule. Clamped to ``max_delay``.
        2. ``jitter_ratio`` — each delay is multiplied by
           ``1 + uniform(-ratio, +ratio)`` to break thundering-herd
           alignment in fleet retries. Defaults to
           :data:`harness.resilience.ResilienceConfig.retry.jitter_ratio`
           (= 0.25) so a fleet of 1000 workers doesn't all hit the API
           at the same instant after a 429.

        All knobs can be overridden per-call; sensible defaults come
        from :mod:`harness.resilience`. Existing call-sites that
        supply no override still work.
        """
        import random

        if base_delay is None:
            base_delay = self.RETRY_BASE_DELAY
        if max_delay is None:
            max_delay = self.RETRY_MAX_DELAY
        if jitter_ratio is None:
            try:
                from harness.resilience import get_resilience_config

                jitter_ratio = get_resilience_config().retry.jitter_ratio
            except Exception:
                jitter_ratio = 0.0  # safe fallback when the module isn't importable

        # Provider hint beats the schedule; clamp to max_delay.
        if retry_after_seconds is not None:
            base = min(float(retry_after_seconds), max_delay)
        else:
            base = min(base_delay * (2**attempt), max_delay)

        # Apply jitter symmetrically: delay ∈ [base*(1-r), base*(1+r)].
        if jitter_ratio > 0:
            jitter = random.uniform(-jitter_ratio, jitter_ratio)
            return base * (1.0 + jitter)
        return base

    def run_with_attachments(
        self,
        prompt: str,
        attachments: list,
        *,
        model: str,
        cwd: Path | str | None = None,
        timeout: int = 120,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        fallback_model: Optional[str] = None,
    ) -> AgentResult:
        """Run the agent with multimodal attachments (images / PDFs).

        Subclasses that support attachments (currently ``ClaudeAdapter``)
        must override this. The default implementation raises a clear
        ``AdapterError`` so the visual reviewer fails immediately when
        pointed at a non-Claude adapter instead of pretending to work.

        Parameters
        ----------
        prompt
            The text prompt.
        attachments
            Iterable of ``Path`` to image/PDF files. Order matters — the
            first attachment is usually the hero/marketing page.
        model
            Model identifier.
        cwd
            Working directory (default: cwd).
        timeout
            Per-attempt timeout in seconds.
        base_url
            T19 — forwarded to the subprocess env as ``ANTHROPIC_BASE_URL``.
        api_key
            T19 — forwarded to the subprocess env as ``ANTHROPIC_API_KEY``.
        fallback_model
            T19 — model to use when ``model`` exhausts retries.
        """
        raise NotImplementedError(
            f"{type(self).__name__} does not support multimodal attachments. "
            "Use ClaudeAdapter, or extend the adapter to forward files to "
            "the underlying CLI."
        )

    @abstractmethod
    def _execute(
        self,
        prompt: str,
        *,
        model: str,
        cwd: Path,
        timeout: int,
        attempt: int,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
    ) -> AgentResult:
        """Execute the agent run. Override in subclasses.

        Subclasses should raise:
        - ``RateLimitError`` on 429 / rate-limit signals (transient → retry)
        - ``ServerError`` on 5xx upstream signals (transient → retry)
        - ``TransientError`` on OS-level subprocess errors
          (ConnectionError / BrokenPipeError → retry)
        - ``TimeoutError`` on timeout (NOT retried)
        - ``AdapterError`` for non-retryable failures

        All retryable exceptions may carry a ``_result: AgentResult``
        attribute that ``run()`` will surface via the final
        ``AdapterError`` raised after retry exhaustion.

        T19 — ``base_url`` and ``api_key`` must reach the underlying CLI's
        subprocess via ``Popen(env=...)`` so third-party workers (e.g.
        MiniMax) are not silently routed at the default endpoint and so
        per-tier credentials don't leak across backends.
        """
        ...
