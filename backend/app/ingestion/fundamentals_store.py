"""One compact, versioned store of quarterly-TTM fundamentals for every market.

The scraper leaves ~45k raw CSVs (~300MB) under data/fundamentals_csv. Those are the local
source of truth, but they are the wrong thing to ship: they compress to ~66MB, most of which is
line items no engine reads, and every refresh would rewrite the whole blob in git history.

This module distills them into one gzipped JSON per market holding only the mapped metrics,
which is roughly an order of magnitude smaller and is what CI actually consumes.

Two consumers with different needs, both served from the same store:

  * the fundamental engine wants an ANNUAL series - so it samples every 4th TTM column, giving
    snapshots one year apart and therefore correct YoY growth.
  * the quality trend wants EVERY quarter, so a rising or falling score is visible sooner than
    once a year.

Storing all periods and letting each consumer choose is why the sampling lives at the read end
rather than being baked in here.

Layout is columnar - parallel arrays keyed by metric, aligned to one `periods` list - because
per-period objects would repeat every key ~20 times per company.
"""

from __future__ import annotations

import gzip
import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.core.safe_path import safe_file
from app.ingestion.providers.base import StatementDTO
from app.ingestion.psx_csv import (
    BALANCE_MAP,
    CASHFLOW_MAP,
    INCOME_MAP,
    MILLION,
    _parse_number,
    parse_statement_csv,
)
from app.ingestion.repository import upsert_statements
from app.models.enums import StatementPeriod
from app.models.market import Security

log = get_logger(__name__)

STORE_VERSION = 1

# provider_symbol suffix and reporting currency per market.
REGION_META: dict[str, tuple[str, str]] = {
    "us": ("", "USD"),
    "india": (".NS", "INR"),
    "australia": (".AX", "AUD"),
    "gcc": (".SR", "SAR"),
    # Dubai. Verified against Yahoo rather than guessed: EMAAR.AE resolves and reports AED,
    # while .DU and .DFM both 404 - and a wrong suffix fails silently as "no price data".
    "dfm": (".AE", "AED"),
    "psx": (".KA", "PKR"),
}

# stockanalysis names the same line item differently across exchanges - the PSX export says
# "Income Tax Expense" where the US one says "Provision for Income Taxes". Without these the
# metric silently goes missing for a whole market, which is far harder to notice than a crash.
ALIASES: dict[str, tuple[str, ...]] = {
    "Income Tax Expense": ("Provision for Income Taxes",),
    "Receivables": ("Accounts Receivable", "Total Trade Receivables",
                    "Accrued Interest and Accounts Receivable"),
    "Basic Shares Outstanding": ("Shares Outstanding (Basic)",),
    "Shares Outstanding (Diluted)": ("Diluted Shares Outstanding",),
    "EPS (Basic)": ("Basic EPS",),
    "Cash & Equivalents": ("Cash & Cash Equivalents",),
    "Common Dividends Paid": ("Common Dividends Paid", "Dividends Paid"),
}

_KINDS: dict[str, tuple[str, dict[str, tuple[str, str]]]] = {
    "income": ("_Income_Statement.csv", INCOME_MAP),
    "balance": ("_Balance_Sheet.csv", BALANCE_MAP),
    "cashflow": ("_Cash_Flow.csv", CASHFLOW_MAP),
}


def _lookup(metrics: dict[str, list[str]], label: str) -> list[str] | None:
    """The row for `label`, falling back to whatever this exchange calls it."""
    row = metrics.get(label)
    if row is not None:
        return row
    for alt in ALIASES.get(label, ()):
        row = metrics.get(alt)
        if row is not None:
            return row
    return None


