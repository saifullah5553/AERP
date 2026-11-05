from __future__ import annotations

import json
from datetime import UTC, datetime

import numpy as np
from app.engines.composite.signals import derive_signal
from app.ingestion import price_pack, tech_refresh
from app.ingestion.tech_refresh import (
    _MAX_MOVES_PER_RUN,
    _composite_at,
    _on_exchange_closes,
    _record_signal_move,
    _signal_since,
    _signal_value_at,
    _update_signal_moves,
    _withdraw_read,
)

# A rising close series, long enough for the swing walk and the lookback. Close stands in for
# open/high/low, which keeps the expected answers independent of candle shape.
_N = 160
_RISING = np.linspace(100.0, 200.0, _N)
_DATES = [f"2026-{1 + i // 28:02d}-{1 + i % 28:02d}" for i in range(_N)]
_VOL = np.full(_N, 1_000.0)
_LEGS = (70.0, None, None, None)  # fundamental only (PSX names often lack mom/qual/risk)


def test_composite_at_returns_triple() -> None:
    c = _composite_at(_DATES, _RISING, _RISING, _RISING, _RISING, _VOL, _N, _LEGS,
                      None, None)
    assert c is not None
    comp, cov, present = c
    assert isinstance(comp, float)
    assert 0.0 <= comp <= 100.0
    assert "fundamental" in present


def test_signal_at_a_bar_is_the_band_of_the_composite_at_that_bar() -> None:
    c = _composite_at(_DATES, _RISING, _RISING, _RISING, _RISING, _VOL, _N, _LEGS,
                      None, None)
    assert c is not None
    sig = _signal_value_at(_DATES, _RISING, _RISING, _RISING, _RISING, _VOL, _N, _LEGS,
                           None, None)
    assert sig == derive_signal(c[0], c[1], c[2]).signal.value


def test_signal_since_walks_back_over_real_trajectory() -> None:
    """A ramp that only recently crossed into the signal band should date the crossing to a
    recent bar, not the first bar — and the returned close must come from that bar."""
    current = _signal_value_at(_DATES, _RISING, _RISING, _RISING, _RISING, _VOL, _N, _LEGS,
                               None, None)
    dates = [f"2026-01-{i + 1:02d}" if i < 28 else f"2026-idx-{i}" for i in range(_N)]
    since, price_at = _signal_since(
        dates, _RISING, _RISING, _RISING, _RISING, _VOL, _LEGS, None, None, current,
    )
    assert since is not None
    # price_at is a real close from the series (not fabricated).
    assert float(_RISING[0]) <= price_at <= float(_RISING[-1])


def test_record_signal_move_buy_and_exit() -> None:
    # Strong Buy is the only buy zone: entering = buy, leaving = exit (any lower rating).
    dst: dict = {}
    row = {"provider_symbol": "X.KA", "symbol": "X", "name": "X Co", "region": "psx"}
    _record_signal_move(dst, row, "buy", "strong_buy", "Strong Buy", 81.0, 10.0, "2026-08-01")
    assert dst["X.KA"]["direction"] == "buy"
    # strong_buy → hold (clear drop) = exit.
    _record_signal_move(dst, row, "strong_buy", "hold", "Hold", 55.0, 11.0, "2026-08-02")
    assert dst["X.KA"]["direction"] == "sell"
    # strong_buy → buy that fell clearly below 80 IS an exit (buy is outside the zone now).
    dst_sb: dict = {}
    _record_signal_move(dst_sb, row, "strong_buy", "buy", "Buy", 76.0, 11.0, "2026-08-02")
    assert dst_sb["X.KA"]["direction"] == "sell"


def test_record_signal_move_ignores_jitter_and_non_zone_moves() -> None:
    row = {"provider_symbol": "X.KA", "symbol": "X", "name": "X Co", "region": "psx"}
    # strong_buy → buy right on the 80 line (composite > 77) → suppressed as boundary jitter.
    dst: dict = {}
    _record_signal_move(dst, row, "strong_buy", "buy", "Buy", 79.0, 11.0, "2026-08-02")
    assert dst == {}
    # buy → hold is NOT an exit — buy was never in the (Strong-Buy-only) buy zone.
    dst2: dict = {}
    _record_signal_move(dst2, row, "buy", "hold", "Hold", 55.0, 11.0, "2026-08-02")
    assert dst2 == {}
    # No prior signal (first observation) → ignored.
    dst3: dict = {}
    _record_signal_move(dst3, row, None, "strong_buy", "Strong Buy", 81.0, 10.0, "2026-08-01")
    assert dst3 == {}


