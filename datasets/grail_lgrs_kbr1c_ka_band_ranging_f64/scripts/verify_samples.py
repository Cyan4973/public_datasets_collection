#!/usr/bin/env python3
"""Independent verification for grail_lgrs_kbr1c_ka_band_ranging_f64.

Does not import the build parser. For every pinned product it re-checks size
and the published MD5, re-parses the ASCII records with its own byte-level
reader, re-derives all four samples and compares them byte for byte, then
checks the index rows, manifest totals and degeneracy rules.
"""
import argparse
import collections
import hashlib
import json
import math
import os
import struct
import sys
import tomllib

DATASET_ID = "grail_lgrs_kbr1c_ka_band_ranging_f64"
PRIMARY = {"kbr1c_biased_range_f64": 1, "kbr1c_range_rate_f64": 2, "kbr1c_range_accl_f64": 3}
AUX = "kbr1c_tdb_seconds_i64"
ALL_SERIES = list(PRIMARY) + [AUX]


def fail(msg):
    print(f"FATAL: {msg}", file=sys.stderr)
    sys.exit(1)


def load_sources(path):
    with open(path, encoding="ascii") as fh:
        lines = [ln.rstrip("\n").split("\t") for ln in fh if ln.strip()]
    head = lines[0]
    return [dict(zip(head, ln)) for ln in lines[1:]]


