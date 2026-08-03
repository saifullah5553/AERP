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
    source and the only one that covers every market uniformly.
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
from app.engines.strategy.quality import assess_quality
from app.ingestion.fundamentals_web import _cache_to_dtos, _roll_ttm

log = get_logger(__name__)

CACHE = Path(__file__).resolve().parents[3] / "data" / "fund_cache"
MAX_POINTS = 8


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


def _series_from_cache(sym: str) -> list[dict] | None:
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
    for i in range(len(inc)):
        res = assess_quality(_statements_at(inc, bal, cfl, i))
        if res.score is not None:
            out.append({
                "date": inc[i].fiscal_date.isoformat(),
                "score": res.score, "passed": res.passed, "period": "ttm",
            })
    return out[-MAX_POINTS:] or None


def _series_from_statements(doc: dict, key: str = "statements") -> list[dict] | None:
    """Score at successive past points by progressively hiding newer periods."""
    st = doc.get(key) or {}
    inc = st.get("income") or []
    if len(inc) < 2:
        return None
    period = str(inc[0].get("period") or "ttm")
    out: list[dict] = []
    # Only the newest MAX_POINTS are kept, so only those are worth computing. Scoring all ~20
    # stored quarters and then slicing cost 2.5s per company - about 8 hours over the universe,
    # which is why this job never once ran to completion.
    oldest = min(len(inc), MAX_POINTS) - 1
    # Statements are newest-first, so slicing from i hides everything more recent than i.
    for i in range(oldest, -1, -1):
        view = {k: (v or [])[i:] for k, v in st.items()}
        res = assess_quality(view)
        if res.score is not None:
            out.append({
                "date": str(inc[i].get("fiscal_date") or "")[:10],
                "score": res.score, "passed": res.passed, "period": period,
            })
    return out[-MAX_POINTS:] or None


def _trend(series: list[dict]) -> tuple[str, float | None]:
    """Direction of the last few points: improving / stable / deteriorating."""
    if len(series) < 2:
        return "unknown", None
    first, last = series[0]["score"], series[-1]["score"]
    change = round(last - first, 2)
    if change >= 5:
        return "improving", change
    if change <= -5:
        return "deteriorating", change
    return "stable", change


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
        series = _series_from_statements(doc, "statements_ttm")
        if series:
            from_store += 1
        else:
            series = _series_from_cache(r["provider_symbol"])
            if series:
                from_cache += 1
            else:
                series = _series_from_statements(doc)
        if not series:
            continue

        direction, change = _trend(series)
        doc["quality_history"] = series
        doc["quality_trend"] = {"direction": direction, "change": change,
                                "points": len(series), "period": series[-1]["period"]}
        try:
            cfile.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
        except OSError:
            continue

        r["quality_trend"] = direction
        r["quality_change"] = change
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
