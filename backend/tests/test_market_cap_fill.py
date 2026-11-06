"""Every company we can price publishes a cap, whether or not the DCF could value it."""

from __future__ import annotations

import json
from pathlib import Path

from app.ingestion import quality_refresh


def income(shares: float | None) -> list[dict]:
    return [{"fiscal_date": f"2026-0{m}-30", "revenue": 100.0, "net_income": 10.0,
             "weighted_shares": shares} for m in (9, 6, 3)]


def publish(tmp_path: Path, rows: list[dict], docs: dict[str, dict]) -> dict[str, dict]:
    (tmp_path / "company").mkdir()
    (tmp_path / "screener.json").write_text(json.dumps(rows), encoding="utf-8")
    for symbol, doc in docs.items():
        (tmp_path / "company" / f"{symbol}.json").write_text(json.dumps(doc), encoding="utf-8")
    quality_refresh._refresh_quality(tmp_path)
    saved = json.loads((tmp_path / "screener.json").read_text(encoding="utf-8"))
    return {row["provider_symbol"]: row for row in saved}


def test_a_bank_the_dcf_cannot_value_still_has_a_cap(tmp_path: Path) -> None:
    """JPM: no cash flow statement here, so the DCF stops before it ever prices the company."""
    rows = [{"provider_symbol": "JPM", "symbol": "JPM", "region": "us", "price": 337.34}]
    docs = {"JPM": {"statements_ttm": {"income": income(2_709_000_000.0)}}}

    assert publish(tmp_path, rows, docs)["JPM"]["market_cap"] == round(337.34 * 2_709_000_000.0, 2)


def test_the_newest_share_count_we_hold_is_used() -> None:
    statements = {"income": [{"weighted_shares": None}, {"weighted_shares": 0},
                             {"weighted_shares": 50.0}, {"weighted_shares": 40.0}]}

    assert quality_refresh._market_cap(statements, 2.0) == 100.0


def test_no_shares_or_no_price_is_blank_and_not_the_old_figure(tmp_path: Path) -> None:
    rows = [{"provider_symbol": "NOSHARES", "symbol": "NOSHARES", "region": "us", "price": 5.0,
             "market_cap": 1e9},
            {"provider_symbol": "NOPRICE", "symbol": "NOPRICE", "region": "us", "price": None,
             "market_cap": 1e9}]
    docs = {"NOSHARES": {"statements_ttm": {"income": income(None)}},
            "NOPRICE": {"statements_ttm": {"income": income(1000.0)}}}

    saved = publish(tmp_path, rows, docs)

    assert saved["NOSHARES"]["market_cap"] is None
    assert saved["NOPRICE"]["market_cap"] is None
