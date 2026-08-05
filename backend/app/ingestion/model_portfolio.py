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
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from app.core.logging import get_logger
from app.core.snapshot_lock import snapshot_lock
from app.ingestion.ohlc_store import load_bars

log = get_logger(__name__)

PORTFOLIO = "model_portfolio.json"
# Below a 1.5x gap between the recorded price and the stored history, the difference is two
# sources disagreeing, not a split. The smallest split worth restating is 2:1.
SPLIT_LIKE_MIN = 1 / 1.5
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


# A quarter becomes the basis for ranking only when most of the market has reported it.
# Below this, the few early filers would be ranked on newer figures than everyone else - and
# ranking is a COMPARISON, so a company is not better because its results are fresher. On
# 5 August only 11% of PSX had filed Jun-26; by the end of the month it is most of them.
MIN_COVERAGE = 0.70


def _quarter_key(period_end: str) -> str:
    """'2026-03-31' -> 'q_2026Q1', the flat field holding that quarter's score."""
    year, month = int(period_end[:4]), int(period_end[5:7])
    return f"q_{year}Q{(month - 1) // 3 + 1}"


def basis_quarter(rows: list[dict], region: str, today: str,
                  min_coverage: float = MIN_COVERAGE) -> str | None:
    """The newest quarter the whole market can be ranked on.

    Two conditions, and both are about fairness rather than freshness. Most of the market must
    have reported it, and its rebalance date - two months on, the same lag the ledger uses -
    must have passed. Jun-26 results therefore become the basis at the end of August, not on
    the day the first company files.
    """
    scored = [r for r in rows
              if r.get("region") == region and r.get("quality_score") is not None]
    if not scored:
        return None
    reported: dict[str, int] = {}
    for r in scored:
        through = str(r.get("results_through") or "")[:10]
        if through:
            reported[through] = reported.get(through, 0) + 1

    for quarter in sorted(reported, reverse=True):
        covered = sum(n for q, n in reported.items() if q >= quarter)
        if covered / len(scored) < min_coverage:
            continue
        try:
            end = date.fromisoformat(quarter)
        except ValueError:
            continue
        month = end.month - 1 + LAG_MONTHS
        trade = date(end.year + month // 12, month % 12 + 1, min(end.day, 28))
        if trade.isoformat() <= today:
            return quarter
    return None


def _rank(rows: list[dict], region: str, company: Path,
          basis: str | None = None) -> list[dict]:
    """Eligible names for a region, best quality first - ranked on the PUBLISHED score.

    This used to recompute its own score: assess_quality over doc["statements"], which are the
    ANNUAL filings, with no sector and no peer medians. The screener's quality_score comes from
    the twenty-quarter TTM store WITH both. Two different numbers, and the portfolio was
    selecting on the one nobody could see - which is how FATIMA sat in a "top 20" at rank 101
    of 432, and SURC at rank 150.

    Ranking on the published figure is the only arrangement where the page can be checked. If
    the score is wrong, it is wrong everywhere at once and visibly so, rather than wrong in one
    place and invisible.
    """
    scored: list[tuple[float, dict]] = []
    for r in rows:
        if r.get("region") != region or not r.get("provider_symbol"):
            continue
        if r.get("price") is None or r.get("quality_score") is None:
            continue
        # Rank everyone on the SAME quarter. Using each company's own latest score would
        # compare a business judged on June against one judged on March, and reward whoever
        # reported first rather than whoever is better.
        score = r.get("quality_score")
        if basis:
            score = r.get(_quarter_key(basis))
            if score is None:
                continue
        # The same gate the screener applies, read from the same row rather than recomputed.
        if not (r.get("quality_passed") or r.get("quality_improving")):
            continue
        scored.append((float(score), {
            "provider_symbol": r["provider_symbol"], "symbol": r.get("symbol"),
            "name": r.get("name"), "sector": r.get("sector"),
            "quality_score": score, "price": r.get("price"),
            "quality_grade": r.get("quality_grade"),
            "quality_confidence": r.get("quality_confidence"),
            "results_through": basis or r.get("results_through"),
        }))
    scored.sort(key=lambda t: -t[0])
    return [d for _, d in scored]


def rebalance(data_dir: str | Path, force: bool = False) -> dict[str, Any]:
    """Quarterly rebalance: add the new top scorers, drop those that fell out."""
    with snapshot_lock("model-portfolio", data_dir) as ok:
        if not ok:
            return {"skipped": True}
        return _rebalance(data_dir, force)


LAG_MONTHS = 2


def _traded_on(results_through: str | None, region: str, symbol: str,
               fallback: str) -> tuple[str, float | None]:
    """When this pick could actually have been bought, and at what.

    A quarter's results are not knowable the day the quarter ends - companies report over the
    following weeks - so the rule acts two months later: Mar-26 results are traded at the end
    of May, not on whatever day the job first ran. Stamping "today" made every holding look
    bought on 2 August whatever quarter it was picked on, which is both wrong and unfalsifiable
    as a record.

    The price is the first close ON OR AFTER that date, from our own split-adjusted history -
    the first price that actually traded, so a rebalance falling on a holiday fills on the next
    session rather than at a number nobody could have paid.
    """
    if not results_through:
        return fallback, None
    try:
        end = date.fromisoformat(str(results_through)[:10])
    except ValueError:
        return fallback, None
    month = end.month - 1 + LAG_MONTHS
    year = end.year + month // 12
    trade = date(year, month % 12 + 1, min(end.day, 28))
    if trade.isoformat() > fallback:
        # The results are not actionable yet; nothing could have been bought on them.
        return fallback, None
    try:
        bars = load_bars(region, symbol)
    except Exception:  # noqa: BLE001 - a missing history must not block the rebalance
        return trade.isoformat(), None
    days = sorted(d for d in bars if d >= trade.isoformat())
    if not days:
        return trade.isoformat(), None
    try:
        return days[0], float(bars[days[0]][4])
    except (TypeError, ValueError, IndexError):
        return days[0], None


def _rebalance(data_dir: str | Path, force: bool = False) -> dict[str, Any]:
    out = Path(data_dir)
    path = out / PORTFOLIO
    doc = _load(path)
    today = datetime.now(UTC).date().isoformat()
    qtr = _quarter(today)
    rows: list[dict] = json.loads((out / "screener.json").read_text(encoding="utf-8"))
    company = out / "company"
    holdings: dict[str, list[dict]] = doc.get("holdings", {}) or {}
    changes: list[dict] = doc.get("changes", []) or []
    added = dropped = 0
    rebalanced_regions: dict[str, str] = {}

    for region, size in SIZE_BY_REGION.items():
        # Which quarter can this market be ranked on at all? Not the newest one that exists -
        # the newest one MOST of the market has reported, whose trade date has arrived.
        basis = basis_quarter(rows, region, today)
        if not basis:
            log.info("model-portfolio[%s]: no quarter has %.0f%% coverage yet - holding",
                     region, MIN_COVERAGE * 100)
            continue
        # Already acted on this quarter's results: nothing to do until the next one lands.
        if not force and (doc.get("basis_by_region") or {}).get(region) == basis:
            log.info("model-portfolio[%s]: already rebalanced on %s results", region, basis)
            continue
        log.info("model-portfolio[%s]: rebalancing on %s results", region, basis)
        ranked = _rank(rows, region, company, basis)
        if not ranked:
            continue
        rebalanced_regions[region] = basis
        target = {r["provider_symbol"]: r for r in ranked[:size]}
        current = {h["provider_symbol"]: h for h in holdings.get(region, [])}
        # The score of the last name that made the cut. "Dropped" on its own says nothing -
        # a holding can leave because its own quality fell, or because it stood still while
        # better names arrived. Those are different events and only the numbers separate them.
        cutoff = min((r.get("quality_score") or 0) for r in ranked[:size]) if target else None
        score_now = {r["provider_symbol"]: r.get("quality_score") for r in rows}

        # Drop: no longer among the top scorers for this market.
        keep: list[dict] = []
        for sym, h in current.items():
            if sym in target:
                h["quality_score"] = target[sym]["quality_score"]
                h["quality_grade"] = target[sym].get("quality_grade")
                h["quality_confidence"] = target[sym].get("quality_confidence")
                h["results_through"] = target[sym].get("results_through")
                keep.append(h)
            else:
                px = next((r.get("price") for r in rows
                           if r.get("provider_symbol") == sym), None)
                ret = None
                if px and h.get("entry_price"):
                    ret = round((float(px) - float(h["entry_price"]))
                                / float(h["entry_price"]) * 100, 2)
                was, now = h.get("quality_score"), score_now.get(sym)
                if was is not None and now is not None and now < was - 1:
                    reason = (f"quality fell {was - now:.1f} points, {was:.1f} to {now:.1f}"
                              + (f" (cut was {cutoff:.1f})" if cutoff is not None else ""))
                elif now is not None and cutoff is not None:
                    reason = (f"outranked at {now:.1f} - the cut rose to {cutoff:.1f}")
                elif now is None:
                    reason = "no longer scoreable from the available statements"
                else:
                    reason = "fell out of the top scorers"
                changes.append({
                    "date": today, "quarter": qtr, "region": region, "action": "drop",
                    "symbol": h.get("symbol"), "provider_symbol": sym,
                    "exit_price": px, "return_pct": ret,
                    "score_before": was, "score_after": now,
                    "reason": reason,
                })
                dropped += 1

        # Add: newly in the top-N.
        for sym, t in target.items():
            if sym in current:
                continue
            bought_on, bought_at = _traded_on(t.get("results_through"), region,
                                              str(t.get("symbol") or ""), today)
            keep.append({
                "provider_symbol": sym, "symbol": t["symbol"], "name": t["name"],
                "sector": t["sector"], "entry_date": bought_on,
                "entry_price": bought_at if bought_at is not None else t["price"],
                "entry_quality": t["quality_score"], "quality_score": t["quality_score"],
                "quality_grade": t.get("quality_grade"),
                "quality_confidence": t.get("quality_confidence"),
                "results_through": t.get("results_through"),
            })
            gained = t["quality_score"]
            reason = (f"quality {gained:.1f}"
                      + (f", clearing the {cutoff:.1f} cut" if cutoff is not None else ""))
            changes.append({
                "date": bought_on, "quarter": qtr, "region": region, "action": "add",
                "symbol": t["symbol"], "provider_symbol": sym,
                "entry_price": bought_at if bought_at is not None else t["price"],
                "quality_score": gained,
                "score_after": gained,
                "reason": reason,
            })
            added += 1

        holdings[region] = sorted(keep, key=lambda h: h.get("quality_score") or 0, reverse=True)

    doc.update({
        "holdings": holdings,
        "changes": changes[-500:],  # keep the recent audit trail bounded
        "basis_by_region": {**(doc.get("basis_by_region") or {}), **rebalanced_regions},
        "last_rebalance": today,
        "last_rebalance_quarter": qtr,
        "updated_at": datetime.now(UTC).isoformat(),
    })
    path.write_text(json.dumps(doc), encoding="utf-8")
    log.info("model-portfolio rebalance %s: +%d added, -%d dropped", qtr, added, dropped)
    return {"rebalanced": True, "quarter": qtr, "added": added, "dropped": dropped}


def _adjusted_entry(region: str, holding: dict) -> float:
    """The entry price on TODAY's basis, from our own split-adjusted daily history.

    Falls back to the recorded price when the day is not in the store - a wrong basis is still
    better than no number, and the fallback is the behaviour this replaces.
    """
    recorded = float(holding.get("entry_price") or 0) or 1.0
    symbol, when = holding.get("symbol"), str(holding.get("entry_date") or "")[:10]
    if not symbol or not when:
        return recorded
    try:
        bars = load_bars(region, str(symbol))
    except Exception:  # noqa: BLE001 - a missing history must not stop the marking
        return recorded
    on_or_after = sorted(d for d in bars if d >= when)
    if not on_or_after:
        return recorded
    try:
        close = float(bars[on_or_after[0]][4])
    except (TypeError, ValueError, IndexError):
        return recorded
    if close <= 0:
        return recorded

    # Only restate when the gap is SPLIT-SIZED. The recorded price came from the market's own
    # feed and the history from Yahoo, and the two differ by a few percent as a matter of
    # course - HINOON was out by 1.38x, which is a source disagreement, not a corporate action.
    # Importing that into the return would replace one wrong number with another.
    ratio = close / recorded if recorded else 1.0
    if SPLIT_LIKE_MIN <= ratio <= 1 / SPLIT_LIKE_MIN:
        return recorded

    # Keep what was actually paid, for the record - the adjusted figure is a restatement, not
    # a correction of the trade.
    holding.setdefault("entry_price_nominal", holding.get("entry_price"))
    holding["entry_price"] = round(close, 4)
    return close


def mark(data_dir: str | Path) -> dict[str, Any]:
    """Mark open holdings to the latest price so the page shows live P&L daily.

    The entry price is re-read from the stored daily history rather than trusted as recorded.
    That history is split-adjusted, so a holding bought before a 5:1 split is compared with
    today on the same basis. Trusting the recorded figure is what showed KOHC at -73% and DLL
    at -89% on the ledger: nothing had been lost, the two ends were simply denominated
    differently.
    """
    out = Path(data_dir)
    path = out / PORTFOLIO
    doc = _load(path)
    holdings = doc.get("holdings") or {}
    if not holdings:
        return {"marked": 0}

    screener = json.loads((out / "screener.json").read_text(encoding="utf-8"))
    prices = {r.get("provider_symbol"): r.get("price") for r in screener}
    # The quarter a holding's figures are through, and how its quality now reads. These change
    # between rebalances as results land and scores move, so marking has to refresh them - the
    # portfolio page shows both, and without this they were blank for every row: the fields
    # were only ever written at a rebalance, and the columns were added after the last one.
    latest = {r.get("provider_symbol"): r for r in screener}
    marked = 0
    for region, hs in holdings.items():
        for h in hs:
            px = prices.get(h.get("provider_symbol"))
            if px is None or not h.get("entry_price"):
                continue
            entry = _adjusted_entry(str(region), h)
            fresh = latest.get(h.get("provider_symbol")) or {}
            # NOT results_through. That records the quarter this holding was PICKED on, which
            # is a fact about the purchase and cannot change afterwards. Refreshing it from the
            # company's latest filing made 14 holdings claim they were bought on Jun-26 results
            # while the rebalance had ranked the whole market on Mar-26 - the page would have
            # asserted a basis that did not exist on the day.
            for field in ("quality_grade", "quality_confidence", "quality_score"):
                if fresh.get(field) is not None:
                    h[field] = fresh[field]
            h["price"] = px
            h["return_pct"] = round((float(px) - entry) / entry * 100, 2)
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
