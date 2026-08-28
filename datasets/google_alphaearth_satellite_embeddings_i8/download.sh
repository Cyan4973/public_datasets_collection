#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$REPO_ROOT/datasets/google_alphaearth_satellite_embeddings_i8"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="google_alphaearth_satellite_embeddings_i8"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
HEADER_DIR="$DOWNLOAD_DIR/headers"
CHUNK_DIR="$DOWNLOAD_DIR/chunks"
DOC_DIR="$DOWNLOAD_DIR/documentation"
mkdir -p "$DOWNLOAD_DIR" "$LOG_DIR" "$HEADER_DIR" "$CHUNK_DIR" "$DOC_DIR"

RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
echo "[$(date -Is)] download start dataset=$DATASET_ID"

UA="openzl-public-datasets-alphaearth-i8/1.0"
HEADER_BYTES="${ALPHAEARTH_HEADER_BYTES:-4194304}"
JOBS="${ALPHAEARTH_JOBS:-8}"
SOURCES="$DOWNLOAD_DIR/pinned_sources.tsv"
PLAN="$DOWNLOAD_DIR/download_plan.tsv"

if (( HEADER_BYTES < 65536 || HEADER_BYTES > 16777216 )); then
  echo "FATAL: ALPHAEARTH_HEADER_BYTES must be between 65536 and 16777216" >&2
  exit 1
fi
if (( JOBS < 1 || JOBS > 32 )); then
  echo "FATAL: ALPHAEARTH_JOBS must be between 1 and 32" >&2
  exit 1
fi
if ! command -v zstd >/dev/null 2>&1; then
  echo "FATAL: zstd command is required for the early tile-decode check" >&2
  exit 1
fi

fetch_document() {
  local name="$1" url="$2" max_size="$3" min_size="$4"
  local output="$DOC_DIR/$name"
  if [[ -f "$output" ]] && [[ "${FORCE_DOWNLOAD:-0}" != "1" ]]; then
    local current_size
    current_size="$(stat -c %s "$output")"
    if (( current_size >= min_size && current_size <= max_size )); then
      echo "documentation cache_hit file=$name bytes=$current_size"
      return
    fi
  fi
  rm -f "$output.part"
  curl --globoff --fail --silent --show-error --location \
    --retry 5 --retry-delay 3 --retry-all-errors --connect-timeout 30 \
    --speed-limit 1024 --speed-time 120 --max-time 300 \
    --max-filesize "$max_size" --user-agent "$UA" \
    --output "$output.part" "$url"
  local actual_size
  actual_size="$(stat -c %s "$output.part")"
  if (( actual_size < min_size || actual_size > max_size )); then
    echo "FATAL: documentation size outside bounds file=$name bytes=$actual_size" >&2
    exit 1
  fi
  mv "$output.part" "$output"
  echo "documentation fetched file=$name bytes=$actual_size"
}

fetch_document \
  "gcs_guide.html" \
  "https://developers.google.com/earth-engine/guides/aef_on_gcs_readme" \
  10000000 \
  20000
fetch_document \
  "catalog.html" \
  "https://developers.google.com/earth-engine/datasets/catalog/GOOGLE_SATELLITE_EMBEDDING_V1_ANNUAL" \
  10000000 \
  20000
fetch_document \
  "stac.json" \
  "https://earthengine-stac.storage.googleapis.com/catalog/GOOGLE/GOOGLE_SATELLITE_EMBEDDING_V1_ANNUAL.json" \
  5000000 \
  1000

export DOC_DIR
python3 - <<'PY'
from __future__ import annotations

import hashlib
import html
import json
import os
from pathlib import Path
import re


root = Path(os.environ["DOC_DIR"])
guide_raw = (root / "gcs_guide.html").read_text(encoding="utf-8", errors="replace")
guide = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html.unescape(guide_raw))).strip().lower()
required_guide_phrases = (
    "alphaearth foundations satellite embedding dataset is produced by google and google deepmind",
    "cc-by 4.0",
    "signed 8-bit integer",
    "8192x8192 pixels, with 64 channels",
    "gs://alphaearth_foundations",
)
missing = [phrase for phrase in required_guide_phrases if phrase not in guide]
if missing:
    raise SystemExit(f"official GCS guide lost required semantic evidence: {missing}")

catalog_raw = (root / "catalog.html").read_text(encoding="utf-8", errors="replace")
catalog = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html.unescape(catalog_raw))).strip().lower()
if "satellite embedding" not in catalog or not any(
    token in catalog for token in ("cc by 4.0", "cc-by 4.0", "cc-by-4.0")
):
    raise SystemExit("official catalog lost dataset identity or CC BY 4.0 evidence")

