"""Model portfolio — persisted holdings, rebalanced quarterly as results land.

Computing the top-N live on every page load would show today's ranking but remember nothing:
no entry price, no holding period, no record of what was dropped or why. This keeps state.

    rebalance()  - once per calendar quarter, recompute the top-N by point-in-time quality
                   score. Names that qualify are ADDED at that day's price; names that fell
                   out of the ranking are DROPPED. Every change is recorded with a reason.
    mark()       - runs every day: marks open holdings to the current price so the portfolio
                   shows live P&L between rebalances.

Sizes follow the drawdown evidence (PSX 20, others 15), not whichever N backtested highest -
that flipped between markets and was therefore noise.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.core.logging import get_logger
from app.engines.strategy.quality import assess_quality

log = get_logger(__name__)

PORTFOLIO = "model_portfolio.json"
SIZE_BY_REGION = {"psx": 20, "us": 15, "india": 15, "australia": 15, "gcc": 15}
DEFAULT_SIZE = 15


def _quarter(day: str) -> str:
    d = datetime.fromisoformat(day).date()
    return f"{d.year}-Q{(d.month - 1) // 3 + 1}"


def _load(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"holdings": {}, "changes": [], "created_at": datetime.now(UTC).isoformat()}


def _rank(rows: list[dict], region: str, company: Path) -> list[dict]:
    """Eligible names for a region, best quality first."""
    scored: list[tuple[float, dict]] = []
    for r in rows:
        if r.get("region") != region or not r.get("provider_symbol") or r.get("price") is None:
            continue
        cf = company / f"{r['provider_symbol']}.json"
        if not cf.exists():
            continue
        try:
            st = json.loads(cf.read_text(encoding="utf-8")).get("statements") or {}
        except (OSError, json.JSONDecodeError):
            continue
        q = assess_quality(st)
        if q.eligible and q.score is not None:
            scored.append((q.score, {
                "provider_symbol": r["provider_symbol"], "symbol": r.get("symbol"),
                "name": r.get("name"), "sector": r.get("sector"),
                "quality_score": q.score, "price": r.get("price"),
            }))
    scored.sort(key=lambda t: t[0], reverse=True)
    return [s for _sc, s in scored]


def rebalance(data_dir: str | Path, force: bool = False) -> dict[str, Any]:
    """Quarterly rebalance: add the new top scorers, drop those that fell out."""
    out = Path(data_dir)
    path = out / PORTFOLIO
    doc = _load(path)
    today = datetime.now(UTC).date().isoformat()
    qtr = _quarter(today)

    if not force and doc.get("last_rebalance_quarter") == qtr:
        log.info("model-portfolio: %s already rebalanced", qtr)
        return {"rebalanced": False, "quarter": qtr}

    rows: list[dict] = json.loads((out / "screener.json").read_text(encoding="utf-8"))
    company = out / "company"
    holdings: dict[str, list[dict]] = doc.get("holdings", {}) or {}
    changes: list[dict] = doc.get("changes", []) or []
    added = dropped = 0

    for region, size in SIZE_BY_REGION.items():
        ranked = _rank(rows, region, company)
        if not ranked:
            continue
        target = {r["provider_symbol"]: r for r in ranked[:size]}
        current = {h["provider_symbol"]: h for h in holdings.get(region, [])}

        # Drop: no longer among the top scorers for this market.
        keep: list[dict] = []
        for sym, h in current.items():
            if sym in target:
                h["quality_score"] = target[sym]["quality_score"]
                keep.append(h)
            else:
                px = next((r.get("price") for r in rows
                           if r.get("provider_symbol") == sym), None)
                ret = None
                if px and h.get("entry_price"):
                    ret = round((float(px) - float(h["entry_price"]))
                                / float(h["entry_price"]) * 100, 2)
                changes.append({
                    "date": today, "quarter": qtr, "region": region, "action": "drop",
                    "symbol": h.get("symbol"), "provider_symbol": sym,
                    "exit_price": px, "return_pct": ret,
                    "reason": "fell out of the top scorers",
                })
                dropped += 1

        # Add: newly in the top-N.
        for sym, t in target.items():
            if sym in current:
                continue
            keep.append({
                "provider_symbol": sym, "symbol": t["symbol"], "name": t["name"],
                "sector": t["sector"], "entry_date": today, "entry_price": t["price"],
                "entry_quality": t["quality_score"], "quality_score": t["quality_score"],
            })
            changes.append({
                "date": today, "quarter": qtr, "region": region, "action": "add",
                "symbol": t["symbol"], "provider_symbol": sym,
                "entry_price": t["price"], "quality_score": t["quality_score"],
                "reason": "entered the top scorers",
            })
            added += 1

        holdings[region] = sorted(keep, key=lambda h: h.get("quality_score") or 0, reverse=True)

    doc.update({
        "holdings": holdings,
        "changes": changes[-500:],  # keep the recent audit trail bounded
        "last_rebalance": today,
        "last_rebalance_quarter": qtr,
        "updated_at": datetime.now(UTC).isoformat(),
    })
    path.write_text(json.dumps(doc), encoding="utf-8")
    log.info("model-portfolio rebalance %s: +%d added, -%d dropped", qtr, added, dropped)
    return {"rebalanced": True, "quarter": qtr, "added": added, "dropped": dropped}


def mark(data_dir: str | Path) -> dict[str, Any]:
    """Mark open holdings to the latest price so the page shows live P&L daily."""
    out = Path(data_dir)
    path = out / PORTFOLIO
    doc = _load(path)
    holdings = doc.get("holdings") or {}
    if not holdings:
        return {"marked": 0}

    prices = {
        r.get("provider_symbol"): r.get("price")
        for r in json.loads((out / "screener.json").read_text(encoding="utf-8"))
    }
    marked = 0
    for _region, hs in holdings.items():
        for h in hs:
            px = prices.get(h.get("provider_symbol"))
            if px is None or not h.get("entry_price"):
                continue
            h["price"] = px
            h["return_pct"] = round(
                (float(px) - float(h["entry_price"])) / float(h["entry_price"]) * 100, 2
            )
            marked += 1

    # Simple equal-weight portfolio return per market, so the page can headline it.
    summary = {}
    for region, hs in holdings.items():
        rets = [h["return_pct"] for h in hs if h.get("return_pct") is not None]
        if rets:
            summary[region] = {
                "holdings": len(hs),
                "avg_return_pct": round(sum(rets) / len(rets), 2),
                "winners": sum(1 for r in rets if r > 0),
            }
    doc["summary"] = summary
    doc["marked_at"] = datetime.now(UTC).isoformat()
    path.write_text(json.dumps(doc), encoding="utf-8")
    log.info("model-portfolio mark: %d holdings", marked)
    return {"marked": marked, "summary": summary}
