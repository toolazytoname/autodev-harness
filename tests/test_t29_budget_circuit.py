"""RED tests for T29 — budget circuit breaker is wired, not a no-op.

Per docs/TASKS.md T29 (A path — wiring):

For two years ``router.check_budget()`` was a ``pass`` block — the
"budget exceeded" safety valve referenced in MASTER-PLAN §5.7 was a
phantom. T29 fixes it by:

1. Adding ``max_tokens`` per tier in config/models.yaml.
2. Making ``check_budget`` compare spent vs (max_tokens * stop_at_percent)
   and ``raise BudgetExceeded`` when the cap is hit.
3. Calling ``router.check_budget(stage)`` at the top of
   ``Pipeline._call_agent`` so the pipeline refuses to start a model call
   that would push the tier over budget.
4. Routing visual-reviewer usage through the budget tracker (the old
   ``return card, Usage()`` short-circuit made UI tasks' budget
   systematically undercount).
5. Removing the dead ``_instance`` singleton attribute and the redundant
   ``Usage`` duplicate from router.py.

These tests are RED until the wiring lands.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from harness.adapters.base import AdapterError, AgentResult, Usage
from harness.pipeline import Pipeline, PipelineConfig
from harness.router import BudgetExceeded, ModelRouter, ModelSpec
from harness.score_card import ScoreCard


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_tight_budget_config(tmp_path: Path, *, worker_max: int = 1000) -> Path:
    """Write a models.yaml with small ``max_tokens`` caps so tests run fast.

    The caps are intentionally tiny (worker=1000, reviewer=2000,
    architect=500) so a test can drive the spend past ``stop_at_percent``
    with a handful of ``record()`` calls instead of synthesising millions
    of tokens.
    """
    cfg = {
        "tiers": {
            "architect": {
                "model": "claude-opus-4-8",
                "fallback": "claude-sonnet-4-6",
                "max_tokens": 500,
            },
            "reviewer": {
                "model": "claude-sonnet-4-6",
                "fallback": "haiku-4-5",
                "max_tokens": 2000,
            },
            "worker": {
                "model": "MiniMax-M2.7",
                "base_url": "https://api.minimaxi.com/anthropic",
                "fallback": "haiku-4-5",
                "max_tokens": worker_max,
            },
        },
        "budget": {
            "warn_at_percent": 80,
            "stop_at_percent": 100,
        },
        "assignments": {
            "research":   "worker",
            "plan":       "architect",
            "generate":   "worker",
            "review.correctness": "reviewer",
            "review.test":        "worker",
            "review.visual":      "reviewer",
        },
    }
    p = tmp_path / "models.yaml"
    p.write_text(yaml.safe_dump(cfg))
    return p


# ---------------------------------------------------------------------------
# RED 1 — TierConfig / ModelSpec carry max_tokens, default config loads them
# ---------------------------------------------------------------------------


class TestTierConfigMaxTokens:
    def test_default_models_yaml_loads_with_max_tokens(self):
        """The committed config/models.yaml has max_tokens on every tier.

        Without this, the budget circuit is silently disabled in
        production (a missing field means ``max_tokens=None`` ⇒ no
        enforcement). The fix is a config-level commitment, not a code
        change.
        """
        from harness.router import ModelRouter  # local — imports config lazily

        router = ModelRouter()
        for tier_name in ("architect", "reviewer", "worker"):
            spec = router._tier_specs[tier_name]  # noqa: SLF001 — internal API
            assert spec.max_tokens is not None, (
                f"tier '{tier_name}' missing max_tokens in config/models.yaml"
            )
            assert spec.max_tokens > 0, (
                f"tier '{tier_name}' max_tokens must be positive, got {spec.max_tokens}"
            )

    def test_tier_config_accepts_max_tokens(self, tmp_path):
        cfg_path = _make_tight_budget_config(tmp_path, worker_max=1234)
        router = ModelRouter(config_path=cfg_path)
        worker = router._tier_specs["worker"]  # noqa: SLF001
        assert worker.max_tokens == 1234

    def test_model_spec_carries_max_tokens(self, tmp_path):
        cfg_path = _make_tight_budget_config(tmp_path)
        router = ModelRouter(config_path=cfg_path)
        spec = router.resolve("generate")
        assert isinstance(spec, ModelSpec)
        assert spec.max_tokens == 1000


# ---------------------------------------------------------------------------
# RED 2 — check_budget actually raises + warns (was a no-op `pass` block)
# ---------------------------------------------------------------------------


class TestCheckBudgetEnforcement:
    def test_under_limit_is_noop(self, tmp_path):
        cfg_path = _make_tight_budget_config(tmp_path, worker_max=1000)
        router = ModelRouter(config_path=cfg_path)
        router.record("generate", Usage(total_tokens=100))
        # Under 80% of 1000 ⇒ silent pass
        router.check_budget("generate")

    def test_warn_threshold_emits_log(self, tmp_path, caplog):
        cfg_path = _make_tight_budget_config(tmp_path, worker_max=1000)
        router = ModelRouter(config_path=cfg_path)
        router.record("generate", Usage(total_tokens=850))
        with caplog.at_level("WARNING"):
            router.check_budget("generate")
        # 850 ≥ 80% of 1000 ⇒ warning
        assert any(
            "warn" in rec.message.lower() or "budget" in rec.message.lower()
            for rec in caplog.records
        ), f"expected warn log, got {[r.message for r in caplog.records]}"

    def test_stop_threshold_raises(self, tmp_path):
        cfg_path = _make_tight_budget_config(tmp_path, worker_max=1000)
        router = ModelRouter(config_path=cfg_path)
        router.record("generate", Usage(total_tokens=1000))
        with pytest.raises(BudgetExceeded) as excinfo:
            router.check_budget("generate")
        assert excinfo.value.tier == "worker"
        assert excinfo.value.spent == 1000
        assert excinfo.value.limit == 1000

    def test_over_limit_raises(self, tmp_path):
        cfg_path = _make_tight_budget_config(tmp_path, worker_max=1000)
        router = ModelRouter(config_path=cfg_path)
        router.record("generate", Usage(total_tokens=1500))
        with pytest.raises(BudgetExceeded):
            router.check_budget("generate")

    def test_no_max_tokens_is_noop(self, tmp_path):
        """If a tier has no max_tokens configured, check_budget never raises."""
        cfg = {
            "tiers": {
                "worker": {"model": "x"},  # no max_tokens
            },
            "budget": {"warn_at_percent": 80, "stop_at_percent": 100},
            "assignments": {"generate": "worker"},
        }
        cfg_path = tmp_path / "models.yaml"
        cfg_path.write_text(yaml.safe_dump(cfg))
        router = ModelRouter(config_path=cfg_path)
        router.record("generate", Usage(total_tokens=10**9))
        # Should NOT raise even with absurd spend — no cap configured.
        router.check_budget("generate")

    def test_other_tiers_unaffected_by_worker_spend(self, tmp_path):
        """Hitting worker cap must not affect reviewer / architect checks."""
        cfg_path = _make_tight_budget_config(tmp_path, worker_max=1000)
        router = ModelRouter(config_path=cfg_path)
        router.record("generate", Usage(total_tokens=2000))  # blow worker
        # reviewer tier is still empty ⇒ check passes
        router.check_budget("review.correctness")


# ---------------------------------------------------------------------------
# RED 3 — Pipeline._call_agent actually invokes check_budget (real interception)
# ---------------------------------------------------------------------------


class TestPipelineCallsCheckBudget:
    def test_call_agent_invokes_check_budget_before_adapter(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Pipeline._call_agent must call ``router.check_budget(stage)`` and
        refuse to call the adapter if the cap is already breached.

        This is the core promise of T29 A path: "撞顶真的暂停并可续".
        """
        cfg_path = _make_tight_budget_config(tmp_path, worker_max=100)
        router = ModelRouter(config_path=cfg_path)
        # Drive worker spend past the cap BEFORE _call_agent runs.
        router.record("research", Usage(total_tokens=200))

        # Build a pipeline pointing at this router; stub the adapter.
        from harness.adapters.base import AdapterBase

        class _NoopAdapter(AdapterBase):
            def _execute(self, *args, **kwargs):
                raise AssertionError("adapter must not be called when budget exceeded")

        project_dir = tmp_path / "proj"
        project_dir.mkdir()
        (project_dir / "agents").mkdir()
        (project_dir / "agents" / "researcher.md").write_text("# researcher\n")
        (project_dir / "artifacts").mkdir()
        (project_dir / "artifacts" / "000-brief.md").write_text("brief\n")

        config = PipelineConfig(project_dir=project_dir)
        pipeline = Pipeline(config, adapter=_NoopAdapter(), router=router)

        # Spy on router.check_budget to prove it was called.
        check_calls: list[str] = []
        real_check = router.check_budget

        def spy_check(stage: str) -> None:
            check_calls.append(stage)
            real_check(stage)

        monkeypatch.setattr(router, "check_budget", spy_check)

        from harness.artifacts import Phase

        with pytest.raises(BudgetExceeded):
            pipeline._call_agent(Phase.RESEARCH, "brief")

        assert check_calls == ["research"], (
            f"check_budget was called with {check_calls}, expected ['research']"
        )

    def test_call_agent_proceeds_when_under_budget(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Under-budget ⇒ adapter IS called; check_budget was the gate that let it through."""
        cfg_path = _make_tight_budget_config(tmp_path, worker_max=1000)
        router = ModelRouter(config_path=cfg_path)
        router.record("research", Usage(total_tokens=10))  # tiny — well under

        from harness.adapters.base import AdapterBase

        called = {"n": 0}

        class _EchoAdapter(AdapterBase):
            def _execute(self, *args, **kwargs):
                called["n"] += 1
                return AgentResult(
                    stdout="ok",
                    stderr="",
                    exit_code=0,
                    usage=Usage(total_tokens=5),
                    duration_ms=1,
                )

        project_dir = tmp_path / "proj2"
        project_dir.mkdir()
        (project_dir / "agents").mkdir()
        (project_dir / "agents" / "researcher.md").write_text("# researcher\n")
        (project_dir / "artifacts").mkdir()
        (project_dir / "artifacts" / "000-brief.md").write_text("brief\n")

        config = PipelineConfig(project_dir=project_dir)
        pipeline = Pipeline(config, adapter=_EchoAdapter(), router=router)

        from harness.artifacts import Phase

        result = pipeline._call_agent(Phase.RESEARCH, "brief")
        assert called["n"] == 1, "adapter should have been invoked"
        assert result.exit_code == 0


# ---------------------------------------------------------------------------
# RED 4 — visual reviewer returns real Usage, not Usage()
# ---------------------------------------------------------------------------


class TestVisualReviewerUsage:
    def test_run_visual_review_returns_real_usage(self, monkeypatch, tmp_path):
        """``run_visual_review`` must return ``tuple[ScoreCard, Usage]`` and
        the Usage must reflect the adapter's reported tokens — not the
        placeholder ``Usage()`` that systematically undercounted UI tasks.
        """
        from harness.adapters.base import AdapterBase, AgentResult

        expected_usage = Usage(
            input_tokens=120, output_tokens=80, total_tokens=200, duration_ms=42
        )

        class _StubAdapter(AdapterBase):
            def run_with_attachments(self, prompt, attachments, **kwargs):
                return AgentResult(
                    stdout='{"score": 0.9, "blockers": [], "suggestions": [], "evidence": "ok"}',
                    stderr="",
                    exit_code=0,
                    usage=expected_usage,
                    duration_ms=42,
                )

            def _execute(self, *args, **kwargs):
                raise NotImplementedError

        from harness.visual_reviewer import run_visual_review
        from harness.score_card import parse_score_card

        prompt_path = tmp_path / "visual.md"
        prompt_path.write_text("# visual prompt\n")
        screenshots = []  # empty is OK for this test

        result = run_visual_review(
            adapter=_StubAdapter(),
            model="claude-opus-4-8",
            spec_text="spec",
            diff_text="diff",
            changed_files=[],
            screenshots=screenshots,
            worktree_path=tmp_path,
            iter_num=1,
            reviewer_prompt=prompt_path,
        )
        # New contract: tuple[ScoreCard, Usage]
        assert isinstance(result, tuple) and len(result) == 2, (
            "run_visual_review must return (ScoreCard, Usage)"
        )
        card, usage = result
        assert isinstance(card, ScoreCard)
        assert usage.total_tokens == 200, (
            f"visual reviewer must return real usage, got total_tokens={usage.total_tokens}"
        )

    def test_reviewer_runner_visual_path_returns_real_usage(
        self, monkeypatch, tmp_path
    ):
        """``_run_visual_reviewer`` must propagate the real Usage through
        the tuple return — not the placeholder ``Usage()`` it currently
        hardcodes. The old short-circuit made every UI task's budget
        undercount.
        """
        from harness.adapters.base import AdapterBase, AgentResult
        from harness.reviewer_runner import _run_visual_reviewer

        real_usage = Usage(total_tokens=777)

        def fake_run_visual_review(*args, **kwargs):
            return (
                ScoreCard(
                    iter=1, reviewer="visual", score=0.9, blockers=[],
                    suggestions=[], evidence="ok",
                ),
                real_usage,
            )

        monkeypatch.setattr(
            "harness.visual_reviewer.run_visual_review", fake_run_visual_review
        )

        from harness.router import ModelRouter

        router = ModelRouter(config_path=_make_tight_budget_config(tmp_path))

        card, usage = _run_visual_reviewer(
            adapter=None,  # not invoked because we stubbed run_visual_review
            router=router,
            worktree_path=tmp_path,
            project_dir=tmp_path,
            task_id="T1",
            spec_text="spec",
            diff_text="diff",
            changed_files=[],
            iter_num=1,
            screenshots=[],
            prompt_path=tmp_path / "v.md",
        )
        assert usage is real_usage, (
            f"expected real usage from run_visual_review, got {usage!r}"
        )


# ---------------------------------------------------------------------------
# RED 5 — dead code removal: no _instance attribute, no duplicate Usage class
# ---------------------------------------------------------------------------


class TestDeadCodeRemoved:
    def test_router_no_longer_exposes_instance_singleton(self):
        """ModelRouter._instance was dead code. The class must not carry it."""
        assert "_instance" not in ModelRouter.__dict__, (
            "ModelRouter._instance should be removed; it was unused dead code"
        )

    def test_router_no_longer_exposes_duplicate_usage_class(self):
        """``Usage`` lives in harness.adapters.base. router.py must not re-export it."""
        import harness.router as rmod

        assert not hasattr(rmod, "Usage") or getattr(rmod, "Usage", None) is None, (
            "harness.router.Usage duplicate should be removed; use harness.adapters.base.Usage"
        )


# ---------------------------------------------------------------------------
# RED 6 — __main__ maps BudgetExceeded to a distinct exit code (137)
# ---------------------------------------------------------------------------


class TestMainExitCode:
    def test_budget_exceeded_maps_to_137(self, tmp_path, monkeypatch):
        """When a BudgetExceeded bubbles out of pipeline.run(), __main__ must
        catch it and return a distinct exit code (137) so cron / CI can
        tell "budget cap hit" apart from generic pipeline errors.
        """
        from harness import __main__ as harness_main

        project_dir = tmp_path / "exitcode_proj"
        project_dir.mkdir()

        # Stub Pipeline so phase.run raises BudgetExceeded without real models.
        class _BoomPipeline:
            def __init__(self, *args, **kwargs) -> None:
                pass

            def run(self, start_phase=None):
                raise BudgetExceeded(tier="worker", spent=1000, limit=1000)

        monkeypatch.setattr(harness_main, "Pipeline", _BoomPipeline)
        # Skip CLI arg parsing — call main() with our own argv.
        exit_code = harness_main.main(["--new", str(project_dir)])
        assert exit_code == 137, (
            f"BudgetExceeded should exit 137 (distinct from 1 generic), got {exit_code}"
        )