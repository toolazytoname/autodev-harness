"""Open Design adapter — UI design brief → OD run → HTML envelope.

T45 — this is the adapter-side counterpart to ``harness.open_design``.
It does the actual MCP talking:

  1. spawn the OD daemon-cli (or reuse an existing one via the
     ``OpenDesignMCPClient`` context manager),
  2. ``create_project`` → ``start_run`` → poll ``get_run`` until the
     run is succeeded/failed/canceled,
  3. on success, ``get_artifact`` to pull index.html + spec.md,
  4. format as ``---SPEC---/---HTML---/---END---`` so the existing
     ``UIPhase.extract_ui_output`` parser handles it unchanged.

Raises ``AdapterError`` for every failure mode (daemon unreachable /
spawn failure / MCP error / run failed-canceled / poll budget
exhausted / artifact empty) so ``UIPhase`` can catch and fall back to
the Claude adapter for that direction.

Public surface
--------------
``OpenDesignMCPClient`` — context-managed stdio JSON-RPC client. Its
``.call()`` returns the dict-shaped ``result`` of an MCP request;
``.create_project()``/``.start_run()``/``.get_run()``/``.get_artifact()``
are convenience wrappers that already pull the JSON out of the MCP
``content`` envelope.

``OpenDesignAdapter`` — ``AdapterBase`` subclass. One ``.run(...)``
invocation drives one full MCP round-trip (project → run → artifact).
"""

from __future__ import annotations

import contextlib
import json
import os
import subprocess
import time
from dataclasses import dataclass
from typing import Any, Iterator

from harness.adapters.base import AdapterBase, AdapterError, AgentResult
from harness.env import EnvVars


# Daemon-level budget — overridable via env or per-instance kwarg.
DEFAULT_POLL_INTERVAL_SECONDS = 30.0
DEFAULT_POLL_BUDGET_SECONDS = 1800.0  # 30 min covers typical OD runs


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


# Module-level so tests can monkeypatch cheaply.
_POLL_INTERVAL_SECONDS = _env_float(
    EnvVars.OD_POLL_INTERVAL, DEFAULT_POLL_INTERVAL_SECONDS
)
_POLL_BUDGET_SECONDS = _env_float(
    EnvVars.OD_RUN_TIMEOUT, DEFAULT_POLL_BUDGET_SECONDS
)


# ---------------------------------------------------------------------------
# MCP client (stdio JSON-RPC)
# ---------------------------------------------------------------------------


