#!/usr/bin/env bash
# Download five exact CC BY 4.0 LeConte Bay SEG-Y objects.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="zenodo_leconte_chirp_segy_f32"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
mkdir -p "$DOWNLOAD_DIR" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
echo "[$(date -Is)] download start dataset=$DATASET_ID"

while IFS=$'\t' read -r name size md5 url; do
  [[ -n "$name" ]] || continue
  target="$DOWNLOAD_DIR/$name"
  if [[ -f "$target" ]] && [[ "$(stat -c %s "$target")" == "$size" ]] && [[ "$(md5sum "$target" | awk '{print $1}')" == "$md5" ]]; then
    echo "verified cached $name"
    continue
  fi
  part="$target.part"
  rm -f "$part"
  echo "downloading $name bytes=$size"
  curl --fail --location --retry 5 --retry-delay 2 --max-time 3600 \
    --output "$part" "$url"
  actual_size="$(stat -c %s "$part")"
  actual_md5="$(md5sum "$part" | awk '{print $1}')"
  [[ "$actual_size" == "$size" ]] || { echo "size mismatch for $name: $actual_size != $size" >&2; exit 1; }
  [[ "$actual_md5" == "$md5" ]] || { echo "MD5 mismatch for $name: $actual_md5 != $md5" >&2; exit 1; }
  mv "$part" "$target"
done <<'EOF'
20170916063700utc_acrossfjord.jsf.sgy	5593632	f8659291d02e652fd0ad1b637ce6f263	https://zenodo.org/api/records/4008565/files/20170916063700utc_acrossfjord.jsf.sgy/content
20170913032800_alongfjord.002.jsf.sgy	18188960	7ec1ad982273e09cab26f0252fb1af77	https://zenodo.org/api/records/4008565/files/20170913032800_alongfjord.002.jsf.sgy/content
20170912181500_alongfjord.001.jsf.sgy	24316656	e73bf3fb9f7bd1be8c047f15bbc10334	https://zenodo.org/api/records/4008565/files/20170912181500_alongfjord.001.jsf.sgy/content
20170913032800_alongfjord.001.jsf.sgy	36287840	1cfa077b18cb7e41133d66e23837e781	https://zenodo.org/api/records/4008565/files/20170913032800_alongfjord.001.jsf.sgy/content
20170918085900utc_acrossfjord.jsf.sgy	42666084	724825ec6356673a052b727f25f66b9b	https://zenodo.org/api/records/4008565/files/20170918085900utc_acrossfjord.jsf.sgy/content
EOF

echo "[$(date -Is)] download done dataset=$DATASET_ID"
