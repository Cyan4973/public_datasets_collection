#!/usr/bin/env python3
# Download validation, scan decoding, building, and verification.
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import re
import shutil
import statistics
import struct
import zipfile


DATASET_ID = "zenodo_powder_xrd_patterns_f32"
RECORD_ID = 4_955_141
EXPECTED_TITLE = "Data from: Pressure-induced symmetry changes in body-centred cubic zeolites"
EXPECTED_LICENSES = {"cc-zero", "cc0-1.0"}
ARCHIVE_NAME = "Cubic_High-Pressure_Repository.zip"
ARCHIVE_SIZE = 36_220_726
ARCHIVE_MD5 = "7c674d184639b5d84a387af11930da6d"
EXPECTED_SAMPLES = 147
EXPECTED_VALUES = 647_009
EXPECTED_BYTES = 2_588_036
EXPECTED_GROUPS = {
    ("Na-X", "empty"): 36,
    ("Na-X", "filled"): 38,
    ("RHO", "empty"): 34,
    ("RHO", "filled"): 39,
}
EXPECTED_DUPLICATES = {
    "Cubic High-Pressure Repository/Zeolite Na-X/Filled_data/zFAUf_p19.xy":
        "Cubic High-Pressure Repository/Zeolite Na-X/Filled_data/zFAUf_p18.xy",
}
MIN_ROWS = 1_000
MAX_MEMBER_BYTES = 5 * 1024 * 1024
MAX_PRIMARY_BYTES = 1_000_000_000
PATH_PATTERN = re.compile(
    r"^Cubic High-Pressure Repository/Zeolite (?P<zeolite>Na-X|RHO)/"
    r"(?P<state>Empty_data|Filled_data)/(?P<basename>[^/]+\.xy)$",
    re.IGNORECASE,
)


def digest(path: Path, algorithm: str) -> str:
    value = hashlib.new(algorithm)
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def normalized_license(record: dict[str, object]) -> str:
    metadata = record.get("metadata", {})
    if not isinstance(metadata, dict):
        return ""
    value = metadata.get("license", {})
    if isinstance(value, dict):
        raw = str(value.get("id") or value.get("title") or "")
    else:
        raw = str(value or "")
    return re.sub(r"-+", "-", raw.lower().strip().replace("_", "-").replace(" ", "-"))


def validate_download(record_path: Path, archive_path: Path) -> dict[str, object]:
    if not record_path.is_file() or not archive_path.is_file():
        raise FileNotFoundError("record metadata or archive is missing")
    record = json.loads(record_path.read_text(encoding="utf-8"))
    if int(record.get("id", 0)) != RECORD_ID:
        raise ValueError("Zenodo record ID mismatch")
    metadata = record.get("metadata", {})
    if not isinstance(metadata, dict) or metadata.get("title") != EXPECTED_TITLE:
        raise ValueError("Zenodo record title mismatch")
    if normalized_license(record) not in EXPECTED_LICENSES:
        raise ValueError("Zenodo record no longer declares CC0")
    files = record.get("files", [])
    if not isinstance(files, list):
        raise ValueError("Zenodo file inventory is missing")
    matching = [item for item in files if isinstance(item, dict) and item.get("key") == "Cubic High-Pressure Repository.zip"]
    if len(matching) != 1:
        raise ValueError("pinned archive is absent or ambiguous in record metadata")
    source = matching[0]
    if int(source.get("size", 0)) != ARCHIVE_SIZE:
        raise ValueError("Zenodo archive size metadata changed")
    checksum = str(source.get("checksum", ""))
    if checksum.lower() != f"md5:{ARCHIVE_MD5}":
        raise ValueError("Zenodo archive checksum metadata changed")
    if archive_path.stat().st_size != ARCHIVE_SIZE:
        raise ValueError("downloaded archive size mismatch")
    if digest(archive_path, "md5") != ARCHIVE_MD5:
        raise ValueError("downloaded archive MD5 mismatch")
    return record


