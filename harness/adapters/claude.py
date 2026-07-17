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
import os
import re
import subprocess
import time
from pathlib import Path
from typing import Optional

from harness.adapters.base import (
    AdapterBase,
    AdapterError,
    AgentResult,
    InvalidResponseError,
    QuotaExhaustedError,
    RateLimitError,
    ServerError,
    TimeoutError,
    TransientError,
    Usage,
    RETRYABLE_EXCEPTIONS,
)
from harness.adapters.json_envelope import (
    extract_json as _extract_json,
    loads_json_envelope as _loads_json_envelope,
    parse_json_output as _parse_json_output,
    parse_usage as _parse_usage,
    strip_code_fence as _strip_code_fence,
)
from harness.quota import (
    QuotaSignal,
    classify_quota_error,
    load_quota_config,
)

# T36: error classification extracted to claude_errors; re-exported
# with the same (private) names so existing call-sites and tests
# that patch ``harness.adapters.claude._RATE_LIMIT_RE`` still work.
from harness.adapters.claude_errors import (  # noqa: F401  (re-export)
    _5XX_RE,
    _RATE_LIMIT_RE,
    _STRUCTURED_ERROR_KEYS,
    classify_error as _classify_error_impl,
    classify_from_structured as _classify_from_structured_impl,
    classify_quota as _classify_quota_impl,
    extract_structured_error as _extract_structured_error_impl,
    quota_error as _quota_error_impl,
)


# ---------------------------------------------------------------------------
# Quota config (T16a)
# ---------------------------------------------------------------------------

# Loaded once at import time so the per-call classification is a
# cheap regex sweep. Operators can edit config/quota.yaml to track
# provider wording changes without touching code.
_QUOTA_CONFIG = load_quota_config()


# ---------------------------------------------------------------------------
# Env construction (T19)
# ---------------------------------------------------------------------------


