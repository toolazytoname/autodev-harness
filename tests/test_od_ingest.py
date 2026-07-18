"""Tests for harness/od_ingest.py — OD HTML → brief markdown reverse-engineering.

Uses ``tests/fixtures/od-sample/`` (5 HTML + shared.css/js) as the
canonical mini OD project. Tests are scoped to the public API and the
three extractor functions:

  - ``extract_design_tokens``
  - ``extract_business_schema``
  - ``extract_page_list``
  - ``scan_od_project``
  - ``build_brief_markdown``
  - ``write_brief``
"""

from __future__ import annotations

from pathlib import Path

import pytest

from harness import od_ingest

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "od-sample"


# ---------------------------------------------------------------------------
# extract_design_tokens
# ---------------------------------------------------------------------------


class TestExtractDesignTokens:
    def test_returns_known_tokens(self):
        tokens = od_ingest.extract_design_tokens(FIXTURE_DIR / "shared.css")
        names = {n for n, _, _ in tokens.entries}
        # Every token we wrote in the fixture must be picked up
        assert "--bg" in names
        assert "--surface" in names
        assert "--ink" in names
        assert "--aqua" in names
        assert "--pass" in names
        assert "--radius" in names

    def test_groups_assignments(self):
        tokens = od_ingest.extract_design_tokens(FIXTURE_DIR / "shared.css")
        by_name = {n: g for n, _, g in tokens.entries}
        assert by_name["--bg"] == "Surface"
        assert by_name["--ink"] == "Ink"
        assert by_name["--aqua"] == "Aqua"
        assert by_name["--pass"] == "Status"
        assert by_name["--radius"] == "Geometry"

    def test_preserves_value(self):
        tokens = od_ingest.extract_design_tokens(FIXTURE_DIR / "shared.css")
        for name, value, _ in tokens.entries:
            if name == "--radius":
                assert value == "20px"

    def test_missing_file_returns_empty(self, tmp_path):
        tokens = od_ingest.extract_design_tokens(tmp_path / "does-not-exist.css")
        assert tokens.entries == []

    def test_ignores_unknown_tokens(self, tmp_path):
        # Tokens that don't match any group prefix are dropped silently
        f = tmp_path / "shared.css"
        f.write_text("--my-custom-thing: 1px;\n--bg: white;\n")
        tokens = od_ingest.extract_design_tokens(f)
        names = {n for n, _, _ in tokens.entries}
        assert "--bg" in names
        assert "--my-custom-thing" not in names


# ---------------------------------------------------------------------------
# extract_business_schema
# ---------------------------------------------------------------------------


class TestExtractBusinessSchema:
    def test_picks_up_top_level_constants(self):
        biz = od_ingest.extract_business_schema(FIXTURE_DIR / "shared.js")
        names = {n for n, _, _ in biz.shapes}
        assert "STUDENTS" in names
        assert "CLASSES" in names
        assert "TERMS" in names

    def test_extracts_keys_from_first_object(self):
        biz = od_ingest.extract_business_schema(FIXTURE_DIR / "shared.js")
        students = next(s for s in biz.shapes if s[0] == "STUDENTS")
        keys = students[1]
        assert "id" in keys
        assert "name" in keys
        assert "classid" in keys or "classId" in keys  # lowercased

    def test_infers_count_from_inline_comment(self):
        biz = od_ingest.extract_business_schema(FIXTURE_DIR / "shared.js")
        students = next(s for s in biz.shapes if s[0] == "STUDENTS")
        # Fixture declares `/* 21 entries */` inside the array — must be detected
        assert students[2] == 21

    def test_missing_file_returns_empty(self, tmp_path):
        biz = od_ingest.extract_business_schema(tmp_path / "no.js")
        assert biz.shapes == []


# ---------------------------------------------------------------------------
# extract_page_list
# ---------------------------------------------------------------------------


class TestExtractPageList:
    def test_lists_html_files(self):
        pages = od_ingest.extract_page_list(FIXTURE_DIR, js_path=FIXTURE_DIR / "shared.js")
        assert "index.html" in pages.html_files
        assert "students.html" in pages.html_files

    def test_parses_tabbar_entries(self):
        pages = od_ingest.extract_page_list(FIXTURE_DIR, js_path=FIXTURE_DIR / "shared.js")
        assert pages.tabbar_entries, "tabbar should be parsed from fixture TAB_ICONS + tabbarHTML"
        ids = [e[0] for e in pages.tabbar_entries]
        assert "home" in ids
        assert "students" in ids
        # First entry should have href + label populated
        first = pages.tabbar_entries[0]
        assert first[1] == "index.html"
        assert first[2] == "首页"

    def test_missing_dir_returns_empty(self, tmp_path):
        pages = od_ingest.extract_page_list(tmp_path / "no-such")
        assert pages.html_files == []
        assert pages.tabbar_entries == []


