#!/usr/bin/env bash
# Build raw uint8 samples of PacBio Revio HiFi consensus pulse width: one
# sample per non-empty 'fp' (forward strand) and one per non-empty 'rp'
# (reverse strand) B:C array of every complete record in the 30 pinned BAM
# prefixes. CodecV1 codes are copied unchanged. Local files only.
set -euo pipefail

RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$RECIPE_DIR/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="hprc_revio_fiberseq_hifi_pulse_width_u8"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
mkdir -p "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/build.$RUN_TS.log" "$LOG_DIR/build.latest.log") 2>&1
echo "[$(date -Is)] build start dataset=$DATASET_ID"

DATA_ROOT="$DATA_ROOT" SCRIPTS="$RECIPE_DIR/scripts" python3 -I -B - <<'PY'
import collections
import csv
import hashlib
import json
import os
import re
import shutil
import statistics
import sys
from pathlib import Path

sys.path.insert(0, os.environ["SCRIPTS"])
import hifi_bam as hb

DATASET_ID = "hprc_revio_fiberseq_hifi_pulse_width_u8"
SERIES = {"fp": "hifi_forward_pulse_width_codecv1_u8", "rp": "hifi_reverse_pulse_width_codecv1_u8"}
STRAND = {"fp": "forward", "rp": "reverse"}
PASSES_TAG = {"fp": "fn", "rp": "rn"}
PREFIX_BYTES = 12582912
MAX_PRIMARY_BYTES = 1_000_000_000

root = Path(os.environ["DATA_ROOT"])
download_dir = root / "downloads" / DATASET_ID
sample_root = root / "samples" / DATASET_ID
index_dir = root / "index" / DATASET_ID
filter_dir = root / "filtered" / DATASET_ID
pinned = list(csv.DictReader(open(Path(os.environ["SCRIPTS"]) / "bams.tsv", encoding="utf-8"), delimiter="\t"))
inv_path = download_dir / "prefix_inventory.tsv"
if not inv_path.is_file():
    raise SystemExit(f"missing {inv_path}; run download.sh first")
inventory = list(csv.DictReader(open(inv_path, encoding="utf-8"), delimiter="\t"))
if [(r["ordinal"], r["key"], r["etag"]) for r in inventory] != [(r["ordinal"], r["key"], r["etag"]) for r in pinned]:
    raise SystemExit("prefix_inventory.tsv does not match scripts/bams.tsv")


def rel(path: Path) -> str:
    return path.relative_to(root).as_posix()


if sample_root.exists():
    shutil.rmtree(sample_root)
for sid in SERIES.values():
    (sample_root / sid).mkdir(parents=True)
index_dir.mkdir(parents=True, exist_ok=True)
filter_dir.mkdir(parents=True, exist_ok=True)

rows = []
per_file = []
skipped_files = []
lengths = {k: [] for k in SERIES}
hist = {k: collections.Counter() for k in SERIES}
dropped_empty = collections.Counter()
dropped_constant = collections.Counter()
flank_zero_samples = collections.Counter()
empty_with_passes = collections.Counter()
nonempty_without_passes = collections.Counter()
total_bytes = 0

