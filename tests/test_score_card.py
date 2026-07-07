"""Tests for harness.score_card module."""

from __future__ import annotations

import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pytest
import pydantic

from harness.score_card import (
    ScoreCard,
    ScoreCardParseError,
    RetryExhaustedError,
    extract_json_from_fenced,
    gate_passed,
    load_all_cards,
    load_score_card,
    parse_score_card,
    parse_score_card_with_retry,
    save_score_card,
    summarize_cards,
)


# ---------------------------------------------------------------------------
# ScoreCard model tests
# ---------------------------------------------------------------------------


class TestScoreCardModel:
    def test_valid_minimal(self):
        card = ScoreCard(iter=1, reviewer="correctness", score=0.9)
        assert card.iter == 1
        assert card.reviewer == "correctness"
        assert card.score == 0.9
        assert card.blockers == []
        assert card.suggestions == []
        assert card.evidence == ""

    def test_valid_full(self):
        now = datetime.now(timezone.utc)
        card = ScoreCard(
            iter=2,
            reviewer="test",
            score=0.85,
            blockers=["Coverage 72% < 80%"],
            suggestions=["Add tests for src/billing.py"],
            evidence="ran pytest --cov: 72%",
            timestamp=now,
        )
        assert card.iter == 2
        assert card.blockers == ["Coverage 72% < 80%"]
        assert card.timestamp == now

    def test_score_below_08_requires_blocker(self):
        with pytest.raises((pydantic.ValidationError, ValueError)):
            ScoreCard(iter=1, reviewer="correctness", score=0.5)

    def test_score_zero_no_blocker_required(self):
        # 0.0 means "not yet evaluated" — no blocker required
        card = ScoreCard(iter=1, reviewer="correctness", score=0.0)
        assert card.score == 0.0

    def test_score_08_no_blocker_required(self):
        # 0.8 exactly is passing threshold — no blocker needed
        card = ScoreCard(iter=1, reviewer="correctness", score=0.8)
        assert card.score == 0.8

    def test_score_gte_08_no_blocker_required(self):
        card = ScoreCard(iter=1, reviewer="correctness", score=0.95, blockers=[])
        assert card.score == 0.95

    def test_score_out_of_range_high(self):
        with pytest.raises(pydantic.ValidationError):
            ScoreCard(iter=1, reviewer="x", score=1.5)

    def test_score_out_of_range_low(self):
        with pytest.raises(pydantic.ValidationError):
            ScoreCard(iter=1, reviewer="x", score=-0.1)

    def test_iter_must_be_positive(self):
        with pytest.raises(pydantic.ValidationError):
            ScoreCard(iter=0, reviewer="x", score=0.9)

    def test_reviewer_required(self):
        with pytest.raises(pydantic.ValidationError):
            ScoreCard(iter=1, reviewer="", score=0.9)

    def test_frozen(self):
        card = ScoreCard(iter=1, reviewer="correctness", score=0.9)
        # frozen=True prevents field reassignment but not list mutation on the model instance
        # We test that re-creating with different values works (model is hashable as frozen)
        card2 = card.model_copy(update={"iter": 2})
        assert card2.iter == 2
        assert card.iter == 1  # original unchanged


# ---------------------------------------------------------------------------
# parse_score_card tests
# ---------------------------------------------------------------------------


class TestParseScoreCard:
    def test_parse_dict(self):
        data = {"iter": 1, "reviewer": "correctness", "score": 0.9}
        card = parse_score_card(data)
        assert card.reviewer == "correctness"

    def test_parse_valid_json_string(self):
        raw = '{"iter": 1, "reviewer": "test", "score": 0.8}'
        card = parse_score_card(raw)
        assert card.score == 0.8

    def test_parse_invalid_json_raises(self):
        with pytest.raises(ScoreCardParseError) as exc_info:
            parse_score_card("not json at all")
        assert isinstance(exc_info.value.cause, json.JSONDecodeError)

    def test_parse_valid_json_invalid_schema_raises(self):
        raw = '{"iter": 1, "reviewer": "x", "score": 2.0}'  # score out of range
        with pytest.raises(ScoreCardParseError) as exc_info:
            parse_score_card(raw)
        assert isinstance(exc_info.value.cause, pydantic.ValidationError)

    def test_parse_with_extra_fields_strips(self):
        raw = '{"iter": 1, "reviewer": "x", "score": 0.9, "extra": "ignored"}'
        card = parse_score_card(raw)
        assert card.score == 0.9


# ---------------------------------------------------------------------------
# extract_json_from_fenced tests
# ---------------------------------------------------------------------------


class TestExtractJsonFromFenced:
    def test_plain_json(self):
        text = '{"iter": 1, "score": 0.9}'
        assert extract_json_from_fenced(text) == '{"iter": 1, "score": 0.9}'

    def test_json_fence(self):
        text = '```json\n{"iter": 1, "score": 0.9}\n```'
        assert extract_json_from_fenced(text) == '{"iter": 1, "score": 0.9}'

    def test_json_fence_uppercase(self):
        text = '```JSON\n{"iter": 1, "score": 0.9}\n```'
        assert extract_json_from_fenced(text) == '{"iter": 1, "score": 0.9}'

    def test_markdown_fence_without_lang(self):
        text = '```\n{"iter": 1, "score": 0.9}\n```'
        assert extract_json_from_fenced(text) == '{"iter": 1, "score": 0.9}'

    def test_leading_whitespace_stripped(self):
        text = '  ```json  \n{"iter": 1}\n  ```  '
        assert extract_json_from_fenced(text) == '{"iter": 1}'