def parse(data, name):
    marker = b"\r\nEND OF HEADER\r\n"
    pos = data.find(marker)
    if pos < 0:
        fail(f"{name}: no END OF HEADER line")
    header = data[:pos].split(b"\r\n")
    hdr = {}
    for ln in header:
        k, _, v = ln.partition(b":")
        hdr.setdefault(k.strip().decode(), v.strip().decode())
    if int(hdr["NUMBER OF HEADER RECORDS"]) != len(header):
        fail(f"{name}: header record count mismatch")
    body = data[pos + len(marker):]
    if not body.endswith(b"\r\n"):
        fail(f"{name}: body does not end with CRLF")
    cols = ([], [], [], [])
    for i, ln in enumerate(body[:-2].split(b"\r\n")):
        tok = ln.split()
        if len(tok) != 20:
            fail(f"{name}: data line {i}: {len(tok)} columns")
        if not tok[0].isdigit():
            fail(f"{name}: data line {i}: non-integer TDB")
        cols[0].append(int(tok[0]))
        for c in (1, 2, 3):
            v = float(tok[c])
            if not math.isfinite(v):
                fail(f"{name}: data line {i}: non-finite column {c + 1}")
            cols[c].append(v)
        flag = tok[15]
        if len(flag) != 8 or flag.strip(b"01"):
            fail(f"{name}: data line {i}: bad quality flag {flag!r}")
    t = cols[0]
    if len(t) != int(hdr["NUMBER OF DATA RECORDS"]):
        fail(f"{name}: record count != header")
    if t[0] != int(float(hdr["TIME FIRST OBS(SEC PAST EPOCH)"].split()[0])) or t[-1] != int(float(hdr["TIME LAST OBS(SEC PAST EPOCH)"].split()[0])):
        fail(f"{name}: first/last TDB != header")
    for a, b in zip(t, t[1:]):
        if b <= a or (b - a) % 2:
            fail(f"{name}: TDB step {b - a} s is not a positive multiple of 2")
    return cols


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-root", required=True)
    ap.add_argument("--sources", required=True)
    ap.add_argument("--manifest", required=True)
    a = ap.parse_args()
    root = a.data_root
    dl = os.path.join(root, "downloads", DATASET_ID)
    sources = load_sources(a.sources)
    if len(sources) != 107 or sources[0]["date"] != "2012_08_30" or sources[-1]["date"] != "2012_12_14":
        fail("sources.tsv must pin the 107 extended-mission products 2012_08_30..2012_12_14")

    # Volume MD5 manifest must list every pinned product with the pinned MD5.
    listed = {}
    with open(os.path.join(dl, "grail_0101_230316.md5"), encoding="ascii") as fh:
        for ln in fh:
            p = ln.split()
            if len(p) == 2:
                listed[p[1].replace("\\", "/").lower()] = p[0].lower()

    index_path = os.path.join(root, "index", DATASET_ID, "samples.jsonl")
    with open(index_path, encoding="ascii") as fh:
        index = [json.loads(ln) for ln in fh if ln.strip()]
    by_key = {}
    for r in index:
        for k in ("dataset_id", "series_id", "sample_path", "numeric_kind", "bit_width", "endianness",
                  "element_size_bytes", "sample_size_bytes", "value_count"):
            if k not in r:
                fail(f"index row missing {k}: {r.get('sample_path')}")
        if r["dataset_id"] != DATASET_ID or r["series_id"] not in ALL_SERIES:
            fail(f"bad index row {r['sample_path']}")
        key = (r["series_id"], r["date"])
        if key in by_key:
            fail(f"duplicate index row {key}")
        by_key[key] = r
    if len(index) != 4 * len(sources):
        fail(f"index has {len(index)} rows, expected {4 * len(sources)}")

    totals = {s: [0, 0] for s in ALL_SERIES}
    total_records = 0
    for src in sources:
        date, fname = src["date"], src["file"]
        base = f"grail_0101/level_1b/{date}/{fname[:-4]}"
        if listed.get(base + ".asc") != src["asc_md5"] or listed.get(base + ".lbl") != src["label_md5"]:
            fail(f"{fname}: pinned MD5 not in the volume manifest")
        path = os.path.join(dl, date, fname)
        with open(path, "rb") as fh:
            data = fh.read()
        if len(data) != int(src["http_bytes"]) or hashlib.md5(data).hexdigest() != src["asc_md5"]:
            fail(f"{fname}: size or MD5 mismatch")
        with open(os.path.join(dl, date, fname[:-4] + ".lbl"), "rb") as fh:
            if hashlib.md5(fh.read()).hexdigest() != src["label_md5"]:
                fail(f"{fname[:-4]}.lbl: MD5 mismatch")
        cols = parse(data, fname)
        n = len(cols[0])
        if n != int(src["data_records"]):
            fail(f"{fname}: {n} records, pinned {src['data_records']}")
        total_records += n
        # Physical consistency: within phase arcs the published range rate integrates to the range.
        t, rg, rr = cols[0], cols[1], cols[2]
        steps = n - 1
        good = sum(1 for i in range(1, n) if abs(rg[i] - rg[i - 1] - 0.5 * (rr[i] + rr[i - 1]) * (t[i] - t[i - 1])) <= 1.0)
        if steps and good / steps < 0.99:
            fail(f"{fname}: only {good}/{steps} steps have range consistent with range rate")
        for sid in ALL_SERIES:
            r = by_key.get((sid, date))
            if r is None:
                fail(f"missing index row {sid} {date}")
            if sid == AUX:
                expect = struct.pack(f"<{n}q", *cols[0])
                kind, ext = ("int", "i64")
            else:
                expect = struct.pack(f"<{n}d", *cols[PRIMARY[sid]])
                kind, ext = ("float", "f64")
            rel = f"samples/{DATASET_ID}/{sid}/{date}.{ext}"
            if r["sample_path"] != rel or r["numeric_kind"] != kind or r["bit_width"] != 64 or r["endianness"] != "little" \
                    or r["element_size_bytes"] != 8 or r["value_count"] != n or r["sample_size_bytes"] != 8 * n:
                fail(f"index row fields wrong for {rel}")
            with open(os.path.join(root, rel), "rb") as fh:
                got = fh.read()
            if got != expect:
                fail(f"{rel}: bytes differ from the independent re-derivation")
            if r.get("sample_sha256") != hashlib.sha256(got).hexdigest():
                fail(f"{rel}: index sha256 mismatch")
            if r.get("role") != ("auxiliary" if sid == AUX else "primary"):
                fail(f"{rel}: wrong role")
            if sid != AUX:
                vals = struct.unpack(f"<{n}d", got)
                if r.get("min") != min(vals) or r.get("max") != max(vals):
                    fail(f"{rel}: index min/max differ from stored values")
                counts = collections.Counter(vals)
                distinct = len(counts)
                top = counts.most_common(1)[0][1]
                if distinct < 100 or max(vals) == min(vals) or top > 0.5 * n:
                    fail(f"{rel}: degenerate sample (distinct={distinct})")
                if all(struct.unpack("<f", struct.pack("<f", v))[0] == v for v in vals[:1000]):
                    fail(f"{rel}: values round-trip through float32; not native float64 material")
            totals[sid][0] += 1
            totals[sid][1] += len(got)

    with open(a.manifest, "rb") as fh:
        man = tomllib.load(fh)
    declared = {s["id"]: s for s in man["series"]}
    if set(declared) != set(ALL_SERIES):
        fail(f"manifest series {sorted(declared)} != {sorted(ALL_SERIES)}")
    for sid, (count, size) in totals.items():
        if declared[sid]["sample_count"] != count or declared[sid]["total_size_bytes"] != size:
            fail(f"manifest totals for {sid}: declared {declared[sid]['sample_count']}/{declared[sid]['total_size_bytes']}, realized {count}/{size}")
        if declared[sid]["role"] != ("auxiliary" if sid == AUX else "primary"):
            fail(f"manifest role wrong for {sid}")
    for sid in ALL_SERIES:
        d = os.path.join(root, "samples", DATASET_ID, sid)
        extra = set(os.listdir(d)) - {os.path.basename(by_key[(sid, s['date'])]['sample_path']) for s in sources}
        if extra:
            fail(f"unindexed files in {d}: {sorted(extra)[:5]}")
    prim_values = sum(totals[s][1] for s in PRIMARY) // 8
    prim_bytes = sum(totals[s][1] for s in PRIMARY)
    if prim_bytes > 1_000_000_000 or prim_values < 10_000:
        fail("primary payload outside floor/cap")
    print(f"verify ok products={len(sources)} records={total_records} primary_samples={sum(totals[s][0] for s in PRIMARY)} "
          f"primary_values={prim_values} primary_bytes={prim_bytes} aux_bytes={totals[AUX][1]}")


if __name__ == "__main__":
    main()
