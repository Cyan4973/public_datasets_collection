#!/usr/bin/env python3
# Exact-record range-only scan preflight.
from __future__ import annotations

import argparse
from collections import Counter
import csv
import hashlib
import json
import math
from pathlib import Path, PurePosixPath
import re
import statistics
import struct

from discover import (
    API,
    DATASET_ID,
    MAX_ARCHIVE_BYTES,
    curl_json,
    extract_small_member,
    file_url,
    license_id,
    metadata,
    normalize_text,
    remote_zip_members,
)


RECORD_ID = 4_955_141
EXPECTED_TITLE = "Data from: Pressure-induced symmetry changes in body-centred cubic zeolites"
EXPECTED_LICENSES = {"cc-zero", "cc0-1.0"}
EXPECTED_ARCHIVE = "Cubic High-Pressure Repository.zip"
MIN_ROWS = 1_000
MIN_UNIQUE_SCANS = 20
MAX_SELECTED_MEMBERS = 1_000
PATH_PATTERN = re.compile(
    r"^Cubic High-Pressure Repository/Zeolite (?P<zeolite>Na-X|RHO)/"
    r"(?P<state>Empty_data|Filled_data)/(?P<basename>[^/]+\.xy)$",
    re.IGNORECASE,
)


def parse_xy(raw: bytes, member_name: str) -> tuple[list[float], list[float]]:
    text = raw.decode("utf-8-sig", errors="strict")
    coordinates: list[float] = []
    intensities: list[float] = []
    data_started = False
    for line_number, raw_line in enumerate(text.splitlines(), 1):
        line = raw_line.strip()
        if not line or line.startswith(("#", "%", ";", "//")):
            continue
        tokens = [token for token in re.split(r"[\s,;]+", line) if token]
        if len(tokens) != 2:
            if not data_started:
                continue
            raise ValueError(f"non-two-column row after data start: {member_name}:{line_number}")
        try:
            coordinate = float(tokens[0].replace("D", "E").replace("d", "e"))
            intensity = float(tokens[1].replace("D", "E").replace("d", "e"))
        except ValueError:
            if not data_started:
                continue
            raise ValueError(f"nonnumeric row after data start: {member_name}:{line_number}")
        if not math.isfinite(coordinate) or not math.isfinite(intensity):
            raise ValueError(f"nonfinite value: {member_name}:{line_number}")
        data_started = True
        coordinates.append(coordinate)
        intensities.append(intensity)
    if len(intensities) < MIN_ROWS:
        raise ValueError(f"scan below row floor: {member_name} rows={len(intensities)}")
    if any(right <= left for left, right in zip(coordinates, coordinates[1:])):
        raise ValueError(f"scan coordinate is not strictly increasing: {member_name}")
    if len(set(intensities)) < 32 or min(intensities) == max(intensities):
        raise ValueError(f"scan intensity is degenerate: {member_name}")
    return coordinates, intensities


