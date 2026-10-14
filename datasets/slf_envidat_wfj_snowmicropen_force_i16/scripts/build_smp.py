#!/usr/bin/env python3
"""Decode the pinned S36M SnowMicroPen .PNT profiles to little-endian int16.

PNT layout (SMP v4 firmware 406/408, as read by snowmicropyn's Pnt.load):
big-endian header of 512 bytes; samples.force.count is '>l' at offset 358;
the force samples are that many big-endian int16 ADC counts starting at byte
512. Bytes after the last sample are padding and are ignored. snowmicropyn
converts a count to newtons as count * samples.conv.force ('>f' at offset 10).

Usage: build_smp.py <data_root> <recipe_dir>
"""
from __future__ import annotations

import array
import csv
import hashlib
import json
import os
import struct
import sys
from pathlib import Path

DATASET_ID = "slf_envidat_wfj_snowmicropen_force_i16"
SERIES_ID = "smp_s36m_force_counts_i16"
HEADER_BYTES = 512
EXPECTED_SPATIAL_RES = struct.unpack(">f", struct.pack(">f", 0.00413223123177886))[0]
CONV_MIN, CONV_MAX = 0.00129, 0.00132  # amplifier range 5000 pC, sensor sensitivity 116-118 pC/N


def parse_header(raw: bytes) -> dict:
    return {
        "firmware": struct.unpack_from(">h", raw, 0)[0],
        "spatial_res_mm": struct.unpack_from(">f", raw, 6)[0],
        "conv_force": struct.unpack_from(">f", raw, 10)[0],
        "speed_mm_s": struct.unpack_from(">f", raw, 64)[0],
        "filename": raw[256:264].decode("latin-1"),
        "force_count": struct.unpack_from(">l", raw, 358)[0],
        "sensor_range_pc": struct.unpack_from(">h", raw, 366)[0],
        "amplifier_range_pc": struct.unpack_from(">h", raw, 368)[0],
        "sensor_sensitivity": struct.unpack_from(">h", raw, 370)[0],
        "tip_diameter_um": struct.unpack_from(">l", raw, 376)[0],
        "smp_serial": struct.unpack_from(">h", raw, 384)[0],
    }


def main() -> None:
    data_root, recipe_dir = Path(sys.argv[1]), Path(sys.argv[2])
    member_dir = data_root / "downloads" / DATASET_ID / "raw_data_members"
    sample_dir = data_root / "samples" / DATASET_ID / SERIES_ID
    index_dir = data_root / "index" / DATASET_ID
    filtered_dir = data_root / "filtered" / DATASET_ID
    for directory in (sample_dir, index_dir, filtered_dir):
        directory.mkdir(parents=True, exist_ok=True)
    for stale in sample_dir.glob("*.bin"):
        stale.unlink()

    with open(recipe_dir / "members.tsv", newline="", encoding="utf-8") as handle:
        members = list(csv.DictReader(handle, delimiter="\t"))
    with open(data_root / "downloads" / DATASET_ID / "raw_data.csv", newline="", encoding="utf-8") as handle:
        flags = {row["Path"]: row for row in csv.DictReader(handle)}

    rows = []
    total_values = 0
    conv_values = set()
    for member in members:
        rel = member["zip_member"][len("raw_data/") :]
        stem = rel.split("/")[1].split(".")[0]
        flag = flags[rel]
        if not (flag["File"].startswith("S36M") and flag["BestOfDay"] == "1" and flag["Quality"] == "1"):
            sys.exit(f"{rel}: raw_data.csv selection flags do not match")
        raw = (member_dir / rel).read_bytes()
        if len(raw) != int(member["uncompressed_size"]):
            sys.exit(f"{rel}: size {len(raw)} != pinned {member['uncompressed_size']}")
        hdr = parse_header(raw)
        problems = []
        if hdr["firmware"] not in (406, 408):
            problems.append(f"firmware {hdr['firmware']}")
        if hdr["smp_serial"] != 36 or hdr["filename"] != stem:
            problems.append(f"serial/filename {hdr['smp_serial']} {hdr['filename']!r}")
        if hdr["amplifier_range_pc"] != 5000 or hdr["sensor_range_pc"] != 5000:
            problems.append(f"range {hdr['sensor_range_pc']}/{hdr['amplifier_range_pc']}")
        if not CONV_MIN <= hdr["conv_force"] <= CONV_MAX or repr(hdr["conv_force"]) != member["force_conv_factor"]:
            problems.append(f"conv {hdr['conv_force']!r}")
        if hdr["spatial_res_mm"] != EXPECTED_SPATIAL_RES or hdr["speed_mm_s"] != 20.0 or hdr["tip_diameter_um"] != 5000:
            problems.append(f"geometry {hdr['spatial_res_mm']} {hdr['speed_mm_s']} {hdr['tip_diameter_um']}")
        count = hdr["force_count"]
        if count != int(member["force_sample_count"]) or count < 1000 or HEADER_BYTES + 2 * count > len(raw):
            problems.append(f"force count {count}")
        if problems:
            sys.exit(f"{rel}: header check failed: {problems}")

        samples = array.array("h")
        samples.frombytes(raw[HEADER_BYTES : HEADER_BYTES + 2 * count])
        if sys.byteorder == "little":
            samples.byteswap()  # source is big-endian
        distinct = len(set(samples))
        lo, hi = min(samples), max(samples)
        if distinct < 50 or lo == hi:
            sys.exit(f"{rel}: degenerate profile distinct={distinct} min={lo} max={hi}")
        payload = samples.tobytes() if sys.byteorder == "little" else _swap(samples)
        out = sample_dir / f"{rel.split('/')[0]}_{stem}.bin"
        out.write_bytes(payload)
        conv_values.add(hdr["conv_force"])
        total_values += count
        rows.append(
            {
                "dataset_id": DATASET_ID,
                "series_id": SERIES_ID,
                "sample_path": str(out.relative_to(data_root)),
                "numeric_kind": "int",
                "bit_width": 16,
                "endianness": "little",
                "element_size_bytes": 2,
                "sample_size_bytes": len(payload),
                "value_count": count,
                "min": lo,
                "max": hi,
                "distinct_values": distinct,
                "sha256": hashlib.sha256(payload).hexdigest(),
                "source_zip_member": member["zip_member"],
                "profile_date": member["profile_date"],
                "force_conv_factor": hdr["conv_force"],
                "spatial_resolution_mm": hdr["spatial_res_mm"],
                "sensor_serial": member["sensor_serial"],
                "smp_firmware": hdr["firmware"],
            }
        )

    if len(rows) != 291:
        sys.exit(f"expected 291 profiles, built {len(rows)}")
    tmp = index_dir / "samples.jsonl.tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")
    os.replace(tmp, index_dir / "samples.jsonl")
    summary = {
        "dataset_id": DATASET_ID,
        "series_id": SERIES_ID,
        "samples": len(rows),
        "values": total_values,
        "bytes": 2 * total_values,
        "distinct_conv_factors": sorted(conv_values),
        "global_min": min(r["min"] for r in rows),
        "global_max": max(r["max"] for r in rows),
    }
    (filtered_dir / "build_summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary))


def _swap(samples: array.array) -> bytes:
    copy = array.array("h", samples)
    copy.byteswap()
    return copy.tobytes()


if __name__ == "__main__":
    main()
