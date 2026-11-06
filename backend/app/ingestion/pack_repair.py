"""Repair split breaks in the price packs, where a recorded split proves the cause.

THE DEFECT. The pack was seeded from CSVs whose closes had a split applied twice, and then each
daily fold overwrote the most recent year with correctly adjusted closes. So a company that split
carries a step where the two meet: UBL's close "doubles" on 5 May 2025, 124.52 to 243.63, on an
exchange with a 10% daily limit, and its May 2023 close reads 29.07 when the split-adjusted figure
is 58.15. Everything before the step is too low by exactly the split ratio.

It went unnoticed because only long-horizon readers touch that history. Technical scores use a
fresh year of bars. The ledger and the model portfolio use the pack, so UBL showed +1,387% from a
May 2023 entry price that never existed, and alone added 69 points to Pakistan's average.

THE RULE. A step is rescaled only when Yahoo records a split whose ratio explains it, near enough
in time, and every earlier close is multiplied by that exact ratio. A jump with no recorded split
is left alone: it may be a real move, a bad print or a re-listing, and rescaling something we
cannot explain would be inventing history. The closes here are prices only, not dividends.

A MATCHING SPLIT IS NOT PROOF, AND `proven` IS WHAT DECIDES. A real move can land near a split of
a similar size, so a name is only changed when it individually fails against Yahoo as stored and
passes once repaired.

THE REFERENCE NEEDS CARE TOO. Yahoo serves US history split-adjusted and much of PSX unadjusted,
so `agreement` works out which it is, per split, from whether the price actually steps there.
Accepting a match against either reading was wrong: IBKR's double-adjusted 7.86 matched Yahoo's
adjusted 30.6 divided by the split again, and it passed as clean while the ledger showed +713%.
"""

from __future__ import annotations

import math
from bisect import bisect_left
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, date, datetime
from statistics import median

import httpx

from app.core.logging import get_logger

log = get_logger(__name__)

_CHART = ("https://query1.finance.yahoo.com/v8/finance/chart/{sym}"
          "?range=10y&interval=1mo&events=split")
_DAILY = "https://query1.finance.yahoo.com/v8/finance/chart/{sym}?range=10y&interval=1d"
_UA = "Mozilla/5.0 (compatible; AERP/1.0)"

# A one-bar move has to be at least this big to be considered. Below it a split is not
# distinguishable from a real day, and 4:3 is about the smallest ratio that occurs.
MIN_STEP = 0.25
# The step includes one real day's move, and most exchanges here limit that to 10%.
RATIO_TOLERANCE = 0.12
# The seam sits where the fold's one-year window began, so up to a year or so BEFORE the split.
MAX_DAYS_BEFORE_SPLIT = 420
MAX_DAYS_AFTER_SPLIT = 10
STEP_WINDOW = 15
SAMPLE_EVERY = 25
MIN_SAMPLE = 10
MATCH_TOLERANCE = 0.03
MAX_AGREEMENT_BEFORE = 0.70
MIN_AGREEMENT_AFTER = 0.90


@dataclass(slots=True)
class Split:
    day: str
    ratio: float       # new shares per old: 2.0 for 2:1, 0.1 for a 1:10 consolidation


@dataclass(slots=True)
class Result:
    closes: dict[str, float]
    applied: list[tuple[str, float]]        # (first day after the seam, ratio)
    unexplained: list[tuple[str, float, float]]


def _gap(a: str, b: str) -> int:
    return (date.fromisoformat(b) - date.fromisoformat(a)).days


def repair(closes: dict[str, float], splits: list[Split]) -> Result:
    """Rescale everything before each step a recorded split explains."""
    days = sorted(closes)
    fixed = dict(closes)
    unused = list(splits)
    applied: list[tuple[str, float]] = []
    unexplained: list[tuple[str, float, float]] = []
    # Newest first, so each step is measured with the later ones already joined up.
    for i in range(len(days) - 1, 0, -1):
        before, after = fixed[days[i - 1]], fixed[days[i]]
        if not before or not after:
            continue
        step = after / before
        if abs(step - 1.0) < MIN_STEP:
            continue
        match = next((s for s in unused
                      if abs(step / s.ratio - 1.0) <= RATIO_TOLERANCE
                      and -MAX_DAYS_AFTER_SPLIT <= _gap(days[i], s.day) <= MAX_DAYS_BEFORE_SPLIT),
                     None)
        if match is None:
            unexplained.append((days[i], before, after))
            continue
        unused.remove(match)
        for day in days[:i]:
            fixed[day] = fixed[day] * match.ratio
        applied.append((days[i], match.ratio))
    return Result(fixed, applied, unexplained)


def _steps_at(reference: dict[str, float], split: Split) -> bool:
    """Does this series still carry the split as a step, i.e. is it unadjusted there?

    Medians either side, because Yahoo's PSX history has stray days on the other basis. Compared
    in logs against both answers, so a 1.1 bonus issue is judged as fairly as a 10:1 split.
    """
    days = sorted(reference)
    cut = bisect_left(days, split.day)
    before = [reference[d] for d in days[max(0, cut - STEP_WINDOW):cut]]
    after = [reference[d] for d in days[cut:cut + STEP_WINDOW]]
    if not before or not after:
        return False
    move = math.log(median(before) / median(after))
    return abs(move - math.log(split.ratio)) < abs(move)


