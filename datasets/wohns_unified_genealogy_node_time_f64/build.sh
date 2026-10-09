#!/usr/bin/env bash
# Decode the tskit node-table `time` column (zarr <f8, blosc/zstd/byteshuffle)
# of every chromosome-arm tree sequence and emit it unchanged as one raw
# little-endian float64 sample per arm, in native node order.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="wohns_unified_genealogy_node_time_f64"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
mkdir -p "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/build.$RUN_TS.log" "$LOG_DIR/build.latest.log") 2>&1
echo "[$(date -Is)] build start dataset=$DATASET_ID"

command -v "${ZSTD_BIN:-zstd}" >/dev/null || { echo "FATAL: zstd CLI not found" >&2; exit 1; }
export DATA_ROOT RECIPE_DIR DATASET_ID
export PYTHONDONTWRITEBYTECODE=1
python3 "$RECIPE_DIR/scripts/blosc1.py" selftest
python3 - <<'PY'
from __future__ import annotations

import array
import hashlib
import json
import math
import os
import shutil
import sys
from pathlib import Path

recipe_dir = Path(os.environ["RECIPE_DIR"])
sys.path.insert(0, str(recipe_dir / "scripts"))
import blosc1  # noqa: E402
import tsz_nodes_time as tsz  # noqa: E402

DATASET_ID = os.environ["DATASET_ID"]
SERIES_ID = "tsdate_node_time_generations_f64"
EXPECTED_ARMS = 39
EXPECTED_SAMPLE_NODES = 7508  # sample (haploid genome) nodes, identical in every arm
MAX_PLAUSIBLE_GENERATIONS = 1.0e6
MIN_DISTINCT = 10_000
RECORD_ID = 5495535

if sys.byteorder != "little":
    raise SystemExit("FATAL: little-endian host assumed")

data_root = Path(os.environ["DATA_ROOT"])
dl_dir = data_root / "downloads" / DATASET_ID
out_dir = data_root / "samples" / DATASET_ID / SERIES_ID
index_dir = data_root / "index" / DATASET_ID
filter_dir = data_root / "filtered" / DATASET_ID
resources = tsz.load_resources(recipe_dir / "resources.tsv")
if len(resources) != EXPECTED_ARMS:
    raise SystemExit(f"FATAL: resources.tsv has {len(resources)} arms")

if out_dir.exists():
    shutil.rmtree(out_dir)
out_dir.mkdir(parents=True)
index_dir.mkdir(parents=True, exist_ok=True)
filter_dir.mkdir(parents=True, exist_ok=True)

