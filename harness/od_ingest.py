"""OD (Open Design) HTML project reverse-engineering → brief markdown.

T-Bridge: lets ``python -m harness --design-draft DIR -- "..."`` ingest a
local Open Design export (5 HTML pages + ``shared.css`` + ``shared.js``)
and emit a structured markdown brief that downstream phases (research,
plan, ui_design) can consume.

What we extract:

  - **Design tokens** from ``shared.css``: ``--<name>: <value>`` lines,
    grouped (Surface / Ink / Aqua / Orange / Status / Geometry).
  - **Business schema** from ``shared.js``: top-level ``const STUDENTS /
    CLASSES / TERMS`` array shapes, schema only (count + keys), not
    actual student data.
  - **Page list**: every ``*.html`` file at the OD root, with the
    inferred tabbar nav structure (parsed from ``TAB_ICONS`` in
    ``shared.js`` if present).
  - **Role system**: ``initRole / toggleRole / getRole / setRole`` +
    the ``coach-only`` CSS class hint.

What we **don't** extract (kept out of brief on purpose):

  - Actual student names / scores / ages — the source data is
    explicitly marked "脱敏" in ``shared.js``; the brief only carries
    schema so the downstream plan doesn't bake real-PII expectations.
  - The full DOM of each page — we list page files and let the
    generator agent reverse-engineer from HTML when it forks the
    scaffold (it has full HTML in the worktree).

This module is **filesystem-only**: no OD MCP daemon required. OD
projects on disk are the canonical source.

CLI hook: see ``__main__.py`` ``--design-draft`` parameter.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

# Token-name → friendly group. Keys are token prefixes (case-sensitive).
_TOKEN_GROUPS: list[tuple[str, str]] = [
    ("--bg", "Surface"),
    ("--surface", "Surface"),
    ("--ink", "Ink"),
    ("--muted", "Ink"),
    ("--faint", "Ink"),
    ("--line", "Ink"),
    ("--aqua", "Aqua"),
    ("--orange", "Orange"),
    ("--pass", "Status"),
    ("--near", "Status"),
    ("--miss", "Status"),
    ("--radius", "Geometry"),
    ("--shadow", "Geometry"),
    ("--font", "Geometry"),
    ("--mono", "Geometry"),
]


@dataclass(frozen=True)
class OdTokens:
    """Design tokens extracted from shared.css.

    ``entries`` is a list of (name, value, group) tuples in source order.
    Empty groups (groups with no tokens in the source) are not present.
    """

    entries: list[tuple[str, str, str]] = field(default_factory=list)


@dataclass(frozen=True)
class OdBusiness:
    """Top-level data shapes from shared.js.

    ``shapes`` is a list of (const_name, sample_keys, count) tuples.
    ``count`` is the literal number of array elements if we can parse it
    from the source (e.g. ``const STUDENTS = [ /* 21 entries */ ]``);
    ``None`` means we couldn't determine it.
    """

    shapes: list[tuple[str, list[str], int | None]] = field(default_factory=list)


@dataclass(frozen=True)
class OdPages:
    """Page list + inferred tabbar nav."""

    html_files: list[str] = field(default_factory=list)
    tabbar_entries: list[tuple[str, str, str]] = field(default_factory=list)
    """Each entry is (id, href, label). Empty when TAB_ICONS not parseable."""


@dataclass(frozen=True)
class OdIngestResult:
    """Aggregate result of scanning an OD project."""

    od_dir: Path
    tokens: OdTokens
    business: OdBusiness
    pages: OdPages
    role_supported: bool


# ---------------------------------------------------------------------------
# Token extraction
# ---------------------------------------------------------------------------

# Matches ``--<name>: <value>;`` (single-line declarations only — multi-line
# values like linear-gradient with stops aren't expected in OD token files).
_TOKEN_LINE_RE = re.compile(
    r"""^\s*(?P<name>--[a-zA-Z][\w-]*)\s*:\s*(?P<value>[^;]+);?\s*$""",
    re.MULTILINE,
)


def _group_for(token_name: str) -> str | None:
    """Return the friendly group name for a token, or None if unknown."""
    for prefix, group in _TOKEN_GROUPS:
        if token_name.startswith(prefix):
            return group
    return None


def extract_design_tokens(css_path: Path) -> OdTokens:
    """Pull ``--<name>: <value>`` declarations from a CSS file."""
    if not css_path.exists():
        return OdTokens()
    text = css_path.read_text(encoding="utf-8")
    entries: list[tuple[str, str, str]] = []
    for match in _TOKEN_LINE_RE.finditer(text):
        name = match.group("name")
        value = match.group("value").strip()
        group = _group_for(name)
        if group is None:
            continue
        entries.append((name, value, group))
    return OdTokens(entries=entries)


# ---------------------------------------------------------------------------
# Business schema extraction
# ---------------------------------------------------------------------------

# Matches ``const NAME = [`` followed by either an inline count comment
# (e.g. ``/* 21 entries */``) or just the array opening. We look back 200
# chars for the count comment for robustness.
#
# NOTE: kept as a single-line raw string so the literal ``\n`` between
# groups doesn't survive into the compiled pattern — that would break
# matching against text that has actual newlines between the identifier
# and the ``=`` (the inline raw triple-quote bug we hit once).
_CONST_ARRAY_RE = re.compile(
    r"\b(?P<name>STUDENTS|CLASSES|TERMS|CLASS_BY_ID|STUDENT_BY_ID|LATEST)\s*=\s*\[",
    re.MULTILINE,
)


def _infer_count_after(text: str, open_bracket_idx: int) -> int | None:
    """Look 400 chars past ``[`` for either ``/* N entries */`` or a
    ``},`` block count. Returns the integer or None.
    """
    window = text[open_bracket_idx : open_bracket_idx + 400]
    # First try the canonical "/* N entries */" comment OD author writes.
    m = re.search(r"/\*\s*(\d+)\s+entries?\s*\*/", window)
    if m:
        return int(m.group(1))
    # Fall back: count top-level ``},`` block separators. Fragile but works
    # for the OD convention where every entry is a single-line literal.
    m = re.search(r"\},\s*\n", window)
    if m:
        # Number of entries ≈ number of closing braces minus 1 (last has no comma)
        return window.count("},")
    return None


# Matches the key list inside an ``mk()`` or first object literal of an
# array: ``{ id: '...', name: '...', age: ..., classId: '...', ... }``.
_OBJECT_KEYS_RE = re.compile(r"\{\s*([^}]+)\}", re.DOTALL)


def _extract_keys(text: str, open_bracket_idx: int) -> list[str]:
    """Heuristically pull key names from the first object literal after
    the array opening. Returns up to 10 keys, lowercased, deduped.
    """
    window = text[open_bracket_idx : open_bracket_idx + 600]
    m = _OBJECT_KEYS_RE.search(window)
    if not m:
        return []
    body = m.group(1)
    keys: list[str] = []
    seen: set[str] = set()
    for km in re.finditer(r"\b([a-zA-Z_]\w*)\s*:", body):
        k = km.group(1).lower()
        if k in seen:
            continue
        seen.add(k)
        keys.append(k)
        if len(keys) >= 10:
            break
    return keys


def extract_business_schema(js_path: Path) -> OdBusiness:
    """Find top-level ``const STUDENTS/CLASSES/TERMS`` arrays and report
    their shapes (name, key list, count).
    """
    if not js_path.exists():
        return OdBusiness()
    text = js_path.read_text(encoding="utf-8")
    shapes: list[tuple[str, list[str], int | None]] = []
    for m in _CONST_ARRAY_RE.finditer(text):
        name = m.group("name")
        open_bracket_idx = m.end() - 1  # position of the '['
        keys = _extract_keys(text, open_bracket_idx)
        count = _infer_count_after(text, open_bracket_idx)
        shapes.append((name, keys, count))
    return OdBusiness(shapes=shapes)


# ---------------------------------------------------------------------------
# Page list + tabbar extraction
# ---------------------------------------------------------------------------

# Matches ``TAB_ICONS = { id: '<svg-path>', ... }`` blocks. We only need
# the keys, not the values, to infer which pages the tabbar links to.
_TAB_ICONS_RE = re.compile(r"TAB_ICONS\s*=\s*\{([^}]+)\}", re.DOTALL)


def _extract_tabbar(js_text: str, html_files: list[str]) -> list[tuple[str, str, str]]:
    """Parse TAB_ICONS + adjacent tabbarHTML convention to get
    (id, href, label) tuples. Returns empty list when neither is parseable.
    """
    m = _TAB_ICONS_RE.search(js_text)
    if not m:
        return []
    block = m.group(1)
    ids = [km.group(1) for km in re.finditer(r"\b([a-zA-Z_]\w*)\s*:", block)]

    # Now look for the matching tabbarHTML that pairs each id with an
    # href + label. The OD convention is::
    #
    #   function tabbarHTML(active) {
    #     const t = (id, href, ico, label) => `...`;
    #     return `<nav>${t('home', 'index.html', ...)}...</nav>`;
    #   }
    #
    # We grep all ``t('<id>', '<href>', '<ico>', '<label>')`` calls.
    entries: list[tuple[str, str, str]] = []
    for tm in re.finditer(
        r"""t\(\s*['"](?P<id>[^'"]+)['"]\s*,\s*['"](?P<href>[^'"]+)['"]\s*,\s*['"][^'"]+['"]\s*,\s*['"](?P<label>[^'"]+)['"]""",
        js_text,
    ):
        entries.append((tm.group("id"), tm.group("href"), tm.group("label")))

    # If we found ids but no entries (some OD versions inline differently),
    # fall back to the id-only list with empty href/label.
    if ids and not entries:
        entries = [(i, "", "") for i in ids]

    return entries


def extract_page_list(od_dir: Path, js_path: Path | None = None) -> OdPages:
    """List ``*.html`` files at OD root and parse tabbar if ``shared.js``
    is provided.
    """
    if not od_dir.exists() or not od_dir.is_dir():
        return OdPages()
    html_files = sorted(
        p.name for p in od_dir.iterdir() if p.is_file() and p.suffix.lower() == ".html"
    )
    tabbar: list[tuple[str, str, str]] = []
    if js_path and js_path.exists():
        tabbar = _extract_tabbar(js_path.read_text(encoding="utf-8"), html_files)
    return OdPages(html_files=html_files, tabbar_entries=tabbar)


# ---------------------------------------------------------------------------
# Role detection
# ---------------------------------------------------------------------------

_ROLE_HINT_RE = re.compile(
    r"\b(initRole|toggleRole|getRole|setRole)\b|coach-only|\.coach-only",
)


def detect_role_system(js_path: Path, html_files: list[Path]) -> bool:
    """Heuristic: does the OD project implement the coach/parent role system?"""
    if js_path and js_path.exists() and _ROLE_HINT_RE.search(
        js_path.read_text(encoding="utf-8")
    ):
        return True
    for hp in html_files:
        try:
            if _ROLE_HINT_RE.search(hp.read_text(encoding="utf-8")):
                return True
        except (UnicodeDecodeError, OSError):
            continue
    return False


# ---------------------------------------------------------------------------
# Top-level orchestrator
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class OdScanResult:
    """Final result returned to ``__main__`` for brief composition."""

    od_dir: Path
    ingest: OdIngestResult


def scan_od_project(od_dir: Path) -> OdScanResult:
    """Scan an Open Design project directory and return structured data.

    Raises FileNotFoundError if ``od_dir`` doesn't exist.
    Returns a result with empty fields if shared.css / shared.js are
    missing (graceful degradation — the brief still lists pages).
    """
    od_dir = od_dir.resolve()
    if not od_dir.exists():
        raise FileNotFoundError(f"OD project dir not found: {od_dir}")
    if not od_dir.is_dir():
        raise NotADirectoryError(f"OD project path is not a directory: {od_dir}")

    css_path = od_dir / "shared.css"
    js_path = od_dir / "shared.js"
    tokens = extract_design_tokens(css_path)
    business = extract_business_schema(js_path)
    pages = extract_page_list(od_dir, js_path=js_path)
    role_supported = detect_role_system(
        js_path,
        [od_dir / name for name in pages.html_files],
    )

    return OdScanResult(
        od_dir=od_dir,
        ingest=OdIngestResult(
            od_dir=od_dir,
            tokens=tokens,
            business=business,
            pages=pages,
            role_supported=role_supported,
        ),
    )


# ---------------------------------------------------------------------------
# Brief markdown composition
# ---------------------------------------------------------------------------


def _render_tokens_markdown(tokens: OdTokens) -> str:
    if not tokens.entries:
        return "_No design tokens extracted (shared.css missing or empty)._"
    # Group by friendly group, preserve source order within group.
    by_group: dict[str, list[tuple[str, str]]] = {}
    for name, value, group in tokens.entries:
        by_group.setdefault(group, []).append((name, value))
    lines = ["| Token | Value |", "|---|---|"]
    for group in dict.fromkeys(g for _, _, g in tokens.entries):  # preserve order
        for name, value in by_group.get(group, []):
            lines.append(f"| `{name}` | `{value}` |")
    return "\n".join(lines)


def _render_business_markdown(business: OdBusiness) -> str:
    if not business.shapes:
        return "_No business constants extracted (shared.js missing or empty)._"
    lines = ["| Const | Keys | Count |", "|---|---|---|"]
    for name, keys, count in business.shapes:
        keys_repr = ", ".join(keys[:6]) + ("…" if len(keys) > 6 else "")
        count_repr = str(count) if count is not None else "—"
        lines.append(f"| `{name}` | `{keys_repr}` | {count_repr} |")
    return "\n".join(lines)


def _render_pages_markdown(pages: OdPages) -> str:
    if not pages.html_files:
        return "_No HTML files found at OD project root._"
    lines = ["- " + f for f in pages.html_files]
    if pages.tabbar_entries:
        lines.append("")
        lines.append("**Tabbar nav (parsed from `shared.js`):**")
        lines.append("")
        lines.append("| id | href | label |")
        lines.append("|---|---|---|")
        for tid, href, label in pages.tabbar_entries:
            lines.append(f"| `{tid}` | `{href}` | {label} |")
    return "\n".join(lines)


def build_brief_markdown(od_dir: Path, user_prompt: str) -> str:
    """Compose the full 000-brief.md markdown for an OD project.

    The result is meant to be written to ``<project_dir>/000-brief.md``,
    replacing the free-form text that ``__main__`` would otherwise write.
    Downstream phases (research / plan / ui_design) read this as a normal
    brief — no schema changes required.
    """
    scan = scan_od_project(od_dir)
    ingest = scan.ingest

    role_line = (
        "**Yes** — `coach` / `parent` role gating via `coach-only` class"
        if ingest.role_supported
        else "_No role system detected._"
    )

    md = f"""# 项目需求

> _Reverse-engineered from Open Design project at `{od_dir}`._
> User description: {user_prompt or "(none provided)"}

## Source layout

{_render_pages_markdown(ingest.pages)}

## Design tokens

Extracted from `shared.css`. Tokens are grouped by role:

{_render_tokens_markdown(ingest.tokens)}

## Business schema

Extracted from `shared.js` — shapes only (no actual student data, per
the脱敏 convention noted at the top of `shared.js`):

{_render_business_markdown(ingest.business)}

## Role system

{role_line}

## Pipeline notes

- This brief was produced via `harness/od_ingest.py`.
- Downstream phases should treat this as a **complete design spec**:
  no `ui_design` topic-direction exploration is needed.
- `WorkflowState.brief_mode = "od_reverse_engineer"`; `UIPhase` will
  switch to `mode=faithful` and skip the 4-direction divergence loop.
- Generator should fork `templates/uniapp-scaffold/` into
  `<project_dir>/` (5 page .vue + common/ + store/ + cloudfunctions/ +
  tests/uni-automator) and translate the OD HTML/CSS/JS into uni-app
  + Vue 3 idioms (`<template>` / `v-for` / `@click` / `uni.*` API).
  Backend is **微信云开发 wx.cloud** (云函数 + 云数据库 + openid 鉴权).
- See `docs/OD-TO-UNIAPP-MAPPING.md` for the node-mapping table.
- For users on the original miniprogram-only path, see
  `templates/miniprogram-scaffold/` + `agents/generator-miniprogram.md`
  + `docs/OD-TO-MINIPROGRAM-MAPPING.md` (kept as the legacy native path).
"""
    return md


def write_brief(project_dir: Path, content: str) -> Path:
    """Write 000-brief.md atomically. Returns the path written."""
    from harness.atomic_io import atomic_write_text

    target = project_dir / "000-brief.md"
    atomic_write_text(target, content)
    return target


__all__ = [
    "OdBusiness",
    "OdIngestResult",
    "OdPages",
    "OdScanResult",
    "OdTokens",
    "build_brief_markdown",
    "detect_role_system",
    "extract_business_schema",
    "extract_design_tokens",
    "extract_page_list",
    "scan_od_project",
    "write_brief",
]