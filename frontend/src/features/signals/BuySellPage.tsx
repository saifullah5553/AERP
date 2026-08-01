import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";

import { api, type SignalMove } from "@/lib/api";

type Dir = "all" | "buy" | "sell";
type Range = "all" | "today" | "7d" | "30d";

const SIG_LABEL: Record<string, string> = {
  strong_buy: "Strong Buy", buy: "Buy", hold: "Hold", sell: "Sell", strong_sell: "Strong Sell",
};

// Buy zone = Strong Buy only. Entering it = BUY; leaving it = EXIT. Colour hints severity
// (amber for a drop to Buy/Hold, red for an outright Sell) but the label stays "EXIT" so it
// never contradicts the company page's model signal.
function moveBadge(m: SignalMove): { text: string; fg: string; bg: string } {
  if (m.direction === "buy")
    return { text: "▲ TIME TO BUY", fg: "#22c55e", bg: "rgba(34,197,94,0.14)" };
  const hard = m.to === "sell" || m.to === "strong_sell";
  return {
    text: "▼ EXIT STRONG BUY",
    fg: hard ? "#ef4444" : "#f59e0b",
    bg: hard ? "rgba(239,68,68,0.14)" : "rgba(245,158,11,0.14)",
  };
}

const RANGES: [Range, string][] = [
  ["all", "All dates"], ["today", "Today"], ["7d", "Last 7 days"], ["30d", "Last 30 days"],
];

function daysAgoISO(n: number): string {
  return new Date(Date.now() - n * 86400000).toISOString().slice(0, 10);
}

