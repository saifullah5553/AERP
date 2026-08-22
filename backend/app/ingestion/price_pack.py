"""The daily closes, packed small enough to version.

WHY THIS EXISTS. `data/ohlc/` is 1.1 GB across 12,299 per-symbol CSVs and is gitignored, so CI
starts every run with an empty price store - and nothing in the pipeline fills it: price_refresh
only READS bars, and no command calls ohlc_store.refresh. The quarterly-history ledger cannot
pick a company it cannot price, so every market rebuilt as ZERO trades and overwrote the real
history with the shape of a missing input.

WHAT IS KEPT, AND WHY IT FITS. Only the date and the close. Everything that reads this - the
ledger's entries and exits, the split detector, the portfolio's mark, the point-in-time price
lookup - reads closes; open/high/low/volume are for the technical engines, which work off the
live fetch. Dropping four columns and gzipping takes the store to about 4% of the CSVs:

    psx   41.7 MB of CSV -> 2.0 MB     gcc  29.5 MB -> 1.1 MB

Roughly 45 MB for all six markets. That is proportionate in a repository that already commits a
380 MB snapshot thirty-six times a day; it is not proportionate to commit the 1.1 GB of CSVs.

The raw store stays local and authoritative. This is a derived, versioned projection of it, and
`ohlc_store.load_bars` falls back to it when the CSV is absent - which is exactly the situation
CI is in.
"""

from __future__ import annotations

import csv
import gzip
import json
from datetime import date
from pathlib import Path

from app.core.logging import get_logger

log = get_logger(__name__)

PACK_DIR = Path(__file__).resolve().parents[3] / "data" / "prices"
# Loaded once per region per process. The ledger asks for thousands of symbols in a row, and
# re-reading a 26 MB gzip for each of them would take the rebuild from seconds to hours.
_CACHE: dict[str, dict[str, dict[str, float]]] = {}


def pack_region(region: str, store: Path | None = None) -> dict[str, int]:
    """Merge the local per-symbol CSVs into data/prices/<region>.json.gz.

    MERGE, not replace. This machine holds five years of CSVs; CI holds almost none, and a run
    there refreshes a capped subset of symbols. Rebuilding the file from whatever CSVs happen to
    be on disk would therefore erase the history on the one runner that most needs it - the
    silent-erasure failure this pack exists to end. So the stored pack is the base, the CSVs
    overlay it, and a date wins if the CSV has it: a re-based split rewrites its whole series, so
    every one of its dates is present and overwrites cleanly, while a symbol nobody refreshed
    keeps everything it had.
    """
    from app.ingestion.ohlc_store import STORE

    folder = (store or STORE) / region
    existing = {sym: dict(series) for sym, series in load_packed(region).items()}
    if not folder.is_dir():
        if not existing:
            return {"symbols": 0, "points": 0}
        # Nothing local to merge - rewrite what we have rather than truncate the file to {}.
        return _write(region, existing, kept=len(existing))

    merged: dict[str, dict[str, float]] = existing
    for path in sorted(folder.glob("*.csv")):
        fresh: dict[str, float] = {}
        try:
            with open(path, encoding="utf-8") as fh:
                for row in csv.DictReader(fh):
                    day, close = (row.get("date") or "").strip(), row.get("close")
                    if not day or close in (None, ""):
                        continue
                    try:
                        value = float(close)
                    except (TypeError, ValueError):
                        continue
                    if value <= 0:
                        continue
                    # SIGNIFICANT figures, not decimal places. Fixed decimals are wrong here
                    # because these markets price across four orders of magnitude: 4 dp is
                    # excessive for a 309 dollar share and lossy for a 0.48 riyal one. Rounding
                    # decimally moved a published DFM return by a basis point for no reason.
                    # Seven significant figures is finer than any exchange quotes, and still
                    # shorter than the float32 artefacts the CSVs carry (47.529998779296875).
                    fresh[day] = float(f"{value:.7g}")
        except OSError:
            continue
        if fresh:
            merged.setdefault(path.stem, {}).update(fresh)

    return _write(region, merged, kept=len(existing))


def merge_series(region: str, series: dict[str, dict[str, float]],
                 volumes: dict[str, dict[str, float]] | None = None) -> dict[str, int]:
    """Fold freshly fetched {symbol: {date: close}} into the stored pack.

    This is how the pack stays current without a second network pass: the daily technical
    refresh already downloads a year of daily bars for the whole universe and throws them away
    after scoring. Keeping the closes costs nothing and means the price history advances on
    every run - including on CI, which has no raw CSVs to pack from.
    """
    merged = {sym: dict(s) for sym, s in load_packed(region).items()}
    kept = len(merged)
    for symbol, points in series.items():
        key = str(symbol).upper().replace("/", "_").replace(":", "_")
        clean = {}
        for day, value in points.items():
            try:
                price = float(value)
            except (TypeError, ValueError):
                continue
            if day and price > 0:
                clean[str(day)[:10]] = float(f"{price:.7g}")
        if clean:
            merged.setdefault(key, {}).update(clean)

    load_packed(region)                      # ensure the volume cache is populated
    merged_vol = {s: dict(v) for s, v in _VOL_CACHE.get(region, {}).items()}
    for symbol, points in (volumes or {}).items():
        key = str(symbol).upper().replace("/", "_").replace(":", "_")
        clean_v = {}
        for day, value in points.items():
            try:
                vol = float(value)
            except (TypeError, ValueError):
                continue
            if day and vol >= 0:
                clean_v[str(day)[:10]] = vol
        if clean_v:
            merged_vol.setdefault(key, {}).update(clean_v)
    return _write(region, merged, kept=kept, volumes=merged_vol)


