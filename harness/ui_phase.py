"""UI design phase — extracted from pipeline.phase_ui.

T24 — split pipeline.py (was 991 lines) so the UI phase is
self-contained and unit-testable. Responsibilities here:

  - ``pick_directions_for_brief`` — choose the 4 aesthetic directions
  - ``extract_ui_output``        — split the agent's output into spec + html
  - ``UIPhase``                  — the render → pick → refine loop

``UIPhase`` borrows the shared infrastructure from its owning
``Pipeline`` (router, adapter, agent prompts, three-piece baseline,
style modules, consumed-feedback set, env-key lookup). This keeps the
shared state in one place while moving the UI-specific decision
machinery out of ``pipeline.py``.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Optional

from harness.artifacts import write_artifact
from harness.env import EnvVars
from harness.pipeline_base import PipelineError, _is_interactive


# Brief-keyword → direction-slug picker. First match wins; if no
# keyword matches, fall back to premium-default. The human can
# override via the AUTODEV_UI_DIRECTION env var (a single slug) at
# any time. Patterns must reference slugs in pipeline.UI_DIRECTIONS
# — keep the two tables in sync.
_DIRECTION_KEYWORDS: list[tuple[str, str]] = [
    (r"dashboard|metric|chart|log|admin|observab|trading|inventory",
     "data-dense-industrial"),
    (r"landing|launch|portfolio|marketing|hero|homepage|brand",
     "high-end-motion"),
    (r"docs?|wiki|blog|linear[-\s]?like|notion[-\s]?like|note|writing",
     "editorial-minimal"),
]
import re as _re_module  # local alias; re is stdlib so this is free
_DIRECTION_KEYWORD_PATTERNS = [
    (_re_module.compile(pattern, _re_module.IGNORECASE), slug)
    for pattern, slug in _DIRECTION_KEYWORDS
]


def pick_directions_for_brief(plan_text: str) -> list[dict[str, str]]:
    """Choose which set of 4 aesthetic directions to render this pass.

    Always returns all four. The first slot is the *recommended* one
    (based on brief keywords); the remaining three rotate in a fixed
    order so the human can compare. An explicit
    ``AUTODEV_UI_DIRECTION`` env var forces the recommended slot to a
    specific slug instead.
    """
    # Imported here to avoid a circular import with pipeline.py
    from harness.pipeline import UI_DIRECTIONS

    explicit = os.environ.get(EnvVars.UI_DIRECTION, "").strip()
    recommended_slug = next(
        (d["slug"] for d in UI_DIRECTIONS if d["slug"] == explicit),
        None,
    )
    if recommended_slug is None:
        for pattern, slug in _DIRECTION_KEYWORD_PATTERNS:
            if pattern.search(plan_text):
                recommended_slug = slug
                break
    if recommended_slug is None:
        recommended_slug = "premium-default"

    by_slug = {d["slug"]: d for d in UI_DIRECTIONS}
    ordered: list[dict[str, str]] = [by_slug[recommended_slug]]
    for d in UI_DIRECTIONS:
        if d["slug"] != recommended_slug:
            ordered.append(d)
    return ordered


def extract_ui_output(raw: str) -> tuple[str, str]:
    """Split ui-design agent output into (spec_markdown, html).

    Supports the ---SPEC--- / ---HTML--- / ---END--- marker convention and
    falls back to ```html fences (same logic as the bash extract_html).
    Returns ("", raw) when no HTML section can be identified — the caller
    decides whether that is acceptable.
    """
    text = raw.strip()
    if not text:
        return "", ""

    lines = text.splitlines()

    def _find(marker: str) -> Optional[int]:
        for i, line in enumerate(lines):
            if line.strip() == marker:
                return i
        return None

    spec_i = _find("---SPEC---")
    html_i = _find("---HTML---")
    end_i = _find("---END---")

    if html_i is not None:
        spec = "\n".join(lines[spec_i + 1 : html_i]) if spec_i is not None else ""
        html_end = end_i if end_i is not None and end_i > html_i else len(lines)
        html = "\n".join(lines[html_i + 1 : html_end])
        return spec.strip(), html.strip()

    # Fallback: fenced html block
    fence_start = None
    for i, line in enumerate(lines):
        if line.strip().startswith("```html"):
            fence_start = i
            break
    if fence_start is not None:
        for j in range(fence_start + 1, len(lines)):
            if lines[j].strip() == "```":
                spec = "\n".join(lines[:fence_start]).strip()
                html = "\n".join(lines[fence_start + 1 : j]).strip()
                return spec, html

    return "", text


