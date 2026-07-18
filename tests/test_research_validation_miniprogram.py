"""Tests for the T-Bridge miniprogram ecosystem gate.

Extends research_validation with two new public APIs:

  - ``brief_targets_miniprogram(brief_text) -> bool``
  - ``validate_miniprogram_decision_coverage(brief_text, table) -> ValidationResult``

These run AFTER the standard ``validate_research_report`` gate in the
research-phase pipeline, only when the brief carries a miniprogram
signal. They enforce "≥2 rows in the reuse decision table must
reference a recognised miniprogram ecosystem library" — a soft variant
of MASTER-PLAN P4 for the OD-bridge code path.
"""

from __future__ import annotations

import pytest

from harness.research_validation import (
    ReuseDecision,
    ReuseDecisionTable,
    ValidationResult,
    brief_targets_miniprogram,
    parse_reuse_table,
    validate_miniprogram_decision_coverage,
)

# ---------------------------------------------------------------------------
# brief_targets_miniprogram
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "brief_text,expected",
    [
        ("做一个鱼跃学员管理小程序", True),
        ("Build a WeChat mini app for tracking", True),
        ("Translate OD HTML to miniprogram", True),
        ("weapp with wxss + wxml", True),
        ("做一个 TODO web app", False),
        ("Build a React Native mobile app", False),
        ("", False),
    ],
)
def test_brief_signal_detection(brief_text: str, expected: bool):
    assert brief_targets_miniprogram(brief_text) is expected


# ---------------------------------------------------------------------------
# validate_miniprogram_decision_coverage
# ---------------------------------------------------------------------------


def _table_with_rows(rows: list[tuple[str, str, str, int, str, str]]) -> ReuseDecisionTable:
    """Convenience: build a ReuseDecisionTable from a list of row tuples
    in the same column order as ``render_reuse_table``:
    (candidate, url, maturity, coverage_pct, decision, reason).
    """
    decisions = [
        ReuseDecision(
            candidate=c,
            url=u,
            maturity=m,
            coverage_pct=cov,
            decision=d,  # type: ignore[arg-type]
            reason=r,
        )
        for (c, u, m, cov, d, r) in rows
    ]
    return ReuseDecisionTable(decisions=decisions)


class TestValidateMiniprogramDecisionCoverage:
    def test_passes_when_brief_is_web(self):
        """Web briefs bypass the miniprogram gate entirely."""
        table = _table_with_rows([
            ("owner/web-lib", "https://github.com/owner/web", "active", 80, "wrap", "covers web"),
        ])
        result = validate_miniprogram_decision_coverage("Build a TODO web app", table)
        assert result.is_valid is True
        assert result.error is None

    def test_passes_when_two_miniprogram_libs_listed(self):
        table = _table_with_rows([
            ("Tencent/weui-wxss", "https://github.com/Tencent/weui-wxss", "active", 70, "wrap", "light baseline"),
            ("youzan/vant-weapp", "https://github.com/youzan/vant-weapp", "active", 90, "drop", "overkill for 5 pages"),
            ("some/web-lib", "https://github.com/owner/web", "active", 50, "wrap", "for tooling"),
        ])
        result = validate_miniprogram_decision_coverage(
            "做一个鱼跃学员管理小程序",
            table,
        )
        assert result.is_valid is True, result.error

    def test_fails_when_no_miniprogram_libs_listed(self):
        table = _table_with_rows([
            ("owner/some-lib", "https://github.com/owner/some", "active", 80, "wrap", "covers X"),
            ("other/another-lib", "https://github.com/other/another", "active", 60, "wrap", "covers Y"),
        ])
        result = validate_miniprogram_decision_coverage(
            "做一个鱼跃学员管理小程序",
            table,
        )
        assert result.is_valid is False
        assert "miniprogram library" in (result.error or "")
        assert "0" in (result.error or "")  # zero hits mentioned

    def test_fails_when_only_one_miniprogram_lib(self):
        table = _table_with_rows([
            ("Tencent/weui-wxss", "https://github.com/Tencent/weui-wxss", "active", 70, "wrap", "baseline"),
            ("other/some-lib", "https://github.com/other/some", "active", 50, "wrap", "tooling"),
        ])
        result = validate_miniprogram_decision_coverage(
            "做一个鱼跃学员管理小程序",
            table,
        )
        assert result.is_valid is False
        assert "1" in (result.error or "")

    def test_recognises_lib_by_url_not_just_candidate(self):
        """Slug appears in url rather than candidate column — should still count."""
        table = _table_with_rows([
            ("wechat ui baseline", "https://github.com/Tencent/weui-wxss", "active", 70, "wrap", "official"),
            ("alt picker", "https://github.com/youzan/vant-weapp", "active", 90, "drop", "overkill"),
        ])
        result = validate_miniprogram_decision_coverage(
            "做一个鱼跃小程序",
            table,
        )
        assert result.is_valid is True, result.error

    def test_recognises_loose_slug_forms(self):
        """Researchers may write 'weui-wxss' or 'Lin UI' without owner/repo."""
        table = _table_with_rows([
            ("weui-wxss", "https://example.com/weui", "active", 70, "wrap", "baseline"),
            ("Lin UI", "https://example.com/lin", "active", 80, "drop", "design system mismatch"),
        ])
        result = validate_miniprogram_decision_coverage(
            "做一个微信小程序",
            table,
        )
        assert result.is_valid is True, result.error


# ---------------------------------------------------------------------------
# End-to-end with parse_reuse_table (research markdown → table → gate)
# ---------------------------------------------------------------------------


class TestEndToEnd:
    def test_miniprogram_research_markdown_passes(self):
        md = """# 研究报告:鱼跃学员管理小程序

## 一、需求理解
学员管理小程序。

## 四、复用决策表

| 候选 | URL | 成熟度 | 覆盖% | 决策 | 理由 |
|------|-----|--------|-------|------|------|
| Tencent/weui-wxss | https://github.com/Tencent/weui-wxss | active | 70 | wrap | 官方设计语言,5 page 够用 |
| youzan/vant-weapp | https://github.com/youzan/vant-weapp | active | 90 | drop | 业务简单不需要 60+ 组件 |

## 七、来源
- https://github.com/Tencent/weui-wxss
"""
        table = parse_reuse_table(md)
        result = validate_miniprogram_decision_coverage(
            "做一个鱼跃学员管理小程序",
            table,
        )
        assert result.is_valid is True

    def test_miniprogram_research_missing_ecosystem_fails(self):
        md = """# 研究报告:鱼跃学员管理小程序

## 一、需求理解
学员管理小程序。

## 四、复用决策表

| 候选 | URL | 成熟度 | 覆盖% | 决策 | 理由 |
|------|-----|--------|-------|------|------|
| owner/some-lib | https://github.com/owner/some | active | 80 | wrap | covers X |
| other/another-lib | https://github.com/other/another | active | 60 | wrap | covers Y |

## 七、来源
- https://github.com/owner/some
"""
        table = parse_reuse_table(md)
        result = validate_miniprogram_decision_coverage(
            "做一个鱼跃学员管理小程序",
            table,
        )
        assert result.is_valid is False