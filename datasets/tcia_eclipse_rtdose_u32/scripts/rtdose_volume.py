#!/usr/bin/env python3
from __future__ import annotations

import argparse
from array import array
import hashlib
import json
import math
from pathlib import Path
import shutil
import statistics
import struct
import sys
import zipfile


DATASET_ID = "tcia_eclipse_rtdose_u32"
SERIES_ID = "eclipse_physical_dose_grid_u32"
# DICOM UID for RT Dose Storage.
RTDOSE_SOP_CLASS = "1.2.840.10008.5.1.4.1.1.481.2"
TRANSFER_SYNTAX = "1.2.840.10008.1.2"
EXPECTED = {
    "01": "1.3.6.1.4.1.14519.5.2.1.337132488476568438964794321553967230469",
    "02": "1.3.6.1.4.1.14519.5.2.1.132957944596075614237465645641313092885",
    "03": "1.3.6.1.4.1.14519.5.2.1.277895508499534253640451142336498460409",
}
LONG_VR = {b"OB", b"OD", b"OF", b"OL", b"OW", b"SQ", b"UC", b"UR", b"UT", b"UN"}


def spans(
    data: bytes, tag: tuple[int, int], *, explicit: bool, limit: int
) -> list[tuple[int, int, int]]:
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
                vr = data[offset + 4 : offset + 6]
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


def unique_text(
    data: bytes,
    tag: tuple[int, int],
    *,
    explicit: bool,
    limit: int,
    max_length: int = 128,
) -> str | None:
    values = set()
    for _, value_offset, length in spans(data, tag, explicit=explicit, limit=limit):
        if not 0 < length <= max_length:
            continue
        raw = data[value_offset : value_offset + length]
        if all(byte in (0, 9, 10, 13) or 32 <= byte <= 126 for byte in raw):
            values.add(raw.decode("ascii").strip("\0 "))
    values.discard("")
    if len(values) > 1:
        raise ValueError(f"ambiguous DICOM text tag {tag}: {sorted(values)}")
    return next(iter(values), None)


def unique_u16(data: bytes, tag: tuple[int, int], *, limit: int) -> int | None:
    values = {
        struct.unpack_from("<H", data, value_offset)[0]
        for _, value_offset, length in spans(data, tag, explicit=False, limit=limit)
        if length == 2
    }
    if len(values) > 1:
        raise ValueError(f"ambiguous DICOM uint16 tag {tag}: {sorted(values)}")
    return next(iter(values), None)


def require_text(data: bytes, tag: tuple[int, int], expected: str, limit: int) -> None:
    actual = unique_text(data, tag, explicit=False, limit=limit)
    if actual != expected:
        raise ValueError(f"DICOM tag {tag} changed: {actual!r} != {expected!r}")


def load_dicom(archive: Path) -> bytes:
    if not zipfile.is_zipfile(archive):
        raise ValueError(f"not a ZIP archive: {archive}")
    with zipfile.ZipFile(archive) as zf:
        members = [member for member in zf.infolist() if not member.is_dir()]
        dicom_members = []
        licenses = []
        for member in members:
            if member.flag_bits & 0x1:
                raise ValueError(f"encrypted ZIP member: {archive}: {member.filename}")
            with zf.open(member) as source:
                head = source.read(132)
            if head[128:132] == b"DICM":
                dicom_members.append(member)
            if Path(member.filename).name.upper() == "LICENSE":
                licenses.append(zf.read(member).decode("utf-8", "replace"))
        if len(dicom_members) != 1:
            raise ValueError(f"expected one DICOM object in {archive}, found {len(dicom_members)}")
        if len(licenses) != 1 or "CC BY 4.0" not in licenses[0]:
            raise ValueError(f"embedded CC BY 4.0 license missing from {archive}")
        return zf.read(dicom_members[0])