def parse_xy(raw: bytes, member_name: str) -> tuple[list[float], list[float]]:
    text = raw.decode("utf-8-sig", errors="strict")
    coordinates = []
    intensities = []
    data_started = False
    for line_number, raw_line in enumerate(text.splitlines(), 1):
        line = raw_line.strip()
        if not line or line.startswith(("#", "%", ";", "//")):
            continue
        tokens = [token for token in re.split(r"[\s,;]+", line) if token]
        if len(tokens) != 2:
            if not data_started:
                continue
            raise ValueError(f"non-two-column row after data start: {member_name}:{line_number}")
        try:
            coordinate = float(tokens[0].replace("D", "E").replace("d", "e"))
            intensity = float(tokens[1].replace("D", "E").replace("d", "e"))
        except ValueError:
            if not data_started:
                continue
            raise ValueError(f"nonnumeric row after data start: {member_name}:{line_number}")
        if not math.isfinite(coordinate) or not math.isfinite(intensity):
            raise ValueError(f"nonfinite value: {member_name}:{line_number}")
        data_started = True
        coordinates.append(coordinate)
        intensities.append(intensity)
    if len(intensities) < MIN_ROWS:
        raise ValueError(f"scan below row floor: {member_name}")
    if any(right <= left for left, right in zip(coordinates, coordinates[1:])):
        raise ValueError(f"scan coordinate is not strictly increasing: {member_name}")
    if len(set(intensities)) < 32 or min(intensities) == max(intensities):
        raise ValueError(f"scan intensity is degenerate: {member_name}")
    return coordinates, intensities


def packed_f32(values: list[float]) -> bytes:
    output = bytearray()
    for value in values:
        output.extend(struct.pack("<f", value))
    return bytes(output)


def read_scans(archive_path: Path) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    scans = []
    duplicates = []
    with zipfile.ZipFile(archive_path) as archive:
        infos = archive.infolist()
        names = [info.filename for info in infos]
        if len(names) != len(set(names)):
            raise ValueError("ZIP contains duplicate member names")
        for info in sorted(infos, key=lambda item: item.filename):
            if info.flag_bits & 1:
                raise ValueError(f"encrypted ZIP member: {info.filename}")
            if info.filename.startswith("/") or ".." in Path(info.filename).parts:
                raise ValueError(f"unsafe ZIP member path: {info.filename}")
            match = PATH_PATTERN.fullmatch(info.filename)
            if not match:
                continue
            if not 0 < info.file_size <= MAX_MEMBER_BYTES:
                raise ValueError(f"eligible member size outside bounds: {info.filename}")
            raw = archive.read(info)
            if len(raw) != info.file_size:
                raise ValueError(f"ZIP member size mismatch: {info.filename}")
            coordinates, intensities = parse_xy(raw, info.filename)
            data = packed_f32(intensities)
            scans.append(
                {
                    "member_name": info.filename,
                    "zeolite": match.group("zeolite"),
                    "state": match.group("state").removesuffix("_data").lower(),
                    "basename": match.group("basename"),
                    "source_size": len(raw),
                    "source_crc32": f"{info.CRC:08x}",
                    "source_sha256": hashlib.sha256(raw).hexdigest(),
                    "coordinates": coordinates,
                    "intensities": intensities,
                    "data": data,
                    "float32_sha256": hashlib.sha256(data).hexdigest(),
                }
            )
    seen = {}
    unique = []
    for scan in scans:
        key = str(scan["float32_sha256"])
        if key in seen:
            duplicates.append({"member_name": scan["member_name"], "duplicate_of": seen[key]})
            continue
        seen[key] = scan["member_name"]
        unique.append(scan)
    return unique, duplicates


