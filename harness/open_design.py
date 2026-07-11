"""Open Design integration — probe, topic-aware direction generation, helpers.

T45 — wires Open Design (a local-first design desktop app) into the
harness UI phase. The MCP daemon lives at a known path and speaks
JSON-RPC over stdio; ``OpenDesignMCPClient`` (in
``harness.adapters.open_design``) consumes that protocol, while this
module stays focused on:

  - ``is_available()`` — cheap MCP ``initialize`` probe
  - ``Direction`` / ``parse_direction_list()`` — topic-aware direction
    table produced by a single LLM call at the top of ``UIPhase.run``
  - ``project_name_for()`` — deterministic, human-readable OD project
    names so users can scan the OD sidebar and recognize them
  - ``DIRECTION_GEN_PROMPT`` — the prompt template used to ask the
    model for the topic-aware list

Detection rule of thumb: if the Open Design desktop app is installed
on macOS, this module lets the harness route the UI design phase
through OD. On Linux servers (or any platform without OD installed)
``is_available()`` returns False and the surrounding code falls back
to the existing Claude-based UI design flow.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path


# Daemon command (resolved at import; tests monkey-patch these for
# cheap subprocess control without touching ``/Applications``).
DEFAULT_COMMAND: tuple[str, ...] = (
    "/Applications/Open Design.app/Contents/Frameworks/Open Design Helper.app/Contents/MacOS/Open Design Helper",
    "/Applications/Open Design.app/Contents/Resources/app/prebundled/daemon/daemon-cli.mjs",
    "mcp",
)

DEFAULT_ENV: dict[str, str] = {
    "ELECTRON_RUN_AS_NODE": "1",
    "OD_DATA_DIR": "/Users/lazy/Library/Application Support/Open Design/namespaces/release-stable/data",
    "OD_SIDECAR_IPC_PATH": "/tmp/open-design/ipc/release-stable/daemon.sock",
    "OD_SIDECAR_NAMESPACE": "release-stable",
}


# ---------------------------------------------------------------------------
# Daemon probe
# ---------------------------------------------------------------------------


def _daemon_command_and_env() -> tuple[list[str], dict[str, str]]:
    """Return (argv, env) for spawning the Open Design daemon CLI.

    Production: the constants above (Mac OD app path). Tests monkey-patch
    DEFAULT_COMMAND + DEFAULT_ENV.
    """
    return list(DEFAULT_COMMAND), dict(DEFAULT_ENV)


def is_available(timeout: float = 3.0) -> bool:
    """Cheap probe: spawn the daemon, send ``initialize``, parse the
    JSON-RPC reply, return True iff we got a ``result`` back.

    Used by ``__main__.main`` to decide whether to wire the
    ``OpenDesignAdapter`` into ``Pipeline(ui_adapter=...)``. Returns
    False for any failure mode (command not found, daemon crashed,
    timeout, malformed reply) so the rest of the pipeline can fall back
    silently to Claude.
    """
    cmd, env = _daemon_command_and_env()
    try:
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
        )
    except (FileNotFoundError, OSError):
        return False

    msg = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "harness-ui-probe", "version": "0.1"},
            },
        }
    )

    try:
        stdout, _stderr = proc.communicate(input=msg.encode(), timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        return False
    if proc.returncode != 0:
        return False

    try:
        reply = json.loads(stdout.decode())
    except (json.JSONDecodeError, UnicodeDecodeError):
        return False
    if not isinstance(reply, dict):
        return False
    result = reply.get("result")
    return isinstance(result, dict) and "serverInfo" in result


# ---------------------------------------------------------------------------
# Topic-aware directions
# ---------------------------------------------------------------------------


# Modules the harness's existing UI design phase supports (see
# ``harness.pipeline.UI_DIRECTIONS``). parse_direction_list rejects rows
# that name any other module, so the new LLM-driven path produces the
# same shape the existing prompt builder expects.
VALID_MODULES = {"minimalist-ui", "gpt-taste", "industrial-brutalist-ui", "(none)"}


@dataclass(frozen=True)
class Direction:
    """One UI design direction the harness renders in the topic-aware loop.

    Attributes
    ----------
    slug : str
        URL-friendly identifier used for the OD project name and the
        on-disk ``preview/versions/<slug>/index.html`` directory.
        Lowercased + non-alphanumerics replaced with ``-``.
    label : str
        Human-facing title (may be Chinese, displayed in pick-prompt).
    module : str
        One of ``VALID_MODULES``: names a style SKILL module to inject.
    intent : str
        1-2 sentence topical anchor: what screen this design depicts
        and which user story it serves (e.g. "Per-student trend lines
        across monthly tests").
    sections : list[str]
        Optional list of content blocks OD should flesh out (e.g.
        ``["trend line", "score comparison"]``).
    """

    slug: str
    label: str
    module: str
    intent: str
    sections: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        """Shape expected by ``_build_ui_prompt`` (and legacy code paths)."""
        return asdict(self)


_SAFE_SLUG = re.compile(r"[^a-z0-9]+")


def _normalize_slug(raw: str) -> str:
    """Filesystem-safe slug: lowercase, separators -> ``-``."""
    s = (raw or "").strip().lower()
    s = _SAFE_SLUG.sub("-", s).strip("-")
    return s or "direction"


def _strip_json_fence(s: str) -> str:
    """Pull a JSON body out of a fenced ``` ``` json ... ``` ``` block if present."""
    text = s.strip()
    if text.startswith("```"):
        # Find first newline after the fence and the last closing fence.
        first_nl = text.find("\n")
        if first_nl != -1:
            text = text[first_nl + 1 :]
        if text.endswith("```"):
            text = text[:-3].rstrip()
    return text


def parse_direction_list(raw: str) -> list[Direction]:
    """Parse the LLM direction-gen output into a ``[Direction]`` list.

    Lenient parsing — keeps:
      - rows with all five required keys (``slug, label, module, intent, sections``)
      - rows whose ``module`` is in ``VALID_MODULES``
      - the FIRST occurrence of each unique slug

    Raises ``ValueError`` when no usable rows survive (caller falls back
    to the hardcoded ``UI_DIRECTIONS`` list).
    """
    body = _strip_json_fence(raw).strip()
    if not body:
        raise ValueError("empty direction-gen output")
    try:
        data = json.loads(body)
    except json.JSONDecodeError as exc:
        raise ValueError(f"direction-gen output is not JSON: {exc}") from exc

    if not isinstance(data, list):
        raise ValueError("direction-gen JSON root is not an array")

    seen: set[str] = set()
    out: list[Direction] = []
    for row in data:
        if not isinstance(row, dict):
            continue
        try:
            slug = _normalize_slug(row["slug"])
            label = str(row["label"]).strip()
            module = str(row["module"]).strip()
            intent = str(row["intent"]).strip()
            sections_raw = row.get("sections") or []
            sections = [str(s).strip() for s in sections_raw if str(s).strip()]
        except (KeyError, TypeError):
            continue
        if not label or not intent or module not in VALID_MODULES or not sections:
            continue
        if slug in seen:
            continue
        seen.add(slug)
        out.append(Direction(slug=slug, label=label, module=module, intent=intent, sections=sections))

    if not out:
        raise ValueError("no valid direction rows survived parsing")
    return out


# ---------------------------------------------------------------------------
# OD project naming
# ---------------------------------------------------------------------------


def project_name_for(slug: str, brief_seed: str, *, when: str | None = None) -> str:
    """Stable, human-readable OD project name.

    Deterministic on (slug, brief_seed, when) so re-running the same
    brief produces the same project name. Format::

        harness-ui-<slug>-<brief_seed[:8]>-<YYYYMMDD>

    Lets users open the OD sidebar and instantly recognize which
    direction a project corresponds to.
    """
    safe_slug = _normalize_slug(slug)
    short = re.sub(r"[^a-z0-9]", "", brief_seed.lower())[:8] or "brief"
    day = (when or datetime.now().strftime("%Y-%m-%d")).replace("-", "")
    return f"harness-ui-{safe_slug}-{short}-{day}"


# ---------------------------------------------------------------------------
# Direction-generation prompt template
# ---------------------------------------------------------------------------


DIRECTION_GEN_PROMPT: str = """You are a UI design strategist. Given a product brief below, propose
{N} distinct design directions a designer should explore for it.

Each direction must describe a CONCRETE screen or view of the product
(dashboard / detail page / shareable reel / intake form / progress
timeline — whatever the brief actually warrants), not an abstract
aesthetic label.

Output JSON only, no prose, no markdown fencing. Array of {N} objects:

  [
    {{
      "slug":   "kebab-case-id-safe-for-filenames",
      "label":  "human-facing title (use the brief's own language)",
      "module": "minimalist-ui | gpt-taste | industrial-brutalist-ui | (none)",
      "intent": "1-2 sentences: which user story this screen serves and how it advances the product's headline promise",
      "sections": ["key content block 1", "key content block 2", ...]
    }},
    ...
  ]

Constraints:
  - Use the brief's own language for ``label`` and ``intent``.
  - ``module`` MUST be one of the four values above (style SKILLs
    the harness has bundled); pick whichever aesthetic best fits the
    screen's purpose.
  - ``sections`` enumerates the visible building blocks so a downstream
    designer / agent can render them faithfully.
  - ``slug`` is lowercase kebab-case, used as a directory name.

---BRIEF---
{plan_text}

---DIRECTIONS---
"""
