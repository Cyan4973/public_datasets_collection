#!/usr/bin/env bash
set -euo pipefail
ROOT_DIR=$(cd "$(dirname "$0")/../.." && pwd)
DATA_DIR=${DATA_DIR:-"$ROOT_DIR/.data"}
DATASET_ID=opendota_pro_matches
DOWNLOAD_DIR="$DATA_DIR/downloads/$DATASET_ID"
FILTERED_DIR="$DATA_DIR/filtered/$DATASET_ID"
SAMPLES_DIR="$DATA_DIR/samples/$DATASET_ID"
INDEX_DIR="$DATA_DIR/index/$DATASET_ID"
LOG_DIR="$DATA_DIR/logs/$DATASET_ID"
mkdir -p "$FILTERED_DIR" "$SAMPLES_DIR" "$INDEX_DIR" "$LOG_DIR"
TS=$(date +%Y%m%d_%H%M%S)
LOG_FILE="$LOG_DIR/build.$TS.log"
LATEST_LOG="$LOG_DIR/build.latest.log"
exec > >(tee "$LOG_FILE") 2>&1
python3 - <<'PY' "$DOWNLOAD_DIR/opendota_pro_matches.json" "$FILTERED_DIR" "$SAMPLES_DIR" "$INDEX_DIR"
import json, os, struct, sys
src, filtered_dir, samples_dir, index_dir = sys.argv[1:5]
rows=json.load(open(src))
series={
  'match_id_u64':('Q',[],'uint',64),
  'duration_u32':('I',[],'uint',32),
  'start_time_u32':('I',[],'uint',32),
  'radiant_team_id_u32':('I',[],'uint',32),
  'dire_team_id_u32':('I',[],'uint',32),
  'league_id_u32':('I',[],'uint',32),
  'series_id_u32':('I',[],'uint',32),
  'series_type_u8':('B',[],'uint',8),
  'radiant_score_u16':('H',[],'uint',16),
  'dire_score_u16':('H',[],'uint',16),
  'radiant_win_u8':('B',[],'uint',8),
  'version_u16':('H',[],'uint',16),
}
kept=0
for r in rows:
    req=['match_id','duration','start_time','series_type','radiant_score','dire_score','radiant_win','version']
    if any(k not in r or r[k] is None for k in req):
        continue
    series['match_id_u64'][1].append(int(r['match_id']))
    series['duration_u32'][1].append(int(r['duration']))
    series['start_time_u32'][1].append(int(r['start_time']))
    series['radiant_team_id_u32'][1].append(int(r.get('radiant_team_id') or 0))
    series['dire_team_id_u32'][1].append(int(r.get('dire_team_id') or 0))
    series['league_id_u32'][1].append(int(r.get('leagueid') or 0))
    series['series_id_u32'][1].append(int(r.get('series_id') or 0))
    series['series_type_u8'][1].append(int(r['series_type']))
    series['radiant_score_u16'][1].append(int(r['radiant_score']))
    series['dire_score_u16'][1].append(int(r['dire_score']))
    series['radiant_win_u8'][1].append(1 if r['radiant_win'] else 0)
    series['version_u16'][1].append(int(r['version']))
    kept += 1
os.makedirs(index_dir, exist_ok=True)
index_path=os.path.join(index_dir,'samples.jsonl')
with open(index_path,'w',encoding='utf-8') as idx:
    for sid,(fmt,vals,nk,bw) in series.items():
        sdir=os.path.join(samples_dir,sid)
        os.makedirs(sdir, exist_ok=True)
        out=os.path.join(sdir,'matches.bin')
        with open(out,'wb') as f:
            for v in vals:
                f.write(struct.pack('<'+fmt, v))
        idx.write(json.dumps({
            'dataset_id':'opendota_pro_matches','series_id':sid,'sample_path':out,
            'numeric_kind':nk,'bit_width':bw,'endianness':'little','element_size_bytes':bw//8,
            'sample_size_bytes':os.path.getsize(out),'value_count':len(vals)})+'\n')
with open(os.path.join(filtered_dir,'ingest_stats.json'),'w',encoding='utf-8') as f:
    json.dump({'rows_total':len(rows),'rows_kept':kept,'rows_skipped':len(rows)-kept,'sample_rows':len(series)}, f)
print('[%s] build done dataset=opendota_pro_matches' % __import__('datetime').datetime.now().astimezone().isoformat(timespec='seconds'))
PY
cp "$LOG_FILE" "$LATEST_LOG" 2>/dev/null || true
