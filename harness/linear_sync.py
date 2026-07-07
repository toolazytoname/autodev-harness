"""Linear MCP sync — project/issue tracking for the inner loop.

Per MASTER-PLAN §3 (P6) and TASKS T12:
- tasks phase creates a Linear project + one issue per task (with
  acceptance steps as the body)
- inner loop transitions:
  - start        → In Progress
  - gate passed  → Done (comment: score card summary)
  - escalation   → Blocked (comment: blockers list)
- when ``LINEAR_API_KEY`` is missing we **degrade silently** to a
  local in-memory store (still prints the link banner so the human
  knows it's running in degraded mode)

The module is split into two layers:

1. :class:`LinearClient` — the protocol. Two implementations:
   - :class:`LocalLinearClient` (in-memory + JSON persistence, always
     works, used in tests and as the no-key fallback)
   - :class:`McpLinearClient` (thin wrapper around the Linear MCP
     server; only used when ``LINEAR_API_KEY`` is set; the import
     is lazy so a missing MCP package doesn't break the local
     fallback path)
2. :class:`LinearSync` — the orchestrator used by the pipeline. It
   doesn't know whether the client is local or MCP; it just calls
   the protocol methods.

The MCP variant is intentionally minimal: the project uses streamable
HTTP transports where possible, and the methods are designed to be
batch-friendly (one issue per task, not per assertion) so we don't
blow the token budget on a thousand GraphQL round trips.
"""

from __future__ import annotations

import json
import os
import threading
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Iterable, Optional

import pydantic


# ---------------------------------------------------------------------------
# Enums and models
# ---------------------------------------------------------------------------


class LinearState(str, Enum):
    """The four states the harness cares about.

    Mirrors Linear's default state names so the MCP client can map
    these onto real state IDs without us hardcoding Linear's project
    templates.
    """

    BACKLOG = "backlog"
    IN_PROGRESS = "in_progress"
    DONE = "done"
    BLOCKED = "blocked"


class LinearComment(pydantic.BaseModel):
    """One comment on an issue."""

    model_config = pydantic.ConfigDict(frozen=True)

    id: str
    body: str
    author: str = "autodev-harness"
    created_at: datetime = pydantic.Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


class LinearIssue(pydantic.BaseModel):
    """One task mirrored as a Linear issue.

    ``linear_key`` is the human-readable ID (e.g. ``task-1``) the
    inner loop uses to look the issue up; the ``id`` is the
    transport-level ID (UUID for the local backend, Linear's UUID
    for the MCP backend).
    """

    model_config = pydantic.ConfigDict(frozen=True)

    id: str
    linear_key: str
    project_id: str
    title: str
    body: str
    state: LinearState = LinearState.BACKLOG
    kind: str = "logic"
    blocked_by: list[str] = field(default_factory=list)
    comments: list[LinearComment] = field(default_factory=list)


class LinearProject(pydantic.BaseModel):
    """A Linear project (= a 003-task-queue.json run)."""

    model_config = pydantic.ConfigDict(frozen=True)

    id: str
    name: str
    url: Optional[str] = None
    created_at: datetime = pydantic.Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


# ---------------------------------------------------------------------------
# Client protocol
# ---------------------------------------------------------------------------


class LinearClient(ABC):
    """The minimal surface a Linear backend must implement.

    The harness's only contract with Linear is: create a project, add
    issues, change state, and add a comment. We do NOT use Linear's
    custom fields, labels, or templates — the harness has its own
    schema and the sync is intentionally lossy in the other direction.
    """

    @abstractmethod
    def create_project(self, name: str) -> LinearProject: ...

    @abstractmethod
    def create_issue(
        self,
        project_id: str,
        title: str,
        body: str = "",
        kind: str = "logic",
        linear_key: Optional[str] = None,
        blocked_by: Optional[list[str]] = None,
    ) -> LinearIssue: ...

    @abstractmethod
    def update_issue_state(self, issue_id: str, state: LinearState) -> None: ...

    @abstractmethod
    def add_comment(self, issue_id: str, body: str) -> None: ...

    @abstractmethod
    def get_issue(self, issue_id: str) -> LinearIssue: ...

    @abstractmethod
    def all_issues(self) -> list[LinearIssue]: ...

    @abstractmethod
    def projects(self) -> list[LinearProject]: ...

    def get_project_url(self, project_id: str) -> Optional[str]:
        """Return a human-facing URL for the project, or None for local."""
        return None


