#!/usr/bin/env python3
"""Preflight, build, and verify UCI SGEMM GPU runtime series."""
from __future__ import annotations

import argparse
import csv
import hashlib
import html
import io
import json
import math
from pathlib import Path, PurePosixPath
import re
import shutil
import struct
from typing import Callable
import zipfile


DATASET_ID = "uci_sgemm_gpu_runtimes_f32"
SERIES_ID = "sgemm_gpu_runtime_f32"
EXPECTED_ROWS = 241_600
EXPECTED_VALUES = 966_400
EXPECTED_BYTES = 3_865_600
RUNTIME_COLUMNS = ("Run1 (ms)", "Run2 (ms)", "Run3 (ms)", "Run4 (ms)")
CONFIG_COLUMNS = (
    "MWG", "NWG", "KWG", "MDIMC", "NDIMC", "MDIMA", "NDIMB",
    "KWI", "VWM", "VWN", "STRM", "STRN", "SA", "SB",
)
EXPECTED_IDENTITIES = {
    "archive": (
        3_186_088,
        "8d3ee0d82708df11b54debc6a4fbade77c604a047f019fa7940413032eb7b096",
    ),
    "metadata": (
        5_044,
        "f86c51dcd111ce1c2fa35d3b510465c25490e0ee09f7f442c3d058710329744a",
    ),
    "rights": (
        84_528,
        "bafa820bd79e3bc2e96fcac284ae2f5d25308fe60ff85acc543e28d0df2546cd",
    ),
}
EXPECTED_PAYLOAD_HASHES = {
    "Run1 (ms)": "99762dee5750e0cc4445cdbcbc39645d0619145e60904fa2d4316e37a0328e87",
    "Run2 (ms)": "b3cad79c0636863b7d3c6b9879492c8f8f62d8177ad796161db50d494821dd72",
    "Run3 (ms)": "fe4529b90c835bf1695ab2cb4a6da46964a338b635078de1bc05a99a61aa2a33",
    "Run4 (ms)": "1994bd658730e81f927d2ca711a9622995fc2c7c9b1a50b375e6ded392b259bc",
}
PayloadConsumer = Callable[[str, bytes, dict[str, object]], None]


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def validate_identity(path: Path, label: str) -> None:
    if not path.is_file():
        raise SystemExit(f"missing {label}: {path}")
    expected_size, expected_hash = EXPECTED_IDENTITIES[label]
    size = path.stat().st_size
    digest = file_hash(path)
    if size != expected_size or digest != expected_hash:
        raise SystemExit(
            f"{label} identity mismatch: size={size} sha256={digest}"
        )