for inv in inventory:
    ordinal, sample, movie = inv["ordinal"], inv["sample"], inv["movie"]
    path = download_dir / inv["prefix_file"]
    data = path.read_bytes()
    if len(data) != PREFIX_BYTES:
        raise SystemExit(f"{path.name}: size {len(data)} != {PREFIX_BYTES}")
    if hashlib.sha256(data).hexdigest() != inv["prefix_sha256"]:
        raise SystemExit(f"{path.name}: sha256 differs from prefix_inventory.tsv")
    reader = hb.BamPrefixReader(data)
    text = reader.read_header()
    problems = hb.header_problems(text, sample, movie)
    if reader.references:
        problems.append(f"{len(reader.references)} reference sequences (expected unaligned)")
    if problems:
        skipped_files.append({"ordinal": ordinal, "sample": sample, "movie": movie, "problems": problems})
        print(f"SKIP {ordinal} {sample} {movie}: {problems}")
        continue
    rg_id = hb.rg_fields(text)[0]["ID"]
    name_re = re.compile(r"^" + re.escape(movie) + r"/(\d+)/ccs$")
    zmws = set()
    n_rec = 0
    n_emit = collections.Counter()
    for rec in reader.records():
        n_rec += 1
        m = name_re.match(rec["name"])
        if not m:
            raise SystemExit(f"{ordinal}: unexpected read name pattern in record {n_rec}")
        zmw = int(m.group(1))
        if zmw in zmws:
            raise SystemExit(f"{ordinal}: duplicate ZMW in record {n_rec}")
        zmws.add(zmw)
        aux = rec["aux"]
        if rec["flag"] != 4 or rec["ref_id"] != -1:
            raise SystemExit(f"{ordinal} record {n_rec}: not unaligned (flag={rec['flag']})")
        if aux.get("RG") != ("Z", rg_id):
            raise SystemExit(f"{ordinal} record {n_rec}: read group {aux.get('RG')} != {rg_id}")
        for tag, sid in SERIES.items():
            if tag not in aux:
                raise SystemExit(f"{ordinal} record {n_rec}: missing {tag} (kinetics stripped?)")
            typ, arr = aux[tag]
            if typ != "BC":
                raise SystemExit(f"{ordinal} record {n_rec}: {tag} has type {typ}, expected B:C")
            if len(arr) not in (0, rec["l_seq"]):
                raise SystemExit(f"{ordinal} record {n_rec}: {tag} length {len(arr)} vs l_seq {rec['l_seq']}")
            ptyp, passes = aux.get(PASSES_TAG[tag], (None, None))
            if not isinstance(passes, int):
                raise SystemExit(f"{ordinal} record {n_rec}: missing integer {PASSES_TAG[tag]}")
            if not arr:
                dropped_empty[tag] += 1
                if passes != 0:
                    empty_with_passes[tag] += 1
                continue
            if passes == 0:
                nonempty_without_passes[tag] += 1
            if arr.count(arr[0]) == len(arr):
                dropped_constant[tag] += 1
                continue
            lead = len(arr) - len(arr.lstrip(b"\x00"))
            trail = len(arr) - len(arr.rstrip(b"\x00"))
            if lead or trail:
                flank_zero_samples[tag] += 1
            total_bytes += len(arr)
            if total_bytes > MAX_PRIMARY_BYTES:
                raise SystemExit(f"primary output exceeds cap: {total_bytes}")
            out = sample_root / sid / f"{ordinal}_{sample}_{movie}_r{n_rec:04d}_{tag}.bin"
            out.write_bytes(arr)
            hist[tag].update(arr)
            lengths[tag].append(len(arr))
            n_emit[tag] += 1
            rows.append(
                {
                    "dataset_id": DATASET_ID,
                    "series_id": sid,
                    "role": "primary",
                    "sample_path": rel(out),
                    "numeric_kind": "uint",
                    "bit_width": 8,
                    "endianness": "little",
                    "element_size_bytes": 1,
                    "sample_size_bytes": len(arr),
                    "value_count": len(arr),
                    "sample_geometry": "per_base_hifi_read_sequence_1d",
                    "sample_rank": 1,
                    "sample_axes": ["called_base"],
                    "natural_record_kind": "pacbio_hifi_read_bam_record_strand_kinetics",
                    "strand": STRAND[tag],
                    "array_order": "seq_5p_to_3p" if tag == "fp" else "seq_3p_to_5p (reverse of SEQ, as stored)",
                    "source_file_ordinal": int(ordinal),
                    "individual": sample,
                    "movie": movie,
                    "record_ordinal": n_rec,
                    "strand_passes": passes,
                    "leading_zero_codes": lead,
                    "trailing_zero_codes": trail,
                    "code_min": min(arr),
                    "code_max": max(arr),
                    "code_distinct": len(set(arr)),
                }
            )
    per_file.append(
        {
            "ordinal": ordinal,
            "sample": sample,
            "movie": movie,
            "bgzf_members_used": reader.members_used,
            "decompressed_tail_bytes_dropped": reader.leftover_bytes,
            "complete_records": n_rec,
            "fp_samples": n_emit["fp"],
            "rp_samples": n_emit["rp"],
        }
    )
    print(f"file {ordinal} {sample} {movie}: records={n_rec} fp={n_emit['fp']} rp={n_emit['rp']} tail_dropped={reader.leftover_bytes}")

