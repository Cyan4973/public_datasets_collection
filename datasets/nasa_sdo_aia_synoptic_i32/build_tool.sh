#!/usr/bin/env bash
# Build only the official CFITSIO funpack decoder using its normal build system.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="nasa_sdo_aia_synoptic_i32"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DOWNLOAD_TOOL_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID/tool"
BUILD_ROOT="$REPO_ROOT/$DATA_DIR/tools/$DATASET_ID"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
JOBS="${JOBS:-2}"

mkdir -p "$BUILD_ROOT" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/build_tool.$RUN_TS.log" "$LOG_DIR/build_tool.latest.log") 2>&1
echo "[$(date -Is)] CFITSIO build start dataset=$DATASET_ID"

mapfile -t archives < <(find "$DOWNLOAD_TOOL_DIR" -maxdepth 1 -type f -name 'cfitsio-*.tar.gz' -print | sort)
[[ "${#archives[@]}" == "1" ]] || {
  echo "expected exactly one versioned CFITSIO tarball, found ${#archives[@]}" >&2
  exit 1
}
archive="${archives[0]}"

python3 - "$archive" "$RECIPE_DIR/tool_selection.tsv" <<'PY'
import csv
import hashlib
from pathlib import Path
import sys

archive = Path(sys.argv[1])
with Path(sys.argv[2]).open(encoding="utf-8", newline="") as handle:
    rows = list(csv.DictReader(handle, delimiter="\t"))
if len(rows) != 1:
    raise SystemExit("tool selection must contain exactly one CFITSIO source")
row = rows[0]
digest = hashlib.sha256(archive.read_bytes()).hexdigest()
if archive.name != row["filename"] or archive.stat().st_size != int(row["size_bytes"]) or digest != row["sha256"]:
    raise SystemExit(f"CFITSIO source identity mismatch: {archive}")
print(f"validated CFITSIO {row['version']} source")
PY

python3 - "$archive" <<'PY'
from pathlib import Path, PurePosixPath
import sys
import tarfile

path = Path(sys.argv[1])
with tarfile.open(path, "r:gz") as archive:
    members = archive.getmembers()
    if not members or len(members) > 10_000:
        raise SystemExit(f"unexpected CFITSIO archive member count: {len(members)}")
    roots = set()
    for member in members:
        parsed = PurePosixPath(member.name)
        if parsed.is_absolute() or ".." in parsed.parts:
            raise SystemExit(f"unsafe CFITSIO archive member: {member.name}")
        if member.issym() or member.islnk():
            raise SystemExit(f"CFITSIO archive contains link member: {member.name}")
        if parsed.parts:
            roots.add(parsed.parts[0])
    if len(roots) != 1:
        raise SystemExit(f"unexpected CFITSIO archive roots: {sorted(roots)}")
    root = next(iter(roots))
    if not root.lower().startswith("cfitsio"):
        raise SystemExit(f"unexpected CFITSIO source root: {root}")
print(root)
PY

source_root="$(python3 - "$archive" <<'PY'
from pathlib import PurePosixPath
import sys, tarfile
with tarfile.open(sys.argv[1], "r:gz") as archive:
    print(PurePosixPath(archive.getmembers()[0].name).parts[0])
PY
)"
rm -rf "$BUILD_ROOT/src" "$BUILD_ROOT/bin"
mkdir -p "$BUILD_ROOT/src" "$BUILD_ROOT/bin"
tar -xzf "$archive" -C "$BUILD_ROOT/src"
source_dir="$BUILD_ROOT/src/$source_root"
[[ -x "$source_dir/configure" ]] || { echo "CFITSIO configure script missing" >&2; exit 1; }

(
  cd "$source_dir"
  ./configure --disable-shared
  make -j"$JOBS" funpack
)

funpack=""
for candidate in "$source_dir/funpack" "$source_dir/utilities/funpack"; do
  if [[ -x "$candidate" ]]; then
    funpack="$candidate"
    break
  fi
done
[[ -n "$funpack" ]] || { echo "CFITSIO build completed without a funpack executable" >&2; exit 1; }
cp "$funpack" "$BUILD_ROOT/bin/funpack"
"$BUILD_ROOT/bin/funpack" -V
echo "[$(date -Is)] CFITSIO build done binary=$BUILD_ROOT/bin/funpack"
