#!/usr/bin/env python3
"""Decode and verify evaluation-only NOAA OISST classic-NetCDF records."""

from __future__ import annotations

import argparse
from array import array
from collections import Counter
import csv
from datetime import date, timedelta
import hashlib
import json
import math
from pathlib import Path
import shutil
import struct
import sys


DATASET_ID = "noaa_oisst_weekly_sst_i16_eval"
SERIES_ID = "oisst_weekly_global_sst_i16_eval"
SOURCE_NAME = "sst.wkmean.1990-present.nc"
SOURCE_SIZE = 223_865_152
SOURCE_SHA256 = "07cb78dcda836d1322897141fbdd79be1bd20190eeb10ffe6e9596588d2160f8"
AGGREGATE_OUTPUT_SHA256 = "3f581e112a4dc720c625af18983a1beb135484318dae99fb8cafddd5847b3064"
EXPECTED_RECORDS = 1_727
GRID_SHAPE = (180, 360)
GRID_VALUES = math.prod(GRID_SHAPE)
GRID_BYTES = GRID_VALUES * 2
TOTAL_VALUES = EXPECTED_RECORDS * GRID_VALUES
TOTAL_BYTES = EXPECTED_RECORDS * GRID_BYTES
RECORD_SIZE = 129_624
SST_BEGIN = 4_504
TIME_BEGIN = 134_104
TIME_BOUNDS_BEGIN = 134_112
MISSING_VALUE = 32_767
NC_SHORT = 3
TYPE_SIZES = {1: 1, 2: 1, 3: 2, 4: 4, 5: 4, 6: 8}
TYPE_CODES = {1: "b", 3: "h", 4: "i", 5: "f", 6: "d"}
BASE_DATE = date(1800, 1, 1)


class HeaderReader:
    def __init__(self, data: bytes) -> None:
        self.data = data
        self.position = 0

    def take(self, size: int) -> bytes:
        end = self.position + size
        if end > len(self.data):
            raise ValueError("truncated classic-NetCDF header")
        value = self.data[self.position:end]
        self.position = end
        return value

    def u32(self) -> int:
        return struct.unpack(">I", self.take(4))[0]

    def u64(self) -> int:
        return struct.unpack(">Q", self.take(8))[0]

    def name(self) -> str:
        length = self.u32()
        raw = self.take(length)
        self.take((-length) % 4)
        return raw.decode("ascii", "strict")


def decode_attribute(value_type: int, raw: bytes, count: int) -> object:
    if value_type == 2:
        return raw.decode("ascii", errors="replace").rstrip("\x00 ")
    code = TYPE_CODES.get(value_type)
    if code is None:
        raise ValueError(f"unsupported attribute type {value_type}")
    values = list(struct.unpack(">" + code * count, raw)) if count else []
    return values[0] if len(values) == 1 else values


def read_attributes(reader: HeaderReader) -> dict[str, object]:
    tag, count = reader.u32(), reader.u32()
    if (tag, count) == (0, 0):
        return {}
    if tag != 12:
        raise ValueError(f"invalid attribute-list tag {tag}")
    result: dict[str, object] = {}
    for _ in range(count):
        name = reader.name()
        value_type = reader.u32()
        element_count = reader.u32()
        size = TYPE_SIZES.get(value_type)
        if size is None:
            raise ValueError(f"unsupported attribute type {value_type}")
        byte_count = size * element_count
        raw = reader.take(byte_count)
        reader.take((-byte_count) % 4)
        result[name] = decode_attribute(value_type, raw, element_count)
    return result


