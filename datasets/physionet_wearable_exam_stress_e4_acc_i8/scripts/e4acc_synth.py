"""Synthetic Empatica E4 ACC.csv inputs for parser self-tests.

`good()` returns (csv_bytes, expected_int8_bytes, start_time_text). `bad()`
yields (label, csv_bytes) variants that every parser must reject.
"""
from __future__ import annotations

import random
import struct

START = "1544027337.000000"


def _rows(count: int, seed: int = 7) -> list[tuple[int, int, int]]:
    rng = random.Random(seed)
    rows = [(-128, 127, 0), (127, -128, -1), (0, 0, 0)]
    x, y, z = -3, 65, 6
    while len(rows) < count:
        if rng.random() < 0.3:  # static stretch
            rows.extend([(x, y, z)] * rng.randint(1, 40))
            continue
        x = max(-128, min(127, x + rng.randint(-9, 9)))
        y = max(-128, min(127, y + rng.randint(-9, 9)))
        z = max(-128, min(127, z + rng.randint(-9, 9)))
        rows.append((x, y, z))
    return rows[:count]


def render(rows, start=START, rate="32.000000", trailing_newline=True) -> bytes:
    lines = [f"{start}, {start}, {start}", f"{rate}, {rate}, {rate}"]
    lines += [",".join(str(v) for v in row) for row in rows]
    text = "\n".join(lines) + ("\n" if trailing_newline else "")
    return text.encode("ascii")


def good(count: int = 5000, trailing_newline: bool = True):
    rows = _rows(count)
    expected = b"".join(struct.pack("<bbb", *row) for row in rows)
    return render(rows, trailing_newline=trailing_newline), expected, START


def bad():
    rows = _rows(2000)
    base = render(rows)
    lines = base.split(b"\n")

    def with_line(i: int, text: bytes) -> bytes:
        copy = list(lines)
        copy[i] = text
        return b"\n".join(copy)

    yield "rate_64", render(rows, rate="64.000000")
    yield "unequal_start", with_line(0, f"{START}, {START}, 1544027338.000000".encode())
    yield "header_two_columns", with_line(0, f"{START}, {START}".encode())
    yield "four_columns", with_line(50, b"1,2,3,4")
    yield "two_columns", with_line(51, b"1,2")
    yield "out_of_range_pos", with_line(52, b"128,0,0")
    yield "out_of_range_neg", with_line(53, b"0,-129,0")
    yield "float_value", with_line(54, b"1.0,2,3")
    yield "blank_middle", with_line(55, b"")
    yield "spaces", with_line(56, b"1, 2,3")
    yield "plus_sign", with_line(57, b"+1,2,3")
    yield "crlf", base.replace(b"\n", b"\r\n")
    yield "header_only", render([])
    yield "double_trailing_newline", base + b"\n"
