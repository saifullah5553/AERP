"""PSX site fallback — partial fundamentals from the PSX data portal.

When a PSX security has no PDF-derived statements, we still populate a headline
``FundamentalSnapshot`` (P/E, EPS-derived market cap, etc.) from the public dps
company page so the screener shows *something*. This is a genuine best-effort
scrape of a page whose markup may change — it writes only the metrics it parses
and nothing else. Full statement-level fundamentals require the PDF path.
"""

from __future__ import annotations

import re
from datetime import date

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.models.enums import AssetClass, MarketRegion
from app.models.fundamentals import FundamentalSnapshot
from app.models.market import Market, Security

log = get_logger(__name__)

COMPANY_URL = "https://dps.psx.com.pk/company/{symbol}"
_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; AERP/1.0)"}

# Label → snapshot column. The dps page renders stat rows as
# "<label> ... <value>"; we match tolerant of markup/whitespace between them.
_METRIC_PATTERNS: dict[str, str] = {
    "pe_ttm": r"P/E[^0-9\-]{0,40}?(-?[\d,]+\.?\d*)",
    "dividend_yield": r"Dividend\s*Yield[^0-9\-]{0,40}?(-?[\d,]+\.?\d*)",
}


def parse_company_metrics(html: str) -> dict[str, float]:
    """Extract available headline metrics from a dps company page."""
    out: dict[str, float] = {}
    for col, pattern in _METRIC_PATTERNS.items():
        m = re.search(pattern, html, re.IGNORECASE | re.DOTALL)
        if not m:
            continue
        try:
            value = float(m.group(1).replace(",", ""))
        except ValueError:
            continue
        # Dividend yield is quoted in %, store as a fraction to match equities.
        out[col] = value / 100 if col == "dividend_yield" else value
    return out


def ingest_psx_site_metrics(
    db: Session, client: httpx.Client, only_missing: bool = True
) -> dict[str, int]:
    """Populate FundamentalSnapshot for PSX securities from the portal."""
    psx = db.scalar(select(Market).where(Market.code == "PSX"))
    if psx is None:
        return {"securities": 0, "updated": 0}

    securities = db.scalars(
        select(Security).where(
            Security.market_id == psx.id,
            Security.asset_class == AssetClass.EQUITY,
            Security.is_active.is_(True),
        )
    ).all()

    updated = 0
    for sec in securities:
        snap = db.get(FundamentalSnapshot, sec.id)
        if only_missing and snap is not None and snap.pe_ttm is not None:
            continue  # already has fundamentals (e.g. from a PDF)
        try:
            resp = client.get(COMPANY_URL.format(symbol=sec.symbol), headers=_HEADERS)
            resp.raise_for_status()
            metrics = parse_company_metrics(resp.text)
        except Exception as exc:
            log.warning("PSX site metrics failed for %s: %s", sec.symbol, exc)
            continue
        if not metrics:
            continue
        if snap is None:
            snap = FundamentalSnapshot(security_id=sec.id)
            db.add(snap)
        snap.as_of = date.today()
        for col, val in metrics.items():
            setattr(snap, col, val)
        updated += 1
    db.commit()
    result = {"securities": len(securities), "updated": updated}
    log.info("ingest_psx_site_metrics: %s", result)
    return result


# Region reference kept for callers/tests that assert PSX scope.
PSX_REGION = MarketRegion.PSX
