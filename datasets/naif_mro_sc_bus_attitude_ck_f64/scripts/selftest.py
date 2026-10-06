#!/usr/bin/env python3
"""Synthetic self-test for ck_type3.py (no network, no local data needed).

Builds big-endian CK type-3 segments with known contents for several
(N, NINTS) shapes, including directory-size edge cases, and checks that the
splitter returns bit-exact little-endian quaternion/rate/epoch blocks. Also
checks that malformed segments, file records and summaries are rejected.
"""
from __future__ import annotations

import math
from pathlib import Path
import random
import struct
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ck_type3 as ck  # noqa: E402


def unit_quaternion(rng: random.Random) -> list[float]:
    while True:
        q = [rng.uniform(-1, 1) for _ in range(4)]
        norm = math.sqrt(sum(c * c for c in q))
        if norm > 0.1:
            # Round to 8 decimals like the MRO telemetry quaternions.
            return [round(c / norm, 8) for c in q]


def build_segment(n: int, interval_records: list[int], rng: random.Random):
    records = []
    for _ in range(n):
        records.append(unit_quaternion(rng) + [rng.uniform(-1e-3, 1e-3) for _ in range(3)])
    epochs = []
    tick = float(rng.randrange(10**11, 4 * 10**11))
    for _ in range(n):
        tick += rng.randrange(20, 80)
        epochs.append(tick)
    epoch_dir = [epochs[100 * (j + 1) - 1] for j in range((n - 1) // 100)]
    starts = [epochs[i] for i in interval_records]
    nints = len(starts)
    int_dir = [starts[100 * (j + 1) - 1] for j in range((nints - 1) // 100)]
    words = [w for rec in records for w in rec] + epochs + epoch_dir + starts + int_dir + [float(nints), float(n)]
    assert len(words) == ck.type3_expected_length(n, nints)
    raw = struct.pack(f">{len(words)}d", *words)
    return raw, records, epochs


def expect_error(func, *args, **kwargs) -> None:
    try:
        func(*args, **kwargs)
    except ck.CKError:
        return
    raise AssertionError(f"expected CKError from {func.__name__}")


def test_shapes() -> None:
    rng = random.Random(20261005)
    shapes = [
        (1, [0]),
        (100, [0]),
        (101, [0, 50]),
        (250, [0, 100, 201]),
        (1000, [0] + list(range(5, 1000, 5))),  # 200 interval starts -> 1 interval directory entry
        (2345, [0, 7, 1500]),
    ]
    for n, interval_records in shapes:
        raw, records, epochs = build_segment(n, interval_records, rng)
        summary = {"sclk_begin": epochs[0], "sclk_end": epochs[-1]}
        result = ck.split_type3(raw, ">", summary, label=f"synthetic N={n}")
        assert result["n"] == n and result["nints"] == len(interval_records)
        q_expected = struct.pack(f"<{4 * n}d", *[c for rec in records for c in rec[:4]])
        r_expected = struct.pack(f"<{3 * n}d", *[c for rec in records for c in rec[4:]])
        e_expected = struct.pack(f"<{n}d", *epochs)
        assert result["quaternion_le"] == q_expected, f"quaternion mismatch N={n}"
        assert result["rate_le"] == r_expected, f"rate mismatch N={n}"
        assert result["epoch_le"] == e_expected, f"epoch mismatch N={n}"
        # Little-endian input must decode identically.
        words = struct.unpack(f">{len(raw) // 8}d", raw)
        raw_le = struct.pack(f"<{len(words)}d", *words)
        assert ck.split_type3(raw_le, "<", summary)["quaternion_le"] == q_expected
    print(f"selftest: {len(shapes)} synthetic type-3 shapes decoded bit-exactly")


def test_rejections() -> None:
    rng = random.Random(7)
    raw, records, epochs = build_segment(250, [0, 100, 201], rng)
    words = list(struct.unpack(f">{len(raw) // 8}d", raw))
    n = 250

    def pack(ws):
        return struct.pack(f">{len(ws)}d", *ws)

    expect_error(ck.split_type3, raw[:-8], ">")  # truncated -> wrong length/trailer
    bad = words[:]
    bad[-1] = 251.0  # N disagrees with length
    expect_error(ck.split_type3, pack(bad), ">")
    bad = words[:]
    bad[7 * n + 10] = bad[7 * n + 9]  # repeated epoch
    expect_error(ck.split_type3, pack(bad), ">")
    bad = words[:]
    bad[8 * n] += 1.0  # epoch directory mismatch
    expect_error(ck.split_type3, pack(bad), ">")
    bad = words[:]
    bad[8 * n + 2] = bad[7 * n] + 0.5  # first interval start not an epoch
    expect_error(ck.split_type3, pack(bad), ">")
    bad = words[:]
    bad[0] = 2.0  # quaternion norm far from 1
    expect_error(ck.split_type3, pack(bad), ">")
    bad = words[:]
    bad[5] = float("nan")
    expect_error(ck.split_type3, pack(bad), ">")
    expect_error(ck.split_type3, raw, ">", {"sclk_begin": epochs[0] + 1, "sclk_end": epochs[-1]})
    print("selftest: malformed segments rejected")


def test_records() -> None:
    record = bytearray(1024)
    record[0:8] = b"DAF/CK  "
    struct.pack_into(">ii", record, 8, 2, 6)
    record[16:76] = b"MRO TLM-Based SC Bus CK File by NAIF/JPL".ljust(60)
    struct.pack_into(">iii", record, 76, 16, 40, 801003)
    record[88:96] = b"BIG-IEEE"
    record[699:727] = b"FTPSTR:\r:\n:\r\n:\r\x00:\x81:\x10\xce:ENDFTP"
    header = ck.parse_file_record(bytes(record))
    assert header["fward"] == 16 and header["endian"] == ">"
    bad = bytearray(record)
    bad[0:8] = b"DAF/SPK "
    expect_error(ck.parse_file_record, bytes(bad))
    bad = bytearray(record)
    bad[88:96] = b"VAX-GFLT"
    expect_error(ck.parse_file_record, bytes(bad))
    bad = bytearray(record)
    struct.pack_into(">ii", bad, 8, 2, 5)
    expect_error(ck.parse_file_record, bytes(bad))

    summary_record = bytearray(1024)
    struct.pack_into(">ddd", summary_record, 0, 40.0, 0.0, 2.0)
    for index, (start, end) in enumerate([(2049, 803050), (803051, 1604052)]):
        offset = 24 + index * 40
        struct.pack_into(">dd", summary_record, offset, 1.0e11 + index, 1.0e11 + index + 0.5)
        struct.pack_into(">6i", summary_record, offset + 16, -74000, -74900, 3, 1, start, end)
    parsed = ck.parse_summary_record(bytes(summary_record), ">", 16)
    assert parsed["next"] == 40 and parsed["nsum"] == 2
    assert parsed["summaries"][1]["start_word"] == 803051
    for item in parsed["summaries"]:
        ck.check_summary_identity(item, "synthetic")
    wrong = dict(parsed["summaries"][0], frame=1)
    expect_error(ck.check_summary_identity, wrong, "synthetic")
    wrong = dict(parsed["summaries"][0], av_flag=0)
    expect_error(ck.check_summary_identity, wrong, "synthetic")
    struct.pack_into(">d", summary_record, 16, 26.0)
    expect_error(ck.parse_summary_record, bytes(summary_record), ">", 16)
    print("selftest: DAF file record and summary parsing checked")


def main() -> int:
    test_shapes()
    test_rejections()
    test_records()
    print("selftest: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
