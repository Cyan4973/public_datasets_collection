#!/usr/bin/env python3
"""Strict extraction and verification of native-uint16 TCIA PET volumes."""

from __future__ import annotations

import argparse
from array import array
import csv
import hashlib
import json
import math
from pathlib import Path
import shutil
import statistics
import struct
import sys
import tomllib
import zipfile
import zlib


PET_IMAGE_STORAGE = "1.2.840.10008.5.1.4.1.1.128"
TRANSFER_SYNTAXES = {
    "1.2.840.10008.1.2": ("<", False, "little"),
    "1.2.840.10008.1.2.1": ("<", True, "little"),
    "1.2.840.10008.1.2.2": (">", True, "big"),
}
EXPECTED = {
    "01": ("1.3.6.1.4.1.14519.5.2.1.6655.2359.139687047425239659671031900378", 136),
    "02": ("1.3.6.1.4.1.14519.5.2.1.6655.2359.172915770919067984477698394110", 145),
    "03": ("1.3.6.1.4.1.14519.5.2.1.6655.2359.226901752069119903728752256048", 171),
}
DATASET_ID = "tcia_lung_pet_ct_dx_u16"
SERIES_ID = "whole_body_pet_activity_u16"
EXPECTED_VALUES = 18_080_000
EXPECTED_BYTES = 36_160_000
LONG_VR = {b"OB", b"OD", b"OF", b"OL", b"OW", b"SQ", b"UC", b"UR", b"UT", b"UN"}


def spans(
    data: bytes, tag: tuple[int, int], *, endian: str, explicit: bool, limit: int
) -> list[tuple[int, int, int]]:
    pattern = struct.pack(endian + "HH", *tag)
    found = []
    offset = 132 if data[128:132] == b"DICM" else 0
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
                    length = struct.unpack_from(endian + "I", data, offset + 8)[0]
                else:
                    value_offset = offset + 8
                    length = struct.unpack_from(endian + "H", data, offset + 6)[0]
            else:
                value_offset = offset + 8
                length = struct.unpack_from(endian + "I", data, offset + 4)[0]
        except struct.error:
            return found
        if length != 0xFFFFFFFF and value_offset + length <= len(data):
            found.append((offset, value_offset, length))
        offset += 2


def unique_text(
    data: bytes,
    tag: tuple[int, int],
    *,
    endian: str,
    explicit: bool,
    limit: int,
    max_length: int = 256,
    expected: str | None = None,
) -> str | None:
    values = set()
    for _, value_offset, length in spans(data, tag, endian=endian, explicit=explicit, limit=limit):
        if not 0 < length <= max_length:
            continue
        raw = data[value_offset : value_offset + length]
        if all(byte in (0, 9, 10, 13, 27) or 32 <= byte <= 126 for byte in raw):
            values.add(raw.decode("ascii", errors="strict").strip("\0 "))
    values.discard("")
    if expected is not None:
        if expected not in values:
            raise ValueError(
                f"expected DICOM text tag {tag} value {expected!r}, found {sorted(values)}"
            )
        return expected
    if len(values) > 1:
        raise ValueError(f"ambiguous DICOM text tag {tag}: {sorted(values)}")
    return next(iter(values), None)


def unique_u16(
    data: bytes, tag: tuple[int, int], *, endian: str, explicit: bool, limit: int
) -> int | None:
    values = {
        struct.unpack_from(endian + "H", data, value_offset)[0]
        for _, value_offset, length in spans(data, tag, endian=endian, explicit=explicit, limit=limit)
        if length == 2
    }
    if len(values) > 1:
        raise ValueError(f"ambiguous DICOM uint16 tag {tag}: {sorted(values)}")
    return next(iter(values), None)


def parse_decimal_list(value: str | None) -> list[float]:
    if value is None:
        return []
    result = [float(part) for part in value.split("\\")]
    if not all(math.isfinite(number) for number in result):
        raise ValueError(f"non-finite DICOM decimal list: {value!r}")
    return result


