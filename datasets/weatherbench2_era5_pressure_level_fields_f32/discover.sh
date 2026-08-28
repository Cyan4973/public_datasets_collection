#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
CANDIDATE_ID="weatherbench2_era5_pressure_level_fields_f32"
OUT_DIR="$REPO_ROOT/$DATA_DIR/discovery/$CANDIDATE_ID"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$CANDIDATE_ID"
LIST_DIR="$OUT_DIR/listings"
LICENSE_DIR="$OUT_DIR/license_documents"
BUCKET="weatherbench2"
WB2_REVISION="95c36d547b22abc2d191451a580b0b194fde67ef"

mkdir -p "$OUT_DIR" "$LOG_DIR" "$LIST_DIR" "$LICENSE_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/discover.$RUN_TS.log" "$LOG_DIR/discover.latest.log") 2>&1
echo "[$(date -Is)] metadata discovery start candidate=$CANDIDATE_ID"

UA="openzl-public-datasets-weatherbench2-era5-discovery/1.0"

fetch() {
  local url="$1" output="$2" cap="$3"
  curl --globoff --fail --silent --show-error --location \
    --retry 5 --retry-delay 2 --retry-all-errors --max-time 180 \
    --max-filesize "$cap" --user-agent "$UA" \
    --output "$output.part" "$url"
  mv "$output.part" "$output"
  echo "metadata url=$url bytes=$(stat -c %s "$output")"
}

fetch_optional() {
  local url="$1" output="$2" cap="$3"
  set +e
  curl --globoff --fail --silent --show-error --location \
    --retry 2 --retry-delay 2 --retry-all-errors --max-time 180 \
    --max-filesize "$cap" --user-agent "$UA" \
    --output "$output.part" "$url"
  local status=$?
  set -e
  if (( status != 0 )); then
    rm -f "$output.part"
    echo "warning optional_metadata_failed url=$url status=$status" >&2
    return
  fi
  mv "$output.part" "$output"
  echo "optional_metadata url=$url bytes=$(stat -c %s "$output")"
}

list_gcs() {
  local prefix="$1" delimiter="$2" output="$3"
  local args=(
    --globoff --fail --silent --show-error --location
    --retry 5 --retry-delay 2 --retry-all-errors --max-time 180
    --max-filesize 10000000 --user-agent "$UA"
    --get --data-urlencode "maxResults=1000" --data-urlencode "prefix=$prefix"
  )
  if [[ -n "$delimiter" ]]; then
    args+=(--data-urlencode "delimiter=$delimiter")
  fi
  curl "${args[@]}" --output "$output.part" \
    "https://storage.googleapis.com/storage/v1/b/$BUCKET/o"
  mv "$output.part" "$output"
  echo "gcs_listing prefix=$prefix delimiter=${delimiter:-none} bytes=$(stat -c %s "$output")"
}

fetch \
  "https://raw.githubusercontent.com/google-research/weatherbench2/$WB2_REVISION/docs/source/data-guide.ipynb" \
  "$OUT_DIR/weatherbench2_data_guide.ipynb" 5000000
fetch_optional \
  "https://weatherbench2.readthedocs.io/en/latest/data-guide.html" \
  "$OUT_DIR/weatherbench2_data_guide.html" 10000000

list_gcs "datasets/era5/" "/" "$LIST_DIR/era5_root.json"

export OUT_DIR
python3 - <<'PY'
from __future__ import annotations

import json
import os
from pathlib import Path


out_dir = Path(os.environ["OUT_DIR"])
listing = json.loads((out_dir / "listings" / "era5_root.json").read_text(encoding="utf-8"))
prefixes = sorted(
    str(value)
    for value in listing.get("prefixes", [])
    if str(value).endswith(".zarr/")
)
if not prefixes:
    raise SystemExit("WeatherBench2 ERA5 listing contains no Zarr prefixes")


def preference(prefix: str) -> tuple[int, int, str]:
    lower = prefix.lower()
    resolution_rank = 99
    for rank, token in enumerate(("240x121", "128x64", "64x32", "1440x721")):
        if token in lower:
            resolution_rank = rank
            break
    conservative_rank = 0 if "conservative" in lower else 1
    return resolution_rank, conservative_rank, prefix


