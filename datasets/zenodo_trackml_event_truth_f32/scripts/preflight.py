#!/usr/bin/env python3
"""Validate and safely inventory the selected reduced TrackML tar archive."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path, PurePosixPath
import tarfile
from typing import Any


EXPECTED_FIELDS = (
    "record_id", "doi", "license", "filename", "size_bytes", "checksum", "url"
)
MAX_EMBEDDED_METADATA_BYTES = 2_000_000


def digest(path: Path, algorithm: str) -> str:
    value = hashlib.new(algorithm)
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            value.update(chunk)
    return value.hexdigest()


def load_selection(path: Path) -> dict[str, str]:
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        if tuple(reader.fieldnames or ()) != EXPECTED_FIELDS:
            raise SystemExit("selection.tsv has an unexpected schema")
        rows = list(reader)
    if len(rows) != 1:
        raise SystemExit("selection.tsv must contain exactly one source")
    return rows[0]


def safe_name(name: str) -> bool:
    path = PurePosixPath(name)
    return bool(name) and not path.is_absolute() and ".." not in path.parts


def signature(payload: bytes) -> str:
    if payload.startswith(b"PK\x03\x04"):
        return "zip_or_numpy_npz"
    if payload.startswith(b"\x93NUMPY"):
        return "numpy_npy"
    if payload.startswith(b"\x89HDF\r\n\x1a\n"):
        return "hdf5"
    if payload.startswith(b"PAR1"):
        return "parquet"
    if payload[:1] in (b"{", b"["):
        return "json_or_text"
    if payload.startswith(b"\x80"):
        return "python_pickle_or_torch"
    printable = sum(byte in b"\t\n\r" or 32 <= byte <= 126 for byte in payload)
    if payload and printable / len(payload) > 0.9:
        return "text"
    return "binary"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--selection", type=Path, required=True)
    parser.add_argument("--record", type=Path, required=True)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()

    selected = load_selection(args.selection)
    expected_size = int(selected["size_bytes"])
    if args.archive.stat().st_size != expected_size:
        raise SystemExit("archive size does not match selection.tsv")
    algorithm, expected_digest = selected["checksum"].split(":", 1)
    actual_digest = digest(args.archive, algorithm)
    if actual_digest != expected_digest:
        raise SystemExit(f"archive {algorithm} mismatch")

    record = json.loads(args.record.read_text(encoding="utf-8"))
    if str(record.get("id")) != selected["record_id"]:
        raise SystemExit("record identity mismatch")
    metadata = record.get("metadata", {})
    if not isinstance(metadata, dict):
        raise SystemExit("record metadata is malformed")
    license_object = metadata.get("license", {})
    license_id = license_object.get("id", "") if isinstance(license_object, dict) else ""
    if str(license_id).lower() != selected["license"]:
        raise SystemExit("record license mismatch")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    embedded_dir = args.output_dir / "embedded_metadata"
    embedded_dir.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []
    extension_counts: dict[str, int] = {}
    total_member_bytes = 0
    regular_files = 0
    with tarfile.open(args.archive, mode="r|gz") as archive:
        for member in archive:
            if not safe_name(member.name):
                raise SystemExit(f"unsafe archive member path: {member.name!r}")
            if member.issym() or member.islnk():
                raise SystemExit(f"archive contains link member: {member.name!r}")
            if not member.isfile():
                continue
            regular_files += 1
            total_member_bytes += member.size
            lowered = member.name.lower()
            suffix = ".tar.gz" if lowered.endswith(".tar.gz") else PurePosixPath(lowered).suffix
            extension_counts[suffix or "[none]"] = extension_counts.get(suffix or "[none]", 0) + 1
            source = archive.extractfile(member)
            if source is None:
                raise SystemExit(f"cannot read archive member: {member.name!r}")
            prefix = source.read(min(member.size, 256))
            kind = signature(prefix)
            rows.append({
                "member": member.name,
                "size_bytes": member.size,
                "suffix": suffix,
                "signature": kind,
                "prefix_hex": prefix[:32].hex(),
            })
            basename = PurePosixPath(member.name).name.lower()
            if member.size <= MAX_EMBEDDED_METADATA_BYTES and (
                "readme" in basename or suffix in {".json", ".yaml", ".yml", ".toml"}
            ):
                remainder = source.read()
                payload = prefix + remainder
                target = embedded_dir / PurePosixPath(member.name).name
                target.write_bytes(payload)

    inventory = args.output_dir / "archive_members.tsv"
    with inventory.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=("member", "size_bytes", "suffix", "signature", "prefix_hex"),
            delimiter="\t",
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(rows)

    summary = {
        "candidate_id": "zenodo_trackml_event_truth_f32",
        "record_id": selected["record_id"],
        "doi": selected["doi"],
        "license": selected["license"],
        "archive": selected["filename"],
        "archive_size_bytes": expected_size,
        "archive_md5": actual_digest,
        "regular_member_count": regular_files,
        "total_uncompressed_member_bytes": total_member_bytes,
        "extension_counts": dict(sorted(extension_counts.items())),
        "next_check": "inspect member schemas and establish the actual numeric representation",
    }
    (args.output_dir / "archive_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    print(f"inventory={inventory}")


if __name__ == "__main__":
    main()
