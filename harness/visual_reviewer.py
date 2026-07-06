"""Visual reviewer — multimodal UI verification for inner-loop UI tasks.

Per TASKS.md T09: for ``kind: ui`` tasks we take screenshots of the
running app and feed them alongside the spec to a multimodal reviewer,
which returns a score card.

Design notes
------------

- Screenshot capture uses **Playwright** because it is the only tool
  that gives us deterministic, headless, no-network browser control.
  We deliberately avoid the ``browser-use`` CLI: that one is agent-
  driven exploration, perfect for ad-hoc tasks but unstable for the
  inner loop where we want every capture to be reproducible.
- The multimodal attachment pathway goes through
  ``AdapterBase.run_with_attachments``, which the ``ClaudeAdapter``
  overrides to forward files as positional args (the claude CLI's
  documented way to attach images). Other adapters raise
  ``NotImplementedError`` so the visual reviewer fails loudly rather
  than silently dropping the screenshot.
- Screenshots are written to ``score-cards/task-{id}/screenshots/`` per
  the spec; the path becomes the reviewer's ``evidence`` so a human
  debugging a blocker can pull the file up directly.
- Pages to capture come from ``006-ui-spec.md`` by extracting the
  ``## Pages`` / ``## Page`` section and reading lines that look like
  paths (``/foo``, ``about``, etc.). If extraction finds nothing, we
  fall back to a single capture of the root URL.

Caveats written here so they cannot be missed later:

- Headless Chromium does not always render custom fonts identically to
  a real browser. We do **not** treat font rendering as a blocker; we
  block on layout, color, and hierarchy violations only.
- The dev server start probe polls on a deadline rather than sleeping
  blindly, but it is still synchronous: the inner loop will wait.
- The screenshots directory is rewritten every iteration. Old
  screenshots stay in the directory tree but get a stale tag in their
  filename (we keep the iter number in the path) so reviewers and
  humans can compare.
"""

from __future__ import annotations

import re
import socket
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from harness.adapters.base import AdapterBase, AdapterError, AgentResult, Usage
from harness.score_card import (
    ScoreCard,
    ScoreCardParseError,
    parse_score_card,
)
from harness.artifacts import ensure_dir

# ---------------------------------------------------------------------------
# Server probe
# ---------------------------------------------------------------------------


def probe_server(url: str, deadline_seconds: float = 30.0, interval: float = 0.5) -> bool:
    """Return True once the URL responds within ``deadline_seconds``.

    We do a HEAD on the URL's host:port; we deliberately do not page
    through the full route tree because the inner loop cares about
    *liveness*, not correctness of routing.
    """
    if "://" in url:
        scheme, rest = url.split("://", 1)
        host_part = rest.split("/", 1)[0]
    else:
        host_part = url
    if ":" in host_part:
        host, port_str = host_part.split(":", 1)
        port = int(port_str)
    else:
        host = host_part
        port = 443 if scheme == "https" else 80

    start = time.monotonic()
    while time.monotonic() - start < deadline_seconds:
        try:
            with socket.create_connection((host, port), timeout=1.5):
                return True
        except OSError:
            time.sleep(interval)
    return False


# ---------------------------------------------------------------------------
# Spec → page list extraction
# ---------------------------------------------------------------------------

# Lines like:
#   - /pricing
#   - **/blog** - The article index
#   - Home — the marketing landing page
# Below: a small, readable parser broken into explicit steps (the
# previous giant regex misbehaved on edge cases like ``- / — the landing``).

_PAGES_HEADING = re.compile(r"^##\s+pages?\b", re.IGNORECASE)
_END_HEADING = re.compile(r"^##\s+\S")
_BULLET = re.compile(r"^\s*[-*]\s+(?P<body>.+?)\s*$")
_BOLD = re.compile(r"^\*\*(?P<body>.+?)\*\*\s*(?:[-—:]\s*(?P<note>.+))?$")
_LABEL = re.compile(r"^(?P<label>[A-Za-z][A-Za-z0-9_\-]*)(?:\s*[-—:]\s*(?P<note>.+))?$")
_PATH = re.compile(r"^(?P<path>/[A-Za-z0-9_\-./]*)(?:\s*[-—:]\s*(?P<note>.+))?$")
_PAGE_LINE = _PATH  # kept as alias for backward compatibility


def _parse_bullet_body(body: str):
    """Parse one bullet body (after the leading ``- ``) into (label, note)."""
    bold = _BOLD.match(body)
    if bold:
        body_inner = bold.group("body")
        note_from_bold = (bold.group("note") or "").strip()
    else:
        body_inner = body
        note_from_bold = ""

    path_match = _PATH.match(body_inner)
    if path_match:
        return path_match.group("path"), (path_match.group("note") or note_from_bold).strip()

    label_match = _LABEL.match(body_inner)
    if label_match:
        return label_match.group("label"), (label_match.group("note") or note_from_bold).strip()

    return None


