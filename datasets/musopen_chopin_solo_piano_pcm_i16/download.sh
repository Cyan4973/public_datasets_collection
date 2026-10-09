#!/usr/bin/env bash
# Fetch the pinned Musopen "Set Chopin Free" solo-piano FLAC tracks (the 39
# Preludes and Etudes whose STREAMINFO is 44.1 kHz / stereo / 16-bit) from the
# Internet Archive item musopen-chopin-complete-works-flac, plus the rights
# evidence: the IA metadata of that item and of Musopen's first-party CC0 item
# musopen-chopin, the item's booklet OCR text, and a pinned Wayback snapshot of
# the 2013 Kickstarter page whose FAQ states the CC0 dedication.
# Every FLAC is checked against its IA md5 and pinned size and its STREAMINFO
# against the pinned format/total_samples/MD5 signature.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="musopen_chopin_solo_piano_pcm_i16"
DOWNLOAD_DIR="$DATA_ROOT/downloads/$DATASET_ID"
META_DIR="$DOWNLOAD_DIR/meta"
EVIDENCE_DIR="$DOWNLOAD_DIR/evidence"
FLAC_DIR="$DOWNLOAD_DIR/flac"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
HELPER="$RECIPE_DIR/scripts/musopen_chopin.py"
UA="openzl-public-datasets-musopen-chopin/1.0"
MAX_PASSES="${MUSOPEN_MAX_PASSES:-6}"

KICKSTARTER_SNAPSHOT_URL="https://web.archive.org/web/20130908225009id_/http://www.kickstarter.com:80/projects/Musopen/set-chopin-free"
KICKSTARTER_SHA256="365d9aecc2579a3637488b738b8a6d988bbb86dadd4d730836838073b292f4e6"
BOOKLET_TXT_URL="https://archive.org/download/musopen-chopin-complete-works-flac/Chopin%20Project%20-%20Musopen_djvu.txt"
BOOKLET_TXT_MD5="4e6005a2954d809c549ffe7deb3dfe0b"

mkdir -p "$META_DIR" "$EVIDENCE_DIR" "$FLAC_DIR" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
echo "[$(date -Is)] download start dataset=$DATASET_ID data_root=$DATA_ROOT"

python3 -I "$HELPER" selftest

fetch_small() {
  # fetch_small URL OUT MAX_BYTES : small metadata/evidence files, whole-file retries.
  local url="$1" out="$2" max_bytes="$3"
  rm -f "$out.part"
  curl --fail --silent --show-error --location \
    --retry 10 --retry-delay 10 --retry-all-errors --connect-timeout 30 --max-time 300 \
    --max-filesize "$max_bytes" --user-agent "$UA" --output "$out.part" "$url"
  mv "$out.part" "$out"
}

# 1. Internet Archive metadata of the bulk FLAC item and of Musopen's own CC0 item.
fetch_small "https://archive.org/metadata/musopen-chopin-complete-works-flac" "$META_DIR/musopen-chopin-complete-works-flac.metadata.json" 5000000
fetch_small "https://archive.org/metadata/musopen-chopin" "$META_DIR/musopen-chopin.metadata.json" 5000000
python3 -I "$HELPER" check-meta --meta-dir "$META_DIR"

# 2. Rights evidence files (pinned).
KS="$EVIDENCE_DIR/kickstarter_set_chopin_free_20130908.html"
if ! { [ -s "$KS" ] && printf '%s  %s\n' "$KICKSTARTER_SHA256" "$KS" | sha256sum --check --status; }; then
  fetch_small "$KICKSTARTER_SNAPSHOT_URL" "$KS" 2000000