def _move(i: int, direction: str = "sell") -> dict:
    return {"provider_symbol": f"S{i}.KA", "symbol": f"S{i}", "name": None, "region": "psx",
            "direction": direction, "from": "strong_buy", "to": "hold", "label": "Hold",
            "composite": 55.0, "price": 1.0, "date": "2026-08-01"}


def test_update_signal_moves_drops_recompute_batch(tmp_path) -> None:
    # A flood of same-run crossings (> the cap) is a score re-baseline, not real events → dropped.
    batch = {f"S{i}.KA": _move(i) for i in range(_MAX_MOVES_PER_RUN + 5)}
    _update_signal_moves(tmp_path, batch, "2026-08-01")
    saved = json.loads((tmp_path / "signal_moves.json").read_text(encoding="utf-8"))
    assert saved["all"] == []


def test_update_signal_moves_keeps_small_genuine_batch(tmp_path) -> None:
    few = {f"S{i}.KA": _move(i) for i in range(3)}
    _update_signal_moves(tmp_path, few, "2026-08-01")
    saved = json.loads((tmp_path / "signal_moves.json").read_text(encoding="utf-8"))
    assert len(saved["sell"]) == 3


def _yahoo(days: list[str], closes: list[float], volume: float = 1_000.0):
    c = np.array(closes, dtype=float)
    return days, c * 0.99, c * 1.01, c * 0.98, c, np.full(len(c), volume)


def _pack_of(monkeypatch, series: dict[str, float]) -> None:
    monkeypatch.setattr(price_pack, "packed_bars", lambda region, symbol: {
        d: [d, None, None, None, c, None] for d, c in series.items()})


_DAYS = [f"2026-{1 + i // 28:02d}-{1 + i % 28:02d}" for i in range(100)]


def test_psx_candles_are_used_where_they_agree_with_the_exchange(monkeypatch) -> None:
    closes = [100.0 + i for i in range(100)]
    _pack_of(monkeypatch, dict(zip(_DAYS, closes, strict=True)))
    checked = _on_exchange_closes("LUCK", _yahoo(_DAYS, closes))
    assert checked is not None
    assert len(checked[0]) == 100


def test_a_psx_bar_that_disagrees_is_dropped_not_averaged(monkeypatch) -> None:
    closes = [100.0 + i for i in range(100)]
    stored = dict(zip(_DAYS, closes, strict=True))
    stored[_DAYS[50]] = closes[50] * 1.2
    _pack_of(monkeypatch, stored)
    checked = _on_exchange_closes("LUCK", _yahoo(_DAYS, closes))
    assert checked is not None
    assert _DAYS[50] not in checked[0]
    assert len(checked[0]) == 99


def test_a_hole_in_the_pack_does_not_cost_a_company_its_chart(monkeypatch) -> None:
    closes = [100.0 + i for i in range(100)]
    stored = dict(zip(_DAYS, closes, strict=True))
    for day in _DAYS[70:95]:
        del stored[day]
    _pack_of(monkeypatch, stored)
    checked = _on_exchange_closes("INDU", _yahoo(_DAYS, closes))
    assert checked is not None
    assert len(checked[0]) == 100


def test_a_series_rebased_by_a_split_is_not_charted(monkeypatch) -> None:
    closes = [100.0 + i for i in range(100)]
    stored = {d: c * 5 for d, c in zip(_DAYS, closes, strict=True)}
    stored[_DAYS[-1]] = closes[-1]
    _pack_of(monkeypatch, stored)
    assert _on_exchange_closes("SPLIT", _yahoo(_DAYS, closes)) is None


def test_gil_is_not_charted_when_the_exchange_is_far_from_yahoo(monkeypatch) -> None:
    """GIL read 125.85 on Yahoo and 1,000 on the exchange. Every old bar agrees, because the
    pack took them from Yahoo; only the newest exchange price shows the series is wrong."""
    closes = [125.85] * 100
    stored = dict(zip(_DAYS, closes, strict=True))
    stored["2026-05-01"] = 1000.0
    _pack_of(monkeypatch, stored)
    assert _on_exchange_closes("GIL", _yahoo(_DAYS, closes)) is None


def test_a_series_yahoo_stopped_carrying_is_not_charted(monkeypatch) -> None:
    closes = [100.0 + i for i in range(100)]
    stored = dict(zip(_DAYS, closes, strict=True))
    stored["2026-08-01"] = closes[-1]
    _pack_of(monkeypatch, stored)
    assert _on_exchange_closes("OLD", _yahoo(_DAYS, closes)) is None


def test_an_untraded_line_is_not_a_chart(monkeypatch) -> None:
    closes = [3.38] * 100
    _pack_of(monkeypatch, dict(zip(_DAYS, closes, strict=True)))
    assert _on_exchange_closes("SGABL", _yahoo(_DAYS, closes, volume=0.0)) is None


