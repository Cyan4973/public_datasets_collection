#!/usr/bin/env python3
"""Preflight, build, and verify USGS ShakeMap float32 rasters."""
from __future__ import annotations

import argparse
import array
import csv
import hashlib
import html
import json
import math
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import sys
from typing import Callable
import zipfile


DATASET_ID = "usgs_shakemap_ground_motion_f32"
EVENT_ID = "us6000qw60"
PRODUCT_SOURCE = "us"
PRODUCT_CODE = "us6000qw60"
PRODUCT_UPDATE_TIME = 1_759_864_843_221
WIDTH = 795
HEIGHT = 496
VALUE_COUNT = WIDTH * HEIGHT
SAMPLE_BYTES = VALUE_COUNT * 4
EXPECTED_VALUES = VALUE_COUNT * 14
EXPECTED_BYTES = SAMPLE_BYTES * 14
EXPECTED_RIGHTS = (
    81_841,
    "a6f640805e5783765fb350d4d60d06a5dbef8ffa3b219fa7713885e5dff9580c",
)
EXPECTED_EVENT = (
    91_037,
    "ca786a617c441a8c233816d60d0bd3e6906d6e9ecf7e0da14e77c1269f049263",
)
EXPECTED_RASTER = (
    13_201_579,
    "1f5b9410ebc7314c3ea2e7a531b7c6f742fba223a8b7b20f0705e585ba52daf9",
)
EXPECTED_HEADER_SHA256 = (
    "b11995ccab1e4d1c02ab9b93e83d9ea908cbe44a8b16473b75b042b8969d51c5"
)
GRID_MAX_PROPERTIES = {
    "mmi": ("maxmmi-grid", False),
    "pga": ("maxpga-grid", True),
    "pgv": ("maxpgv-grid", True),
    "psa0p3": ("maxpsa03-grid", True),
    "psa1p0": ("maxpsa10-grid", True),
    "psa3p0": ("maxpsa30-grid", True),
}
PayloadConsumer = Callable[[dict[str, object], bytes, dict[str, object]], None]


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def validate_identity(path: Path, expected: tuple[int, str], label: str) -> None:
    if not path.is_file():
        raise SystemExit(f"missing {label}: {path}")
    if path.stat().st_size != expected[0] or file_hash(path) != expected[1]:
        raise SystemExit(f"{label} identity mismatch")


def normalized_html(path: Path) -> str:
    text = path.read_text(encoding="utf-8", errors="replace")
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", html.unescape(text)).lower()


def validate_rights(path: Path) -> None:
    validate_identity(path, EXPECTED_RIGHTS, "USGS rights evidence")
    phrase = (
        "usgs-authored or produced data and information are considered "
        "to be in the u.s. public domain"
    )
    if phrase not in normalized_html(path):
        raise SystemExit("official USGS public-domain statement not found")


def load_selection(path: Path) -> dict[str, str]:
    with path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    if len(rows) != 1 or rows[0].get("event_id") != EVENT_ID:
        raise SystemExit("event selection count or identity changed")
    return rows[0]


def load_layers(path: Path) -> list[dict[str, object]]:
    with path.open(encoding="utf-8", newline="") as handle:
        raw = list(csv.DictReader(handle, delimiter="\t"))
    required = {
        "measure", "statistic", "series_id", "stored_units", "member",
        "size_bytes", "compressed_size_bytes", "crc32", "sha256",
        "distinct_values", "minimum", "maximum",
    }
    if len(raw) != 14 or not required.issubset(raw[0]):
        raise SystemExit("layer selection count or schema changed")
    rows: list[dict[str, object]] = []
    for source in raw:
        rows.append(
            {
                **source,
                "size_bytes": int(source["size_bytes"]),
                "compressed_size_bytes": int(source["compressed_size_bytes"]),
                "distinct_values": int(source["distinct_values"]),
                "minimum": float(source["minimum"]),
                "maximum": float(source["maximum"]),
            }
        )
    expected = [
        f"{measure}_{statistic}.flt"
        for measure in ("mmi", "pga", "pgv", "psa0p3", "psa0p6", "psa1p0", "psa3p0")
        for statistic in ("mean", "std")
    ]
    if [row["member"] for row in rows] != expected:
        raise SystemExit("layer order changed")
    return rows


