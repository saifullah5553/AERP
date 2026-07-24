// Display formatters. All tolerate null/undefined and return an em-dash so the
// grid never shows a fabricated value where data is genuinely absent.

const DASH = "—";

export function fmtNumber(v: number | null | undefined, digits = 2): string {
  if (v === null || v === undefined || Number.isNaN(v)) return DASH;
  return v.toLocaleString(undefined, {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

export function fmtInt(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return DASH;
  return Math.round(v).toLocaleString();
}

export function fmtPercent(v: number | null | undefined, digits = 2): string {
  if (v === null || v === undefined || Number.isNaN(v)) return DASH;
  return `${(v * 100).toFixed(digits)}%`;
}

// change_pct arrives already in percent units (e.g. 2.04 == +2.04%).
export function fmtChangePct(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return DASH;
  const sign = v > 0 ? "+" : "";
  return `${sign}${v.toFixed(2)}%`;
}

export function fmtCompact(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return DASH;
  const abs = Math.abs(v);
  const units: [number, string][] = [
    [1e12, "T"],
    [1e9, "B"],
    [1e6, "M"],
    [1e3, "K"],
  ];
  for (const [n, suffix] of units) {
    if (abs >= n) return `${(v / n).toFixed(2)}${suffix}`;
  }
  return v.toFixed(0);
}

export function fmtScore(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return DASH;
  return v.toFixed(0);
}

export function titleize(v: string | null | undefined): string {
  if (!v) return DASH;
  return v.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

// Green→amber→red gradient for a 0..100 score.
export function scoreColor(v: number | null | undefined): string {
  if (v === null || v === undefined) return "transparent";
  const hue = Math.max(0, Math.min(120, (v / 100) * 120)); // 0=red, 120=green
  return `hsl(${hue}, 65%, 45%)`;
}
