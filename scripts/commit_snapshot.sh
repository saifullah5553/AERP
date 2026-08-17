#!/usr/bin/env bash
# Commit what the caller has already staged, and push it even if another job wins the race.
#
# Usage:  git add <whatever this job produced>
#         scripts/commit_snapshot.sh "<commit message>"
#
# Why this exists, in the order the failures actually happened:
#
#   1. `git push || echo "push skipped"` - the original. A job that lost the race discarded
#      its entire output and exited 0. A whole day of technicals, computed and thrown away,
#      reported as success.
#   2. `git pull --rebase` - replaying a commit that rewrites thousands of generated JSON
#      files onto another job's copy of the same files conflicts on every one of them.
#   3. `git merge -X ours` - right intent, and it did work for the daily refresh. But it
#      depends on finding a merge base, and `actions/checkout` clones at depth 1, so whether
#      it works at all turns on how much history a given fetch happens to bring back. A push
#      path that works or not depending on that is not one to build on.
#
# So this uses no merge, no rebase and no history at all. It takes the current remote tip and
# lays this run's files back on top. These are GENERATED artefacts - the job that just
# recomputed them holds the newer answer - so file-level "ours wins" is the correct resolution
# and needs no common ancestor to justify it.
#
# It replays exactly the files in THIS run's commit, rather than a directory list, for two
# reasons: a file the remote added while we were working is left alone instead of being
# clobbered, and a caller that deliberately stages only part of a directory (refresh-data
# throttles the two largest JSON files to every six hours) keeps that decision on the retry.

set -euo pipefail

MESSAGE="${1:?commit message required}"

if git diff --cached --quiet; then
  echo "No changes to commit."
  exit 0
fi
git commit -m "$MESSAGE"

# The exact paths this commit touched, NUL-separated so spaces in filenames survive.
mapfile -d '' CHANGED < <(git diff --name-only -z HEAD^ HEAD)
echo "Commit touches ${#CHANGED[@]} file(s)."

for attempt in 1 2 3 4 5; do
  if git push; then
    echo "Pushed on attempt $attempt."
    exit 0
  fi
  echo "Push rejected (attempt $attempt) - replaying this run's files onto the current origin/main."

  staging="$(mktemp -d)"
  for f in "${CHANGED[@]}"; do
    [ -e "$f" ] || continue          # deleted by this run; handled after the reset
    mkdir -p "$staging/$(dirname "$f")"
    cp -a "$f" "$staging/$f"
  done

  git fetch --depth=1 origin main
  git reset --hard FETCH_HEAD

  for f in "${CHANGED[@]}"; do
    if [ -e "$staging/$f" ]; then
      mkdir -p "$(dirname "$f")"
      cp -a "$staging/$f" "$f"
    else
      rm -f "$f"                     # this run deleted it; keep it deleted
    fi
  done
  rm -rf "$staging"

  git add -A -- "${CHANGED[@]}"
  if git diff --cached --quiet; then
    echo "Nothing left to commit - origin already carries this run's output."
    exit 0
  fi
  git commit -m "$MESSAGE"
  mapfile -d '' CHANGED < <(git diff --name-only -z HEAD^ HEAD)
  sleep $((attempt * 5))
done

echo "::error::could not push after 5 attempts - this run's work was computed and then lost"
exit 1
