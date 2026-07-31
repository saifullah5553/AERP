import { useEffect, useState } from "react";

import { api } from "@/lib/api";
import type { CountryRegime, MacroRegimeData } from "@/types/api";

const REGIME_TONE: Record<CountryRegime["regime"], string> = {
  Bullish: "#22c55e",
  Bearish: "#ef4444",
  Neutral: "#94a3b8",
};

function healthTone(h: number | null): string {
  if (h == null) return "#64748b";
  return h >= 60 ? "#22c55e" : h >= 45 ? "#eab308" : "#f87171";
}

// A dynamic per-country Market Regime strip: index/rate/inflation/currency/commodity/
// breadth signals synthesised into a Market Health Score, recomputed each refresh so it
// shifts automatically when the macro backdrop changes. Research context — not a signal.
export default function MarketRegime() {
  const [data, setData] = useState<MacroRegimeData | null>(null);
  const [open, setOpen] = useState<string | null>(null);

  useEffect(() => {
    const ctrl = new AbortController();
    api.regime(ctrl.signal).then(setData).catch(() => setData(null));
    return () => ctrl.abort();
  }, []);

  const countries = data ? Object.values(data.countries) : [];
  if (countries.length === 0) return null;

  return (
    <div className="border-b border-base-600 bg-base-900 px-4 py-2.5">
      <div className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-slate-500">
        Market Regime — macro-driven, updates each refresh
      </div>
      <div className="flex flex-wrap gap-2">
        {countries.map((c) => {
          const tone = REGIME_TONE[c.regime];
          const hTone = healthTone(c.health);
          const isOpen = open === c.region;
          return (
            <div
              key={c.region}
              className="min-w-[190px] flex-1 overflow-hidden rounded-lg border transition-transform hover:-translate-y-0.5"
              style={{ borderColor: `${tone}44` }}
            >
              <button
                onClick={() => setOpen(isOpen ? null : c.region)}
                className="flex w-full items-center justify-between gap-3 px-3 py-2 text-left"
                style={{ background: `linear-gradient(135deg, ${tone}22 0%, rgb(var(--base-900) / 0.5) 75%)` }}
              >
                <div>
                  <div className="text-xs font-semibold text-slate-100">{c.label}</div>
                  <span
                    className="mt-0.5 inline-block rounded-full px-2 py-0.5 text-[10px] font-bold"
                    style={{ background: `${tone}26`, color: tone }}
                  >
                    {c.regime}
                  </span>
                </div>
                <div className="flex flex-col items-center">
                  <span
                    className="num flex h-10 w-10 items-center justify-center rounded-full text-base font-black"
                    style={{ background: `${hTone}1f`, color: hTone, border: `2px solid ${hTone}66` }}
                  >
                    {c.health == null ? "—" : Math.round(c.health)}
                  </span>
                  <span className="mt-0.5 text-[9px] uppercase tracking-wide text-slate-500">Health</span>
                </div>
              </button>
              <div className="h-1 w-full bg-base-900">
                <span className="block h-full" style={{ width: `${c.health ?? 0}%`, background: hTone }} />
              </div>
              {isOpen && (
                <div className="border-t border-base-700/60 px-3 py-2">
                  <p className="mb-2 text-[11px] leading-relaxed text-slate-400">{c.explanation}</p>
                  <div className="space-y-1">
                    {c.signals.map((s) => (
                      <div key={s.key} className="flex items-center justify-between text-[11px]">
                        <span className="text-slate-400" title={s.note}>{s.label}</span>
                        <span className="flex items-center gap-2">
                          <span className="text-slate-300">{s.value}</span>
                          <span
                            className="h-1.5 w-10 overflow-hidden rounded bg-base-700"
                            title={s.score == null ? "" : `${Math.round(s.score)}/100`}
                          >
                            <span
                              className="block h-full"
                              style={{ width: `${s.score ?? 0}%`, background: healthTone(s.score) }}
                            />
                          </span>
                        </span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
