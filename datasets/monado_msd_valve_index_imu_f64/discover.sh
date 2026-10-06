#!/usr/bin/env bash
# Range-only discovery of every Valve Index sequence's <seq>/mav0/imu0/data.csv
# member in the pinned Hugging Face revision. Produces sources.all.tsv (49) and
# the in-scope candidate sources.tsv (30)
# (exact part file, local-header offset, header length, sizes, CRC-32) under
# $DATA_DIR/discovery/<id>/. The committed sources.tsv was generated this way.
# Only small metadata requests: the tree API, 128 KiB archive tails, a 1 MiB
# central-directory window per archive (full directory only as fallback) and
# 1 KiB at each local header. No member payload is fetched.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="monado_msd_valve_index_imu_f64"
REVISION="74c07d42d980c55775dd0edc06e58c486b848be1"
REPO_URL="https://huggingface.co/datasets/collabora/monado-slam-datasets"
TREE_URL="https://huggingface.co/api/datasets/collabora/monado-slam-datasets/tree/$REVISION/M_monado_datasets/MI_valve_index?recursive=true"
OUT_DIR="$DATA_ROOT/discovery/$DATASET_ID"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
ZIPTOOL="$RECIPE_DIR/scripts/msd_zip.py"
UA="openzl-public-datasets-monado-msd-discovery/1.0"
WINDOW=1048576
TAIL=131072

mkdir -p "$OUT_DIR/tails" "$OUT_DIR/windows" "$OUT_DIR/headers" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/discover.$RUN_TS.log" "$LOG_DIR/discover.latest.log") 2>&1
echo "[$(date -Is)] discover start dataset=$DATASET_ID revision=$REVISION"

small_get() {  # small_get <url> <out> [range]
  local url="$1" out="$2" range="${3:-}"
  local args=(--fail --silent --show-error --location --retry 5 --retry-delay 3 --retry-all-errors
    --connect-timeout 30 --max-time 300 --user-agent "$UA" --max-filesize 50000000)
  if [ -n "$range" ]; then args+=(--range "$range"); fi
  curl "${args[@]}" --output "$out.part" "$url"
  mv "$out.part" "$out"
}

small_get "$TREE_URL" "$OUT_DIR/tree.json"

# Sequence list: every .zip under MIC_calibration, MIO_others and MIP_playing;
# split-part siblings (.z01, .z02, ...) are recorded for the multi-disk MIPB08.
python3 - "$OUT_DIR/tree.json" "$OUT_DIR/archives.tsv" <<'PY'
import json, sys
from pathlib import PurePosixPath
tree = json.load(open(sys.argv[1]))
files = {e["path"]: e for e in tree if e.get("type") == "file"}
rows = []
for path, e in sorted(files.items()):
    p = PurePosixPath(path)
    if p.suffix != ".zip" or "/extras/" in path:
        continue
    stem = p.stem
    parts = sorted(q for q in files if PurePosixPath(q).parent == p.parent and PurePosixPath(q).stem == stem
                   and PurePosixPath(q).suffix.startswith(".z") and PurePosixPath(q).suffix != ".zip")
    chain = parts + [path]
    for disk, q in enumerate(chain):
        rows.append((stem, disk, len(chain), q, files[q]["size"], files[q]["lfs"]["oid"]))
with open(sys.argv[2], "w") as out:
    out.write("sequence\tdisk\ttotal_disks\tpath\tsize_bytes\tlfs_sha256\n")
    for r in rows:
        out.write("\t".join(map(str, r)) + "\n")
print(f"archives sequences={len({r[0] for r in rows})} files={len(rows)}")
PY

: > "$OUT_DIR/sources.candidate.rows"
tail -n +2 "$OUT_DIR/archives.tsv" | awk -F'\t' '$2 == $3 - 1' | while IFS=$'\t' read -r seq disk total path size sha; do
  url="$REPO_URL/resolve/$REVISION/$path"
  tail_file="$OUT_DIR/tails/$seq.bin"
  [ -s "$tail_file" ] || small_get "$url" "$tail_file" "$((size - TAIL))-$((size - 1))"
  info="$(python3 "$ZIPTOOL" tail "$tail_file" "$size")"
  read -r cd_off cd_size total_disks <<<"$(python3 -c 'import json,sys; d=json.loads(sys.argv[1]); print(d["cd_offset"], d["cd_size"], d["total_disks"])' "$info")"
  if [ "$total_disks" != "$total" ]; then
    echo "FATAL $seq: EOCD reports $total_disks disks but the tree has $total part files" >&2
    exit 1
  fi
  member="$seq/mav0/imu0/data.csv"
  # The writer emits gt/, cam0/, imu0/, cam1/ in that order with equal camera
  # frame counts, so imu0 sits near the middle of the central directory.
  if [ "$cd_size" -le "$WINDOW" ]; then
    w_start="$cd_off"; w_end="$((cd_off + cd_size - 1))"
  else
    w_start="$((cd_off + cd_size / 2 - WINDOW / 2))"; w_end="$((w_start + WINDOW - 1))"
  fi
  window="$OUT_DIR/windows/$seq.bin"
  [ -s "$window" ] || small_get "$url" "$window" "$w_start-$w_end"
  found="$(python3 "$ZIPTOOL" find "$window" "$member")"
  if ! python3 -c 'import json,sys; sys.exit(0 if json.loads(sys.argv[1])["found"] else 1)' "$found"; then
    echo "window miss for $seq; fetching the full central directory ($cd_size bytes)"
    small_get "$url" "$window" "$cd_off-$((cd_off + cd_size - 1))"
    found="$(python3 "$ZIPTOOL" find "$window" "$member")"
  fi
  python3 - "$found" "$OUT_DIR/archives.tsv" "$seq" "$OUT_DIR/member.$seq.json" <<'PY'
