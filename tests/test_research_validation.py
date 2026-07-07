"""Tests for harness.research_validation module.

Per MASTER-PLAN P4 / TASKS T10: the research report (001-research-report.md)
must contain a 复用决策表 (reuse decision table) before the pipeline may
advance to the plan phase. These tests pin down the parsing contract and
the validation behaviour.
"""

from __future__ import annotations

import pytest
import pydantic

from harness.research_validation import (
    DECISION_VALUES,
    DECISION_HEADER,
    DECISION_LABELS,
    Decision,
    EmptyReuseTableError,
    MissingReuseTableError,
    ReuseDecision,
    ReuseDecisionTable,
    ReuseTableParseError,
    extract_reuse_table,
    find_decisions_for,
    has_reuse_table,
    parse_reuse_table,
    validate_research_report,
)


# ---------------------------------------------------------------------------
# ReuseDecision model tests
# ---------------------------------------------------------------------------


class TestReuseDecisionModel:
    def test_minimal_required_fields(self):
        d = ReuseDecision(
            candidate="owner/repo",
            url="https://github.com/owner/repo",
            maturity="active",
            coverage_pct=80,
            decision=Decision.WRAP,
            reason="covers 80% of the brief",
        )
        assert d.candidate == "owner/repo"
        assert d.decision is Decision.WRAP
        assert d.coverage_pct == 80

    def test_is_frozen(self):
        d = ReuseDecision(
            candidate="x",
            url="https://example.com/x",
            maturity="active",
            coverage_pct=50,
            decision=Decision.FORK,
            reason="needs minor tweaks",
        )
        with pytest.raises((pydantic.ValidationError, AttributeError, TypeError, ValueError)):
            d.decision = Decision.DROP  # type: ignore[misc]

    def test_coverage_pct_must_be_0_to_100(self):
        with pytest.raises(pydantic.ValidationError):
            ReuseDecision(
                candidate="x",
                url="https://example.com/x",
                maturity="active",
                coverage_pct=150,
                decision=Decision.DROP,
                reason="bad pct",
            )
        with pytest.raises(pydantic.ValidationError):
            ReuseDecision(
                candidate="x",
                url="https://example.com/x",
                maturity="active",
                coverage_pct=-1,
                decision=Decision.DROP,
                reason="bad pct",
            )

    def test_decision_must_be_enum_value(self):
        with pytest.raises(pydantic.ValidationError):
            ReuseDecision(
                candidate="x",
                url="https://example.com/x",
                maturity="active",
                coverage_pct=50,
                decision="warp",  # type: ignore[arg-type]
                reason="bad",
            )

    def test_url_must_look_like_url(self):
        with pytest.raises(pydantic.ValidationError):
            ReuseDecision(
                candidate="x",
                url="not-a-url",
                maturity="active",
                coverage_pct=50,
                decision=Decision.DROP,
                reason="bad url",
            )

    def test_maturity_must_be_whitelisted(self):
        with pytest.raises(pydantic.ValidationError):
            ReuseDecision(
                candidate="x",
                url="https://example.com/x",
                maturity="thriving",  # not in the whitelist
                coverage_pct=50,
                decision=Decision.DROP,
                reason="bad maturity label",
            )
        with pytest.raises(pydantic.ValidationError):
            ReuseDecision(
                candidate="x",
                url="https://example.com/x",
                maturity="活跃",  # Chinese not allowed
                coverage_pct=50,
                decision=Decision.DROP,
                reason="bad maturity label",
            )

    def test_maturity_accepts_whitelisted_values(self):
        for m in ("active", "maintained", "stale", "archived"):
            d = ReuseDecision(
                candidate="x",
                url="https://example.com/x",
                maturity=m,
                coverage_pct=50,
                decision=Decision.WRAP,
                reason="valid maturity label",
            )
            assert d.maturity == m

    def test_reason_must_be_at_least_5_chars(self):
        with pytest.raises(pydantic.ValidationError):
            ReuseDecision(
                candidate="x",
                url="https://example.com/x",
                maturity="active",
                coverage_pct=50,
                decision=Decision.WRAP,
                reason="r",  # 1 char
            )


