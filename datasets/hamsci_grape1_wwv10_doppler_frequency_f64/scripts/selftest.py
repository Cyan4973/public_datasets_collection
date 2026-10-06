#!/usr/bin/env python3
"""Synthetic self-test: build parser and independent verifier must agree.

Writes synthetic Grape-style station-day files into a temporary directory,
classifies them with both code paths, round-trips the kept ones through
build `process` and verify `check_one`. Run from a scratch directory:
    python3 staging/<id>/scripts/selftest.py
"""
from __future__ import annotations

import gzip
import hashlib
import random
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import grape_wwv10 as build  # noqa: E402
import grape_wwv10_verify as verify  # noqa: E402

NODE = "N00009"
GRID = "FN20ge"


def header(start: str, beacon: str = "WWV10", standard: str = "LB GPSDO", node: str = NODE) -> str:
    lines = [
        f"#,{start},{node},{GRID},40.176, -75.494, 90,Collegeville PA,G1,WWV10",
        "#######################################",
        "# MetaData for Grape Gen 1 Station",
        "#",
        f"# Station Node Number      {node}",
        "# Callsign                 AB1CD",
        f"# Grid Square              {GRID}",
        "# Lat, Long, Elv           40.176, -75.494, 90",
        "# City State               Collegeville PA",
        "# Radio1                   Grape Gen 1 Rcvr 1",
        "# Radio1ID                 G1",
        "# Antenna                  Dipole",
        f"# Frequency Standard       {standard}",
        "# System Info              RasPi3B+",
        "#",
        f"# Beacon Now Decoded       {beacon}",
        "#",
        "#######################################",
        "UTC,Freq,Vpk",
    ]
    return "\n".join(lines) + "\n"


def rows(date: str, start_second: int, count: int, rng: random.Random, constant: bool = False) -> list[tuple[str, str]]:
    out = []
    second = start_second
    for number in range(count):
        hh, rem = divmod(second, 3600)
        mm, ss = divmod(rem, 60)
        milli = 10_000_000_000 if constant else 10_000_000_000 + rng.randint(-2500, 2500)
        out.append((f"{date}T{hh:02d}:{mm:02d}:{ss:02d}Z", f"{milli // 1000}.{milli % 1000:03d}"))
        second += 2 if number % 41 == 7 else 1
        if number == count // 2:
            second += 1800  # a half-hour receiver gap
    return out


def render(start: str, data: list[tuple[str, str]], tail: str = "\r\n", **kwargs) -> str:
    body = "".join(f"{ts}, {freq:>12}, 0.0{abs(hash(ts)) % 90000 + 10000:05d}\r\n" for ts, freq in data)
    if tail != "\r\n":
        body = body[:-2] + tail
    return header(start, **kwargs) + body


