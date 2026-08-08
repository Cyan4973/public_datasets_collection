#!/usr/bin/env python3
"""Extract and independently verify exact native uint16 CMMD mammograms."""
from __future__ import annotations

import argparse
from array import array
import hashlib
import json
from pathlib import Path
import struct
import sys
import zipfile


DATASET_ID = "tcia_cmmd_mammography_u16"
SERIES_ID = "cmmd_mammography_pixel_u16"
SERIES_UID = "1.3.6.1.4.1.14519.5.2.1.1239.1759.338921544064671779799433793481"
MAMMOGRAPHY_SOP_CLASS = "1.2.840.10008.5.1.4.1.1.1.2"
TRANSFER_SYNTAX = "1.2.840.10008.1.2.1"
ROWS = 2294
COLUMNS = 1914
VALUES_PER_IMAGE = ROWS * COLUMNS
BYTES_PER_IMAGE = VALUES_PER_IMAGE * 2
EXPECTED_PRIMARY_VALUES = VALUES_PER_IMAGE * 2
EXPECTED_PRIMARY_BYTES = BYTES_PER_IMAGE * 2
EXPECTED_MEMBERS = {
    "LICENSE": (2784, "e586c7380104cd254f08d7758705ba9494db2d8d0db33b27ab4d88418f965865"),
    "00000001.dcm": (8783862, "ab9c82e3fc5c0c1149943b0d08126021364370148631f03e429dcf5bdda5f602"),
    "00000002.dcm": (8783870, "6c6ca46caf550654755e5fb20f88683d1363ecb87e26e89e8079e295ef6e07b2"),
}
LONG_VR = {b"OB", b"OD", b"OF", b"OL", b"OW", b"SQ", b"UC", b"UR", b"UT", b"UN"}


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def spans(data: bytes, tag: tuple[int, int], *, explicit: bool, limit: int) -> list[tuple[int, int, int]]:
    pattern = struct.pack("<HH", *tag)
    found = []
    offset = 132
    while True:
        offset = data.find(pattern, offset, limit)
        if offset < 0:
            return found
        if offset % 2:
            offset += 1
            continue
        try:
            if explicit:
                vr = data[offset + 4:offset + 6]
                if len(vr) != 2 or not all(65 <= byte <= 90 for byte in vr):
                    offset += 2
                    continue
                if vr in LONG_VR:
                    value_offset = offset + 12
                    length = struct.unpack_from("<I", data, offset + 8)[0]
                else:
                    value_offset = offset + 8
                    length = struct.unpack_from("<H", data, offset + 6)[0]
            else:
                value_offset = offset + 8
                length = struct.unpack_from("<I", data, offset + 4)[0]
        except struct.error:
            return found
        if length != 0xFFFFFFFF and value_offset + length <= len(data):
            found.append((offset, value_offset, length))
        offset += 2


def unique_text(data: bytes, tag: tuple[int, int], *, limit: int, explicit: bool = True) -> str | None:
    values = set()
    for _, value_offset, length in spans(data, tag, explicit=explicit, limit=limit):
        if not 0 < length <= 512:
            continue
        raw = data[value_offset:value_offset + length]
        if all(byte in (0, 9, 10, 13, 27) or 32 <= byte <= 126 for byte in raw):
            values.add(raw.decode("ascii", "strict").strip("\0 "))
    values.discard("")
    if len(values) > 1:
        raise ValueError(f"ambiguous DICOM text tag {tag}: {sorted(values)}")
    return next(iter(values), None)


def unique_u16(data: bytes, tag: tuple[int, int], *, limit: int) -> int | None:
    values = {
        struct.unpack_from("<H", data, value_offset)[0]
        for _, value_offset, length in spans(data, tag, explicit=True, limit=limit)
        if length == 2
    }
    if len(values) > 1:
        raise ValueError(f"ambiguous DICOM uint16 tag {tag}: {sorted(values)}")
    return next(iter(values), None)


def require_text(data: bytes, tag: tuple[int, int], expected: str, limit: int) -> None:
    actual = unique_text(data, tag, limit=limit)
    if actual != expected:
        raise ValueError(f"DICOM tag {tag} changed: {actual!r} != {expected!r}")


