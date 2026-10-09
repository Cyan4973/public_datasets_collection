#!/usr/bin/env python3
"""FLIR Vue Pro R 640 iceberg frames: zip-member range checks, TIFF decode, build, verify.

Each pixel is the camera's in-camera T-linear scene (brightness) temperature in
units of 0.04 K (kelvin = value * 0.04), as declared by every frame's XMP
packet (Camera:TlinearGain = 0.04, Camera:IsNormalized = 1). decode_tiff
enforces those two tags; the recipe applies no scaling.

Pure standard library. Commands:
  list         print the selected download jobs (session frame zip_size start end length)
  check        validate one fetched zip-member byte range (local header, raw
               deflate, CRC32 and sizes against the pinned central directory,
               data descriptor, TIFF IFD incl. XMP T-linear gain 0.04 / normalized)
  selftest     synthetic TIFF (II and MM, single and multi-strip, XMP gain tags) and
               synthetic deflated zip members with and without data descriptors
  build        decode every selected frame and emit raw uint16 LE samples
  verify       independently re-decode, re-derive statistics, check outputs
"""
from __future__ import annotations

import argparse
from array import array
from collections import Counter
import hashlib
import json
import os
import re
from pathlib import Path
import random
import shutil
import struct
import sys
import tomllib
import zlib

DATASET_ID = "zenodo_flir_vue_iceberg_thermal_u16"
SERIES_ID = "flir_tlinear_temperature_u16"
RECORD_URL = "https://zenodo.org/records/10641368"
STRIDE = 8
WIDTH = 640
HEIGHT = 512
PIXELS = WIDTH * HEIGHT
STRIP_BYTES = PIXELS * 2
TSV_COLUMNS = ["session", "frame", "selected", "zip_size", "member_lho", "range_end",
               "compressed_size", "uncompressed_size", "crc32"]
# Pinned from https://zenodo.org/api/records/10641368 (fetched 2026-10-08).
SESSIONS: dict[str, dict[str, object]] = {
    "20180820_035505": {"zip_size": 70929301, "md5": "da4d86a666305d3374be550b390b01af", "frames": 295},
    "20180820_040000": {"zip_size": 77082289, "md5": "f57d06cdfd67369ed31ced6d9c70ed63", "frames": 346},
    "20180821_034534": {"zip_size": 138761841, "md5": "51287ebb5c3170ab665a45b7a0631058", "frames": 634},
    "20180821_092823": {"zip_size": 324409553, "md5": "0225d56976d13d3ad92142998f9f4c06", "frames": 798},
    "20180821_155204": {"zip_size": 453347875, "md5": "39b6a5199a45b617602e969ff15b30f9", "frames": 786},
}
DUPLICATE_ZIP = {"name": "20180821_160000.zip", "session": "20180821_160000", "zip_size": 71072781,
                 "md5": "86277aaa6275c4ac4c4981f96d622a91", "duplicate_of": "20180821_155204"}
EXPECTED_SELECTED = 360
# T-linear lattice: every frame's XMP (TIFF tag 700) must declare exactly one
# Camera:TlinearGain of 0.04 K per count and Camera:IsNormalized = 1 (rejects
# the camera's 0.4 K low-gain mode and non-linearized raw output).
TLINEAR_GAIN = "0.04"
TLINEAR_GAIN_K_PER_COUNT = 0.04
# Per-frame semantic gates (see README). Observed over all 360 selected frames:
# 56-973 distinct values (three open-sea frames at the end of 20180821_092823
# have 56-59), modal fraction <= 0.123, range >= 57 steps of 0.04 K, no 0/65535 pixels.
MIN_DISTINCT = 32
MAX_MODAL_FRACTION = 0.25
MIN_RANGE = 50
MAX_EXTREME_FRACTION = 0.001


def url_for(session: str) -> str:
    return f"{RECORD_URL}/files/{session}.zip?download=1"


# --------------------------------------------------------------------------- table

