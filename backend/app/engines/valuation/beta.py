"""Beta, computed from our own price history against the market's own index.

Not fetched. We already hold five years of daily closes for every listing and, since the index
work, for every benchmark - so beta is a covariance we can compute rather than a number to take
on trust. That matters beyond tidiness: a vendor's beta comes with an undisclosed window, an
undisclosed index and an undisclosed adjustment, and three vendors will give three answers for
the same stock. Here the window, the index and the adjustment are all visible below.

WEEKLY returns, not daily. Daily beta on a thinly traded listing is dominated by non-synchronous
trading - the stock does not print on the days the index moves, so the covariance is measured
against the wrong day and beta is biased toward zero. Weekly sampling is the standard remedy and
it costs nothing here.

BLUME ADJUSTMENT, deliberately. A raw regression beta is a noisy estimate of a quantity that is
known to drift toward 1.0 over time, and on a small listing the noise is larger than the signal.
The two-thirds/one-third shrink is the textbook correction and it is the difference between a
usable input and a fair value that swings on regression error.
"""

from __future__ import annotations

from dataclasses import dataclass

# Two years of weekly observations is the common professional window: long enough to estimate a
# covariance, short enough that the company is still the same company.
WEEKS = 104
MIN_OBSERVATIONS = 52
# Beyond these the estimate is almost certainly noise rather than a real risk profile.
BETA_FLOOR, BETA_CAP = 0.3, 2.5


@dataclass(slots=True)
class BetaResult:
    beta: float                 # the adjusted figure the model should use
    raw: float | None = None    # before the Blume shrink, for inspection
    observations: int = 0
    source: str = "default"     # computed | default
    note: str = ""


def _weekly_returns(series: dict[str, float], weeks: int) -> dict[str, float]:
    """{week-ending date: return}, taking the last close in each ISO week."""
    from datetime import date

    by_week: dict[tuple[int, int], tuple[str, float]] = {}
    for day, close in series.items():
        try:
            year, week, _ = date(int(day[:4]), int(day[5:7]), int(day[8:10])).isocalendar()
        except (ValueError, TypeError):
            continue
        key = (year, week)
        if key not in by_week or day > by_week[key][0]:
            by_week[key] = (day, close)

    ordered = [by_week[k][1] for k in sorted(by_week)][-(weeks + 1):]
    keys = sorted(by_week)[-(weeks + 1):]
    out: dict[str, float] = {}
    for i in range(1, len(ordered)):
        prev, now = ordered[i - 1], ordered[i]
        if prev and prev > 0 and now > 0:
            out[f"{keys[i][0]}-W{keys[i][1]:02d}"] = now / prev - 1
    return out


def compute(region: str, symbol: str) -> BetaResult:
    """Adjusted beta for one listing, or 1.0 with the reason it could not be measured."""
    from app.ingestion.price_pack import load_packed
    from app.ingestion.rebalance_ledger import INDEX_FOR_REGION

    index_symbol = INDEX_FOR_REGION.get(region)
    if not index_symbol:
        return BetaResult(1.0, note=f"no benchmark index for {region}")

    stock = load_packed(region).get(str(symbol).upper().replace("/", "_").replace(":", "_"))
    index = load_packed("global").get(index_symbol)
    if not stock or not index:
        return BetaResult(1.0, note="no stored price history for the stock or its index")

    s_ret = _weekly_returns(stock, WEEKS)
    i_ret = _weekly_returns(index, WEEKS)
    shared = sorted(set(s_ret) & set(i_ret))
    if len(shared) < MIN_OBSERVATIONS:
        return BetaResult(1.0, observations=len(shared),
                          note=f"only {len(shared)} overlapping weeks, needs {MIN_OBSERVATIONS}")

    xs = [i_ret[w] for w in shared]
    ys = [s_ret[w] for w in shared]
    n = len(xs)
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    var = sum((x - mean_x) ** 2 for x in xs)
    if var <= 0:
        return BetaResult(1.0, observations=n, note="the index did not move over the window")
    cov = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys, strict=True))
    raw = cov / var

    # Blume: two-thirds the estimate, one-third the market. Then clamped, because a beta of 6
    # from 52 noisy weeks is a data artefact and would dominate the discount rate.
    adjusted = min(max(0.67 * raw + 0.33 * 1.0, BETA_FLOOR), BETA_CAP)
    return BetaResult(
        beta=round(adjusted, 3), raw=round(raw, 3), observations=n, source="computed",
        note=f"{n} weekly returns against {index_symbol}, Blume-adjusted",
    )
