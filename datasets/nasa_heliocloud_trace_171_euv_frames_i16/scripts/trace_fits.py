#!/usr/bin/env python3
"""Shared FITS header/regime/metric code for the TRACE 171 A full-frame recipe.

Used by discover.py, check_payload.py and build.py. verify.py deliberately does
NOT import this module; it carries its own independent implementation.

Pure standard library. The SDAC TRACE files are simple single-HDU FITS images:
an ASCII header of 2880-byte blocks (two blocks for these files), then
NAXIS1 x NAXIS2 big-endian int16 pixels (BITPIX 16, no BZERO/BSCALE), padded to
a 2880-byte boundary.
"""

from __future__ import annotations

import operator
import re
import sys
from array import array
from collections import Counter

BLOCK = 2880
CARD = 80
WIDTH = 1024
HEIGHT = 1024
NPIX = WIDTH * HEIGHT
FILE_SIZE = 2_105_280          # 2 header blocks + 729 data blocks
HEADER_SIZE = 5_760
DATA_SIZE = NPIX * 2

# Observation window: TRACE first light to the end of October 1998. The SDAC trace_prep
# output carries a multiplicative calibration gain g that drifts with time. Inside this
# window g is close to 1 (measured ~1.015 in early May rising to ~1.09 in October, seen as
# a partial near-zero hole drifting from |k|~33 to |k|~5-6); later it reaches ~1.06-1.17
# (Nov 1998-Mar 1999), ~1.25 (mid 1999), ~1.45-1.5 (2000-2001, 2005-2010) and ~1.9 (2003),
# which leaves periodic empty near-zero bins. See README.md.
WINDOW_START = "1998-04-20"
WINDOW_END = "1998-10-31"

KEY_RE = re.compile(
    r"^sdac/trace/1998/(\d{2})/(\d{2})/trac_171____a0_(1998\d{4})_(\d{6})\.fts$")

HISTORY_PATTERNS = [
    ("prep_saturated", re.compile(r"^trace_prep\s+Replaced\s+(\d+) saturated pixels with value > 4100$")),
    ("dark_sub", re.compile(r"^tr_dark_sub VERSION:\s+2\.10 Subtracted dark pedestal and current$")),
    ("flat_sub", re.compile(r"^tr_flat_sub VERSION:\s+1\.60 Image divided by corrected flat field$")),
    ("wave2point", re.compile(r"^trace_wave2point\s+XYOffsets:\s+(-?\d+\.\d+)\s+(-?\d+\.\d+)$")),
]
CANONICAL_HISTORIES = (
    ("prep_saturated", "dark_sub", "flat_sub", "wave2point"),
    ("dark_sub", "flat_sub", "wave2point"),
)

# Data-regime thresholds (applied by build.py; verify.py re-implements them).
LATTICE_KMIN, LATTICE_KMAX = -60, 1500
LATTICE_MIN_NEIGHBOUR = 300
LATTICE_HOLE_RATIO = 0.5
LATTICE_MIN_ELIGIBLE = 8       # below this the frame is reported as lattice-untestable
BLOCK_RATIO_MIN, BLOCK_RATIO_MAX = 0.80, 1.06
MAX_DOMINANT_FRACTION = 0.15
MAX_ZERO_FRACTION = 0.15
MIN_DISTINCT = 256
MIN_EXPOSURE_S = 1.0
MIN_IMG_MAX = 300.0

# Onboard JPEG mode is named by the frame program FRM_NAM (it selects the JPEG table).
# Near-lossless programs: names containing 'lossless', ending in 'Q0' (JPEG table 0), or the
# disk-centre calibration program cjs.caldc171. Measured on the 1998 pool, every one of them
# is free of lossy-JPEG ringing, and every other program (cjs.stdaecfull171, cjs.stdfull171,
# ras.aecfb171, cck.FeX.Q6, ...) rings. CONDITIONAL_PROGRAMS are admitted only if the data
# ringing test passes with at least RING_MIN_CELLS_CONDITIONAL spike cells.
NEAR_LOSSLESS_PROGRAM_RE = re.compile(r"(lossless|Q0$)")
NEAR_LOSSLESS_PROGRAMS = frozenset({"cjs.caldc171"})
CONDITIONAL_PROGRAMS = frozenset({"ras.jpeg171.aecm4"})

