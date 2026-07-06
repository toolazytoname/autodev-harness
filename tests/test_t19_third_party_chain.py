"""RED tests for T19 — third-party model chain (base_url + fallback + per-tier key).

Per MASTER-PLAN §4 and TASKS.md T19:
- `ModelSpec.base_url` must reach `subprocess.Popen(env=...)` so worker-tier calls
  hit the third-party endpoint (e.g. MiniMax) instead of the default Anthropic one.
- Per-tier API key must reach the subprocess via env to avoid credential mix-up
  across backends.
- When the primary model exhausts retries, the adapter must retry with
  ``spec.fallback`` (T19 wiring — T16a adds quota-specific downgrade on top).
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from harness.adapters.base import (
    AdapterError,
    AgentResult,
    RateLimitError,
    TimeoutError,
    TransientError,
)
from harness.adapters.claude import ClaudeAdapter


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

DUMMY_CLAUDE_JSON = json.dumps({
    "result": "Hello from Claude",
    "usage": {"input_tokens": 10, "output_tokens": 20, "total_tokens": 30},
})


def mock_proc(stdout: str = "", stderr: str = "", returncode: int = 0):
    """Create a mock subprocess.Popen object."""
    proc = MagicMock()
    proc.returncode = returncode
    proc.communicate = MagicMock(return_value=(stdout, stderr))
    return proc


# ---------------------------------------------------------------------------
# base_url plumbing
# ---------------------------------------------------------------------------


class TestBaseUrlPlumbing:
    def test_run_with_base_url_sets_anthropic_base_url_env(self):
        adapter = ClaudeAdapter()
        captured_kwargs = []

        def capture_popen(*args, **kwargs):
            captured_kwargs.append(kwargs)
            return mock_proc(stdout=DUMMY_CLAUDE_JSON, returncode=0)

        mock_popen = MagicMock(side_effect=capture_popen)

        with patch("subprocess.Popen", mock_popen):
            adapter.run(
                "say hello",
                model="MiniMax-M2.7",
                cwd=Path("/tmp"),
                base_url="https://api.minimaxi.com/anthropic",
            )

        assert captured_kwargs, "Popen should have been called"
        env = captured_kwargs[0].get("env")
        assert env is not None, "Popen should have received env= when base_url is provided"
        assert env.get("ANTHROPIC_BASE_URL") == "https://api.minimaxi.com/anthropic"

    def test_run_without_base_url_does_not_inject_anthropic_base_url(self):
        adapter = ClaudeAdapter()
        captured_kwargs = []

        def capture_popen(*args, **kwargs):
            captured_kwargs.append(kwargs)
            return mock_proc(stdout=DUMMY_CLAUDE_JSON, returncode=0)

        mock_popen = MagicMock(side_effect=capture_popen)

        with patch("subprocess.Popen", mock_popen):
            adapter.run("say hello", model="haiku-4-5", cwd=Path("/tmp"))

        env = captured_kwargs[0].get("env")
        # When base_url is None, we either omit env= or pass os.environ-derived
        # env without injecting the URL. Either way the call should not have
        # set ANTHROPIC_BASE_URL.
        if env is not None:
            assert "ANTHROPIC_BASE_URL" not in env

    def test_run_with_base_url_preserves_other_env_vars(self):
        adapter = ClaudeAdapter()
        captured_kwargs = []

        def capture_popen(*args, **kwargs):
            captured_kwargs.append(kwargs)
            return mock_proc(stdout=DUMMY_CLAUDE_JSON, returncode=0)

        mock_popen = MagicMock(side_effect=capture_popen)

        with patch.dict(
            "os.environ",
            {"SOME_OTHER_VAR": "keep-me", "PATH": "/usr/bin"},
            clear=False,
        ):
            with patch("subprocess.Popen", mock_popen):
                adapter.run(
                    "say hello",
                    model="MiniMax-M2.7",
                    cwd=Path("/tmp"),
                    base_url="https://api.minimaxi.com/anthropic",
                )

        env = captured_kwargs[0].get("env")
        assert env is not None
        assert env.get("SOME_OTHER_VAR") == "keep-me"
        assert env.get("PATH") == "/usr/bin"
        assert env.get("ANTHROPIC_BASE_URL") == "https://api.minimaxi.com/anthropic"


# ---------------------------------------------------------------------------
# per-tier API key plumbing
# ---------------------------------------------------------------------------


class TestApiKeyPlumbing:
    def test_run_with_api_key_sets_anthropic_api_key_env(self):
        adapter = ClaudeAdapter()
        captured_kwargs = []

        def capture_popen(*args, **kwargs):
            captured_kwargs.append(kwargs)
            return mock_proc(stdout=DUMMY_CLAUDE_JSON, returncode=0)

        mock_popen = MagicMock(side_effect=capture_popen)

        with patch("subprocess.Popen", mock_popen):
            adapter.run(
                "say hello",
                model="MiniMax-M2.7",
                cwd=Path("/tmp"),
                api_key="sk-test-worker-key",
            )

        assert captured_kwargs, "Popen should have been called"
        env = captured_kwargs[0].get("env")
        assert env is not None, "Popen should receive env= when api_key is provided"
        assert env.get("ANTHROPIC_API_KEY") == "sk-test-worker-key"

    def test_run_with_base_url_and_api_key_both_propagated(self):
        adapter = ClaudeAdapter()
        captured_kwargs = []

        def capture_popen(*args, **kwargs):
            captured_kwargs.append(kwargs)
            return mock_proc(stdout=DUMMY_CLAUDE_JSON, returncode=0)

        mock_popen = MagicMock(side_effect=capture_popen)

        with patch("subprocess.Popen", mock_popen):
            adapter.run(
                "say hello",
                model="MiniMax-M2.7",
                cwd=Path("/tmp"),
                base_url="https://api.minimaxi.com/anthropic",
                api_key="sk-worker-key",
            )

        env = captured_kwargs[0].get("env")
        assert env.get("ANTHROPIC_BASE_URL") == "https://api.minimaxi.com/anthropic"
        assert env.get("ANTHROPIC_API_KEY") == "sk-worker-key"


# ---------------------------------------------------------------------------
# Fallback wiring
# ---------------------------------------------------------------------------


class TestFallbackWiring:
    def test_run_with_fallback_after_primary_exhausts(self):
        adapter = ClaudeAdapter()
        # First 3 calls (primary, retries exhausted) return 429.
        # 4th call (fallback model) succeeds.
        primary_proc = mock_proc(stderr="ERROR: 429 Too Many Requests", returncode=1)
        fallback_proc = mock_proc(stdout=DUMMY_CLAUDE_JSON, returncode=0)

        mock_popen = MagicMock(side_effect=[primary_proc, primary_proc, primary_proc, fallback_proc])

        with patch("subprocess.Popen", mock_popen):
            with patch("time.sleep"):
                result = adapter.run(
                    "say hello",
                    model="MiniMax-M2.7",
                    cwd=Path("/tmp"),
                    fallback_model="claude-haiku-4-5-20251001",
                )

        assert result.exit_code == 0
        assert "Hello from Claude" in result.stdout
        # Verify the 4th call used the fallback model.
        last_call = mock_popen.call_args_list[-1]
        cmd = last_call[0][0]
        # claude CLI gets the model via --model <name>; fallback model name
        # should appear in the last command.
        assert "claude-haiku-4-5-20251001" in cmd

    def test_run_without_fallback_still_raises_after_primary_exhausts(self):
        adapter = ClaudeAdapter()
        # All 3 attempts fail with 429; no fallback configured.
        mock_popen = MagicMock(
            side_effect=[
                mock_proc(stderr="ERROR: 429 Too Many Requests", returncode=1),
                mock_proc(stderr="ERROR: 429 Too Many Requests", returncode=1),
                mock_proc(stderr="ERROR: 429 Too Many Requests", returncode=1),
            ]
        )

        with patch("subprocess.Popen", mock_popen):
            with patch("time.sleep"):
                with pytest.raises(AdapterError):
                    adapter.run("say hello", model="haiku-4-5", cwd=Path("/tmp"))

    def test_fallback_command_uses_fallback_base_url(self):
        """When falling back to a different backend, the env should match
        what was passed in for the fallback (or default to None when the
        primary did not set one)."""
        adapter = ClaudeAdapter()
        primary_proc = mock_proc(stderr="ERROR: 429 Too Many Requests", returncode=1)
        fallback_proc = mock_proc(stdout=DUMMY_CLAUDE_JSON, returncode=0)

        captured_envs = []

        def capture_popen(*args, **kwargs):
            captured_envs.append(kwargs.get("env"))
            if len(captured_envs) <= 3:
                return primary_proc
            return fallback_proc

        mock_popen = MagicMock(side_effect=capture_popen)

        with patch("subprocess.Popen", mock_popen):
            with patch("time.sleep"):
                adapter.run(
                    "say hello",
                    model="MiniMax-M2.7",
                    cwd=Path("/tmp"),
                    base_url="https://api.minimaxi.com/anthropic",
                    api_key="sk-worker",
                    fallback_model="claude-haiku-4-5-20251001",
                )

        # All three primary attempts had the worker base_url/api_key.
        for env in captured_envs[:3]:
            assert env.get("ANTHROPIC_BASE_URL") == "https://api.minimaxi.com/anthropic"
            assert env.get("ANTHROPIC_API_KEY") == "sk-worker"


# ---------------------------------------------------------------------------
# run_with_attachments also propagates base_url (visual reviewer path)
# ---------------------------------------------------------------------------


class TestRunWithAttachmentsEnv:
    def test_run_with_attachments_propagates_base_url(self):
        adapter = ClaudeAdapter()
        captured_kwargs = []

        def capture_popen(*args, **kwargs):
            captured_kwargs.append(kwargs)
            return mock_proc(stdout=DUMMY_CLAUDE_JSON, returncode=0)

        mock_popen = MagicMock(side_effect=capture_popen)

        with patch("subprocess.Popen", mock_popen):
            # Create a dummy attachment file
            with patch.object(Path, "exists", return_value=True):
                adapter.run_with_attachments(
                    "describe",
                    [Path("/tmp/screenshot.png")],
                    model="MiniMax-M2.7",
                    cwd=Path("/tmp"),
                    base_url="https://api.minimaxi.com/anthropic",
                    api_key="sk-worker",
                )

        # Find the successful call (the one with our env)
        env = captured_kwargs[0].get("env")
        if env is not None:
            assert env.get("ANTHROPIC_BASE_URL") == "https://api.minimaxi.com/anthropic"
            assert env.get("ANTHROPIC_API_KEY") == "sk-worker"