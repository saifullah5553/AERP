import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";

import { api, type LedgerMarket, type LedgerQuarter, type RebalanceLedger , type LedgerPosition } from "@/lib/api";
import { fmtNumber } from "@/lib/format";
import { Th, useSortable } from "@/lib/useSortable";

// Display order only. The list of markets comes from the ledger itself - a hardcoded array is
// how Dubai built eighteen quarters of history that no page ever showed. Anything the backend
// publishes and this array has not heard of still appears, at the end.
const ORDER = ["psx", "us", "india", "australia", "gcc", "dfm"];

// One accessor for both ledger tables - closed trades and open positions carry the same
// LedgerPosition shape, so they sort by the same rules.
const positionValue = (r: LedgerPosition, key: string): unknown => {
  switch (key) {
    case "symbol": return r.symbol;
    case "name": return r.name;
    case "entered": return r.entry_date;
    case "entry_price": return r.entry_price;
    case "exit_price": return r.exit_price;
    case "last_price": return r.last_price;
    case "return": return r.return_pct;
    default: return null;
  }
};

function pctColor(v: number | null | undefined): string {
  if (v == null) return "#94a3b8";
  return v > 0 ? "#22c55e" : v < 0 ? "#ef4444" : "#94a3b8";
}

function Pct({ v }: { v: number | null | undefined }) {
  if (v == null) return <span className="text-slate-600">—</span>;
  return (
    <span className="font-semibold" style={{ color: pctColor(v) }}>
      {v > 0 ? "+" : ""}{v.toFixed(2)}%
    </span>
  );
}