def parse_volume(data: bytes, expected_uid: str) -> dict[str, object]:
    if data[128:132] != b"DICM":
        raise ValueError("DICOM preamble missing")
    transfer = unique_text(data, (0x0002, 0x0010), explicit=True, limit=len(data))
    if transfer != TRANSFER_SYNTAX:
        raise ValueError(f"unsupported transfer syntax: {transfer!r}")
    pixel_candidates = [
        span
        for span in spans(data, (0x7FE0, 0x0010), explicit=False, limit=len(data))
        if span[2] >= 100_000
    ]
    if len(pixel_candidates) != 1:
        raise ValueError(f"expected one native Pixel Data field, found {len(pixel_candidates)}")
    pixel_tag_offset, pixel_offset, pixel_length = pixel_candidates[0]
    if pixel_offset + pixel_length != len(data):
        raise ValueError("trailing or truncated bytes around Pixel Data")

    required_text = {
        (0x0008, 0x0016): RTDOSE_SOP_CLASS,
        (0x0008, 0x0060): "RTDOSE",
        (0x0008, 0x0070): "Varian Medical Systems",
        (0x0008, 0x103E): "Eclipse Doses",
        (0x0008, 0x1090): "ARIA RadOnc",
        (0x0018, 0x0015): "ABDOMEN",
        (0x0020, 0x000E): expected_uid,
        (0x0028, 0x0004): "MONOCHROME2",
        (0x3004, 0x0002): "GY",
        (0x3004, 0x0004): "PHYSICAL",
        (0x3004, 0x000A): "PLAN",
    }
    for tag, expected in required_text.items():
        require_text(data, tag, expected, pixel_tag_offset)

    frames_text = unique_text(data, (0x0028, 0x0008), explicit=False, limit=pixel_tag_offset)
    scaling_text = unique_text(data, (0x3004, 0x000E), explicit=False, limit=pixel_tag_offset)
    if frames_text is None or scaling_text is None:
        raise ValueError("missing NumberOfFrames or DoseGridScaling")
    frames = int(frames_text)
    scaling = float(scaling_text)
    if frames <= 1 or not math.isfinite(scaling) or scaling <= 0:
        raise ValueError("invalid frames or DoseGridScaling")
    rows = unique_u16(data, (0x0028, 0x0010), limit=pixel_tag_offset)
    columns = unique_u16(data, (0x0028, 0x0011), limit=pixel_tag_offset)
    samples = unique_u16(data, (0x0028, 0x0002), limit=pixel_tag_offset)
    bits_allocated = unique_u16(data, (0x0028, 0x0100), limit=pixel_tag_offset)
    bits_stored = unique_u16(data, (0x0028, 0x0101), limit=pixel_tag_offset)
    high_bit = unique_u16(data, (0x0028, 0x0102), limit=pixel_tag_offset)
    pixel_representation = unique_u16(data, (0x0028, 0x0103), limit=pixel_tag_offset)
    if not rows or not columns:
        raise ValueError("invalid RTDOSE geometry")
    if (samples, bits_allocated, bits_stored, high_bit, pixel_representation) != (1, 32, 32, 31, 0):
        raise ValueError(
            "not native unsigned 32-bit monochrome data: "
            f"{samples=}, {bits_allocated=}, {bits_stored=}, {high_bit=}, {pixel_representation=}"
        )
    expected_length = frames * rows * columns * 4
    if pixel_length != expected_length:
        raise ValueError(f"Pixel Data length mismatch: {pixel_length} != {expected_length}")
    payload = data[pixel_offset : pixel_offset + pixel_length]
    values = array("I")
    if values.itemsize != 4:
        raise ValueError("host array('I') is not 32-bit")
    values.frombytes(payload)
    if sys.byteorder != "little":
        values.byteswap()
    minimum = min(values)
    maximum = max(values)
    distinct = len(set(values))
    zero_count = values.count(0)
    transitions = sum(left != right for left, right in zip(values, values[1:]))
    if distinct < 10_000 or minimum == maximum or transitions < len(values) // 10:
        raise ValueError("degenerate dose grid")
    return {
        "payload": payload,
        "shape": [frames, rows, columns],
        "dose_grid_scaling": scaling_text,
        "minimum": minimum,
        "maximum": maximum,
        "distinct_values": distinct,
        "zero_count": zero_count,
        "transitions": transitions,
        "sha256": hashlib.sha256(payload).hexdigest(),
    }


def source_volumes(download_dir: Path) -> list[tuple[str, str, Path, dict[str, object]]]:
    expected_names = {f"{ordinal}_{uid}.zip" for ordinal, uid in EXPECTED.items()}
    archives = sorted(download_dir.glob("*.zip"))
    if {archive.name for archive in archives} != expected_names:
        raise ValueError(f"download ZIP set mismatch: {sorted(a.name for a in archives)}")
    return [
        (
            ordinal,
            uid,
            download_dir / f"{ordinal}_{uid}.zip",
            parse_volume(load_dicom(download_dir / f"{ordinal}_{uid}.zip"), uid),
        )
        for ordinal, uid in EXPECTED.items()
    ]


