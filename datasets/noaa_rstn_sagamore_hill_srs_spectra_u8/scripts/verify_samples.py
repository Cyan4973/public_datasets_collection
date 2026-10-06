#!/usr/bin/env python3
"""Independent verifier for noaa_rstn_sagamore_hill_srs_spectra_u8.

Does not import scripts/srs.py. Re-decodes each pinned day file with a
streaming zlib decoder, unpacks every 826-byte SRS record with one struct
format, re-derives the band A / band B uint8 planes and the uint32 sweep-time
series, and compares them byte for byte with the built samples. Also checks
index fields, manifest totals and per-sample degeneracy.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import json
import struct
import sys
import tomllib
import zlib
from pathlib import Path

DATASET_ID = "noaa_rstn_sagamore_hill_srs_spectra_u8"
REC = struct.Struct(">8B3H2B3H2B401s401s")
assert REC.size == 826
SERIES_A = "srs_band_a_25_75mhz_u8"
SERIES_B = "srs_band_b_75_180mhz_u8"
SERIES_T = "srs_sweep_start_utc_seconds_u32"
INDEX_KEYS = ["dataset_id", "series_id", "sample_path", "numeric_kind", "bit_width", "endianness",
              "element_size_bytes", "sample_size_bytes", "value_count"]
MIN_RECORDS = 5000
# Degeneracy thresholds per band sample.
MIN_DISTINCT = 64
MAX_MODE_FRACTION = 0.25
MAX_EXTREME_FRACTION = 0.01      # codes 0 and 255 together
MIN_VARYING_CHANNEL_FRACTION = 0.99
MAX_FLAT_SWEEP_FRACTION = 0.001
MAX_REPEAT_SWEEP_FRACTION = 0.02

errors: list[str] = []


def fail(msg: str) -> None:
    errors.append(msg)
    print(f"ERROR: {msg}")


def stream_gunzip(path: Path, size: int, sha: str) -> tuple[bytes, str]:
    h = hashlib.sha256()
    dec = zlib.decompressobj(16 + zlib.MAX_WBITS)
    out = []
    n = 0
    with path.open("rb") as fh:
        while True:
            chunk = fh.read(1 << 20)
            if not chunk:
                break
            n += len(chunk)
            h.update(chunk)
            out.append(dec.decompress(chunk))
    out.append(dec.flush())
    if not dec.eof or dec.unused_data:
        raise ValueError(f"{path.name}: gzip stream truncated or multi-member")
    digest = h.hexdigest()
    if n != size:
        raise ValueError(f"{path.name}: {n} bytes != pinned {size}")
    if sha != "-" and digest != sha:
        raise ValueError(f"{path.name}: sha256 {digest} != pinned {sha}")
    return b"".join(out), digest


def plane_metrics(plane: bytes, sweeps: int) -> dict:
    counts = {v: plane.count(bytes([v])) for v in set(plane)}
    total = len(plane)
    flat = repeats = 0
    prev = None
    for t in range(sweeps):
        row = plane[t * 401:(t + 1) * 401]
        if min(row) == max(row):
            flat += 1
        if row == prev:
            repeats += 1
        prev = row
    varying = sum(1 for c in range(401) if min(plane[c::401]) != max(plane[c::401]))
    return {
        "min": min(counts),
        "max": max(counts),
        "mean": round(sum(plane) / total, 6),
        "distinct_codes": len(counts),
        "code0_fraction": round(counts.get(0, 0) / total, 6),
        "code255_fraction": round(counts.get(255, 0) / total, 6),
        "mode_fraction": round(max(counts.values()) / total, 6),
        "flat_sweeps": flat,
        "repeat_sweeps": repeats,
        "varying_channels": varying,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    for name in ("--manifest", "--sources", "--downloads", "--index", "--data-root"):
        ap.add_argument(name, required=True)
    args = ap.parse_args()
    data_root = Path(args.data_root)
    downloads = Path(args.downloads)
    manifest = tomllib.loads(Path(args.manifest).read_text(encoding="utf-8"))
    if manifest.get("dataset_id") != DATASET_ID:
        fail("manifest dataset_id mismatch")
    series = {s["id"]: s for s in manifest.get("series", [])}
    if set(series) != {SERIES_A, SERIES_B, SERIES_T}:
        fail(f"manifest series {sorted(series)} unexpected")
    with open(args.sources, encoding="utf-8", newline="") as fh:
        sources = list(csv.DictReader(fh, delimiter="\t"))
    if len(sources) != 36 or len({r["selected_date"] for r in sources}) != 36:
        fail(f"expected 36 distinct pinned days, got {len(sources)}")

    index_rows = [json.loads(line) for line in Path(args.index).read_text(encoding="utf-8").splitlines() if line.strip()]
    by_path = {}
    for row in index_rows:
        missing = [k for k in INDEX_KEYS if k not in row]
        if missing:
            fail(f"index row {row.get('sample_path')} missing {missing}")
            continue
        if row["dataset_id"] != DATASET_ID or row["endianness"] != "little":
            fail(f"index row {row['sample_path']}: dataset/endianness")
        s = series.get(row["series_id"])
        if s is None:
            fail(f"index row {row['sample_path']}: undeclared series")
            continue
        if (row["numeric_kind"], row["bit_width"]) != (s["numeric_kind"], s["bit_width"]) or row["element_size_bytes"] * 8 != row["bit_width"]:
            fail(f"index row {row['sample_path']}: kind/width disagree with manifest")
        by_path[row["sample_path"]] = row
    if len(by_path) != len(index_rows) or len(index_rows) != 3 * len(sources):
        fail(f"index has {len(index_rows)} rows ({len(by_path)} unique), expected {3 * len(sources)}")

    seen = set()
    for src in sources:
        name = src["filename"]
        day = dt.date.fromisoformat(src["selected_date"])
        nxt = day + dt.timedelta(days=1)
        allowed = {(day.year % 100, day.month, day.day): 0, (nxt.year % 100, nxt.month, nxt.day): 86400}
        try:
            raw, digest = stream_gunzip(downloads / name, int(src["size_bytes"]), src["sha256"])
        except (ValueError, OSError, zlib.error) as exc:
            fail(str(exc))
            continue
        if len(raw) != int(src["gzip_isize"]) or f"{zlib.crc32(raw):08x}" != src["gzip_crc32"]:
            fail(f"{name}: length/CRC32 differ from pinned gzip trailer")
            continue
        if len(raw) % 826:
            fail(f"{name}: length {len(raw)} not a multiple of 826")
            continue
        sweeps = len(raw) // 826
        if sweeps != int(src["records"]) or sweeps < MIN_RECORDS:
            fail(f"{name}: {sweeps} sweeps (pinned {src['records']}, minimum {MIN_RECORDS})")
            continue
        parts_a, parts_b, times = [], [], []
        bad = 0
        for rec in REC.iter_unpack(raw):
            yy, mo, dd, hh, mi, ss, site, nb = rec[:8]
            if (site, nb) != (5, 2) or rec[8:13] != (25, 75, 401, 20, 0) or rec[13:18] != (75, 180, 401, 20, 0):
                bad += 1
            off = allowed.get((yy, mo, dd))
            if off is None or hh > 23 or mi > 59 or ss > 59:
                bad += 1
                off = 0
            times.append(off + hh * 3600 + mi * 60 + ss)
            parts_a.append(rec[18])
            parts_b.append(rec[19])
        if bad:
            fail(f"{name}: {bad} header violations (site/bands/descriptors/date)")
            continue
        if f"{times[0] // 3600 % 24:02d}:{times[0] // 60 % 60:02d}:{times[0] % 60:02d}" != src["first_sweep_utc"]:
            fail(f"{name}: first sweep time differs from pinned {src['first_sweep_utc']}")
        stem = "sagamore_hill_" + src["selected_date"].replace("-", "")
        expected = {
            SERIES_A: (f"{stem}_band_a.u8", b"".join(parts_a), 1),
            SERIES_B: (f"{stem}_band_b.u8", b"".join(parts_b), 1),
            SERIES_T: (f"{stem}_sweep_start_utc_s.u32", struct.pack(f"<{sweeps}I", *times), 4),
        }
        for sid, (fname, payload, elem) in expected.items():
            rel = f"samples/{DATASET_ID}/{sid}/{fname}"
            seen.add(rel)
            row = by_path.get(rel)
            path = data_root / rel
            if row is None or not path.is_file():
                fail(f"missing sample or index row {rel}")
                continue
            data = path.read_bytes()
            if data != payload:
                fail(f"{rel}: content differs from re-derived {sid}")
                continue
            if row["sample_size_bytes"] != len(data) or row["value_count"] * elem != len(data) or row.get("records") != sweeps:
                fail(f"{rel}: index size/value_count/records mismatch")
            if row.get("sha256") != hashlib.sha256(data).hexdigest() or row.get("source_sha256") != digest:
                fail(f"{rel}: index sha256 fields mismatch")
            if sid == SERIES_T:
                if min(times) < 0 or max(times) >= 2 * 86400 or min(times) == max(times):
                    fail(f"{rel}: sweep times out of range or constant")
                if row.get("min") != min(times) or row.get("max") != max(times):
                    fail(f"{rel}: index min/max disagree")
                steps = [b - a for a, b in zip(times, times[1:])]
                nonpos = sum(1 for s in steps if s <= 0)
                print(f"  {rel}: sweeps={sweeps} span={times[0]}..{times[-1]}s non_increasing_steps={nonpos}")
                continue
            m = plane_metrics(data, sweeps)
            for key in ("min", "max", "mean", "distinct_codes", "code0_fraction", "code255_fraction", "mode_fraction"):
                if row.get(key) != m[key]:
                    fail(f"{rel}: index {key}={row.get(key)} != recomputed {m[key]}")
            if row.get("sample_shape") != [sweeps, 401]:
                fail(f"{rel}: sample_shape {row.get('sample_shape')}")
            if m["distinct_codes"] < MIN_DISTINCT or m["mode_fraction"] > MAX_MODE_FRACTION:
                fail(f"{rel}: degenerate value distribution {m}")
            if m["code0_fraction"] + m["code255_fraction"] > MAX_EXTREME_FRACTION:
                fail(f"{rel}: too many extreme codes {m}")
            if m["varying_channels"] < MIN_VARYING_CHANNEL_FRACTION * 401:
                fail(f"{rel}: only {m['varying_channels']} of 401 channels vary over the day")
            if m["flat_sweeps"] > MAX_FLAT_SWEEP_FRACTION * sweeps or m["repeat_sweeps"] > MAX_REPEAT_SWEEP_FRACTION * sweeps:
                fail(f"{rel}: flat/repeated sweeps {m['flat_sweeps']}/{m['repeat_sweeps']} of {sweeps}")
            print(f"  {rel}: sweeps={sweeps} range={m['min']}..{m['max']} mean={m['mean']} distinct={m['distinct_codes']} "
                  f"repeat_sweeps={m['repeat_sweeps']} flat_sweeps={m['flat_sweeps']}")

    extra = set(by_path) - seen
    if extra:
        fail(f"index rows without a pinned source: {sorted(extra)[:5]}")
    for sid, s in series.items():
        rows = [r for r in index_rows if r.get("series_id") == sid]
        size = sum(r["sample_size_bytes"] for r in rows)
        if s.get("sample_count") != len(rows) or s.get("total_size_bytes") != size:
            fail(f"manifest {sid}: sample_count/total_size_bytes {s.get('sample_count')}/{s.get('total_size_bytes')} != index {len(rows)}/{size}")
    primary = [r for r in index_rows if series.get(r.get("series_id"), {}).get("role") == "primary"]
    primary_bytes = sum(r["sample_size_bytes"] for r in primary)
    counts = sorted(r["value_count"] for r in primary)
    mid = len(counts) // 2
    median = 0 if not counts else (counts[mid] if len(counts) % 2 else (counts[mid - 1] + counts[mid]) / 2)
    print(f"primary samples={len(primary)} bytes={primary_bytes} median_values={median}")
    if primary_bytes > 1_000_000_000 or median < 1000 or primary_bytes < 100_000:
        fail("primary floor/cap violated")
    if errors:
        print(f"verify FAILED with {len(errors)} error(s)")
        sys.exit(1)
    print("verify OK")


if __name__ == "__main__":
    main()
