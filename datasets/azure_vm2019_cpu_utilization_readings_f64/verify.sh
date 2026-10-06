#!/usr/bin/env bash
# Independently re-derive every fleet-snapshot sample from the local source
# files and check index, stats, manifest totals and the missing-value policy.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="azure_vm2019_cpu_utilization_readings_f64"
DOWNLOAD_DIR="$DATA_ROOT/downloads/$DATASET_ID"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
mkdir -p "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/verify.$RUN_TS.log" "$LOG_DIR/verify.latest.log") 2>&1
echo "[$(date -Is)] verify start dataset=$DATASET_ID data_root=$DATA_ROOT"

F1="$DOWNLOAD_DIR/trace_data_vm_cpu_readings_vm_cpu_readings-file-1-of-195.csv.gz"
F2="$DOWNLOAD_DIR/trace_data_vm_cpu_readings_vm_cpu_readings-file-2-of-195.csv.gz"
F3_HEAD="$DOWNLOAD_DIR/trace_data_vm_cpu_readings_vm_cpu_readings-file-3-of-195.head-0-65535.gz"

printf '%s  %s\n' \
  010c375e5e69624c300a2dad1460762364b89b8ca030e1de05dcd808e9d7032a "$F1" \
  26d03dee50b36ae4d572d17206431905b3ebb18faa9851efb985d2239eb43389 "$F2" \
  93b3b6f50f0fc9bcdda1ec1e6ed00101fdab3bb2f6883d790c334de799282291 "$F3_HEAD" \
  | sha256sum --check --quiet || { echo "VERIFY FAILED: source checksum mismatch" >&2; exit 1; }

python3 "$RECIPE_DIR/scripts/verify_snapshots.py" \
  --dataset-id "$DATASET_ID" \
  --data-root "$DATA_ROOT" \
  --source "$F1" \
  --source "$F2" \
  --first-ts 0 \
  --snapshots 88 \
  --next-head "$F3_HEAD:26400" \
  --samples-dir "$DATA_ROOT/samples/$DATASET_ID" \
  --index "$DATA_ROOT/index/$DATASET_ID/samples.jsonl" \
  --stats "$DATA_ROOT/filtered/$DATASET_ID/ingest_stats.json" \
  --manifest "$RECIPE_DIR/manifest.toml" \
  --interval 300

echo "[$(date -Is)] verify done dataset=$DATASET_ID"
