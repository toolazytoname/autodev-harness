"""T26 tests: config robustness + PhaseSpec consolidation + magic numbers.

Drives TASKS.md T26:

1. ``config/models.yaml`` and ``config/slop_rules.yaml`` are loaded as raw
   dicts / yaml — missing fields silently default or raise KeyError
   deep in the call stack. Convert to pydantic models so bad config
   fails at load time with a clear error.
2. ``PHASE_ARTIFACTS`` / ``PHASE_STAGES`` / ``PHASE_AGENTS`` are three
   parallel dicts in ``pipeline.py``; adding a phase means editing three
   tables. Consolidate into a single ``PhaseSpec`` dataclass.
3. ``inner_loop`` reaches into ``ReviewerAssembly._agents_dir`` (private).
   Expose as a public property.
4. Empty reviewer list silently passes through ``run_reviewers_parallel``
   instead of failing fast with a diagnostic.
5. Magic numbers (timeout 300/180, git 30/10, dev-server port 8765,
   ``fallback[:6]`` cap) become named constants.
"""

from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# 1. ModelsConfig pydantic validation
# ---------------------------------------------------------------------------


def test_models_config_loads_valid_yaml():
    from harness.router import ModelsConfig

    raw = {
        "tiers": {
            "worker": {"model": "haiku", "base_url": "https://x", "fallback": "haiku2"},
            "reviewer": {"model": "sonnet"},
            "architect": {"model": "opus"},
        },
        "assignments": {
            "generate": "worker",
            "review": "reviewer",
            "plan": "architect",
        },
        "budget": {"warn_at_percent": 80, "stop_at_percent": 100},
    }
    cfg = ModelsConfig.model_validate(raw)
    assert cfg.tiers["worker"].model == "haiku"
    assert cfg.tiers["worker"].base_url == "https://x"
    assert cfg.budget.warn_at_percent == 80


def test_models_config_rejects_missing_model_field():
    """A tier without 'model' must fail loudly at load, not deep in resolve()."""
    from harness.router import ModelsConfig

    raw = {
        "tiers": {"worker": {"fallback": "x"}},  # missing 'model'
        "assignments": {"generate": "worker"},
        "budget": {"warn_at_percent": 80, "stop_at_percent": 100},
    }
    with pytest.raises(Exception):  # pydantic.ValidationError
        ModelsConfig.model_validate(raw)


def test_models_config_router_uses_validated_spec(tmp_path):
    """ModelRouter builds its tier specs from the validated config so the
    public surface keeps working."""
    from harness.router import ModelRouter

    cfg_path = tmp_path / "models.yaml"
    cfg_path.write_text(
        """
tiers:
  worker:
    model: haiku-x
    fallback: haiku-y
  reviewer:
    model: sonnet-x
  architect:
    model: opus-x
assignments:
  generate: worker
budget:
  warn_at_percent: 80
  stop_at_percent: 100
"""
    )
    router = ModelRouter(config_path=cfg_path)
    spec = router.resolve("generate")
    assert spec.model == "haiku-x"
    assert spec.fallback == "haiku-y"
    assert spec.tier == "worker"


# ---------------------------------------------------------------------------
# 2. SlopConfig pydantic validation
# ---------------------------------------------------------------------------


def test_slop_config_validates_rule_shape():
    from harness.slop_check import SlopConfig, SlopRule

    rule = SlopRule.model_validate({
        "id": "test.foo",
        "severity": "blocker",
        "description": "demo",
        "patterns": [r"foo", r"bar"],
    })
    assert rule.id == "test.foo"
    assert rule.severity == "blocker"
    assert len(rule.patterns) == 2

    cfg = SlopConfig.model_validate({"rules": [rule.model_dump()]})
    assert len(cfg.rules) == 1


def test_slop_config_rejects_invalid_severity():
    from harness.slop_check import SlopConfig

    raw = {
        "rules": [
            {
                "id": "test.bad_severity",
                "severity": "fatal",  # not in {blocker, warn}
                "description": "x",
                "patterns": [r"x"],
            }
        ]
    }
    with pytest.raises(Exception):
        SlopConfig.model_validate(raw)


def test_slop_config_rejects_empty_patterns():
    from harness.slop_check import SlopConfig

    raw = {
        "rules": [
            {
                "id": "test.no_patterns",
                "severity": "blocker",
                "description": "x",
                "patterns": [],  # useless rule
            }
        ]
    }
    with pytest.raises(Exception):
        SlopConfig.model_validate(raw)