selected = min(prefixes, key=preference)
(out_dir / "era5_zarr_prefixes.txt").write_text("\n".join(prefixes) + "\n", encoding="utf-8")
(out_dir / "selected_prefix.txt").write_text(selected + "\n", encoding="utf-8")
print(f"era5_zarr_prefix_count={len(prefixes)}")
print(f"selected_prefix={selected}")
PY

SELECTED_PREFIX="$(tr -d '\r\n' < "$OUT_DIR/selected_prefix.txt")"
BASE_URL="https://storage.googleapis.com/$BUCKET/${SELECTED_PREFIX%/}"
fetch "$BASE_URL/.zmetadata" "$OUT_DIR/zmetadata.json" 20000000
fetch_optional "$BASE_URL/.zattrs" "$OUT_DIR/zattrs.json" 1000000
fetch_optional "$BASE_URL/.zgroup" "$OUT_DIR/zgroup.json" 1000000

: > "$OUT_DIR/license_listings.tsv"
printf 'scope\tstem\tprefix\tlocal_path\n' >> "$OUT_DIR/license_listings.tsv"
for scope in root era5 zarr; do
  case "$scope" in
    root) base="" ;;
    era5) base="datasets/era5/" ;;
    zarr) base="$SELECTED_PREFIX" ;;
  esac
  for stem in LICENSE LICENSE.txt License license LICENCE COPYING TERMS NOTICE README README.md; do
    safe_scope="${scope}_${stem//./_}"
    prefix="${base}${stem}"
    output="$LIST_DIR/license_${safe_scope}.json"
    list_gcs "$prefix" "" "$output"
    printf '%s\t%s\t%s\t%s\n' "$scope" "$stem" "$prefix" "$output" >> "$OUT_DIR/license_listings.tsv"
  done
done

export BASE_URL BUCKET LICENSE_DIR SELECTED_PREFIX WB2_REVISION
python3 - <<'PY'
from __future__ import annotations

import csv
import hashlib
import html
import json
import math
import os
from pathlib import Path
import re
from urllib.parse import quote


out_dir = Path(os.environ["OUT_DIR"])
license_dir = Path(os.environ["LICENSE_DIR"])
metadata_value = json.loads((out_dir / "zmetadata.json").read_text(encoding="utf-8"))
metadata = metadata_value.get("metadata") if isinstance(metadata_value, dict) else None
if not isinstance(metadata, dict) or not metadata:
    raise SystemExit("invalid consolidated Zarr metadata")


def product(items: list[int]) -> int:
    result = 1
    for item in items:
        result *= item
    return result


arrays: list[dict[str, object]] = []
for key, array_meta in sorted(metadata.items()):
    if not key.endswith("/.zarray") or not isinstance(array_meta, dict):
        continue
    name = key[: -len("/.zarray")]
    attrs = metadata.get(f"{name}/.zattrs", {})
    dimensions = attrs.get("_ARRAY_DIMENSIONS", []) if isinstance(attrs, dict) else []
    shape = [int(value) for value in array_meta.get("shape", [])]
    chunks = [int(value) for value in array_meta.get("chunks", [])]
    dtype = str(array_meta.get("dtype") or "")
    item_bytes_match = re.fullmatch(r"[<>=|]?[A-Za-z](\d+)", dtype)
    item_bytes = int(item_bytes_match.group(1)) if item_bytes_match else 0
    arrays.append(
        {
            "name": name,
            "dtype": dtype,
            "dimensions": ",".join(str(value) for value in dimensions),
            "shape": ",".join(str(value) for value in shape),
            "chunks": ",".join(str(value) for value in chunks),
            "values": product(shape) if shape else 0,
            "decoded_bytes": (product(shape) if shape else 0) * item_bytes,
            "compressor": json.dumps(array_meta.get("compressor"), sort_keys=True),
            "order": str(array_meta.get("order") or ""),
            "fill_value": json.dumps(array_meta.get("fill_value"), sort_keys=True),
        }
    )

