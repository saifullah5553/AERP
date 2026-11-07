"""A dollar quote read against rupee accounts is how HDB published a P/E of 0.48."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from app.ingestion import quality_history, reporting_basis
from app.ingestion.reporting_basis import Basis, build, entry_for, quarter_factor, read_ratios
from app.ingestion.us_universe import Investable

HEADER = ('Fiscal Quarter,Current,Q2 2026,Q1 2026,Period Ending,'
          '"Nov 5, 2026","Jun 30, 2026","Mar 31, 2026"\n')
BODY = ('Market Capitalization,"1,000",900,800\nLast Close Price,10.00,9.00,8.00\n'
        'PE Ratio,20.00,18.00,16.00\nPS Ratio,2.00,1.80,1.60\nPB Ratio,4.00,3.60,3.20\n')


def record(net: float = 3500.0, shares: float = 100.0) -> dict:
    """Accounts in a currency seven to the dollar, one hundred dollar-units of shares."""
    return {"periods": ["2026-06-30", "2026-03-31"],
            "income": {"weighted_shares": [shares, shares], "net_income": [net, net],
                       "revenue": [net * 10, net * 10]},
            "balance": {"total_equity": [net * 5, net * 5]}}


def test_the_ratios_csv_reads_the_dates_run_onto_the_header(tmp_path: Path) -> None:
    path = tmp_path / "ATAT_Ratios.csv"
    path.write_text(HEADER + BODY, encoding="utf-8")

    quarters, current = read_ratios(path)

    assert sorted(quarters) == ["2026-03-31", "2026-06-30"]
    assert quarters["2026-06-30"]["PE Ratio"] == 18.0
    assert current["Market Capitalization"] == 1000.0


def test_the_ratios_csv_reads_a_period_ending_row(tmp_path: Path) -> None:
    path = tmp_path / "X_Ratios.csv"
    path.write_text('Fiscal Quarter,Current,Q2 2026\nPeriod Ending,"Nov 5, 2026","Jun 30, 2026"\n'
                    'PE Ratio,20.00,18.00\n', encoding="utf-8")

    quarters, current = read_ratios(path)

    assert quarters["2026-06-30"]["PE Ratio"] == 18.0 and current["PE Ratio"] == 20.0


def test_the_older_layout_is_read_too(tmp_path: Path) -> None:
    """TSM and 118 others: a label before each date, and a shorter name for the cap."""
    path = tmp_path / "TSM_Ratios.csv"
    path.write_text("\n".join([
        "Fiscal Quarter,Current,Q2 2026,Period Ending,"
        "\"Jul '26 Jul 31, 2026\",\"Jun '26 Jun 30, 2026\"",
        'Market Cap,"1,947","2,476"',
        "Last Close Price,10.00,9.00",
        "PE Ratio,20.00,18.00",
    ]) + "\n", encoding="utf-8")

    quarters, current = read_ratios(path)

    assert list(quarters) == ["2026-06-30"]
    assert quarters["2026-06-30"]["PE Ratio"] == 18.0
    assert current["Market Capitalization"] == 1947.0


def test_a_factor_after_a_big_reverse_split_is_not_rounded_away() -> None:
    company = record(net=1.0, shares=1_000_000.0)
    closes = {"2026-06-30": 100.0}
    row = {"2026-06-30": {"PE Ratio": 4.0}}

    entry = entry_for(company, closes, row, {}, "China")

    assert entry["factors"]["2026-06-30"] == 4e-08


def test_a_break_in_our_prices_does_not_read_as_a_foreign_currency() -> None:
    """AVB: a true close of 188 stored as 67, on accounts that are already in dollars."""
    company = record(net=100.0, shares=10.0)
    row = {"2026-06-30": {"PE Ratio": 18.8, "Last Close Price": 188.0}}

    entry = entry_for(company, {"2026-06-30": 67.0}, row, {}, "United States")

    assert entry is None


def test_a_dividend_adjusted_page_close_leaves_our_close_alone() -> None:
    company = record(net=100.0, shares=10.0)
    row = {"2026-06-30": {"PE Ratio": 7.0, "Last Close Price": 8.0}}

    entry = entry_for(company, {"2026-06-30": 10.0}, row, {}, "China")

    assert entry["factors"]["2026-06-30"] == 7.0


def test_the_factor_recovers_the_exchange_rate() -> None:
    """Worth 7,000 in the accounts' currency, quoted at 1,000 dollars."""
    row = {"PE Ratio": 20.0, "PS Ratio": 2.0, "PB Ratio": 4.0}

    assert quarter_factor(row, 10.0, 100.0, 350.0, 3500.0, 1750.0) == 7.0


def test_a_loss_maker_is_still_read_from_its_other_multiples() -> None:
    row = {"PE Ratio": None, "PS Ratio": 2.0, "PB Ratio": 4.0}

    assert quarter_factor(row, 10.0, 100.0, -50.0, 3500.0, 1750.0) == 7.0


def test_nothing_readable_gives_no_factor() -> None:
    assert quarter_factor({}, 10.0, 100.0, 350.0, 3500.0, 1750.0) is None


def closes() -> dict[str, float]:
    return {"2026-03-31": 8.0, "2026-06-30": 10.0}


def ratios(pe: float = 20.0) -> dict[str, dict]:
    row = {"PE Ratio": pe, "PS Ratio": None, "PB Ratio": None}
    return {"2026-06-30": row, "2026-03-31": row}


def test_a_foreign_filer_gets_an_entry_and_a_dollar_unit_count() -> None:
    entry = entry_for(record(net=350.0), closes(), ratios(),
                      {"Market Capitalization": 1000.0, "Last Close Price": 10.0}, "China")

    assert entry["factors"]["2026-06-30"] == 7.0
    assert entry["units"] == 100_000_000.0