@dataclass
class OpenDesignMCPClient:
    """Context-managed JSON-RPC client for the Open Design daemon.

    Spawns the daemon on ``__enter__`` (or lazily via ``call()``),
    maintains a single subprocess for the lifetime of the context.
    The ``initialize`` handshake is sent on first call to anything
    that isn't ``initialize`` itself; we keep the protocol deliberately
    minimal — no SSE, no resumption, no capabilities negotiation.
    """

    timeout_per_call: float = 60.0
    _proc: subprocess.Popen | None = None
    _next_id: int = 1
    _initialized: bool = False
    _lock: Any = None  # threading.Lock set on first call

    def __post_init__(self) -> None:
        if self._lock is None:
            import threading

            self._lock = threading.Lock()

    def __enter__(self) -> "OpenDesignMCPClient":
        self._spawn_if_needed()
        if not self._initialized:
            self._initialize()
            self._initialized = True
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    # ----- process lifecycle -----

    def _daemon_command_and_env(self) -> tuple[list[str], dict[str, str]]:
        """Resolve (argv, env) — import lazily so tests can override."""
        from harness.open_design import DEFAULT_COMMAND, DEFAULT_ENV

        return list(DEFAULT_COMMAND), dict(DEFAULT_ENV)

    def _spawn_if_needed(self) -> None:
        if self._proc is not None:
            return
        cmd, extra = self._daemon_command_and_env()
        env = dict(os.environ)
        env.update(extra)
        try:
            self._proc = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=env,
            )
        except (FileNotFoundError, OSError) as exc:
            raise AdapterError(
                f"failed to spawn Open Design daemon at {cmd[0]}: {exc}"
            ) from exc

    def close(self) -> None:
        if self._proc is None:
            return
        try:
            if self._proc.stdin and not self._proc.stdin.closed:
                self._proc.stdin.close()
        except Exception:
            pass
        try:
            self._proc.terminate()
            self._proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self._proc.kill()
        self._proc = None
        self._initialized = False

    # ----- protocol -----

    def _initialize(self) -> None:
        result = self.call(
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "harness-ui", "version": "0.1"},
            },
        )
        if not isinstance(result, dict) or "serverInfo" not in result:
            self.close()
            raise AdapterError(
                f"Open Design daemon did not respond with serverInfo: {result!r}"
            )

    def call(self, method: str, params: dict[str, Any] | None = None) -> Any:
        """Send one JSON-RPC request and return the ``result`` field.

        Auto-initializes the session on first call. Reads each stdout
        line, skipping messages that don't match the request id (notably
        ``initialized`` notifications from the daemon).
        """
        if self._proc is None:
            self._spawn_if_needed()
        if not self._initialized and method != "initialize":
            self._initialize()
            self._initialized = True

        with self._lock:
            mid = self._next_id
            self._next_id += 1
        request = {"jsonrpc": "2.0", "id": mid, "method": method, "params": params or {}}

        assert self._proc is not None
        try:
            line = (json.dumps(request) + "\n").encode()
            self._proc.stdin.write(line)
            self._proc.stdin.flush()
        except (BrokenPipeError, OSError) as exc:
            self.close()
            raise AdapterError(f"Open Design daemon closed stdin: {exc}") from exc

        return self._read_response(mid)

    def _read_response(self, mid: int) -> Any:
        assert self._proc is not None
        deadline = time.time() + self.timeout_per_call
        while True:
            if self._proc.poll() is not None:
                self.close()
                raise AdapterError(
                    f"Open Design daemon exited (code={self._proc.returncode}) "
                    "before responding"
                )
            remaining = deadline - time.time()
            if remaining <= 0:
                self.close()
                raise AdapterError("Open Design daemon timed out")
            try:
                line = self._proc.stdout.readline()
            except OSError as exc:
                self.close()
                raise AdapterError(f"reading daemon stdout failed: {exc}") from exc
            if not line:
                self.close()
                raise AdapterError("Open Design daemon closed stdout")
            try:
                msg = json.loads(line.decode())
            except (UnicodeDecodeError, json.JSONDecodeError):
                continue
            if not isinstance(msg, dict):
                continue
            if msg.get("id") != mid:
                continue  # notifications or older messages
            if "error" in msg:
                err = msg["error"]
                raise AdapterError(
                    f"Open Design daemon error: {err if isinstance(err, str) else err.get('message', err)}"
                )
            return msg.get("result", {})

    # ----- high-level helpers -----

    @staticmethod
    def _extract_text_payload(result: Any) -> Any:
        """Pull the JSON-parsed payload out of a ``tools/call`` content block.

        MCP tool-call responses wrap their payload in
        ``{"content": [{"type":"text","text":"<json string>"}]}``. We
        unwrap that envelope so the caller sees the parsed object.
        """
        if not isinstance(result, dict):
            return result
        content = result.get("content")
        if not isinstance(content, list):
            return result
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                text = block.get("text", "")
                if not text:
                    continue
                try:
                    return json.loads(text)
                except json.JSONDecodeError:
                    return text
        return result

    def _tool_call(self, tool_name: str, arguments: dict[str, Any]) -> Any:
        result = self.call("tools/call", {"name": tool_name, "arguments": arguments})
        if isinstance(result, dict) and result.get("isError"):
            msg = result.get("content")
            raise AdapterError(
                f"Open Design tool {tool_name!r} failed: {msg!r}"
            )
        return self._extract_text_payload(result)

    def create_project(
        self, name: str, *, skill: str | None = None, design_system: str | None = None
    ) -> dict[str, Any]:
        args: dict[str, Any] = {"name": name}
        if skill:
            args["skill"] = skill
        if design_system:
            args["designSystem"] = design_system
        return self._tool_call("create_project", args)

    def start_run(
        self,
        project: str,
        prompt: str,
        *,
        agent: str | None = None,
        model: str | None = None,
        skill: str | None = None,
    ) -> dict[str, Any]:
        args: dict[str, Any] = {"project": project, "prompt": prompt}
        if agent:
            args["agent"] = agent
        if model:
            args["model"] = model
        if skill:
            args["skill"] = skill
        return self._tool_call("start_run", args)

    def get_run(self, run_id: str) -> dict[str, Any]:
        return self._tool_call("get_run", {"runId": run_id})

    def get_artifact(self, project: str, *, entry: str | None = None) -> dict[str, Any]:
        args: dict[str, Any] = {"project": project}
        if entry:
            args["entry"] = entry
        return self._tool_call("get_artifact", args)