def _write(region: str, merged: dict[str, dict[str, float]], kept: int,
           volumes: dict[str, dict[str, float]] | None = None) -> dict[str, int]:
    """Serialise the merged series, dates ascending, and drop the stale in-process copy."""
    out: dict[str, dict[str, list]] = {}
    points = 0
    for symbol, series in merged.items():
        if not series:
            continue
        days = sorted(series)
        entry: dict[str, list] = {"d": days, "c": [series[d] for d in days]}
        vol = (volumes or {}).get(symbol)
        if vol:
            # Aligned to the SAME day list as the closes, so index i means the same bar in
            # both arrays. None where a day has no volume rather than a zero, because zero
            # volume is a real and different statement about a trading day.
            entry["v"] = [vol.get(d) for d in days]
        out[symbol] = entry
        points += len(days)

    PACK_DIR.mkdir(parents=True, exist_ok=True)
    target = PACK_DIR / f"{region}.json.gz"
    payload = json.dumps(out, separators=(",", ":")).encode("utf-8")
    # Write beside and replace, so an interrupted run leaves the previous pack intact rather
    # than a half-written file that reads as no prices at all.
    tmp = target.with_suffix(".gz.tmp")
    with gzip.open(tmp, "wb", compresslevel=6) as fh:
        fh.write(payload)
    tmp.replace(target)
    # A process that packs and then reads must see what it just wrote, not the copy it loaded
    # before the write.
    _CACHE.pop(region, None)
    _VOL_CACHE.pop(region, None)
    log.info("price-pack[%s]: %d symbols (%d already stored), %d closes -> %.1f MB",
             region, len(out), kept, points, target.stat().st_size / 1024 / 1024)
    _report_freshness(region, out)
    return {"symbols": len(out), "points": points}


# How many calendar days behind the newest bar in a region before we call it a problem. Four
# covers an ordinary weekend plus a public holiday on either side of it.
STALE_AFTER_DAYS = 4


def _report_freshness(region: str, out: dict[str, dict[str, list]]) -> None:
    """Say out loud how old this region's newest bar is, and how much of it lags behind.

    Quotes already had `price_refresh.report_staleness`; BARS had nothing, and the difference
    mattered. When the daily refresh was being cancelled, the half-hourly job kept quoting
    today's price while this pack sat at 3 Aug for Pakistan and 11 Aug for everywhere else -
    so every technical score, divergence and index trend was computed on a fortnight-old chart
    behind a price that said today. Nothing looked wrong on any screen.

    A log line is not a fix, but it is the difference between a defect you can find and one
    that has to be stumbled over.
    """
    newest: list[str] = []
    for series in out.values():
        days = series.get("d") or []
        if days:
            newest.append(days[-1])
    if not newest:
        log.warning("price-pack[%s]: no dated bars at all", region)
        return

    latest = max(newest)
    try:
        lag = (date.today() - date.fromisoformat(latest)).days
    except ValueError:
        lag = -1
    behind = sum(1 for d in newest if d < latest)
    msg = ("price-pack[%s]: newest bar %s (%d days old), %d of %d symbols behind it")
    args = (region, latest, lag, behind, len(newest))
    if lag > STALE_AFTER_DAYS:
        log.warning(msg + " - THIS REGION'S CHARTS ARE STALE", *args)
    else:
        log.info(msg, *args)


_VOL_CACHE: dict[str, dict[str, dict[str, float]]] = {}


def load_packed(region: str) -> dict[str, dict[str, float]]:
    """{symbol: {date: close}} for a market, or {} when the pack is absent."""
    if region in _CACHE:
        return _CACHE[region]
    path = PACK_DIR / f"{region}.json.gz"
    if not path.exists():
        _CACHE[region] = {}
        return _CACHE[region]
    try:
        with gzip.open(path, "rt", encoding="utf-8") as fh:
            raw = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        log.warning("price-pack[%s]: unreadable (%s)", region, exc)
        _CACHE[region] = {}
        return _CACHE[region]

    out: dict[str, dict[str, float]] = {}
    vols: dict[str, dict[str, float]] = {}
    for symbol, series in (raw or {}).items():
        dates, closes = series.get("d") or [], series.get("c") or []
        key = str(symbol).upper()
        out[key] = dict(zip(dates, closes, strict=False))
        # "v" is OPTIONAL and sparse. Volume matters where we can get it - the Elder Force
        # Index is close times volume, so without it EFI divergences silently degrade to
        # RSI-only, which is how PSX ran for months. A symbol with no "v" simply keeps None
        # in the volume column rather than a fabricated number.
        if series.get("v"):
            vols[key] = dict(zip(dates, series["v"], strict=False))
    _VOL_CACHE[region] = vols
    _CACHE[region] = out
    log.info("price-pack[%s]: loaded %d symbols", region, len(out))
    return out


def packed_bars(region: str, symbol: str) -> dict[str, list]:
    """The packed closes in the row shape load_bars returns, so callers see no difference.

    HEADER is date, open, high, low, close, volume - close at index 4. The columns this pack
    does not carry come back as None rather than as a fabricated number: a caller that needs a
    high is better served by nothing than by a close wearing a high's name.
    """
    # The keys are CSV stems, so they carry the writer's substitutions: forex and a few
    # listings contain '/' or ':', which cannot appear in a filename. Look up by the same
    # spelling the file was written under, or those symbols miss their own history.
    key = str(symbol).upper().replace("/", "_").replace(":", "_")
    series = load_packed(region).get(key)
    if not series:
        return {}
    vols = _VOL_CACHE.get(region, {}).get(key) or {}
    return {day: [day, None, None, None, close, vols.get(day)]
            for day, close in series.items()}
