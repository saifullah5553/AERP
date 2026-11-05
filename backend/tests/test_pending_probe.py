"""A throttled probe must not read as "nothing new".

On 5 Nov 2026 it reported 94 US companies pending while Apple, Microsoft and JPMorgan all had a
quarter we did not hold, because a 429 was treated the same as an empty answer.
"""

from __future__ import annotations

from datetime import date

import httpx
import pytest
from app.ingestion import pending_results as pr


def _client(status: int, body: str = "") -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(
        lambda request: httpx.Response(status, text=body)))


@pytest.mark.parametrize("status", [403, 429])
def test_a_refusal_raises_rather_than_reading_as_no_page(status: int) -> None:
    with pytest.raises(pr.Throttled):
        pr.newest_at_source("us", "AAPL", _client(status))


def test_a_genuine_missing_page_is_still_none() -> None:
    assert pr.newest_at_source("us", "NOPE", _client(404)) is None


def test_the_newest_period_is_read_from_the_page() -> None:
    assert pr.newest_at_source("us", "AAPL", _client(200, 'datekey:["2026-09-26"')) == "2026-09-26"


def test_an_unconfirmed_company_is_assumed_due_only_when_old_enough() -> None:
    today = date(2026, 11, 5)
    assert pr.assume_due("2026-06-30", today)
    assert not pr.assume_due("2026-09-30", today)
    assert pr.assume_due(None, today)


def test_throttled_names_old_enough_are_kept_on_the_list(monkeypatch, tmp_path) -> None:
    held = {"OLD": "2026-03-31", "NEW": "2026-09-30", "GOOD": "2026-06-30"}

    def source(region, symbol, client):
        if symbol == "GOOD":
            return "2026-09-30"
        raise pr.Throttled("429")

    monkeypatch.setattr(pr, "held_periods", lambda region, store: held)
    monkeypatch.setattr(pr, "newest_at_source", source)
    monkeypatch.setattr(pr, "due_for_probe", lambda h, today, *a: True)
    monkeypatch.setattr(pr, "COOLDOWN_SECONDS", 0.0)
    monkeypatch.setattr(pr, "PROBE_ATTEMPTS", 1)
    pending, seen = pr.probe_for_new_quarters("us", list(held), tmp_path, pause=0, workers=1)
    assert "GOOD" in pending
    assert "OLD" in pending, "a refusal must not hide a company this stale"
    assert "NEW" not in pending
