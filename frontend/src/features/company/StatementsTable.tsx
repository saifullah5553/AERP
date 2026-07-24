import { fmtCompact } from "@/lib/format";
import type { Row } from "@/types/company";

interface Field {
  key: string;
  label: string;
}

interface Props {
  rows: Row[]; // newest-first periods
  fields: Field[];
}

// Renders statement line items (rows) across reporting periods (columns).
export default function StatementsTable({ rows, fields }: Props) {
  if (rows.length === 0) {
    return (
      <div className="p-4 text-sm text-slate-500">
        No statements ingested yet for this security.
      </div>
    );
  }
  const periods = rows.map((r) => String(r.fiscal_date ?? "—"));

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-base-600 text-slate-400">
            <th className="px-3 py-2 text-left font-medium">Metric</th>
            {periods.map((p) => (
              <th key={p} className="px-3 py-2 text-right font-medium">
                {p}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {fields.map((f) => (
            <tr key={f.key} className="border-b border-base-700/50">
              <td className="px-3 py-1.5 text-slate-300">{f.label}</td>
              {rows.map((r, i) => {
                const v = r[f.key];
                return (
                  <td key={i} className="num px-3 py-1.5 text-right text-slate-200">
                    {typeof v === "number" ? fmtCompact(v) : "—"}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export const INCOME_FIELDS: Field[] = [
  { key: "revenue", label: "Revenue" },
  { key: "gross_profit", label: "Gross Profit" },
  { key: "operating_income", label: "Operating Income" },
  { key: "ebitda", label: "EBITDA" },
  { key: "net_income", label: "Net Income" },
  { key: "eps", label: "EPS" },
];

export const BALANCE_FIELDS: Field[] = [
  { key: "total_assets", label: "Total Assets" },
  { key: "current_assets", label: "Current Assets" },
  { key: "total_debt", label: "Total Debt" },
  { key: "total_liabilities", label: "Total Liabilities" },
  { key: "total_equity", label: "Total Equity" },
  { key: "cash_and_equivalents", label: "Cash" },
];

export const CASHFLOW_FIELDS: Field[] = [
  { key: "operating_cash_flow", label: "Operating CF" },
  { key: "capital_expenditure", label: "CapEx" },
  { key: "free_cash_flow", label: "Free Cash Flow" },
  { key: "dividends_paid", label: "Dividends Paid" },
  { key: "net_change_in_cash", label: "Net Change in Cash" },
];
