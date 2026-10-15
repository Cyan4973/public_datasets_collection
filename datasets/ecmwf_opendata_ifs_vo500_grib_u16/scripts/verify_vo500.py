#!/usr/bin/env python3
"""Independent verifier for ecmwf_opendata_ifs_vo500_grib_u16.

Does not import the build parser. Re-walks each source GRIB2 message with its
own section scanner, re-derives the little-endian uint16 codes by byte-lane
swapping section 7, and compares them byte-for-byte with the emitted sample.
Also checks index fields, R/E/D metadata, manifest totals, the scope (every
calendar day of the window is either present or logged missing), duplicates,
and degeneracy (constant fields, few distinct codes, dominant value, codes that
never reach the upper byte).

Usage: verify_vo500.py <data_root> <manifest.toml>
"""
from __future__ import annotations

import collections
import datetime as dt
import hashlib
import json
import math
import struct
import sys
import tomllib
from pathlib import Path

DATASET_ID = "ecmwf_opendata_ifs_vo500_grib_u16"
SERIES_ID = "vo500_packed_codes_u16"
NPTS = 405900
MSG_LEN = 811996
WINDOW = (dt.date(2023, 1, 18), dt.date(2023, 6, 27))
MIN_DAYS = 150


def fail(msg: str) -> None:
    print(f"VERIFY FAIL: {msg}", file=sys.stderr)
    sys.exit(1)


def sections_of(buf: bytes) -> dict[int, tuple[int, int]]:
    """Return {section_number: (start, length)} for a single-field GRIB2 message."""
    if buf[:4] != b"GRIB" or buf[7] != 2 or int.from_bytes(buf[8:16], "big") != len(buf):
        fail("bad GRIB2 indicator section")
    out: dict[int, tuple[int, int]] = {}
    pos = 16
    while buf[pos:pos + 4] != b"7777":
        length = int.from_bytes(buf[pos:pos + 4], "big")
        num = buf[pos + 4]
        if num in out or length < 5:
            fail(f"bad or repeated section {num}")
        out[num] = (pos, length)
        pos += length
        if pos > len(buf) - 4:
            fail("section overrun")
    if pos != len(buf) - 4:
        fail("trailing bytes after 7777")
    return out


def signmag(raw: int, bits: int) -> int:
    top = 1 << (bits - 1)
    return -(raw - top) if raw & top else raw