def parse_header(path: Path) -> dict[str, object]:
    with path.open("rb") as handle:
        raw = handle.read(4 * 1024 * 1024)
    if raw[:4] not in {b"CDF\x01", b"CDF\x02"}:
        raise ValueError("source is not classic NetCDF CDF1/CDF2")
    offset64 = raw[3] == 2
    reader = HeaderReader(raw)
    reader.take(4)
    num_records = reader.u32()
    dim_tag, dim_count = reader.u32(), reader.u32()
    dimensions: list[dict[str, object]] = []
    if dim_tag == 10:
        for _ in range(dim_count):
            dimensions.append({"name": reader.name(), "declared_length": reader.u32()})
    elif (dim_tag, dim_count) != (0, 0):
        raise ValueError("invalid dimension list")
    global_attributes = read_attributes(reader)
    variable_tag, variable_count = reader.u32(), reader.u32()
    variables: dict[str, dict[str, object]] = {}
    if variable_tag == 11:
        for _ in range(variable_count):
            name = reader.name()
            rank = reader.u32()
            dim_ids = [reader.u32() for _ in range(rank)]
            if any(dim_id >= len(dimensions) for dim_id in dim_ids):
                raise ValueError(f"{name}: invalid dimension id")
            attributes = read_attributes(reader)
            value_type, vsize = reader.u32(), reader.u32()
            begin = reader.u64() if offset64 else reader.u32()
            variables[name] = {
                "type": value_type,
                "vsize": vsize,
                "begin": begin,
                "dim_names": [str(dimensions[dim_id]["name"]) for dim_id in dim_ids],
                "shape": [
                    num_records if int(dimensions[dim_id]["declared_length"]) == 0
                    else int(dimensions[dim_id]["declared_length"])
                    for dim_id in dim_ids
                ],
                "attributes": attributes,
                "is_record": bool(
                    dim_ids and int(dimensions[dim_ids[0]]["declared_length"]) == 0
                ),
            }
    elif (variable_tag, variable_count) != (0, 0):
        raise ValueError("invalid variable list")
    record_size = sum(
        int(variable["vsize"])
        for variable in variables.values()
        if variable["is_record"]
    )
    return {
        "format": "CDF2" if offset64 else "CDF1",
        "header_bytes": reader.position,
        "num_records": num_records,
        "dimensions": dimensions,
        "global_attributes": global_attributes,
        "variables": variables,
        "record_size": record_size,
    }


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(8 * 1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def selected_hashes(recipe_dir: Path) -> tuple[str, str]:
    rows = list(csv.DictReader((recipe_dir / "selection.tsv").open(), delimiter="\t"))
    if len(rows) != 1 or rows[0]["name"] != SOURCE_NAME:
        raise ValueError("evaluation selection must contain exactly the OISST source")
    if int(rows[0]["size_bytes"]) != SOURCE_SIZE:
        raise ValueError("selection source-size mismatch")
    return rows[0]["sha256"], rows[0]["aggregate_output_sha256"]


def numeric_scalar(attributes: dict[str, object], name: str) -> float | None:
    value = attributes.get(name)
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, list) and len(value) == 1 and isinstance(value[0], (int, float)):
        return float(value[0])
    return None


def checked_layout(path: Path) -> dict[str, object]:
    header = parse_header(path)
    if header["format"] != "CDF1" or header["header_bytes"] != 2_340:
        raise ValueError("unexpected classic-NetCDF format/header size")
    if header["num_records"] != EXPECTED_RECORDS or header["record_size"] != RECORD_SIZE:
        raise ValueError("unexpected record count or stride")
    expected_dimensions = [
        {"name": "lat", "declared_length": 180},
        {"name": "lon", "declared_length": 360},
        {"name": "time", "declared_length": 0},
        {"name": "nbnds", "declared_length": 2},
    ]
    if header["dimensions"] != expected_dimensions:
        raise ValueError(f"dimension mismatch: {header['dimensions']}")
    global_attrs = header["global_attributes"]
    if global_attrs.get("dataset_title") != "NOAA Optimum Interpolation (OI) SST V2":
        raise ValueError("dataset identity mismatch")
    variables = header["variables"]
    required = {"lat", "lon", "sst", "time", "time_bnds"}
    if set(variables) != required:
        raise ValueError(f"variable inventory mismatch: {sorted(variables)}")
    sst = variables["sst"]
    if (
        sst["type"] != NC_SHORT
        or sst["dim_names"] != ["time", "lat", "lon"]
        or sst["shape"] != [EXPECTED_RECORDS, *GRID_SHAPE]
        or sst["begin"] != SST_BEGIN
        or sst["vsize"] != GRID_BYTES
        or not sst["is_record"]
    ):
        raise ValueError(f"SST layout mismatch: {sst}")
    attrs = sst["attributes"]
    scale = numeric_scalar(attrs, "scale_factor")
    offset = numeric_scalar(attrs, "add_offset")
    missing = numeric_scalar(attrs, "missing_value")
    if scale is None or abs(scale - 0.01) > 1e-8 or offset != 0.0 or missing != MISSING_VALUE:
        raise ValueError(f"SST packing metadata mismatch: scale={scale} offset={offset} missing={missing}")
    if attrs.get("standard_name") != "sea_surface_temperature" or attrs.get("statistic") != "Weekly Mean":
        raise ValueError("SST semantic metadata mismatch")
    time = variables["time"]
    bounds = variables["time_bnds"]
    if time["type"] != 6 or time["begin"] != TIME_BEGIN or time["vsize"] != 8:
        raise ValueError("time layout mismatch")
    if bounds["type"] != 6 or bounds["begin"] != TIME_BOUNDS_BEGIN or bounds["vsize"] != 16:
        raise ValueError("time-bounds layout mismatch")
    return header


