"""T32 — adapter factory + per-tier resolution + fail-fast on unknown.

Background
----------
Pre-T32, ``harness/adapters/__init__.py`` re-exported the base classes
but had no central registry. ``__main__.py`` hard-coded
``Pipeline(..., adapter=ClaudeAdapter())`` and the opencode/codex
stubs were never instantiated. Changing ``config/models.yaml`` to
point a tier at ``opencode`` would silently keep using
``ClaudeAdapter`` and the run would fail in obscure ways deep inside
``_call_agent``.

T32 fixes this by:

1. Adding ``ADAPTER_REGISTRY: dict[str, type[AdapterBase]]`` to
   ``harness/adapters/__init__.py`` (currently just ``"claude"``;
   opencode/codex stay as stub modules until they have real
   implementations — see T32 spec: "注册过的 adapter 必须能跑").
2. Adding ``adapter: str = "claude"`` to ``TierConfig`` so the YAML
   can opt a tier into a non-default backend.
3. Adding an ``adapter_resolver: Callable[[str], AdapterBase]`` knob
   on ``Pipeline.__init__``; when given, the pipeline looks up the
   right adapter per stage.
4. Failing fast at ``ModelRouter._load_config`` when a tier
   references an adapter name that's not in the registry — the
   operator sees the misconfiguration at startup, not at first call.
"""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent
from unittest.mock import patch

import pytest

from harness.adapters import ADAPTER_REGISTRY
from harness.adapters.base import AdapterBase, AgentResult
from harness.adapters.claude import ClaudeAdapter
from harness.router import ModelRouter, ModelSpec, TierConfig


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_yaml(path: Path, body: str) -> Path:
    path.write_text(dedent(body))
    return path


# A minimal-yet-valid models.yaml body. Tests override only the bits
# they care about; everything else matches the shipping default.
_VALID_YAML = """
tiers:
  architect:
    model: claude-opus-4-8
  reviewer:
    model: claude-sonnet-4-6
  worker:
    model: claude-haiku-4-5-20251001
assignments:
  plan: architect
  generate: worker
  review: reviewer
"""


# ---------------------------------------------------------------------------
# 1. ADAPTER_REGISTRY contract
# ---------------------------------------------------------------------------


class TestAdapterRegistry:
    """The registry must be importable, dict-shaped, and contain claude."""

    def test_registry_is_dict(self):
        assert isinstance(ADAPTER_REGISTRY, dict)

    def test_registry_contains_claude(self):
        assert "claude" in ADAPTER_REGISTRY
        assert ADAPTER_REGISTRY["claude"] is ClaudeAdapter

    def test_registry_keys_are_strings(self):
        # Keys are CLI-typed names; values are subclasses of AdapterBase.
        for key, value in ADAPTER_REGISTRY.items():
            assert isinstance(key, str)
            assert issubclass(value, AdapterBase)


# ---------------------------------------------------------------------------
# 2. TierConfig.adapter defaults to "claude" (back-compat)
# ---------------------------------------------------------------------------


class TestTierConfigAdapterField:
    def test_default_adapter_is_claude(self):
        """A tier that doesn't specify ``adapter`` must default to claude —
        preserves the current YAML in config/models.yaml."""
        cfg = TierConfig(model="claude-opus-4-8")
        assert cfg.adapter == "claude"

    def test_explicit_adapter_round_trip(self):
        cfg = TierConfig(model="claude-haiku-4-5", adapter="opencode")
        assert cfg.adapter == "opencode"


# ---------------------------------------------------------------------------
# 3. Unknown adapter in YAML fails fast
# ---------------------------------------------------------------------------


