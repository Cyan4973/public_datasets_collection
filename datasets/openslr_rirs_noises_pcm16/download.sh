#!/usr/bin/env bash
# Acquire the pinned official archive and inventory only the measured RIR subset.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
CANDIDATE_ID="openslr_rirs_noises_pcm16"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$CANDIDATE_ID"
METADATA_DIR="$DOWNLOAD_DIR/metadata"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$CANDIDATE_ID"
PAGE_URL="https://www.openslr.org/28/"
ARCHIVE_URL="https://www.openslr.org/resources/28/rirs_noises.zip"
ARCHIVE_SIZE="1311166223"
ARCHIVE_ETAG="4e26cf0f-55aaceedf12a1"
ARCHIVE_SHA256="3b50cfde915b3984738169b4beb341e9f6b8062ae4c2076146c5db71c2c05dc7"
ARCHIVE="$DOWNLOAD_DIR/rirs_noises.zip"

mkdir -p "$DOWNLOAD_DIR" "$METADATA_DIR" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
echo "[$(date -Is)] download start candidate=$CANDIDATE_ID"

curl --fail --show-error --location --retry 3 --retry-all-errors \
  --max-time 180 --max-filesize 5000000 \
  --user-agent "openzl-public-datasets-openslr-rirs/1.0" \
  --output "$METADATA_DIR/resource_page.html.part" "$PAGE_URL"
mv "$METADATA_DIR/resource_page.html.part" "$METADATA_DIR/resource_page.html"

export ARCHIVE ARCHIVE_SIZE ARCHIVE_ETAG ARCHIVE_SHA256 ARCHIVE_URL DOWNLOAD_DIR METADATA_DIR
python3 - <<'PY'
from html.parser import HTMLParser
import os
from pathlib import Path
import re


class Text(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


page = Path(os.environ["METADATA_DIR"]) / "resource_page.html"
parser = Text()
parser.feed(page.read_text(errors="replace"))
text = " ".join(" ".join(parser.parts).split())
if not re.search(r"License\s*:\s*Apache\s*2\.0", text, re.I):
    raise SystemExit("official resource page no longer states License: Apache 2.0")
if not re.search(r"16\s*[- ]?bit precision", text, re.I):
    raise SystemExit("official resource page no longer states 16-bit precision")
print("validated official page: Apache 2.0, 16-bit precision")
PY

if [[ -f "$ARCHIVE" ]]; then
  actual_size="$(stat -c %s "$ARCHIVE")"
  if [[ "$actual_size" != "$ARCHIVE_SIZE" ]]; then
    echo "existing archive has unexpected size: $actual_size" >&2
    exit 1
  fi
  echo "using existing archive bytes=$actual_size"
else
  touch "$ARCHIVE.part"
  part_size="$(stat -c %s "$ARCHIVE.part")"
  if (( part_size > ARCHIVE_SIZE )); then
    echo "partial archive exceeds expected size: $part_size" >&2
    exit 1
  fi
  echo "fetch archive resume_at=$part_size expected_bytes=$ARCHIVE_SIZE"
  curl --fail --show-error --location --retry 5 --retry-all-errors \
    --retry-delay 3 --max-time 7200 --continue-at - \
    --header "If-Match: \"$ARCHIVE_ETAG\"" \
    --user-agent "openzl-public-datasets-openslr-rirs/1.0" \
    --output "$ARCHIVE.part" "$ARCHIVE_URL"
  actual_size="$(stat -c %s "$ARCHIVE.part")"
  if [[ "$actual_size" != "$ARCHIVE_SIZE" ]]; then
    echo "archive size mismatch: got=$actual_size expected=$ARCHIVE_SIZE" >&2
    exit 1
  fi
  mv "$ARCHIVE.part" "$ARCHIVE"
fi

python3 - <<'PY'
from __future__ import annotations

from collections import Counter
import csv
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import zipfile


archive = Path(os.environ["ARCHIVE"])
download_dir = Path(os.environ["DOWNLOAD_DIR"])
expected_size = int(os.environ["ARCHIVE_SIZE"])
if archive.stat().st_size != expected_size:
    raise SystemExit("archive changed size before validation")

digest = hashlib.sha256()
with archive.open("rb") as handle:
    while chunk := handle.read(8 * 1024 * 1024):
        digest.update(chunk)
sha256 = digest.hexdigest()
if sha256 != os.environ["ARCHIVE_SHA256"]:
    raise SystemExit(
        f"archive SHA-256 mismatch: got={sha256} expected={os.environ['ARCHIVE_SHA256']}"
    )

prefix = "RIRS_NOISES/real_rirs_isotropic_noises/"
patterns = (
    ("AIR", re.compile(r"^air_type1_air_")),
    ("REVERB2014", re.compile(r"^RVB2014_type[12]_rir_")),
    ("RWCP", re.compile(r"^RWCP_type[1-4]_rir_")),
)

rows: list[dict[str, object]] = []
with zipfile.ZipFile(archive) as zf:
    infos = zf.infolist()
    paths = [info.filename for info in infos]
    if len(paths) != 61880 or len(set(paths)) != len(paths):
        raise SystemExit("unexpected ZIP member count or duplicate member path")
    for info in infos:
        if not info.filename.startswith(prefix) or info.is_dir():
            continue
        name = PurePosixPath(info.filename).name
        family = next((label for label, pattern in patterns if pattern.match(name)), None)
        if family is None:
            continue
        if info.flag_bits & 1:
            raise SystemExit(f"encrypted selected member: {info.filename}")
        if info.compress_type not in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}:
            raise SystemExit(f"unsupported compression method: {info.filename}")
        rows.append(
            {
                "family": family,
                "path": info.filename,
                "crc32": f"{info.CRC:08x}",
                "compressed_size": info.compress_size,
                "uncompressed_size": info.file_size,
            }
        )

counts = Counter(str(row["family"]) for row in rows)
expected_counts = {"AIR": 107, "REVERB2014": 36, "RWCP": 182}
if counts != expected_counts or len(rows) != 325:
    raise SystemExit(f"selected-member mismatch: counts={dict(counts)} total={len(rows)}")
if sum(int(row["uncompressed_size"]) for row in rows) != 133979812:
    raise SystemExit("selected uncompressed byte total changed")

inventory = download_dir / "selected_members.tsv"
with inventory.open("w", newline="") as handle:
    writer = csv.DictWriter(
        handle,
        fieldnames=["family", "path", "crc32", "compressed_size", "uncompressed_size"],
        delimiter="\t",
        lineterminator="\n",
    )
    writer.writeheader()
    writer.writerows(rows)

record = {
    "archive_url": os.environ["ARCHIVE_URL"],
    "archive_size_bytes": expected_size,
    "discovery_etag": f'"{os.environ["ARCHIVE_ETAG"]}"',
    "sha256": sha256,
    "zip_members": 61880,
    "selected_members": len(rows),
    "selected_counts": dict(sorted(counts.items())),
    "selected_uncompressed_wav_bytes": sum(int(row["uncompressed_size"]) for row in rows),
}
(download_dir / "acquisition.json").write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")
print(f"archive_sha256={sha256}")
print(f"selected measured RIR WAVs={len(rows)} counts={dict(sorted(counts.items()))}")
print(f"selected WAV bytes={record['selected_uncompressed_wav_bytes']}")
PY

echo "[$(date -Is)] download done candidate=$CANDIDATE_ID"
