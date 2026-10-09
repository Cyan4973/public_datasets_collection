#!/usr/bin/env python3
"""Minimal FITS reader for the PRIMARY + IMAGE prefix of SPHEREx QR3 L2 spectral images.

Used by discover.py, check_payload.py and build.py. verify.py deliberately carries its own,
separately written card parser and byte-swap so that the two paths cross-check each other.
Pure standard library; no network I/O.
"""
from __future__ import annotations

import array
import hashlib
import math
import re
import sys

BLOCK = 2880
CARD = 80
NAXIS1 = 2040
NAXIS2 = 2040
IMAGE_VALUES = NAXIS1 * NAXIS2  # 4,161,600
IMAGE_BYTES = IMAGE_VALUES * 4  # 16,646,400 (exactly 5,780 FITS blocks, no padding)
MAX_HEADER_BLOCKS = 64
MAX_NONFINITE_FRACTION = 0.02
MIN_DISTINCT = 100_000

NAME_RE = re.compile(
    r"^level2_(?P<group>20\d\dW\d\d_\d[A-Z])_(?P<obs>\d{4})_(?P<exp>\d)D(?P<det>\d)_spx_(?P<ver>l2b-v27-\d{4}-\d{3})\.fits$"
)

if sys.byteorder != "little":  # pragma: no cover - the recipe targets little-endian hosts
    raise SystemExit("FATAL this recipe assumes a little-endian host")


class FitsError(ValueError):
    pass


def _value(raw: str):
    """Parse the value field of one card (after '= ')."""
    raw = raw.strip()
    if raw.startswith("'"):
        out = []
        i = 1
        while i < len(raw):
            ch = raw[i]
            if ch == "'":
                if i + 1 < len(raw) and raw[i + 1] == "'":
                    out.append("'")
                    i += 2
                    continue
                break
            out.append(ch)
            i += 1
        return "".join(out).rstrip()
    body = raw.split("/", 1)[0].strip()
    if body == "T":
        return True
    if body == "F":
        return False
    try:
        return int(body)
    except ValueError:
        pass
    try:
        return float(body.replace("D", "E"))
    except ValueError:
        return body


def read_header(buf: bytes, start: int) -> tuple[dict, int]:
    """Walk 2,880-byte blocks from `start` until END; return (cards, data_offset)."""
    cards: dict = {}
    for b in range(MAX_HEADER_BLOCKS):
        lo = start + b * BLOCK
        block = buf[lo:lo + BLOCK]
        if len(block) < BLOCK:
            raise FitsError(f"header truncated at byte {lo}")
        for c in range(0, BLOCK, CARD):
            card = block[c:c + CARD].decode("ascii")
            key = card[:8].rstrip()
            if key == "END":
                return cards, lo + BLOCK
            if key.startswith("HIERARCH"):
                rest = card[8:]
                if "=" in rest:
                    k, v = rest.split("=", 1)
                    cards["HIERARCH " + k.strip()] = _value(v)
                continue
            if card[8:10] == "= " and key not in ("COMMENT", "HISTORY", ""):
                if key in cards:
                    raise FitsError(f"duplicate card {key}")
                cards[key] = _value(card[10:])
    raise FitsError("END not found")


def walk_prefix(buf: bytes) -> dict:
    """Parse PRIMARY and IMAGE headers; returns dict with both card sets and offsets."""
    primary, p_end = read_header(buf, 0)
    if primary.get("SIMPLE") is not True or primary.get("NAXIS") != 0 or primary.get("EXTEND") is not True:
        raise FitsError(f"unexpected PRIMARY header {primary}")
    image, data_offset = read_header(buf, p_end)
    return {"primary": primary, "image": image, "image_header_offset": p_end, "data_offset": data_offset,
            "prefix_bytes": data_offset + IMAGE_BYTES}