def build_company(texts: dict[str, str | None]) -> dict[str, Any] | None:
    """Columnar record for one company from its statement CSVs, or None if unusable."""
    periods: list[date | None] = []
    series: dict[str, dict[str, list[float | None]]] = {}

    for kind, (_suffix, mapping) in _KINDS.items():
        text = texts.get(kind)
        if not text:
            continue
        dates, metrics = parse_statement_csv(text)
        if not dates:
            continue
        # Every statement for a company shares the same period grid; keep the longest we see so
        # a short cash-flow table cannot truncate the others.
        if len(dates) > len(periods):
            periods = dates
        cols: dict[str, list[float | None]] = {}
        for label, (col, scale) in mapping.items():
            row = _lookup(metrics, label)
            if row is None:
                continue
            vals: list[float | None] = []
            for cell in row:
                v = _parse_number(cell)
                vals.append(None if v is None else (v * MILLION if scale == "m" else v))
            if any(v is not None for v in vals):
                cols[col] = vals
        if cols:
            series[kind] = cols

    if not periods or not series:
        return None
    return {
        "periods": [d.isoformat() if d else None for d in periods],
        **series,
    }


# The per-market scrapers write "<market>_data/" beside themselves, and Saudi output lands in
# "tadawul_data" rather than "gcc". Accepting both layouts means a folder handed over from a
# scraping machine ingests as-is, with no renaming step to get wrong.
_DIR_ALIASES = {
    "us": ("us", "us_data"),
    "india": ("india", "india_data"),
    "australia": ("australia", "australia_data"),
    # psx_csv is the original PSX export - 20 quarterly TTM columns per statement, sitting
    # unused by the store because only the annual sampling was ever ingested.
    "psx": ("psx", "psx_data", "psx_csv"),
    "gcc": ("gcc", "gcc_data", "tadawul_data", "tadawul"),
    "dfm": ("dfm", "dfm_data"),
}


def _region_dir(csv_dir: Path, region: str) -> Path | None:
    """The folder holding this market's CSVs, under either naming scheme."""
    for name in _DIR_ALIASES.get(region, (region,)):
        candidate = csv_dir / name
        if candidate.exists():
            return candidate
    return None


def merge_records(old: dict | None, new: dict | None) -> dict | None:
    """Union two columnar records by PERIOD, newest first, so history only ever grows.

    The source publishes a rolling twenty quarters. When Jun-26 appears the oldest quarter
    falls off the end, so replacing a company's record with each fresh scrape quietly discards
    a quarter every three months - and the loss is invisible, because the file still holds a
    tidy twenty periods. After five years of refreshes we would still have five years of
    history and never notice the first five had gone.

    Newer values win where the two overlap: a restated figure is the better number.
    """
    if not old:
        return new
    if not new:
        return old

    sections = ("income", "balance", "cashflow")
    old_periods = list(old.get("periods") or [])
    new_periods = list(new.get("periods") or [])

    # metric -> {period: value}, new applied over old.
    merged: dict[str, dict[str, dict]] = {}
    for section in sections:
        cells: dict[str, dict] = {}
        for rec, periods in ((old, old_periods), (new, new_periods)):
            for metric, values in (rec.get(section) or {}).items():
                slot = cells.setdefault(metric, {})
                for period, value in zip(periods, values, strict=False):
                    if period and value is not None:
                        slot[period] = value
        merged[section] = cells

    periods = sorted({p for p in old_periods + new_periods if p}, reverse=True)
    out: dict = {"periods": periods}
    for section in sections:
        out[section] = {
            metric: [cells.get(p) for p in periods]
            for metric, cells in merged[section].items()
        }
    return out


