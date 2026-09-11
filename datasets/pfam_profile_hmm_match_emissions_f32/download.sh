#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
CANDIDATE_ID="pfam_profile_hmm_match_emissions_f32"
RELEASE="38.2"
RELEASE_BASE="${PFAM_RELEASE_BASE:-https://ftp.ebi.ac.uk/pub/databases/Pfam/releases/Pfam38.2}"
ARCHIVE_URL="${PFAM_HMM_URL:-$RELEASE_BASE/Pfam-A.hmm.gz}"
RELNOTES_URL="${PFAM_RELNOTES_URL:-$RELEASE_BASE/relnotes.txt}"
CHECKSUMS_URL="${PFAM_CHECKSUMS_URL:-$RELEASE_BASE/md5_checksums}"
EXPECTED_ARCHIVE_BYTES=418160514
EXPECTED_ARCHIVE_MD5="7ab3c4e215d0daaea3004e37c4e24f8a"
EXPECTED_RELNOTES_SHA256="f84c96d00633adaae19227bd15625cfad87929b1b6c18fcc981050896c6b7d34"
EXPECTED_CHECKSUMS_SHA256="c4a4918552332c8093030578b52eb580c4dd2d940e5acc7fe3da44b1290f1c2d"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$CANDIDATE_ID"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$CANDIDATE_ID"
UA="openzl-public-datasets-pfam-profile-hmm/1.0"

mkdir -p "$DOWNLOAD_DIR" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
echo "[$(date -Is)] download start candidate=$CANDIDATE_ID release=$RELEASE"

download_small_exact() {
  local url="$1"
  local output="$2"
  local expected_sha256="$3"
  if [ ! -s "$output" ] || [ "${FORCE_DOWNLOAD:-0}" = "1" ]; then
    rm -f "$output.part"
    curl --fail --silent --show-error --location \
      --retry 5 --retry-delay 2 --retry-all-errors \
      --max-time 180 --max-filesize 2000000 \
      --user-agent "$UA" --output "$output.part" "$url"
    mv "$output.part" "$output"
  fi
  printf '%s  %s\n' "$expected_sha256" "$output" | sha256sum --check --status || {
    echo "FATAL: SHA-256 mismatch for $output" >&2
    exit 1
  }
}

download_small_exact "$RELNOTES_URL" "$DOWNLOAD_DIR/relnotes.txt" "$EXPECTED_RELNOTES_SHA256"
download_small_exact "$CHECKSUMS_URL" "$DOWNLOAD_DIR/md5_checksums" "$EXPECTED_CHECKSUMS_SHA256"

python3 - "$DOWNLOAD_DIR/relnotes.txt" "$DOWNLOAD_DIR/md5_checksums" \
  "$RELEASE" "$EXPECTED_ARCHIVE_MD5" <<'PY'
from __future__ import annotations

from pathlib import Path
import re
import sys


relnotes = Path(sys.argv[1]).read_text(encoding="utf-8", errors="strict")
checksums = Path(sys.argv[2]).read_text(encoding="ascii", errors="strict")
release = sys.argv[3]
expected_md5 = sys.argv[4]
if not re.search(rf"\bRELEASE\s+{re.escape(release)}\b", relnotes):
    raise SystemExit(f"release notes do not identify Pfam release {release}")
normalized_relnotes = re.sub(r"\s+", " ", relnotes)
license_patterns = (
    r"terms of the CC0 1\.0 license",
    r"dedicated the work to the public domain",
)
if not all(re.search(pattern, normalized_relnotes, flags=re.IGNORECASE) for pattern in license_patterns):
    raise SystemExit("release notes do not contain the expected CC0/public-domain grant")
checksum_match = re.search(
    r"^([0-9a-f]{32})\s+\*?Pfam-A\.hmm\.gz\s*$",
    checksums,
    flags=re.IGNORECASE | re.MULTILINE,
)
if not checksum_match or checksum_match.group(1).lower() != expected_md5:
    raise SystemExit("published Pfam-A.hmm.gz MD5 does not match the pinned value")
print(f"release_and_license_ok=1 release={release} license=CC0-1.0")
print(f"published_archive_md5={checksum_match.group(1).lower()}")
PY

archive="$DOWNLOAD_DIR/Pfam-A.hmm.gz"
if [ -s "$archive" ] && [ "${FORCE_DOWNLOAD:-0}" != "1" ]; then
  echo "cache_hit path=$archive"
else
  if [ "${FORCE_DOWNLOAD:-0}" = "1" ]; then
    rm -f "$archive" "$archive.tmp"
  fi
  echo "downloading url=$ARCHIVE_URL expected_bytes=$EXPECTED_ARCHIVE_BYTES"
  curl --fail --location --continue-at - \
    --retry 10 --retry-delay 5 --retry-all-errors \
    --speed-limit 1024 --speed-time 180 \
    --user-agent "$UA" --output "$archive.tmp" "$ARCHIVE_URL"
  mv "$archive.tmp" "$archive"
fi

actual_bytes="$(wc -c < "$archive" | tr -d ' ')"
if [ "$actual_bytes" != "$EXPECTED_ARCHIVE_BYTES" ]; then
  echo "FATAL: archive size mismatch: expected=$EXPECTED_ARCHIVE_BYTES actual=$actual_bytes" >&2
  exit 1
fi
printf '%s  %s\n' "$EXPECTED_ARCHIVE_MD5" "$archive" | md5sum --check --status || {
  echo "FATAL: archive MD5 mismatch" >&2
  exit 1
}
gzip -t "$archive"

echo "archive_validation=ok bytes=$actual_bytes md5=$EXPECTED_ARCHIVE_MD5"
echo "[$(date -Is)] download done candidate=$CANDIDATE_ID"
