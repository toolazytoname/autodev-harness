"""Prompt assembly helpers (T36 extract from pipeline).

T24 originally placed these in :mod:`harness.pipeline`. T36 hoists
them into a standalone module so :mod:`harness.ui_phase` can import
the prompt builders without going through the full ``Pipeline``
import chain (which had a circular ``pipeline ↔ ui_phase`` cycle
broken with a local import — a smell).

The four functions are the same as before; same signatures, same
underscore-prefixed names. ``harness.pipeline`` re-exports the same
names for back-compat so existing test ``patch("harness.pipeline._read_agent_prompt")``
calls still work.
"""

from __future__ import annotations

from pathlib import Path


class PromptLoadError(FileNotFoundError):
    """Raised when a required prompt or bundled skill is missing.

    A ``PipelineError`` is normally used in pipeline.py — but this
    module has no dependency on Pipeline, so we use the more
    specific exception that callers can catch at the right layer.
    """


def _read_agent_prompt(agents_dir: Path, agent_name: str) -> str:
    """Load an agent's markdown prompt, failing clearly when missing."""
    path = agents_dir / f"{agent_name}.md"
    if not path.exists():
        raise PromptLoadError(f"Agent prompt not found: {path}")
    return path.read_text()


def _read_bundle_skill(bundle_path: Path, *relative_parts: str) -> str:
    """Load one skill from skills-bundle; raises PromptLoadError if missing."""
    path = bundle_path.joinpath(*relative_parts, "SKILL.md")
    if not path.exists():
        raise PromptLoadError(f"Bundled skill missing: {path}")
    return path.read_text()


def _build_prompt(agent_prompt: str, input_text: str) -> str:
    """Append input context to an agent prompt, matching the bash convention."""
    return f"{agent_prompt}\n\n---INPUT---\n{input_text}\n"


def _build_direction_gen_prompt(plan_text: str, n: int = 3) -> str:
    """Build the prompt that asks the LLM for topic-aware design directions.

    T45 — the UI phase now starts with a small LLM call that proposes
    N concrete screen/concept directions tailored to the brief, instead
    of always rendering the same 4 abstract aesthetics. The directions
    keep the harness's existing ``module`` constraint (so the rest of
    the prompt-building pipeline can stay unchanged) and add
    ``intent`` + ``sections`` for downstream use.

    The full template lives in ``harness.open_design`` (where the
    parser / dataclass also live) so the prompt, the parser, and the
    schema are co-located.
    """
    from harness.open_design import DIRECTION_GEN_PROMPT

    return DIRECTION_GEN_PROMPT.format(plan_text=plan_text, N=n)


def _build_ui_prompt(
    base_prompt: str,
    plan_text: str,
    direction: dict[str, str],
    three_piece_text: str,
    style_module_text: str,
) -> str:
    """Assemble a per-direction ui_design prompt.

    The base prompt lives in agents/ui-design.md and tells the model how
    to respond (markers, structure, rules). The directional context
    (PLAN + DIRECTION + STYLE MODULE + 3-PIECE BASELINE + optional
    TOPIC INTENT + KEY SECTIONS) is appended in the order ui-design.md
    expects in its 'Input' section.

    T45 — directions from the new topic-aware step include ``intent``
    and ``sections`` keys. They are emitted as two extra blocks when
    present so the downstream model has the *what* of the screen, not
    only the *aesthetic*. Existing call sites that omit these keys
    keep working unchanged (see ``tests/test_t45_prompts.py``).
    """
    module_block = (
        "---STYLE MODULE PROMPT---\n(none — use only the three-piece baseline)"
        if direction["module"] == "(none)"
        else f"---STYLE MODULE PROMPT---\n{style_module_text}"
    )

    extras: list[str] = []
    intent = direction.get("intent")
    if intent:
        extras.append(f"---TOPIC INTENT---\n{intent}")
    sections = direction.get("sections") or []
    if sections:
        section_lines = "\n".join(f"- {s}" for s in sections)
        extras.append(f"---KEY SECTIONS---\n{section_lines}")
    extras_block = ("\n\n" + "\n\n".join(extras)) if extras else ""

    context = (
        f"---PLAN---\n{plan_text}\n\n"
        f"---AESTHETIC DIRECTION---\n{direction['slug']}\n\n"
        f"{module_block}\n\n"
        f"---THREE-PIECE BASELINE---\n{three_piece_text}{extras_block}"
    )
    return _build_prompt(base_prompt, context)

