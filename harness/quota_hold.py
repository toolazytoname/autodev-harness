"""Quota-hold persistence + observability + guardrails for T16d/T16e.

T16d delivered the on-disk format and the OS-level scheduler helpers.
T16e layers the operator surface on top:

- ``resume_count`` field — track how many auto-resumes have happened.
- ``MAX_AUTO_RESUME`` — cap on consecutive auto-resumes before we
  escalate to a human instead of looping forever on a quota that
  never recovers.
- ``begin_resume()`` — called at the start of ``--continue`` to read
  any prior hold, enforce the cap, and clear the file so the pipeline
  can re-run from a clean slate.
- ``enter_quota_hold()`` — the T16d flow wired into a single callable:
  persist the hold + register an OS wake-up + return the path.
- ``format_hold_status()`` — human-readable status string (used by
  both ``harness status`` and ``harness quota-status``).
- ``cancel_pending_hold()`` — cancel the OS wake-up + delete the file
  (the ``--cancel-hold`` CLI flag calls this).
- ``QuotaResumeExhaustedError`` — raised by ``begin_resume`` when the
  cap is hit. Subclasses ``QuotaExhaustedError`` so existing
  catch-and-retry paths still recognise it.

Public API::

    from harness.quota_hold import (
        MAX_AUTO_RESUME, HOLD_RELATIVE_PATH,
        QuotaHold, QuotaResumeExhaustedError,
        write_hold, read_hold, clear_hold,
        begin_resume, enter_quota_hold, cancel_pending_hold,
        format_hold_status,
    )
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import pydantic

from harness.adapters.base import AdapterError, QuotaExhaustedError
from harness.atomic_io import AtomicIOError, atomic_write_json, read_json_or_raise
from harness.scheduler import cancel_wakeup, register_wakeup


HOLD_RELATIVE_PATH = Path(".runner") / "quota-hold.json"

# Maximum number of consecutive auto-resumes before we escalate to a
# human. Quota that never recovers (e.g. an exhausted monthly plan)
# would otherwise spin forever — each resume eats a wake-up cycle and
# the operator gets no signal that anything is wrong.
MAX_AUTO_RESUME: int = 3


class QuotaHold(pydantic.BaseModel):
    """A single pending quota wake-up for one project.

    Fields are deliberately small and stringly-typed where it helps
    portability: ``strategy`` is the strategy name (so the wake-up
    side can re-construct the same ``next_reset`` math) and
    ``job_id`` is the OS scheduler's identifier (so the wake-up side
    can correlate with whatever launchd / systemd timer it owns).
    """

    model_config = pydantic.ConfigDict(frozen=True)

    tier: str
    provider: str
    exhausted_at: datetime
    resume_at: datetime
    strategy: str
    project_dir: Path
    phase: Optional[str] = None
    task_id: Optional[str] = None
    job_id: str
    resume_count: int = 0


class QuotaResumeExhaustedError(QuotaExhaustedError):
    """Auto-resume hit the cap — operator must intervene manually.

    Subclasses :class:`QuotaExhaustedError` so existing catch blocks
    recognise it; the ``__main__`` handler special-cases this subclass
    to print the escalation message and exit with a distinct code.
    """


# ---------------------------------------------------------------------------
# File I/O
# ---------------------------------------------------------------------------


def _hold_path(project_dir: Path) -> Path:
    return project_dir / HOLD_RELATIVE_PATH


def write_hold(project_dir: Path, hold: QuotaHold) -> Path:
    """Persist ``hold`` atomically (T17) under ``.runner/quota-hold.json``.

    Returns the file path. Creates ``.runner/`` if missing.
    """
    path = _hold_path(project_dir)
    path.parent.mkdir(parents=True, exist_ok=True)

    # serialise: datetime → ISO string, Path → str (so the JSON is
    # portable across machines and survives the round-trip).
    payload = hold.model_dump(mode="json")
    atomic_write_json(path, payload)
    return path


def read_hold(project_dir: Path) -> Optional[QuotaHold]:
    """Return the on-disk ``QuotaHold`` or ``None`` when absent.

    A present-but-corrupt file raises :class:`AtomicIOError` so the
    operator doesn't silently believe "no quota issue".
    """
    path = _hold_path(project_dir)
    if not path.exists():
        return None
    raw = read_json_or_raise(path)
    # project_dir was serialised as a string; round-trip it back.
    if isinstance(raw.get("project_dir"), str):
        raw["project_dir"] = Path(raw["project_dir"])
    try:
        return QuotaHold.model_validate(raw)
    except pydantic.ValidationError as exc:
        raise AtomicIOError(
            f"quota-hold at {path} has invalid schema: {exc}",
            path=path,
            cause=exc,
        ) from exc


def clear_hold(project_dir: Path) -> bool:
    """Remove the on-disk ``quota-hold.json``.

    Returns True when a file was removed, False when there was nothing
    to clear. Never raises on missing files.
    """
    path = _hold_path(project_dir)
    if not path.exists():
        return False
    path.unlink()
    return True


# ---------------------------------------------------------------------------
# T16e: resume lifecycle + guardrails + OS integration
# ---------------------------------------------------------------------------


def begin_resume(
    project_dir: Path,
    *,
    max_auto_resume: int = MAX_AUTO_RESUME,
) -> int:
    """Read the prior hold, enforce the cap, clear it, return the next count.

    Called at the start of ``python -m harness --continue <project>``.

    Returns
    -------
    int
        The ``resume_count`` value the next ``QuotaHold`` should carry:
        ``0`` when no prior hold exists, otherwise ``prior.resume_count + 1``.

    Raises
    ------
    QuotaResumeExhaustedError
        When the prior hold's ``resume_count`` is already at or above
        ``max_auto_resume``. The on-disk hold is preserved so the
        operator can inspect or ``--cancel-hold`` it.
    """
    hold = read_hold(project_dir)
    if hold is None:
        return 0
    if hold.resume_count >= max_auto_resume:
        raise QuotaResumeExhaustedError(
            f"quota auto-resume hit cap ({max_auto_resume}) for project "
            f"{project_dir}: tier={hold.tier} provider={hold.provider} "
            f"resume_at={hold.resume_at.isoformat()}. Manual intervention "
            f"required — cancel with --cancel-hold or wait for quota reset.",
            tier=hold.tier,
            provider=hold.provider,
            reset_hint=f"resume_at={hold.resume_at.isoformat()}",
        )
    next_count = hold.resume_count + 1
    clear_hold(project_dir)
    return next_count


def enter_quota_hold(
    project_dir: Path,
    exc: QuotaExhaustedError,
    *,
    resume_count: int = 0,
    phase: Optional[str] = None,
    task_id: Optional[str] = None,
    strategy_params: Optional[dict] = None,
) -> Path:
    """Persist a fresh hold + register an OS-level wake-up.

    Composes T16d's ``write_hold`` + ``register_wakeup`` into a single
    callable that the pipeline / inner_loop invoke when they've
    decided to suspend rather than die.

    The next ``resume_count`` comes from :func:`begin_resume` (passed
    in by the caller) so we don't accidentally reset the counter on
    each auto-resume.

    Returns the path to the written ``quota-hold.json``.
    """
    from harness.quota import next_reset, ResetHint, ResetStrategy

    # Pick the right strategy from the held config; default to rolling
    # so a missing strategy still produces a sane wake-up time.
    strategy = ResetStrategy.ROLLING
    params = dict(strategy_params or {"window_hours": 5})
    hint = ResetHint(
        reset_at=exc.reset_hint if (exc.reset_hint and "T" in (exc.reset_hint or "")) else None,
        retry_after_seconds=exc.retry_after_seconds,
    ) if exc.reset_hint or exc.retry_after_seconds else None

    resume_at = next_reset(
        strategy,
        now=datetime.now(timezone.utc),
        strategy_params=params,
        hint=hint,
    )

    # Job id is unique per project_dir; same project reuses it so the
    # scheduler replaces the prior pending job instead of stacking.
    import hashlib
    digest = hashlib.sha1(str(project_dir.resolve()).encode("utf-8")).hexdigest()[:12]
    job_id = f"harness-{digest}"

    hold = QuotaHold(
        tier=exc.tier or "unknown",
        provider=exc.provider or "unknown",
        exhausted_at=datetime.now(timezone.utc),
        resume_at=resume_at,
        strategy=strategy.value,
        project_dir=project_dir,
        phase=phase,
        task_id=task_id,
        job_id=job_id,
        resume_count=resume_count,
    )
    path = write_hold(project_dir, hold)

    # Register the OS-level wake-up. The scheduler is best-effort; a
    # registration failure must not stop us from returning the path so
    # the operator can still inspect (or cancel) the hold.
    try:
        resume_cmd = f'python -m harness --continue "{project_dir}"'
        register_wakeup(
            at=resume_at,
            command=resume_cmd,
            job_id=job_id,
        )
    except Exception:
        # Don't propagate — the hold file itself is the source of truth.
        pass

    return path


def cancel_pending_hold(project_dir: Path) -> bool:
    """Cancel the OS wake-up + delete the on-disk hold.

    Returns True when there was a hold to clear, False when nothing
    existed. Never raises on missing files or missing wake-ups.
    """
    hold = read_hold(project_dir)
    if hold is None:
        return False
    try:
        cancel_wakeup(job_id=hold.job_id)
    except Exception:
        # Best-effort; the on-disk clear below is what actually matters.
        pass
    return clear_hold(project_dir)


def format_hold_status(hold: QuotaHold, *, now: Optional[datetime] = None) -> str:
    """Render a one-paragraph, human-readable hold summary.

    Used by ``harness status`` and ``harness quota-status``.
    """
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    delta = hold.resume_at - now
    seconds = int(delta.total_seconds())
    if seconds <= 0:
        countdown = "due now"
    elif seconds < 60:
        countdown = f"in {seconds}s"
    elif seconds < 3600:
        countdown = f"in {seconds // 60}m {seconds % 60:02d}s"
    elif seconds < 86400:
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        countdown = f"in {hours}h {minutes}m"
    else:
        days = seconds // 86400
        hours = (seconds % 86400) // 3600
        countdown = f"in {days}d {hours}h"

    resume_local = hold.resume_at.astimezone().strftime("%Y-%m-%d %H:%M %Z")
    lines = [
        "Quota hold:",
        f"  tier:        {hold.tier}",
        f"  provider:    {hold.provider}",
        f"  resume at:   {resume_local} ({countdown})",
        f"  resume count: {hold.resume_count} / {MAX_AUTO_RESUME}",
    ]
    if hold.phase or hold.task_id:
        where_parts = []
        if hold.phase:
            where_parts.append(f"phase={hold.phase}")
        if hold.task_id:
            where_parts.append(f"task={hold.task_id}")
        lines.append(f"  context:     {', '.join(where_parts)}")
    return "\n".join(lines)