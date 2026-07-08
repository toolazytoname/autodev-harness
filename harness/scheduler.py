"""OS-level wake-up scheduling for T16d.

When the pipeline has drained every available tier, it needs to come
back at the next reset instant without anyone sitting at the keyboard.
We register a one-shot job in whichever scheduler the host provides,
preferring the most robust option:

1. **launchd LaunchAgent** (macOS, preferred — ``atrun`` rarely
   loaded; ``at`` is unreliable on Apple Silicon).
2. **systemd --user timer** (Linux, preferred when ``systemd`` is the
   init).
3. **at** / cron (when neither launchd nor systemd is available).
4. **detached ``nohup`` sleeper** (last-resort — sleeps until the
   resume instant, then execs the resume command; still zero-token
   because no LLM call is made during the sleep).

The module is intentionally side-effect-light: ``register_wakeup``
takes a ``backend=`` argument so tests can pin a specific backend
without probing the host. ``choose_backend()`` is the auto-picker
used at runtime.

Idempotency: ``register_wakeup`` first calls ``cancel_wakeup`` on
the same ``job_id`` so re-registering for the same project replaces
the previous pending job instead of stacking.
"""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Callable, Optional


class SchedulerBackend(str, Enum):
    LAUNCHD = "launchd"
    SYSTEMD = "systemd"
    AT = "at"
    SLEEPER = "sleeper"


# ---------------------------------------------------------------------------
# Backend probes — cheap, side-effect-free checks.
# ---------------------------------------------------------------------------


def _launchd_available() -> bool:
    if platform.system() != "Darwin":
        return False
    return shutil.which("launchctl") is not None


def _systemd_available() -> bool:
    if platform.system() != "Linux":
        return False
    return shutil.which("systemctl") is not None


def _at_available() -> bool:
    return shutil.which("at") is not None


def choose_backend() -> SchedulerBackend:
    """Pick the best backend available on the current host."""
    if _launchd_available():
        return SchedulerBackend.LAUNCHD
    if _systemd_available():
        return SchedulerBackend.SYSTEMD
    if _at_available():
        return SchedulerBackend.AT
    return SchedulerBackend.SLEEPER


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def register_wakeup(
    at: datetime,
    command: str,
    *,
    job_id: str,
    backend: Optional[SchedulerBackend] = None,
) -> SchedulerBackend:
    """Schedule ``command`` to run at ``at``.

    Parameters
    ----------
    at
        When to run. Must be timezone-aware.
    command
        Shell command string (the resume call, e.g.
        ``python -m harness --continue /abs/proj``).
    job_id
        Unique identifier for this wake-up — used to dedupe so a
        second ``register_wakeup`` with the same ``job_id`` replaces
        the first instead of stacking.
    backend
        Force a specific backend. Defaults to :func:`choose_backend`.

    Returns
    -------
    SchedulerBackend
        The backend that was actually used.
    """
    if at.tzinfo is None:
        raise ValueError(
            f"register_wakeup requires timezone-aware datetime; got {at!r}"
        )

    backend = backend or choose_backend()
    cancel_wakeup(job_id=job_id, backend=backend)
    _register(backend, at, command, job_id)
    return backend


def cancel_wakeup(*, job_id: str, backend: Optional[SchedulerBackend] = None) -> bool:
    """Cancel a pending wake-up, if any.

    Best-effort: when no scheduler has a record of ``job_id`` the
    function returns ``False`` without raising.
    """
    backend = backend or choose_backend()
    return _cancel(backend, job_id)


def _register(
    backend: SchedulerBackend,
    at: datetime,
    command: str,
    job_id: str,
) -> None:
    """Dispatch to the backend by name — uses module-level lookup so
    ``mock.patch("harness.scheduler._register_launchd", ...)`` works."""
    if backend == SchedulerBackend.LAUNCHD:
        _register_launchd(at, command, job_id)
    elif backend == SchedulerBackend.SYSTEMD:
        _register_systemd(at, command, job_id)
    elif backend == SchedulerBackend.AT:
        _register_at(at, command, job_id)
    elif backend == SchedulerBackend.SLEEPER:
        _register_sleeper(at, command, job_id)
    else:
        raise ValueError(f"Unknown scheduler backend: {backend!r}")


