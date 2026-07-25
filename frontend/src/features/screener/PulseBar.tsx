import { useEffect, useState } from "react";

import { api } from "@/lib/api";
import type { MarketPulse } from "@/types/api";

const TONE: Record<MarketPulse["pulse"], { dot: string; text: string; label: string }> = {
  bullish: { dot: "bg-emerald-400", text: "text-emerald-400", label: "Bullish" },
  bearish: { dot: "bg-rose-400", text: "text-rose-400", label: "Bearish" },
  neutral: { dot: "bg-slate-400", text: "text-slate-400", label: "Neutral" },
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
            className="flex items-center gap-1.5 rounded border border-base-600 bg-base-800 px-2.5 py-1"
          >
            <span className={`h-2 w-2 rounded-full ${tone.dot}`} />
            <span className="text-xs font-medium text-slate-200">{m.label}</span>
            <span className={`text-xs font-semibold ${tone.text}`}>{tone.label}</span>
            <span className="text-[11px] text-slate-500">{m.avg_composite}</span>
          </div>
        );
      })}
    </div>
  );
}
