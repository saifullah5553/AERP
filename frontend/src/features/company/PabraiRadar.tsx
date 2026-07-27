// Pabrai checklist radar — pure inline SVG (no chart lib). Plots each checklist
// dimension's 0..1 score on its own axis so business-quality shape is visible at a glance.

interface RadarItem {
  name: string;
  score: number | null; // 0..1
  available: boolean;
}

// Short axis labels (kept ≤ ~11 chars so they don't collide around the ring).
const ABBR: Record<string, string> = {
  "Understandable Business": "Understand",
  "Durable Competitive Advantage": "Moat",
  "High Return on Capital": "ROIC",
  "Conservative Balance Sheet": "Balance",
  "Consistent Earnings Growth": "Growth",
  "Strong Free Cash Flow": "FCF",
  "Honest Capital Allocation": "Capital Alloc",
  "Stable Margins": "Margins",
  "High Owner Earnings": "Owner Earn",
  "Predictable Business": "Predictable",
  "Conservative Accounting": "Accounting",
  "Attractive Valuation": "Valuation",
  "Management Quality": "Mgmt",
};

function tone(s: number): string {
  return s >= 0.7 ? "#22c55e" : s >= 0.45 ? "#eab308" : "#f87171";
}

export default function PabraiRadar({ items }: { items: RadarItem[] }) {
  const pts = items.filter((it) => it.name in ABBR || it.name.length > 0);
  const n = pts.length;
  if (n < 3) return null;

  const size = 260;
  const cx = size / 2;
  const cy = size / 2;
  const R = 92;
  const rings = [0.25, 0.5, 0.75, 1];

  const angle = (i: number) => (-90 + (i * 360) / n) * (Math.PI / 180);
  const at = (i: number, r: number): [number, number] => [
    cx + Math.cos(angle(i)) * R * r,
    cy + Math.sin(angle(i)) * R * r,
  ];

  const ringPath = (r: number) =>
    pts.map((_, i) => at(i, r).join(",")).join(" ");

  // Data polygon — unavailable dims collapse to centre (score 0).
  const dataPoly = pts
    .map((it, i) => at(i, it.available && it.score != null ? Math.max(0, Math.min(1, it.score)) : 0).join(","))
    .join(" ");

  const avg =
    pts.reduce((a, it) => a + (it.available && it.score != null ? it.score : 0), 0) / n;
  const fill = tone(avg);

  return (
    <div className="flex justify-center px-4 py-3">
      <svg viewBox={`0 0 ${size} ${size}`} width={size} height={size} role="img" aria-label="Pabrai checklist radar">
        {/* grid rings */}
        {rings.map((r) => (
          <polygon key={r} points={ringPath(r)} fill="none" stroke="#334155" strokeWidth={r === 1 ? 1 : 0.5} />
        ))}
        {/* axes + labels */}
        {pts.map((it, i) => {
          const [x, y] = at(i, 1);
          const [lx, ly] = at(i, 1.18);
          const anchor = lx > cx + 4 ? "start" : lx < cx - 4 ? "end" : "middle";
          return (
            <g key={it.name}>
              <line x1={cx} y1={cy} x2={x} y2={y} stroke="#334155" strokeWidth={0.5} />
              <text
                x={lx}
                y={ly}
                fontSize={8}
                fill={it.available ? "#94a3b8" : "#64748b"}
                textAnchor={anchor}
                dominantBaseline="middle"
              >
                {ABBR[it.name] ?? it.name.slice(0, 11)}
              </text>
            </g>
          );
        })}
        {/* data polygon */}
        <polygon points={dataPoly} fill={`${fill}33`} stroke={fill} strokeWidth={1.5} strokeLinejoin="round" />
        {pts.map((it, i) => {
          const s = it.available && it.score != null ? Math.max(0, Math.min(1, it.score)) : 0;
          const [x, y] = at(i, s);
          return <circle key={it.name} cx={x} cy={y} r={1.8} fill={it.available ? tone(it.score ?? 0) : "#475569"} />;
        })}
      </svg>
    </div>
  );
}
