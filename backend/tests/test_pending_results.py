"""The pending list must not miss a filer.

Its whole reason for existing is that the announcement feed did: catalysts.json is a rolling
window, and asked which PSX companies had reported it named 17 when 50 had.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

from app.ingestion.pending_results import (
    announced_recently,
    read_pending,
    write_pending,
)


def _catalysts(tmp_path, entries: dict[str, list[tuple[str, str]]]):
    payload = {"by_symbol": {sym: [{"date": d, "title": t} for d, t in evs]
                            for sym, evs in entries.items()}}
    (tmp_path / "catalysts.json").write_text(json.dumps(payload), encoding="utf-8")
    return tmp_path


def _days_ago(n: int) -> str:
    return (datetime.now(UTC).date() - timedelta(days=n)).isoformat()


def test_only_results_shaped_announcements_inside_the_window_count(tmp_path) -> None:
    d = _catalysts(tmp_path, {
        "FRESH": [(_days_ago(1), "Financial Results For The Quarter Ended 2026-06-30")],
        "OLD": [(_days_ago(40), "Financial Results For The Year Ended June 30, 2026")],
        "NOISE": [(_days_ago(1), "Change of Registered Office Address")],
    })
    out = announced_recently(d, "psx", days=5)
    assert out == {"FRESH"}


def test_a_board_meeting_counts_because_results_usually_follow(tmp_path) -> None:
    """Deliberately loose: a missed filer costs a stale quarter, a false positive costs a page
    load. The asymmetry is the whole design."""
    d = _catalysts(tmp_path, {"ACPL": [(_days_ago(2), "Board Meeting")]})
    assert announced_recently(d, "psx", days=5) == {"ACPL"}


def test_the_window_actually_bounds_it(tmp_path) -> None:
    d = _catalysts(tmp_path, {"X": [(_days_ago(6), "Financial Results")]})
    assert announced_recently(d, "psx", days=5) == set()
    assert announced_recently(d, "psx", days=10) == {"X"}


def test_a_missing_or_broken_feed_is_empty_not_an_error(tmp_path) -> None:
    assert announced_recently(tmp_path, "psx", days=5) == set()
    (tmp_path / "catalysts.json").write_text("{not json", encoding="utf-8")
    assert announced_recently(tmp_path, "psx", days=5) == set()


def test_the_file_round_trips_and_ignores_comments(monkeypatch, tmp_path) -> None:
    import app.ingestion.pending_results as mod

    monkeypatch.setattr(mod, "PENDING_DIR", tmp_path)
    write_pending("psx", {"HBL", "ubl", "NESTLE"}, note="written by a test")
    got = read_pending("psx")
    assert got == ["HBL", "NESTLE", "UBL"]          # sorted, upper-cased, header skipped
    assert (tmp_path / "psx.txt").read_text(encoding="utf-8").startswith("#")


def test_an_absent_file_reads_as_empty(monkeypatch, tmp_path) -> None:
    import app.ingestion.pending_results as mod

    monkeypatch.setattr(mod, "PENDING_DIR", tmp_path)
    assert read_pending("nowhere") == []