def extract_pages_from_spec(spec_text: str) -> list[tuple[str, str]]:
    """Return ``[(path_or_label, note)]`` found in the spec's Pages section.

    Tolerant parser: looks for a ``## Pages`` / ``## Page`` heading and
    reads bulleted lines until the next heading. If no headings are
    found, falls back to scanning every bullet in the whole document.
    """
    if not spec_text:
        return []

    lines = spec_text.splitlines()
    in_pages = False
    out: list[tuple[str, str]] = []
    fallback: list[tuple[str, str]] = []

    for line in lines:
        if _PAGES_HEADING.match(line):
            in_pages = True
            continue
        if in_pages and _END_HEADING.match(line):
            in_pages = False

        bullet = _BULLET.match(line)
        if not bullet:
            continue
        parsed = _parse_bullet_body(bullet.group("body"))
        if parsed is None:
            continue
        if in_pages:
            out.append(parsed)
        else:
            fallback.append(parsed)

    if out:
        return out
    if fallback:
        return fallback[:6]  # cap to keep capture time bounded
    return [("/", "")]


# ---------------------------------------------------------------------------
# Screenshot capture (Playwright)
# ---------------------------------------------------------------------------


@dataclass
class CaptureResult:
    """One captured screenshot."""

    path: Path
    url: str
    note: str
    duration_ms: int


@dataclass
class CaptureReport:
    """Aggregate result of a UI capture pass."""

    pages_requested: list[tuple[str, str]] = field(default_factory=list)
    captures: list[CaptureResult] = field(default_factory=list)
    failures: list[tuple[str, str]] = field(default_factory=list)  # (url, reason)

    @property
    def captured_paths(self) -> list[Path]:
        return [c.path for c in self.captures]


class ScreenshotCapture:
    """Take screenshots of a running app at the spec's URLs.

    The class is stateful enough to keep a single browser process alive
    across calls within an iteration so the first-after-cold-start
    penalty only happens once.
    """

    def __init__(
        self,
        headless: bool = True,
        viewport_width: int = 1280,
        viewport_height: int = 800,
        navigation_timeout_ms: int = 15000,
    ) -> None:
        self.headless = headless
        self.viewport_width = viewport_width
        self.viewport_height = viewport_height
        self.navigation_timeout_ms = navigation_timeout_ms
        self._playwright = None
        self._browser = None

    def __enter__(self) -> "ScreenshotCapture":
        from playwright.sync_api import sync_playwright

        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch(headless=self.headless)
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self._browser is not None:
            self._browser.close()
        if self._playwright is not None:
            self._playwright.stop()
        self._browser = None
        self._playwright = None

    def capture_pages(
        self,
        base_url: str,
        pages: list[tuple[str, str]],
        out_dir: Path,
    ) -> CaptureReport:
        """Open each page in the spec and write a screenshot to ``out_dir``.

        Filename pattern: ``{idx:02d}-{slug}.png`` where ``slug`` is a
        path-safe form of the path/label.
        """
        out_dir.mkdir(parents=True, exist_ok=True)
        report = CaptureReport(pages_requested=list(pages))

        if self._browser is None:
            raise RuntimeError(
                "ScreenshotCapture must be used as a context manager "
                "(`with ScreenshotCapture() as cap: ...`)."
            )

        context = self._browser.new_context(
            viewport={"width": self.viewport_width, "height": self.viewport_height},
            device_scale_factor=2,
        )

        for idx, (path, note) in enumerate(pages):
            url = base_url.rstrip("/") + ("/" if not path.startswith("/") else "") + path.lstrip("/")
            slug = re.sub(r"[^A-Za-z0-9_-]+", "_", path.strip("/") or "root")[:48]
            slug = f"{idx:02d}-{slug or 'root'}.png"
            target = out_dir / slug
            start = time.monotonic()
            try:
                page = context.new_page()
                page.goto(url, timeout=self.navigation_timeout_ms, wait_until="networkidle")
                # Wait for fonts to settle so the screenshot is fair
                page.evaluate("document.fonts ? document.fonts.ready : Promise.resolve()")
                page.screenshot(path=str(target), full_page=True)
                page.close()
                elapsed = int((time.monotonic() - start) * 1000)
                report.captures.append(
                    CaptureResult(path=target, url=url, note=note, duration_ms=elapsed)
                )
            except Exception as exc:
                report.failures.append((url, f"{type(exc).__name__}: {exc}"))
                try:
                    page.close()  # type: ignore[possibly-undefined]
                except Exception:
                    pass

        context.close()
        return report


