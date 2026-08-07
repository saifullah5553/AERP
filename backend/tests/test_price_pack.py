"""The packed closes must be a drop-in for the raw CSVs, because CI has only the pack."""

from __future__ import annotations

import gzip
import json

import pytest
from app.ingestion import ohlc_store, price_pack


def _bar(date, close, **rest):
    return {"date": date, "open": 10.0, "high": 11.0, "low": 9.5, "close": close,
            "volume": 1000, **rest}


BARS = [_bar("2026-07-27", 10.5), _bar("2026-07-28", 11.25), _bar("2026-07-29", 0.4809615)]


@pytest.fixture()
def packed(tmp_path, monkeypatch):
    """A raw store with one symbol, packed, then the raw store taken away - CI's situation."""
    monkeypatch.setattr(price_pack, "PACK_DIR", tmp_path / "prices")
    price_pack._CACHE.clear()
    ohlc_store.save_bars("psx", "LUCK", BARS, store=tmp_path / "ohlc")
    price_pack.pack_region("psx", store=tmp_path / "ohlc")
    monkeypatch.setattr(ohlc_store, "STORE", tmp_path / "gone")
    return tmp_path


def test_load_bars_falls_back_to_the_pack(packed):
    bars = ohlc_store.load_bars("psx", "LUCK")
    assert len(bars) == 3, "the pack is what CI prices from; empty here means zero trades there"
    # HEADER order must survive: callers index [4] for the close.
    assert bars["2026-07-28"][4] == 11.25
    assert bars["2026-07-28"][0] == "2026-07-28"


def test_absent_columns_are_none_not_invented(packed):
    row = ohlc_store.load_bars("psx", "LUCK")["2026-07-27"]
    assert row[1] is row[2] is row[3] is row[5] is None, \
        "open/high/low/volume are not carried - a close wearing a high's name is worse than a gap"


def test_seven_significant_figures_not_four_decimals(packed):
    """Decimal rounding cost a published DFM return a basis point on a sub-1.0 price."""
    assert ohlc_store.load_bars("psx", "LUCK")["2026-07-29"][4] == 0.4809615


def test_unknown_symbol_is_empty_never_an_exception(packed):
    assert ohlc_store.load_bars("psx", "NOSUCH") == {}
    assert ohlc_store.load_bars("dfm", "LUCK") == {}


def test_pack_reflects_a_later_write(tmp_path, monkeypatch):
    """Re-packing must invalidate the cache, or a run prices on the bars it loaded first."""
    monkeypatch.setattr(price_pack, "PACK_DIR", tmp_path / "prices")
    price_pack._CACHE.clear()
    ohlc_store.save_bars("psx", "LUCK", BARS, store=tmp_path / "ohlc")
    price_pack.pack_region("psx", store=tmp_path / "ohlc")
    assert len(price_pack.load_packed("psx")["LUCK"]) == 3

    ohlc_store.save_bars("psx", "LUCK",
                         [*BARS, _bar("2026-07-30", 12.0)],
                         store=tmp_path / "ohlc")
    price_pack.pack_region("psx", store=tmp_path / "ohlc")
    assert price_pack.load_packed("psx")["LUCK"]["2026-07-30"] == 12.0


def test_junk_rows_are_dropped_not_carried(tmp_path, monkeypatch):
    monkeypatch.setattr(price_pack, "PACK_DIR", tmp_path / "prices")
    price_pack._CACHE.clear()
    ohlc_store.save_bars("psx", "LUCK", [
        _bar("2026-07-27", ""),      # no close
        _bar("2026-07-28", 0),       # a zero close is not a price
        _bar("2026-07-29", "abc"),   # unparseable
        _bar("2026-07-30", 10.0),
    ], store=tmp_path / "ohlc")
    price_pack.pack_region("psx", store=tmp_path / "ohlc")
    assert price_pack.load_packed("psx")["LUCK"] == {"2026-07-30": 10.0}


def test_packing_on_ci_does_not_erase_history(tmp_path, monkeypatch):
    """CI holds almost no CSVs. Packing there must ADD to the stored history, never replace it.

    This is the whole point of the merge: a runner that refreshed twenty symbols must not
    publish a pack containing only those twenty.
    """
    monkeypatch.setattr(price_pack, "PACK_DIR", tmp_path / "prices")
    price_pack._CACHE.clear()
    # Five years, this machine.
    ohlc_store.save_bars("psx", "LUCK", BARS, store=tmp_path / "ohlc")
    ohlc_store.save_bars("psx", "ENGRO", BARS, store=tmp_path / "ohlc")
    price_pack.pack_region("psx", store=tmp_path / "ohlc")

    # Now CI: an empty raw store, one symbol refreshed with one new day.
    ohlc_store.save_bars("psx", "LUCK", [_bar("2026-07-30", 12.0)], store=tmp_path / "ci")
    price_pack.pack_region("psx", store=tmp_path / "ci")

    packed = price_pack.load_packed("psx")
    assert set(packed) == {"LUCK", "ENGRO"}, "a symbol nobody refreshed lost its history"
    assert packed["ENGRO"] == {"2026-07-27": 10.5, "2026-07-28": 11.25, "2026-07-29": 0.4809615}
    assert packed["LUCK"]["2026-07-30"] == 12.0, "the new day is missing"
    assert packed["LUCK"]["2026-07-27"] == 10.5, "the old days were dropped"


