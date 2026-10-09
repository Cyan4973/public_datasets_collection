#!/usr/bin/env python3
"""swissSURFACE3D 2021 LAS 1.2 point-format-1 Z extraction (pure stdlib).

Subcommands:
  self-test   build a synthetic zipped LAS 1.2 pf1 tile and check extraction
  validate    structural + CRC validation of the downloaded zips (download.sh)
  build       stream each zipped LAS member and emit its Z column as LE int32

One sample = one 1 km2 tile = the complete Z field of the tile's single LAS
member, in point-record order. No values are dropped, reordered or rescaled:
the stored int32 Z codes (0.01 m units, offset 0, LN02 heights) are copied
byte-for-byte from offset 8 of every 28-byte record.
"""

from __future__ import annotations

import argparse
import array
import collections
import csv
import hashlib
import io
import json
import struct
import sys
import tempfile
import zipfile
from pathlib import Path

DATASET_ID = "swisstopo_swisssurface3d_alps_las_z_i32"
SERIES_ID = "swisssurface3d_z_i32"
HEADER_SIZE = 227
RECORD_LENGTH = 28
POINT_FORMAT = 1
Z_OFFSET_IN_RECORD = 8
SCALE = 0.01
SYSTEM_ID = "LAStools (c) by rapidlasso GmbH"
SOFTWARE_PREFIX = "las2las"
BLOCK_POINTS = 1 << 18
# Plausibility window for stored Z codes (cm): 1,000 m .. 5,000 m.
Z_CODE_MIN = 100_000
Z_CODE_MAX = 500_000
MAX_TOP_VALUE_FRACTION = 0.05
MIN_DISTINCT = 10_000
MAX_PRIMARY_BYTES = 1_000_000_000

if sys.byteorder != "little":  # array('i') must already be little-endian
    raise SystemExit("this script assumes a little-endian host")


def load_sources(path: Path) -> list[dict]:
    with path.open(newline="") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    if not rows:
        raise ValueError("empty sources.tsv")
    for row in rows:
        for key in ("zip_bytes", "member_bytes", "point_count"):
            row[key] = int(row[key])
        row["member_crc32"] = int(row["member_crc32"], 16)
        row["header_min_z_code"] = round(float(row["header_min_z_m"]) * 100)
        row["header_max_z_code"] = round(float(row["header_max_z_m"]) * 100)
        easting, northing = row["item_id"].rsplit("_", 1)[1].split("-")
        row["tile_e_km"], row["tile_n_km"] = int(easting), int(northing)
        if row["member_bytes"] != HEADER_SIZE + RECORD_LENGTH * row["point_count"]:
            raise ValueError(f"{row['item_id']}: pinned member size inconsistent")
    ids = [row["item_id"] for row in rows]
    if ids != sorted(ids) or len(set(ids)) != len(ids):
        raise ValueError("sources.tsv must be sorted and unique")
    return rows


def parse_header(raw: bytes, row: dict) -> None:
    name = row["item_id"]
    if len(raw) != HEADER_SIZE or raw[:4] != b"LASF":
        raise ValueError(f"{name}: not a LAS header")
    if (raw[24], raw[25]) != (1, 2):
        raise ValueError(f"{name}: expected LAS 1.2, got {raw[24]}.{raw[25]}")
    system_id = raw[26:58].rstrip(b"\0").decode("ascii", "replace")
    software = raw[58:90].rstrip(b"\0").decode("ascii", "replace")
    if system_id != SYSTEM_ID or not software.startswith(SOFTWARE_PREFIX):
        raise ValueError(f"{name}: unexpected producer {system_id!r}/{software!r}")
    header_size, point_offset, n_vlr, point_format, record_length, count = struct.unpack_from(
        "<HIIBHI", raw, 94
    )
    if (header_size, point_offset, n_vlr) != (HEADER_SIZE, HEADER_SIZE, 0):
        raise ValueError(f"{name}: unexpected header layout {header_size}/{point_offset}/{n_vlr}")
    if point_format != POINT_FORMAT or record_length != RECORD_LENGTH:
        raise ValueError(f"{name}: expected pf1/28, got pf{point_format}/{record_length}")
    if count != row["point_count"]:
        raise ValueError(f"{name}: point count {count} != pinned {row['point_count']}")
    sx, sy, sz, ox, oy, oz, _maxx, _minx, _maxy, _miny, maxz, minz = struct.unpack_from(
        "<12d", raw, 131
    )
    if (sx, sy, sz) != (SCALE, SCALE, SCALE):
        raise ValueError(f"{name}: unexpected scale {(sx, sy, sz)}")
    if (ox, oy, oz) != (row["tile_e_km"] * 1000.0, row["tile_n_km"] * 1000.0, 0.0):
        raise ValueError(f"{name}: unexpected offsets {(ox, oy, oz)}")
    if (round(minz * 100), round(maxz * 100)) != (row["header_min_z_code"], row["header_max_z_code"]):
        raise ValueError(f"{name}: header Z bounds {minz}..{maxz} differ from pinned")