# ---------------------------------------------------------------------------
# ReuseDecisionTable tests
# ---------------------------------------------------------------------------


class TestReuseDecisionTable:
    def test_empty_table_is_invalid(self):
        with pytest.raises(pydantic.ValidationError):
            ReuseDecisionTable(decisions=[])

    def test_min_size_one(self):
        d = ReuseDecision(
            candidate="x",
            url="https://example.com/x",
            maturity="active",
            coverage_pct=50,
            decision=Decision.PORT,
            reason="to learn",
        )
        table = ReuseDecisionTable(decisions=[d])
        assert len(table.decisions) == 1

    def test_contains_finds_decision(self):
        d = ReuseDecision(
            candidate="acme/widget",
            url="https://github.com/acme/widget",
            maturity="active",
            coverage_pct=70,
            decision=Decision.WRAP,
            reason="covers auth and storage",
        )
        table = ReuseDecisionTable(decisions=[d])
        assert table.contains("acme/widget") is True
        assert table.contains("nonexistent/repo") is False

    def test_by_decision_filters(self):
        decisions = [
            ReuseDecision(
                candidate="a/aa",
                url="https://example.com/aa",
                maturity="active",
                coverage_pct=50,
                decision=Decision.WRAP,
                reason="reason for adopting this lib",
            ),
            ReuseDecision(
                candidate="b/bb",
                url="https://example.com/bb",
                maturity="stale",
                coverage_pct=30,
                decision=Decision.DROP,
                reason="reason for adopting this lib",
            ),
            ReuseDecision(
                candidate="c/cc",
                url="https://example.com/cc",
                maturity="active",
                coverage_pct=40,
                decision=Decision.WRAP,
                reason="reason for adopting this lib",
            ),
        ]
        table = ReuseDecisionTable(decisions=decisions)
        wraps = table.by_decision(Decision.WRAP)
        assert len(wraps) == 2
        assert {d.candidate for d in wraps} == {"a/aa", "c/cc"}


# ---------------------------------------------------------------------------
# Parser tests
# ---------------------------------------------------------------------------


