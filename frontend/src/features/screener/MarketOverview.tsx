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

  const kpis: { label: string; value: string; tone?: string }[] = [
    { label: "Companies Analysed", value: total.toLocaleString() },
    { label: "Average AI Score", value: avg.toFixed(1) },
    { label: "Bullish", value: `${pct(bullish)}%`, tone: "#22c55e" },
    { label: "Neutral", value: `${pct(neutral)}%`, tone: "#94a3b8" },
    { label: "Bearish", value: `${pct(bearish)}%`, tone: "#ef4444" },
  ];

  return (
    <div className="flex flex-wrap items-stretch gap-px border-b border-base-600 bg-base-600">
      {kpis.map((k) => (
        <div key={k.label} className="flex min-w-[130px] flex-1 flex-col bg-base-900 px-4 py-2">
          <span className="num text-lg font-bold" style={{ color: k.tone ?? "#e2e8f0" }}>{k.value}</span>
          <span className="text-[10px] uppercase tracking-wide text-slate-500">{k.label}</span>
        </div>
      ))}
      <div className="flex min-w-[200px] flex-[2] flex-col justify-center bg-base-900 px-4 py-2">
        <span className="text-[10px] uppercase tracking-wide text-slate-500">Markets Covered</span>
        <span className="text-sm font-medium text-slate-200">
          {pulse.map((p) => p.label).join(" · ")}
        </span>
      </div>
    </div>
  );
}
