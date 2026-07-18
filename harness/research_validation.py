"""Research report validation — enforce the 复用决策表 contract.

Per MASTER-PLAN P4 / TASKS T10: the research phase must surface a
"reuse decision table" listing every candidate repository or library
considered, what fraction of the brief it covers, and the
adopt/fork/port/wrap/drop decision with a one-line reason. The
pipeline refuses to advance into the plan phase until the table is
present and non-empty, and the planner reads the table to avoid
re-inventing something already on the shelf.

This module is intentionally pure: it takes the markdown body of
``001-research-report.md`` and returns either a parsed
:class:`ReuseDecisionTable` or a :class:`MissingReuseTableError` /
:class:`EmptyReuseTableError` / :class:`ReuseTableParseError`. The
pipeline wraps this in its own error class so callers can react
cleanly.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from enum import Enum

import pydantic

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


# Section headers we accept as marking the start of the reuse decision
# table. The canonical one is "复用决策表"; English / bilingual variants
# are also accepted so the researcher can be terse when it suits them.
DECISION_HEADER_ALIASES: tuple[str, ...] = (
    "复用决策表",
    "Reuse Decision Table",
    "复用决策表 (Reuse Decision Table)",
    "Reuse Table",
    "复用决策",
)

# The first alias is the canonical / preferred label.
DECISION_HEADER: str = DECISION_HEADER_ALIASES[0]

# Order matters here — longer aliases must be checked first so
# "复用决策表 (Reuse Decision Table)" isn't matched as the bare
# "复用决策表" token.
_HEADER_RE = re.compile(
    r"^\s*#{1,6}\s+[^#\n]*?\b(?P<title>" + "|".join(re.escape(a) for a in DECISION_HEADER_ALIASES) + r")\b[^\n]*$",
    re.MULTILINE,
)


# ---------------------------------------------------------------------------
# Decision enum
# ---------------------------------------------------------------------------


class Decision(str, Enum):
    """How the researcher decided to handle a candidate."""

    FORK = "fork"
    PORT = "port"
    WRAP = "wrap"
    DROP = "drop"


# All valid values, as a set for O(1) membership tests.
DECISION_VALUES: frozenset[str] = frozenset(d.value for d in Decision)

# Chinese / English aliases the markdown may use for the decision
# column. The parser normalises everything to the :class:`Decision`
# enum value, but the researcher can spell it however it likes.
DECISION_LABELS: dict[Decision, tuple[str, ...]] = {
    Decision.FORK: ("fork", "Fork", "FORK", "分叉", "改造"),
    Decision.PORT: ("port", "Port", "PORT", "移植"),
    Decision.WRAP: ("wrap", "Wrap", "WRAP", "包装", "封装"),
    Decision.DROP: ("drop", "Drop", "DROP", "弃", "弃用", "不用", "不采用"),
}


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class ReuseTableError(Exception):
    """Base class for all reuse-table problems."""


class MissingReuseTableError(ReuseTableError):
    """No '复用决策表' section header was found in the report."""


class EmptyReuseTableError(ReuseTableError):
    """A reuse table section exists but contains no decision rows."""


class ReuseTableParseError(ReuseTableError):
    """A reuse table row failed to parse (bad decision word, bad URL, etc.)."""


# ---------------------------------------------------------------------------
# Pydantic models (immutable)
# ---------------------------------------------------------------------------


_URL_RE = re.compile(r"^https?://[^\s)]+$")

# Maturity values the researcher may write (English aliases).
# Chinese / longer phrasings are intentionally rejected: the spec
# asks for a small whitelist so reviewers can grade the field
# objectively.
ALLOWED_MATURITY: frozenset[str] = frozenset(
    {"active", "maintained", "stale", "archived"}
)

# Minimum length for the `reason` cell. The spec asks for "no less
# than 5 characters" so we encode that here as a hard gate.
MIN_REASON_LEN: int = 5


class ReuseDecision(pydantic.BaseModel):
    """A single row of the reuse decision table."""

    model_config = pydantic.ConfigDict(frozen=True)

    candidate: str = pydantic.Field(min_length=1, description="repo or library name, e.g. 'acme/widget'")
    url: str = pydantic.Field(min_length=1, description="source URL — must be http(s)")
    maturity: str = pydantic.Field(min_length=1, description="active | maintained | stale | archived")
    coverage_pct: int = pydantic.Field(ge=0, le=100, description="0-100, % of brief covered")
    decision: Decision
    reason: str = pydantic.Field(min_length=1)

    @pydantic.field_validator("url")
    @classmethod
    def _url_must_look_like_url(cls, v: str) -> str:
        if not _URL_RE.match(v):
            raise ValueError(f"url must start with http:// or https:// and contain no whitespace: {v!r}")
        return v

    @pydantic.field_validator("maturity")
    @classmethod
    def _maturity_must_be_whitelisted(cls, v: str) -> str:
        if v not in ALLOWED_MATURITY:
            allowed = sorted(ALLOWED_MATURITY)
            raise ValueError(
                f"maturity must be one of {allowed}, got {v!r}"
            )
        return v

    @pydantic.field_validator("reason")
    @classmethod
    def _reason_must_have_substance(cls, v: str) -> str:
        if len(v) < MIN_REASON_LEN:
            raise ValueError(
                f"reason must be at least {MIN_REASON_LEN} characters (got {len(v)}: {v!r})"
            )
        return v


class ReuseDecisionTable(pydantic.BaseModel):
    """A non-empty set of reuse decisions."""

    model_config = pydantic.ConfigDict(frozen=True)

    decisions: list[ReuseDecision] = pydantic.Field(min_length=1)

    def contains(self, candidate: str) -> bool:
        """Return True iff *candidate* is one of the rows."""
        return any(d.candidate == candidate for d in self.decisions)

    def by_decision(self, decision: Decision) -> list[ReuseDecision]:
        """Filter to rows whose decision matches *decision*."""
        return [d for d in self.decisions if d.decision is decision]


# ---------------------------------------------------------------------------
# Validation result
# ---------------------------------------------------------------------------


class ValidationResult(pydantic.BaseModel):
    """Outcome of :func:`validate_research_report`."""

    model_config = pydantic.ConfigDict(frozen=True)

    is_valid: bool
    table: ReuseDecisionTable | None = None
    error: str | None = None


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------


def has_reuse_table(markdown_text: str) -> bool:
    """Cheap check: does the markdown body contain the table section header?

    Used by the pipeline to decide whether to even attempt parsing. Returns
    True as soon as any accepted alias is found.
    """
    return _HEADER_RE.search(markdown_text) is not None


def _normalize_decision(raw: str) -> Decision:
    """Map a free-form decision word to the :class:`Decision` enum."""
    s = raw.strip()
    for decision, aliases in DECISION_LABELS.items():
        if s in aliases:
            return decision
    valid = sorted({a for aliases in DECISION_LABELS.values() for a in aliases})
    raise ReuseTableParseError(
        f"invalid decision value {raw!r}; expected one of {valid}"
    )


# Columns we recognise, in order. The header row must contain ALL of
# these labels (in some order) — otherwise the report is not conformant.
_REQUIRED_HEADERS: dict[str, tuple[str, ...]] = {
    "candidate": ("候选", "候选(repo/库)", "候选 (repo/库)"),
    "url": ("URL", "url", "链接", "地址"),
    "maturity": ("成熟度",),
    "coverage_pct": ("覆盖%", "覆盖率", "覆盖 %", "coverage"),
    "decision": ("决策", "决定"),
    "reason": ("理由", "原因"),
}


def _classify_headers(header_cells: list[str]) -> dict[str, int]:
    """Map column role → position-in-row for the header cells.

    Raises :class:`ReuseTableParseError` if a required column is missing.
    """
    role_for_index: dict[str, int] = {}
    for idx, cell in enumerate(header_cells):
        cell_norm = cell.strip()
        for role, labels in _REQUIRED_HEADERS.items():
            if cell_norm in labels and role not in role_for_index:
                role_for_index[role] = idx
                break
    missing = [r for r in _REQUIRED_HEADERS if r not in role_for_index]
    if missing:
        labels = {r: _REQUIRED_HEADERS[r] for r in missing}
        raise ReuseTableParseError(
            f"reuse decision table is missing required columns: {labels}"
        )
    return role_for_index


def _parse_row(
    row_cells: list[str],
    column_index: dict[str, int],
) -> ReuseDecision:
    """Build a :class:`ReuseDecision` from one parsed table row."""
    # Pad short rows so callers don't have to special-case the trailing
    # pipe: "| a | b |" → [" a ", " b ", ""] is fine for indexing.
    while len(row_cells) < max(column_index.values()) + 1:
        row_cells.append("")

    def cell(role: str) -> str:
        return row_cells[column_index[role]].strip()

    candidate = cell("candidate")
    url = cell("url")
    maturity = cell("maturity")
    coverage_raw = cell("coverage_pct")
    decision_raw = cell("decision")
    reason = cell("reason")

    if not candidate or not url or not maturity or not decision_raw or not reason:
        raise ReuseTableParseError(
            f"reuse decision row has empty required cell: {row_cells!r}"
        )

    # Coverage may be written as "80" or "80%" — strip the trailing sign.
    coverage_clean = coverage_raw.rstrip("%").strip()
    try:
        coverage_pct = int(coverage_clean)
    except ValueError as e:
        raise ReuseTableParseError(
            f"coverage must be an integer 0-100, got {coverage_raw!r}"
        ) from e

    # ``_normalize_decision`` only raises ReuseTableParseError, which
    # we want to propagate unchanged so the row-level error message is
    # preserved.
    decision = _normalize_decision(decision_raw)

    try:
        return ReuseDecision(
            candidate=candidate,
            url=url,
            maturity=maturity,
            coverage_pct=coverage_pct,
            decision=decision,
            reason=reason,
        )
    except pydantic.ValidationError as e:
        # Translate pydantic's ValidationError (e.g. bad URL) into our
        # own error class so callers can match a single exception type.
        first = e.errors()[0] if e.errors() else {"msg": str(e)}
        loc = ".".join(str(p) for p in first.get("loc", ()))
        raise ReuseTableParseError(
            f"invalid reuse decision row {row_cells!r}: {loc} — {first.get('msg', '')}"
        ) from e


def _split_row(line: str) -> list[str]:
    """Split one markdown table row on ``|`` while tolerating edge pipes.

    Markdown tables can begin/end with ``|``; the separator row is also
    split by this code path but produces a list of ``---`` cells which
    are filtered out by the caller.
    """
    stripped = line.strip()
    # Drop leading/trailing pipes for uniform splitting.
    if stripped.startswith("|"):
        stripped = stripped[1:]
    if stripped.endswith("|"):
        stripped = stripped[:-1]
    return [c.strip() for c in stripped.split("|")]


def _extract_table_after_header(markdown_text: str) -> list[list[str]]:
    """Return the raw rows of the first reuse decision table in the text.

    The function looks for the section header, then consumes lines that
    look like table rows until the first non-table line. A markdown
    table row either begins with ``|`` or is the line directly under the
    header (the separator row of ``---``).

    Returns the header row + body rows. The caller is responsible for
    dropping the separator row.
    """
    match = _HEADER_RE.search(markdown_text)
    if not match:
        raise MissingReuseTableError(
            f"research report is missing the '{DECISION_HEADER}' section header"
        )
    body = markdown_text[match.end():]

    rows: list[list[str]] = []
    # The header row must follow directly (allow a blank line of
    # slack — some models add one).
    saw_header = False
    saw_separator = False
    for line in body.splitlines():
        if not line.strip():
            if saw_header:
                # End of the table when we hit a blank line after seeing
                # at least the header.
                break
            continue

        if not saw_header:
            if "|" not in line:
                # Header must be followed by a table row, otherwise the
                # section is just a label with no data.
                raise MissingReuseTableError(
                    f"section '{DECISION_HEADER}' is not followed by a markdown table"
                )
            rows.append(_split_row(line))
            saw_header = True
            continue

        if not saw_separator:
            # This line must be the separator row " | --- | --- | ".
            if "|" not in line or not re.search(r"^[\s|:-]+$", line):
                raise ReuseTableParseError(
                    f"expected markdown table separator (| --- |) after header, got: {line!r}"
                )
            saw_separator = True
            continue

        # Body row
        if "|" not in line:
            break
        if re.search(r"^[\s|:-]+$", line):
            # A separator-shaped row that somehow slipped past the
            # first separator (e.g. the researcher repeated the
            # separator). Treat it as a non-row terminator.
            break
        rows.append(_split_row(line))

    # rows[0] = header, rows[1:] = body (separator consumed but not stored)
    return rows


def parse_reuse_table(markdown_text: str) -> ReuseDecisionTable:
    """Parse the reuse decision table out of *markdown_text*.

    Raises:
        MissingReuseTableError: no section header found.
        EmptyReuseTableError: section present but no decision rows.
        ReuseTableParseError: a row could not be parsed.
    """
    rows = _extract_table_after_header(markdown_text)
    header = rows[0]
    # The separator row was consumed by _extract_table_after_header but
    # never appended to ``rows``; everything after the header is a body row.
    body = rows[1:]

    if not body:
        raise EmptyReuseTableError(
            f"section '{DECISION_HEADER}' has 0 decision rows (空表 — at least one required)"
        )

    column_index = _classify_headers(header)
    decisions = [_parse_row(row, column_index) for row in body]
    return ReuseDecisionTable(decisions=decisions)


def extract_reuse_table(markdown_text: str) -> ReuseDecisionTable | None:
    """Lenient parser: return the table on success, ``None`` on any error.

    Use this when the caller wants to gracefully degrade (e.g. the
    planner wants to know if a table is around to read, but should
    keep going without it).
    """
    try:
        return parse_reuse_table(markdown_text)
    except ReuseTableError:
        return None


def find_decisions_for(
    markdown_text: str,
    decision: Decision,
) -> list[ReuseDecision]:
    """Return all rows whose decision matches *decision*, or ``[]`` if absent.

    Convenience used by the planner: ``find_decisions_for(md, Decision.WRAP)``
    yields every candidate the researcher marked as "wrap".
    """
    table = extract_reuse_table(markdown_text)
    if table is None:
        return []
    return table.by_decision(decision)


# ---------------------------------------------------------------------------
# Full validation gate
# ---------------------------------------------------------------------------


def validate_research_report(markdown_text: str) -> ValidationResult:
    """Return a structured :class:`ValidationResult` for the pipeline gate.

    The gate is the contract the pipeline enforces before advancing
    into the plan phase:

    1. The section header must be present.
    2. The table must have at least one decision row.
    3. Every row must parse cleanly (valid decision, valid URL, etc.).

    All parse-time errors are translated to ``is_valid=False`` so the
    pipeline never has to handle three different exception classes —
    it just reads ``result.error`` and bails.
    """
    if not has_reuse_table(markdown_text):
        return ValidationResult(
            is_valid=False,
            table=None,
            error=(
                f"research report is missing required section: {DECISION_HEADER}. "
                "Per MASTER-PLAN P4 the research phase must produce a reuse decision table."
            ),
        )
    try:
        table = parse_reuse_table(markdown_text)
    except ReuseTableError as e:
        # Catches MissingReuseTableError, EmptyReuseTableError and
        # ReuseTableParseError uniformly — the gate doesn't care which
        # specific kind of failure it was, only that the report is bad.
        return ValidationResult(is_valid=False, table=None, error=str(e))
    return ValidationResult(is_valid=True, table=table, error=None)


# ---------------------------------------------------------------------------
# T-Bridge: miniprogram ecosystem requirements
# ---------------------------------------------------------------------------


# Canonical miniprogram signals — any of these in the brief text triggers
# the miniprogram-ecosystem gate. Mirrors the keyword set in
# ``agents/taskgen.md`` so the two phases agree on what "miniprogram"
# means.
_MINIPROGRAM_SIGNALS = (
    "小程序",
    "miniprogram",
    "wechat",
    "weapp",
    "wxss",
    "wxml",
    "wx-",
    "wx.",
)

# Recognised miniprogram ecosystem library slugs — used to confirm the
# researcher's reuse table actually has miniprogram picks. Slugs match
# GitHub `owner/repo` casing for the canonical candidates from
# ``docs/MINIPROGRAM-LIBRARIES.md``.
_MINIPROGRAM_LIB_SLUGS = {
    "Tencent/weui-wxss",
    "tencent/weui-wxss",
    "youzan/vant-weapp",
    "Youzan/vant-weapp",
    "TDesignOfficial/Lin UI",
    "tdesignofficial/lin ui",
    "xiaolin3303/wx-charts",
    "wx-charts",
    "weui-wxss",
    "vant-weapp",
    "Lin UI",
    "lin ui",
    "tdesign",
}


def brief_targets_miniprogram(brief_text: str) -> bool:
    """True iff the brief text carries any miniprogram signal keyword.

    Used by :func:`validate_miniprogram_decision_coverage` and by the
    pipeline's research-phase gate to decide whether the stricter
    miniprogram ecosystem check applies.
    """
    if not brief_text:
        return False
    lowered = brief_text.lower()
    return any(sig.lower() in lowered for sig in _MINIPROGRAM_SIGNALS)


def validate_miniprogram_decision_coverage(
    brief_text: str,
    table: ReuseDecisionTable,
) -> ValidationResult:
    """Enforce the T-Bridge miniprogram ecosystem rule.

    When :func:`brief_targets_miniprogram` is True, the reuse table
    must cover the miniprogram ecosystem — at least 2 rows must
    reference a recognised miniprogram library slug (weui-wxss /
    vant-weapp / Lin UI / wx-charts). Researcher agents that list
    none, or only one, get a structured failure here so the pipeline
    can bounce them back into the research phase instead of silently
    shipping a miniprogram that violates the "first find wheels" rule.

    This is layered on top of :func:`validate_research_report` rather
    than baked in, so web/mobile briefs keep their existing behaviour
    unchanged.
    """
    if not brief_targets_miniprogram(brief_text):
        return ValidationResult(is_valid=True, table=table, error=None)

    hits = [
        d
        for d in table.decisions
        if any(slug.lower() in d.candidate.lower() or slug.lower() in d.url.lower()
               for slug in _MINIPROGRAM_LIB_SLUGS)
    ]
    if len(hits) >= 2:
        return ValidationResult(is_valid=True, table=table, error=None)
    return ValidationResult(
        is_valid=False,
        table=table,
        error=(
            f"miniprogram brief detected but the reuse decision table only "
            f"references {len(hits)} known miniprogram library row(s); "
            "T-Bridge requires at least 2 (e.g. weui-wxss + vant-weapp "
            "or Lin UI). See docs/MINIPROGRAM-LIBRARIES.md."
        ),
    )


# ---------------------------------------------------------------------------
# Markdown generation helpers — used by the researcher to be self-consistent
# ---------------------------------------------------------------------------


def render_reuse_table(decisions: Iterable[ReuseDecision]) -> str:
    """Render a :class:`ReuseDecisionTable` back to markdown.

    Primarily useful for tests and for the planner to echo the
    table back into its own output as evidence that it read the
    research report.
    """
    rows = list(decisions)
    if not rows:
        raise ValueError("refusing to render an empty reuse table")
    header = "| 候选 | URL | 成熟度 | 覆盖% | 决策 | 理由 |"
    sep = "|------|-----|--------|-------|------|------|"
    body_lines = [
        f"| {_escape_cell(d.candidate)} | {_escape_cell(d.url)} | {_escape_cell(d.maturity)} | {d.coverage_pct} | {d.decision.value} | {_escape_cell(d.reason)} |"
        for d in rows
    ]
    return "\n".join([header, sep, *body_lines])


def _escape_cell(s: str) -> str:
    """Escape characters that would break a markdown table cell."""
    return s.replace("|", "\\|").replace("\n", " ")
