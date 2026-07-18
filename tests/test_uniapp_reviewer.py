"""Reviewer prompt tests — verify agents/reviewers/uniapp.md covers the
T-Bridge uniapp 5 hard rules + cross-platform scoring matrix.

Mirrors what would be tests/test_miniprogram_reviewer.py once that
exists; the rules differ (uni-app vs miniprogram) but the structure
parallels the miniprogram reviewer prompt verbatim.
"""

from __future__ import annotations

from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).parent.parent
REVIEWER = REPO_ROOT / "agents" / "reviewers" / "uniapp.md"


@pytest.fixture(scope="module")
def reviewer_text() -> str:
    assert REVIEWER.exists(), f"missing reviewer: {REVIEWER}"
    return REVIEWER.read_text(encoding="utf-8")


def test_reviewer_is_markdown(reviewer_text: str) -> None:
    assert reviewer_text.startswith("# ")


def test_reviewer_identifies_self(reviewer_text: str) -> None:
    """标题包含 'UniApp' 或 'uni-app',便于 grep。"""
    head = reviewer_text.split("\n", 5)
    assert any("UniApp" in line or "uni-app" in line.lower() for line in head[:3])


# ----------------------------------------------------------------------
# 5 硬规则覆盖
# ----------------------------------------------------------------------


def test_rule_1_automator_script(reviewer_text: str) -> None:
    """规则 1:uni-automator script 存在 + 结构正确。"""
    assert "uni-automator script exists" in reviewer_text.lower()
    assert "@dcloudio/uni-automator" in reviewer_text
    assert "init({platform" in reviewer_text or "init({" in reviewer_text


def test_rule_2_pure_functions(reviewer_text: str) -> None:
    """规则 2:业务逻辑纯函数化,page ≤ 100 行。"""
    assert "pure-function-ized" in reviewer_text.lower() or "pure function" in reviewer_text.lower()
    assert "src/common/" in reviewer_text
    assert "100 lines" in reviewer_text or "200 lines" in reviewer_text


def test_rule_3_uni_wx_isolation(reviewer_text: str) -> None:
    """规则 3:uni.* / wx.* API 隔离,common 白名单 = storage.js + cloud.js。"""
    assert "isolation" in reviewer_text.lower() or "isolated" in reviewer_text.lower()
    assert "storage.js" in reviewer_text
    assert "cloud.js" in reviewer_text
    assert "whitelist" in reviewer_text.lower()


def test_rule_4_acceptance_mapping(reviewer_text: str) -> None:
    """规则 4:acceptance ↔ uni-automator it() 对应。"""
    assert "acceptance" in reviewer_text.lower()
    assert "it(" in reviewer_text or "describe(" in reviewer_text


def test_rule_5_pages_json_manifest(reviewer_text: str) -> None:
    """规则 5:pages.json + manifest.json + cloudfunctions 配置正确。"""
    assert "pages.json" in reviewer_text
    assert "manifest.json" in reviewer_text
    assert "cloudfunctions" in reviewer_text


# ----------------------------------------------------------------------
# 评分矩阵
# ----------------------------------------------------------------------


def test_scoring_table(reviewer_text: str) -> None:
    """完整的 scoring guide 表,1.0 / 0.8-0.99 / 0.5-0.79 / 0.0-0.49 四档。"""
    assert "1.0" in reviewer_text
    assert "0.0–0.49" in reviewer_text or "0.0-0.49" in reviewer_text


def test_blocker_conditions(reviewer_text: str) -> None:
    """reviewer blocker 条件。"""
    assert "blocker" in reviewer_text.lower()
    # 至少 2 个 blocker 条件
    assert reviewer_text.lower().count("blocker") >= 3


def test_evidence_required(reviewer_text: str) -> None:
    """evidence 必填(macOS runtime 或 lint 输出)。"""
    assert "evidence" in reviewer_text.lower()
    assert "node --check" in reviewer_text or "node tests" in reviewer_text


# ----------------------------------------------------------------------
# 跨端平台清单
# ----------------------------------------------------------------------


def test_cross_platform_targets_documented(reviewer_text: str) -> None:
    """uni-app 跨端目标清单(mp-weixin / h5 / app-plus / mp-toutiao 等)。"""
    assert "mp-weixin" in reviewer_text
    assert "h5" in reviewer_text
    # 至少提到 iOS / Android(MVP 后期目标)
    assert "iOS" in reviewer_text or "ios" in reviewer_text
    assert "Android" in reviewer_text or "android" in reviewer_text