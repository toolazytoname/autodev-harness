"""Real smoke test for ClaudeAdapter.

This test makes an actual claude CLI call and is marked 'slow' so it is
excluded from normal CI runs. Run manually with:
    pytest tests/smoke_test_adapter.py -v -m slow

Requires: claude CLI in PATH, network access.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = pytest.mark.slow


def test_claude_adapter_smoke():
    """Smoke test: call haiku with a simple prompt, verify it returns text."""
    from harness.adapters.claude import ClaudeAdapter

    adapter = ClaudeAdapter()
    result = adapter.run(
        "Reply with exactly the word: hello",
        model="haiku-4-5-20251001",
        cwd=Path("/tmp"),
        timeout=60,
    )

    assert result.exit_code == 0, f"Non-zero exit: {result.stderr}"
    assert result.success, f"stderr present: {result.stderr!r}"
    assert "hello" in result.stdout.lower(), f"Unexpected output: {result.stdout!r}"
    # Usage should be reported (claude --output-format json provides it)
    assert result.usage is not None
