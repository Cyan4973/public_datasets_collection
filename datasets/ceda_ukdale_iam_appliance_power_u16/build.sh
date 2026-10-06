#!/usr/bin/env bash
# Build uint16 IAM real-power samples (+ uint32 auxiliary timestamps) from the
# locally fetched UK-DALE ZIP member ranges. No network access.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="ceda_ukdale_iam_appliance_power_u16"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
mkdir -p "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/build.$RUN_TS.log" "$LOG_DIR/build.latest.log") 2>&1
echo "[$(date -Is)] build start dataset=$DATASET_ID"

if ! cmp -s "$DATA_ROOT/downloads/$DATASET_ID/selection.tsv" "$RECIPE_DIR/members.tsv"; then
  echo "FATAL: downloads/$DATASET_ID/selection.tsv missing or differs from members.tsv; run download.sh" >&2
  exit 1
fi
python3 "$RECIPE_DIR/scripts/ukdale_iam_build.py" --data-root "$DATA_ROOT" --pinned "$RECIPE_DIR/members.tsv"

echo "[$(date -Is)] build done dataset=$DATASET_ID"