def build_subprocess_env(
    base_url: Optional[str] = None,
    api_key: Optional[str] = None,
) -> Optional[dict[str, str]]:
    """Build the env dict for the ``claude`` subprocess.

    T19 — third-party worker calls must reach the configured endpoint and
    use the per-tier credential. We never mutate the process-global
    ``os.environ``; instead we hand the subprocess a derived copy so the
    rest of the harness keeps reading the original env.

    Returns ``None`` when neither ``base_url`` nor ``api_key`` is supplied,
    which lets ``subprocess.Popen`` fall back to inheriting the parent
    process env (no unnecessary allocation / no surprise overrides).
    """
    if not base_url and not api_key:
        return None

    env = os.environ.copy()
    if base_url:
        env["ANTHROPIC_BASE_URL"] = base_url
    if api_key:
        env["ANTHROPIC_API_KEY"] = api_key
    return env


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

    # ------------------------------------------------------------------
    # Shared subprocess helpers (T25)
    # ------------------------------------------------------------------

    def _run_subprocess(
        self,
        cmd: list[str],
        *,
        prompt: str,
        cwd: Path,
        timeout: int,
        env: Optional[dict[str, str]],
    ) -> tuple[str, str, int, int]:
        """Run ``cmd`` via Popen and capture stdout/stderr/exit_code.

        T25 — single source of truth for the subprocess plumbing shared
        by ``_execute`` (text path) and ``run_with_attachments``
        (multimodal path). Both used to fork their own copy; the copies
        had drifted (multimodal was missing the 5xx/timeout/transient
        handling that ``_execute`` had picked up).

        Returns ``(stdout, stderr, exit_code, duration_ms)``. Raises:

        - ``TimeoutError`` if the subprocess exceeds ``timeout`` (NOT
          retried by the outer loop — timeouts are not transient).
        - ``TransientError`` on ``ConnectionError`` / ``BrokenPipeError``
          — retried with backoff.
        - ``AdapterError`` on any other OS-level failure (binary
          missing, permission denied, …). Not retried.

        Does NOT raise on non-zero exit codes; that branch lives in
        :meth:`_post_subprocess` where the error classifier can attach
        its ``_result`` to the exception for the retry loop to surface.
        """
        start_time = time.monotonic()
        try:
            proc = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=cwd,
                env=env,
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
                    f"claude subprocess timed out after {timeout}s"
                )
        except TimeoutError:
            raise
        except (ConnectionError, BrokenPipeError) as exc:
            # Transient OS-level errors (peer reset, pipe closed). Surface as
            # TransientError so the retry loop backs off and tries again
            # instead of burning the budget on the first attempt.
            raise TransientError(f"transient subprocess error: {exc}") from exc
        except Exception as exc:
            raise AdapterError(f"Failed to execute claude: {exc}") from exc

        exit_code = proc.returncode
        duration_ms = int((time.monotonic() - start_time) * 1000)
        return stdout, stderr, exit_code, duration_ms

    def _post_subprocess(
        self,
        stdout: str,
        stderr: str,
        exit_code: int,
        duration_ms: int,
        attempt: int,
    ) -> AgentResult:
        """Classify + parse a finished subprocess run.

        T25 — second half of the shared pipeline. Both ``_execute`` and
        ``run_with_attachments`` feed the same captured output through
        this method so error mapping and JSON parsing stay identical
        across text and multimodal paths.
        """
        # T20 error classification: prefers structured JSON envelope, falls
        # back to word-boundary substring matching on stderr.
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
            # Exit code 1 with empty stderr is the proxy-flake signature
            # we've been hitting: the upstream provider hiccups, claude
            # CLI exits 1 with no stderr diagnostic. _classify_error
            # (above) already had first crack at any structured JSON
            # error envelope on stdout — if it found nothing actionable
            # there and stderr is empty, we have zero diagnostic info to
            # act on. That opacity is the actual signal, not "stdout must
            # also be empty": a long-running generator call can print
            # partial output (streaming text, an interrupted JSON blob)
            # before dying with the same uninformative exit 1. Requiring
            # empty stdout too meant that case fell through to a
            # non-retried generic AdapterError and burned the entire
            # pipeline on what was almost certainly the same transient
            # failure. Promoting it to TransientError makes it retryable
            # with the same back-off schedule as 5xx.
            if exit_code == 1 and not stderr.strip():
                raise TransientError(
                    f"claude exited with code 1 with no stderr diagnostic — "
                    f"likely upstream provider unreachable"
                )
            raise AdapterError(
                f"claude exited with code {exit_code}: {stderr.strip()}"
            )

        usage, result_text = _parse_json_output(stdout, duration_ms)

        return AgentResult(
            stdout=result_text,
            stderr=stderr,
            exit_code=exit_code,
            usage=usage,
            duration_ms=duration_ms,
            retry_count=attempt,
        )

    def run_with_attachments(
        self,
        prompt: str,
        attachments,
        *,
        model: str,
        cwd: Path | str | None = None,
        timeout: int = 120,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        fallback_model: Optional[str] = None,
        allowed_tools: Optional[list[str]] = None,
    ) -> AgentResult:
        """Run claude -p with image/PDF attachments and apply the same
        retry / classification machinery as the text path.

        T25 — used to fork a private copy of the subprocess plumbing and
        therefore had *zero* retries (a single 429 / 5xx blew up the
        visual reviewer instead of backing off). Now it shares
        ``_run_subprocess`` + ``_post_subprocess`` with ``_execute`` and
        walks the same exponential-backoff retry loop, plus an optional
        ``fallback_model`` swap on quota / retry-exhaustion.
        """
        if isinstance(cwd, str):
            cwd = Path(cwd)
        cwd = cwd or Path.cwd()

        attachments = [Path(p) for p in attachments]
        missing = [p for p in attachments if not p.exists()]
        if missing:
            raise AdapterError(f"Attachments not found: {missing}")

        cmd = self._build_cmd(prompt, model, cwd, allowed_tools=allowed_tools)
        # ``--`` ends the option list so the attachment paths can't be
        # interpreted as continuation of the prompt or as flags.
        cmd.append("--")
        cmd.extend(str(p) for p in attachments)

        env = build_subprocess_env(base_url=base_url, api_key=api_key)

        return self._run_cmd_with_retry(
            cmd=cmd,
            prompt=prompt,
            cwd=cwd,
            timeout=timeout,
            env=env,
            primary_model=model,
            fallback_model=fallback_model,
            allowed_tools=allowed_tools,
        )

    def _run_cmd_with_retry(
        self,
        *,
        cmd: list[str],
        prompt: str,
        cwd: Path,
        timeout: int,
        env: Optional[dict[str, str]],
        primary_model: str,
        fallback_model: Optional[str],
        allowed_tools: Optional[list[str]] = None,
    ) -> AgentResult:
        """Drive ``cmd`` through the standard retry loop, with an optional
        fallback model after the primary exhausts retries or hits a
        quota signal.

        T25 — the multimodal path needed this loop because it bypasses
        ``AdapterBase.run``; sharing the loop's shape (but not reusing
        ``_run_with_retry`` itself, since that one calls ``_execute``)
        keeps the retry/timeout/classification behaviour identical.
        """
        try:
            return self._attempt(
                cmd=cmd, prompt=prompt, cwd=cwd, timeout=timeout, env=env,
                model=primary_model,
            )
        except (*RETRYABLE_EXCEPTIONS, QuotaExhaustedError):
            if not (fallback_model and fallback_model != primary_model):
                raise
            cmd_fb = self._swap_model_in_cmd(cmd, prompt, fallback_model, cwd, allowed_tools=allowed_tools)
            return self._attempt(
                cmd=cmd_fb, prompt=prompt, cwd=cwd, timeout=timeout, env=env,
                model=fallback_model,
            )

    def _swap_model_in_cmd(
        self,
        cmd: list[str],
        prompt: str,
        new_model: str,
        cwd: Path,
        allowed_tools: Optional[list[str]] = None,
    ) -> list[str]:
        """Rebuild ``cmd`` with a different ``--model`` value, preserving
        any ``--`` separator + attachment list that followed it."""
        fallback_cmd = self._build_cmd(prompt, new_model, cwd, allowed_tools=allowed_tools)
        fallback_cmd.append("--")
        try:
            dash_idx = cmd.index("--")
            attachments = cmd[dash_idx + 1:]
        except ValueError:
            attachments = []
        return fallback_cmd + attachments

    def _attempt(
        self,
        *,
        cmd: list[str],
        prompt: str,
        cwd: Path,
        timeout: int,
        env: Optional[dict[str, str]],
        model: str,
    ) -> AgentResult:
        """Run ``cmd`` up to ``RETRY_MAX_ATTEMPTS`` times with exponential
        backoff. Returns the first successful result, re-raises the last
        retryable exception on exhaustion, or propagates non-retryable
        errors immediately.
        """
        attempt = 0
        last_retryable: BaseException | None = None

        while attempt < self.RETRY_MAX_ATTEMPTS:
            try:
                stdout, stderr, exit_code, duration_ms = self._run_subprocess(
                    cmd, prompt=prompt, cwd=cwd, timeout=timeout, env=env,
                )
                return self._post_subprocess(
                    stdout, stderr, exit_code, duration_ms, attempt,
                )
            except RETRYABLE_EXCEPTIONS as exc:
                last_retryable = exc
                attempt += 1
                if attempt >= self.RETRY_MAX_ATTEMPTS:
                    break
                time.sleep(self._backoff_delay(attempt))
            except (TimeoutError, QuotaExhaustedError):
                # Non-retryable — surface immediately.
                raise

        if last_retryable is not None:
            raise last_retryable
        raise AdapterError(
            f"All {self.RETRY_MAX_ATTEMPTS} attempts failed for model '{model}'"
        )

    def _build_cmd(
        self,
        prompt: str,
        model: str,
        cwd: Path,
        *,
        allowed_tools: Optional[list[str]] = None,
    ) -> list[str]:
        """Build the subprocess command list.

        ``allowed_tools`` (when non-empty) is forwarded as the
        ``--allowedTools`` flag so the worker model can actually
        *use* Write/Edit/Bash. Without it, ``claude -p`` runs in a
        permission-prompted sandbox and every file mutation blocks
        waiting for an interactive approval that never comes — the
        classic "generator wrote zero files" failure mode.

        Special sentinel ``model == "cli-default"`` means: do not pass
        ``--model`` at all, letting the CLI resolve its own default from
        the user's local settings (ANTHROPIC_MODEL, etc.). This keeps the
        harness vendor-neutral and lets the user swap underlying models
        without touching harness config.
        """
        cmd = [
            "claude",
            "-p",
            "--output-format",
            "json",
        ]
        if model != "cli-default":
            cmd.extend(["--model", model])
        if allowed_tools:
            cmd.extend(["--allowedTools", ",".join(allowed_tools)])
        return cmd

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
        allowed_tools: Optional[list[str]] = None,
    ) -> AgentResult:
        """Execute a single claude -p invocation (text path)."""
        cmd = self._build_cmd(prompt, model, cwd, allowed_tools=allowed_tools)

        # T19 — propagate base_url / api_key to the subprocess env so
        # worker-tier calls actually reach the configured endpoint and use
        # the right credential. None of this mutates the parent process env.
        env = build_subprocess_env(base_url=base_url, api_key=api_key)

        stdout, stderr, exit_code, duration_ms = self._run_subprocess(
            cmd, prompt=prompt, cwd=cwd, timeout=timeout, env=env,
        )
        return self._post_subprocess(
            stdout, stderr, exit_code, duration_ms, attempt,
        )

    def _parse_json_output(
        self,
        raw_stdout: str,
        duration_ms: int,
        attempt: int,
    ) -> tuple[Usage, str]:
        """T30 — delegate to the provider-agnostic parser.

        Kept as an instance method (with the legacy ``attempt`` arg) so
        existing test contracts that call ``adapter._parse_json_output``
        keep working without changes.
        """
        return _parse_json_output(raw_stdout, duration_ms)

    @staticmethod
    def _loads_json_envelope(text: str):
        """T30 delegate — see :func:`harness.adapters.json_envelope.loads_json_envelope`."""
        return _loads_json_envelope(text)

    @staticmethod
    def _strip_code_fence(text: str) -> str:
        """T30 delegate — see :func:`harness.adapters.json_envelope.strip_code_fence`."""
        return _strip_code_fence(text)

    @staticmethod
    def _extract_json(text: str) -> Optional[dict]:
        """T30 delegate — see :func:`harness.adapters.json_envelope.extract_json`."""
        return _extract_json(text)

    @staticmethod
    def _parse_usage(data: dict, duration_ms: int) -> Usage:
        """T30 delegate — see :func:`harness.adapters.json_envelope.parse_usage`."""
        return _parse_usage(data, duration_ms)

    # ------------------------------------------------------------------
    # Error classification (T20/T36: implementation in claude_errors)
    # ------------------------------------------------------------------

    def _classify_error(
        self,
        stderr: str,
        stdout: str,
        exit_code: int,
    ) -> Optional[AdapterError]:
        """T36 thin delegate. Implementation lives in
        :mod:`harness.adapters.claude_errors`. The class-method form
        is kept so existing call-sites (``self._classify_error(...)``)
        continue to work without touching the call-graph."""
        return _classify_error_impl(
            stderr, stdout, exit_code, self.RETRY_SERVER_ERROR_CODES
        )

    def _classify_quota(
        self,
        stderr: str,
        stdout: str,
    ) -> Optional[QuotaSignal]:
        """T36 thin delegate. See :mod:`harness.adapters.claude_errors`."""
        return _classify_quota_impl(stderr, stdout)

    def _quota_error(
        self,
        signal: QuotaSignal,
        stderr: str,
    ) -> QuotaExhaustedError:
        """T36 thin delegate. See :mod:`harness.adapters.claude_errors`."""
        return _quota_error_impl(signal, stderr)

    def _classify_from_structured(self, data: dict) -> Optional[AdapterError]:
        """T36 thin delegate. See :mod:`harness.adapters.claude_errors`."""
        return _classify_from_structured_impl(data, self.RETRY_SERVER_ERROR_CODES)

    def _extract_structured_error(self, stdout: str) -> Optional[dict]:
        """T36 thin delegate. See :mod:`harness.adapters.claude_errors`."""
        return _extract_structured_error_impl(stdout)