class TestUnknownAdapterFailsFast:
    """The T32 spec's primary acceptance: misconfig surfaces at startup."""

    def test_unknown_adapter_in_yaml_raises(self, tmp_path):
        yaml = _write_yaml(
            tmp_path / "models.yaml",
            _VALID_YAML.replace(
                "  architect:\n    model: claude-opus-4-8",
                "  architect:\n    model: claude-opus-4-8\n    adapter: bogus",
            ),
        )
        with pytest.raises(Exception) as exc_info:
            ModelRouter(config_path=yaml)

        # The error must mention the bad name so the operator can grep
        # the YAML quickly.
        message = str(exc_info.value)
        assert "bogus" in message, (
            f"error message must name the bad adapter ('bogus'); got:\n{message}"
        )
        # And it should also surface *which* registry was checked so
        # the operator can see what adapters are actually available.
        assert "claude" in message or "registry" in message.lower(), (
            f"error message should list available adapters; got:\n{message}"
        )

    def test_missing_adapter_field_uses_default(self, tmp_path):
        """The shipping YAML has no ``adapter`` key on any tier — T32 must
        not break the boot path for the project itself."""
        yaml = _write_yaml(tmp_path / "models.yaml", _VALID_YAML)
        # Must NOT raise — back-compat.
        router = ModelRouter(config_path=yaml)
        spec = router.resolve("plan")
        assert spec.adapter == "claude"


# ---------------------------------------------------------------------------
# 4. ModelSpec carries the adapter name from the tier config
# ---------------------------------------------------------------------------


class TestModelSpecCarriesAdapter:
    def test_resolve_returns_adapter_field(self, tmp_path):
        """The resolved ModelSpec must include the adapter name so the
        Pipeline can look up the right backend."""
        yaml = _write_yaml(
            tmp_path / "models.yaml",
            _VALID_YAML.replace(
                "  architect:\n    model: claude-opus-4-8",
                "  architect:\n    model: claude-opus-4-8\n    adapter: claude",
            ),
        )
        router = ModelRouter(config_path=yaml)
        spec = router.resolve("plan")
        assert spec.adapter == "claude"


# ---------------------------------------------------------------------------
# 5. Pipeline uses the resolver to pick an adapter per tier
# ---------------------------------------------------------------------------


class _StubAdapter(AdapterBase):
    """Lightweight adapter for the per-tier resolver test."""

    instances: list = []  # class-level, so we can see creation order

    def __init__(self):
        super().__init__()
        type(self).instances.append(self)
        self.calls: list[dict] = []

    def _execute(self, *args, **kwargs):  # pragma: no cover - never called
        raise NotImplementedError

    # Override run so we can spy on dispatch without going through
    # the full subprocess + retry loop.
    def run(self, prompt, *, model, cwd, timeout, **kwargs):  # type: ignore[override]
        self.calls.append(
            {"model": model, "tier": kwargs.get("tier"), "stage": kwargs.get("stage")}
        )
        return AgentResult(
            stdout="ok",
            stderr="",
            exit_code=0,
            usage=None,
            duration=0.0,
        )


class TestPipelineAdapterResolver:
    def test_pipeline_resolves_adapters_by_tier(self, tmp_path):
        """Give the worker tier one mock and the reviewer tier another;
        assert the resolver receives both adapter names (one per tier)."""
        from harness.pipeline import Pipeline, PipelineConfig

        resolved_calls: list[str] = []

        def resolver(name: str) -> AdapterBase:
            resolved_calls.append(name)
            return _StubAdapter()

        # Patch the registry so both adapter names are accepted at
        # config-load time (the production ``_load_config`` would
        # otherwise reject "worker_backend" / "reviewer_backend").
        fake_registry = dict(ADAPTER_REGISTRY)
        fake_registry["worker_backend"] = _StubAdapter
        fake_registry["reviewer_backend"] = _StubAdapter

        yaml = _write_yaml(
            tmp_path / "models.yaml",
            """
            tiers:
              worker:
                model: claude-haiku
                adapter: worker_backend
              reviewer:
                model: claude-sonnet
                adapter: reviewer_backend
            assignments:
              generate: worker
              review.correctness: reviewer
            """,
        )

        with patch("harness.adapters.ADAPTER_REGISTRY", fake_registry):
            config = PipelineConfig(project_dir=tmp_path)
            router = ModelRouter(config_path=yaml)
            pipeline = Pipeline(
                config,
                adapter=ClaudeAdapter(),
                router=router,
                adapter_resolver=resolver,
            )
            # Drive the resolver for both tiers — this is the same code
            # path the pipeline uses internally for per-stage dispatch.
            pipeline._adapter_resolver(router.resolve("generate").adapter)
            pipeline._adapter_resolver(router.resolve("review.correctness").adapter)

        # Both adapter names must have been requested — one per tier.
        assert "worker_backend" in resolved_calls, (
            f"resolver must be called for the worker tier; got {resolved_calls}"
        )
        assert "reviewer_backend" in resolved_calls, (
            f"resolver must be called for the reviewer tier; got {resolved_calls}"
        )

    def test_default_resolver_uses_registry(self):
        """With no resolver supplied, Pipeline falls back to a default
        ``lambda name: ADAPTER_REGISTRY[name]()`` so existing call-sites
        (single ``adapter=ClaudeAdapter()``) keep working."""
        from harness.pipeline import Pipeline, PipelineConfig

        config = PipelineConfig(project_dir=Path("/tmp/nonexistent-for-this-test"))
        # No resolver given — must not raise; the default resolver is
        # installed at __init__ time and reads from ADAPTER_REGISTRY.
        pipeline = Pipeline(config, adapter=ClaudeAdapter())
        assert pipeline._adapter_resolver is not None, (
            "Pipeline must install a default adapter_resolver"
        )
        resolved = pipeline._adapter_resolver("claude")
        assert isinstance(resolved, ClaudeAdapter)