def agreement(closes: dict[str, float], reference: dict[str, float],
              splits: list[Split]) -> float | None:
    """Share of sampled days within tolerance of Yahoo, or None with too few days to say.

    The target is Yahoo's close put on today's basis: divided by each later split that Yahoo's
    series has not already absorbed.
    """
    days = [d for d in sorted(closes) if reference.get(d)][::SAMPLE_EVERY]
    if len(days) < MIN_SAMPLE:
        return None
    unadjusted = [s for s in splits if _steps_at(reference, s)]
    good = 0
    for day in days:
        target = reference[day]
        for split in unadjusted:
            if split.day > day:
                target /= split.ratio
        good += abs(closes[day] / target - 1.0) <= MATCH_TOLERANCE
    return good / len(days)


def proven(before: float | None, after: float | None) -> bool:
    """Wrong as stored, and right once repaired. Anything less stays as it is."""
    return (before is not None and after is not None
            and before <= MAX_AGREEMENT_BEFORE and after >= MIN_AGREEMENT_AFTER)


def fetch_splits(symbol: str, client: httpx.Client) -> list[Split] | None:
    """Every split Yahoo records for a symbol, or None when it would not answer."""
    try:
        resp = client.get(_CHART.format(sym=symbol), headers={"User-Agent": _UA}, timeout=30)
        if resp.status_code == 404:
            return []
        resp.raise_for_status()
        result = resp.json()["chart"]["result"][0]
    except Exception:  # noqa: BLE001 - one bad symbol must not stop the sweep
        return None
    out = []
    for event in ((result.get("events") or {}).get("splits") or {}).values():
        try:
            ratio = float(event["numerator"]) / float(event["denominator"])
            day = datetime.fromtimestamp(int(event["date"]), UTC).date().isoformat()
        except (KeyError, TypeError, ValueError, ZeroDivisionError):
            continue
        if ratio > 0 and ratio != 1.0:
            out.append(Split(day, ratio))
    return sorted(out, key=lambda s: s.day, reverse=True)


def fetch_closes(symbol: str, client: httpx.Client) -> dict[str, float] | None:
    """Yahoo's daily closes for as long as it has them, to check a repair against."""
    try:
        resp = client.get(_DAILY.format(sym=symbol), headers={"User-Agent": _UA}, timeout=40)
        resp.raise_for_status()
        result = resp.json()["chart"]["result"][0]
        offset = (result.get("meta") or {}).get("gmtoffset") or 0
        days = [datetime.fromtimestamp(ts + offset, UTC).date().isoformat()
                for ts in result["timestamp"]]
        closes = result["indicators"]["quote"][0]["close"]
    except Exception:  # noqa: BLE001 - one bad symbol must not stop the sweep
        return None
    return {d: c for d, c in zip(days, closes, strict=True) if c}


def sweep(region: str, provider: dict[str, str], apply: bool = False,
          workers: int = 6) -> dict[str, object]:
    """Find what is provably wrong in a market's pack, and with `apply`, repair only that.

    `provider` maps pack keys to Yahoo symbols, so only names in the universe are considered.
    """
    from app.ingestion.price_pack import load_packed, merge_series

    pack = load_packed(region)
    stepped = []
    for key in provider:
        series = pack.get(key) or {}
        closes = [series[d] for d in sorted(series)]
        if any(a and b and abs(b / a - 1.0) >= MIN_STEP
               for a, b in zip(closes, closes[1:], strict=False)):
            stepped.append(key)

    with httpx.Client(follow_redirects=True) as client:
        with ThreadPoolExecutor(workers) as pool:
            splits = dict(zip(stepped, pool.map(lambda k: fetch_splits(provider[k], client),
                                                stepped), strict=True))
        candidates = {}
        for key, found in splits.items():
            if found:
                result = repair(dict(pack[key]), found)
                if result.applied:
                    candidates[key] = result
        with ThreadPoolExecutor(workers) as pool:
            yahoo = dict(zip(candidates, pool.map(lambda k: fetch_closes(provider[k], client),
                                                  candidates), strict=True))

    repaired: dict[str, dict[str, float]] = {}
    for key, result in candidates.items():
        reference = yahoo.get(key)
        if reference and proven(agreement(dict(pack[key]), reference, splits[key]),
                                agreement(result.closes, reference, splits[key])):
            repaired[key] = result.closes
    if apply and repaired:
        merge_series(region, repaired)
    log.info("pack-repair[%s]: %d stepped, %d explained by a split, %d proven: %s",
             region, len(stepped), len(candidates), len(repaired), sorted(repaired))
    return {"stepped": len(stepped), "candidates": len(candidates), "proven": sorted(repaired),
            "applied": apply}
