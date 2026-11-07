"""A step in a stored price series is repaired only when a recorded split explains it."""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from app.ingestion import pack_repair, price_pack
from app.ingestion.pack_repair import (
    Split,
    agreement,
    continuous,
    overlay,
    proven,
    rejoin,
    repair,
)


def _series(start: str, closes: list[float]) -> dict[str, float]:
    first = date.fromisoformat(start)
    return {(first + timedelta(days=i)).isoformat(): c for i, c in enumerate(closes)}


def test_ubl_step_is_rescaled_by_the_exact_split_ratio() -> None:
    """UBL: 124.52 to 243.63 on 5 May 2025, a 2:1 split on 24 June. May 2023 read 29.07."""
    closes = {"2025-04-30": 120.0, "2025-05-02": 124.52, "2025-05-05": 243.63,
              "2026-11-05": 250.0}
    res = repair(closes, [Split("2025-06-24", 2.0)])
    assert res.closes["2025-04-30"] == pytest.approx(240.0)
    assert res.closes["2025-05-02"] == pytest.approx(249.04)
    assert res.closes["2025-05-05"] == 243.63
    assert res.closes["2026-11-05"] == 250.0
    assert res.applied == [("2025-05-05", 2.0)]
    assert res.unexplained == []


def test_a_jump_with_no_recorded_split_is_left_alone_and_reported() -> None:
    """GIL went 125.85 to 1,000. Nothing explains it, so nothing may rescale it."""
    closes = {"2026-08-03": 125.85, "2026-11-05": 1000.0}
    res = repair(closes, [])
    assert res.closes == closes
    assert res.applied == []
    assert res.unexplained == [("2026-11-05", 125.85, 1000.0)]


def test_a_split_of_the_wrong_ratio_does_not_explain_a_step() -> None:
    closes = {"2025-05-02": 100.0, "2025-05-05": 500.0}
    res = repair(closes, [Split("2025-06-24", 2.0)])
    assert res.closes == closes
    assert len(res.unexplained) == 1


def test_a_split_years_after_a_step_does_not_explain_it() -> None:
    closes = {"2021-05-02": 100.0, "2021-05-05": 200.0}
    assert repair(closes, [Split("2025-06-24", 2.0)]).applied == []


def test_a_step_after_the_split_is_not_that_split() -> None:
    closes = {"2025-08-02": 100.0, "2025-08-05": 200.0}
    assert repair(closes, [Split("2025-06-24", 2.0)]).applied == []


def test_a_consolidation_scales_down() -> None:
    """ABEO: 118.75 to 4.08 is a step the other way."""
    closes = {"2022-07-01": 118.75, "2022-07-05": 4.08}
    res = repair(closes, [Split("2022-07-05", 1 / 30)])
    assert res.closes["2022-07-01"] == pytest.approx(3.958, abs=0.001)


def test_two_splits_stack_and_each_is_used_once() -> None:
    """SYS: x2 in 2022 and x5 in 2025, so its oldest closes move by both."""
    closes = {"2022-03-29": 7.14, "2022-03-30": 14.35, "2025-04-16": 19.77, "2025-04-17": 99.63}
    res = repair(closes, [Split("2025-05-29", 5.0), Split("2022-03-31", 2.0)])
    assert res.closes["2022-03-29"] == pytest.approx(71.4)
    assert res.closes["2022-03-30"] == pytest.approx(71.75)
    assert res.closes["2025-04-16"] == pytest.approx(98.85)
    assert len(res.applied) == 2


def test_one_split_cannot_be_spent_on_two_steps() -> None:
    closes = {"2025-05-01": 50.0, "2025-05-02": 100.0, "2025-05-05": 200.0}
    res = repair(closes, [Split("2025-06-24", 2.0)])
    assert len(res.applied) == 1
    assert len(res.unexplained) == 1


def test_an_ordinary_series_is_untouched() -> None:
    closes = _series("2026-01-01", [100.0, 104.0, 99.0, 103.0])
    res = repair(closes, [Split("2026-01-02", 2.0)])
    assert res.closes == closes
    assert res.applied == []
    assert res.unexplained == []


