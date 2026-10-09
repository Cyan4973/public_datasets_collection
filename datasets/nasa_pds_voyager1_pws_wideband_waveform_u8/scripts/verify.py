#!/usr/bin/env python3
"""Independent verification for nasa_pds_voyager1_pws_wideband_waveform_u8.

Re-implements the record walk, line rule, nibble unpacking and frame rule
(does not import vgpws.py), re-derives every sample from the local DAT/LBL,
byte-compares it with the emitted sample, and checks the index, exclusions,
manifest totals, stratum coverage and non-degeneracy.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sys
import tomllib
from collections import Counter
from pathlib import Path

DATASET_ID = "nasa_pds_voyager1_pws_wideband_waveform_u8"
SERIES_ID = "vg1_pws_wideband_4bit_code_u8"
MIN_KEPT_LINES = 50
MIN_DISTINCT = 6
MAX_MODE_FRACTION = 0.80
STRATA = {"A_prejupiter", "B_jupiter", "C_jupiter_saturn", "D_saturn", "E_cruise_full",
          "F_cruise_decimated", "G_heliosheath", "H_interstellar"}
PAIR = [bytes(divmod(b, 16)) for b in range(256)]  # (high nibble, low nibble)


def fail(msg: str) -> None:
    raise SystemExit(f"VERIFY FAIL: {msg}")


def rederive(data: bytes) -> tuple[bytes, dict]:
    if len(data) % 1024:
        fail(f"size {len(data)} not a multiple of 1024")
    if not data[248:261] == b"VOYAGER-1 PWS":
        fail(f"header label {data[248:300]!r}")
    out = []
    kept = repeat = zero = bad = 0
    last_line = 0
    last_kept = b""
    n_rec = len(data) // 1024 - 1
    for r in range(1, n_rec + 1):
        rec = data[r * 1024:(r + 1) * 1024]
        line = int.from_bytes(rec[22:24], "big")
        if not (1 <= line <= 800) or line <= last_line:
            bad += 1
            continue
        last_line = line
        wf = rec[220:1020]
        if wf.count(0) == 800:
            zero += 1
            continue
        if wf == last_kept:
            repeat += 1
            continue
        last_kept = wf
        kept += 1
        out.extend(PAIR[b] for b in wf[8:])
    return b"".join(out), {"kept_lines": kept, "repeat_lines": repeat, "zero_fill_lines": zero,
                           "bad_line_records": bad, "data_records": n_rec}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", type=Path, required=True)
    ap.add_argument("--recipe-dir", type=Path, required=True)
    args = ap.parse_args()
    data_dir, recipe = args.data_dir, args.recipe_dir
    dl = data_dir / "downloads" / DATASET_ID
    sample_dir = data_dir / "samples" / DATASET_ID / SERIES_ID

    with (recipe / "sources.tsv").open(encoding="utf-8") as fh:
        sources = list(csv.DictReader(fh, delimiter="\t"))
    with (dl / "download_plan.tsv").open(encoding="utf-8") as fh:
        plan = {r["product_id"]: r for r in csv.DictReader(fh, delimiter="\t")}
    index_rows = [json.loads(x) for x in
                  (data_dir / "index" / DATASET_ID / "samples.jsonl").read_text(encoding="utf-8").splitlines()]
    by_path = {r["sample_path"]: r for r in index_rows}
    if len(by_path) != len(index_rows):
        fail("duplicate sample_path in index")
    if len({s["product_id"] for s in sources}) != len(sources):
        fail("duplicate product in sources.tsv")

    expected = set()
    hashes = set()
    hist = Counter()
    strata_seen = Counter()
    excluded = 0
    for src in sources:
        product = src["product_id"]
        if not re.fullmatch(r"VG1P\d\dC\d{7}", product):
            fail(f"{product}: not a Voyager 1 waveform product id")
        if src["stratum"] not in STRATA:
            fail(f"{product}: unknown stratum {src['stratum']}")
        dat = (dl / "frames" / f"{src['path_stem']}.DAT").read_bytes()
        lbl = (dl / "frames" / f"{src['path_stem']}.LBL").read_text(encoding="latin-1")
        if len(dat) != int(src["dat_size"]):
            fail(f"{product}: DAT size")
        if hashlib.sha256(dat).hexdigest() != plan[product]["dat_sha256"]:
            fail(f"{product}: DAT sha256 differs from download plan")
        if hashlib.md5(dat).hexdigest() != src["dat_md5"]:
            fail(f"{product}: DAT md5 differs from upstream MD5LF pin")
        for pat in (r'DATA_SET_ID\s*=\s*"VG1-J/S/SS-PWS-1-EDR-WFRM-60MS-V1.0"', r"INSTRUMENT_HOST_ID\s*=\s*VG1\b",
                    rf'PRODUCT_ID\s*=\s*"{product}"', r"OFFSET\s*=\s*-7\.5", r"ITEM_BITS\s*=\s*4\b",
                    r"START_BIT\s*=\s*1\b", r"START_BYTE\s*=\s*221\b", rf"START_TIME\s*=\s*{re.escape(src['start_time'])}"):
            if not re.search(pat, lbl):
                fail(f"{product}: label lacks {pat}")
        m = re.search(r"FILE_RECORDS\s*=\s*(\d+)", lbl)
        if not m or int(m.group(1)) * 1024 != len(dat):
            fail(f"{product}: FILE_RECORDS inconsistent with DAT size")
        payload, st = rederive(dat)
        rel = f"samples/{DATASET_ID}/{SERIES_ID}/{product}.u8"
        c = Counter(payload)
        mode = (c.most_common(1)[0][1] / len(payload)) if payload else 1.0
        if st["kept_lines"] < MIN_KEPT_LINES or len(c) < MIN_DISTINCT or mode > MAX_MODE_FRACTION:
            excluded += 1
            if rel in by_path or (data_dir / rel).exists():
                fail(f"{product}: should be excluded but was emitted")
            continue
        expected.add(rel)
        row = by_path.get(rel)
        if row is None:
            fail(f"{product}: missing from index")
        if (data_dir / rel).read_bytes() != payload:
            fail(f"{product}: sample bytes differ from re-derivation")
        if len(payload) != st["kept_lines"] * 1584:
            fail(f"{product}: value count is not kept_lines * 1584")
        if max(payload) > 15:
            fail(f"{product}: value above 15")
        digest = hashlib.sha256(payload).hexdigest()
        if digest in hashes:
            fail(f"{product}: duplicate payload")
        hashes.add(digest)
        hist.update(c)
        strata_seen[src["stratum"]] += 1
        want = {"dataset_id": DATASET_ID, "series_id": SERIES_ID, "numeric_kind": "uint", "bit_width": 8,
                "endianness": "little", "element_size_bytes": 1, "sample_size_bytes": len(payload),
                "value_count": len(payload), "sha256": digest, "min": min(payload), "max": max(payload),
                "distinct_values": len(c), "stratum": src["stratum"], "product_id": product, **st}
        for k, v in want.items():
            if row.get(k) != v:
                fail(f"{product}: index {k}={row.get(k)!r} want {v!r}")

    if set(by_path) != expected:
        fail(f"index/sample set mismatch: extra={sorted(set(by_path) - expected)[:3]}")
    on_disk = {f"samples/{DATASET_ID}/{SERIES_ID}/{p.name}" for p in sample_dir.glob("*")}
    if on_disk != expected:
        fail("sample directory holds unexpected files")
    if set(strata_seen) != STRATA:
        fail(f"strata missing from output: {sorted(STRATA - set(strata_seen))}")
    total = sum(r["sample_size_bytes"] for r in index_rows)
    sizes = sorted(r["value_count"] for r in index_rows)
    median = sizes[len(sizes) // 2]
    if median < 1000 or total < 100_000:
        fail("below floor")
    if total > 1_000_000_000:
        fail("over 1 GB cap")
    if len(hist) != 16:
        fail(f"aggregate uses only {len(hist)} of 16 codes")
    if hist.most_common(1)[0][1] / total > 0.5:
        fail("one code holds more than half of all values")

    manifest = tomllib.loads((recipe / "manifest.toml").read_text(encoding="utf-8"))
    series = [s for s in manifest["series"] if s["id"] == SERIES_ID]
    if len(series) != 1:
        fail("manifest series missing")
    if series[0]["sample_count"] != len(index_rows) or series[0]["total_size_bytes"] != total:
        fail(f"manifest totals {series[0]['sample_count']}/{series[0]['total_size_bytes']} "
             f"!= realized {len(index_rows)}/{total}")
    print(f"verify ok samples={len(index_rows)} excluded={excluded} bytes={total} median={median} "
          f"strata={dict(sorted(strata_seen.items()))} code_hist={[hist[i] for i in range(16)]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
