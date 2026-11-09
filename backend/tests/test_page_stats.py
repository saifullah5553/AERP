from __future__ import annotations

import json
from pathlib import Path

from app.ingestion import company_ratios, sector_stats
from app.ingestion.company_ratios import ttm_ratios


def _ttm(date: str, revenue: float, eps: float, ni: float, equity: float = 500.0) -> tuple:
    inc = {"period": "ttm", "fiscal_date": date, "revenue": revenue, "net_income": ni, "eps": eps,
           "operating_income": ni * 1.4, "ebitda": ni * 2, "interest_expense": -10.0,
           "weighted_shares": 100.0, "gross_profit": revenue * 0.5}
    bal = {"fiscal_date": date, "total_equity": equity, "total_assets": 1000.0,
           "total_liabilities": 500.0, "total_debt": 100.0, "cash_and_equivalents": 50.0,
           "current_assets": 300.0, "current_liabilities": 150.0, "retained_earnings": 200.0}
    cf = {"fiscal_date": date, "operating_cash_flow": ni * 1.2, "dividends_paid": -20.0}
    return inc, bal, cf


def _statements() -> dict:
    """Quarterly TTM rows, newest first, as the company files carry them."""
    rows = [_ttm("2026-09-30", 1371.0, 3.74, 374.0), _ttm("2026-06-30", 1300.0, 3.36, 336.0),
            _ttm("2026-03-31", 1200.0, 3.19, 319.0), _ttm("2025-12-31", 1100.0, 2.56, 256.0),
            _ttm("2025-09-30", 1000.0, 1.73, 173.0)]
    return {"income": [r[0] for r in rows], "balance": [r[1] for r in rows],
            "cashflow": [r[2] for r in rows]}


def test_growth_is_a_year_apart_not_a_quarter() -> None:
    """PAAS: September against September, 37.1% and 116%, not against June."""
    r = ttm_ratios(_statements(), price=41.17, pe=10.97)

    assert round(r["revenue_growth"], 3) == 0.371
    assert round(r["eps_growth"], 3) == 1.162
    assert r["period"] == "ttm" and r["fiscal_date"] == "2026-09-30"


def test_pe_is_the_screeners_and_peg_follows_it() -> None:
    r = ttm_ratios(_statements(), price=41.17, pe=10.97)

    assert r["pe_ratio"] == 10.97
    assert round(r["peg_ratio"], 4) == round(10.97 / (r["eps_growth"] * 100), 4)


def test_foreign_filer_keeps_ratios_but_not_currency_amounts() -> None:
    r = ttm_ratios(_statements(), price=20.0, factor=25.0, pe=20.0, foreign=True)

    assert r["enterprise_value"] is None and r["book_value_per_share"] is None
    # P/B on the accounts' basis: 20 x 25 x 100 shares over 500 equity.
    assert round(r["price_to_book"], 2) == 100.0


def test_no_income_rows_means_no_block() -> None:
    assert ttm_ratios({}, price=10.0) is None


def test_sync_replaces_the_frozen_annual_block_and_corrects_the_row(tmp_path: Path) -> None:
    (tmp_path / "company").mkdir()
    doc = {"ratios": {"period": "annual", "fiscal_date": "2026-03-31", "revenue_growth": 0.09,
                      "altman_z": 1.5, "id": 513},
           "fundamentals": {"revenue_growth": 0.3373, "eps_growth": 2.5862, "roe": 0.2},
           "statements_ttm": _statements()}
    (tmp_path / "company" / "PAAS.json").write_text(json.dumps(doc), encoding="utf-8")
    row = {"symbol": "PAAS", "provider_symbol": "PAAS", "region": "psx", "asset_class": "equity",
           "price": 41.17, "pe_ttm": 10.97, "roe": 0.2118, "revenue_growth": 0.3373,
           "eps_growth": 2.5862}

    company_ratios.sync(tmp_path, [row])

    out = json.loads((tmp_path / "company" / "PAAS.json").read_text(encoding="utf-8"))
    assert out["ratios"]["period"] == "ttm" and "id" not in out["ratios"]
    assert out["ratios"]["roe"] == 0.2118  # the engine's figure, as on the grid
    assert round(row["revenue_growth"], 3) == 0.371 == round(out["ratios"]["revenue_growth"], 3)
    assert round(out["fundamentals"]["eps_growth"], 3) == 1.162


def test_sector_stats_from_rows_with_breadth_from_the_pack() -> None:
    rows = [
        {"symbol": "A", "region": "dfm", "sector": "Banks", "asset_class": "equity",
         "composite_score": 70.0, "technical_score": 60.0, "fundamental_score": 80.0,
         "roe": 0.1, "pe_ttm": 8.0},
        {"symbol": "B", "region": "dfm", "sector": "Banks", "asset_class": "equity",
         "composite_score": 50.0, "technical_score": 40.0, "fundamental_score": 60.0,
         "roe": 0.2, "pe_ttm": -3.0},
        {"symbol": "C", "region": "dfm", "sector": "Lonely", "asset_class": "equity",
         "composite_score": 90.0},
        {"symbol": "X", "region": "global", "sector": "Crypto", "asset_class": "crypto",
         "composite_score": 50.0},
    ]
    rising, falling = list(range(1, 61)), list(range(60, 0, -1))

    stats = sector_stats.build(rows, lambda region, s: rising if s == "A" else falling)

    banks = stats["dfm"][0]
    assert list(stats) == ["dfm"] and len(stats["dfm"]) == 1  # one-name sector and crypto out
    assert banks["count"] == 2 and banks["score"] == 60.0 and banks["fundamental"] == 70.0
    assert banks["breadth_above_50dma"] == 0.5 and banks["trend"] == "Neutral"
    assert banks["medians"]["pe_ratio"] == 8.0  # a loss is not a cheap P/E
    assert banks["medians"]["roe"] == 0.15
