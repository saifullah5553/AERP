#!/usr/bin/env bash
# Fold the scraped CSVs into the store, then carry the new quarter through to every published
# score. Run from the repo root, on the tree that is about to be published.

set -euo pipefail

cd backend
python -m app.cli consolidate-fundamentals
# Consolidating alone changes NOTHING a user can see. The score reads statements_ttm inside the
# company files, so freshly scraped results sat in the store while the dashboard kept showing last
# quarter. That is exactly what happened: FFC has carried Q2 2026 at the source for days and every
# PSX company still scored to Mar-26.
python -m app.cli apply-fundamentals --data-dir ../frontend/public/data
# Applying the statements is not the end of it. The fundamental score and the DCF fair value are
# both computed FROM statements_ttm, so without these two the new quarter lands in the company
# files and every published score still describes the old one. refresh-quality recomputes the
# score and the valuation; the history pass adds the new quarter to the per-quarter series the
# ledger ranks on.
python -m app.cli refresh-quality --out ../frontend/public/data || true
python -m app.cli refresh-quality-history --out ../frontend/public/data || true
