#!/usr/bin/env bash
# Build one raw uint8 sample per PacBio subread: the BAM 'ip' aux array
# (B:C, IPD in CodecV1 8-bit codes) exactly as stored. Local files only.
set -euo pipefail

RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$RECIPE_DIR/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="zenodo_pacbio_sequel_subread_ipd_codecv1_u8"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
mkdir -p "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/build.$RUN_TS.log" "$LOG_DIR/build.latest.log") 2>&1
echo "[$(date -Is)] build start dataset=$DATASET_ID"

DATA_ROOT="$DATA_ROOT" SCRIPTS="$RECIPE_DIR/scripts" python3 -I -B - <<'PY'
import collections
import hashlib
import json
import os
import re
import shutil
import statistics
import sys
from pathlib import Path

sys.path.insert(0, os.environ["SCRIPTS"])
import pacbio_bam as pb

DATASET_ID = "zenodo_pacbio_sequel_subread_ipd_codecv1_u8"
SERIES_ID = "subread_ipd_codecv1_u8"
PREFIX_BYTES = 268435456
MAX_PRIMARY_BYTES = 1_000_000_000
MOVIE = "m54091_180306_141024"
READ_GROUP = "dbce2615"
REQUIRED_DS = [
    "READTYPE=SUBREAD",
    "Ipd:CodecV1=ip",
    "PulseWidth:CodecV1=pw",
    "BINDINGKIT=100-862-200",
    "SEQUENCINGKIT=100-861-800",
    "BASECALLERVERSION=5.0.0.6236",
    "FRAMERATEHZ=80.000000",
]
NAME_RE = re.compile(r"^(m\d+_\d+_\d+)/(\d+)/(\d+)_(\d+)$")

root = Path(os.environ["DATA_ROOT"])
download_dir = root / "downloads" / DATASET_ID
out_dir = root / "samples" / DATASET_ID / SERIES_ID
index_dir = root / "index" / DATASET_ID
filter_dir = root / "filtered" / DATASET_ID
source = download_dir / f"veillonella.subreads.prefix_{PREFIX_BYTES}.bam"
inventory_path = download_dir / "download_inventory.json"


def rel(path: Path) -> str:
    return path.relative_to(root).as_posix()


if not source.is_file() or not inventory_path.is_file():
    raise SystemExit(f"missing download ({source} / {inventory_path}); run download.sh first")
if source.stat().st_size != PREFIX_BYTES:
    raise SystemExit(f"prefix size {source.stat().st_size} != {PREFIX_BYTES}")
inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
sha = hashlib.sha256()
with source.open("rb") as fh:
    for block in iter(lambda: fh.read(1 << 22), b""):
        sha.update(block)
if sha.hexdigest() != inventory["prefix_sha256"]:
    raise SystemExit("prefix sha256 differs from download_inventory.json")
if sha.hexdigest() != "1f5b05dd9f69dcbcc3b6c595b3a0d328d7f238f2eba2f96106dabf5b0b782ecb":
    raise SystemExit("prefix sha256 differs from the pinned value")

if out_dir.exists():
    shutil.rmtree(out_dir)
out_dir.mkdir(parents=True)
index_dir.mkdir(parents=True, exist_ok=True)
filter_dir.mkdir(parents=True, exist_ok=True)

rows = []
lengths = []
hist = collections.Counter()
seen_names = set()
dropped_empty = 0
dropped_constant = 0
total_bytes = 0

prefix_data = source.read_bytes()
reader = pb.BamPrefixReader(prefix_data)
text = reader.read_header()
rg = [line for line in text.splitlines() if line.startswith("@RG\t")]
if len(rg) != 1:
    raise SystemExit(f"expected one @RG line, found {len(rg)}")
fields = dict(item.split(":", 1) for item in rg[0].split("\t")[1:])
ds = fields.get("DS", "").split(";")
missing = [item for item in REQUIRED_DS if item not in ds]
if missing:
    raise SystemExit(f"@RG DS lacks {missing}")
if any(item.startswith("Ipd:Frames") for item in ds):
    raise SystemExit("@RG declares raw-frame IPD; expected CodecV1 only")
if fields.get("PM") != "SEQUEL" or fields.get("PU") != MOVIE or fields.get("ID") != READ_GROUP or fields.get("PL") != "PACBIO":
    raise SystemExit(f"@RG identity changed: {fields}")
if reader.references:
    raise SystemExit("unexpected reference sequences in subreads BAM")
print(f"header ok: {rg[0]}")

