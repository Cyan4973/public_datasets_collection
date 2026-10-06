#!/usr/bin/env bash
# Metadata-only discovery used to pin sources.tsv (not part of the acceptance
# path). Fetches the CKAN package, the last 64 KiB of each exemplary ZIP and the
# first 64 KiB of every SHMTS member, then decodes each member's Dat struct
# header (Fs, dims, channel names/units, start time) with probe.py.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="luh_lumo_tower_acceleration_f32"
OUT="$DATA_ROOT/discovery/$DATASET_ID"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
BASE_URL="https://data.uni-hannover.de/dataset/93b52576-6a5a-4ce9-8c27-a0372590f7b0/resource"
UA="openzl-public-datasets-lumo/1.0"
mkdir -p "$OUT/heads" "$LOG_DIR"
exec > >(tee "$LOG_DIR/discover.latest.log") 2>&1

curl -fsSL --max-time 120 -A "$UA" -o "$OUT/package_show.json" \
  "https://data.uni-hannover.de/api/3/action/package_show?id=lumo"
python3 - "$OUT/package_show.json" > "$OUT/zips.tsv" <<'PY'
import json, sys
r = json.load(open(sys.argv[1]))["result"]
print(f"# license_id={r['license_id']} isopen={r['isopen']} doi={r.get('doi')}", file=sys.stderr)
for res in r["resources"]:
    if res.get("format") == "ZIP" and "exemplary" in res["url"]:
        name = res["url"].rsplit("/", 1)[1]
        tag = name.replace("exemplary_datasets_", "").replace(".zip", "")
        print(f"{tag}\t{res['id']}\t{name}\t{res['size']}")
PY
: > "$OUT/headers.jsonl"
while IFS=$'\t' read -r tag rid name size; do
  url="$BASE_URL/$rid/download/$name"
  curl -fsSL --max-time 120 -A "$UA" -r "$((size - 65536))-$((size - 1))" -o "$OUT/$tag.tail" "$url"
  python3 "$RECIPE_DIR/probe.py" zipdir "$OUT/$tag.tail" "$size" > "$OUT/$tag.zipdir.json"
  python3 -c "import json,sys; [print(e['name'], e['lho']) for e in json.load(open(sys.argv[1])) if e['name'].endswith('.mat')]" \
    "$OUT/$tag.zipdir.json" | while read -r member lho; do
      head_file="$OUT/heads/${tag}__${member//\//_}.head"
      curl -fsSL --max-time 120 -A "$UA" -r "$lho-$((lho + 65535))" -o "$head_file" "$url"
      python3 "$RECIPE_DIR/probe.py" header "$head_file" >> "$OUT/headers.jsonl"
    done
done < "$OUT/zips.tsv"
echo "discovery written to $OUT ($(wc -l < "$OUT/headers.jsonl") member headers)"