def validate_event(path: Path, selection: dict[str, str]) -> dict[str, str]:
    validate_identity(path, EXPECTED_EVENT, "USGS event detail")
    event = json.loads(path.read_text(encoding="utf-8"))
    if event.get("id") != EVENT_ID:
        raise SystemExit("USGS event ID mismatch")
    properties = event.get("properties", {})
    if (
        float(properties.get("mag", 0)) != 8.8
        or properties.get("place") != selection["place"]
    ):
        raise SystemExit("USGS event identity fields changed")
    products = properties.get("products", {})
    shakemaps = products.get("shakemap", []) if isinstance(products, dict) else []
    matches = [
        product
        for product in shakemaps
        if isinstance(product, dict)
        and product.get("source") == PRODUCT_SOURCE
        and product.get("code") == PRODUCT_CODE
        and int(product.get("updateTime", 0)) == PRODUCT_UPDATE_TIME
        and product.get("status") != "DELETE"
    ]
    if len(matches) != 1:
        raise SystemExit("pinned ShakeMap product is absent or ambiguous")
    product = matches[0]
    content = product.get("contents", {}).get("download/raster.zip", {})
    if (
        int(content.get("length", 0)) != EXPECTED_RASTER[0]
        or content.get("url") != selection["raster_url"]
    ):
        raise SystemExit("pinned raster content metadata changed")
    product_properties = product.get("properties", {})
    required = {
        "event-type": "ACTUAL",
        "eventsource": "us",
        "eventsourcecode": "6000qw60",
        "magnitude": "8.8",
        "version": "16",
    }
    for key, expected in required.items():
        if product_properties.get(key) != expected:
            raise SystemExit(f"ShakeMap product property changed: {key}")
    return {str(key): str(value) for key, value in product_properties.items()}


def parse_header(raw: bytes) -> dict[str, str]:
    if hashlib.sha256(raw).hexdigest() != EXPECTED_HEADER_SHA256:
        raise ValueError("ESRI header identity changed")
    values: dict[str, str] = {}
    for line in raw.decode("ascii", errors="strict").splitlines():
        parts = line.strip().split(None, 1)
        if len(parts) != 2:
            raise ValueError(f"malformed ESRI header line: {line!r}")
        values[parts[0].upper()] = parts[1].strip()
    expected = {
        "BYTEORDER": "LSBFIRST",
        "LAYOUT": "BIL",
        "NROWS": "496",
        "NCOLS": "795",
        "NBANDS": "1",
        "NBITS": "32",
        "BANDROWBYTES": "3180.0",
        "TOTALROWBYTES": "3180.0",
        "PIXELTYPE": "FLOAT",
        "ULXMAP": "147.5",
        "ULYMAP": "58.516666666666666",
        "XDIM": "0.03333333333333333",
        "YDIM": "0.03333333333333333",
        "NODATA": "999.0",
    }
    if values != expected:
        raise ValueError("ESRI float-raster header contents changed")
    return values


def payload_profile(payload: bytes) -> dict[str, object]:
    if len(payload) != SAMPLE_BYTES:
        raise ValueError(f"raster byte count changed: {len(payload)}")
    values = array.array("f")
    values.frombytes(payload)
    if sys.byteorder != "little":
        values.byteswap()
    if len(values) != VALUE_COUNT or not all(math.isfinite(value) for value in values):
        raise ValueError("raster contains wrong count or non-finite values")
    nodata_count = values.count(999.0)
    if nodata_count:
        raise ValueError(f"raster unexpectedly contains {nodata_count} NoData cells")
    return {
        "value_count": len(values),
        "sample_size_bytes": len(payload),
        "nodata_count": nodata_count,
        "zero_count": values.count(0.0),
        "distinct_values": len(set(values)),
        "minimum": min(values),
        "maximum": max(values),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }


def validate_grid_max(
    row: dict[str, object], profile: dict[str, object], properties: dict[str, str]
) -> None:
    if row["statistic"] != "mean" or row["measure"] not in GRID_MAX_PROPERTIES:
        return
    property_name, logarithmic = GRID_MAX_PROPERTIES[str(row["measure"])]
    expected = float(properties[property_name])
    stored_max = float(profile["maximum"])
    actual = math.exp(stored_max) if logarithmic else stored_max
    if not math.isclose(actual, expected, rel_tol=0, abs_tol=0.0015):
        raise ValueError(
            f"stored maximum does not match {property_name}: {actual} vs {expected}"
        )


def validate_zip(
    archive: zipfile.ZipFile, layers: list[dict[str, object]]
) -> dict[str, zipfile.ZipInfo]:
    expected = {
        name
        for row in layers
        for name in (str(row["member"]), str(row["member"]).replace(".flt", ".hdr"))
    }
    infos = archive.infolist()
    if len(infos) != 28 or {info.filename for info in infos} != expected:
        raise SystemExit("ShakeMap raster ZIP member set changed")
    indexed: dict[str, zipfile.ZipInfo] = {}
    for info in infos:
        path = PurePosixPath(info.filename)
        if path.is_absolute() or ".." in path.parts or info.is_dir():
            raise SystemExit(f"unsafe ZIP member: {info.filename}")
        if info.flag_bits & 1 or stat.S_ISLNK(info.external_attr >> 16):
            raise SystemExit(f"encrypted or linked ZIP member: {info.filename}")
        indexed[info.filename] = info
    return indexed


