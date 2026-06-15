#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
BATCH_ID="source_variety_batch_20260615_16a"
BATCH_DIR="$REPO_ROOT/$DATA_DIR/batches/$BATCH_ID"
mkdir -p "$BATCH_DIR"
SUMMARY="$BATCH_DIR/summary.tsv"
printf 'dataset_id\tstatus\n' > "$SUMMARY"

DATASETS=(
  hf_smolllm2_135m_safetensors_f16
)

DEFERRED_DATASETS=(
  nasa_sdo_aia_synoptic_fits_i16
  nasa_pds_magellan_sar_i16
  nasa_pds_messenger_mdis_basemap_i16
  nasa_pds_clementine_uvvis_i16
  noaa_nexrad_level2_moments_i16
  nasa_pds_themis_ir_mosaic_i16
)

for dataset_id in "${DATASETS[@]}"; do
  echo "[$(date -Is)] batch download start dataset=$dataset_id"
  if DATA_DIR="$DATA_DIR" "$REPO_ROOT/staging/$dataset_id/download.sh"; then
    printf '%s\tok\n' "$dataset_id" >> "$SUMMARY"
  else
    printf '%s\tfailed\n' "$dataset_id" >> "$SUMMARY"
  fi
done

if [[ "${INCLUDE_DEFERRED:-0}" == "1" ]]; then
  for dataset_id in "${DEFERRED_DATASETS[@]}"; do
    echo "[$(date -Is)] batch download start deferred dataset=$dataset_id"
    if DATA_DIR="$DATA_DIR" "$REPO_ROOT/staging/$dataset_id/download.sh"; then
      printf '%s\tok\n' "$dataset_id" >> "$SUMMARY"
    else
      printf '%s\tfailed\n' "$dataset_id" >> "$SUMMARY"
    fi
  done
else
  for dataset_id in "${DEFERRED_DATASETS[@]}"; do
    printf '%s\tdeferred\n' "$dataset_id" >> "$SUMMARY"
  done
fi

cat "$SUMMARY"
