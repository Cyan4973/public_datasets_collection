#!/usr/bin/env bash
# Fetch a fixed, pinned byte-range prefix of the CC BY 4.0 PacBio Sequel
# subreads BAM in Zenodo record 13306684, plus the record metadata JSON.
# Resumable: a partial prefix is continued with an offset range request.
set -euo pipefail

RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$RECIPE_DIR/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="zenodo_pacbio_sequel_subread_ipd_codecv1_u8"
DOWNLOAD_DIR="$DATA_ROOT/downloads/$DATASET_ID"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
mkdir -p "$DOWNLOAD_DIR" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
echo "[$(date -Is)] download start dataset=$DATASET_ID"

RECORD_ID=13306684
RECORD_URL="https://zenodo.org/api/records/$RECORD_ID"
FILE_KEY="veillonella.subreads.bam"
CONTENT_URL="https://zenodo.org/api/records/$RECORD_ID/files/$FILE_KEY/content"
FULL_FILE_BYTES=5927559159
FULL_FILE_MD5="5c2a00da331ed1b8479e7c080b800835"
# Fixed prefix: the first 256 MiB of the BAM (bytes 0..268435455).
PREFIX_BYTES=268435456
# SHA-256 of exactly those PREFIX_BYTES bytes. The full-file MD5 does not apply
# to a prefix. Pinned from the first download (2026-10-08); a mismatch is
# rejected and the file is renamed *.rejected.
PREFIX_SHA256="1f5b05dd9f69dcbcc3b6c595b3a0d328d7f238f2eba2f96106dabf5b0b782ecb"

RECORD_JSON="$DOWNLOAD_DIR/record_$RECORD_ID.json"
TARGET="$DOWNLOAD_DIR/veillonella.subreads.prefix_${PREFIX_BYTES}.bam"
PART="$TARGET.part"

# 1. Record metadata: identity, license, pinned file size and checksum.
curl -fsSL --retry 5 --retry-delay 5 --max-time 120 --max-filesize 5000000 \
  -o "$RECORD_JSON.part" "$RECORD_URL"
mv "$RECORD_JSON.part" "$RECORD_JSON"
RECORD_JSON="$RECORD_JSON" python3 -I -B - <<'PY'
import json, os
r = json.load(open(os.environ["RECORD_JSON"], encoding="utf-8"))
m = r.get("metadata", {})
if int(r.get("id", 0)) != 13306684:
    raise SystemExit("unexpected Zenodo record id")
if m.get("title") != "Material for LORA paper (Veillonella Parvula case)":
    raise SystemExit(f"unexpected record title: {m.get('title')!r}")
lic = m.get("license", {})
if not isinstance(lic, dict) or lic.get("id") != "cc-by-4.0":
    raise SystemExit(f"record no longer declares cc-by-4.0: {lic!r}")
files = {f.get("key"): f for f in r.get("files", [])}
f = files.get("veillonella.subreads.bam")
if f is None or int(f.get("size", 0)) != 5927559159:
    raise SystemExit("pinned subreads BAM size changed or file missing")
if f.get("checksum") != "md5:5c2a00da331ed1b8479e7c080b800835":
    raise SystemExit("pinned subreads BAM md5 changed")
print("record_validation=ok license=cc-by-4.0 file_size=5927559159")
PY

# 2. Bounded, resumable prefix transfer.
if [[ -f "$TARGET" && "$(wc -c < "$TARGET" | tr -d ' ')" == "$PREFIX_BYTES" && "${FORCE_DOWNLOAD:-0}" != "1" ]]; then
  echo "cache_hit path=$TARGET"
else
  # Liveness: one-byte range request must answer 206.
  code="$(curl -sSL -r 0-0 -o /dev/null -w '%{http_code}' --max-time 60 "$CONTENT_URL" || true)"
  [[ "$code" == "206" ]] || { echo "liveness check failed: HTTP $code (expected 206)" >&2; exit 1; }
  touch "$PART"
  attempt=0
  while :; do
    have="$(wc -c < "$PART" | tr -d ' ')"
    if (( have == PREFIX_BYTES )); then break; fi
    if (( have > PREFIX_BYTES )); then echo "partial file larger than prefix: $have" >&2; exit 1; fi
    attempt=$((attempt + 1))
    if (( attempt > 60 )); then echo "giving up after $((attempt - 1)) attempts at $have bytes" >&2; exit 1; fi
    want=$((PREFIX_BYTES - have))
    echo "[$(date -Is)] attempt=$attempt range=$have-$((PREFIX_BYTES - 1)) remaining=$want"
    chunk="$DOWNLOAD_DIR/.chunk"
    headers="$DOWNLOAD_DIR/.chunk.headers"
    rm -f "$chunk" "$headers"
    set +e
    curl -fsSL --speed-limit 1024 --speed-time 120 --connect-timeout 60 \
      --max-filesize "$want" -r "$have-$((PREFIX_BYTES - 1))" \
      -D "$headers" -o "$chunk" "$CONTENT_URL"
    rc=$?
    set -e
    got=0
    [[ -f "$chunk" ]] && got="$(wc -c < "$chunk" | tr -d ' ')"
    # Only append bytes from a 206 whose Content-Range starts at our offset.
    if grep -qiE "^content-range: bytes $have-" "$headers" 2>/dev/null && (( got <= want )); then
      if (( got > 0 )); then cat "$chunk" >> "$PART"; fi
    else
      echo "response is not a 206 at offset $have (rc=$rc); discarding $got bytes" >&2
    fi
    rm -f "$chunk" "$headers"
    if (( rc != 0 )); then sleep 5; fi
  done
  mv "$PART" "$TARGET"
