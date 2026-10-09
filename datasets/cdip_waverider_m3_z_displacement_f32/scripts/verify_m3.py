#!/usr/bin/env python3
"""Independent verification of cdip_waverider_m3_z_displacement_f32.

Re-derives every sample from the downloaded .dods responses with its own
fixed-layout XDR decoder (not cdip_dods.py), applies the same missing-value
policy as build (xyzFlagPrimary in {1,2}, xyzFlagSecondary == 0, no
_FillValue -999.99, |z| <= 20.47 m), and checks the emitted samples, index
and manifest byte for byte. Rejects constant or degenerate series.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import struct
import sys
import tomllib

N = 331776
EXPECTED_WINDOWS = 128
FILL_BITS = struct.pack(">f", -999.99)
RATE_BITS = struct.pack(">f", 1.28)
INDEX_KEYS = [
    "dataset_id", "series_id", "sample_path", "numeric_kind", "bit_width",
    "endianness", "element_size_bytes", "sample_size_bytes", "value_count",
]


def fail(msg: str) -> None:
    print(f"VERIFY FAIL: {msg}", file=sys.stderr)
    sys.exit(1)


def decode(path: str, url_path: str) -> bytes:
    buf = open(path, "rb").read()
    expected_dds = (
        "Dataset {\n"
        "    Int32 xyzStartTime;\n"
        "    Float32 xyzSampleRate;\n"
        "    Float32 xyzFilterDelay;\n"
        f"    Byte xyzFlagPrimary[xyzCount = {N}];\n"
        f"    Byte xyzFlagSecondary[xyzCount = {N}];\n"
        f"    Float32 xyzZDisplacement[xyzCount = {N}];\n"
        f"}} {url_path};\n"
        "\nData:\n"
    ).encode()
    if not buf.startswith(expected_dds):
        fail(f"{path}: DDS header differs from the expected projection")
    p = len(expected_dds)
    if buf[p + 4 : p + 8] != RATE_BITS:
        fail(f"{path}: xyzSampleRate is not 1.28")
    p += 12
    pad = (N + 3) // 4 * 4
    flags = []
    for _ in range(2):
        if struct.unpack_from(">ii", buf, p) != (N, N):
            fail(f"{path}: bad flag array counts")
        p += 8
        flags.append(buf[p : p + N])
        p += pad
    if struct.unpack_from(">ii", buf, p) != (N, N):
        fail(f"{path}: bad Z array counts")
    p += 8
    zbe = buf[p : p + 4 * N]
    if p + 4 * N != len(buf):
        fail(f"{path}: payload length mismatch")
    if flags[0].translate(None, b"\x01\x02") != b"":
        fail(f"{path}: xyzFlagPrimary outside {{1,2}}")
    if flags[1].count(0) != N:
        fail(f"{path}: nonzero xyzFlagSecondary")
    # big-endian -> little-endian by reversing each 4-byte group
    le = bytearray(4 * N)
    le[0::4], le[1::4], le[2::4], le[3::4] = zbe[3::4], zbe[2::4], zbe[1::4], zbe[0::4]
    return bytes(le), zbe


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--recipe", required=True)
    ap.add_argument("--data-root", required=True)
    args = ap.parse_args()
    root = os.path.abspath(args.data_root)
    manifest = tomllib.load(open(os.path.join(args.recipe, "manifest.toml"), "rb"))
    did = manifest["dataset_id"]
    series = [s for s in manifest["series"] if s.get("role") == "primary"]
    if len(series) != 1:
        fail("expected exactly one primary series")
    s = series[0]
    sid = s["id"]
    with open(os.path.join(args.recipe, "windows.tsv"), encoding="utf-8") as fh:
        hdr = fh.readline().rstrip("\n").split("\t")
        windows = [dict(zip(hdr, ln.rstrip("\n").split("\t"))) for ln in fh if ln.strip()]
    if len(windows) != EXPECTED_WINDOWS:
        fail(f"windows.tsv has {len(windows)} rows")
    if len({w["station"] for w in windows}) != len(windows):
        fail("more than one window per station")
    if len({w["deployment"] for w in windows}) != len(windows):
        fail("more than one window per deployment")
    idx_path = os.path.join(root, "index", did, "samples.jsonl")
    rows = [json.loads(ln) for ln in open(idx_path, encoding="utf-8") if ln.strip()]
    if len(rows) != len(windows):
        fail(f"index has {len(rows)} rows, expected {len(windows)}")
    out_dir = os.path.join(root, "samples", did, sid)
    on_disk = sorted(f for f in os.listdir(out_dir))
    expected_files = sorted(f"{w['deployment']}.bin" for w in windows)
    if on_disk != expected_files:
        fail("sample directory contents differ from windows.tsv")
    das_re = re.compile(r'String license "These data may be redistributed and used without restriction\."')
    total = 0
    global_distinct: set[bytes] = set()
    for w, row in zip(windows, rows):
        dep = w["deployment"]
        for k in INDEX_KEYS:
            if k not in row:
                fail(f"index row for {dep} lacks {k}")
        rel = f"samples/{did}/{sid}/{dep}.bin"
        if row["sample_path"] != rel or row["dataset_id"] != did or row["series_id"] != sid:
            fail(f"index identity mismatch for {dep}")
        if (row["numeric_kind"], row["bit_width"], row["endianness"], row["element_size_bytes"]) != ("float", 32, "little", 4):
            fail(f"index dtype mismatch for {dep}")
        if row["value_count"] != N or row["sample_size_bytes"] != 4 * N:
            fail(f"index size mismatch for {dep}")
        das = open(os.path.join(root, "downloads", did, "das", f"{dep}.das"), encoding="utf-8").read()
        if "Datawell DWR-M3 directional buoy" not in das or not das_re.search(das):
            fail(f"{dep}: DAS lacks DWR-M3 title or license")
        le, zbe = decode(os.path.join(root, "downloads", did, "dods", f"{dep}_{w['start_index']}_{N}.dods"), w["url_path"])
        sample = open(os.path.join(root, rel), "rb").read()
        if sample != le:
            fail(f"{dep}: sample bytes differ from re-derived source values")
        if hashlib.sha256(sample).hexdigest() != row["sample_sha256"]:
            fail(f"{dep}: sample_sha256 mismatch")
        vals = struct.unpack(f"<{N}f", sample)
        if any(v != v for v in vals):
            fail(f"{dep}: NaN present")
        if any(zbe[i : i + 4] == FILL_BITS for i in range(0, len(zbe), 4)):
            fail(f"{dep}: _FillValue present")
        lo, hi = min(vals), max(vals)
        if lo < -20.47 or hi > 20.47:
            fail(f"{dep}: value outside +-20.47 m")
        if row["min"] != lo or row["max"] != hi:
            fail(f"{dep}: index min/max differ from stored float32")
        distinct = {sample[i : i + 4] for i in range(0, len(sample), 4)}
        if len(distinct) < 50:
            fail(f"{dep}: degenerate ({len(distinct)} distinct values)")
        mean = sum(vals) / N
        if abs(mean) > 0.5:
            fail(f"{dep}: heave mean {mean:.3f} m is not near zero")
        sd = (sum((v - mean) ** 2 for v in vals) / N) ** 0.5
        if sd < 0.02:
            fail(f"{dep}: heave std {sd:.4f} m is degenerate")
        longest = run = 1
        for a, b in zip(vals, vals[1:]):
            run = run + 1 if a == b else 1
            longest = max(longest, run)
        if longest > 256:
            fail(f"{dep}: stuck run of {longest} identical values")
        global_distinct |= distinct
        total += len(sample)
        print(f"ok {dep} min={lo:.2f} max={hi:.2f} sd={sd:.3f} distinct={len(distinct)} longest_run={longest}")
    if s["sample_count"] != len(rows) or s["total_size_bytes"] != total:
        fail(f"manifest sample_count/total_size_bytes ({s['sample_count']}/{s['total_size_bytes']}) != realized ({len(rows)}/{total})")
    if total > 1_000_000_000:
        fail("primary bytes exceed 1 GB cap")
    print(f"verify_ok samples={len(rows)} bytes={total} distinct_values_overall={len(global_distinct)}")


if __name__ == "__main__":
    main()