columns = (
    "name", "dtype", "dimensions", "shape", "chunks", "values",
    "decoded_bytes", "compressor", "order", "fill_value",
)
with (out_dir / "arrays.tsv").open("w", encoding="utf-8", newline="") as handle:
    writer = csv.DictWriter(handle, fieldnames=columns, delimiter="\t", lineterminator="\n")
    writer.writeheader()
    writer.writerows(arrays)

pressure_float32 = [
    row
    for row in arrays
    if row["dtype"] in {"<f4", "=f4", "f4"}
    and {"level", "latitude", "longitude"}.issubset(set(str(row["dimensions"]).split(",")))
]

license_candidates: dict[tuple[str, str], dict[str, object]] = {}
with (out_dir / "license_listings.tsv").open(encoding="utf-8", newline="") as handle:
    for request in csv.DictReader(handle, delimiter="\t"):
        value = json.loads(Path(request["local_path"]).read_text(encoding="utf-8"))
        for item in value.get("items", []) if isinstance(value, dict) else []:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "")
            generation = str(item.get("generation") or "")
            license_candidates[(name, generation)] = {
                "scope": request["scope"],
                "name": name,
                "size_bytes": int(str(item.get("size") or "0")),
                "generation": generation,
                "md5_base64": str(item.get("md5Hash") or ""),
                "url": f"https://storage.googleapis.com/{os.environ['BUCKET']}/{quote(name, safe='/')}",
            }
license_rows = sorted(license_candidates.values(), key=lambda row: (str(row["scope"]), str(row["name"])))
with (out_dir / "license_candidates.tsv").open("w", encoding="utf-8", newline="") as handle:
    fields = ("scope", "name", "size_bytes", "generation", "md5_base64", "url")
    writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n")
    writer.writeheader()
    writer.writerows(license_rows)

guide_hits: list[dict[str, str]] = []
for path in sorted(out_dir.glob("weatherbench2_data_guide.*")):
    raw = html.unescape(path.read_text(encoding="utf-8", errors="replace"))
    for line_number, line in enumerate(raw.splitlines(), 1):
        normalized = re.sub(r"\s+", " ", line).strip()
        lower = normalized.lower()
        if normalized and any(token in lower for token in ("era5", "license", "licence", "copernicus", "ecmwf")):
            guide_hits.append({"document": path.name, "line": str(line_number), "text": normalized[:1500]})
with (out_dir / "guide_hits.tsv").open("w", encoding="utf-8", newline="") as handle:
    writer = csv.DictWriter(handle, fieldnames=("document", "line", "text"), delimiter="\t", lineterminator="\n")
    writer.writeheader()
    writer.writerows(guide_hits)

summary = {
    "candidate_id": "weatherbench2_era5_pressure_level_fields_f32",
    "weatherbench2_revision": os.environ["WB2_REVISION"],
    "selected_zarr_prefix": os.environ["SELECTED_PREFIX"],
    "zarr_metadata_url": os.environ["BASE_URL"] + "/.zmetadata",
    "array_count": len(arrays),
    "pressure_level_float32_array_count": len(pressure_float32),
    "pressure_level_float32_arrays": pressure_float32,
    "license_candidate_count": len(license_rows),
    "license_candidates": license_rows,
    "guide_relevant_hit_count": len(guide_hits),
    "dataset_payload_bytes_downloaded": 0,
    "next_step": (
        "Review exact ERA5 license evidence and pressure-level float32 arrays. "
        "Only then probe one numerical Zarr chunk and its compressor."
    ),
}
(out_dir / "summary.json").write_text(
    json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
)
print(json.dumps(summary, indent=2, sort_keys=True))
PY

while IFS=$'\t' read -r scope name size_bytes generation md5_base64 url; do
  [[ "$scope" != "scope" ]] || continue
  : "$generation" "$md5_base64"
  if (( size_bytes <= 0 || size_bytes > 2000000 )); then
    echo "warning license_candidate_size_rejected name=$name bytes=$size_bytes" >&2
    continue
  fi
  safe="${scope}__${name//\//__}"
  fetch "$url" "$LICENSE_DIR/$safe" 2000000
done < "$OUT_DIR/license_candidates.tsv"

echo "[$(date -Is)] metadata discovery done candidate=$CANDIDATE_ID"
