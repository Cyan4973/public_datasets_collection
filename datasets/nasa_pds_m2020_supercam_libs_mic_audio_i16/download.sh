#!/usr/bin/env bash
# Fetch the 634 pinned Mars 2020 SuperCam raw-audio FITS products listed in
# sources.tsv (396,984,960 bytes) and validate each against its pinned size,
# the bundle MD5 manifest value, and its FITS structure (primary header
# keywords and final SOUND HDU header, compared to the SHA-256 of the header
# blocks probed at discovery). Resumable: re-runs keep validated files and
# resume partial .part files.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
[[ "$DATA_DIR" = /* ]] || DATA_DIR="$REPO_ROOT/$DATA_DIR"
CANDIDATE_ID="nasa_pds_m2020_supercam_libs_mic_audio_i16"
SOURCES="$RECIPE_DIR/sources.tsv"
DOWNLOAD_DIR="$DATA_DIR/downloads/$CANDIDATE_ID"
LOG_DIR="$DATA_DIR/logs/$CANDIDATE_ID"
PARALLEL="${DOWNLOAD_PARALLEL:-4}"
EXPECTED_PRODUCTS=634
EXPECTED_BYTES=396984960
EXPECTED_SOURCES_SHA256="3bea302314c546f8aba21d0f6757272166ebabe9ef085ab4883691f806252661"

mkdir -p "$DOWNLOAD_DIR" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
echo "[$(date -Is)] download start candidate=$CANDIDATE_ID"

actual_sha="$(sha256sum "$SOURCES" | cut -d' ' -f1)"
[[ "$actual_sha" == "$EXPECTED_SOURCES_SHA256" ]] || { echo "sources.tsv SHA-256 changed: $actual_sha" >&2; exit 1; }

# Validate the source plan before any network I/O.
python3 - "$SOURCES" "$EXPECTED_PRODUCTS" "$EXPECTED_BYTES" <<'PY'
import csv, re, sys
rows = list(csv.DictReader(open(sys.argv[1], encoding="utf-8", newline=""), delimiter="\t"))
if len(rows) != int(sys.argv[2]) or [int(r["ordinal"]) for r in rows] != list(range(1, len(rows) + 1)):
    raise SystemExit("pinned product count or order changed")
if sum(int(r["file_bytes"]) for r in rows) != int(sys.argv[3]):
    raise SystemExit("pinned byte total changed")
prefix = "https://pds-geosciences.wustl.edu/m2020/urn-nasa-pds-mars2020_supercam/data_raw_audio/sol_"
for r in rows:
    name = r["fits_filename"]
    if not re.fullmatch(r"LS__\d{4}_\d{10}_\d{3}E[A-Z0-9]{2}__\d{7}SCAM\d{5}_\d{3}_LUJ\d{2}\.fits", name):
        raise SystemExit(f"unsafe product name {name}")
    if r["fits_url"] != f"{prefix}{int(r['sol']):05d}/{name}":
        raise SystemExit(f"non-official or inconsistent URL for {name}")
    if not re.fullmatch(r"[0-9a-f]{32}", r["md5"]):
        raise SystemExit(f"bad pinned MD5 for {name}")
    if int(r["sound_header_offset"]) != int(r["file_bytes"]) - 351360:
        raise SystemExit(f"inconsistent SOUND offset for {name}")
if len({r["fits_filename"] for r in rows}) != len(rows):
    raise SystemExit("duplicate product")
print(f"source_plan=ok products={len(rows)} bytes={sum(int(r['file_bytes']) for r in rows)}")
PY

fetch_one() {
  local name="$1" url="$2" size="$3" md5="$4"
  local target="$DOWNLOAD_DIR/$name"
  if [[ -f "$target" && "$(stat -c %s "$target")" == "$size" ]] && [[ "$(md5sum "$target" | cut -d' ' -f1)" == "$md5" ]]; then
    echo "cache_hit $name"
    return 0
  fi
  rm -f "$target"
  local attempt
  for attempt in 1 2 3; do
    if [[ -f "$target.part" && "$(stat -c %s "$target.part")" -gt "$size" ]]; then
      rm -f "$target.part"
    fi
    curl -fL -sS -C - --retry 10 --retry-delay 5 --speed-limit 1024 --speed-time 120 \
      --max-filesize 2000000 -o "$target.part" "$url" || true
    if [[ -f "$target.part" && "$(stat -c %s "$target.part")" == "$size" ]]; then
      if [[ "$(md5sum "$target.part" | cut -d' ' -f1)" == "$md5" ]]; then
        mv "$target.part" "$target"
        echo "fetched $name"
        return 0
      fi
      echo "md5_mismatch attempt=$attempt $name" >&2
      rm -f "$target.part"
    fi
  done
  echo "FAILED $name" >&2
  return 1
}
export -f fetch_one
export DOWNLOAD_DIR

tail -n +2 "$SOURCES" | awk -F'\t' '{print $3 "\t" $4 "\t" $5 "\t" $6}' \
  | xargs -P "$PARALLEL" -L 1 bash -c 'fetch_one "$@"' _

# Semantic validation of every payload and a durable inventory.
python3 - "$SOURCES" "$DOWNLOAD_DIR" "$RECIPE_DIR/scripts" <<'PY'
import csv, hashlib, json, sys
from pathlib import Path
sys.path.insert(0, sys.argv[3])
import m2020mic as M
rows = list(csv.DictReader(open(sys.argv[1], encoding="utf-8", newline=""), delimiter="\t"))
ddir = Path(sys.argv[2])
records = []
for r in rows:
    raw = (ddir / r["fits_filename"]).read_bytes()
    if len(raw) != int(r["file_bytes"]) or hashlib.md5(raw).hexdigest() != r["md5"]:
        raise SystemExit(f"{r['fits_filename']}: size/MD5 mismatch")
    if hashlib.sha256(raw[:M.PRIMARY_HEADER_BYTES]).hexdigest() != r["primary_header_sha256"]:
        raise SystemExit(f"{r['fits_filename']}: primary header differs from discovery probe")
    off = int(r["sound_header_offset"])
    if hashlib.sha256(raw[off:off + M.BLOCK]).hexdigest() != r["sound_header_sha256"]:
        raise SystemExit(f"{r['fits_filename']}: SOUND header differs from discovery probe")
    hdus = M.walk_hdus(raw)
    if M.primary_ok(hdus[0]["cards"]) or M.sound_ok(hdus[-1]["cards"]) or hdus[-1]["header_offset"] != off:
        raise SystemExit(f"{r['fits_filename']}: FITS structure outside the pinned configuration")
    records.append({"fits_filename": r["fits_filename"], "bytes": len(raw), "md5": r["md5"],
                    "sha256": hashlib.sha256(raw).hexdigest(), "hdus": len(hdus)})
inv = {"candidate_id": M.DATASET_ID, "products": len(records), "bytes": sum(x["bytes"] for x in records),
       "sources_sha256": hashlib.sha256(Path(sys.argv[1]).read_bytes()).hexdigest(), "records": records}
(ddir / "download_inventory.json").write_text(json.dumps(inv, indent=1, sort_keys=True) + "\n", encoding="utf-8")
print(f"validated_products={inv['products']} bytes={inv['bytes']}")
PY

echo "[$(date -Is)] download done candidate=$CANDIDATE_ID"
