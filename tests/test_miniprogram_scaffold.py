"""Tests for templates/miniprogram-scaffold/ structural correctness.

Validates the scaffold is a legal miniprogram project skeleton that
will pass the miniprogram reviewer's 5 hard rules out of the box:

  1. All 5 pages exist with full {wxml, wxss, json, js} quartet.
  2. ``app.json`` is valid JSON with the expected page list + tabBar.
  3. Pure-function utils (data/format/charts) do NOT use ``wx.*``.
  4. utils/storage.js is the wx.* whitelist and does use wx.*.
  5. Each page's ``.js`` file is ≤ 50 lines (reviewer cap is ~30 logic
     lines; 50 leaves headroom for generator to fill in skeleton
     stubs).
  6. ``tests/automator/_smoke.spec.js`` exists and requires
     ``miniprogram-automator``.
  7. ``shared/token.wxss`` exists and contains OD token names
     (--aqua, --pass, --radius).
  8. ``project.config.json`` is valid JSON with ``miniprogramRoot``.

These tests don't run the scaffold itself — they verify the static
structure is sound enough that a generator agent can fork it
without breaking the miniprogram reviewer.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

SCAFFOLD = Path(__file__).parent.parent / "templates" / "miniprogram-scaffold"

PAGES = [
    "index",
    "class-overview",
    "students",
    "profile",
]

# students/student-detail lives under students/ — verify separately
STUDENT_DETAIL = ["students", "student-detail"]


# ---------------------------------------------------------------------------
# 1. Page files
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("page", PAGES)
def test_top_level_page_has_all_four_files(page: str):
    pdir = SCAFFOLD / "pages" / page
    assert pdir.is_dir(), f"missing page dir: {pdir}"
    for ext in ("wxml", "wxss", "json", "js"):
        f = pdir / f"{page}.{ext}"
        assert f.exists(), f"missing {f}"


def test_student_detail_lives_under_students():
    pdir = SCAFFOLD / "pages" / "students" / "student-detail"
    assert pdir.is_dir()
    for ext in ("wxml", "wxss", "json", "js"):
        f = pdir / f"student-detail.{ext}"
        assert f.exists(), f"missing {f}"


# ---------------------------------------------------------------------------
# 2. app.json
# ---------------------------------------------------------------------------


def test_app_json_valid():
    app_json = SCAFFOLD / "app.json"
    data = json.loads(app_json.read_text(encoding="utf-8"))
    assert "pages" in data and isinstance(data["pages"], list)
    # 5 expected page paths (students/student-detail nested)
    expected = {
        "pages/index/index",
        "pages/class-overview/class-overview",
        "pages/students/students",
        "pages/students/student-detail",
        "pages/profile/profile",
    }
    actual = set(data["pages"])
    assert actual == expected


def test_app_json_has_tabbar():
    data = json.loads((SCAFFOLD / "app.json").read_text(encoding="utf-8"))
    tb = data.get("tabBar", {})
    assert tb.get("list"), "tabBar.list must be non-empty"
    # All 4 tab entries should point to known page paths
    paths = {item["pagePath"] for item in tb["list"]}
    assert "pages/index/index" in paths
    assert "pages/students/students" in paths
    assert "pages/class-overview/class-overview" in paths
    assert "pages/profile/profile" in paths


# ---------------------------------------------------------------------------
# 3. Pure utils don't use wx.*
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "utils_file",
    ["utils/data.js", "utils/format.js", "utils/charts.js"],
)
def test_pure_utils_have_no_wx_calls(utils_file: str):
    path = SCAFFOLD / utils_file
    text = path.read_text(encoding="utf-8")
    # Strip block + line comments before scanning so docs/example code
    # mentioning wx.* as a forbidden pattern doesn't trigger.
    stripped = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    stripped = re.sub(r"//[^\n]*", "", stripped)
    # Find wx. followed by an identifier — covers wx.getStorageSync etc.
    matches = re.findall(r"\bwx\.[A-Za-z_]\w*", stripped)
    assert not matches, (
        f"{utils_file} contains forbidden wx.* call(s): {matches}. "
        "Per miniprogram reviewer §3, only utils/storage.js + page "
        "lifecycle files may call wx.*."
    )


def test_utils_storage_uses_wx():
    text = (SCAFFOLD / "utils" / "storage.js").read_text(encoding="utf-8")
    assert "wx.getStorageSync" in text or "wx.setStorageSync" in text, (
        "utils/storage.js is the wx.* whitelist module — must actually use wx.*"
    )


def test_utils_storage_documents_whitelist_role():
    text = (SCAFFOLD / "utils" / "storage.js").read_text(encoding="utf-8")
    assert "whitelist" in text.lower() or "白名单" in text, (
        "utils/storage.js must self-document that it's the wx.* whitelist"
    )


# ---------------------------------------------------------------------------
# 5. Page JS file size
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("page", PAGES)
def test_page_js_under_50_lines(page: str):
    f = SCAFFOLD / "pages" / page / f"{page}.js"
    line_count = sum(1 for _ in f.read_text(encoding="utf-8").splitlines())
    assert line_count <= 50, f"{f} has {line_count} lines; cap is 50"


def test_student_detail_js_under_50_lines():
    f = SCAFFOLD / "pages" / "students" / "student-detail" / "student-detail.js"
    line_count = sum(1 for _ in f.read_text(encoding="utf-8").splitlines())
    assert line_count <= 50


# ---------------------------------------------------------------------------
# 6. Smoke test file
# ---------------------------------------------------------------------------


def test_smoke_spec_exists():
    f = SCAFFOLD / "tests" / "automator" / "_smoke.spec.js"
    assert f.exists()
    text = f.read_text(encoding="utf-8")
    assert "miniprogram-automator" in text, "smoke spec must require miniprogram-automator"
    # Should reference all 5 page paths so generator gets a working launch
    for path in (
        "/pages/index/index",
        "/pages/students/students",
        "/pages/class-overview/class-overview",
        "/pages/students/student-detail",
        "/pages/profile/profile",
    ):
        assert path in text, f"smoke spec missing page reference: {path}"
    # Must include the SKIP_RUNTIME escape hatch for Linux CI
    assert "MINIPROGRAM_SKIP_RUNTIME" in text


# ---------------------------------------------------------------------------
# 7. Token stylesheet
# ---------------------------------------------------------------------------


def test_token_wxss_has_od_tokens():
    f = SCAFFOLD / "shared" / "token.wxss"
    text = f.read_text(encoding="utf-8")
    for name in ("--aqua", "--pass", "--radius", "--ink", "--muted"):
        assert name in text, f"token.wxss missing {name}"


# ---------------------------------------------------------------------------
# 8. project.config.json
# ---------------------------------------------------------------------------


def test_project_config_valid():
    data = json.loads((SCAFFOLD / "project.config.json").read_text(encoding="utf-8"))
    assert "miniprogramRoot" in data
    assert "appid" in data
    assert "setting" in data


# ---------------------------------------------------------------------------
# Bonus: page js uses Page({...}) — required by miniprogram runtime
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("page", PAGES)
def test_page_js_calls_Page(page: str):
    f = SCAFFOLD / "pages" / page / f"{page}.js"
    text = f.read_text(encoding="utf-8")
    assert "Page(" in text, f"{f} must call Page(...) at top level"


def test_app_js_calls_App():
    text = (SCAFFOLD / "app.js").read_text(encoding="utf-8")
    assert "App(" in text, "app.js must call App(...) at top level"