# ---------------------------------------------------------------------------
# detect_role_system
# ---------------------------------------------------------------------------


class TestDetectRoleSystem:
    def test_true_when_role_helpers_present(self):
        result = od_ingest.detect_role_system(
            FIXTURE_DIR / "shared.js",
            [FIXTURE_DIR / "students.html"],
        )
        assert result is True

    def test_false_when_no_role_hints(self, tmp_path):
        js = tmp_path / "shared.js"
        js.write_text("// no role helpers here\nconst X = 1;\n")
        html = tmp_path / "page.html"
        html.write_text("<html><body>no role class</body></html>\n")
        assert od_ingest.detect_role_system(js, [html]) is False


# ---------------------------------------------------------------------------
# scan_od_project
# ---------------------------------------------------------------------------


class TestScanOdProject:
    def test_returns_aggregate_result(self):
        scan = od_ingest.scan_od_project(FIXTURE_DIR)
        assert scan.od_dir == FIXTURE_DIR.resolve()
        ingest = scan.ingest
        assert ingest.tokens.entries, "tokens should be non-empty"
        assert ingest.business.shapes, "business shapes should be non-empty"
        assert ingest.pages.html_files, "pages should be non-empty"
        assert ingest.role_supported is True

    def test_missing_dir_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            od_ingest.scan_od_project(tmp_path / "no-such")

    def test_file_path_raises_not_a_directory(self, tmp_path):
        f = tmp_path / "just-a-file"
        f.write_text("x")
        with pytest.raises(NotADirectoryError):
            od_ingest.scan_od_project(f)


# ---------------------------------------------------------------------------
# build_brief_markdown
# ---------------------------------------------------------------------------


class TestBuildBriefMarkdown:
    def test_markdown_contains_token_table(self):
        md = od_ingest.build_brief_markdown(FIXTURE_DIR, user_prompt="鱼跃")
        assert "## Design tokens" in md
        assert "--aqua" in md
        assert "--pass" in md

    def test_markdown_contains_business_schema(self):
        md = od_ingest.build_brief_markdown(FIXTURE_DIR, user_prompt="鱼跃")
        assert "## Business schema" in md
        assert "STUDENTS" in md

    def test_markdown_contains_page_list(self):
        md = od_ingest.build_brief_markdown(FIXTURE_DIR, user_prompt="鱼跃")
        assert "## Source layout" in md
        assert "index.html" in md
        assert "students.html" in md

    def test_markdown_contains_role_section(self):
        md = od_ingest.build_brief_markdown(FIXTURE_DIR, user_prompt="鱼跃")
        assert "## Role system" in md
        assert "**Yes**" in md

    def test_markdown_includes_user_prompt(self):
        md = od_ingest.build_brief_markdown(FIXTURE_DIR, user_prompt="鱼跃学员管理小程序")
        assert "鱼跃学员管理小程序" in md

    def test_markdown_mentions_pipeline_notes(self):
        md = od_ingest.build_brief_markdown(FIXTURE_DIR, user_prompt="")
        assert "Pipeline notes" in md
        assert "od_reverse_engineer" in md

    def test_missing_css_graceful(self, tmp_path):
        # OD dir with only shared.js (no css) — should still emit a brief
        d = tmp_path / "minimal"
        d.mkdir()
        (d / "shared.js").write_text("const STUDENTS = [];\n")
        (d / "index.html").write_text("<html></html>")
        md = od_ingest.build_brief_markdown(d, user_prompt="x")
        assert "_No design tokens extracted" in md


# ---------------------------------------------------------------------------
# write_brief
# ---------------------------------------------------------------------------


class TestWriteBrief:
    def test_writes_atomically(self, tmp_path):
        content = "# 项目需求\n\nFrom OD fixture.\n"
        path = od_ingest.write_brief(tmp_path, content)
        assert path == tmp_path / "000-brief.md"
        assert path.read_text(encoding="utf-8") == content