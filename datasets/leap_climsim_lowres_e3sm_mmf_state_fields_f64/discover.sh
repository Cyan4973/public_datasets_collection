#!/usr/bin/env bash
# Regenerate selection.tsv: the deterministic timestep list with pinned
# per-file size, LFS sha256 and xet hash from the HF paths-info API at the
# pinned revision. Metadata only (about 9 small POST requests); download.sh
# re-checks the committed pins and never needs this script.
set -euo pipefail

RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATASET_ID="leap_climsim_lowres_e3sm_mmf_state_fields_f64"
REVISION="bab82a2ebdc750a0134ddcd0d5813867b92eed2a"
PATHS_INFO_URL="https://huggingface.co/api/datasets/LEAP/ClimSim_low-res/paths-info/$REVISION"
WORK="${DISCOVER_TMP:-/tmp/autocollect/$DATASET_ID/discover}"
UA="openzl-public-datasets-climsim/1.0"
BATCH=100
export PYTHONDONTWRITEBYTECODE=1

mkdir -p "$WORK"
rm -f "$WORK"/paths_info_*.json "$WORK"/batch_*
python3 "$RECIPE_DIR/scripts/climsim.py" plan --output "$WORK/planned_paths.txt"
split -l "$BATCH" -d -a 3 "$WORK/planned_paths.txt" "$WORK/batch_"
for batch in "$WORK"/batch_[0-9][0-9][0-9]; do
  n="${batch##*_}"
  sed -e 's#/#%2F#g' -e 's#^#paths=#' "$batch" | paste -sd '&' - | tr -d '\n' > "$batch.form"
  curl --fail --silent --show-error --retry 5 --retry-all-errors --max-time 120 \
    --user-agent "$UA" -X POST --data "@$batch.form" \
    --output "$WORK/paths_info_$n.json" "$PATHS_INFO_URL"
  sleep 0.5
done
python3 "$RECIPE_DIR/scripts/climsim.py" pin --output "$RECIPE_DIR/selection.tsv" "$WORK"/paths_info_*.json
