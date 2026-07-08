"""Tests for harness.visual_reviewer — T09 visual reviewer step.

Tests cover, in order:
- ``probe_server`` behaviour against a real local socket.
- ``extract_pages_from_spec`` parser on the spec shapes the UI agent emits.
- ``run_visual_review`` dispatches through ``adapter.run_with_attachments``
  and parses the multimodal JSON score card; on parse failure it returns
  a 0.0 blocker card.
- The visual reviewer name dispatch inside inner_loop is covered by
  test_inner_loop.py::test_visual_reviewer_dispatch (added below).
"""

from __future__ import annotations

import http.server
import json
import socket
import socketserver
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from harness.adapters.base import AgentResult, Usage
from harness.score_card import ScoreCard
from harness.visual_reviewer import (
    extract_pages_from_spec,
    probe_server,
    run_visual_review,
    screenshots_dir_for,
)


# ---------------------------------------------------------------------------
# Spec → page list
# ---------------------------------------------------------------------------


class TestExtractPages:
    def test_pages_heading_then_bullets(self):
        spec = (
            "## Color and type\n"
            "primary #112\n\n"
            "## Pages\n"
            "- / — the landing\n"
            "- /pricing — pricing tiers\n"
            "- /blog — article index\n"
        )
        pages = extract_pages_from_spec(spec)
        assert pages == [
            ("/", "the landing"),
            ("/pricing", "pricing tiers"),
            ("/blog", "article index"),
        ]

    def test_single_page_heading(self):
        spec = "## Page\n- /calendar — the schedule\n"
        assert extract_pages_from_spec(spec) == [("/calendar", "the schedule")]

    def test_no_pages_falls_back_to_root(self):
        spec = "Spec with no headings and no bullets at all"
        pages = extract_pages_from_spec(spec)
        assert pages == [("/", "")]

    def test_no_pages_falls_back_to_global_bullets(self):
        spec = (
            "## Hero copy\n"
            "- /signup — sign up here\n"
            "- /about\n"
            "## Footer\n"
            "Some other section.\n"
        )
        pages = extract_pages_from_spec(spec)
        # No Pages heading → uses any bullets it found, capped to 6
        assert ("/signup", "sign up here") in pages
        assert ("/about", "") in pages


# ---------------------------------------------------------------------------
# Server probe
# ---------------------------------------------------------------------------


def _serve_once(handler_cls, port: int, ready_event: threading.Event) -> None:
    class _Reusable(socketserver.ThreadingTCPServer):
        allow_reuse_address = True

        def __init__(self, addr, h):
            super().__init__(addr, h)
            ready_event.set()

    with _Reusable(("127.0.0.1", port), handler_cls) as srv:
        srv.serve_forever(poll_interval=0.05)


class _HealthOKHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"ok")

    def log_message(self, *_args):  # noqa: N802 - silence stderr noise
        return


@pytest.fixture
def live_server():
    ready = threading.Event()
    port = _free_port()
    t = threading.Thread(
        target=_serve_once, args=(_HealthOKHandler, port, ready), daemon=True
    )
    t.start()
    ready.wait(timeout=5)
    try:
        yield port
    finally:
        # daemon thread dies when process exits — that's fine for tests
        pass


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class TestProbeServer:
    def test_returns_true_when_port_is_open(self, live_server):
        assert probe_server(f"http://127.0.0.1:{live_server}", deadline_seconds=2.0)

    def test_returns_false_when_no_server(self):
        port = _free_port()
        # T37: was 0.3s — flaked on slow CI. 1.5s still proves the
        # unreachable-port path is fast, but gives the kernel time
        # to actually attempt the connection.
        assert not probe_server(f"http://127.0.0.1:{port}", deadline_seconds=1.5)


# ---------------------------------------------------------------------------
# run_visual_review — multimodal dispatch
# ---------------------------------------------------------------------------


SCORE_CARD_JSON_BLOCKED = json.dumps(
    {
        "reviewer": "visual",
        "iter": 1,
        "score": 0.6,
        "blockers": [
            "Hero uses gradient not in spec",
            "Inter font used (spec: Fraunces)",
        ],
        "suggestions": ["Reduce card border-radius from 8px to spec's 4px"],
        "evidence": "score-cards/task-1/screenshots/00-home.png shows the gradient",
    }
)


SCORE_CARD_JSON_PASS = json.dumps(
    {
        "reviewer": "visual",
        "iter": 2,
        "score": 0.92,
        "blockers": [],
        "suggestions": ["Consider slight tightening of line-height in hero"],
        "evidence": "All four screens match 006-ui-spec.md at score-cards/...",
    }
)