def check_zip(zf: zipfile.ZipFile, row: dict) -> zipfile.ZipInfo:
    infos = zf.infolist()
    if [info.filename for info in infos] != [row["member_name"]]:
        raise ValueError(f"{row['item_id']}: unexpected members {[i.filename for i in infos]}")
    info = infos[0]
    if info.compress_type != zipfile.ZIP_DEFLATED:
        raise ValueError(f"{row['item_id']}: member not deflated")
    if info.file_size != row["member_bytes"] or info.CRC != row["member_crc32"]:
        raise ValueError(
            f"{row['item_id']}: member size/CRC {info.file_size}/{info.CRC:08x} differ from pinned"
        )
    return info


def iter_z_blocks(zip_path: Path, row: dict):
    """Yield little-endian int32 Z payload blocks; enforces header and zip CRC."""
    with zipfile.ZipFile(zip_path) as zf:
        info = check_zip(zf, row)
        with zf.open(info) as member:
            parse_header(member.read(HEADER_SIZE), row)
            remaining = row["point_count"]
            while remaining:
                count = min(remaining, BLOCK_POINTS)
                size = count * RECORD_LENGTH
                buf = member.read(size)
                if len(buf) != size:
                    raise ValueError(f"{row['item_id']}: truncated LAS member")
                out = bytearray(count * 4)
                for lane in range(4):
                    start = Z_OFFSET_IN_RECORD + lane
                    out[lane::4] = buf[start::RECORD_LENGTH]
                yield bytes(out)
                remaining -= count
            if member.read(1) != b"":  # also forces zipfile's CRC-32 check at EOF
                raise ValueError(f"{row['item_id']}: trailing bytes after point records")


def validate(download_dir: Path, sources: list[dict]) -> None:
    for row in sources:
        path = download_dir / row["asset_name"]
        crc = 0
        with zipfile.ZipFile(path) as zf:
            info = check_zip(zf, row)
            with zf.open(info) as member:
                parse_header(member.read(HEADER_SIZE), row)
                while True:
                    chunk = member.read(1 << 24)
                    if not chunk:
                        break
        print(f"validated {row['asset_name']} points={row['point_count']} crc={row['member_crc32']:08x}")
    print(f"semantic_validation=ok tiles={len(sources)}")


def build(download_dir: Path, data_root: Path, sources: list[dict]) -> None:
    samples_dir = data_root / "samples" / DATASET_ID
    series_dir = samples_dir / SERIES_ID
    index_path = data_root / "index" / DATASET_ID / "samples.jsonl"
    stats_path = data_root / "filtered" / DATASET_ID / "ingest_stats.json"
    if samples_dir.exists():
        for old in sorted(samples_dir.rglob("*"), reverse=True):
            old.unlink() if old.is_file() else old.rmdir()
    series_dir.mkdir(parents=True, exist_ok=True)
    index_path.parent.mkdir(parents=True, exist_ok=True)
    stats_path.parent.mkdir(parents=True, exist_ok=True)

    rows_out = []
    total_bytes = 0
    for row in sources:
        tile = f"{row['tile_e_km']}_{row['tile_n_km']}"
        out_path = series_dir / f"{tile}.i32.bin"
        digest = hashlib.sha256()
        counts: collections.Counter = collections.Counter()
        zmin, zmax, n = None, None, 0
        with out_path.open("wb") as handle:
            for block in iter_z_blocks(download_dir / row["asset_name"], row):
                handle.write(block)
                digest.update(block)
                values = array.array("i")
                values.frombytes(block)
                bmin, bmax = min(values), max(values)
                zmin = bmin if zmin is None else min(zmin, bmin)
                zmax = bmax if zmax is None else max(zmax, bmax)
                counts.update(values)
                n += len(values)
        if n != row["point_count"]:
            raise ValueError(f"{tile}: wrote {n} values, expected {row['point_count']}")
        if (zmin, zmax) != (row["header_min_z_code"], row["header_max_z_code"]):
            raise ValueError(f"{tile}: data Z range {zmin}..{zmax} != header bounds")
        if zmin < Z_CODE_MIN or zmax > Z_CODE_MAX or zmin == zmax:
            raise ValueError(f"{tile}: implausible or constant Z range {zmin}..{zmax}")
        top_value, top_count = counts.most_common(1)[0]
        top_fraction = top_count / n
        if len(counts) < MIN_DISTINCT or top_fraction > MAX_TOP_VALUE_FRACTION:
            raise ValueError(f"{tile}: degenerate Z distinct={len(counts)} top_fraction={top_fraction:.4f}")
        size = out_path.stat().st_size
        total_bytes += size
        record = {
            "dataset_id": DATASET_ID,
            "series_id": SERIES_ID,
            "sample_path": out_path.relative_to(data_root).as_posix(),
            "numeric_kind": "int",
            "bit_width": 32,
            "endianness": "little",
            "element_size_bytes": 4,
            "sample_size_bytes": size,
            "value_count": n,
            "source_item": row["item_id"],
            "source_url": row["url"],
            "source_member": row["member_name"],
            "sha256": digest.hexdigest(),
            "min": zmin,
            "max": zmax,
            "distinct_values": len(counts),
            "top_value": top_value,
            "top_value_fraction": round(top_fraction, 6),
        }
        rows_out.append(record)
        print(
            f"sample {tile} values={n} z_code={zmin}..{zmax} distinct={len(counts)} "
            f"top_fraction={top_fraction:.5f}"
        )
    if total_bytes > MAX_PRIMARY_BYTES:
        raise ValueError(f"primary bytes {total_bytes} exceed cap")
    with index_path.open("w") as handle:
        for record in rows_out:
            handle.write(json.dumps(record, sort_keys=True) + "\n")
    stats = {
        "dataset_id": DATASET_ID,
        "samples": len(rows_out),
        "total_values": sum(r["value_count"] for r in rows_out),
        "total_bytes": total_bytes,
        "z_code_min": min(r["min"] for r in rows_out),
        "z_code_max": max(r["max"] for r in rows_out),
    }
    stats_path.write_text(json.dumps(stats, indent=2) + "\n")
    print(json.dumps(stats))