def test_slop_load_rules_uses_pydantic_validation(tmp_path):
    """load_rules() must catch malformed YAML at load time, not when a
    validator later tries to compile the patterns."""
    from harness.slop_check import load_rules

    bad = tmp_path / "slop.yaml"
    bad.write_text(
        """
rules:
  - id: bad
    severity: fatal
    description: nope
    patterns: ["x"]
"""
    )
    with pytest.raises(Exception):
        load_rules(bad)


# ---------------------------------------------------------------------------
# 3. PhaseSpec single source of truth
# ---------------------------------------------------------------------------


def test_phase_spec_table_exposes_artifacts_stages_agents():
    from harness.pipeline import PHASE_SPECS, Phase

    plan = PHASE_SPECS[Phase.PLAN]
    assert plan.artifact == "002-plan"
    assert plan.stage == "plan"
    assert plan.agent == "planner"


def test_phase_spec_table_covers_all_pipelined_phases():
    """Adding a phase should mean editing one row, not three dicts."""
    from harness.pipeline import PIPELINE_PHASES, PHASE_SPECS

    assert set(PIPELINE_PHASES).issubset(set(PHASE_SPECS.keys()))


def test_phase_spec_drives_pipeline_phase_dispatch():
    """Pipeline.phase_* methods read from PHASE_SPECS only. The legacy
    PHASE_ARTIFACTS / PHASE_STAGES / PHASE_AGENTS dicts no longer exist
    — adding a new phase means editing one row of PHASE_SPECS."""
    import harness.pipeline as pipeline_mod

    assert not hasattr(pipeline_mod, "PHASE_ARTIFACTS")
    assert not hasattr(pipeline_mod, "PHASE_STAGES")
    assert not hasattr(pipeline_mod, "PHASE_AGENTS")


# ---------------------------------------------------------------------------
# 4. ReviewerAssembly exposes agents_dir as a public property
# ---------------------------------------------------------------------------


def test_reviewer_assembly_agents_dir_is_public_property():
    """inner_loop reaches into ``_agents_dir`` (private). Once a public
    ``agents_dir`` property exists, callers should use that instead."""
    from harness.reviewers import ReviewerAssembly

    assembly = ReviewerAssembly()
    # Public property exists and matches what _agents_dir would return.
    assert hasattr(assembly, "agents_dir")
    assert assembly.agents_dir == assembly._agents_dir


# ---------------------------------------------------------------------------
# 5. Empty reviewer list fails fast with a clear message
# ---------------------------------------------------------------------------


def test_run_reviewers_parallel_rejects_empty_reviewer_list(tmp_path):
    """An empty reviewer list must surface a clear AdapterError instead
    of silently passing through ThreadPoolExecutor with max_workers=1."""
    from harness.reviewer_runner import run_reviewers_parallel
    from harness.adapters.base import AdapterBase, AdapterError

    class _StubAdapter(AdapterBase):
        def _execute(self, *args, **kwargs):
            raise NotImplementedError

    class _StubRouter:
        def resolve(self, stage):
            from harness.router import ModelSpec
            return ModelSpec(model="m", tier="worker")

    adapter = _StubAdapter()
    router = _StubRouter()
    with pytest.raises(AdapterError, match="[Rr]eviewer"):
        run_reviewers_parallel(
            adapter=adapter,
            router=router,
            worktree_path=tmp_path,
            project_dir=tmp_path,
            task_id="t1",
            reviewer_names=[],
            agents_dir=tmp_path,
            spec_text="spec",
            diff_text="diff",
            changed_files=[],
            iter_num=1,
        )


# ---------------------------------------------------------------------------
# 6. Magic numbers become named constants
# ---------------------------------------------------------------------------


def test_visual_reviewer_fallback_page_cap_is_named_constant():
    """``fallback[:6]`` was a bare magic number. The cap should be a
    named constant we can assert on."""
    from harness import visual_reviewer

    assert hasattr(visual_reviewer, "FALLBACK_PAGE_LIMIT")
    assert isinstance(visual_reviewer.FALLBACK_PAGE_LIMIT, int)
    assert visual_reviewer.FALLBACK_PAGE_LIMIT >= 1


def test_visual_default_base_url_is_named_constant():
    """``http://127.0.0.1:8765`` was a magic literal. The default must
    live in a named constant."""
    from harness import reviewer_runner

    assert hasattr(reviewer_runner, "DEFAULT_VISUAL_BASE_URL")
    assert reviewer_runner.DEFAULT_VISUAL_BASE_URL.startswith("http")