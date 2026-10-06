"""Synthetic 3-signal WFDB format-16 records for the build/verify self-tests.

The generator packs frames with struct ('<hhh'), a different code path from
both decoders, and computes expected diagnostics by brute force.
"""
from __future__ import annotations

import math
import struct

SIGNALS = ("ABP", "ECG", "ICP")


def signed16(total: int) -> int:
    return ((total + 32768) & 0xFFFF) - 32768


def make_record(
    record_id: str = "synth1",
    frames: int = 10321,
    gain_text: str = "40.0",
    baseline: int = -100,
    window: int = 3000,
) -> dict:
    """Four diagnostic regimes in successive windows: ICP waveform, high, ICP-band noise, flat.

    The noise window is a deterministic LCG with +/-30 codes around a constant
    level (60 codes peak-to-peak = 1.5 mmHg at the default gain of 40 codes/mmHg).
    """
    gain = float(gain_text)
    state = 12345

    def rand() -> int:
        nonlocal state
        state = (1103515245 * state + 12345) & 0x7FFFFFFF
        return state >> 8

    abp, ecg, icp = [], [], []
    for index in range(frames):
        abp.append(rand() % 20000 - 10000)
        ecg.append(rand() % 2000 - 1000)
        noise = rand()
        if index < window:
            value = baseline + int(gain * 15) + round(200 * math.sin(2 * math.pi * index / 50)) + noise % 5 - 2
        elif index < 2 * window:
            value = baseline + int(gain * 120) + noise % 8000 - 4000
        elif index < 3 * window:
            value = baseline + int(gain * 25) + noise % 61 - 30
        else:
            value = baseline + int(gain * 5) + noise % 3
        icp.append(value)
    icp[window + 1000] = -32768
    icp[window + 1001] = 32767
    icp[2 * window - 1] = -32767  # wrap straddling a window (and chunk) boundary
    icp[2 * window] = 32767
    channels = (abp, ecg, icp)
    gains = ("80.0(0)/mmHg", "6081.5(-398)/mV", f"{gain_text}({baseline})/mmHg")
    lines = [f"{record_id} 3 50 {frames}"]
    for index, name in enumerate(SIGNALS):
        checksum = signed16(sum(channels[index]))
        lines.append(f"{record_id}.dat 16 {gains[index]} 0 0 0 {checksum} 0 {name}")
    lines.append("# <age>: 99  <sex>: X  <diagnoses>: (SYNTH)  <outcome>: none")
    header = "\n".join(lines)  # no trailing newline, like several CHARIS headers
    data = b"".join(struct.pack("<hhh", a, e, i) for a, e, i in zip(abp, ecg, icp))

    low_code = baseline + (-10.0) * gain
    high_code = baseline + 100.0 * gain
    classes = dict.fromkeys(
        ("plausible_icp", "icp_range_noise", "flat_icp_range", "negative", "high_pulsatile", "high_flat",
         "high_other", "very_high"), 0
    )
    for start in range(0, frames, window):
        raw = icp[start:start + window]
        part = sorted(raw)
        to_mmhg = [(v - baseline) / gain for v in part]
        median = to_mmhg[len(part) // 2]
        spread = to_mmhg[len(part) * 19 // 20] - to_mmhg[len(part) // 20]
        peak = to_mmhg[-1] - to_mmhg[0]
        if median < -10:
            classes["negative"] += 1
        elif median <= 50:
            if peak < 1:
                classes["flat_icp_range"] += 1
            else:
                count, mean = len(raw), sum(raw) / len(raw)
                centred = [v - mean for v in raw]
                lag = sum(centred[k] * centred[k + 1] for k in range(count - 1))
                energy = sum(c * c for c in centred)
                classes["plausible_icp" if lag / energy >= 0.5 else "icp_range_noise"] += 1
        elif median > 250:
            classes["very_high"] += 1
        elif spread >= 20:
            classes["high_pulsatile"] += 1
        elif spread < 2:
            classes["high_flat"] += 1
        else:
            classes["high_other"] += 1
    expected = {
        "values_below_minus10_mmhg": sum(1 for v in icp if v < low_code),
        "values_above_100_mmhg": sum(1 for v in icp if v > high_code),
        "windows_60s": -(-frames // window),
        "minimum": min(icp),
        "maximum": max(icp),
        "distinct_values": len(set(icp)),
        "invalid_sample_count": icp.count(-32768),
        "positive_rail_count": icp.count(32767),
        "negative_rail_count": icp.count(-32767),
        "wrap_like_jumps": sum(1 for a, b in zip(icp, icp[1:]) if abs(a - b) > 32768),
        "stretch_vs_native": round(gain / 60.8182, 4),
    }
    present = set(icp)
    band = range(baseline, math.floor(baseline + 40.0 * gain) + 1)
    expected["unused_code_fraction_0_40mmhg"] = round(sum(1 for code in band if code not in present) / len(band), 3)
    expected.update({f"windows_{name}": count for name, count in classes.items()})
    if min(classes["plausible_icp"], classes["icp_range_noise"], classes["high_pulsatile"], classes["flat_icp_range"],
           expected["wrap_like_jumps"]) < 1:
        raise SystemExit("synthetic generator no longer produces the intended regimes")
    return {
        "header": header,
        "data": data,
        "icp_bytes": struct.pack(f"<{frames}h", *icp),
        "expected": expected,
        "frames": frames,
    }