def enforce_expected(scans: list[dict[str, object]], duplicates: list[dict[str, object]]) -> None:
    counts = [len(scan["intensities"]) for scan in scans]
    groups = Counter((str(scan["zeolite"]), str(scan["state"])) for scan in scans)
    observed_duplicates = {
        str(row["member_name"]): str(row["duplicate_of"])
        for row in duplicates
    }
    if observed_duplicates != EXPECTED_DUPLICATES:
        raise ValueError(f"duplicate intensity inventory changed: {observed_duplicates}")
    if len(scans) != EXPECTED_SAMPLES:
        raise ValueError(f"sample count changed: {len(scans)} != {EXPECTED_SAMPLES}")
    if sum(counts) != EXPECTED_VALUES or sum(len(scan["data"]) for scan in scans) != EXPECTED_BYTES:
        raise ValueError("aggregate value or byte total changed")
    if groups != Counter(EXPECTED_GROUPS):
        raise ValueError(f"group inventory changed: {dict(groups)}")


def safe_stem(scan: dict[str, object]) -> str:
    basename = Path(str(scan["basename"])).stem
    value = f"{scan['zeolite']}_{scan['state']}_{basename}".lower()
    return re.sub(r"[^a-z0-9]+", "_", value).strip("_")


def command_validate_download(args: argparse.Namespace) -> None:
    validate_download(Path(args.record), Path(args.archive))
    scans, duplicates = read_scans(Path(args.archive))
    enforce_expected(scans, duplicates)
    print(
        f"validated record={RECORD_ID} archive_bytes={ARCHIVE_SIZE} "
        f"samples={len(scans)} primary_values={EXPECTED_VALUES} primary_bytes={EXPECTED_BYTES}"
    )


