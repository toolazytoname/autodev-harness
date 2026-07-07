"""CLI Adapters for AutoDevHarness.

Each adapter implements the `run(prompt, model, cwd, timeout)` interface
and returns an AgentResult. Different adapters call different CLI tools
(claude, opencode, codex) while presenting a unified interface.
"""

from harness.adapters.base import (
    AdapterBase,
    AdapterError,
    AgentResult,
    RateLimitError,
    ServerError,
    TransientError,
)

__all__ = [
    "AgentResult",
    "AdapterBase",
    "AdapterError",
    "RateLimitError",
    "ServerError",
    "TransientError",
]
