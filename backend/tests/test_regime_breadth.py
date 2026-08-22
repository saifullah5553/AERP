"""Breadth must measure the MARKET, not our opinion of it."""

from __future__ import annotations

import json

from app.ingestion import price_pack
from app.services.regime_snapshot import _breadth_signal, _index_from_pack


def _seed(tmp_path, monkeypatch, region, series):
    monkeypatch.setattr(price_pack, "PACK_DIR", tmp_path)
    price_pack._CACHE.clear()
    price_pack._VOL_CACHE.clear()
    price_pack.merge_series(region, series)


def _rising(n=60, start=100.0, step=1.0):
    return {f"2026-{(i // 28) + 1:02d}-{(i % 28) + 1:02d}": start + i * step for i in range(n)}


def _falling(n=60, start=200.0, step=1.0):
    return {f"2026-{(i // 28) + 1:02d}-{(i % 28) + 1:02d}": start - i * step for i in range(n)}


def test_breadth_is_percent_above_the_50_day_not_our_score(tmp_path, monkeypatch) -> None:
    """The defect: breadth was the mean COMPOSITE SCORE, so it measured how much our engine
    liked a market's companies. Dubai has the highest median fundamental score we publish and
    was therefore reported Bullish on a signal that could not disagree with us."""
    _seed(tmp_path, monkeypatch, "dfm",
          {f"UP{i}": _rising() for i in range(15)} | {f"DN{i}": _falling() for i in range(15)})
    rows = [{"symbol": f"UP{i}", "asset_class": "equity", "composite_score": 99.0}
            for i in range(15)]
    rows += [{"symbol": f"DN{i}", "asset_class": "equity", "composite_score": 99.0}
             for i in range(15)]

    sig = _breadth_signal(rows, "dfm")
    assert sig is not None
    # Half the market is above its average, so breadth is ~50 - NOT the 99 every one of these
    # companies scores fundamentally. If this ever returns ~99 again, breadth has gone back to
    # reading our own scores.
    assert 40 <= sig["score"] <= 60, sig
    assert "above 50-day" in sig["value"]
    assert "composite" not in (sig.get("source") or "")


def test_breadth_reflects_a_falling_market(tmp_path, monkeypatch) -> None:
    _seed(tmp_path, monkeypatch, "gcc", {f"DN{i}": _falling() for i in range(25)})
    rows = [{"symbol": f"DN{i}", "asset_class": "equity"} for i in range(25)]
    sig = _breadth_signal(rows, "gcc")
    assert sig is not None and sig["score"] == 0.0


def test_breadth_reflects_a_rising_market(tmp_path, monkeypatch) -> None:
    _seed(tmp_path, monkeypatch, "us", {f"UP{i}": _rising() for i in range(25)})
    rows = [{"symbol": f"UP{i}", "asset_class": "equity"} for i in range(25)]
    sig = _breadth_signal(rows, "us")
    assert sig is not None and sig["score"] == 100.0


def test_a_market_too_small_to_measure_returns_nothing(tmp_path, monkeypatch) -> None:
    """No signal is honest; a signal built on three companies is not."""
    _seed(tmp_path, monkeypatch, "dfm", {f"UP{i}": _rising() for i in range(3)})
    rows = [{"symbol": f"UP{i}", "asset_class": "equity"} for i in range(3)]
    assert _breadth_signal(rows, "dfm") is None


def test_index_trend_falls_back_to_the_stored_series(tmp_path, monkeypatch) -> None:
    """^KSE100 and DFMGI.AE have never had a screener row, so the lookup found nothing and the
    merge kept a stale value - Pakistan published a 26 July reading in mid-August."""
    _seed(tmp_path, monkeypatch, "global", {"DFMGI.AE": _rising(n=250)})
    sig = _index_from_pack("DFMGI.AE")
    assert sig is not None
    assert sig["score"] == 100.0            # at the top of its own range
    assert "52-week range" in sig["source"]

    price_pack._CACHE.clear()
    _seed(tmp_path, monkeypatch, "global", {"^KSE100": _falling(n=250, start=500.0)})
    sig = _index_from_pack("^KSE100")
    assert sig is not None and sig["score"] == 0.0