function Quarter({ q }: { q: LedgerQuarter }) {
  // Sells first: what the previous quarter's picks actually returned is the result, and the
  // new buys are only a claim until the next rebalance prices them.
  const sold = q.exits ?? [];
  const bought = q.entries ?? [];
  // Tagged and combined so the table can be sorted as one. Action stays a sortable column, so
  // the sold/bought grouping this page is built around is one click away again.
  const tagged = useMemo(
    () => [...sold.map((r) => ({ r, action: "SOLD" })), ...bought.map((r) => ({ r, action: "BOUGHT" }))],
    [sold, bought],
  );
  const trades = useSortable(
    tagged,
    (row, key) => (key === "action" ? row.action : positionValue(row.r, key)),
    { key: "action", dir: "desc" },
  );
  if (!sold.length && !bought.length) return null;

  return (
    <div className="mb-5">
      <div className="mb-1.5 flex flex-wrap items-baseline gap-3 px-1">
        <h3 className="text-sm font-bold text-slate-100">{q.quarter} results</h3>
        <span className="text-[11px] text-slate-500">
          traded {q.traded_on} · {q.universe.toLocaleString()} scored
        </span>
        {q.closed_count > 0 && (
          <span className="text-xs">
            <span className="text-slate-500">{q.closed_count} sold · </span>
            <Pct v={q.closed_avg_return_pct} />
            <span className="text-slate-500"> avg · {q.closed_winners}/{q.closed_count} up</span>
          </span>
        )}
        {/* This quarter's own scoreboard: what the book did against what the market did over
            the same two trading days. */}
        {q.portfolio_return_pct != null && (
          <span className="text-xs" title="The held book over this quarter, equal weight">
            <span className="text-slate-500">book </span>
            <Pct v={q.portfolio_return_pct} />
            {q.index_return_pct != null && (
              <>
                <span className="text-slate-500"> vs index </span>
                <Pct v={q.index_return_pct} />
                <span
                  className="ml-1 font-semibold"
                  style={{
                    color: q.portfolio_return_pct >= q.index_return_pct ? "#22c55e" : "#ef4444",
                  }}
                >
                  ({q.portfolio_return_pct >= q.index_return_pct ? "+" : ""}
                  {(q.portfolio_return_pct - q.index_return_pct).toFixed(2)}pp)
                </span>
              </>
            )}
          </span>
        )}
      </div>
      <div className="overflow-x-auto rounded-lg border border-base-600">
        <table className="w-full text-sm">
          <thead className="bg-base-800 text-[10px] uppercase tracking-wide text-slate-400">
            <tr>
              <Th sortKey="action" sort={trades.sort} onSort={trades.toggle} className="px-3 py-2 text-left">Action</Th>
              <Th sortKey="symbol" sort={trades.sort} onSort={trades.toggle} className="px-3 py-2 text-left">Ticker</Th>
              <Th sortKey="name" sort={trades.sort} onSort={trades.toggle} className="px-3 py-2 text-left">Company</Th>
              <Th sortKey="entered" sort={trades.sort} onSort={trades.toggle} align="right" className="px-3 py-2 text-right">Entered</Th>
              <Th sortKey="entry_price" sort={trades.sort} onSort={trades.toggle} align="right" className="px-3 py-2 text-right">Buy Price</Th>
              <Th sortKey="exit_price" sort={trades.sort} onSort={trades.toggle} align="right" className="px-3 py-2 text-right">Exit Price</Th>
              <Th sortKey="return" sort={trades.sort} onSort={trades.toggle} align="right" className="px-3 py-2 text-right">Return</Th>
            </tr>
          </thead>
          <tbody>
            {trades.sorted.map(({ r, action }) => {
              const isSold = action === "SOLD";
              return (
                <tr key={`${action}-${r.symbol}`}
                    className="border-t border-base-700/40 hover:bg-base-700/40">
                  <td className="px-3 py-1.5">
                    <span className="rounded px-2 py-0.5 text-[10px] font-bold"
                          style={isSold
                            ? { background: "rgba(239,68,68,0.16)", color: "#ef4444" }
                            : { background: "rgba(34,197,94,0.16)", color: "#22c55e" }}>
                      {action}
                    </span>
                  </td>
                  <td className="px-3 py-1.5 font-semibold text-accent">{r.symbol}</td>
                  <td className="max-w-[220px] truncate px-3 py-1.5 text-xs text-slate-400"
                      title={r.name ?? ""}>{r.name ?? "—"}</td>
                  <td className="num px-3 py-1.5 text-right text-[11px] text-slate-500">
                    {isSold ? r.entry_quarter : q.quarter}
                  </td>
                  <td className="num px-3 py-1.5 text-right text-slate-300">
                    {fmtNumber(r.entry_price)}
                  </td>
                  {isSold ? (
                    <td className="num px-3 py-1.5 text-right text-slate-300">
                      {fmtNumber(r.exit_price)}
                    </td>
                  ) : (
                    <td className="num px-3 py-1.5 text-right text-slate-600">held</td>
                  )}
                  {isSold ? (
                    <td className="num px-3 py-1.5 text-right"><Pct v={r.return_pct} /></td>
                  ) : (
                    <td className="num px-3 py-1.5 text-right text-slate-600">—</td>
                  )}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function Market({ m }: { m: LedgerMarket }) {
  const open = useSortable(m.open_positions ?? [], positionValue);
  if (!m.quarters?.length) {
    return (
      <div className="p-8 text-center text-sm text-slate-500">
        {m.note ?? "No rebalance history for this market yet."}
      </div>
    );
  }
  return (
    <>
      <div className="mb-4 flex flex-wrap items-center gap-4 rounded-lg border border-base-600 bg-base-800 px-4 py-2.5">
        <span className="text-sm font-bold text-slate-100">{m.label}</span>
        <span className="text-xs text-slate-500">top {m.top_n}, rebalanced quarterly</span>
        {m.realised_trades > 0 && (
          <span className="text-xs">
            <span className="text-slate-500">{m.realised_trades} closed · </span>
            <Pct v={m.realised_avg_return_pct} />
            <span className="text-slate-500">
              {" "}avg · {m.realised_winners}/{m.realised_trades} up
            </span>
          </span>
        )}
        {m.compounded_return_pct != null && (
          <span className="text-xs" title="Each quarter's equal-weight return, compounded">
            <span className="text-slate-500">compounded </span>
            <Pct v={m.compounded_return_pct} />
            {m.first_quarter && (
              <span className="text-slate-500"> · {m.first_quarter} to {m.last_quarter}</span>
            )}
          </span>
        )}
        {/* The benchmark over the SAME quarters. Without it "compounded +88%" reads as a win
            even when the index made 152% over the same stretch, which is what the US actually
            did. The excess is the number that answers "did we beat it". */}
        {m.index_compounded_return_pct != null && (
          <span
            className="text-xs"
            title={`${m.index_label ?? "Index"} over the same ${m.index_quarters} quarters, compounded the same way`}
          >
            <span className="text-slate-500">{m.index_label ?? "index"} </span>
            <Pct v={m.index_compounded_return_pct} />
            {m.excess_return_pct != null && (
              <>
                <span className="text-slate-500"> · </span>
                <span
                  className="font-semibold"
                  style={{ color: m.excess_return_pct >= 0 ? "#22c55e" : "#ef4444" }}
                >
                  {m.excess_return_pct >= 0 ? "beat by " : "lagged by "}
                  {Math.abs(m.excess_return_pct).toFixed(2)}pp
                </span>
              </>
            )}
          </span>
        )}
        {m.index_compounded_return_pct == null && m.compounded_return_pct != null && (
          <span className="text-xs text-slate-600" title="No index history is available for this market, so no comparison is shown rather than one built from our own universe">
            no index available
          </span>
        )}
        {m.open_positions?.length > 0 && (
          <span className="ml-auto text-xs text-slate-500">
            {m.open_positions.length} still held
          </span>
        )}
      </div>

      {/* Newest quarter first. */}
      {m.quarters.slice().reverse().map((q) => <Quarter key={q.results_for} q={q} />)}

      {m.open_positions?.length > 0 && (
        <div className="mb-6">
          <h3 className="mb-1.5 px-1 text-sm font-bold text-slate-100">
            Still held
            <span className="ml-2 text-[11px] font-normal text-slate-500">
              marked to the last close — an unrealised gain is not a result
            </span>
          </h3>
          <div className="overflow-x-auto rounded-lg border border-base-600">
            <table className="w-full text-sm">
              <thead className="bg-base-800 text-[10px] uppercase tracking-wide text-slate-400">
                <tr>
                  <Th sortKey="symbol" sort={open.sort} onSort={open.toggle} className="px-3 py-2 text-left">Ticker</Th>
                  <Th sortKey="name" sort={open.sort} onSort={open.toggle} className="px-3 py-2 text-left">Company</Th>
                  <Th sortKey="entered" sort={open.sort} onSort={open.toggle} align="right" className="px-3 py-2 text-right">Entered</Th>
                  <Th sortKey="entry_price" sort={open.sort} onSort={open.toggle} align="right" className="px-3 py-2 text-right">Buy Price</Th>
                  <Th sortKey="last_price" sort={open.sort} onSort={open.toggle} align="right" className="px-3 py-2 text-right">Last</Th>
                  <Th sortKey="return" sort={open.sort} onSort={open.toggle} align="right" className="px-3 py-2 text-right">Unrealised</Th>
                </tr>
              </thead>
              <tbody>
                {open.sorted.map((r) => (
                  <tr key={r.symbol} className="border-t border-base-700/40 hover:bg-base-700/40">
                    <td className="px-3 py-1.5 font-semibold text-accent">{r.symbol}</td>
                    <td className="max-w-[220px] truncate px-3 py-1.5 text-xs text-slate-400"
                        title={r.name ?? ""}>{r.name ?? "—"}</td>
                    <td className="num px-3 py-1.5 text-right text-[11px] text-slate-500">
                      {r.entry_quarter}
                    </td>
                    <td className="num px-3 py-1.5 text-right text-slate-300">
                      {fmtNumber(r.entry_price)}
                    </td>
                    <td className="num px-3 py-1.5 text-right text-slate-300">
                      {fmtNumber(r.last_price)}
                    </td>
                    <td className="num px-3 py-1.5 text-right"><Pct v={r.return_pct} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </>
  );
}

// Quarterly rebalance ledger: what the top-N-by-fundamental-score rule bought each quarter, what
// it sold when a name dropped out, and what the round trip returned — per market, last four
// rebalances.
export default function BuySellPage() {
  const [led, setLed] = useState<RebalanceLedger | null>(null);
  const [market, setMarket] = useState("psx");
  const [quarter, setQuarter] = useState("all");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const ctrl = new AbortController();
    api.rebalanceLedger(ctrl.signal).then(setLed).catch(() => setLed(null))
      .finally(() => setLoading(false));
    return () => ctrl.abort();
  }, []);

  const markets = Object.keys(led?.markets ?? {}).sort((a, b) => {
    const ia = ORDER.indexOf(a);
    const ib = ORDER.indexOf(b);
    return (ia < 0 ? ORDER.length : ia) - (ib < 0 ? ORDER.length : ib) || a.localeCompare(b);
  });
  const base = led?.markets?.[market] ?? (markets[0] ? led?.markets?.[markets[0]] : null);
  // Newest first in the picker; the record now runs back to 2021 rather than the last four.
  const quarters = (base?.quarters ?? []).map((q) => q.quarter).reverse();
  const current = base && quarter !== "all"
    ? { ...base, quarters: base.quarters.filter((q) => q.quarter === quarter) }
    : base;

  return (
    <div className="flex h-full flex-col bg-base-900 text-slate-200">
      <header className="flex flex-wrap items-center gap-3 border-b border-base-600 bg-base-900 px-5 py-3">
        <Link to="/" className="text-sm text-slate-400 hover:text-accent">← Dashboard</Link>
        <span className="text-lg font-bold text-slate-100">Quarterly History</span>
        <select
          value={quarter}
          onChange={(e) => setQuarter(e.target.value)}
          className="rounded border border-base-500 bg-base-700 px-2 py-1 text-xs text-slate-200"
          title="Show one rebalance, or the whole record"
        >
          <option value="all">All quarters ({quarters.length})</option>
          {quarters.map((q) => <option key={q} value={q}>{q}</option>)}
        </select>
        <div className="ml-auto flex flex-wrap gap-1.5">
          {markets.map((m) => (
            <button
              key={m}
              onClick={() => setMarket(m)}
              className={`rounded-full border px-3 py-1 text-xs font-semibold transition-colors ${
                market === m
                  ? "border-accent bg-accent/20 text-accent"
                  : "border-base-500 bg-base-700 text-slate-300 hover:bg-base-600"
              }`}
            >
              {led?.markets?.[m]?.label ?? m.toUpperCase()}
            </button>
          ))}
        </div>
      </header>

      <div className="mx-auto w-full max-w-6xl px-4 pt-3">
        {/* Stated plainly, because these numbers look like a track record and are not one. The
            live portfolio has rebalanced once; these four quarters are rebuilt from the score
            each company carried at each past quarter-end and our own stored closes. */}
        <div className="rounded-lg border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-[11px] text-slate-300">
          <b>Reconstructed, not traded.</b> Each quarter buys the top {current?.top_n ?? 20} by
          fundamental score and sells a name when it drops out. Prices are real closes from our
          own daily history, bought {current?.lag_months ?? 2} months after the quarter end,
          since results are not knowable the day a quarter closes. These are trades the rule
          <i> would</i> have made. The universe is today's listings, so companies that delisted
          are missing and their absence flatters the record. No costs, spread or slippage. The index is measured on the same trading days the rule bought and sold on, and compounded over the same quarters; markets with no index history show none rather than a substitute.
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto p-4">
        {loading ? (
          <div className="p-8 text-center text-sm text-slate-500">Loading…</div>
        ) : !current ? (
          <div className="p-8 text-center text-sm text-slate-500">
            The ledger builds on the next refresh.
          </div>
        ) : (
          <Market m={current} />
        )}
      </div>
    </div>
  );
}