# ---------------------------------------------------------------------------
# 6. CLI gate: --validate-config
# ---------------------------------------------------------------------------


class TestValidateConfigCLI:
    """``python -m harness --validate-config`` is the cheap CI gate.
    Exits 0 on a valid config, non-zero with a clear error on bad
    adapter names (or any other load-time failure)."""

    def test_shipping_config_validates(self):
        """The shipping ``config/models.yaml`` (no ``adapter`` key on any
        tier) must still pass — this is the smoke that catches accidental
        regressions where ``TierConfig.adapter`` is removed or the
        registry loses ``"claude"``."""
        from harness.router import ModelRouter

        try:
            ModelRouter()
        except (FileNotFoundError, ValueError) as exc:
            pytest.fail(f"default config/models.yaml must validate: {exc}")

    def test_validate_config_flag_is_parsed(self):
        """The argparse parser must accept ``--validate-config`` as a
        store_true flag (smoke: no SystemExit on a known-good invocation)."""
        from harness.__main__ import _build_parser

        parser = _build_parser()
        args = parser.parse_args(["--validate-config"])
        assert args.validate_config is True

    def test_validate_config_fails_on_unknown_adapter(self, tmp_path, capsys):
        """End-to-end: a temp YAML with a bad adapter → loading it
        raises and the error message names the offending adapter.
        We test the underlying ModelRouter path (which is what
        ``--validate-config`` calls) rather than main() — that gives
        us the same coverage without the mock gymnastics."""
        from harness.router import ModelRouter

        bad_yaml = _write_yaml(
            tmp_path / "models.yaml",
            _VALID_YAML.replace(
                "  architect:\n    model: claude-opus-4-8",
                "  architect:\n    model: claude-opus-4-8\n    adapter: bogus",
            ),
        )
        with pytest.raises(ValueError) as exc_info:
            ModelRouter(config_path=bad_yaml)

        assert "bogus" in str(exc_info.value), (
            f"error must name the bad adapter; got:\n{exc_info.value}"
        )

    def test_validate_config_main_dispatch(self, tmp_path, monkeypatch):
        """Smoke: ``main(["--validate-config"])`` exits 0 when the config
        is good. We monkeypatch the router construction to use a temp
        valid YAML so the test doesn't depend on the repo's working dir."""
        from harness.__main__ import EXIT_OK, main
        from harness.router import ModelRouter

        good_yaml = _write_yaml(tmp_path / "models.yaml", _VALID_YAML)

        # Force the default ModelRouter to read our temp file by
        # monkeypatching its module-level default path resolution.
        original_init = ModelRouter.__init__

        def patched_init(self, config_path=None):
            original_init(self, config_path=good_yaml)

        monkeypatch.setattr(ModelRouter, "__init__", patched_init)
        rc = main(["--validate-config"])
        assert rc == EXIT_OK