def index_rows(data_root: Path, volumes: list[tuple[str, str, Path, dict[str, object]]]) -> list[dict[str, object]]:
    rows = []
    for ordinal, uid, archive, volume in volumes:
        payload = volume["payload"]
        assert isinstance(payload, bytes)
        rows.append({
            "dataset_id": DATASET_ID,
            "series_id": SERIES_ID,
            "role": "primary",
            "sample_path": f"samples/{DATASET_ID}/{SERIES_ID}/{ordinal}.bin",
            "numeric_kind": "uint",
            "bit_width": 32,
            "endianness": "little",
            "element_size_bytes": 4,
            "sample_size_bytes": len(payload),
            "value_count": len(payload) // 4,
            "sample_geometry": "3d_dose_volume",
            "sample_rank": 3,
            "sample_shape": volume["shape"],
            "sample_axes": ["z", "y", "x"],
            "natural_record_kind": "dicom_rtdose_object",
            "source_format": "DICOM RT Dose Storage",
            "source_field": "Pixel Data (7FE0,0010)",
            "source_archive": archive.relative_to(data_root).as_posix(),
            "series_instance_uid": uid,
            "dose_units": "GY",
            "dose_type": "PHYSICAL",
            "dose_summation_type": "PLAN",
            "dose_grid_scaling": volume["dose_grid_scaling"],
            "minimum_stored_value": volume["minimum"],
            "maximum_stored_value": volume["maximum"],
            "distinct_stored_values": volume["distinct_values"],
            "zero_count": volume["zero_count"],
            "transition_count": volume["transitions"],
            "sha256": volume["sha256"],
        })
    return rows


def stats_for(rows: list[dict[str, object]]) -> dict[str, object]:
    sizes = [int(row["sample_size_bytes"]) for row in rows]
    return {
        "dataset_id": DATASET_ID,
        "series_id": SERIES_ID,
        "sample_count": len(rows),
        "primary_bytes": sum(sizes),
        "primary_values": sum(int(row["value_count"]) for row in rows),
        "min_sample_bytes": min(sizes),
        "median_sample_bytes": statistics.median(sizes),
        "max_sample_bytes": max(sizes),
        "unique_sample_sizes": len(set(sizes)),
    }


def build(data_root: Path) -> None:
    volumes = source_volumes(data_root / "downloads" / DATASET_ID)
    rows = index_rows(data_root, volumes)
    sample_dir = data_root / "samples" / DATASET_ID / SERIES_ID
    if sample_dir.exists():
        shutil.rmtree(sample_dir)
    sample_dir.mkdir(parents=True)
    for row, (_, _, _, volume) in zip(rows, volumes, strict=True):
        payload = volume["payload"]
        assert isinstance(payload, bytes)
        (data_root / str(row["sample_path"])).write_bytes(payload)
    index_dir = data_root / "index" / DATASET_ID
    filtered_dir = data_root / "filtered" / DATASET_ID
    index_dir.mkdir(parents=True, exist_ok=True)
    filtered_dir.mkdir(parents=True, exist_ok=True)
    with (index_dir / "samples.jsonl").open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")
    stats = stats_for(rows)
    (filtered_dir / "ingest_stats.json").write_text(
        json.dumps(stats, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(stats, sort_keys=True))


def verify(data_root: Path) -> None:
    volumes = source_volumes(data_root / "downloads" / DATASET_ID)
    expected_index = index_rows(data_root, volumes)
    index_path = data_root / "index" / DATASET_ID / "samples.jsonl"
    actual_index = [json.loads(line) for line in index_path.read_text().splitlines() if line]
    if actual_index != expected_index:
        raise ValueError("sample index does not match independently reparsed sources")
    for row, (_, _, _, volume) in zip(actual_index, volumes, strict=True):
        payload = volume["payload"]
        assert isinstance(payload, bytes)
        if (data_root / row["sample_path"]).read_bytes() != payload:
            raise ValueError(f"sample is not byte-identical to source Pixel Data: {row['sample_path']}")
    expected_stats = stats_for(expected_index)
    stats_path = data_root / "filtered" / DATASET_ID / "ingest_stats.json"
    if json.loads(stats_path.read_text()) != expected_stats:
        raise ValueError("ingest stats mismatch")
    if not 100_000 <= int(expected_stats["primary_bytes"]) <= 1_000_000_000:
        raise ValueError("primary output outside corpus bounds")
    print("verified " + json.dumps(expected_stats, sort_keys=True))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("build", "verify"))
    parser.add_argument("--data-root", type=Path, required=True)
    args = parser.parse_args()
    try:
        (build if args.command == "build" else verify)(args.data_root)
    except (OSError, ValueError, zipfile.BadZipFile, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
