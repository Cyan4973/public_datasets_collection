#!/usr/bin/env python3
"""Independent verification of the LoRaIQ SF10 cf32 samples.

Re-derives every sample from its local ZIP byte range with a separate local
header parser and zlib.decompress(wbits=-15), then checks byte identity with
the emitted sample, the SigMF sha512, the index fields, stored-float32
min/max, finiteness, non-constant I and Q, the off-grid (not widened int16)
property, and the manifest totals and realized scope.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import struct
import sys
import tomllib
import zlib
from array import array
from pathlib import Path

DATASET_ID = "zenodo_epfl_loraiq_sf10_iq_frames_f32"
SERIES_ID = "loraiq_sf10_iq_cf32"


def fail(msg: str) -> None:
    raise SystemExit(f"VERIFY FAILED: {msg}")


def member_at(buf: bytes, rel: int) -> tuple[str, bytes, int, int]:
    if buf[rel:rel + 4] != b"PK\x03\x04":
        fail("missing local header signature")
    crc, csize, usize, nlen, elen = struct.unpack_from("<IIIHH", buf, rel + 14)
    method = struct.unpack_from("<H", buf, rel + 8)[0]
    if method != 8:
        fail(f"method {method}")
    name = buf[rel + 30:rel + 30 + nlen].decode("utf-8")
    start = rel + 30 + nlen + elen
    raw = zlib.decompress(buf[start:start + csize], -15)
    if len(raw) != usize or zlib.crc32(raw) & 0xFFFFFFFF != crc:
        fail(f"CRC/size mismatch for {name}")
    return name, raw, crc, start + csize


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--recipe-dir", type=Path, required=True)
    ap.add_argument("--download-dir", type=Path, required=True)
    ap.add_argument("--index", type=Path, required=True)
    ap.add_argument("--data-root", type=Path, required=True)
    args = ap.parse_args()

    manifest = tomllib.loads((args.recipe_dir / "manifest.toml").read_text(encoding="utf-8"))
    series = [s for s in manifest["series"] if s["id"] == SERIES_ID]
    if len(series) != 1 or series[0].get("role") != "primary":
        fail("manifest primary series missing")
    with (args.recipe_dir / "selection.tsv").open(encoding="utf-8", newline="") as handle:
        selection = list(csv.DictReader(handle, delimiter="\t"))
    index = [json.loads(line) for line in args.index.read_text(encoding="utf-8").splitlines() if line.strip()]
    if len(index) != len(selection):
        fail(f"index rows {len(index)} != selection rows {len(selection)}")
    by_member = {r["source_member"]: r for r in index}
    if len(by_member) != len(index):
        fail("duplicate source members in index")

    total = 0
    sizes = []
    sessions, rrhs, areas = set(), set(), set()
    for row in selection:
        rng = args.download_dir / "members" / f"{row['session']}_{row['rrh']}_{row['file_no']}.zipr"
        buf = rng.read_bytes()
        if len(buf) != int(row["range_end"]) - int(row["range_start"]) + 1:
            fail(f"range length {rng.name}")
        dname, data, dcrc, dend = member_at(buf, 0)
        mname, meta_raw, mcrc, mend = member_at(buf, dend)
        if (dname, mname) != (row["data_name"], row["meta_name"]) or mend != len(buf):
            fail(f"member layout {rng.name}")
        if f"{dcrc:08x}" != row["data_crc32"] or f"{mcrc:08x}" != row["meta_crc32"]:
            fail(f"pinned CRC mismatch {rng.name}")
        g = json.loads(meta_raw)["global"]
        if g["core:datatype"] != "cf32_le" or g["core:sample_rate"] != 500000:
            fail(f"SigMF global mismatch {rng.name}")
        if "core:sha512" in g and hashlib.sha512(data).hexdigest() != g["core:sha512"]:
            fail(f"sha512 mismatch {rng.name}")
        ir = by_member.get(dname)
        if ir is None:
            fail(f"{dname} missing from index")
        sample = args.data_root / ir["sample_path"]
        stored = sample.read_bytes()
        if stored != data:
            fail(f"sample bytes differ from source member: {sample}")
        expected = {"dataset_id": DATASET_ID, "series_id": SERIES_ID, "numeric_kind": "float", "bit_width": 32,
                    "endianness": "little", "element_size_bytes": 4, "sample_size_bytes": len(stored),
                    "value_count": len(stored) // 4, "complex_sample_count": len(stored) // 8}
        for k, v in expected.items():
            if ir.get(k) != v:
                fail(f"index field {k}={ir.get(k)!r} != {v!r} for {sample.name}")
        if len(stored) % 8:
            fail(f"partial complex sample in {sample.name}")
        vals = array("f")
        vals.frombytes(stored)
        if sys.byteorder != "little":
            vals.byteswap()
        if not all(math.isfinite(v) for v in vals):
            fail(f"non-finite value in {sample.name}")
        lo, hi = min(vals), max(vals)
        if (lo, hi) != (ir["min"], ir["max"]):
            fail(f"min/max mismatch {sample.name}: {(lo, hi)} vs {(ir['min'], ir['max'])}")
        i_vals, q_vals = vals[0::2], vals[1::2]
        if min(i_vals) == max(i_vals) or min(q_vals) == max(q_vals):
            fail(f"constant I or Q in {sample.name}")
        grid = sum(1 for v in vals if v * 32768.0 == round(v * 32768.0)) / len(vals)
        if grid > 0.01:
            fail(f"{sample.name}: {grid:.4f} of values on the 1/32768 grid")
        uniq = len(set(vals)) / len(vals)
        if uniq < 0.5:
            fail(f"{sample.name}: unique fraction {uniq:.4f}")
        total += len(stored)
        sizes.append(len(stored) // 4)
        sessions.add(row["session"])
        rrhs.add(row["rrh"])
        areas.add(row["area_type"])

    s = series[0]
    if s["sample_count"] != len(index) or s["total_size_bytes"] != total:
        fail(f"manifest sample_count/total_size_bytes {s['sample_count']}/{s['total_size_bytes']} "
             f"!= realized {len(index)}/{total}")
    if total > 1_000_000_000:
        fail("primary output exceeds 1 GB")
    sizes.sort()
    median = sizes[len(sizes) // 2]
    if median < 1000 or total < 100_000:
        fail("below acceptance floor")
    if len(sessions) != 16 or rrhs != {"rrh1", "rrh2", "rrh3", "rrh4"} or areas != {"drone_los", "drone_nlos"}:
        fail(f"realized scope mismatch sessions={len(sessions)} rrhs={sorted(rrhs)} areas={sorted(areas)}")
    files = sorted(p.name for p in (args.data_root / s["output_path"]).glob("*"))
    if len(files) != len(index):
        fail(f"output directory holds {len(files)} files, index has {len(index)}")
    print(f"verify ok samples={len(index)} bytes={total} median_values={median} sessions={len(sessions)} "
          f"rrhs={len(rrhs)} areas={sorted(areas)}")


if __name__ == "__main__":
    main()
