#!/usr/bin/env bash
# Build from the current tip and push the result. If another job pushes first, build again.
#
# Usage:  scripts/publish_on_tip.sh "<commit message>" "<build command>" <path>...
#
# For a job whose output is DERIVED from files other jobs also write. commit_snapshot.sh is right
# for a job that owns its output outright, because it lays the run's files back over the tip. It
# is wrong here. The Fundamentals job checked out the store at 12:11 and pushed at 15:48, and in
# between India's September results had landed on main. Its replay put the old store back, and
# 1,173 company pages with it, and wiped five technical reads the Daily could not recompute. The
# run reported success, and the screener still said September while Reliance's page said June.
#
# Anything a job fetches outside the repo (the scraped CSVs here) must be in an ignored path, so
# that it survives the reset. The build then folds it into whatever the tip holds by now.

set -euo pipefail

MESSAGE="${1:?commit message required}"
BUILD="${2:?build command required}"
shift 2
[ "$#" -gt 0 ] || { echo "at least one path to publish is required" >&2; exit 2; }

for attempt in 1 2 3; do
  git fetch --depth=1 origin main
  git reset --hard FETCH_HEAD
  echo "Building on $(git rev-parse --short HEAD) (attempt $attempt)."

  bash -c "$BUILD"

  git add -- "$@"
  if git diff --cached --quiet; then
    echo "Nothing changed - nothing to publish."
    exit 0
  fi
  git commit -m "$MESSAGE"

  if git push origin HEAD:main; then
    echo "Pushed on attempt $attempt."
    exit 0
  fi
  echo "The tip moved during the build. Starting again from the new tip."
done

echo "::error::the tip kept moving through 3 builds - this run's output was not published"
exit 1
