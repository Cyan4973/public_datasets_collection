#!/usr/bin/env bash
# Download the 7 pinned GWOSC O3b H1 4 kHz bulk strain HDF5 files (files.tsv)
# and validate each one semantically before it is accepted.
#
# Per file: check the GWOSC v2 detail document still reports the pinned size
# (and 100 % duty cycle, 0 NaN), resume the transfer into <name>.part with curl
# (stall-based abort, no hard time limit), require the exact pinned size, then
# run the full decoder validation (channel, GPS, DQ DATA bit for all 4096 s,
# every chunk's Fletcher-32, finite non-zero strain, min/max equal to GWOSC's
# published values).  The observed sha256 is recorded in SHA256SUMS for build
# and verify.  A file that fails validation is renamed <name>.rejected and the
# script exits non-zero; a re-run re-validates a same-size .rejected file
# instead of fetching it again.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="gwosc_o3b_h1_bulk_strain_f64"
DL="$DATA_ROOT/downloads/$DATASET_ID"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
FILES_TSV="$RECIPE_DIR/files.tsv"
mkdir -p "$DL/details" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
echo "[$(date -Is)] download start dataset=$DATASET_ID"
export PYTHONDONTWRITEBYTECODE=1

python3 -I "$RECIPE_DIR/scripts/selftest_gwosc_h5.py"

size_of() { stat -c %s "$1" 2>/dev/null || echo 0; }

tail -n +2 "$FILES_TSV" | while IFS=$'\t' read -r gps utc url size _rest; do
  name="${url##*/}"
  final="$DL/$name"
  part="$final.part"
  stamp="$final.sha256"
  echo "[$(date -Is)] file gps=$gps name=$name size=$size"
  case "$url" in
    "https://gwosc.org/archive/data/O3b_4KHZ_R1/"*"/H-H1_GWOSC_O3b_4KHZ_R1-$gps-4096.hdf5") ;;
    *) echo "FATAL: unexpected url $url" >&2; exit 1 ;;
  esac

  if [ -f "$final" ] && [ -s "$stamp" ] && [ "$(size_of "$final")" = "$size" ]; then
    echo "cache_hit $name sha256=$(cut -d' ' -f1 "$stamp")"
    continue
  fi

  # upstream identity: GWOSC v2 strain-file detail (small JSON)
  detail="$DL/details/H1-$gps-4kHz.json"
  curl -fsSL --retry 5 --retry-delay 5 --max-time 120 -o "$detail.part" \
    "https://gwosc.org/api/v2/strain-files/H1-$gps-4kHz?format=json" < /dev/null
  mv "$detail.part" "$detail"
  python3 -I - "$detail" "$gps" "$size" "$url" <<'PY'
import json, sys
d = json.load(open(sys.argv[1]))
gps, size, url = int(sys.argv[2]), int(sys.argv[3]), sys.argv[4]
problems = []
if d.get("gps_start") != gps or d.get("detector") != "H1" or d.get("sample_rate_kHz") != 4:
    problems.append(f"identity {d.get('gps_start')} {d.get('detector')} {d.get('sample_rate_kHz')}")
if int(d.get("filesize_bytes", -1)) != size:
    problems.append(f"filesize_bytes {d.get('filesize_bytes')} != pinned {size}")
if float(d.get("dutycycle_percent", 0)) != 100.0 or float(d.get("nans_fraction", 1)) != 0.0:
    problems.append(f"dutycycle {d.get('dutycycle_percent')} nans {d.get('nans_fraction')}")
if str(d.get("hdf5_url", "")).split("?")[0] != url:
    problems.append(f"hdf5_url {d.get('hdf5_url')}")
if problems:
    raise SystemExit("FATAL: GWOSC detail changed: " + "; ".join(problems))
print(f"detail_ok gps={gps} filesize={size}")
PY

  if [ ! -f "$final" ] && [ -f "$final.rejected" ] && [ "$(size_of "$final.rejected")" = "$size" ]; then
    echo "re-validating previously rejected $name"
    mv "$final.rejected" "$final"
  fi
  if [ ! -f "$final" ]; then
    if [ "$(size_of "$part")" -gt "$size" ]; then
      echo "oversized partial $part; restarting"
      rm -f "$part"
    fi
    if [ "$(size_of "$part")" != "$size" ]; then
      curl -fL -C - --retry 10 --retry-delay 5 --retry-all-errors \
        --speed-limit 1024 --speed-time 120 --max-filesize "$((size + 1024))" \
        -o "$part" "$url" < /dev/null
    fi
    got="$(size_of "$part")"
    if [ "$got" != "$size" ]; then
      echo "FATAL: $name has $got bytes, expected $size" >&2
      exit 1
    fi
    mv "$part" "$final"
  fi

  if ! python3 -I "$RECIPE_DIR/scripts/gwosc_strain.py" validate --files "$FILES_TSV" --file "$final" --gps "$gps" < /dev/null; then
    mv "$final" "$final.rejected"
    rm -f "$stamp"
    echo "FATAL: $name failed semantic validation (kept as $name.rejected)" >&2
    exit 1
  fi
  sha="$(sha256sum "$final" | cut -d' ' -f1)"
  printf '%s  %s\n' "$sha" "$name" > "$stamp"
  echo "validated $name sha256=$sha"
done

# SHA256SUMS in files.tsv order (observed at download time; GWOSC publishes none)
: > "$DL/SHA256SUMS.part"
tail -n +2 "$FILES_TSV" | while IFS=$'\t' read -r _gps _utc url _rest; do
  cat "$DL/${url##*/}.sha256" >> "$DL/SHA256SUMS.part"
done
mv "$DL/SHA256SUMS.part" "$DL/SHA256SUMS"
cat "$DL/SHA256SUMS"
echo "[$(date -Is)] download done dataset=$DATASET_ID files=$(wc -l < "$DL/SHA256SUMS")"
