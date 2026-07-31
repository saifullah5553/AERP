import { useEffect, useState } from "react";

import { api } from "@/lib/api";
import type { MarketPulse, MarketRegion } from "@/types/api";

type Sentiment = "bullish" | "bearish";

// KPI strip: two headline tiles + a clickable per-market breadth panel. Clicking a
// market's bullish/bearish count filters the screener to those names.
export default function MarketOverview({
  onSelect,
}: {
  onSelect?: (region: MarketRegion, sentiment: Sentiment) => void;
}) {
  const [pulse, setPulse] = useState<MarketPulse[]>([]);

  useEffect(() => {
    const ctrl = new AbortController();
    api.pulse(ctrl.signal).then(setPulse).catch(() => setPulse([]));
    return () => ctrl.abort();
  }, []);

  if (pulse.length === 0) return null;

  const total = pulse.reduce((a, p) => a + p.count, 0);
  const avg = total ? pulse.reduce((a, p) => a + p.avg_composite * p.count, 0) / total : 0;
  const avgTone = avg >= 60 ? "#22c55e" : avg >= 45 ? "#eab308" : "#f87171";

  const kpi = (label: string, value: string, tone: string, icon: string) => (
    <div
      className="flex min-w-[132px] items-center gap-3 rounded-lg border px-3 py-2.5 shadow-lg"
      style={{
        borderColor: `${tone}55`,
        borderTop: `3px solid ${tone}`,
        background: `linear-gradient(135deg, ${tone}3a 0%, ${tone}12 45%, rgb(var(--base-900) / 0.55) 100%)`,
      }}
    >
      <span
        className="flex h-9 w-9 items-center justify-center rounded-lg text-base font-bold"
        style={{ background: `${tone}33`, color: tone, boxShadow: `0 0 12px ${tone}44` }}
      >
        {icon}
      </span>
      <div className="flex flex-col">
        <span className="num text-2xl font-black leading-none" style={{ color: tone }}>{value}</span>
        <span className="mt-1 text-[10px] uppercase tracking-wide text-slate-300">{label}</span>
      </div>
    </div>
  );

  return (
    <div className="border-b border-base-600 bg-base-900 px-3 py-2.5">
      <div className="flex flex-wrap items-stretch gap-2">
        {kpi("Companies Analysed", total.toLocaleString(), "#38bdf8", "▦")}
        {kpi("Average AI Score", avg.toFixed(1), avgTone, "◈")}

        {/* Per-market breadth — click a count to filter the screener */}
        {pulse.map((p) => (
          <div
            key={p.region}
            className="flex min-w-[150px] flex-1 flex-col justify-center rounded-lg border border-base-600 bg-base-800/60 px-3 py-2"
          >
            <span className="mb-1 text-[11px] font-semibold text-slate-200">{p.label}</span>
            <div className="flex items-center gap-2">
              <button
                onClick={() => onSelect?.(p.region, "bullish")}
                title={`Show ${p.bullish} bullish ${p.label} names`}
                className="flex flex-1 items-center justify-center gap-1 rounded border border-emerald-500/40 bg-emerald-500/10 px-2 py-1 text-xs font-bold text-emerald-400 transition-colors hover:bg-emerald-500/25"
              >
                ▲ {p.bullish}
              </button>
              <button
                onClick={() => onSelect?.(p.region, "bearish")}
                title={`Show ${p.bearish} bearish ${p.label} names`}
                className="flex flex-1 items-center justify-center gap-1 rounded border border-rose-500/40 bg-rose-500/10 px-2 py-1 text-xs font-bold text-rose-400 transition-colors hover:bg-rose-500/25"
              >
                ▼ {p.bearish}
              </button>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