def consolidate(csv_dir: Path, out_dir: Path, regions: list[str] | None = None,
                replace: bool = False) -> dict[str, int]:
    """Distil raw scraped CSVs into one gzipped JSON per market.

    Merges into the existing store by default. That matters for the quarterly refresh: it
    re-scrapes only the companies that just reported, so the CSV folder holds a handful of
    names while the store holds thousands. Rebuilding from what happens to be on disk would
    silently delete every company that did not report this quarter.

    Pass replace=True only for a full rebuild from a complete CSV set.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    result: dict[str, int] = {}

    for region in regions or list(REGION_META):
        rdir = _region_dir(csv_dir, region)
        if rdir is None:
            continue
        suffix, currency = REGION_META[region]
        income_sfx = _KINDS["income"][0]
        symbols = sorted(p.name[: -len(income_sfx)] for p in rdir.glob(f"*{income_sfx}"))

        existing = None if replace else load(region, out_dir)
        companies: dict[str, Any] = dict((existing or {}).get("companies") or {})
        for sym in symbols:
            texts = {
                kind: _read(rdir / f"{sym}{sfx}")
                for kind, (sfx, _m) in _KINDS.items()
            }
            rec = build_company(texts)
            if rec:
                # Union with what we already hold rather than overwrite it - see merge_records.
                companies[sym] = rec if replace else merge_records(companies.get(sym), rec)

        payload = {
            "version": STORE_VERSION,
            "region": region,
            "currency": currency,
            "suffix": suffix,
            "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "companies": companies,
        }
        path = out_dir / f"{region}.json.gz"
        with gzip.open(path, "wt", encoding="utf-8") as fh:
            json.dump(payload, fh, separators=(",", ":"))
        result[region] = len(companies)
        log.info("fundamentals_store: %s -> %d companies (%d from CSV this run, %s)",
                 region, len(companies), len(symbols), _size(path))

    return result


def load(region: str, store_dir: Path) -> dict[str, Any] | None:
    path = store_dir / f"{region}.json.gz"
    if not path.exists():
        return None
    try:
        with gzip.open(path, "rt", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        log.warning("fundamentals_store: cannot read %s: %s", path, exc)
        return None


def stale_symbols(region: str, store_dir: Path, older_than_days: int = 100,
                  today: date | None = None) -> list[str]:
    """Companies whose newest stored period is old enough that results have likely landed.

    This is what makes the quarterly update cheap: instead of re-scraping ~11k names, the
    refresh touches only those whose data has actually aged past a reporting cycle. Default is
    100 days - a quarter plus the usual filing lag - so a company that reports on time is
    picked up on the first run after it files, and one that has not reported yet is not
    re-scraped pointlessly every week.
    """
    data = load(region, store_dir)
    if not data:
        return []
    now = today or datetime.now(UTC).date()
    out: list[str] = []
    for sym, rec in (data.get("companies") or {}).items():
        newest = next((p for p in (rec.get("periods") or []) if p), None)
        if not newest:
            out.append(sym)
            continue
        try:
            when = date.fromisoformat(newest)
        except ValueError:
            out.append(sym)
            continue
        if (now - when).days > older_than_days:
            out.append(sym)
    return sorted(out)


def annual_dtos(rec: dict[str, Any], currency: str) -> list[StatementDTO]:
    """Every 4th TTM column as an ANNUAL statement.

    The columns are one quarter apart but each is already a full trailing year, so taking every
    4th gives snapshots one year apart. That spacing is the point: the fundamental engine reads
    consecutive rows as consecutive years, so feeding it all 20 would silently turn every YoY
    growth figure into quarter-on-quarter.
    """
    periods = rec.get("periods") or []
    out: list[StatementDTO] = []
    for idx in range(0, len(periods), 4):
        raw = periods[idx]
        if not raw:
            continue
        try:
            when = date.fromisoformat(raw)
        except ValueError:
            continue
        for kind in ("income", "balance", "cashflow"):
            cols = rec.get(kind) or {}
            values = {
                col: vals[idx]
                for col, vals in cols.items()
                if idx < len(vals) and vals[idx] is not None
            }
            if values:
                out.append(StatementDTO(kind, when, StatementPeriod.ANNUAL,
                                        reported_currency=currency, values=values))
    return out


def _statement_rows(rec: dict[str, Any], currency: str, quarterly: bool) -> dict[str, list[dict]]:
    """Statements in the shape the snapshot's company files use, newest first."""
    periods = rec.get("periods") or []
    step = 1 if quarterly else 4
    out: dict[str, list[dict]] = {}
    for kind in ("income", "balance", "cashflow"):
        cols = rec.get(kind) or {}
        if not cols:
            continue
        rows: list[dict] = []
        for idx in range(0, len(periods), step):
            raw = periods[idx]
            if not raw:
                continue
            values = {
                col: vals[idx]
                for col, vals in cols.items()
                if idx < len(vals) and vals[idx] is not None
            }
            if not values:
                continue
            rows.append({
                # Every column is already a full trailing twelve months; the quarterly series
                # differs only in spacing, so calling it "quarter" would misread as raw
                # single-quarter figures and invite seasonal comparisons.
                "period": "ttm" if quarterly else "annual",
                "fiscal_date": raw,
                "reported_currency": currency,
                **values,
            })
        if rows:
            out[kind] = rows
    return out


