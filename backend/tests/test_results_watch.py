from __future__ import annotations

import gzip
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from app.ingestion.results_watch import announced, pick


def _today() -> str:
    return datetime.now(UTC).date().isoformat()


def _days_ago(n: int) -> str:
    return (datetime.now(UTC).date() - timedelta(days=n)).isoformat()


def _snapshot(tmp_path: Path, catalysts: dict, news: dict) -> Path:
    d = tmp_path / "data"
    d.mkdir(parents=True, exist_ok=True)
    (d / "catalysts.json").write_text(json.dumps(catalysts), encoding="utf-8")
    (d / "news.json").write_text(json.dumps(news), encoding="utf-8")
    return d


def _store(tmp_path: Path, companies: dict) -> Path:
    s = tmp_path / "store"
    s.mkdir(parents=True, exist_ok=True)
    payload = {"version": 1, "region": "us", "currency": "USD", "suffix": "",
               "companies": companies}
    with gzip.open(s / "us.json.gz", "wt", encoding="utf-8") as fh:
        json.dump(payload, fh)
    return s


def test_announcement_sources_are_unioned(tmp_path: Path) -> None:
    data = _snapshot(
        tmp_path,
        {"by_symbol": {"PSXCO": [{"title": "Board Meeting - Financial Results",
                                  "date": _today()}]}},
        {"items": [{"symbol": "NEWSCO", "title": "Reports Q1 Earnings Results",
                    "published_at": _today()}]},
    )
    hits = announced(data, days=3)
    assert set(hits) == {"PSXCO", "NEWSCO"}


def test_old_and_unrelated_announcements_are_ignored(tmp_path: Path) -> None:
    data = _snapshot(
        tmp_path,
        {"by_symbol": {"OLD": [{"title": "Annual Results", "date": _days_ago(30)}]}},
        {"items": [{"symbol": "NOISE", "title": "Appoints new chief marketing officer",
                    "published_at": _today()}]},
    )
    assert announced(data, days=3) == {}


def test_pick_skips_companies_whose_figures_we_already_hold(tmp_path: Path) -> None:
    # The announcement is an echo of a period already in the store. Without this the job would
    # re-download the same table every day for the whole look-back window.
    data = _snapshot(
        tmp_path,
        {"by_symbol": {"COVERED": [{"title": "Quarterly Results", "date": _today()}]}},
        {"items": []},
    )
    store = _store(tmp_path, {"COVERED": {"periods": [_days_ago(40)]}})
    assert pick(data, store, days=3, backstop=0) == []


def test_pick_selects_a_company_that_just_reported(tmp_path: Path) -> None:
    data = _snapshot(
        tmp_path,
        {"by_symbol": {"FRESH": [{"title": "Quarterly Results", "date": _today()}]}},
        {"items": []},
    )
    # Newest stored period long predates the announcement, so the new figures are not in yet.
    store = _store(tmp_path, {"FRESH": {"periods": [_days_ago(200)]}})
    assert pick(data, store, days=3, backstop=0) == ["FRESH"]


def test_backstop_covers_markets_with_no_announcement_feed(tmp_path: Path) -> None:
    # India and Australia have no feed we can rely on. Without the quota they would drift
    # indefinitely while the job reported success every day.
    data = _snapshot(tmp_path, {"by_symbol": {}}, {"items": []})
    store = _store(tmp_path, {"AGED": {"periods": [_days_ago(400)]}})
    assert pick(data, store, days=3, backstop=5) == ["AGED"]


def test_pick_respects_the_cap(tmp_path: Path) -> None:
    data = _snapshot(tmp_path, {"by_symbol": {}}, {"items": []})
    store = _store(tmp_path, {f"S{i}": {"periods": [_days_ago(400)]} for i in range(30)})
    assert len(pick(data, store, days=3, backstop=25, cap=10)) == 10
