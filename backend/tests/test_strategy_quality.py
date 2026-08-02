from __future__ import annotations

from app.engines.strategy.quality import assess_quality


def _stmts(
    revenue: list[float], op: list[float], eps: list[float], ocf: list[float],
    cash: list[float], debt: list[float] | None = None, ni: list[float] | None = None,
    fcf: list[float] | None = None, cur_liab: float = 100.0,
) -> dict[str, list[dict]]:
    """Build newest-first statements from oldest-first inputs (the export contract)."""
    n = len(revenue)
    ni = ni or [e * 10 for e in eps]
    fcf = fcf if fcf is not None else [o * 0.8 for o in ocf]
    debt = debt if debt is not None else [50.0] * n
    idx = list(reversed(range(n)))  # newest first
    return {
        "income": [
            {"revenue": revenue[i], "operating_income": op[i], "eps": eps[i],
             "net_income": ni[i]} for i in idx
        ],
        "balance": [
            {"cash_and_equivalents": cash[i], "total_debt": debt[i], "total_equity": 500.0,
             "current_assets": 300.0, "current_liabilities": cur_liab} for i in idx
        ],
        "cashflow": [
            {"operating_cash_flow": ocf[i], "free_cash_flow": fcf[i]} for i in idx
        ],
    }


def test_strong_grower_with_building_cash_passes() -> None:
    q = assess_quality(_stmts(
        revenue=[100, 120, 140, 170], op=[10, 14, 18, 24], eps=[1.0, 1.4, 1.8, 2.4],
        ocf=[12, 16, 20, 26], cash=[40, 55, 70, 95],
    ))
    assert q.passed is True
    assert q.score is not None and q.score > 90


def test_falling_eps_fails_even_when_everything_else_is_fine() -> None:
    # EPS is a non-negotiable: a business whose per-share earnings shrink is not "strong".
    q = assess_quality(_stmts(
        revenue=[100, 120, 140, 170], op=[10, 14, 18, 24], eps=[2.4, 2.0, 1.6, 1.0],
        ocf=[12, 16, 20, 26], cash=[40, 55, 70, 95],
    ))
    assert q.passed is False
    assert "eps_rising" in q.reasons


def test_negative_operating_cash_flow_fails() -> None:
    q = assess_quality(_stmts(
        revenue=[100, 120, 140, 170], op=[10, 14, 18, 24], eps=[1.0, 1.4, 1.8, 2.4],
        ocf=[-5, -8, -10, -12], cash=[40, 55, 70, 95],
    ))
    assert q.passed is False


def test_growth_without_cash_fails_the_cash_pillar() -> None:
    # Revenue/profit/EPS all rising, but cash is draining and earnings aren't cash-backed.
    # Growth alone must not qualify a company - this is the pillar rule doing its job.
    q = assess_quality(_stmts(
        revenue=[100, 130, 160, 200], op=[10, 15, 20, 28], eps=[1.0, 1.5, 2.0, 2.8],
        ocf=[1, 1, 1, 1], cash=[90, 70, 50, 20], ni=[10, 15, 20, 28],
        fcf=[-5, -8, -12, -20],
    ))
    assert q.passed is False
    assert "cash_pillar_weak" in q.reasons


def test_thin_data_is_not_scored() -> None:
    # One known check must never render as a confident 100.
    q = assess_quality({"income": [{"eps": 2.0}, {"eps": 1.0}], "balance": [], "cashflow": []})
    assert q.score is None
    assert q.passed is False
