"""Market regime from the SNAPSHOT, so every market moves when its market moves.

Only Pakistan was ever live. Its signals come from Portfolio360 on each refresh, so its health
drifted 56.6 to 57.1 across a week. The other four read the database - `_index_signal`,
`_wb_change`, `_breadth` all take a Session - and the static pipeline never populates it. Each
run therefore produced an EMPTY regime for them, `_merge_regime` carried the previous entry
forward so the page would not blank, and the number froze:

    us 61.5   india 57.5   gcc 35.5   australia 70.0

Identical across all 141 commits that touched the file. Australia's exactly-70.0 was the tell.
Nothing failed and nothing said the figures were old; a fallback meant to survive a partial run
became the permanent answer.

What is computable locally, and refreshed every thirty minutes:

  * INDEX TREND - the index rows (^GSPC, ^NSEI, ^AXJO, ^TASI.SR) carry a live price and a
    technical score in the same snapshot every page reads.
  * BREADTH - the mean composite across that market's own equities. Already recomputed each
    refresh, and the frozen figures were badly wrong: Australia published 61.1 while its actual
    breadth was 37.6, a 23-point error on a signal carrying 12% of the weight.

What is NOT computable here, and is left to the database path rather than invented: policy
rates, inflation and FX. Those are macro series, they move monthly at best, and a plausible
guess at them would be worse than their absence - the weights renormalise over what exists.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.core.logging import get_logger
from app.services.macro_regime import REGION_LABEL

log = get_logger(__name__)

# The index whose trend represents each market. Every entry here must also appear in
# `universe_curated.INDICES`, or the lookup below finds nothing and the market silently keeps
# whatever index trend was last written - which is exactly how PSX came to publish a 26 Jul
# reading in the middle of August, and Dubai came to have no index signal at all.
REGION_INDEX = {
    "us": "^GSPC",
    "india": "^NSEI",
    "australia": "^AXJO",
    "gcc": "^TASI.SR",
    "psx": "^KSE100",
    "dfm": "DFMGI.AE",
}


def _rows_by_region(rows: list[dict]) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for r in rows:
        out.setdefault(str(r.get("region") or "").lower(), []).append(r)
    return out


def _index_signal(index_row: dict | None) -> dict | None:
    """Index trend from the snapshot's own index row.

    The technical score already folds trend, momentum and position against the moving averages
    into 0-100 on the same basis every other technical figure uses. Re-deriving a second trend
    measure here would give the dashboard two answers to one question.
    """
    if not index_row:
        return None
    score = index_row.get("technical_score")
    if score is None:
        return None
    price = index_row.get("price")
    change = index_row.get("change_pct")
    arrow = "→" if change is None else ("↑" if change > 0 else "↓" if change < 0 else "→")
    shown = f"{arrow} {price:,.0f}" if isinstance(price, int | float) else str(price)
    return {
        "key": "index_trend",
        "label": f"Index Trend ({index_row.get('symbol') or ''})".strip(),
        "value": shown,
        "score": round(float(score), 1),
        "source": "own daily bars, this snapshot",
        "as_of": index_row.get("as_of") or index_row.get("price_date"),
    }


MA_WINDOW = 50
MIN_BREADTH_SAMPLE = 20
RANGE_WINDOW = 250          # about a trading year


def _index_from_pack(symbol: str) -> dict | None:
    """Index trend computed straight from the stored series, when no snapshot row exists.

    ^KSE100 and DFMGI.AE are maintained in the global pack by `refresh-indices` on every run,
    but neither has ever appeared as a screener ROW - the rows come from the database export
    and the two symbols never made it in. The lookup above therefore found nothing, and the
    merge kept whatever was last written: Pakistan published a 26 July index reading in the
    middle of August, and Dubai had no index signal at all, which left its regime resting on
    breadth and inflation alone.

    Waiting on the database path to be fixed leaves those two markets wrong in the meantime,
    so this reads the series we already keep. The measure is where today's close sits inside
    its own trading-year range: 100 at a 52-week high, 0 at the low, 50 mid-range. Bounded,
    standard, and obvious to argue with - and it announces its own source so nobody has to
    guess which method produced a given number.
    """
    from app.ingestion.price_pack import load_packed

    series = load_packed("global").get(str(symbol).upper())
    if not series or len(series) < MA_WINDOW:
        return None
    days = sorted(series)[-RANGE_WINDOW:]
    closes = [series[d] for d in days]
    low, high, last = min(closes), max(closes), closes[-1]
    if high <= low:
        return None
    score = (last - low) / (high - low) * 100.0
    prior = closes[-min(len(closes), 63)]          # roughly three months back
    arrow = "↑" if last > prior else ("↓" if last < prior else "→")
    return {
        "key": "index_trend",
        "label": f"Index Trend ({symbol})",
        "value": f"{arrow} {last:,.0f}",
        "score": round(score, 1),
        "source": "position in 52-week range, our own stored series",
        "as_of": days[-1],
    }


def _breadth_signal(region_rows: list[dict], region: str) -> dict | None:
    """Percentage of the market trading above its own 50-day average.

    THIS USED TO BE THE MEAN COMPOSITE SCORE, and that was not breadth. It measured how much
    OUR ENGINE liked a market's companies, not whether the market was advancing - so Dubai,
    which has the highest median fundamental score of any market we cover, scored highest on
    "breadth" almost by construction and was published as Bullish on the strength of it. A
    regime signal that reads our own opinion back to us cannot disagree with us, which makes
    it worthless as a regime signal.

    Percent-above-50-day is the textbook measure and it is now computable: the price pack
    carries the daily closes for every market. It says something the index cannot - whether a
    rise is broad or is a handful of large names carrying an otherwise flat market.
    """
    from app.ingestion.price_pack import load_packed

    packed = load_packed(region)
    if not packed:
        return None

    above = total = 0
    for r in region_rows:
        if (r.get("asset_class") or "equity") != "equity" or not r.get("symbol"):
            continue
        key = str(r["symbol"]).upper().replace("/", "_").replace(":", "_")
        series = packed.get(key)
        if not series or len(series) < MA_WINDOW:
            continue
        days = sorted(series)[-MA_WINDOW:]
        closes = [series[d] for d in days]
        ma = sum(closes) / len(closes)
        if ma <= 0:
            continue
        total += 1
        if closes[-1] > ma:
            above += 1

    if total < MIN_BREADTH_SAMPLE:
        return None
    pct = above / total * 100.0
    return {
        "key": "breadth",
        "label": "Market Breadth",
        "value": f"{pct:.0f}% above 50-day ({above:,} of {total:,})",
        # The percentage IS the 0-100 score: half the market above its average is a neutral
        # 50, which is the right anchor and needs no rescaling.
        "score": round(pct, 1),
        "source": f"{MA_WINDOW}-day average, our own daily closes",
        "as_of": None,
    }


def snapshot_signals(data_dir: str | Path) -> dict[str, list[dict]]:
    """{region: [signal, ...]} for everything the snapshot can measure today."""
    out_dir = Path(data_dir)
    try:
        rows = json.loads((out_dir / "screener.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        log.warning("regime-snapshot: no usable screener (%s)", exc)
        return {}

    by_symbol = {r.get("provider_symbol"): r for r in rows}
    by_region = _rows_by_region(rows)

    out: dict[str, list[dict]] = {}
    for region, index_sym in REGION_INDEX.items():
        signals = []
        idx = _index_signal(by_symbol.get(index_sym)) if index_sym else None
        if idx is None and index_sym:
            # No row for this index. Fall back to the stored series rather than leaving the
            # market with no trend at all - an absent signal does not renormalise to neutral,
            # it hands the whole weight to whatever else happens to be present.
            idx = _index_from_pack(index_sym)
        if idx:
            signals.append(idx)
        breadth = _breadth_signal(by_region.get(region) or [], region)
        if breadth:
            signals.append(breadth)
        if signals:
            out[region] = signals
    return out


def merge_live_signals(regime: dict[str, Any], data_dir: str | Path,
                       weights: dict[str, float],
                       label_for: Any, stale_after_days: int = 7) -> dict[str, Any]:
    """Replace each market's stale index/breadth with what the snapshot measures now.

    Only these two signals are touched. A rate or inflation reading carried over from the last
    database-backed run is old but still TRUE - the policy rate does not change because our
    pipeline cannot see it - so it is kept and left to say its own date. A breadth figure from
    a week ago is simply wrong, because breadth is recomputed from prices every refresh.
    """
    live = snapshot_signals(data_dir)
    if not live:
        return regime

    countries = dict(regime.get("countries") or {})
    touched = []
    for region, fresh in live.items():
        country = dict(countries.get(region) or {})
        keep = [s for s in (country.get("signals") or [])
                if s.get("key") not in {sig["key"] for sig in fresh}]
        country["signals"] = fresh + keep
        country["region"] = region
        # ALWAYS set the label, never setdefault. A market this function creates - Dubai had no
        # regime entry at all - would otherwise render as a card with no title, which is exactly
        # how it shipped. And a market that was RENAMED keeps the old label forever if the
        # existing entry is left alone: "GCC (Saudi)" survived the rename to "Saudi (Tadawul)".
        country["label"] = REGION_LABEL.get(region, region.upper())

        scored = [(s["key"], s["score"]) for s in country["signals"]
                  if s.get("score") is not None]
        if scored:
            total_w = sum(weights.get(k, 0.0) for k, _ in scored)
            if total_w > 0:
                health = sum(weights.get(k, 0.0) * v for k, v in scored) / total_w
                country["health"] = round(health, 1)
                country["regime"] = label_for(country["health"])
        countries[region] = country
        touched.append(region)

    log.info("regime-snapshot: refreshed index/breadth for %s", ", ".join(sorted(touched)))
    return {**regime, "countries": countries}
