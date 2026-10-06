#!/usr/bin/env bash
# Fetch the pinned ISEA home-storage system-month CSV members by exact ZIP byte
# range from Zenodo record 12091223 (CC BY 4.0), plus the 31 KB metadata zip.
# Only the 39 selected deflated members are transferred (about 878 MB), never
# the whole 0.3-2.1 GB per-system archives.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="rwth_isea_home_storage_battery_voltage_f32"
DOWNLOAD_DIR="$DATA_ROOT/downloads/$DATASET_ID"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
SELECTION="$RECIPE_DIR/selection.tsv"
VALIDATOR="$RECIPE_DIR/scripts/zip_member.py"
RECORD_ID=12091223
API_URL="https://zenodo.org/api/records/$RECORD_ID"
FILE_URL_BASE="https://zenodo.org/api/records/$RECORD_ID/files"
META_KEY="Metadata_and_Code.zip"
META_BYTES=31123
META_MD5="23720da306f63fd2fd20fdc1a7b8f106"
UA="openzl-public-datasets-isea-hss-voltage/1.0"
MAX_ATTEMPTS="${MAX_ATTEMPTS:-8}"

mkdir -p "$DOWNLOAD_DIR/members" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
echo "[$(date -Is)] download start dataset=$DATASET_ID data_root=$DATA_ROOT"

# Small JSON/zip fetch with retries; -f makes HTTP >= 400 (including 429/503
# rate-limit pages) a failure instead of saving the HTML body.
small_fetch() {
  local url="$1" out="$2" max_bytes="$3" attempt
  for attempt in $(seq 1 "$MAX_ATTEMPTS"); do
    rm -f "$out.part"
    if curl --fail --silent --show-error --location \
        --retry 6 --retry-delay 10 --retry-all-errors --connect-timeout 30 \
        --max-time 300 --max-filesize "$max_bytes" --user-agent "$UA" \
        --output "$out.part" "$url"; then
      mv "$out.part" "$out"
      return 0
    fi
    echo "small_fetch attempt=$attempt failed url=$url; backing off"
    sleep $((attempt * 20))
  done
  echo "FATAL: could not fetch $url" >&2
  return 1
}

# 1. Record identity, license, and pinned archive sizes/MD5s.
record_json="$DOWNLOAD_DIR/record.json"
small_fetch "$API_URL" "$record_json" 5000000
python3 "$VALIDATOR" record "$record_json" "$SELECTION" "$META_KEY" "$META_BYTES" "$META_MD5"

# 2. Metadata_and_Code.zip (system metadata: nominal voltage, cells in series,
#    manufacturer, chemistry). Build uses it to re-check the voltage class.
meta_zip="$DOWNLOAD_DIR/$META_KEY"
if [ ! -s "$meta_zip" ] || ! printf '%s  %s\n' "$META_MD5" "$meta_zip" | md5sum --check --status; then
  small_fetch "$FILE_URL_BASE/$META_KEY/content" "$meta_zip" 1000000
fi
printf '%s  %s\n' "$META_MD5" "$meta_zip" | md5sum --check --status || {
  echo "FATAL: $META_KEY MD5 mismatch" >&2
  exit 1
}
head -c 4 "$meta_zip" | od -An -tx1 | grep -q "50 4b 03 04" || { echo "FATAL: $META_KEY is not a ZIP" >&2; exit 1; }
echo "metadata_zip=ok bytes=$META_BYTES md5=$META_MD5"

# Final 206 status and exact Content-Range from a curl header dump (the proxy
# CONNECT response, if any, precedes it).
range_headers_ok() {
  python3 - "$1" "$2" "$3" "$4" <<'PY'
import re, sys
text = open(sys.argv[1], encoding="iso-8859-1").read()
start, end, total = (int(v) for v in sys.argv[2:5])
blocks = [b for b in re.split(r"(?=^HTTP/)", text, flags=re.M) if b.strip()]
final = blocks[-1] if blocks else ""
status = re.search(r"^HTTP/\S+\s+(\d+)", final, flags=re.M)
rng = re.search(r"^content-range:\s*bytes\s+(\d+)-(\d+)/(\d+)", final, flags=re.M | re.I)
ok = status and status.group(1) == "206" and rng and int(rng.group(1)) == start and int(rng.group(2)) == end and int(rng.group(3)) == total
sys.exit(0 if ok else 1)
PY
}

