"""Task acceptance helpers — turn human-written acceptance steps into
executable form for the test reviewer.

Per TASKS T11 / MASTER-PLAN §3 (P3): every task in 003-task-queue.json
must have an ``acceptance`` field listing the user-flow steps that prove
the task is done. The test reviewer is supposed to be able to convert
each step into a runnable command (or browser-use action) — this module
is the small bridge that does that conversion explicitly so the harness
itself can validate the conversion is sane.

The class is intentionally pure: it does not run any commands. It just
parses the acceptance list, classifies each step, and produces a list
of :class:`AcceptanceStep` records the inner loop can dispatch to the
right executor (shell / browser-use / pytest).
"""

from __future__ import annotations

import re
from enum import Enum
from typing import Iterable, Optional

import pydantic


class StepKind(str, Enum):
    """How an acceptance step is meant to be executed."""

    # A shell command the test reviewer runs and inspects exit code + output.
    SHELL = "shell"
    # A HTTP request: tester hits a URL and asserts on status / body.
    HTTP = "http"
    # A user-flow step for browser-use: visit / click / type / assert.
    BROWSER = "browser"
    # A unit-test invocation: a pytest node id or `pytest -k` query.
    PYTEST = "pytest"
    # Plain text assertion (no automatic execution path) — reviewer
    # judges manually.
    ASSERT = "assert"


_SHELL_PREFIXES = ("$ ", "! ", "run ", "sh ", "bash ", "shell> ")
_HTTP_PREFIXES = ("GET ", "POST ", "PUT ", "DELETE ", "PATCH ", "http://", "https://")
_PYTEST_PREFIXES = ("pytest ", "pytest::", "tests/", "test_")
_BROWSER_KEYWORDS = (
    "click", "visit", "navigate", "type", "fill", "submit",
    "see ", "expect ", "verify ", "assert ", "should ",
    "登录", "点击", "打开", "输入", "提交", "看到", "检查",
)


class AcceptanceStep(pydantic.BaseModel):
    """A single executable step derived from a task's acceptance field."""

    model_config = pydantic.ConfigDict(frozen=True)

    raw: str
    kind: StepKind
    # The extracted command (for SHELL / PYTEST) or URL (for HTTP).
    # Empty string when not applicable (e.g. ASSERT / most BROWSER steps).
    payload: str = ""
    # If true, the step is mandatory — failing it is a blocker.
    # Optional steps are nice-to-have and produce suggestions instead.
    required: bool = True


def classify_step(raw: str) -> AcceptanceStep:
    """Map a free-form acceptance string to an :class:`AcceptanceStep`.

    Heuristics, in priority order:
    1. Lines starting with ``$`` or ``!`` (shell) → SHELL.
    2. Lines starting with an HTTP verb or ``http(s)://`` → HTTP.
    3. Lines starting with ``pytest``, ``tests/`` etc. → PYTEST.
    4. Lines containing browser-flow keywords (click, 登录, ...) → BROWSER.
    5. Otherwise → ASSERT (manual reviewer judgement).

    The original ``raw`` text is always preserved so the reviewer can
    re-read it verbatim.
    """
    s = raw.strip()
    if not s:
        raise ValueError("acceptance step must not be empty or whitespace-only")

    # Shell: "$ command" / "! command" / "run command" — the body is
    # everything after the first whitespace.
    for prefix in _SHELL_PREFIXES:
        if s.startswith(prefix):
            cmd = s[len(prefix):].strip()
            return AcceptanceStep(raw=raw, kind=StepKind.SHELL, payload=cmd)

    # HTTP: extract URL when present; full step goes in raw for context.
    for prefix in _HTTP_PREFIXES:
        if s.startswith(prefix):
            url_match = re.search(r"https?://\S+", s)
            url = url_match.group(0) if url_match else s.split()[1] if len(s.split()) > 1 else ""
            return AcceptanceStep(raw=raw, kind=StepKind.HTTP, payload=url)

    # Pytest: extract the node id / path.
    for prefix in _PYTEST_PREFIXES:
        if s.startswith(prefix):
            return AcceptanceStep(raw=raw, kind=StepKind.PYTEST, payload=s)

    # Browser: keyword match — no payload, raw text describes the step.
    s_lower = s.lower()
    if any(kw in s_lower for kw in _BROWSER_KEYWORDS):
        return AcceptanceStep(raw=raw, kind=StepKind.BROWSER, payload="")

    return AcceptanceStep(raw=raw, kind=StepKind.ASSERT, payload="")


def classify_all(steps: Iterable[str]) -> list[AcceptanceStep]:
    """Classify every step in *steps* in order.

    Raises :class:`ValueError` if any step is empty (caller's
    responsibility to filter sentinel defaults out first).
    """
    return [classify_step(s) for s in steps]


def has_legacy_acceptance(steps: list[str]) -> bool:
    """Return True iff *steps* looks like a pre-T11 sentinel default.

    Used by the pipeline to detect old task-queue files that need
    re-generation.
    """
    return any(s.startswith("(legacy)") for s in steps)


def summarize(steps: Iterable[AcceptanceStep]) -> dict[str, int]:
    """Return counts of steps by kind. Useful for the test reviewer's score card."""
    counts: dict[str, int] = {k.value: 0 for k in StepKind}
    for s in steps:
        counts[s.kind.value] += 1
    return counts


def shell_commands(steps: Iterable[AcceptanceStep]) -> list[str]:
    """Return just the SHELL payloads — handy for the test reviewer to run them."""
    return [s.payload for s in steps if s.kind is StepKind.SHELL]


def http_targets(steps: Iterable[AcceptanceStep]) -> list[str]:
    """Return just the HTTP URLs — handy for an HTTP-level review."""
    return [s.payload for s in steps if s.kind is StepKind.HTTP and s.payload]
