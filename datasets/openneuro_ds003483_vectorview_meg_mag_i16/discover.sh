#!/usr/bin/env bash
# Documentation of how selection.tsv was resolved (not called by download.sh
# or build.sh). Uses small metadata requests only: one bucket listing, HEADs,
# and byte ranges for each candidate's FIFF_DIR_POINTER, trailing FIFF_DIR
# directory (about 25 KB) and leading FIFF_DATA_SKIP tag (20 bytes).
# Prints candidate selection rows to stdout; scratch goes to a temp dir.
set -euo pipefail

RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TOOL="$RECIPE_DIR/scripts/fif_meg.py"
BASE_URL="https://s3.amazonaws.com/openneuro.org"
COUNT="${COUNT:-6}"
SCRATCH="$(mktemp -d "${TMPDIR:-/tmp}/ds003483_discover.XXXXXX")"
trap 'rm -rf "$SCRATCH"' EXIT
CURL=(curl --fail --silent --show-error --location --retry 3 --max-time 120)

# 1. List the dataset prefix (331 keys in 2026-10; one page of <= 1000).
"${CURL[@]}" -o "$SCRATCH/list.xml" "$BASE_URL/?list-type=2&prefix=ds003483/"
grep -q '<IsTruncated>false</IsTruncated>' "$SCRATCH/list.xml" || { echo "listing truncated" >&2; exit 1; }

# 2. The COUNT smallest task-deduction run-1 FIF objects.
python3 - "$SCRATCH/list.xml" "$COUNT" > "$SCRATCH/keys.tsv" <<'PY'
import re, sys
xml = open(sys.argv[1]).read()
items = re.findall(r"<Key>([^<]+)</Key>.*?<Size>(\d+)</Size>", xml, re.S)
fifs = sorted((int(size), key) for key, size in items if key.endswith("_task-deduction_run-1_meg.fif"))
for size, key in fifs[: int(sys.argv[2])]:
    print(f"{key}\t{size}")
PY

printf 'subject\tsession\ttask\trun\tkey\tversion_id\tsize_bytes\tmd5\tdir_pointer\tn_buffers\tleading_skip_buffers\n'
while IFS=$'\t' read -r key listed_size; do
  url="$BASE_URL/$key"
  headers="$("${CURL[@]}" --head "$url" < /dev/null | tr -d '\r')"
  version="$(printf '%s\n' "$headers" | awk 'tolower($1)=="x-amz-version-id:"{print $2}')"
  length="$(printf '%s\n' "$headers" | awk 'tolower($1)=="content-length:"{print $2}')"
  etag="$(printf '%s\n' "$headers" | awk 'tolower($1)=="etag:"{gsub(/"/,"",$2); print $2}')"
  [[ "$length" == "$listed_size" && "$etag" != *-* ]] || { echo "unexpected HEAD for $key" >&2; exit 1; }
  pinned="$url?versionId=$version"
  "${CURL[@]}" --range 36-55 -o "$SCRATCH/ptr.bin" "$pinned" < /dev/null
  dir_pointer="$(python3 -c 'import struct,sys; k,t,s,n,v=struct.unpack(">5i",open(sys.argv[1],"rb").read()); assert (k,t,s)==(101,3,4); print(v)' "$SCRATCH/ptr.bin")"
  "${CURL[@]}" --range "$dir_pointer-" -o "$SCRATCH/tail.bin" "$pinned" < /dev/null
  summary="$(python3 "$TOOL" dir-summary --tail "$SCRATCH/tail.bin")"
  n_buffers="$(printf '%s' "$summary" | python3 -c 'import json,sys; d=json.load(sys.stdin); assert d["inner_skips"]==0 and d["buffer_types"]==[[16,640000]] and len(d["leading_skip_positions"])==1, d; print(d["n_buffers"])')"
  skip_pos="$(printf '%s' "$summary" | python3 -c 'import json,sys; print(json.load(sys.stdin)["leading_skip_positions"][0])')"
  "${CURL[@]}" --range "$skip_pos-$((skip_pos + 19))" -o "$SCRATCH/skip.bin" "$pinned" < /dev/null
  skip="$(python3 -c 'import struct,sys; k,t,s,n,v=struct.unpack(">5i",open(sys.argv[1],"rb").read()); assert (k,t,s)==(301,3,4); print(v)' "$SCRATCH/skip.bin")"
  name="${key##*/}"
  subject="${name%%_*}"
  printf '%s\tses-1\tdeduction\trun-1\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' \
    "$subject" "$key" "$version" "$length" "$etag" "$dir_pointer" "$n_buffers" "$skip"
done < "$SCRATCH/keys.tsv"
