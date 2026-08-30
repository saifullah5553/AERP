"""The financial-sector matrix: banks and insurers, scored on metrics they actually have.

WHY A SECOND MATRIX. The fifteen-metric matrix measures an operating company - gross margin,
inventory-adjusted liquidity, interest coverage, free cash flow. Eleven of the fifteen have no
meaning for a bank, and marking them N/A left banks scored on four: revenue growth, net profit
growth, net margin and return on equity. That is not an assessment, it is what was left over.
JPMorgan and UBL both came out at exactly 100.0 on those four and ranked above NVIDIA, which
was measured on all fifteen.

So a bank is now measured on nine metrics chosen for a balance-sheet business:

    #  Metric                    Why a bank analyst looks at it
    1  Revenue growth            total income - net interest plus fees
    2  Net profit growth
    3  Asset growth              the loan book; a bank grows by lending
    4  Book value per share      what the shareholder actually owns, compounding
    5  Return on equity          the headline measure of a bank
    6  Return on assets          the OTHER headline: earnings per unit of balance sheet,
                                 and the one leverage cannot flatter
    7  Net margin                what survives of total income
    8  Equity to assets          capital strength, and the closest we can get to a capital
                                 ratio from a general-purpose statement store
    9  Earnings stability        how much net income swings; for a lender that is where
                                 credit losses show up

WHAT IS STILL MISSING, said plainly. Net interest margin, CET1, non-performing loans,
provision coverage, CASA and the loan-to-deposit ratio are not in our quarterly-TTM store and
no arithmetic on these statements produces them. Operating income is reported by only 32.7% of
the financial sector and interest expense by 23.4%, so cost-to-income and cost of funds cannot
be built either. This matrix is the best available reading of a bank from general-purpose
statements; it is not a credit assessment, and asset quality - the thing that actually kills
banks - is exactly what it cannot see.

THE THRESHOLDS ARE MEASURED, not borrowed. Every anchor below is the 25th percentile, median
and 75th percentile of our own statements for that model: 471 banks and 187 insurers. They
land where the textbooks say they should, which is the point - a bank ROA median of 1.0% and
equity/assets of 10.7% are the numbers a credit analyst would recognise, arrived at from our
data rather than asserted over it.

BANKS AND INSURERS ARE SCORED SEPARATELY because they are not alike. Median ROA is 1.0% for a
bank and 2.7% for an insurer; equity to assets is 10.7% against 27.5%; net margin 28.6%
against 7.4%, because an insurer's revenue is premiums. One set of thresholds would have
called every insurer over-capitalised and every bank thin.

FEE FINANCIALS ARE NOT SCORED HERE. Exchanges, asset managers and index providers keep the
fifteen-metric matrix: they have real margins, real working capital and no deposit base, and
`classify_model` already separates them on the balance sheet. Sending them here would apply a
1% ROA standard to an asset manager earning 20%.
"""

from __future__ import annotations

from app.engines.fundamental.adaptive import (
    BAD,
    COUNTRIES,
    DEFAULT_COUNTRY,
    INSURER,
    Metric,
    _at,
    _series,
    prorata,
)

# Four growth, three profitability, two capital - nine metrics, equal weight, out of 100.
FIN_METRIC_COUNT = 9
FIN_CATEGORY_METRICS = {
    "fin_growth": 4,
    "fin_profitability": 3,
    "fin_capital": 2,
}

# (bad, avg, good) - the 25th percentile, median and 75th of our own statements. Anchors run
# in whichever direction the metric does; `prorata` reads the direction from the values.
ANCHORS: dict[str, dict[str, tuple[float, float, float]]] = {
    "bank": {
        "roe": (0.071, 0.104, 0.131),
        "roa": (0.007, 0.010, 0.014),
        "equity_to_assets": (0.086, 0.107, 0.127),
        "net_margin": (0.201, 0.286, 0.351),
        # Lower is better: the coefficient of variation of net income.
        "earnings_stability": (0.485, 0.257, 0.153),
    },
    "insurer": {
        "roe": (0.029, 0.108, 0.177),
        "roa": (0.005, 0.027, 0.055),
        "equity_to_assets": (0.157, 0.275, 0.428),
        "net_margin": (0.013, 0.074, 0.164),
        "earnings_stability": (1.210, 0.565, 0.307),
    },
}

MIN_STABILITY_PERIODS = 8
STABILITY_WINDOW = 20


def _cv(values: list[float | None]) -> float | None:
    """Coefficient of variation of net income - the spread relative to the average.

    Relative, not absolute, so a large bank and a small one are comparable. Undefined when the
    average is not positive: a company that lost money on average has no meaningful "variation
    around its earnings", and dividing by a negative mean would score the most troubled banks
    as the most stable.
    """
    clean = [v for v in values[:STABILITY_WINDOW] if v is not None]
    if len(clean) < MIN_STABILITY_PERIODS:
        return None
    mean = sum(clean) / len(clean)
    if mean <= 0:
        return None
    var = sum((x - mean) ** 2 for x in clean) / len(clean)
    return (var**0.5) / mean


def _latest_all(*series: list[float | None]) -> int | None:
    """Newest index where every series reports a value - see the note in adaptive_metrics."""
    if not series:
        return None
    n = min((len(s) for s in series), default=0)
    for i in range(n):
        if all(s[i] is not None for s in series):
            return i
    return None


