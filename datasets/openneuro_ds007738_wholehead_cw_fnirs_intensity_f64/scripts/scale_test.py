#!/usr/bin/env python3
"""Per-channel "integer-like mantissa times a constant" disclosure test.

Same ratio/LCM test as the accepted dandi_ibl_bwm_spike_amplitudes_f64
recipe. If every value of one channel equals fl(k_i * s) for integers (or
float32 mantissas) k_i below 2**24 and one float64 scale s, each ratio
v_i / v_ref equals k_i / k_ref up to a few float64 ulps; its best rational
approximation with denominator below 2**24 then matches to ~2e-16 and the LCM
of the denominators stays within 24 bits. Generic full-precision float64
values give errors of ~1e-14 and LCMs of hundreds of bits.

The test is evidence for the README width disclosure, not a filter.
"""

from __future__ import annotations

import math
from fractions import Fraction

PROBES = 32
DENOMINATOR_LIMIT = 1 << 24
PASS_BITS = 24
PASS_ERR = 1e-15


def ratio_test(values, probes: int = PROBES) -> tuple[int, float]:
    """Return (bit length of the LCM of ratio denominators, max relative error)."""
    n = len(values)
    if n < 2:
        return 0, 0.0
    reference = values[0]
    step = max(1, (n - 1) // probes)
    lcm = 1
    max_err = 0.0
    taken = 0
    for i in range(1, n, step):
        if taken >= probes:
            break
        mantissa, _ = math.frexp(abs(values[i] / reference))
        normalized = 2.0 * mantissa  # in [1, 2)
        approx = Fraction(normalized).limit_denominator(DENOMINATOR_LIMIT)
        err = abs(approx.numerator / approx.denominator - normalized) / normalized
        max_err = max(max_err, err)
        lcm = lcm * approx.denominator // math.gcd(lcm, approx.denominator)
        taken += 1
    return lcm.bit_length(), max_err


def channel_scale_summary(columns, floor: float) -> dict[str, object]:
    """Run ratio_test on every channel column (values > floor, finite only)."""
    tested = 0
    passing = 0
    bits_seen = []
    for column in columns:
        usable = [v for v in column if v > floor and math.isfinite(v)]
        if len(usable) < 16:
            continue
        bits, err = ratio_test(usable)
        tested += 1
        bits_seen.append(bits)
        if bits <= PASS_BITS and err <= PASS_ERR:
            passing += 1
    bits_seen.sort()
    return {
        "scale_channels_tested": tested,
        "scale_channels_int24_like": passing,
        "scale_lcm_bits_median": bits_seen[len(bits_seen) // 2] if bits_seen else 0,
        "scale_lcm_bits_max": bits_seen[-1] if bits_seen else 0,
    }
