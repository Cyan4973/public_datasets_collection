#!/usr/bin/env bash
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="coinpaprika_tickers"
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
export REPO_ROOT DATA_DIR DOWNLOAD_DIR FILTER_DIR INDEX_DIR SAMPLES_DIR
python3 - <<'PY'
from __future__ import annotations
import json, os, shutil, struct
from pathlib import Path
repo_root=Path(os.environ['REPO_ROOT']); data_root=repo_root/os.environ['DATA_DIR']
download_dir=Path(os.environ['DOWNLOAD_DIR']); filter_dir=Path(os.environ['FILTER_DIR']); index_dir=Path(os.environ['INDEX_DIR']); samples_dir=Path(os.environ['SAMPLES_DIR'])
obj=json.load(open(download_dir/"coinpaprika_tickers.json",encoding='utf-8'))
items=obj
meta={
    "coinpaprika_rank": ("uint", 16, "H"),
    "coinpaprika_price_usd": ("float", 64, "d"),
    "coinpaprika_market_cap_usd": ("float", 64, "d"),
    "coinpaprika_volume_24h_usd": ("float", 64, "d"),
    "coinpaprika_volume_24h_change_pct_f64": ("float", 64, "d"),
    "coinpaprika_market_cap_change_24h_pct_f64": ("float", 64, "d"),
    "coinpaprika_percent_change_7d_f64": ("float", 64, "d"),
    "coinpaprika_ath_price_usd_f64": ("float", 64, "d"),
}
vals={sid:[] for sid in meta}
skipped=0
for sid in vals:
    d=samples_dir/sid
    if d.exists(): shutil.rmtree(d)
    d.mkdir(parents=True, exist_ok=True)
for row in items:
    try:
        usd = row["quotes"]["USD"]
        vals["coinpaprika_rank"].append(int(row["rank"]))
        vals["coinpaprika_price_usd"].append(float(usd["price"]))
        vals["coinpaprika_market_cap_usd"].append(float(usd["market_cap"]))
        vals["coinpaprika_volume_24h_usd"].append(float(usd["volume_24h"]))
        vals["coinpaprika_volume_24h_change_pct_f64"].append(float(usd["volume_24h_change_24h"]))
        vals["coinpaprika_market_cap_change_24h_pct_f64"].append(float(usd["market_cap_change_24h"]))
        vals["coinpaprika_percent_change_7d_f64"].append(float(usd["percent_change_7d"]))
        vals["coinpaprika_ath_price_usd_f64"].append(float(usd["ath_price"]))
    except Exception:
        skipped += 1
rows=[]
for sid,(kind,bits,code) in meta.items():
    values=vals[sid]
    out=samples_dir/sid/f"{sid}_{kind}{bits}_n{len(values):06d}.bin"
    with out.open('wb') as fh:
        fh.write(struct.pack('<' + code*len(values), *values))
    rows.append({"dataset_id":"coinpaprika_tickers","series_id":sid,"sample_path":out.relative_to(data_root).as_posix(),"numeric_kind":kind,"bit_width":bits,"endianness":"little","element_size_bytes":bits//8,"sample_size_bytes":out.stat().st_size,"value_count":len(values)})
if len({row["value_count"] for row in rows}) != 1:
    raise SystemExit("series length mismatch")
if sum(row["value_count"] for row in rows) < 10_000 and sum(row["sample_size_bytes"] for row in rows) < 102_400:
    raise SystemExit("below aggregate floor")
for sid, values in vals.items():
    if min(values) == max(values):
        raise SystemExit(f"constant sample: {sid}")
(filter_dir/'ingest_stats.json').write_text(json.dumps({"dataset_id":"coinpaprika_tickers","rows_total":len(items),"rows_skipped":skipped,"primary_values":sum(row["value_count"] for row in rows),"primary_sample_bytes":sum(row["sample_size_bytes"] for row in rows)}, indent=2, sort_keys=True) + '\n', encoding='utf-8')
with (index_dir/'samples.jsonl').open('w', encoding='utf-8') as fh:
    for row in rows:
        fh.write(json.dumps(row, sort_keys=True) + '\n')
PY
echo "[$(date -Is)] build done dataset=$DATASET_ID"
