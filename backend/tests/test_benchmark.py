from __future__ import annotations

from app.engines.benchmark.engine import score_metric
from app.engines.benchmark.profiles import country_profile, sector_adjust


def test_country_profiles_differ() -> None:
    # Pakistan demands a higher ROE bar and lower P/E norm than the US.
    pk = country_profile("psx")
    us = country_profile("us")
    assert pk["roe"][0] > us["roe"][0]
    assert pk["pe"][0] < us["pe"][0]


def test_higher_is_better_scoring() -> None:
    # ROE well above the 'great' PK threshold → near-full country leg.
    hi = score_metric("roe", 0.30, "psx", "Cement", None)
    lo = score_metric("roe", 0.05, "psx", "Cement", None)
    assert hi.score is not None and lo.score is not None
    assert hi.score > lo.score
    assert hi.score >= 0.9


def test_lower_is_better_scoring() -> None:
    cheap = score_metric("pe", 5.0, "psx", "Cement", None)
    rich = score_metric("pe", 30.0, "psx", "Cement", None)
    assert cheap.score > rich.score


def test_sector_skip_for_financials() -> None:
    # Debt/equity does not apply to banks → band returns None.
    band = country_profile("psx")["debt_to_equity"]
    assert sector_adjust(band, "debt_to_equity", "Commercial Banks", None) is None
    # ...but applies to a manufacturer.
    assert sector_adjust(band, "debt_to_equity", "Cement", None) is not None


def test_blend_uses_all_legs() -> None:
    s = score_metric(
        "roe", 0.22, "psx", "Cement", None,
        industry_median=0.15, company_history=[0.18, 0.19, 0.20, 0.21],
    )
    assert set(s.legs) == {"country", "industry", "history"}
    assert 0.0 <= s.score <= 1.0
