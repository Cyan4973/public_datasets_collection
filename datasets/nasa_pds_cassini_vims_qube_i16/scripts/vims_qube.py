#!/usr/bin/env python3
"""Build and independently verify Cassini VIMS PDS3 QUBE cores."""
from __future__ import annotations

import argparse
from array import array
import hashlib
import json
from math import prod
from pathlib import Path
import re
import sys


DATASET_ID = "nasa_pds_cassini_vims_qube_i16"
SERIES_ID = "cassini_vims_core_i16"
EXPECTED_PRODUCTS = 120
EXPECTED_SOURCE_BYTES = 194_715_648
EXPECTED_PLANNED_CORE_BYTES = 179_397_504
EXPECTED_PLANNED_VALUES = 89_698_752
EXPECTED_TARGETS = {
    "ATLAS": 1,
    "BESTLA": 1,
    "SATURN": 39,
    "SKY": 32,
    "SUN": 8,
    "TITAN": 38,
    "UNK": 1,
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def pds_value(text: str, key: str) -> str:
    match = re.search(
        rf"(?im)^\s*{re.escape(key)}\s*=\s*(\([^)]*\)|[^\r\n]*)", text
    )
    return match.group(1).strip().strip('"') if match else ""


def tuple_tokens(value: str) -> list[str]:
    if not value:
        return []
    return [
        token.strip().strip('"')
        for token in value.strip().strip("()").split(",")
        if token.strip()
    ]


def scalar_int(value: str) -> int:
    match = re.fullmatch(r"([-+]?\d+)(?:\s*<[^>]+>)?", value.strip())
    if not match:
        raise ValueError(f"not a scalar PDS integer: {value}")
    return int(match.group(1))


def tuple_ints(value: str) -> list[int]:
    return [scalar_int(token) for token in tuple_tokens(value)]


def read_label(path: Path) -> str:
    data = bytearray()
    with path.open("rb") as handle:
        while len(data) < 1_000_000:
            chunk = handle.read(512)
            if not chunk:
                break
            data.extend(chunk)
            text = data.decode("latin-1", "replace")
            match = re.search(r"(?m)^END\s*\r?$", text)
            if match:
                return text[:match.end()] + "\n"
    raise ValueError("PDS3 END marker absent before QUBE data")


def pointer_record(value: str, filename: str) -> int:
    if value.strip().startswith("("):
        tokens = tuple_tokens(value)
        if len(tokens) != 2 or tokens[0].lower() != filename.lower():
            raise ValueError(f"unsupported detached QUBE pointer: {value}")
        return scalar_int(tokens[1])
    return scalar_int(value)


def parse_schema(path: Path) -> dict[str, object]:
    text = read_label(path)
    data_set_id = pds_value(text, "DATA_SET_ID").upper()
    host_id = pds_value(text, "INSTRUMENT_HOST_ID").upper()
    host_name = pds_value(text, "INSTRUMENT_HOST_NAME").upper()
    if (
        not data_set_id.startswith("CO-")
        or "VIMS" not in data_set_id
        or pds_value(text, "INSTRUMENT_ID").upper() != "VIMS"
        or not (host_id == "CO" or "CASSINI" in host_name)
    ):
        raise ValueError("source is not a Cassini VIMS QUBE")
    if not re.search(r"(?im)^\s*OBJECT\s*=\s*QUBE\s*$", text):
        raise ValueError("PDS3 QUBE object missing")
    axes = [token.upper() for token in tuple_tokens(pds_value(text, "AXIS_NAME"))]
    core_items = tuple_ints(pds_value(text, "CORE_ITEMS"))
    suffix_items = tuple_ints(pds_value(text, "SUFFIX_ITEMS"))
    if axes != ["SAMPLE", "BAND", "LINE"] or len(core_items) != 3:
        raise ValueError(f"unsupported VIMS QUBE axis order: {axes}/{core_items}")
    if len(suffix_items) != 3 or any(value < 0 for value in suffix_items):
        raise ValueError("invalid VIMS suffix geometry")
    if scalar_int(pds_value(text, "CORE_ITEM_BYTES")) != 2:
        raise ValueError("VIMS core is not 16-bit")
    if pds_value(text, "CORE_ITEM_TYPE").upper() != "SUN_INTEGER":
        raise ValueError("VIMS core is not big-endian signed integer")
    suffix_bytes = scalar_int(pds_value(text, "SUFFIX_BYTES"))
    if not 0 < suffix_bytes <= 16:
        raise ValueError("invalid VIMS suffix width")
    record_bytes = scalar_int(pds_value(text, "RECORD_BYTES"))
    pointer = pointer_record(pds_value(text, "^QUBE"), path.name.split("_", 1)[1])
    core_offset = (pointer - 1) * record_bytes
    value_count = prod(core_items)
    core_bytes = value_count * 2
    expanded_items = [core + suffix for core, suffix in zip(core_items, suffix_items)]
    suffix_value_count = prod(expanded_items) - value_count
    qube_bytes = core_bytes + suffix_value_count * suffix_bytes
    special = {
        key.lower(): pds_value(text, key)
        for key in (
            "CORE_NULL", "CORE_LOW_REPR_SATURATION", "CORE_LOW_INSTR_SATURATION",
            "CORE_HIGH_REPR_SATURATION", "CORE_HIGH_INSTR_SATURATION",
            "CORE_VALID_MINIMUM", "CORE_BASE", "CORE_MULTIPLIER",
        )
        if pds_value(text, key)
    }
    return {
        "axes": axes,
        "bands": core_items[1],
        "core_bytes": core_bytes,
        "core_items": core_items,
        "core_offset": core_offset,
        "file_bytes": path.stat().st_size,
        "lines": core_items[2],
        "product_id": pds_value(text, "PRODUCT_ID") or path.stem,
        "qube_bytes": qube_bytes,
        "samples": core_items[0],
        "special_constants": special,
        "start_time": pds_value(text, "START_TIME"),
        "suffix_bytes": suffix_bytes,
        "suffix_items": suffix_items,
        "suffix_value_count": suffix_value_count,
        "target_name": pds_value(text, "TARGET_NAME"),
        "value_count": value_count,
    }


def extract_core(path: Path, schema: dict[str, object]) -> bytes:
    samples, bands, lines = (int(value) for value in schema["core_items"])
    sample_suffix, band_suffix, line_suffix = (
        int(value) for value in schema["suffix_items"]
    )
    suffix_bytes = int(schema["suffix_bytes"])
    output = bytearray(int(schema["core_bytes"]))
    output_offset = 0
    with path.open("rb") as handle:
        handle.seek(int(schema["core_offset"]))
        for _line in range(lines):
            for _band in range(bands):
                count = samples * 2
                chunk = handle.read(count)
                if len(chunk) != count:
                    raise ValueError("truncated VIMS core row")
                output[output_offset:output_offset + count] = chunk
                output_offset += count
                handle.seek(sample_suffix * suffix_bytes, 1)
            handle.seek(band_suffix * (samples + sample_suffix) * suffix_bytes, 1)
        handle.seek(
            line_suffix * (bands + band_suffix) * (samples + sample_suffix) * suffix_bytes,
            1,
        )
        consumed = handle.tell() - int(schema["core_offset"])
    if consumed != int(schema["qube_bytes"]) or output_offset != len(output):
        raise ValueError(
            f"VIMS QUBE traversal mismatch: consumed={consumed} expected={schema['qube_bytes']}"
        )
    output[0::2], output[1::2] = output[1::2], output[0::2]
    return bytes(output)


def sample_stats(data: bytes) -> dict[str, object]:
    values = array("h")
    values.frombytes(data)
    if sys.byteorder != "little":
        values.byteswap()
    distinct = len(set(values))
    transitions = sum(left != right for left, right in zip(values, values[1:]))
    return {
        "distinct_values": distinct,
        "maximum": max(values),
        "minimum": min(values),
        "negative_count": sum(value < 0 for value in values),
        "sha256": hashlib.sha256(data).hexdigest(),
        "transition_count": transitions,
        "value_count": len(values),
        "zero_count": values.count(0),
    }


def load_inventory(download_dir: Path) -> list[dict[str, object]]:
    path = download_dir / "download_inventory.json"
    inventory = json.loads(path.read_text(encoding="utf-8"))
    records = inventory.get("records")
    if not isinstance(records, list) or len(records) != EXPECTED_PRODUCTS:
        raise SystemExit("VIMS download inventory count changed")
    if (
        inventory.get("source_bytes") != EXPECTED_SOURCE_BYTES
        or inventory.get("core_bytes") != EXPECTED_PLANNED_CORE_BYTES
        or inventory.get("source_plan_sha256")
        != "485cbe552ab98fbfe9d5fc99622d31cb126aeb1aacb9b2afd411f5651a4ab51f"
    ):
        raise SystemExit("VIMS download inventory aggregates changed")
    for ordinal, record in enumerate(records, 1):
        if record.get("ordinal") != ordinal:
            raise SystemExit("VIMS download inventory order changed")
        payload = download_dir / str(record["local_filename"])
        if payload.name != record["local_filename"]:
            raise SystemExit("unsafe VIMS local filename")
        if payload.stat().st_size != int(record["file_bytes"]):
            raise SystemExit(f"VIMS payload size changed: {payload.name}")
        if sha256_file(payload) != record["payload_sha256"]:
            raise SystemExit(f"VIMS payload identity changed: {payload.name}")
    return records


def compare_schema(schema: dict[str, object], record: dict[str, object]) -> None:
    keys = (
        "product_id", "target_name", "start_time", "file_bytes", "core_offset",
        "core_bytes", "value_count", "lines", "bands", "samples", "suffix_bytes",
        "suffix_value_count", "qube_bytes", "axes", "core_items", "suffix_items",
        "special_constants",
    )
    for key in keys:
        if schema[key] != record[key]:
            raise ValueError(
                f"VIMS schema differs from pinned inventory for {key}: "
                f"{schema[key]} != {record[key]}"
            )


def collect(
    *, mode: str, download_dir: Path, samples_dir: Path, data_root: Path,
) -> tuple[list[dict[str, object]], dict[str, object]]:
    records = load_inventory(download_dir)
    if mode == "build":
        samples_dir.mkdir(parents=True, exist_ok=True)
        for path in samples_dir.glob("*.bin"):
            path.unlink()
    entries = []
    accepted_details = []
    rejected = []
    output_hashes = set()
    target_counts = {}
    for record in records:
        payload = download_dir / str(record["local_filename"])
        schema = parse_schema(payload)
        compare_schema(schema, record)
        decoded = extract_core(payload, schema)
        result = sample_stats(decoded)
        reason = ""
        if result["distinct_values"] < 2:
            reason = "constant_core"
        elif result["transition_count"] < 100:
            reason = "insufficient_core_transitions"
        elif result["sha256"] in output_hashes:
            reason = "duplicate_core_payload"
        if reason:
            rejected.append({
                "local_filename": payload.name,
                "product_id": schema["product_id"],
                "reason": reason,
                **result,
            })
            continue
        output_hashes.add(result["sha256"])
        output = samples_dir / f"{Path(payload.name).stem}.bin"
        if mode == "build":
            output.write_bytes(decoded)
        elif output.read_bytes() != decoded:
            raise ValueError(f"built sample differs from VIMS core: {output.name}")
        target = str(schema["target_name"])
        target_counts[target] = target_counts.get(target, 0) + 1
        accepted_details.append({
            "local_filename": payload.name,
            "payload_sha256": record["payload_sha256"],
            **schema,
            **result,
        })
        entries.append({
            "bit_width": 16,
            "dataset_id": DATASET_ID,
            "distinct_values": result["distinct_values"],
            "element_size_bytes": 2,
            "endianness": "little",
            "maximum": result["maximum"],
            "minimum": result["minimum"],
            "natural_record_kind": "cassini_vims_qube_core",
            "negative_count": result["negative_count"],
            "numeric_kind": "int",
            "product_id": schema["product_id"],
            "role": "primary",
            "sample_axes": ["line", "spectral_band", "sample"],
            "sample_format": "raw homogeneous little-endian signed-int16 VIMS QUBE core",
            "sample_geometry": "variable_spatial_shape_fixed_352_band_vims_cube",
            "sample_path": output.relative_to(data_root).as_posix(),
            "sample_rank": 3,
            "sample_shape": [schema["lines"], schema["bands"], schema["samples"]],
            "sample_size_bytes": len(decoded),
            "semantic_field": "vims_raw_spectral_detector_dn",
            "series_id": SERIES_ID,
            "sha256": result["sha256"],
            "source_sample": payload.relative_to(data_root).as_posix(),
            "source_variable": "PDS3 QUBE CORE",
            "start_time": schema["start_time"],
            "target_name": target,
            "transition_count": result["transition_count"],
            "value_count": result["value_count"],
            "zero_count": result["zero_count"],
        })
    expected_names = {Path(entry["sample_path"]).name for entry in entries}
    if {path.name for path in samples_dir.glob("*.bin")} != expected_names:
        raise SystemExit("VIMS sample directory differs from accepted source cores")
    primary_bytes = sum(int(entry["sample_size_bytes"]) for entry in entries)
    primary_values = sum(int(entry["value_count"]) for entry in entries)
    if len(entries) < 40 or primary_values < 10_000_000:
        raise SystemExit("too little nondegenerate VIMS material survived source validation")
    stats = {
        "accepted_products": len(entries),
        "candidate_id": DATASET_ID,
        "global_maximum": max(int(entry["maximum"]) for entry in entries),
        "global_minimum": min(int(entry["minimum"]) for entry in entries),
        "planned_products": EXPECTED_PRODUCTS,
        "planned_source_bytes": EXPECTED_SOURCE_BYTES,
        "planned_values": EXPECTED_PLANNED_VALUES,
        "primary_bytes": primary_bytes,
        "primary_values": primary_values,
        "records": accepted_details,
        "rejected_products": rejected,
        "series_id": SERIES_ID,
        "target_counts": target_counts,
        "total_negative_count": sum(int(entry["negative_count"]) for entry in entries),
        "total_transition_count": sum(int(entry["transition_count"]) for entry in entries),
        "total_zero_count": sum(int(entry["zero_count"]) for entry in entries),
    }
    return entries, stats


def write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")
    temporary.replace(path)


def read_jsonl(path: Path) -> list[dict[str, object]]:
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("build", "verify"))
    parser.add_argument("--download-dir", type=Path, required=True)
    parser.add_argument("--samples-dir", type=Path, required=True)
    parser.add_argument("--index", type=Path, required=True)
    parser.add_argument("--stats", type=Path, required=True)
    parser.add_argument("--data-root", type=Path, required=True)
    args = parser.parse_args()
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
            raise SystemExit("VIMS sample index differs from independent source decode")
        if json.loads(args.stats.read_text(encoding="utf-8")) != stats:
            raise SystemExit("VIMS ingest statistics differ from independent source decode")
    print(
        f"mode={args.mode} accepted={stats['accepted_products']} "
        f"rejected={len(stats['rejected_products'])} primary_values={stats['primary_values']} "
        f"primary_bytes={stats['primary_bytes']}"
    )


if __name__ == "__main__":
    main()