class FakeAdapter:
    """Stand-in for an AdapterBase that records attachments and returns canned JSON."""

    def __init__(self, raw: str):
        self.raw = raw
        self.calls = []

    def run_with_attachments(self, prompt, attachments, *, model, cwd, timeout):
        self.calls.append(
            {
                "prompt": prompt,
                "attachments": list(attachments),
                "model": model,
                "cwd": str(cwd),
                "timeout": timeout,
            }
        )
        return AgentResult(
            stdout=self.raw,
            stderr="",
            exit_code=0,
            usage=Usage(input_tokens=10, output_tokens=20, total_tokens=30),
            duration_ms=42,
        )

    def run(self, *args, **kwargs):  # pragma: no cover — visual reviewer uses the multimodal path
        raise AssertionError("non-multimodal run() should not be called by visual reviewer")


@pytest.fixture
def fake_screenshot(tmp_path):
    p = tmp_path / "screenshots" / "00-home.png"
    p.parent.mkdir(parents=True)
    p.write_bytes(b"\x89PNG\r\n\x1a\n")
    return [p]


class TestRunVisualReview:
    def test_parses_pass_card(self, fake_screenshot, tmp_path):
        adapter = FakeAdapter(SCORE_CARD_JSON_PASS)
        card, _usage = run_visual_review(
            adapter,
            model="claude-sonnet-5",
            spec_text="## Pages\n- /\n",
            diff_text="",
            changed_files=[],
            screenshots=fake_screenshot,
            worktree_path=tmp_path,
            iter_num=2,
            reviewer_prompt=tmp_path / "visual.md",
        )
        assert isinstance(card, ScoreCard)
        assert card.reviewer == "visual"
        assert card.iter == 2
        assert card.score == 0.92
        assert card.blockers == []

    def test_parses_blocker_card_and_preserves_blockers(self, fake_screenshot, tmp_path):
        adapter = FakeAdapter(SCORE_CARD_JSON_BLOCKED)
        card, _usage = run_visual_review(
            adapter,
            model="claude-sonnet-5",
            spec_text="## Pages\n- /\n",
            diff_text="",
            changed_files=[],
            screenshots=fake_screenshot,
            worktree_path=tmp_path,
            iter_num=1,
            reviewer_prompt=tmp_path / "visual.md",
        )
        assert card.score == 0.6
        assert "Inter" in card.blockers[1]

    def test_strips_markdown_fences(self, fake_screenshot, tmp_path):
        raw = "```json\n" + SCORE_CARD_JSON_PASS + "\n```"
        adapter = FakeAdapter(raw)
        card, _usage = run_visual_review(
            adapter,
            model="claude-sonnet-5",
            spec_text="",
            diff_text="",
            changed_files=[],
            screenshots=fake_screenshot,
            worktree_path=tmp_path,
            iter_num=1,
            reviewer_prompt=tmp_path / "v.md",
        )
        assert card.score == 0.92

    def test_unparseable_returns_blocker_card(self, fake_screenshot, tmp_path):
        adapter = FakeAdapter("this response has no JSON at all")
        card, _usage = run_visual_review(
            adapter,
            model="claude-sonnet-5",
            spec_text="",
            diff_text="",
            changed_files=[],
            screenshots=fake_screenshot,
            worktree_path=tmp_path,
            iter_num=1,
            reviewer_prompt=tmp_path / "v.md",
        )
        assert card.score == 0.0
        assert any("unparseable JSON" in b for b in card.blockers)

    def test_adapter_not_implemented_returns_blocker(self, tmp_path):
        # Adapter that explicitly raises NotImplementedError on
        # ``run_with_attachments`` — the same contract AdapterBase
        # declares by default — should yield a blocker card, not a crash.
        class NoMultimodalAdapter:
            def run_with_attachments(self, *args, **kwargs):
                raise NotImplementedError("no multimodal here")

            def run(self, *args, **kwargs):
                raise AssertionError("non-multimodal run() should not be called by visual reviewer")

        adapter = NoMultimodalAdapter()
        card, _usage = run_visual_review(
            adapter,
            model="claude-sonnet-5",
            spec_text="",
            diff_text="",
            changed_files=[],
            screenshots=[],
            worktree_path=tmp_path,
            iter_num=1,
            reviewer_prompt=tmp_path / "v.md",
        )
        assert card.score == 0.0
        assert any("unavailable" in b for b in card.blockers)

    def test_attachments_forwarded_to_adapter(self, fake_screenshot, tmp_path):
        adapter = FakeAdapter(SCORE_CARD_JSON_PASS)
        # T29: ``run_visual_review`` now returns ``(ScoreCard, Usage)``;
        # we ignore the return here because this test only asserts on
        # the adapter's recorded call args.
        _card, _usage = run_visual_review(
            adapter,
            model="claude-sonnet-5",
            spec_text="x",
            diff_text="y",
            changed_files=["src/index.html"],
            screenshots=fake_screenshot,
            worktree_path=tmp_path,
            iter_num=1,
            reviewer_prompt=tmp_path / "v.md",
        )
        assert len(adapter.calls) == 1
        call = adapter.calls[0]
        assert call["attachments"] == fake_screenshot
        assert "Spec" in call["prompt"]
        assert "src/index.html" in call["prompt"]