# ---------------------------------------------------------------------------
# Local implementation — always works, used in tests + no-key fallback
# ---------------------------------------------------------------------------


class LocalLinearClient(LinearClient):
    """In-memory + JSON-on-disk Linear stand-in.

    Used:
    - as the implementation under test in ``test_linear_sync.py``
    - as the silent fallback when ``LINEAR_API_KEY`` is unset
    - as the developer-mode "scratch tracker" — the JSON file is small
      and human-readable, useful for postmortems.
    """

    def __init__(self, path: Optional[Path] = None) -> None:
        self._lock = threading.Lock()
        self._projects: dict[str, LinearProject] = {}
        self._issues: dict[str, LinearIssue] = {}
        self._comments: dict[str, list[LinearComment]] = {}
        # linear_key -> issue_id (so the harness can find issues by
        # task id rather than transport UUID)
        self._key_index: dict[str, str] = {}
        self._path = path
        if path is not None and path.exists():
            self._load_from_disk()

    # ---- persistence -------------------------------------------------------

    def flush(self) -> None:
        if self._path is None:
            return
        snapshot = {
            "projects": {pid: p.model_dump(mode="json") for pid, p in self._projects.items()},
            "issues": {iid: i.model_dump(mode="json") for iid, i in self._issues.items()},
            "comments": {iid: [c.model_dump(mode="json") for c in cs] for iid, cs in self._comments.items()},
            "key_index": self._key_index,
        }
        self._path.write_text(json.dumps(snapshot, indent=2, ensure_ascii=False))

    def _load_from_disk(self) -> None:
        if self._path is None or not self._path.exists():
            return
        data = json.loads(self._path.read_text())
        for pid, p in data.get("projects", {}).items():
            self._projects[pid] = LinearProject.model_validate(p)
        for iid, i in data.get("issues", {}).items():
            self._issues[iid] = LinearIssue.model_validate(i)
        for iid, cs in data.get("comments", {}).items():
            self._comments[iid] = [LinearComment.model_validate(c) for c in cs]
        self._key_index = data.get("key_index", {})

    # ---- CRUD --------------------------------------------------------------

    def create_project(self, name: str) -> LinearProject:
        with self._lock:
            pid = f"local-proj-{uuid.uuid4().hex[:8]}"
            project = LinearProject(id=pid, name=name, url=None)
            self._projects[pid] = project
            self.flush()
            return project

    def create_issue(
        self,
        project_id: str,
        title: str,
        body: str = "",
        kind: str = "logic",
        linear_key: Optional[str] = None,
        blocked_by: Optional[list[str]] = None,
    ) -> LinearIssue:
        with self._lock:
            if project_id not in self._projects:
                raise KeyError(f"project {project_id!r} does not exist")
            iid = f"local-iss-{uuid.uuid4().hex[:8]}"
            issue = LinearIssue(
                id=iid,
                linear_key=linear_key or iid,
                project_id=project_id,
                title=title,
                body=body,
                kind=kind,
                blocked_by=list(blocked_by or []),
            )
            self._issues[iid] = issue
            self._comments.setdefault(iid, [])
            if linear_key:
                self._key_index[linear_key] = iid
            self.flush()
            return issue

    def update_issue_state(self, issue_id: str, state: LinearState) -> None:
        with self._lock:
            issue = self._resolve(issue_id)
            # Pydantic models are frozen; rebuild with new state.
            new_issue = issue.model_copy(update={"state": state})
            self._issues[issue.id] = new_issue
            self.flush()

    def add_comment(self, issue_id: str, body: str) -> None:
        with self._lock:
            issue = self._resolve(issue_id)
            comment = LinearComment(id=f"c-{uuid.uuid4().hex[:8]}", body=body)
            self._comments.setdefault(issue.id, []).append(comment)
            # We have to rebuild the issue with the new comment list.
            new_comments = list(issue.comments) + [comment]
            self._issues[issue.id] = issue.model_copy(
                update={"comments": new_comments}
            )
            self.flush()

    def get_issue(self, issue_id: str) -> LinearIssue:
        with self._lock:
            return self._resolve(issue_id)

    def all_issues(self) -> list[LinearIssue]:
        with self._lock:
            return list(self._issues.values())

    def projects(self) -> list[LinearProject]:
        with self._lock:
            return list(self._projects.values())

    # ---- internal helpers --------------------------------------------------

    def _resolve(self, issue_id: str) -> LinearIssue:
        # Accept either a transport ID or a linear_key.
        if issue_id in self._issues:
            return self._issues[issue_id]
        if issue_id in self._key_index:
            return self._issues[self._key_index[issue_id]]
        raise KeyError(f"issue {issue_id!r} not found")

    # Backwards-compat attribute for tests / callers that read the
    # field directly: ``client.projects``. Returns a fresh list each
    # call so callers cannot mutate the internal map.
    @property
    def projects(self) -> list[LinearProject]:
        return list(self._projects.values())


