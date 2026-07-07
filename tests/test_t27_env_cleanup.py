"""T27 tests: env doc + adapter stub fail-fast + legacy cleanup + success semantics.

Drives TASKS.md T27:

1. The legacy bash pipeline (``autodev-harness-legacy.sh`` + the
   ``AUTODEV_USE_LEGACY=1`` switch) is dead code; it has to be deleted
   or replaced by a one-line deprecation shim.
2. ``AUTODEV_*`` env vars are scattered across 8+ files; a single
   ``docs/ENV.md`` documents them.
3. ``AgentResult.success`` currently checks ``exit_code == 0 and not
   stderr`` — the ``not stderr`` clause is wrong because stderr can
   carry harmless diagnostics from a clean run. Should be exit_code-only.
4. ``opencode`` / ``codex`` adapter stubs raise NotImplementedError on
   ``_execute`` — verify the failure mode carries the class name so
   misconfigured callers can find the right stub.
"""

from __future__ import annotations

from pathlib import Path


# ---------------------------------------------------------------------------
# 1. Legacy bash removed (or one-line deprecation shim)
# ---------------------------------------------------------------------------


def test_legacy_bash_pipeline_removed():
    """The 707-line ``autodev-harness-legacy.sh`` and the
    ``AUTODEV_USE_LEGACY=1`` switch in ``autodev-harness.sh`` are dead
    weight now that T07 has shipped the Python pipeline. They must be
    gone, OR ``autodev-harness.sh`` must refuse the switch with a clear
    error rather than silently exec'ing the old bash."""
    repo_root = Path(__file__).parent.parent
    sh = repo_root / "autodev-harness.sh"
    legacy = repo_root / "autodev-harness-legacy.sh"

    sh_text = sh.read_text()

    if legacy.exists():
        # Legacy is still on disk — ``autodev-harness.sh`` must NOT
        # exec it. The forwarding line was the bug.
        assert "autodev-harness-legacy" not in sh_text, (
            "autodev-harness.sh still forwards to legacy bash; "
            "remove the AUTODEV_USE_LEGACY branch"
        )
    # Always: no live reference to the legacy script in the entrypoint.
    assert "AUTODEV_USE_LEGACY" not in sh_text or "removed" in sh_text.lower() or "deprecated" in sh_text.lower(), (
        "autodev-harness.sh still wires AUTODEV_USE_LEGACY; remove the switch"
    )


# ---------------------------------------------------------------------------
# 2. AgentResult.success — exit_code only
# ---------------------------------------------------------------------------


def test_agent_result_success_ignores_stderr():
    """A clean exit with stderr noise (warnings / debug logs) must still
    be reported as success. The legacy ``exit_code == 0 and not stderr``
    heuristic mis-classifies healthy runs as failures whenever the CLI
    logs anything to stderr."""
    from harness.adapters.base import AgentResult

    # Clean exit, stderr carries a warning → still success.
    noisy_ok = AgentResult(exit_code=0, stderr="warning: deprecated flag used")
    assert noisy_ok.success is True

    # Non-zero exit → still failure regardless of stderr.
    noisy_fail = AgentResult(exit_code=1, stderr="anything")
    assert noisy_fail.success is False

    # Empty stderr → success.
    quiet_ok = AgentResult(exit_code=0, stderr="")
    assert quiet_ok.success is True

    # None stderr → success.
    none_stderr = AgentResult(exit_code=0, stderr=None)
    assert none_stderr.success is True


# ---------------------------------------------------------------------------
# 3. Env vars documented in one place
# ---------------------------------------------------------------------------


def test_env_doc_lists_all_autodev_vars():
    """A single ``docs/ENV.md`` must enumerate every ``AUTODEV_*`` env
    var actually referenced in the codebase. The legacy shell used
    ``AUTODEV_MODEL`` / ``AUTODEV_API_KEY`` / ``AUTODEV_BASE_URL`` (no
    per-tier suffix); the Python harness uses ``AUTODEV_MODEL_<TIER>``
    / ``AUTODEV_API_KEY_<TIER>`` / ``AUTODEV_BASE_URL_<TIER>`` /
    ``AUTODEV_FALLBACK_<TIER>``. Both, plus the feedback/visual vars,
    must show up in the doc."""
    repo_root = Path(__file__).parent.parent
    env_doc = repo_root / "docs" / "ENV.md"
    assert env_doc.exists(), "docs/ENV.md must exist as the single env-var reference"

    text = env_doc.read_text()
    expected = [
        "AUTODEV_MODEL_",
        "AUTODEV_API_KEY_",
        "AUTODEV_BASE_URL_",
        "AUTODEV_FALLBACK_",
        "AUTODEV_PLAN_FEEDBACK",
        "AUTODEV_UI_CHOICE",
        "AUTODEV_UI_FEEDBACK",
        "AUTODEV_UI_DIRECTION",
        "AUTODEV_VISUAL_BASE_URL",
        "AUTODEV_TEST_MODE",
    ]
    for var in expected:
        assert var in text, f"docs/ENV.md is missing documentation for {var}"


# ---------------------------------------------------------------------------
# 4. Adapter stubs fail-fast with self-identifying messages
# ---------------------------------------------------------------------------


def test_opencode_stub_failure_message_mentions_class():
    """When a caller picks the opencode stub, the failure must point at
    the class so the operator can fix config/models.yaml."""
    from harness.adapters.opencode import OpenCodeAdapter

    adapter = OpenCodeAdapter()
    try:
        adapter._execute(
            "x", model="m", cwd=Path("/tmp"), timeout=30, attempt=0,
        )
    except NotImplementedError as exc:
        assert "OpenCodeAdapter" in str(exc) or "opencode" in str(exc).lower()
    else:
        pytest.fail("OpenCodeAdapter._execute should have raised NotImplementedError")


def test_codex_stub_failure_message_mentions_class():
    from harness.adapters.codex import CodexAdapter

    adapter = CodexAdapter()
    try:
        adapter._execute(
            "x", model="m", cwd=Path("/tmp"), timeout=30, attempt=0,
        )
    except NotImplementedError as exc:
        assert "CodexAdapter" in str(exc) or "codex" in str(exc).lower()
    else:
        pytest.fail("CodexAdapter._execute should have raised NotImplementedError")


# ---------------------------------------------------------------------------
# 5. Central env-vars registry (no more scattered string literals)
# ---------------------------------------------------------------------------


def test_pipeline_exposes_env_var_registry():
    """``harness.env`` exposes a single :class:`EnvVars` namespace with
    every AUTODEV_* name. Scattered ``os.environ.get("AUTODEV_FOO")``
    literals are replaced by attribute access on this registry so a
    typo shows up as an AttributeError instead of silently returning
    ``None``."""
    from harness import env  # noqa: F401

    import harness.env as env_mod

    assert hasattr(env_mod, "EnvVars"), "harness.env.EnvVars registry is missing"
    registry = env_mod.EnvVars

    # Spot-check the documented vars all live on the registry.
    assert hasattr(registry, "MODEL_PREFIX")
    assert hasattr(registry, "API_KEY_PREFIX")
    assert hasattr(registry, "BASE_URL_PREFIX")
    assert hasattr(registry, "FALLBACK_PREFIX")
    assert hasattr(registry, "PLAN_FEEDBACK")
    assert hasattr(registry, "UI_CHOICE")
    assert hasattr(registry, "UI_FEEDBACK")
    assert hasattr(registry, "UI_DIRECTION")
    assert hasattr(registry, "VISUAL_BASE_URL")
    assert hasattr(registry, "TEST_MODE")