#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="bitcoin_block_output_amounts_i64"
API_BASE="https://blockstream.info/api"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
BLOCK_DIR="$DOWNLOAD_DIR/blocks"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
PLAN="$DOWNLOAD_DIR/download_plan.tsv"
INVENTORY="$DOWNLOAD_DIR/download_inventory.tsv"
MAX_FILE_BYTES=8000000
MAX_TOTAL_BYTES=100000000

mkdir -p "$BLOCK_DIR" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
echo "[$(date -Is)] download start dataset=$DATASET_ID"

export PLAN API_BASE
python3 - <<'PY'
import os
from pathlib import Path

blocks = [
    (840000, "0000000000000000000320283a032748cef8227873ff4872689bf23f1cda83a5", 2325617, "42e6ab3dc0a19c205d975265997334ffe3981282f43da0a9bdb9295271f5b258"),
    (840001, "00000000000000000001b48a75d5a3077913f3f441eb7e08c13c43f768db2463", 2363016, "64a01e1f73e3c1f1fa0410baaa508b77e13c8ee4ea4e3f58ef9227e578e9454b"),
    (840002, "00000000000000000002c0cc73626b56fb3ee1ce605b0ce125cc4fb58775a0a9", 1426321, "f533ac41f4eb44ea3c3608df447c0afe742813b3c47239f83d26426928e065b8"),
    (840003, "00000000000000000001cfe8671cb9269dfeded2c4e900e365fffae09b34b119", 1406707, "135bca486e4eb8de3b149a169dbb8c9644044a7dd56ec69c61b31c0a581f0d61"),
    (840004, "000000000000000000028458274b1f458d57d817fdce349e31dd5cb51b277d36", 1421352, "420b25534eb0bccf3e2ea9cedfd6988c2830c11a0b066a8913152db253f6f637"),
    (840005, "000000000000000000027b0ec0e3acadd018cd19e7dd976602f216a1bc12d079", 1433644, "2957ca8fed4e7d11c9887dfae151d9e738b119e5c1259502db7bf999405180b5"),
    (840006, "0000000000000000000098dab8c28e5f20ab1663b8dd6c81bb54bbbcd0ead5ac", 1430437, "a39b2c83cd77a83a5dfd1f43f193c886cbc5fbaeef5916247c2eeda5c38e8d1f"),
    (840007, "000000000000000000030d1455700ec234e4214e75e8e1112632b74febe80c78", 1412031, "5a5705c91e2e46177cd890e0c6fc40bf3b3d0908ca619d2f95401f6405a779db"),
    (840008, "00000000000000000001d57c33db2ebb841d806bcf853549d35d852693b9fc2d", 1407989, "ac6de0289e28684e97746e0b31c125c00db5275dc4be522b9b26cfa37bc2bf72"),
    (840009, "00000000000000000000c6075e66b667adcdb8935e6d9a877f5cf140c806ae87", 1401811, "8eae6d44d3940138689e6855fc99b4f23de8a2e7ff382d9d667cf0080245b4d5"),
    (840010, "00000000000000000000da20f7d8e9e6412d4f1d8b62d88264cddbdd48256ba0", 1433552, "0512ebf9fb9b5b127895270fd879015152ebd0474316979a2ba26a7db2efae4e"),
    (840011, "00000000000000000002d12efb02bcf70580b2eebf4b775578844640512e30f3", 1411920, "a2a7a00cb0004df71c317e42c7f653cdf6acce5a144703bfdd3995cbe73443bd"),
]
base = os.environ["API_BASE"]
with Path(os.environ["PLAN"]).open("w", encoding="utf-8") as handle:
    handle.write("height\tblock_hash\traw_url\texpected_bytes\texpected_sha256\n")
    for height, block_hash, size, sha256 in blocks:
        handle.write(f"{height}\t{block_hash}\t{base}/block/{block_hash}/raw\t{size}\t{sha256}\n")
print(f"pinned_blocks={len(blocks)} heights={blocks[0][0]}..{blocks[-1][0]}")
PY

total_bytes=0
printf 'height\tblock_hash\traw_url\tbytes\tsha256\n' > "$INVENTORY"
tail -n +2 "$PLAN" | while IFS=$'\t' read -r height hash raw_url expected_bytes expected_sha256; do
  block="$BLOCK_DIR/height_${height}_${hash}.blk"
  if [[ -s "$block" ]]; then
    echo "reuse existing height=$height hash=$hash"
  else
    rm -f "$block" "$block.part"
    curl --fail --location --retry 4 --retry-delay 3 \
      --user-agent "openzl-public-datasets/1.0" \
      --max-filesize "$MAX_FILE_BYTES" --output "$block.part" "$raw_url"
    mv "$block.part" "$block"
  fi
  bytes="$(wc -c < "$block" | tr -d ' ')"
  [[ "$bytes" == "$expected_bytes" ]] || { echo "pinned size mismatch at height $height" >&2; exit 1; }
  (( bytes > 80 && bytes <= MAX_FILE_BYTES )) || { echo "invalid block size at height $height" >&2; exit 1; }
  total_bytes=$((total_bytes + bytes))
  (( total_bytes <= MAX_TOTAL_BYTES )) || { echo "total source cap exceeded" >&2; exit 1; }
  sha256="$(sha256sum "$block" | awk '{print $1}')"
  [[ "$sha256" == "$expected_sha256" ]] || { echo "pinned SHA-256 mismatch at height $height" >&2; exit 1; }
  printf '%s\t%s\t%s\t%s\t%s\n' "$height" "$hash" "$raw_url" "$bytes" "$sha256" >> "$INVENTORY"
done

mapfile -t BLOCKS < <(find "$BLOCK_DIR" -maxdepth 1 -type f -name 'height_*.blk' | sort)
[[ "${#BLOCKS[@]}" -eq 12 ]] || { echo "expected 12 blocks, found ${#BLOCKS[@]}" >&2; exit 1; }
python3 "$REPO_ROOT/datasets/$DATASET_ID/scripts/bitcoin_blocks.py" inspect "${BLOCKS[@]}"
echo "[$(date -Is)] download done dataset=$DATASET_ID"
