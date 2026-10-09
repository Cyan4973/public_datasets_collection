#!/usr/bin/env bash
# Independently re-derive every fp/rp sample from the downloaded prefixes
# (own gzip-member inflater, header checks and aux walker; does not import
# scripts/hifi_bam.py) and check samples, index, scope, manifest totals and
# degeneracy.
set -euo pipefail

RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$RECIPE_DIR/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
case "$DATA_DIR" in /*) DATA_ROOT="$DATA_DIR" ;; *) DATA_ROOT="$REPO_ROOT/$DATA_DIR" ;; esac
DATASET_ID="hprc_revio_fiberseq_hifi_pulse_width_u8"
LOG_DIR="$DATA_ROOT/logs/$DATASET_ID"
mkdir -p "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/verify.$RUN_TS.log" "$LOG_DIR/verify.latest.log") 2>&1
echo "[$(date -Is)] verify start dataset=$DATASET_ID"

DATA_ROOT="$DATA_ROOT" MANIFEST="$RECIPE_DIR/manifest.toml" BAMS="$RECIPE_DIR/scripts/bams.tsv" python3 -I -B - <<'PY'
import csv
import hashlib
import json
import os
import statistics
import struct
import tomllib
import zlib
from pathlib import Path

DATASET_ID = "hprc_revio_fiberseq_hifi_pulse_width_u8"
SERIES = {b"fp": "hifi_forward_pulse_width_codecv1_u8", b"rp": "hifi_reverse_pulse_width_codecv1_u8"}
PREFIX_BYTES = 12582912
EXPECTED_FILES = 30
EXPECTED_INDIVIDUALS = 25
NEEDLES = (
    "DS:READTYPE=CCS;Ipd:CodecV1=ip;PulseWidth:CodecV1=pw;",
    "BINDINGKIT=103-496-900;",
    "SEQUENCINGKIT=103-496-700;",
    "ICSVERSION=13.3.0.253824;",
    "FRAMERATEHZ=100.000000",
    "\tPM:REVIO",
    "\tCM:R/P2-C2/5.0-25M",
)
PG_NEEDLES = ("ID:ccs\tPN:ccs\tVN:8.2.0 ", "ID:jasmine\tPN:jasmine\tVN:2.3.0 ", "ID:lima\tVN:2.11.0 ", "ID:pbtrim\tVN:1.1.0 ", "--6ma")

root = Path(os.environ["DATA_ROOT"])
download_dir = root / "downloads" / DATASET_ID
index_path = root / "index" / DATASET_ID / "samples.jsonl"
manifest = tomllib.loads(Path(os.environ["MANIFEST"]).read_text(encoding="utf-8"))
pinned = list(csv.DictReader(open(os.environ["BAMS"], encoding="utf-8"), delimiter="\t"))
inventory = list(csv.DictReader(open(download_dir / "prefix_inventory.tsv", encoding="utf-8"), delimiter="\t"))
assert len(pinned) == EXPECTED_FILES and len({r["sample"] for r in pinned}) == EXPECTED_INDIVIDUALS
assert [(r["key"], r["etag"], r["size_bytes"]) for r in pinned] == [(r["key"], r["etag"], r["full_size_bytes"]) for r in inventory]


def inflate_members(buf):
    """Inflate concatenated gzip members; stop at an incomplete final member."""
    pos, n, view = 0, len(buf), memoryview(buf)
    while pos < n:
        d = zlib.decompressobj(31)
        parts, p = [], pos
        while not d.eof and p < n:
            chunk = view[p : p + 65536]
            parts.append(d.decompress(chunk))
            p += len(chunk)
        if not d.eof:
            return
        yield b"".join(parts)
        pos = p - len(d.unused_data)


FIXED = {ord(c): s for c, s in zip("AcCsSiIf", (1, 1, 1, 2, 2, 4, 4, 4))}
BW = {ord(c): s for c, s in zip("cCsSiIf", (1, 1, 2, 2, 4, 4, 4))}


def derive(data, sample, movie):
    """Return list of (tag, record_ordinal, bytes) after the drop policy, or None if skipped."""
    stream = b"".join(inflate_members(data))
    assert stream[:4] == b"BAM\x01"
    (l_text,) = struct.unpack_from("<i", stream, 4)
    header = stream[8 : 8 + l_text].decode("ascii", "replace")
    p = 8 + l_text
    (n_ref,) = struct.unpack_from("<i", stream, p)
    p += 4
    rg = [line for line in header.splitlines() if line.startswith("@RG")]
    ok = (
        n_ref == 0
        and len(rg) == 1
        and all(nd in rg[0] for nd in NEEDLES)
        and f"\tPU:{movie}" in rg[0]
        and f"\tSM:{sample}_FS" in rg[0]
        and all(nd in header for nd in PG_NEEDLES)
        and "Frames" not in rg[0]
    )
    if not ok:
        return None
    out = []
    rec_no = 0
    while p + 4 <= len(stream):
        (bs,) = struct.unpack_from("<i", stream, p)
        assert 32 <= bs < (1 << 26), f"bad block size {bs}"
        if p + 4 + bs > len(stream):
            break  # truncated final record
        rec = stream[p + 4 : p + 4 + bs]
        p += 4 + bs
        rec_no += 1
        flag = struct.unpack_from("<H", rec, 14)[0]
        assert flag == 4, f"record {rec_no}: flag {flag}"
        l_name = rec[8]
        n_cig = struct.unpack_from("<H", rec, 12)[0]
        (l_seq,) = struct.unpack_from("<i", rec, 16)
        name = rec[32 : 32 + l_name - 1].decode("ascii")
        assert name.startswith(movie + "/") and name.endswith("/ccs"), f"record {rec_no}: bad name"
        q = 32 + l_name + 4 * n_cig + (l_seq + 1) // 2 + l_seq
        found = {}
        while q < bs:
            tag, t = rec[q : q + 2], rec[q + 2]
            q += 3
            if t in FIXED:
                q += FIXED[t]
            elif t in (ord("Z"), ord("H")):
                q = rec.index(b"\x00", q) + 1
            elif t == ord("B"):
                sub = rec[q]
                (cnt,) = struct.unpack_from("<I", rec, q + 1)
                if tag in SERIES:
                    assert sub == ord("C"), f"record {rec_no}: {tag} subtype {chr(sub)}"
                    found[tag] = rec[q + 5 : q + 5 + cnt]
                q += 5 + cnt * BW[sub]
            else:
                raise AssertionError(f"record {rec_no}: unknown aux type {t}")
        assert q == bs, f"record {rec_no}: aux walk overran"
        for tag in (b"fp", b"rp"):
            arr = found.get(tag)
            assert arr is not None, f"record {rec_no}: missing {tag}"
            assert len(arr) in (0, l_seq), f"record {rec_no}: {tag} length {len(arr)} vs {l_seq}"
            if not arr or arr.count(arr[0]) == len(arr):
                continue  # empty strand or constant array: dropped (same policy as build)
            out.append((tag, rec_no, arr))
    return out


expected = []  # (series_id, ordinal, sample, movie, record_ordinal, bytes)
files_used = set()
for inv in inventory:
    data = (download_dir / inv["prefix_file"]).read_bytes()
    assert len(data) == PREFIX_BYTES, f"{inv['prefix_file']}: size"
    assert hashlib.sha256(data).hexdigest() == inv["prefix_sha256"], f"{inv['prefix_file']}: sha256"
    got = derive(data, inv["sample"], inv["movie"])
    if got is None:
        print(f"skip nonconforming {inv['ordinal']} {inv['sample']}")
        continue
    files_used.add(inv["ordinal"])
    for tag, rec_no, arr in got:
        expected.append((SERIES[tag], int(inv["ordinal"]), inv["sample"], inv["movie"], rec_no, arr))

rows = [json.loads(line) for line in index_path.read_text(encoding="utf-8").splitlines() if line.strip()]
assert len(rows) == len(expected), f"index has {len(rows)} rows, re-derived {len(expected)}"
per_series = {sid: {"n": 0, "bytes": 0, "lengths": [], "counts": [0] * 256, "individuals": set(), "files": set()} for sid in SERIES.values()}
indexed = set()
for row, (sid, ordn, sample, movie, rec_no, arr) in zip(rows, expected):
    for key in ("dataset_id", "series_id", "sample_path", "numeric_kind", "bit_width", "endianness", "element_size_bytes", "sample_size_bytes", "value_count"):
        assert key in row, f"index row lacks {key}"
    assert row["dataset_id"] == DATASET_ID and row["series_id"] == sid, f"series/order mismatch at {row['sample_path']}"
    assert (row["source_file_ordinal"], row["individual"], row["movie"], row["record_ordinal"]) == (ordn, sample, movie, rec_no), f"order mismatch at {row['sample_path']}"
    assert (row["numeric_kind"], row["bit_width"], row["endianness"], row["element_size_bytes"]) == ("uint", 8, "little", 1)
    path = root / row["sample_path"]
    payload = path.read_bytes()
    assert payload == arr, f"sample bytes differ: {row['sample_path']}"
    assert row["value_count"] == row["sample_size_bytes"] == len(payload)
    assert row["code_min"] == min(arr) and row["code_max"] == max(arr) and row["code_distinct"] == len(set(arr))
    assert row["code_distinct"] >= 2, "constant sample"
    indexed.add(row["sample_path"])
    s = per_series[sid]
    s["n"] += 1
    s["bytes"] += len(payload)
    s["lengths"].append(len(payload))
    s["individuals"].add(sample)
    s["files"].add(ordn)
    if s["n"] % 50 == 1:
        for b in payload:
            s["counts"][b] += 1

on_disk = {p.relative_to(root).as_posix() for sid in SERIES.values() for p in (root / "samples" / DATASET_ID / sid).iterdir()}
assert on_disk == indexed, f"stale or missing sample files: {len(on_disk ^ indexed)}"
assert len(files_used) == EXPECTED_FILES, f"only {len(files_used)} conforming files (manifest claims {EXPECTED_FILES})"
total = 0
mseries = {s["id"]: s for s in manifest["series"]}
for sid, s in per_series.items():
    assert len(s["files"]) == EXPECTED_FILES and len(s["individuals"]) == EXPECTED_INDIVIDUALS, f"{sid}: scope {len(s['files'])} files / {len(s['individuals'])} individuals"
    med = statistics.median(s["lengths"])
    assert med >= 1000, f"{sid}: median {med} below floor"
    distinct = sum(1 for c in s["counts"] if c)
    assert distinct >= 64, f"{sid}: degenerate code alphabet in spot check ({distinct})"
    top = max(s["counts"]) / sum(s["counts"])
    assert top < 0.5, f"{sid}: one code dominates the spot check ({top:.3f})"
    assert mseries[sid]["sample_count"] == s["n"], f"{sid}: manifest sample_count {mseries[sid]['sample_count']} != {s['n']}"
    assert mseries[sid]["total_size_bytes"] == s["bytes"], f"{sid}: manifest total_size_bytes {mseries[sid]['total_size_bytes']} != {s['bytes']}"
    total += s["bytes"]
    print(f"{sid}: samples={s['n']} values={s['bytes']} median={med} min={min(s['lengths'])} max={max(s['lengths'])} spot_distinct={distinct} spot_top_share={top:.4f}")
assert total <= 1_000_000_000
print(f"verify ok files={len(files_used)} samples={len(rows)} primary_bytes={total}")
PY

echo "[$(date -Is)] verify done dataset=$DATASET_ID"
