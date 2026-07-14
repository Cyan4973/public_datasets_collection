#!/usr/bin/env bash
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="statlog_landsat_satellite_u8"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
EXTRACT_DIR="$REPO_ROOT/$DATA_DIR/extracted/$DATASET_ID"
FILTER_DIR="$REPO_ROOT/$DATA_DIR/filtered/$DATASET_ID"
INDEX_DIR="$REPO_ROOT/$DATA_DIR/index/$DATASET_ID"
SAMPLES_DIR="$REPO_ROOT/$DATA_DIR/samples/$DATASET_ID"
mkdir -p "$LOG_DIR" "$DOWNLOAD_DIR" "$EXTRACT_DIR" "$FILTER_DIR" "$INDEX_DIR" "$SAMPLES_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/build.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/build.latest.log"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1
echo "[$(date -Is)] build start dataset=$DATASET_ID"
export REPO_ROOT DATA_DIR EXTRACT_DIR FILTER_DIR INDEX_DIR SAMPLES_DIR
python3 - <<'PY'
import json, os, shutil
from pathlib import Path

repo = Path(os.environ["REPO_ROOT"]); data_dir = os.environ["DATA_DIR"]
extract = Path(os.environ["EXTRACT_DIR"]); filter_dir = Path(os.environ["FILTER_DIR"])
index_dir = Path(os.environ["INDEX_DIR"]); samples_dir = Path(os.environ["SAMPLES_DIR"])

# Each Statlog line is a 3x3 pixel neighbourhood: 36 attributes = 9 pixels x 4
# spectral bands, interleaved pixel-major (p0b0,p0b1,p0b2,p0b3, p1b0,...), plus a
# trailing class label. Band b occupies attribute positions b, b+4, ..., b+32.
# Each band is one coherent quantity (surface reflectance DN in that band), so it
# becomes one series; its nine per-pixel values are serialized in row order.
BANDS = [
    (0, "landsat_band_green_u8"),
    (1, "landsat_band_red_u8"),
    (2, "landsat_band_nir1_u8"),
    (3, "landsat_band_nir2_u8"),
]
# The upstream train/test files are the natural record boundary; each becomes its
# own sample per band (no concatenation across files).
SPLITS = [("trn", "sat.trn"), ("tst", "sat.tst")]

shutil.rmtree(samples_dir, ignore_errors=True)
filter_dir.mkdir(parents=True, exist_ok=True)
index_dir.mkdir(parents=True, exist_ok=True)

rows = []
inventory = []
for split_id, fname in SPLITS:
    src = extract / fname
    if not src.exists():
        raise SystemExit(f"missing source: {src}")
    band_bytes = {bi: bytearray() for bi, _ in BANDS}
    row_count = 0
    with src.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            toks = line.split()
            if len(toks) != 37:
                raise SystemExit(f"{fname}: unexpected row width {len(toks)}")
            vals = [int(t) for t in toks]
            attrs = vals[:36]
            if any(v < 0 or v > 255 for v in attrs):
                raise SystemExit(f"{fname}: spectral attribute outside 0..255")
            if not (1 <= vals[36] <= 7):
                raise SystemExit(f"{fname}: class label outside 1..7: {vals[36]}")
            for bi, _ in BANDS:
                for pos in range(bi, 36, 4):
                    band_bytes[bi].append(attrs[pos])
            row_count += 1
    if row_count == 0:
        raise SystemExit(f"{fname}: no rows parsed")
    inventory.append((split_id, row_count))
    for bi, sid in BANDS:
        data = bytes(band_bytes[bi])
        if not data:
            raise SystemExit(f"empty band sample: {sid} {split_id}")
        if min(data) == max(data):
            raise SystemExit(f"constant band sample: {sid} {split_id}")
        outdir = samples_dir / sid
        outdir.mkdir(parents=True, exist_ok=True)
        out = outdir / f"{split_id}.bin"
        out.write_bytes(data)
        rows.append({
            "dataset_id": "statlog_landsat_satellite_u8",
            "series_id": sid,
            "role": "primary",
            "split": split_id,
            "sample_path": str(out.relative_to(repo / data_dir)),
            "numeric_kind": "uint",
            "bit_width": 8,
            "endianness": "little",
            "element_size_bytes": 1,
            "sample_size_bytes": len(data),
            "value_count": len(data),
        })

(filter_dir / "inventory.tsv").write_text(
    "split\trow_count\n" + "".join(f"{s}\t{c}\n" for s, c in inventory),
    encoding="utf-8",
)
with (index_dir / "samples.jsonl").open("w", encoding="utf-8") as fh:
    for r in rows:
        fh.write(json.dumps(r, sort_keys=True) + "\n")
total = sum(r["value_count"] for r in rows)
print(f"wrote {len(rows)} samples, {total} primary u8 values; rows per split: {inventory}")
PY
echo "[$(date -Is)] build done dataset=$DATASET_ID"