def _growth(values: list[float | None], spans=(12, 8, 4)) -> float | None:
    """CAGR over the longest span the history supports, from the newest reported period.

    Anchored on the newest period that REPORTS a figure rather than on index 0, for the same
    reason every other metric is: a blank newest column is a reporting lag, not a zero.
    """
    start = _latest_all(values)
    if start is None:
        return None
    end = values[start]
    if end is None or end <= 0:
        return None
    for span in spans:
        i = start + span
        begin = _at(values, i)
        if begin is not None and begin > 0:
            return (end / begin) ** (4.0 / span) - 1.0
    return None


def build_financial_metrics(inc: list[dict], bal: list[dict], region: str,
                            model: str) -> list[Metric]:
    """The nine metrics of the financial matrix."""
    c = COUNTRIES.get(region, DEFAULT_COUNTRY)
    key = INSURER if model == INSURER else "bank"
    a = ANCHORS[key]
    kind = "insurer" if key == INSURER else "bank"

    rev = _series(inc, "revenue")
    net = _series(inc, "net_income")
    shares = _series(inc, "weighted_shares")
    assets = _series(bal, "total_assets")
    equity = _series(bal, "total_equity")

    out: list[Metric] = []

    def add(k, category, label, value, score, benchmark, note=""):
        out.append(Metric(k, category, label, value, None, None, score, benchmark,
                          note or ("" if score is not None else "no data")))

    # ---------------------------------------------------------------- growth
    gb, ga = c.growth_good, c.growth_avg
    bench_g = f"{ga:.0%} avg / {gb:.0%} good ({c.name})"
    floor = ga - (gb - ga)
    for k, label, series in (("sales_growth", "Total Income Growth", rev),
                             ("net_growth", "Net Profit Growth", net),
                             ("asset_growth", "Asset Growth (loan book)", assets)):
        v = _growth(series)
        score = prorata(v, floor if k != "net_growth" else 0.0, ga, gb)
        if score is None and k == "net_growth":
            # A bank whose profit series crossed zero has no CAGR, and that is a finding.
            now = _at(series, _latest_all(series) or 0)
            if now is not None and now <= 0:
                score = BAD
        add(k, "fin_growth", label, v, score, bench_g)

    # Book value per share: what the shareholder owns, compounding. The series is built first
    # so the CAGR is measured on per-share book value rather than on total equity - a bank that
    # grew its equity purely by issuing stock has not compounded anything for its holders.
    bvps = [None if (e is None or s is None or s <= 0) else e / s
            for e, s in zip(equity, shares, strict=False)]
    add("book_value_growth", "fin_growth", "Book Value per Share Growth",
        _growth(bvps), prorata(_growth(bvps), floor, ga, gb), bench_g)

    # ---------------------------------------------------------------- profitability
    i = _latest_all(net, equity)
    roe = net[i] / equity[i] if i is not None and equity[i] > 0 else None
    add("roe", "fin_profitability", "Return on Equity", roe, prorata(roe, *a["roe"]),
        f"{kind} median {a['roe'][1]:.1%}, upper quartile {a['roe'][2]:.1%}")

    i = _latest_all(net, assets)
    roa = net[i] / assets[i] if i is not None and assets[i] > 0 else None
    add("roa", "fin_profitability", "Return on Assets", roa, prorata(roa, *a["roa"]),
        f"{kind} median {a['roa'][1]:.1%}, upper quartile {a['roa'][2]:.1%}")

    i = _latest_all(net, rev)
    nm = net[i] / rev[i] if i is not None and rev[i] > 0 else None
    add("net_margin", "fin_profitability", "Net Margin", nm, prorata(nm, *a["net_margin"]),
        f"{kind} median {a['net_margin'][1]:.1%}")

    # ---------------------------------------------------------------- capital & stability
    i = _latest_all(equity, assets)
    eta = equity[i] / assets[i] if i is not None and assets[i] > 0 else None
    add("equity_to_assets", "fin_capital", "Equity to Assets (capital strength)", eta,
        prorata(eta, *a["equity_to_assets"]),
        f"{kind} median {a['equity_to_assets'][1]:.1%} - NOT a regulatory capital ratio")

    cv = _cv(net)
    add("earnings_stability", "fin_capital", "Earnings Stability", cv,
        prorata(cv, *a["earnings_stability"]),
        f"variation in net income; {kind} median {a['earnings_stability'][1]:.2f}, "
        "lower is steadier")

    return out


def classify_financial(growth: str, profitability: str, capital: str, trend: str) -> str:
    """What kind of financial institution this is.

    Deliberately short of the operating-company vocabulary: with no cash-flow leg and no view
    of asset quality, most of those labels would be claims this matrix cannot support.
    """
    strong = {"Exceptional", "Strong"}
    weak = {"Weak"}

    if capital in weak and profitability in weak:
        return "Weak and Thinly Capitalised"
    if growth in strong and profitability in strong and capital in strong:
        return "Quality Compounder"
    if profitability in strong and capital in strong:
        return "Profitable & Well Capitalised"
    if growth == "Exceptional" and capital in weak:
        # Growing the book faster than the capital behind it is the classic way a lender gets
        # into trouble, and it looks like success right up until it does not.
        return "Growing Ahead of Its Capital"
    if growth == "Exceptional":
        return "High-Growth Lender"
    if capital in strong and growth in weak:
        return "Mature & Conservative"
    if trend == "Improving" and (growth in weak or profitability in weak):
        return "Turnaround"
    if profitability in weak:
        return "Low-Return Franchise"
    return "Unclassified"


__all__ = ["ANCHORS", "FIN_CATEGORY_METRICS", "FIN_METRIC_COUNT",
           "build_financial_metrics", "classify_financial"]
