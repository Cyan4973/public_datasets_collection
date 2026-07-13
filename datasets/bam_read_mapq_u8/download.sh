#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="bam_read_mapq_u8"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
mkdir -p "$LOG_DIR" "$DOWNLOAD_DIR"

RUN_TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/download.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/download.latest.log"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1

echo "[$(date -Is)] download start dataset=$DATASET_ID"

# Per-read mapping quality (MAPQ) is a native uint8 field of every BAM alignment
# record. BAMs are multi-GB, so we download only a bounded byte-range PREFIX of
# each source BAM (a whole number of leading BGZF blocks); the build extracts the
# MAPQ stream from the reads present in that prefix. One BAM -> one sample.
#
# Sources: 1000 Genomes phase3 low-coverage BWA alignments (EBI mirror, all bwa
# so MAPQ shares the 0..60 scale = homogeneous). Exact BAM filenames carry a
# per-sample date, so instead of hard-coding them we resolve each sample's BAM
# from its alignment directory listing. Override entirely with BAM_URLS_FILE
# (one BAM URL per line, or "name<TAB>url"). Only numeric MAPQ bytes are
# extracted -- no sequence, read names, or identifiers.
BAM_MAX_BYTES="${BAM_MAX_BYTES:-48000000}"          # per-BAM prefix cap (~48 MB)
BAM_MIN_BYTES="${BAM_MIN_BYTES:-2000000}"           # a usable prefix must exceed this
MIN_SAMPLE_COUNT="${MIN_SAMPLE_COUNT:-5}"
BAM_URLS_FILE="${BAM_URLS_FILE:-}"
UA="openzl-public-datasets/1.0 (numeric dataset collection)"
PLAN="$DOWNLOAD_DIR/download_plan.tsv"

ONEKG="https://ftp.1000genomes.ebi.ac.uk/vol1/ftp/phase3/data"
# Sample pool (more than needed; some may lack a low-coverage BWA BAM). Override
# the whole selection with BAM_URLS_FILE if desired.
SAMPLES="${BAM_SAMPLES:-HG00096 HG00097 HG00099 HG00100 HG00101 HG00102 HG00103 HG00105 HG00106 HG00107 HG00108 HG00109 HG00110 HG00111}"

# Resolve each source BAM URL: either the explicit list, or per-sample directory
# listing lookup of the low-coverage BWA BAM (date-agnostic).
urls=()
if [ -n "$BAM_URLS_FILE" ]; then
  [ -s "$BAM_URLS_FILE" ] || { echo "FATAL: BAM_URLS_FILE not found or empty: $BAM_URLS_FILE"; exit 1; }
  while IFS=$'\t' read -r a b || [ -n "$a" ]; do
    case "$a" in ""|\#*) continue;; esac
    if [ -n "${b:-}" ]; then urls+=("$b"); else urls+=("$a"); fi
  done < "$BAM_URLS_FILE"
else
  for s in $SAMPLES; do
    dir="$ONEKG/$s/alignment/"
    listing="$(curl --globoff -fsSL --max-time 90 -A "$UA" "$dir" 2>/dev/null || true)"
    fname="$(printf '%s' "$listing" \
      | grep -oE "${s}\.mapped\.ILLUMINA\.bwa\.[A-Za-z]+\.low_coverage\.[0-9]+\.bam" \
      | grep -v exome | sort -u | head -1 || true)"
    if [ -z "$fname" ]; then
      echo "  WARN: no low-coverage BWA BAM listed for $s"
      continue
    fi
    urls+=("$dir$fname")
  done
fi

printf 'local_name\turl\tbytes\n' > "$PLAN"

is_bgzf() {
  # first 4 bytes must be gzip magic with FEXTRA (1f 8b 08 04) = a BGZF block
  [ "$(LC_ALL=C head -c 4 "$1" | od -An -tx1 | tr -d ' \n')" = "1f8b0804" ]
}

ok=0
for url in "${urls[@]}"; do
  name="$(basename "${url%%\?*}")"
  out="$DOWNLOAD_DIR/$name"
  part="$out.part"

  if [ -s "$out" ] && [ "${FORCE_DOWNLOAD:-0}" != "1" ] && is_bgzf "$out"; then
    sz="$(wc -c < "$out" | tr -d ' ')"
    echo "cache_hit name=$name bytes=$sz"
    printf '%s\t%s\t%s\n' "$name" "$url" "$sz" >> "$PLAN"
    ok=$((ok + 1))
    continue
  fi

  echo "probe url=$url"
  code="$(curl --globoff -fsSL -r 0-0 -o /dev/null -w '%{http_code}' --max-time 60 -A "$UA" "$url" 2>/dev/null || true)"
  if [ "$code" != "200" ] && [ "$code" != "206" ]; then
    echo "  WARN: skip (liveness HTTP '$code')"
    continue
  fi

  # Bounded ranged prefix. --max-filesize guards against servers that ignore Range.
  # Stall-based abort (no hard total-time cap), retries for transient failures.
  rm -f "$part"
  if ! curl --globoff -fSL --retry 10 --retry-delay 5 \
        --speed-limit 1024 --speed-time 120 \
        --max-filesize "$((BAM_MAX_BYTES * 2))" \
        -r "0-$((BAM_MAX_BYTES - 1))" -A "$UA" -o "$part" "$url"; then
    echo "  WARN: download failed for $name"; rm -f "$part"; continue
  fi

  sz="$(wc -c < "$part" | tr -d ' ')"
  if [ "$sz" -lt "$BAM_MIN_BYTES" ] || ! is_bgzf "$part"; then
    echo "  WARN: prefix too small or not BGZF (bytes=$sz); skipping $name"; rm -f "$part"; continue
  fi
  mv "$part" "$out"
  echo "downloaded name=$name bytes=$sz"
  printf '%s\t%s\t%s\n' "$name" "$url" "$sz" >> "$PLAN"
  ok=$((ok + 1))
done

echo "usable_bam_prefixes=$ok"
if [ "$ok" -lt "$MIN_SAMPLE_COUNT" ]; then
  echo "FATAL: only $ok usable BAM prefixes (need >= $MIN_SAMPLE_COUNT)."
  echo "       Supply current URLs via BAM_URLS_FILE=/path/to/urls.txt (one BAM URL per line)."
  exit 1
fi

echo "[$(date -Is)] download done dataset=$DATASET_ID prefixes=$ok"
