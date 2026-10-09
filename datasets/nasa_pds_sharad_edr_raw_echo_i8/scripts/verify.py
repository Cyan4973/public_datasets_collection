#!/usr/bin/env python3
"""Independent verifier for nasa_pds_sharad_edr_raw_echo_i8.

Does not import sharad.py. Re-reads each local detached label with its own
regexes, re-slices the echo bytes of every *_S.DAT row with memoryview, and
byte-compares against the emitted sample. Re-computes statistics with a
different method (bytes.count per level) and checks the index, the manifest
totals, and non-degeneracy (same policy as build: no sample values dropped
or imputed; reject a product with <32 distinct levels, >5% constant echo
rows, or one level >50% of values).
"""
import argparse
import hashlib
import json
import math
import os
import re
import sys
import tomllib

DATASET_ID = "nasa_pds_sharad_edr_raw_echo_i8"
SERIES_ID = "sharad_edr_ss19_echo_i8"
ROW = 3786
HDR = 186
NS = 3600
REQUIRED_INDEX = ["dataset_id", "series_id", "sample_path", "numeric_kind", "bit_width", "endianness",
                  "element_size_bytes", "sample_size_bytes", "value_count"]

fail = []


def bad(msg):
    fail.append(msg)
    print("FAIL " + msg)


