"""Quota-hold persistence for T16d.

When the pipeline runs out of quota on every available tier it must
(1) record what is waiting so the operator can inspect it, and
(2) hand off the wake-up responsibility to an OS-level scheduler.

This module owns the on-disk side of (1): ``.runner/quota-hold.json``
inside the project directory. The wake-up scheduling itself lives in
``harness.scheduler``.

Public API::

    from harness.quota_hold import QuotaHold, write_hold, read_hold, clear_hold

    hold = QuotaHold(
        tier="worker", provider="MiniMax",
        exhausted_at=datetime.now(timezone.utc),
        resume_at=datetime.now(timezone.utc) + timedelta(hours=5),
        strategy="fixed_clock",
        project_dir=Path("/abs/proj"),
        phase="develop", task_id="task-1",
        job_id="harness-1234abcd",
    )
    write_hold(project_dir, hold)
    restored = read_hold(project_dir)
    clear_hold(project_dir)
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Optional

import pydantic

from harness.atomic_io import AtomicIOError, atomic_write_json, read_json_or_raise


HOLD_RELATIVE_PATH = Path(".runner") / "quota-hold.json"


class QuotaHold(pydantic.BaseModel):
    """A single pending quota wake-up for one project.

    The fields are deliberately small and stringly-typed where it
    helps portability: ``strategy`` is the strategy name (so the
    wake-up side can re-construct the same ``next_reset`` math) and
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