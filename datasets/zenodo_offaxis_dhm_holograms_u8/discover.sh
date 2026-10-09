#!/usr/bin/env bash
# Discovery (metadata only, ~2 MB of range requests): resolve the 17 pinned
# 405 nm DHM videos of Zenodo record 10632465, read each zip's central
# directory from its tail, and derive the evenly spaced frame selection.
# Output: $DATA_DIR/discovery/<id>/{videos.tsv,selected_frames.tsv,members/*.tsv}
# The committed videos.tsv and selected_frames.tsv in this recipe were
# produced by this script on 2026-10-08.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="zenodo_offaxis_dhm_holograms_u8"
OUT_DIR="$DATA_ROOT/discovery/$DATASET_ID"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
FRAMES_PER_VIDEO="${FRAMES_PER_VIDEO:-6}"
API_URL="https://zenodo.org/api/records/10632465"
UA="openzl-public-datasets-dhm-holograms/1.0"
PY="python3 -I $RECIPE_DIR/scripts/dhm_zip.py"

mkdir -p "$OUT_DIR/members" "$OUT_DIR/tails" "$LOG_DIR"
exec > >(tee "$LOG_DIR/discover.latest.log") 2>&1
echo "[$(date -Is)] discover start"

curl -fsS -L --retry 5 --retry-delay 3 --max-time 120 -A "$UA" -o "$OUT_DIR/record.json" "$API_URL"

# All zips except the 520 nm gold video (README: 405 nm unless specified 520 nm).
python3 -I - "$OUT_DIR/record.json" > "$OUT_DIR/zips.tsv" <<'PY'
import json, sys
r = json.load(open(sys.argv[1]))
for f in sorted(r["files"], key=lambda f: f["key"]):
    k = f["key"]
    if k.endswith(".zip") and k != "2022.08.02_14-37_AuFlat520.zip":
        print(k, f["size"], f["checksum"].split(":", 1)[1], sep="\t")
PY

printf 'key\tarchive_size\tarchive_md5\tcd_offset\tcd_size\tholograms\n' > "$OUT_DIR/videos.tsv"
first=1
while IFS=$'\t' read -r key size md5; do
  url="https://zenodo.org/api/records/10632465/files/$key/content"
  probe="$OUT_DIR/tails/$key.probe"
  curl -fsS -L --retry 5 --retry-delay 3 --max-time 120 -A "$UA" \
    -r "$((size - 262144))-$((size - 1))" -o "$probe" "$url"
  read -r cd_offset cd_size < <(python3 -I - "$probe" <<'PY'
import struct, sys
t = open(sys.argv[1], "rb").read()
e = t.rfind(b"PK\x05\x06")
f = struct.unpack_from("<4s4H2IH", t, e)
print(f[6], f[5])
PY
)
  tail="$OUT_DIR/tails/$key.cd"
  curl -fsS -L --retry 5 --retry-delay 3 --max-time 120 -A "$UA" -D "$tail.headers" \
    -r "$cd_offset-$((size - 1))" -o "$tail" "$url"
  $PY parse-cd "$tail" "$tail.headers" "$size" "$cd_offset" "$key" "$OUT_DIR/members/$key.tsv"
  n="$(($(wc -l < "$OUT_DIR/members/$key.tsv") - 1))"
  printf '%s\t%s\t%s\t%s\t%s\t%s\n' "$key" "$size" "$md5" "$cd_offset" "$cd_size" "$n" >> "$OUT_DIR/videos.tsv"
  frames="$($PY select "$OUT_DIR/members/$key.tsv" "$FRAMES_PER_VIDEO" | tr '\n' ' ')"
  python3 -I - "$OUT_DIR/members/$key.tsv" "$first" $frames >> "$OUT_DIR/selected_frames.tsv" <<'PY'
import csv, sys
rows = list(csv.DictReader(open(sys.argv[1]), delimiter="\t"))
first = sys.argv[2] == "1"
keep = {int(x) for x in sys.argv[3:]}
w = csv.DictWriter(sys.stdout, fieldnames=list(rows[0]), delimiter="\t", lineterminator="\n")
if first:
    w.writeheader()
for r in rows:
    if int(r["frame"]) in keep:
        w.writerow(r)
PY
  first=0
  sleep 1
done < "$OUT_DIR/zips.tsv"

echo "videos=$(($(wc -l < "$OUT_DIR/videos.tsv") - 1)) selected_frames=$(($(wc -l < "$OUT_DIR/selected_frames.tsv") - 1))"
echo "[$(date -Is)] discover done out=$OUT_DIR"
