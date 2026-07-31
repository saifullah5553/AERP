import { useEffect, useState } from "react";

import { api } from "@/lib/api";
import type { MarketPulse } from "@/types/api";

// Institutional-style KPI strip summarising the whole analysed universe, computed
// from the per-market pulse (which already carries counts + average composite).
export default function MarketOverview() {
  const [pulse, setPulse] = useState<MarketPulse[]>([]);

  useEffect(() => {
    const ctrl = new AbortController();
    api.pulse(ctrl.signal).then(setPulse).catch(() => setPulse([]));
    return () => ctrl.abort();
  }, []);

  if (pulse.length === 0) return null;

  const total = pulse.reduce((a, p) => a + p.count, 0);
  const bullish = pulse.reduce((a, p) => a + p.bullish, 0);
  const bearish = pulse.reduce((a, p) => a + p.bearish, 0);
  const neutral = pulse.reduce((a, p) => a + p.neutral, 0);
  const avg = total ? pulse.reduce((a, p) => a + p.avg_composite * p.count, 0) / total : 0;
  const pct = (n: number) => (total ? Math.round((n / total) * 100) : 0);
  const avgTone = avg >= 60 ? "#22c55e" : avg >= 45 ? "#eab308" : "#f87171";

  const kpis: { label: string; value: string; tone: string; icon: string }[] = [
    { label: "Companies Analysed", value: total.toLocaleString(), tone: "#38bdf8", icon: "▦" },
    { label: "Average AI Score", value: avg.toFixed(1), tone: avgTone, icon: "◈" },
    { label: "Bullish", value: `${pct(bullish)}%`, tone: "#22c55e", icon: "▲" },
    { label: "Neutral", value: `${pct(neutral)}%`, tone: "#94a3b8", icon: "＝" },
    { label: "Bearish", value: `${pct(bearish)}%`, tone: "#ef4444", icon: "▼" },
  ];

  return (
    <div className="border-b border-base-600 bg-base-900 px-3 py-2.5">
      <div className="flex flex-wrap items-stretch gap-2">
        {kpis.map((k) => (
          <div
            key={k.label}
            className="flex min-w-[132px] flex-1 items-center gap-3 rounded-lg border px-3 py-2 transition-transform hover:-translate-y-0.5"
            style={{
              borderColor: `${k.tone}44`,
              background: `linear-gradient(135deg, ${k.tone}1f 0%, rgba(15,23,42,0.4) 70%)`,
            }}
          >
            <span
              className="flex h-8 w-8 items-center justify-center rounded-md text-sm font-bold"
              style={{ background: `${k.tone}22`, color: k.tone }}
            >
              {k.icon}
            </span>
            <div className="flex flex-col">
              <span className="num text-xl font-black leading-none" style={{ color: k.tone }}>
                {k.value}
              </span>
              <span className="mt-1 text-[10px] uppercase tracking-wide text-slate-400">{k.label}</span>
            </div>
          </div>
        ))}

        {/* Sentiment bar + markets */}
        <div className="flex min-w-[240px] flex-[2] flex-col justify-center gap-1.5 rounded-lg border border-base-600 bg-base-800/60 px-3 py-2">
          <div className="flex items-center justify-between">
            <span className="text-[10px] uppercase tracking-wide text-slate-400">Sentiment</span>
            <span className="text-[10px] text-slate-500">{pulse.length} markets</span>
          </div>
          <div className="flex h-2.5 w-full overflow-hidden rounded-full bg-base-900">
            <span style={{ width: `${pct(bullish)}%`, background: "#22c55e" }} />
            <span style={{ width: `${pct(neutral)}%`, background: "#64748b" }} />
            <span style={{ width: `${pct(bearish)}%`, background: "#ef4444" }} />
          </div>
          <div className="truncate text-[11px] text-slate-400">
            {pulse.map((p) => p.label).join(" · ")}
          </div>
        </div>
      </div>
    </div>
  );
}
