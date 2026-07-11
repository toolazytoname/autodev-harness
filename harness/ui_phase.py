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

from concurrent.futures import ThreadPoolExecutor, as_completed

from harness.artifacts import write_artifact
from harness.adapters.base import AdapterError
from harness.env import EnvVars
from harness.open_design import (
    Direction,
    parse_direction_list,
)
from harness.pipeline_base import PipelineError, _is_interactive
# Imported at module scope (instead of inside _generate_topic_directions)
# so tests can ``patch.object(ui_phase, "_build_direction_gen_prompt", ...)``
# to short-circuit the LLM call and assert on the parser wiring.
from harness.prompts import _build_direction_gen_prompt  # noqa: E402,F401
from harness.pipeline import UI_DIRECTIONS  # noqa: E402,F401  (T45 fallback list)


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
        """Run the full UI phase: derive topic-aware directions → render all
        in parallel → human pick loop → finalize."""
        self._log("━━━ Phase: ui_design (topic-aware directions) ━━━")
        if plan_text is None:
            raise PipelineError("002-plan.md not found — run plan first")

        versions_dir = self._project_dir / "preview" / "versions"
        versions_dir.mkdir(parents=True, exist_ok=True)

        # T45 — topic-aware direction set: an LLM proposes N directions
        # tailored to this brief (concrete screens / views of the
        # product). Falls back to the canonical ``UI_DIRECTIONS`` list
        # when the LLM call or its parser fails — see
        # ``_generate_topic_directions`` for the failure modes.
        n = self._resolve_direction_count()
        ordered = self._generate_topic_directions(plan_text, n=n)
        self._log(
            f"Directions ({len(ordered)}, recommended first): "
            f"{[d['slug'] if isinstance(d, dict) else d.slug for d in ordered]}"
        )

        versions = self._render_all_directions(
            ordered, plan_text, previous_spec="", user_feedback=""
        )
        self._run_slop_check(versions)
        return self._human_pick_loop(ordered, plan_text, versions, versions_dir)

    # ------------------------------------------------------------------
    # Direction generation
    # ------------------------------------------------------------------

    def _resolve_direction_count(self) -> int:
        """Resolve the N for topic-aware generation.

        Honors ``AUTODEV_UI_DIRECTION_COUNT`` (env override); defaults
        to 3 (the plan-time default — T45 chose 3 over the historical
        4 because the new directions are more specific and 3 is enough
        for a meaningful comparison)."""
        try:
            raw = os.environ.get(EnvVars.UI_DIRECTION_COUNT, "").strip()
            return int(raw) if raw else 3
        except ValueError:
            return 3

    def _generate_topic_directions(
        self, plan_text: str, n: int
    ) -> list[dict[str, str]]:
        """LLM-driven topic-aware direction list. Falls back to the
        hardcoded ``UI_DIRECTIONS`` on any failure.

        Returns the same ``dict`` shape the legacy 4-direction path
        used so the rest of the UI phase (render, prompt-build,
        slop-check, finalize) keeps working unchanged. ``Direction``
        rows from the new parser carry extra ``intent``/``sections``
        keys which ``_build_ui_prompt`` slots into the model prompt.
        """
        try:
            prompt = _build_direction_gen_prompt(plan_text, n=n)
            result = self._p._adapter.run(
                prompt,
                # The direction-gen step uses whatever the pipeline's
                # main adapter resolves to — typically a small worker
                # model (cheap, fast).
                model="haiku-4-5",
                cwd=self._project_dir,
                timeout=120,
            )
            directions = parse_direction_list(result.stdout)
            return [d.to_dict() for d in directions]
        except Exception as exc:
            # Any failure mode (LLM error, parse error, empty output)
            # falls back to the canonical list. Keeps a stale or
            # misconfigured model from breaking the UI phase.
            self._log(
                f"  topic dirs: LLM failed ({exc!r}); falling back to "
                f"hardcoded {len(UI_DIRECTIONS)} directions"
            )
            return list(UI_DIRECTIONS)

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

        result = self._p._ui_adapter.run(
            prompt,
            model=spec.model,
            cwd=self._project_dir,
            timeout=PHASE_TIMEOUT_SECONDS,
            base_url=spec.base_url,
            api_key=self._p._api_key_for(spec.tier),
            fallback_model=spec.fallback,
            # UI spec generation writes a markdown spec to stdout and
            # the harness captures it. We allow Write too so the agent
            # can save preview HTML directly into preview/versions/
            # without going through permission prompts.
            allowed_tools=["Read", "Write", "Glob", "Grep"],
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
        """Render every direction in parallel; on per-direction failure,
        fall back to ``self._p._adapter`` (the main stage adapter).

        T45 — the topic-aware direction list is rendered with the
        ``_ui_adapter`` (Open Design when available; Claude otherwise)
        and any single failure (daemon unreachable / run failed-canceled
        / poll budget exhausted) is recovered by retrying the same
        direction with the main adapter, so the UI phase never silently
        drops a direction.

        Order of results mirrors the input direction list — the human
        pick loop indexes by position.
        """
        # Pre-create version directories so on disk they show up even
        # before the parallel calls complete.
        for direction in directions:
            dir_path = self._project_dir / "preview" / "versions" / direction["slug"]
            dir_path.mkdir(parents=True, exist_ok=True)

        # Map future → (direction, attempt_path) so we can place each
        # result back into the same position as its source direction.
        results_by_index: dict[int, tuple[dict[str, str], str, str]] = {}

        def _render(index: int, direction: dict[str, str]) -> tuple[dict[str, str], str, str]:
            """Try ``_ui_adapter`` first; on AdapterError, fall back to
            the main adapter. Any other failure (PipelineError, OS
            error) propagates so the caller can surface it."""
            self._log(f"  rendering direction: {direction['slug']}")
            try:
                result = self._p._call_ui_direction(
                    direction,
                    plan_text,
                    previous_spec=previous_spec,
                    user_feedback=user_feedback,
                )
                spec_md, html = extract_ui_output(result.stdout)
            except AdapterError as exc:
                # OD specifically failed for this direction — fall back
                # to the main adapter with the same prompt.
                self._log(
                    f"    direction {direction['slug']} failed on _ui_adapter "
                    f"({exc!r}); retrying via _adapter"
                )
                try:
                    # Rebuild the same prompt out of band. We can't
                    # reach into _call_ui_direction's internals here, so
                    # just call _adapter.run with a minimal "design
                    # this direction" prompt — the same one _call_ui_direction
                    # would build. Keeping the fallback lightweight
                    # means a single OD hiccup doesn't double the run
                    # time per direction.
                    from harness.pipeline import (
                        PHASE_SPECS,
                        PHASE_TIMEOUT_SECONDS,
                        _build_ui_prompt,
                    )
                    from harness.artifacts import Phase

                    ui_spec = PHASE_SPECS[Phase.UI]
                    stage = ui_spec.stage
                    spec = self._p._router.resolve(stage)
                    three_piece = self._p._load_three_piece_baseline()
                    style_module = self._p._load_style_module(direction["module"])
                    agent_prompt = self._read_ui_agent_prompt(ui_spec.agent)
                    prompt = _build_ui_prompt(
                        base_prompt=agent_prompt,
                        plan_text=plan_text,
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
                        allowed_tools=["Read", "Write", "Glob", "Grep"],
                    )
                    spec_md, html = extract_ui_output(result.stdout)
                except Exception as inner_exc:
                    self._log(
                        f"    direction {direction['slug']} fallback also failed: {inner_exc!r}"
                    )
                    spec_md, html = "", ""
            except Exception as exc:
                # ``PipelineError`` from the harness, OS errors, etc.
                self._log(f"    direction {direction['slug']} failed: {exc}")
                spec_md, html = "", ""
            return direction, spec_md, html

        # Render all directions concurrently. ``ThreadPoolExecutor``
        # is the harness's standard fan-out pattern (see
        # ``harness.reviewer_runner`` for the canonical template).
        max_workers = max(1, len(directions))
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            future_to_index = {
                pool.submit(_render, i, d): i
                for i, d in enumerate(directions)
            }
            for future in as_completed(future_to_index):
                idx = future_to_index[future]
                try:
                    results_by_index[idx] = future.result()
                except Exception as exc:
                    direction = directions[idx]
                    self._log(
                        f"    direction {direction['slug']} crashed: {exc!r}"
                    )
                    results_by_index[idx] = (direction, "", "")

        # Persist + return in original order.
        rendered: list[tuple[dict[str, str], str, str]] = []
        for idx, direction in enumerate(directions):
            d, spec_md, html = results_by_index.get(
                idx, (direction, "", "")
            )
            dir_path = self._project_dir / "preview" / "versions" / d["slug"]
            (dir_path / "index.html").write_text(
                html or "<!DOCTYPE html><!-- empty -->\n"
            )
            (dir_path / "spec.md").write_text(spec_md or "")
            rendered.append((d, spec_md, html))
        return rendered

    def _read_ui_agent_prompt(self, agent_name: str) -> str:
        """Read agents/<name>.md via the pipeline's ``_agents_dir``.

        Mirrors what ``Pipeline._load_three_piece_baseline`` does for
        style module text so the fallback path stays consistent.
        """
        from harness.prompts import _read_agent_prompt

        return _read_agent_prompt(self._p._agents_dir, agent_name)

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
