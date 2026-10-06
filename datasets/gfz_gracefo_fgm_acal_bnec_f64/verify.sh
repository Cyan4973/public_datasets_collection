#!/usr/bin/env bash
# Independently re-derive every sample from its source CDF and check the
# index, manifest counts, missing-value policy, nondegeneracy and the
# B_NEC == conj(q_NEC_FGM) * B_FGM rotation identity.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="gfz_gracefo_fgm_acal_bnec_f64"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"

mkdir -p "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/verify.$RUN_TS.log" "$LOG_DIR/verify.latest.log") 2>&1
echo "[$(date -Is)] verify start dataset=$DATASET_ID"

PYTHONDONTWRITEBYTECODE=1 python3 "$RECIPE_DIR/scripts/selftest_cdf3.py"
PYTHONDONTWRITEBYTECODE=1 python3 "$RECIPE_DIR/scripts/gracefo_fgm.py" verify \
  --repo-root "$REPO_ROOT" --data-dir "$DATA_DIR" --sources "$RECIPE_DIR/sources.tsv" \
  --manifest "$RECIPE_DIR/manifest.toml"

echo "[$(date -Is)] verify done dataset=$DATASET_ID"