stac = json.loads((root / "stac.json").read_text(encoding="utf-8"))
if not isinstance(stac, dict) or "SATELLITE_EMBEDDING" not in str(stac.get("id") or "").upper():
    raise SystemExit("official STAC identity mismatch")
if "cc-by-4.0" not in json.dumps(stac, sort_keys=True).lower():
    raise SystemExit("official STAC lost CC BY 4.0 evidence")

inventory = {"documents": {}}
for path in sorted(root.iterdir()):
    if path.is_file() and path.name != "inventory.json":
        inventory["documents"][path.name] = {
            "size_bytes": path.stat().st_size,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
(root / "inventory.json").write_text(
    json.dumps(inventory, indent=2, sort_keys=True) + "\n", encoding="utf-8"
)
print(json.dumps(inventory, indent=2, sort_keys=True))
PY

cat > "$SOURCES" <<'EOF'
source_id	year	utm_zone	object_name	size_bytes	generation	md5_hex	url
australia_2025_55s	2025	55S	satellite_embedding/v1/annual/2025/55S/xbqektjnb7312lfhy-0000000000-0000008192.tiff	2896755609	1772032541598515	c13a616b8d8d33d95a3e882277c396b1	https://storage.googleapis.com/alphaearth_foundations/satellite_embedding/v1/annual/2025/55S/xbqektjnb7312lfhy-0000000000-0000008192.tiff
western_north_america_2024_10n	2024	10N	satellite_embedding/v1/annual/2024/10N/xm8mdfftcd7ymnjc1-0000000000-0000008192.tiff	3201573223	1759311753062003	bbff1a105492504bf9b88c8b4a9b32af	https://storage.googleapis.com/alphaearth_foundations/satellite_embedding/v1/annual/2024/10N/xm8mdfftcd7ymnjc1-0000000000-0000008192.tiff
eastern_north_america_2023_18n	2023	18N	satellite_embedding/v1/annual/2023/18N/xchhzj5zbdl07ojsg-0000008192-0000008192.tiff	3236172986	1759996428479550	8a2a1991af7ff98d0cc3e72a84c5ef01	https://storage.googleapis.com/alphaearth_foundations/satellite_embedding/v1/annual/2023/18N/xchhzj5zbdl07ojsg-0000008192-0000008192.tiff
west_africa_2022_31n	2022	31N	satellite_embedding/v1/annual/2022/31N/xuhz4pul4k1uzdfph-0000000000-0000008192.tiff	2746543589	1760181898877534	5775e0f175f70c076980f0a105c0587c	https://storage.googleapis.com/alphaearth_foundations/satellite_embedding/v1/annual/2022/31N/xuhz4pul4k1uzdfph-0000000000-0000008192.tiff
south_asia_2021_43n	2021	43N	satellite_embedding/v1/annual/2021/43N/x0rjukn8ly2zhpw1f-0000000000-0000000000.tiff	3062147417	1760328087090149	e4b936ce70b54d00f2644e3a86f0a6cb	https://storage.googleapis.com/alphaearth_foundations/satellite_embedding/v1/annual/2021/43N/x0rjukn8ly2zhpw1f-0000000000-0000000000.tiff
eastern_south_america_2020_23s	2020	23S	satellite_embedding/v1/annual/2020/23S/xxzcanefndzs0zmb2-0000008192-0000008192.tiff	3047429043	1760075270286017	3f4f069166238c59e8fe76ef96d68d60	https://storage.googleapis.com/alphaearth_foundations/satellite_embedding/v1/annual/2020/23S/xxzcanefndzs0zmb2-0000008192-0000008192.tiff
EOF

tail -n +2 "$SOURCES" | while IFS=$'\t' read -r source_id year utm_zone object_name size_bytes generation md5_hex url; do
  : "$year" "$utm_zone" "$object_name" "$size_bytes" "$md5_hex"
  output="$HEADER_DIR/$source_id.header.bin"
  response_headers="$HEADER_DIR/$source_id.headers.txt"
  pinned_url="${url}?generation=${generation}"
  end=$((HEADER_BYTES - 1))
  if [[ -f "$output" ]] && [[ "$(stat -c %s "$output")" == "$HEADER_BYTES" ]] && \
     [[ "${FORCE_DOWNLOAD:-0}" != "1" ]]; then
    echo "header cache_hit source=$source_id bytes=$HEADER_BYTES"
    continue
  fi
  rm -f "$output.part" "$response_headers.part"
  echo "fetch_header source=$source_id range=0-$end"
  curl --globoff --fail --silent --show-error --location \
    --retry 5 --retry-delay 3 --retry-all-errors --connect-timeout 30 \
    --speed-limit 1024 --speed-time 120 --max-time 600 \
    --max-filesize "$((HEADER_BYTES + 1))" --range "0-$end" \
    --user-agent "$UA" --dump-header "$response_headers.part" \
    --output "$output.part" "$pinned_url"
  if [[ "$(stat -c %s "$output.part")" != "$HEADER_BYTES" ]]; then
    echo "FATAL: header range size mismatch source=$source_id" >&2
    exit 1
  fi
  mv "$response_headers.part" "$response_headers"
  mv "$output.part" "$output"
done

export HEADER_DIR PLAN RECIPE_DIR SOURCES
python3 - <<'PY'
from __future__ import annotations

import csv
import json
import os
from pathlib import Path
import re
import statistics
import sys


sys.path.insert(0, str(Path(os.environ["RECIPE_DIR"]) / "scripts"))
from alphaearth_tiff import chunk_index, parse_header, validate_alphaearth


header_dir = Path(os.environ["HEADER_DIR"])
sources_path = Path(os.environ["SOURCES"])
plan_path = Path(os.environ["PLAN"])


def parse_response_headers(path: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for line in path.read_text(encoding="latin-1").splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        result[key.strip().lower()] = value.strip()
    return result


positions = [
    (3, 3), (4, 3), (3, 4), (4, 4),
    (2, 2), (5, 2), (2, 5), (5, 5),
    (1, 1), (6, 1), (1, 6), (6, 6),
]
source_rows = list(csv.DictReader(sources_path.open("r", encoding="utf-8", newline=""), delimiter="\t"))
plan_rows: list[dict[str, object]] = []
source_summaries: list[dict[str, object]] = []
for source in source_rows:
    source_id = source["source_id"]
    response = parse_response_headers(header_dir / f"{source_id}.headers.txt")
    content_range = response.get("content-range", "")
    match = re.search(r"/(\d+)$", content_range)
    if not match or int(match.group(1)) != int(source["size_bytes"]):
        raise SystemExit(f"{source_id}: source size mismatch in Content-Range: {content_range!r}")
    if response.get("x-goog-generation") != source["generation"]:
        raise SystemExit(f"{source_id}: generation mismatch in response headers")

    info = parse_header(header_dir / f"{source_id}.header.bin")
    validate_alphaearth(info, source_id)
    zone_number = int(source["utm_zone"][:-1])
    expected_epsg = (32600 if source["utm_zone"].endswith("N") else 32700) + zone_number
    if info["projected_crs_epsg"] != expected_epsg:
        raise SystemExit(
            f"{source_id}: path zone {source['utm_zone']} disagrees with "
            f"GeoTIFF EPSG:{info['projected_crs_epsg']}"
        )
    counts = info["tile_byte_counts"]
    candidates = []
    for x, y in positions:
        spatial = y * 8 + x
        axis_counts = [counts[chunk_index(axis, spatial)] for axis in range(64)]
        candidates.append(
            {
                "x": x,
                "y": y,
                "spatial": spatial,
                "minimum": min(axis_counts),
                "median": statistics.median(axis_counts),
                "total": sum(axis_counts),
            }
        )
    chosen = next(
        (row for row in candidates if row["minimum"] >= 1024 and row["median"] >= 65536),
        max(candidates, key=lambda row: (row["minimum"], row["median"], row["total"])),
    )
    if chosen["minimum"] <= 64:
        raise SystemExit(f"{source_id}: no convincingly nonconstant interior tile: {candidates}")
    spatial = int(chosen["spatial"])
    for axis in range(64):
        index = chunk_index(axis, spatial)
        sample_id = f"{source_id}_A{axis:02d}_x{chosen['x']:02d}_y{chosen['y']:02d}"
        plan_rows.append(
            {
                "sample_id": sample_id,
                "source_id": source_id,
                "year": source["year"],
                "utm_zone": source["utm_zone"],
                "object_name": source["object_name"],
                "source_size_bytes": source["size_bytes"],
                "generation": source["generation"],
                "source_md5_hex": source["md5_hex"],
                "url": source["url"],
                "embedding_axis": f"A{axis:02d}",
                "embedding_axis_index": axis,
                "tile_x": chosen["x"],
                "tile_y": chosen["y"],
                "spatial_tile_index": spatial,
                "tiff_chunk_index": index,
                "tile_width": info["tile_width"],
                "tile_length": info["tile_length"],
                "compression": info["compression"],
                "predictor": info["predictor"],
                "projected_crs_epsg": info["projected_crs_epsg"],
                "byte_offset": info["tile_offsets"][index],
                "byte_count": info["tile_byte_counts"][index],
                "chunk_path": f"chunks/{source_id}/{sample_id}.zstd",
            }
        )
    source_summaries.append(
        {
            "source_id": source_id,
            "selected_tile_x": chosen["x"],
            "selected_tile_y": chosen["y"],
            "selected_spatial_tile_index": spatial,
            "compressed_axis_bytes_min": chosen["minimum"],
            "compressed_axis_bytes_median": chosen["median"],
            "compressed_axis_bytes_total": chosen["total"],
        }
    )

if len(plan_rows) != 6 * 64:
    raise SystemExit(f"unexpected plan size: {len(plan_rows)}")
columns = tuple(plan_rows[0])
with plan_path.open("w", encoding="utf-8", newline="") as handle:
    writer = csv.DictWriter(handle, fieldnames=columns, delimiter="\t", lineterminator="\n")
    writer.writeheader()
    writer.writerows(plan_rows)
summary = {
    "dataset_id": "google_alphaearth_satellite_embeddings_i8",
    "source_count": len(source_rows),
    "planned_samples": len(plan_rows),
    "planned_decoded_bytes": len(plan_rows) * 1024 * 1024,
    "planned_compressed_bytes": sum(int(row["byte_count"]) for row in plan_rows),
    "selection_policy": "first qualifying fixed interior tile; same spatial tile across all 64 separate embedding axes",
    "sources": source_summaries,
}
(plan_path.parent / "download_plan.json").write_text(
    json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
)
print(json.dumps(summary, indent=2, sort_keys=True))
PY

export CHUNK_DIR JOBS PLAN UA
python3 - <<'PY'
from __future__ import annotations

import csv
from concurrent.futures import ThreadPoolExecutor, as_completed
import os
from pathlib import Path
import subprocess


plan = Path(os.environ["PLAN"])
download_dir = plan.parent
jobs = int(os.environ["JOBS"])
ua = os.environ["UA"]
rows = list(csv.DictReader(plan.open("r", encoding="utf-8", newline=""), delimiter="\t"))


def fetch(row: dict[str, str]) -> tuple[str, int, str]:
    output = download_dir / row["chunk_path"]
    output.parent.mkdir(parents=True, exist_ok=True)
    expected = int(row["byte_count"])
    if output.is_file() and output.stat().st_size == expected and os.environ.get("FORCE_DOWNLOAD", "0") != "1":
        return row["sample_id"], expected, "cache_hit"
    part = output.with_suffix(output.suffix + ".part")
    part.unlink(missing_ok=True)
    start = int(row["byte_offset"])
    end = start + expected - 1
    url = f"{row['url']}?generation={row['generation']}"
    completed = subprocess.run(
        [
            "curl", "--globoff", "--fail", "--silent", "--show-error", "--location",
            "--retry", "5", "--retry-delay", "3", "--retry-all-errors",
            "--connect-timeout", "30", "--speed-limit", "1024", "--speed-time", "120",
            "--max-time", "900", "--max-filesize", str(expected + 1),
            "--range", f"{start}-{end}", "--user-agent", ua,
            "--output", str(part), url,
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    if completed.returncode != 0:
        part.unlink(missing_ok=True)
        raise RuntimeError(
            f"curl failed sample={row['sample_id']}: "
            f"{completed.stderr.decode('utf-8', errors='replace').strip()}"
        )
    actual = part.stat().st_size
    if actual != expected:
        part.unlink(missing_ok=True)
        raise RuntimeError(f"range size mismatch sample={row['sample_id']}: {actual} != {expected}")
    part.replace(output)
    return row["sample_id"], expected, "fetched"


first_id, first_size, first_status = fetch(rows[0])
first_chunk = download_dir / rows[0]["chunk_path"]
decoded = subprocess.run(
    ["zstd", "-q", "-d", "-c", str(first_chunk)],
    check=False,
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
)
expected_decoded = int(rows[0]["tile_width"]) * int(rows[0]["tile_length"])
if decoded.returncode != 0 or len(decoded.stdout) != expected_decoded:
    raise RuntimeError(
        f"early Zstandard decode failed sample={first_id}: returncode={decoded.returncode} "
        f"decoded_bytes={len(decoded.stdout)} expected={expected_decoded} "
        f"stderr={decoded.stderr.decode('utf-8', errors='replace').strip()}"
    )
print(f"chunk {first_status} sample={first_id} bytes={first_size} early_decode_bytes={len(decoded.stdout)}")

total = first_size
with ThreadPoolExecutor(max_workers=jobs) as pool:
    futures = [pool.submit(fetch, row) for row in rows[1:]]
    for completed_count, future in enumerate(as_completed(futures), 1):
        sample_id, size, status = future.result()
        total += size
        print(f"chunk {status} sample={sample_id} bytes={size} progress={completed_count + 1}/{len(rows)}")
print(f"range chunks ready samples={len(rows)} compressed_bytes={total}")
PY

echo "[$(date -Is)] download done dataset=$DATASET_ID"
