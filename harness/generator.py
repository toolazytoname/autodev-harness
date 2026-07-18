"""Generator step — single LLM call that writes code in the worktree.

T24 — extracted from inner_loop.py so the generator can be unit-tested
in isolation (mock adapter, fake router) without spinning up a worktree
or reviewer fan-out.

The generator runs in the task worktree using the worker-tier model.
Its prompt includes the spec plus any feedback from previous
iterations (blockers + suggestions). Reviewer transcripts are NEVER
included — only structured feedback, per the design in MASTER-PLAN §2.

Platform-specific guidance (T-Bridge, uni-app era):
``run_generator`` accepts ``task_platform`` and ``agents_dir``; when set,
the matching ``agents/generator-<platform>.md`` file is loaded and
appended to the prompt as a "platform guidance" block. ``resolve_generator_agent``
returns the file stem for the given platform (so callers can pre-load
the prompt or branch on the choice).
"""

from __future__ import annotations

import os
import textwrap
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from harness.adapters.base import AdapterBase, AgentResult
from harness.env import EnvVars, api_key_for
from harness.progress import log_attempt
from harness.router import ModelRouter


# Generator uses a 4-minute ceiling — long enough for a real model to
# write a small feature, short enough that a hung process is detected
# before the orchestrator times out the whole task. Was 300s, then
# 120s in T40; 120 hit the test-mode "todo app" regression. 240s
# matches PHASE_TIMEOUT_SECONDS so worst-case wall-clock is
# predictable. Override: AUTODEV_GENERATOR_TIMEOUT=300 python -m ...
GENERATOR_TIMEOUT_SECONDS = int(os.environ.get("AUTODEV_GENERATOR_TIMEOUT", "240"))


# T-Bridge: map task.platform → agent prompt file stem. The default
# (``"web"``) falls back to the original ``agents/generator.md``.
PLATFORM_GENERATOR_AGENT: dict[str, str] = {
    "web": "generator",
    "miniprogram": "generator-miniprogram",
    "uniapp": "generator-uniapp",
    # ``mobile`` reuses the web generator for now — the prompt covers
    # RN / Flutter patterns well enough for MVP, and the lack of a
    # dedicated mobile generator is documented in MASTER-PLAN T19.
    "mobile": "generator",
}


def resolve_generator_agent(platform: Optional[str]) -> str:
    """Return the agent prompt file stem for *platform*.

    Unknown / ``None`` / empty values fall back to ``"generator"`` so
    existing web callers keep working unchanged. The returned value is
    a filename stem (no ``.md`` extension), suitable for joining with
    ``agents/`` and passing to :func:`harness.prompts._read_agent_prompt`.
    """
    if not platform:
        return "generator"
    return PLATFORM_GENERATOR_AGENT.get(platform, "generator")


def load_platform_guidance(
    agents_dir: Optional[Path], platform: Optional[str]
) -> str:
    """Return the platform-specific guidance block (empty if absent).

    Used by :func:`run_generator` to append the per-platform prompt to
    the generic template. Returning an empty string (instead of erroring)
    when the file is missing keeps a missing file non-fatal — a
    researcher who picked an unknown platform still gets the generic
    generator prompt with no platform-specific steering.
    """
    if not agents_dir or not platform:
        return ""
    stem = resolve_generator_agent(platform)
    if stem == "generator":
        return ""  # default prompt is already in _GENERATOR_PROMPT_TEMPLATE
    path = Path(agents_dir) / f"{stem}.md"
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return ""


# Generator prompt template. Kept at module level (vs inlined in
# run_generator) so a 50-line-function body doesn't bloat — and so
# tests / prompt-engineering iterations don't have to re-import the
# whole generator module to tweak wording.
_GENERATOR_PROMPT_TEMPLATE = textwrap.dedent(
    """\
    You are implementing task: {task_id} — {task_title}

    {task_description}

    ## Product Specification
    {spec}

    {feedback_block}
    ## Your job

    Implement the feature as specified.  Write clean, complete code.
    When done, output a brief summary of what you changed and confirm the implementation
    is complete.

    Important:
    - Do NOT run tests yourself (that is the reviewers' job).
    - Do NOT include reviewer feedback or score card content in your output.
    - Work only in the current directory (the worktree).

    {platform_guidance}
    """
)


