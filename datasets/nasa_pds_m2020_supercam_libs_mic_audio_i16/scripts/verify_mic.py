#!/usr/bin/env python3
"""Independent verifier for nasa_pds_m2020_supercam_libs_mic_audio_i16.

Deliberately does not import m2020mic.py. It locates the SOUND HDU by scanning
2880-byte header blocks backwards from the end of each FITS file, parses cards
with a regex, re-derives the uint16 samples with a byte-level sign-bit flip
(stored int16 + 32768 == stored bit pattern XOR 0x8000) instead of struct
arithmetic, and re-applies the same quality policy as the build.
"""
from __future__ import annotations

import argparse
import array
import collections
import csv
import hashlib
import json
import math
import re
import sys
import tomllib
from pathlib import Path

DATASET_ID = "nasa_pds_m2020_supercam_libs_mic_audio_i16"
SERIES_ID = "supercam_mic_libs_100khz_gain2_u16"
N = 174000
BLOCK = 2880
CARD_RE = re.compile(r"^([A-Z0-9_-]{1,8}) *= *('(?:[^']|'')*'|[^/]*)")
PRIMARY = {"MIC_SAMP": "100000", "MIC_SAMC": "21", "MIC_DOWN": "F", "MIC_GAIN": "2", "MIC_DURA": "1",
           "HSS_NUMW": "174000", "LIBS_MIC": "T", "LASDNS00": "30", "SCMDTYPE": "9"}
SOUND = {"XTENSION": "BINTABLE", "BITPIX": "8", "NAXIS": "2", "NAXIS1": "2", "NAXIS2": "174000",
         "PCOUNT": "0", "GCOUNT": "1", "TFIELDS": "1", "EXTNAME": "SOUND", "TTYPE1": "Sound",
         "TFORM1": "I", "TZERO1": "32768"}
MIN_DISTINCT = 64
MAX_DOMINANT_FRACTION = 0.5
INDEX_KEYS = ["dataset_id", "series_id", "sample_path", "numeric_kind", "bit_width", "endianness",
              "element_size_bytes", "sample_size_bytes", "value_count"]
FLIP = bytes(b ^ 0x80 for b in range(256))


def fail(msg: str) -> None:
    raise SystemExit(f"VERIFY FAILED: {msg}")


