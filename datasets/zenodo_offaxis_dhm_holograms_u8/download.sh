#!/usr/bin/env bash
# Range-fetch 102 pinned hologram TIFF members (6 evenly spaced frames from
# each of the 17 405 nm DHM videos) out of the Zenodo 10632465 zips, without
# downloading the 22 GB of whole archives.
#
# For every zip: re-validate the record (CC0, size, MD5), fetch the exact
# central directory + EOCD range, reject ZIP64 / non-deflate members, check
# the pinned members against the live directory. For every frame: fetch
# exactly [local header offset, next entry offset), check HTTP 206 and the
# Content-Range, validate the local header, inflate, check CRC32 and size
# against the central directory and check the TIFF IFD (2048x2048, 8 bps,
# spp 1, LZW, predictor 2). Only the validated .tif is kept.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="zenodo_offaxis_dhm_holograms_u8"
DL="$DATA_ROOT/downloads/$DATASET_ID"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
API_URL="https://zenodo.org/api/records/10632465"
README_URL="https://zenodo.org/api/records/10632465/files/README.md/content"
README_MD5="56361931b6db1ccede5acabe4dd622c0"
UA="openzl-public-datasets-dhm-holograms/1.0"
VIDEOS="$RECIPE_DIR/videos.tsv"
SELECTED="$RECIPE_DIR/selected_frames.tsv"
PY="python3 -I $RECIPE_DIR/scripts/dhm_zip.py"
CURL=(curl --fail --silent --show-error --location --retry 10 --retry-delay 5 --retry-all-errors
      --speed-limit 1024 --speed-time 120 --user-agent "$UA")

mkdir -p "$DL/cd" "$DL/members" "$DL/tif" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
echo "[$(date -Is)] download start dataset=$DATASET_ID"

# 1. Record metadata and README (small, always refreshed).
rm -f "$DL/record.json.part"
"${CURL[@]}" --max-time 180 --max-filesize 20000000 -H "Accept: application/json" \
  -o "$DL/record.json.part" "$API_URL"
mv "$DL/record.json.part" "$DL/record.json"
$PY check-record "$DL/record.json" "$VIDEOS"

if [ ! -s "$DL/README.md" ] || ! printf '%s  %s\n' "$README_MD5" "$DL/README.md" | md5sum --check --status; then
  rm -f "$DL/README.md.part"
  "${CURL[@]}" --max-time 180 --max-filesize 100000 -o "$DL/README.md.part" "$README_URL"
  printf '%s  %s\n' "$README_MD5" "$DL/README.md.part" | md5sum --check --status \
    || { echo "FATAL: README.md MD5 mismatch" >&2; exit 1; }
  mv "$DL/README.md.part" "$DL/README.md"
fi
$PY check-readme "$DL/README.md"

# 2. Central directories (exact range cd_offset..end) and pin checks.
tail -n +2 "$VIDEOS" | while IFS=$'\t' read -r key size md5 cd_offset cd_size holograms; do
  url="https://zenodo.org/api/records/10632465/files/$key/content"
  cd="$DL/cd/$key.cd"
  if [ ! -s "$DL/members/$key.tsv" ] || [ ! -s "$cd" ]; then
    rm -f "$cd.part" "$cd.headers.part"
    "${CURL[@]}" --max-time 300 --max-filesize $((size - cd_offset + 1024)) \
      -r "$cd_offset-$((size - 1))" -D "$cd.headers.part" -o "$cd.part" "$url"
    mv "$cd.headers.part" "$cd.headers"
    mv "$cd.part" "$cd"
    sleep 1
  fi
  $PY parse-cd "$cd" "$cd.headers" "$size" "$cd_offset" "$key" "$DL/members/$key.tsv"
  n="$(($(wc -l < "$DL/members/$key.tsv") - 1))"
  [ "$n" = "$holograms" ] || { echo "FATAL: $key has $n holograms, pinned $holograms" >&2; exit 1; }
  $PY check-pins "$DL/members/$key.tsv" "$SELECTED" "$key"
done

# 3. Pinned members.
declare -A ARCHIVE_SIZE
while IFS=$'\t' read -r key size _rest; do ARCHIVE_SIZE["$key"]="$size"; done < <(tail -n +2 "$VIDEOS")

total=0; fetched=0; cached=0
while IFS=$'\t' read -r key frame name flags method crc csize usize lho nl next; do
  total=$((total + 1))
  stem="${key%.zip}"
  out="$DL/tif/$stem/$(printf '%05d' "$frame")_holo.tif"
  mkdir -p "$(dirname "$out")"
  if [ -s "$out" ] && [ "$(wc -c < "$out" | tr -d ' ')" = "$usize" ] \
     && python3 -I -c 'import sys,zlib; sys.exit(0 if zlib.crc32(open(sys.argv[1],"rb").read()) == int(sys.argv[2],16) else 1)' "$out" "$crc"; then
    cached=$((cached + 1))
    continue
  fi
  url="https://zenodo.org/api/records/10632465/files/$key/content"
  rng="$out.zip-range"
  ok=0
  for attempt in 1 2 3; do
    rm -f "$rng" "$rng.headers" "$out.part"
    if "${CURL[@]}" --max-time 1800 --max-filesize $((next - lho + 1024)) \
         -r "$lho-$((next - 1))" -D "$rng.headers" -o "$rng" "$url" \
       && $PY extract "$rng" "$rng.headers" "${ARCHIVE_SIZE[$key]}" "$lho" "$name" "$method" \
            "$csize" "$usize" "$crc" "$out.part"; then
      ok=1; break
    fi
    echo "retry member key=$key frame=$frame attempt=$attempt" >&2
    sleep $((attempt * 10))
  done
  [ "$ok" = 1 ] || { echo "FATAL: could not fetch/validate $key frame $frame" >&2; exit 1; }
  mv "$out.part" "$out"
  rm -f "$rng" "$rng.headers"
  fetched=$((fetched + 1))
  echo "[$(date -Is)] member $total/102 key=$key frame=$frame"
  sleep 1
done < <(tail -n +2 "$SELECTED")

[ "$total" = 102 ] || { echo "FATAL: expected 102 pinned frames, found $total" >&2; exit 1; }
echo "members total=$total fetched=$fetched cached=$cached bytes=$(du -sb "$DL/tif" | cut -f1)"
echo "[$(date -Is)] download done dataset=$DATASET_ID"