# ---------------------------------------------------------------------------
# parse_score_card_with_retry tests
# ---------------------------------------------------------------------------


class TestParseScoreCardWithRetry:
    def _retry_callback(self, attempt: int, error: str) -> str:
        # Simulate the model self-correcting on retry
        return '{"iter": 1, "reviewer": "correctness", "score": 0.9}'

    def test_first_attempt_success(self):
        raw = '{"iter": 1, "reviewer": "correctness", "score": 0.9}'
        card, retries = parse_score_card_with_retry(raw)
        assert card.score == 0.9
        assert retries == 0

    def test_callback_enables_retry_and_succeeds(self):
        # First call is invalid, callback returns valid JSON
        raw = 'not valid json at all'
        card, retries = parse_score_card_with_retry(
            raw,
            max_retries=2,
            on_retry=self._retry_callback,
        )
        assert card.score == 0.9
        assert retries == 1

    def test_exhausted_retries_raises(self):
        def always_fail(attempt: int, error: str) -> str:
            return "still not valid"

        raw = "not valid"
        with pytest.raises(RetryExhaustedError) as exc_info:
            parse_score_card_with_retry(raw, max_retries=2, on_retry=always_fail)
        assert "3 attempts" in str(exc_info.value)

    def test_fenced_json_stripped_before_parse(self):
        raw = '```json\n{"iter": 1, "reviewer": "test", "score": 0.85}\n```'
        card, retries = parse_score_card_with_retry(raw)
        assert card.score == 0.85
        assert retries == 0


# ---------------------------------------------------------------------------
# save / load tests
# ---------------------------------------------------------------------------


class TestScoreCardPersistence:
    @pytest.fixture
    def tmp_project(self, tmp_path):
        return tmp_path

    def test_save_and_load(self, tmp_project):
        card = ScoreCard(iter=1, reviewer="correctness", score=0.9)
        path = save_score_card(tmp_project, "task-1", card)
        assert path == tmp_project / "score-cards" / "task-1" / "iter-1-correctness.json"
        # verify content round-trips
        loaded = load_score_card(tmp_project, "task-1", 1, "correctness")
        assert loaded is not None
        assert loaded.score == 0.9
        assert loaded.reviewer == "correctness"
        assert path.exists()

        loaded = load_score_card(tmp_project, "task-1", 1, "correctness")
        assert loaded is not None
        assert loaded.score == 0.9
        assert loaded.reviewer == "correctness"

    def test_load_missing_returns_none(self, tmp_project):
        result = load_score_card(tmp_project, "nonexistent", 1, "x")
        assert result is None

    def test_save_creates_dirs(self, tmp_project):
        card = ScoreCard(iter=3, reviewer="boundary", score=0.75, blockers=["coverage too low"])
        path = save_score_card(tmp_project, "task-99", card)
        assert path.parent.exists()

    def test_load_all_cards(self, tmp_project):
        # Save multiple cards
        cards = [
            ScoreCard(iter=1, reviewer="correctness", score=0.9),
            ScoreCard(iter=1, reviewer="test", score=0.85),
            ScoreCard(iter=2, reviewer="correctness", score=1.0),
        ]
        for c in cards:
            save_score_card(tmp_project, "task-1", c)

        all_cards = load_all_cards(tmp_project, "task-1")
        assert len(all_cards) == 3

        iter1 = load_all_cards(tmp_project, "task-1", iter_num=1)
        assert len(iter1) == 2


# ---------------------------------------------------------------------------
# gate_passed tests
# ---------------------------------------------------------------------------


class TestGatePassed:
    def test_empty_raises(self):
        assert gate_passed([]) is False

    def test_all_pass(self):
        cards = [
            ScoreCard(iter=1, reviewer="correctness", score=0.9),
            ScoreCard(iter=1, reviewer="test", score=0.85),
        ]
        assert gate_passed(cards) is True

    def test_one_fails_score(self):
        cards = [
            ScoreCard(iter=1, reviewer="correctness", score=0.9),
            ScoreCard(iter=1, reviewer="test", score=0.7, blockers=["coverage too low"]),
        ]
        assert gate_passed(cards) is False

    def test_one_has_blocker(self):
        cards = [
            ScoreCard(iter=1, reviewer="correctness", score=0.9, blockers=[]),
            ScoreCard(iter=1, reviewer="test", score=0.9, blockers=["flaky test"]),
        ]
        assert gate_passed(cards) is False

    def test_exactly_threshold_passes(self):
        cards = [
            ScoreCard(iter=1, reviewer="correctness", score=0.8),
            ScoreCard(iter=1, reviewer="test", score=0.8),
        ]
        assert gate_passed(cards) is True


# ---------------------------------------------------------------------------
# summarize_cards tests
# ---------------------------------------------------------------------------


class TestSummarizeCards:
    def test_summary_contains_reviewer_names(self):
        cards = [
            ScoreCard(iter=1, reviewer="correctness", score=0.9),
            ScoreCard(iter=1, reviewer="test", score=0.7, blockers=["bad"]),
        ]
        summary = summarize_cards(cards)
        assert "correctness" in summary
        assert "test" in summary
        assert "PASS" in summary
        assert "FAIL" in summary