def validate_coordinates(path: Path, header: dict[str, object]) -> None:
    variables = header["variables"]
    with path.open("rb") as handle:
        lat = variables["lat"]
        handle.seek(int(lat["begin"]))
        latitudes = struct.unpack(">180f", handle.read(180 * 4))
        lon = variables["lon"]
        handle.seek(int(lon["begin"]))
        longitudes = struct.unpack(">360f", handle.read(360 * 4))
    expected_latitudes = tuple(89.5 - index for index in range(180))
    expected_longitudes = tuple(0.5 + index for index in range(360))
    if latitudes != expected_latitudes or longitudes != expected_longitudes:
        raise ValueError("latitude/longitude coordinate mismatch")


def decode_be_i16(raw: bytes) -> tuple[array[int], bytes]:
    if len(raw) != GRID_BYTES:
        raise ValueError("wrong-sized SST record")
    values = array("h")
    values.frombytes(raw)
    if sys.byteorder == "little":
        values.byteswap()
        little = values.tobytes()
    else:
        output = array("h", values)
        output.byteswap()
        little = output.tobytes()
    return values, little


def source_path(eval_root: Path, recipe_dir: Path) -> Path:
    selected_source_hash, selected_output_hash = selected_hashes(recipe_dir)
    if selected_source_hash != SOURCE_SHA256 or selected_output_hash != AGGREGATE_OUTPUT_SHA256:
        raise ValueError("selection hash constants mismatch")
    path = eval_root / "downloads" / SOURCE_NAME
    if not path.is_file() or path.stat().st_size != SOURCE_SIZE:
        raise ValueError(f"missing or wrong-sized source: {path}")
    if file_sha256(path) != SOURCE_SHA256:
        raise ValueError("pinned source SHA-256 mismatch")
    rights = eval_root / "rights" / "ncei_iso_c00844.html"
    rights_text = rights.read_text(encoding="utf-8", errors="replace")
    if "doi:10.7289/V5SQ8XB5" not in rights_text or "See the Use Agreement for this CDR" not in rights_text:
        raise ValueError("rights-status evidence missing or changed")
    return path