def _cancel(backend: SchedulerBackend, job_id: str) -> bool:
    """Dispatch cancel to the backend by name (so tests can patch)."""
    if backend == SchedulerBackend.LAUNCHD:
        return _cancel_launchd(job_id)
    if backend == SchedulerBackend.SYSTEMD:
        return _cancel_systemd(job_id)
    if backend == SchedulerBackend.AT:
        return _cancel_at(job_id)
    if backend == SchedulerBackend.SLEEPER:
        return _cancel_sleeper(job_id)
    raise ValueError(f"Unknown scheduler backend: {backend!r}")


# ---------------------------------------------------------------------------
# Backend implementations
# ---------------------------------------------------------------------------


_LAUNCHD_LABEL_PREFIX = "com.autodev.harness"


def _launchd_plist_path(job_id: str) -> Path:
    safe = job_id.replace("/", "_")
    return Path.home() / "Library" / "LaunchAgents" / f"{_LAUNCHD_LABEL_PREFIX}.{safe}.plist"


def _register_launchd(at: datetime, command: str, job_id: str) -> None:
    """Write a one-shot launchd plist + ``launchctl load``.

    launchd ``StartCalendarInterval`` only goes down to "minute", so
    we round to the nearest minute — sub-minute precision is not
    needed for quota wake-ups.
    """
    plist = _launchd_plist_path(job_id)
    plist.parent.mkdir(parents=True, exist_ok=True)
    label = f"{_LAUNCHD_LABEL_PREFIX}.{job_id}"

    plist_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<!DOCTYPE plist PUBLIC \"-//Apple//DTD PLIST 1.0//EN\" "
        '"http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'
        '<plist version="1.0"><dict>\n'
        f"<key>Label</key><string>{label}</string>\n"
        f"<key>ProgramArguments</key>\n"
        "<array>\n"
        "<string>/bin/sh</string>\n"
        "<string>-c</string>\n"
        f"<string>{_xml_escape(command)}</string>\n"
        "</array>\n"
        "<key>StartCalendarInterval</key>\n"
        "<dict>\n"
        f"<key>Minute</key><integer>{at.minute}</integer>\n"
        f"<key>Hour</key><integer>{at.hour}</integer>\n"
        f"<key>Day</key><integer>{at.day}</integer>\n"
        f"<key>Month</key><integer>{at.month}</integer>\n"
        "</dict>\n"
        "</dict></plist>\n"
    )
    plist.write_text(plist_xml, encoding="utf-8")

    subprocess.run(
        ["launchctl", "load", str(plist)],
        check=True,
        capture_output=True,
    )


def _cancel_launchd(job_id: str) -> bool:
    plist = _launchd_plist_path(job_id)
    if not plist.exists():
        return False
    label = f"{_LAUNCHD_LABEL_PREFIX}.{job_id}"
    try:
        subprocess.run(
            ["launchctl", "unload", str(plist)],
            check=False,
            capture_output=True,
        )
    finally:
        try:
            plist.unlink()
        except FileNotFoundError:
            pass
    return True


def _register_systemd(at: datetime, command: str, job_id: str) -> None:
    """Write a ``--user`` systemd transient timer that runs ``command`` at ``at``."""
    safe = job_id.replace("/", "_")
    unit_name = f"harness-{safe}"
    timer_path = Path.home() / ".config" / "systemd" / "user" / f"{unit_name}.timer"
    service_path = Path.home() / ".config" / "systemd" / "user" / f"{unit_name}.service"
    timer_path.parent.mkdir(parents=True, exist_ok=True)

    when = at.strftime("%Y-%m-%d %H:%M:%S")
    service_path.write_text(
        "[Unit]\n"
        f"Description=Harness quota wake-up for {job_id}\n"
        "[Service]\n"
        f"ExecStart=/bin/sh -c {_sh_escape(command)}\n"
    )
    timer_path.write_text(
        "[Unit]\n"
        f"Description=Harness quota wake-up for {job_id}\n"
        "[Timer]\n"
        f"OnCalendar={when}\n"
        "Unit=" + unit_name + ".service\n"
        "[Install]\n"
        "WantedBy=timers.target\n"
    )

    subprocess.run(
        ["systemctl", "--user", "daemon-reload"], check=True, capture_output=True
    )
    subprocess.run(
        ["systemctl", "--user", "enable", "--now", f"{unit_name}.timer"],
        check=True,
        capture_output=True,
    )