# Resumable exact-range fetch of one member span into "$out" (.part, appended
# chunk by chunk only after the 206 Content-Range is checked).
fetch_span() {
  local url="$1" start="$2" span="$3" total="$4" out="$5"
  local part="$out.part" chunk="$out.chunk" hdr="$out.hdr" have a b attempt=0 rc
  have=0
  [ -f "$part" ] && have="$(stat -c %s "$part")"
  if [ "$have" -gt "$span" ]; then rm -f "$part"; have=0; fi
  while [ "$have" -lt "$span" ]; do
    attempt=$((attempt + 1))
    if [ "$attempt" -gt "$MAX_ATTEMPTS" ]; then
      echo "FATAL: giving up on $url range after $MAX_ATTEMPTS attempts" >&2
      return 1
    fi
    a=$((start + have))
    b=$((start + span - 1))
    rm -f "$chunk" "$hdr"
    rc=0
    curl --fail --silent --show-error --location \
      --retry 6 --retry-delay 15 --retry-all-errors --connect-timeout 30 \
      --speed-limit 1024 --speed-time 120 --user-agent "$UA" \
      --range "$a-$b" --dump-header "$hdr" --output "$chunk" "$url" || rc=$?
    if [ -s "$chunk" ] && [ -s "$hdr" ] && range_headers_ok "$hdr" "$a" "$b" "$total"; then
      cat "$chunk" >> "$part"
    elif [ -s "$chunk" ]; then
      echo "discarding chunk without a valid 206 Content-Range ($a-$b/$total)"
    fi
    rm -f "$chunk" "$hdr"
    have=0
    [ -f "$part" ] && have="$(stat -c %s "$part")"
    if [ "$have" -lt "$span" ]; then
      echo "range attempt=$attempt rc=$rc have=$have/$span; backing off"
      sleep $((attempt * 15))
    fi
  done
  if [ "$have" -ne "$span" ]; then
    echo "FATAL: span overshoot $have != $span" >&2
    rm -f "$part"
    return 1
  fi
}

# 3. The pinned members, sequentially, with a pause between requests.
sums="$DOWNLOAD_DIR/member_validation.tsv"
: > "$sums.part"
count=0
total_span=0
while IFS=$'\t' read -r -u 3 system_id month zip_key zip_bytes zip_md5 member_name lho span csz usz crc rows; do
  [ "$system_id" = "system_id" ] && continue
  out_dir="$DOWNLOAD_DIR/members/$system_id"
  mkdir -p "$out_dir"
  out="$out_dir/${month}_System_ID_${system_id}.zipmember"
  if [ -s "$out" ] && [ "$(stat -c %s "$out")" = "$span" ]; then
    echo "cache_hit member=$member_name"
  else
    rm -f "$out"
    echo "[$(date -Is)] fetch member=$member_name zip=$zip_key offset=$lho span=$span"
    fetch_span "$FILE_URL_BASE/$zip_key/content" "$lho" "$span" "$zip_bytes" "$out"
    if ! python3 "$VALIDATOR" member "$out.part" "$member_name" "$span" "$csz" "$usz" "$crc" > "$out.check"; then
      cat "$out.check" || true
      rm -f "$out.part" "$out.check"
      echo "FATAL: member validation failed for $member_name" >&2
      exit 1
    fi
    rm -f "$out.check"
    mv "$out.part" "$out"
    sleep 2
  fi
  line="$(python3 "$VALIDATOR" member "$out" "$member_name" "$span" "$csz" "$usz" "$crc")"
  echo "$line"
  printf '%s\t%s\t%s\n' "$system_id" "$month" "$line" >> "$sums.part"
  count=$((count + 1))
  total_span=$((total_span + span))
done 3< "$SELECTION"
mv "$sums.part" "$sums"

expected_count="$(($(wc -l < "$SELECTION") - 1))"
if [ "$count" -ne "$expected_count" ]; then
  echo "FATAL: validated $count members, selection lists $expected_count" >&2
  exit 1
fi
echo "members_validated=$count span_bytes=$total_span"

# 4. Remove member spans (and partial transfers) left over from earlier
#    selections, so the download directory holds exactly the declared members.
pruned=0
while IFS= read -r -d '' stale; do
  rel="${stale#"$DOWNLOAD_DIR/members/"}"
  sid="${rel%%/*}"
  base="$(basename "$stale")"
  month="${base%%_System_ID_*}"
  if ! awk -F'\t' -v s="$sid" -v m="$month" 'NR > 1 && $1 == s && $2 == m { found = 1 } END { exit !found }' "$SELECTION"; then
    echo "pruned undeclared member span $rel"
    rm -f "$stale"
    pruned=$((pruned + 1))
  fi
done < <(find "$DOWNLOAD_DIR/members" -type f \( -name '*.zipmember' -o -name '*.zipmember.part' -o -name '*.zipmember.chunk' -o -name '*.zipmember.hdr' \) -print0)
find "$DOWNLOAD_DIR/members" -mindepth 1 -type d -empty -delete
echo "pruned_members=$pruned"
echo "[$(date -Is)] download done dataset=$DATASET_ID"
