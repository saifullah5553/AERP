"""Every company page's ratios, recomputed each Daily from its own TTM statements.

THE DEFECT. A company file's `ratios` block was written once, by the database build of 27 July,
from ANNUAL statements, and only its P/E was touched afterwards. The Fundamentals card labels
the first row "Revenue Growth (TTM)" and showed RELIANCE's growth to March 2026; Key Ratios,
Valuation and Company vs Sector all read the same frozen block. Names added since July had no
block at all and showed dashes. Annual figures are also outside the fundamentals rule: only our
scraped quarterly-TTM statements count.

THE CURE. The file already carries `statements_ttm` (quarterly-spaced TTM rows, newest first),
and `compute_ratios` already reads such rows a year apart. Price comes from the screener row,
put on the accounts' basis for foreign US filers. P/E is the screener's own, so the page and the
grid can never disagree.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from app.core.logging import get_logger
from app.core.safe_path import safe_file
from app.engines.common import growth
from app.engines.fundamental.health import altman_z_score, piotroski_f_score
from app.engines.fundamental.ratios import MarketInputs, _year_ago, compute_ratios

log = get_logger(__name__)
NEWEST = "9999-12-31"
# Measured by the quality engine and already written to the row by refresh-quality-history:
# the page takes the engine's figure so the grid, the scorecard and the ratios agree.
ENGINE_KEYS = ("roe", "net_margin", "operating_margin", "debt_to_equity")
# NOT measured by the engine, so the row and the Fundamental Analysis panel kept whatever an
# older pass left: PAAS showed revenue growth of 33.7%, its March figure, two quarters after
# September's 37.1%. These come from here, a year apart on the TTM rows, for row and page alike.
OURS = ("revenue_growth", "eps_growth", "roa", "gross_margin", "roic")


class _Row(dict):
    """A statement row whose missing fields read as None, as the engines expect of ORM rows."""

    def __getattr__(self, name: str) -> Any:
        return self.get(name)


def _ascending(rows: Iterable[dict] | None) -> list[_Row]:
    return [_Row(r) for r in reversed(list(rows or [])) if isinstance(r, dict)]


def ttm_ratios(statements: dict, price: float | None, factor: float = 1.0,
               pe: float | None = None, foreign: bool = False) -> dict[str, Any] | None:
    """The ratios block for one company, or None when it has no TTM income row."""
    inc = _ascending(statements.get("income"))
    bal = _ascending(statements.get("balance"))
    cf = _ascending(statements.get("cashflow"))
    if not inc:
        return None
    shares = inc[-1].weighted_shares
    on_books = price * factor if price else None
    market = MarketInputs(price=on_books, shares_outstanding=shares)
    out = compute_ratios(inc, bal, cf, market).as_dict()

    # Year-apart pairs for anything that compares two periods: the health module and dividend
    # growth step back one row, which on quarterly TTM is one quarter.
    prior = _year_ago(inc)
    if prior is not None:
        when = prior.fiscal_date
        bal_prior = next((b for b in bal if b.fiscal_date == when), None)
        cf_prior = next((c for c in cf if c.fiscal_date == when), None)
        if bal and bal_prior is not None:
            out["piotroski_f"] = piotroski_f_score([prior, inc[-1]], [bal_prior, bal[-1]],
                                                   cf[-1:]).score
        div_now = cf[-1].dividends_paid if cf else None
        div_then = cf_prior.dividends_paid if cf_prior is not None else None
        out["dividend_growth"] = (growth(abs(div_now), abs(div_then))
                                  if div_now and div_then else None)
    else:
        out["piotroski_f"] = None
        out["dividend_growth"] = None
    mcap = market.resolved_market_cap()
    out["altman_z"] = altman_z_score(inc[-1], bal[-1] if bal else None, mcap)
    out["pe_ratio"] = pe
    eps_growth = out.get("eps_growth")
    growing = bool(pe and pe > 0 and eps_growth and eps_growth > 0)
    out["peg_ratio"] = pe / (eps_growth * 100) if growing else None
    if foreign:
        # In the accounts' currency, which the page does not label: yen read as dollars.
        out["enterprise_value"] = None
        out["book_value_per_share"] = None
    out = {k: (round(v, 6) if isinstance(v, float) else v) for k, v in out.items()}
    out["period"] = "ttm"
    out["fiscal_date"] = inc[-1].fiscal_date
    return out


def sync(out_dir: Path, rows: list[dict]) -> dict[str, int]:
    """Rewrite the ratios block of every company file the screener lists."""
    from app.ingestion.reporting_basis import load_basis

    basis = load_basis()
    company = out_dir / "company"
    stats = {"written": 0, "unchanged": 0, "no_statements": 0, "missing": 0}
    for r in rows:
        if r.get("asset_class") not in (None, "equity") or r.get("region") == "global":
            continue
        symbol = str(r.get("symbol"))
        path = safe_file(company, f"{r.get('provider_symbol') or symbol}.json")
        if path is None:
            stats["missing"] += 1
            continue
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            stats["missing"] += 1
            continue
        us = r.get("region") == "us"
        block = ttm_ratios(doc.get("statements_ttm") or {}, r.get("price"),
                           basis.factor(symbol, NEWEST) if us else 1.0,
                           pe=r.get("pe_ttm"), foreign=us and symbol in basis)
        before = (doc.get("ratios"), doc.get("fundamentals"))
        if block is None:
            stats["no_statements"] += 1
            if not doc.get("ratios"):
                continue
            # A frozen annual block is worse than none: it reads as current.
            doc["ratios"] = {"pe_ratio": r.get("pe_ttm")}
        else:
            for key in ENGINE_KEYS:
                if r.get(key) is not None:
                    block[key] = r[key]
            fundamentals = dict(doc.get("fundamentals") or {})
            for key in OURS:
                r[key] = block.get(key)
                fundamentals[key] = block.get(key)
            doc["fundamentals"] = fundamentals
            doc["ratios"] = block
        if (doc.get("ratios"), doc.get("fundamentals")) == before:
            stats["unchanged"] += 1
            continue
        try:
            path.write_text(json.dumps(doc), encoding="utf-8")
            stats["written"] += 1
        except OSError:
            stats["missing"] += 1
    log.info("company-ratios: %s", stats)
    return stats
