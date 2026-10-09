#!/usr/bin/env python3
"""Independent verification for nasa_pds_cassini_rpws_wbr_10khz_waveform_u8.

Re-implements the record walk and selection rule (does not import rpws.py),
re-derives every sample from the local DAT/LBL pair, byte-compares it with the
emitted sample, and checks the index, manifest totals, exclusion rule and
non-degeneracy.
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

DATASET_ID = "nasa_pds_cassini_rpws_wbr_10khz_waveform_u8"
SERIES_ID = "rpws_wbr_10khz_ex_waveform_u8"
MIN_SAMPLE_VALUES = 100_000
MIN_DISTINCT = 16
MAX_MODE_FRACTION = 0.5
NAME_RE = re.compile(r"^T\d{7}_\d{2}_10KHZ[12468]_WBRFR$")


def fail(msg: str) -> None:
    raise SystemExit(f"VERIFY FAIL: {msg}")


def label_kv(text: str) -> dict[str, str]:
    kv: dict[str, str] = {}
    for line in text.splitlines():
        if "=" in line and not line.lstrip().startswith("/*"):
            k, v = line.split("=", 1)
            k = k.strip()
            if k and k not in kv:
                kv[k] = v.strip()
    return kv


def rederive(data: bytes, record_bytes: int) -> tuple[bytes, int, int]:
    """Walk fixed-length records; keep valid samples of band-2 / Ex / clean WBR records."""
    if len(data) % record_bytes:
        fail(f"size {len(data)} not a multiple of {record_bytes}")
    mv = memoryview(data)
    parts = []
    n_rec = kept = 0
    for off in range(0, len(data), record_bytes):
        hdr = mv[off:off + 32]
        rb = (hdr[12] << 8) | hdr[13]
        ns = (hdr[14] << 8) | hdr[15]
        if rb != record_bytes or ns > record_bytes - 32:
            fail(f"bad prefix at {off}: rb={rb} ns={ns}")
        n_rec += 1
        validity, status, band, antenna = hdr[18], hdr[19], hdr[20], hdr[22]
        if band == 2 and antenna == 0 and (validity & 0x40) and not (status & 0x30) and ns:
            parts.append(mv[off + 32:off + 32 + ns])
            kept += 1
    return b"".join(parts), n_rec, kept


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
        plan = {r["product"]: r for r in csv.DictReader(fh, delimiter="\t")}
    index_rows = [json.loads(line) for line in
                  (data_dir / "index" / DATASET_ID / "samples.jsonl").read_text(encoding="utf-8").splitlines()]
    by_path = {r["sample_path"]: r for r in index_rows}
    if len(by_path) != len(index_rows):
        fail("duplicate sample_path in index")

    expected_paths = set()
    hist = Counter()
    hashes = set()
    excluded = 0
    volumes = set()
    for src in sources:
        product = src["product"]
        if not NAME_RE.match(product):
            fail(f"{product}: not a 10-kHz baseband product name")
        dat = (dl / src["volume"] / f"{product}.DAT").read_bytes()
        lbl = (dl / src["volume"] / f"{product}.LBL").read_text(encoding="latin-1")
        if len(dat) != int(src["dat_size"]):
            fail(f"{product}: DAT size")
        if hashlib.sha256(dat).hexdigest() != plan[product]["dat_sha256"]:
            fail(f"{product}: DAT sha256 differs from download plan")
        kv = label_kv(lbl)
        checks = {"SAMPLING_PARAMETER_INTERVAL": "0.000036", "OFFSET": "-127.5", "DATA_TYPE": "UNSIGNED_INTEGER",
                  "ITEM_BYTES": "1", "SECTION_ID": "WBR"}
        for k, v in checks.items():
            if kv.get(k) != v:
                fail(f"{product}: label {k}={kv.get(k)!r}")
        rb = int(kv["RECORD_BYTES"])
        if rb != int(src["record_bytes"]) or rb * int(kv["FILE_RECORDS"]) != len(dat):
            fail(f"{product}: RECORD_BYTES/FILE_RECORDS inconsistent")
        payload, n_rec, kept = rederive(dat, rb)
        rel = f"samples/{DATASET_ID}/{SERIES_ID}/{product}.u8"
        distinct = len(set(payload))
        if len(payload) < MIN_SAMPLE_VALUES or distinct < MIN_DISTINCT:
            excluded += 1
            if rel in by_path or (data_dir / rel).exists():
                fail(f"{product}: should be excluded but was emitted")
            continue
        expected_paths.add(rel)
        row = by_path.get(rel)
        if row is None:
            fail(f"{product}: missing from index")
        got = (data_dir / rel).read_bytes()
        if got != payload:
            fail(f"{product}: sample bytes differ from re-derivation")
        digest = hashlib.sha256(payload).hexdigest()
        if digest in hashes:
            fail(f"{product}: duplicate payload")
        hashes.add(digest)
        c = Counter(payload)
        mode_frac = c.most_common(1)[0][1] / len(payload)
        if mode_frac > MAX_MODE_FRACTION:
            fail(f"{product}: degenerate, one DN holds {mode_frac:.2%}")
        hist.update(c)
        want = {"dataset_id": DATASET_ID, "series_id": SERIES_ID, "numeric_kind": "uint", "bit_width": 8,
                "endianness": "little", "element_size_bytes": 1, "sample_size_bytes": len(payload),
                "value_count": len(payload), "sha256": digest, "min": min(payload), "max": max(payload),
                "kept_records": kept, "source_records": n_rec, "volume_id": src["volume"]}
        for k, v in want.items():
            if row.get(k) != v:
                fail(f"{product}: index {k}={row.get(k)!r} want {v!r}")
        volumes.add(src["volume"])

    if set(by_path) != expected_paths:
        fail(f"index/sample set mismatch: extra={sorted(set(by_path) - expected_paths)[:3]}")
    on_disk = {f"samples/{DATASET_ID}/{SERIES_ID}/{p.name}" for p in sample_dir.glob("*")}
    if on_disk != expected_paths:
        fail("sample directory holds unexpected files")
    total = sum(r["sample_size_bytes"] for r in index_rows)
    sizes = sorted(r["value_count"] for r in index_rows)
    median = sizes[len(sizes) // 2]
    if median < 1000 or total < 100_000:
        fail("below floor")
    if total > 1_000_000_000:
        fail("over 1 GB cap")
    if len(hist) < 200:
        fail(f"aggregate uses only {len(hist)} DN levels")

    manifest = tomllib.loads((recipe / "manifest.toml").read_text(encoding="utf-8"))
    series = [s for s in manifest["series"] if s["id"] == SERIES_ID]
    if len(series) != 1:
        fail("manifest series missing")
    if series[0]["sample_count"] != len(index_rows) or series[0]["total_size_bytes"] != total:
        fail(f"manifest totals {series[0]['sample_count']}/{series[0]['total_size_bytes']} "
             f"!= realized {len(index_rows)}/{total}")
    print(f"verify ok samples={len(index_rows)} excluded={excluded} bytes={total} median={median} "
          f"volumes={len(volumes)} dn_levels={len(hist)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
