#!/usr/bin/env bash
# Prove that the pinned official decoder is a conventional local source build.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
CANDIDATE_ID="zenodo_nanopore_slow5_i16"
TOOL_ROOT="$REPO_ROOT/$DATA_DIR/tools/slow5tools_probe"
SOURCE_DIR="$TOOL_ROOT/source"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$CANDIDATE_ID"
REPORT_DIR="$REPO_ROOT/$DATA_DIR/discovery/$CANDIDATE_ID"
REPOSITORY_URL="https://github.com/hasindu2008/slow5tools.git"
PINNED_TAG="v1.4.0"
PINNED_COMMIT="f73fc6b8f65813b7b1f5d787934d790e5d58b90f"
PINNED_SLOW5LIB_COMMIT="e4bf785d696ce70eec4e54c37cbbdda19c25cc50"
FIXTURE_REL="test/data/raw/merge/zlib_svb-zd_v0.2.0.blow5"
FIXTURE_SHA256="8cabc638c0f933eee3dea2063fbaf8a3cec75695fab49398c1e0b1c9ff801f9f"
MAX_CHECKOUT_BYTES=$((600 * 1024 * 1024))
MAX_BUILD_TREE_BYTES=$((25 * 1024 * 1024))

mkdir -p "$TOOL_ROOT" "$LOG_DIR" "$REPORT_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/tooling_preflight.$RUN_TS.log"
exec > >(tee "$LOG_FILE" "$LOG_DIR/tooling_preflight.latest.log") 2>&1
echo "[$(date -Is)] tooling preflight start candidate=$CANDIDATE_ID"

for tool in git make cc g++ timeout find ldd sha256sum python3; do
  command -v "$tool" >/dev/null 2>&1 || {
    echo "required existing build tool is missing: $tool" >&2
    exit 1
  }
done

if [[ -e "$SOURCE_DIR" ]]; then
  [[ -d "$SOURCE_DIR/.git" ]] || {
    echo "existing probe path is not a Git checkout: $SOURCE_DIR" >&2
    exit 1
  }
  actual_origin="$(git -C "$SOURCE_DIR" remote get-url origin)"
  [[ "$actual_origin" == "$REPOSITORY_URL" ]] || {
    echo "unexpected existing checkout origin: $actual_origin" >&2
    exit 1
  }
  echo "using existing source checkout: $SOURCE_DIR"
else
  git clone --depth 1 --branch "$PINNED_TAG" --recurse-submodules --shallow-submodules \
    "$REPOSITORY_URL" "$SOURCE_DIR"
fi

[[ -f "$SOURCE_DIR/Makefile" ]] || {
  echo "official source has no top-level Makefile" >&2
  exit 1
}

COMMIT="$(git -C "$SOURCE_DIR" rev-parse HEAD)"
[[ "$COMMIT" == "$PINNED_COMMIT" ]] || {
  echo "slow5tools commit mismatch: $COMMIT != $PINNED_COMMIT" >&2
  exit 1
}
SLOW5LIB_COMMIT="$(git -C "$SOURCE_DIR/slow5lib" rev-parse HEAD)"
[[ "$SLOW5LIB_COMMIT" == "$PINNED_SLOW5LIB_COMMIT" ]] || {
  echo "slow5lib commit mismatch: $SLOW5LIB_COMMIT != $PINNED_SLOW5LIB_COMMIT" >&2
  exit 1
}

CHECKOUT_BYTES="$(du -sb "$SOURCE_DIR" | awk '{print $1}')"
BUILD_TREE_BYTES="$(SOURCE_DIR="$SOURCE_DIR" python3 - <<'PY'
import os
from pathlib import Path

root = Path(os.environ["SOURCE_DIR"])
total = 0
for path in root.rglob("*"):
    if not path.is_file():
        continue
    relative = path.relative_to(root)
    if ".git" in relative.parts or relative.parts[0] == "test":
        continue
    if len(relative.parts) > 1 and relative.parts[0] == "slow5lib" and relative.parts[1] == "test":
        continue
    total += path.stat().st_size
print(total)
PY
)"
SUBMODULE_STATUS="$(git -C "$SOURCE_DIR" submodule status --recursive || true)"
if [[ -n "$SUBMODULE_STATUS" ]]; then
  SUBMODULE_COUNT="$(printf '%s\n' "$SUBMODULE_STATUS" | wc -l)"
else
  SUBMODULE_COUNT=0
fi
echo "source_tag=$PINNED_TAG"
echo "source_commit=$COMMIT"
echo "slow5lib_commit=$SLOW5LIB_COMMIT"
echo "checkout_bytes=$CHECKOUT_BYTES"
echo "build_tree_bytes=$BUILD_TREE_BYTES"
echo "recursive_submodules=$SUBMODULE_COUNT"
printf '%s\n' "$SUBMODULE_STATUS"
(( CHECKOUT_BYTES <= MAX_CHECKOUT_BYTES )) || {
  echo "source checkout exceeds $MAX_CHECKOUT_BYTES bytes" >&2
  exit 1
}
(( BUILD_TREE_BYTES <= MAX_BUILD_TREE_BYTES )) || {
  echo "build-relevant source exceeds $MAX_BUILD_TREE_BYTES bytes" >&2
  exit 1
}
(( SUBMODULE_COUNT == 1 )) || {
  echo "source checkout does not have exactly one recursive submodule" >&2
  exit 1
}

