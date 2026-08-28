#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
CANDIDATE_ID="hf_timm_resnet18_conv_f32"
MODEL_ID="timm/resnet18.a1_in1k"
OUT_DIR="$REPO_ROOT/$DATA_DIR/discovery/$CANDIDATE_ID"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$CANDIDATE_ID"
API_JSON="$OUT_DIR/model_api.json"
RESOLVED_JSON="$OUT_DIR/resolved_source.json"
README_FILE="$OUT_DIR/model_card.md"
PREFIX_FILE="$OUT_DIR/model.safetensors.header-prefix"
HEADERS_FILE="$OUT_DIR/model.safetensors.headers"

mkdir -p "$OUT_DIR" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/discover.$RUN_TS.log" "$LOG_DIR/discover.latest.log") 2>&1
echo "[$(date -Is)] metadata discovery start candidate=$CANDIDATE_ID model=$MODEL_ID"

curl --fail --silent --show-error --location --retry 5 --retry-delay 2 \
  --retry-all-errors --max-time 180 --max-filesize 5000000 \
  --user-agent "openzl-public-datasets-resnet18-f32-discovery/1.0" \
  --header "Accept: application/json" \
  --output "$API_JSON.part" \
  "https://huggingface.co/api/models/$MODEL_ID?blobs=true"
mv "$API_JSON.part" "$API_JSON"

export API_JSON MODEL_ID RESOLVED_JSON
python3 - <<'PY'
from __future__ import annotations

import json
import os
from pathlib import Path
import re


api_path = Path(os.environ["API_JSON"])
model_id = os.environ["MODEL_ID"]
resolved_path = Path(os.environ["RESOLVED_JSON"])
try:
    model = json.loads(api_path.read_text(encoding="utf-8"))
except Exception as exc:
    raise SystemExit(f"invalid Hugging Face model API JSON: {exc}") from exc
if not isinstance(model, dict) or str(model.get("id") or "") != model_id:
    raise SystemExit("Hugging Face API returned the wrong model identity")
if bool(model.get("private")) or bool(model.get("disabled")) or bool(model.get("gated")):
    raise SystemExit("model repository is private, disabled, or gated")

revision = str(model.get("sha") or "").strip()
if not re.fullmatch(r"[0-9a-f]{40}", revision):
    raise SystemExit(f"invalid resolved repository revision: {revision!r}")
card = model.get("cardData")
if not isinstance(card, dict):
    raise SystemExit("model API omitted cardData")
license_id = str(card.get("license") or "").strip().lower()
if license_id != "apache-2.0":
    raise SystemExit(f"model card API license is not apache-2.0: {license_id!r}")

siblings = model.get("siblings")
if not isinstance(siblings, list):
    raise SystemExit("model API omitted sibling inventory")
matches = [
    row
    for row in siblings
    if isinstance(row, dict) and row.get("rfilename") == "model.safetensors"
]
if len(matches) != 1:
    raise SystemExit(f"expected one model.safetensors entry, found {len(matches)}")
source = matches[0]
lfs = source.get("lfs")
if not isinstance(lfs, dict):
    raise SystemExit("model.safetensors is not exposed as a pinned LFS object")
size = int(lfs.get("size") or source.get("size") or 0)
sha256 = str(lfs.get("sha256") or "").strip().lower()
if not 10_000_000 <= size <= 200_000_000:
    raise SystemExit(f"checkpoint size outside discovery bounds: {size}")
if not re.fullmatch(r"[0-9a-f]{64}", sha256):
    raise SystemExit("model.safetensors LFS SHA-256 is missing or malformed")

resolved = {
    "candidate_id": "hf_timm_resnet18_conv_f32",
    "model_id": model_id,
    "revision": revision,
    "license": "apache-2.0",
    "model_card_url": f"https://huggingface.co/{model_id}/raw/{revision}/README.md",
    "model_url": f"https://huggingface.co/{model_id}/resolve/{revision}/model.safetensors",
    "model_bytes": size,
    "model_sha256": sha256,
}
resolved_path.write_text(
    json.dumps(resolved, indent=2, sort_keys=True) + "\n", encoding="utf-8"
)
print(
    f"api_validation=ok revision={revision} license=apache-2.0 "
    f"model_bytes={size} model_sha256={sha256}"
)
PY

