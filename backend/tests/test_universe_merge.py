from __future__ import annotations

import csv
from pathlib import Path

import app.ingestion.expand_universe as eu


def _write_list(tmp_path: Path, region: str, rows: list[tuple[str, str]]) -> None:
    d = tmp_path / "universe"
    d.mkdir(parents=True, exist_ok=True)
    with open(d / f"{region}.csv", "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["symbol", "name"])
        w.writerows(rows)


def test_listed_symbols_restore_exchange_spelling(tmp_path, monkeypatch) -> None:
    _write_list(tmp_path, "india", [("BAJAJ_AUTO", "Bajaj Auto"), ("RELIANCE", "Reliance")])
    monkeypatch.setattr(eu, "_LISTED_DIR", tmp_path / "universe")

    got = {r["symbol"]: r["provider_symbol"] for r in eu.fetch_listed_symbols("india")}
    # The rest of the platform and the price feeds use NSE's spelling, not stockanalysis's.
    assert got == {"BAJAJ-AUTO": "BAJAJ-AUTO.NS", "RELIANCE": "RELIANCE.NS"}


def test_merge_adds_only_genuinely_new_names(tmp_path, monkeypatch) -> None:
    _write_list(tmp_path, "india", [("RELIANCE", "Reliance"), ("NEWCO", "New Co")])
    monkeypatch.setattr(eu, "_LISTED_DIR", tmp_path / "universe")

    feed = [{"symbol": "RELIANCE", "name": "Reliance Industries", "market_code": "NSE",
             "region": "india", "provider_symbol": "RELIANCE.NS"}]
    rows = eu._merged("india", lambda: list(feed))()

    assert [r["symbol"] for r in rows] == ["RELIANCE", "NEWCO"]
    # The exchange feed's name wins for names present in both.
    assert rows[0]["name"] == "Reliance Industries"


def test_ampersand_ticker_is_not_duplicated(tmp_path, monkeypatch) -> None:
    # stockanalysis collapses BOTH '-' and '&' to '_', so ARE_M cannot be told apart from NSE's
    # ARE&M by spelling. Matching literally would add a second, wrongly-named row for a company
    # we already have - and a duplicate company is far harder to spot than a missing one.
    _write_list(tmp_path, "india", [("ARE_M", "Are And M"), ("M_M", "Mahindra")])
    monkeypatch.setattr(eu, "_LISTED_DIR", tmp_path / "universe")

    feed = [
        {"symbol": "ARE&M", "name": "ARE&M Ltd", "market_code": "NSE",
         "region": "india", "provider_symbol": "ARE&M.NS"},
        {"symbol": "M&M", "name": "Mahindra & Mahindra", "market_code": "NSE",
         "region": "india", "provider_symbol": "M&M.NS"},
    ]
    rows = eu._merged("india", lambda: list(feed))()

    assert [r["symbol"] for r in rows] == ["ARE&M", "M&M"]


def test_missing_list_file_is_harmless(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(eu, "_LISTED_DIR", tmp_path / "nothing-here")
    feed = [{"symbol": "RELIANCE", "name": "R", "market_code": "NSE",
             "region": "india", "provider_symbol": "RELIANCE.NS"}]
    assert eu._merged("india", lambda: list(feed))() == feed
