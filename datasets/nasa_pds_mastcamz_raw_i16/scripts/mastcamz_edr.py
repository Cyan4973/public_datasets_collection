#!/usr/bin/env python3
"""Build and independently verify native SignedMSB2 Mastcam-Z EDR frames."""
from __future__ import annotations

import argparse
from array import array
import csv
import hashlib
import json
from pathlib import Path
import re
import sys
import xml.etree.ElementTree as ET


DATASET_ID = "nasa_pds_mastcamz_raw_i16"
SERIES_ID = "mastcamz_edr_detector_i16"
EXPECTED_PRODUCTS = 52
LINES = 1200
SAMPLES = 1648
VALUES_PER_IMAGE = LINES * SAMPLES
BYTES_PER_IMAGE = VALUES_PER_IMAGE * 2
ARRAY_OFFSET = 32_960
FILE_BYTES = ARRAY_OFFSET + BYTES_PER_IMAGE
EXPECTED_PRIMARY_VALUES = EXPECTED_PRODUCTS * VALUES_PER_IMAGE
EXPECTED_PRIMARY_BYTES = EXPECTED_PRODUCTS * BYTES_PER_IMAGE


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def local_name(element: ET.Element) -> str:
    return element.tag.rsplit("}", 1)[-1]


def child_text(parent: ET.Element, name: str) -> str:
    for element in parent.iter():
        if local_name(element) == name and element.text:
            return element.text.strip()
    return ""


def parse_sources(path: Path) -> list[dict[str, object]]:
    with path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    if len(rows) != EXPECTED_PRODUCTS:
        raise SystemExit("source-plan product count changed")
    payload_hashes = {}
    for line in path.with_name("payloads.sha256").read_text(encoding="utf-8").splitlines():
        digest, filename = line.split()
        if not re.fullmatch(r"[0-9a-f]{64}", digest) or filename in payload_hashes:
            raise SystemExit("invalid pinned payload SHA256 plan")
        payload_hashes[filename] = digest
    if set(payload_hashes) != {row["payload_filename"] for row in rows}:
        raise SystemExit("pinned payload SHA256 inventory differs from source plan")
    result = []
    for ordinal, row in enumerate(rows, 1):
        if int(row["ordinal"]) != ordinal:
            raise SystemExit("source-plan order changed")
        if (
            int(row["file_bytes"]) != FILE_BYTES
            or int(row["array_offset"]) != ARRAY_OFFSET
            or int(row["array_bytes"]) != BYTES_PER_IMAGE
            or int(row["lines"]) != LINES
            or int(row["samples"]) != SAMPLES
            or row["data_type"] != "SignedMSB2"
        ):
            raise SystemExit("source-plan image schema changed")
        result.append({
            "label_bytes": int(row["label_bytes"]),
            "label_filename": row["label_filename"],
            "label_sha256": row["label_sha256"],
            "ordinal": ordinal,
            "payload_filename": row["payload_filename"],
            "payload_sha256": payload_hashes[row["payload_filename"]],
            "product_id": row["product_id"],
        })
    return result


def load_inventory(
    download_dir: Path, sources_path: Path, sources: list[dict[str, object]]
) -> list[dict[str, object]]:
    inventory = json.loads((download_dir / "download_inventory.json").read_text(encoding="utf-8"))
    records = inventory.get("records")
    if not isinstance(records, list) or len(records) != EXPECTED_PRODUCTS:
        raise SystemExit("download inventory count changed")
    if inventory.get("label_bytes") != 2_851_659 or inventory.get("payload_bytes") != 207_384_320:
        raise SystemExit("download inventory aggregate sizes changed")
    if inventory.get("source_plan_sha256") != hashlib.sha256(sources_path.read_bytes()).hexdigest():
        raise SystemExit("download inventory was not built from this source plan")
    if inventory.get("payload_hash_plan_sha256") != hashlib.sha256(
        sources_path.with_name("payloads.sha256").read_bytes()
    ).hexdigest():
        raise SystemExit("download inventory was not built from this payload hash plan")
    for source, record in zip(sources, records):
        for key in (
            "ordinal", "product_id", "label_filename", "payload_filename",
            "label_bytes", "payload_sha256",
        ):
            if source[key] != record.get(key):
                raise SystemExit(f"download inventory differs from source plan: {key}")
        label = download_dir / str(source["label_filename"])
        payload = download_dir / str(source["payload_filename"])
        if label.name != source["label_filename"] or payload.name != source["payload_filename"]:
            raise SystemExit("unsafe source filename")
        if label.stat().st_size != source["label_bytes"] or sha256_file(label) != source["label_sha256"]:
            raise SystemExit(f"label identity changed: {label.name}")
        if payload.stat().st_size != record["payload_bytes"] or sha256_file(payload) != source["payload_sha256"]:
            raise SystemExit(f"payload identity changed: {payload.name}")
    return records


