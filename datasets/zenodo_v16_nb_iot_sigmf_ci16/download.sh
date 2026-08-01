#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$REPO_ROOT/datasets/zenodo_v16_nb_iot_sigmf_ci16"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="zenodo_v16_nb_iot_sigmf_ci16"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
DISCOVERY_META="$REPO_ROOT/$DATA_DIR/discovery/zenodo_sigmf_ci16/meta"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"

mkdir -p "$DOWNLOAD_DIR" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
echo "[$(date -Is)] download start dataset=$DATASET_ID"

for record_id in 18202739 19771729; do
  record_json="$DOWNLOAD_DIR/record_$record_id.json"
  curl --fail --silent --show-error --location --retry 3 --max-time 90 \
    --user-agent "openzl-public-datasets/1.0" \
    --output "$record_json.part" "https://zenodo.org/api/records/$record_id"
  mv "$record_json.part" "$record_json"
done
python3 - "$DOWNLOAD_DIR/record_18202739.json" "$DOWNLOAD_DIR/record_19771729.json" <<'PY'
import json
import sys
from pathlib import Path
for name in sys.argv[1:]:
    obj=json.loads(Path(name).read_text(encoding="utf-8"))
    md=obj.get("metadata", {})
    values=[]
    lic=md.get("license")
    if isinstance(lic, dict): values.extend(str(lic.get(k,"")) for k in ("id","name","title"))
    if isinstance(md.get("rights"), list):
        for right in md["rights"]:
            if isinstance(right, dict): values.extend(str(right.get(k,"")) for k in ("id","title"))
    normalized=" ".join(values).lower().replace("_","-")
    if "cc-by-4.0" not in normalized and "creative commons attribution 4.0" not in normalized:
        raise SystemExit(f"record {obj.get('id')} does not explicitly declare CC BY 4.0: {values}")
    print(f"record={obj.get('id')} license=CC-BY-4.0")
PY

files=0
data_bytes=0
while IFS=$'\t' read -r kind record_id name expected_size expected_md5 expected_sha512 url; do
  [[ "$kind" == "kind" ]] && continue
  [[ -n "$kind" ]] || continue
  target="$DOWNLOAD_DIR/$name"
  valid=false
  if [[ -f "$target" ]] \
    && [[ "$(wc -c < "$target" | tr -d ' ')" == "$expected_size" ]] \
    && [[ "$(md5sum "$target" | awk '{print $1}')" == "$expected_md5" ]]; then
    if [[ "$expected_sha512" == "-" ]] \
      || [[ "$(sha512sum "$target" | awk '{print $1}')" == "$expected_sha512" ]]; then
      valid=true
      echo "validated existing $name"
    fi
  fi
  if [[ "$valid" != true ]]; then
    rm -f "$target" "$target.part"
    reuse="$DISCOVERY_META/${record_id}__${name}"
    if [[ "$kind" == "meta" && -f "$reuse" ]] \
      && [[ "$(wc -c < "$reuse" | tr -d ' ')" == "$expected_size" ]] \
      && [[ "$(md5sum "$reuse" | awk '{print $1}')" == "$expected_md5" ]]; then
      echo "reuse validated discovery metadata $reuse"
      cp --reflink=auto "$reuse" "$target"
    else
      echo "fetch $name bytes=$expected_size"
      curl --fail --location --retry 3 --retry-delay 2 \
        --user-agent "openzl-public-datasets/1.0" \
        --max-filesize 500000000 --output "$target.part" "$url"
      mv "$target.part" "$target"
    fi
    actual_size="$(wc -c < "$target" | tr -d ' ')"
    actual_md5="$(md5sum "$target" | awk '{print $1}')"
    if [[ "$actual_size" != "$expected_size" || "$actual_md5" != "$expected_md5" ]]; then
      echo "size/MD5 validation failed for $name" >&2
      exit 1
    fi
    if [[ "$expected_sha512" != "-" ]] \
      && [[ "$(sha512sum "$target" | awk '{print $1}')" != "$expected_sha512" ]]; then
      echo "SHA-512 validation failed for $name" >&2
      exit 1
    fi
  fi
  files=$((files + 1))
  [[ "$kind" == "data" ]] && data_bytes=$((data_bytes + expected_size))
done < "$RECIPE_DIR/selection.tsv"

if [[ "$files" -ne 4 || "$data_bytes" -ne 877648544 ]]; then
  echo "selection realization mismatch files=$files data_bytes=$data_bytes" >&2
  exit 1
fi
echo "[$(date -Is)] download done files=$files primary_source_bytes=$data_bytes"
