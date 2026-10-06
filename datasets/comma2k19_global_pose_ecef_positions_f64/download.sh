#!/usr/bin/env bash
# Range-fetch every global_pose/frame_positions member of comma2k19 from the
# ten pinned ZIP64 chunk archives on Hugging Face, without downloading the
# ~94 GB archives themselves.
#
# Per chunk: validate archive identity (resolve HEAD), fetch the 4 KiB tail and
# check the ZIP64 EOCD against pins, fetch the central directory and check its
# SHA-256, parse it into exact member byte ranges (local header + deflate data,
# ending where the next member's local header starts). Then fetch the ranges
# with curl (parallel, resumable by skipping members already present) and
# validate each one: local header vs central directory, inflate, CRC32, NPY
# header ('<f8', C order, (N,3)), finite values, plausible ECEF radius.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="comma2k19_global_pose_ecef_positions_f64"
REVISION="4bff77c7254c654c28d4c2726186b4e825adccee"
HF_REPO="https://huggingface.co/datasets/commaai/comma2k19"
RAW_BASE="$HF_REPO/resolve/$REVISION/raw_data"
README_URL="$HF_REPO/raw/$REVISION/README.md"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
CHUNK_DIR="$DOWNLOAD_DIR/chunks"
PLAN_DIR="$DOWNLOAD_DIR/plan"
MEMBERS_DIR="$DOWNLOAD_DIR/members"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
PY="$RECIPE_DIR/scripts/comma2k19_pose.py"
CHUNKS_TSV="$RECIPE_DIR/chunks.tsv"
TAIL_BYTES=4096
PARALLEL="${COMMA2K19_PARALLEL:-4}"
MAX_ROUNDS=6
UA="openzl-public-datasets-comma2k19-pose/1.0"

mkdir -p "$CHUNK_DIR" "$PLAN_DIR" "$MEMBERS_DIR" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
echo "[$(date -Is)] download start dataset=$DATASET_ID revision=$REVISION parallel=$PARALLEL"

if [ "${FORCE_DOWNLOAD:-0}" = "1" ]; then
  rm -rf "$CHUNK_DIR" "$PLAN_DIR" "$MEMBERS_DIR" "$DOWNLOAD_DIR/README.md"
  mkdir -p "$CHUNK_DIR" "$PLAN_DIR" "$MEMBERS_DIR"
fi

python3 "$PY" selftest

# Fetch an exact byte range; reuse an existing file of the exact length.
fetch_range() {
  local url="$1" start="$2" end="$3" output="$4"
  local length=$((end - start + 1))
  if [ -f "$output" ] && [ "$(stat -c %s "$output")" = "$length" ]; then
    echo "cache_hit bytes=$length file=${output#"$REPO_ROOT/"}"
    return 0
  fi
  rm -f "$output" "$output.part"
  curl --globoff --fail --silent --show-error --location \
    --retry 5 --retry-delay 3 --retry-all-errors --max-time 900 \
    --speed-limit 1024 --speed-time 120 \
    --max-filesize "$((length + 4096))" --range "$start-$end" \
    --user-agent "$UA" --output "$output.part" "$url"
  local got
  got="$(stat -c %s "$output.part")"
  if [ "$got" != "$length" ]; then
    rm -f "$output.part"
    echo "FATAL: range $start-$end of $url returned $got bytes, expected $length" >&2
    return 1
  fi
  mv "$output.part" "$output"
  echo "fetched bytes=$length file=${output#"$REPO_ROOT/"}"
}

# 1. Dataset card at the pinned revision (license + identity evidence).
card="$DOWNLOAD_DIR/README.md"
if [ ! -s "$card" ]; then
  curl --fail --silent --show-error --location \
    --retry 5 --retry-delay 3 --retry-all-errors --max-time 120 --max-filesize 1000000 \
    --user-agent "$UA" --output "$card.part" "$README_URL"
  mv "$card.part" "$card"
fi
python3 "$PY" check-readme --readme "$card" || { rm -f "$card"; exit 1; }

