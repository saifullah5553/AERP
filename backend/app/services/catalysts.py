"""Catalyst tracker feed (Feature 9) — real, dated, forward-looking events.

Aggregates Pakistan market catalysts from Portfolio360: the economic-event calendar
(SBP policy-rate decisions, data releases), per-company exchange announcements, and
corporate actions (splits / dividends). Written to catalysts.json so the company page
can surface the events relevant to a symbol (plus the market-wide macro calendar).

Network-only (no DB) and CI-friendly. Only real disclosed events — no fabrication.
"""

from __future__ import annotations

from app.core.logging import get_logger
from app.ingestion.portfolio360 import Portfolio360Client

log = get_logger(__name__)


def build_catalysts(client: Portfolio360Client | None = None) -> dict:
    client = client or Portfolio360Client()

    def _try(fn, default):
        try:
            return fn()
        except Exception as exc:  # network optional
            log.warning("catalysts fetch failed: %s", exc)
            return default

    events = _try(lambda: client.pk_economic_events(20), [])
    announcements = _try(lambda: client.announcements(80), [])
    actions = _try(lambda: client.pk_corporate_actions(), [])

    # Market-wide PK economic calendar.
    market_events = [
        {
            "date": e.get("date"),
            "title": e.get("title"),
            "category": e.get("category"),
            "note": e.get("note"),
        }
        for e in events if e.get("date") and e.get("title")
    ]

    # Per-symbol announcements + corporate actions (PSX).
    by_symbol: dict[str, list[dict]] = {}
    for a in announcements:
        sym = (a.get("symbol") or "").strip().upper()
        if not sym or not a.get("title"):
            continue
        by_symbol.setdefault(sym, []).append({
            "type": "announcement",
            "title": a.get("title"),
            "date": (a.get("announcedAt") or "")[:10] or a.get("date"),
            "pdf_url": a.get("pdfUrl") or a.get("sourceUrl"),
        })
    for c in actions:
        sym = (c.get("symbol") or "").strip().upper()
        if not sym or not c.get("action_type"):
            continue
        ratio = ""
        if c.get("ratio_num") and c.get("ratio_den"):
            ratio = f" {c['ratio_num']}:{c['ratio_den']}"
        by_symbol.setdefault(sym, []).append({
            "type": "corporate_action",
            "title": f"{c['action_type'].title()}{ratio}",
            "date": c.get("ex_date"),
        })

    return {
        "market_events": market_events,   # PK macro calendar
        "by_symbol": by_symbol,           # PSX per-company announcements/actions
    }
