#!/usr/bin/env bash
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
ID="covid19_google_mobility_f64"
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
import os, json, struct, math, csv, shutil, statistics
repo=Path(os.environ["REPO_ROOT"])
data_root=repo/Path(os.environ["DATA_DIR"])
dl=Path(os.environ["DOWNLOAD_DIR"])
filt=Path(os.environ["FILTER_DIR"])
idx=Path(os.environ["INDEX_DIR"])
samp=Path(os.environ["SAMPLES_DIR"])
if samp.exists():
    shutil.rmtree(samp)
samp.mkdir(parents=True, exist_ok=True)
filt.mkdir(parents=True, exist_ok=True)
idx.mkdir(parents=True, exist_ok=True)
src=dl/"mobility.csv"
if not src.exists():
    raise SystemExit("missing mobility.csv")
fields=["mobility_retail_and_recreation","mobility_grocery_and_pharmacy","mobility_parks","mobility_transit_stations","mobility_workplaces","mobility_residential"]
buffers={f:[] for f in fields}
rows_seen=0
with src.open('r',encoding='utf-8',errors='replace',newline='') as fh:
    reader=csv.DictReader(fh)
    for row in reader:
        rows_seen+=1
        for f in fields:
            raw=row.get(f,"")
            if raw=="" or raw is None:
                continue
            try:
                v=float(raw)
            except:
                continue
            if not math.isfinite(v):
                continue
            buffers[f].append(v)
# emit
total_bytes=0
index_rows=[]
for f in fields:
    vals=buffers[f]
    if len(vals)<1000 or len(set(vals))<=1:
        print(f"skip {f} {len(vals)}")
        continue
    series_id=f"covid19_{f.replace('mobility_','')}_f64"
    out_dir=samp/series_id
    out_dir.mkdir(parents=True, exist_ok=True)
    out=out_dir/f"{series_id}_n{len(vals):07d}.bin"
    out.write_bytes(struct.pack("<"+"d"*len(vals),*vals))
    size=out.stat().st_size
    total_bytes+=size
    index_rows.append({
        "dataset_id":"covid19_google_mobility_f64",
        "series_id":series_id,
        "role":"primary",
        "sample_path":str(out.relative_to(data_root)),
        "numeric_kind":"float",
        "bit_width":64,
        "endianness":"little",
        "element_size_bytes":8,
        "sample_size_bytes":size,
        "value_count":len(vals),
        "sample_format":"raw homogeneous float64 mobility time series",
        "sample_geometry":"table_column",
        "sample_rank":1,
        "sample_shape":[len(vals)],
        "sample_axes":["record"],
        "natural_record_kind":"covid19_mobility_column",
        "source_file":str(src.relative_to(dl)),
        "source_field":f,
        "min":min(vals),
        "max":max(vals),
    })
if not index_rows:
    raise SystemExit("no samples")
pv=sum(r["value_count"] for r in index_rows)
pb=sum(r["sample_size_bytes"] for r in index_rows)
med=statistics.median([r["value_count"] for r in index_rows])
if pv<10000 and pb<102400:
    raise SystemExit(f"below floor {pv}/{pb}")
if med<1000:
    raise SystemExit(f"median below floor {med}")
with (idx/"samples.jsonl").open("w") as fh:
    for r in sorted(index_rows,key=lambda x:x["sample_path"]):
        fh.write(json.dumps(r,sort_keys=True)+"\n")
(filt/"ingest_stats.json").write_text(json.dumps({"dataset_id":"covid19_google_mobility_f64","primary_samples":len(index_rows),"primary_values":pv,"primary_bytes":pb,"median_values":med,"rows_seen":rows_seen},indent=2,sort_keys=True)+"\n")
print(f"built samples={len(index_rows)} values={pv} bytes={pb} median={med} rows_seen={rows_seen}")
PY
echo "[$(date -Is)] build done $ID"