def label_value(text, key):
    m = re.search(r"^\s*" + re.escape(key) + r"\s*=\s*(.+?)\s*$", text, re.M)
    return m.group(1).strip().strip('"') if m else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--recipe-dir", required=True)
    ap.add_argument("--data-root", required=True)
    a = ap.parse_args()

    with open(os.path.join(a.recipe_dir, "manifest.toml"), "rb") as fh:
        man = tomllib.load(fh)
    series = [s for s in man["series"] if s["id"] == SERIES_ID]
    if len(series) != 1 or series[0].get("role") != "primary":
        bad("manifest primary series missing")
        sys.exit(1)
    ser = series[0]

    src = []
    with open(os.path.join(a.recipe_dir, "sources.tsv"), encoding="ascii") as fh:
        hdr = fh.readline().rstrip("\n").split("\t")
        for line in fh:
            if line.strip():
                src.append(dict(zip(hdr, line.rstrip("\n").split("\t"))))

    idx_path = os.path.join(a.data_root, "index", DATASET_ID, "samples.jsonl")
    with open(idx_path) as fh:
        idx = [json.loads(l) for l in fh if l.strip()]
    if len(idx) != len(src):
        bad("index rows %d != sources %d" % (len(idx), len(src)))
        sys.exit(1)

    dl = os.path.join(a.data_root, "downloads", DATASET_ID)
    fmt = open(os.path.join(dl, "science8bit.fmt"), encoding="ascii").read()
    if not (re.search(r"ITEMS\s*=\s*3600", fmt) and re.search(r"ITEM_BITS\s*=\s*8", fmt)
            and re.search(r"BIT_DATA_TYPE\s*=\s*MSB_INTEGER", fmt) and re.search(r"START_BYTE\s*=\s*187", fmt)):
        bad("science8bit.fmt layout unexpected")

    total = 0
    shas = set()
    sample_dir = os.path.join(a.data_root, "samples", DATASET_ID, SERIES_ID)
    on_disk = sorted(f for f in os.listdir(sample_dir) if f.endswith(".i8"))
    if len(on_disk) != len(src):
        bad("sample files on disk %d != %d" % (len(on_disk), len(src)))

    for s, ir in zip(src, idx):
        pid = s["product_id"]
        tag = "%02d %s" % (int(s["ordinal"]), pid)
        for k in REQUIRED_INDEX:
            if k not in ir:
                bad("%s: index lacks %s" % (tag, k))
        if (ir["dataset_id"], ir["series_id"], ir["numeric_kind"], ir["bit_width"], ir["endianness"],
                ir["element_size_bytes"]) != (DATASET_ID, SERIES_ID, "int", 8, "little", 1):
            bad("%s: index type fields wrong" % tag)
        if ir.get("product_id") != pid:
            bad("%s: index order/product mismatch" % tag)

        lbl = open(os.path.join(dl, "%02d_%s.lbl" % (int(s["ordinal"]), pid.lower())), encoding="ascii").read()
        rec_bytes = label_value(lbl, "RECORD_BYTES")
        nrec = int(label_value(lbl, "FILE_RECORDS"))
        mode = label_value(lbl, "INSTRUMENT_MODE_ID")
        desc = " ".join(re.search(r"INSTRUMENT_MODE_DESC\s*=\s*\"([^\"]*)\"", lbl).group(1).split())
        if rec_bytes != "3786" or mode != "SS19" or "08-bit precision" not in desc or "summing 04" not in desc:
            bad("%s: label is not SS19/8-bit/3786" % tag)
        if label_value(lbl, "DATA_QUALITY_ID") != "0" or label_value(lbl, "^STRUCTURE") != "SCIENCE8BIT.FMT":
            bad("%s: label DQ/structure" % tag)
        if nrec != int(s["file_records"]):
            bad("%s: label FILE_RECORDS %d != pinned" % (tag, nrec))

        dat = open(os.path.join(dl, "%02d_%s_s.dat" % (int(s["ordinal"]), pid.lower())), "rb").read()
        if len(dat) != nrec * ROW:
            bad("%s: table size %d != %d*3786" % (tag, len(dat), nrec))
            continue
        mv = memoryview(dat)
        echo = b"".join(mv[i * ROW + HDR:(i + 1) * ROW] for i in range(nrec))
        zero_row = bytes(ROW)
        fill = [i for i in range(nrec) if dat[i * ROW:(i + 1) * ROW] == zero_row]
        fillset = set(fill)
        modes = set(dat[i * ROW + 26] for i in range(nrec) if i not in fillset)
        if modes != {51}:
            bad("%s: OPERATIVE_MODE values %s" % (tag, sorted(modes)))
        if ir.get("zero_fill_rows") != len(fill) or len(fill) > 0.01 * nrec:
            bad("%s: zero_fill_rows index=%r recomputed=%d" % (tag, ir.get("zero_fill_rows"), len(fill)))

        spath = os.path.join(a.data_root, ir["sample_path"])
        sample = open(spath, "rb").read()
        if sample != echo:
            bad("%s: sample bytes differ from re-derived echoes" % tag)
        n = len(sample)
        if n != nrec * NS or ir["sample_size_bytes"] != n or ir["value_count"] != n:
            bad("%s: size/value_count mismatch" % tag)
        if ir.get("shape") != [nrec, NS]:
            bad("%s: shape mismatch" % tag)
        sha = hashlib.sha256(sample).hexdigest()
        if ir.get("sha256") != sha:
            bad("%s: sha256 mismatch" % tag)
        shas.add(sha)

        counts = {v: sample.count(bytes([v])) for v in range(256)}
        levels = {(v - 256 if v > 127 else v): c for v, c in counts.items() if c}
        mean = sum(k * c for k, c in levels.items()) / n
        var = sum(c * (k - mean) ** 2 for k, c in levels.items()) / n
        const_rows = sum(1 for i in range(nrec) if sample[i * NS:(i + 1) * NS] == sample[i * NS:i * NS + 1] * NS)
        exp = {"min": min(levels), "max": max(levels), "distinct_values": len(levels),
               "constant_rows": const_rows, "zero_fraction": round(counts[0] / n, 6)}
        for k, v in exp.items():
            if ir.get(k) != v:
                bad("%s: index %s=%r recomputed %r" % (tag, k, ir.get(k), v))
        if abs(ir.get("mean", 1e9) - mean) > 1e-5:
            bad("%s: mean mismatch" % tag)
        if len(levels) < 32 or const_rows > 0.05 * nrec or max(counts.values()) > 0.5 * n or math.sqrt(var) < 2.0:
            bad("%s: degenerate (distinct=%d const_rows=%d std=%.2f)" % (tag, len(levels), const_rows, math.sqrt(var)))
        total += n
        print("ok %s rows=%d bytes=%d range=[%d,%d] distinct=%d mean=%.3f std=%.2f zero=%.4f const_rows=%d zero_fill_rows=%d" % (
            tag, nrec, n, exp["min"], exp["max"], len(levels), mean, math.sqrt(var), exp["zero_fraction"], const_rows,
            len(fill)))

    if len(shas) != len(idx):
        bad("duplicate samples")
    if ser.get("sample_count") != len(idx) or ser.get("total_size_bytes") != total:
        bad("manifest sample_count/total_size_bytes (%s/%s) != realized (%d/%d)" % (
            ser.get("sample_count"), ser.get("total_size_bytes"), len(idx), total))
    if total > 1_000_000_000:
        bad("primary total exceeds 1e9 bytes")
    if fail:
        print("verify FAILED: %d problems" % len(fail))
        sys.exit(1)
    print("verify OK: %d samples, %d bytes" % (len(idx), total))


if __name__ == "__main__":
    main()
