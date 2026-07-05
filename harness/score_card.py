"""Score card schema, validation, and persistence.

Per MASTER-PLAN §5.2 — score cards are structured JSON with schema validation.
On validation failure the harness retries the same model (max 2 times),
then switches to the fallback model for that tier.
"""

from __future__ import annotations

import json
import textwrap
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Optional

import pydantic


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class ScoreCardVersion(str, Enum):
    """Version marker for forward compatibility."""

    V1 = "v1"


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class ScoreCard(pydantic.BaseModel):
    """Single reviewer score card.

    Attributes
    ----------
    iter : int
        Iteration number within the inner loop (1-based).
    reviewer : str
        Reviewer identifier, e.g. "correctness", "test", "boundary".
    score : float
        Quality score in [0.0, 1.0].  Gate requires >= 0.8.
    blockers : list[str]
        List of blocking issues. Empty list means no blockers.
    suggestions : list[str]
        Non-blocking improvement suggestions.
    evidence : str
        Raw output or citation supporting the assessment
        (e.g. "ran `npm test` — all 23 tests passed").
    timestamp : datetime
        When this card was produced.
    version : ScoreCardVersion
        Schema version marker.
    """

    model_config = pydantic.ConfigDict(frozen=True)

    iter: int = pydantic.Field(ge=1, description="Iteration number (1-based)")
    reviewer: str = pydantic.Field(min_length=1, description="Reviewer identifier")
    score: float = pydantic.Field(ge=0.0, le=1.0, description="Quality score 0.0–1.0")
    blockers: list[str] = pydantic.Field(default_factory=list)
    suggestions: list[str] = pydantic.Field(default_factory=list)
    evidence: str = pydantic.Field(default="")
    timestamp: datetime = pydantic.Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    version: ScoreCardVersion = ScoreCardVersion.V1

    @pydantic.model_validator(mode="after")
    def _check_blockers_consistency(self) -> "ScoreCard":
        """Score < 0.8 implies at least one blocker unless score is 0.0 (not yet evaluated)."""
        if 0.0 < self.score < 0.8 and not self.blockers:
            raise ValueError("Score < 0.8 requires at least one blocker entry")
        return self


# ---------------------------------------------------------------------------
# Parsing / validation with retry semantics
# ---------------------------------------------------------------------------


class ScoreCardParseError(Exception):
    """Raised when a score card string cannot be parsed or validated."""

    def __init__(self, raw: str, cause: Exception):
        super().__init__(f"Failed to parse score card: {cause}")
        self.raw = raw
        self.cause = cause


def parse_score_card(raw: str | dict) -> ScoreCard:
    """Parse and validate a score card from raw JSON string or dict.

    Parameters
    ----------
    raw
        JSON string or already-parsed dict.

    Returns
    -------
    ScoreCard
        Validated instance.

    Raises
    ------
    ScoreCardParseError
        If the input cannot be parsed into a valid ScoreCard.
    """
    if isinstance(raw, str):
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ScoreCardParseError(raw, exc) from exc
    else:
        data = raw

    try:
        return ScoreCard.model_validate(data)
    except pydantic.ValidationError as exc:
        raise ScoreCardParseError(raw, exc) from exc


def extract_json_from_fenced(text: str) -> str:
    """Strip markdown code fences from a string and return the inner JSON.

    Handles both ````json`...``` and plain (unfenced) JSON.
    """
    text = text.strip()
    # Strip opening fence if present
    for fence in ("```json", "```JSON", "```"):
        if text.startswith(fence):
            text = text[len(fence) :]
            # Strip the closing fence too
            if text.rstrip().endswith("```"):
                text = text[: text.rstrip().rfind("```")].rstrip()
            break
    return text.strip()


# ---------------------------------------------------------------------------
# Score card persistence
# ---------------------------------------------------------------------------


def get_score_card_dir(project_dir: Path, task_id: str) -> Path:
    """Return the directory path for a task's score cards."""
    # Normalise "task-1" → "1" to avoid "task-task-1"
    safe_id = task_id.removeprefix("task-")
    return project_dir / "score-cards" / f"task-{safe_id}"


def save_score_card(
    project_dir: Path,
    task_id: str,
    card: ScoreCard,
) -> Path:
    """Write a score card to disk.

    File path: ``score-cards/task-{id}/iter-{n}-{reviewer}.json``

    Creates parent directories as needed.
    """
    dir_path = get_score_card_dir(project_dir, task_id)
    dir_path.mkdir(parents=True, exist_ok=True)

    filename = f"iter-{card.iter}-{card.reviewer}.json"
    file_path = dir_path / filename

    raw = card.model_dump(mode="json")
    # version is already a string after model_dump(mode="json")

    file_path.write_text(json.dumps(raw, indent=2) + "\n")
    return file_path