def cards_from(raw: bytes, start: int) -> tuple[dict[str, str], int]:
    out: dict[str, str] = {}
    pos = start
    while pos + 80 <= len(raw):
        card = raw[pos:pos + 80].decode("ascii")
        pos += 80
        if card.startswith("END "):
            return out, ((pos - start + BLOCK - 1) // BLOCK) * BLOCK
        m = CARD_RE.match(card)
        if m and card[8] == "=":
            v = m.group(2).strip()
            out[m.group(1)] = v[1:-1].replace("''", "'").rstrip() if v.startswith("'") else v
    fail(f"no END card from byte {start}")
    return out, 0


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--recipe-dir", required=True)
    ap.add_argument("--data-root", required=True)
    args = ap.parse_args()
    recipe = Path(args.recipe_dir)
    root = Path(args.data_root).resolve()
    manifest = tomllib.loads((recipe / "manifest.toml").read_text(encoding="utf-8"))
    sources = list(csv.DictReader(open(recipe / "sources.tsv", encoding="utf-8", newline=""), delimiter="\t"))
    ddir = root / "downloads" / DATASET_ID
    index_path = root / "index" / DATASET_ID / "samples.jsonl"
    index = [json.loads(line) for line in index_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    by_product = {}
    for row in index:
        for k in INDEX_KEYS:
            if k not in row:
                fail(f"index row missing {k}")
        if row["product_id"] in by_product:
            fail(f"duplicate index row {row['product_id']}")
        by_product[row["product_id"]] = row

    expected_rejected = []
    seen_sha = set()
    produced = []
    for src in sources:
        name = src["fits_filename"]
        raw = (ddir / name).read_bytes()
        if len(raw) != int(src["file_bytes"]) or hashlib.md5(raw).hexdigest() != src["md5"]:
            fail(f"{name}: size or bundle MD5 mismatch")
        prim, plen = cards_from(raw, 0)
        if prim.get("SIMPLE") != "T":
            fail(f"{name}: not a FITS primary header")
        for k, v in PRIMARY.items():
            if prim.get(k) != v:
                fail(f"{name}: primary {k}={prim.get(k)!r}, expected {v}")
        # Scan backwards over block boundaries for the SOUND extension header.
        hdr_off = None
        for off in range(len(raw) - BLOCK, plen - 1, -BLOCK):
            if raw[off:off + 9] == b"XTENSION=":
                c, _ = cards_from(raw, off)
                if c.get("EXTNAME") == "SOUND":
                    hdr_off = off
                    break
        if hdr_off is None or hdr_off != int(src["sound_header_offset"]):
            fail(f"{name}: SOUND header at {hdr_off}, pinned {src['sound_header_offset']}")
        scards, slen = cards_from(raw, hdr_off)
        for k, v in SOUND.items():
            if scards.get(k) != v:
                fail(f"{name}: SOUND {k}={scards.get(k)!r}, expected {v}")
        if scards.get("TSCAL1", "1") not in ("1", "1.0"):
            fail(f"{name}: TSCAL1 present and not 1")
        d0 = hdr_off + slen
        be = raw[d0:d0 + 2 * N]
        if len(be) != 2 * N or d0 + 2 * N + (-(2 * N) % BLOCK) != len(raw) or raw[d0 + 2 * N:].count(0) != len(raw) - d0 - 2 * N:
            fail(f"{name}: SOUND data extent or padding wrong (SOUND must be the final HDU)")
        le = bytearray(2 * N)
        le[0::2] = be[1::2]
        le[1::2] = be[0::2].translate(FLIP)
        vals = array.array("H")
        vals.frombytes(bytes(le))
        if sys.byteorder != "little":
            vals.byteswap()
        counts = collections.Counter(vals)
        dom_val, dom_n = counts.most_common(1)[0]
        dom = dom_n / N
        reject = len(counts) < MIN_DISTINCT or dom > MAX_DOMINANT_FRACTION
        if reject:
            expected_rejected.append(src["product_id"])
            if src["product_id"] in by_product:
                fail(f"{name}: violates quality policy but is in the index")
            continue
        row = by_product.get(src["product_id"])
        if row is None:
            fail(f"{name}: passes quality policy but missing from index")
        sample = root / row["sample_path"]
        if sample.read_bytes() != bytes(le):
            fail(f"{name}: sample bytes differ from independent re-derivation")
        sha = hashlib.sha256(le).hexdigest()
        if sha != row["sha256"] or sha in seen_sha:
            fail(f"{name}: sha256 mismatch or duplicate sample content")
        seen_sha.add(sha)
        if len(counts) < 2:
            fail(f"{name}: constant sample")
        mean = sum(vals) / N
        std = math.sqrt(sum((v - mean) ** 2 for v in vals) / N)
        checks = {
            "numeric_kind": "uint", "bit_width": 16, "endianness": "little", "element_size_bytes": 2,
            "sample_size_bytes": 2 * N, "value_count": N, "dataset_id": DATASET_ID, "series_id": SERIES_ID,
            "min": min(vals), "max": max(vals), "distinct_values": len(counts),
            "dominant_value": dom_val, "dominant_fraction": round(dom, 6), "sample_rate_hz": 100000,
            "sol": int(src["sol"]), "mic_gain": 2, "source_md5": src["md5"],
        }
        for k, v in checks.items():
            if row.get(k) != v:
                fail(f"{name}: index {k}={row.get(k)!r}, re-derived {v!r}")
        if abs(row["mean"] - mean) > 1e-3 or abs(row["std"] - std) > 1e-3:
            fail(f"{name}: index mean/std mismatch")
        if std <= 0:
            fail(f"{name}: degenerate sample")
        produced.append(row)

    if len(produced) + len(expected_rejected) != len(sources) or len(produced) != len(index):
        fail("index rows do not match pinned products minus quality rejections")
    order = [r["sample_path"] for r in index]
    if order != sorted(order):
        fail("index not in ordinal order")
    series = [s for s in manifest["series"] if s["id"] == SERIES_ID]
    if len(series) != 1 or series[0].get("role") != "primary":
        fail("manifest must declare exactly one primary series with the expected id")
    total = sum(r["sample_size_bytes"] for r in produced)
    if series[0]["sample_count"] != len(produced) or series[0]["total_size_bytes"] != total:
        fail(f"manifest totals {series[0]['sample_count']}/{series[0]['total_size_bytes']} != realized {len(produced)}/{total}")
    sols = {r["sol"] for r in produced}
    print(f"verified samples={len(produced)} quality_rejected={len(expected_rejected)} "
          f"values={len(produced) * N} bytes={total} distinct_sols={len(sols)} "
          f"sol_range={min(sols)}-{max(sols)} max_dominant_fraction={max(r['dominant_fraction'] for r in produced)} "
          f"value_range={min(r['min'] for r in produced)}-{max(r['max'] for r in produced)}")


if __name__ == "__main__":
    main()