def validate_evidence(metadata: Path, rights: Path) -> None:
    validate_identity(metadata, "metadata")
    validate_identity(rights, "rights")
    try:
        document = json.loads(metadata.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise SystemExit(f"invalid UCI metadata JSON: {error}") from error
    serialized = json.dumps(document, ensure_ascii=False).lower()
    if not re.search(r'"uci_id"\s*:\s*440(?:\D|$)', serialized):
        raise SystemExit("UCI metadata does not identify dataset 440")
    if "sgemm gpu kernel performance" not in serialized:
        raise SystemExit("UCI metadata title mismatch")
    text = html.unescape(rights.read_text(encoding="utf-8", errors="replace"))
    normalized = re.sub(r"\s+", " ", text).lower()
    if "sgemm gpu kernel performance" not in normalized:
        raise SystemExit("official UCI page identity mismatch")
    if not any(term in normalized for term in (
        "cc by 4.0", "cc-by-4.0", "creative commons attribution 4.0",
        "creativecommons.org/licenses/by/4.0",
    )):
        raise SystemExit("official UCI page lacks CC BY 4.0 evidence")


def find_csv(archive: zipfile.ZipFile) -> zipfile.ZipInfo:
    candidates: list[zipfile.ZipInfo] = []
    total = 0
    for info in archive.infolist():
        member = PurePosixPath(info.filename)
        if member.is_absolute() or ".." in member.parts:
            raise SystemExit(f"unsafe ZIP member: {info.filename}")
        if info.flag_bits & 1:
            raise SystemExit(f"encrypted ZIP member: {info.filename}")
        total += info.file_size
        if total > 500_000_000:
            raise SystemExit("uncompressed archive exceeds 500 MB safety cap")
        if not info.is_dir() and member.name.lower() == "sgemm_product.csv":
            candidates.append(info)
    if len(candidates) != 1:
        raise SystemExit(f"expected one sgemm_product.csv, found {len(candidates)}")
    info = candidates[0]
    if info.file_size != 14_353_701 or info.compress_size != 3_183_365 or info.CRC != 0x252AF115:
        raise SystemExit("CSV member identity changed")
    return info


def scan_archive(
    archive_path: Path, consumer: PayloadConsumer | None = None
) -> dict[str, object]:
    validate_identity(archive_path, "archive")
    if not zipfile.is_zipfile(archive_path):
        raise SystemExit(f"invalid ZIP: {archive_path}")
    columns = {name: bytearray() for name in RUNTIME_COLUMNS}
    minima = {name: math.inf for name in RUNTIME_COLUMNS}
    maxima = {name: -math.inf for name in RUNTIME_COLUMNS}
    distinct = {name: set() for name in RUNTIME_COLUMNS}
    configurations: set[tuple[int, ...]] = set()
    try:
        with zipfile.ZipFile(archive_path) as archive:
            info = find_csv(archive)
            with archive.open(info) as raw:
                text = io.TextIOWrapper(
                    raw, encoding="utf-8-sig", errors="strict", newline=""
                )
                reader = csv.DictReader(text)
                if reader.fieldnames != list(CONFIG_COLUMNS + RUNTIME_COLUMNS):
                    raise SystemExit(f"unexpected CSV header: {reader.fieldnames}")
                row_count = 0
                for row_count, row in enumerate(reader, 1):
                    if None in row or any(value is None for value in row.values()):
                        raise SystemExit(f"malformed CSV row {row_count}")
                    try:
                        configuration = tuple(
                            int(row[name].strip()) for name in CONFIG_COLUMNS
                        )
                    except ValueError as error:
                        raise SystemExit(
                            f"non-integer configuration at row {row_count}"
                        ) from error
                    if configuration in configurations:
                        raise SystemExit(f"duplicate configuration at row {row_count}")
                    configurations.add(configuration)
                    for name in RUNTIME_COLUMNS:
                        token = row[name].strip()
                        try:
                            value = float(token)
                            word = struct.pack("<f", value)
                            rounded = struct.unpack("<f", word)[0]
                        except (ValueError, OverflowError, struct.error) as error:
                            raise SystemExit(
                                f"invalid float at row {row_count}, {name}: {token!r}"
                            ) from error
                        if not math.isfinite(rounded) or rounded <= 0:
                            raise SystemExit(
                                f"invalid runtime at row {row_count}, {name}: {rounded}"
                            )
                        columns[name].extend(word)
                        minima[name] = min(minima[name], rounded)
                        maxima[name] = max(maxima[name], rounded)
                        distinct[name].add(word)
    except (UnicodeDecodeError, zipfile.BadZipFile, RuntimeError) as error:
        raise SystemExit(f"cannot decode source archive: {error}") from error
    if row_count != EXPECTED_ROWS or len(configurations) != EXPECTED_ROWS:
        raise SystemExit(
            f"CSV has {row_count} rows and {len(configurations)} configurations; "
            f"expected {EXPECTED_ROWS} unique rows"
        )
    profiles: list[dict[str, object]] = []
    for run_index, name in enumerate(RUNTIME_COLUMNS, 1):
        payload = bytes(columns[name])
        digest = hashlib.sha256(payload).hexdigest()
        if digest != EXPECTED_PAYLOAD_HASHES[name]:
            raise SystemExit(f"converted payload identity changed: {name}")
        if len(distinct[name]) < 2:
            raise SystemExit(f"constant runtime column: {name}")
        profile = {
            "run_index": run_index,
            "source_column": name,
            "value_count": EXPECTED_ROWS,
            "sample_size_bytes": len(payload),
            "minimum": minima[name],
            "maximum": maxima[name],
            "distinct_values": len(distinct[name]),
            "sha256": digest,
        }
        profiles.append(profile)
        if consumer is not None:
            consumer(name, payload, profile)
    result = {
        "dataset_id": DATASET_ID,
        "series_id": SERIES_ID,
        "source_member": info.filename,
        "source_member_size_bytes": info.file_size,
        "source_member_compressed_size_bytes": info.compress_size,
        "source_member_crc32": f"{info.CRC:08x}",
        "source_row_count": row_count,
        "configuration_count": len(configurations),
        "sample_count": len(profiles),
        "value_count": sum(int(profile["value_count"]) for profile in profiles),
        "total_size_bytes": sum(int(profile["sample_size_bytes"]) for profile in profiles),
        "runtime_profiles": profiles,
    }
    if result["value_count"] != EXPECTED_VALUES or result["total_size_bytes"] != EXPECTED_BYTES:
        raise SystemExit("converted aggregate totals changed")
    return result


def preflight(args: argparse.Namespace) -> None:
    validate_evidence(args.metadata, args.rights)
    result = scan_archive(args.archive)
    result.update({
        "uci_dataset_id": 440,
        "license": "CC BY 4.0",
        "archive_size_bytes": args.archive.stat().st_size,
        "archive_sha256": file_hash(args.archive),
        "metadata_size_bytes": args.metadata.stat().st_size,
        "metadata_sha256": file_hash(args.metadata),
        "rights_size_bytes": args.rights.stat().st_size,
        "rights_sha256": file_hash(args.rights),
    })
    args.profile.parent.mkdir(parents=True, exist_ok=True)
    args.profile.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(result, indent=2, sort_keys=True))