def test_withdrawing_a_read_leaves_no_old_signal_behind(tmp_path) -> None:
    row = {"provider_symbol": "GIL.KA", "region": "psx", "fundamental_score": 60.0,
           "quality_score": 60.0, "risk_score": 60.0, "composite_score": 85.0,
           "technical_score": 82.34, "signal": "strong_buy", "signal_label": "Strong Buy",
           "signal_since": "2026-04-01", "price_at_signal": 100.0}
    doc = {"scores": {"technical": 82.34, "composite": 85.0, "momentum": 70.0},
           "signal": {"signal_type": "strong_buy"}, "patterns": [{"name": "doji"}],
           "price_action": {"score": 80}}
    (tmp_path / "GIL.KA.json").write_text(json.dumps(doc), encoding="utf-8")
    _withdraw_read(row, tmp_path, {})
    assert row["technical_score"] is None
    assert row["signal"] is None
    assert row["signal_since"] is None
    assert row["composite_score"] == 60.0, "composite must lose the old technical leg too"
    saved = json.loads((tmp_path / "GIL.KA.json").read_text(encoding="utf-8"))
    assert saved["scores"]["technical"] is None
    assert saved["signal"] is None
    assert saved["patterns"] == []
    assert "price_action" not in saved


def _snapshot(tmp_path, prior_read: str | None) -> list[dict]:
    rows = [{"provider_symbol": "LUCK.KA", "symbol": "LUCK", "region": "psx", "price": 199.0,
             "technical_score": 82.34, "composite_score": 10.0, "signal": "strong_sell",
             "fundamental_score": 70.0},
            {"provider_symbol": "GIL.KA", "symbol": "GIL", "region": "psx", "price": 1000.0,
             "technical_score": 51.0, "composite_score": 50.0, "signal": "hold",
             "fundamental_score": 60.0}]
    if prior_read:
        rows[0]["technical_as_of"] = prior_read
        rows[0]["technical_engine"] = tech_refresh.TECHNICAL_ENGINE
    (tmp_path / "company").mkdir()
    for r in rows:
        doc = {"scores": {"fundamental": r["fundamental_score"]}, "signal": {}}
        (tmp_path / "company" / f"{r['provider_symbol']}.json").write_text(
            json.dumps(doc), encoding="utf-8")
    (tmp_path / "screener.json").write_text(json.dumps(rows), encoding="utf-8")
    return rows


def _market(monkeypatch) -> list:
    """LUCK has a chart, GIL is 8x off the exchange; returns what reached the price pack."""
    days = _DATES[:_N]
    closes = list(_RISING)
    stored = {"LUCK": dict(zip(days, closes, strict=True)),
              "GIL": {**{d: 125.85 for d in days}, "2026-12-30": 1000.0}}
    monkeypatch.setattr(price_pack, "packed_bars", lambda region, symbol: {
        d: [d, None, None, None, c, None] for d, c in stored[symbol].items()})
    merged: list = []
    monkeypatch.setattr(price_pack, "merge_series",
                        lambda region, series, **kw: merged.append(region))
    monkeypatch.setattr(tech_refresh, "fetch_history", lambda sym, client: _yahoo(
        days, closes if sym == "LUCK.KA" else [125.85] * _N))
    monkeypatch.setattr(tech_refresh, "_benchmark_bars", lambda region: [])
    return merged


def test_psx_is_read_every_run_and_a_broken_chart_keeps_no_old_signal(tmp_path,
                                                                      monkeypatch) -> None:
    """The regression itself: 445 PSX scores sat unchanged for three months because this pass
    skipped the market and nothing else computed it."""
    _snapshot(tmp_path, prior_read=None)
    merged = _market(monkeypatch)
    result = tech_refresh.refresh_technicals(tmp_path)
    rows = {r["symbol"]: r for r in
            json.loads((tmp_path / "screener.json").read_text(encoding="utf-8"))}
    assert result["updated"] == 1
    assert result["uncharted"] == 1
    assert rows["LUCK"]["technical_score"] != 82.34
    assert rows["LUCK"]["technical_as_of"] == _DATES[_N - 1]
    assert rows["LUCK"]["rel_volume"] == 1.0
    assert rows["GIL"]["technical_score"] is None
    assert rows["GIL"]["signal"] is None
    assert merged == [], "Yahoo closes must never reach the PSX pack from this pass"


def test_a_first_read_is_a_rebaseline_not_a_move(tmp_path, monkeypatch) -> None:
    _snapshot(tmp_path, prior_read=None)
    _market(monkeypatch)
    assert tech_refresh.refresh_technicals(tmp_path)["movers"] == 0


