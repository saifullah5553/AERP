#!/usr/bin/env bash
# Lay this run's PSX scrape over the CSV archive on the current tip, and pack it again.
#
# Usage:  scripts/psx_pack_scrape.sh <folder of scraped CSVs>
#
# The archive is unpacked here, on the tree about to be published, and not at the start of the
# job. The scrape takes over an hour, and a folder unpacked before it would put back whatever the
# archive gained in the meantime. Run it as part of a publish_on_tip.sh build: a retry unpacks the
# newer archive and lays the same scrape over it.
#
# A missing or unreadable archive stops the build. Packing the scrape alone would replace 1,800
# CSVs with a few dozen.

set -euo pipefail

SCRAPED="${1:?folder of scraped CSVs required}"
ARCHIVE=data/psx_csv.tar.gz

shopt -s nullglob
csvs=("$SCRAPED"/*.csv)
if [ "${#csvs[@]}" -eq 0 ]; then
  echo "No CSVs in $SCRAPED - the archive stays as it is."
  exit 0
fi

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

tar xzf "$ARCHIVE" -C "$work"
cp "${csvs[@]}" "$work/psx_csv/"

# The same CSVs must give the same bytes. A plain `tar czf` stamps the time into the file, so a run
# that re-fetched identical numbers would still commit a new archive, in a repo already at 19.7 GB.
tar --sort=name --mtime='2020-01-01 00:00:00Z' --owner=0 --group=0 --numeric-owner \
  -cf - -C "$work" psx_csv | gzip -n > "$work/packed.tar.gz"
mv "$work/packed.tar.gz" "$ARCHIVE"
echo "Packed ${#csvs[@]} scraped CSV(s) into $ARCHIVE."