def build(args: argparse.Namespace) -> None:
    source = source_path(args.eval_root, args.recipe_dir)
    header = checked_layout(source)
    validate_coordinates(source, header)
    samples_dir = args.eval_root / "samples" / SERIES_ID
    filtered_dir = args.eval_root / "filtered"
    index_dir = args.eval_root / "index"
    if samples_dir.parent.exists():
        shutil.rmtree(samples_dir.parent)
    samples_dir.mkdir(parents=True)
    filtered_dir.mkdir(parents=True, exist_ok=True)
    index_dir.mkdir(parents=True, exist_ok=True)

    rows: list[dict[str, object]] = []
    records: list[dict[str, object]] = []
    hashes: set[str] = set()
    aggregate = hashlib.sha256()
    global_values: set[int] = set()
    total_zeros = 0
    total_missing = 0
    previous_time: float | None = None
    with source.open("rb") as handle:
        for record_index in range(EXPECTED_RECORDS):
            record_offset = SST_BEGIN + record_index * RECORD_SIZE
            handle.seek(record_offset)
            raw = handle.read(GRID_BYTES)
            values, payload = decode_be_i16(raw)
            minimum, maximum = min(values), max(values)
            if minimum == maximum:
                raise ValueError(f"constant SST grid: record={record_index}")
            unique_count = len(set(values))
            zero_count = values.count(0)
            missing_count = values.count(MISSING_VALUE)
            global_values.update(values)
            total_zeros += zero_count
            total_missing += missing_count
            sha256 = hashlib.sha256(payload).hexdigest()
            if sha256 in hashes:
                raise ValueError(f"duplicate SST grid: record={record_index}")
            hashes.add(sha256)
            aggregate.update(payload)

            handle.seek(TIME_BEGIN + record_index * RECORD_SIZE)
            time_value = struct.unpack(">d", handle.read(8))[0]
            handle.seek(TIME_BOUNDS_BEGIN + record_index * RECORD_SIZE)
            lower, upper = struct.unpack(">2d", handle.read(16))
            if upper - lower != 7.0 or time_value != lower:
                raise ValueError(f"time-bound mismatch: record={record_index}")
            if previous_time is not None and time_value - previous_time != 7.0:
                raise ValueError(f"nonweekly time step: record={record_index}")
            previous_time = time_value
            sample_date = BASE_DATE + timedelta(days=time_value)
            output = samples_dir / f"oisst_weekly_{sample_date.isoformat()}.i16le.bin"
            output.write_bytes(payload)
            row = {
                "dataset_id": DATASET_ID,
                "series_id": SERIES_ID,
                "role": "evaluation",
                "intended_use": "evaluation_only",
                "training_eligible": False,
                "redistribution_authorized": False,
                "rights_status": "unclear",
                "benchmark_eligible": True,
                "sample_path": output.relative_to(args.eval_root).as_posix(),
                "numeric_kind": "int",
                "bit_width": 16,
                "endianness": "little",
                "element_size_bytes": 2,
                "sample_size_bytes": GRID_BYTES,
                "value_count": GRID_VALUES,
                "sample_format": "raw homogeneous little-endian signed-int16 packed SST grid",
                "sample_geometry": "180x360_weekly_global_sst_grid",
                "sample_rank": 2,
                "sample_shape": list(GRID_SHAPE),
                "sample_axes": ["latitude_descending", "longitude_ascending"],
                "natural_record_kind": "complete_oisst_weekly_global_grid",
                "record_index": record_index,
                "record_offset": record_offset,
                "date": sample_date.isoformat(),
                "time_days_since_1800_01_01": time_value,
                "time_bounds_days": [lower, upper],
                "scale_factor": 0.01,
                "add_offset": 0.0,
                "missing_value": MISSING_VALUE,
                "missing_count": missing_count,
                "zero_count": zero_count,
                "distinct_value_count": unique_count,
                "min": int(minimum),
                "max": int(maximum),
                "sha256": sha256,
            }
            rows.append(row)
            records.append(
                {
                    "record_index": record_index,
                    "date": sample_date.isoformat(),
                    "min": int(minimum),
                    "max": int(maximum),
                    "distinct_value_count": unique_count,
                    "zero_count": zero_count,
                    "missing_count": missing_count,
                    "sha256": sha256,
                }
            )

    if aggregate.hexdigest() != AGGREGATE_OUTPUT_SHA256:
        raise ValueError("aggregate output SHA-256 mismatch")
    if len(rows) != EXPECTED_RECORDS or len(hashes) != EXPECTED_RECORDS:
        raise ValueError("record count or uniqueness mismatch")
    if len(global_values) != 3_572 or min(global_values) != -180 or max(global_values) != 3_616:
        raise ValueError("global stored-value distribution mismatch")
    if total_zeros != 112_961 or total_missing != 0:
        raise ValueError("global zero/missing count mismatch")
    index = index_dir / "samples.jsonl"
    with index.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")
    stats = {
        "dataset_id": DATASET_ID,
        "intended_use": "evaluation_only",
        "training_eligible": False,
        "redistribution_authorized": False,
        "rights_status": "unclear",
        "source_sha256": SOURCE_SHA256,
        "aggregate_output_sha256": AGGREGATE_OUTPUT_SHA256,
        "sample_count": len(rows),
        "benchmark_eligible_count": len(rows),
        "total_values": TOTAL_VALUES,
        "total_size_bytes": TOTAL_BYTES,
        "date_first": rows[0]["date"],
        "date_last": rows[-1]["date"],
        "global_min": min(global_values),
        "global_max": max(global_values),
        "global_distinct_values": len(global_values),
        "total_zero_count": total_zeros,
        "total_missing_count": total_missing,
        "all_grids_nonconstant_and_unique": True,
        "records": records,
    }
    (filtered_dir / "ingest_stats.json").write_text(
        json.dumps(stats, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(
        f"built evaluation samples={len(rows)} values={TOTAL_VALUES} bytes={TOTAL_BYTES} "
        f"dates={rows[0]['date']}..{rows[-1]['date']}"
    )


def verify(args: argparse.Namespace) -> None:
    source = source_path(args.eval_root, args.recipe_dir)
    header = checked_layout(source)
    validate_coordinates(source, header)
    index_path = args.eval_root / "index" / "samples.jsonl"
    stats_path = args.eval_root / "filtered" / "ingest_stats.json"
    rows = [json.loads(line) for line in index_path.read_text().splitlines() if line.strip()]
    stats = json.loads(stats_path.read_text())
    if len(rows) != EXPECTED_RECORDS or stats.get("sample_count") != EXPECTED_RECORDS:
        raise ValueError("evaluation sample count mismatch")
    indexed_paths: set[str] = set()
    hashes: set[str] = set()
    aggregate = hashlib.sha256()
    previous_time: float | None = None
    with source.open("rb") as handle:
        for record_index, row in enumerate(rows):
            handle.seek(SST_BEGIN + record_index * RECORD_SIZE)
            values, expected = decode_be_i16(handle.read(GRID_BYTES))
            handle.seek(TIME_BEGIN + record_index * RECORD_SIZE)
            time_value = struct.unpack(">d", handle.read(8))[0]
            if previous_time is not None and time_value - previous_time != 7.0:
                raise ValueError("verification time sequence mismatch")
            previous_time = time_value
            expected_date = (BASE_DATE + timedelta(days=time_value)).isoformat()
            if (
                row.get("dataset_id") != DATASET_ID
                or row.get("series_id") != SERIES_ID
                or row.get("role") != "evaluation"
                or row.get("intended_use") != "evaluation_only"
                or row.get("training_eligible") is not False
                or row.get("redistribution_authorized") is not False
                or row.get("rights_status") != "unclear"
                or row.get("benchmark_eligible") is not True
            ):
                raise ValueError(f"evaluation isolation marker mismatch: record={record_index}")
            if row.get("record_index") != record_index or row.get("date") != expected_date:
                raise ValueError(f"record identity mismatch: record={record_index}")
            if row.get("sample_shape") != list(GRID_SHAPE) or row.get("sample_axes") != ["latitude_descending", "longitude_ascending"]:
                raise ValueError(f"sample geometry mismatch: record={record_index}")
            if row.get("natural_record_kind") != "complete_oisst_weekly_global_grid":
                raise ValueError(f"natural boundary mismatch: record={record_index}")
            sample_path = str(row.get("sample_path", ""))
            prefix = f"samples/{SERIES_ID}/"
            if not sample_path.startswith(prefix) or sample_path in indexed_paths:
                raise ValueError(f"invalid or duplicate sample path: {sample_path}")
            indexed_paths.add(sample_path)
            actual = (args.eval_root / sample_path).read_bytes()
            if actual != expected:
                raise ValueError(f"fresh source decode mismatch: record={record_index}")
            digest = hashlib.sha256(actual).hexdigest()
            if digest != row.get("sha256") or digest in hashes:
                raise ValueError(f"hash mismatch or duplicate: record={record_index}")
            hashes.add(digest)
            if row.get("min") != min(values) or row.get("max") != max(values):
                raise ValueError(f"range mismatch: record={record_index}")
            if row.get("missing_count") != values.count(MISSING_VALUE):
                raise ValueError(f"missing-count mismatch: record={record_index}")
            aggregate.update(actual)

    actual_paths = {
        path.relative_to(args.eval_root).as_posix()
        for path in (args.eval_root / "samples" / SERIES_ID).rglob("*")
        if path.is_file()
    }
    if actual_paths != indexed_paths:
        raise ValueError("evaluation sample directory and index differ")
    if aggregate.hexdigest() != AGGREGATE_OUTPUT_SHA256 or len(hashes) != EXPECTED_RECORDS:
        raise ValueError("verified aggregate hash or uniqueness mismatch")
    if (
        stats.get("intended_use") != "evaluation_only"
        or stats.get("training_eligible") is not False
        or stats.get("total_values") != TOTAL_VALUES
        or stats.get("total_size_bytes") != TOTAL_BYTES
    ):
        raise ValueError("evaluation statistics mismatch")
    print(
        f"verified evaluation dataset={DATASET_ID} samples={len(rows)} "
        f"values={TOTAL_VALUES} bytes={TOTAL_BYTES} unique_hashes={len(hashes)}"
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("build", "verify"))
    parser.add_argument("--recipe-dir", required=True, type=Path)
    parser.add_argument("--eval-root", required=True, type=Path)
    args = parser.parse_args()
    try:
        if args.command == "build":
            build(args)
        else:
            verify(args)
    except (OSError, ValueError, struct.error) as error:
        raise SystemExit(str(error)) from error


if __name__ == "__main__":
    main()