def test_a_read_from_an_older_engine_is_not_comparable(tmp_path, monkeypatch) -> None:
    rows = _snapshot(tmp_path, prior_read="2026-11-03")
    rows[0]["technical_engine"] = tech_refresh.TECHNICAL_ENGINE - 1
    (tmp_path / "screener.json").write_text(json.dumps(rows), encoding="utf-8")
    _market(monkeypatch)
    assert tech_refresh.refresh_technicals(tmp_path)["movers"] == 0


def test_a_later_read_is_a_move(tmp_path, monkeypatch) -> None:
    _snapshot(tmp_path, prior_read="2026-11-03")
    _market(monkeypatch)
    assert tech_refresh.refresh_technicals(tmp_path)["movers"] == 1


def _unify_world(tmp_path, row: dict, doc: dict) -> tuple[dict, dict]:
    from app.ingestion.score_unify import unify

    (tmp_path / "company").mkdir()
    (tmp_path / "screener.json").write_text(json.dumps([row]), encoding="utf-8")
    path = tmp_path / "company" / f"{row['provider_symbol']}.json"
    path.write_text(json.dumps(doc), encoding="utf-8")
    unify(tmp_path)
    return (json.loads((tmp_path / "screener.json").read_text(encoding="utf-8"))[0],
            json.loads(path.read_text(encoding="utf-8")))


def test_unify_moves_the_signal_with_the_composite(tmp_path) -> None:
    """FFC published a composite of 87.81 labelled Buy, which is the 65-80 band."""
    row, doc = _unify_world(
        tmp_path,
        {"provider_symbol": "FFC.KA", "region": "psx", "quality_score": 90.0, "signal": "hold",
         "signal_label": "Hold", "composite_score": 50.0},
        {"scores": {"technical": 90.0}, "signal": {"signal_type": "hold", "label": "Hold"}})
    assert row["composite_score"] >= 80
    assert row["signal"] == "strong_buy"
    assert doc["signal"]["signal_type"] == "strong_buy"


def test_unify_gives_no_signal_to_a_company_with_no_chart(tmp_path) -> None:
    row, _doc = _unify_world(
        tmp_path,
        {"provider_symbol": "ENGROH.KA", "region": "psx", "quality_score": 90.0, "signal": None},
        {"scores": {"technical": None}, "signal": None})
    assert row["signal"] is None


def test_unify_keeps_a_technical_only_name_shrunk_toward_neutral(tmp_path) -> None:
    """IGIHL published 87.24 as its composite: its raw technical score, with no fundamentals."""
    row, _doc = _unify_world(
        tmp_path,
        {"provider_symbol": "IGIHL.KA", "region": "psx", "quality_score": None, "signal": "hold",
         "composite_score": 87.24},
        {"scores": {"technical": 87.24}, "signal": {"signal_type": "hold"}})
    assert row["composite_score"] < 65


def test_a_failed_fetch_does_not_blank_a_recent_read(tmp_path, monkeypatch) -> None:
    """HUBC had a chart on one run and none on the next because Yahoo refused the request."""
    seen = datetime.now(UTC).date().isoformat()
    row = {"provider_symbol": "HUBC.KA", "symbol": "HUBC", "region": "psx", "signal": "hold",
           "technical_score": 53.27, "technical_as_of": seen}
    (tmp_path / "company").mkdir()
    (tmp_path / "screener.json").write_text(json.dumps([row]), encoding="utf-8")
    monkeypatch.setattr(tech_refresh, "fetch_history", lambda sym, client: None)
    monkeypatch.setattr(tech_refresh, "RETRY_PAUSE_SECONDS", 0)
    result = tech_refresh.refresh_technicals(tmp_path)
    saved = json.loads((tmp_path / "screener.json").read_text(encoding="utf-8"))[0]
    assert result["uncharted"] == 0
    assert saved["technical_score"] == 53.27
    assert saved["signal"] == "hold"


def test_a_failed_fetch_is_retried(tmp_path, monkeypatch) -> None:
    _snapshot(tmp_path, prior_read=None)
    _market(monkeypatch)
    answer = tech_refresh.fetch_history
    calls: list[str] = []

    def flaky(sym, client):
        calls.append(sym)
        return None if calls.count(sym) == 1 else answer(sym, client)

    monkeypatch.setattr(tech_refresh, "fetch_history", flaky)
    monkeypatch.setattr(tech_refresh, "RETRY_PAUSE_SECONDS", 0)
    assert tech_refresh.refresh_technicals(tmp_path)["updated"] == 1
