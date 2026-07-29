#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="osm_daily_way_references_i64"
BASE_URL="https://planet.openstreetmap.org/replication/day"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
DIFF_DIR="$DOWNLOAD_DIR/diffs"
STATE_DIR="$DOWNLOAD_DIR/states"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
PLAN="$DOWNLOAD_DIR/download_plan.tsv"
INVENTORY="$DOWNLOAD_DIR/download_inventory.tsv"
MAX_FILE_BYTES=500000000
MAX_TOTAL_BYTES=900000000

mkdir -p "$DIFF_DIR" "$STATE_DIR" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
echo "[$(date -Is)] download start dataset=$DATASET_ID"

export PLAN BASE_URL
python3 - <<'PY'
import os
from pathlib import Path

expected={
    5066: (92648123, '4e4330eda9c18a11d8648ba9497401e5b81102ad22f8aae06436094f914563c7'),
    5067: (98493917, '765b9dd66fc45ae9cfd6f5a27f230c2cc9c40706e79c7cddd5b4454e6f4667b5'),
    5068: (97949914, 'fbe8f275940c4a6eb9e51a7bd36faaa1f5e38a44d80427c45430b306b6b6dd2d'),
}
sequences=sorted(expected)
base=os.environ['BASE_URL']
with Path(os.environ['PLAN']).open('w',encoding='utf-8') as handle:
    handle.write('sequence\tpath\tdiff_url\tstate_url\texpected_bytes\texpected_sha256\n')
    for sequence in sequences:
        digits=f'{sequence:09d}'
        path=f'{digits[:3]}/{digits[3:6]}/{digits[6:]}'
        size, sha256=expected[sequence]
        handle.write(f'{sequence}\t{path}\t{base}/{path}.osc.gz\t{base}/{path}.state.txt\t{size}\t{sha256}\n')
print(f'pinned_sequences={sequences}')
PY

total_bytes=0
printf 'sequence\tdiff_url\tbytes\tsha256\tstate_timestamp\n' > "$INVENTORY"
tail -n +2 "$PLAN" | while IFS=$'\t' read -r sequence path diff_url state_url expected_bytes expected_sha256; do
  name="sequence_$(printf '%09d' "$sequence").osc.gz"
  diff="$DIFF_DIR/$name"
  state="$STATE_DIR/sequence_$(printf '%09d' "$sequence").state.txt"
  if [[ -s "$diff" ]] && gzip -t "$diff"; then
    echo "reuse existing $name"
  else
    rm -f "$diff" "$diff.part"
    curl --fail --location --retry 4 --retry-delay 3 \
      --user-agent "openzl-public-datasets/1.0" \
      --max-filesize "$MAX_FILE_BYTES" --output "$diff.part" "$diff_url"
    gzip -t "$diff.part"
    mv "$diff.part" "$diff"
  fi
  curl --fail --location --retry 4 --retry-delay 2 \
    --user-agent "openzl-public-datasets/1.0" --output "$state.part" "$state_url"
  mv "$state.part" "$state"
  grep -q "^sequenceNumber=$sequence" "$state" || { echo "state sequence mismatch for $sequence" >&2; exit 1; }
  bytes="$(wc -c < "$diff" | tr -d ' ')"
  [[ "$bytes" == "$expected_bytes" ]] || { echo "pinned size mismatch for $name" >&2; exit 1; }
  (( bytes <= MAX_FILE_BYTES )) || { echo "file cap exceeded for $name" >&2; exit 1; }
  total_bytes=$((total_bytes + bytes))
  (( total_bytes <= MAX_TOTAL_BYTES )) || { echo "total cap exceeded" >&2; exit 1; }
  sha256="$(sha256sum "$diff" | awk '{print $1}')"
  [[ "$sha256" == "$expected_sha256" ]] || { echo "pinned SHA-256 mismatch for $name" >&2; exit 1; }
  timestamp="$(sed -n 's/^timestamp=//p' "$state" | tr -d '\r')"
  printf '%s\t%s\t%s\t%s\t%s\n' "$sequence" "$diff_url" "$bytes" "$sha256" "$timestamp" >> "$INVENTORY"
done

mapfile -t DIFFS < <(find "$DIFF_DIR" -maxdepth 1 -type f -name 'sequence_*.osc.gz' | sort)
[[ "${#DIFFS[@]}" -eq 3 ]] || { echo "expected exactly 3 diff files, found ${#DIFFS[@]}" >&2; exit 1; }
python3 "$REPO_ROOT/datasets/$DATASET_ID/scripts/osm_way_refs.py" inspect "${DIFFS[@]}"
echo "[$(date -Is)] download done dataset=$DATASET_ID"
