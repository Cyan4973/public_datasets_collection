#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
CANDIDATE_ID="physionet_bidmc_ppg_resp_i16"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$CANDIDATE_ID"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$CANDIDATE_ID"
BASE_URL="https://physionet.org/files/bidmc/1.0.0"

mkdir -p "$DOWNLOAD_DIR" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
echo "[$(date -Is)] download start candidate=$CANDIDATE_ID"

fetch() {
  local relative="$1"
  local max_bytes="$2"
  local target="$DOWNLOAD_DIR/$relative"
  if [[ -s "$target" && "${FORCE_DOWNLOAD:-0}" != "1" ]]; then
    echo "cache_hit file=$relative"
    return
  fi
  echo "fetch file=$relative"
  curl --fail --location --retry 4 --retry-delay 3 --max-time 600 \
    --max-filesize "$max_bytes" --output "$target.part" "$BASE_URL/$relative"
  mv "$target.part" "$target"
}

fetch "LICENSE" 100000
fetch "RECORDS" 100000
fetch "SHA256SUMS.txt" 1000000

mapfile -t RECORDS < <(sed -e 's/\r$//' -e '/^[[:space:]]*$/d' "$DOWNLOAD_DIR/RECORDS")
[[ "${#RECORDS[@]}" == "53" ]] || {
  echo "official RECORDS count changed: ${#RECORDS[@]} != 53" >&2
  exit 1
}
for index in $(seq -w 1 53); do
  [[ "${RECORDS[$((10#$index - 1))]}" == "bidmc$index" ]] || {
    echo "official RECORDS identity/order changed at $index" >&2
    exit 1
  }
done

for record in "${RECORDS[@]}"; do
  [[ "$record" =~ ^bidmc[0-9]{2}$ ]] || {
    echo "unsafe record identity: $record" >&2
    exit 1
  }
  fetch "$record.hea" 100000
  fetch "$record.dat" 1000000
done

export DOWNLOAD_DIR
python3 - <<'PY'
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re


download_dir = Path(os.environ["DOWNLOAD_DIR"])
expected_records = [f"bidmc{index:02d}" for index in range(1, 54)]
records = [line.strip() for line in (download_dir / "RECORDS").read_text().splitlines() if line.strip()]
if records != expected_records:
    raise SystemExit("official RECORDS inventory changed")

checksums: dict[str, str] = {}
for line in (download_dir / "SHA256SUMS.txt").read_text(encoding="utf-8").splitlines():
    match = re.fullmatch(r"([0-9a-fA-F]{64})\s+(.+)", line.strip())
    if not match:
        continue
    name = match.group(2).lstrip("*").removeprefix("./")
    checksums[name] = match.group(1).lower()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


inventory = []
for record in records:
    item: dict[str, object] = {"record_id": record}
    for kind, suffix in (("header", ".hea"), ("data", ".dat")):
        filename = record + suffix
        expected = checksums.get(filename)
        if expected is None:
            raise SystemExit(f"official SHA256 missing for {filename}")
        path = download_dir / filename
        actual = sha256_file(path)
        if actual != expected:
            raise SystemExit(f"SHA256 mismatch for {filename}: {actual} != {expected}")
        item[f"{kind}_file"] = filename
        item[f"{kind}_bytes"] = path.stat().st_size
        item[f"{kind}_sha256"] = actual
    inventory.append(item)

source_bytes = sum(int(item["data_bytes"]) for item in inventory)
if source_bytes != 34_200_570:
    raise SystemExit(f"aggregate waveform size changed: {source_bytes} != 34200570")
payload = {
    "candidate_id": "physionet_bidmc_ppg_resp_i16",
    "license_file": "LICENSE",
    "official_checksum_file": "SHA256SUMS.txt",
    "records": inventory,
    "source_bytes": source_bytes,
    "source_files": len(inventory) * 2,
}
(download_dir / "download_inventory.json").write_text(
    json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
)
print(f"records={len(inventory)} source_files={len(inventory) * 2} source_bytes={source_bytes}")
PY

echo "[$(date -Is)] download done candidate=$CANDIDATE_ID"