def test_an_ordinary_american_company_gets_none() -> None:
    """Its multiple agrees with price x shares, so there is nothing to convert."""
    assert entry_for(record(net=50.0), closes(), ratios(), {}, "United States") is None


def test_a_company_the_listing_calls_american_is_caught_by_its_factor() -> None:
    entry = entry_for(record(net=350.0), closes(), ratios(), {}, "United States")

    assert entry and entry["factors"]["2026-06-30"] == 7.0


def test_build_drops_a_name_that_has_turned_out_normal(tmp_path: Path) -> None:
    (tmp_path / "AAA_Ratios.csv").write_text(HEADER + BODY, encoding="utf-8")
    pack = {"AAA": {"d": ["2026-03-31", "2026-06-30"], "c": [8.0, 9.0]}}
    store = {"AAA": record(net=50.0)}

    table = build(store, pack, tmp_path, {"AAA": "United States"}, {"AAA": {"factors": {"x": 7}}})

    assert table == {}


def test_build_keeps_what_this_machine_has_no_csv_for(tmp_path: Path) -> None:
    kept = {"HDB": {"factors": {"2026-06-30": 90.0}}}

    assert build({}, {}, tmp_path, {}, kept) == kept


def table() -> Basis:
    return Basis({"HDB": {"factors": {"2026-03-31": 80.0, "2026-06-30": 85.0}, "units": 5.0e9}})


def test_the_factor_is_the_latest_quarter_on_or_before_the_day() -> None:
    assert table().factor("HDB", "2026-06-30") == 85.0
    assert table().factor("HDB", "2026-05-15") == 80.0
    assert table().factor("HDB", "2026-11-06") == 85.0


def test_before_our_first_quarter_the_earliest_stands() -> None:
    assert table().factor("HDB", "2021-01-01") == 80.0


def test_everyone_else_is_untouched() -> None:
    def price_on(when):
        return 25.0

    assert table().factor("AAPL", "2026-06-30") == 1.0
    assert table().on_books("AAPL", price_on) is price_on
    assert table().usd_cap("AAPL", 100.0) is None


def test_the_cap_is_the_listed_units_at_the_dollar_price() -> None:
    assert table().usd_cap("HDB", 25.0) == 125_000_000_000.0


def test_a_price_lookup_comes_back_in_the_accounts_terms() -> None:
    converted = table().on_books("HDB", lambda when: 25.0 if when > "2022" else None)

    assert converted("2026-06-30") == 25.0 * 85.0
    assert converted("2021-01-01") is None


def test_a_missing_file_converts_nothing(tmp_path: Path) -> None:
    reporting_basis.load_basis.cache_clear()

    assert "HDB" not in reporting_basis.load_basis(tmp_path / "absent.json")
    reporting_basis.load_basis.cache_clear()


def test_every_past_quarter_is_valued_on_the_books(tmp_path: Path, monkeypatch) -> None:
    """Through the real pass: this is the number the page and the signal are built on."""
    seen = []

    def spy(symbol, price_on):
        converted = table().on_books(symbol, price_on)
        seen.append(converted("2026-06-30"))
        return converted

    (tmp_path / "company").mkdir()
    row = {"provider_symbol": "HDB", "symbol": "HDB", "region": "us", "sector": "Banks"}
    (tmp_path / "screener.json").write_text(json.dumps([row]), encoding="utf-8")
    (tmp_path / "company" / "HDB.json").write_text(json.dumps({"statements_ttm": {}}), "utf-8")
    monkeypatch.setattr(quality_history, "_price_lookup", lambda r, s: lambda when: 25.0)
    basis = SimpleNamespace(on_books=spy)
    monkeypatch.setattr(quality_history, "load_basis", lambda: basis)

    quality_history._refresh(tmp_path)

    assert seen == [25.0 * 85.0]


def test_a_name_on_another_basis_is_not_a_us_portfolio_holding(tmp_path: Path) -> None:
    doc = {"statements_ttm": {"income": [
        {"fiscal_date": "2026-03-28", "net_income": 1e8, "weighted_shares": 1e9}]}}
    (tmp_path / "IH.json").write_text(json.dumps(doc), encoding="utf-8")
    check = Investable(tmp_path, {}, {"IH": "United States"}, lambda s, d: ("2026-05-29", 50.0),
                       off_basis={"IH"})

    assert not check("IH", "2026-03-31", "2026-05-29")


def test_a_peer_multiple_reads_a_foreign_filer_on_its_accounts(tmp_path: Path, monkeypatch) -> None:
    """A dollar quote against rupee equity went into the sector median as a P/B of 0.01."""
    from app.engines.valuation import multi

    doc = {"statements_ttm": {
        "income": [{"fiscal_date": "2026-06-30", "weighted_shares": 100.0}],
        "balance": [{"fiscal_date": "2026-06-30", "total_equity": 42500.0}]}}
    rows = []
    for i in range(multi.MIN_PEERS):
        symbol = f"F{i}"
        (tmp_path / f"{symbol}.json").write_text(json.dumps(doc), encoding="utf-8")
        rows.append({"symbol": symbol, "provider_symbol": symbol, "region": "us",
                     "sector": "Banks", "price": 25.0})
    table = Basis({r["symbol"]: {"factors": {"2026-06-30": 85.0}} for r in rows})
    monkeypatch.setattr(reporting_basis, "load_basis", lambda: table)

    assert multi.sector_multiples(rows, tmp_path)["us|Banks"]["pb"] == 5.0