def apply_to_snapshot(data_dir: Path, store_dir: Path,
                      regions: list[str] | None = None) -> dict[str, int]:
    """Write stored fundamentals into the snapshot's company files.

    The refresh pipeline is file-based - quality, the trend and the model portfolio all read
    company/<provider_symbol>.json rather than the database - so this, not the database ingest,
    is what actually puts the scraped data in front of the engines.

    Both series are written: `statements` stays annual because the fundamental engine reads
    consecutive rows as consecutive years, while `statements_ttm` carries every quarter for the
    8-quarter quality trend.
    """
    cdir = Path(data_dir) / "company"
    if not cdir.exists():
        log.warning("apply_to_snapshot: no company dir at %s", cdir)
        return {}

    totals: dict[str, int] = {}
    for region in regions or list(REGION_META):
        data = load(region, store_dir)
        if not data:
            continue
        suffix = data.get("suffix", REGION_META.get(region, ("", ""))[0])
        currency = data.get("currency") or "USD"
        written = skipped = 0
        for sym, rec in (data.get("companies") or {}).items():
            cfile = safe_file(cdir, f"{sym}{suffix}.json")
            if cfile is None or not cfile.exists():
                continue
            annual = _statement_rows(rec, currency, quarterly=False)
            if not annual:
                continue
            try:
                doc = json.loads(cfile.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            # Never trade richer history for thinner. A company whose scrape came back partial
            # would otherwise lose the years it already had, and the quality gate needs 5 known
            # checks before it will score at all - so a silent downgrade reads as "no data"
            # rather than as an error.
            have = len((doc.get("statements") or {}).get("income") or [])
            if have > len(annual.get("income") or []):
                skipped += 1
                continue
            doc["statements"] = annual
            doc["statements_ttm"] = _statement_rows(rec, currency, quarterly=True)
            try:
                cfile.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
            except OSError:
                continue
            written += 1
        totals[region] = written
        log.info("apply_to_snapshot: %s -> %d company files (%d kept richer existing)",
                 region, written, skipped)
    return totals


def ingest_region(db: Session, region: str, store_dir: Path) -> dict[str, int]:
    """Write one market's stored fundamentals into the database."""
    data = load(region, store_dir)
    if not data:
        return {"companies": 0, "ingested": 0, "statements_written": 0}

    suffix = data.get("suffix", REGION_META.get(region, ("", ""))[0])
    currency = data.get("currency") or "USD"
    companies: dict[str, Any] = data.get("companies") or {}

    ingested = written = 0
    for sym, rec in companies.items():
        provider_symbol = f"{sym}{suffix}"
        security = db.scalar(
            select(Security).where(Security.provider_symbol == provider_symbol)
        )
        if security is None:
            continue  # universe expansion owns creating securities, not this
        dtos = annual_dtos(rec, currency)
        if not dtos:
            continue
        n = upsert_statements(db, security.id, dtos)
        if n:
            ingested += 1
            written += n
            db.commit()

    result = {"companies": len(companies), "ingested": ingested, "statements_written": written}
    log.info("fundamentals_store.ingest_region(%s): %s", region, result)
    return result


def _read(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return None


def _size(path: Path) -> str:
    n = path.stat().st_size
    return f"{n / 1024 / 1024:.1f}MB" if n > 1024 * 1024 else f"{n / 1024:.0f}KB"
