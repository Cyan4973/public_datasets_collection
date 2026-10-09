#!/usr/bin/env bash
# Fetch a pinned byte-range prefix of each of the 28 TUM VI euroc 1024_16
# sequence tars: exactly bytes 0..(end of the 8th cam1 PNG member)-1.
# The prefixes are validated against scripts/members.tsv (member names,
# offsets, sizes, PNG chunk CRCs, pinned last-IDAT CRC, IHDR).
set -euo pipefail

RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$RECIPE_DIR/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in
  /*) DATA_ROOT="$DATA_DIR" ;;
  *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;;
esac
DATASET_ID="tumvi_euroc_1024_cam_frames_u16"
BASE_URL="https://vision.in.tum.de/tumvi/exported/euroc/1024_16"
LICENSE_URL="https://cvg.cit.tum.de/data/datasets/visual-inertial-dataset"
MEMBERS_TSV="$RECIPE_DIR/scripts/members.tsv"
DOWNLOAD_DIR="$DATA_ROOT/downloads/$DATASET_ID"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
UA="openzl-public-datasets-tumvi/1.0"
mkdir -p "$DOWNLOAD_DIR" "$LOG_DIR"

RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/download.$RUN_TS.log" "$LOG_DIR/download.latest.log") 2>&1
echo "[$(date -Is)] download start dataset=$DATASET_ID"

# 1. License page: small, bounded fetch; require the CC BY 4.0 statement.
license_file="$DOWNLOAD_DIR/license_page.html"
curl -fsSL --retry 5 --retry-delay 3 --max-time 120 --max-filesize 5000000 \
  -A "$UA" -o "$license_file.part" "$LICENSE_URL"
mv "$license_file.part" "$license_file"
python3 -I - "$license_file" <<'PY'
import html, re, sys
t = open(sys.argv[1], encoding="utf-8", errors="replace").read()
t = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", t)))
need = ["All data in the Visual Inertial Dataset is licensed under a Creative Commons 4.0 Attribution License (CC BY 4.0)",
        "16-bit intensity depth and linear response function"]
for s in need:
    if s not in t:
        raise SystemExit(f"license/format statement not found on dataset page: {s!r}")
print("license_check=ok CC-BY-4.0")
PY

# 2. Per-tar prefixes.
plan="$(python3 -I - "$MEMBERS_TSV" <<'PY'
import csv, sys
pre = {}
for r in csv.DictReader(open(sys.argv[1], encoding="utf-8"), delimiter="\t"):
    t = pre.setdefault(r["tar"], [int(r["tar_bytes"]), 0])
    t[1] = max(t[1], int(r["data_offset"]) + int(r["size"]))
for tar, (total, end) in pre.items():
    print(tar, total, end)
PY
)"
n_tars="$(printf '%s\n' "$plan" | wc -l | tr -d ' ')"
[ "$n_tars" = "28" ] || { echo "FATAL: expected 28 tars in member table, got $n_tars" >&2; exit 1; }

fetch_prefix() {
  local tar="$1" total="$2" want="$3"
  local out="$DOWNLOAD_DIR/$tar.prefix"
  local part="$out.part" chunk="$out.chunk" hdr="$out.headers"
  if [ -s "$out" ] && [ "$(wc -c < "$out" | tr -d ' ')" = "$want" ]; then
    echo "cache_hit $tar bytes=$want"
    return 0
  fi
  rm -f "$out"
  touch "$part"
  local attempt=0 have
  while :; do
    have="$(wc -c < "$part" | tr -d ' ')"
    if [ "$have" -gt "$want" ]; then
      echo "WARN: $part larger than pinned prefix; restarting" >&2
      : > "$part"; have=0
    fi
    [ "$have" = "$want" ] && break
    attempt=$((attempt + 1))
    if [ "$attempt" -gt 20 ]; then
      echo "FATAL: $tar prefix incomplete after 20 attempts ($have/$want)" >&2
      return 1
    fi
    rm -f "$chunk" "$hdr"
    # Resume manually: request only the missing byte range (curl -C - cannot
    # be combined with an explicit --range). Stall-based abort, no --max-time.
    if ! curl -fsSL -A "$UA" --connect-timeout 30 \
        --speed-limit 1024 --speed-time 120 \
        -r "$have-$((want - 1))" -D "$hdr" -o "$chunk" "$BASE_URL/$tar"; then
      echo "WARN: curl attempt $attempt for $tar failed; keeping received bytes" >&2
      sleep 5
    fi
    [ -s "$chunk" ] || continue
    # Accept the chunk only if the final response is 206 for the requested
    # start offset and the expected whole-tar size.
    if python3 -I - "$hdr" "$have" "$total" <<'PY'
import re, sys
h = open(sys.argv[1], encoding="iso-8859-1").read()
final = [p for p in re.split(r"(?=^HTTP/)", h, flags=re.M) if p.strip()][-1]
st = re.search(r"^HTTP/\S+\s+(\d+)", final, re.M)
cr = re.search(r"^Content-Range:\s*bytes\s+(\d+)-(\d+)/(\d+)", final, re.I | re.M)
ok = st and st.group(1) == "206" and cr and int(cr.group(1)) == int(sys.argv[2]) and int(cr.group(3)) == int(sys.argv[3])
sys.exit(0 if ok else 1)
PY
    then
      cat "$chunk" >> "$part"
    else
      echo "WARN: unexpected range response for $tar; discarding chunk" >&2
      sleep 5
    fi
  done
  rm -f "$chunk" "$hdr"
  mv "$part" "$out"
  echo "fetched $tar bytes=$want of $total"
}

while read -r tar total want; do
  fetch_prefix "$tar" "$total" "$want"
done <<< "$plan"

# 3. Semantic validation of every prefix against the pinned member table.
python3 -I - "$RECIPE_DIR/scripts" "$MEMBERS_TSV" "$DOWNLOAD_DIR" <<'PY'
import hashlib, json, sys
from pathlib import Path
sys.dont_write_bytecode = True
sys.path.insert(0, sys.argv[1])
import tumvi_lib as L

rows = L.load_members(Path(sys.argv[2]))
dl = Path(sys.argv[3])
pinned_sha = {}
for line in (Path(sys.argv[1]) / "prefix_sha256.tsv").read_text(encoding="utf-8").splitlines()[1:]:
    t, nbytes, digest = line.split("\t")
    pinned_sha[t] = (int(nbytes), digest)
if set(pinned_sha) != set(L.tar_prefixes(rows)):
    raise SystemExit("prefix_sha256.tsv does not cover exactly the pinned tars")
report = {}
total_bytes = 0
for tar, info in L.tar_prefixes(rows).items():
    p = dl / f"{tar}.prefix"
    buf = p.read_bytes()
    if len(buf) != info["prefix_bytes"]:
        raise SystemExit(f"{tar}: prefix size {len(buf)} != {info['prefix_bytes']}")
    rx = L.member_regex(info["sequence"])
    pngs = []
    for name, typ, off, size in L.walk_tar_prefix(buf):
        if typ == b"5":
            continue
        if typ not in (b"0", b"\0") or not rx.match(name):
            raise SystemExit(f"{tar}: unexpected member in prefix: {name!r} type {typ!r}")
        pngs.append((name, off, size))
    pinned = [(m["member"], m["data_offset"], m["size"]) for m in info["members"]]
    if pngs != pinned:
        raise SystemExit(f"{tar}: member list differs from pin\n got={pngs}\n pin={pinned}")
    for m in info["members"]:
        data = buf[m["data_offset"]:m["data_offset"] + m["size"]]
        chunks = L.png_chunks(data)
        w, h, depth, ctype, comp, filt, inter = L.ihdr(chunks)
        if (w, h, depth, ctype, inter) != (1024, 1024, 16, 0, 0):
            raise SystemExit(f"{m['member']}: unexpected IHDR {(w, h, depth, ctype, inter)}")
        if L.last_idat_crc(chunks) != m["last_idat_crc"]:
            raise SystemExit(f"{m['member']}: last IDAT CRC {L.last_idat_crc(chunks)} != pin {m['last_idat_crc']}")
    digest = hashlib.sha256(buf).hexdigest()
    if (len(buf), digest) != pinned_sha[tar]:
        p.rename(p.with_name(p.name + ".bad"))
        raise SystemExit(f"{tar}: prefix SHA-256 {digest} != pin {pinned_sha[tar][1]} (moved aside as .bad; re-run to refetch)")
    report[tar] = {"bytes": len(buf), "sha256": digest, "members": len(pngs)}
    total_bytes += len(buf)
(dl / "prefix_checksums.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
print(f"prefix_validation=ok tars={len(report)} members={len(rows)} bytes={total_bytes}")
PY

echo "[$(date -Is)] download done dataset=$DATASET_ID"
