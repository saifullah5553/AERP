"""Fair value from several methods, chosen by what the company IS, then blended.

One DCF for every company is the mistake this module exists to correct. Discounting free cash
flow is the right tool for an industrial with capex and working capital; it is close to
meaningless for a bank, whose "capex" is regulatory capital and whose cash flow statement says
almost nothing about value creation. Applying it anyway is how a lender ends up valued off a
number that is really a deposit-flow artefact.

So the method is routed by sector, several are run wherever the data supports them, and the
published figure is the AVERAGE of the ones that survived their own sanity checks:

    FINANCIALS      residual income, P/B vs sector, dividend discount
                    - value is earned on BOOK EQUITY at a spread over the cost of that equity,
                      which is exactly what residual income measures and FCFF cannot see
    REAL ESTATE     P/B vs sector, dividend discount
                    - a developer's cash flow is off-plan collection timing, not earning power
    UTILITIES       dividend discount, DCF, P/E vs sector
                    - regulated returns and a payout policy that means something
    EVERYTHING ELSE DCF, P/E vs sector, EV/EBITDA vs sector

A METHOD THAT CANNOT BE COMPUTED IS SKIPPED, NOT DEFAULTED. Substituting a sector median for a
missing input is how a blend acquires false confidence: the average of three real numbers and
one invented one looks exactly like the average of four real ones. Where fewer than two methods
survive, the blend reports the single method and says so, and where none do it declines.

RELATIVE METHODS USE THE SECTOR MEDIAN, not the mean, and require a minimum peer count. A mean
multiple is dragged by the one company on 300x earnings; a median of four peers is not a peer
group at all.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

MIN_PEERS = 8              # below this a "sector median" is an anecdote
# A method whose answer is this far from the traded price is discarded from the blend. Same
# reasoning as the DCF's own bound: at that distance the input is wrong, not the market.
MAX_MULTIPLE, MIN_MULTIPLE = 5.0, 0.1

_FINANCIAL = ("bank", "insur", "financ", "capital market", "asset manag", "credit",
              "securities", "invest", "leasing", "modaraba", "brokerage")
_REAL_ESTATE = ("real estate", "reit", "property", "developer", "construction & real")
_UTILITY = ("utilit", "power", "electric", "gas distribution", "water")


# Financials that are NOT balance-sheet businesses. An exchange, an index provider or an asset
# manager earns fees on other people's capital: book value is small and beside the point, so
# residual income - which anchors on book - undervalues them badly. MCX came out at 398 against
# a price of 2,766 for exactly this reason. They belong with general companies, on cash flow
# and earnings multiples.
_FEE_FINANCIAL = ("exchange", "financial data", "capital markets", "asset manage",
                  "shell compan", "financial conglomerate", "fintech")


def sector_bucket(sector: str | None, industry: str | None = None) -> str:
    s = (sector or "").lower()
    ind = (industry or "").lower()
    if any(k in ind for k in _FEE_FINANCIAL):
        return "general"
    if any(k in s for k in _FINANCIAL):
        return "financial"
    if any(k in s for k in _REAL_ESTATE):
        return "real_estate"
    if any(k in s for k in _UTILITY):
        return "utility"
    return "general"


@dataclass(slots=True)
class Method:
    name: str
    value: float                # fair value per share
    basis: str                  # the one-line justification


@dataclass(slots=True)
class Blend:
    fair_value: float | None = None
    upside_pct: float | None = None
    verdict: str = "no value"
    methods: list[dict] = field(default_factory=list)
    used: int = 0
    spread_pct: float | None = None     # disagreement between methods - the honesty metric
    bucket: str = ""
    reason: str = ""


def _latest(rows: list[dict], key: str) -> float | None:
    for r in rows or []:
        v = r.get(key)
        if isinstance(v, int | float) and v != 0:
            return float(v)
    return None


def _ttm_sum(rows: list[dict], key: str) -> float | None:
    """The newest TTM value - each stored column is already a trailing year."""
    return _latest(rows, key)


def residual_income(book_per_share: float | None, eps: float | None,
                    cost_of_equity: float, growth: float) -> Method | None:
    """Book value plus the present value of returns earned ABOVE the cost of equity.

    The right model for a bank. A lender creates value only by earning more on its equity than
    that equity costs; if ROE equals the cost of equity the franchise is worth its book and no
    more, which is what this returns. FCFF cannot express that at all.
    """
    if not book_per_share or book_per_share <= 0 or eps is None:
        return None
    spread = eps - cost_of_equity * book_per_share
    if cost_of_equity - growth < 0.02:
        return None
    value = book_per_share + spread / (cost_of_equity - growth)
    if value <= 0:
        return None
    roe = eps / book_per_share
    return Method("residual_income", value,
                  f"book {book_per_share:,.2f} plus perpetual excess return; "
                  f"ROE {roe:.1%} against a {cost_of_equity:.1%} cost of equity")


def relative(multiple_name: str, per_share_metric: float | None,
             sector_multiple: float | None, peers: int) -> Method | None:
    """What the market pays a peer for the same unit of earnings, book or EBITDA."""
    if not per_share_metric or per_share_metric <= 0 or not sector_multiple or peers < MIN_PEERS:
        return None
    value = per_share_metric * sector_multiple
    if value <= 0:
        return None
    return Method(multiple_name, value,
                  f"{sector_multiple:,.1f}x the sector median across {peers} peers")


def dividend_discount(dps: float | None, cost_of_equity: float, growth: float) -> Method | None:
    """Gordon growth on the actual dividend. Only where a real payout exists."""
    if not dps or dps <= 0 or cost_of_equity - growth < 0.02:
        return None
    value = dps * (1 + growth) / (cost_of_equity - growth)
    if value <= 0:
        return None
    return Method("dividend_discount", value,
                  f"dividend {dps:,.2f} growing at {growth:.1%}, discounted at "
                  f"{cost_of_equity:.1%}")


def sector_multiples(rows: list[dict], company_dir: Any) -> dict[str, dict[str, Any]]:
    """Median P/E, P/B and EV/EBITDA per sector, from OUR universe.

    Our own peers rather than a published table: the table would be US-centric, and a Karachi
    cement company is not valued on a Houston cement multiple. Medians, and only where enough
    peers exist - a mean is dragged by the one name on 300x earnings, and four companies are
    not a sector.
    """
    import json as _json
    from statistics import median as _median

    from app.core.safe_path import safe_file

    buckets: dict[str, dict[str, list[float]]] = {}
    for r in rows:
        sector = r.get("sector")
        price = r.get("price")
        region = r.get("region")
        if not sector or not region or not isinstance(price, int | float) or price <= 0:
            continue
        # Keyed by MARKET AND SECTOR. Keying on sector alone valued a Karachi auto assembler on
        # a 20.9x median drawn from 1,065 "peers" - the whole world's autos, when PSX has 453
        # listings in total and trades nearer 7x. It made every Pakistani industrial look 2-3x
        # undervalued, which is the error you spotted in the autos and the pharma names. This
        # module's own docstring said a Karachi cement company is not valued on a Houston
        # cement multiple, and then the code did exactly that.
        slot = buckets.setdefault(f"{region}|{sector}", {"pe": [], "pb": [], "ev_ebitda": []})
        pe = r.get("pe_ttm")
        if isinstance(pe, int | float) and 0 < pe < 100:      # a 300x P/E is not a comparable
            slot["pe"].append(float(pe))
        cf = safe_file(company_dir, f"{r.get('provider_symbol')}.json")
        if cf is None or not cf.exists():
            continue
        try:
            doc = _json.loads(cf.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        st = doc.get("statements_ttm") or {}
        inc, bal = st.get("income") or [], st.get("balance") or []
        shares = _latest(inc, "weighted_shares")
        equity = _latest(bal, "total_equity")
        ebitda = _latest(inc, "ebitda")
        debt = _latest(bal, "total_debt") or 0.0
        cash_now = _latest(bal, "cash_and_equivalents") or 0.0
        if shares and shares > 0 and equity and equity > 0:
            pb = price / (equity / shares)
            if 0 < pb < 20:
                slot["pb"].append(pb)
            if ebitda and ebitda > 0:
                ev = price * shares + debt - cash_now
                mult = ev / ebitda
                if 0 < mult < 40:
                    slot["ev_ebitda"].append(mult)

    out: dict[str, dict[str, Any]] = {}
    for sector, vals in buckets.items():
        entry: dict[str, Any] = {"count": len(vals["pe"])}
        for key in ("pe", "pb", "ev_ebitda"):
            if len(vals[key]) >= MIN_PEERS:
                entry[key] = round(_median(vals[key]), 3)
        entry["count"] = max(len(vals["pe"]), len(vals["pb"]))
        out[sector] = entry
    return out


def blend(statements: dict[str, list[dict]], price: float | None, region: str,
          sector: str | None, symbol: str | None,
          sector_multiples: dict[str, dict[str, Any]] | None = None,
          industry: str | None = None) -> Blend:
    """Run the methods this company's sector calls for, and average what survives."""
    from app.engines.valuation.dcf import _FALLBACK, COUNTRY_RATES, TERMINAL_GROWTH
    from app.engines.valuation.dcf import value as dcf_value

    bucket = sector_bucket(sector, industry)
    rates = COUNTRY_RATES.get(region, _FALLBACK)
    g_term = TERMINAL_GROWTH.get(region, 0.03)

    income = (statements or {}).get("income") or []
    balance = (statements or {}).get("balance") or []
    cash = (statements or {}).get("cashflow") or []

    shares = _latest(income, "weighted_shares")
    eps = _latest(income, "eps")
    equity = _latest(balance, "total_equity")
    ebitda = _ttm_sum(income, "ebitda")
    debt = _latest(balance, "total_debt") or 0.0
    cash_now = _latest(balance, "cash_and_equivalents") or 0.0
    dividends = _latest(cash, "dividends_paid")

    book_ps = (equity / shares) if (equity and shares and shares > 0) else None
    dps = (abs(dividends) / shares) if (dividends and shares and shares > 0) else None

    # Cost of equity with the same measured beta the DCF uses, so the two models cannot
    # disagree about the discount rate while claiming to value the same company.
    beta = 1.0
    try:
        from app.engines.valuation.beta import compute as compute_beta

        if symbol:
            beta = compute_beta(region, symbol).beta
    except Exception:  # noqa: BLE001
        pass
    coe = rates["rf"] + beta * rates["erp"]

    sm = (sector_multiples or {}).get(f"{region}|{sector or ''}", {})
    peers = int(sm.get("count") or 0)

    methods: list[Method] = []
    wanted = {
        "financial": ("residual_income", "pb", "ddm"),
        "real_estate": ("pb", "ddm"),
        "utility": ("ddm", "dcf", "pe"),
        "general": ("dcf", "pe", "ev_ebitda"),
    }[bucket]

    if "dcf" in wanted:
        got = dcf_value(statements, price, region, symbol=symbol)
        if got.fair_value:
            methods.append(Method("dcf", got.fair_value, got.reason))
    if "residual_income" in wanted:
        m = residual_income(book_ps, eps, coe, min(g_term, coe - 0.03))
        if m:
            methods.append(m)
    if "pe" in wanted:
        m = relative("pe_relative", eps, sm.get("pe"), peers)
        if m:
            methods.append(m)
    if "pb" in wanted:
        m = relative("pb_relative", book_ps, sm.get("pb"), peers)
        if m:
            methods.append(m)
    if "ev_ebitda" in wanted and ebitda and shares and shares > 0 and sm.get("ev_ebitda"):
        ev = ebitda * float(sm["ev_ebitda"])
        per_share = (ev - (debt - cash_now)) / shares
        if per_share > 0 and peers >= MIN_PEERS:
            methods.append(Method("ev_ebitda_relative", per_share,
                                  f"{sm['ev_ebitda']:,.1f}x sector EV/EBITDA, less net debt"))
    if "ddm" in wanted:
        m = dividend_discount(dps, coe, min(g_term, coe - 0.03))
        if m:
            methods.append(m)

    # Discard any method that disagrees with the market by more than the model can justify -
    # the same bound the DCF applies to itself. One wild method must not drag an average that
    # is meant to be more robust than any single one of them.
    if price and price > 0:
        methods = [m for m in methods if MIN_MULTIPLE <= m.value / price <= MAX_MULTIPLE]

    if not methods:
        return Blend(bucket=bucket, reason="no method this sector calls for could be computed")

    values = [m.value for m in methods]
    fair = sum(values) / len(values)
    spread = ((max(values) - min(values)) / fair * 100) if len(values) > 1 and fair else None
    upside = ((fair / price - 1) * 100) if price and price > 0 else None
    verdict = "no value"
    if upside is not None:
        verdict = ("undervalued" if upside > 20 else
                   "overvalued" if upside < -20 else "fairly valued")

    return Blend(
        fair_value=round(fair, 4),
        upside_pct=round(upside, 2) if upside is not None else None,
        verdict=verdict,
        methods=[{"name": m.name, "value": round(m.value, 4), "basis": m.basis}
                 for m in methods],
        used=len(methods),
        spread_pct=round(spread, 1) if spread is not None else None,
        bucket=bucket,
        reason=(f"{bucket.replace('_', ' ')} company; average of "
                f"{', '.join(m.name for m in methods)}"),
    )
