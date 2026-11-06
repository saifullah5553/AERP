/** One-time notice for the 6 Nov 2026 scoring change. Remove once the restated figures are old news. */
export function ScoringNote() {
  return (
    <div className="border-b border-base-600 bg-base-800 px-5 py-2 text-xs text-slate-300">
      <span className="font-semibold text-slate-100">6 Nov 2026, scoring method changed.</span>{" "}
      Every market had been scored on Pakistan's thresholds. Each company is now scored for its own
      country and industry, and past quarters were restated, so holdings and past returns differ
      from earlier versions. This is a change of method, not news about these companies.
    </div>
  );
}