@dataclass
class GeneratorOutput:
    """Output from the generator step."""

    stdout: str
    stderr: str
    exit_code: int
    usage: "AgentResult"


def run_generator(
    adapter: AdapterBase,
    router: ModelRouter,
    worktree_path,
    spec_text: str,
    task_id: str,
    task_title: str,
    task_description: Optional[str],
    blockers_from_previous: list[str],
    suggestions_from_previous: list[str],
    iter_num: int,
    task_platform: Optional[str] = None,
    agents_dir: Optional[Path] = None,
) -> GeneratorOutput:
    """Run the generator in the task worktree using the worker-tier model.

    T19 — propagates ``spec.base_url`` and the per-tier API key (read
    from ``AUTODEV_API_KEY_<TIER>``) so worker-tier calls reach the
    configured third-party endpoint instead of the default.

    T-Bridge — ``task_platform`` + ``agents_dir`` thread the platform-
    specific generator prompt through to the worker. ``uniapp`` /
    ``miniprogram`` append their respective ``agents/generator-<x>.md``
    file as a guidance block; ``web`` / ``mobile`` / ``None`` use the
    default template unchanged.
    """
    spec = router.resolve("generate")
    api_key = os.environ.get(api_key_for(spec.tier))
    feedback_block = _format_feedback_block(
        iter_num=iter_num,
        blockers=blockers_from_previous,
        suggestions=suggestions_from_previous,
    )
    platform_guidance = load_platform_guidance(agents_dir, task_platform)
    if platform_guidance:
        platform_guidance = (
            "## Platform-specific guidance\n\n"
            f"Task platform is `{task_platform}` — follow these rules:\n\n"
            f"{platform_guidance}"
        )
    prompt = _GENERATOR_PROMPT_TEMPLATE.format(
        task_id=task_id, task_title=task_title,
        task_description=task_description or "(no description)",
        spec=spec_text, feedback_block=feedback_block,
        platform_guidance=platform_guidance,
    )
    # T40 — log every generator attempt so a hung subprocess is
    # visibly distinct from a silent crash. ``iter_num`` is the
    # current loop iteration; ``total`` is unbounded (capped by
    # MAX_FEEDBACK_ITERATIONS at the caller) so we report the
    # known cap instead of "?"
    log_attempt(
        phase="develop",
        attempt=iter_num,
        total=5,  # matches MAX_FEEDBACK_ITERATIONS in pipeline.py
        target=task_id,
        extra=f"timeout={GENERATOR_TIMEOUT_SECONDS}s platform={task_platform or 'web'}",
    )
    result = adapter.run(
        prompt, model=spec.model, cwd=worktree_path,
        timeout=GENERATOR_TIMEOUT_SECONDS,
        base_url=spec.base_url, api_key=api_key, fallback_model=spec.fallback,
        # Generator actually needs Write/Edit/Bash to materialize the
        # code in the worktree; without these flags, claude -p blocks
        # on a permission prompt that never resolves and the worktree
        # ends up empty — every reviewer then scores 0 for "no source".
        allowed_tools=["Read", "Write", "Edit", "Bash", "Glob", "Grep"],
    )
    return GeneratorOutput(
        stdout=result.stdout, stderr=result.stderr,
        exit_code=result.exit_code, usage=result,
    )


def _format_feedback_block(
    iter_num: int,
    blockers: list[str],
    suggestions: list[str],
) -> str:
    """Return the "Feedback from previous attempt" markdown block.

    Empty on iter 1 (no previous feedback exists yet) and whenever the
    caller passes empty lists (no blockers / no suggestions). Keeping
    this a pure function makes it trivial to assert prompt content in
    unit tests.
    """
    if not blockers and not suggestions:
        return ""
    return textwrap.dedent(
        """
        ## Feedback from previous attempt (iter {iter})

        The following issues were identified.  Please address them in your next attempt.
        Do NOT include reviewer transcripts in your response — only fix the issues.

        ### Blockers (must fix)
        {blockers}

        ### Suggestions (consider fixing)
        {suggestions}
        """
    ).format(
        iter=iter_num,
        blockers="\n".join(f"- {b}" for b in blockers) or "(none)",
        suggestions="\n".join(f"- {s}" for s in suggestions) or "(none)",
    )