# ---------------------------------------------------------------------------
# screenshots_dir_for
# ---------------------------------------------------------------------------


def test_screenshots_dir_for_normalises_task_id(tmp_path):
    p = screenshots_dir_for(tmp_path, "task-1")
    assert p == tmp_path / "score-cards" / "task-1" / "screenshots"


def test_screenshots_dir_for_id_without_prefix(tmp_path):
    p = screenshots_dir_for(tmp_path, "7")
    assert p == tmp_path / "score-cards" / "task-7" / "screenshots"


# ---------------------------------------------------------------------------
# Inner-loop dispatch: visual reviewer routes through _run_visual_reviewer
# when task kind is ui.
# ---------------------------------------------------------------------------


class TestInnerLoopVisualDispatch:
    def test_visual_reviewer_dispatch_routes_through_multimodal(self, tmp_path):
        """Smoke: dispatching the 'visual' reviewer name goes through
        ``run_visual_review`` and writes a multimodal score card.

        Uses a fully mocked adapter to skip any real model call.
        """
        from harness.inner_loop import _run_visual_reviewer
        from harness.router import ModelSpec

        captured = MagicMock()
        captured.run_with_attachments = MagicMock(
            return_value=AgentResult(
                stdout=SCORE_CARD_JSON_PASS,
                stderr="",
                exit_code=0,
                usage=Usage(),
                duration_ms=10,
            )
        )

        router = MagicMock()
        router.resolve.return_value = ModelSpec(model="mock-model", tier="reviewer")

        card, usage = _run_visual_reviewer(
            adapter=captured,
            router=router,
            worktree_path=tmp_path,
            project_dir=tmp_path,
            task_id="task-99",
            spec_text="## Pages\n- /\n",
            diff_text="",
            changed_files=["src/index.html"],
            iter_num=1,
            screenshots=[],
            prompt_path=tmp_path / "visual.md",
        )
        assert card.reviewer == "visual"
        assert card.iter == 1
        assert card.score == 0.92
        captured.run_with_attachments.assert_called_once()

    def test_inner_loop_uses_screenshots_when_kind_is_ui(self, tmp_path):
        """Top-level proof that run_inner_loop pre-captures screenshots
        only for ui tasks and forwards them to run_reviewers_parallel.

        We mock everything expensive: worktree helpers, generator,
        reviewers, capture. The whole point is to confirm the wiring,
        not the rendering.
        """
        import subprocess
        from harness.inner_loop import LoopConfig, run_inner_loop
        from harness.router import ModelSpec

        repo = tmp_path / "project"
        repo.mkdir()
        subprocess.run(["git", "init", "-b", "main"], cwd=repo, capture_output=True)
        subprocess.run(["git", "config", "user.email", "t@t"], cwd=repo, capture_output=True)
        subprocess.run(["git", "config", "user.name", "T"], cwd=repo, capture_output=True)
        (repo / "README.md").write_text("init")
        subprocess.run(["git", "add", "."], cwd=repo, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "init"], cwd=repo, capture_output=True, text=True
        )
        (repo / "004-spec.md").write_text("Spec content")
        (repo / "003-task-queue.json").write_text(json.dumps(
            {
                "tasks": [
                    {
                        "id": "task-1",
                        "name": "Build the UI",
                        "status": "pending",
                        "dependencies": [],
                        "kind": "ui",
                    }
                ]
            }
        ))

        adapter = MagicMock()
        adapter.run.return_value = AgentResult(
            stdout="implemented", stderr="", exit_code=0, usage=Usage()
        )
        router = MagicMock()
        router.resolve.return_value = ModelSpec(model="m", tier="worker")
        router.record = MagicMock()

        captured_screenshots = [tmp_path / "shot.png"]
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(
                "harness.inner_loop.create_worktree",
                lambda *_a, **_kw: repo,
            )
            mp.setattr("harness.inner_loop.merge_worktree", lambda *_a, **_kw: None)
            mp.setattr("harness.inner_loop.capture_ui_screenshots", lambda **_kw: captured_screenshots)
            captured_parallel_args = {}

            def fake_parallel(*args, **kwargs):
                captured_parallel_args.update(kwargs)
                return ([ScoreCard(iter=1, reviewer="correctness", score=0.9)], [Usage()])

            mp.setattr("harness.inner_loop.run_reviewers_parallel", fake_parallel)

            run_inner_loop(
                project_dir=repo,
                task_id="task-1",
                spec_text="spec",
                task_kind="ui",
                adapter=adapter,
                router=router,
                config=LoopConfig(max_iterations=1),
            )

        assert captured_parallel_args["screenshots"] == captured_screenshots
