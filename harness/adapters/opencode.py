"""OpenCode adapter stub.

This is a placeholder for the opencode CLI adapter.
The interface contract is identical to ClaudeAdapter.run() —
swap adapters in router.py to use opencode instead.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from harness.adapters.base import AdapterBase, AgentResult


class OpenCodeAdapter(AdapterBase):
    """Adapter for the `opencode` CLI.

    .. note::
        Not yet implemented. To complete this adapter:

        1. Identify the opencode CLI's equivalent of
           ``claude -p --model X --output-format json``
           (e.g. ``opencode run --model X --json`` or similar).
        2. Implement ``_build_cmd()`` returning the correct command list.
        3. If opencode uses a different JSON field for the response text,
           override ``_parse_json_output()`` accordingly.
        4. Update ``config/models.yaml`` to point ``worker`` / ``reviewer``
           assignments at opencode instead of claude where desired.
        5. Add real subprocess tests (similar to the claude adapter tests)
           once the CLI is available in the environment.
    """

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
        # TODO: implement once opencode CLI interface is known
        raise NotImplementedError(
            "OpenCodeAdapter is not yet implemented. "
            "See docstring for implementation guide."
        )