def parse_slice(data: bytes, expected_series_uid: str, label: str) -> dict[str, object]:
    if len(data) < 132 or data[128:132] != b"DICM":
        raise ValueError(f"{label}: DICOM preamble missing")
    transfer = unique_text(
        data, (0x0002, 0x0010), endian="<", explicit=True, limit=len(data)
    )
    if transfer not in TRANSFER_SYNTAXES:
        raise ValueError(f"{label}: compressed or unsupported transfer syntax {transfer!r}")
    endian, explicit, endianness = TRANSFER_SYNTAXES[str(transfer)]
    pixel_candidates = spans(
        data, (0x7FE0, 0x0010), endian=endian, explicit=explicit, limit=len(data)
    )
    if len(pixel_candidates) != 1:
        raise ValueError(f"{label}: expected one native Pixel Data field, found {len(pixel_candidates)}")
    pixel_tag_offset, pixel_offset, pixel_length = pixel_candidates[0]

    def text(tag: tuple[int, int], expected: str | None = None) -> str | None:
        return unique_text(
            data,
            tag,
            endian=endian,
            explicit=explicit,
            limit=pixel_tag_offset,
            expected=expected,
        )

    def uint(tag: tuple[int, int]) -> int | None:
        return unique_u16(data, tag, endian=endian, explicit=explicit, limit=pixel_tag_offset)

    if text((0x0008, 0x0016)) != PET_IMAGE_STORAGE:
        raise ValueError(f"{label}: not PET Image Storage")
    if text((0x0008, 0x0060)) != "PT" or text(
        (0x0020, 0x000E), expected_series_uid
    ) != expected_series_uid:
        raise ValueError(f"{label}: modality or SeriesInstanceUID mismatch")
    rows = uint((0x0028, 0x0010))
    columns = uint((0x0028, 0x0011))
    samples = uint((0x0028, 0x0002))
    bits_allocated = uint((0x0028, 0x0100))
    bits_stored = uint((0x0028, 0x0101))
    high_bit = uint((0x0028, 0x0102))
    pixel_representation = uint((0x0028, 0x0103))
    if not rows or not columns:
        raise ValueError(f"{label}: missing geometry")
    if samples != 1 or bits_allocated != 16 or pixel_representation not in (0, 1):
        raise ValueError(
            f"{label}: not native single-channel 16-bit pixels: "
            f"{samples=}, {bits_allocated=}, {pixel_representation=}"
        )
    if bits_stored is None or high_bit is None or not (1 <= bits_stored <= 16) or high_bit != bits_stored - 1:
        raise ValueError(f"{label}: inconsistent stored-bit declaration")
    if text((0x0028, 0x0004)) not in {"MONOCHROME1", "MONOCHROME2"}:
        raise ValueError(f"{label}: unsupported photometric interpretation")
    expected_length = rows * columns * 2
    if pixel_length != expected_length:
        raise ValueError(f"{label}: Pixel Data length {pixel_length} != {expected_length}")
    payload = data[pixel_offset : pixel_offset + pixel_length]
    typecode = "h" if pixel_representation else "H"
    values = array(typecode)
    if values.itemsize != 2:
        raise ValueError("host 16-bit array type unavailable")
    values.frombytes(payload)
    source_little = endianness == "little"
    if (sys.byteorder == "little") != source_little:
        values.byteswap()
    position = parse_decimal_list(text((0x0020, 0x0032)))
    instance_text = text((0x0020, 0x0013))
    if len(position) != 3 or instance_text is None:
        raise ValueError(f"{label}: missing ImagePositionPatient or InstanceNumber")
    slope_text = text((0x0028, 0x1053))
    intercept_text = text((0x0028, 0x1052))
    slope = float(slope_text) if slope_text is not None else 1.0
    intercept = float(intercept_text) if intercept_text is not None else 0.0
    if not math.isfinite(slope) or slope == 0 or not math.isfinite(intercept):
        raise ValueError(f"{label}: invalid rescale transform")
    return {
        "payload": payload,
        "transfer_syntax": transfer,
        "endianness": endianness,
        "rows": rows,
        "columns": columns,
        "bits_stored": bits_stored,
        "high_bit": high_bit,
        "pixel_representation": pixel_representation,
        "photometric": text((0x0028, 0x0004)),
        "series_uid": expected_series_uid,
        "study_uid": text((0x0020, 0x000D)),
        "sop_instance_uid": text((0x0008, 0x0018)),
        "instance_number": int(instance_text),
        "position": position,
        "units": text((0x0054, 0x1001)),
        "decay_correction": text((0x0054, 0x1102)),
        "corrected_image": text((0x0028, 0x0051)),
        "rescale_slope": slope,
        "rescale_intercept": intercept,
        "minimum": min(values),
        "maximum": max(values),
        "distinct": len(set(values)),
        "zero_count": values.count(0),
        "transitions": sum(left != right for left, right in zip(values, values[1:])),
    }