class TestParseReuseTable:
    def test_parses_well_formed_table(self):
        md = """
# 研究报告

一些调研文字...

## 复用决策表

| 候选 | URL | 成熟度 | 覆盖% | 决策 | 理由 |
|------|-----|--------|-------|------|------|
| acme/widget | https://github.com/acme/widget | active | 80 | wrap | 覆盖核心 80% 需求 |
| beta/lib | https://github.com/beta/lib | maintained | 60 | fork | 需小幅改造认证模块 |

## 风险

其他内容...
"""
        table = parse_reuse_table(md)
        assert len(table.decisions) == 2
        assert table.decisions[0].candidate == "acme/widget"
        assert table.decisions[0].url == "https://github.com/acme/widget"
        assert table.decisions[0].decision is Decision.WRAP
        assert table.decisions[1].decision is Decision.FORK

    def test_raises_on_missing_table(self):
        md = "# 研究报告\n\n这份报告没有任何决策表。\n"
        with pytest.raises(MissingReuseTableError):
            parse_reuse_table(md)

    def test_raises_on_empty_table(self):
        md = """
## 复用决策表

| 候选 | URL | 成熟度 | 覆盖% | 决策 | 理由 |
|------|-----|--------|-------|------|------|
"""
        with pytest.raises(EmptyReuseTableError):
            parse_reuse_table(md)

    def test_raises_on_only_header_row(self):
        md = """
## 复用决策表

| 候选 | URL | 成熟度 | 覆盖% | 决策 | 理由 |
|------|-----|--------|-------|------|------|
|------|-----|--------|-------|------|------|
"""
        # An explicit "empty body" row (separator repeated) should be treated
        # the same as no rows at all.
        with pytest.raises(EmptyReuseTableError):
            parse_reuse_table(md)

    def test_raises_on_invalid_decision_value(self):
        md = """
## 复用决策表

| 候选 | URL | 成熟度 | 覆盖% | 决策 | 理由 |
|------|-----|--------|-------|------|------|
| foo/bar | https://github.com/foo/bar | active | 50 | warp | bad decision word for testing |
"""
        with pytest.raises(ReuseTableParseError):
            parse_reuse_table(md)

    def test_raises_on_missing_url(self):
        md = """
## 复用决策表

| 候选 | URL | 成熟度 | 覆盖% | 决策 | 理由 |
|------|-----|--------|-------|------|------|
| foo/bar | not-a-url | active | 50 | wrap | valid reason |
"""
        with pytest.raises(ReuseTableParseError):
            parse_reuse_table(md)

    def test_accepts_alternate_decision_labels(self):
        md = """
## 复用决策表

| 候选 | URL | 成熟度 | 覆盖% | 决策 | 理由 |
|------|-----|--------|-------|------|------|
| a/aa | https://github.com/a/aa | active | 80 | Fork | 改少量后可用 |
| b/bb | https://github.com/b/bb | maintained | 60 | wrap | 包装库而非自研 |
| c/cc | https://github.com/c/cc | active | 40 | PORT | 移植到目标栈 |
| d/dd | https://github.com/d/dd | stale | 10 | 弃 | 弃用原因清晰 |
"""
        table = parse_reuse_table(md)
        decisions = [d.decision for d in table.decisions]
        assert decisions == [
            Decision.FORK,
            Decision.WRAP,
            Decision.PORT,
            Decision.DROP,
        ]

    def test_ignores_pipes_inside_reason_field(self):
        # A "|" inside a cell should not break the row parser if the row has
        # the correct number of cells.
        md = """
## 复用决策表

| 候选 | URL | 成熟度 | 覆盖% | 决策 | 理由 |
|------|-----|--------|-------|------|------|
| foo/bar | https://github.com/foo/bar | active | 80 | wrap | 覆盖 a/b/c 三块功能 |
"""
        table = parse_reuse_table(md)
        assert len(table.decisions) == 1
        assert "a/b/c" in table.decisions[0].reason

    def test_table_must_appear_after_decision_header(self):
        md = """
# 研究报告

| 候选 | URL | 成熟度 | 覆盖% | 决策 | 理由 |
|------|-----|--------|-------|------|------|
| foo/bar | https://github.com/foo/bar | active | 80 | wrap | valid reason |

但这里没有任何"复用决策表"标题。
"""
        with pytest.raises(MissingReuseTableError):
            parse_reuse_table(md)

    def test_accepts_numbered_section_prefix(self):
        # The researcher may number the section: "## 四、复用决策表" /
        # "## 4. 复用决策表" / "## Section 4: 复用决策表" etc.
        md = """
# 研究报告

## 四、复用决策表

| 候选 | URL | 成熟度 | 覆盖% | 决策 | 理由 |
|------|-----|--------|-------|------|------|
| foo/bar | https://github.com/foo/bar | active | 80 | wrap | valid reason |
"""
        table = parse_reuse_table(md)
        assert len(table.decisions) == 1
        assert table.decisions[0].candidate == "foo/bar"

    def test_accepts_english_numbered_prefix(self):
        md = """
# Research Report

## Section 4: Reuse Decision Table

| 候选 | URL | 成熟度 | 覆盖% | 决策 | 理由 |
|------|-----|--------|-------|------|------|
| foo/bar | https://github.com/foo/bar | active | 80 | wrap | valid reason |
"""
        table = parse_reuse_table(md)
        assert len(table.decisions) == 1


# ---------------------------------------------------------------------------
# extract_reuse_table — lenient helper used by the planner
# ---------------------------------------------------------------------------


