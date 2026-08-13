#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$REPO_ROOT/datasets/polyhaven_hdri_exr_f32"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="polyhaven_hdri_exr_f32"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
TOOL_DIR="$REPO_ROOT/$DATA_DIR/tools/tinyexr_v1.0.12"
METADATA_DIR="$DOWNLOAD_DIR/metadata"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"

mkdir -p "$DOWNLOAD_DIR" "$TOOL_DIR" "$METADATA_DIR" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
echo "[$(date -Is)] download start dataset=$DATASET_ID"

valid_file() {
  local path="$1" size="$2" md5="$3" sha256="$4"
  [[ -f "$path" ]] \
    && [[ "$(wc -c < "$path" | tr -d ' ')" == "$size" ]] \
    && [[ "$(md5sum "$path" | awk '{print $1}')" == "$md5" ]] \
    && [[ "$(sha256sum "$path" | awk '{print $1}')" == "$sha256" ]]
}

while IFS=$'\t' read -r kind name size md5 sha256 url alternate_url; do
  [[ "$kind" == "kind" ]] && continue
  target_dir="$DOWNLOAD_DIR"
  [[ "$kind" == "tool" ]] && target_dir="$TOOL_DIR"
  target="$target_dir/$name"
  if valid_file "$target" "$size" "$md5" "$sha256"; then
    echo "validated existing name=$name bytes=$size"
    continue
  fi

  reused=false
  for reuse_dir in \
    "$REPO_ROOT/$DATA_DIR/downloads/polyhaven_hdri_exr_f16" \
    "$REPO_ROOT/$DATA_DIR/downloads/polyhaven_hdri_exr_f32_tinyexr_expand" \
    "$REPO_ROOT/$DATA_DIR/tools/tinyexr_v1.0.12"; do
    candidate="$reuse_dir/$name"
    if valid_file "$candidate" "$size" "$md5" "$sha256"; then
      cp --reflink=auto "$candidate" "$target"
      echo "reused pinned local file name=$name from=$candidate"
      reused=true
      break
    fi
  done
  [[ "$reused" == true ]] && continue

  success=false
  for candidate_url in "$url" "$alternate_url"; do
    [[ "$candidate_url" == "-" ]] && continue
    echo "fetch name=$name bytes=$size url=$candidate_url"
    if curl --fail --show-error --location --retry 3 --retry-delay 2 \
      --max-time 3600 --max-filesize "$size" \
      --user-agent "openzl-public-datasets-exr/1.0" \
      --output "$target.part" "$candidate_url"; then
      if valid_file "$target.part" "$size" "$md5" "$sha256"; then
        mv "$target.part" "$target"
        success=true
        break
      fi
    fi
    rm -f "$target.part"
  done
  if [[ "$success" != true ]]; then
    echo "unable to acquire pinned file: $name" >&2
    exit 1
  fi
done < "$RECIPE_DIR/selection.tsv"

curl --fail --silent --show-error --location --retry 3 --max-time 90 \
  --user-agent "openzl-public-datasets-exr/1.0" \
  --output "$METADATA_DIR/polyhaven_license.html.part" https://polyhaven.com/license
mv "$METADATA_DIR/polyhaven_license.html.part" "$METADATA_DIR/polyhaven_license.html"
for asset in abandoned_greenhouse brown_photostudio_02 golden_gate_hills; do
  curl --fail --silent --show-error --location --retry 3 --max-time 90 \
    --user-agent "openzl-public-datasets-exr/1.0" \
    --output "$METADATA_DIR/${asset}_files.json.part" "https://api.polyhaven.com/files/$asset"
  mv "$METADATA_DIR/${asset}_files.json.part" "$METADATA_DIR/${asset}_files.json"
done

export DOWNLOAD_DIR TOOL_DIR METADATA_DIR
python3 - <<'PY'
import json
import os
from pathlib import Path

download = Path(os.environ["DOWNLOAD_DIR"])
metadata = Path(os.environ["METADATA_DIR"])
tool = Path(os.environ["TOOL_DIR"])

license_text = (metadata / "polyhaven_license.html").read_text(encoding="utf-8").lower()
required_license_phrases = ("our assets are all licensed as", "cc0", "commercial work")
if not all(phrase in license_text for phrase in required_license_phrases):
    raise SystemExit("official Poly Haven license page lacks expected CC0/commercial-use statements")

expected = {
    "abandoned_greenhouse": ("1k", "abandoned_greenhouse_1k.exr", 6115125, "b190c4a06d12ee0b641cfe6053aa6056"),
    "brown_photostudio_02": ("8k", "ph_brown_photostudio_02_8k.exr", 77556275, "ea9d4aebdc6ab119c99daea63e547900"),
    "golden_gate_hills": ("4k", "ph_golden_gate_hills_4k.exr", 96436466, "7fbc8ea1646f59ef5cd0b202a4359cb6"),
}
for asset, (resolution, local_name, size, md5) in expected.items():
    obj = json.loads((metadata / f"{asset}_files.json").read_text(encoding="utf-8"))
    exr = obj.get("hdri", {}).get(resolution, {}).get("exr", {})
    if int(exr.get("size", -1)) != size or str(exr.get("md5", "")) != md5:
        raise SystemExit(f"official Poly Haven metadata mismatch for {asset}: {exr}")
    if not (download / local_name).is_file():
        raise SystemExit(f"missing local EXR after acquisition: {local_name}")

tinyexr = (tool / "tinyexr.h").read_text(encoding="utf-8")
if "TINYEXR_IMPLEMENTATION" not in tinyexr or "Redistribution and use in source and binary forms" not in tinyexr:
    raise SystemExit("TinyEXR header or embedded BSD notice is invalid")
print("validated official Poly Haven CC0 metadata and TinyEXR embedded license")
PY

echo "[$(date -Is)] download done dataset=$DATASET_ID"
