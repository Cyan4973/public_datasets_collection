"""Synthetic WFDB format-80 multi-signal segment for decoder self-tests.

Shared by build and verify self-tests. It writes a header and an interleaved
.dat whose ABP column has known content: a smooth pulsatile window, a flat
window, an invalid-dominated window, a low window and a partial final
window, with -128 (WFDB invalid) codes and rail codes. Expected per-signal
checksums and the exact ABP int8 sequence are computed here with plain
integer arithmetic, independent of either decoder.
"""
from __future__ import annotations

import math
from pathlib import Path

SYNTH_SEGMENT = "3999999_0001"
SYNTH_NSIG = 4
SYNTH_ABP_INDEX = 2
SYNTH_NAMES = ("II", "V", "ABP", "PLETH")


def synth_abp(window: int) -> list[int]:
    vals: list[int] = []
    # window 1: pulsatile arterial-like wave, about 120/70 mmHg -> codes 50..-12
    for i in range(window):
        phase = (i % 100) / 100.0
        mmhg = 85 + 30 * math.sin(2 * math.pi * phase) + 8 * math.sin(4 * math.pi * phase)
        vals.append(max(-127, min(127, round(1.25 * mmhg - 100))))
    vals[17] = -128  # isolated invalid sample
    vals[window - 1] = 127  # rail
    # window 2: flat at 60 mmHg (code -25) with a 1-code wobble
    vals += [-25 if (i // 7) % 2 else -24 for i in range(window)]
    # window 3: mostly invalid
    vals += [-128 if i % 5 else 10 for i in range(window)]
    # window 4: low (about 5 mmHg, code -94) with small noise
    vals += [-94 + ((i * 7) % 5) - 2 for i in range(window)]
    # window 5: partial, pulsatile again, includes -127 rail
    part = window // 3
    for i in range(part):
        vals.append(-127 if i == 3 else round(1.25 * (90 + 25 * math.sin(2 * math.pi * i / 90)) - 100))
    return vals


def write_synth(directory: Path, window: int) -> dict:
    """Write <seg>.hea and <seg>.dat; return the expected facts."""
    directory.mkdir(parents=True, exist_ok=True)
    abp = synth_abp(window)
    n = len(abp)
    cols = []
    for s in range(SYNTH_NSIG):
        if s == SYNTH_ABP_INDEX:
            cols.append(abp)
        else:
            cols.append([((i * (31 + 17 * s)) % 251) - 125 for i in range(n)])
    raw = bytearray()
    for i in range(n):
        for s in range(SYNTH_NSIG):
            raw.append(cols[s][i] + 128)
    (directory / f"{SYNTH_SEGMENT}.dat").write_bytes(bytes(raw))
    lines = [f"{SYNTH_SEGMENT} {SYNTH_NSIG} 125 {n} 12:00:00.000"]
    gains = ["29/mV", "14/mV", "1.25(-100)/mmHg", "255(-128)/NU"]
    for s in range(SYNTH_NSIG):
        csum = sum(cols[s]) & 0xFFFF
        if csum >= 0x8000:
            csum -= 0x10000
        lines.append(
            f"{SYNTH_SEGMENT}.dat 80 {gains[s]} 8 0 {cols[s][0]} {csum} 0 {SYNTH_NAMES[s]}"
        )
    (directory / f"{SYNTH_SEGMENT}.hea").write_text("\n".join(lines) + "\n")
    checks = []
    for s in range(SYNTH_NSIG):
        c = sum(cols[s]) & 0xFFFF
        checks.append(c - 0x10000 if c >= 0x8000 else c)
    return {
        "segment": SYNTH_SEGMENT,
        "nsig": SYNTH_NSIG,
        "abp_index": SYNTH_ABP_INDEX,
        "frames": n,
        "abp": abp,
        "checksums": checks,
        "invalid_count": sum(1 for v in abp if v == -128),
        # expected window classes in order
        "window_classes": ["pulsatile", "flat", "invalid", "low", "pulsatile"],
    }
