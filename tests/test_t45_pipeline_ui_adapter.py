"""T45 — ``Pipeline._ui_adapter`` hook regression tests.

Lock in the contract that:

  - ``Pipeline(ui_adapter=X)`` exposes ``pipeline._ui_adapter is X``
  - When ``ui_adapter`` is omitted, ``_ui_adapter is _adapter`` (no
    behavior change on hosts without Open Design)
  - The source of ``harness.ui_phase`` references ``self._p._ui_adapter``
    (not ``self._p._adapter``) at the call site, so a future refactor
    that accidentally rebinds cannot ship silently
  - When ``UIPhase._call_ui_direction`` runs end-to-end, it dispatches
    to ``_ui_adapter`` (not ``_adapter``)

``tests/test_t32_adapter_factory.py`` covers the resolver machinery
(this file narrowly covers the per-instance ``_ui_adapter`` slot).
"""

from __future__ import annotations

import re
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from harness.adapters.base import AdapterBase, AgentResult
from harness.pipeline import Pipeline, PipelineConfig
from harness import ui_phase as ui_phase_module


class _StubAdapter(AdapterBase):
    """Adapter that records its calls; used to verify which slot a
    UI direction fell through to."""

    instances: list = []

    def __init__(self, name: str):
        super().__init__()
        self.name = name
        self.calls: list[dict] = []
        type(self).instances.append(self)

    def _execute(self, *args, **kwargs):  # pragma: no cover
        raise NotImplementedError

    def run(self, prompt, *, model, cwd, timeout, **kwargs):  # type: ignore[override]
        self.calls.append({"name": self.name, "prompt": prompt, "model": model})
        return AgentResult(
            stdout=f"ok-{self.name}",
            stderr="",
            exit_code=0,
            duration_ms=0,
        )


@pytest.fixture
def stub_config(tmp_path: Path) -> PipelineConfig:
    return PipelineConfig(project_dir=tmp_path)


# ---------------------------------------------------------------------------
# Slot tests — pure attribute assertions
# ---------------------------------------------------------------------------


class TestPipelineUiAdapterSlot:
    def test_default_falls_back_to_main_adapter(self, stub_config):
        main = _StubAdapter("main")
        pipeline = Pipeline(stub_config, adapter=main)
        assert pipeline._ui_adapter is main

    def test_explicit_override(self, stub_config):
        main = _StubAdapter("main")
        ui = _StubAdapter("ui")
        pipeline = Pipeline(stub_config, adapter=main, ui_adapter=ui)
        assert pipeline._ui_adapter is ui
        assert pipeline._ui_adapter is not pipeline._adapter

    def test_explicit_none_falls_back_to_main(self, stub_config):
        main = _StubAdapter("main")
        pipeline = Pipeline(stub_config, adapter=main, ui_adapter=None)
        assert pipeline._ui_adapter is main


# ---------------------------------------------------------------------------
# Source-level assertion — protects against accidental rebinding
# ---------------------------------------------------------------------------


class TestSourceUsesUiAdapter:
    def test_call_ui_direction_dispatches_through_ui_adapter(self):
        """Read ``ui_phase.py`` and require ``self._p._ui_adapter.run(...)``
        inside ``_call_ui_direction``. Catches accidental rebinds to
        ``self._p._adapter.run`` without spinning up a real pipeline."""
        path = Path(ui_phase_module.__file__)
        text = path.read_text()
        # The exact substring expected at the call site.
        assert "self._p._ui_adapter.run" in text, (
            "harness.ui_phase no longer routes the UI design call through "
            "self._p._ui_adapter — rewire the Open Design integration"
        )
        # …and ensure the legacy ``self._p._adapter.run`` is no longer
        # the call site for ``_call_ui_direction`` (allowed elsewhere).
        # We grep the function body's first 80 lines for the active call.
        for fn_match in re.finditer(r"def _call_ui_direction\(.*?\n(?=\S)", text, re.S):
            body = fn_match.group(0)
            assert "self._p._ui_adapter.run(" in body, (
                f"_call_ui_direction body does not call self._p._ui_adapter.run:\n{body[:200]}"
            )


# ---------------------------------------------------------------------------
# Dispatch integration — narrow, mocked borrowed state
# ---------------------------------------------------------------------------


class TestUIPhaseDispatch:
    def test_dispatches_to_ui_adapter_not_main(self, stub_config, monkeypatch):
        """Replace ``_call_ui_direction``'s heavy lifted bits with stubs
        so we can verify the *dispatch* — i.e. that the call goes to
        ``_ui_adapter`` and not to ``_adapter``."""
        main = _StubAdapter("main")
        ui = _StubAdapter("ui")
        pipeline = Pipeline(stub_config, adapter=main, ui_adapter=ui)

        # Patch the expensive / borrowed machinery on Pipeline.
        # ``UIPhase`` reuses them via ``__getattr__`` fallback, so the
        # instance-level attribute is what gets found at call time.
        pipeline._load_three_piece_baseline = lambda: ""
        pipeline._load_style_module = lambda name: ""
        # Stub the borrowed-pipeline helpers.
        pipeline._router = MagicMock()
        sentinel_spec = MagicMock()
        sentinel_spec.stage = "ui"
        sentinel_spec.agent = "ui-design"
        sentinel_spec.model = "haiku-4-5"
        sentinel_spec.fallback = None
        sentinel_spec.base_url = None
        sentinel_spec.tier = "worker"
        pipeline._router.resolve.return_value = sentinel_spec

        # Stub the helpers _call_ui_direction imports from
        # harness.pipeline.
        from harness import pipeline as pipeline_module
        from harness.artifacts import Phase

        sentinel = type(
            "S",
            (),
            {"stage": "ui", "agent": "ui-design", "model": "haiku-4-5",
             "fallback": None, "base_url": None, "tier": "worker"},
        )()
        monkeypatch.setattr(pipeline_module, "PHASE_SPECS", {Phase.UI: sentinel})
        monkeypatch.setattr(pipeline_module, "PHASE_TIMEOUT_SECONDS", 60)

        # Patch _read_agent_prompt + _build_ui_prompt on the pipeline
        # module (which is what the local ``from harness.pipeline
        # import ...`` resolves them from — they are re-exported from
        # prompts there).
        monkeypatch.setattr(
            pipeline_module, "_read_agent_prompt",
            lambda *a, **kw: "AGENT-PROMPT",
        )
        monkeypatch.setattr(
            pipeline_module, "_build_ui_prompt",
            lambda **kw: "PROMPT-CONTENT",
        )
        # _api_key_for is borrowed from Pipeline; stub it on the instance.
        pipeline._api_key_for = lambda tier: "test-key"

        direction = {"slug": "growth", "label": "Growth", "module": "(none)"}
        ui_phase_module.UIPhase(pipeline)._call_ui_direction(direction, "PLAN")

        assert ui.calls == [{"name": "ui", "prompt": "PROMPT-CONTENT",
                             "model": "haiku-4-5"}]
        assert main.calls == []
