"""Codex adapter stub.

This is a placeholder for the OpenAI/codex CLI adapter.
The interface contract is identical to ClaudeAdapter.run() —
swap adapters in router.py to use codex instead.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from harness.adapters.base import AdapterBase, AgentResult


class CodexAdapter(AdapterBase):
    """Adapter for the `codex` CLI (OpenAI's official tool).

    .. note::
        Not yet implemented. To complete this adapter:

        1. Identify the codex CLI's equivalent of
           ``claude -p --model X --output-format json``
           (e.g. ``codex completion --model X --json`` or similar).
        2. Implement ``_build_cmd()`` returning the correct command list.
        3. If codex uses a different JSON field for the response text,
           override ``_parse_json_output()`` accordingly.
        4. Update ``config/models.yaml`` to point assignments at codex
           where desired (e.g. cheaper worker-tier tasks).
        5. Add real subprocess tests once the CLI is available.
    """

    def _execute(
        self,
        prompt: str,
        *,
        model: str,
        cwd: Path,
        timeout: int,
        attempt: int,
    ) -> AgentResult:
        # TODO: implement once codex CLI interface is known
        raise NotImplementedError(
            "CodexAdapter is not yet implemented. "
            "See docstring for implementation guide."
        )