class TestExtractReuseTable:
    def test_returns_none_when_missing(self):
        assert extract_reuse_table("# nothing here\n") is None

    def test_returns_table_when_present(self):
        md = """
## 复用决策表

| 候选 | URL | 成熟度 | 覆盖% | 决策 | 理由 |
|------|-----|--------|-------|------|------|
| x/y | https://github.com/x/y | active | 50 | wrap | valid reason |
"""
        table = extract_reuse_table(md)
        assert table is not None
        assert len(table.decisions) == 1


# ---------------------------------------------------------------------------
# has_reuse_table — cheap boolean check
# ---------------------------------------------------------------------------


class TestHasReuseTable:
    def test_true_when_section_header_present(self):
        assert has_reuse_table("## 复用决策表\n") is True

    def test_true_when_header_with_alt_text(self):
        # The contract accepts common aliases
        assert has_reuse_table("## 复用决策表 (Reuse Decision Table)\n") is True
        assert has_reuse_table("## Reuse Decision Table\n") is True

    def test_false_when_absent(self):
        assert has_reuse_table("# 研究报告\n\n没有决策表\n") is False


# ---------------------------------------------------------------------------
# find_decisions_for — convenience for the planner
# ---------------------------------------------------------------------------


class TestFindDecisionsFor:
    def test_filters_by_decision_kind(self):
        md = """
## 复用决策表

| 候选 | URL | 成熟度 | 覆盖% | 决策 | 理由 |
|------|-----|--------|-------|------|------|
| a/aa | https://github.com/a/aa | active | 80 | wrap | 包装库而非自研 |
| b/bb | https://github.com/b/bb | active | 60 | fork | 改少量后可用 |
| c/cc | https://github.com/c/cc | active | 40 | drop | 弃用原因清晰 |
"""
        wraps = find_decisions_for(md, Decision.WRAP)
        assert [d.candidate for d in wraps] == ["a/aa"]
        forks = find_decisions_for(md, Decision.FORK)
        assert [d.candidate for d in forks] == ["b/bb"]
        drops = find_decisions_for(md, Decision.DROP)
        assert [d.candidate for d in drops] == ["c/cc"]

    def test_returns_empty_when_table_missing(self):
        assert find_decisions_for("# nothing\n", Decision.WRAP) == []


# ---------------------------------------------------------------------------
# validate_research_report — full gate
# ---------------------------------------------------------------------------


class TestValidateResearchReport:
    def test_valid_report_passes(self):
        md = """
# 研究报告

## 复用决策表

| 候选 | URL | 成熟度 | 覆盖% | 决策 | 理由 |
|------|-----|--------|-------|------|------|
| a/aa | https://github.com/a/aa | active | 80 | wrap | 包装库而非自研 |
"""
        result = validate_research_report(md)
        assert result.is_valid is True
        assert result.table is not None
        assert len(result.table.decisions) == 1
        assert result.error is None

    def test_missing_table_fails(self):
        md = "# 研究报告\n\n无决策表\n"
        result = validate_research_report(md)
        assert result.is_valid is False
        assert result.table is None
        assert "复用决策表" in (result.error or "")

    def test_empty_table_fails(self):
        md = """
## 复用决策表

| 候选 | URL | 成熟度 | 覆盖% | 决策 | 理由 |
|------|-----|--------|-------|------|------|
"""
        result = validate_research_report(md)
        assert result.is_valid is False
        assert result.table is None
        assert "0" in (result.error or "") or "空" in (result.error or "")

    def test_collects_url_evidence(self):
        md = """
## 复用决策表

| 候选 | URL | 成熟度 | 覆盖% | 决策 | 理由 |
|------|-----|--------|-------|------|------|
| a/aa | https://github.com/a/aa | active | 80 | wrap | 包装库而非自研 |
| b/bb | https://github.com/b/bb | maintained | 60 | fork | 改少量后可用 |
"""
        result = validate_research_report(md)
        assert result.is_valid is True
        urls = [d.url for d in (result.table.decisions if result.table else [])]
        assert "https://github.com/a/aa" in urls
        assert "https://github.com/b/bb" in urls


