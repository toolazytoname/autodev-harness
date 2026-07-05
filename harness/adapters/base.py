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
        """Return True only for clean exits with no stderr."""
        return self.exit_code == 0 and not self.stderr


# ---------------------------------------------------------------------------
# Adapter error types
# ---------------------------------------------------------------------------


class AdapterError(Exception):
    """Base exception for adapter failures."""

    pass


class RateLimitError(AdapterError):
    """Raised when the remote API returns 429 Too Many Requests."""

    pass


class TimeoutError(AdapterError):
    """Raised when the agent run exceeds the configured timeout."""

    pass


class InvalidResponseError(AdapterError):
    """Raised when the agent returns unparseable or unexpected output."""

    pass


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

        Returns
        -------
        AgentResult
            The result of the run including stdout, exit code, and usage.

        Raises
        ------
        AdapterError
            If all retries are exhausted or an unexpected error occurs.
        TimeoutError
            If the timeout is exceeded on every attempt.
        """
        if isinstance(cwd, str):
            cwd = Path(cwd)
        cwd = cwd or Path.cwd()

        attempt = 0
        last_result: AgentResult | None = None

        while attempt < self.RETRY_MAX_ATTEMPTS:
            try:
                result = self._execute(
                    prompt=prompt,
                    model=model,
                    cwd=cwd,
                    timeout=timeout,
                    attempt=attempt,
                )
                # Success — return immediately
                return result

            except RateLimitError as exc:
                last_result = getattr(exc, "_result", None)
                delay = self._backoff_delay(attempt)
                attempt += 1
                if attempt >= self.RETRY_MAX_ATTEMPTS:
                    break
                time.sleep(delay)

            except TimeoutError:
                # Do not retry timeouts — they are not transient
                raise

            except Exception as exc:
                # Unexpected error — do not retry, propagate immediately
                raise AdapterError(f"Unexpected adapter error: {exc}") from exc

        # All retries exhausted — promote last error to AdapterError
        if last_result is not None:
            raise AdapterError(
                f"All {self.RETRY_MAX_ATTEMPTS} attempts failed. Last error: "
                f"exit={last_result.exit_code}, stderr={last_result.stderr!r}"
            )
        raise AdapterError(
            f"All {self.RETRY_MAX_ATTEMPTS} attempts failed without a usable result"
        )

    def _backoff_delay(self, attempt: int) -> float:
        """Compute exponential back-off delay for a given attempt number."""
        import math

        delay = self.RETRY_BASE_DELAY * (2**attempt)
        return min(delay, self.RETRY_MAX_DELAY)

    @abstractmethod
    def _execute(
        self,
        prompt: str,
        *,
        model: str,
        cwd: Path,
        timeout: int,
        attempt: int,
    ) -> AgentResult:
        """Execute the agent run. Override in subclasses.

        Subclasses should raise RateLimitError on 429 and TimeoutError on
        timeout so the retry logic in run() can handle them appropriately.
        """
        ...