# ---------------------------------------------------------------------------
# MCP implementation — lazy import so the local fallback path doesn't need it
# ---------------------------------------------------------------------------


class _McpLinearClient(LinearClient):
    """Linear MCP client. Lazily imported; only constructed when an API key
    is present and the user opts into MCP-backed tracking.

    The class is a stub for now — the real implementation will need to
    talk to the ``mcp__linear__*`` tools (or to a streamable HTTP
    transport). Until that wiring lands the constructor raises so the
    factory doesn't silently hand out a broken client.
    """

    def __init__(self, api_key: str, base_url: Optional[str] = None) -> None:
        self._api_key = api_key
        self._base_url = base_url or "https://api.linear.app/graphql"
        # NOTE: actual MCP wiring is left to a follow-up task. The
        # constructor captures the key so a future implementation can
        # use it without re-plumbing the factory.
        raise NotImplementedError(
            "McpLinearClient is a stub. Set LINEAR_API_KEY=local or unset it "
            "to use LocalLinearClient until the MCP wiring lands (T12 follow-up)."
        )

    # ---- unimplemented -----------------------------------------------------

    def create_project(self, name: str) -> LinearProject:
        raise NotImplementedError

    def create_issue(
        self,
        project_id: str,
        title: str,
        body: str,
        kind: str = "logic",
        linear_key: Optional[str] = None,
        blocked_by: Optional[list[str]] = None,
    ) -> LinearIssue:
        raise NotImplementedError

    def update_issue_state(self, issue_id: str, state: LinearState) -> None:
        raise NotImplementedError

    def add_comment(self, issue_id: str, body: str) -> None:
        raise NotImplementedError

    def get_issue(self, issue_id: str) -> LinearIssue:
        raise NotImplementedError

    def all_issues(self) -> list[LinearIssue]:
        raise NotImplementedError

    def projects(self) -> list[LinearProject]:
        raise NotImplementedError


# Make the private name importable for tests that want to patch it.
_McpLinearClient = _McpLinearClient  # noqa: PLW0127


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def is_linear_configured() -> bool:
    """True iff the user has set LINEAR_API_KEY."""
    return bool(os.environ.get("LINEAR_API_KEY", "").strip())


def get_linear_client(api_key: Optional[str] = None) -> LinearClient:
    """Pick the right Linear backend.

    Precedence:
    1. Explicit ``api_key=...`` argument → MCP
    2. ``LINEAR_API_KEY`` env var        → MCP
    3. Neither                          → Local (in-memory)
    """
    key = api_key or os.environ.get("LINEAR_API_KEY", "").strip()
    if not key:
        return LocalLinearClient()
    # The MCP client is currently a stub. We instantiate it lazily
    # so tests can patch ``harness.linear_sync._McpLinearClient``.
    return _McpLinearClient(key)


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