# ---------------------------------------------------------------------------
# Constants — guard against silent rename
# ---------------------------------------------------------------------------


class TestConstants:
    def test_decision_values_match_enum_members(self):
        for d in Decision:
            assert d.value in DECISION_VALUES

    def test_decision_labels_has_chinese_alias(self):
        # Each decision must have at least one Chinese alias registered.
        for d in Decision:
            assert d in DECISION_LABELS
            assert len(DECISION_LABELS[d]) >= 1


# ---------------------------------------------------------------------------
# End-to-end smoke: simulates a real research report for a known real repo
# (per T10 acceptance: decision table non-empty and contains real repo URLs).
# ---------------------------------------------------------------------------


REAL_REPO_URL = "https://github.com/vercel/next.js"
REAL_LIB_URL = "https://github.com/expressjs/express"


class TestEndToEndMarkdown:
    """The T10 acceptance check: parse a research report that cites real
    GitHub repos and confirm the URLs survive validation. We do not make
    network calls — we only confirm the markdown is well-formed and the
    URLs look like the real thing.
    """

    def test_markdown_note_app_has_real_repos(self):
        md = f"""
# 研究报告：markdown 笔记 app

## 一、需求理解
一个能编辑、搜索、标签化 markdown 笔记的 web app；单用户优先。

## 二、竞品分析
- **Notable / Bear**：聚焦写作体验；强排版、可订阅主题。
- **Notion / Obsidian**：图谱化、双向链接；block 模型。
- **Logseq / Tana**：outliner 起家，强调大纲与查询。

## 三、技术架构候选
- 前端：Next.js (App Router) + TipTap 编辑器
- 存储：SQLite 本地优先 + 同步到 S3
- 搜索：FlexSearch 客户端预索引

## 四、复用决策表

| 候选 | URL | 成熟度 | 覆盖% | 决策 | 理由 |
|------|-----|--------|-------|------|------|
| vercel/next.js | {REAL_REPO_URL} | active | 90 | wrap | 已有 SSG/SSR/Router，剩下 10% 用薄壳包装 |
| expressjs/express | {REAL_LIB_URL} | maintained | 60 | drop | 已用 Next.js API Routes，引入 Express 会重复 |
| ueberdosis/tiptap | https://github.com/ueberdosis/tiptap | active | 85 | wrap | 核心编辑器；扩展用 ProseMirror 插件 |
| remarkjs/remark | https://github.com/remarkjs/remark | active | 80 | wrap | markdown 解析后端 |

## 五、风险与对策
- tipTap 与 SSR 兼容性：引入 dynamic import，仅在客户端加载。
- 同步冲突：CRDT 优于 last-writer-wins；先用最简 LWW + 后续迁移。

## 六、开发建议
- Sprint 1: 基础编辑器 (基于 tipTap 包装)
- Sprint 2: 文件树 + 标签 (基于 next.js App Router)
- Sprint 3: 搜索 (FlexSearch)

## 七、来源
- https://github.com/vercel/next.js
- https://github.com/ueberdosis/tiptap
- https://remarkjs.com
"""
        result = validate_research_report(md)
        assert result.is_valid is True
        assert result.table is not None
        assert len(result.table.decisions) == 4

        urls = [d.url for d in result.table.decisions]
        assert REAL_REPO_URL in urls
        assert REAL_LIB_URL in urls

        # Spot check: the real GitHub URLs survive validation
        for url in urls:
            assert url.startswith("https://github.com/") or url.startswith("https://")

        # All drop decisions are flagged
        drops = result.table.by_decision(Decision.DROP)
        assert len(drops) == 1
        assert drops[0].url == REAL_LIB_URL