def load_table(path: Path) -> list[dict[str, object]]:
    lines = path.read_text(encoding="utf-8").splitlines()
    if lines[0].split("\t") != TSV_COLUMNS:
        raise SystemExit(f"unexpected header in {path}")
    rows: list[dict[str, object]] = []
    for line in lines[1:]:
        parts = line.split("\t")
        if len(parts) != len(TSV_COLUMNS):
            raise SystemExit(f"bad row in {path}: {line!r}")
        row: dict[str, object] = dict(zip(TSV_COLUMNS, parts))
        for key in ("selected", "zip_size", "member_lho", "range_end", "compressed_size", "uncompressed_size"):
            row[key] = int(str(row[key]))
        rows.append(row)
    for session, meta in SESSIONS.items():
        srows = [r for r in rows if r["session"] == session]
        if len(srows) != meta["frames"]:
            raise SystemExit(f"{session}: expected {meta['frames']} frames, table has {len(srows)}")
        names = [str(r["frame"]) for r in srows]
        if names != sorted(names) or len(set(names)) != len(names):
            raise SystemExit(f"{session}: frames must be unique and sorted")
        for idx, r in enumerate(srows):
            if r["selected"] != (1 if idx % STRIDE == 0 else 0):
                raise SystemExit(f"{session}: selection must be every {STRIDE}th frame in time order")
            if r["zip_size"] != meta["zip_size"]:
                raise SystemExit(f"{session}: zip size mismatch")
    if {str(r["session"]) for r in rows} != set(SESSIONS):
        raise SystemExit("table contains unexpected sessions")
    return rows


def selected_rows(path: Path) -> list[dict[str, object]]:
    rows = [r for r in load_table(path) if r["selected"] == 1]
    if len(rows) != EXPECTED_SELECTED:
        raise SystemExit(f"expected {EXPECTED_SELECTED} selected frames, got {len(rows)}")
    return rows


def member_path(download_dir: Path, row: dict[str, object]) -> Path:
    return download_dir / str(row["session"]) / (str(row["frame"]) + ".zipmember")


def find_row(table: Path, session: str, frame: str) -> dict[str, object]:
    for r in selected_rows(table):
        if r["session"] == session and r["frame"] == frame:
            return r
    raise SystemExit(f"{session}/{frame} is not a selected frame")


# --------------------------------------------------------------------------- zip member

def inflate_member(data: bytes, row: dict[str, object]) -> bytes:
    """Validate one [local header .. next local header) range; return the inflated TIFF."""
    label = f"{row['session']}/{row['frame']}"
    expect_len = int(row["range_end"]) - int(row["member_lho"]) + 1
    if len(data) != expect_len:
        raise ValueError(f"{label}: range length {len(data)} != {expect_len}")
    if len(data) < 30:
        raise ValueError(f"{label}: truncated local header")
    (sig, _ver, flags, method, _mt, _md, crc, csize, usize, nlen, elen) = struct.unpack_from("<IHHHHHIIIHH", data, 0)
    if sig != 0x04034B50:
        raise ValueError(f"{label}: bad local file header signature")
    if method != 8:
        raise ValueError(f"{label}: member is not deflated (method {method})")
    if flags & 0x0001:
        raise ValueError(f"{label}: encrypted member")
    name = f"{row['session']}/{row['frame']}".encode()
    if data[30:30 + nlen] != name:
        raise ValueError(f"{label}: member name mismatch {data[30:30 + nlen]!r}")
    exp_crc = int(str(row["crc32"]), 16)
    exp_cs = int(row["compressed_size"])
    exp_us = int(row["uncompressed_size"])
    has_dd = bool(flags & 0x0008)
    if not has_dd and (crc, csize, usize) != (exp_crc, exp_cs, exp_us):
        raise ValueError(f"{label}: local header crc/sizes {(crc, csize, usize)} differ from central directory")
    # With a data descriptor each local field is either deferred (0) or already final;
    # the macOS archiver used upstream writes crc=0, csize=0, usize=final.
    if has_dd and not all(v in (0, w) for v, w in ((crc, exp_crc), (csize, exp_cs), (usize, exp_us))):
        raise ValueError(f"{label}: unexpected local header crc/sizes with data descriptor")
    start = 30 + nlen + elen
    comp = data[start:start + exp_cs]
    tail = data[start + exp_cs:]
    if len(comp) != exp_cs:
        raise ValueError(f"{label}: compressed data truncated")
    inflater = zlib.decompressobj(-15)
    raw = inflater.decompress(comp) + inflater.flush()
    if not inflater.eof or inflater.unused_data:
        raise ValueError(f"{label}: deflate stream incomplete or does not end at compressed_size")
    if len(raw) != exp_us:
        raise ValueError(f"{label}: inflated {len(raw)} bytes != {exp_us}")
    if zlib.crc32(raw) & 0xFFFFFFFF != exp_crc:
        raise ValueError(f"{label}: CRC32 mismatch")
    if has_dd:
        dd = struct.pack("<III", exp_crc, exp_cs, exp_us)
        if tail not in (b"PK\x07\x08" + dd, dd):
            raise ValueError(f"{label}: data descriptor mismatch or trailing bytes ({len(tail)})")
    elif tail:
        raise ValueError(f"{label}: {len(tail)} unexpected bytes after member")
    return raw