# Re-exported constants (kept here so the rest of the module doesn't
# reach back into pipeline.py at import time)
MAX_FEEDBACK_ITERATIONS = 3


class UIPhase:
    """The UI phase's render → pick → refine loop.

    Owns nothing — borrows router, adapter, prompts, and feedback-
    consumption state from the owning ``Pipeline``. The split keeps
    the UI logic testable in isolation (a fake ``Pipeline`` that
    exposes the same surface works as a stub) while preserving the
    single source of truth for shared state.
    """

    def __init__(self, pipeline) -> None:
        # Type hint omitted to dodge the circular import with pipeline.py.
        # ``pipeline`` must expose: _config, _router, _adapter,
        # _call_ui_direction, _run_slop_check, _load_three_piece_baseline,
        # _load_style_module, _log, _consumed_feedback.
        self._p = pipeline

    def __getattr__(self, name: str):
        # T24 — let the wrapper transparently forward any shared
        # helper that lives on the owning Pipeline. Keeps UIPhase.run
        # readable (``self._render_all_directions(...)`` reads better
        # than ``self._p._render_all_directions(...)``) without
        # having to add a delegating method for every shared helper
        # (_call_ui_direction, _run_slop_check, _ask_version_choice).
        # Real attributes (``_p``, methods defined on UIPhase) resolve
        # normally; this hook only fires for missing ones.
        if name.startswith("_") and not name.startswith("__"):
            try:
                return getattr(self._p, name)
            except AttributeError:
                pass
        raise AttributeError(name)

    # ------------------------------------------------------------------
    # Public entry — equivalent to pipeline.phase_ui
    # ------------------------------------------------------------------

    def run(self, plan_text: str) -> Path:
        """Run the full UI phase: render 4 → human pick loop → finalize."""
        self._log("━━━ Phase: ui_design (4 aesthetic directions) ━━━")
        if plan_text is None:
            raise PipelineError("002-plan.md not found — run plan first")

        versions_dir = self._project_dir / "preview" / "versions"
        versions_dir.mkdir(parents=True, exist_ok=True)

        ordered = pick_directions_for_brief(plan_text)
        self._log(f"Directions (recommended first): {[d['slug'] for d in ordered]}")

        versions = self._render_all_directions(
            ordered, plan_text, previous_spec="", user_feedback=""
        )
        self._run_slop_check(versions)
        return self._human_pick_loop(ordered, plan_text, versions, versions_dir)

    def _human_pick_loop(
        self,
        ordered: list[dict[str, str]],
        plan_text: str,
        versions: list[tuple[dict[str, str], str, str]],
        versions_dir: Path,
    ) -> Path:
        """Run the human pick loop: list → ask → refine / regenerate.

        Up to ``MAX_FEEDBACK_ITERATIONS`` rounds. Falls back to the
        recommended direction at the end (the ``accept_first`` path
        is what ``_ask_version_choice`` returns on non-TTY runs).
        """
        for _iteration in range(1, MAX_FEEDBACK_ITERATIONS + 1):
            self._log("━ UI versions ━")
            for idx, (direction, _spec_md, _html) in enumerate(versions, start=1):
                path = versions_dir / direction["slug"] / "index.html"
                self._log(f"  [{idx}] {direction['label']}  →  file://{path}")

            choice, feedback = self._ask_version_choice(len(versions))
            if choice == "accept_first":
                return self._finalize_version(versions[0], versions_dir)
            if choice.isdigit():
                idx = int(choice) - 1
                if not (0 <= idx < len(versions)):
                    feedback = choice  # treat as textual feedback
                else:
                    versions[idx] = self._refine_version(
                        versions[idx],
                        plan_text,
                        previous_spec=versions[idx][1],
                        user_feedback=feedback,
                    )
                    continue

            # Free-form feedback → regenerate all 4 with the feedback appended
            versions = self._render_all_directions(
                ordered,
                plan_text,
                previous_spec=versions[0][1],
                user_feedback=feedback,
            )

        self._log(
            f"Max feedback iterations ({MAX_FEEDBACK_ITERATIONS}) reached, "
            "falling back to recommended direction"
        )
        return self._finalize_version(versions[0], versions_dir)

    # ------------------------------------------------------------------
    # Direction rendering
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # Per-direction call (borrows router + adapter + skills_bundle)
    # ------------------------------------------------------------------

    def _call_ui_direction(
        self,
        direction: dict[str, str],
        plan_text: str,
        previous_spec: str = "",
        user_feedback: str = "",
    ) -> AgentResult:
        """Run the ui_design agent for one specific aesthetic direction."""
        from harness.artifacts import Phase
        from harness.pipeline import (
            PHASE_SPECS,
            PHASE_TIMEOUT_SECONDS,
            _build_ui_prompt,
            _read_agent_prompt,
        )

        ui_spec = PHASE_SPECS[Phase.UI]
        if ui_spec.stage is None or ui_spec.agent is None:
            raise RuntimeError("UI phase spec is missing stage/agent metadata")
        stage = ui_spec.stage
        spec = self._p._router.resolve(stage)
        agent_prompt = _read_agent_prompt(self._p._agents_dir, ui_spec.agent)
        three_piece = self._p._load_three_piece_baseline()
        style_module = self._p._load_style_module(direction["module"])

        context_extra = ""
        if previous_spec:
            context_extra += f"\n\n---PREVIOUS SPEC---\n{previous_spec}"
        if user_feedback:
            context_extra += f"\n\n---USER FEEDBACK---\n{user_feedback}"

        prompt = _build_ui_prompt(
            base_prompt=agent_prompt,
            plan_text=plan_text + context_extra,
            direction=direction,
            three_piece_text=three_piece,
            style_module_text=style_module,
        )

        result = self._p._adapter.run(
            prompt,
            model=spec.model,
            cwd=self._project_dir,
            timeout=PHASE_TIMEOUT_SECONDS,
            base_url=spec.base_url,
            api_key=self._p._api_key_for(spec.tier),
            fallback_model=spec.fallback,
        )
        self._p._router.record(stage, result.usage)
        return result

    def _run_slop_check(self, versions):
        """Print the slop check report for every rendered direction.

        Non-blocking: warnings/blockers are logged so the human sees
        the diagnostics, but we still let the pipeline proceed — T09
        ``visual`` reviewer will block in the inner loop if needed.
        """
        from harness.slop_check import SlopValidator, load_rules

        repo_root = Path(__file__).parent.parent.parent
        rules_path = repo_root / "config" / "slop_rules.yaml"
        validator = (
            SlopValidator(rules=load_rules(rules_path))
            if rules_path.exists()
            else SlopValidator()
        )
        versions_dir = self._project_dir / "preview" / "versions"
        for direction, _spec, _html in versions:
            self._log(f"  slop check: {direction['slug']}")
            for artifact_name in ("index.html", "spec.md"):
                artifact = versions_dir / direction["slug"] / artifact_name
                if not artifact.exists():
                    continue
                result = validator.validate_file(artifact)
                for line in result.render().splitlines():
                    self._log(f"    {line}")
                if not result.passed:
                    self._log(
                        f"    → {direction['slug']}/{artifact_name} has {len(result.blockers)} "
                        "slop blocker(s); T09 visual reviewer will gate."
                    )

    def _render_all_directions(
        self,
        directions: list[dict[str, str]],
        plan_text: str,
        previous_spec: str,
        user_feedback: str,
    ) -> list[tuple[dict[str, str], str, str]]:
        """Render every aesthetic direction in ``directions`` and persist them."""
        rendered: list[tuple[dict[str, str], str, str]] = []
        for direction in directions:
            self._log(f"  rendering direction: {direction['slug']}")
            try:
                result = self._p._call_ui_direction(
                    direction,
                    plan_text,
                    previous_spec=previous_spec,
                    user_feedback=user_feedback,
                )
                spec_md, html = extract_ui_output(result.stdout)
            except PipelineError as exc:
                self._log(f"    direction {direction['slug']} failed: {exc}")
                spec_md, html = "", ""

            dir_path = self._project_dir / "preview" / "versions" / direction["slug"]
            dir_path.mkdir(parents=True, exist_ok=True)
            (dir_path / "index.html").write_text(html or "<!DOCTYPE html><!-- empty -->\n")
            (dir_path / "spec.md").write_text(spec_md or "")
            rendered.append((direction, spec_md, html))
        return rendered

    def _refine_version(
        self,
        version: tuple[dict[str, str], str, str],
        plan_text: str,
        previous_spec: str,
        user_feedback: str,
    ) -> tuple[dict[str, str], str, str]:
        """Re-run one direction with feedback (no other directions affected)."""
        direction = version[0]
        result = self._p._call_ui_direction(
            direction,
            plan_text,
            previous_spec=previous_spec,
            user_feedback=user_feedback,
        )
        spec_md, html = extract_ui_output(result.stdout)
        dir_path = self._project_dir / "preview" / "versions" / direction["slug"]
        dir_path.mkdir(parents=True, exist_ok=True)
        (dir_path / "index.html").write_text(html)
        (dir_path / "spec.md").write_text(spec_md)
        self._log(f"  regenerated: {direction['slug']}")
        return (direction, spec_md, html)

    def _finalize_version(
        self,
        winner: tuple[dict[str, str], str, str],
        versions_dir: Path,
    ) -> Path:
        """Copy the chosen version's spec+html into the canonical artifacts."""
        direction, spec_md, html = winner
        canonical_html = self._project_dir / "preview" / "index.html"
        canonical_html.parent.mkdir(parents=True, exist_ok=True)
        canonical_html.write_text(html)
        spec_path = write_artifact(
            self._project_dir, "006-ui-spec", spec_md
        )
        self._log(f"Picked {direction['label']} → {spec_path}")
        return spec_path

    # ------------------------------------------------------------------
    # Human-in-the-loop prompts
    # ------------------------------------------------------------------

    def _ask_version_choice(self, num_versions: int) -> tuple[str, str]:
        """Prompt the human for a version choice.

        Returns ``(choice, feedback)``. ``choice`` is one of:
          - ``"accept_first"`` — accept whichever is at position 1
          - ``"1"`` / ``"2"`` / ... — pick that version (feedback ignored)
          - any other string — treat as free-form feedback text
        In non-TTY runs reads ``AUTODEV_UI_CHOICE`` (1-4) or
        ``AUTODEV_UI_FEEDBACK`` (free-form text).
        """
        env_choice = os.environ.get(EnvVars.UI_CHOICE, "").strip()
        env_feedback = os.environ.get(EnvVars.UI_FEEDBACK, "")

        if not _is_interactive():
            # T23: consumption is instance-scoped; env vars themselves
            # stay untouched so other Pipelines / tests see a clean env.
            consumed = self._p._consumed_feedback
            if env_choice and EnvVars.UI_CHOICE not in consumed:
                consumed.add(EnvVars.UI_CHOICE)
                return env_choice, ""
            if env_feedback and EnvVars.UI_FEEDBACK not in consumed:
                consumed.add(EnvVars.UI_FEEDBACK)
                return "", env_feedback
            # No env set — auto-accept the recommended slot
            return "accept_first", ""

        prompt = (
            f"Choose 1-{num_versions}, type feedback to regenerate all, "
            "or press Enter to accept #1: "
        )
        try:
            raw = input(prompt).strip()
        except EOFError:
            return "accept_first", ""
        if not raw:
            return "accept_first", ""
        if raw in {str(i) for i in range(1, num_versions + 1)}:
            return raw, ""
        return "", raw

    # ------------------------------------------------------------------
    # Borrowed-state shims
    # ------------------------------------------------------------------

    @property
    def _project_dir(self) -> Path:
        return self._p._config.project_dir

    def _log(self, msg: str) -> None:
        self._p._log(msg)