ordinal = 0
for rec in reader.records():
    ordinal += 1
    name = rec["name"]
    match = NAME_RE.match(name)
    if not match or match.group(1) != MOVIE:
        raise SystemExit(f"unexpected subread name {name!r}")
    zmw, qs, qe = int(match.group(2)), int(match.group(3)), int(match.group(4))
    aux = rec["aux"]
    if name in seen_names:
        raise SystemExit(f"duplicate subread {name}")
    seen_names.add(name)
    if rec["flag"] != 4 or rec["ref_id"] != -1:
        raise SystemExit(f"{name}: not an unaligned subread record (flag={rec['flag']})")
    if aux.get("RG") != ("Z", READ_GROUP):
        raise SystemExit(f"{name}: unexpected read group {aux.get('RG')}")
    if aux.get("zm", (None, None))[1] != zmw or aux.get("qs", (None, None))[1] != qs or aux.get("qe", (None, None))[1] != qe:
        raise SystemExit(f"{name}: zm/qs/qe tags disagree with read name")
    if "ip" not in aux:
        raise SystemExit(f"{name}: missing ip tag")
    typ, ip = aux["ip"]
    if typ != "BC":
        raise SystemExit(f"{name}: ip has type {typ}, expected B:C (CodecV1 uint8)")
    if len(ip) != rec["l_seq"] or len(ip) != qe - qs:
        raise SystemExit(f"{name}: ip length {len(ip)} != l_seq {rec['l_seq']} / qe-qs {qe - qs}")
    if not ip:
        dropped_empty += 1
        continue
    if ip.count(ip[0]) == len(ip):
        dropped_constant += 1
        print(f"drop constant subread {name} len={len(ip)}")
        continue
    total_bytes += len(ip)
    if total_bytes > MAX_PRIMARY_BYTES:
        raise SystemExit(f"primary output exceeds cap: {total_bytes}")
    out = out_dir / f"{ordinal:05d}_zmw{zmw}_{qs}_{qe}.bin"
    out.write_bytes(ip)
    hist.update(ip)
    lengths.append(len(ip))
    rows.append(
        {
            "dataset_id": DATASET_ID,
            "series_id": SERIES_ID,
            "role": "primary",
            "sample_path": rel(out),
            "numeric_kind": "uint",
            "bit_width": 8,
            "endianness": "little",
            "element_size_bytes": 1,
            "sample_size_bytes": len(ip),
            "value_count": len(ip),
            "sample_geometry": "per_base_subread_sequence_1d",
            "sample_rank": 1,
            "sample_axes": ["called_base"],
            "natural_record_kind": "pacbio_subread_bam_record",
            "record_ordinal": ordinal,
            "read_name": name,
            "zmw": zmw,
            "qstart": qs,
            "qend": qe,
            "context_flags": aux.get("cx", (None, None))[1],
            "code_min": min(ip),
            "code_max": max(ip),
            "code_distinct": len(set(ip)),
        }
    )
members_used = reader.members_used
leftover = reader.leftover_bytes

if len(rows) < 5000:
    raise SystemExit(f"only {len(rows)} subreads built; expected about 14,700")
median = statistics.median(lengths)
if median < 1000:
    raise SystemExit(f"median subread length {median} below floor")
q = statistics.quantiles(lengths, n=20)
total_values = sum(lengths)
stats = {
    "dataset_id": DATASET_ID,
    "series_id": SERIES_ID,
    "source_prefix": source.name,
    "source_prefix_sha256": inventory["prefix_sha256"],
    "bgzf_members_used": members_used,
    "decompressed_tail_bytes_dropped": leftover,
    "records_complete": ordinal,
    "samples": len(rows),
    "dropped_empty": dropped_empty,
    "dropped_constant": dropped_constant,
    "total_values": total_values,
    "length_min": min(lengths),
    "length_p05": q[0],
    "length_p10": q[1],
    "length_p25": q[4],
    "length_median": median,
    "length_p75": q[14],
    "length_p90": q[17],
    "length_p95": q[18],
    "length_max": max(lengths),
    "samples_under_1000_values": sum(1 for n in lengths if n < 1000),
    "distinct_zmws": len({r["zmw"] for r in rows}),
    "code_distinct": len(hist),
    "code_fraction_0_63": round(sum(v for k, v in hist.items() if k < 64) / total_values, 6),
    "code_fraction_64_127": round(sum(v for k, v in hist.items() if 64 <= k < 128) / total_values, 6),
    "code_fraction_128_191": round(sum(v for k, v in hist.items() if 128 <= k < 192) / total_values, 6),
    "code_fraction_192_255": round(sum(v for k, v in hist.items() if k >= 192) / total_values, 6),
    "code_fraction_255_capped": round(hist[255] / total_values, 6),
    "code_histogram": {str(k): hist[k] for k in range(256) if hist[k]},
}
(filter_dir / "ingest_stats.json").write_text(json.dumps(stats, indent=2) + "\n", encoding="utf-8")
with (index_dir / "samples.jsonl").open("w", encoding="utf-8") as fh:
    for row in rows:
        fh.write(json.dumps(row, sort_keys=True) + "\n")
print(json.dumps({k: v for k, v in stats.items() if k != "code_histogram"}, indent=1))
print(f"built_samples={len(rows)} primary_values={total_values} primary_bytes={total_bytes}")
PY

echo "[$(date -Is)] build done dataset=$DATASET_ID"
