"""CLI Adapters for AutoDevHarness.

Each adapter implements the `run(prompt, model, cwd, timeout)` interface
and returns an AgentResult. Different adapters call different CLI tools
(claude, opencode, codex) while presenting a unified interface.
"""

from harness.adapters.base import AgentResult, AdapterBase, AdapterError

__all__ = ["AgentResult", "AdapterBase", "AdapterError"]
