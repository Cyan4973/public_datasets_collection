#!/usr/bin/env python3
"""Independently re-derive and check every emitted SPED diffraction pattern.

This verifier does not import the build script. It re-reads the IMGBLO
headers by explicit byte offsets, checks the pinned header and row
checksums, re-derives the expected (scan, scan row, scan column) list,
re-checks every frame prefix, byte-compares every sample against the pixel
slice of its frame, recomputes per-sample statistics, and checks the
manifest totals and ingest_stats.json against the realized output.
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import sys
import tomllib
from pathlib import Path

DATASET_ID = "zenodo_astar_niti_sped_patterns_u8"
SERIES_ID = "sped_diffraction_pattern_u8"
SIDE = 144
NBYTES = SIDE * SIDE
FRAME = NBYTES + 6
STRIDE = 16
MIN_DISTINCT = 8
EXPECTED_SAMPLES = 14_781
# scan -> (file size, header sha256, DP offset, NX, NY)
EXPECTED = {
    "Fig5": (453_653_506, "6f6b3522fc910a845996f0b09f7eb35fcf2ec872ed7eb16d08aae5fe66835997", 25966, 135, 162),
    "Fig6": (583_380_228, "7be6c4e7b05e1cba663dbd7eb9dd46615fd59a32d69965c0ae62db40b208e086", 32220, 158, 178),
    "Fig7": (635_258_471, "bb35bc211256eef89ef36d0d21cb3432f68b524ea0e01f24e6cfe8fad6fc2e67", 34721, 175, 175),
    "Fig8": (622_045_180, "e3492609166990d19f419fc7a5686636eb3218f79776407360de9ca2b02f3673", 34084, 147, 204),
    "FigS5": (543_055_836, "efe138455c15a638945f518ece0fe7ba6fcce64e60f15f0251c62082226aae97", 30276, 154, 170),
    "Fig9": (463_485_688, "923248db0710b62695da2058eaf6d6bb064e7391c11a020a4e5cfbb2e9d83c40", 26440, 152, 147),
    "Fig10": (963_309_016, "e5d37c17252b1e8eb7f1b6683d4936275e7615db96c32eeee7de41557b4c6085", 50536, 215, 216),
    "Fig11": (430_836_206, "6c58ceb0e759e6cb234045c7d45be966476ce945b71daa32c367f11e129b8b15", 24866, 134, 155),
}
INDEX_FIXED = {
    "dataset_id": DATASET_ID,
    "series_id": SERIES_ID,
    "numeric_kind": "uint",
    "bit_width": 8,
    "endianness": "little",
    "element_size_bytes": 1,
    "sample_size_bytes": NBYTES,
    "value_count": NBYTES,
}


def fail(message: str) -> None:
    raise SystemExit(f"VERIFY FAIL: {message}")


def le(blob: bytes, offset: int, width: int) -> int:
    return int.from_bytes(blob[offset:offset + width], "little")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--pins", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args(argv)
    root: Path = args.data_root
    downloads = root / "downloads" / DATASET_ID
    series_dir = root / "samples" / DATASET_ID / SERIES_ID
    index_path = root / "index" / DATASET_ID / "samples.jsonl"
    stats_path = root / "filtered" / DATASET_ID / "ingest_stats.json"

    if not args.pins.is_file():
        fail(f"missing pinned row checksum file {args.pins}")
    pins: dict[str, tuple[int, str]] = {}
    for line in args.pins.read_text(encoding="utf-8").splitlines():
        cells = line.split("\t")
        if cells and cells[0] and not cells[0].startswith("#"):
            pins[cells[0]] = (int(cells[1]), cells[2].strip())

    expected: list[tuple[str, int, int, int, int]] = []  # scan, row, col, nx, dp_offset
    row_cache: dict[str, bytes] = {}
    for scan, (size, header_sha, dp_offset, nx, ny) in EXPECTED.items():
        header = (downloads / f"{scan}.header.bin").read_bytes()
        if len(header) != 4096 or hashlib.sha256(header).hexdigest() != header_sha:
            fail(f"{scan}: header length or sha256 differs from the pin")
        if header[0:6] != b"IMGBLO" or le(header, 6, 2) != 258:
            fail(f"{scan}: not an IMGBLO blockfile header")
        vbf, dpo, dp_sz, hx, hy = le(header, 8, 4), le(header, 12, 4), le(header, 20, 2), le(header, 24, 2), le(header, 26, 2)
        if (vbf, dpo, dp_sz, hx, hy) != (4096, dp_offset, SIDE, nx, ny):
            fail(f"{scan}: header (vbf, dp_offset, dp_sz, nx, ny) = {(vbf, dpo, dp_sz, hx, hy)} disagrees with pins")
        if vbf + nx * ny != dpo or dpo + nx * ny * FRAME != size:
            fail(f"{scan}: offsets do not tile the pinned file size {size}")
        for row in range(0, ny, STRIDE):
            fname = f"{scan}.row{row:03d}.bin"
            blob = (downloads / fname).read_bytes()
            if fname not in pins:
                fail(f"{fname}: not pinned")
            pin_size, pin_sha = pins[fname]
            if len(blob) != pin_size or len(blob) != nx * FRAME:
                fail(f"{fname}: size {len(blob)} != pinned {pin_size} / {nx * FRAME}")
            if hashlib.sha256(blob).hexdigest() != pin_sha:
                fail(f"{fname}: sha256 mismatch against pin")
            row_cache[fname] = blob
            expected.extend((scan, row, col, nx, dp_offset) for col in range(nx))
    if len(pins) != len(row_cache):
        fail(f"pin file lists {len(pins)} rows, recipe selects {len(row_cache)}")
    if len(expected) != EXPECTED_SAMPLES:
        fail(f"expected {EXPECTED_SAMPLES} samples, derived {len(expected)}")

    lines = [line for line in index_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if len(lines) != len(expected):
        fail(f"index has {len(lines)} rows, expected {len(expected)}")

    histogram = [0] * 256
    aggregate = hashlib.sha256()
    seen: set[bytes] = set()
    duplicates = 0
    for line, (scan, row, col, nx, dp_offset) in zip(lines, expected):
        record = json.loads(line)
        for key, value in INDEX_FIXED.items():
            if record.get(key) != value:
                fail(f"index {scan} r{row} c{col}: {key}={record.get(key)!r} != {value!r}")
        rel = f"samples/{DATASET_ID}/{SERIES_ID}/{scan}_r{row:03d}_c{col:03d}.bin"
        if record.get("sample_path") != rel:
            fail(f"index order/path mismatch: {record.get('sample_path')!r} != {rel!r}")
        frame_index = row * nx + col
        if (record.get("scan"), record.get("scan_row"), record.get("scan_col"), record.get("frame_index")) != (scan, row, col, frame_index):
            fail(f"{rel}: scan coordinates in index disagree")
        if record.get("source_byte_offset") != dp_offset + frame_index * FRAME + 6:
            fail(f"{rel}: source_byte_offset mismatch")
        source = row_cache[f"{scan}.row{row:03d}.bin"]
        frame = source[col * FRAME:(col + 1) * FRAME]
        if frame[0:2] != b"\xaa\x55" or le(frame, 2, 4) != frame_index:
            fail(f"{rel}: source frame prefix is not AA 55 + index {frame_index}")
        sample = (root / rel).read_bytes()
        if len(sample) != NBYTES:
            fail(f"{rel}: {len(sample)} bytes != {NBYTES}")
        if sample != frame[6:]:
            fail(f"{rel}: bytes differ from the source frame pixel raster")
        tally = collections.Counter(sample)
        lo, hi = min(tally), max(tally)
        if lo == hi:
            fail(f"{rel}: constant pattern")
        distinct = len(tally)
        if distinct < MIN_DISTINCT:
            fail(f"{rel}: degenerate pattern with {distinct} distinct values")
        recomputed = (lo, hi, distinct, tally.get(255, 0), tally.get(0, 0), sum(sample))
        recorded = tuple(record.get(k) for k in ("min", "max", "distinct_values", "count_255", "count_0", "pixel_sum"))
        if recorded != recomputed:
            fail(f"{rel}: recorded statistics {recorded} disagree with recomputation {recomputed}")
        digest = hashlib.sha256(sample).digest()
        if record.get("sha256") != digest.hex():
            fail(f"{rel}: sha256 in index disagrees")
        if digest in seen:
            duplicates += 1
        seen.add(digest)
        for value, count in tally.items():
            histogram[value] += count
        aggregate.update(sample)

    on_disk = sum(1 for _ in series_dir.iterdir())
    if on_disk != len(expected):
        fail(f"samples directory holds {on_disk} files, expected {len(expected)}")
    if duplicates > 0.005 * len(expected):
        fail(f"{duplicates} byte-identical duplicate patterns")
    used = [v for v in range(256) if histogram[v]]
    if len(used) < 64:
        fail(f"series uses only {len(used)} distinct values overall")

    stats = json.loads(stats_path.read_text(encoding="utf-8"))
    if stats.get("aggregate_sha256") != aggregate.hexdigest() or stats.get("histogram") != histogram:
        fail("ingest_stats.json aggregate hash or histogram disagrees with the samples")

    manifest = tomllib.loads(args.manifest.read_text(encoding="utf-8"))
    series = [s for s in manifest.get("series", []) if s.get("id") == SERIES_ID]
    if len(series) != 1:
        fail(f"manifest must declare exactly one {SERIES_ID} series")
    total_bytes = len(expected) * NBYTES
    if series[0].get("sample_count") != len(expected) or series[0].get("total_size_bytes") != total_bytes:
        fail(
            f"manifest sample_count/total_size_bytes {series[0].get('sample_count')}/{series[0].get('total_size_bytes')} "
            f"!= realized {len(expected)}/{total_bytes}"
        )

    values = sum(histogram)
    print(
        f"verify ok samples={len(expected)} bytes={total_bytes} range={used[0]}..{used[-1]} "
        f"distinct={len(used)} mean={sum(v * c for v, c in enumerate(histogram)) / values:.4f} "
        f"sat255_fraction={histogram[255] / values:.8f} zero_fraction={histogram[0] / values:.8f} "
        f"duplicates={duplicates} aggregate_sha256={aggregate.hexdigest()}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