def _ramp(n: int, scale: float = 1.0) -> dict[str, float]:
    return _series("2023-01-01", [(100.0 + i) * scale for i in range(n)])


_SPLIT = Split("2023-09-15", 2.0)


def _unadjusted() -> dict[str, float]:
    """How Yahoo serves much of PSX: the price really halves on the split."""
    return {day: price if day < _SPLIT.day else price / 2 for day, price in _ramp(300).items()}


def test_agreement_puts_an_unadjusted_reference_on_todays_basis() -> None:
    assert agreement(_ramp(300, 0.5), _unadjusted(), [_SPLIT]) == 1.0
    assert agreement(_ramp(300, 0.25), _unadjusted(), [_SPLIT]) < 0.5


def test_a_double_adjusted_series_fails_against_an_adjusted_reference() -> None:
    """IBKR: 7.86 stored, 30.6 adjusted. Dividing by the split again made it look clean."""
    adjusted = _ramp(300, 0.5)
    assert agreement(_ramp(300, 0.5), adjusted, [_SPLIT]) == 1.0
    assert agreement(_ramp(300, 0.125), adjusted, [_SPLIT]) == 0.0


def test_too_few_shared_days_is_no_verdict() -> None:
    assert agreement(_ramp(20), _ramp(20), []) is None


def test_only_a_name_wrong_before_and_right_after_is_changed() -> None:
    assert proven(0.0, 1.0)
    assert not proven(0.95, 1.0), "a name that already matches must not be touched"
    assert not proven(0.95, 0.6), "the 7 US names the first version would have damaged"
    assert not proven(0.3, 0.8), "better is not the same as right"
    assert not proven(None, 1.0)


def _sweep_world(monkeypatch, stored: dict[str, dict[str, float]],
                 yahoo: dict[str, dict[str, float]]) -> list:
    written: list = []
    monkeypatch.setattr(price_pack, "load_packed", lambda region: stored)
    monkeypatch.setattr(price_pack, "merge_series",
                        lambda region, series, **kw: written.append((region, series)))
    monkeypatch.setattr(pack_repair, "fetch_splits",
                        lambda sym, client: [_SPLIT])
    monkeypatch.setattr(pack_repair, "fetch_closes", lambda sym, client: yahoo[sym])
    return written


def _broken() -> dict[str, float]:
    """The UBL shape: adjusted once from the seam on, and twice before it."""
    return {day: price / 4 if day < "2023-08-01" else price / 2
            for day, price in _ramp(300).items()}


def test_the_sweep_repairs_a_proven_name_and_leaves_a_clean_one(monkeypatch) -> None:
    clean = _broken()
    written = _sweep_world(monkeypatch, {"UBL": _broken(), "OK": clean},
                           {"UBL.KA": _unadjusted(), "OK.KA": clean})
    result = pack_repair.sweep("psx", {"UBL": "UBL.KA", "OK": "OK.KA"}, apply=True, workers=2)
    assert result["proven"] == ["UBL"]
    assert list(written[0][1]) == ["UBL"]


def test_the_sweep_writes_nothing_unless_told_to(monkeypatch) -> None:
    written = _sweep_world(monkeypatch, {"UBL": _broken()}, {"UBL.KA": _unadjusted()})
    assert pack_repair.sweep("psx", {"UBL": "UBL.KA"}, workers=2)["proven"] == ["UBL"]
    assert written == []


def _flat(price: float, days: int = 40, start: str = "2023-09-01") -> dict[str, float]:
    return _series(start, [price] * days)


def test_a_step_only_we_have_is_joined_to_the_reference() -> None:
    """Tadawul 2282: 0.651 then 66.1, while Yahoo ran at 65 throughout."""
    reference = _flat(65.0)
    days = sorted(reference)
    closes = {d: (0.65 if i < 20 else 65.0) for i, d in enumerate(days)}

    res = rejoin(closes, reference)

    assert res.closes[days[0]] == pytest.approx(65.0)
    assert res.closes[days[-1]] == 65.0
    assert res.applied == [(days[20], pytest.approx(100.0))]