def inspect_archive(
    archive: Path, ordinal: str, uid: str, expected_images: int
) -> tuple[dict[str, object], bytes]:
    if not zipfile.is_zipfile(archive):
        raise ValueError(f"not a ZIP archive: {archive}")
    slices: list[dict[str, object]] = []
    source_bytes = 0
    with zipfile.ZipFile(archive) as zf:
        licenses = []
        for member in zf.infolist():
            if member.is_dir():
                continue
            if member.flag_bits & 0x1:
                raise ValueError(f"encrypted member: {archive.name}: {member.filename}")
            data = zf.read(member)
            if data[128:132] == b"DICM":
                source_bytes += len(data)
                slices.append(parse_slice(data, uid, f"{archive.name}:{member.filename}"))
            elif Path(member.filename).name.upper() == "LICENSE":
                licenses.append(data.decode("utf-8", "replace"))
        if len(licenses) != 1 or "CC BY 4.0" not in licenses[0]:
            raise ValueError(f"embedded CC BY 4.0 license missing: {archive}")
    if len(slices) != expected_images:
        raise ValueError(f"slice count changed: {archive.name}: {len(slices)}/{expected_images}")
    invariant_keys = (
        "transfer_syntax",
        "endianness",
        "rows",
        "columns",
        "bits_stored",
        "high_bit",
        "pixel_representation",
        "photometric",
        "series_uid",
        "study_uid",
        "units",
        "decay_correction",
        "corrected_image",
    )
    invariants = {key: {str(item[key]) for item in slices} for key in invariant_keys}
    changed = {key: values for key, values in invariants.items() if len(values) != 1}
    if changed:
        raise ValueError(f"series invariants vary: {archive.name}: {changed}")
    positions = [tuple(float(value) for value in item["position"]) for item in slices]
    instances = [int(item["instance_number"]) for item in slices]
    sop_uids = [str(item["sop_instance_uid"]) for item in slices]
    if len(set(positions)) != len(slices) or len(set(instances)) != len(slices) or len(set(sop_uids)) != len(slices):
        raise ValueError(f"duplicate PET slice identity or position: {archive.name}")
    ordered = sorted(slices, key=lambda item: tuple(float(value) for value in item["position"]))
    payload = b"".join(bytes(item["payload"]) for item in ordered)
    all_min = min(int(item["minimum"]) for item in slices)
    all_max = max(int(item["maximum"]) for item in slices)
    slopes = {float(item["rescale_slope"]) for item in slices}
    intercepts = {float(item["rescale_intercept"]) for item in slices}
    return {
        "ordinal": ordinal,
        "series_uid": uid,
        "study_uid": next(iter(invariants["study_uid"])),
        "archive_bytes": archive.stat().st_size,
        "dicom_source_bytes": source_bytes,
        "slices": len(slices),
        "rows": int(next(iter(invariants["rows"]))),
        "columns": int(next(iter(invariants["columns"]))),
        "values": len(payload) // 2,
        "payload_bytes": len(payload),
        "pixel_representation": int(next(iter(invariants["pixel_representation"]))),
        "numeric_kind": "int" if int(next(iter(invariants["pixel_representation"]))) else "uint",
        "bits_stored": int(next(iter(invariants["bits_stored"]))),
        "endianness": next(iter(invariants["endianness"])),
        "transfer_syntax": next(iter(invariants["transfer_syntax"])),
        "photometric": next(iter(invariants["photometric"])),
        "units": next(iter(invariants["units"])),
        "decay_correction": next(iter(invariants["decay_correction"])),
        "corrected_image": next(iter(invariants["corrected_image"])),
        "distinct_rescale_slopes": len(slopes),
        "minimum_rescale_slope": min(slopes),
        "maximum_rescale_slope": max(slopes),
        "distinct_rescale_intercepts": len(intercepts),
        "minimum_rescale_intercept": min(intercepts),
        "maximum_rescale_intercept": max(intercepts),
        "rescale_slopes": [float(item["rescale_slope"]) for item in ordered],
        "rescale_intercepts": [float(item["rescale_intercept"]) for item in ordered],
        "minimum": all_min,
        "maximum": all_max,
        "minimum_slice_distinct": min(int(item["distinct"]) for item in slices),
        "maximum_slice_distinct": max(int(item["distinct"]) for item in slices),
        "zero_count": sum(int(item["zero_count"]) for item in slices),
        "transition_count": sum(int(item["transitions"]) for item in slices),
        "payload_sha256": hashlib.sha256(payload).hexdigest(),
        "zlib_ratio": round(len(zlib.compress(payload, 9)) / len(payload), 6),
        "position_first": ordered[0]["position"],
        "position_last": ordered[-1]["position"],
    }, payload