REVISION="$(jq -r '.revision' "$RESOLVED_JSON")"
MODEL_URL="$(jq -r '.model_url' "$RESOLVED_JSON")"
MODEL_BYTES="$(jq -r '.model_bytes' "$RESOLVED_JSON")"
MODEL_CARD_URL="$(jq -r '.model_card_url' "$RESOLVED_JSON")"

curl --fail --silent --show-error --location --retry 5 --retry-delay 2 \
  --retry-all-errors --max-time 180 --max-filesize 5000000 \
  --user-agent "openzl-public-datasets-resnet18-f32-discovery/1.0" \
  --output "$README_FILE.part" "$MODEL_CARD_URL"
mv "$README_FILE.part" "$README_FILE"

export README_FILE REVISION
python3 - <<'PY'
from __future__ import annotations

import os
from pathlib import Path
import re


text = Path(os.environ["README_FILE"]).read_text(encoding="utf-8", errors="strict")
frontmatter = text.split("---", 2)
if len(frontmatter) < 3:
    raise SystemExit("pinned model card has no YAML front matter")
if not re.search(r"(?mi)^license:\s*apache-2\.0\s*$", frontmatter[1]):
    raise SystemExit("pinned model card does not declare license: apache-2.0")
if "resnet18" not in text.lower() or "image classification" not in text.lower():
    raise SystemExit("pinned model card identity or task text is missing")
print(
    f"model_card_validation=ok revision={os.environ['REVISION']} "
    "license=apache-2.0 task=image-classification"
)
PY

rm -f "$PREFIX_FILE.part" "$HEADERS_FILE.part"
curl --fail --silent --show-error --location --retry 5 --retry-delay 2 \
  --retry-all-errors --max-time 180 --max-filesize 1048576 \
  --user-agent "openzl-public-datasets-resnet18-f32-discovery/1.0" \
  --header "Range: bytes=0-1048575" \
  --dump-header "$HEADERS_FILE.part" \
  --output "$PREFIX_FILE.part" "$MODEL_URL"
mv "$PREFIX_FILE.part" "$PREFIX_FILE"
mv "$HEADERS_FILE.part" "$HEADERS_FILE"

export MODEL_BYTES MODEL_URL PREFIX_FILE OUT_DIR RESOLVED_JSON
python3 - <<'PY'
from __future__ import annotations

import csv
import json
import math
import os
from pathlib import Path
import statistics
import struct


model_bytes = int(os.environ["MODEL_BYTES"])
prefix_path = Path(os.environ["PREFIX_FILE"])
out_dir = Path(os.environ["OUT_DIR"])
resolved_path = Path(os.environ["RESOLVED_JSON"])
prefix = prefix_path.read_bytes()
if not 8 <= len(prefix) <= 1_048_576:
    raise SystemExit(f"unexpected range-response size: {len(prefix)}")
header_length = struct.unpack_from("<Q", prefix, 0)[0]
if not 2 <= header_length <= 1_000_000 or 8 + header_length > len(prefix):
    raise SystemExit(
        f"SafeTensors header does not fit bounded prefix: header={header_length} prefix={len(prefix)}"
    )
try:
    header = json.loads(prefix[8 : 8 + header_length].rstrip(b" ").decode("utf-8"))
except Exception as exc:
    raise SystemExit(f"invalid SafeTensors header JSON: {exc}") from exc
if not isinstance(header, dict):
    raise SystemExit("SafeTensors header is not an object")

