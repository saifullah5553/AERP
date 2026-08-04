from __future__ import annotations

import json
import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from app.core.snapshot_lock import LOCK_NAME, MAX_HOLD_MINUTES, snapshot_lock


def test_second_writer_skips_instead_of_blocking(tmp_path) -> None:
    # The whole point: a second writer must return immediately rather than queue. Queuing is
    # what deadlocked the pipeline before.
    with snapshot_lock("first", tmp_path) as a:
        assert a is True
        with snapshot_lock("second", tmp_path) as b:
            assert b is False


def test_lock_is_released_on_exit(tmp_path) -> None:
    with snapshot_lock("writer", tmp_path) as ok:
        assert ok is True
        assert (tmp_path / LOCK_NAME).exists()
    assert not (tmp_path / LOCK_NAME).exists()


def test_lock_is_released_even_when_the_writer_raises(tmp_path) -> None:
    # A crashed writer must not wedge every future run.
    try:
        with snapshot_lock("boom", tmp_path) as ok:
            assert ok is True
            raise RuntimeError("writer failed mid-run")
    except RuntimeError:
        pass
    assert not (tmp_path / LOCK_NAME).exists()


def test_lock_from_a_dead_process_is_broken(tmp_path) -> None:
    # PID 999999 will not exist; the lock is stale and must be taken over.
    (tmp_path / LOCK_NAME).write_text(json.dumps({
        "owner": "ghost", "pid": 999999,
        "started_at": datetime.now(UTC).isoformat(),
    }), encoding="utf-8")
    with snapshot_lock("newcomer", tmp_path) as ok:
        assert ok is True


def test_lock_held_too_long_is_broken(tmp_path) -> None:
    # Our own live PID, but held far past the deadline - the "frozen in network backoff" case.
    (tmp_path / LOCK_NAME).write_text(json.dumps({
        "owner": "wedged", "pid": os.getpid(),
        "started_at": (datetime.now(UTC)
                       - timedelta(minutes=MAX_HOLD_MINUTES + 5)).isoformat(),
    }), encoding="utf-8")
    with snapshot_lock("newcomer", tmp_path) as ok:
        assert ok is True


def test_corrupt_lock_file_is_not_a_lock(tmp_path) -> None:
    (tmp_path / LOCK_NAME).write_text("{not json", encoding="utf-8")
    with snapshot_lock("newcomer", tmp_path) as ok:
        assert ok is True


@pytest.mark.skipif(os.name != "nt", reason="the image-name check is Windows-only by design")
def test_recycled_pid_owned_by_another_program_is_broken(tmp_path) -> None:
    # A live PID, inside the deadline, but the image name does not match the recorded owner.
    # This is the real-world case: the pipeline churns through hundreds of browser processes,
    # Windows hands the dead owner's number to one of them, and a bare PID check then reports
    # the lock as live forever - wedging every scheduled writer behind a process that is gone.
    (tmp_path / LOCK_NAME).write_text(json.dumps({
        "owner": "ghost", "pid": os.getpid(), "exe": "definitely-not-this.exe",
        "started_at": datetime.now(UTC).isoformat(),
    }), encoding="utf-8")
    with snapshot_lock("newcomer", tmp_path) as ok:
        assert ok is True


def test_live_owner_with_matching_exe_still_holds(tmp_path) -> None:
    # The guard above must not make the lock useless: a genuine live holder is respected.
    (tmp_path / LOCK_NAME).write_text(json.dumps({
        "owner": "busy", "pid": os.getpid(), "exe": Path(sys.executable).name,
        "started_at": datetime.now(UTC).isoformat(),
    }), encoding="utf-8")
    with snapshot_lock("newcomer", tmp_path) as ok:
        assert ok is False


def test_recycled_pid_of_the_same_program_is_broken(tmp_path) -> None:
    # The case that actually bit us, and the one the image-name check alone cannot catch: the
    # dead owner's pid now belongs to a *python* process too, and the lock is still inside the
    # deadline. Only start time separates them - this process began well after the lock was
    # written, so it cannot be the writer.
    (tmp_path / LOCK_NAME).write_text(json.dumps({
        "owner": "ghost", "pid": os.getpid(), "exe": Path(sys.executable).name,
        "started_at": (datetime.now(UTC) - timedelta(minutes=10)).isoformat(),
    }), encoding="utf-8")
    with snapshot_lock("newcomer", tmp_path) as ok:
        assert ok is True
