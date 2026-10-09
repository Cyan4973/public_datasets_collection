#!/usr/bin/env bash
# Download the 25 pinned HDAP Walz lunar plate scans (FITS) and the CC0 rights record.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="gavo_hdap_walz_photographic_plate_scans_u16"
DOWNLOAD_DIR="$DATA_ROOT/downloads/$DATASET_ID"
PLATE_DIR="$DOWNLOAD_DIR/fits"
EVIDENCE_DIR="$DOWNLOAD_DIR/evidence"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
SOURCES="$RECIPE_DIR/sources.tsv"
PLAN="$DOWNLOAD_DIR/download_plan.tsv"
OAI_URL="https://dc.g-vo.org/oai.xml?verb=GetRecord&metadataPrefix=ivo_vor&identifier=ivo://org.gavo.dc/lswscans/res/positions/siap"
UA="openzl-public-datasets-hdap-walz/1.0"

mkdir -p "$PLATE_DIR" "$EVIDENCE_DIR" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
echo "[$(date -Is)] download start dataset=$DATASET_ID data_root=$DATA_ROOT"

# --- rights evidence (small; transport failure warns, changed content is fatal) ---
oai="$EVIDENCE_DIR/hdap_siap_vor_record.xml"
if curl -fsS -L --retry 5 --retry-delay 5 --retry-all-errors --max-time 120 \
     --max-filesize 5000000 --user-agent "$UA" -o "$oai.part" "$OAI_URL"; then
  mv "$oai.part" "$oai"
else
  rm -f "$oai.part"
  echo "WARN: could not fetch the HDAP VOResource record (transport); keeping any earlier copy"
fi
if [ -s "$oai" ]; then
  python3 -I -B - "$oai" <<'PY'
import re, sys
text = open(sys.argv[1], encoding="utf-8").read()
if "HDAP -- Heidelberg Digitized Astronomical Plates" not in text:
    raise SystemExit("FATAL: VOResource record no longer identifies HDAP")
rights = re.findall(r"<rights[^>]*rightsURI=\"([^\"]+)\"[^>]*>(.*?)</rights>", text, re.S)
ok = [uri for uri, body in rights
      if "CC0-1.0" in uri and "waived all copyright" in body and "HDAP scans" in body]
if not ok:
    raise SystemExit(f"FATAL: CC0 rights element missing or changed: {rights!r}")
print(f"license_check=ok rightsURI={ok[0]}")
PY
fi

# --- plates ---
python3 -I -B - "$SOURCES" <<'PY' > "$DOWNLOAD_DIR/.pins"
import sys
lines = [l for l in open(sys.argv[1], encoding="utf-8").read().splitlines() if l and not l.startswith("#")]
head = lines[0].split("\t")
for line in lines[1:]:
    row = dict(zip(head, line.split("\t")))
    print(row["plate_id"], row["url"], row["size_bytes"])
PY

n_pins="$(wc -l < "$DOWNLOAD_DIR/.pins" | tr -d ' ')"
[ "$n_pins" = "25" ] || { echo "FATAL: expected 25 pinned plates, found $n_pins"; exit 1; }

: > "$PLAN.part"
i=0
while read -r plate url size <&3; do
  i=$((i + 1))
  dest="$PLATE_DIR/$plate.fits"
  if [ -f "$dest" ] && [ "${FORCE_DOWNLOAD:-0}" = "1" ]; then rm -f "$dest"; fi
  if [ -f "$dest" ] && [ "$(stat -c %s "$dest")" != "$size" ]; then
    echo "WARN: $plate final file has wrong size; re-fetching"
    rm -f "$dest"
  fi
  if [ ! -f "$dest" ]; then
    part="$dest.part"
    have=0
    [ -f "$part" ] && have="$(stat -c %s "$part")"
    if [ "$have" -gt "$size" ]; then rm -f "$part"; have=0; fi
    if [ "$have" -lt "$size" ]; then
      echo "[$(date -Is)] fetch $i/$n_pins $plate ($size bytes, resume_from=$have)"
      attempt=0
      while :; do
        rc=0
        curl -fL -C - --retry 10 --retry-delay 5 --retry-all-errors \
          --speed-limit 1024 --speed-time 120 --user-agent "$UA" \
          -sS -o "$part" "$url" || rc=$?
        [ "$rc" = "0" ] && break
        attempt=$((attempt + 1))
        if [ "$attempt" -ge 5 ]; then echo "FATAL: $plate download failed repeatedly (curl rc=$rc)"; exit 1; fi
        if [ "$rc" = "33" ]; then
          echo "WARN: server refused to resume $plate (curl rc=33); restarting from byte 0"
          rm -f "$part"
        else
          echo "WARN: curl failed for $plate (rc=$rc, attempt $attempt); resuming in 15 s"
          sleep 15
        fi
      done
    fi
    got="$(stat -c %s "$part")"
    if [ "$got" != "$size" ]; then
      echo "FATAL: $plate size $got != pinned $size"; exit 1
    fi
    if ! python3 -I -B "$RECIPE_DIR/scripts/fitsplate.py" check-file "$part" "$plate" > /dev/null; then
      echo "FATAL: $plate failed the header/regime check; removing partial payload"
      rm -f "$part"
      exit 1
    fi
    mv "$part" "$dest"
  fi
  line="$(python3 -I -B "$RECIPE_DIR/scripts/fitsplate.py" check-file "$dest" "$plate")" || {
    echo "FATAL: $plate failed validation"; exit 1; }
  echo "$line"
  sha="${line##*sha256=}"
  printf '%s\t%s\t%s\n' "$plate" "$size" "$sha" >> "$PLAN.part"
done 3< "$DOWNLOAD_DIR/.pins"

{ printf 'plate_id\tsize_bytes\tsha256\n'; cat "$PLAN.part"; } > "$PLAN"
rm -f "$PLAN.part" "$DOWNLOAD_DIR/.pins"
total="$(awk -F'\t' 'NR>1{s+=$2} END{print s}' "$PLAN")"
dups="$(awk -F'\t' 'NR>1{print $3}' "$PLAN" | sort | uniq -d | wc -l)"
[ "$dups" = "0" ] || { echo "FATAL: duplicate plate payloads in download plan"; exit 1; }
echo "plates=$(($(wc -l < "$PLAN") - 1)) total_bytes=$total plan=$PLAN"
echo "[$(date -Is)] download done dataset=$DATASET_ID"
