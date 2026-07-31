import { useEffect, useState } from "react";

import { api } from "@/lib/api";
import type { MarketPulse } from "@/types/api";

const TONE: Record<MarketPulse["pulse"], { color: string; label: string; arrow: string }> = {
  bullish: { color: "#22c55e", label: "Bullish", arrow: "▲" },
  bearish: { color: "#ef4444", label: "Bearish", arrow: "▼" },
  neutral: { color: "#94a3b8", label: "Neutral", arrow: "＝" },
};

// A compact strip of per-market sentiment (bullish/bearish/neutral) derived from
// the average composite score of each market's securities.
export default function PulseBar() {
  const [pulse, setPulse] = useState<MarketPulse[]>([]);

  useEffect(() => {
    const ctrl = new AbortController();
    api.pulse(ctrl.signal).then(setPulse).catch(() => setPulse([]));
    return () => ctrl.abort();
  }, []);

  if (pulse.length === 0) return null;

  return (
    <div className="flex flex-wrap items-center gap-2 border-b border-base-600 bg-base-900 px-4 py-2">
      <span className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">
        Market Pulse
      </span>
      {pulse.map((m) => {
        const tone = TONE[m.pulse];
        return (
          <div
            key={m.region}
            title={`${m.count} names · avg composite ${m.avg_composite} · ${m.bullish}▲ / ${m.bearish}▼`}
            className="flex items-center gap-1.5 rounded-full border px-2.5 py-1 transition-transform hover:-translate-y-0.5"
            style={{ borderColor: `${tone.color}55`, background: `${tone.color}18` }}
          >
            <span className="text-xs font-bold" style={{ color: tone.color }}>{tone.arrow}</span>
            <span className="text-xs font-semibold text-slate-100">{m.label}</span>
            <span className="text-xs font-semibold" style={{ color: tone.color }}>{tone.label}</span>
            <span
              className="num rounded px-1 text-[10px] font-bold"
              style={{ background: `${tone.color}22`, color: tone.color }}
            >
              {m.avg_composite}
            </span>
          </div>
        );
      })}
    </div>
  );
}
