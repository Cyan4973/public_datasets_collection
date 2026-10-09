#!/usr/bin/env python3
"""Self-test of the FITS walkers, decoders and data-regime metrics on synthetic frames.

Exercises both trace_fits.py (build path) and verify.py (independent path) and requires
them to agree. No network, no downloaded files.
"""

from __future__ import annotations

import random
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import trace_fits as T  # noqa: E402
import verify as V  # noqa: E402

W = H = 1024
N = W * H
KEY = "sdac/trace/1998/07/10/trac_171____a0_19980710_072030.fts"


def card(text: str) -> bytes:
    return text.ljust(80)[:80].encode("ascii")


def header(overrides: dict | None = None, history: list[str] | None = None) -> bytes:
    kv = {
        "SIMPLE": "T", "BITPIX": "16", "NAXIS": "2", "DATE_OBS": "'1998-07-10T07:20:30.977'",
        "TELESCOP": "'TRACE   '", "INSTRUME": "'TRACE   '", "NAXIS1": "1024", "NAXIS2": "1024",
        "AMP": "'A       '", "SUM_CCDX": "1", "SUM_CCDY": "1", "BIN_CCD": "1", "TBIN_CCD": "1",
        "SRI_LLEX": "0.00000", "SRI_LLEY": "0.00000", "FRM_NAM": "'cjs.stdfull171Q0'",
        "SHT_MDUR": "3.44386", "WAVE_LEN": "'171     '", "SOU_AREA": "0", "PERCENTD": "100.000",
        "IMG_MIN": "22.0000", "IMG_MAX": "898.000",
    }
    kv.update(overrides or {})
    cards = [card(f"{k:<8}= {v:>20} / synthetic") for k, v in kv.items() if v is not None]
    if history is None:
        history = ["trace_prep  Replaced     2 saturated pixels with value > 4100",
                   "tr_dark_sub VERSION:  2.10 Subtracted dark pedestal and current",
                   "tr_flat_sub VERSION:  1.60 Image divided by corrected flat field",
                   "trace_wave2point  XYOffsets:   0.00  0.00"]
    cards += [card("HISTORY " + h) for h in history]
    while len(cards) < 40:   # real SDAC headers span two 2880-byte blocks
        cards.append(card("COMMENT synthetic filler"))
    cards.append(card("END"))
    blob = b"".join(cards)
    return blob + b" " * (-len(blob) % 2880)


def fits(vals: list[int], **kw) -> bytes:
    data = struct.pack(">%dh" % N, *vals)
    blob = header(**kw) + data
    return blob + b"\x00" * (-len(blob) % 2880)