def test_dates_are_stored_ascending(tmp_path, monkeypatch):
    monkeypatch.setattr(price_pack, "PACK_DIR", tmp_path / "prices")
    price_pack._CACHE.clear()
    ohlc_store.save_bars("psx", "LUCK", [_bar("2026-07-30", 12.0)], store=tmp_path / "ohlc")
    price_pack.pack_region("psx", store=tmp_path / "ohlc")
    ohlc_store.save_bars("psx", "LUCK", [_bar("2026-07-28", 11.0)], store=tmp_path / "ci")
    price_pack.pack_region("psx", store=tmp_path / "ci")
    with gzip.open(tmp_path / "prices" / "psx.json.gz", "rt", encoding="utf-8") as fh:
        days = json.load(fh)["LUCK"]["d"]
    assert days == sorted(days)


def test_a_csv_close_wins_over_the_stored_one(tmp_path, monkeypatch):
    """A date present in both takes the CSV's price - that is how a split re-base propagates.

    save_bars re-writes a symbol's WHOLE series when the vendor re-bases it, so every date of a
    split-adjusted company arrives here and overwrites; without this precedence the pack would
    keep the pre-split prices and re-create the cliff that read as an 88.9% loss.
    """
    monkeypatch.setattr(price_pack, "PACK_DIR", tmp_path / "prices")
    price_pack._CACHE.clear()
    ohlc_store.save_bars("psx", "LUCK", [_bar("2026-07-28", 100.0)], store=tmp_path / "ohlc")
    price_pack.pack_region("psx", store=tmp_path / "ohlc")
    assert price_pack.load_packed("psx")["LUCK"]["2026-07-28"] == 100.0

    csv_dir = tmp_path / "rebased" / "psx"
    csv_dir.mkdir(parents=True)
    (csv_dir / "LUCK.csv").write_text(
        "date,open,high,low,close,volume\n2026-07-28,1,1,1,10.0,1\n", encoding="utf-8")
    price_pack.pack_region("psx", store=tmp_path / "rebased")
    assert price_pack.load_packed("psx")["LUCK"]["2026-07-28"] == 10.0


def test_missing_pack_is_empty_not_a_crash(tmp_path, monkeypatch):
    monkeypatch.setattr(price_pack, "PACK_DIR", tmp_path / "nothing")
    price_pack._CACHE.clear()
    assert price_pack.load_packed("psx") == {}


def test_corrupt_pack_is_empty_not_a_crash(tmp_path, monkeypatch):
    monkeypatch.setattr(price_pack, "PACK_DIR", tmp_path / "prices")
    price_pack._CACHE.clear()
    (tmp_path / "prices").mkdir()
    with gzip.open(tmp_path / "prices" / "psx.json.gz", "wb") as fh:
        fh.write(b"{not json")
    assert price_pack.load_packed("psx") == {}


def test_filename_substitutions_survive_the_round_trip(tmp_path, monkeypatch):
    """Forex tickers contain '/', which the CSV writer maps - the lookup must map it too."""
    monkeypatch.setattr(price_pack, "PACK_DIR", tmp_path / "prices")
    price_pack._CACHE.clear()
    ohlc_store.save_bars("global", "EUR/USD", BARS, store=tmp_path / "ohlc")
    price_pack.pack_region("global", store=tmp_path / "ohlc")
    monkeypatch.setattr(ohlc_store, "STORE", tmp_path / "gone")
    assert len(ohlc_store.load_bars("global", "EUR/USD")) == 3


def test_the_pack_counts_as_bars_for_the_ledger(tmp_path, monkeypatch):
    """_has_bars gates a rebuild. If the pack did not count, CI could never add a quarter."""
    from app.ingestion import rebalance_ledger

    monkeypatch.setattr(price_pack, "PACK_DIR", tmp_path / "prices")
    monkeypatch.setattr(ohlc_store, "STORE", tmp_path / "gone")
    price_pack._CACHE.clear()
    assert rebalance_ledger._has_bars("psx") is False

    (tmp_path / "prices").mkdir()
    with gzip.open(tmp_path / "prices" / "psx.json.gz", "wb") as fh:
        fh.write(json.dumps({"LUCK": {"d": ["2026-07-27"], "c": [10.0]}}).encode())
    assert rebalance_ledger._has_bars("psx") is True
