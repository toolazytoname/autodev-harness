"""Generator step — single LLM call that writes code in the worktree.

T24 — extracted from inner_loop.py so the generator can be unit-tested
in isolation (mock adapter, fake router) without spinning up a worktree
or reviewer fan-out.

The generator runs in the task worktree using the worker-tier model.
Its prompt includes the spec plus any feedback from previous
iterations (blockers + suggestions). Reviewer transcripts are NEVER
included — only structured feedback, per the design in MASTER-PLAN §2.
"""

from __future__ import annotations

import os
import textwrap
from dataclasses import dataclass
from typing import Optional

from harness.adapters.base import AdapterBase, AgentResult
from harness.env import EnvVars, api_key_for
from harness.router import ModelRouter


# Generator uses a 5-minute ceiling — long enough for a real model to
# write a small feature, short enough that a hung process is detected
# before the orchestrator times out the whole task.
GENERATOR_TIMEOUT_SECONDS = 300


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
) -> GeneratorOutput:
    """Run the generator in the task worktree using the worker-tier model.

    T19 — propagates ``spec.base_url`` and the per-tier API key (read
    from ``AUTODEV_API_KEY_<TIER>``) so worker-tier calls reach the
    configured third-party endpoint instead of the default.
    """
    spec = router.resolve("generate")
    api_key = os.environ.get(api_key_for(spec.tier))
    feedback_block = _format_feedback_block(
        iter_num=iter_num,
        blockers=blockers_from_previous,
        suggestions=suggestions_from_previous,
    )
    prompt = _GENERATOR_PROMPT_TEMPLATE.format(
        task_id=task_id, task_title=task_title,
        task_description=task_description or "(no description)",
        spec=spec_text, feedback_block=feedback_block,
    )
    result = adapter.run(
        prompt, model=spec.model, cwd=worktree_path,
        timeout=GENERATOR_TIMEOUT_SECONDS,
        base_url=spec.base_url, api_key=api_key, fallback_model=spec.fallback,
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