if len(per_file) < 25:
    raise SystemExit(f"only {len(per_file)} conforming files; expected 30")


def summary(tag):
    ls = lengths[tag]
    q = statistics.quantiles(ls, n=20)
    h = hist[tag]
    tot = sum(ls)
    return {
        "series_id": SERIES[tag],
        "samples": len(ls),
        "total_values": tot,
        "length_min": min(ls),
        "length_p05": q[0],
        "length_median": statistics.median(ls),
        "length_p95": q[18],
        "length_max": max(ls),
        "samples_under_1000_values": sum(1 for n in ls if n < 1000),
        "dropped_empty": dropped_empty[tag],
        "dropped_constant": dropped_constant[tag],
        "empty_array_with_nonzero_passes": empty_with_passes[tag],
        "nonempty_array_with_zero_passes": nonempty_without_passes[tag],
        "samples_with_flanking_zero_codes": flank_zero_samples[tag],
        "code_distinct": len(h),
        "code_fraction_0_63": round(sum(v for k, v in h.items() if k < 64) / tot, 6),
        "code_fraction_64_127": round(sum(v for k, v in h.items() if 64 <= k < 128) / tot, 6),
        "code_fraction_128_191": round(sum(v for k, v in h.items() if 128 <= k < 192) / tot, 6),
        "code_fraction_192_255": round(sum(v for k, v in h.items() if k >= 192) / tot, 6),
        "code_fraction_zero": round(h[0] / tot, 6),
        "code_fraction_255": round(h[255] / tot, 6),
        "top_codes": h.most_common(10),
        "code_histogram": {str(k): h[k] for k in range(256) if h[k]},
    }


for tag in SERIES:
    if len(lengths[tag]) < 1000:
        raise SystemExit(f"only {len(lengths[tag])} {tag} samples built")
    if statistics.median(lengths[tag]) < 1000:
        raise SystemExit(f"median {tag} length below floor")
stats = {
    "dataset_id": DATASET_ID,
    "prefix_bytes_per_file": PREFIX_BYTES,
    "files_used": len(per_file),
    "files_skipped": skipped_files,
    "individuals_used": len({f["sample"] for f in per_file}),
    "complete_records": sum(f["complete_records"] for f in per_file),
    "primary_bytes": total_bytes,
    "series": {tag: summary(tag) for tag in SERIES},
    "per_file": per_file,
}
(filter_dir / "ingest_stats.json").write_text(json.dumps(stats, indent=2) + "\n", encoding="utf-8")
with (index_dir / "samples.jsonl").open("w", encoding="utf-8") as fh:
    for row in rows:
        fh.write(json.dumps(row, sort_keys=True) + "\n")
brief = {k: v for k, v in stats.items() if k not in ("series", "per_file")}
brief["series"] = {t: {k: v for k, v in s.items() if k != "code_histogram"} for t, s in stats["series"].items()}
print(json.dumps(brief, indent=1))
for tag, sid in SERIES.items():
    print(f"series {sid}: sample_count={len(lengths[tag])} total_size_bytes={sum(lengths[tag])}")
print(f"built_samples={len(rows)} primary_bytes={total_bytes}")
PY

echo "[$(date -Is)] build done dataset=$DATASET_ID"