def parse_image(data: bytes, member_name: str) -> tuple[bytes, dict[str, object]]:
    if len(data) != EXPECTED_MEMBERS[member_name][0] or sha256_bytes(data) != EXPECTED_MEMBERS[member_name][1]:
        raise ValueError(f"pinned DICOM identity changed: {member_name}")
    if len(data) < 132 or data[128:132] != b"DICM":
        raise ValueError("DICOM preamble missing")
    transfer = unique_text(data, (0x0002, 0x0010), limit=len(data))
    if transfer != TRANSFER_SYNTAX:
        raise ValueError(f"unsupported transfer syntax: {transfer!r}")
    pixel_candidates = [
        span for span in spans(data, (0x7FE0, 0x0010), explicit=True, limit=len(data))
        if span[2] == BYTES_PER_IMAGE
    ]
    if len(pixel_candidates) != 1:
        raise ValueError(f"expected one exact native Pixel Data field, found {len(pixel_candidates)}")
    pixel_tag_offset, pixel_offset, pixel_length = pixel_candidates[0]
    require_text(data, (0x0008, 0x0016), MAMMOGRAPHY_SOP_CLASS, pixel_tag_offset)
    require_text(data, (0x0008, 0x0060), "MG", pixel_tag_offset)
    require_text(data, (0x0008, 0x0068), "FOR PRESENTATION", pixel_tag_offset)
    require_text(data, (0x0020, 0x000E), SERIES_UID, pixel_tag_offset)
    require_text(data, (0x0020, 0x0062), "L", pixel_tag_offset)
    require_text(data, (0x0028, 0x0004), "MONOCHROME2", pixel_tag_offset)
    require_text(data, (0x0028, 0x2110), "00", pixel_tag_offset)
    schema = (
        unique_u16(data, (0x0028, 0x0010), limit=pixel_tag_offset),
        unique_u16(data, (0x0028, 0x0011), limit=pixel_tag_offset),
        unique_u16(data, (0x0028, 0x0002), limit=pixel_tag_offset),
        unique_u16(data, (0x0028, 0x0100), limit=pixel_tag_offset),
        unique_u16(data, (0x0028, 0x0101), limit=pixel_tag_offset),
        unique_u16(data, (0x0028, 0x0102), limit=pixel_tag_offset),
        unique_u16(data, (0x0028, 0x0103), limit=pixel_tag_offset),
    )
    if schema != (ROWS, COLUMNS, 1, 16, 16, 15, 0):
        raise ValueError(f"unexpected mammography pixel schema: {schema}")
    payload = data[pixel_offset:pixel_offset + pixel_length]
    values = array("H")
    values.frombytes(payload)
    if sys.byteorder != "little":
        values.byteswap()
    distinct = len(set(values))
    transitions = sum(left != right for left, right in zip(values, values[1:]))
    if len(values) != VALUES_PER_IMAGE or distinct < 256 or transitions < 10_000:
        raise ValueError("degenerate mammography pixel plane")
    return payload, {
        "distinct_values": distinct,
        "maximum": max(values),
        "minimum": min(values),
        "sha256": sha256_bytes(payload),
        "transition_count": transitions,
        "value_count": len(values),
        "zero_count": values.count(0),
    }


def load_archive(download_dir: Path) -> tuple[Path, list[tuple[str, bytes]]]:
    archive = download_dir / "cmmd_mammography_u16.zip"
    inventory = json.loads((download_dir / "download_inventory.json").read_text(encoding="utf-8"))
    if inventory.get("series_uid") != SERIES_UID or inventory.get("dicom_source_bytes") != 17_567_732:
        raise ValueError("download inventory identity changed")
    if archive.stat().st_size != int(inventory["archive_bytes"]):
        raise ValueError("archive size differs from download inventory")
    if sha256_bytes(archive.read_bytes()) != inventory["archive_sha256"]:
        raise ValueError("archive hash differs from download inventory")
    with zipfile.ZipFile(archive) as zf:
        members = [member for member in zf.infolist() if not member.is_dir()]
        if {member.filename for member in members} != set(EXPECTED_MEMBERS):
            raise ValueError("archive member inventory changed")
        license_data = zf.read("LICENSE")
        if len(license_data) != EXPECTED_MEMBERS["LICENSE"][0] or sha256_bytes(license_data) != EXPECTED_MEMBERS["LICENSE"][1]:
            raise ValueError("embedded license identity changed")
        if not (b"CC BY 4.0" in license_data or b"creativecommons.org/licenses/by/4.0" in license_data):
            raise ValueError("embedded CC BY 4.0 license missing")
        dicoms = [(name, zf.read(name)) for name in ("00000001.dcm", "00000002.dcm")]
    return archive, dicoms


