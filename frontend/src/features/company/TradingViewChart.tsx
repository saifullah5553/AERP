import { useEffect, useRef } from "react";

interface Props {
  symbol: string | null;
  height?: number;
}

// Embeds TradingView's free "Advanced Chart" widget. When no TradingView symbol
// is available for the market (e.g. PSX), we show an honest placeholder instead
// of a misleading chart.
export default function TradingViewChart({ symbol, height = 480 }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const container = containerRef.current;
    if (!symbol || !container) return;
    container.innerHTML = "";

    const script = document.createElement("script");
    script.src =
      "https://s3.tradingview.com/external-embedding/embed-widget-advanced-chart.js";
    script.type = "text/javascript";
    script.async = true;
    script.innerHTML = JSON.stringify({
      autosize: true,
      symbol,
      interval: "D",
      timezone: "Etc/UTC",
      theme: "dark",
      style: "1",
      locale: "en",
      enable_publishing: false,
      allow_symbol_change: false,
      hide_side_toolbar: false,
      support_host: "https://www.tradingview.com",
    });
    container.appendChild(script);

    return () => {
      container.innerHTML = "";
    };
  }, [symbol]);

  if (!symbol) {
    return (
      <div
        className="flex items-center justify-center rounded border border-base-600 bg-base-800 text-sm text-slate-500"
        style={{ height }}
      >
        No TradingView chart available for this market.
      </div>
    );
  }

  return (
    <div
      className="tradingview-widget-container overflow-hidden rounded border border-base-600"
      ref={containerRef}
      style={{ height }}
    />
  );
}