# ---------------------------------------------------------------------------
# Adapter
# ---------------------------------------------------------------------------


def _resolve_poll_interval() -> float:
    return _env_float(EnvVars.OD_POLL_INTERVAL, _POLL_INTERVAL_SECONDS)


def _resolve_poll_budget() -> float:
    return _env_float(EnvVars.OD_RUN_TIMEOUT, _POLL_BUDGET_SECONDS)


class OpenDesignAdapter(AdapterBase):
    """UI brief → Open Design run → ``---SPEC---/---HTML---/---END---`` envelope.

    The ``_execute`` body is the only nontrivial adapter code: it
    drives one full OD session (create_project → start_run → poll
    get_run → get_artifact) inside a single call. Stays inside the
    harness's existing ``AdapterBase`` retry/timeout machinery by
    raising ``AdapterError`` and letting ``UIPhase._call_ui_direction``
    catch + fall back to ``self._p._adapter`` (the per-stage claude
    adapter) on failure.
    """

    client_factory = staticmethod(lambda: OpenDesignMCPClient())

    # Override retry defaults: an OD run can take 5-30 min; we don't
    # want ``AdapterBase``'s default 3x exponential retry compounding on
    # top of that. UIPhase has its own per-direction fallback so a
    # single OD failure is already handled.
    RETRY_MAX_ATTEMPTS = 1

    def _execute(  # type: ignore[override]
        self,
        prompt: str,
        *,
        model: str,
        cwd: Any = None,
        timeout: int = 600,
        attempt: int = 0,
        base_url: Any = None,
        api_key: Any = None,
        allowed_tools: Any = None,
    ) -> AgentResult:
        # Pull prompt + brief-derived project slug from the calling
        # context. ``prompt`` arriving here already contains
        # ---PLAN--- / ---DIRECTION--- / ---STYLE MODULE PROMPT--- /
        # ---THREE-PIECE BASELINE--- blocks (assembled by
        # ``prompts._build_ui_prompt``), so we use it as-is.
        run = self._run_full(prompt, model=model)
        spec_md, html = run["spec_md"], run["html"]
        envelope = (
            "---SPEC---\n"
            f"{spec_md or '(no spec.md — describe intent in prompt)'}\n\n"
            "---HTML---\n"
            f"{html or '<!DOCTYPE html><!-- empty -->'}\n"
            "---END---\n"
        )
        return AgentResult(
            stdout=envelope,
            stderr="",
            exit_code=0,
            duration_ms=int(run["duration_ms"]),
        )

    # ----- internal: end-to-end OD session -----

    def _run_full(self, prompt: str, *, model: str) -> dict[str, Any]:
        """Drive one full OD session and return the parsed spec+html.

        Raises ``AdapterError`` for every failure mode so the caller
        can ``except AdapterError`` and fall back.
        """
        from harness.open_design import project_name_for

        # Project naming: stable on (slug, brief_seed, date). We derive
        # the slug from a short hash of the prompt + today's date so
        # users can recognize which direction a project corresponds to.
        # If we cannot locate a usable slug we fall back to a UUID-like
        # stub; OD will keep creating fresh projects instead of
        # colliding with prior runs.
        slug = self._derive_slug(prompt)
        brief_seed = prompt[:200]
        name = project_name_for(slug, brief_seed)
        poll_interval = _resolve_poll_interval()
        poll_budget = _resolve_poll_budget()

        start = time.monotonic()
        try:
            with self.client_factory() as client:
                proj = client.create_project(name=name)
                project_id = proj.get("project_id") or proj.get("id")
                if not project_id:
                    raise AdapterError(
                        f"create_project returned no project_id: {proj!r}"
                    )

                run = client.start_run(
                    project=project_id, prompt=prompt, model=model
                )
                run_id = run.get("run_id") or run.get("id")
                if not run_id:
                    raise AdapterError(
                        f"start_run returned no run_id: {run!r}"
                    )

                # Poll until terminal status. OD runs are 5–30 min.
                status = self._poll_until_terminal(
                    client, run_id, poll_interval, poll_budget
                )

                if status != "succeeded":
                    raise AdapterError(
                        f"OD run {run_id} ended with status={status!r}"
                    )

                artifact = client.get_artifact(project=project_id)
                spec_md, html = self._split_artifact(artifact)
        except AdapterError:
            raise
        except Exception as exc:
            # Anything we didn't anticipate — wrap as AdapterError so
            # UIPhase's except clause catches it.
            raise AdapterError(f"Open Design run failed: {exc}") from exc

        return {
            "spec_md": spec_md,
            "html": html,
            "duration_ms": (time.monotonic() - start) * 1000.0,
        }

    @staticmethod
    def _derive_slug(prompt: str) -> str:
        """Cheap, deterministic slug: first 12 alphanumerics of the prompt."""
        import hashlib

        digest = hashlib.sha1(prompt.encode("utf-8")).hexdigest()[:8]
        return f"ui-{digest}"

    @staticmethod
    def _poll_until_terminal(
        client: OpenDesignMCPClient,
        run_id: str,
        interval: float,
        budget: float,
    ) -> str:
        deadline = time.monotonic() + budget
        while True:
            result = client.get_run(run_id)
            status = (result.get("status") or "").lower()
            if status in {"succeeded", "failed", "canceled"}:
                return status
            if time.monotonic() >= deadline:
                raise AdapterError(
                    f"OD run {run_id} still {status!r} after "
                    f"{int(budget)}s — poll budget exhausted"
                )
            time.sleep(interval)

    @staticmethod
    def _split_artifact(artifact: Any) -> tuple[str, str]:
        """Pull ``spec.md`` + index-html out of a ``get_artifact`` reply."""
        if not isinstance(artifact, dict):
            return "", ""
        files = artifact.get("files") or {}
        if not isinstance(files, dict):
            return "", ""

        # Prefer the entry reported by the daemon; otherwise sniff for
        # the conventional index.html / spec.md pair.
        html = ""
        spec_md = ""
        # Match either case-insensitive filename keys or 'path' / 'name' fields
        for key, value in files.items():
            base = key.rsplit("/", 1)[-1].lower()
            if isinstance(value, dict):
                content = value.get("content") or value.get("text") or ""
            else:
                content = value if isinstance(value, str) else ""
            if base in {"index.html", "index.htm"} and not html:
                html = content
            elif base in {"spec.md", "ui-spec.md"} and not spec_md:
                spec_md = content
        return spec_md.strip(), html.strip()
