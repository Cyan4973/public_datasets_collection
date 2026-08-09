#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
CANDIDATE_ID="nasa_pds_cassini_vims_qube_i16"
RECIPE_DIR="$REPO_ROOT/datasets/$CANDIDATE_ID"
OUTPUT_DIR="$REPO_ROOT/$DATA_DIR/discovery/$CANDIDATE_ID"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$CANDIDATE_ID"

mkdir -p "$OUTPUT_DIR" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/discover.$RUN_TS.log" "$LOG_DIR/discover.latest.log") 2>&1
echo "[$(date -Is)] discovery start candidate=$CANDIDATE_ID"

python3 "$RECIPE_DIR/scripts/discover.py" \
  --output-dir "$OUTPUT_DIR" \
  --archive-root "${VIMS_ARCHIVE_ROOT:-https://pds-imaging.jpl.nasa.gov/data/cassini/cassini_orbiter/}" \
  --volume-limit "${VIMS_VOLUME_LIMIT:-8}" \
  --candidate-limit "${VIMS_CANDIDATE_LIMIT:-320}" \
  --qualified-limit "${VIMS_QUALIFIED_LIMIT:-120}"

echo "[$(date -Is)] discovery done candidate=$CANDIDATE_ID"
