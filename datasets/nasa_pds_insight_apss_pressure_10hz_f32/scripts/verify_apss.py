#!/usr/bin/env python3
"""Independent verification of nasa_pds_insight_apss_pressure_10hz_f32.

Re-derives every sample from the downloaded CSV with a different code path
than apss_ps.py (csv module over a text stream, struct.pack per value),
re-applies the same row policy (drop empty PRESSURE, drop PRESSURE_FREQUENCY
!= 10.0, fatal above 1%), byte-compares each sample, checks that every
stored float32 rounds back to the source 4-decimal string, recomputes index
min/max from the stored float32, and checks index, ingest stats and manifest
counts.  Rejects constant/degenerate series.
"""
import argparse
import csv
import hashlib
import io
import json
import math
import re
import struct
import sys
import tomllib
from pathlib import Path

DATASET_ID = "nasa_pds_insight_apss_pressure_10hz_f32"
SERIES_ID = "insight_apss_pressure_10hz_f32"
FIELDS = ["AOBT", "SCLK", "LMST", "LTST", "UTC", "PRESSURE", "PRESSURE_FREQUENCY",
          "PRESSURE_TEMP", "PRESSURE_TEMP_FREQUENCY"]
DEC4 = re.compile(r"^\d{3,4}\.\d{4}$")


def fail(msg):
    print(f"VERIFY FAIL: {msg}", file=sys.stderr)
    sys.exit(1)


def inventory(path):
    with open(path, encoding="utf-8") as fh:
        rd = csv.DictReader(fh, delimiter="\t")
        return list(rd)


def rederive(path, row):
    raw = path.read_bytes()
    if len(raw) != int(row["size_bytes"]):
        fail(f"{row['file']}: size mismatch")
    if hashlib.md5(raw).hexdigest() != row["md5"]:
        fail(f"{row['file']}: md5 mismatch against PDS4 label value")
    text = io.StringIO(raw.decode("ascii"), newline="")
    rd = csv.reader(text)
    hdr = next(rd)
    if hdr != FIELDS:
        fail(f"{row['file']}: header {hdr}")
    vals, srcs = [], []
    n = blank = non10 = 0
    for rec in rd:
        n += 1
        if len(rec) != 9:
            fail(f"{row['file']}: record {n} has {len(rec)} fields")
        p, fq = rec[5], rec[6]
        if p == "":
            blank += 1
            continue
        if fq != "10.0":
            non10 += 1
            continue
        if not DEC4.match(p):
            fail(f"{row['file']}: record {n} PRESSURE {p!r}")
        vals.append(p)
    if n != int(row["records"]):
        fail(f"{row['file']}: {n} records != label {row['records']}")
    if non10 > 0.01 * n:
        fail(f"{row['file']}: {non10} non-10 Hz rows")
    payload = b"".join(struct.pack("<f", float(p)) for p in vals)
    return payload, vals, n, blank, non10


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--inventory", required=True)
    ap.add_argument("--data-root", required=True)
    ap.add_argument("--manifest", required=True)
    a = ap.parse_args()
    root = Path(a.data_root)
    inv = inventory(a.inventory)
    dl = root / "downloads" / DATASET_ID / "csv"
    sdir = root / "samples" / DATASET_ID / SERIES_ID
    idx_path = root / "index" / DATASET_ID / "samples.jsonl"
    stats = json.loads((root / "filtered" / DATASET_ID / "ingest_stats.json").read_text())
    with open(idx_path, encoding="utf-8") as fh:
        index = [json.loads(ln) for ln in fh if ln.strip()]
    if len(index) != len(inv):
        fail(f"index rows {len(index)} != inventory {len(inv)}")
    by_file = {e["source_file"]: e for e in index}
    expected_paths = set()
    total_vals = total_bytes = tot_blank = tot_non10 = 0
    sols = set()
    for k, row in enumerate(inv, 1):
        e = by_file.get(row["file"])
        if e is None:
            fail(f"no index row for {row['file']}")
        payload, srcs, n, blank, non10 = rederive(dl / row["file"], row)
        sp = root / e["sample_path"]
        expected_paths.add(sp.resolve())
        if e["sample_path"] != f"samples/{DATASET_ID}/{SERIES_ID}/{row['file'][:-4]}.f32":
            fail(f"unexpected sample_path {e['sample_path']}")
        got = sp.read_bytes()
        if got != payload:
            fail(f"{sp.name}: bytes differ from independent re-derivation")
        cnt = len(got) // 4
        stored = struct.unpack(f"<{cnt}f", got)
        for v, s in zip(stored, srcs):
            if f"{v:.4f}" != s:
                fail(f"{sp.name}: float32 {v!r} does not round-trip to {s}")
            if not math.isfinite(v):
                fail(f"{sp.name}: non-finite value")
        mn, mx = min(stored), max(stored)
        distinct = len(set(stored))
        mean = math.fsum(stored) / cnt
        std = math.sqrt(math.fsum((x - mean) ** 2 for x in stored) / cnt)
        if cnt < 1000 or distinct < 1000 or std <= 0.0 or mx - mn <= 0.0:
            fail(f"{sp.name}: degenerate (n={cnt} distinct={distinct} std={std})")
        checks = {
            "dataset_id": DATASET_ID, "series_id": SERIES_ID, "numeric_kind": "float",
            "bit_width": 32, "endianness": "little", "element_size_bytes": 4,
            "sample_size_bytes": len(got), "value_count": cnt, "source_md5": row["md5"],
            "sol": int(row["sol"]), "source_records": n, "blank_pressure_rows": blank,
            "non_10hz_rows": non10, "min": mn, "max": mx,
            "sha256": hashlib.sha256(got).hexdigest(),
        }
        for key, want in checks.items():
            if e.get(key) != want:
                fail(f"{sp.name}: index {key}={e.get(key)!r} expected {want!r}")
        total_vals += cnt
        total_bytes += len(got)
        tot_blank += blank
        tot_non10 += non10
        sols.add(int(row["sol"]))
        print(f"[{k}/{len(inv)}] ok {sp.name} n={cnt} blank={blank} non10={non10} "
              f"range=[{mn:.4f},{mx:.4f}] std={std:.4f} distinct={distinct}")
    present = {p.resolve() for p in sdir.iterdir()}
    if present != expected_paths:
        fail(f"sample dir has unexpected files: {sorted(str(p) for p in present - expected_paths)}")
    if len(sols) != len(inv):
        fail("duplicate sols")
    for key, want in (("samples", len(inv)), ("total_values", total_vals), ("total_bytes", total_bytes),
                      ("blank_pressure_rows", tot_blank), ("non_10hz_rows", tot_non10)):
        if stats.get(key) != want:
            fail(f"ingest_stats {key}={stats.get(key)} expected {want}")
    with open(a.manifest, "rb") as fh:
        man = tomllib.load(fh)
    ser = [s for s in man["series"] if s["id"] == SERIES_ID]
    if len(ser) != 1 or ser[0].get("role") != "primary":
        fail("manifest primary series missing")
    if ser[0]["sample_count"] != len(inv) or ser[0]["total_size_bytes"] != total_bytes:
        fail(f"manifest sample_count/total_size_bytes {ser[0]['sample_count']}/{ser[0]['total_size_bytes']} "
             f"!= realized {len(inv)}/{total_bytes}")
    vc = sorted(e["value_count"] for e in index)
    print(f"verify ok: samples={len(inv)} values={total_vals} bytes={total_bytes} "
          f"median_values={vc[len(vc) // 2]} blank_dropped={tot_blank} non10_dropped={tot_non10}")


if __name__ == "__main__":
    main()
