"""Tests for UIPhase faithful mode (T-Bridge).

When ``PipelineConfig.brief_mode == "od_reverse_engineer"`` and
``PipelineConfig.od_dir`` is set, ``UIPhase.run()`` must:

  - Copy ``*.html`` / ``*.css`` / ``*.js`` from the OD project into
    ``<project>/preview/versions/od-source/`` verbatim.
  - Write ``<project>/preview/versions/od-source/spec.md``.
  - Write ``<project>/preview/index.html`` (canonical landing).
  - Write ``<project>/006-ui-spec.md``.
  - **NOT** call any LLM adapter (no `_ui_adapter.run`, no `_adapter.run`).
  - **NOT** run the slop check or human-pick loop.

Tests use a minimal fake-pipeline (not a full ``Pipeline`` instance)
to dodge the Linear MCP stub pre-existing issue. Faithful mode only
needs ``_config``, ``_project_dir``, and ``_log`` from the owning
pipeline — UIPhase's ``__getattr__`` forwarder does the rest.

We pair the test with a ``_StubAdapter`` mirroring
``tests/test_t45_pipeline_ui_adapter.py`` so we can assert that
``adapter.calls`` stays empty.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from harness import ui_phase as ui_phase_module
from harness.adapters.base import AdapterBase, AgentResult
from harness.pipeline import PipelineConfig
from harness.ui_phase import UIPhase

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "od-sample"


class _StubAdapter(AdapterBase):
    """Records every ``run()`` call so tests can assert no LLM was invoked."""

    def __init__(self, name: str = "stub"):
        super().__init__()
        self.name = name
        self.calls: list[dict] = []

    def _execute(self, *args, **kwargs):  # pragma: no cover
        raise NotImplementedError

    def run(self, prompt, *, model, cwd, timeout, **kwargs):  # type: ignore[override]
        self.calls.append({"prompt": prompt, "model": model, "cwd": str(cwd)})
        return AgentResult(stdout="ok", stderr="", exit_code=0, duration_ms=0)


def _make_fake_pipeline(project_dir: Path, brief_mode: str, od_dir: Path) -> SimpleNamespace:
    """Build a minimal fake pipeline with just what UIPhase needs.

    UIPhase's ``__getattr__`` forwards any ``_*`` attribute lookup to the
    owning pipeline, so we don't have to provide every helper. The
    minimum is ``_config`` + ``_project_dir`` + ``_log``.
    """
    config = PipelineConfig(
        project_dir=project_dir,
        brief_mode=brief_mode,
        od_dir=od_dir,
    )
    main_adapter = _StubAdapter("main")
    ui_adapter = _StubAdapter("ui")
    return SimpleNamespace(
        _config=config,
        _project_dir=project_dir,
        _adapter=main_adapter,
        _ui_adapter=ui_adapter,
        _log=lambda msg: None,  # silent in tests
    )


def _write_minimal_plan(project_dir: Path) -> None:
    """UIPhase.run() reads 002-plan.md and aborts if missing."""
    (project_dir / "002-plan.md").write_text(
        "# Plan\n\n鱼跃 YuYue 学员管理小程序 — translate OD HTML to miniprogram.\n",
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# Faithful mode — happy path
# ---------------------------------------------------------------------------


class TestFaithfulHappyPath:
    def test_copies_html_files(self, tmp_path):
        _write_minimal_plan(tmp_path)
        fake = _make_fake_pipeline(tmp_path, "od_reverse_engineer", FIXTURE_DIR)
        UIPhase(fake).run(
            plan_text=(tmp_path / "002-plan.md").read_text(encoding="utf-8"),
            od_dir=FIXTURE_DIR,
        )
        target = tmp_path / "preview" / "versions" / "od-source"
        assert target.is_dir()
        assert (target / "index.html").exists()
        assert (target / "students.html").exists()

    def test_copies_shared_css_and_js(self, tmp_path):
        _write_minimal_plan(tmp_path)
        fake = _make_fake_pipeline(tmp_path, "od_reverse_engineer", FIXTURE_DIR)
        UIPhase(fake).run(
            plan_text=(tmp_path / "002-plan.md").read_text(encoding="utf-8"),
            od_dir=FIXTURE_DIR,
        )
        target = tmp_path / "preview" / "versions" / "od-source"
        assert (target / "shared.css").exists()
        assert (target / "shared.js").exists()

    def test_writes_spec_md(self, tmp_path):
        _write_minimal_plan(tmp_path)
        fake = _make_fake_pipeline(tmp_path, "od_reverse_engineer", FIXTURE_DIR)
        UIPhase(fake).run(
            plan_text=(tmp_path / "002-plan.md").read_text(encoding="utf-8"),
            od_dir=FIXTURE_DIR,
        )
        spec = (tmp_path / "preview" / "versions" / "od-source" / "spec.md").read_text(
            encoding="utf-8"
        )
        assert "faithful" in spec.lower()
        assert "Fish Leap" not in spec  # sanity — no LLM prose pollution
        # Must reference the source OD dir so a human can audit
        assert str(FIXTURE_DIR) in spec

    def test_writes_canonical_landing(self, tmp_path):
        _write_minimal_plan(tmp_path)
        fake = _make_fake_pipeline(tmp_path, "od_reverse_engineer", FIXTURE_DIR)
        landing = UIPhase(fake).run(
            plan_text=(tmp_path / "002-plan.md").read_text(encoding="utf-8"),
            od_dir=FIXTURE_DIR,
        )
        assert landing == tmp_path / "preview" / "index.html"
        assert landing.exists()
        text = landing.read_text(encoding="utf-8")
        # Links into the copied OD HTML
        assert "versions/od-source/index.html" in text
        assert "versions/od-source/students.html" in text

    def test_writes_006_ui_spec_md(self, tmp_path):
        _write_minimal_plan(tmp_path)
        fake = _make_fake_pipeline(tmp_path, "od_reverse_engineer", FIXTURE_DIR)
        UIPhase(fake).run(
            plan_text=(tmp_path / "002-plan.md").read_text(encoding="utf-8"),
            od_dir=FIXTURE_DIR,
        )
        spec = tmp_path / "006-ui-spec.md"
        assert spec.exists()
        text = spec.read_text(encoding="utf-8")
        assert "faithful" in text.lower()
        assert "OD HTML reference" in text
        # Should reference at least one copied artifact
        assert "preview/versions/od-source/" in text


# ---------------------------------------------------------------------------
# Faithful mode — must NOT call any LLM
# ---------------------------------------------------------------------------


class TestFaithfulNoLLM:
    def test_no_adapter_calls(self, tmp_path):
        _write_minimal_plan(tmp_path)
        fake = _make_fake_pipeline(tmp_path, "od_reverse_engineer", FIXTURE_DIR)
        UIPhase(fake).run(
            plan_text=(tmp_path / "002-plan.md").read_text(encoding="utf-8"),
            od_dir=FIXTURE_DIR,
        )
        assert fake._adapter.calls == [], "main adapter should not be called in faithful mode"
        assert fake._ui_adapter.calls == [], "ui adapter should not be called in faithful mode"


# ---------------------------------------------------------------------------
# Faithful mode — error paths
# ---------------------------------------------------------------------------


class TestFaithfulErrors:
    def test_missing_od_dir_raises(self, tmp_path):
        from harness.pipeline import PipelineError

        _write_minimal_plan(tmp_path)
        fake = _make_fake_pipeline(tmp_path, "od_reverse_engineer", tmp_path / "no-such")
        with pytest.raises(PipelineError):
            UIPhase(fake).run(
                plan_text=(tmp_path / "002-plan.md").read_text(encoding="utf-8"),
                od_dir=tmp_path / "no-such",
            )

    def test_missing_plan_raises(self, tmp_path):
        from harness.pipeline import PipelineError

        fake = _make_fake_pipeline(tmp_path, "od_reverse_engineer", FIXTURE_DIR)
        with pytest.raises(PipelineError):
            UIPhase(fake).run(plan_text=None, od_dir=FIXTURE_DIR)


# ---------------------------------------------------------------------------
# Faithful mode — gating
# ---------------------------------------------------------------------------


class TestFaithfulGating:
    def test_freeform_mode_skips_faithful(self, tmp_path, monkeypatch):
        """When brief_mode != 'od_reverse_engineer', UIPhase falls back to
        the regular topic-aware path — it should NOT call _render_faithful
        even if od_dir is set."""
        from harness.adapters.base import AdapterError

        _write_minimal_plan(tmp_path)
        fake = _make_fake_pipeline(tmp_path, "freeform", FIXTURE_DIR)
        fake._consumed_feedback = set()

        def boom(*a, **kw):
            raise AdapterError("stop — faithful shouldn't have been entered")

        # Patch _generate_topic_directions on the UIPhase class itself,
        # since the regular run() path calls self._generate_topic_directions
        # which resolves to UIPhase's own method (not via __getattr__).
        monkeypatch.setattr(UIPhase, "_generate_topic_directions", boom)
        monkeypatch.setattr(UIPhase, "_resolve_direction_count", lambda self: 3)
        with pytest.raises(AdapterError):
            UIPhase(fake).run(
                plan_text=(tmp_path / "002-plan.md").read_text(encoding="utf-8"),
                od_dir=FIXTURE_DIR,
            )
        assert not (tmp_path / "preview" / "versions" / "od-source").exists()

    def test_od_dir_none_skips_faithful(self, tmp_path, monkeypatch):
        """Even with brief_mode='od_reverse_engineer', if od_dir is None
        UIPhase must not call _render_faithful (which would crash on
        the missing dir). Falls through to the regular path."""
        from harness.adapters.base import AdapterError

        _write_minimal_plan(tmp_path)
        fake = _make_fake_pipeline(tmp_path, "od_reverse_engineer", od_dir=None)
        fake._consumed_feedback = set()

        def boom(*a, **kw):
            raise AdapterError("stop — faithful shouldn't have been entered")

        monkeypatch.setattr(UIPhase, "_generate_topic_directions", boom)
        monkeypatch.setattr(UIPhase, "_resolve_direction_count", lambda self: 3)
        with pytest.raises(AdapterError):
            UIPhase(fake).run(
                plan_text=(tmp_path / "002-plan.md").read_text(encoding="utf-8"),
                od_dir=None,
            )
        assert not (tmp_path / "preview" / "versions" / "od-source").exists()


# ---------------------------------------------------------------------------
# Idempotent re-run
# ---------------------------------------------------------------------------


class TestFaithfulIdempotent:
    def test_rerun_replaces_files(self, tmp_path):
        """A second run with the same od_dir must not leave stale files
        from a prior draft. (We test that copied files match the source
        byte-for-byte, which implies no merge artifacts.)"""
        _write_minimal_plan(tmp_path)
        fake = _make_fake_pipeline(tmp_path, "od_reverse_engineer", FIXTURE_DIR)

        # First run
        UIPhase(fake).run(
            plan_text=(tmp_path / "002-plan.md").read_text(encoding="utf-8"),
            od_dir=FIXTURE_DIR,
        )
        first_bytes = (tmp_path / "preview" / "versions" / "od-source" / "index.html").read_bytes()

        # Mutate the copied file to simulate a partial prior state
        target = tmp_path / "preview" / "versions" / "od-source" / "index.html"
        target.write_bytes(b"<html>stale</html>")

        # Second run
        UIPhase(fake).run(
            plan_text=(tmp_path / "002-plan.md").read_text(encoding="utf-8"),
            od_dir=FIXTURE_DIR,
        )
        second_bytes = target.read_bytes()
        assert second_bytes == first_bytes, "rerun must overwrite stale copied files"