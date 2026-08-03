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

# provider_symbol suffix and reporting currency per market. GCC is absent because
# stockanalysis does not carry Tadawul.
REGION_META: dict[str, tuple[str, str]] = {
    "us": ("", "USD"),
    "india": (".NS", "INR"),
    "australia": (".AX", "AUD"),
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


def consolidate(csv_dir: Path, out_dir: Path, regions: list[str] | None = None) -> dict[str, int]:
    """Distil raw scraped CSVs into one gzipped JSON per market."""
    out_dir.mkdir(parents=True, exist_ok=True)
    result: dict[str, int] = {}

    for region in regions or list(REGION_META):
        rdir = csv_dir / region
        if not rdir.exists():
            continue
        suffix, currency = REGION_META[region]
        income_sfx = _KINDS["income"][0]
        symbols = sorted(p.name[: -len(income_sfx)] for p in rdir.glob(f"*{income_sfx}"))

        companies: dict[str, Any] = {}
        for sym in symbols:
            texts = {
                kind: _read(rdir / f"{sym}{sfx}")
                for kind, (sfx, _m) in _KINDS.items()
            }
            rec = build_company(texts)
            if rec:
                companies[sym] = rec

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
        log.info("fundamentals_store: %s -> %d companies (%s)",
                 region, len(companies), _size(path))

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
            cfile = cdir / f"{sym}{suffix}.json"
            if not cfile.exists():
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