def build(args: argparse.Namespace) -> None:
    validate_evidence(args.metadata, args.rights)
    if args.samples_dir.exists():
        shutil.rmtree(args.samples_dir)
    series_dir = args.samples_dir / SERIES_ID
    series_dir.mkdir(parents=True)
    args.index.parent.mkdir(parents=True, exist_ok=True)
    index_rows: list[dict[str, object]] = []

    def emit(name: str, payload: bytes, profile: dict[str, object]) -> None:
        run_index = int(profile["run_index"])
        output = series_dir / f"run_{run_index}_f32_n{EXPECTED_ROWS}.bin"
        output.write_bytes(payload)
        index_rows.append({
            "dataset_id": DATASET_ID,
            "series_id": SERIES_ID,
            "role": "primary",
            "sample_path": output.relative_to(args.data_root).as_posix(),
            "source_sample": args.archive.relative_to(args.data_root).as_posix(),
            "source_member": "sgemm_product.csv",
            "source_field": name,
            "run_index": run_index,
            "numeric_kind": "float",
            "bit_width": 32,
            "endianness": "little",
            "element_size_bytes": 4,
            "value_count": EXPECTED_ROWS,
            "sample_size_bytes": len(payload),
            "sample_format": "raw homogeneous IEEE-754 float32 GPU runtime series",
            "sample_geometry": "ordered_gpu_kernel_configuration_sweep_1d",
            "sample_rank": 1,
            "sample_shape": [EXPECTED_ROWS],
            "sample_axes": ["kernel_configuration"],
            "natural_record_kind": "complete_repeated_sgemm_benchmark_run",
            "minimum": profile["minimum"],
            "maximum": profile["maximum"],
            "distinct_values": profile["distinct_values"],
            "sha256": profile["sha256"],
        })

    summary = scan_archive(args.archive, emit)
    args.index.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in index_rows),
        encoding="utf-8",
    )
    args.stats.parent.mkdir(parents=True, exist_ok=True)
    args.stats.write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps({key: value for key, value in summary.items() if key != "runtime_profiles"}, indent=2, sort_keys=True))


def verify(args: argparse.Namespace) -> None:
    validate_evidence(args.metadata, args.rights)
    if not args.index.is_file() or not args.stats.is_file():
        raise SystemExit("missing index or stats; run build first")
    indexed = [
        json.loads(line) for line in args.index.read_text().splitlines() if line.strip()
    ]
    cursor = 0
    expected_outputs: set[Path] = set()

    def compare(name: str, payload: bytes, profile: dict[str, object]) -> None:
        nonlocal cursor
        if cursor >= len(indexed):
            raise SystemExit("sample index has fewer rows than runtime columns")
        entry = indexed[cursor]
        cursor += 1
        required = {
            "dataset_id": DATASET_ID,
            "series_id": SERIES_ID,
            "role": "primary",
            "source_field": name,
            "run_index": profile["run_index"],
            "numeric_kind": "float",
            "bit_width": 32,
            "endianness": "little",
            "element_size_bytes": 4,
            "value_count": EXPECTED_ROWS,
            "sample_size_bytes": profile["sample_size_bytes"],
            "minimum": profile["minimum"],
            "maximum": profile["maximum"],
            "distinct_values": profile["distinct_values"],
            "sha256": profile["sha256"],
        }
        for key, expected in required.items():
            if entry.get(key) != expected:
                raise SystemExit(f"index mismatch for {name}: {key}")
        output = args.data_root / str(entry.get("sample_path", ""))
        if not output.is_file() or output.read_bytes() != payload:
            raise SystemExit(f"output differs from fresh CSV conversion: {output}")
        expected_outputs.add(output.resolve())

    summary = scan_archive(args.archive, compare)
    if cursor != len(indexed):
        raise SystemExit("sample index has extra rows")
    actual_outputs = {path.resolve() for path in args.samples_dir.rglob("*.bin")}
    if actual_outputs != expected_outputs:
        raise SystemExit("sample directory contains missing or stale outputs")
    if json.loads(args.stats.read_text()) != summary:
        raise SystemExit("ingest stats differ from fresh source scan")
    print(
        f"verified_samples={cursor} values={summary['value_count']} "
        f"bytes={summary['total_size_bytes']}"
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("preflight", "build", "verify"))
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--metadata", type=Path, required=True)
    parser.add_argument("--rights", type=Path, required=True)
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
