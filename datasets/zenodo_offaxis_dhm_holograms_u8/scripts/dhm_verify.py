#!/usr/bin/env python3
"""Independent verification for zenodo_offaxis_dhm_holograms_u8.

Re-derives every sample from the downloaded TIFF with a second, separately
written decoder (own IFD reader, prefix/suffix-table LZW with windowed bit
reads, per-pixel predictor undo) instead of the build module, byte-compares
it with the emitted sample, and checks index, manifest totals, degeneracy
and duplicates.
"""

from __future__ import annotations

import argparse
import collections
import csv
import hashlib
import json
from pathlib import Path
import struct
import sys
import tomllib
import zlib

DATASET_ID = "zenodo_offaxis_dhm_holograms_u8"
SERIES_ID = "dhm_offaxis_hologram_u8"
W = H = 2048
FRAME_BYTES = W * H
INDEX_KEYS = (
    "dataset_id", "series_id", "sample_path", "numeric_kind", "bit_width",
    "endianness", "element_size_bytes", "sample_size_bytes", "value_count",
)


def fail(msg: str) -> None:
    raise SystemExit(f"VERIFY FAIL: {msg}")


def ifd(data: bytes) -> dict[int, list[int]]:
    if data[:4] != b"II\x2a\x00":
        fail("not II* TIFF")
    off = struct.unpack("<I", data[4:8])[0]
    count = struct.unpack("<H", data[off : off + 2])[0]
    tags: dict[int, list[int]] = {}
    for i in range(count):
        e = data[off + 2 + 12 * i : off + 14 + 12 * i]
        tag, typ, n = struct.unpack("<HHI", e[:8])
        if typ == 3:
            size, fmt = 2, "H"
        elif typ == 4:
            size, fmt = 4, "I"
        else:
            continue
        if size * n <= 4:
            raw = e[8 : 8 + size * n]
        else:
            p = struct.unpack("<I", e[8:12])[0]
            raw = data[p : p + size * n]
        tags[tag] = list(struct.unpack("<" + fmt * n, raw))
    if struct.unpack("<I", data[off + 2 + 12 * count : off + 6 + 12 * count])[0] != 0:
        fail("multiple IFDs")
    return tags


def lzw(src: bytes, expected: int) -> bytes:
    prefix = [-1] * 4096
    suffix = list(range(256)) + [0] * (4096 - 256)
    first = list(range(256)) + [0] * (4096 - 256)
    out = bytearray()
    padded = src + b"\x00\x00\x00"
    bitpos = 0
    total_bits = 8 * len(src)

    def code_at(p: int, w: int) -> int:
        if p + w > total_bits:
            return -1
        q = p >> 3
        return ((padded[q] << 16 | padded[q + 1] << 8 | padded[q + 2]) >> (24 - (p & 7) - w)) & ((1 << w) - 1)

    def expand(c: int) -> bytes:
        rev = []
        while c >= 0:
            rev.append(suffix[c])
            c = prefix[c]
        return bytes(reversed(rev))

    width, avail, old = 9, 258, -1
    just_widened = False
    while len(out) < expected:
        c = code_at(bitpos, width)
        if c < 0:
            fail("LZW data exhausted")
        bitpos += width
        if c == 256:
            width, avail, old, just_widened = 9, 258, -1, False
            continue
        if c == 257:
            fail("premature EOI")
        if old < 0:
            if c > 255:
                fail("non-literal after clear")
            out.append(c)
            old = c
            just_widened = False
            continue
        if c < avail:
            s = expand(c)
            prefix[avail], suffix[avail], first[avail] = old, s[0], first[old]
        elif c == avail:
            prefix[avail], suffix[avail], first[avail] = old, first[old], first[old]
            s = expand(c)
        else:
            fail(f"LZW code {c} > {avail}")
        avail += 1
        out += s
        old = c
        just_widened = False
        if avail >= (1 << width) - 1 and width < 12:
            width += 1
            just_widened = True
    if len(out) != expected:
        fail("LZW overrun")

    def ends(p: int, w: int) -> int:
        c = code_at(p, w)
        if c == 256:
            p += w
            w = 9
            c = code_at(p, w)
        return p + w if c == 257 else -1

    end = ends(bitpos, width)
    if end < 0 and just_widened:
        end = ends(bitpos, width - 1)
    if end < 0:
        fail("no EOI at strip end")
    if len(src) - (end + 7) // 8 > 1:
        fail("trailing LZW bytes")
    return bytes(out)