# --------------------------------------------------------------------------- TIFF

TYPE_SIZES = {1: 1, 2: 1, 3: 2, 4: 4, 5: 8, 7: 1, 13: 4}


def decode_tiff(raw: bytes, label: str) -> tuple[bytes, dict[str, object]]:
    """Parse IFD0 of a FLIR Vue Pro R T-linear TIFF; return the uint16 LE pixel plane and header facts."""
    if raw[:4] == b"II*\x00":
        e = "<"
    elif raw[:4] == b"MM\x00*":
        e = ">"
    else:
        raise ValueError(f"{label}: not a classic TIFF")
    ifd = struct.unpack_from(e + "I", raw, 4)[0]
    if ifd < 8 or ifd + 2 > len(raw):
        raise ValueError(f"{label}: IFD offset out of range")
    n = struct.unpack_from(e + "H", raw, ifd)[0]
    if ifd + 2 + 12 * n + 4 > len(raw):
        raise ValueError(f"{label}: IFD exceeds file")
    tags: dict[int, object] = {}
    for k in range(n):
        tag, typ, cnt = struct.unpack_from(e + "HHI", raw, ifd + 2 + 12 * k)
        size = TYPE_SIZES.get(typ, 1) * cnt
        voff = ifd + 2 + 12 * k + 8
        if size > 4:
            voff = struct.unpack_from(e + "I", raw, voff)[0]
            if voff + size > len(raw):
                raise ValueError(f"{label}: tag {tag} value out of range")
        if typ == 3:
            tags[tag] = list(struct.unpack_from(e + f"{cnt}H", raw, voff))
        elif typ == 4:
            tags[tag] = list(struct.unpack_from(e + f"{cnt}I", raw, voff))
        elif typ == 2:
            tags[tag] = raw[voff:voff + cnt].split(b"\x00")[0].decode("latin-1")
        elif tag == 700 and typ in (1, 7):
            tags[tag] = bytes(raw[voff:voff + cnt])
    next_ifd = struct.unpack_from(e + "I", raw, ifd + 2 + 12 * n)[0]
    if next_ifd != 0:
        raise ValueError(f"{label}: multi-page TIFF")

    def one(tag: int, default: int | None = None) -> int:
        v = tags.get(tag)
        if v is None:
            if default is None:
                raise ValueError(f"{label}: missing tag {tag}")
            return default
        if not isinstance(v, list) or len(v) != 1:
            raise ValueError(f"{label}: tag {tag} not a single integer")
        return int(v[0])

    facts = {
        "width": one(256), "height": one(257), "bits_per_sample": one(258),
        "compression": one(259, 1), "photometric": one(262), "samples_per_pixel": one(277, 1),
        "planar": one(284, 1), "byte_order": "II" if e == "<" else "MM",
        "make": tags.get(271, ""), "model": tags.get(272, ""),
    }
    want = {"width": WIDTH, "height": HEIGHT, "bits_per_sample": 16, "compression": 1,
            "photometric": 1, "samples_per_pixel": 1, "planar": 1}
    for key, value in want.items():
        if facts[key] != value:
            raise ValueError(f"{label}: {key}={facts[key]} (want {value})")
    if 339 in tags and tags[339] != [1]:
        raise ValueError(f"{label}: SampleFormat {tags[339]} is not unsigned integer")
    if facts["make"] != "FLIR" or not str(facts["model"]).startswith("Vue Pro R 640"):
        raise ValueError(f"{label}: camera {facts['make']!r} {facts['model']!r} is not a FLIR Vue Pro R 640")
    xmp = tags.get(700)
    if not isinstance(xmp, bytes) or not xmp:
        raise ValueError(f"{label}: missing XMP packet (tag 700)")
    text = xmp.decode("utf-8", "replace")
    gains = re.findall(r"<Camera:TlinearGain>\s*([^<]*?)\s*</Camera:TlinearGain>", text)
    norms = re.findall(r"<Camera:IsNormalized>\s*([^<]*?)\s*</Camera:IsNormalized>", text)
    if gains != [TLINEAR_GAIN]:
        raise ValueError(f"{label}: XMP Camera:TlinearGain {gains} (want exactly ['{TLINEAR_GAIN}'])")
    if norms != ["1"]:
        raise ValueError(f"{label}: XMP Camera:IsNormalized {norms} (want exactly ['1'])")
    facts["tlinear_gain_k_per_count"] = TLINEAR_GAIN_K_PER_COUNT
    offsets = tags.get(273)
    counts = tags.get(279)
    if not isinstance(offsets, list) or not isinstance(counts, list) or len(offsets) != len(counts) or not offsets:
        raise ValueError(f"{label}: bad strip tags")
    if sum(counts) != STRIP_BYTES:
        raise ValueError(f"{label}: strip bytes {sum(counts)} != {STRIP_BYTES}")
    plane = bytearray()
    for off, cnt in zip(offsets, counts):
        if off + cnt > len(raw):
            raise ValueError(f"{label}: strip out of range")
        plane += raw[off:off + cnt]
    if e == ">":
        swapped = bytearray(len(plane))
        swapped[0::2] = plane[1::2]
        swapped[1::2] = plane[0::2]
        plane = swapped
    facts["strips"] = len(offsets)
    return bytes(plane), facts