def command_build(args: argparse.Namespace) -> None:
    validate_download(Path(args.record), Path(args.archive))
    scans, duplicates = read_scans(Path(args.archive))
    enforce_expected(scans, duplicates)
    samples_dir = Path(args.samples_dir)
    if samples_dir.exists():
        shutil.rmtree(samples_dir)
    series_id = "zeolite_powder_xrd_intensity_f32"
    out_dir = samples_dir / series_id
    out_dir.mkdir(parents=True)
    rows = []
    records = []
    for scan in scans:
        filename = f"{safe_stem(scan)}_n{len(scan['intensities'])}.bin"
        path = out_dir / filename
        data = scan["data"]
        path.write_bytes(data)
        values = struct.unpack(f"<{len(scan['intensities'])}f", data)
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
            "sample_format": "raw homogeneous IEEE-754 float32 intensity array",
            "sample_geometry": "powder_xrd_intensity_scan_1d",
            "sample_rank": 1,
            "sample_shape": [len(values)],
            "sample_axes": ["increasing_scattering_coordinate"],
            "natural_record_kind": "deposited_powder_xrd_xy_scan",
            "source_member": scan["member_name"],
            "source_sha256": scan["source_sha256"],
            "zeolite": scan["zeolite"],
            "state": scan["state"],
            "coordinate_min": min(scan["coordinates"]),
            "coordinate_max": max(scan["coordinates"]),
            "intensity_min_f32": min(values),
            "intensity_max_f32": max(values),
            "sha256": scan["float32_sha256"],
        }
        rows.append(row)
        records.append(
            {
                "member_name": scan["member_name"],
                "zeolite": scan["zeolite"],
                "state": scan["state"],
                "value_count": len(values),
                "sample_bytes": len(data),
                "source_sha256": scan["source_sha256"],
                "sample_sha256": scan["float32_sha256"],
            }
        )
    index_path = Path(args.index)
    index_path.parent.mkdir(parents=True, exist_ok=True)
    with index_path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")
    counts = sorted(int(row["value_count"]) for row in rows)
    stats = {
        "dataset_id": DATASET_ID,
        "samples": len(rows),
        "primary_values": sum(counts),
        "primary_sample_bytes": sum(int(row["sample_size_bytes"]) for row in rows),
        "median_value_count": statistics.median(counts),
        "min_value_count": counts[0],
        "max_value_count": counts[-1],
        "groups": {f"{key[0]}:{key[1]}": value for key, value in sorted(Counter((row["zeolite"], row["state"]) for row in rows).items())},
        "records": records,
    }
    stats_path = Path(args.stats)
    stats_path.parent.mkdir(parents=True, exist_ok=True)
    stats_path.write_text(json.dumps(stats, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        f"built samples={len(rows)} primary_values={stats['primary_values']} "
        f"primary_bytes={stats['primary_sample_bytes']} median_values={stats['median_value_count']}"
    )


def command_verify(args: argparse.Namespace) -> None:
    validate_download(Path(args.record), Path(args.archive))
    scans, duplicates = read_scans(Path(args.archive))
    enforce_expected(scans, duplicates)
    expected = {safe_stem(scan) + f"_n{len(scan['intensities'])}.bin": scan for scan in scans}
    index_path = Path(args.index)
    stats_path = Path(args.stats)
    rows = [json.loads(line) for line in index_path.read_text().splitlines() if line.strip()]
    stats = json.loads(stats_path.read_text())
    if len(rows) != EXPECTED_SAMPLES:
        raise ValueError("index sample count mismatch")
    actual_files = {path.name for path in (Path(args.samples_dir) / "zeolite_powder_xrd_intensity_f32").glob("*.bin")}
    if actual_files != set(expected):
        raise ValueError("sample file inventory mismatch")
    total_values = 0
    total_bytes = 0
    for row in rows:
        if row.get("dataset_id") != DATASET_ID or row.get("series_id") != "zeolite_powder_xrd_intensity_f32":
            raise ValueError("unexpected dataset or series ID")
        if row.get("numeric_kind") != "float" or int(row.get("bit_width", 0)) != 32 or row.get("endianness") != "little":
            raise ValueError("sample schema is not little-endian float32")
        filename = Path(str(row["sample_path"])).name
        scan = expected.get(filename)
        if scan is None:
            raise ValueError(f"unexpected indexed sample: {filename}")
        data = (Path(args.samples_dir) / "zeolite_powder_xrd_intensity_f32" / filename).read_bytes()
        if data != scan["data"]:
            raise ValueError(f"source/output byte mismatch: {filename}")
        if hashlib.sha256(data).hexdigest() != row.get("sha256"):
            raise ValueError(f"sample hash mismatch: {filename}")
        count = int(row["value_count"])
        if len(data) != count * 4 or len(data) != int(row["sample_size_bytes"]):
            raise ValueError(f"sample size mismatch: {filename}")
        values = struct.unpack(f"<{count}f", data)
        if any(not math.isfinite(value) for value in values) or len(set(values)) < 32:
            raise ValueError(f"invalid or degenerate float32 sample: {filename}")
        total_values += count
        total_bytes += len(data)
    if total_values != EXPECTED_VALUES or total_bytes != EXPECTED_BYTES:
        raise ValueError("verified aggregate totals changed")
    if total_bytes > MAX_PRIMARY_BYTES:
        raise ValueError("primary output exceeds cap")
    if int(stats.get("primary_values", -1)) != total_values or int(stats.get("primary_sample_bytes", -1)) != total_bytes:
        raise ValueError("stats/index totals disagree")
    print(
        f"verified dataset={DATASET_ID} samples={len(rows)} primary_values={total_values} "
        f"primary_bytes={total_bytes} median_values={int(statistics.median(int(row['value_count']) for row in rows))}"
    )


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser()
    commands = root.add_subparsers(dest="command", required=True)
    validate = commands.add_parser("validate-download")
    validate.add_argument("--record", required=True)
    validate.add_argument("--archive", required=True)
    validate.set_defaults(func=command_validate_download)
    build = commands.add_parser("build")
    build.add_argument("--record", required=True)
    build.add_argument("--archive", required=True)
    build.add_argument("--samples-dir", required=True)
    build.add_argument("--index", required=True)
    build.add_argument("--stats", required=True)
    build.set_defaults(func=command_build)
    verify = commands.add_parser("verify")
    verify.add_argument("--record", required=True)
    verify.add_argument("--archive", required=True)
    verify.add_argument("--samples-dir", required=True)
    verify.add_argument("--index", required=True)
    verify.add_argument("--stats", required=True)
    verify.set_defaults(func=command_verify)
    return root


if __name__ == "__main__":
    arguments = parser().parse_args()
    arguments.func(arguments)
