#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="zenodo_nanopore_slow5_i16"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
TOOL_SOURCE="$REPO_ROOT/$DATA_DIR/tools/slow5tools_probe/source"
SLOW5TOOLS="$TOOL_SOURCE/slow5tools"
TARGET="$DOWNLOAD_DIR/SIRV_from_MNXKXX240359.blow5"
RECORD_JSON="$DOWNLOAD_DIR/record_14676368.json"
RECORD_URL="https://zenodo.org/api/records/14676368"
CONTENT_URL="https://zenodo.org/api/records/14676368/files/SIRV_from_MNXKXX240359.blow5/content"
EXPECTED_BYTES=717345984
EXPECTED_MD5="fa088d06040ef3202a61b01f49b1d831"
PINNED_TOOL_COMMIT="f73fc6b8f65813b7b1f5d787934d790e5d58b90f"
PINNED_LIB_COMMIT="e4bf785d696ce70eec4e54c37cbbdda19c25cc50"

mkdir -p "$DOWNLOAD_DIR" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
echo "[$(date -Is)] download start dataset=$DATASET_ID"

[[ -x "$SLOW5TOOLS" ]] || {
  echo "missing proven decoder; run probe_slow5tools_build.sh first" >&2
  exit 1
}
[[ "$(git -C "$TOOL_SOURCE" rev-parse HEAD)" == "$PINNED_TOOL_COMMIT" ]] || {
  echo "slow5tools checkout is not the pinned commit" >&2
  exit 1
}
[[ "$(git -C "$TOOL_SOURCE/slow5lib" rev-parse HEAD)" == "$PINNED_LIB_COMMIT" ]] || {
  echo "slow5lib checkout is not the pinned commit" >&2
  exit 1
}

curl --fail --silent --show-error --location --retry 4 --retry-delay 2 \
  --max-time 300 --max-filesize 20000000 --output "$RECORD_JSON.part" "$RECORD_URL"
mv "$RECORD_JSON.part" "$RECORD_JSON"

RECORD_JSON="$RECORD_JSON" python3 - <<'PY'
import json
import os
from pathlib import Path

path = Path(os.environ["RECORD_JSON"])
record = json.loads(path.read_text(encoding="utf-8"))
metadata = record.get("metadata", {})
if int(record.get("id", 0)) != 14676368:
    raise SystemExit("unexpected Zenodo record ID")
if metadata.get("title") != "Nanopore RNA004 MinION SIRV synthetic raw signal data":
    raise SystemExit("unexpected Zenodo record title")
license_info = metadata.get("license", {})
if not isinstance(license_info, dict) or license_info.get("id") != "cc-by-4.0":
    raise SystemExit("record no longer declares CC BY 4.0")
files = record.get("files", [])
items = {str(item.get("key", "")): item for item in files if isinstance(item, dict)}
item = items.get("SIRV_from_MNXKXX240359.blow5")
if item is None or int(item.get("size", 0)) != 717345984:
    raise SystemExit("pinned BLOW5 file identity changed")
if item.get("checksum") != "md5:fa088d06040ef3202a61b01f49b1d831":
    raise SystemExit("pinned BLOW5 MD5 changed")
print("record_validation=ok license=cc-by-4.0")
PY

if [[ -s "$TARGET" && "${FORCE_DOWNLOAD:-0}" != "1" ]]; then
  echo "cache_hit path=$TARGET"
else
  curl --fail --location --retry 4 --retry-delay 5 --max-time 7200 \
    --max-filesize 750000000 --output "$TARGET.part" "$CONTENT_URL"
  mv "$TARGET.part" "$TARGET"
fi

ACTUAL_BYTES="$(wc -c < "$TARGET" | tr -d ' ')"
[[ "$ACTUAL_BYTES" == "$EXPECTED_BYTES" ]] || {
  echo "source size mismatch: $ACTUAL_BYTES != $EXPECTED_BYTES" >&2
  exit 1
}
ACTUAL_MD5="$(md5sum "$TARGET" | awk '{print $1}')"
[[ "$ACTUAL_MD5" == "$EXPECTED_MD5" ]] || {
  echo "source MD5 mismatch: $ACTUAL_MD5 != $EXPECTED_MD5" >&2
  exit 1
}

TARGET="$TARGET" python3 - <<'PY'
import os
from pathlib import Path

path = Path(os.environ["TARGET"])
with path.open("rb") as handle:
    header = handle.read(128 * 1024)
if header[:6] != b"BLOW5\x01":
    raise SystemExit(f"unexpected BLOW5 magic: {header[:8]!r}")
required = (b"@data_source\treal_device", b"@is_simulated\t0", b"@sample_frequency\t4000", b"int16_t*")
missing = [item.decode("ascii") for item in required if item not in header]
if missing:
    raise SystemExit(f"BLOW5 header lacks required semantics: {missing}")
print("header_validation=ok raw_signal=int16_t data_source=real_device is_simulated=0 sample_frequency=4000")
PY

"$SLOW5TOOLS" quickcheck "$TARGET"
SHA256="$(sha256sum "$TARGET" | awk '{print $1}')"
export DOWNLOAD_DIR TARGET ACTUAL_BYTES ACTUAL_MD5 SHA256 PINNED_TOOL_COMMIT PINNED_LIB_COMMIT
python3 - <<'PY'
import json
import os
from pathlib import Path

payload = {
    "dataset_id": "zenodo_nanopore_slow5_i16",
    "file": Path(os.environ["TARGET"]).name,
    "source_bytes": int(os.environ["ACTUAL_BYTES"]),
    "md5": os.environ["ACTUAL_MD5"],
    "sha256": os.environ["SHA256"],
    "record_id": 14676368,
    "license": "cc-by-4.0",
    "slow5tools_commit": os.environ["PINNED_TOOL_COMMIT"],
    "slow5lib_commit": os.environ["PINNED_LIB_COMMIT"],
}
path = Path(os.environ["DOWNLOAD_DIR"]) / "download_inventory.json"
path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
PY

echo "source_sha256=$SHA256"
echo "[$(date -Is)] download done dataset=$DATASET_ID bytes=$ACTUAL_BYTES"
