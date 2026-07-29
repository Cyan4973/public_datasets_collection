#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="figshare_rmd17_trajectories_f64"
API_URL="https://api.figshare.com/v2/articles/12672038/versions/3"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
METADATA="$DOWNLOAD_DIR/figshare_article_12672038_v3.json"
PLAN="$DOWNLOAD_DIR/download_plan.tsv"
INVENTORY="$DOWNLOAD_DIR/download_inventory.tsv"
MAX_FILE_BYTES=3000000000
MAX_TOTAL_BYTES=3000000000

mkdir -p "$DOWNLOAD_DIR" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
echo "[$(date -Is)] download start dataset=$DATASET_ID"

curl --fail --location --retry 4 --retry-delay 2 \
  --user-agent "openzl-public-datasets/1.0" --output "$METADATA.part" "$API_URL"
mv "$METADATA.part" "$METADATA"

export METADATA PLAN MAX_FILE_BYTES MAX_TOTAL_BYTES
python3 - <<'PY'
import json, os
from pathlib import Path

metadata = Path(os.environ["METADATA"])
plan = Path(os.environ["PLAN"])
doc = json.loads(metadata.read_text(encoding="utf-8"))
license_obj = doc.get("license") or {}
license_text = " ".join(
    str(license_obj.get(k, "")) for k in ("name", "title", "url")
)
if "creativecommons.org/publicdomain/zero/1.0" not in license_text.lower() and "cc0" not in license_text.lower():
    raise SystemExit(f"pinned record is not confirmed CC0: {license_obj!r}")
files = doc.get("files") or []
if not files:
    raise SystemExit("pinned Figshare record has no files")
wanted = ("aspirin", "benzene", "ethanol", "malonaldehyde", "toluene")
direct = []
for item in files:
    name = str(item.get("name", ""))
    lower = name.lower()
    if lower.endswith(".npz") and any(molecule in lower for molecule in wanted):
        direct.append(item)
selected = direct
if len({next(m for m in wanted if m in str(x.get('name','')).lower()) for x in direct}) != len(wanted):
    archives = [
        item for item in files
        if "rmd17" in str(item.get("name", "")).lower()
        and str(item.get("name", "")).lower().endswith((".tar.bz2", ".tar.gz", ".tgz", ".zip"))
    ]
    if not archives:
        names = ", ".join(str(item.get("name", "")) for item in files)
        raise SystemExit(f"no complete direct NPZ set or recognized rMD17 archive; files: {names}")
    selected = [min(archives, key=lambda item: int(item.get("size", 0) or 0))]
max_file = int(os.environ["MAX_FILE_BYTES"])
max_total = int(os.environ["MAX_TOTAL_BYTES"])
total = 0
rows = []
for item in selected:
    name = str(item.get("name", ""))
    url = str(item.get("download_url", ""))
    size = int(item.get("size", 0) or 0)
    checksum = str(item.get("computed_md5", "") or item.get("supplied_md5", ""))
    if not name or not url or size <= 0 or size > max_file:
        raise SystemExit(f"invalid or over-cap Figshare file: {item!r}")
    total += size
    rows.append((name, url, size, checksum))
if total > max_total:
    raise SystemExit(f"Figshare selection exceeds total cap: {total}")
with plan.open("w", encoding="utf-8") as handle:
    handle.write("name\tdownload_url\tbytes\tmd5\n")
    for row in rows:
        handle.write("\t".join(map(str, row)) + "\n")
print(f"planned_files={len(rows)} planned_bytes={total}")
for row in rows:
    print(f"plan name={row[0]} bytes={row[2]}")
PY

printf 'name\tdownload_url\tbytes\tmd5\tsha256\n' > "$INVENTORY"
tail -n +2 "$PLAN" | while IFS=$'\t' read -r name url expected_size expected_md5; do
  target="$DOWNLOAD_DIR/$name"
  if [[ -f "$target" ]] && [[ "$(wc -c < "$target" | tr -d ' ')" == "$expected_size" ]]; then
    echo "reuse existing $name"
  else
    rm -f "$target" "$target.part"
    curl --fail --location --retry 4 --retry-delay 3 \
      --user-agent "openzl-public-datasets/1.0" \
      --max-filesize "$MAX_FILE_BYTES" --output "$target.part" "$url"
    mv "$target.part" "$target"
  fi
  actual_size="$(wc -c < "$target" | tr -d ' ')"
  [[ "$actual_size" == "$expected_size" ]] || { echo "size mismatch for $name" >&2; exit 1; }
  if [[ -n "$expected_md5" ]]; then
    [[ "$(md5sum "$target" | awk '{print $1}')" == "$expected_md5" ]] || { echo "MD5 mismatch for $name" >&2; exit 1; }
  fi
  sha256="$(sha256sum "$target" | awk '{print $1}')"
  printf '%s\t%s\t%s\t%s\t%s\n' "$name" "$url" "$actual_size" "$expected_md5" "$sha256" >> "$INVENTORY"
done

python3 "$REPO_ROOT/datasets/$DATASET_ID/scripts/rmd17_npz.py" inventory \
  --download-dir "$DOWNLOAD_DIR"
echo "[$(date -Is)] download done dataset=$DATASET_ID"