rows = []
seen = set()
for arm, res in resources.items():
    cd_path = dl_dir / f"{arm}.cd.bin"
    range_path = dl_dir / f"{arm}.nodes_time.bin"
    if not cd_path.is_file() or not range_path.is_file():
        raise SystemExit(f"FATAL: missing local inputs for {arm} (run download.sh first)")
    try:
        tsz.parse_cd(cd_path.read_bytes(), res)
        meta, frame = tsz.parse_range(range_path.read_bytes(), res)
        raw, header = blosc1.decode(frame)
    except (tsz.TszError, blosc1.BloscError) as exc:
        raise SystemExit(f"FATAL: {arm}: {exc}")
    n = meta["shape"][0]
    if len(raw) != n * 8 or header["nbytes"] != n * 8:
        raise SystemExit(f"FATAL: {arm}: decoded {len(raw)} bytes for shape {n}")
    vals = array.array("d")
    vals.frombytes(raw)
    bad = sum(1 for v in vals if not math.isfinite(v) or v < 0.0)
    if bad:
        raise SystemExit(f"FATAL: {arm}: {bad} non-finite or negative node times")
    lead = 0
    while lead < n and vals[lead] == 0.0:
        lead += 1
    zeros = vals.count(0.0)
    if lead != EXPECTED_SAMPLE_NODES or zeros != lead:
        raise SystemExit(f"FATAL: {arm}: leading zero run {lead}, total zeros {zeros}, "
                         f"expected exactly {EXPECTED_SAMPLE_NODES} leading sample-node zeros")
    vmax = max(vals)
    nonzero_min = min(vals[lead:])
    distinct = len(set(vals))
    if vmax > MAX_PLAUSIBLE_GENERATIONS or distinct < MIN_DISTINCT:
        raise SystemExit(f"FATAL: {arm}: implausible/degenerate max={vmax} distinct={distinct}")
    digest = hashlib.sha256(raw).hexdigest()
    if digest in seen:
        raise SystemExit(f"FATAL: {arm}: duplicate sample content")
    seen.add(digest)
    out = out_dir / f"hgdp_tgp_sgdp_{arm}_node_time_f64le.bin"
    out.write_bytes(raw)
    rows.append({
        "dataset_id": DATASET_ID,
        "series_id": SERIES_ID,
        "role": "primary",
        "sample_path": out.relative_to(data_root).as_posix(),
        "numeric_kind": "float",
        "bit_width": 64,
        "endianness": "little",
        "element_size_bytes": 8,
        "sample_size_bytes": len(raw),
        "value_count": n,
        "sample_format": "raw homogeneous little-endian float64 vector in native tskit node-ID order",
        "sample_rank": 1,
        "sample_shape": [n],
        "sample_axes": ["tskit_node_id"],
        "natural_record_kind": "chromosome_arm_tree_sequence_node_table",
        "source_format": "tskit_zarr_v2_zipstore_trees_tsz_blosc_zstd_byteshuffle_f8",
        "source_field": "nodes/time",
        "units": "generations_before_present",
        "arm": arm,
        "chromosome": int(arm[3:].split("_")[0]),
        "arm_side": arm[-1],
        "source_url": f"https://zenodo.org/api/records/{RECORD_ID}/files/{res['file_key']}/content",
        "source_file_md5": res["file_md5"],
        "source_member_crc32": res["chunk_crc32"],
        "blosc_flags": header["flags"],
        "blosc_blocksize": header["blocksize"],
        "blosc_cbytes": header["cbytes"],
        "missing_value": "none; every node has a finite non-negative time",
        "sample_node_zero_count": lead,
        "min_value_stored": 0.0,
        "min_nonzero_value_stored": nonzero_min,
        "max_value_stored": vmax,
        "mean_value": sum(vals) / n,
        "distinct_values": distinct,
        "sha256": digest,
    })
    print(f"built arm={arm} nodes={n} zeros={lead} min_nonzero={nonzero_min:.6g} max={vmax:.6f} "
          f"distinct={distinct} sha256={digest[:16]}", flush=True)

with (index_dir / "samples.jsonl").open("w", encoding="utf-8") as fh:
    for r in rows:
        fh.write(json.dumps(r, sort_keys=True) + "\n")
total_values = sum(r["value_count"] for r in rows)
total_bytes = sum(r["sample_size_bytes"] for r in rows)
counts = sorted(r["value_count"] for r in rows)
summary = {
    "dataset_id": DATASET_ID,
    "series_id": SERIES_ID,
    "samples": len(rows),
    "primary_values": total_values,
    "primary_sample_bytes": total_bytes,
    "median_sample_values": counts[len(counts) // 2],
    "min_sample_values": counts[0],
    "max_sample_values": counts[-1],
    "sample_node_zero_share": round(sum(r["sample_node_zero_count"] for r in rows) / total_values, 6),
    "max_value_stored": max(r["max_value_stored"] for r in rows),
    "aggregate_sha256": hashlib.sha256("".join(r["sha256"] for r in rows).encode()).hexdigest(),
}
(filter_dir / "ingest_stats.json").write_text(json.dumps(summary, indent=1, sort_keys=True) + "\n", encoding="utf-8")
print(f"built dataset={DATASET_ID} samples={len(rows)} values={total_values} bytes={total_bytes} "
      f"median_values={summary['median_sample_values']} zero_share={summary['sample_node_zero_share']}")
PY
echo "[$(date -Is)] build done dataset=$DATASET_ID"
