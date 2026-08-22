import { useMemo, useState } from "react";

/**
 * Click-to-sort for the plain tables. One implementation, used by every page.
 *
 * The screener runs on ag-grid and has always been sortable; every other table was fixed in
 * whatever order its builder happened to emit - sector rotation by score, movers by delta,
 * the portfolio by market - so a question as ordinary as "which holding is down the most"
 * could not be asked at all.
 *
 * Nulls always sort LAST regardless of direction. A missing value is not a small value, and
 * letting blanks win the top of an ascending sort buries the rows the sort was for.
 */

export type SortDir = "asc" | "desc";

export interface SortState {
  key: string | null;
  dir: SortDir;
}

export function useSortable<T>(
  rows: T[],
  getValue: (row: T, key: string) => unknown,
  initial?: SortState,
) {
  const [sort, setSort] = useState<SortState>(initial ?? { key: null, dir: "desc" });

  const sorted = useMemo(() => {
    if (!sort.key) return rows;
    const key = sort.key;
    const factor = sort.dir === "asc" ? 1 : -1;
    // Copy first: sorting the prop array in place mutates the caller's state and React will
    // not re-render reliably off a mutation it did not see.
    return [...rows].sort((a, b) => {
      const av = getValue(a, key);
      const bv = getValue(b, key);
      const aEmpty = av === null || av === undefined || av === "";
      const bEmpty = bv === null || bv === undefined || bv === "";
      if (aEmpty && bEmpty) return 0;
      if (aEmpty) return 1;
      if (bEmpty) return -1;
      if (typeof av === "number" && typeof bv === "number") return (av - bv) * factor;
      return String(av).localeCompare(String(bv), undefined, { numeric: true }) * factor;
    });
  }, [rows, sort, getValue]);

  /** Click a header: first click sorts descending, clicking the same one flips it. */
  const toggle = (key: string) =>
    setSort((prev) =>
      prev.key === key
        ? { key, dir: prev.dir === "desc" ? "asc" : "desc" }
        : { key, dir: "desc" },
    );

  return { sorted, sort, toggle };
}

/** A clickable header cell. `sortKey` is what gets handed back to `getValue`. */
export function Th({
  sortKey,
  sort,
  onSort,
  children,
  className = "",
  align = "left",
}: {
  sortKey: string;
  sort: SortState;
  onSort: (key: string) => void;
  children: React.ReactNode;
  className?: string;
  align?: "left" | "right";
}) {
  const active = sort.key === sortKey;
  return (
    <th
      className={`${className} cursor-pointer select-none hover:text-slate-300 ${
        active ? "text-slate-200" : ""
      }`}
      onClick={() => onSort(sortKey)}
      // Keyboard-reachable: a header that only responds to a mouse is not a control.
      tabIndex={0}
      role="columnheader"
      aria-sort={active ? (sort.dir === "asc" ? "ascending" : "descending") : "none"}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          onSort(sortKey);
        }
      }}
      title="Click to sort"
    >
      <span className={`inline-flex items-center gap-1 ${align === "right" ? "flex-row-reverse" : ""}`}>
        {children}
        <span className={`text-[9px] ${active ? "opacity-100" : "opacity-25"}`}>
          {active ? (sort.dir === "asc" ? "▲" : "▼") : "▾"}
        </span>
      </span>
    </th>
  );
}