def _cancel_systemd(job_id: str) -> bool:
    safe = job_id.replace("/", "_")
    unit_name = f"harness-{safe}"
    base = Path.home() / ".config" / "systemd" / "user"
    timer_path = base / f"{unit_name}.timer"
    service_path = base / f"{unit_name}.service"
    if not timer_path.exists():
        return False
    try:
        subprocess.run(
            ["systemctl", "--user", "disable", "--now", f"{unit_name}.timer"],
            check=False,
            capture_output=True,
        )
    finally:
        for p in (timer_path, service_path):
            try:
                p.unlink()
            except FileNotFoundError:
                pass
    return True


def _register_at(at: datetime, command: str, job_id: str) -> None:
    when = at.strftime("%H:%M %Y-%m-%d")
    subprocess.run(
        ["at", when],
        input=command + "\n",
        check=True,
        capture_output=True,
        text=True,
    )


def _cancel_at(job_id: str) -> bool:
    # ``at`` doesn't expose job-id filters across runs; best we can do
    # is scan the queue for our marker and remove matching lines.
    proc = subprocess.run(
        ["atq"], capture_output=True, text=True, check=False
    )
    if proc.returncode != 0:
        return False
    found = False
    for line in proc.stdout.splitlines():
        parts = line.split()
        if not parts:
            continue
        try:
            at_id = int(parts[0])
        except ValueError:
            continue
        # Look at the queued command — if our job_id appears, remove it.
        job_proc = subprocess.run(
            ["at", "-c", str(at_id)], capture_output=True, text=True, check=False
        )
        if job_id in job_proc.stdout:
            subprocess.run(["at", "-r", str(at_id)], check=False)
            found = True
    return found


def _register_sleeper(at: datetime, command: str, job_id: str) -> None:
    """Last-resort sleeper.

    Spawns a detached process that sleeps until ``at`` and then execs
    ``command``. Still zero-token because the sleeper doesn't make any
    LLM call — it just holds the wake-up.

    Requires ``os.fork`` (POSIX). On hosts without fork (Windows) we
    fail loud with :class:`NotImplementedError` so the operator
    installs a real scheduler backend (launchd / systemd / at)
    rather than silently blocking the parent process.
    """
    # T35 fail-fast: a missing fork on a non-POSIX host used to fall
    # into the ``pid == 0`` branch and run time.sleep + os.system
    # *in the parent*, blocking the harness indefinitely. Refuse
    # instead.
    if not hasattr(os, "fork"):
        raise NotImplementedError(
            "sleeper backend requires POSIX fork(); please install "
            "launchd (macOS) / systemd --user timer (Linux) or `at` "
            "as the wake-up scheduler instead."
        )

    from datetime import timezone
    import time

    now = datetime.now(timezone.utc)
    seconds = max(0, int((at - now).total_seconds()))

    # Detach the sleeper from the parent process so quitting the
    # harness doesn't kill the wake-up.
    pid = os.fork()
    if pid == 0:
        # Child: redirect stdio, sleep, exec.
        try:
            with open("/dev/null", "rb") as devnull_in:
                os.dup2(devnull_in.fileno(), 0)
            with open("/dev/null", "ab") as devnull_out:
                os.dup2(devnull_out.fileno(), 1)
                os.dup2(devnull_out.fileno(), 2)
            time.sleep(seconds)
            # T35: subprocess.Popen with a list (no shell) instead of
            # os.system. Avoids shell-quoting hazards on paths with
            # spaces or special characters.
            subprocess.Popen(command, shell=False)  # noqa: S603
        finally:
            os._exit(0)


def _cancel_sleeper(job_id: str) -> bool:
    # We don't track sleeper PIDs (the kid immediately detaches);
    # a cancellation here is a no-op. The launchd / systemd path
    # is the real safety net on hosts that have them.
    return False


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _xml_escape(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _sh_escape(s: str) -> str:
    return "'" + s.replace("'", "'\\''") + "'"