def scan_source(
    selection_path: Path,
    layers_path: Path,
    rights: Path,
    event: Path,
    raster: Path,
    consumer: PayloadConsumer | None = None,
) -> dict[str, object]:
    selection = load_selection(selection_path)
    layers = load_layers(layers_path)
    validate_rights(rights)
    properties = validate_event(event, selection)
    validate_identity(raster, EXPECTED_RASTER, "ShakeMap raster archive")
    profiles: list[dict[str, object]] = []
    output_hashes: set[str] = set()
    with zipfile.ZipFile(raster) as archive:
        infos = validate_zip(archive, layers)
        for row in layers:
            member = str(row["member"])
            info = infos[member]
            if (
                info.file_size != row["size_bytes"]
                or info.compress_size != row["compressed_size_bytes"]
                or f"{info.CRC:08x}" != row["crc32"]
            ):
                raise SystemExit(f"ZIP metadata changed: {member}")
            header_name = member.replace(".flt", ".hdr")
            try:
                parse_header(archive.read(header_name))
                payload = archive.read(info)
                metrics = payload_profile(payload)
                validate_grid_max(row, metrics, properties)
            except ValueError as error:
                raise SystemExit(f"{member}: {error}") from error
            for key in ("sha256", "distinct_values", "minimum", "maximum"):
                if metrics[key] != row[key]:
                    raise SystemExit(f"pinned layer profile changed: {member} {key}")
            digest = str(metrics["sha256"])
            if digest in output_hashes:
                raise SystemExit(f"duplicate raster payload: {member}")
            output_hashes.add(digest)
            profile = {
                "measure": row["measure"],
                "statistic": row["statistic"],
                "series_id": row["series_id"],
                "stored_units": row["stored_units"],
                "source_member": member,
                "shape": [HEIGHT, WIDTH],
                **metrics,
            }
            profiles.append(profile)
            if consumer is not None:
                consumer(row, payload, profile)
    result = {
        "dataset_id": DATASET_ID,
        "event_id": EVENT_ID,
        "magnitude": 8.8,
        "place": selection["place"],
        "product_source": PRODUCT_SOURCE,
        "product_code": PRODUCT_CODE,
        "product_update_time_ms": PRODUCT_UPDATE_TIME,
        "license": "U.S. Government Public Domain",
        "grid_shape": [HEIGHT, WIDTH],
        "upper_left_map": [147.5, 58.516666666666666],
        "pixel_size_degrees": [0.03333333333333333, 0.03333333333333333],
        "sample_count": len(profiles),
        "value_count": sum(int(profile["value_count"]) for profile in profiles),
        "total_size_bytes": sum(int(profile["sample_size_bytes"]) for profile in profiles),
        "rights_sha256": file_hash(rights),
        "event_sha256": file_hash(event),
        "raster_sha256": file_hash(raster),
        "layer_profiles": profiles,
    }
    if result["value_count"] != EXPECTED_VALUES or result["total_size_bytes"] != EXPECTED_BYTES:
        raise SystemExit("aggregate output totals changed")
    return result


def preflight(args: argparse.Namespace) -> None:
    result = scan_source(
        args.selection, args.layers, args.rights, args.event, args.raster
    )
    args.profile.parent.mkdir(parents=True, exist_ok=True)
    args.profile.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps({k: v for k, v in result.items() if k != "layer_profiles"}, indent=2, sort_keys=True))


