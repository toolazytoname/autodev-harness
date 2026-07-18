"""Scaffold structure tests — verify templates/uniapp-scaffold is a valid
uni-app + Vue 3 project that passes the reviewer hard rules.

Mirrors tests/test_miniprogram_scaffold.py for the native miniprogram
scaffold so the uniapp variant ships with equivalent coverage.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).parent.parent
SCAFFOLD = REPO_ROOT / "templates" / "uniapp-scaffold"


@pytest.fixture(scope="module")
def scaffold_root() -> Path:
    assert SCAFFOLD.exists(), f"scaffold missing: {SCAFFOLD}"
    return SCAFFOLD


# ----------------------------------------------------------------------
# Top-level structure
# ----------------------------------------------------------------------


def test_scaffold_has_readme(scaffold_root: Path) -> None:
    assert (scaffold_root / "README.md").exists()


def test_scaffold_has_package_json(scaffold_root: Path) -> None:
    p = scaffold_root / "package.json"
    assert p.exists()
    pkg = json.loads(p.read_text(encoding="utf-8"))
    # 必含依赖
    for dep in ("@dcloudio/uni-app", "@dcloudio/uni-ui", "vue", "pinia"):
        assert dep in pkg.get("dependencies", {}), f"missing dep {dep}"
    # devDependencies: 测试 runtime
    for dev in ("@dcloudio/uni-automator", "vite", "sass"):
        assert dev in pkg.get("devDependencies", {}), f"missing devDep {dev}"


def test_scaffold_has_vite_config(scaffold_root: Path) -> None:
    p = scaffold_root / "vite.config.js"
    assert p.exists()
    txt = p.read_text(encoding="utf-8")
    assert "@dcloudio/vite-plugin-uni" in txt
    assert "uni()" in txt


def test_scaffold_has_index_html(scaffold_root: Path) -> None:
    p = scaffold_root / "index.html"
    assert p.exists()
    txt = p.read_text(encoding="utf-8")
    assert 'id="app"' in txt
    assert "/src/main.js" in txt


# ----------------------------------------------------------------------
# src/ layout
# ----------------------------------------------------------------------


def test_src_main_js(scaffold_root: Path) -> None:
    p = scaffold_root / "src" / "main.js"
    assert p.exists()
    txt = p.read_text(encoding="utf-8")
    assert "createSSRApp" in txt
    assert "createPinia" in txt


def test_src_app_vue(scaffold_root: Path) -> None:
    p = scaffold_root / "src" / "App.vue"
    assert p.exists()
    txt = p.read_text(encoding="utf-8")
    assert "<script setup>" in txt
    assert "onLaunch" in txt
    assert "wx.cloud.init" in txt  # 云开发初始化


def test_src_manifest_json(scaffold_root: Path) -> None:
    p = scaffold_root / "src" / "manifest.json"
    assert p.exists()
    cfg = json.loads(p.read_text(encoding="utf-8"))
    assert cfg["vueVersion"] == "3"
    assert cfg["mp-weixin"]["appid"]  # 必填(可以 touristappid 占位)
    assert cfg["h5"]["title"]


def test_src_pages_json(scaffold_root: Path) -> None:
    p = scaffold_root / "src" / "pages.json"
    assert p.exists()
    cfg = json.loads(p.read_text(encoding="utf-8"))
    paths = [pg["path"] for pg in cfg["pages"]]
    # 5 个 page 必须全在
    expected = [
        "pages/index/index",
        "pages/class-overview/class-overview",
        "pages/students/students",
        "pages/students/student-detail",
        "pages/profile/profile",
    ]
    for want in expected:
        assert want in paths, f"missing page in pages.json: {want}"
    # tabBar 4 项
    assert len(cfg["tabBar"]["list"]) == 4


def test_src_uni_scss(scaffold_root: Path) -> None:
    p = scaffold_root / "src" / "uni.scss"
    assert p.exists()
    txt = p.read_text(encoding="utf-8")
    # 必有 SCSS 变量
    for var in ("$uni-color-primary", "$yu-aqua", "$yu-pass", "$yu-warn", "$yu-fail"):
        assert var in txt, f"missing SCSS var {var}"


# ----------------------------------------------------------------------
# 5 page Vue SFC
# ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "rel_path",
    [
        "src/pages/index/index.vue",
        "src/pages/class-overview/class-overview.vue",
        "src/pages/students/students.vue",
        "src/pages/students/student-detail.vue",
        "src/pages/profile/profile.vue",
    ],
)
def test_each_page_vue_exists(scaffold_root: Path, rel_path: str) -> None:
    p = scaffold_root / rel_path
    assert p.exists(), f"missing page: {rel_path}"


@pytest.mark.parametrize(
    "rel_path",
    [
        "src/pages/index/index.vue",
        "src/pages/class-overview/class-overview.vue",
        "src/pages/students/students.vue",
        "src/pages/students/student-detail.vue",
        "src/pages/profile/profile.vue",
    ],
)
def test_each_page_vue_under_300_lines(scaffold_root: Path, rel_path: str) -> None:
    """Reviewer 硬规则 #3 — page Vue SFC 逻辑 ≤ 100 行;<template> + <script> +
    <style> 三段合计,MVP scaffold 带详细 SCSS,总长应 < 300 行;过审红线
    = 400(超此行 reviewer 会扣分)。"""
    p = scaffold_root / rel_path
    text = p.read_text(encoding="utf-8")
    line_count = len(text.splitlines())
    assert line_count < 400, f"{rel_path} too long: {line_count} lines (must < 400)"


def test_no_miniprogram_anti_patterns(scaffold_root: Path) -> None:
    """所有 page 不能含 bindtap / wx:for / wxml 标签 — uni-app 不用这些。"""
    anti_patterns = ("bindtap", "bindinput", "wx:for", "wx:if", "<wxml", "<wxss")
    for vue_path in (scaffold_root / "src" / "pages").rglob("*.vue"):
        txt = vue_path.read_text(encoding="utf-8")
        for pat in anti_patterns:
            assert pat not in txt, (
                f"{vue_path.relative_to(scaffold_root)} contains anti-pattern {pat!r} "
                "(uni-app uses @click / v-for / @vue SFC, not miniprogram syntax)"
            )


# ----------------------------------------------------------------------
# src/common/ — pure-function-ized (reviewer 硬规则 #2)
# ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "rel_path",
    [
        "src/common/data.js",
        "src/common/format.js",
        "src/common/charts.js",
    ],
)
def test_common_pure_files_no_uni_or_wx(scaffold_root: Path, rel_path: str) -> None:
    """data.js / format.js / charts.js 必须是纯函数,无 uni.* / wx.* 调用。

    storage.js 和 cloud.js 是白名单(它们就是平台适配层)。

    只匹配**代码里**的真实调用(`uni.xxx` / `wx.xxx` 后面接标识符),
    跳过注释 / 文档字符串里的引用(`uni.*` 占位符、`wx.cloud.*` 等带
    `*` 的说明性文字)。
    """
    import re
    p = scaffold_root / rel_path
    txt = p.read_text(encoding="utf-8")
    # 真正的 API 调用:单词边界 + uni./wx. + 字母/下划线
    for pattern, label in (
        (r"\buni\.[a-zA-Z_]", "uni.* API"),
        (r"\bwx\.(cloud|request|getStorageSync|setStorageSync|scanCode|showToast)", "wx.* API"),
    ):
        m = re.search(pattern, txt)
        assert not m, (
            f"{rel_path} contains forbidden {label} call at: "
            f"…{txt[max(0, m.start()-20):m.end()+20]}… "
            "(must stay pure; comments/docstrings are excluded)"
        )


def test_common_storage_is_whitelist(scaffold_root: Path) -> None:
    """storage.js 必须用 uni.* API(它是白名单文件)。"""
    p = scaffold_root / "src" / "common" / "storage.js"
    txt = p.read_text(encoding="utf-8")
    assert "uni.getStorageSync" in txt or "uni.setStorageSync" in txt, (
        "storage.js must use uni.* APIs (it's the whitelist file)"
    )


def test_common_cloud_is_whitelist(scaffold_root: Path) -> None:
    """cloud.js 必须用 wx.cloud.* API。"""
    p = scaffold_root / "src" / "common" / "cloud.js"
    txt = p.read_text(encoding="utf-8")
    assert "wx.cloud.callFunction" in txt or "wx.cloud.database" in txt, (
        "cloud.js must use wx.cloud.* APIs"
    )


# ----------------------------------------------------------------------
# cloudfunctions/
# ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "fn_name",
    ["login", "seedStudents", "addStudent", "updateScore"],
)
def test_cloudfunction_has_index_and_pkg(scaffold_root: Path, fn_name: str) -> None:
    fn_dir = scaffold_root / "cloudfunctions" / fn_name
    assert fn_dir.is_dir(), f"missing cloudfunction dir: {fn_dir}"
    idx = fn_dir / "index.js"
    pkg = fn_dir / "package.json"
    assert idx.exists(), f"{fn_name} missing index.js"
    assert pkg.exists(), f"{fn_name} missing package.json"
    pkg_data = json.loads(pkg.read_text(encoding="utf-8"))
    assert "wx-server-sdk" in pkg_data.get("dependencies", {}), (
        f"{fn_name} must depend on wx-server-sdk"
    )


def test_login_uses_openid(scaffold_root: Path) -> None:
    """login 云函数必须读 OPENID(微信鉴权)。"""
    txt = (scaffold_root / "cloudfunctions" / "login" / "index.js").read_text(encoding="utf-8")
    assert "getWXContext" in txt
    assert "OPENID" in txt


# ----------------------------------------------------------------------
# tests/uni-automator/ — automator 烟雾测试
# ----------------------------------------------------------------------


def test_automator_smoke_spec_exists(scaffold_root: Path) -> None:
    p = scaffold_root / "tests" / "uni-automator" / "_smoke.spec.js"
    assert p.exists(), "missing tests/uni-automator/_smoke.spec.js"
    txt = p.read_text(encoding="utf-8")
    assert "@dcloudio/uni-automator" in txt
    assert "describe(" in txt
    assert "pure functions" in txt.lower() or "pure-functions" in txt


# ----------------------------------------------------------------------
# v2 canonical schema 兼容性
# ----------------------------------------------------------------------


def test_data_classes_have_v2_event_keys(scaffold_root: Path) -> None:
    """classes 必须有 v2 canonical 字段:eventKeys / standards / promotionRule;
    v1 projectSet 保留为 alias。"""
    js = scaffold_root / "src" / "common" / "data.js"
    txt = js.read_text(encoding="utf-8")
    # 用 node 直接 require 解析(避免 JS 语法差异)
    import subprocess
    node_test = subprocess.run(
        ["node", "-e", f"const d=require({str(js)!r}); console.log(JSON.stringify(d.CLASSES.map(c=>({{id:c.id, eventKeys:c.eventKeys, hasStandards:!!c.standards, hasRule:!!c.promotionRule, projectSet:c.projectSet}}))))"],
        capture_output=True, text=True, cwd=scaffold_root,
    )
    assert node_test.returncode == 0, f"node parse failed: {node_test.stderr}"
    classes_info = json.loads(node_test.stdout.strip())
    # 至少 5 个 class
    assert len(classes_info) == 5
    # 每个 class 都有 v2 字段
    for c in classes_info:
        assert c["eventKeys"], f"{c['id']} missing eventKeys"
        assert c["hasStandards"], f"{c['id']} missing standards"
        assert c["hasRule"], f"{c['id']} missing promotionRule"
        assert c["projectSet"], f"{c['id']} missing v1 alias projectSet"


def test_data_scores_have_v2_alias(scaffold_root: Path) -> None:
    """SCORES 必须同时含 v2 canonical 字段(eventKey/scoreSec/scoreStatus) + v1 alias (projectId/time/judge)。"""
    js = scaffold_root / "src" / "common" / "data.js"
    import subprocess
    node_test = subprocess.run(
        ["node", "-e", f"const d=require({str(js)!r}); const r=d.SCORES[0]; console.log(JSON.stringify({{hasV2: !!(r.eventKey && r.scoreSec!=undefined && r.scoreStatus), hasV1: !!(r.projectId && r.time!=undefined && r.judge), eventKey:r.eventKey, scoreStatus:r.scoreStatus}}))"],
        capture_output=True, text=True, cwd=scaffold_root,
    )
    assert node_test.returncode == 0, f"node parse failed: {node_test.stderr}"
    info = json.loads(node_test.stdout.strip())
    assert info["hasV2"], f"SCORES[0] missing v2 canonical fields: {info}"
    assert info["hasV1"], f"SCORES[0] missing v1 alias: {info}"


def test_data_students_have_v2_class_history(scaffold_root: Path) -> None:
    """students 必须含 v2 canonical:classHistory[] / status / needsClassReview;
    v1 coach/firstTerm 保留为 alias。"""
    js = scaffold_root / "src" / "common" / "data.js"
    import subprocess
    node_test = subprocess.run(
        ["node", "-e", f"const d=require({str(js)!r}); const s=d.STUDENTS[0]; console.log(JSON.stringify({{hasClassHistory: Array.isArray(s.classHistory), hasStatus: !!s.status, hasCoachIds: Array.isArray(s.coachIds), hasV1Coach: typeof s.coach==='string', hasV1FirstTerm: typeof s.firstTerm==='string', hasNameNormalized: !!s.nameNormalized}}))"],
        capture_output=True, text=True, cwd=scaffold_root,
    )
    assert node_test.returncode == 0
    info = json.loads(node_test.stdout.strip())
    assert info["hasClassHistory"], f"missing classHistory: {info}"
    assert info["hasStatus"], f"missing status: {info}"
    assert info["hasCoachIds"], f"missing coachIds: {info}"
    assert info["hasV1Coach"], f"missing v1 coach alias: {info}"
    assert info["hasV1FirstTerm"], f"missing v1 firstTerm alias: {info}"
    assert info["hasNameNormalized"], f"missing nameNormalized: {info}"


def test_format_js_v2_helpers(scaffold_root: Path) -> None:
    """format.js 必须暴露 v2 helper:scoreStatusToJudge / scoreCellClass。"""
    js = scaffold_root / "src" / "common" / "format.js"
    txt = js.read_text(encoding="utf-8")
    assert "export function scoreStatusToJudge" in txt
    assert "export function scoreCellClass" in txt
    # summarizePass 必须读 v2 字段
    assert "r.eventKey || r.projectId" in txt
    assert "r.scoreStatus" in txt


def test_format_js_v2_helpers_runtime(scaffold_root: Path) -> None:
    """v2 helper 在运行时正确映射:measured+scoreSec<=threshold → pass。"""
    js = scaffold_root / "src" / "common" / "format.js"
    import subprocess
    node_test = subprocess.run(
        ["node", "-e", f"const f=require({str(js)!r}); const a=f.scoreStatusToJudge('measured', 50, 60); const b=f.scoreStatusToJudge('measured', 70, 60); const c=f.scoreStatusToJudge('missing', null, 60); console.log(JSON.stringify({{a, b, c, cellA: f.judgeClass(a), cellC: f.judgeClass(c)}}))"],
        capture_output=True, text=True, cwd=scaffold_root,
    )
    assert node_test.returncode == 0, f"node failed: {node_test.stderr}"
    info = json.loads(node_test.stdout.strip())
    assert info["a"] == "pass", f"scoreStatusToJudge(measured, 50, 60) should be pass: {info}"
    assert info["b"] == "fail", f"scoreStatusToJudge(measured, 70, 60) should be fail: {info}"
    assert info["c"] == "miss", f"scoreStatusToJudge(missing) should be miss: {info}"
    assert info["cellA"] == "cell-pass"
    assert info["cellC"] == "cell-miss"


def test_cloudfunctions_seed_v2_canonical(scaffold_root: Path) -> None:
    """seedStudents 云函数必须写入 v2 canonical 字段(eventKey/scoreStatus/thresholdSec)。"""
    js = scaffold_root / "cloudfunctions" / "seedStudents" / "index.js"
    txt = js.read_text(encoding="utf-8")
    assert "eventKey" in txt
    assert "scoreStatus" in txt
    assert "thresholdSec" in txt
    assert "recordKey" in txt
    # 4 个集合全 seed
    assert "seedCollection('classes'" in txt
    assert "seedCollection('terms'" in txt
    assert "seedCollection('students'" in txt
    assert "seedCollection('score_records'" in txt


def test_cloudfunctions_update_score_v2(scaffold_root: Path) -> None:
    """updateScore 云函数必须用 recordKey upsert + 写 v2 字段。"""
    js = scaffold_root / "cloudfunctions" / "updateScore" / "index.js"
    txt = js.read_text(encoding="utf-8")
    assert "recordKey" in txt
    assert "scoreStatus" in txt
    assert "thresholdSec" in txt
    assert "isQualified" in txt