import json, sys
found = json.loads(sys.argv[1])
if not found["found"]:
    raise SystemExit(f"member not found in central directory of {sys.argv[3]}")
e = found["entry"]
parts = [l.rstrip("\n").split("\t") for l in open(sys.argv[2])][1:]
chain = [p for p in parts if p[0] == sys.argv[3]]
part = chain[e["disk"]]
e.update(part_path=part[3], part_size=int(part[4]), part_sha256=part[5], total_disks=len(chain),
         siblings=found["siblings"])
if e["flags"] & 0x1:
    raise SystemExit("encrypted member")
if e["method"] not in (0, 8):
    raise SystemExit(f"unsupported method {e['method']}")
json.dump(e, open(sys.argv[4], "w"), sort_keys=True)
print(f"member seq={sys.argv[3]} disk={e['disk']} part={part[3].rsplit('/',1)[-1]} lho={e['local_header_offset']} "
      f"csz={e['compressed_size']} usz={e['uncompressed_size']} method={e['method']} crc32={e['crc32']:08x} siblings={found['siblings']}")
PY
  read -r part_path lho <<<"$(python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); print(d["part_path"], d["local_header_offset"])' "$OUT_DIR/member.$seq.json")"
  header="$OUT_DIR/headers/$seq.bin"
  [ -s "$header" ] || small_get "$REPO_URL/resolve/$REVISION/$part_path" "$header" "$lho-$((lho + 1023))"
  python3 - "$OUT_DIR/member.$seq.json" "$header" "$ZIPTOOL" "$seq" >> "$OUT_DIR/sources.candidate.rows" <<'PY'
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(sys.argv[3]).parent))
import msd_zip
e = json.load(open(sys.argv[1]))
h = msd_zip.parse_local_header(Path(sys.argv[2]).read_bytes())
if h["name"] != e["name"]:
    raise SystemExit(f"local header name {h['name']!r} != {e['name']!r}")
if h["method"] != e["method"]:
    raise SystemExit("local/central method mismatch")
if not h["flags"] & 0x8 and (h["crc32"], h["compressed_size"], h["uncompressed_size"]) != (
        e["crc32"], e["compressed_size"], e["uncompressed_size"]):
    raise SystemExit("local/central CRC or size mismatch")
end = e["local_header_offset"] + h["header_bytes"] + e["compressed_size"]
if end > e["part_size"]:
    raise SystemExit(f"member crosses the end of part {e['part_path']} ({end} > {e['part_size']})")
seq = sys.argv[4]
group = seq[:3]
print("\t".join(map(str, [seq, group, e["part_path"], e["part_size"], e["part_sha256"], e["disk"], e["total_disks"],
                          e["name"], e["local_header_offset"], h["header_bytes"], e["compressed_size"],
                          e["uncompressed_size"], f"{e['crc32']:08x}", e["method"]])))
PY
done

# All 49 resolved members go to sources.all.tsv. The recipe scope (sources.tsv)
# drops the 19 sequences whose published data.csv carries the Basalt correction
# more than once; download.sh pins the same EXCLUDED list and build/verify
# enforce the single-correction accel-x lattice step.
EXCLUDED_RE='^(MIC(0[1-9]|1[0-6])_|MIO0[1-3]_)'
HEADER_LINE='sequence\tgroup\tpart_path\tpart_size_bytes\tpart_lfs_sha256\tdisk\ttotal_disks\tmember\tlocal_header_offset\tlocal_header_bytes\tcompressed_size\tuncompressed_size\tcrc32\tmethod\n'
{ printf "$HEADER_LINE"; sort "$OUT_DIR/sources.candidate.rows"; } > "$OUT_DIR/sources.all.tsv"
{ printf "$HEADER_LINE"; sort "$OUT_DIR/sources.candidate.rows" | grep -E -v "$EXCLUDED_RE"; } > "$OUT_DIR/sources.candidate.tsv"
rows="$(($(wc -l < "$OUT_DIR/sources.candidate.tsv") - 1))"
echo "candidate sources: $OUT_DIR/sources.candidate.tsv rows=$rows"
if [ -f "$RECIPE_DIR/sources.tsv" ]; then
  if cmp -s "$OUT_DIR/sources.candidate.tsv" "$RECIPE_DIR/sources.tsv"; then
    echo "committed sources.tsv matches discovery"
  else
    echo "WARNING: committed sources.tsv differs from discovery" >&2
    diff "$RECIPE_DIR/sources.tsv" "$OUT_DIR/sources.candidate.tsv" | head -20 || true
  fi
fi
echo "[$(date -Is)] discover done dataset=$DATASET_ID"