def build(args: argparse.Namespace) -> None:
    if args.samples_dir.exists():
        shutil.rmtree(args.samples_dir)
    args.samples_dir.mkdir(parents=True)
    args.index.parent.mkdir(parents=True, exist_ok=True)
    index_rows: list[dict[str, object]] = []

    def emit(row: dict[str, object], payload: bytes, profile: dict[str, object]) -> None:
        series_id = str(row["series_id"])
        output_dir = args.samples_dir / series_id
        output_dir.mkdir(exist_ok=True)
        output = output_dir / f"{row['measure']}_{row['statistic']}_y496_x795.bin"
        output.write_bytes(payload)
        index_rows.append(
            {
                "dataset_id": DATASET_ID,
                "series_id": series_id,
                "role": "primary",
                "sample_path": output.relative_to(args.data_root).as_posix(),
                "source_sample": args.raster.relative_to(args.data_root).as_posix(),
                "source_member": row["member"],
                "event_id": EVENT_ID,
                "measure": row["measure"],
                "statistic": row["statistic"],
                "stored_units": row["stored_units"],
                "numeric_kind": "float",
                "bit_width": 32,
                "endianness": "little",
                "element_size_bytes": 4,
                "value_count": profile["value_count"],
                "sample_size_bytes": profile["sample_size_bytes"],
                "sample_format": "raw homogeneous IEEE-754 float32 ShakeMap raster",
                "sample_geometry": "earthquake_ground_motion_grid_2d",
                "sample_rank": 2,
                "sample_shape": [HEIGHT, WIDTH],
                "sample_axes": ["latitude_north_to_south", "longitude_west_to_east"],
                "natural_record_kind": "complete_shakemap_measure_statistic_layer",
                "nodata_count": profile["nodata_count"],
                "zero_count": profile["zero_count"],
                "distinct_values": profile["distinct_values"],
                "minimum": profile["minimum"],
                "maximum": profile["maximum"],
                "sha256": profile["sha256"],
            }
        )

    summary = scan_source(
        args.selection, args.layers, args.rights, args.event, args.raster, emit
    )
    args.index.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in index_rows),
        encoding="utf-8",
    )
    args.stats.parent.mkdir(parents=True, exist_ok=True)
    args.stats.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    print(f"built_samples={summary['sample_count']} values={summary['value_count']} bytes={summary['total_size_bytes']}")


def verify(args: argparse.Namespace) -> None:
    if not args.index.is_file() or not args.stats.is_file():
        raise SystemExit("missing index or stats; run build first")
    indexed = [json.loads(line) for line in args.index.read_text().splitlines() if line.strip()]
    cursor = 0
    expected_outputs: set[Path] = set()

    def compare(row: dict[str, object], payload: bytes, profile: dict[str, object]) -> None:
        nonlocal cursor
        if cursor >= len(indexed):
            raise SystemExit("sample index has fewer rows than source layers")
        entry = indexed[cursor]
        cursor += 1
        required = {
            "dataset_id": DATASET_ID,
            "series_id": row["series_id"],
            "role": "primary",
            "source_member": row["member"],
            "event_id": EVENT_ID,
            "measure": row["measure"],
            "statistic": row["statistic"],
            "stored_units": row["stored_units"],
            "numeric_kind": "float",
            "bit_width": 32,
            "endianness": "little",
            "element_size_bytes": 4,
            "value_count": profile["value_count"],
            "sample_size_bytes": profile["sample_size_bytes"],
            "sample_shape": [HEIGHT, WIDTH],
            "nodata_count": profile["nodata_count"],
            "zero_count": profile["zero_count"],
            "distinct_values": profile["distinct_values"],
            "minimum": profile["minimum"],
            "maximum": profile["maximum"],
            "sha256": profile["sha256"],
        }
        for key, expected in required.items():
            if entry.get(key) != expected:
                raise SystemExit(f"index mismatch for {row['member']}: {key}")
        output = args.data_root / str(entry.get("sample_path", ""))
        if not output.is_file() or output.read_bytes() != payload:
            raise SystemExit(f"output differs from fresh raster extraction: {output}")
        expected_outputs.add(output.resolve())

    summary = scan_source(
        args.selection, args.layers, args.rights, args.event, args.raster, compare
    )
    if cursor != len(indexed):
        raise SystemExit("sample index has extra rows")
    actual_outputs = {path.resolve() for path in args.samples_dir.rglob("*.bin")}
    if actual_outputs != expected_outputs:
        raise SystemExit("sample directory contains missing or stale outputs")
    if json.loads(args.stats.read_text()) != summary:
        raise SystemExit("ingest stats differ from fresh source scan")
    print(f"verified_samples={cursor} values={summary['value_count']} bytes={summary['total_size_bytes']}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("preflight", "build", "verify"))
    parser.add_argument("--selection", type=Path, required=True)
    parser.add_argument("--layers", type=Path, required=True)
    parser.add_argument("--rights", type=Path, required=True)
    parser.add_argument("--event", type=Path, required=True)
    parser.add_argument("--raster", type=Path, required=True)
    parser.add_argument("--profile", type=Path)
    parser.add_argument("--samples-dir", type=Path)
    parser.add_argument("--index", type=Path)
    parser.add_argument("--stats", type=Path)
    parser.add_argument("--data-root", type=Path)
    args = parser.parse_args()
    if args.command == "preflight":
        if args.profile is None:
            parser.error("preflight requires --profile")
        preflight(args)
    elif args.command == "build":
        if any(value is None for value in (args.samples_dir, args.index, args.stats, args.data_root)):
            parser.error("build requires --samples-dir, --index, --stats, and --data-root")
        build(args)
    else:
        if any(value is None for value in (args.samples_dir, args.index, args.stats, args.data_root)):
            parser.error("verify requires --samples-dir, --index, --stats, and --data-root")
        verify(args)


if __name__ == "__main__":
    main()