def parse_label(path: Path, source: dict[str, object]) -> dict[str, object]:
    root = ET.fromstring(path.read_bytes())
    logical_identifier = child_text(root, "logical_identifier")
    title = child_text(root, "title")
    if logical_identifier.rsplit(":", 1)[-1] != source["product_id"]:
        raise ValueError("PDS logical identifier changed")
    if " edr " not in f" {title.lower()} " or "mars2020" not in logical_identifier:
        raise ValueError("not a Mars 2020 EDR label")
    matches = []
    for area in root.iter():
        if local_name(area) != "File_Area_Observational":
            continue
        filename = child_text(area, "file_name")
        for element in area.iter():
            if local_name(element) != "Array_2D_Image":
                continue
            data_type = child_text(element, "data_type")
            offset = int(child_text(element, "offset"))
            axes = {}
            for axis in element.iter():
                if local_name(axis) == "Axis_Array":
                    axes[child_text(axis, "axis_name").lower()] = int(child_text(axis, "elements"))
            if data_type == "SignedMSB2":
                matches.append((filename, offset, axes, element))
    if len(matches) != 1:
        raise ValueError(f"expected one SignedMSB2 Array_2D_Image, found {len(matches)}")
    filename, offset, axes, array_element = matches[0]
    if filename != source["payload_filename"] or offset != ARRAY_OFFSET:
        raise ValueError("label file reference or array offset changed")
    if axes != {"line": LINES, "sample": SAMPLES}:
        raise ValueError(f"label axes changed: {axes}")
    special = {}
    for element in array_element.iter():
        name = local_name(element)
        if name.endswith("_constant") and element.text:
            value = element.text.strip()
            if re.fullmatch(r"[-+]?\d+", value):
                special[name] = int(value)
    sample_bits = child_text(root, "sample_bits")
    bit_mask = child_text(root, "sample_bit_mask")
    companding_states = {
        element.text.strip()
        for element in root.iter()
        if local_name(element) == "companding_state" and element.text
    }
    companding_algorithms = {
        element.text.strip()
        for element in root.iter()
        if local_name(element) == "processing_algorithm"
        and element.text
        and element.text.strip().upper().startswith("MCZ_LUT")
    }
    if sample_bits != "12" or bit_mask != "2#0000111111111111#":
        raise ValueError("Mastcam-Z sampling representation changed")
    if (
        "Expanded" not in companding_states
        or not companding_algorithms
        or not companding_algorithms <= {"MCZ_LUT0", "MCZ_LUT1"}
    ):
        raise ValueError("Mastcam-Z companding metadata changed")
    return {
        "companding_algorithms": sorted(companding_algorithms),
        "companding_states": sorted(companding_states),
        "sample_bit_mask": bit_mask,
        "sample_bits": int(sample_bits),
        "special_constants": special,
        "title": title,
    }


def decode_image(path: Path) -> tuple[bytes, dict[str, object]]:
    data = path.read_bytes()
    if len(data) != FILE_BYTES:
        raise ValueError("Mastcam-Z IMG size changed")
    source = data[ARRAY_OFFSET:ARRAY_OFFSET + BYTES_PER_IMAGE]
    encoded = bytearray(BYTES_PER_IMAGE)
    encoded[0::2] = source[1::2]
    encoded[1::2] = source[0::2]
    output = bytes(encoded)
    values = array("h")
    values.frombytes(output)
    if sys.byteorder != "little":
        values.byteswap()
    distinct = len(set(values))
    transitions = sum(left != right for left, right in zip(values, values[1:]))
    # Expanded hardware-companded EDRs can legitimately use only a small subset
    # of the 12-bit DN codes. Require spatial variation and a useful value range
    # instead of assuming a minimum codebook size.
    if (
        len(values) != VALUES_PER_IMAGE
        or distinct < 8
        or max(values) - min(values) < 128
        or transitions < 10_000
    ):
        raise ValueError("degenerate Mastcam-Z EDR image")
    return output, {
        "distinct_values": distinct,
        "maximum": max(values),
        "minimum": min(values),
        "negative_count": sum(value < 0 for value in values),
        "sha256": hashlib.sha256(output).hexdigest(),
        "transition_count": transitions,
        "value_count": len(values),
        "zero_count": values.count(0),
    }


