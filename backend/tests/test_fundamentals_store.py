from __future__ import annotations

import gzip
import json
from pathlib import Path

from app.ingestion.fundamentals_store import (
    annual_dtos,
    build_company,
    consolidate,
    load,
)

# Two TTM quarters' worth of a statement, in the exact shape the scraper writes: a "Fiscal
# Quarter" label row, quarter headings, then "Period Ending" followed by the period dates.
INCOME = (
    "Fiscal Quarter,Q2 2026,Q1 2026,Period Ending,\"Jun 30, 2026\",\"Mar 31, 2026\"\n"
    "Revenue,1000,900,,,\n"
    "Operating Income,300,250,,,\n"
    "Net Income,200,150,,,\n"
    "EPS (Basic),2.5,1.9,,,\n"
)
BALANCE = (
    "Fiscal Quarter,Q2 2026,Q1 2026,Period Ending,\"Jun 30, 2026\",\"Mar 31, 2026\"\n"
    "Cash & Equivalents,500,400,,,\n"
    "Total Debt,100,120,,,\n"
)
CASHFLOW = (
    "Fiscal Quarter,Q2 2026,Q1 2026,Period Ending,\"Jun 30, 2026\",\"Mar 31, 2026\"\n"
    "Operating Cash Flow,350,300,,,\n"
    "Free Cash Flow,250,200,,,\n"
)


def test_build_company_is_columnar_and_scaled() -> None:
    rec = build_company({"income": INCOME, "balance": BALANCE, "cashflow": CASHFLOW})
    assert rec is not None
    assert rec["periods"] == ["2026-06-30", "2026-03-31"]
    # Monetary values are reported in millions and stored absolute; EPS is left as given.
    assert rec["income"]["revenue"] == [1_000_000_000.0, 900_000_000.0]
    assert rec["income"]["eps"] == [2.5, 1.9]
    assert rec["balance"]["total_debt"] == [100_000_000.0, 120_000_000.0]
    assert rec["cashflow"]["operating_cash_flow"] == [350_000_000.0, 300_000_000.0]


def test_us_label_variants_are_mapped() -> None:
    # stockanalysis names these differently per exchange. If the aliases stop working the
    # metric does not error - it silently vanishes for a whole market, so pin it.
    us = (
        "Fiscal Quarter,Q2 2026,Period Ending,\"Jun 30, 2026\"\n"
        "Revenue,1000,,\n"
        "Provision for Income Taxes,50,,\n"
    )
    rec = build_company({"income": us})
    assert rec is not None
    assert rec["income"]["income_tax_expense"] == [50_000_000.0]


def test_responsive_date_header_still_parses() -> None:
    # Some exports put both labels in the cell: "Jun '26 Jun 30, 2026". Matching the whole cell
    # dropped every period for those companies.
    text = (
        "Fiscal Quarter,Q2 2026,Period Ending,\"Jun '26 Jun 30, 2026\"\n"
        "Revenue,1000,,\n"
    )
    rec = build_company({"income": text})
    assert rec is not None
    assert rec["periods"] == ["2026-06-30"]


def test_annual_dtos_sample_a_year_apart() -> None:
    # Five quarters of TTM columns: only the 1st and 5th are a year apart, and those are the
    # only two the fundamental engine may see - it reads consecutive rows as consecutive years,
    # so handing it all five would turn YoY growth into quarter-on-quarter.
    quarters = ["Jun 30, 2026", "Mar 31, 2026", "Dec 31, 2025", "Sep 30, 2025", "Jun 30, 2025"]
    header = ("Fiscal Quarter," + ",".join(f"Q{i}" for i in range(5))
              + ",Period Ending," + ",".join(f'"{d}"' for d in quarters))
    text = header + "\nRevenue,1000,900,800,700,600," + "," * 5 + "\n"
    rec = build_company({"income": text})
    assert rec is not None

    dtos = annual_dtos(rec, "USD")
    assert [str(d.fiscal_date) for d in dtos] == ["2026-06-30", "2025-06-30"]
    assert [d.values["revenue"] for d in dtos] == [1_000_000_000.0, 600_000_000.0]
    assert all(d.reported_currency == "USD" for d in dtos)


def test_consolidate_round_trips_through_gzip(tmp_path: Path) -> None:
    raw = tmp_path / "csv" / "us"
    raw.mkdir(parents=True)
    (raw / "AAA_Income_Statement.csv").write_text(INCOME, encoding="utf-8")
    (raw / "AAA_Balance_Sheet.csv").write_text(BALANCE, encoding="utf-8")
    (raw / "AAA_Cash_Flow.csv").write_text(CASHFLOW, encoding="utf-8")

    out = tmp_path / "store"
    assert consolidate(tmp_path / "csv", out, regions=["us"]) == {"us": 1}

    data = load("us", out)
    assert data is not None
    assert data["currency"] == "USD"
    assert data["companies"]["AAA"]["periods"] == ["2026-06-30", "2026-03-31"]

    # Actually gzipped, not just named .gz - CI reads this directly.
    with gzip.open(out / "us.json.gz", "rt", encoding="utf-8") as fh:
        assert json.load(fh)["region"] == "us"


def test_load_missing_region_is_none(tmp_path: Path) -> None:
    assert load("nowhere", tmp_path) is None


