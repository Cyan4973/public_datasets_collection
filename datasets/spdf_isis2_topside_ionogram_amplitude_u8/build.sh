#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="spdf_isis2_topside_ionogram_amplitude_u8"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"

mkdir -p "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/build.$RUN_TS.log" "$LOG_DIR/build.latest.log") 2>&1
echo "[$(date -Is)] build start dataset=$DATASET_ID"

# Parser self-test on synthetic CDF v2.6 files before touching real data.
(cd "$(mktemp -d)" && python3 -I -B "$RECIPE_DIR/scripts/selftest_cdf26.py")

python3 -I -B "$RECIPE_DIR/scripts/isis2_ionogram.py" build \
  --repo-root "$REPO_ROOT" --data-dir "$DATA_DIR" --sources "$RECIPE_DIR/sources.tsv"

echo "[$(date -Is)] build done dataset=$DATASET_ID"
