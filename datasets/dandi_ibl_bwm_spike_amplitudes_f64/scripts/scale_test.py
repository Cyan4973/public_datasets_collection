#!/usr/bin/env python3
"""Per-unit "float32 times a constant" disclosure test (ratio/LCM test).

If every value of a unit equals fl(x_i * s) for float32 values x_i and one
float64 scale s, then each ratio v_i / v_ref equals x_i / x_ref up to a few
float64 ulps. After removing the power of two, x_i / x_ref is a ratio of two
24-bit integer mantissas, so its best rational approximation with denominator
below 2**24 matches to ~1e-16 and all denominators divide the reference
mantissa: their LCM stays within 24 bits. For generic float64 values the
approximation error is ~1e-15 and the LCM grows by ~24 bits per probe.

The test is evidence for the README width disclosure, not a filter: build and
verify record its result for every kept unit.
"""

from __future__ import annotations

import math
from fractions import Fraction

PROBES = 64
DENOMINATOR_LIMIT = 1 << 24


def float32_scale_test(values, probes: int = PROBES) -> tuple[int, float]:
    """Return (bit length of the LCM of ratio denominators, max relative error)."""
    n = len(values)
    reference = next((v for v in values if v != 0.0 and math.isfinite(v)), None)
    if reference is None or n < 2:
        return 0, 0.0
    step = max(1, (n - 1) // probes)
    lcm = 1
    max_err = 0.0
    taken = 0
    for i in range(1, n, step):
        if taken >= probes:
            break
        value = values[i]
        if value == 0.0:
            continue
        mantissa, _ = math.frexp(abs(value / reference))
        normalized = 2.0 * mantissa  # in [1, 2)
        approx = Fraction(normalized).limit_denominator(DENOMINATOR_LIMIT)
        err = abs(approx.numerator / approx.denominator - normalized) / normalized
        max_err = max(max_err, err)
        lcm = lcm * approx.denominator // math.gcd(lcm, approx.denominator)
        taken += 1
    return lcm.bit_length(), max_err