def check_regime(info: dict, name: str) -> list[str]:
    """Return a list of regime violations (empty when the file is in the declared regime)."""
    m = NAME_RE.match(name)
    if not m:
        return [f"file name {name!r} does not match the pinned naming pattern"]
    p, h = info["primary"], info["image"]
    bad = []
    expect = {
        "XTENSION": "IMAGE", "BITPIX": -32, "NAXIS": 2, "NAXIS1": NAXIS1, "NAXIS2": NAXIS2,
        "PCOUNT": 0, "GCOUNT": 1, "EXTNAME": "IMAGE", "BUNIT": "MJy / sr", "DETECTOR": 1,
        "DETCOORD": "sky", "L1DQAFLG": "Pass", "L2DQAFLG": "Pass",
        "HIERARCH NON_SURVEY": "False",
        "OBSID": f"{m['group']}_{m['obs']}_{m['exp']}",
        "JACTIVE": 2040, "KACTIVE": 2040,
    }
    for k, v in expect.items():
        if h.get(k) != v:
            bad.append(f"{k}={h.get(k)!r} (expected {v!r})")
    for k in ("BSCALE", "BZERO", "BLANK", "ZIMAGE"):
        if k in h and not (k == "BSCALE" and h[k] == 1) and not (k == "BZERO" and h[k] == 0):
            bad.append(f"unexpected scaling/compression card {k}={h[k]!r}")
    if p.get("VERSION") != "7.0.5":
        bad.append(f"PRIMARY VERSION={p.get('VERSION')!r} (expected '7.0.5')")
    if m["det"] != "1":
        bad.append("file name detector is not D1")
    xp = h.get("XPOSURE")
    if not isinstance(xp, float) or not 100.0 < xp < 130.0:
        bad.append(f"XPOSURE={xp!r} outside the nominal ~113.6 s survey exposure")
    return bad


def decode_be_f32(data: bytes) -> array.array:
    """Big-endian float32 bytes -> native (little-endian) array('f'); bit-exact, NaN payloads kept."""
    if len(data) != IMAGE_BYTES:
        raise FitsError(f"image data has {len(data)} bytes, expected {IMAGE_BYTES}")
    arr = array.array("f")
    arr.frombytes(data)
    arr.byteswap()
    return arr


def image_stats(arr: array.array) -> dict:
    """Statistics over the stored float32 values (min/max/mean over finite values only)."""
    n = len(arr)
    nan = inf = 0
    lo = math.inf
    hi = -math.inf
    total = 0.0
    for x in arr:
        if x != x:
            nan += 1
        elif x in (math.inf, -math.inf):
            inf += 1
        else:
            total += x
            if x < lo:
                lo = x
            if x > hi:
                hi = x
    finite = n - nan - inf
    bits = array.array("I")
    bits.frombytes(arr.tobytes())
    distinct = len(set(bits))
    return {"value_count": n, "nan_count": nan, "inf_count": inf, "finite_count": finite,
            "finite_min": lo if finite else None, "finite_max": hi if finite else None,
            "finite_mean": (total / finite) if finite else None, "distinct_bit_patterns": distinct}


def stats_problems(st: dict) -> list[str]:
    bad = []
    n = st["value_count"]
    if (st["nan_count"] + st["inf_count"]) > MAX_NONFINITE_FRACTION * n:
        bad.append(f"non-finite fraction {(st['nan_count'] + st['inf_count']) / n:.4f} > {MAX_NONFINITE_FRACTION}")
    if st["distinct_bit_patterns"] < MIN_DISTINCT:
        bad.append(f"only {st['distinct_bit_patterns']} distinct values (< {MIN_DISTINCT})")
    if st["finite_count"] == 0 or st["finite_min"] == st["finite_max"]:
        bad.append("constant or empty image")
    elif not (-10.0 < st["finite_mean"] < 1000.0):
        bad.append(f"finite mean {st['finite_mean']} MJy/sr outside a plausible sky-brightness range")
    return bad


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
