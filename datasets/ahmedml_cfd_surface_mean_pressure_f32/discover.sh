#!/usr/bin/env bash
# Regenerate selection.tsv: for each selected run (run_1, run_11, ..., run_491
# at the pinned revision) pin the boundary VTP size, LFS sha256 and xet hash
# from the paths-info API, then locate the pMean CellData base64 block with
# small HTTP Range requests only:
#   1. bytes 0-2047          -> VTKFile attributes, NumberOfPoints/NumberOfPolys
#   2. last 1,024 bytes      -> end of the last CellData base64 block
#   3. walk backwards over the fixed CellData order
#      wallShearStressMean(3) <- yPlusMean <- static(p)_coeffMean <- pMean,
#      each step computing the block length ceil((8 + 4*N*ncomp)/3)*4 and
#      fetching 272 bytes around the computed block start to confirm the
#      opening tag (Name, Float32, components) and the decoded UInt64 byte-count
#      prefix (== 4*N*ncomp).
# About 7 KB per run; the bulk pMean bytes are fetched only by download.sh.
# Never touches volume_*.vtu, slices/ or whole VTP files.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="ahmedml_cfd_surface_mean_pressure_f32"
WORK_DIR="${WORK_DIR:-$DATA_ROOT/downloads/$DATASET_ID/discover}"
SELECTION_OUT="${SELECTION_OUT:-$RECIPE_DIR/selection.tsv}"
REVISION="02688c727cdb8dc8678e28abc6bbbb7e93c5fa15"
HF="https://huggingface.co"
API_INFO_URL="$HF/api/datasets/neashton/ahmedml/revision/$REVISION?expand%5B%5D=cardData&expand%5B%5D=sha&expand%5B%5D=gated&expand%5B%5D=private&expand%5B%5D=disabled"
PATHS_INFO_URL="$HF/api/datasets/neashton/ahmedml/paths-info/$REVISION"
RESOLVE_BASE="$HF/datasets/neashton/ahmedml/resolve/$REVISION"
HELPER="$RECIPE_DIR/scripts/ahmedml_vtp.py"
UA="openzl-public-datasets-ahmedml/1.0"
export PYTHONDONTWRITEBYTECODE=1

mkdir -p "$WORK_DIR/meta" "$WORK_DIR/probe"
echo "[$(date -Is)] discover start dataset=$DATASET_ID revision=$REVISION work=$WORK_DIR"
python3 "$HELPER" selftest

small_get() {  # url output
  rm -f "$2.part"
  curl --fail --silent --show-error --location \
    --retry 6 --retry-all-errors --connect-timeout 30 --max-time 180 \
    --max-filesize 5000000 --user-agent "$UA" --output "$2.part" "$1"
  mv "$2.part" "$2"
}

small_get "$API_INFO_URL" "$WORK_DIR/meta/api_info.json"
small_get "$RESOLVE_BASE/README.md" "$WORK_DIR/meta/README.md"
small_get "$RESOLVE_BASE/LICENSE.txt" "$WORK_DIR/meta/LICENSE.txt"
python3 "$HELPER" check-meta --api-info "$WORK_DIR/meta/api_info.json" \
  --readme "$WORK_DIR/meta/README.md" --license "$WORK_DIR/meta/LICENSE.txt"

python3 "$HELPER" plan | cut -f2 | sed -e 's#/#%2F#g' -e 's#^#paths=#' | paste -sd '&' - | tr -d '\n' \
  > "$WORK_DIR/meta/paths_form.txt"
rm -f "$WORK_DIR/meta/paths_info.json.part"
curl --fail --silent --show-error --retry 6 --retry-all-errors --connect-timeout 30 --max-time 180 \
  --user-agent "$UA" -X POST --data "@$WORK_DIR/meta/paths_form.txt" \
  --output "$WORK_DIR/meta/paths_info.json.part" "$PATHS_INFO_URL"
mv "$WORK_DIR/meta/paths_info.json.part" "$WORK_DIR/meta/paths_info.json"
python3 "$HELPER" pin-paths --out "$WORK_DIR/meta/draft.tsv" "$WORK_DIR/meta/paths_info.json"

probe() {  # repo_path start end size lfs xet output
  local attempt
  for attempt in 1 2 3 4; do
    rm -f "$7" "$7.http"
    if curl --fail --silent --show-error --location --proto-redir =https \
        --retry 6 --retry-all-errors --connect-timeout 30 --max-time 120 \
        --max-filesize 100000 --range "$2-$3" --user-agent "$UA" \
        --dump-header "$7.http" --output "$7" "$RESOLVE_BASE/$1"; then
      python3 "$HELPER" check-http --http "$7.http" --start "$2" --end "$3" --size "$4" --lfs "$5" --xet "$6"
      sleep 0.2
      return 0
    fi
    echo "WARN: probe $1 $2-$3 failed (attempt $attempt)" >&2
    sleep 30
  done
  echo "FATAL: probe $1 $2-$3 failed" >&2
  return 1
}

tmp_out="$SELECTION_OUT.part"
printf 'run\tpath\tsize_bytes\tlfs_sha256\txet_hash\tnumber_of_points\tnumber_of_polys\tpmean_b64_start\tpmean_b64_end\n' > "$tmp_out"
while IFS=$'\t' read -r run path size lfs xet; do
  [ "$run" = "run" ] && continue
  p="$WORK_DIR/probe/run_$run"
  probe "$path" 0 2047 "$size" "$lfs" "$xet" "$p.head"
  read -r npoints npolys < <(python3 "$HELPER" parse-head --head "$p.head")
  tail_start=$((size - 1024))
  probe "$path" "$tail_start" $((size - 1)) "$size" "$lfs" "$xet" "$p.tail"
  end="$(python3 "$HELPER" tail-end --tail "$p.tail" --tail-start "$tail_start" --size "$size")"
  for spec in "wallShearStressMean:3" "yPlusMean:1" "static(p)_coeffMean:1" "pMean:1"; do
    name="${spec%:*}"
    ncomp="${spec##*:}"
    blen=$(( (8 + 4 * npolys * ncomp + 2) / 3 * 4 ))
    start=$((end - blen))
    probe "$path" $((start - 256)) $((start + 15)) "$size" "$lfs" "$xet" "$p.$ncomp.$name.win"
    prev="$(python3 "$HELPER" walk-step --window "$p.$ncomp.$name.win" --window-start $((start - 256)) \
      --b64-start "$start" --name "$name" --ncomp "$ncomp" --polys "$npolys")"
    if [ "$name" = "pMean" ]; then
      printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' "$run" "$path" "$size" "$lfs" "$xet" \
        "$npoints" "$npolys" "$start" "$end" >> "$tmp_out"
      echo "run=$run polys=$npolys pmean_b64=[$start,$end) bytes=$((end - start))"
    fi
    end="$prev"
  done
done < "$WORK_DIR/meta/draft.tsv"
mv "$tmp_out" "$SELECTION_OUT"
python3 "$HELPER" check-paths --selection "$SELECTION_OUT" "$WORK_DIR/meta/paths_info.json"
echo "[$(date -Is)] discover done selection=$SELECTION_OUT"