# --------------------------------------------------------------------------- stats

def characterize(payload: bytes, label: str) -> dict[str, object]:
    if len(payload) != STRIP_BYTES:
        raise ValueError(f"{label}: payload size mismatch")
    values = array("H")
    values.frombytes(payload)
    if sys.byteorder == "big":
        values.byteswap()
    counts = Counter(values)
    lo, hi = min(counts), max(counts)
    modal_value, modal_count = counts.most_common(1)[0]
    ordered = sorted(counts)
    cum = 0
    p01 = p99 = None
    for v in ordered:
        cum += counts[v]
        if p01 is None and cum >= PIXELS * 0.01:
            p01 = v
        if p99 is None and cum >= PIXELS * 0.99:
            p99 = v
    extreme = (counts.get(0, 0) + counts.get(65535, 0)) / PIXELS
    report = {
        "value_count": PIXELS,
        "sample_size_bytes": STRIP_BYTES,
        "minimum": lo,
        "maximum": hi,
        "p01": p01,
        "p99": p99,
        "distinct_values": len(counts),
        "modal_value": modal_value,
        "modal_fraction": round(modal_count / PIXELS, 6),
        "mean": round(sum(v * c for v, c in counts.items()) / PIXELS, 3),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }
    if len(counts) < MIN_DISTINCT:
        raise ValueError(f"{label}: only {len(counts)} distinct values")
    if modal_count / PIXELS > MAX_MODAL_FRACTION:
        raise ValueError(f"{label}: value {modal_value} fills {modal_count / PIXELS:.3f} of the frame")
    if hi - lo < MIN_RANGE:
        raise ValueError(f"{label}: dynamic range {hi - lo} < {MIN_RANGE}")
    if extreme > MAX_EXTREME_FRACTION:
        raise ValueError(f"{label}: {extreme:.4f} of pixels are 0 or 65535")
    return report


# --------------------------------------------------------------------------- selftest

def make_xmp(gain: str | None = TLINEAR_GAIN, normalized: str | None = "1") -> bytes:
    body = '<?xpacket begin="" id="W5M0MpCehiHzreSzNTczkc9d"?>\n<rdf:RDF><rdf:Description rdf:about="">\n'
    if gain is not None:
        body += f"<Camera:TlinearGain>{gain}</Camera:TlinearGain>\n"
    if normalized is not None:
        body += f"<Camera:IsNormalized>{normalized}</Camera:IsNormalized>\n"
    body += "<Camera:DetectorBitDepth>16</Camera:DetectorBitDepth>\n</rdf:Description></rdf:RDF>\n<?xpacket end=\"w\"?> "
    return body.encode()