def capture_with_fallback(
    base_url: str,
    pages: list[tuple[str, str]],
    out_dir: Path,
    **capture_kwargs,
) -> CaptureReport:
    """Try Playwright first, fall back to a stub report on ImportError.

    The fallback is *not* a real screenshot — it returns an empty
    report with the pages list preserved, so the reviewer knows no
    images were captured. This is deliberate: a transparent "no
    screenshots" is better than a fake one.
    """
    try:
        with ScreenshotCapture(**capture_kwargs) as cap:
            return cap.capture_pages(base_url, pages, out_dir)
    except ImportError as exc:
        return CaptureReport(
            pages_requested=list(pages),
            failures=[(base_url, f"playwright unavailable: {exc}")],
        )


# ---------------------------------------------------------------------------
# Multimodal review orchestration
# ---------------------------------------------------------------------------


def run_visual_review(
    adapter: AdapterBase,
    *,
    model: str,
    spec_text: str,
    diff_text: str,
    changed_files: list[str],
    screenshots: list[Path],
    worktree_path: Path,
    iter_num: int,
    reviewer_prompt: Path,
    timeout: int = 180,
) -> ScoreCard:
    """Run the multimodal visual reviewer and return its score card.

    The reviewer prompt (``agents/reviewers/visual.md``) is loaded from
    disk, the screenshot paths are appended as a ``## Screenshots``
    block, and the whole prompt + attachments are sent through
    ``adapter.run_with_attachments``. JSON score card is parsed and
    returned; on parse failure a 0.0-score card with the parser error
    in ``evidence`` is returned so the inner loop can still gate.
    """
    base_prompt = reviewer_prompt.read_text() if reviewer_prompt.exists() else ""

    screenshot_block_lines = ["## Screenshots (in order attached)"]
    if screenshots:
        for i, p in enumerate(screenshots, start=1):
            screenshot_block_lines.append(f"{i}. `{p}`")
    else:
        screenshot_block_lines.append("(none captured — review based on diff only)")

    context_block = (
        "\n\n".join(
            [
                "## Spec\n" + (spec_text or "(no spec)"),
                "## Diff since main\n" + (diff_text or "(no diff)"),
                "## Changed files\n"
                + ("\n".join(f"- {f}" for f in changed_files) or "(none)"),
                "\n".join(screenshot_block_lines),
                "## Iteration\n" + str(iter_num),
            ]
        )
    )

    prompt = base_prompt + "\n\n" + context_block + (
        "\n\nOutput ONLY the JSON score card at the end of your reply."
    )

    try:
        result: AgentResult = adapter.run_with_attachments(
            prompt,
            screenshots,
            model=model,
            cwd=worktree_path,
            timeout=timeout,
        )
    except (NotImplementedError, AdapterError) as exc:
        return ScoreCard(
            iter=iter_num,
            reviewer="visual",
            score=0.0,
            blockers=[f"Visual reviewer unavailable: {exc}"],
            suggestions=[],
            evidence=f"adapter {type(adapter).__name__} could not run multimodal review",
        )

    raw = result.stdout or ""
    # Strip markdown fences if present; fall back to brace extraction
    from harness.score_card import extract_json_from_fenced

    cleaned = extract_json_from_fenced(raw)
    try:
        card = parse_score_card(cleaned)
    except ScoreCardParseError as exc:
        # Try the whole raw stdout as a last resort
        try:
            card = parse_score_card(raw)
        except ScoreCardParseError:
            evidence_files = ", ".join(str(p) for p in screenshots)
            return ScoreCard(
                iter=iter_num,
                reviewer="visual",
                score=0.0,
                blockers=[f"Visual reviewer returned unparseable JSON: {exc.cause}"],
                suggestions=[],
                evidence=(
                    f"raw truncated: {raw[:400]}; "
                    f"screenshots: {evidence_files}"
                ),
            )

    # Normalise iter + reviewer. The model may forget to set them or set
    # the wrong number; we always pin iter to the iteration we called for
    # so the inner loop's gate logic keys on a stable identifier.
    return ScoreCard(
        iter=iter_num,
        reviewer="visual",
        score=card.score,
        blockers=card.blockers,
        suggestions=card.suggestions,
        evidence=card.evidence,
    )


def screenshots_dir_for(project_dir: Path, task_id: str) -> Path:
    """Return the canonical screenshots directory for a task."""
    norm = task_id.removeprefix("task-")
    return project_dir / "score-cards" / f"task-{norm}" / "screenshots"