def make_synthetic(directory: Path) -> tuple[Path, dict, list[int]]:
    """Write a zipped LAS 1.2 pf1 tile with known Z values; return (zip, row, z)."""
    count = BLOCK_POINTS + 1234  # crosses a block boundary
    z_values = [200_000 + ((i * 7919) % 150_001) - (i % 3) for i in range(count)]
    header = bytearray(HEADER_SIZE)
    header[:4] = b"LASF"
    header[24:26] = bytes((1, 2))
    header[26 : 26 + len(SYSTEM_ID)] = SYSTEM_ID.encode()
    header[58:76] = b"las2las (version 1)"[:18]
    struct.pack_into("<HIIBHI", header, 94, HEADER_SIZE, HEADER_SIZE, 0, POINT_FORMAT, RECORD_LENGTH, count)
    struct.pack_into(
        "<12d", header, 131, SCALE, SCALE, SCALE, 2600000.0, 1100000.0, 0.0,
        2600999.99, 2600000.0, 1100999.99, 1100000.0, max(z_values) / 100, min(z_values) / 100,
    )
    body = io.BytesIO()
    for i, z in enumerate(z_values):
        body.write(struct.pack("<iiiHBBbBHd", i % 100000, (i * 3) % 100000, z, i % 4096, 0x12, 2, -5, 0, 7, 1.5 * i))
    payload = bytes(header) + body.getvalue()
    assert len(payload) == HEADER_SIZE + RECORD_LENGTH * count
    zip_path = directory / "synthetic_2600-1100.las.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("2600_1100.las", payload)
    import zlib

    row = {
        "item_id": "swisssurface3d_2021_2600-1100",
        "asset_name": zip_path.name,
        "url": "synthetic",
        "member_name": "2600_1100.las",
        "member_bytes": len(payload),
        "point_count": count,
        "member_crc32": zlib.crc32(payload),
        "header_min_z_code": min(z_values),
        "header_max_z_code": max(z_values),
        "tile_e_km": 2600,
        "tile_n_km": 1100,
    }
    return zip_path, row, z_values


def self_test() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        zip_path, row, z_values = make_synthetic(Path(tmp))
        got = b"".join(iter_z_blocks(zip_path, row))
        if got != array.array("i", z_values).tobytes():
            raise SystemExit("self-test failed: Z extraction mismatch")
        bad = dict(row, member_crc32=row["member_crc32"] ^ 1)
        try:
            list(iter_z_blocks(zip_path, bad))
        except ValueError:
            pass
        else:
            raise SystemExit("self-test failed: CRC mismatch not rejected")
        bad = dict(row, point_count=row["point_count"] - 1)
        try:
            list(iter_z_blocks(zip_path, bad))
        except ValueError:
            pass
        else:
            raise SystemExit("self-test failed: point-count mismatch not rejected")
    print("self_test=ok")


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("self-test")
    for name in ("validate", "build"):
        p = sub.add_parser(name)
        p.add_argument("--sources", type=Path, required=True)
        p.add_argument("--download-dir", type=Path, required=True)
        if name == "build":
            p.add_argument("--data-root", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "self-test":
        self_test()
    elif args.command == "validate":
        validate(args.download_dir, load_sources(args.sources))
    else:
        build(args.download_dir, args.data_root.resolve(), load_sources(args.sources))


if __name__ == "__main__":
    main()