fi
printf '%s  %s\n' "$KICKSTARTER_SHA256" "$KS" | sha256sum --check --status || { echo "FATAL: Kickstarter snapshot sha256 mismatch" >&2; exit 1; }
grep -q "What license will the music recordings be released under?" "$KS" || { echo "FATAL: Kickstarter snapshot lacks the license FAQ" >&2; exit 1; }
grep -q "CC0 dedication" "$KS" && grep -q "creativecommons.org/publicdomain/zero/1.0/" "$KS" || { echo "FATAL: Kickstarter snapshot lacks the CC0 statement" >&2; exit 1; }
echo "evidence_ok kickstarter_faq=CC0"

BOOKLET="$EVIDENCE_DIR/chopin_project_musopen_booklet_djvu.txt"
if ! { [ -s "$BOOKLET" ] && printf '%s  %s\n' "$BOOKLET_TXT_MD5" "$BOOKLET" | md5sum --check --status; }; then
  fetch_small "$BOOKLET_TXT_URL" "$BOOKLET" 1000000
fi
printf '%s  %s\n' "$BOOKLET_TXT_MD5" "$BOOKLET" | md5sum --check --status || { echo "FATAL: booklet OCR text md5 mismatch" >&2; exit 1; }
grep -q "SET FREE BY MUSOPEN.ORG" "$BOOKLET" || { echo "FATAL: booklet OCR text lacks the Musopen title page" >&2; exit 1; }
echo "evidence_ok booklet=SET FREE BY MUSOPEN.ORG"

# 3. The 39 pinned FLAC tracks: resumable per-file transfers, validated before
#    promotion. No --max-time on bulk transfers; stalls are caught by
#    --speed-limit/--speed-time and retried, and every pass re-plans.
size_of() { stat -c %s "$1" 2>/dev/null || echo 0; }
pinned_size() { awk -F'\t' -v id="$1" 'NR>1 && $1==id {print $3}' "$RECIPE_DIR/scripts/pinned_files.tsv"; }
pass=0
while :; do
  PLAN="$(python3 -I "$HELPER" plan --flac-dir "$FLAC_DIR")"
  if [ -z "$PLAN" ]; then
    break
  fi
  pass=$((pass + 1))
  if [ "$pass" -gt "$MAX_PASSES" ]; then
    echo "FATAL: $(printf '%s\n' "$PLAN" | wc -l) FLAC files still missing after $MAX_PASSES passes" >&2
    exit 1
  fi
  echo "pass=$pass pending=$(printf '%s\n' "$PLAN" | wc -l)"
  while IFS=$'\t' read -r sid url out; do
    part="$out.part"
    want="$(pinned_size "$sid")"
    if [ "$(size_of "$part")" -gt "$want" ]; then
      echo "discard oversized partial $sid"
      rm -f "$part"
    fi
    if [ "$(size_of "$part")" -lt "$want" ]; then
      echo "fetch $sid"
      if ! curl --fail --silent --show-error --location -C - \
        --retry 10 --retry-delay 5 --retry-all-errors --connect-timeout 30 \
        --speed-limit 1024 --speed-time 120 --user-agent "$UA" \
        --output "$part" "$url" </dev/null; then
        echo "WARN: transfer failed for $sid (will retry next pass)"
        continue
      fi
    fi
    if python3 -I "$HELPER" check-flac "$sid" "$part" </dev/null; then
      mv "$part" "$out"
    else
      echo "WARN: invalid payload for $sid; discarding partial"
      rm -f "$part"
    fi
  done <<< "$PLAN"
done

# 4. Final full validation of every promoted file (size, md5, STREAMINFO).
total=0
while IFS=$'\t' read -r sid _rest; do
  [ "$sid" = "sample_id" ] && continue
  python3 -I "$HELPER" check-flac "$sid" "$FLAC_DIR/$sid.flac" >/dev/null
  total=$((total + $(size_of "$FLAC_DIR/$sid.flac")))
done < "$RECIPE_DIR/scripts/pinned_files.tsv"
echo "flac_files_ok count=$(($(wc -l < "$RECIPE_DIR/scripts/pinned_files.tsv") - 1)) bytes=$total"
echo "[$(date -Is)] download done dataset=$DATASET_ID"
