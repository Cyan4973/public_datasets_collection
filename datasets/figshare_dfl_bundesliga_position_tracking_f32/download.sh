#!/usr/bin/env bash
# Download the seven pinned DFL positions_raw_observed XML files from figshare
# article 28196177 v1 (Bassek et al. 2025, CC BY 4.0).
#
# ndownloader.figshare.com redirects to S3 presigned URLs that expire ~10 s
# after issue, so every curl invocation (including every resume) re-requests
# the stable ndownloader URL with -L. Resumes use an outer retry loop with
# `curl -C -` instead of curl's internal --retry, so each attempt recomputes
# the resume offset from the .part size and obtains a fresh signed URL.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="figshare_dfl_bundesliga_position_tracking_f32"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
ARTICLE_ID=28196177
API_URL="https://api.figshare.com/v2/articles/$ARTICLE_ID"
SOURCES="$RECIPE_DIR/sources.tsv"
UA="openzl-public-datasets-dfl-tracking/1.0"
MAX_ATTEMPTS="${MAX_ATTEMPTS:-30}"

mkdir -p "$DOWNLOAD_DIR" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
echo "[$(date -Is)] download start dataset=$DATASET_ID"

# 1. Article metadata: identity, license, and per-file size/MD5 must match the pins.
metadata="$DOWNLOAD_DIR/article_$ARTICLE_ID.json"
rm -f "$metadata.part"
curl --fail --silent --show-error --location \
  --retry 5 --retry-delay 3 --retry-all-errors \
  --max-time 120 --max-filesize 5000000 \
  --user-agent "$UA" --header "Accept: application/json" \
  --output "$metadata.part" "$API_URL"
mv "$metadata.part" "$metadata"

python3 -I - "$metadata" "$SOURCES" "$ARTICLE_ID" <<'PY'
import json
import sys

meta_path, sources_path, article_id = sys.argv[1], sys.argv[2], int(sys.argv[3])
with open(meta_path, encoding="utf-8") as handle:
    article = json.load(handle)
if int(article.get("id") or 0) != article_id:
    raise SystemExit(f"unexpected article id {article.get('id')!r}")
title = str(article.get("title") or "")
if "spatiotemporal and event data in elite soccer" not in title.lower():
    raise SystemExit(f"unexpected article title {title!r}")
if int(article.get("version") or 0) != 1:
    raise SystemExit(f"article version changed: {article.get('version')!r}")
lic = article.get("license") or {}
if lic.get("name") != "CC BY" or "creativecommons.org/licenses/by/4.0" not in str(lic.get("url")):
    raise SystemExit(f"license changed: {lic!r}")
files = {int(item["id"]): item for item in article.get("files") or []}
count = 0
with open(sources_path, encoding="utf-8") as handle:
    for line in handle:
        if not line.strip():
            continue
        fid, name, size, md5 = line.rstrip("\n").split("\t")
        item = files.get(int(fid))
        if item is None:
            raise SystemExit(f"file {fid} missing from article")
        if item.get("name") != name or int(item.get("size") or -1) != int(size):
            raise SystemExit(f"file {fid} name/size changed: {item.get('name')!r} {item.get('size')!r}")
        if str(item.get("computed_md5") or "").lower() != md5:
            raise SystemExit(f"file {fid} md5 changed: {item.get('computed_md5')!r}")
        count += 1
if count != 7:
    raise SystemExit(f"expected 7 pinned files, found {count}")
print(f"metadata_validation=ok article={article_id} v1 license=CC-BY-4.0 pinned_files={count}")
PY

validate_xml() {
  # $1 path, $2 expected size, $3 expected md5, $4 expected match id
  local path="$1" size="$2" md5="$3" match="$4"
  local actual
  actual="$(stat -c %s "$path")"
  if [ "$actual" != "$size" ]; then
    echo "size mismatch for $path: expected=$size actual=$actual" >&2
    return 1
  fi
  actual="$(md5sum "$path" | cut -d' ' -f1)"
  if [ "$actual" != "$md5" ]; then
    echo "md5 mismatch for $path: expected=$md5 actual=$actual" >&2
    return 1
  fi
  python3 -I - "$path" "$match" <<'PY'
import sys

path, match = sys.argv[1], sys.argv[2]
with open(path, "rb") as handle:
    head = handle.read(4096)
    handle.seek(-256, 2)
    tail = handle.read()
if not head.startswith(b"<?xml") or b"<PutDataRequest" not in head or b"<Positions" not in head:
    raise SystemExit(f"{path}: not a DFL PutDataRequest/Positions document")
if f'MatchId="{match}"'.encode() not in head or b"<FrameSet " not in head:
    raise SystemExit(f"{path}: header lacks MatchId {match} or FrameSet")
if not tail.rstrip().endswith(b"</PutDataRequest>") or b"</Positions>" not in tail:
    raise SystemExit(f"{path}: truncated (no closing </PutDataRequest>)")
if b"</FrameSet>" not in tail:
    raise SystemExit(f"{path}: last FrameSet not closed")
print(f"xml_validation=ok {path.rsplit('/', 1)[-1]}")
PY
}

# 2. Position XMLs.
while IFS=$'\t' read -r fid name size md5; do
  [ -n "$fid" ] || continue
  match="${name##*_}"
  match="${match%.xml}"
  out="$DOWNLOAD_DIR/$name"
  part="$out.part"
  url="https://ndownloader.figshare.com/files/$fid"
  if [ -f "$out" ] && [ "${FORCE_DOWNLOAD:-0}" != "1" ]; then
    if validate_xml "$out" "$size" "$md5" "$match"; then
      echo "cache_hit file=$name"
      continue
    fi
    echo "cached file invalid, re-downloading: $name"
    rm -f "$out"
  fi
  if [ "${FORCE_DOWNLOAD:-0}" = "1" ]; then rm -f "$out" "$part"; fi
  attempt=0
  while :; do
    have=0
    [ -f "$part" ] && have="$(stat -c %s "$part")"
    if [ "$have" -gt "$size" ]; then
      echo "partial larger than expected; discarding $part"
      rm -f "$part"
      have=0
    fi
    if [ "$have" -eq "$size" ]; then
      break
    fi
    attempt=$((attempt + 1))
    if [ "$attempt" -gt "$MAX_ATTEMPTS" ]; then
      echo "FATAL: giving up on $name after $MAX_ATTEMPTS attempts (have=$have of $size)" >&2
      exit 1
    fi
    echo "[$(date -Is)] fetch $name attempt=$attempt resume_from=$have size=$size"
    if ! curl --fail --location --silent --show-error \
        --continue-at - --speed-limit 1024 --speed-time 120 \
        --connect-timeout 60 --user-agent "$UA" \
        --output "$part" "$url"; then
      echo "curl attempt $attempt failed for $name; retrying in 10 s"
      sleep 10
    fi
  done
  if ! validate_xml "$part" "$size" "$md5" "$match"; then
    echo "FATAL: downloaded payload invalid for $name; removing partial" >&2
    rm -f "$part"
    exit 1
  fi
  mv "$part" "$out"
  echo "[$(date -Is)] done file=$name bytes=$size"
done < "$SOURCES"

echo "[$(date -Is)] download done dataset=$DATASET_ID"
