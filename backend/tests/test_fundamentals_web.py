from __future__ import annotations

from datetime import date

from app.ingestion.expand_universe import _tech_only_composite
from app.ingestion.fundamentals_web import _roll_ttm
from app.ingestion.providers.base import StatementDTO
from app.models.enums import StatementPeriod


def _q(stype: str, y: int, m: int, **vals) -> StatementDTO:
    return StatementDTO(statement_type=stype, fiscal_date=date(y, m, 28),
                        period=StatementPeriod.QUARTER, values=vals)


def test_roll_ttm_sums_trailing_four_quarters() -> None:
    # 5 quarters of revenue → 2 TTM points (trailing-4 sums), newest reflects the last 4.
    q = [
        _q("income", 2025, 3, revenue=100.0, weighted_shares=10.0),
        _q("income", 2025, 6, revenue=110.0, weighted_shares=10.0),
        _q("income", 2025, 9, revenue=120.0, weighted_shares=10.0),
        _q("income", 2025, 12, revenue=130.0, weighted_shares=10.0),
        _q("income", 2026, 3, revenue=140.0, weighted_shares=11.0),
    ]
    inc, bal, cf = _roll_ttm(q)
    revs = [r.revenue for r in inc]
    assert revs == [460.0, 500.0]  # 100+110+120+130, then 110+120+130+140
    # share counts are NOT summed — the latest quarter's value is carried through.
    assert inc[-1].weighted_shares == 11.0


def test_roll_ttm_needs_four_clean_quarters() -> None:
    q = [_q("income", 2025, 6, revenue=110.0), _q("income", 2025, 9, revenue=120.0)]
    inc, _bal, _cf = _roll_ttm(q)
    assert inc == []  # <4 quarters → no TTM point


def test_roll_ttm_balance_is_snapshot_per_quarter() -> None:
    q = [
        _q("balance", 2025, 12, total_assets=1000.0),
        _q("balance", 2026, 3, total_assets=1100.0),
    ]
    _inc, bal, _cf = _roll_ttm(q)
    assert [b.total_assets for b in bal] == [1000.0, 1100.0]  # carried, not summed


def test_tech_only_composite_shrinks_toward_neutral() -> None:
    # 50 + (tech - 50) * 0.35 — a raw technical can't masquerade as a full composite.
    assert _tech_only_composite(50.0) == 50.0
    assert _tech_only_composite(100.0) == 67.5
    assert _tech_only_composite(0.0) == 32.5
    # A strong technical (90) lands mid-pack, below a fully-analyzed 73.
    assert _tech_only_composite(90.0) < 73.0
