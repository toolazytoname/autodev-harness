"""Claude CLI adapter.

Calls `claude -p --model X --output-format json` via subprocess.
Handles exponential back-off on 429/5xx and strips markdown fences from output.
"""

from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path
from typing import Optional

from harness.adapters.base import (
    AdapterBase,
    AdapterError,
    AgentResult,
    RateLimitError,
    TimeoutError,
    Usage,
)


class ClaudeAdapter(AdapterBase):
    """Adapter for the `claude` CLI (Anthropic's official tool)."""

    # Increase base delay — claude's rate limits benefit from slightly longer waits
    RETRY_BASE_DELAY: float = 2.0

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
        except Exception as exc:
            raise AdapterError(f"Failed to execute claude: {exc}") from exc

        exit_code = proc.returncode
        duration_ms = int((time.monotonic() - start_time) * 1000)

        # Detect rate limit from stderr
        if "429" in stderr or "rate limit" in stderr.lower():
            exc = RateLimitError(f"Rate limit hit: {stderr.strip()}")
            exc._result = AgentResult(
                stdout=stdout,
                stderr=stderr,
                exit_code=exit_code,
                usage=Usage(duration_ms=duration_ms),
                retry_count=attempt,
            )
            raise exc

        # Detect server errors for retry
        for code in self.RETRY_SERVER_ERROR_CODES:
            if str(code) in stderr:
                exc = RateLimitError(f"Server error {code}: {stderr.strip()}")
                exc._result = AgentResult(
                    stdout=stdout,
                    stderr=stderr,
                    exit_code=exit_code,
                    usage=Usage(duration_ms=duration_ms),
                    retry_count=attempt,
                )
                raise exc

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