// Stocks that crossed a decision line: entered Strong Buy (time to buy) or left the buy zone
// entirely — Strong Buy/Buy → Hold/Sell (time to sell / trim). A one-notch Strong Buy→Buy
// dip is NOT a sell (still buy-rated), so it's excluded upstream.
export default function BuySellPage() {
  const [moves, setMoves] = useState<SignalMove[]>([]);
  const [dir, setDir] = useState<Dir>("all");
  const [region, setRegion] = useState("all");
  const [range, setRange] = useState<Range>("all");

  useEffect(() => {
    const ctrl = new AbortController();
    api
      .signalMoves(ctrl.signal)
      .then((d) => setMoves([...d.buy, ...d.sell].sort((a, b) => (a.date < b.date ? 1 : -1))))
      .catch(() => setMoves([]));
    return () => ctrl.abort();
  }, []);

  const regions = useMemo(
    () => ["all", ...[...new Set(moves.map((m) => m.region))].sort()],
    [moves],
  );

  const rows = useMemo(() => {
    const floor = range === "today" ? daysAgoISO(0) : range === "7d" ? daysAgoISO(7) : range === "30d" ? daysAgoISO(30) : null;
    return moves.filter(
      (m) =>
        (dir === "all" || m.direction === dir) &&
        (region === "all" || m.region === region) &&
        (floor === null || (m.date || "") >= floor),
    );
  }, [moves, dir, region, range]);

  const nBuy = rows.filter((m) => m.direction === "buy").length;
  const nExit = rows.filter((m) => m.direction === "sell").length;

  const chip = (active: boolean, tone: "buy" | "sell" | "accent") =>
    `rounded-full border px-2.5 py-0.5 text-xs font-semibold transition-colors ${
      active
        ? tone === "buy"
          ? "border-up bg-up/15 text-up"
          : tone === "sell"
            ? "border-down bg-down/15 text-down"
            : "border-accent bg-accent/20 text-accent"
        : "border-base-500 bg-base-700 text-slate-300 hover:bg-base-600"
    }`;

  return (
    <div className="flex h-full flex-col bg-base-900 text-slate-200">
      <header className="flex flex-wrap items-center gap-3 border-b border-base-600 bg-base-900 px-5 py-3">
        <Link to="/" className="text-sm text-slate-400 hover:text-accent">← Dashboard</Link>
        <span className="text-lg font-bold text-slate-100">Buy / Exit Signals</span>
        <span className="rounded-full bg-up/15 px-2 py-0.5 text-xs font-semibold text-up">{nBuy} buy</span>
        <span className="rounded-full bg-down/15 px-2 py-0.5 text-xs font-semibold text-down">{nExit} exit</span>

        <div className="ml-auto flex flex-wrap items-center gap-1.5">
          <button onClick={() => setDir("all")} className={chip(dir === "all", "accent")}>All</button>
          <button onClick={() => setDir("buy")} className={chip(dir === "buy", "buy")}>▲ Buy</button>
          <button onClick={() => setDir("sell")} className={chip(dir === "sell", "sell")}>▼ Exit</button>
          <span className="mx-1 h-4 w-px bg-base-600" />
          {regions.map((r) => (
            <button
              key={r}
              onClick={() => setRegion(r)}
              className={`rounded-full border px-2.5 py-0.5 text-xs font-medium uppercase ${
                region === r ? "border-accent bg-accent/20 text-accent" : "border-base-500 bg-base-700 text-slate-300 hover:bg-base-600"
              }`}
            >
              {r}
            </button>
          ))}
          <span className="mx-1 h-4 w-px bg-base-600" />
          <select
            value={range}
            onChange={(e) => setRange(e.target.value as Range)}
            className="rounded border border-base-500 bg-base-900 px-2 py-1 text-xs text-slate-200"
          >
            {RANGES.map(([v, label]) => (
              <option key={v} value={v}>{label}</option>
            ))}
          </select>
        </div>
      </header>

      <div className="mx-auto mt-3 max-w-4xl px-2">
        <div className="rounded-lg border border-accent/30 bg-accent/10 px-3 py-2 text-[11px] text-slate-300">
          <b>Strong Buy is the buy zone.</b> <span className="font-semibold text-up">▲ Buy</span> = the
          stock entered Strong Buy. <span className="ml-1 font-semibold text-down">▼ Exit</span> = it
          dropped out of Strong Buy (to Buy, Hold or lower). Rolling 30-day window. Research context
          only — not investment advice.
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto">
        {rows.length === 0 ? (
          <div className="p-8 text-center text-sm text-slate-500">No matching signals.</div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="sticky top-0 bg-base-800 text-[10px] uppercase tracking-wide text-slate-400">
                <tr className="border-b border-base-600">
                  <th className="px-3 py-2 text-left">Signal</th>
                  <th className="px-3 py-2 text-left">Ticker</th>
                  <th className="px-3 py-2 text-left">Name</th>
                  <th className="px-3 py-2 text-left">Transition</th>
                  <th className="px-3 py-2 text-right">Score</th>
                  <th className="px-3 py-2 text-left">Market</th>
                  <th className="px-3 py-2 text-right">Date</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((m, i) => {
                  const b = moveBadge(m);
                  return (
                    <tr key={i} className="border-b border-base-700/40 hover:bg-base-700/40">
                      <td className="px-3 py-1.5">
                        <span
                          className="rounded px-2 py-0.5 text-[11px] font-bold"
                          style={{ color: b.fg, background: b.bg }}
                        >
                          {b.text}
                        </span>
                      </td>
                      <td className="px-3 py-1.5">
                        <Link to={`/company/${encodeURIComponent(m.provider_symbol)}`} className="font-semibold text-accent">
                          {m.symbol}
                        </Link>
                      </td>
                      <td className="px-3 py-1.5 text-slate-300">
                        <span className="block max-w-[220px] truncate" title={m.name ?? ""}>{m.name ?? "—"}</span>
                      </td>
                      <td className="px-3 py-1.5 text-xs text-slate-400">
                        {SIG_LABEL[m.from] ?? m.from} → <span className="font-semibold text-slate-200">{SIG_LABEL[m.to] ?? m.to}</span>
                      </td>
                      <td className="num px-3 py-1.5 text-right text-slate-300">{m.composite == null ? "—" : m.composite.toFixed(1)}</td>
                      <td className="px-3 py-1.5 text-[11px] uppercase text-slate-500">{m.region}</td>
                      <td className="num px-3 py-1.5 text-right text-[11px] text-slate-500">{m.date}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
