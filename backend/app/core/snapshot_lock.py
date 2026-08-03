"""A single lock for everything that writes the snapshot — with a deadline, so it can't hang.

Three failure modes hit this project in one session and they share a cause: several commands
write frontend/public/data and nothing coordinated them.

  * concurrent writers  - last-writer-wins silently destroyed completed work twice
  * deadlocked waiters  - "wait until no python is running" loops that were themselves python,
                          so they waited on each other forever
  * frozen processes    - a run stuck in yfinance's rate-limit backoff at 0% CPU, holding its
                          turn indefinitely with nothing to break the stall

So the lock is deliberately NOT a blocking mutex. A writer either takes it immediately or gives
up and lets the next scheduled run handle it — nothing ever queues, so nothing can deadlock.
A lock whose owner has died, or which has simply been held too long, is treated as stale and
broken automatically, so a frozen process can't wedge the pipeline permanently.

    with snapshot_lock("refresh-quality") as ok:
        if not ok:
            return {"skipped": "another writer holds the snapshot lock"}
        ...
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from app.core.logging import get_logger

log = get_logger(__name__)

LOCK_NAME = ".snapshot.lock"
# Longest a writer may legitimately hold the lock. The full technical pass over ~11k names is
# the slowest job; beyond this the holder is assumed wedged (e.g. stuck in network backoff).
MAX_HOLD_MINUTES = 90


def _alive(pid: int, exe: str | None = None) -> bool:
    """Is the lock's owner still running?

    A bare PID check is not enough. Windows recycles PIDs aggressively, and this pipeline
    spawns hundreds of short-lived browser processes, so a dead owner's number is very likely
    to be live again as something else - which is exactly how a stale lock survived long enough
    to block a scheduled run. Matching the image name too makes a false "alive" require both a
    recycled PID and the same executable.
    """
    if pid <= 0:
        return False
    try:
        if os.name == "nt":
            out = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}", "/NH", "/FO", "CSV"],
                capture_output=True, text=True, timeout=15,
            ).stdout
            if str(pid) not in out:
                return False
            # First CSV field is the image name: "python.exe","34060",...
            name = out.strip().split('","')[0].lstrip('"').lower() if '","' in out else ""
            return not exe or not name or name == exe.lower()
        os.kill(pid, 0)
    except (OSError, subprocess.SubprocessError, ValueError):
        return False
    return True


def _stale(path: Path) -> bool:
    try:
        info = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return True  # unreadable lock is not a lock

    pid = int(info.get("pid") or 0)
    if not _alive(pid, info.get("exe")):
        log.warning("snapshot lock: owner pid %s is gone - breaking it", pid)
        return True

    started = info.get("started_at")
    try:
        age = (datetime.now(UTC) - datetime.fromisoformat(started)).total_seconds() / 60.0
    except (TypeError, ValueError):
        return True
    if age > MAX_HOLD_MINUTES:
        log.warning(
            "snapshot lock: held %.0f min by %s (pid %s) - assuming wedged, breaking it",
            age, info.get("owner"), pid,
        )
        return True
    return False


@contextmanager
def snapshot_lock(owner: str, data_dir: str | Path) -> Iterator[bool]:
    """Yield True if this process holds the snapshot lock, False if it should skip.

    Never blocks: skipping is always cheaper than risking a deadlock, because every writer
    here runs on a schedule and is resumable.
    """
    path = Path(data_dir) / LOCK_NAME
    held = False
    try:
        if path.exists() and not _stale(path):
            try:
                info = json.loads(path.read_text(encoding="utf-8"))
                other = info.get("owner", "unknown")
            except (OSError, json.JSONDecodeError):
                other = "unknown"
            log.info("snapshot lock held by %s - skipping %s this run", other, owner)
            yield False
            return

        path.write_text(json.dumps({
            "owner": owner, "pid": os.getpid(),
            "exe": Path(sys.executable).name,
            "started_at": datetime.now(UTC).isoformat(),
        }), encoding="utf-8")
        held = True
        yield True
    finally:
        if held:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass
