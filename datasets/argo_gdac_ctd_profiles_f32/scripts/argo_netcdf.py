#!/usr/bin/env python3
"""Decode pinned classic-NetCDF Argo CTD record variables without dependencies."""
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


DATASET_ID = "argo_gdac_ctd_profiles_f32"
VARIABLES = {
    "PRES": ("argo_pressure_f32", "pressure_dbar"),
    "TEMP": ("argo_temperature_f32", "temperature_degree_celsius"),
    "PSAL": ("argo_salinity_f32", "practical_salinity"),
}
NC_FLOAT = 5
TYPE_SIZES = {1: 1, 2: 1, 3: 2, 4: 4, 5: 4, 6: 8}
TYPE_CODES = {1: "b", 3: "h", 4: "i", 5: "f", 6: "d"}
EXPECTED_FILES = 46
EXPECTED_SAMPLES = 138
EXPECTED_SOURCE_BYTES = 239_866_364
EXPECTED_PRIMARY_BYTES = 56_436_348
MIN_VALID_VALUES = 1_000
MIN_VALID_FRACTION = 0.05


class HeaderReader:
    def __init__(self, data: bytes):
        self.data = data
        self.position = 0

    def take(self, size: int) -> bytes:
        end = self.position + size
        if end > len(self.data):
            raise ValueError("truncated NetCDF header")
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
        return raw.decode("ascii", "replace").rstrip("\x00 ")
    code = TYPE_CODES.get(value_type)
    if code is None:
        raise ValueError(f"unsupported NetCDF attribute type {value_type}")
    values = list(struct.unpack(">" + code * count, raw)) if count else []
    return values[0] if len(values) == 1 else values


def read_attributes(reader: HeaderReader) -> dict[str, object]:
    tag = reader.u32()
    count = reader.u32()
    if tag == 0 and count == 0:
        return {}
    if tag != 12:
        raise ValueError(f"unexpected NetCDF attribute tag {tag}")
    result = {}
    for _ in range(count):
        name = reader.name()
        value_type = reader.u32()
        element_count = reader.u32()
        size = TYPE_SIZES.get(value_type)
        if size is None:
            raise ValueError(f"unsupported NetCDF attribute type {value_type}")
        byte_count = size * element_count
        raw = reader.take(byte_count)
        reader.take((-byte_count) % 4)
        result[name] = decode_attribute(value_type, raw, element_count)
    return result


def parse_header(path: Path) -> dict[str, object]:
    with path.open("rb") as handle:
        raw = handle.read(min(path.stat().st_size, 4 * 1024 * 1024))
    if raw[:4] not in {b"CDF\x01", b"CDF\x02"}:
        raise ValueError(f"{path.name}: not classic NetCDF CDF1/CDF2")
    offset64 = raw[3] == 2
    reader = HeaderReader(raw)
    reader.take(4)
    num_records = reader.u32()
    dim_tag, dim_count = reader.u32(), reader.u32()
    dimensions = []
    if dim_tag == 10:
        for _ in range(dim_count):
            dimensions.append({"name": reader.name(), "declared_length": reader.u32()})
    elif (dim_tag, dim_count) != (0, 0):
        raise ValueError(f"{path.name}: invalid dimension list")
    global_attributes = read_attributes(reader)
    variable_tag, variable_count = reader.u32(), reader.u32()
    variables = {}
    if variable_tag == 11:
        for _ in range(variable_count):
            name = reader.name()
            rank = reader.u32()
            dim_ids = [reader.u32() for _ in range(rank)]
            if any(item >= len(dimensions) for item in dim_ids):
                raise ValueError(f"{path.name}:{name}: invalid dimension id")
            attributes = read_attributes(reader)
            value_type, vsize = reader.u32(), reader.u32()
            begin = reader.u64() if offset64 else reader.u32()
            dim_names = [str(dimensions[item]["name"]) for item in dim_ids]
            shape = [
                num_records if int(dimensions[item]["declared_length"]) == 0
                else int(dimensions[item]["declared_length"])
                for item in dim_ids
            ]
            variables[name] = {
                "type": value_type, "vsize": vsize, "begin": begin,
                "dim_ids": dim_ids, "dim_names": dim_names, "shape": shape,
                "attributes": attributes,
                "is_record": bool(dim_ids and int(dimensions[dim_ids[0]]["declared_length"]) == 0),
            }
    elif (variable_tag, variable_count) != (0, 0):
        raise ValueError(f"{path.name}: invalid variable list")
    record_size = sum(int(item["vsize"]) for item in variables.values() if item["is_record"])
    return {
        "format": "CDF2" if offset64 else "CDF1", "num_records": num_records,
        "dimensions": dimensions, "global_attributes": global_attributes,
        "variables": variables, "record_size": record_size,
    }


def checked_variable(header: dict[str, object], name: str) -> dict[str, object]:
    variable = header["variables"].get(name)
    if not isinstance(variable, dict):
        raise ValueError(f"missing CTD variable {name}")
    if variable["type"] != NC_FLOAT or variable["dim_names"] != ["N_PROF", "N_LEVELS"]:
        raise ValueError(f"{name}: expected NC_FLOAT(N_PROF,N_LEVELS), got {variable}")
    shape = variable["shape"]
    if len(shape) != 2 or shape[0] <= 0 or shape[1] <= 0:
        raise ValueError(f"{name}: invalid shape {shape}")
    return variable


def read_variable(path: Path, header: dict[str, object], name: str) -> bytes:
    variable = checked_variable(header, name)
    shape = variable["shape"]
    per_record_bytes = math.prod(shape[1:]) * 4
    total_bytes = math.prod(shape) * 4
    if not variable["is_record"]:
        with path.open("rb") as handle:
            handle.seek(int(variable["begin"]))
            raw = handle.read(total_bytes)
        if len(raw) != total_bytes:
            raise ValueError(f"{path.name}:{name}: truncated contiguous variable")
        return raw
    record_size = int(header["record_size"])
    if record_size <= 0 or int(variable["vsize"]) < per_record_bytes:
        raise ValueError(f"{path.name}:{name}: invalid record layout")
    output = bytearray(total_bytes)
    with path.open("rb") as handle:
        for record in range(shape[0]):
            handle.seek(int(variable["begin"]) + record * record_size)
            raw = handle.read(per_record_bytes)
            if len(raw) != per_record_bytes:
                raise ValueError(f"{path.name}:{name}: truncated record {record}")
            start = record * per_record_bytes
            output[start:start + per_record_bytes] = raw
    return bytes(output)


def canonical_values(raw: bytes) -> tuple[array, bytes]:
    if sys.byteorder != "little":
        raise SystemExit("canonical output requires a little-endian host")
    values = array("f")
    values.frombytes(raw)
    values.byteswap()
    return values, values.tobytes()


def plan_rows(path: Path) -> list[dict[str, object]]:
    with path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    if len(rows) != EXPECTED_FILES or len({row["wmo"] for row in rows}) != EXPECTED_FILES:
        raise ValueError(f"download plan must contain {EXPECTED_FILES} unique floats")
    result = []
    for row in rows:
        digest = row.get("sha256", "")
        if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
            raise ValueError(f"invalid pinned SHA-256 for WMO {row['wmo']}")
        result.append({
            "wmo": row["wmo"], "source_bytes": int(row["source_bytes"]),
            "sha256": digest, "url": row["url"],
        })
    return result


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def inspect_values(values: array, variable: dict[str, object]) -> dict[str, object]:
    fill = variable["attributes"].get("_FillValue", 99999.0)
    if isinstance(fill, list) or not isinstance(fill, (int, float)):
        raise ValueError(f"invalid _FillValue {fill!r}")
    valid_count = 0
    nonfinite = 0
    distinct = set()
    minimum = math.inf
    maximum = -math.inf
    for value in values:
        if value == fill:
            continue
        if not math.isfinite(value):
            nonfinite += 1
            continue
        minimum = min(minimum, value)
        maximum = max(maximum, value)
        if len(distinct) < 64:
            distinct.add(value)
        valid_count += 1
    valid_fraction = valid_count / len(values) if values else 0.0
    if nonfinite:
        raise ValueError(f"stored non-fill values include {nonfinite} non-finite values")
    if valid_count < MIN_VALID_VALUES or valid_fraction < MIN_VALID_FRACTION:
        raise ValueError(f"insufficient valid coverage: values={valid_count} fraction={valid_fraction:.6f}")
    if len(distinct) <= 1 or minimum >= maximum:
        raise ValueError("degenerate valid measurement values")
    return {
        "fill_value": float(fill), "fill_count": len(values) - valid_count,
        "valid_count": valid_count, "valid_fraction": round(valid_fraction, 9),
        "minimum": minimum, "maximum": maximum,
    }


def validate_download(download_dir: Path, plan: Path) -> None:
    inventory = []
    total = 0
    for row in plan_rows(plan):
        path = download_dir / f"{row['wmo']}_prof.nc"
        if not path.is_file() or path.stat().st_size != row["source_bytes"]:
            raise SystemExit(f"missing or wrong-sized source: {path}")
        header = parse_header(path)
        shapes = []
        for name in VARIABLES:
            variable = checked_variable(header, name)
            shapes.append(variable["shape"])
        if len({tuple(shape) for shape in shapes}) != 1:
            raise SystemExit(f"core CTD shapes disagree: {path}")
        digest = file_sha256(path)
        if digest != row["sha256"]:
            raise SystemExit(f"pinned source hash mismatch: {path}")
        total += path.stat().st_size
        inventory.append({
            **row, "file": path.name,
            "netcdf_format": header["format"], "shape": shapes[0],
        })
    if total != EXPECTED_SOURCE_BYTES:
        raise SystemExit(f"unexpected aggregate source bytes: {total}")
    payload = {"dataset_id": DATASET_ID, "source_bytes": total, "records": inventory}
    (download_dir / "download_inventory.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"validated_files={len(inventory)} source_bytes={total}")


def build(repo_root: Path, data_dir_name: str, plan: Path) -> None:
    data_root = repo_root / data_dir_name
    download_dir = data_root / "downloads" / DATASET_ID
    samples_dir = data_root / "samples" / DATASET_ID
    filter_dir = data_root / "filtered" / DATASET_ID
    index_dir = data_root / "index" / DATASET_ID
    if samples_dir.exists():
        shutil.rmtree(samples_dir)
    samples_dir.mkdir(parents=True)
    filter_dir.mkdir(parents=True, exist_ok=True)
    index_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    records = []
    for source in plan_rows(plan):
        wmo = str(source["wmo"])
        path = download_dir / f"{wmo}_prof.nc"
        if not path.is_file() or path.stat().st_size != source["source_bytes"]:
            raise SystemExit(f"missing local source: {path}; run download.sh")
        if file_sha256(path) != source["sha256"]:
            raise SystemExit(f"pinned source hash mismatch: {path}")
        header = parse_header(path)
        for variable_name, (series_id, semantic_field) in VARIABLES.items():
            variable = checked_variable(header, variable_name)
            raw = read_variable(path, header, variable_name)
            values, canonical = canonical_values(raw)
            quality = inspect_values(values, variable)
            out_dir = samples_dir / series_id
            out_dir.mkdir(exist_ok=True)
            output = out_dir / f"{wmo}_{variable_name.lower()}.bin"
            output.write_bytes(canonical)
            digest = hashlib.sha256(canonical).hexdigest()
            value_count = len(values)
            shape = list(variable["shape"])
            row = {
                "dataset_id": DATASET_ID, "series_id": series_id, "role": "primary",
                "sample_path": output.relative_to(data_root).as_posix(),
                "source_sample": f"downloads/{DATASET_ID}/{path.name}",
                "wmo": wmo, "source_variable": variable_name, "semantic_field": semantic_field,
                "numeric_kind": "float", "bit_width": 32, "endianness": "little",
                "element_size_bytes": 4, "value_count": value_count,
                "sample_size_bytes": len(canonical), "sample_format": "raw homogeneous float32 array",
                "sample_geometry": "argo_float_profile_history_matrix_2d", "sample_rank": 2,
                "sample_shape": shape, "sample_axes": ["profile", "depth_level"],
                "natural_record_kind": "complete_argo_float_ctd_variable_matrix",
                "sha256": digest, **quality,
            }
            rows.append(row)
            records.append({
                "wmo": wmo, "source_file": path.name, "source_variable": variable_name,
                "series_id": series_id, "shape": shape, "sha256": digest, **quality,
            })
    primary_bytes = sum(int(row["sample_size_bytes"]) for row in rows)
    if len(rows) != EXPECTED_SAMPLES or primary_bytes != EXPECTED_PRIMARY_BYTES:
        raise SystemExit(f"unexpected output totals: samples={len(rows)} bytes={primary_bytes}")
    stats = {
        "dataset_id": DATASET_ID, "sample_count": len(rows),
        "primary_values": sum(int(row["value_count"]) for row in rows),
        "primary_bytes": primary_bytes,
        "valid_values": sum(int(row["valid_count"]) for row in rows),
        "fill_values": sum(int(row["fill_count"]) for row in rows),
        "minimum_valid_fraction": min(float(row["valid_fraction"]) for row in rows),
        "median_valid_fraction": statistics.median(float(row["valid_fraction"]) for row in rows),
        "records": records,
    }
    (filter_dir / "ingest_stats.json").write_text(
        json.dumps(stats, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    with (index_dir / "samples.jsonl").open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")
    print(json.dumps({key: value for key, value in stats.items() if key != "records"}, indent=2, sort_keys=True))


def verify(repo_root: Path, data_dir_name: str, plan: Path) -> None:
    data_root = repo_root / data_dir_name
    index_path = data_root / "index" / DATASET_ID / "samples.jsonl"
    stats_path = data_root / "filtered" / DATASET_ID / "ingest_stats.json"
    if not index_path.is_file() or not stats_path.is_file():
        raise SystemExit("missing index or stats; run build.sh")
    rows = [json.loads(line) for line in index_path.read_text(encoding="utf-8").splitlines() if line]
    by_key = {(row["wmo"], row["source_variable"]): row for row in rows}
    if len(rows) != EXPECTED_SAMPLES or len(by_key) != EXPECTED_SAMPLES:
        raise SystemExit("unexpected or duplicate sample index rows")
    verified_bytes = 0
    verified_values = 0
    expected_paths = set()
    for source in plan_rows(plan):
        wmo = str(source["wmo"])
        path = data_root / "downloads" / DATASET_ID / f"{wmo}_prof.nc"
        if not path.is_file() or path.stat().st_size != source["source_bytes"] or file_sha256(path) != source["sha256"]:
            raise SystemExit(f"missing or mismatched pinned source: {path}")
        header = parse_header(path)
        for variable_name, (series_id, _semantic_field) in VARIABLES.items():
            row = by_key.get((wmo, variable_name))
            if row is None or row.get("series_id") != series_id:
                raise SystemExit(f"missing indexed sample: {wmo}/{variable_name}")
            if (row.get("numeric_kind"), row.get("bit_width"), row.get("endianness")) != ("float", 32, "little"):
                raise SystemExit(f"wrong numeric representation: {wmo}/{variable_name}")
            variable = checked_variable(header, variable_name)
            values, canonical = canonical_values(read_variable(path, header, variable_name))
            quality = inspect_values(values, variable)
            output = data_root / row["sample_path"]
            expected_paths.add(output.resolve())
            if not output.is_file() or output.read_bytes() != canonical:
                raise SystemExit(f"output differs from canonical source values: {output}")
            if row.get("sha256") != hashlib.sha256(canonical).hexdigest():
                raise SystemExit(f"indexed hash mismatch: {output}")
            for key, value in quality.items():
                if row.get(key) != value:
                    raise SystemExit(f"quality metadata mismatch {key}: {output}")
            verified_bytes += len(canonical)
            verified_values += len(values)
    actual_paths = {path.resolve() for path in (data_root / "samples" / DATASET_ID).glob("*/*.bin")}
    if actual_paths != expected_paths or verified_bytes != EXPECTED_PRIMARY_BYTES:
        raise SystemExit("sample inventory or byte total mismatch")
    stats = json.loads(stats_path.read_text(encoding="utf-8"))
    if stats.get("sample_count") != EXPECTED_SAMPLES or stats.get("primary_bytes") != verified_bytes:
        raise SystemExit("stored stats disagree with verified samples")
    print(f"verified_samples={len(rows)} verified_values={verified_values} verified_bytes={verified_bytes}")


def main() -> None:
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    validate_parser = commands.add_parser("validate-download")
    validate_parser.add_argument("--download-dir", type=Path, required=True)
    validate_parser.add_argument("--plan", type=Path, required=True)
    for command in ("build", "verify"):
        sub = commands.add_parser(command)
        sub.add_argument("--repo-root", type=Path, required=True)
        sub.add_argument("--data-dir", required=True)
        sub.add_argument("--plan", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "validate-download":
        validate_download(args.download_dir, args.plan)
    elif args.command == "build":
        build(args.repo_root, args.data_dir, args.plan)
    else:
        verify(args.repo_root, args.data_dir, args.plan)


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, struct.error) as error:
        raise SystemExit(str(error)) from error
