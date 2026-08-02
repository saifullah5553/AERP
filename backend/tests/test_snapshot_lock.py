from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta

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
