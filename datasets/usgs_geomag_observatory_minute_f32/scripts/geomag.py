#!/usr/bin/env python3
# Download validation, decoding, and independent verification helpers.
from __future__ import annotations

import argparse
import calendar
import datetime as dt
import hashlib
import json
import math
from pathlib import Path
import shutil
import statistics
import struct
import subprocess
import urllib.parse


DATASET_ID = "usgs_geomag_observatory_minute_f32"
BASE_URL = "https://geomag.usgs.gov/ws/data/"
YEAR = 2024
STATIONS = {
    "BOU": "Boulder",
    "CMO": "College",
    "FRD": "Fredericksburg",
    "HON": "Honolulu",
}
COMPONENTS = ("X", "Y", "Z")
EXPECTED_YEAR_MINUTES = 366 * 24 * 60
MIN_YEAR_VALUES = math.floor(EXPECTED_YEAR_MINUTES * 0.95)
MAX_SOURCE_BYTES = 500_000_000
MAX_PRIMARY_BYTES = 1_000_000_000
MAX_RESPONSE_BYTES = 12_000_000
MIN_FETCH_MINUTES = 360
USER_AGENT = "openzl-public-datasets-usgs-geomag-f32/1.0"


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def month_bounds(month: int) -> tuple[str, str, int]:
    days = calendar.monthrange(YEAR, month)[1]
    start = f"{YEAR}-{month:02d}-01T00:00:00Z"
    end = f"{YEAR}-{month:02d}-{days:02d}T23:59:00Z"
    return start, end, days * 24 * 60


def make_url(station: str, start: str, end: str) -> str:
    params = {
        "id": station,
        "starttime": start,
        "endtime": end,
        "elements": "X,Y,Z,F",
        "sampling_period": "60",
        "type": "variation",
        "format": "json",
    }
    return BASE_URL + "?" + urllib.parse.urlencode(params)


def expected_rows() -> list[dict[str, object]]:
    rows = []
    for station in STATIONS:
        for month in range(1, 13):
            start, end, expected = month_bounds(month)
            rows.append(
                {
                    "station": station,
                    "month": f"{YEAR}-{month:02d}",
                    "start": start,
                    "end": end,
                    "expected_minutes": expected,
                    "filename": f"{station.lower()}_{YEAR}_{month:02d}.json",
                    "url": make_url(station, start, end),
                }
            )
    return rows


def command_make_plan(args: argparse.Namespace) -> None:
    path = Path(args.output)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        handle.write("station\tmonth\tstart\tend\tfilename\turl\n")
        for row in expected_rows():
            handle.write(
                "\t".join(
                    str(row[key])
                    for key in ("station", "month", "start", "end", "filename", "url")
                )
                + "\n"
            )
    print(f"planned resources={len(expected_rows())} path={path}")


def parse_timestamp(value: str) -> dt.datetime:
    return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))