# Ringing test: aligned 8x8 cells with rows and columns 8..1015 (cell indices 1..126);
# a spike cell has median < 60 DN and max > 400 DN; median = mean of the 32nd and 33rd
# sorted values. D = median over spike cells of (cell min - cell median).
RING_CELL_MEDIAN_MAX = 60
RING_CELL_MAX_MIN = 400
RING_D_MIN = -15.0
RING_MIN_CELLS = 5
RING_MIN_CELLS_CONDITIONAL = 20
RING_LOW_PIXEL = -15


def program_class(frm_nam: str) -> str:
    if frm_nam in NEAR_LOSSLESS_PROGRAMS or NEAR_LOSSLESS_PROGRAM_RE.search(frm_nam):
        return "allowlisted"
    if frm_nam in CONDITIONAL_PROGRAMS:
        return "conditional"
    return "excluded"


def parse_header(blob: bytes) -> tuple[dict, list[str], int]:
    """Return (keywords, history lines, data offset). Raises ValueError."""
    cards: dict = {}
    history: list[str] = []
    pos = 0
    while True:
        if pos + CARD > len(blob):
            raise ValueError("header truncated before END")
        raw = blob[pos:pos + CARD]
        pos += CARD
        try:
            card = raw.decode("ascii")
        except UnicodeDecodeError as exc:
            raise ValueError(f"non-ASCII header card at byte {pos - CARD}") from exc
        name = card[:8].rstrip()
        if name == "END":
            break
        if name == "HISTORY":
            history.append(card[8:].strip())
            continue
        if name in ("COMMENT", "") or card[8:10] != "= ":
            continue
        cards[name] = parse_value(card[10:])
    data_offset = ((pos + BLOCK - 1) // BLOCK) * BLOCK
    return cards, history, data_offset


def parse_value(text: str):
    text = text.strip()
    if text.startswith("'"):
        end = text.find("'", 1)
        while end != -1 and end + 1 < len(text) and text[end + 1] == "'":
            end = text.find("'", end + 2)
        if end == -1:
            raise ValueError(f"unterminated string value {text!r}")
        return text[1:end].replace("''", "'").rstrip()
    value = text.split("/", 1)[0].strip()
    if value == "T":
        return True
    if value == "F":
        return False
    try:
        return int(value)
    except ValueError:
        pass
    try:
        return float(value)
    except ValueError:
        return value


def history_signature(history: list[str]) -> tuple[tuple[str, ...], list[str]]:
    sig, unknown = [], []
    for line in history:
        for name, pattern in HISTORY_PATTERNS:
            if pattern.match(line):
                sig.append(name)
                break
        else:
            unknown.append(line)
    return tuple(sig), unknown


def regime_problems(h: dict, history: list[str]) -> list[str]:
    """Header regime: TRACE 171 A, full unsummed 1024x1024 amp-A frame, canonical prep."""
    p = []
    def want(key, value):
        if h.get(key) != value:
            p.append(f"{key}={h.get(key)!r} (want {value!r})")
    want("SIMPLE", True)
    want("BITPIX", 16)
    want("NAXIS", 2)
    want("NAXIS1", WIDTH)
    want("NAXIS2", HEIGHT)
    want("TELESCOP", "TRACE")
    want("INSTRUME", "TRACE")
    want("WAVE_LEN", "171")
    want("AMP", "A")
    want("SUM_CCDX", 1)
    want("SUM_CCDY", 1)
    want("BIN_CCD", 1)
    want("TBIN_CCD", 1)
    want("SOU_AREA", 0)
    if program_class(str(h.get("FRM_NAM", ""))) == "excluded":
        p.append(f"FRM_NAM={h.get('FRM_NAM')!r} is not a near-lossless JPEG program")
    for key in ("BZERO", "BSCALE", "BLANK", "NAXIS3", "PBADPIX"):
        if key in h:
            p.append(f"unexpected keyword {key}")
    for key in ("SRI_LLEX", "SRI_LLEY"):
        if not isinstance(h.get(key), (int, float)) or float(h[key]) != 0.0:
            p.append(f"{key}={h.get(key)!r} (want 0: full-CCD extract)")
    pct = h.get("PERCENTD")
    if not isinstance(pct, (int, float)) or abs(float(pct) - 100.0) > 1e-6:
        p.append(f"PERCENTD={pct!r} (want 100)")
    exp = h.get("SHT_MDUR")
    if not isinstance(exp, (int, float)) or float(exp) < MIN_EXPOSURE_S:
        p.append(f"SHT_MDUR={exp!r} (want >= {MIN_EXPOSURE_S} s)")
    imax = h.get("IMG_MAX")
    if not isinstance(imax, (int, float)) or float(imax) < MIN_IMG_MAX:
        p.append(f"IMG_MAX={imax!r} (want >= {MIN_IMG_MAX})")
    date_obs = str(h.get("DATE_OBS", ""))
    if not re.fullmatch(r"1998-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?", date_obs):
        p.append(f"DATE_OBS={date_obs!r}")
    elif not (WINDOW_START <= date_obs[:10] <= WINDOW_END):
        p.append(f"DATE_OBS {date_obs} outside {WINDOW_START}..{WINDOW_END}")
    sig, unknown = history_signature(history)
    if unknown:
        p.append(f"unrecognised HISTORY {unknown[:2]!r}")
    if sig not in CANONICAL_HISTORIES:
        p.append(f"HISTORY signature {sig!r} not canonical")
    return p


def key_matches_header(key: str, h: dict) -> bool:
    m = KEY_RE.match(key)
    if not m:
        return False
    stamp = m.group(3) + "_" + m.group(4)
    d = str(h.get("DATE_OBS", ""))
    return (len(d) >= 19 and d[:4] + d[5:7] + d[8:10] + "_" + d[11:13] + d[14:16] + d[17:19] == stamp
            and m.group(1) == d[5:7] and m.group(2) == d[8:10])


def decode_pixels(blob: bytes, data_offset: int) -> array:
    """Big-endian int16 FITS pixels -> array('h') in native (little-endian) order."""
    if data_offset != HEADER_SIZE or len(blob) != FILE_SIZE:
        raise ValueError(f"unexpected layout offset={data_offset} size={len(blob)}")
    pad = blob[data_offset + DATA_SIZE:]
    if pad.strip(b"\x00"):
        raise ValueError("non-zero bytes in FITS data padding")
    pixels = array("h")
    pixels.frombytes(blob[data_offset:data_offset + DATA_SIZE])
    if sys.byteorder == "little":
        pixels.byteswap()
    return pixels


def lattice_holes(counts: Counter) -> tuple[int, list[int], int | None, float | None]:
    """Tested bins (both neighbours >= LATTICE_MIN_NEIGHBOUR) that hold < half the smaller
    neighbour, plus the tested bin with the lowest count/neighbour ratio."""
    eligible, holes, worst_k, worst_r = 0, [], None, None
    for k in range(LATTICE_KMIN, LATTICE_KMAX + 1):
        m = min(counts.get(k - 1, 0), counts.get(k + 1, 0))
        if m >= LATTICE_MIN_NEIGHBOUR:
            eligible += 1
            ratio = counts.get(k, 0) / m
            if worst_r is None or ratio < worst_r:
                worst_k, worst_r = k, ratio
            if counts.get(k, 0) < LATTICE_HOLE_RATIO * m:
                holes.append(k)
    return eligible, holes, worst_k, worst_r


def ringing(px: array) -> tuple[int, float | None]:
    """(number of spike cells, D = median of cell min - cell median over spike cells)."""
    ds = []
    for cy in range(1, HEIGHT // 8 - 1):
        rows = [px[(cy * 8 + j) * WIDTH:(cy * 8 + j + 1) * WIDTH] for j in range(8)]
        for cx in range(1, WIDTH // 8 - 1):
            x0 = cx * 8
            cell = []
            for row in rows:
                cell.extend(row[x0:x0 + 8])
            if max(cell) <= RING_CELL_MAX_MIN:
                continue
            cell.sort()
            med = (cell[31] + cell[32]) / 2
            if med < RING_CELL_MEDIAN_MAX:
                ds.append(cell[0] - med)
    if not ds:
        return 0, None
    ds.sort()
    n = len(ds)
    d = ds[n // 2] if n % 2 else (ds[n // 2 - 1] + ds[n // 2]) / 2
    return n, d


def block_ratios(px: array) -> tuple[float, float]:
    """Mean |neighbour difference| across 8-pixel JPEG cell boundaries / inside cells.

    Horizontal: pairs (x, x+1) with x % 8 == 7 vs the other in-row pairs.
    Vertical: pairs (y, y+1) with y % 8 == 7 vs the other column pairs.
    """
    sub = operator.sub
    hb = hi = 0
    for r in range(HEIGHT):
        row = px[r * WIDTH:(r + 1) * WIDTH]
        for phase in range(8):
            s = sum(map(abs, map(sub, row[phase + 1::8], row[phase::8])))
            if phase == 7:
                hb += s
            else:
                hi += s
    n_hb = HEIGHT * (WIDTH // 8 - 1)
    n_hi = HEIGHT * (WIDTH // 8) * 7
    vb = vi = 0
    prev = px[0:WIDTH]
    for r in range(1, HEIGHT):
        cur = px[r * WIDTH:(r + 1) * WIDTH]
        s = sum(map(abs, map(sub, cur, prev)))
        if (r - 1) % 8 == 7:
            vb += s
        else:
            vi += s
        prev = cur
    n_vb = (HEIGHT // 8 - 1) * WIDTH
    n_vi = (HEIGHT - 1 - (HEIGHT // 8 - 1)) * WIDTH
    h_ratio = (hb / n_hb) / (hi / n_hi) if hi else float("inf")
    v_ratio = (vb / n_vb) / (vi / n_vi) if vi else float("inf")
    return h_ratio, v_ratio


def frame_metrics(px: array) -> dict:
    counts = Counter(px)
    dom_value, dom_count = counts.most_common(1)[0]
    eligible, holes, worst_k, worst_r = lattice_holes(counts)
    n_spike, ring_d = ringing(px)
    h_ratio, v_ratio = block_ratios(px)
    const_rows = sum(1 for r in range(HEIGHT)
                     if min(px[r * WIDTH:(r + 1) * WIDTH]) == max(px[r * WIDTH:(r + 1) * WIDTH]))
    const_cols = sum(1 for c in range(WIDTH) if min(px[c::WIDTH]) == max(px[c::WIDTH]))
    return {
        "min": min(px), "max": max(px), "distinct": len(counts),
        "dominant_value": dom_value, "dominant_fraction": dom_count / NPIX,
        "zero_fraction": counts.get(0, 0) / NPIX,
        "lattice_eligible": eligible, "lattice_holes": holes,
        "lattice_worst_k": worst_k, "lattice_worst_ratio": worst_r,
        "n_spike_cells": n_spike, "ring_d": ring_d,
        "n_below_low": sum(1 for v in px if v < RING_LOW_PIXEL),
        "block_h": h_ratio, "block_v": v_ratio,
        "const_rows": const_rows, "const_cols": const_cols,
        "sum": sum(px),
    }


def data_problems(m: dict, frm_nam: str) -> list[str]:
    p = []
    cls = program_class(frm_nam)
    need = RING_MIN_CELLS_CONDITIONAL if cls == "conditional" else RING_MIN_CELLS
    if cls == "excluded":
        p.append(f"FRM_NAM {frm_nam!r} not near-lossless")
    if m["n_spike_cells"] >= RING_MIN_CELLS:
        if m["ring_d"] <= RING_D_MIN:
            p.append(f"ringing D={m['ring_d']} <= {RING_D_MIN} over {m['n_spike_cells']} spike cells (lossy JPEG)")
    if m["n_spike_cells"] < need:
        if cls != "allowlisted":
            p.append(f"ringing untestable: {m['n_spike_cells']} spike cells < {need} for a conditional program")
        elif m["n_below_low"]:
            p.append(f"ringing untestable ({m['n_spike_cells']} spike cells) and {m['n_below_low']} pixels < {RING_LOW_PIXEL}")
    if m["lattice_eligible"] < LATTICE_MIN_ELIGIBLE:
        p.append(f"lattice untestable: {m['lattice_eligible']} tested bins")
    if m["lattice_holes"]:
        p.append(f"empty near-zero bins {m['lattice_holes']}")
    for axis in ("block_h", "block_v"):
        if not (BLOCK_RATIO_MIN <= m[axis] <= BLOCK_RATIO_MAX):
            p.append(f"{axis}={m[axis]:.4f} outside [{BLOCK_RATIO_MIN}, {BLOCK_RATIO_MAX}] (JPEG cell edges)")
    if m["dominant_fraction"] > MAX_DOMINANT_FRACTION:
        p.append(f"dominant value {m['dominant_value']} covers {m['dominant_fraction']:.3f}")
    if m["zero_fraction"] > MAX_ZERO_FRACTION:
        p.append(f"zero fraction {m['zero_fraction']:.3f}")
    if m["distinct"] < MIN_DISTINCT:
        p.append(f"only {m['distinct']} distinct values")
    if m["const_rows"] or m["const_cols"]:
        p.append(f"constant rows/cols {m['const_rows']}/{m['const_cols']}")
    return p