def collect(
    *, mode: str, download_dir: Path, samples_dir: Path, data_root: Path
) -> tuple[list[dict[str, object]], dict[str, object]]:
    archive, dicoms = load_archive(download_dir)
    if mode == "build":
        if samples_dir.exists():
            for path in samples_dir.glob("*.bin"):
                path.unlink()
        samples_dir.mkdir(parents=True, exist_ok=True)
    entries = []
    details = []
    hashes = set()
    for ordinal, (member_name, data) in enumerate(dicoms, 1):
        payload, result = parse_image(data, member_name)
        output = samples_dir / f"left_mammogram_{ordinal:02d}.bin"
        if mode == "build":
            output.write_bytes(payload)
        elif output.read_bytes() != payload:
            raise ValueError(f"built sample differs from DICOM Pixel Data: {output.name}")
        if result["sha256"] in hashes:
            raise ValueError("duplicate mammography pixel plane")
        hashes.add(result["sha256"])
        details.append({
            "dicom_bytes": len(data),
            "dicom_sha256": sha256_bytes(data),
            "member_name": member_name,
            "ordinal": ordinal,
            **result,
        })
        entries.append({
            "bit_width": 16,
            "dataset_id": DATASET_ID,
            "distinct_values": result["distinct_values"],
            "element_size_bytes": 2,
            "endianness": "little",
            "image_laterality": "L",
            "maximum": result["maximum"],
            "minimum": result["minimum"],
            "natural_record_kind": "complete_dicom_mammogram_pixel_plane",
            "numeric_kind": "uint",
            "role": "primary",
            "sample_axes": ["image_y", "image_x"],
            "sample_format": "raw homogeneous little-endian unsigned-int16 mammography plane",
            "sample_geometry": "fixed_2294x1914_mammography_projection",
            "sample_path": output.relative_to(data_root).as_posix(),
            "sample_rank": 2,
            "sample_shape": [ROWS, COLUMNS],
            "sample_size_bytes": len(payload),
            "semantic_field": "mammography_for_presentation_pixel_data",
            "series_id": SERIES_ID,
            "sha256": result["sha256"],
            "source_archive": archive.relative_to(data_root).as_posix(),
            "source_member": member_name,
            "source_variable": "Pixel Data (7FE0,0010)",
            "transition_count": result["transition_count"],
            "value_count": result["value_count"],
            "zero_count": result["zero_count"],
        })
    expected_names = {f"left_mammogram_{ordinal:02d}.bin" for ordinal in (1, 2)}
    if {path.name for path in samples_dir.glob("*.bin")} != expected_names:
        raise ValueError("sample directory differs from selected image inventory")
    if sum(int(entry["value_count"]) for entry in entries) != EXPECTED_PRIMARY_VALUES:
        raise ValueError("aggregate mammography value count changed")
    if sum(int(entry["sample_size_bytes"]) for entry in entries) != EXPECTED_PRIMARY_BYTES:
        raise ValueError("aggregate mammography byte count changed")
    stats = {
        "candidate_id": DATASET_ID,
        "dicom_source_bytes": sum(int(detail["dicom_bytes"]) for detail in details),
        "global_maximum": max(int(entry["maximum"]) for entry in entries),
        "global_minimum": min(int(entry["minimum"]) for entry in entries),
        "images": len(entries),
        "primary_bytes": EXPECTED_PRIMARY_BYTES,
        "primary_values": EXPECTED_PRIMARY_VALUES,
        "records": details,
        "series_id": SERIES_ID,
        "total_transition_count": sum(int(entry["transition_count"]) for entry in entries),
        "total_zero_count": sum(int(entry["zero_count"]) for entry in entries),
        "values_per_image": VALUES_PER_IMAGE,
    }
    return entries, stats


def write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")
    temporary.replace(path)


def write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def read_jsonl(path: Path) -> list[dict[str, object]]:
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("build", "verify"))
    parser.add_argument("--download-dir", type=Path, required=True)
    parser.add_argument("--samples-dir", type=Path, required=True)
    parser.add_argument("--index", type=Path, required=True)
    parser.add_argument("--stats", type=Path, required=True)
    parser.add_argument("--data-root", type=Path, required=True)
    args = parser.parse_args()
    if args.mode == "verify" and not args.samples_dir.is_dir():
        raise SystemExit("missing built sample directory")
    entries, stats = collect(
        mode=args.mode,
        download_dir=args.download_dir,
        samples_dir=args.samples_dir,
        data_root=args.data_root,
    )
    if args.mode == "build":
        write_jsonl(args.index, entries)
        write_json(args.stats, stats)
    else:
        if read_jsonl(args.index) != entries:
            raise SystemExit("sample index differs from independent DICOM decode")
        if json.loads(args.stats.read_text(encoding="utf-8")) != stats:
            raise SystemExit("ingest stats differ from independent DICOM decode")
    print(
        f"mode={args.mode} images={stats['images']} primary_values={stats['primary_values']} "
        f"primary_bytes={stats['primary_bytes']} transitions={stats['total_transition_count']}"
    )


if __name__ == "__main__":
    main()
