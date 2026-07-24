import { Link } from "react-router-dom";

import { fmtNumber, fmtScore, scoreColor } from "@/lib/format";
import type { Peer } from "@/types/company";

export default function PeersTable({ peers }: { peers: Peer[] }) {
  if (peers.length === 0) {
    return (
      <div className="rounded border border-base-600 bg-base-800 p-4 text-sm text-slate-500">
        No sector peers available.
      </div>
    );
  }
  return (
    <div className="rounded border border-base-600 bg-base-800">
      <div className="border-b border-base-600 px-4 py-2 text-xs font-semibold uppercase tracking-wide text-slate-400">
        Sector Peers
      </div>
      <table className="w-full text-sm">
        <tbody>
          {peers.map((p) => (
            <tr key={p.provider_symbol} className="border-b border-base-700/40 hover:bg-base-700/40">
              <td className="px-4 py-2">
                <Link
                  to={`/company/${encodeURIComponent(p.provider_symbol)}`}
                  className="font-semibold text-accent hover:underline"
                >
                  {p.symbol}
                </Link>
                <div className="text-xs text-slate-500">{p.name}</div>
              </td>
              <td className="num px-4 py-2 text-right text-slate-300">{fmtNumber(p.price)}</td>
              <td className="num px-4 py-2 text-right font-semibold" style={{ color: scoreColor(p.composite_score) }}>
                {fmtScore(p.composite_score)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