def float32_bytes(values: list[float]) -> bytes:
    output = bytearray()
    for value in values:
        output.extend(struct.pack("<f", value))
    return bytes(output)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    record = curl_json(f"{API}/{RECORD_ID}")
    meta = metadata(record)
    title = str(meta.get("title", ""))
    license_value = license_id(record)
    if title != EXPECTED_TITLE:
        raise SystemExit(f"record title mismatch: {title!r}")
    if license_value not in EXPECTED_LICENSES:
        raise SystemExit(f"record license is not CC0: {license_value!r}")
    files = record.get("files", [])
    if not isinstance(files, list):
        raise SystemExit("record file inventory is missing")
    archives = [item for item in files if isinstance(item, dict) and item.get("key") == EXPECTED_ARCHIVE]
    if len(archives) != 1:
        raise SystemExit(f"expected exactly one {EXPECTED_ARCHIVE!r}, found {len(archives)}")
    archive = archives[0]
    archive_size = int(archive.get("size", 0) or 0)
    archive_url = file_url(archive)
    if not archive_url or not 0 < archive_size <= MAX_ARCHIVE_BYTES:
        raise SystemExit(f"archive URL/size invalid: bytes={archive_size} url={archive_url!r}")

    members = remote_zip_members(archive_url, archive_size)
    selected = []
    rejected = []
    for member in members:
        match = PATH_PATTERN.fullmatch(str(member["name"]))
        if not match:
            continue
        if len(selected) + len(rejected) >= MAX_SELECTED_MEMBERS:
            raise SystemExit("eligible member count exceeds safety cap")
        try:
            raw = extract_small_member(archive_url, member)
            coordinates, intensities = parse_xy(raw, str(member["name"]))
            data = float32_bytes(intensities)
            steps = [right - left for left, right in zip(coordinates, coordinates[1:])]
            selected.append(
                {
                    "member_name": member["name"],
                    "zeolite": match.group("zeolite"),
                    "state": match.group("state").removesuffix("_data").lower(),
                    "basename": match.group("basename"),
                    "compressed_size": int(member["compressed_size"]),
                    "source_size": len(raw),
                    "source_crc32": f"{int(member['crc32']):08x}",
                    "source_sha256": hashlib.sha256(raw).hexdigest(),
                    "value_count": len(intensities),
                    "float32_bytes": len(data),
                    "float32_sha256": hashlib.sha256(data).hexdigest(),
                    "coordinate_min": min(coordinates),
                    "coordinate_max": max(coordinates),
                    "median_step": statistics.median(steps),
                    "intensity_min": min(intensities),
                    "intensity_max": max(intensities),
                    "intensity_distinct": len(set(intensities)),
                }
            )
        except Exception as exc:
            rejected.append({"member_name": member["name"], "reason": str(exc)})

    hashes = Counter(row["float32_sha256"] for row in selected)
    duplicate_hashes = {key: count for key, count in hashes.items() if count > 1}
    seen_hashes = set()
    unique = []
    for row in selected:
        if row["float32_sha256"] in seen_hashes:
            continue
        seen_hashes.add(row["float32_sha256"])
        unique.append(row)
    counts = sorted(int(row["value_count"]) for row in unique)
    total_values = sum(counts)
    total_bytes = sum(int(row["float32_bytes"]) for row in unique)
    by_group = Counter((str(row["zeolite"]), str(row["state"])) for row in unique)

    fields = [
        "member_name", "zeolite", "state", "basename", "compressed_size", "source_size",
        "source_crc32", "source_sha256", "value_count", "float32_bytes", "float32_sha256",
        "coordinate_min", "coordinate_max", "median_step", "intensity_min", "intensity_max",
        "intensity_distinct",
    ]
    with (args.output_dir / "selection.tsv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(unique)
    with (args.output_dir / "rejected.tsv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["member_name", "reason"], delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rejected)

    record_evidence = {
        "record_id": RECORD_ID,
        "record_url": f"https://zenodo.org/records/{RECORD_ID}",
        "title": title,
        "license": meta.get("license"),
        "creators": meta.get("creators"),
        "publication_date": meta.get("publication_date"),
        "description": normalize_text(meta.get("description", "")),
        "keywords": meta.get("keywords", []),
        "archive": {
            "name": EXPECTED_ARCHIVE,
            "size": archive_size,
            "checksum": archive.get("checksum"),
            "url": archive_url,
        },
    }
    (args.output_dir / "record.json").write_text(
        json.dumps(record_evidence, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    summary = {
        "candidate_id": DATASET_ID,
        "record_id": RECORD_ID,
        "archive_size": archive_size,
        "archive_checksum": archive.get("checksum"),
        "zip_members": len(members),
        "eligible_xy_members": len(selected) + len(rejected),
        "valid_xy_members": len(selected),
        "rejected_xy_members": len(rejected),
        "duplicate_float32_hashes": duplicate_hashes,
        "unique_samples": len(unique),
        "primary_values": total_values,
        "primary_float32_bytes": total_bytes,
        "median_value_count": statistics.median(counts) if counts else 0,
        "min_value_count": counts[0] if counts else 0,
        "max_value_count": counts[-1] if counts else 0,
        "groups": {f"{key[0]}:{key[1]}": value for key, value in sorted(by_group.items())},
    }
    (args.output_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    if len(unique) < MIN_UNIQUE_SCANS:
        raise SystemExit(f"too few unique valid scans: {len(unique)}")
    if statistics.median(counts) < MIN_ROWS:
        raise SystemExit("median natural sample is below acceptance floor")
    if total_values < 10_000 or total_bytes < 100 * 1024:
        raise SystemExit("aggregate primary payload is below acceptance floor")


if __name__ == "__main__":
    main()