def make_tiff(values: list[int], order: str, strips: int, width: int = WIDTH, height: int = HEIGHT,
              xmp: bytes | None = None) -> bytes:
    e = "<" if order == "II" else ">"
    pix = struct.pack(e + f"{len(values)}H", *values)
    make = b"FLIR\x00"
    model = b"Vue Pro R 640 13mm\x00"
    per = len(pix) // strips
    strip_counts = [per] * (strips - 1) + [len(pix) - per * (strips - 1)]
    if xmp is None:
        xmp = make_xmp()
    entries_n = 13 if xmp else 12
    ifd_off = 8
    ifd_size = 2 + 12 * entries_n + 4
    extra_off = ifd_off + ifd_size
    extra = bytearray()

    def put(blob: bytes) -> int:
        off = extra_off + len(extra)
        extra.extend(blob)
        if len(extra) % 2:
            extra.append(0)
        return off

    make_off = put(make)
    model_off = put(model)
    xmp_off = put(xmp) if xmp else 0
    offs_off = put(b"\x00" * (4 * strips)) if strips > 1 else 0
    cnts_off = put(struct.pack(e + f"{strips}I", *strip_counts)) if strips > 1 else 0
    pix_off = extra_off + len(extra) + 64  # gap before pixel data
    strip_offs = [pix_off + sum(strip_counts[:i]) for i in range(strips)]
    if strips > 1:
        extra[offs_off - extra_off:offs_off - extra_off + 4 * strips] = struct.pack(e + f"{strips}I", *strip_offs)

    def ent(tag: int, typ: int, cnt: int, val: int) -> bytes:
        if typ == 3 and cnt == 1:
            return struct.pack(e + "HHIH", tag, typ, cnt, val) + b"\x00\x00"
        return struct.pack(e + "HHII", tag, typ, cnt, val)

    ents = [ent(256, 3, 1, width), ent(257, 3, 1, height), ent(258, 3, 1, 16), ent(259, 3, 1, 1),
            ent(262, 3, 1, 1), ent(271, 2, len(make), make_off), ent(272, 2, len(model), model_off),
            ent(273, 4, strips, strip_offs[0] if strips == 1 else offs_off), ent(277, 3, 1, 1),
            ent(279, 4, strips, strip_counts[0] if strips == 1 else cnts_off), ent(284, 3, 1, 1),
            ent(339, 3, 1, 1)]
    if xmp:
        ents.append(ent(700, 1, len(xmp), xmp_off))
    assert len(ents) == entries_n
    head = (b"II*\x00" if e == "<" else b"MM\x00*") + struct.pack(e + "I", ifd_off)
    ifd = struct.pack(e + "H", entries_n) + b"".join(ents) + struct.pack(e + "I", 0)
    body = head + ifd + bytes(extra) + b"\xAA" * 64 + pix + b"trailer-metadata"
    return body


def make_member(name: str, raw: bytes, mode: str) -> tuple[bytes, dict[str, object]]:
    co = zlib.compressobj(6, zlib.DEFLATED, -15)
    comp = co.compress(raw) + co.flush()
    crc = zlib.crc32(raw) & 0xFFFFFFFF
    nb = name.encode()
    extra = b"\x55\x54\x05\x00\x01\x00\x00\x00\x00" if mode != "plain" else b""
    if mode == "plain":
        lfh = struct.pack("<IHHHHHIIIHH", 0x04034B50, 20, 0, 8, 0, 0, crc, len(comp), len(raw), len(nb), len(extra))
        dd = b""
    else:
        usize_field = len(raw) if mode == "dd_sig" else 0  # dd_sig mimics the upstream macOS layout
        lfh = struct.pack("<IHHHHHIIIHH", 0x04034B50, 20, 8, 8, 0, 0, 0, 0, usize_field, len(nb), len(extra))
        dd = struct.pack("<III", crc, len(comp), len(raw))
        if mode == "dd_sig":
            dd = b"PK\x07\x08" + dd
    blob = lfh + nb + extra + comp + dd
    session, frame = name.split("/")
    row = {"session": session, "frame": frame, "member_lho": 1000, "range_end": 1000 + len(blob) - 1,
           "compressed_size": len(comp), "uncompressed_size": len(raw), "crc32": f"{crc:08x}"}
    return blob, row