def load_score_card(
    project_dir: Path,
    task_id: str,
    iter_num: int,
    reviewer: str,
) -> Optional[ScoreCard]:
    """Load a single score card from disk."""
    file_path = get_score_card_dir(project_dir, task_id) / f"iter-{iter_num}-{reviewer}.json"
    if not file_path.exists():
        return None
    try:
        return parse_score_card(json.loads(file_path.read_text()))
    except ScoreCardParseError:
        return None


def load_all_cards(
    project_dir: Path,
    task_id: str,
    iter_num: Optional[int] = None,
) -> list[ScoreCard]:
    """Load all score cards for a task, optionally filtered by iteration."""
    dir_path = get_score_card_dir(project_dir, task_id)
    if not dir_path.exists():
        return []

    cards = []
    for fp in dir_path.iterdir():
        if fp.suffix != ".json":
            continue
        # Parse iter-X-reviewer.json
        stem = fp.stem  # e.g. "iter-2-correctness"
        parts = stem.split("-")
        if len(parts) < 3 or parts[0] != "iter":
            continue
        try:
            card_iter = int(parts[1])
        except ValueError:
            continue
        if iter_num is not None and card_iter != iter_num:
            continue
        try:
            card = parse_score_card(json.loads(fp.read_text()))
            cards.append(card)
        except ScoreCardParseError:
            continue
    return cards


# ---------------------------------------------------------------------------
# Gate logic
# ---------------------------------------------------------------------------


def gate_passed(cards: list[ScoreCard], pass_threshold: float = 0.8) -> bool:
    """Return True when all score cards pass the gate.

    Gate criteria (all must hold):
    1. Every card has score >= pass_threshold
    2. Every card has an empty blockers list
    3. At least one card is present
    """
    if not cards:
        return False
    return all(
        card.score >= pass_threshold and not card.blockers for card in cards
    )


def summarize_cards(cards: list[ScoreCard]) -> str:
    """Render a human-readable summary of score cards for commit messages."""
    lines = ["Score card summary", "=" * 50, ""]
    for card in cards:
        status = "✅ PASS" if (card.score >= 0.8 and not card.blockers) else "❌ FAIL"
        lines.append(
            f"  [{card.reviewer}] iter={card.iter}  score={card.score:.2f}  {status}"
        )
        if card.blockers:
            for b in card.blockers:
                lines.append(f"    BLOCKER: {b}")
        if card.suggestions:
            for s in card.suggestions[:3]:
                lines.append(f"    SUGGESTION: {s}")
    lines.append("")
    lines.append(f"Overall: {'PASS ✅' if gate_passed(cards) else 'FAIL ❌'}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Retry helper
# ---------------------------------------------------------------------------


class RetryExhaustedError(Exception):
    """Raised when all retry attempts for a score card have been exhausted."""

    def __init__(self, attempts: int, last_error: str):
        super().__init__(
            f"Failed to produce a valid score card after {attempts} attempts: {last_error}"
        )


def parse_score_card_with_retry(
    raw: str,
    *,
    max_retries: int = 2,
    on_retry: Optional[callable] = None,
) -> tuple[ScoreCard, int]:
    """Parse a score card with automatic retry on validation failure.

    On the first failure, the same model is asked to fix its output.
    After ``max_retries`` failures, raises ``RetryExhaustedError``.

    Parameters
    ----------
    raw
        The raw text to parse (may contain markdown fences).
    max_retries
        Maximum number of repair attempts (default 2).
    on_retry
        Optional callback ``(attempt: int, error: str) -> str`` that returns
        the corrected text. If not provided, the function extracts JSON from
        the original text and tries again (useful when the model self-corrects
        in a second pass).

    Returns
    -------
    tuple[ScoreCard, int]
        The parsed card and the number of retry attempts made.

    Raises
    ------
    RetryExhaustedError
        If parsing fails after all retry attempts.
    """
    attempts = 0

    # Strip fences first — the model may have wrapped JSON in ```json ... ```
    cleaned = extract_json_from_fenced(raw)

    while attempts <= max_retries:
        attempts += 1
        try:
            card = parse_score_card(cleaned)
            return card, attempts - 1
        except ScoreCardParseError as exc:
            last_error = str(exc.cause)

        if attempts > max_retries:
            break

        if on_retry is not None:
            cleaned = on_retry(attempts, last_error)
        # else: with no callback, we just re-try the stripped text once
        # (the model is expected to self-correct on the next LLM call)

    raise RetryExhaustedError(attempts, last_error)