def timestamp_text(value: dt.datetime) -> str:
    return value.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_response(raw: bytes, expected: dict[str, object], label: str) -> dict[str, object]:
    if not raw or raw.lstrip().startswith(b"<"):
        raise ValueError(f"not JSON data: {label}")
    payload = json.loads(raw)
    if not isinstance(payload, dict) or payload.get("type") != "Timeseries":
        raise ValueError(f"unexpected JSON root/type: {label}")
    metadata = payload.get("metadata")
    if not isinstance(metadata, dict) or int(metadata.get("status", 0)) != 200:
        raise ValueError(f"unsuccessful API metadata: {label}")
    intermagnet = metadata.get("intermagnet")
    if not isinstance(intermagnet, dict):
        raise ValueError(f"missing INTERMAGNET metadata: {label}")
    imo = intermagnet.get("imo")
    if not isinstance(imo, dict) or imo.get("iaga_code") != expected["station"]:
        raise ValueError(f"station mismatch: {label}")
    if intermagnet.get("data_type") != "variation":
        raise ValueError(f"unexpected data type: {label}")
    if float(intermagnet.get("sampling_period", 0)) != 60.0:
        raise ValueError(f"unexpected sampling period: {label}")

    times = payload.get("times")
    expected_minutes = int(expected["expected_minutes"])
    if not isinstance(times, list) or len(times) != expected_minutes:
        raise ValueError(
            f"timestamp count mismatch: {label} expected={expected_minutes} "
            f"actual={len(times) if isinstance(times, list) else 'not-list'}"
        )
    first = parse_timestamp(str(times[0]))
    last = parse_timestamp(str(times[-1]))
    if first != parse_timestamp(str(expected["start"])) or last != parse_timestamp(str(expected["end"])):
        raise ValueError(f"timestamp boundary mismatch: {label}")
    for index in range(1, len(times)):
        previous = parse_timestamp(str(times[index - 1]))
        current = parse_timestamp(str(times[index]))
        if current - previous != dt.timedelta(minutes=1):
            raise ValueError(f"non-minute timestamp step: {label} index={index}")

    entries = payload.get("values")
    if not isinstance(entries, list):
        raise ValueError(f"missing component entries: {label}")
    by_id = {}
    for entry in entries:
        if not isinstance(entry, dict) or not isinstance(entry.get("id"), str):
            raise ValueError(f"malformed component entry: {label}")
        component = str(entry["id"])
        values = entry.get("values")
        if not isinstance(values, list) or len(values) != len(times):
            raise ValueError(f"component length mismatch: {label} component={component}")
        by_id[component] = values
    for component in COMPONENTS:
        if component not in by_id:
            raise ValueError(f"missing component: {label} component={component}")

    return {
        "raw": raw,
        "payload": payload,
        "times": times,
        "components": by_id,
        "metadata": intermagnet,
    }


def load_month(path: Path, expected: dict[str, object]) -> dict[str, object]:
    return parse_response(path.read_bytes(), expected, str(path))