fi

ACTUAL_BYTES="$(wc -c < "$TARGET" | tr -d ' ')"
[[ "$ACTUAL_BYTES" == "$PREFIX_BYTES" ]] || { echo "prefix size mismatch: $ACTUAL_BYTES != $PREFIX_BYTES" >&2; exit 1; }
ACTUAL_SHA256="$(sha256sum "$TARGET" | awk '{print $1}')"
echo "prefix_sha256=$ACTUAL_SHA256"
if [[ -n "$PREFIX_SHA256" && "$ACTUAL_SHA256" != "$PREFIX_SHA256" ]]; then
  echo "prefix sha256 mismatch: $ACTUAL_SHA256 != $PREFIX_SHA256" >&2
  mv "$TARGET" "$TARGET.rejected"
  exit 1
fi

# 3. Semantic validation: BGZF/BAM header and the first records.
TARGET="$TARGET" SCRIPTS="$RECIPE_DIR/scripts" python3 -I -B - <<'PY'
import os, sys
sys.path.insert(0, os.environ["SCRIPTS"])
import pacbio_bam as pb
with open(os.environ["TARGET"], "rb") as fh:
    head = fh.read(8 * 1024 * 1024)
r = pb.BamPrefixReader(head)
text = r.read_header()
rg = [l for l in text.splitlines() if l.startswith("@RG\t")]
if len(rg) != 1:
    raise SystemExit(f"expected exactly one @RG line, got {len(rg)}")
fields = dict(f.split(":", 1) for f in rg[0].split("\t")[1:])
ds = fields.get("DS", "").split(";")
need = ["READTYPE=SUBREAD", "Ipd:CodecV1=ip", "FRAMERATEHZ=80.000000"]
missing = [n for n in need if n not in ds]
if missing or fields.get("PM") != "SEQUEL" or any(d.startswith("Ipd:Frames") for d in ds):
    raise SystemExit(f"@RG semantics changed: missing={missing} PM={fields.get('PM')!r}")
if r.references:
    raise SystemExit("subreads BAM unexpectedly has references")
n = 0
for rec in r.records():
    typ, ip = rec["aux"]["ip"]
    if typ != "BC" or len(ip) != rec["l_seq"]:
        raise SystemExit(f"record {rec['name']}: ip is {typ} len {len(ip)} vs l_seq {rec['l_seq']}")
    n += 1
    if n >= 50:
        break
if n < 50:
    raise SystemExit(f"only {n} records parsed from prefix head")
print("bam_validation=ok rg=SUBREAD Ipd:CodecV1=ip PM=SEQUEL FRAMERATEHZ=80 first_records=50")
PY

export DOWNLOAD_DIR TARGET ACTUAL_BYTES ACTUAL_SHA256 CONTENT_URL FULL_FILE_BYTES FULL_FILE_MD5
python3 -I -B - <<'PY'
import json, os
from pathlib import Path
payload = {
    "dataset_id": "zenodo_pacbio_sequel_subread_ipd_codecv1_u8",
    "record_id": 13306684,
    "license": "cc-by-4.0",
    "source_url": os.environ["CONTENT_URL"],
    "source_full_file_bytes": int(os.environ["FULL_FILE_BYTES"]),
    "source_full_file_md5": os.environ["FULL_FILE_MD5"],
    "prefix_file": Path(os.environ["TARGET"]).name,
    "prefix_range": f"0-{int(os.environ['ACTUAL_BYTES']) - 1}",
    "prefix_bytes": int(os.environ["ACTUAL_BYTES"]),
    "prefix_sha256": os.environ["ACTUAL_SHA256"],
}
Path(os.environ["DOWNLOAD_DIR"], "download_inventory.json").write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
PY
echo "[$(date -Is)] download done dataset=$DATASET_ID bytes=$ACTUAL_BYTES"