def collect(
    *,
    mode: str,
    sources_path: Path,
    download_dir: Path,
    samples_dir: Path,
    data_root: Path,
) -> tuple[list[dict[str, object]], dict[str, object]]:
    sources = parse_sources(sources_path)
    inventory = load_inventory(download_dir, sources_path, sources)
    if mode == "build":
        if samples_dir.exists():
            for path in samples_dir.glob("*.bin"):
                path.unlink()
        samples_dir.mkdir(parents=True, exist_ok=True)
    entries = []
    details = []
    hashes = set()
    for source, record in zip(sources, inventory):
        label_path = download_dir / str(source["label_filename"])
        payload_path = download_dir / str(source["payload_filename"])
        label = parse_label(label_path, source)
        decoded, result = decode_image(payload_path)
        output = samples_dir / f"{source['product_id']}.bin"
        if mode == "build":
            output.write_bytes(decoded)
        elif output.read_bytes() != decoded:
            raise ValueError(f"built sample differs from source image: {output.name}")
        if result["sha256"] in hashes:
            raise ValueError("duplicate complete Mastcam-Z EDR image")
        hashes.add(result["sha256"])
        camera = "left" if str(source["product_id"]).startswith("zl") else "right"
        filter_number = int(str(source["product_id"])[2])
        details.append({
            "camera": camera,
            "companding_algorithms": label["companding_algorithms"],
            "companding_states": label["companding_states"],
            "filter_number": filter_number,
            "label_sha256": source["label_sha256"],
            "ordinal": source["ordinal"],
            "payload_sha256": record["payload_sha256"],
            "product_id": source["product_id"],
            "sample_bit_mask": label["sample_bit_mask"],
            "sample_bits": label["sample_bits"],
            "special_constants": label["special_constants"],
            **result,
        })
        entries.append({
            "bit_width": 16,
            "camera": camera,
            "dataset_id": DATASET_ID,
            "distinct_values": result["distinct_values"],
            "element_size_bytes": 2,
            "endianness": "little",
            "filter_number": filter_number,
            "maximum": result["maximum"],
            "minimum": result["minimum"],
            "natural_record_kind": "complete_mastcamz_edr_detector_frame",
            "negative_count": result["negative_count"],
            "numeric_kind": "int",
            "product_id": source["product_id"],
            "role": "primary",
            "sample_axes": ["detector_line", "detector_sample"],
            "sample_format": "raw homogeneous little-endian signed-int16 detector plane",
            "sample_geometry": "fixed_1200x1648_mastcamz_edr_frame",
            "sample_path": output.relative_to(data_root).as_posix(),
            "sample_rank": 2,
            "sample_shape": [LINES, SAMPLES],
            "sample_size_bytes": len(decoded),
            "semantic_field": "mastcamz_edr_detector_dn",
            "series_id": SERIES_ID,
            "sha256": result["sha256"],
            "source_sample": payload_path.relative_to(data_root).as_posix(),
            "source_variable": "PDS4 Array_2D_Image",
            "transition_count": result["transition_count"],
            "value_count": result["value_count"],
            "zero_count": result["zero_count"],
        })
    expected_names = {f"{source['product_id']}.bin" for source in sources}
    if {path.name for path in samples_dir.glob("*.bin")} != expected_names:
        raise SystemExit("sample directory differs from source plan")
    if sum(int(entry["value_count"]) for entry in entries) != EXPECTED_PRIMARY_VALUES:
        raise SystemExit("aggregate EDR value count changed")
    if sum(int(entry["sample_size_bytes"]) for entry in entries) != EXPECTED_PRIMARY_BYTES:
        raise SystemExit("aggregate EDR byte count changed")
    stats = {
        "candidate_id": DATASET_ID,
        "global_maximum": max(int(entry["maximum"]) for entry in entries),
        "global_minimum": min(int(entry["minimum"]) for entry in entries),
        "images": len(entries),
        "primary_bytes": EXPECTED_PRIMARY_BYTES,
        "primary_values": EXPECTED_PRIMARY_VALUES,
        "records": details,
        "series_id": SERIES_ID,
        "source_bytes": sum(int(record["payload_bytes"]) for record in inventory),
        "total_negative_count": sum(int(entry["negative_count"]) for entry in entries),
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
    parser.add_argument("--sources", type=Path, required=True)
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
        sources_path=args.sources,
        download_dir=args.download_dir,
        samples_dir=args.samples_dir,
        data_root=args.data_root,
    )
    if args.mode == "build":
        write_jsonl(args.index, entries)
        write_json(args.stats, stats)
    else:
        if read_jsonl(args.index) != entries:
            raise SystemExit("sample index differs from independent source decode")
        if json.loads(args.stats.read_text(encoding="utf-8")) != stats:
            raise SystemExit("ingest stats differ from independent source decode")
    print(
        f"mode={args.mode} images={stats['images']} primary_values={stats['primary_values']} "
        f"primary_bytes={stats['primary_bytes']} transitions={stats['total_transition_count']}"
    )


if __name__ == "__main__":
    main()