def decode(data: bytes) -> bytes:
    t = ifd(data)
    want = {256: [W], 257: [H], 258: [8], 259: [5], 262: [1], 317: [2]}
    for tag, val in want.items():
        if t.get(tag) != val:
            fail(f"TIFF tag {tag}={t.get(tag)} expected {val}")
    if t.get(277, [1]) != [1] or t.get(284, [1]) != [1] or t.get(339, [1]) != [1]:
        fail("unexpected spp/planar/sampleformat")
    rps = t.get(278, [H])[0]
    offs, cnts = t[273], t[279]
    if len(offs) != (H + rps - 1) // rps or len(offs) != len(cnts):
        fail("strip table")
    pixels = bytearray(FRAME_BYTES)
    pos = 0
    for o, c in zip(offs, cnts):
        rows = min(rps, H - pos // W)
        raw = lzw(data[o : o + c], rows * W)
        for r in range(rows):
            acc = 0
            base = r * W
            for x in range(W):
                acc = (acc + raw[base + x]) & 255
                pixels[pos] = acc
                pos += 1
    if pos != FRAME_BYTES:
        fail("pixel count")
    return bytes(pixels)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--recipe", required=True)
    ap.add_argument("--data-root", required=True)
    ap.add_argument("--full-decode-every", type=int, default=1,
                    help="independently decode every Nth sample (1 = all)")
    args = ap.parse_args()
    recipe = Path(args.recipe)
    root = Path(args.data_root)
    manifest = tomllib.loads((recipe / "manifest.toml").read_text(encoding="utf-8"))
    series = [s for s in manifest["series"] if s["id"] == SERIES_ID]
    if len(series) != 1 or series[0].get("role") != "primary":
        fail("manifest primary series missing")
    series = series[0]
    with open(recipe / "selected_frames.tsv", encoding="utf-8") as h:
        selected = list(csv.DictReader(h, delimiter="\t"))
    with open(recipe / "videos.tsv", encoding="utf-8") as h:
        videos = list(csv.DictReader(h, delimiter="\t"))
    if len(videos) != 17 or any("520" in v["key"] for v in videos):
        fail("video pin set changed or contains the 520 nm video")
    per_video = collections.Counter(r["key"] for r in selected)
    if len(selected) != 102 or set(per_video.values()) != {6}:
        fail("selected frame pins are not 6 per video")
    for v in videos:
        n = int(v["holograms"])
        frames = [int(r["frame"]) for r in selected if r["key"] == v["key"]]
        if frames != [((2 * k + 1) * n) // 12 for k in range(6)]:
            fail(f"{v['key']}: frames {frames} are not the even selection")

    index_path = root / "index" / DATASET_ID / "samples.jsonl"
    rows = [json.loads(line) for line in index_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if len(rows) != len(selected):
        fail(f"index rows {len(rows)} != {len(selected)}")
    out_dir = root / "samples" / DATASET_ID / SERIES_ID
    on_disk = sorted(p.name for p in out_dir.glob("*.bin"))
    if on_disk != sorted(Path(r["sample_path"]).name for r in rows):
        fail("sample directory does not match index")

    seen: set[str] = set()
    total = 0
    decoded_count = 0
    for i, (r, pin) in enumerate(zip(rows, selected)):
        for k in INDEX_KEYS:
            if k not in r:
                fail(f"index row missing {k}")
        if (r["dataset_id"], r["series_id"], r["numeric_kind"], r["bit_width"], r["endianness"],
                r["element_size_bytes"], r["sample_size_bytes"], r["value_count"]) != (
                DATASET_ID, SERIES_ID, "uint", 8, "little", 1, FRAME_BYTES, FRAME_BYTES):
            fail(f"index row fields wrong: {r['sample_path']}")
        if r["source_zip"] != pin["key"] or r["source_frame"] != int(pin["frame"]) or r["source_member"] != pin["name"]:
            fail(f"index order/provenance mismatch at row {i}")
        sample = (root / r["sample_path"]).read_bytes()
        if len(sample) != FRAME_BYTES:
            fail(f"sample size {len(sample)}: {r['sample_path']}")
        digest = hashlib.sha256(sample).hexdigest()
        if digest != r["sha256"]:
            fail(f"sha256 mismatch: {r['sample_path']}")
        if digest in seen:
            fail(f"duplicate sample: {r['sample_path']}")
        seen.add(digest)
        hist = collections.Counter(sample)
        top = hist.most_common(1)[0][1] / FRAME_BYTES
        if len(hist) < 64 or top > 0.05 or min(hist) != r["min"] or max(hist) != r["max"] \
                or len(hist) != r["distinct_values"]:
            fail(f"degenerate or stats mismatch: {r['sample_path']} distinct={len(hist)} mode={top:.4f}")
        tif = root / "downloads" / DATASET_ID / "tif" / pin["key"][:-4] / f"{int(pin['frame']):05d}_holo.tif"
        data = tif.read_bytes()
        if len(data) != int(pin["uncompressed_size"]) or f"{zlib.crc32(data) & 0xFFFFFFFF:08x}" != pin["crc32_hex"]:
            fail(f"source TIFF size/CRC32 mismatch: {tif}")
        if i % args.full_decode_every == 0:
            if decode(data) != sample:
                fail(f"independent decode differs from sample: {r['sample_path']}")
            decoded_count += 1
        total += len(sample)
        print(f"ok {i + 1}/{len(rows)} {Path(r['sample_path']).name}", flush=True)

    if series["sample_count"] != len(rows) or series["total_size_bytes"] != total:
        fail(f"manifest totals {series['sample_count']}/{series['total_size_bytes']} != {len(rows)}/{total}")
    print(f"verify=ok samples={len(rows)} bytes={total} independently_decoded={decoded_count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