def test_a_step_the_reference_also_made_is_real() -> None:
    days = sorted(_flat(10.0))
    closes = {d: (10.0 if i < 20 else 25.0) for i, d in enumerate(days)}

    res = rejoin(closes, dict(closes))

    assert res.closes == closes
    assert res.applied == []


def test_a_step_with_no_reference_nearby_is_left_and_reported() -> None:
    days = sorted(_flat(10.0))
    closes = {d: (10.0 if i < 20 else 30.0) for i, d in enumerate(days)}
    reference = {d: 30.0 for d in days[20:]}

    res = rejoin(closes, reference)

    assert res.closes == closes
    assert res.unexplained == [(days[20], 10.0, 30.0)]


def test_a_stretch_on_the_wrong_scale_comes_back_at_both_ends() -> None:
    reference = _flat(50.0, days=60)
    days = sorted(reference)
    closes = {d: (0.5 if 20 <= i < 40 else 50.0) for i, d in enumerate(days)}

    res = rejoin(closes, reference)

    assert all(v == pytest.approx(50.0) for v in res.closes.values())


def test_a_real_move_beside_a_break_keeps_its_size() -> None:
    days = sorted(_flat(10.0, days=60))
    reference = {d: (10.0 if i < 45 else 20.0) for i, d in enumerate(days)}
    closes = {d: reference[d] / (100.0 if i < 20 else 1.0) for i, d in enumerate(days)}

    res = rejoin(closes, reference)

    assert res.closes[days[0]] == pytest.approx(10.0)
    assert res.closes[days[-1]] == 20.0


def test_a_staircase_of_small_bonuses_takes_the_reference() -> None:
    """1020: 0.64, 0.80, 1.00 of Yahoo, each stretch adjusted twice, no step big enough to find."""
    reference = _flat(10.0, days=160)
    days = sorted(reference)
    closes = {d: 10.0 * (0.64 if i < 40 else 0.8 if i < 80 else 1.0) for i, d in enumerate(days)}

    assert continuous(closes, reference, [])
    assert overlay(closes, reference) == reference


def test_a_day_the_reference_lacks_moves_with_its_neighbour() -> None:
    reference = _flat(10.0, days=80)
    days = sorted(reference)
    closes = {d: (1.0 if i < 10 else 10.0) for i, d in enumerate(days)}
    del reference[days[0]]

    assert overlay(closes, reference)[days[0]] == pytest.approx(10.0)


def test_the_recent_sessions_stay_ours() -> None:
    """BOP: the exchange said 30.94, and Yahoo's 30.16 must not replace it."""
    reference = _flat(30.16, days=80)
    days = sorted(reference)
    closes = {d: (3.0 if i < 10 else 30.94) for i, d in enumerate(days)}

    fixed = overlay(closes, reference)

    assert fixed[days[-1]] == 30.94
    assert fixed[days[0]] == 30.16


def test_an_old_day_already_close_is_not_rewritten() -> None:
    reference = _flat(30.16, days=80)
    days = sorted(reference)
    closes = {d: (3.0 if i < 10 else 30.94) for i, d in enumerate(days)}

    assert overlay(closes, reference)[days[12]] == 30.94


def test_a_reference_still_carrying_a_split_cannot_stand_in() -> None:
    """VIVIANA: Yahoo steps at its bonus, so our smooth closes are the right ones."""
    reference = {**_flat(16.0, days=60), **_flat(10.0, days=60, start="2023-11-01")}
    closes = {d: 10.0 for d in reference}

    assert not continuous(closes, reference, [Split("2023-11-01", 1.6)])


def test_a_reference_on_another_basis_today_cannot_stand_in() -> None:
    assert not continuous(_flat(5.0, days=80), _flat(10.0, days=80), [])