def test_apply_to_snapshot_writes_annual_and_ttm(tmp_path: Path) -> None:
    store = tmp_path / "store"
    raw = tmp_path / "csv" / "us"
    raw.mkdir(parents=True)
    (raw / "AAA_Income_Statement.csv").write_text(INCOME, encoding="utf-8")
    consolidate(tmp_path / "csv", store, regions=["us"])

    cdir = tmp_path / "data" / "company"
    cdir.mkdir(parents=True)
    (cdir / "AAA.json").write_text(json.dumps({"symbol": "AAA"}), encoding="utf-8")

    from app.ingestion.fundamentals_store import apply_to_snapshot

    assert apply_to_snapshot(tmp_path / "data", store, regions=["us"]) == {"us": 1}
    doc = json.loads((cdir / "AAA.json").read_text(encoding="utf-8"))
    # Annual for the engine (reads consecutive rows as consecutive years), every quarter for
    # the trend.
    assert [r["fiscal_date"] for r in doc["statements"]["income"]] == ["2026-06-30"]
    assert [r["fiscal_date"] for r in doc["statements_ttm"]["income"]] == [
        "2026-06-30", "2026-03-31",
    ]
    assert doc["statements"]["income"][0]["revenue"] == 1_000_000_000.0


def test_apply_never_replaces_richer_history(tmp_path: Path) -> None:
    # A partial scrape must not cost a company the years it already had.
    store = tmp_path / "store"
    raw = tmp_path / "csv" / "us"
    raw.mkdir(parents=True)
    (raw / "AAA_Income_Statement.csv").write_text(INCOME, encoding="utf-8")
    consolidate(tmp_path / "csv", store, regions=["us"])

    cdir = tmp_path / "data" / "company"
    cdir.mkdir(parents=True)
    rich = {"statements": {"income": [{"fiscal_date": f"202{i}-06-30"} for i in range(5)]}}
    (cdir / "AAA.json").write_text(json.dumps(rich), encoding="utf-8")

    from app.ingestion.fundamentals_store import apply_to_snapshot

    apply_to_snapshot(tmp_path / "data", store, regions=["us"])
    doc = json.loads((cdir / "AAA.json").read_text(encoding="utf-8"))

    # The guarantee this test is named for: the five annual years survive a one-period scrape.
    assert len(doc["statements"]["income"]) == 5

    # ...but the TTM series IS written, because it is a DIFFERENT series and the only one
    # scoring reads. Skipping the whole company to protect the annual history cost 785
    # Australian companies their entire quarterly history - HUB held ten TTM periods in the
    # store and none in its file, and scored three points off annual data instead of ten off
    # TTM. Counting files written is not the property worth asserting; these two are.
    assert doc["statements_ttm"]["income"], "the TTM series was discarded with the annual guard"


def test_consolidate_merges_instead_of_dropping_absent_companies(tmp_path: Path) -> None:
    # The quarterly refresh re-scrapes only the companies that just reported, so the CSV folder
    # holds a handful of names while the store holds thousands. Rebuilding from what happens to
    # be on disk would silently delete everyone who did not report.
    raw = tmp_path / "csv" / "us"
    raw.mkdir(parents=True)
    (raw / "AAA_Income_Statement.csv").write_text(INCOME, encoding="utf-8")
    store = tmp_path / "store"
    consolidate(tmp_path / "csv", store, regions=["us"])

    (raw / "AAA_Income_Statement.csv").unlink()
    (raw / "BBB_Income_Statement.csv").write_text(INCOME, encoding="utf-8")
    assert consolidate(tmp_path / "csv", store, regions=["us"]) == {"us": 2}

    data = load("us", store)
    assert data is not None
    assert sorted(data["companies"]) == ["AAA", "BBB"]


def test_consolidate_replace_rebuilds_from_scratch(tmp_path: Path) -> None:
    raw = tmp_path / "csv" / "us"
    raw.mkdir(parents=True)
    (raw / "AAA_Income_Statement.csv").write_text(INCOME, encoding="utf-8")
    store = tmp_path / "store"
    consolidate(tmp_path / "csv", store, regions=["us"])

    (raw / "AAA_Income_Statement.csv").unlink()
    (raw / "BBB_Income_Statement.csv").write_text(INCOME, encoding="utf-8")
    assert consolidate(tmp_path / "csv", store, regions=["us"], replace=True) == {"us": 1}

    data = load("us", store)
    assert data is not None
    assert list(data["companies"]) == ["BBB"]


def test_stale_symbols_picks_only_aged_data(tmp_path: Path) -> None:
    # What keeps the quarterly refresh cheap: touch only companies whose data has aged past a
    # reporting cycle, not all ~11k names.
    from datetime import date

    from app.ingestion.fundamentals_store import stale_symbols

    store = tmp_path / "store"
    store.mkdir()
    payload = {
        "version": 1, "region": "us", "currency": "USD", "suffix": "",
        "companies": {
            "FRESH": {"periods": ["2026-06-30"]},
            "AGED": {"periods": ["2025-09-30"]},
            "BROKEN": {"periods": [None]},
        },
    }
    with gzip.open(store / "us.json.gz", "wt", encoding="utf-8") as fh:
        json.dump(payload, fh)

    got = stale_symbols("us", store, older_than_days=100, today=date(2026, 8, 3))
    assert got == ["AGED", "BROKEN"]