def selftest(_args: argparse.Namespace) -> None:
    rng = random.Random(20180821)
    cases = 0
    base = [6800 + ((x * 7 + y * 3) % 300) + rng.randrange(40) for y in range(HEIGHT) for x in range(WIDTH)]
    expected = array("H", base)
    if sys.byteorder == "big":
        expected.byteswap()
    for order in ("II", "MM"):
        for strips in (1, 3, 512):
            tif = make_tiff(base, order, strips)
            plane, facts = decode_tiff(tif, "synthetic")
            if plane != expected.tobytes() or facts["byte_order"] != order or facts["strips"] != strips:
                raise SystemExit(f"selftest: TIFF decode mismatch order={order} strips={strips}")
            cases += 1
    tif = make_tiff(base, "II", 1)
    for mode in ("plain", "dd", "dd_sig"):
        blob, row = make_member("20180821_092823/20180821_093500.tiff", tif, mode)
        if inflate_member(blob, row) != tif:
            raise SystemExit(f"selftest: member mismatch mode={mode}")
        bad = bytearray(blob)
        bad[len(blob) // 2] ^= 0x10
        try:
            inflate_member(bytes(bad), row)
            raise SystemExit(f"selftest: corrupted member not rejected mode={mode}")
        except (ValueError, zlib.error):
            pass
        try:
            inflate_member(blob[:-1], row)
            raise SystemExit("selftest: truncated member not rejected")
        except ValueError:
            pass
        cases += 1
    # wrong geometry / bit depth / compression rejected
    for bad_tif in (make_tiff(base[:PIXELS // 2], "II", 1, WIDTH, HEIGHT // 2),
                    tif.replace(b"Vue Pro R 640", b"Boson 640 XXX")):
        try:
            decode_tiff(bad_tif, "synthetic-bad")
            raise SystemExit("selftest: bad TIFF not rejected")
        except ValueError:
            pass
    bad8 = bytearray(tif)
    pos = bad8.find(struct.pack("<HHIH", 258, 3, 1, 16))
    bad8[pos + 8:pos + 10] = struct.pack("<H", 8)
    try:
        decode_tiff(bytes(bad8), "synthetic-8bit")
        raise SystemExit("selftest: 8-bit TIFF not rejected")
    except ValueError:
        pass
    # XMP T-linear lattice: accept 0.04/1 (already exercised above); reject others
    for bad_xmp in (make_xmp("0.4", "1"), make_xmp(TLINEAR_GAIN, "0"), make_xmp(None, "1"),
                    make_xmp(TLINEAR_GAIN, None), make_xmp(TLINEAR_GAIN, "1") + make_xmp("0.4", "1"), b""):
        try:
            decode_tiff(make_tiff(base, "II", 1, xmp=bad_xmp), "synthetic-xmp")
            raise SystemExit(f"selftest: bad XMP not rejected: {bad_xmp[:120]!r}")
        except ValueError:
            pass
    _plane, facts = decode_tiff(make_tiff(base, "MM", 3), "synthetic-xmp-ok")
    if facts["tlinear_gain_k_per_count"] != TLINEAR_GAIN_K_PER_COUNT:
        raise SystemExit("selftest: gain fact missing")
    # semantic gates
    characterize(expected.tobytes(), "synthetic")
    flat = array("H", [7000] * PIXELS)
    flat[0] = 7100
    for bad_payload in (flat, array("H", [7000 + (i % 2) * 10 for i in range(PIXELS)])):
        if sys.byteorder == "big":
            bad_payload.byteswap()
        try:
            characterize(bad_payload.tobytes(), "synthetic-degenerate")
            raise SystemExit("selftest: degenerate frame not rejected")
        except ValueError:
            pass
    print(f"selftest ok ({cases} decode cases + rejection cases)")


# --------------------------------------------------------------------------- commands

def cmd_list(args: argparse.Namespace) -> None:
    for r in selected_rows(args.table):
        start, end = int(r["member_lho"]), int(r["range_end"])
        print(f"{r['session']}\t{r['frame']}\t{r['zip_size']}\t{start}\t{end}\t{end - start + 1}")


def cmd_check(args: argparse.Namespace) -> None:
    row = find_row(args.table, args.session, args.frame)
    try:
        raw = inflate_member(args.range_file.read_bytes(), row)
        decode_tiff(raw, f"{args.session}/{args.frame}")
    except (ValueError, zlib.error, struct.error) as exc:
        print(f"check failed: {exc}", file=sys.stderr)
        raise SystemExit(1)


def sample_rel(row: dict[str, object]) -> str:
    stem = str(row["frame"]).removesuffix(".tiff")
    return f"samples/{DATASET_ID}/{SERIES_ID}/{stem}_h{HEIGHT}_w{WIDTH}_u16le.bin"


def decode_row(download_dir: Path, row: dict[str, object]) -> tuple[bytes, dict[str, object]]:
    label = f"{row['session']}/{row['frame']}"
    path = member_path(download_dir, row)
    if not path.is_file():
        raise SystemExit(f"missing download {path}")
    raw = inflate_member(path.read_bytes(), row)
    return decode_tiff(raw, label)


def cmd_build(args: argparse.Namespace) -> None:
    rows = selected_rows(args.table)
    tree = args.data_root / "samples" / DATASET_ID
    if tree.exists():
        shutil.rmtree(tree)
    out_dir = tree / SERIES_ID
    out_dir.mkdir(parents=True, exist_ok=True)
    index_rows = []
    per_session: dict[str, int] = Counter()
    hashes = set()
    gmin, gmax = 65535, 0
    for i, row in enumerate(rows):
        label = f"{row['session']}/{row['frame']}"
        plane, facts = decode_row(args.download_dir, row)
        stats = characterize(plane, label)
        if stats["sha256"] in hashes:
            raise SystemExit(f"{label}: duplicate frame content")
        hashes.add(stats["sha256"])
        rel = sample_rel(row)
        target = args.data_root / rel
        tmp = target.with_suffix(".tmp")
        tmp.write_bytes(plane)
        os.replace(tmp, target)
        per_session[str(row["session"])] += 1
        gmin, gmax = min(gmin, int(stats["minimum"])), max(gmax, int(stats["maximum"]))
        index_rows.append({
            "dataset_id": DATASET_ID, "series_id": SERIES_ID, "sample_path": rel,
            "numeric_kind": "uint", "bit_width": 16, "endianness": "little",
            "element_size_bytes": 2, "sample_size_bytes": STRIP_BYTES, "value_count": PIXELS,
            "height": HEIGHT, "width": WIDTH, "session": row["session"],
            "source_member": f"{row['session']}.zip:{row['session']}/{row['frame']}",
            "source_crc32": row["crc32"], "source_byte_order": facts["byte_order"],
            "tlinear_gain_k_per_count": facts["tlinear_gain_k_per_count"],
            "minimum": stats["minimum"], "maximum": stats["maximum"], "p01": stats["p01"], "p99": stats["p99"],
            "distinct_values": stats["distinct_values"], "modal_fraction": stats["modal_fraction"],
            "mean": stats["mean"], "sha256": stats["sha256"],
        })
        if (i + 1) % 40 == 0:
            print(f"  {i + 1}/{len(rows)} frames")
    args.index.parent.mkdir(parents=True, exist_ok=True)
    with args.index.open("w", encoding="utf-8") as fh:
        for r in index_rows:
            fh.write(json.dumps(r, sort_keys=True) + "\n")
    summary = {
        "dataset_id": DATASET_ID, "series_id": SERIES_ID, "sample_count": len(index_rows),
        "total_size_bytes": STRIP_BYTES * len(index_rows), "total_values": PIXELS * len(index_rows),
        "per_session": dict(per_session), "minimum": gmin, "maximum": gmax,
        "tlinear_gain_k_per_count": TLINEAR_GAIN_K_PER_COUNT,
        "median_distinct_values": sorted(r["distinct_values"] for r in index_rows)[len(index_rows) // 2],
        "max_modal_fraction": max(r["modal_fraction"] for r in index_rows),
        "aggregate_sha256": hashlib.sha256("".join(r["sha256"] for r in index_rows).encode()).hexdigest(),
    }
    args.stats.parent.mkdir(parents=True, exist_ok=True)
    args.stats.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(summary, sort_keys=True))


def cmd_verify(args: argparse.Namespace) -> None:
    rows = selected_rows(args.table)
    manifest = tomllib.loads(args.manifest.read_text(encoding="utf-8"))
    series = [s for s in manifest["series"] if s["id"] == SERIES_ID]
    if len(series) != 1:
        raise SystemExit("manifest must declare exactly one primary series")
    index = [json.loads(line) for line in args.index.read_text(encoding="utf-8").splitlines() if line.strip()]
    if len(index) != len(rows):
        raise SystemExit(f"index has {len(index)} rows, expected {len(rows)}")
    hashes = set()
    total = 0
    for row, entry in zip(rows, index):
        label = f"{row['session']}/{row['frame']}"
        rel = sample_rel(row)
        want = {"dataset_id": DATASET_ID, "series_id": SERIES_ID, "sample_path": rel, "numeric_kind": "uint",
                "bit_width": 16, "endianness": "little", "element_size_bytes": 2,
                "sample_size_bytes": STRIP_BYTES, "value_count": PIXELS, "session": row["session"],
                "source_crc32": row["crc32"], "tlinear_gain_k_per_count": TLINEAR_GAIN_K_PER_COUNT}
        for key, value in want.items():
            if entry.get(key) != value:
                raise SystemExit(f"{label}: index field {key}={entry.get(key)!r} (want {value!r})")
        stored = (args.data_root / rel).read_bytes()
        if len(stored) != STRIP_BYTES:
            raise SystemExit(f"{label}: stored size {len(stored)}")
        plane, facts = decode_row(args.download_dir, row)
        if facts["tlinear_gain_k_per_count"] != TLINEAR_GAIN_K_PER_COUNT:
            raise SystemExit(f"{label}: source frame is not on the 0.04 K T-linear lattice")
        if plane != stored:
            raise SystemExit(f"{label}: stored sample differs from re-decoded source")
        stats = characterize(stored, label)
        for key in ("minimum", "maximum", "p01", "p99", "distinct_values", "modal_fraction", "mean", "sha256"):
            if entry.get(key) != stats[key]:
                raise SystemExit(f"{label}: index {key}={entry.get(key)!r} but recomputed {stats[key]!r}")
        if stats["sha256"] in hashes:
            raise SystemExit(f"{label}: duplicate frame")
        hashes.add(stats["sha256"])
        total += len(stored)
    tree = args.data_root / "samples" / DATASET_ID
    if sorted(p.name for p in tree.iterdir()) != [SERIES_ID] or not (tree / SERIES_ID).is_dir():
        raise SystemExit(f"{tree} must contain only the {SERIES_ID}/ directory")
    out_dir = tree / SERIES_ID
    on_disk = sorted(p.name for p in out_dir.iterdir())
    if on_disk != sorted(Path(r["sample_path"]).name for r in index):
        raise SystemExit("sample directory contents differ from the index")
    s = series[0]
    if s["sample_count"] != len(index) or s["total_size_bytes"] != total:
        raise SystemExit(f"manifest declares {s['sample_count']} samples / {s['total_size_bytes']} bytes; "
                         f"realized {len(index)} / {total}")
    stats_json = json.loads(args.stats.read_text(encoding="utf-8"))
    agg = hashlib.sha256("".join(r["sha256"] for r in index).encode()).hexdigest()
    if (stats_json.get("aggregate_sha256") != agg or stats_json.get("sample_count") != len(index)
            or stats_json.get("tlinear_gain_k_per_count") != TLINEAR_GAIN_K_PER_COUNT):
        raise SystemExit("ingest_stats.json disagrees with the index")
    print(f"verify ok: {len(index)} frames, {total} bytes, {len(index) * PIXELS} values, aggregate {agg}")


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("selftest")
    p = sub.add_parser("list")
    p.add_argument("--table", type=Path, required=True)
    p = sub.add_parser("check")
    p.add_argument("--table", type=Path, required=True)
    p.add_argument("--session", required=True)
    p.add_argument("--frame", required=True)
    p.add_argument("--range-file", type=Path, required=True)
    for name in ("build", "verify"):
        p = sub.add_parser(name)
        p.add_argument("--table", type=Path, required=True)
        p.add_argument("--download-dir", type=Path, required=True)
        p.add_argument("--index", type=Path, required=True)
        p.add_argument("--stats", type=Path, required=True)
        p.add_argument("--data-root", type=Path, required=True)
        if name == "verify":
            p.add_argument("--manifest", type=Path, required=True)
    args = ap.parse_args()
    {"selftest": selftest, "list": cmd_list, "check": cmd_check, "build": cmd_build, "verify": cmd_verify}[args.cmd](args)


if __name__ == "__main__":
    main()