def frame(kind: str, rng: random.Random) -> list[int]:
    vals = []
    if kind == "unit":       # clean integer noise around a faint corona + bright blob
        for y in range(H):
            base = 6 + 600 * max(0.0, 1 - ((y - 700) / 200) ** 2)
            vals += [int(round(rng.gauss(base * (x / W), 3 + 0.05 * base * (x / W)))) for x in range(W)]
        for i in range(300):            # isolated cosmic-ray spikes in the dark lower part
            y, x = rng.randrange(16, 400), rng.randrange(16, 1000)
            vals[y * W + x] = 1500 + rng.randrange(500)
    elif kind == "ringing":   # lossy-JPEG-like undershoot ring around every spike
        vals = frame("unit", rng)
        for i, v in enumerate(vals):
            if v >= 1500 and i // W < 400:
                y, x = divmod(i, W)
                for dy in (-1, 1):
                    for dx in (-1, 0, 1):
                        vals[(y + dy) * W + x + dx] -= 45
    elif kind == "lattice15":  # same signal, values multiplied by 1.5 then rounded
        for v in frame("unit", rng):
            vals.append(int(round(1.5 * v)))
    elif kind == "blocky":   # 8x8 cells with independent offsets and weak interior noise
        offs = [[rng.randint(0, 30) for _ in range(W // 8)] for _ in range(H // 8)]
        for y in range(H):
            vals += [offs[y // 8][x // 8] + rng.choice((-1, 0, 0, 1)) for x in range(W)]
    elif kind == "flat":     # degenerate: mostly a single value
        vals = [5] * N
        for i in range(0, N, 7):
            vals[i] = 5 + (i // 7) % 400
    return vals


def check(cond: bool, msg: str) -> None:
    if not cond:
        raise SystemExit(f"selftest FAILED: {msg}")


def main() -> None:
    rng = random.Random(1998)
    for kind, expect_pass in (("unit", True), ("ringing", False), ("lattice15", False),
                              ("blocky", False), ("flat", False)):
        vals = frame(kind, rng)
        blob = fits(vals)
        check(len(blob) == T.FILE_SIZE, f"{kind}: synthetic size {len(blob)}")
        h, hist, off = T.parse_header(blob)
        check(off == T.HEADER_SIZE, f"{kind}: offset {off}")
        check(T.regime_problems(h, hist) == [], f"{kind}: header {T.regime_problems(h, hist)}")
        check(T.key_matches_header(KEY, h), f"{kind}: key/DATE_OBS")
        px = T.decode_pixels(blob, off)
        check(list(px) == vals, f"{kind}: build decode mismatch")
        m = T.frame_metrics(px)
        build_ok = not T.data_problems(m, "cjs.stdfull171Q0")
        kw, vh, voff = V.walk_header(blob)
        check(voff == off and V.header_ok(kw, vh) == [], f"{kind}: verify header {V.header_ok(kw, vh)}")
        vv = struct.unpack(">%dh" % N, blob[voff:voff + 2 * N])
        check(list(vv) == vals, f"{kind}: verify decode mismatch")
        vm = V.metrics(vv)
        check(vm["spikes"] == m["n_spike_cells"] and vm["ring_d"] == m["ring_d"]
              and vm["worst_k"] == m["lattice_worst_k"] and vm["below"] == m["n_below_low"],
              f"{kind}: ringing/lattice-worst disagreement")
        check(vm["holes"] == m["lattice_holes"] and abs(vm["hr"] - m["block_h"]) < 1e-9
              and abs(vm["vr"] - m["block_v"]) < 1e-9, f"{kind}: metric disagreement {m} {vm}")
        check(build_ok == V.passes(vm, "cjs.stdfull171Q0") == expect_pass,
              f"{kind}: verdict build={build_ok} verify={V.passes(vm, 'cjs.stdfull171Q0')} expected={expect_pass} "
              f"{T.data_problems(m, 'cjs.stdfull171Q0')}")
        print(f"selftest {kind}: holes={m['lattice_holes'][:6]} block=({m['block_h']:.3f},{m['block_v']:.3f}) "
              f"spikes={m['n_spike_cells']} D={m['ring_d']} pass={build_ok}")
        if kind == "unit":
            unit_metrics, unit_vm = m, vm
    # Program classes on the clean frame: excluded program fails, conditional program needs
    # >= 20 spike cells, allowlisted program with < 5 spike cells needs no pixel < -15.
    check(T.data_problems(unit_metrics, "cjs.stdaecfull171") and not V.passes(unit_vm, "cjs.stdaecfull171"),
          "excluded program accepted")
    check(not T.data_problems(unit_metrics, "ras.jpeg171.aecm4") and V.passes(unit_vm, "ras.jpeg171.aecm4"),
          "conditional program with many clean spike cells rejected")
    few = dict(unit_metrics, n_spike_cells=3, ring_d=-6.0)
    few_v = dict(unit_vm, spikes=3, ring_d=-6.0)
    check(T.data_problems(few, "ras.jpeg171.aecm4") and not V.passes(few_v, "ras.jpeg171.aecm4"),
          "conditional program with too few spike cells accepted")
    check(not T.data_problems(dict(few, n_below_low=0), "cjs.caldc171")
          and V.passes(dict(few_v, below=0), "cjs.caldc171"), "clean allowlisted low-spike frame rejected")
    check(T.data_problems(dict(few, n_below_low=1), "cjs.caldc171")
          and not V.passes(dict(few_v, below=1), "cjs.caldc171"), "allowlisted low-spike frame with deep pixel accepted")
    # Header regime rejections (both paths).
    base = frame("unit", rng)
    bad_cases = {
        "wave195": {"overrides": {"WAVE_LEN": "'195     '"}},
        "binned": {"overrides": {"TBIN_CCD": "2"}},
        "partial": {"overrides": {"PERCENTD": "97.1910"}},
        "subarea": {"overrides": {"SOU_AREA": "2"}},
        "lossy_program": {"overrides": {"FRM_NAM": "'cjs.stdaecfull171'"}},
        "bzero": {"overrides": {"BZERO": "32768"}},
        "late": {"overrides": {"DATE_OBS": "'1998-11-05T20:47:04.000'"}},
        "double_flat": {"history": ["tr_dark_sub VERSION:  2.10 Subtracted dark pedestal and current",
                                    "tr_flat_sub VERSION:  1.60 Image divided by corrected flat field",
                                    "tr_flat_sub VERSION:  1.60 Image divided by corrected flat field",
                                    "trace_wave2point  XYOffsets:   0.00  0.00"]},
        "missing_fill": {"history": ["trace_prep  Replaced     9 missing pixels with IMAGE_AVERAGE =   80",
                                     "tr_dark_sub VERSION:  2.10 Subtracted dark pedestal and current",
                                     "tr_flat_sub VERSION:  1.60 Image divided by corrected flat field",
                                     "trace_wave2point  XYOffsets:   0.00  0.00"]},
    }
    for name, kw_ in bad_cases.items():
        blob = fits(base, **kw_)
        h, hist, _ = T.parse_header(blob)
        kw, vh, _ = V.walk_header(blob)
        check(T.regime_problems(h, hist) != [] and V.header_ok(kw, vh) != [],
              f"header case {name} not rejected by both paths")
    # Truncated header and non-zero padding.
    try:
        T.parse_header(header()[:1000])
        check(False, "truncated header accepted")
    except ValueError:
        pass
    blob = bytearray(fits(base))
    blob[-1] = 1
    try:
        T.decode_pixels(bytes(blob), T.HEADER_SIZE)
        check(False, "non-zero padding accepted")
    except ValueError:
        pass
    print("selftest ok")


if __name__ == "__main__":
    main()
