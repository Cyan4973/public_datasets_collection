#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="smollm2_135m_q8_gguf_weights"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
FILTER_DIR="$REPO_ROOT/$DATA_DIR/filtered/$DATASET_ID"
INDEX_DIR="$REPO_ROOT/$DATA_DIR/index/$DATASET_ID"
SAMPLES_DIR="$REPO_ROOT/$DATA_DIR/samples/$DATASET_ID"
mkdir -p "$LOG_DIR" "$DOWNLOAD_DIR" "$FILTER_DIR" "$INDEX_DIR" "$SAMPLES_DIR"

RUN_TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/build.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/build.latest.log"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1

echo "[$(date -Is)] build start dataset=$DATASET_ID"
MIN_RECORDS="${GGUF_MIN_RECORDS:-1000}"
export REPO_ROOT DATA_DIR DOWNLOAD_DIR FILTER_DIR INDEX_DIR SAMPLES_DIR MIN_RECORDS
python3 - <<'PY'
from __future__ import annotations

import json
import os
import shutil
import struct
from collections import defaultdict
from pathlib import Path

repo_root = Path(os.environ["REPO_ROOT"])
data_root = repo_root / os.environ["DATA_DIR"]
gguf_path = Path(os.environ["DOWNLOAD_DIR"]) / "model.gguf"
filter_dir = Path(os.environ["FILTER_DIR"])
index_dir = Path(os.environ["INDEX_DIR"])
samples_dir = Path(os.environ["SAMPLES_DIR"])
min_records = int(os.environ["MIN_RECORDS"])

DATASET_ID = "smollm2_135m_q8_gguf_weights"
GGML_Q8_0 = 8
QK8_0 = 32
BLK = 2 + QK8_0  # fp16 scale + 32 int8
# metadata value types
T_STR, T_ARR = 8, 9
_FIX = {0: 1, 1: 1, 2: 2, 3: 2, 4: 4, 5: 4, 6: 4, 7: 1, 10: 8, 11: 8, 12: 8}

ROLE_TO_FAMILY = {
    "attn": "gguf_q8_attn",
    "mlp": "gguf_q8_mlp",
    "embed": "gguf_q8_embed",
}


class R:
    def __init__(self, b):
        self.b = b
        self.p = 0

    def take(self, n):
        v = self.b[self.p:self.p + n]
        if len(v) != n:
            raise EOFError("short read")
        self.p += n
        return v

    def u32(self):
        return struct.unpack('<I', self.take(4))[0]

    def u64(self):
        return struct.unpack('<Q', self.take(8))[0]

    def gstr(self):
        return self.take(self.u64()).decode('utf-8', 'replace')

    def skip(self, vt):
        if vt in _FIX:
            self.take(_FIX[vt])
        elif vt == T_STR:
            self.gstr()
        elif vt == T_ARR:
            et = self.u32()
            n = self.u64()
            for _ in range(n):
                self.skip(et)
        else:
            raise ValueError(f"unknown metadata value type {vt}")


def role_of(name):
    n = name.lower()
    if "attn" in n:
        return "attn"
    if "ffn" in n or "mlp" in n:
        return "mlp"
    if "embd" in n or "embed" in n or n == "output.weight" or "lm_head" in n:
        return "embed"
    return None


data = gguf_path.read_bytes()
r = R(data)
if r.take(4) != b"GGUF":
    raise SystemExit("not a GGUF file")
version = r.u32()
n_tensors = r.u64()
n_kv = r.u64()
alignment = 32
for _ in range(n_kv):
    k = r.gstr()
    vt = r.u32()
    if k == "general.alignment" and vt == 4:
        alignment = struct.unpack('<I', r.take(4))[0]
    else:
        r.skip(vt)

tensors = []
for _ in range(n_tensors):
    name = r.gstr()
    ndim = r.u32()
    dims = [r.u64() for _ in range(ndim)]
    ttype = r.u32()
    offset = r.u64()
    nelem = 1
    for d in dims:
        nelem *= d
    tensors.append((name, ttype, nelem, offset))

data_start = r.p
if data_start % alignment:
    data_start += alignment - (data_start % alignment)


def extract_int8(nelem, offset):
    nblk = nelem // QK8_0
    base = data_start + offset
    mv = memoryview(data)
    out = bytearray(nblk * QK8_0)
    for i in range(nblk):
        s = base + i * BLK + 2
        out[i * QK8_0:(i + 1) * QK8_0] = mv[s:s + QK8_0]
    return out


# Collect int8 values per family, one sample per Q8_0 tensor.
by_family = defaultdict(list)  # family -> list of (name, bytes)
skipped_type = 0
for name, ttype, nelem, offset in tensors:
    role = role_of(name)
    if role is None:
        continue
    if ttype != GGML_Q8_0:
        skipped_type += 1
        continue
    if nelem % QK8_0 != 0:
        continue
    payload = extract_int8(nelem, offset)
    by_family[ROLE_TO_FAMILY[role]].append((name, payload))

if samples_dir.exists():
    shutil.rmtree(samples_dir)
samples_dir.mkdir(parents=True, exist_ok=True)

index_rows = []
fam_summary = {}
for fam, items in by_family.items():
    qualifying = [(nm, p) for (nm, p) in items
                  if len(p) >= min_records and len(set(p)) > 1]
    if not qualifying:
        continue
    (samples_dir / fam).mkdir(parents=True, exist_ok=True)
    for nm, payload in qualifying:
        safe = nm.replace("/", "_").replace(".", "_")
        out = samples_dir / fam / f"{fam}_{safe}_n{len(payload):08d}.bin"
        out.write_bytes(payload)
        index_rows.append({
            "dataset_id": DATASET_ID,
            "series_id": fam,
            "role": "primary",
            "sample_path": out.relative_to(data_root).as_posix(),
            "numeric_kind": "int",
            "bit_width": 8,
            "endianness": "little",
            "element_size_bytes": 1,
            "sample_size_bytes": out.stat().st_size,
            "value_count": len(payload),
            "sample_geometry": "sequence",
            "sample_rank": 1,
            "tensor_name": nm,
            "natural_record_kind": "gguf_q8_0_tensor",
        })
    fam_summary[fam] = len(qualifying)

if not fam_summary:
    raise SystemExit(f"no family qualified (tensors={n_tensors}, skipped_non_q8={skipped_type})")

primary_values = sum(r2["value_count"] for r2 in index_rows)
primary_bytes = sum(r2["sample_size_bytes"] for r2 in index_rows)
counts = sorted(r2["value_count"] for r2 in index_rows)
median = counts[len(counts) // 2]
stats = {
    "dataset_id": DATASET_ID,
    "gguf_version": version,
    "alignment": alignment,
    "families": fam_summary,
    "samples": len(index_rows),
    "tensors_total": n_tensors,
    "skipped_non_q8_in_roles": skipped_type,
    "primary_values": primary_values,
    "primary_sample_bytes": primary_bytes,
    "median_value_count": median,
    "min_value_count": counts[0],
    "max_value_count": counts[-1],
}
(filter_dir / "ingest_stats.json").write_text(
    json.dumps(stats, indent=2, sort_keys=True) + "\n", encoding="utf-8")
with (index_dir / "samples.jsonl").open("w", encoding="utf-8") as fh:
    for row in sorted(index_rows, key=lambda r2: r2["sample_path"]):
        fh.write(json.dumps(row, sort_keys=True) + "\n")
print(
    f"built families={fam_summary} samples={len(index_rows)} "
    f"primary_values={primary_values} median={median} range=[{counts[0]},{counts[-1]}]")
PY
echo "[$(date -Is)] build done dataset=$DATASET_ID"