def main() -> None:
    data_root = Path(sys.argv[1])
    manifest = tomllib.loads(Path(sys.argv[2]).read_text())
    if manifest["dataset_id"] != DATASET_ID:
        fail("manifest dataset_id mismatch")
    series = [s for s in manifest["series"] if s["id"] == SERIES_ID]
    if len(series) != 1 or len(manifest["series"]) != 1:
        fail("manifest must declare exactly the one primary series")
    series = series[0]

    dl = data_root / "downloads" / DATASET_ID
    plan = {}
    for line in (dl / "messages.tsv").read_text().splitlines()[1:]:
        date, offset, length, sha, url = line.split("\t")
        plan[date] = (int(offset), int(length), sha, url)
    missing = {}
    for line in (dl / "missing_days.tsv").read_text().splitlines()[1:]:
        date, reason = line.split("\t")
        missing[date] = reason

    # Scope: every calendar day in the window is present or explicitly logged missing.
    day = WINDOW[0]
    calendar = []
    while day <= WINDOW[1]:
        calendar.append(day.strftime("%Y%m%d"))
        day += dt.timedelta(days=1)
    if set(plan) & set(missing):
        fail("a day is both present and missing")
    if set(plan) | set(missing) != set(calendar):
        fail(f"window not fully accounted: extra={sorted(set(plan) | set(missing) - set(calendar))} "
             f"unaccounted={sorted(set(calendar) - set(plan) - set(missing))}")
    if len(plan) < MIN_DAYS:
        fail(f"only {len(plan)} days present")

    rows = [json.loads(l) for l in (data_root / "index" / DATASET_ID / "samples.jsonl").read_text().splitlines() if l]
    if [r["run_date"] for r in rows] != sorted(plan):
        fail("index run dates do not match the downloaded message set")

    sample_dir = data_root / "samples" / DATASET_ID / SERIES_ID
    on_disk = sorted(p.name for p in sample_dir.iterdir())
    if on_disk != [f"{d}.bin" for d in sorted(plan)]:
        fail("sample directory contents differ from the index")

    seen = set()
    total_bytes = 0
    e_values = collections.Counter()
    cmax_all = []
    for row in rows:
        date = row["run_date"]
        offset, length, sha, url = plan[date]
        expect = {
            "dataset_id": DATASET_ID, "series_id": SERIES_ID,
            "sample_path": f"samples/{DATASET_ID}/{SERIES_ID}/{date}.bin",
            "numeric_kind": "uint", "bit_width": 16, "endianness": "little",
            "element_size_bytes": 2, "sample_size_bytes": 2 * NPTS, "value_count": NPTS,
            "source_message_sha256": sha, "source_byte_offset": offset, "source_byte_length": length,
        }
        for k, v in expect.items():
            if row.get(k) != v:
                fail(f"{date}: index {k}={row.get(k)!r} expected {v!r}")

        src = (dl / "grib" / f"{date}.grib2").read_bytes()
        if len(src) != MSG_LEN or length != MSG_LEN or hashlib.sha256(src).hexdigest() != sha:
            fail(f"{date}: source message size/hash mismatch")
        sec = sections_of(src)
        s1 = src[sec[1][0]:sec[1][0] + sec[1][1]]
        if f"{int.from_bytes(s1[12:14], 'big'):04d}{s1[14]:02d}{s1[15]:02d}" != date or s1[16] != 0:
            fail(f"{date}: section 1 reference time mismatch")
        s4 = src[sec[4][0]:sec[4][0] + sec[4][1]]
        if (s4[9], s4[10], s4[17], int.from_bytes(s4[18:22], "big"), s4[22], int.from_bytes(s4[24:28], "big")) \
                != (2, 12, 1, 24, 100, 50000):
            fail(f"{date}: section 4 is not vo / 24 h / 500 hPa")
        s5 = src[sec[5][0]:sec[5][0] + sec[5][1]]
        if int.from_bytes(s5[5:9], "big") != NPTS or int.from_bytes(s5[9:11], "big") != 0 or s5[19] != 16:
            fail(f"{date}: section 5 is not template 0 / 16 bits / {NPTS} points")
        s6 = src[sec[6][0]:sec[6][0] + sec[6][1]]
        if s6[5] != 255:
            fail(f"{date}: bitmap present")
        R = struct.unpack(">f", s5[11:15])[0]
        E = signmag(int.from_bytes(s5[15:17], "big"), 16)
        D = signmag(int.from_bytes(s5[17:19], "big"), 16)
        if (row["grib_reference_value_R"], row["grib_binary_scale_E"], row["grib_decimal_scale_D"]) != (R, E, D):
            fail(f"{date}: R/E/D metadata mismatch")
        start7, len7 = sec[7]
        if len7 != 5 + 2 * NPTS:
            fail(f"{date}: section 7 length {len7}")
        be = src[start7 + 5:start7 + len7]

        sample = (data_root / row["sample_path"]).read_bytes()
        if len(sample) != 2 * NPTS:
            fail(f"{date}: sample size {len(sample)}")
        if sample[0::2] != be[1::2] or sample[1::2] != be[0::2]:
            fail(f"{date}: sample is not the byte-swapped section 7 payload")
        digest = hashlib.sha256(sample).hexdigest()
        if digest != row["sample_sha256"] or digest in seen:
            fail(f"{date}: sample hash mismatch or duplicate sample")
        seen.add(digest)

        codes = struct.unpack(f"<{NPTS}H", sample)
        counts = collections.Counter(codes)
        cmin, cmax = min(codes), max(codes)
        top_share = counts.most_common(1)[0][1] / NPTS
        if (row["code_min"], row["code_max"], row["distinct_codes"]) != (cmin, cmax, len(counts)):
            fail(f"{date}: code statistics mismatch")
        if cmax == cmin or len(counts) < 1000:
            fail(f"{date}: degenerate field ({len(counts)} distinct codes)")
        if cmax < 256:
            fail(f"{date}: codes never reach the upper byte (max {cmax})")
        if top_share > 0.5:
            fail(f"{date}: one code covers {top_share:.1%} of the field")
        vmin = (R + cmin * 2.0 ** E) / 10.0 ** D
        vmax = (R + cmax * 2.0 ** E) / 10.0 ** D
        if not (math.isclose(row["vo_min_s-1"], vmin, rel_tol=0, abs_tol=1e-15)
                and math.isclose(row["vo_max_s-1"], vmax, rel_tol=0, abs_tol=1e-15)):
            fail(f"{date}: physical range metadata mismatch")
        if not (-0.01 < vmin < 0 < vmax < 0.01):
            fail(f"{date}: implausible 500 hPa vorticity range {vmin}..{vmax} s-1")
        e_values[E] += 1
        cmax_all.append(cmax)
        total_bytes += len(sample)

    if series["sample_count"] != len(rows):
        fail(f"manifest sample_count {series['sample_count']} != realized {len(rows)}")
    if series["total_size_bytes"] != total_bytes:
        fail(f"manifest total_size_bytes {series['total_size_bytes']} != realized {total_bytes}")
    print(f"verified samples={len(rows)} bytes={total_bytes} missing_days={sorted(missing)} "
          f"E_counts={dict(sorted(e_values.items()))} code_max_range={min(cmax_all)}..{max(cmax_all)}")


if __name__ == "__main__":
    main()