def main() -> None:
    rng = random.Random(20261006)
    date = "2020-07-21"
    start = f"{date}T00:00:00Z"
    good = rows(date, 0, 5000, rng)
    cases: dict[str, tuple[str, str, str]] = {}

    def add(name: str, text: str, expected: str, file_start: str = start) -> None:
        cases[name] = (text, expected, file_start)

    add("good", render(start, good), "keep")
    add("good_truncated_tail", render(start, good) + f"{date}T23:00:00Z,  99999", "keep")
    add("good_tail_no_newline", render(start, good, tail=""), "keep")
    add("short", render(start, good[:100]), "exclude:too_short")
    bad = list(good)
    bad[2000] = (bad[2000][0], "nan")
    add("malformed", render(start, bad), "exclude:malformed_row")
    dup = list(good)
    dup[3000] = (dup[2999][0], dup[3000][1])  # repeated second: allowed
    add("duplicate_time", render(start, dup), "keep")
    back = list(good)
    back[3000] = (back[2000][0], back[3000][1])  # clock reset: backward step
    add("backward_time", render(start, back), "exclude:time_order")
    off = list(good)
    off[-1] = ("2020-07-22T00:00:01Z", off[-1][1])
    add("off_date", render(start, off), "exclude:time_order")
    late = f"{date}T00:00:01Z"
    add("first_row_before_name_time", render(late, good), "keep", late)
    oob = list(good)
    oob[10] = (oob[10][0], "10000370.308")
    add("out_of_band", render(start, oob), "exclude:out_of_band")
    near = list(good)
    near[10] = (near[10][0], "10000050.000")
    add("near_band", render(start, near), "keep")
    add("constant", render(start, rows(date, 0, 4000, rng, constant=True)), "exclude:constant")
    add("not_gpsdo", render(start, good, standard="TCXO"), "exclude:reference_not_gpsdo")
    add("wrong_beacon_header", render(start, good, beacon="WWV5"), "exclude:header_mismatch")
    add("short_and_malformed", render(start, bad[1990:2100]), "exclude:malformed_row+too_short")
    shifted = [(ts, "%.3f" % (float(freq) - 5_000_000)) for ts, freq in good]  # 5 MHz data labelled WWV10
    add("other_carrier", render(start, shifted), "exclude:out_of_band")

    with tempfile.TemporaryDirectory(prefix="grape_selftest_") as temp:
        root = Path(temp)
        downloads = root / "downloads"
        downloads.mkdir()
        for order, (name, (text, expected, file_start)) in enumerate(sorted(cases.items())):
            stamp = file_start[11:19].replace(":", "")
            key = f"{date}T{stamp}Z_{NODE}_G1_{GRID}_FRQ_WWV10.csv.gz"
            # Distinct file names per case: put each case in its own folder.
            case_dir = downloads / name
            case_dir.mkdir()
            blob = gzip.compress(text.encode("ascii"))
            (case_dir / key).write_bytes(blob)
            source = {
                "sample_order": str(order),
                "key": key,
                "node": NODE,
                "receiver": "G1",
                "grid": GRID,
                "beacon": "WWV10",
                "file_start_utc": file_start,
                "size_bytes": str(len(blob)),
                "md5": hashlib.md5(blob).hexdigest(),
                "url": "synthetic",
                "expected_status": expected,
            }
            meta = build.process((source, str(case_dir), str(root / name)))
            status_v, tokens, facts = verify.rederive(verify.gunzip_members(blob), source)
            assert meta["status"] == expected, (name, meta["status"], expected)
            assert status_v == expected, (name, status_v, expected)
            if expected == "keep":
                index_row = {
                    "sample_path": meta["sample_path"],
                    "sha256": meta["sha256"],
                    "min": meta["min"],
                    "max": meta["max"],
                    "value_count": meta["rows"],
                    "sample_size_bytes": meta["sample_size_bytes"],
                    "distinct_values": meta["distinct_values"],
                    "truncated_tail_dropped": meta["truncated_tail_dropped"],
                }
                index_row.update({field: meta[field] for field in verify.GAP_FIELDS})
                result = verify.check_one((source, index_row, str(case_dir), str(root / name)))
                assert result["status"] == "keep" and result["values"] == meta["rows"], (name, result)
                whole_hz = sum(1 for token in tokens if token.endswith(b".000"))
                assert result["beyond_f32"] == meta["rows"] - whole_hz, (name, "float32 would lose mHz")
                assert meta["steps_0s"] == (1 if name == "duplicate_time" else 0), (name, meta["steps_0s"])
                assert meta["values_beyond_10hz"] == (1 if name == "near_band" else 0), name
                index_row["steps_2s"] += 1
                try:
                    verify.check_one((source, index_row, str(case_dir), str(root / name)))
                except RuntimeError:
                    index_row["steps_2s"] -= 1
                else:
                    raise AssertionError(f"{name}: wrong gap bookkeeping passed verification")
                assert meta["missing_seconds"] > 1800, (name, meta["missing_seconds"])
                expected_tail = 1 if name == "good_truncated_tail" else 0
                assert meta["truncated_tail_dropped"] == expected_tail == facts["truncated_tail"], name
                assert meta["rows"] == 5000, (name, meta["rows"])
                # Corrupt one stored double: verify must notice.
                sample = root / name / meta["sample_path"]
                raw = bytearray(sample.read_bytes())
                raw[8] ^= 0x01
                sample.write_bytes(bytes(raw))
                try:
                    verify.check_one((source, index_row, str(case_dir), str(root / name)))
                except RuntimeError:
                    pass
                else:
                    raise AssertionError(f"{name}: corrupted sample passed verification")
            print(f"ok {name}: {expected}")
    print(f"selftest=ok cases={len(cases)}")


if __name__ == "__main__":
    main()
