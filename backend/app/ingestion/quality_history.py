"""Quality score history — is this business getting stronger or weaker?

A single score says how good a company looks today. The trend says whether the thesis is
working. So for each name we recompute the quality score at successive past points and store
the series, letting the screener answer "improving / stable / deteriorating".

Always TTM, never single quarters: a raw quarter is dominated by seasonality (a retailer's
December, a fertiliser company's planting season), which would show up as a fake trend. Each
point is a full trailing twelve months, so consecutive points differ only by what actually
changed year-on-year.

Two sources, both already local — nothing is re-fetched:
  * statements_ttm          - ~20 quarterly TTM columns straight from the scraped store. Best
    source, the only one covering every market uniformly, and the reason the series runs to
    20 points: PSX has five years of TTM today, other markets as their scrapes land.
  * data/fund_cache/*.json  - up to 12 raw QUARTERS per name, rolled into ~8 quarterly-spaced
    TTM points. Only exists for names yfinance managed to serve.
  * the stored statements   - one point a year, so the trend is annual. Last resort.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.core.logging import get_logger
from app.core.safe_path import safe_file
from app.core.snapshot_lock import snapshot_lock
from app.engines.strategy.fundamental_quality import grade_for
from app.engines.strategy.quality import assess_quality
from app.ingestion.fundamentals_web import _cache_to_dtos, _roll_ttm
from app.ingestion.ohlc_store import load_bars
from app.ingestion.quality_refresh import _peer_margins, _peers_for

log = get_logger(__name__)

CACHE = Path(__file__).resolve().parents[3] / "data" / "fund_cache"
# The scraped store carries ~20 quarterly TTM columns - five years - and that whole run is
# worth showing: a five-year arc of fundamental quality says something a single score cannot.
# Markets still short of 20 simply render fewer points rather than being padded.
MAX_POINTS = 20


def _statements_at(inc: list, bal: list, cf: list, upto: int) -> dict[str, list[dict]]:
    """Statement view as of index `upto` (inclusive), newest-first, for assess_quality."""
    def pack(rows: list) -> list[dict]:
        return [{**r._v, "fiscal_date": r.fiscal_date.isoformat()}
                for r in reversed(rows[: upto + 1])]
    # Balance sheets are snapshots, so align them to the same cut-off by date.
    cut = inc[upto].fiscal_date if upto < len(inc) else None
    bal_cut = [b for b in bal if cut is None or b.fiscal_date <= cut]
    return {
        "income": pack(inc),
        "balance": [{**b._v, "fiscal_date": b.fiscal_date.isoformat()}
                    for b in reversed(bal_cut)],
        "cashflow": [{**c._v, "fiscal_date": c.fiscal_date.isoformat()}
                     for c in reversed([x for x in cf if cut is None or x.fiscal_date <= cut])],
    }


def _series_from_cache(sym: str, peers: dict | None = None,
                       sector: str | None = None) -> list[dict] | None:
    """Quarterly-spaced TTM quality points from the cached raw quarters."""
    cf = CACHE / f"{sym}.json"
    if not cf.exists():
        return None
    try:
        raw = json.loads(cf.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    q = _cache_to_dtos(raw.get("q", []))
    if not q:
        return None
    inc, bal, cfl = _roll_ttm(q)
    if len(inc) < 2:
        return None

    out: list[dict] = []
    last_res = None
    for i in range(len(inc)):
        res = assess_quality(_statements_at(inc, bal, cfl, i), peers=peers,
                             sector=sector)
        if res.score is not None:
            last_res = res
            out.append({
                "date": inc[i].fiscal_date.isoformat(),
                "score": res.score, "passed": res.passed, "period": "ttm",
                # The six category marks for THIS period. The whole point of scoring each TTM
                # separately is to be able to see which part of the business moved, and a bare
                # total cannot answer that: 62 -> 71 could be cash flow recovering or leverage
                # coming down, and those are different companies.
                "cats": _cat_points(res),
                "confidence": res.confidence,
            })
    out = out[-MAX_POINTS:]
    if out:
        # Only the newest point carries the full category detail: it is what the scorecard
        # renders, and repeating every sub-metric for all twenty periods would multiply the
        # company file for a table nobody reads twenty times over.
        out[-1]["full_cats"] = getattr(last_res, "categories", None) or None
        out[-1]["flags"] = list(getattr(last_res, "flags", None) or [])
        out[-1]["fund_metrics"] = getattr(last_res, "fundamental_metrics", None) or None
    return out or None


def _cat_points(res) -> dict[str, float]:
    """{category: earned} for one period, rounded. Points budgets are fixed and live in
    CATEGORY_POINTS, so only what was earned needs storing per period."""
    out = {}
    for name, cat in (getattr(res, "categories", None) or {}).items():
        earned = cat.get("earned") if isinstance(cat, dict) else getattr(cat, "earned", None)
        if earned is not None:
            out[name] = round(float(earned), 2)
    return out


def _price_lookup(region: str, symbol: str):
    """price_on(date) using our own stored daily bars, or None if we have no history.

    A five-year score history must value each quarter at the price that quarter traded at.
    Scoring 2021 against today's price would not be a trend, it would be an artefact - and one
    that looks entirely plausible on a chart.
    """
    bars = load_bars(region, symbol)
    if not bars:
        return None
    dates = sorted(bars)

    def price_on(when: str):
        # Last close at or before the period end - the price actually available then.
        candidates = [d for d in dates if d <= when]
        if not candidates:
            return None
        try:
            return float(bars[candidates[-1]][4])
        except (TypeError, ValueError, IndexError):
            return None

    return price_on


def _series_from_statements(doc: dict, key: str = "statements",
                            price_on=None, peers: dict | None = None,
                            sector: str | None = None) -> list[dict] | None:
    """Score at successive past points by progressively hiding newer periods."""
    st = doc.get(key) or {}
    inc = st.get("income") or []
    if len(inc) < 2:
        return None
    period = str(inc[0].get("period") or "ttm")
    out: list[dict] = []
    last_res = None
    # Only the newest MAX_POINTS are kept, so only those are worth computing. Scoring all ~20
    # stored quarters and then slicing cost 2.5s per company - about 8 hours over the universe,
    # which is why this job never once ran to completion.
    oldest = min(len(inc), MAX_POINTS) - 1
    # Statements are newest-first, so slicing from i hides everything more recent than i.
    for i in range(oldest, -1, -1):
        view = {k: (v or [])[i:] for k, v in st.items()}
        when = str(inc[i].get("fiscal_date") or "")[:10]
        market = None
        if price_on and when:
            px = price_on(when)
            if px:
                shares = None
                for row in (inc[i], {}):
                    shares = row.get("weighted_shares") or row.get("shares_outstanding")
                    if shares:
                        break
                market = {"price": px,
                          "market_cap": (px * float(shares)) if shares else None}
        res = assess_quality(view, market=market, peers=peers,
                             sector=sector)
        if res.score is not None:
            last_res = res
            out.append({
                "date": str(inc[i].get("fiscal_date") or "")[:10],
                "score": res.score, "passed": res.passed, "period": period,
                "cats": _cat_points(res),
                "confidence": res.confidence,
            })
    out = out[-MAX_POINTS:]
    if out:
        # Only the newest point carries the full category detail: it is what the scorecard
        # renders, and repeating every sub-metric for all twenty periods would multiply the
        # company file for a table nobody reads twenty times over.
        out[-1]["full_cats"] = getattr(last_res, "categories", None) or None
        out[-1]["flags"] = list(getattr(last_res, "flags", None) or [])
        out[-1]["fund_metrics"] = getattr(last_res, "fundamental_metrics", None) or None
    return out or None


# Fitted movement across the whole history, in score points, at which a trajectory earns each
# label. STRONG is reserved for a move of 15 points - roughly a grade and a half - so it means
# something when it appears.
_STRONG = 15.0
_MOVE = 5.0
# Scatter around the fit, above which a flat net change is "mixed" rather than "stable": a
# company that ran 50 -> 80 -> 50 did not have a stable five years.
_NOISE = 6.0


def _trend(series: list[dict]) -> tuple[str, float | None]:
    """Classify the WHOLE score history, not its endpoints.

    First-versus-last reads 50 -> 80 -> 50 as unchanged and 50 -> 20 -> 55 as an improvement.
    Both are the same answer for opposite stories, and both were being published. A least-
    squares fit over every period asks the different question - which way has this company been
    going, on balance, across five years - and the scatter around that fit separates a steady
    company from a volatile one whose net change happens to be small.

    Returns (label, latest-minus-previous). The change is the LAST STEP, because that is the
    most recent fundamental signal; the label carries the long view.
    """
    scores = [s["score"] for s in series if s.get("score") is not None]
    if len(scores) < 2:
        return "unknown", None
    step = round(scores[-1] - scores[-2], 2)
    if len(scores) < 4:
        # Too short to fit a line through with any confidence; fall back to the net move.
        net = scores[-1] - scores[0]
        if net >= _MOVE:
            return "improving", step
        if net <= -_MOVE:
            return "deteriorating", step
        return "stable", step

    n = len(scores)
    mean_x = (n - 1) / 2
    mean_y = sum(scores) / n
    sxx = sum((i - mean_x) ** 2 for i in range(n))
    sxy = sum((i - mean_x) * (y - mean_y) for i, y in enumerate(scores))
    slope = (sxy / sxx) if sxx else 0.0
    fitted = slope * (n - 1)          # the move the fit implies across the whole series

    resid = [y - (mean_y + slope * (i - mean_x)) for i, y in enumerate(scores)]
    noise = (sum(r * r for r in resid) / n) ** 0.5

    if fitted >= _STRONG:
        return "strongly_improving", step
    if fitted >= _MOVE:
        return "improving", step
    if fitted <= -_STRONG:
        return "strongly_deteriorating", step
    if fitted <= -_MOVE:
        return "deteriorating", step
    return ("mixed" if noise > _NOISE else "stable"), step


def _history_stats(series: list[dict]) -> dict[str, float | None]:
    """Where the latest score sits against the company's OWN five-year record.

    A score of 62 means one thing for a company that has never been above 60 and another for
    one that spent four years in the eighties. The percentile is what makes the difference
    legible without having to read the whole series.
    """
    scores = [s["score"] for s in series if s.get("score") is not None]
    if not scores:
        return {}
    latest = scores[-1]
    at_or_below = sum(1 for s in scores if s <= latest)
    return {
        "score_high": round(max(scores), 2),
        "score_low": round(min(scores), 2),
        "score_avg": round(sum(scores) / len(scores), 2),
        "score_percentile": round(100 * at_or_below / len(scores), 1),
        "score_periods": len(scores),
    }


def refresh_quality_history(data_dir: str | Path, limit: int | None = None) -> dict[str, int]:
    with snapshot_lock("quality-history", data_dir) as ok:
        if not ok:
            return {"skipped": 1}
        return _refresh(data_dir, limit)


def _refresh(data_dir: str | Path, limit: int | None = None) -> dict[str, int]:
    out = Path(data_dir)
    cdir = out / "company"
    rows: list[dict] = json.loads((out / "screener.json").read_text(encoding="utf-8"))
    targets = [r for r in rows if r.get("provider_symbol")]
    if limit is not None:
        targets = targets[:limit]

    # Same peer medians the headline score uses - margins graded against a different peer group
    # would reintroduce exactly the disagreement this is fixing.
    medians = _peer_margins(targets, cdir)

    built = from_store = from_cache = improving = deteriorating = 0
    for i, r in enumerate(targets, 1):
        # This is a read-modify-write over every company file, so a full pass takes tens of
        # minutes. Without a heartbeat it is indistinguishable from a hang, and a silent
        # long-runner is what gets killed by mistake.
        if i % 500 == 0:
            log.info("refresh-quality-history: %d/%d (built %d)", i, len(targets), built)
        # Never build this path by hand: a ticker like CON resolves to a Windows device and
        # the read blocks forever at 0% CPU - which is what this job kept doing.
        cfile = safe_file(cdir, f"{r['provider_symbol']}.json")
        if cfile is None or not cfile.exists():
            continue
        try:
            doc = json.loads(cfile.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue

        # Preference order is a data-quality order. The scraped store carries ~20 quarterly TTM
        # columns for every market; the yfinance cache carries at most 12 raw quarters and only
        # for names it managed to fetch; the annual statements give one point a year.
        price_on = _price_lookup(str(r.get("region") or ""), str(r.get("symbol") or ""))
        peers = _peers_for(r, medians)
        sector = r.get("sector")
        series = _series_from_statements(doc, "statements_ttm", price_on, peers, sector)
        if series:
            from_store += 1
        else:
            series = _series_from_cache(r["provider_symbol"], peers, sector)
            if series:
                from_cache += 1
            else:
                series = _series_from_statements(doc, "statements", price_on, peers, sector)
        if not series:
            continue

        direction, change = _trend(series)
        stats = _history_stats(series)
        doc["quality_history"] = series
        doc["quality_trend"] = {"direction": direction, "change": change,
                                "points": len(series), "period": series[-1]["period"],
                                **stats}

        # The scorecard on the company page IS the newest period of this series, restated here
        # rather than left to a separate job to compute and hope they agree. They did not:
        # refresh-quality scores the company independently and last ran on the previous engine,
        # so HCI published 93.7 in the scorecard against 85.4 everywhere else - two numbers
        # answering one question, under headings a reader would take to be the same thing, and
        # the scorecard still itemising a category that no longer exists.
        newest = series[-1]
        card = dict(doc.get("fundamental_scorecard") or {})
        card["score"] = newest["score"]
        card["grade"] = grade_for(newest["score"])
        card["as_of"] = newest.get("date")
        if newest.get("confidence") is not None:
            card["confidence"] = newest["confidence"]
        # Categories come from the newest period in full - earned, budget and the sub-metrics
        # behind them - so a category the engine has retired cannot linger on the page. The
        # scorecard was still itemising "Capital Efficiency /20", which no longer exists.
        if newest.get("full_cats"):
            card["categories"] = newest["full_cats"]
        if newest.get("flags") is not None:
            card["flags"] = newest["flags"]
        if newest.get("fund_metrics"):
            card["metrics"] = newest["fund_metrics"]
        doc["fundamental_scorecard"] = card

        # The Fundamental Analysis panel reads doc["fundamentals"]. Those figures came from the
        # legacy ratio engine, which - handed quarterly TTM rows - measured growth against the
        # ADJACENT quarter and labelled it "(TTM)". HCI showed 2.90% revenue growth and -3.46%
        # EPS beside a net profit growth of 128.64% that was annual: one panel, two bases, and
        # the score computed from neither of the two that were wrong.
        #
        # Overwrite only what the engine actually measured; anything else on the panel is left
        # alone rather than blanked.
        if newest.get("fund_metrics"):
            fundamentals = dict(doc.get("fundamentals") or {})
            for key, value in newest["fund_metrics"].items():
                if value is not None:
                    fundamentals[key] = value
            doc["fundamentals"] = fundamentals
            # ...and the same figures on the screener row, so the grid's Rev Gr / ROE columns
            # cannot disagree with the company page they link to.
            for key in ("revenue_growth", "eps_growth", "roe", "roa", "net_margin",
                        "gross_margin", "operating_margin", "debt_to_equity", "roic"):
                if newest["fund_metrics"].get(key) is not None:
                    r[key] = newest["fund_metrics"][key]
        try:
            cfile.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
        except OSError:
            continue

        # The headline score IS the newest quarter, set here rather than left to agree by
        # coincidence. The three history sources build their statements differently - the
        # scraped TTM store, the yfinance cache, the annual sampling - so a headline computed
        # separately drifted from its own newest column by up to 38 points on the same date.
        # Two numbers answering one question, with nothing to say which was right.
        r["quality_score"] = series[-1]["score"]
        r["quality_trend"] = direction
        # The LATEST step - this TTM against the one before it. The most recent fundamental
        # signal there is, and the one worth sorting a screener by.
        r["quality_change"] = change
        # Where the latest score sits in the company's own five-year range. 62 means one thing
        # for a company that has never been above 60 and another for one that spent four years
        # in the eighties, and the raw score cannot tell those apart.
        for key in ("score_high", "score_low", "score_avg", "score_percentile"):
            if stats.get(key) is not None:
                r[key] = stats[key]
        # The six category marks for the newest period, so the grid can show WHERE the quality
        # is rather than only how much of it there is.
        if series[-1].get("cats"):
            r["score_cats"] = series[-1]["cats"]
        # The series itself, oldest -> newest, so the screener can draw the arc rather than
        # just name its direction. Scores only: dates live in the company file.
        r["score_history"] = [p["score"] for p in series]
        # Dates alongside, so the dashboard can label each quarter rather than showing an
        # anonymous line. Parallel arrays keep screener.json small - pairing them as objects
        # would repeat two keys 20 times for every one of 12,000 rows.
        r["score_history_dates"] = [p["date"] for p in series]
        # One flat field per quarter (q_2026Q2), because the grid sorts by column id and the
        # static sort path reads a plain numeric field. Emitted only for quarters a company
        # actually reported, so a name with three points costs three fields rather than twenty.
        for point in series:
            when = str(point.get("date") or "")
            if len(when) >= 7:
                year, month = int(when[:4]), int(when[5:7])
                r[f"q_{year}Q{(month - 1) // 3 + 1}"] = point["score"]
        # Which set of results this name's numbers are through - shown on the portfolio.
        r["results_through"] = series[-1]["date"]
        built += 1
        improving += direction == "improving"
        deteriorating += direction == "deteriorating"

    (out / "screener.json").write_text(json.dumps(rows), encoding="utf-8")
    result: dict[str, Any] = {
        "targets": len(targets), "built": built,
        "quarterly_from_store": from_store, "quarterly_from_cache": from_cache,
        "improving": improving, "deteriorating": deteriorating,
    }
    log.info("refresh-quality-history: %s", result)
    return result