# 2. Per chunk: identity, ZIP64 tail, central directory, member plan.
chunk_count=0
while IFS=$'\t' read -r -u 3 chunk archive_bytes lfs_sha256 _eocd64 cd_offset cd_bytes _entries cd_sha256 members range_bytes _npy; do
  [ "$chunk" != "chunk" ] || continue
  kk="$(printf '%02d' "$chunk")"
  url="$RAW_BASE/Chunk_$chunk.zip"
  echo "chunk=$chunk archive_bytes=$archive_bytes members=$members range_bytes=$range_bytes"

  head_file="$CHUNK_DIR/Chunk_$kk.head.txt"
  curl --globoff --silent --show-error --head \
    --retry 5 --retry-delay 3 --retry-all-errors --max-time 120 \
    --user-agent "$UA" --output "$head_file.part" "$url"
  mv "$head_file.part" "$head_file"
  python3 "$PY" check-head --headers "$head_file" --chunk "$chunk" --size "$archive_bytes" --sha256 "$lfs_sha256"

  tail_file="$CHUNK_DIR/Chunk_$kk.tail.bin"
  fetch_range "$url" "$((archive_bytes - TAIL_BYTES))" "$((archive_bytes - 1))" "$tail_file"
  python3 "$PY" check-tail --chunks "$CHUNKS_TSV" --chunk "$chunk" --tail "$tail_file" || { rm -f "$tail_file"; exit 1; }

  cd_file="$CHUNK_DIR/Chunk_$kk.central_directory.bin"
  fetch_range "$url" "$cd_offset" "$((cd_offset + cd_bytes - 1))" "$cd_file"
  printf '%s  %s\n' "$cd_sha256" "$cd_file" | sha256sum --check --status || {
    rm -f "$cd_file"
    echo "FATAL: central directory SHA-256 mismatch for chunk $chunk" >&2
    exit 1
  }
  python3 "$PY" plan --chunks "$CHUNKS_TSV" --chunk "$chunk" --cd "$cd_file" --out "$PLAN_DIR/chunk_$kk.plan.tsv"
  chunk_count=$((chunk_count + 1))
done 3< "$CHUNKS_TSV"
[ "$chunk_count" = 10 ] || { echo "FATAL: expected 10 chunks, planned $chunk_count" >&2; exit 1; }

# 3. Member ranges. Failures are retried in later rounds; validate deletes
#    transport-corrupt members so they are refetched.
fetch_member() {
  local chunk="$1" start="$2" end="$3" rel="$4"
  local length=$((end - start + 1))
  local target="$MEMBERS_DIR/$rel"
  mkdir -p "$(dirname "$target")"
  rm -f "$target.part"
  if curl --globoff --fail --silent --show-error --location \
      --retry 5 --retry-delay 3 --retry-all-errors --max-time 300 \
      --speed-limit 256 --speed-time 60 \
      --max-filesize "$((length + 4096))" --range "$start-$end" \
      --user-agent "$UA" --output "$target.part" "$RAW_BASE/Chunk_$chunk.zip"; then
    local got
    got="$(stat -c %s "$target.part" 2>/dev/null || echo 0)"
    if [ "$got" = "$length" ]; then
      mv "$target.part" "$target"
      return 0
    fi
    echo "member_wrong_length rel=$rel got=$got expected=$length"
  else
    echo "member_fetch_failed rel=$rel"
  fi
  rm -f "$target.part"
  return 0
}
export -f fetch_member
export MEMBERS_DIR RAW_BASE UA

ok=0
for round in $(seq 1 "$MAX_ROUNDS"); do
  pending="$(python3 "$PY" pending --plan-dir "$PLAN_DIR" --members-dir "$MEMBERS_DIR" --count)"
  echo "[$(date -Is)] round=$round pending_members=$pending"
  if [ "$pending" != "0" ]; then
    for chunk in 1 2 3 4 5 6 7 8 9 10; do
      chunk_pending="$(python3 "$PY" pending --plan-dir "$PLAN_DIR" --members-dir "$MEMBERS_DIR" --chunk "$chunk" --count)"
      [ "$chunk_pending" != "0" ] || continue
      python3 "$PY" pending --plan-dir "$PLAN_DIR" --members-dir "$MEMBERS_DIR" --chunk "$chunk" \
        | xargs -r -P "$PARALLEL" -n 4 bash -c 'fetch_member "$@"' _
      left="$(python3 "$PY" pending --plan-dir "$PLAN_DIR" --members-dir "$MEMBERS_DIR" --chunk "$chunk" --count)"
      echo "[$(date -Is)] round=$round chunk=$chunk requested=$chunk_pending still_missing=$left"
    done
  fi
  set +e
  python3 "$PY" validate --plan-dir "$PLAN_DIR" --members-dir "$MEMBERS_DIR" \
    --summary "$DOWNLOAD_DIR/download_summary.json"
  rc=$?
  set -e
  if [ "$rc" = 0 ]; then
    ok=1
    break
  fi
  if [ "$rc" != 3 ]; then
    echo "FATAL: member validation failed (rc=$rc)" >&2
    exit 1
  fi
  sleep $((round * 15))
done
[ "$ok" = 1 ] || { echo "FATAL: members still missing or corrupt after $MAX_ROUNDS rounds" >&2; exit 1; }

echo "download_bytes_on_disk=$(du -sb "$DOWNLOAD_DIR" | cut -f1)"
echo "[$(date -Is)] download done dataset=$DATASET_ID"
