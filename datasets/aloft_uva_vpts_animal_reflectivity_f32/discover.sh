#!/usr/bin/env bash
# Metadata-only discovery that documents how this recipe's pins were resolved.
# Prints the UVA_VPTS Zenodo record identity, license, file sizes/checksums and
# the German radar-month population from coverage.csv. Downloads only the
# record JSON and coverage.csv (< 1 MB) into a temporary directory.
set -euo pipefail

RECORD_ID=14711244
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
curl --fail --silent --show-error --location --max-time 120 --retry 20 --retry-delay 30 --retry-all-errors \
  --output "$TMP/record.json" "https://zenodo.org/api/records/$RECORD_ID"
curl --fail --silent --show-error --location --max-time 300 --retry 20 --retry-delay 30 --retry-all-errors \
  --output "$TMP/coverage.csv" "https://zenodo.org/api/records/$RECORD_ID/files/coverage.csv/content"

python3 - "$TMP/record.json" "$TMP/coverage.csv" <<'PY'
import collections
import csv
import json
import sys

record = json.load(open(sys.argv[1], encoding="utf-8"))
meta = record["metadata"]
print(f"record={record['id']} doi={record.get('doi')} concept_doi={record.get('conceptdoi')}")
print(f"title={meta['title']!r}")
print(f"publication_date={meta.get('publication_date')} license={meta.get('license')}")
for item in record["files"]:
    print(f"file {item['key']:<28} size={item['size']:>12} checksum={item['checksum']}")
months = collections.defaultdict(lambda: [0, set()])
with open(sys.argv[2], encoding="utf-8-sig", newline="") as handle:
    for row in csv.DictReader(handle):
        if row["country"] != "de":
            continue
        entry = months[(row["radar"], row["date"][:7])]
        entry[0] += int(row["records"])
        entry[1].add(row["unique_heights"])
records = sum(value[0] for value in months.values())
radars = sorted({key[0] for key in months})
print(f"german_radar_months={len(months)} records={records} radars={len(radars)} {radars}")
print(f"unique_heights={sorted(set().union(*(value[1] for value in months.values())))}")
print(f"month_range={min(k[1] for k in months)}..{max(k[1] for k in months)}")
counts = sorted(value[0] for value in months.values())
print(f"records_per_month min={counts[0]} median={counts[len(counts) // 2]} max={counts[-1]}")
PY