def source_volumes(download_dir: Path) -> list[tuple[dict[str, object], bytes, Path]]:
    expected_names = {
        f"{ordinal}_{uid}.zip" for ordinal, (uid, _) in EXPECTED.items()
    }
    actual_names = {path.name for path in download_dir.glob("*.zip")}
    if actual_names != expected_names:
        raise ValueError(
            f"archive set mismatch missing={sorted(expected_names-actual_names)} "
            f"extra={sorted(actual_names-expected_names)}"
        )
    volumes = []
    for ordinal, (uid, images) in EXPECTED.items():
        archive = download_dir / f"{ordinal}_{uid}.zip"
        row, payload = inspect_archive(archive, ordinal, uid, images)
        volumes.append((row, payload, archive))
    if len({str(row["numeric_kind"]) for row, _, _ in volumes}) != 1 or volumes[0][0]["numeric_kind"] != "uint":
        raise ValueError("selected PET series are not uniformly uint16")
    if len({str(row["endianness"]) for row, _, _ in volumes}) != 1 or volumes[0][0]["endianness"] != "little":
        raise ValueError("selected PET series are not uniformly little-endian")
    return volumes


def build(data_root: Path) -> None:
    volumes = source_volumes(data_root / "downloads" / DATASET_ID)
    sample_dir = data_root / "samples" / DATASET_ID / SERIES_ID
    index_dir = data_root / "index" / DATASET_ID
    filtered_dir = data_root / "filtered" / DATASET_ID
    for target in (sample_dir, index_dir, filtered_dir):
        if target.exists():
            shutil.rmtree(target)
        target.mkdir(parents=True, exist_ok=True)
    rows = []
    for volume, payload, archive in volumes:
        output = sample_dir / f"{volume['ordinal']}.bin"
        output.write_bytes(payload)
        rows.append(
            {
                "dataset_id": DATASET_ID,
                "series_id": SERIES_ID,
                "role": "primary",
                "sample_path": str(output.relative_to(data_root)),
                "numeric_kind": "uint",
                "bit_width": 16,
                "endianness": "little",
                "element_size_bytes": 2,
                "sample_size_bytes": len(payload),
                "value_count": len(payload) // 2,
                "sample_geometry": "3d_pet_volume",
                "sample_rank": 3,
                "sample_shape": [volume["slices"], volume["rows"], volume["columns"]],
                "sample_axes": ["z", "y", "x"],
                "natural_record_kind": "complete_dicom_pet_series",
                "source_archive": str(archive.relative_to(data_root)),
                "series_instance_uid": volume["series_uid"],
                "study_instance_uid": volume["study_uid"],
                "transfer_syntax_uid": volume["transfer_syntax"],
                "units": volume["units"],
                "decay_correction": volume["decay_correction"],
                "corrected_image": volume["corrected_image"],
                "rescale_slopes": volume["rescale_slopes"],
                "rescale_intercepts": volume["rescale_intercepts"],
                "minimum_stored_value": volume["minimum"],
                "maximum_stored_value": volume["maximum"],
                "zero_count": volume["zero_count"],
                "transition_count": volume["transition_count"],
                "sha256": hashlib.sha256(payload).hexdigest(),
            }
        )
    total_values = sum(int(row["value_count"]) for row in rows)
    total_bytes = sum(int(row["sample_size_bytes"]) for row in rows)
    if len(rows) != 3 or total_values != EXPECTED_VALUES or total_bytes != EXPECTED_BYTES:
        raise ValueError(
            f"aggregate output changed samples={len(rows)} values={total_values} bytes={total_bytes}"
        )
    with (index_dir / "samples.jsonl").open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")
    stats = {
        "dataset_id": DATASET_ID,
        "series_id": SERIES_ID,
        "sample_count": len(rows),
        "primary_values": total_values,
        "primary_bytes": total_bytes,
        "sample_shapes": [row["sample_shape"] for row in rows],
        "unique_sample_sizes": len({int(row["sample_size_bytes"]) for row in rows}),
    }
    (filtered_dir / "ingest_stats.json").write_text(
        json.dumps(stats, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(stats, indent=2, sort_keys=True))


def verify(data_root: Path, manifest_path: Path) -> None:
    manifest = tomllib.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("dataset_id") != DATASET_ID:
        raise ValueError("manifest dataset identity mismatch")
    series = manifest.get("series", [])
    if not isinstance(series, list) or len(series) != 1:
        raise ValueError("manifest must contain exactly one series")
    declared = series[0]
    if (
        declared.get("id") != SERIES_ID
        or declared.get("numeric_kind") != "uint"
        or declared.get("bit_width") != 16
        or declared.get("endianness") != "little"
        or declared.get("sample_count") != 3
        or declared.get("total_size_bytes") != EXPECTED_BYTES
    ):
        raise ValueError("manifest series declaration changed")
    volumes = source_volumes(data_root / "downloads" / DATASET_ID)
    index_path = data_root / "index" / DATASET_ID / "samples.jsonl"
    rows = [json.loads(line) for line in index_path.read_text(encoding="utf-8").splitlines()]
    if len(rows) != 3:
        raise ValueError("sample index count changed")
    expected_paths = set()
    for row, (volume, payload, _) in zip(rows, volumes, strict=True):
        sample_path = str(row["sample_path"])
        sample = data_root / sample_path
        if not sample.is_file() or sample.read_bytes() != payload:
            raise ValueError(f"sample differs from ordered source Pixel Data: {sample_path}")
        if (
            row.get("dataset_id") != DATASET_ID
            or row.get("series_id") != SERIES_ID
            or row.get("numeric_kind") != "uint"
            or row.get("bit_width") != 16
            or row.get("endianness") != "little"
            or row.get("element_size_bytes") != 2
            or row.get("value_count") != volume["values"]
            or row.get("sample_size_bytes") != len(payload)
            or row.get("sample_shape") != [volume["slices"], volume["rows"], volume["columns"]]
            or row.get("rescale_slopes") != volume["rescale_slopes"]
            or row.get("sha256") != hashlib.sha256(payload).hexdigest()
        ):
            raise ValueError(f"index metadata mismatch: {sample_path}")
        expected_paths.add(sample_path)
    actual_paths = {
        str(path.relative_to(data_root))
        for path in (data_root / "samples" / DATASET_ID / SERIES_ID).glob("*.bin")
        if path.is_file()
    }
    if actual_paths != expected_paths:
        raise ValueError("sample directory contains missing or extra outputs")
    print(f"verify_ok series=3 slices=452 values={EXPECTED_VALUES} bytes={EXPECTED_BYTES}")


def inspect(download_dir: Path, output_dir: Path) -> None:
    rows = []
    for row, _, _ in source_volumes(download_dir):
        rows.append(row)
        print(
            f"ok ordinal={row['ordinal']} slices={row['slices']} shape="
            f"{row['slices']}x{row['rows']}x{row['columns']} kind={row['numeric_kind']} "
            f"stored_bits={row['bits_stored']} range={row['minimum']}..{row['maximum']} "
            f"units={row['units']!r} zlib_ratio={row['zlib_ratio']}"
        )
    output_dir.mkdir(parents=True, exist_ok=True)
    columns = tuple(rows[0].keys())
    with (output_dir / "pet_probe.tsv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)
    summary = {
        "series": len(rows),
        "slices": sum(int(row["slices"]) for row in rows),
        "values": sum(int(row["values"]) for row in rows),
        "payload_bytes": sum(int(row["payload_bytes"]) for row in rows),
        "numeric_kind": rows[0]["numeric_kind"],
        "endianness": rows[0]["endianness"],
        "observed_bits_stored": sorted({int(row["bits_stored"]) for row in rows}),
        "distinct_volume_shapes": len({(int(row["slices"]), int(row["rows"]), int(row["columns"])) for row in rows}),
        "minimum_zlib_ratio": min(float(row["zlib_ratio"]) for row in rows),
        "median_zlib_ratio": statistics.median(float(row["zlib_ratio"]) for row in rows),
        "maximum_zlib_ratio": max(float(row["zlib_ratio"]) for row in rows),
    }
    (output_dir / "pet_probe_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, indent=2, sort_keys=True))


def main() -> None:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    inspect_parser = subparsers.add_parser("inspect")
    inspect_parser.add_argument("--download-dir", type=Path, required=True)
    inspect_parser.add_argument("--output-dir", type=Path, required=True)
    build_parser = subparsers.add_parser("build")
    build_parser.add_argument("--data-root", type=Path, required=True)
    verify_parser = subparsers.add_parser("verify")
    verify_parser.add_argument("--data-root", type=Path, required=True)
    verify_parser.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "inspect":
        inspect(args.download_dir, args.output_dir)
    elif args.command == "build":
        build(args.data_root)
    elif args.command == "verify":
        verify(args.data_root, args.manifest)


if __name__ == "__main__":
    main()