class LinearSync:
    """The high-level wrapper the pipeline uses.

    Encapsulates the project name, the per-task issue creation, and
    the state transitions triggered by the inner loop.
    """

    def __init__(self, client: LinearClient, project_dir: Path) -> None:
        self._client = client
        self._project_dir = project_dir
        self._project: Optional[LinearProject] = None
        # linear_key -> issue id (cache to skip round trips on every
        # status update — important for the MCP path).
        self._key_to_id: dict[str, str] = {}

    # ---- tasks phase -------------------------------------------------------

    def sync_tasks_phase(
        self,
        brief: str,
        tasks: list[dict[str, Any]],
    ) -> LinearProject:
        """Create the project + one issue per task.

        ``tasks`` is the list of dicts the pipeline parsed out of
        003-task-queue.json. Each dict must have ``id``, ``title`` and
        ``kind``; ``dependencies`` and ``acceptance`` are forwarded
        into the issue body so humans can read them in Linear.
        """
        project_name = self._derive_project_name(brief)
        self._project = self._client.create_project(project_name)
        for task in tasks:
            issue = self._client.create_issue(
                project_id=self._project.id,
                title=task.get("title") or task.get("id", "untitled"),
                body=self._render_issue_body(task),
                kind=task.get("kind", "logic"),
                linear_key=task["id"],
                blocked_by=task.get("dependencies") or [],
            )
            self._key_to_id[task["id"]] = issue.id
        return self._project

    # ---- inner loop transitions -------------------------------------------

    def mark_in_progress(self, linear_key: str) -> None:
        self._safe_state_update(linear_key, LinearState.IN_PROGRESS, comment=None)

    def mark_done(self, linear_key: str, score_card_summary: str) -> None:
        self._safe_state_update(
            linear_key,
            LinearState.DONE,
            comment=f"Gate passed. Score cards:\n{score_card_summary}",
        )

    def mark_blocked(self, linear_key: str, blockers: list[str]) -> None:
        body = "Escalated — gate did not pass after MAX_ITER.\nBlockers:\n" + "\n".join(
            f"- {b}" for b in blockers
        )
        self._safe_state_update(linear_key, LinearState.BLOCKED, comment=body)

    # ---- user-facing link --------------------------------------------------

    def print_progress_link(self) -> None:
        """Print a one-line progress banner the human can use to follow
        along. In MCP mode the line includes the real Linear URL; in
        local mode it says so.
        """
        if self._project is None:
            # No project yet — show a useful placeholder so the human
            # still gets a hint that Linear sync is wired up.
            print(
                "[Linear] (local mode — set LINEAR_API_KEY to publish to real "
                "Linear). sync_tasks_phase not called yet."
            )
            return
        url = self._client.get_project_url(self._project.id)
        if url:
            print(f"[Linear] {self._project.name}: {url}")
        else:
            print(
                f"[Linear] {self._project.name} (local mode — set "
                "LINEAR_API_KEY to publish to real Linear): "
                f"{len(self._client.all_issues())} issue(s) tracked"
            )

    # ---- internal helpers --------------------------------------------------

    def _derive_project_name(self, brief: str) -> str:
        first_line = brief.strip().splitlines()[0] if brief.strip() else "untitled"
        # Cap to 60 chars so Linear doesn't truncate the title.
        return f"AutoDevHarness: {first_line[:60]}"

    def _render_issue_body(self, task: dict[str, Any]) -> str:
        lines: list[str] = []
        if task.get("description"):
            lines.append(task["description"])
            lines.append("")
        lines.append("## Acceptance criteria")
        for step in task.get("acceptance") or []:
            lines.append(f"- {step}")
        if task.get("dependencies"):
            lines.append("")
            lines.append("## Blocked by")
            for d in task["dependencies"]:
                lines.append(f"- {d}")
        return "\n".join(lines) or "(no body)"

    def _safe_state_update(
        self,
        linear_key: str,
        state: LinearState,
        comment: Optional[str],
    ) -> None:
        """Apply a state transition + optional comment, but never raise.

        The inner loop must keep running even if Linear is down; the
        worst case is that progress doesn't get mirrored. We log the
        failure to stderr via the print so the user notices.
        """
        try:
            issue_id = self._key_to_id.get(linear_key) or linear_key
            self._client.update_issue_state(issue_id, state)
            if comment is not None:
                self._client.add_comment(issue_id, comment)
        except KeyError as e:
            # Issue wasn't created (e.g. linear_key typo, sync_tasks
            # wasn't called). Don't kill the inner loop.
            print(f"[Linear] skipping state update for {linear_key!r}: {e}")
        except Exception as e:  # defensive — never let sync break the loop
            print(f"[Linear] sync error for {linear_key!r}: {type(e).__name__}: {e}")


# ---------------------------------------------------------------------------
# Public re-exports
# ---------------------------------------------------------------------------


__all__ = [
    "LinearClient",
    "LinearComment",
    "LinearIssue",
    "LinearProject",
    "LinearState",
    "LinearSync",
    "LocalLinearClient",
    "get_linear_client",
    "is_linear_configured",
]