data_bytes = model_bytes - 8 - header_length
tensors: list[dict[str, object]] = []
all_spans: list[tuple[int, int, str]] = []
for name, metadata in header.items():
    if name == "__metadata__":
        continue
    if not isinstance(metadata, dict):
        raise SystemExit(f"invalid tensor metadata: {name}")
    dtype = str(metadata.get("dtype") or "")
    shape = metadata.get("shape")
    offsets = metadata.get("data_offsets")
    if not isinstance(shape, list) or not all(isinstance(value, int) and value >= 0 for value in shape):
        raise SystemExit(f"invalid tensor shape: {name}")
    if not isinstance(offsets, list) or len(offsets) != 2 or not all(isinstance(value, int) for value in offsets):
        raise SystemExit(f"invalid tensor offsets: {name}")
    start, end = offsets
    if start < 0 or end <= start or end > data_bytes:
        raise SystemExit(f"tensor offsets outside payload: {name}")
    all_spans.append((start, end, name))
    values = math.prod(shape)
    if dtype == "F32" and len(shape) == 4:
        if values < 1_000 or end - start != values * 4:
            raise SystemExit(f"rank-4 F32 tensor has invalid size or falls below floor: {name}")
        tensors.append(
            {
                "tensor_name": name,
                "dtype": dtype,
                "shape": "x".join(str(value) for value in shape),
                "output_channels": shape[0],
                "input_channels": shape[1],
                "kernel_height": shape[2],
                "kernel_width": shape[3],
                "value_count": values,
                "payload_bytes": end - start,
                "data_offset_start": start,
                "data_offset_end": end,
            }
        )

ordered = sorted(all_spans)
cursor = 0
for start, end, name in ordered:
    if start != cursor:
        raise SystemExit(f"SafeTensors payload has a gap or overlap before {name}: {cursor} != {start}")
    cursor = end
if cursor != data_bytes:
    raise SystemExit(f"SafeTensors payload coverage mismatch: {cursor} != {data_bytes}")
if len(tensors) < 12:
    raise SystemExit(f"insufficient rank-4 F32 kernel tensors: {len(tensors)}")

tensors.sort(key=lambda row: (int(row["data_offset_start"]), str(row["tensor_name"])))
columns = (
    "tensor_name",
    "dtype",
    "shape",
    "output_channels",
    "input_channels",
    "kernel_height",
    "kernel_width",
    "value_count",
    "payload_bytes",
    "data_offset_start",
    "data_offset_end",
)
with (out_dir / "candidate_tensors.tsv").open("w", encoding="utf-8", newline="") as handle:
    writer = csv.DictWriter(handle, fieldnames=columns, delimiter="\t", lineterminator="\n")
    writer.writeheader()
    writer.writerows(tensors)

counts = sorted(int(row["value_count"]) for row in tensors)
summary = {
    **json.loads(resolved_path.read_text(encoding="utf-8")),
    "safetensors_header_bytes": header_length,
    "safetensors_payload_bytes": data_bytes,
    "all_tensor_count": len(all_spans),
    "rank4_f32_tensor_count": len(tensors),
    "rank4_f32_values": sum(counts),
    "rank4_f32_bytes": sum(int(row["payload_bytes"]) for row in tensors),
    "rank4_f32_median_values": statistics.median(counts),
    "rank4_f32_min_values": counts[0],
    "rank4_f32_max_values": counts[-1],
    "kernel_shapes": sorted(
        {f"{row['kernel_height']}x{row['kernel_width']}" for row in tensors}
    ),
    "checkpoint_payload_downloaded": False,
    "header_prefix_bytes_downloaded": len(prefix),
    "next_step": "download exact pinned SafeTensors checkpoint and validate selected byte ranges",
}
(out_dir / "summary.json").write_text(
    json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
)
print(json.dumps(summary, indent=2, sort_keys=True))
for row in tensors:
    print(
        f"tensor name={row['tensor_name']} shape={row['shape']} "
        f"values={row['value_count']} bytes={row['payload_bytes']}"
    )
PY

echo "[$(date -Is)] metadata discovery done candidate=$CANDIDATE_ID"