def curl_bytes(url: str) -> tuple[bytes | None, str]:
    command = [
        "curl",
        "--fail-with-body",
        "--silent",
        "--show-error",
        "--location",
        "--retry",
        "4",
        "--retry-delay",
        "3",
        "--max-time",
        "300",
        "--max-filesize",
        str(MAX_RESPONSE_BYTES),
        "--user-agent",
        USER_AGENT,
        url,
    ]
    result = subprocess.run(command, check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if result.returncode:
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        body = result.stdout.decode("utf-8", errors="replace").strip()[:500]
        return None, f"rc={result.returncode} {detail} response={body}"
    if len(result.stdout) > MAX_RESPONSE_BYTES:
        return None, f"response exceeded {MAX_RESPONSE_BYTES} bytes"
    return result.stdout, ""


def interval_expected(station: str, start: dt.datetime, end: dt.datetime) -> dict[str, object]:
    minutes = int((end - start).total_seconds() // 60) + 1
    return {
        "station": station,
        "start": timestamp_text(start),
        "end": timestamp_text(end),
        "expected_minutes": minutes,
    }


def fetch_interval(station: str, start: dt.datetime, end: dt.datetime) -> list[dict[str, object]]:
    expected = interval_expected(station, start, end)
    url = make_url(station, str(expected["start"]), str(expected["end"]))
    raw, error = curl_bytes(url)
    if raw is not None:
        try:
            parsed = parse_response(raw, expected, url)
        except Exception as exc:
            error = str(exc)
        else:
            print(
                f"fetch_ok station={station} start={expected['start']} end={expected['end']} "
                f"minutes={expected['expected_minutes']} bytes={len(raw)}"
            )
            return [{"expected": expected, "url": url, "raw": raw, "parsed": parsed}]

    minutes = int(expected["expected_minutes"])
    if minutes <= MIN_FETCH_MINUTES:
        raise RuntimeError(
            f"USGS interval failed at minimum span station={station} "
            f"start={expected['start']} end={expected['end']} detail={error}"
        )
    left_minutes = minutes // 2
    left_end = start + dt.timedelta(minutes=left_minutes - 1)
    right_start = left_end + dt.timedelta(minutes=1)
    print(
        f"fetch_split station={station} start={expected['start']} end={expected['end']} "
        f"minutes={minutes} detail={error}"
    )
    return fetch_interval(station, start, left_end) + fetch_interval(station, right_start, end)


def assemble_month(expected: dict[str, object], chunks: list[dict[str, object]], chunk_dir: Path) -> bytes:
    chunk_dir.mkdir(parents=True, exist_ok=True)
    times: list[object] = []
    component_values: dict[str, list[object]] = {}
    component_metadata: dict[str, object] = {}
    chunk_records = []
    for index, chunk in enumerate(chunks):
        parsed = chunk["parsed"]
        times.extend(parsed["times"])
        for entry in parsed["payload"]["values"]:
            component = str(entry["id"])
            component_values.setdefault(component, []).extend(entry["values"])
            component_metadata.setdefault(component, entry.get("metadata", {}))
        raw = chunk["raw"]
        filename = f"chunk_{index:03d}.json"
        path = chunk_dir / filename
        path.write_bytes(raw)
        chunk_records.append(
            {
                "file": f"chunks/{chunk_dir.parent.name}/{chunk_dir.name}/{filename}",
                "url": chunk["url"],
                "start": chunk["expected"]["start"],
                "end": chunk["expected"]["end"],
                "minutes": chunk["expected"]["expected_minutes"],
                "bytes": len(raw),
                "sha256": sha256_bytes(raw),
            }
        )
    first = chunks[0]["parsed"]["payload"]
    payload = {
        "type": first["type"],
        "metadata": first["metadata"],
        "times": times,
        "values": [
            {"id": component, "metadata": component_metadata[component], "values": component_values[component]}
            for component in component_values
        ],
        "_openzl_source_chunks": chunk_records,
    }
    raw = (json.dumps(payload, separators=(",", ":"), ensure_ascii=False) + "\n").encode("utf-8")
    parse_response(raw, expected, "assembled monthly response")
    return raw


def command_fetch(args: argparse.Namespace) -> None:
    download_dir = Path(args.download_dir)
    chunk_root = download_dir / "chunks"
    download_dir.mkdir(parents=True, exist_ok=True)
    chunk_root.mkdir(parents=True, exist_ok=True)
    force = str(args.force) == "1"
    for expected in expected_rows():
        target = download_dir / str(expected["filename"])
        if target.is_file() and target.stat().st_size > 0 and not force:
            load_month(target, expected)
            print(f"cache_hit station={expected['station']} month={expected['month']} path={target}")
            continue
        start = parse_timestamp(str(expected["start"]))
        end = parse_timestamp(str(expected["end"]))
        chunks = fetch_interval(str(expected["station"]), start, end)
        chunk_dir = chunk_root / str(expected["station"]).lower() / str(expected["month"])
        chunk_dir.mkdir(parents=True, exist_ok=True)
        assembled = assemble_month(expected, chunks, chunk_dir)
        target.with_suffix(target.suffix + ".part").write_bytes(assembled)
        target.with_suffix(target.suffix + ".part").replace(target)
        print(
            f"month_assembled station={expected['station']} month={expected['month']} "
            f"chunks={len(chunks)} bytes={len(assembled)}"
        )


def retained_values(values: list[object]) -> tuple[list[float], int]:
    result: list[float] = []
    missing = 0
    for value in values:
        if value is None or isinstance(value, bool):
            missing += 1
            continue
        try:
            number = float(value)
        except (TypeError, ValueError):
            missing += 1
            continue
        if not math.isfinite(number) or abs(number) >= 90_000:
            missing += 1
            continue
        result.append(number)
    return result, missing


def validate_all(download_dir: Path) -> tuple[list[dict[str, object]], int]:
    inventory = []
    total_bytes = 0
    for expected in expected_rows():
        path = download_dir / str(expected["filename"])
        if not path.is_file():
            raise FileNotFoundError(f"missing response: {path}")
        parsed = load_month(path, expected)
        raw = parsed["raw"]
        chunks = parsed["payload"].get("_openzl_source_chunks")
        if not isinstance(chunks, list) or not chunks:
            raise ValueError(f"missing raw source-chunk inventory: {path}")
        checked_chunks = []
        for chunk in chunks:
            if not isinstance(chunk, dict):
                raise ValueError(f"malformed source-chunk inventory: {path}")
            chunk_path = download_dir / str(chunk.get("file", ""))
            chunk_raw = chunk_path.read_bytes()
            if len(chunk_raw) != int(chunk.get("bytes", -1)):
                raise ValueError(f"source chunk size mismatch: {chunk_path}")
            if sha256_bytes(chunk_raw) != chunk.get("sha256"):
                raise ValueError(f"source chunk hash mismatch: {chunk_path}")
            total_bytes += len(chunk_raw)
            checked_chunks.append(chunk)
        component_stats = {}
        for component in COMPONENTS:
            values, missing = retained_values(parsed["components"][component])
            if len(values) < int(expected["expected_minutes"]) * 0.90:
                raise ValueError(f"too many missing values: {path} component={component}")
            if len(set(values)) <= 1:
                raise ValueError(f"constant component: {path} component={component}")
            component_stats[component] = {
                "retained": len(values),
                "missing": missing,
                "minimum": min(values),
                "maximum": max(values),
            }
        inventory.append(
            {
                **expected,
                "bytes": len(raw),
                "sha256": sha256_bytes(raw),
                "source_chunks": checked_chunks,
                "station_name": parsed["metadata"]["imo"]["name"],
                "reported_orientation": parsed["metadata"].get("reported_orientation"),
                "digital_sampling_rate": parsed["metadata"].get("digital_sampling_rate"),
                "components": component_stats,
            }
        )
    if total_bytes > MAX_SOURCE_BYTES:
        raise ValueError(f"source responses exceed cap: {total_bytes}")
    return inventory, total_bytes


def command_validate_download(args: argparse.Namespace) -> None:
    download_dir = Path(args.download_dir)
    inventory, total_bytes = validate_all(download_dir)
    output = {
        "dataset_id": DATASET_ID,
        "year": YEAR,
        "product_type": "variation",
        "sampling_period_seconds": 60,
        "resource_count": len(inventory),
        "source_bytes": total_bytes,
        "resources": inventory,
    }
    path = Path(args.inventory)
    path.write_text(json.dumps(output, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"validated resources={len(inventory)} source_bytes={total_bytes} inventory={path}")


def source_series(download_dir: Path) -> dict[tuple[str, str], dict[str, object]]:
    result = {
        (station, component): {"values": [], "missing": 0, "source_files": []}
        for station in STATIONS
        for component in COMPONENTS
    }
    for expected in expected_rows():
        parsed = load_month(download_dir / str(expected["filename"]), expected)
        for component in COMPONENTS:
            values, missing = retained_values(parsed["components"][component])
            row = result[(str(expected["station"]), component)]
            row["values"].extend(values)
            row["missing"] = int(row["missing"]) + missing
            row["source_files"].append(str(expected["filename"]))
    return result


def packed_f32(values: list[float]) -> bytes:
    output = bytearray()
    for value in values:
        output.extend(struct.pack("<f", value))
    return bytes(output)


def build_rows(download_dir: Path, samples_dir: Path) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    source = source_series(download_dir)
    rows = []
    records = []
    for (station, component), item in sorted(source.items()):
        values = item["values"]
        if len(values) < MIN_YEAR_VALUES:
            raise ValueError(
                f"year coverage below 95 percent: station={station} component={component} "
                f"values={len(values)} expected={EXPECTED_YEAR_MINUTES}"
            )
        data = packed_f32(values)
        unpacked = struct.unpack(f"<{len(values)}f", data)
        if len(set(unpacked)) <= 1:
            raise ValueError(f"constant float32 output: station={station} component={component}")
        series_id = "usgs_geomag_xyz_minute_f32"
        out_dir = samples_dir / series_id
        out_dir.mkdir(parents=True, exist_ok=True)
        filename = f"{station.lower()}_{component.lower()}_{YEAR}_n{len(values)}.bin"
        path = out_dir / filename
        path.write_bytes(data)
        row = {
            "dataset_id": DATASET_ID,
            "series_id": series_id,
            "role": "primary",
            "sample_path": f"samples/{DATASET_ID}/{series_id}/{filename}",
            "numeric_kind": "float",
            "bit_width": 32,
            "endianness": "little",
            "element_size_bytes": 4,
            "sample_size_bytes": len(data),
            "value_count": len(values),
            "sample_format": "raw homogeneous IEEE-754 float32 time-series array",
            "sample_geometry": "geomagnetic_observatory_component_year",
            "sample_rank": 1,
            "sample_shape": [len(values)],
            "sample_axes": ["valid_minute_observation"],
            "natural_record_kind": "observatory_component_calendar_year",
            "station": station,
            "station_name": STATIONS[station],
            "component": component,
            "unit": "nT",
            "year": YEAR,
            "expected_minute_slots": EXPECTED_YEAR_MINUTES,
            "missing_slots": int(item["missing"]),
            "source_files": item["source_files"],
            "sha256": sha256_bytes(data),
            "minimum_f32": min(unpacked),
            "maximum_f32": max(unpacked),
        }
        rows.append(row)
        records.append(
            {
                "station": station,
                "station_name": STATIONS[station],
                "component": component,
                "values": len(values),
                "missing_slots": int(item["missing"]),
                "bytes": len(data),
                "sha256": row["sha256"],
                "minimum_f32": row["minimum_f32"],
                "maximum_f32": row["maximum_f32"],
            }
        )
    return rows, records


def command_build(args: argparse.Namespace) -> None:
    download_dir = Path(args.download_dir)
    validate_all(download_dir)
    samples_dir = Path(args.samples_dir)
    if samples_dir.exists():
        shutil.rmtree(samples_dir)
    samples_dir.mkdir(parents=True)
    rows, records = build_rows(download_dir, samples_dir)
    total_bytes = sum(int(row["sample_size_bytes"]) for row in rows)
    total_values = sum(int(row["value_count"]) for row in rows)
    if total_bytes > MAX_PRIMARY_BYTES:
        raise ValueError(f"primary output exceeds cap: {total_bytes}")
    index = Path(args.index)
    index.parent.mkdir(parents=True, exist_ok=True)
    with index.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")
    counts = sorted(int(row["value_count"]) for row in rows)
    stats = {
        "dataset_id": DATASET_ID,
        "year": YEAR,
        "samples": len(rows),
        "stations": len(STATIONS),
        "components": list(COMPONENTS),
        "primary_values": total_values,
        "primary_sample_bytes": total_bytes,
        "median_value_count": statistics.median(counts),
        "min_value_count": counts[0],
        "max_value_count": counts[-1],
        "records": records,
    }
    stats_path = Path(args.stats)
    stats_path.parent.mkdir(parents=True, exist_ok=True)
    stats_path.write_text(json.dumps(stats, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        f"built samples={len(rows)} primary_values={total_values} "
        f"primary_bytes={total_bytes} median_values={statistics.median(counts)}"
    )


def command_verify(args: argparse.Namespace) -> None:
    download_dir = Path(args.download_dir)
    samples_dir = Path(args.samples_dir)
    index_path = Path(args.index)
    stats_path = Path(args.stats)
    if not index_path.is_file() or not stats_path.is_file():
        raise FileNotFoundError("missing index or ingest stats")
    indexed = [json.loads(line) for line in index_path.read_text().splitlines() if line.strip()]
    stats = json.loads(stats_path.read_text())
    if len(indexed) != len(STATIONS) * len(COMPONENTS):
        raise ValueError(f"unexpected sample count: {len(indexed)}")

    source = source_series(download_dir)
    total_bytes = 0
    total_values = 0
    seen = set()
    for row in indexed:
        if row.get("dataset_id") != DATASET_ID or row.get("series_id") != "usgs_geomag_xyz_minute_f32":
            raise ValueError("unexpected dataset or series ID")
        if row.get("numeric_kind") != "float" or int(row.get("bit_width", 0)) != 32:
            raise ValueError("sample is not float32")
        if row.get("endianness") != "little" or int(row.get("element_size_bytes", 0)) != 4:
            raise ValueError("sample is not canonical little-endian float32")
        station = str(row["station"])
        component = str(row["component"])
        key = (station, component)
        if key in seen or key not in source:
            raise ValueError(f"duplicate or unexpected sample: {key}")
        seen.add(key)
        expected_data = packed_f32(source[key]["values"])
        path = samples_dir / "usgs_geomag_xyz_minute_f32" / Path(str(row["sample_path"])).name
        actual = path.read_bytes()
        if actual != expected_data:
            raise ValueError(f"source/output mismatch: {path}")
        if len(actual) != int(row["sample_size_bytes"]) or len(actual) != int(row["value_count"]) * 4:
            raise ValueError(f"size metadata mismatch: {path}")
        if sha256_bytes(actual) != row.get("sha256"):
            raise ValueError(f"hash mismatch: {path}")
        if int(row["value_count"]) < MIN_YEAR_VALUES:
            raise ValueError(f"coverage floor failed: {path}")
        values = struct.unpack(f"<{int(row['value_count'])}f", actual)
        if any(not math.isfinite(value) for value in values) or len(set(values)) <= 1:
            raise ValueError(f"invalid float payload: {path}")
        total_bytes += len(actual)
        total_values += len(values)

    if seen != set(source):
        raise ValueError("station/component coverage mismatch")
    counts = [int(row["value_count"]) for row in indexed]
    if statistics.median(counts) < 1_000:
        raise ValueError("median sample floor failed")
    if total_values < 10_000 or total_bytes < 100_000:
        raise ValueError("aggregate acceptance floor failed")
    if total_bytes > MAX_PRIMARY_BYTES:
        raise ValueError("primary output cap exceeded")
    if int(stats.get("primary_values", -1)) != total_values:
        raise ValueError("stats primary-value total mismatch")
    if int(stats.get("primary_sample_bytes", -1)) != total_bytes:
        raise ValueError("stats primary-byte total mismatch")
    print(
        f"verified dataset={DATASET_ID} samples={len(indexed)} "
        f"primary_values={total_values} primary_bytes={total_bytes} "
        f"median_values={int(statistics.median(counts))}"
    )


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser()
    commands = root.add_subparsers(dest="command", required=True)
    make_plan = commands.add_parser("make-plan")
    make_plan.add_argument("--output", required=True)
    make_plan.set_defaults(func=command_make_plan)
    validate = commands.add_parser("validate-download")
    validate.add_argument("--download-dir", required=True)
    validate.add_argument("--inventory", required=True)
    validate.set_defaults(func=command_validate_download)
    fetch = commands.add_parser("fetch")
    fetch.add_argument("--download-dir", required=True)
    fetch.add_argument("--force", default="0")
    fetch.set_defaults(func=command_fetch)
    build = commands.add_parser("build")
    build.add_argument("--download-dir", required=True)
    build.add_argument("--samples-dir", required=True)
    build.add_argument("--index", required=True)
    build.add_argument("--stats", required=True)
    build.set_defaults(func=command_build)
    verify = commands.add_parser("verify")
    verify.add_argument("--download-dir", required=True)
    verify.add_argument("--samples-dir", required=True)
    verify.add_argument("--index", required=True)
    verify.add_argument("--stats", required=True)
    verify.set_defaults(func=command_verify)
    return root


if __name__ == "__main__":
    arguments = parser().parse_args()
    arguments.func(arguments)
