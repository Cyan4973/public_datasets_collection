#!/usr/bin/env bash
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
ID="landsat_scene_cloud_cover_f64"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$ID"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$ID"
FILTER_DIR="$REPO_ROOT/$DATA_DIR/filtered/$ID"
INDEX_DIR="$REPO_ROOT/$DATA_DIR/index/$ID"
SAMPLES_DIR="$REPO_ROOT/$DATA_DIR/samples/$ID"
mkdir -p "$LOG_DIR" "$DOWNLOAD_DIR" "$FILTER_DIR" "$INDEX_DIR" "$SAMPLES_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/build.$RUN_TS.log" "$LOG_DIR/build.latest.log") 2>&1
echo "[$(date -Is)] build start $ID"
export REPO_ROOT DATA_DIR DOWNLOAD_DIR FILTER_DIR INDEX_DIR SAMPLES_DIR
python3 - <<'PY'
from pathlib import Path
import os, json, struct, gzip, math, csv, shutil, statistics
repo=Path(os.environ["REPO_ROOT"])
data_root=repo/Path(os.environ["DATA_DIR"])
dl=Path(os.environ["DOWNLOAD_DIR"])
filt=Path(os.environ["FILTER_DIR"])
idx=Path(os.environ["INDEX_DIR"])
samp=Path(os.environ["SAMPLES_DIR"])
if samp.exists():
    shutil.rmtree(samp)
(samp/"cloud_cover_f64").mkdir(parents=True, exist_ok=True)
filt.mkdir(parents=True, exist_ok=True)
idx.mkdir(parents=True, exist_ok=True)
src=dl/"index.csv.gz"
if not src.exists():
    raise SystemExit("missing index.csv.gz")
vals=[]
with gzip.open(src,'rt',errors='replace',newline='') as fh:
    reader=csv.DictReader(fh)
    for row in reader:
        raw=row.get("CLOUD_COVER","")
        if raw=="" : continue
        try:
            v=float(raw)
        except: continue
        if not math.isfinite(v): continue
        if v<0 or v>100: continue
        vals.append(v)
        if len(vals)>=5000000:  # cap for test
            break
if len(vals)<1000 or len(set(vals))<=1:
    raise SystemExit(f"too few or constant {len(vals)}")
out=samp/"cloud_cover_f64"/f"landsat_cloud_cover_f64_n{len(vals):07d}.bin"
out.write_bytes(struct.pack("<"+"d"*len(vals),*vals))
size=out.stat().st_size
row={
    "dataset_id":"landsat_scene_cloud_cover_f64",
    "series_id":"cloud_cover_f64",
    "role":"primary",
    "sample_path":str(out.relative_to(data_root)),
    "numeric_kind":"float",
    "bit_width":64,
    "endianness":"little",
    "element_size_bytes":8,
    "sample_size_bytes":size,
    "value_count":len(vals),
    "sample_format":"raw homogeneous float64 cloud cover",
    "sample_geometry":"table_column",
    "sample_rank":1,
    "sample_shape":[len(vals)],
    "sample_axes":["scene"],
    "natural_record_kind":"landsat_scene_cloud_cover_column",
    "source_file":str(src.relative_to(dl)),
    "source_field":"CLOUD_COVER",
    "min":min(vals),
    "max":max(vals),
}
with (idx/"samples.jsonl").open("w") as fh:
    fh.write(json.dumps(row,sort_keys=True)+"\n")
(filt/"ingest_stats.json").write_text(json.dumps({"dataset_id":"landsat_scene_cloud_cover_f64","primary_samples":1,"primary_values":len(vals),"primary_bytes":size,"median_values":len(vals)},indent=2,sort_keys=True)+"\n")
print(f"built values={len(vals)} bytes={size}")
PY
echo "[$(date -Is)] build done $ID"
