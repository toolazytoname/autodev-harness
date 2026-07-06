"""Claude CLI adapter.

Calls `claude -p --model X --output-format json` via subprocess.
Handles exponential back-off on 429/5xx/transient errors and strips markdown
fences from output.

Error classification (T20): prefers structured JSON from
``--output-format json`` envelopes when available, and falls back to
word-boundary substring matching on stderr — so a "429" or "500" that
appears as part of a path or token count no longer false-positives a
retry.
"""

from __future__ import annotations

import json
import re
import subprocess
import time
from pathlib import Path
from typing import Optional

from harness.adapters.base import (
    AdapterBase,
    AdapterError,
    AgentResult,
    RateLimitError,
    ServerError,
    TimeoutError,
    TransientError,
    Usage,
)


# ---------------------------------------------------------------------------
# Error classification patterns (T20)
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

# Keys the claude --output-format json envelope uses to signal errors.
_STRUCTURED_ERROR_KEYS = ("is_error", "error", "status_code", "error_type")


class ClaudeAdapter(AdapterBase):
    """Adapter for the `claude` CLI (Anthropic's official tool)."""

    # Increase base delay — claude's rate limits benefit from slightly longer waits
    RETRY_BASE_DELAY: float = 2.0

    def run_with_attachments(
        self,
        prompt: str,
        attachments,
        *,
        model: str,
        cwd: Path | str | None = None,
        timeout: int = 120,
    ) -> AgentResult:
        """Run claude -p with image/PDF attachments.

        The current claude CLI accepts multimodal inputs by listing file
        paths as positional arguments after the prompt (or as stdin
        prompt followed by the files). When attachments are present we
        route them through the same path the CLI uses for screenshots,
        which keeps the JSON-mode behaviour: stdout is the JSON envelope
        with ``result`` and ``usage``.
        """
        from harness.adapters.base import AdapterError  # local import to avoid cycles

        if isinstance(cwd, str):
            cwd = Path(cwd)
        cwd = cwd or Path.cwd()

        attachments = [Path(p) for p in attachments]
        missing = [p for p in attachments if not p.exists()]
        if missing:
            raise AdapterError(f"Attachments not found: {missing}")

        cmd = ["claude", "-p", "--model", model, "--output-format", "json"]
        cmd.extend(str(p) for p in attachments)

        start_time = time.monotonic()
        try:
            proc = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=cwd,
                text=True,
                encoding="utf-8",
            )
            assert proc.stdin is not None
            assert proc.stdout is not None
            assert proc.stderr is not None
            try:
                stdout, stderr = proc.communicate(input=prompt, timeout=timeout)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
                raise TimeoutError(
                    f"claude multimodal subprocess timed out after {timeout}s"
                )
        except TimeoutError:
            raise
        except (ConnectionError, BrokenPipeError) as exc:
            # Transient OS-level errors (peer reset, pipe closed). Surface as
            # TransientError so the retry loop in base.run() backs off and
            # tries again instead of burning the budget on the first attempt.
            raise TransientError(
                f"transient subprocess error (multimodal): {exc}"
            ) from exc
        except Exception as exc:
            raise AdapterError(f"Failed to execute claude (multimodal): {exc}") from exc

        exit_code = proc.returncode
        duration_ms = int((time.monotonic() - start_time) * 1000)

        classified = self._classify_error(stderr, stdout, exit_code)
        if classified is not None:
            classified._result = AgentResult(  # type: ignore[attr-defined]
                stdout=stdout,
                stderr=stderr,
                exit_code=exit_code,
                usage=Usage(duration_ms=duration_ms),
                retry_count=0,
            )
            raise classified

        if exit_code != 0:
            raise AdapterError(
                f"claude (multimodal) exited with code {exit_code}: {stderr.strip()}"
            )

        usage, result_text = self._parse_json_output(stdout, duration_ms, 0)
        return AgentResult(
            stdout=result_text,
            stderr=stderr,
            exit_code=exit_code,
            usage=usage,
            duration_ms=duration_ms,
            retry_count=0,
        )

    def _build_cmd(
        self,
        prompt: str,
        model: str,
        cwd: Path,
    ) -> list[str]:
        """Build the subprocess command list."""
        return [
            "claude",
            "-p",
            "--model",
            model,
            "--output-format",
            "json",
        ]

    def _execute(
        self,
        prompt: str,
        *,
        model: str,
        cwd: Path,
        timeout: int,
        attempt: int,
    ) -> AgentResult:
        """Execute a single claude -p invocation."""
        cmd = self._build_cmd(prompt, model, cwd)

        start_time = time.monotonic()

        try:
            proc = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=cwd,
                text=True,
                encoding="utf-8",
            )
            assert proc.stdin is not None
            assert proc.stdout is not None
            assert proc.stderr is not None

            try:
                stdout, stderr = proc.communicate(input=prompt, timeout=timeout)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
                raise TimeoutError(f"claude subprocess timed out after {timeout}s")

        except TimeoutError:
            raise
        except (ConnectionError, BrokenPipeError) as exc:
            # Transient OS-level errors (peer reset, pipe closed). Surface as
            # TransientError so the retry loop in base.run() backs off and
            # tries again instead of burning the budget on the first attempt.
            raise TransientError(
                f"transient subprocess error: {exc}"
            ) from exc
        except Exception as exc:
            raise AdapterError(f"Failed to execute claude: {exc}") from exc

        exit_code = proc.returncode
        duration_ms = int((time.monotonic() - start_time) * 1000)

        # T20 error classification: prefers structured JSON envelope, falls
        # back to word-boundary substring matching on stderr. Returns
        # RateLimitError / ServerError / None — never raises on its own.
        classified = self._classify_error(stderr, stdout, exit_code)
        if classified is not None:
            classified._result = AgentResult(  # type: ignore[attr-defined]
                stdout=stdout,
                stderr=stderr,
                exit_code=exit_code,
                usage=Usage(duration_ms=duration_ms),
                retry_count=attempt,
            )
            raise classified

        if exit_code != 0:
            raise AdapterError(
                f"claude exited with code {exit_code}: {stderr.strip()}"
            )

        # Parse usage + result from JSON output
        usage, result_text = self._parse_json_output(stdout, duration_ms, attempt)

        return AgentResult(
            stdout=result_text,
            stderr=stderr,
            exit_code=exit_code,
            usage=usage,
            duration_ms=duration_ms,
            retry_count=attempt,
        )

    def _parse_json_output(
        self,
        raw_stdout: str,
        duration_ms: int,
        attempt: int,
    ) -> tuple[Usage, str]:
        """Parse --output-format json output from claude -p.

        The JSON may be wrapped in a markdown code fence. We strip it if present.
        Expected top-level shape (subject to verification per the note below):
        {
          "result": "...plain text response...",
          "usage": { "input_tokens": N, "output_tokens": N, "total_tokens": N }
        }

        Returns (Usage, result_text).
        """
        text = raw_stdout.strip()

        # Strip markdown code fence if present
        fence_stripped = self._strip_code_fence(text)

        # Try direct JSON parse first
        try:
            data = json.loads(fence_stripped)
        except json.JSONDecodeError:
            # Fallback: try to extract the first JSON object or array
            data = self._extract_json(fence_stripped)
            if data is None:
                # Last resort: return the raw text as-is
                return (
                    Usage(duration_ms=duration_ms),
                    fence_stripped,
                )

        # Extract usage
        usage = self._parse_usage(data, duration_ms)

        # Extract result text — claude's JSON mode typically uses "content" or "result"
        result_text = data.get("result") or data.get("content") or data.get("text") or ""

        return usage, str(result_text)

    def _strip_code_fence(self, text: str) -> str:
        """Remove triple-backtick markdown fences from JSON output."""
        import re

        # Remove ```json ... ``` or ``` ... ```
        text = re.sub(r"^```json\s*\n", "", text, flags=re.MULTILINE)
        text = re.sub(r"^```\s*\n", "", text, flags=re.MULTILINE)
        text = re.sub(r"\n```\s*$", "", text, flags=re.MULTILINE)
        return text.strip()

    def _extract_json(self, text: str) -> Optional[dict]:
        """Try to extract a JSON object from text that may contain extra content."""
        import re

        # Find first { and last } and try to parse that slice
        start = text.find("{")
        if start == -1:
            return None
        # Try progressively larger slices
        for end in range(len(text), start, -1):
            try:
                return json.loads(text[start:end])
            except json.JSONDecodeError:
                continue
        return None

    def _parse_usage(self, data: dict, duration_ms: int) -> Usage:
        """Extract Usage from parsed JSON data."""
        raw_usage = data.get("usage") or {}
        return Usage(
            input_tokens=raw_usage.get("input_tokens"),
            output_tokens=raw_usage.get("output_tokens"),
            total_tokens=raw_usage.get("total_tokens"),
            duration_ms=duration_ms,
        )

    # ------------------------------------------------------------------
    # Error classification (T20)
    # ------------------------------------------------------------------

    def _classify_error(
        self,
        stderr: str,
        stdout: str,
        exit_code: int,
    ) -> Optional[AdapterError]:
        """Classify subprocess output into a retryable error type.

        Returns
        -------
        Optional[AdapterError]
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
        """
        structured = self._extract_structured_error(stdout)
        if structured is not None:
            classified = self._classify_from_structured(structured)
            if classified is not None:
                return classified

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

    def _classify_from_structured(self, data: dict) -> Optional[AdapterError]:
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
            if status in self.RETRY_SERVER_ERROR_CODES or 500 <= status < 600:
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

    def _extract_structured_error(self, stdout: str) -> Optional[dict]:
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
            text = self._strip_code_fence(text)
            try:
                data = json.loads(text)
            except json.JSONDecodeError:
                data = self._extract_json(text)
                if data is None:
                    return None
        if not isinstance(data, dict):
            return None
        if not any(k in data for k in _STRUCTURED_ERROR_KEYS):
            return None
        return data