LICENSE_PATH="$SOURCE_DIR/LICENSE"
[[ -f "$LICENSE_PATH" ]] || {
  echo "official source has no top-level LICENSE" >&2
  exit 1
}
LICENSE_SHA256="$(sha256sum "$LICENSE_PATH" | awk '{print $1}')"
[[ "$LICENSE_SHA256" == "288911e425cb7b194409c97e569e82a8a159e6ef604adae086e1484e31d0ca67" ]] || {
  echo "pinned slow5tools license hash mismatch" >&2
  exit 1
}
echo "license_file=LICENSE"
echo "license_sha256=$LICENSE_SHA256"

MAKE_PLAN="$TOOL_ROOT/slow5_only_make_plan.txt"
make -n -C "$SOURCE_DIR" disable_hdf5=1 > "$MAKE_PLAN"
if grep -E '(curl|wget|git[[:space:]]+(clone|fetch|pull)|pip[0-9]*[[:space:]]+install|conda|apt(-get)?|dnf|yum)[[:space:]]' "$MAKE_PLAN"; then
  echo "S/BLOW5-only make plan attempts a network fetch or package installation" >&2
  exit 1
fi

BUILD_START="$(date +%s)"
if ! timeout 300 make -C "$SOURCE_DIR" -j2 disable_hdf5=1; then
  echo "documented S/BLOW5-only make failed or exceeded five minutes; do not install dependencies" >&2
  exit 1
fi
BUILD_SECONDS=$(( $(date +%s) - BUILD_START ))

SLOW5TOOLS_BIN="$SOURCE_DIR/slow5tools"
[[ -x "$SLOW5TOOLS_BIN" ]] || {
  echo "build completed but produced no executable slow5tools" >&2
  exit 1
}
VERSION_OUTPUT="$($SLOW5TOOLS_BIN --version 2>&1)" || {
  echo "built executable failed --version" >&2
  exit 1
}

FIXTURE="$SOURCE_DIR/$FIXTURE_REL"
[[ -f "$FIXTURE" ]] || {
  echo "pinned SVB-ZD fixture is missing: $FIXTURE" >&2
  exit 1
}
[[ "$(sha256sum "$FIXTURE" | awk '{print $1}')" == "$FIXTURE_SHA256" ]] || {
  echo "pinned SVB-ZD fixture hash mismatch" >&2
  exit 1
}
SMOKE_OUTPUT="$TOOL_ROOT/zlib_svb-zd_v0.2.0.decoded.slow5"
"$SLOW5TOOLS_BIN" view "$FIXTURE" -o "$SMOKE_OUTPUT"
[[ -s "$SMOKE_OUTPUT" ]] || {
  echo "SVB-ZD functional decode produced no output" >&2
  exit 1
}
grep -a -F -q 'int16_t*' "$SMOKE_OUTPUT" || {
  echo "decoded SLOW5 schema does not declare an int16 raw signal" >&2
  exit 1
}
SMOKE_SHA256="$(sha256sum "$SMOKE_OUTPUT" | awk '{print $1}')"

echo "build_seconds=$BUILD_SECONDS"
echo "binary=$SLOW5TOOLS_BIN"
echo "binary_sha256=$(sha256sum "$SLOW5TOOLS_BIN" | awk '{print $1}')"
echo "version_output=$VERSION_OUTPUT"
echo "fixture_sha256=$FIXTURE_SHA256"
echo "decoded_fixture_bytes=$(wc -c < "$SMOKE_OUTPUT" | tr -d ' ')"
echo "decoded_fixture_sha256=$SMOKE_SHA256"
echo "dynamic_dependencies:"
ldd "$SLOW5TOOLS_BIN"

REPORT="$REPORT_DIR/slow5tools_build_preflight.tsv"
{
  printf 'repository_url\ttag\tcommit\tslow5lib_commit\tcheckout_bytes\tbuild_tree_bytes\trecursive_submodules\tbuild_seconds\tbinary_sha256\tfixture_sha256\tdecoded_fixture_sha256\tversion_output\n'
  printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' \
    "$REPOSITORY_URL" "$PINNED_TAG" "$COMMIT" "$SLOW5LIB_COMMIT" \
    "$CHECKOUT_BYTES" "$BUILD_TREE_BYTES" "$SUBMODULE_COUNT" "$BUILD_SECONDS" \
    "$(sha256sum "$SLOW5TOOLS_BIN" | awk '{print $1}')" "$FIXTURE_SHA256" \
    "$SMOKE_SHA256" "$(printf '%s' "$VERSION_OUTPUT" | tr '\t\n' '  ')"
} > "$REPORT"

echo "report=$REPORT"
echo "[$(date -Is)] tooling preflight passed candidate=$CANDIDATE_ID"
