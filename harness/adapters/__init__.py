"""CLI Adapters for AutoDevHarness.

Each adapter implements the `run(prompt, model, cwd, timeout)` interface
and returns an AgentResult. Different adapters call different CLI tools
(claude, opencode, codex) while presenting a unified interface.

T32 — :data:`ADAPTER_REGISTRY` is the central name → class map. The
pipeline looks up the right backend per-tier from this registry via the
``adapter_resolver`` hook on :class:`harness.pipeline.Pipeline`. Only
fully-implemented adapters belong here; the opencode/codex stub modules
remain excluded until their real backends land (T32 spec rule: "注册过
的 adapter 必须能跑").
"""

from harness.adapters.base import (
    AdapterBase,
    AdapterError,
    AgentResult,
    RateLimitError,
    ServerError,
    TransientError,
)
from harness.adapters.claude import ClaudeAdapter
from harness.adapters.open_design import OpenDesignAdapter

# Map of adapter name (the value of ``TierConfig.adapter``) to the
# concrete class. Adding a new backend: import the class above and
# register the name here. Until then, config that points at a missing
# name is rejected at startup with a clear error (see
# ``harness.router.ModelRouter._load_config``).
ADAPTER_REGISTRY: dict[str, type[AdapterBase]] = {
    "claude": ClaudeAdapter,
    # T45 — Open Design adapter is a fully-implemented backend (the
    # implementation lives in ``harness.adapters.open_design``). Only
    # wired when ``__main__`` detects an OD installation via
    # ``harness.open_design.is_available()``; absent that, the UI phase
    # silently falls back to Claude.
    "open_design": OpenDesignAdapter,
}

__all__ = [
    "ADAPTER_REGISTRY",
    "AgentResult",
    "AdapterBase",
    "AdapterError",
    "RateLimitError",
    "ServerError",
    "TransientError",
]
