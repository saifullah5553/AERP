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

# The index whose trend represents each market. DFM has no index row in the snapshot, so that
# market runs on breadth alone rather than borrowing another market's index.
REGION_INDEX = {
    "us": "^GSPC",
    "india": "^NSEI",
    "australia": "^AXJO",
    "gcc": "^TASI.SR",
    "psx": "^KSE100",
    "dfm": None,
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


def _breadth_signal(region_rows: list[dict]) -> dict | None:
    """Mean composite across the market's equities - how much of it is working, not just the
    index, which a handful of large names can carry on their own."""
    vals = [r["composite_score"] for r in region_rows
            if r.get("composite_score") is not None
            and (r.get("asset_class") or "equity") == "equity"]
    if len(vals) < 5:
        return None
    avg = sum(vals) / len(vals)
    return {
        "key": "breadth",
        "label": "Market Breadth",
        "value": f"avg score {avg:.0f} across {len(vals):,}",
        "score": round(avg, 1),
        "source": "composite score, this snapshot",
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
        if idx:
            signals.append(idx)
        breadth = _breadth_signal(by_region.get(region) or [])
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
