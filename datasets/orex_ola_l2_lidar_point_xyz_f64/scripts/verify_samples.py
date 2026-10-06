#!/usr/bin/env python3
"""Independently re-derive and check OLA L2 lidar-return xyz float64 samples.

This verifier does not import the build code or scripts/ola_l2.py. For every
product pinned in sources.tsv it
  * re-checks the label bytes (size, SHA-256) and the .dat size against
    sources.tsv, the .dat SHA-256 against payload_sha256.tsv when that pin file
    exists, and that the LIDVID is a primary member of the downloaded
    data_calibrated_v2 collection inventory;
  * re-reads the label with its own parser: record_length 186, x/y/z at bytes
    115/123/131 as IEEE754LSBDouble in m, and the flag_status location, type and
    "valid return" codes taken from the label text;
  * re-derives the expected sample by concatenating bytes 114..137 of every
    record whose flag is a "valid return" code (no float conversion) and
    compares it byte-for-byte with the sample file;
  * re-applies the shared policy: dropped codes must be exactly the label's
    "no return"/"missing sample" codes, no other flag value may occur, kept
    records must be laser_selection 0 (High Energy) and scan_mode 1 (Linear),
    kept xyz must be finite (checked on IEEE-754 bit patterns), at least 90% of
    records must be kept, and at most 1% of kept points may lie outside
    150..350 m of Bennu's centre (the count must match the index);
  * rejects constant samples or axes, checks index fields, min/max from the
    stored float64 values, SHA-256 digests, the sample-directory inventory,
    the floors and cap, and the manifest's sample_count and total_size_bytes.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
import struct
import sys
import tomllib
import xml.etree.ElementTree as ET
from array import array
from pathlib import Path

DATASET_ID = "orex_ola_l2_lidar_point_xyz_f64"
SERIES_ID = "ola_l2_return_xyz_f64"
P = "{http://pds.nasa.gov/pds4/pds/v1}"
INDEX_KEYS = {
    "dataset_id",
    "series_id",
    "sample_path",
    "numeric_kind",
    "bit_width",
    "endianness",
    "element_size_bytes",
    "sample_size_bytes",
    "value_count",
}
EXP_MASK = 0x7FF0000000000000


def fail(message: str) -> None:
    raise SystemExit(f"VERIFY FAIL: {message}")


def label_layout(path: Path) -> dict:
    root = ET.parse(path).getroot()
    fields = {}
    for node in root.iter(f"{P}Field_Binary"):
        fields[node.findtext(f"{P}name")] = (
            int(node.findtext(f"{P}field_location")),
            node.findtext(f"{P}data_type"),
            int(node.findtext(f"{P}field_length")),
            (node.findtext(f"{P}unit") or "").strip(),
            " ".join((node.findtext(f"{P}description") or "").split()),
        )
    record_length = int(root.find(f".//{P}Record_Binary/{P}record_length").text)
    records = int(root.find(f".//{P}Table_Binary/{P}records").text)
    table_offset = int(root.find(f".//{P}Table_Binary/{P}offset").text)
    lid = root.find(f"{P}Identification_Area/{P}logical_identifier").text.strip()
    vid = root.find(f"{P}Identification_Area/{P}version_id").text.strip()
    if record_length != 186 or table_offset != 0 or len(fields) != 23:
        fail(f"{path.name}: table layout record_length={record_length} offset={table_offset} fields={len(fields)}")
    for name, location in (("x", 115), ("y", 123), ("z", 131)):
        if fields[name][:4] != (location, "IEEE754LSBDouble", 8, "m"):
            fail(f"{path.name}: field {name} layout {fields[name][:4]}")
    for name in ("flag_status", "laser_selection", "scan_mode"):
        if fields[name][1] != "SignedLSB2" or fields[name][2] != 2:
            fail(f"{path.name}: {name} is not SignedLSB2")
    description = fields["flag_status"][4]
    valid = {int(c) for c in re.findall(r"(\d+): valid return", description)}
    invalid = {int(c) for c in re.findall(r"(\d+): (?:no return|missing sample)", description)}
    if valid != {0, 1, 100, 101} or invalid != {2, 3, 102, 103}:
        fail(f"{path.name}: flag semantics valid={sorted(valid)} invalid={sorted(invalid)}")
    if "High Energy (0)" not in fields["laser_selection"][4] or "1: Linear" not in fields["scan_mode"][4]:
        fail(f"{path.name}: laser/scan code descriptions changed")
    return {
        "lidvid": f"{lid}::{vid}",
        "records": records,
        "flag_pos": fields["flag_status"][0] - 1,
        "laser_pos": fields["laser_selection"][0] - 1,
        "scan_pos": fields["scan_mode"][0] - 1,
        "valid": valid,
        "invalid": invalid,
    }


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            block = handle.read(1 << 22)
            if not block:
                return digest.hexdigest()
            digest.update(block)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--sources", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--payload-sha256", type=Path, required=True)
    args = parser.parse_args()
    data_root = args.data_root.resolve()
    download_dir = data_root / "downloads" / DATASET_ID
    series_dir = data_root / "samples" / DATASET_ID / SERIES_ID
    index_path = data_root / "index" / DATASET_ID / "samples.jsonl"

    manifest = tomllib.loads(args.manifest.read_text(encoding="utf-8"))
    if manifest.get("dataset_id") != DATASET_ID:
        fail("manifest dataset_id mismatch")
    series = {entry["id"]: entry for entry in manifest.get("series", [])}
    if set(series) != {SERIES_ID}:
        fail(f"manifest series {sorted(series)} != [{SERIES_ID}]")
    declared = series[SERIES_ID]
    if (declared.get("role"), declared.get("numeric_kind"), declared.get("bit_width"), declared.get("endianness")) != (
        "primary",
        "float",
        64,
        "little",
    ):
        fail("manifest series must be primary little-endian float64")

    with args.sources.open(encoding="utf-8", newline="") as handle:
        sources = list(csv.DictReader(handle, delimiter="\t"))
    products = [row["product"] for row in sources]
    if not sources or len(set(products)) != len(products):
        fail("sources.tsv empty or has duplicate products")
    if {row["phase"] for row in sources} - {"recon_b", "recon_c"}:
        fail("sources.tsv lists a phase outside recon_b/recon_c")
    if any(int(row["dat_bytes"]) >= 200_000_000 for row in sources):
        fail("sources.tsv lists a product at or above the 200,000,000-byte scope bound")
    pins = {}
    if args.payload_sha256.is_file():
        with args.payload_sha256.open(encoding="utf-8", newline="") as handle:
            pins = {row["product"]: row for row in csv.DictReader(handle, delimiter="\t")}
        if set(pins) != set(products):
            fail("payload_sha256.tsv does not cover exactly the pinned products")
    inventory_text = (download_dir / "collection_inventory_ola_data_calibrated_v2.csv").read_text(encoding="ascii")
    members = {line[2:].strip() for line in inventory_text.splitlines() if line.startswith("P,")}

    index_rows = [json.loads(line) for line in index_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    by_product = {}
    for row in index_rows:
        missing = INDEX_KEYS - set(row)
        if missing:
            fail(f"index row missing {sorted(missing)}")
        if row.get("product") in by_product:
            fail(f"duplicate index row for {row.get('product')}")
        by_product[row.get("product")] = row
    if list(by_product) != products:
        fail("index rows do not correspond one-to-one, in order, with sources.tsv")

    expected_files = set()
    total_bytes = total_values = 0
    for source in sources:
        product = source["product"]
        label_path = download_dir / source["phase"] / f"{product}.xml"
        dat_path = download_dir / source["phase"] / f"{product}.dat"
        raw_label = label_path.read_bytes()
        if len(raw_label) != int(source["label_bytes"]) or hashlib.sha256(raw_label).hexdigest() != source["label_sha256"]:
            fail(f"{product}: label bytes differ from sources.tsv")
        layout = label_layout(label_path)
        if layout["lidvid"] != source["lidvid"] or source["lidvid"] not in members:
            fail(f"{product}: LIDVID {layout['lidvid']} not pinned or not in the collection inventory")
        payload = dat_path.read_bytes()
        if len(payload) != int(source["dat_bytes"]) or len(payload) != 186 * layout["records"] or layout["records"] != int(source["records"]):
            fail(f"{product}: .dat size {len(payload)} inconsistent with label/sources")
        if pins:
            pin = pins[product]
            if int(pin["dat_bytes"]) != len(payload) or hashlib.sha256(payload).hexdigest() != pin["sha256"]:
                fail(f"{product}: .dat SHA-256 differs from payload_sha256.tsv")

        fpos, lpos, spos = layout["flag_pos"], layout["laser_pos"], layout["scan_pos"]
        valid, invalid = layout["valid"], layout["invalid"]
        view = memoryview(payload)
        pieces = []
        flag_counts: dict[int, int] = {}
        for offset in range(0, len(payload), 186):
            flag = int.from_bytes(view[offset + fpos : offset + fpos + 2], "little", signed=True)
            flag_counts[flag] = flag_counts.get(flag, 0) + 1
            if flag in valid:
                if payload[offset + lpos : offset + lpos + 2] != b"\x00\x00" or payload[offset + spos : offset + spos + 2] != b"\x01\x00":
                    fail(f"{product}: kept record at byte {offset} is not High Energy Linear")
                pieces.append(view[offset + 114 : offset + 138])
            elif flag not in invalid:
                fail(f"{product}: undocumented flag_status {flag} at byte {offset}")
        expected = b"".join(pieces)
        points = len(pieces)

        row = by_product[product]
        sample_path = data_root / row["sample_path"]
        if sample_path.parent != series_dir or sample_path.name != f"{product}_xyz.f64":
            fail(f"{product}: unexpected sample path {row['sample_path']}")
        expected_files.add(sample_path.name)
        actual = sample_path.read_bytes()
        if actual != expected:
            fail(f"{product}: sample bytes differ from the valid-return x/y/z fields")
        if (
            row["dataset_id"] != DATASET_ID
            or row["series_id"] != SERIES_ID
            or row["numeric_kind"] != "float"
            or int(row["bit_width"]) != 64
            or row["endianness"] != "little"
            or int(row["element_size_bytes"]) != 8
            or int(row["sample_size_bytes"]) != len(actual)
            or int(row["value_count"]) != 3 * points
            or int(row.get("point_count", -1)) != points
            or row.get("sample_shape") != [points, 3]
            or int(row.get("source_records", -1)) != layout["records"]
            or row.get("flag_counts") != {str(k): v for k, v in sorted(flag_counts.items())}
            or int(row.get("dropped_no_return", -1)) != flag_counts.get(2, 0) + flag_counts.get(102, 0)
            or int(row.get("dropped_missing_sample", -1)) != flag_counts.get(3, 0) + flag_counts.get(103, 0)
        ):
            fail(f"{product}: index fields disagree with the re-derived sample")
        if row.get("sha256") != hashlib.sha256(actual).hexdigest():
            fail(f"{product}: sample sha256 mismatch")
        if points < 0.90 * layout["records"]:
            fail(f"{product}: only {points}/{layout['records']} valid returns")

        words = array("Q")
        if words.itemsize != 8:
            fail("no 64-bit unsigned array type")
        words.frombytes(actual)
        if sys.byteorder != "little":
            words.byteswap()
        if any((word & EXP_MASK) == EXP_MASK for word in words):
            fail(f"{product}: non-finite xyz value")
        floats = struct.unpack(f"<{3 * points}d", actual)
        for axis in range(3):
            column = floats[axis::3]
            if min(column) == max(column):
                fail(f"{product}: constant axis {axis}")
        if min(floats) != row.get("min") or max(floats) != row.get("max"):
            fail(f"{product}: index min/max do not match stored float64 values")
        out_of_band = 0
        for i in range(0, len(floats), 3):
            radius = math.sqrt(floats[i] * floats[i] + floats[i + 1] * floats[i + 1] + floats[i + 2] * floats[i + 2])
            if not 150.0 <= radius <= 350.0:
                out_of_band += 1
        if out_of_band != int(row.get("out_of_band_points", -1)) or out_of_band > 0.01 * points:
            fail(f"{product}: {out_of_band} points outside 150..350 m (index says {row.get('out_of_band_points')})")
        total_bytes += len(actual)
        total_values += 3 * points
        print(f"verified product={product} points={points} out_of_band={out_of_band}")

    present = {path.name for path in series_dir.iterdir()} if series_dir.is_dir() else set()
    if present != expected_files:
        fail(f"sample directory inventory mismatch: extra={sorted(present - expected_files)[:5]} missing={sorted(expected_files - present)[:5]}")
    if int(declared.get("sample_count", -1)) != len(index_rows):
        fail(f"manifest sample_count {declared.get('sample_count')} != {len(index_rows)}")
    if int(declared.get("total_size_bytes", -1)) != total_bytes:
        fail(f"manifest total_size_bytes {declared.get('total_size_bytes')} != {total_bytes}")
    counts = sorted(int(row["value_count"]) for row in index_rows)
    mid = len(counts) // 2
    median = counts[mid] if len(counts) % 2 else (counts[mid - 1] + counts[mid]) / 2
    if total_values < 10_000 or median < 1_000 or total_bytes > 1_000_000_000:
        fail(f"floor/cap violated: values={total_values} median={median} bytes={total_bytes}")
    print(
        f"verify_ok samples={len(index_rows)} points={total_values // 3} values={total_values} "
        f"bytes={total_bytes} median_values={median}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
