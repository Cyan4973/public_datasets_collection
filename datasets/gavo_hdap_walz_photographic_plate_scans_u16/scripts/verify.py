#!/usr/bin/env python3
"""Independent verification of the HDAP Walz lunar plate samples.

Uses its own FITS header reader and a different decode path (array byteswap + sign-bit XOR,
plus exact struct arithmetic on a strided row subset), recomputes value statistics from the
sample bytes, and cross-checks index rows, pins, download plan and manifest totals.
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import struct
import sys
import tomllib
from array import array
from pathlib import Path

DATASET_ID = "gavo_hdap_walz_photographic_plate_scans_u16"
SERIES_ID = "walz_lunar_plate_scan_dn_u16"
XOR = bytes(b ^ 0x80 for b in range(256))
ROW_STRIDE = 97
INDEX_REQUIRED = [
    "dataset_id", "series_id", "sample_path", "numeric_kind", "bit_width", "endianness",
    "element_size_bytes", "sample_size_bytes", "value_count",
]


def fail(msg: str) -> None:
    raise SystemExit(f"VERIFY FAIL: {msg}")


def tsv(path: Path) -> list[dict]:
    lines = [l for l in path.read_text(encoding="utf-8").splitlines() if l and l[0] != "#"]
    keys = lines[0].split("\t")
    return [dict(zip(keys, l.split("\t"))) for l in lines[1:]]


def header_cards(blob: bytes) -> tuple[dict, int]:
    """Independent reader: scan 2880-byte blocks for keyword/value pairs until END."""
    cards = {}
    block = 0
    while True:
        chunk = blob[block * 2880 : (block + 1) * 2880]
        if len(chunk) != 2880:
            fail("header END not found")
        for k in range(36):
            card = chunk[k * 80 : (k + 1) * 80].decode("ascii")
            name = card[:8].strip()
            if name == "END":
                return cards, (block + 1) * 2880
            if card[8] == "=":
                value = card[9:].strip()
                if value.startswith("'"):
                    value = value[1:].split("'", 1)[0].strip()
                else:
                    value = value.split("/")[0].strip()
                cards.setdefault(name, value)
        block += 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--recipe", required=True, type=Path)
    ap.add_argument("--data-root", required=True, type=Path)
    args = ap.parse_args()
    root = args.data_root
    if sys.byteorder != "little":
        fail("verification assumes a little-endian host")
    manifest = tomllib.loads((args.recipe / "manifest.toml").read_text(encoding="utf-8"))
    primaries = [s for s in manifest["series"] if s.get("role") == "primary"]
    if len(primaries) != 1 or primaries[0]["id"] != SERIES_ID:
        fail("manifest must declare exactly the one primary series")
    series = primaries[0]
    pins = {p["plate_id"]: p for p in tsv(args.recipe / "sources.tsv")}
    plan = {p["plate_id"]: p for p in tsv(root / "downloads" / DATASET_ID / "download_plan.tsv")}
    if set(pins) != set(plan) or len(pins) != 25:
        fail("pins and download plan disagree")
    rows = [json.loads(l) for l in (root / "index" / DATASET_ID / "samples.jsonl").read_text().splitlines() if l]
    if [r["plate_id"] for r in rows] != list(pins):
        fail("index rows are not the pinned plates in pinned order")
    sample_dir = root / "samples" / DATASET_ID / SERIES_ID
    on_disk = sorted(p.name for p in sample_dir.iterdir())
    if on_disk != sorted(f"{p}.u16" for p in pins):
        fail(f"sample directory contents differ from pins: {on_disk}")

    hashes = set()
    total_bytes = 0
    seasons = collections.Counter()
    for row in rows:
        plate = row["plate_id"]
        pin = pins[plate]
        for key in INDEX_REQUIRED:
            if key not in row:
                fail(f"{plate}: index lacks {key}")
        if (row["dataset_id"], row["series_id"], row["numeric_kind"], row["bit_width"], row["endianness"],
                row["element_size_bytes"]) != (DATASET_ID, SERIES_ID, "uint", 16, "little", 2):
            fail(f"{plate}: index type fields wrong")
        src = root / "downloads" / DATASET_ID / "fits" / f"{plate}.fits"
        blob = src.read_bytes()
        if len(blob) != int(pin["size_bytes"]):
            fail(f"{plate}: source size")
        digest = hashlib.sha256(blob).hexdigest()
        if digest != plan[plate]["sha256"] or digest != row["source_sha256"]:
            fail(f"{plate}: source sha256 mismatch")
        cards, hdr = header_cards(blob)
        if hashlib.sha256(blob[:hdr]).hexdigest() != pin["header_sha256"]:
            fail(f"{plate}: header sha256 differs from pin")
        expect = {"SIMPLE": "T", "BITPIX": "16", "NAXIS": "2", "BZERO": "32768", "BSCALE": "1",
                  "TELESCOP": "72cm Walz Reflektor"}
        for key, val in expect.items():
            if cards.get(key) != val:
                fail(f"{plate}: {key}={cards.get(key)!r}")
        if "BLANK" in cards or not cards.get("OBJECT", "").startswith("Moon"):
            fail(f"{plate}: BLANK present or not a lunar plate")
        nx, ny = int(cards["NAXIS1"]), int(cards["NAXIS2"])
        if (nx, ny) != (int(pin["naxis1"]), int(pin["naxis2"])) or row["shape"] != [ny, nx]:
            fail(f"{plate}: geometry")
        nbytes = nx * ny * 2
        if hdr + nbytes + (-nbytes % 2880) != len(blob):
            fail(f"{plate}: extra HDUs or truncation")
        sample_path = root / row["sample_path"]
        sample = sample_path.read_bytes()
        if len(sample) != nbytes or row["sample_size_bytes"] != nbytes or row["value_count"] != nx * ny:
            fail(f"{plate}: sample size")
        # decode path 1: array byteswap of big-endian words, then flip the sign bit of the high byte
        words = array("H")
        words.frombytes(blob[hdr : hdr + nbytes])
        words.byteswap()
        expected = bytearray(words.tobytes())
        del words
        expected[1::2] = expected[1::2].translate(XOR)
        if expected != sample:
            fail(f"{plate}: sample bytes differ from independent decode")
        del expected
        # decode path 2: exact arithmetic on every ROW_STRIDE-th scan row
        for r in range(0, ny, ROW_STRIDE):
            off = hdr + r * nx * 2
            signed = struct.unpack(f">{nx}h", blob[off : off + nx * 2])
            stored = struct.unpack(f"<{nx}H", sample[r * nx * 2 : (r + 1) * nx * 2])
            if any(s + 32768 != u for s, u in zip(signed, stored)):
                fail(f"{plate}: arithmetic decode mismatch in row {r}")
        del blob
        counts = collections.Counter(memoryview(sample).cast("H"))
        dom_value, dom_count = counts.most_common(1)[0]
        n = nx * ny
        checks = {
            "min": min(counts), "max": max(counts), "distinct_values": len(counts),
            "dominant_value": dom_value, "dominant_fraction": round(dom_count / n, 6),
            "count_0": counts.get(0, 0), "count_65535": counts.get(65535, 0),
            "floor_1422_fraction": round(counts.get(1422, 0) / n, 6),
        }
        for key, val in checks.items():
            if row.get(key) != val:
                fail(f"{plate}: index {key}={row.get(key)!r} recomputed {val!r}")
        if len(counts) < 256 or dom_count / n > 0.9:
            fail(f"{plate}: degenerate image (distinct={len(counts)}, dominant={dom_count / n:.3f})")
        # row-level degeneracy: the first, middle and last rows must not all be identical
        mid = (ny // 2) * nx * 2
        if sample[: nx * 2] == sample[mid : mid + nx * 2] == sample[-nx * 2 :]:
            fail(f"{plate}: identical boundary/middle rows")
        sha = hashlib.sha256(sample).hexdigest()
        if sha != row["sample_sha256"] or sha in hashes:
            fail(f"{plate}: sample hash mismatch or duplicate")
        hashes.add(sha)
        total_bytes += nbytes
        seasons[row["season"]] += 1
        print(f"ok {plate} {nx}x{ny} dominant={dom_value}@{dom_count / n:.4f} distinct={len(counts)}")

    if len(rows) != series["sample_count"] or total_bytes != series["total_size_bytes"]:
        fail(f"manifest totals {series['sample_count']}/{series['total_size_bytes']} != realized {len(rows)}/{total_bytes}")
    if set(seasons) != {"S1", "S2", "S3", "S4", "S5", "S6"}:
        fail(f"season coverage {dict(seasons)}")
    if total_bytes > 1_000_000_000:
        fail("primary bytes exceed 1 GB")
    print(f"verify ok samples={len(rows)} bytes={total_bytes} seasons={dict(sorted(seasons.items()))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
