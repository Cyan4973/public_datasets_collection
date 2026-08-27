#!/usr/bin/env python3
"""Preflight, build, and verify processed LiBforSecUse EIS histories."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from pathlib import Path
import re
import shutil
import struct
from typing import Callable


DATASET_ID = "zenodo_battery_eis_complex_f32"
SERIES_ID = "battery_eis_complex_history_f32"
EXPECTED_RECORD = (
    9_011,
    "b034365c664eeb9cbc4a35b3c44c2d3b847dc859aa478ab342ac3ac64e437987",
)
EXPECTED_TABLE = (
    8_139_517,
    "d8f3abd2a38b4f0c88a6d297ce733264",
    "9ccd34f7534ed0045c965e6c34dc6044b76394c6727283d1f5feb383bf078eb6",
)
EXPECTED_ROWS = 4_297
EXPECTED_VALUES = 524_234
EXPECTED_BYTES = 2_096_936
EXPECTED_FINITE = 522_880
EXPECTED_NAN = 1_354
EXPECTED_PAYLOAD_SHA256 = (
    "24dc7a1ccb70e1633ecbdf26b006daaec8de2e48ca0262a6f9bbe8b362c0e6da"
)
CANONICAL_F32_NAN = struct.pack("<I", 0x7FC00000)
METADATA_FIELDS = (
    "exp_ID",
    "LCT_ID",
    "Institution",
    "T_cycle_degC",
    "SOC_cycle_high",
    "DOD_cycle",
    "Cell_ID",
    "nCycle",
    "SOC",
    "nFreqExp_EIS",
    "Qcap_mAh",
    "SOH",
)
FREQUENCY_EXPONENTS = tuple(value / 10 for value in range(-20, 41))
REAL_FIELDS = tuple(f"Z_real@10^{value:.1f}_Hz" for value in FREQUENCY_EXPONENTS)
IMAG_FIELDS = tuple(f"Z_imag@10^{value:.1f}_Hz" for value in FREQUENCY_EXPONENTS)
EIS_FIELDS = tuple(
    field
    for pair in zip(REAL_FIELDS, IMAG_FIELDS)
    for field in pair
)
EXPECTED_FIELDS = METADATA_FIELDS + EIS_FIELDS
EXPECTED_CELL_PROFILES = (
    ("Inst1-04", 130, 12, "85112eb1248f7bad549a39c093d06f776033acfae398d1e033b311855b16442a"),
    ("Inst1-05", 238, 12, "abad33ebcce8776c797f3cb9583ff9c34b469caca4830ceb5db70650dcdadc5a"),
    ("Inst1-06", 232, 12, "3b93ce42565eb3d949ea0b7a1e9e288b2c3b17b77d06a4c210fb0b54bcd00936"),
    ("Inst1-09", 156, 0, "5b6822c9addf866805d572c37ddc885e9df7686bee470472b9c725dbf06d4e40"),
    ("Inst1-10", 394, 0, "d6f4270c89267c67cfb16fea4411f019409c5590c9adee102666fe50f8111bb5"),
    ("Inst1-11", 396, 0, "8b70eff2d813857b4b11fc0bf721bcd05730dfb9b10c4bfb3ae2c92c2de7b997"),
    ("Inst1-13", 276, 0, "31a5fbfb3d2d5a8ce41f5b49f974898538cbdf7116963384140f7f36516ecd9e"),
    ("Inst1-14", 79, 0, "44f90891d8655442052ae53f4368b52079dbd1ed2b8947eead4e2500ebe8aff4"),
    ("Inst1-17", 198, 0, "9f800c333edf01441eadcafac6a91c8efe26277fd53e92f2967321615b3e763f"),
    ("Inst1-19", 198, 0, "1e8cec691527585e55b912a5af3fb40f8c43b2222aeaf3274ba8f1bff61be00b"),
    ("Inst2-06", 202, 4, "784afc3d6ce93ebb70eb7051bd2887b94998868e7807e43682cfec6ac4494d8f"),
    ("Inst2-07", 203, 0, "2367d4d26e9226c13d595d1b54042318fc1a00f52bf9ee0942759e6b0f769947"),
    ("Inst2-10", 203, 24, "a5ab6dc2c16ddafda38d65d61e854ebed3062a4897b9f2373d6d09e6cc991e1a"),
    ("Inst2-11", 203, 24, "f52c7394a25ae7cb1dcf30421ba9b87272ec4360d6f06f2e8d698100b9c7190f"),
    ("Inst2-12", 202, 24, "c3c4a777d3c5005674b16631d4578adfbf5c09608f64e9c3084039f995d0ea7d"),
    ("Inst2-13", 204, 24, "766966146285a9038d4d5106951c2e0b9f0f3c48d0e99a401e71e309682e92f8"),
    ("Inst3-01", 121, 170, "6b1508d85a95b7daeb0350c07be51b5035d78305372279bea4f9f54ccfeba9fb"),
    ("Inst3-02", 96, 120, "ea954227023b9d654810e0ecd01f557c21615aca286698de8eab0fa10a475e48"),
    ("Inst3-03", 102, 192, "acab2c2c05bb54bebc7032236a39bedd7ba3214520666e33c36e503f3496ae3c"),
    ("Inst3-04", 96, 192, "6cc16aaee282375553758e4c4e1f04c200a31ef728c11368f8e2cd2fb471bbff"),
    ("Inst3-07", 96, 108, "947b08b85251004497497e7a640133446775a242c882785f2b3e993f767af8c7"),
    ("Inst3-08", 96, 84, "78864fe39f93246a150e4e319dc5b0350318b7ec2853330bf22dc45c0b0cb6ed"),
    ("Inst4-03", 59, 118, "ee9b72709cafa9c9a0be33e1c32d62e2b0610da79a3758ced6a303ce4f43664e"),
    ("Inst4-04", 59, 118, "527a2ada918ab3014c7da5bdc94ddd4b351bfbcf817c0ec3afdea7b441964d78"),
    ("Inst4-07", 29, 58, "cac848fe3b8e1177cba8b7604528f4291a149f12ed5dad02818e1117767f00c6"),
    ("Inst4-08", 29, 58, "13cec7184150f6b12fbab52dd9e8da2da409806d787a4ee98b7898c571709b3e"),
)
PayloadConsumer = Callable[[str, bytes, dict[str, object]], None]


def file_hash(path: Path, algorithm: str = "sha256") -> str:
    digest = hashlib.new(algorithm)
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def validate_selection(path: Path) -> None:
    with path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    required = {
        "record_id",
        "doi",
        "filename",
        "size_bytes",
        "md5",
        "sha256",
        "row_count",
        "cell_count",
        "frequency_count",
        "output_value_count",
        "output_size_bytes",
        "output_sha256",
        "url",
    }
    if len(rows) != 1 or not required.issubset(rows[0]):
        raise SystemExit("selection count or schema changed")
    row = rows[0]
    expected = {
        "record_id": "17792537",
        "doi": "10.5281/zenodo.17792537",
        "filename": "frequency-space_spline-interp_v1-3.txt",
        "size_bytes": str(EXPECTED_TABLE[0]),
        "md5": EXPECTED_TABLE[1],
        "sha256": EXPECTED_TABLE[2],
        "row_count": str(EXPECTED_ROWS),
        "cell_count": str(len(EXPECTED_CELL_PROFILES)),
        "frequency_count": str(len(FREQUENCY_EXPONENTS)),
        "output_value_count": str(EXPECTED_VALUES),
        "output_size_bytes": str(EXPECTED_BYTES),
        "output_sha256": EXPECTED_PAYLOAD_SHA256,
    }
    for key, value in expected.items():
        if row.get(key) != value:
            raise SystemExit(f"selection mismatch: {key}")


def validate_identity(path: Path, expected: tuple[int, str], label: str) -> None:
    if not path.is_file():
        raise SystemExit(f"missing {label}: {path}")
    size, digest = expected
    if path.stat().st_size != size or file_hash(path) != digest:
        raise SystemExit(f"{label} identity mismatch")


def validate_record(path: Path) -> None:
    validate_identity(path, EXPECTED_RECORD, "Zenodo record metadata")
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise SystemExit(f"invalid Zenodo metadata JSON: {error}") from error
    if int(record.get("id", 0)) != 17_792_537:
        raise SystemExit("Zenodo record ID mismatch")
    metadata = record.get("metadata", {})
    if metadata.get("doi") != "10.5281/zenodo.17792537":
        raise SystemExit("Zenodo DOI mismatch")
    if metadata.get("title") != (
        "LiBforSecUse processed data for machine learning modelling and "
        "uncertainty propagation"
    ):
        raise SystemExit("Zenodo title mismatch")
    if metadata.get("license", {}).get("id", "").lower() != "cc-by-4.0":
        raise SystemExit("Zenodo record does not declare CC BY 4.0")
    description = re.sub(
        r"\s+",
        " ",
        re.sub(r"<[^>]+>", " ", str(metadata.get("description", ""))),
    ).lower()
    for phrase in (
        "10.5281/zenodo.6418665",
        "26 cells",
        "4297 experiments",
        "122 for eis",
        "cubic splines",
        "missing values (nan)",
        "z_real",
        "z_imag",
    ):
        if phrase not in description:
            raise SystemExit(f"Zenodo metadata lacks expected statement: {phrase}")


def validate_table_identity(path: Path) -> None:
    if not path.is_file():
        raise SystemExit(f"missing EIS table: {path}")
    size, md5, sha256 = EXPECTED_TABLE
    if (
        path.stat().st_size != size
        or file_hash(path, "md5") != md5
        or file_hash(path) != sha256
    ):
        raise SystemExit("EIS table identity mismatch")


def parse_int(row: dict[str, str], field: str, row_number: int) -> int:
    token = row[field].strip()
    try:
        value = int(token)
    except ValueError as error:
        raise SystemExit(
            f"non-integer metadata row={row_number} field={field} token={token!r}"
        ) from error
    return value


def validate_metadata(row: dict[str, str], row_number: int) -> tuple[str, int]:
    if any(not row[field].strip() for field in METADATA_FIELDS):
        raise SystemExit(f"blank metadata value at row {row_number}")
    cell_id = row["Cell_ID"].strip()
    cycle = parse_int(row, "nCycle", row_number)
    soc = parse_int(row, "SOC", row_number)
    frequency_count = parse_int(row, "nFreqExp_EIS", row_number)
    if cycle < 0 or soc not in {20, 25, 35, 50, 65, 80, 100}:
        raise SystemExit(f"invalid cycle or SOC metadata at row {row_number}")
    if frequency_count not in {48, 49, 58, 60, 61}:
        raise SystemExit(f"unexpected original frequency count at row {row_number}")
    if row["exp_ID"].strip() != f"{cell_id}_{cycle}_{soc}":
        raise SystemExit(f"experiment ID relation changed at row {row_number}")
    for field in (
        "T_cycle_degC",
        "SOC_cycle_high",
        "DOD_cycle",
        "Qcap_mAh",
        "SOH",
    ):
        try:
            value = float(row[field].strip())
        except ValueError as error:
            raise SystemExit(
                f"invalid metadata row={row_number} field={field}"
            ) from error
        if not math.isfinite(value):
            raise SystemExit(f"non-finite metadata row={row_number} field={field}")
    return cell_id, cycle


def scan_table(
    table: Path, consumer: PayloadConsumer | None = None
) -> dict[str, object]:
    validate_table_identity(table)
    expected_by_cell = {
        cell_id: (row_count, nan_count, digest)
        for cell_id, row_count, nan_count, digest in EXPECTED_CELL_PROFILES
    }
    payloads = {cell_id: bytearray() for cell_id in expected_by_cell}
    finite_values = {cell_id: [] for cell_id in expected_by_cell}
    distinct_words = {cell_id: set() for cell_id in expected_by_cell}
    row_counts = {cell_id: 0 for cell_id in expected_by_cell}
    nan_counts = {cell_id: 0 for cell_id in expected_by_cell}
    first_cycles: dict[str, int] = {}
    last_cycles: dict[str, int] = {}
    observed_order: list[str] = []
    experiment_ids: set[str] = set()
    aggregate = hashlib.sha256()
    row_count = 0
    with table.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if tuple(reader.fieldnames or ()) != EXPECTED_FIELDS:
            raise SystemExit("EIS table header changed")
        for row_count, row in enumerate(reader, 1):
            if None in row or any(value is None for value in row.values()):
                raise SystemExit(f"malformed CSV row {row_count}")
            cell_id, cycle = validate_metadata(row, row_count)
            if cell_id not in expected_by_cell:
                raise SystemExit(f"unexpected cell ID at row {row_count}: {cell_id}")
            experiment_id = row["exp_ID"].strip()
            if experiment_id in experiment_ids:
                raise SystemExit(f"duplicate experiment ID at row {row_count}")
            experiment_ids.add(experiment_id)
            if not observed_order or observed_order[-1] != cell_id:
                if cell_id in observed_order:
                    raise SystemExit(f"non-contiguous cell block: {cell_id}")
                observed_order.append(cell_id)
                first_cycles[cell_id] = cycle
            if cell_id in last_cycles and cycle < last_cycles[cell_id]:
                raise SystemExit(f"cycle order decreased for cell {cell_id}")
            last_cycles[cell_id] = cycle
            row_counts[cell_id] += 1
            for real_field, imag_field in zip(REAL_FIELDS, IMAG_FIELDS):
                real_token = row[real_field].strip()
                imag_token = row[imag_field].strip()
                if bool(real_token) != bool(imag_token):
                    raise SystemExit(
                        f"unpaired missing complex value row={row_count} "
                        f"frequency={real_field}"
                    )
                for field, token in (
                    (real_field, real_token),
                    (imag_field, imag_token),
                ):
                    if not token:
                        word = CANONICAL_F32_NAN
                        nan_counts[cell_id] += 1
                    else:
                        try:
                            value = float(token)
                            word = struct.pack("<f", value)
                            rounded = struct.unpack("<f", word)[0]
                        except (ValueError, OverflowError, struct.error) as error:
                            raise SystemExit(
                                f"invalid EIS value row={row_count} "
                                f"field={field} token={token!r}"
                            ) from error
                        if not math.isfinite(rounded):
                            raise SystemExit(
                                f"non-finite explicit EIS value row={row_count} field={field}"
                            )
                        finite_values[cell_id].append(rounded)
                    payloads[cell_id].extend(word)
                    distinct_words[cell_id].add(word)
                    aggregate.update(word)
    if row_count != EXPECTED_ROWS or len(experiment_ids) != EXPECTED_ROWS:
        raise SystemExit(
            f"table has {row_count} rows and {len(experiment_ids)} experiment IDs; "
            f"expected {EXPECTED_ROWS}"
        )
    expected_order = [profile[0] for profile in EXPECTED_CELL_PROFILES]
    if observed_order != expected_order:
        raise SystemExit("cell block order changed")
    profiles: list[dict[str, object]] = []
    output_hashes: set[str] = set()
    for cell_id, expected_rows, expected_nan, expected_hash in EXPECTED_CELL_PROFILES:
        payload = bytes(payloads[cell_id])
        digest = hashlib.sha256(payload).hexdigest()
        if (
            row_counts[cell_id] != expected_rows
            or nan_counts[cell_id] != expected_nan
            or digest != expected_hash
        ):
            raise SystemExit(f"pinned output profile changed for cell {cell_id}")
        if digest in output_hashes:
            raise SystemExit(f"duplicate cell-history payload: {cell_id}")
        output_hashes.add(digest)
        values = finite_values[cell_id]
        if len(payload) < 1_024 or len(distinct_words[cell_id]) < 100:
            raise SystemExit(f"cell-history payload is too small or degenerate: {cell_id}")
        profile = {
            "cell_id": cell_id,
            "experiment_count": expected_rows,
            "first_cycle": first_cycles[cell_id],
            "last_cycle": last_cycles[cell_id],
            "frequency_count": len(FREQUENCY_EXPONENTS),
            "component_count": 2,
            "value_count": len(payload) // 4,
            "sample_size_bytes": len(payload),
            "finite_value_count": len(values),
            "nan_value_count": nan_counts[cell_id],
            "minimum_finite": min(values),
            "maximum_finite": max(values),
            "distinct_words": len(distinct_words[cell_id]),
            "sha256": digest,
        }
        profiles.append(profile)
        if consumer is not None:
            consumer(cell_id, payload, profile)
    result = {
        "dataset_id": DATASET_ID,
        "series_id": SERIES_ID,
        "source_row_count": row_count,
        "experiment_id_count": len(experiment_ids),
        "cell_count": len(profiles),
        "frequency_count": len(FREQUENCY_EXPONENTS),
        "frequency_exponents": list(FREQUENCY_EXPONENTS),
        "complex_component_order": ["Z_real", "Z_imag"],
        "sample_count": len(profiles),
        "value_count": sum(int(profile["value_count"]) for profile in profiles),
        "finite_value_count": sum(
            int(profile["finite_value_count"]) for profile in profiles
        ),
        "nan_value_count": sum(int(profile["nan_value_count"]) for profile in profiles),
        "total_size_bytes": sum(
            int(profile["sample_size_bytes"]) for profile in profiles
        ),
        "aggregate_row_order_payload_sha256": aggregate.hexdigest(),
        "cell_profiles": profiles,
    }
    if (
        result["value_count"] != EXPECTED_VALUES
        or result["finite_value_count"] != EXPECTED_FINITE
        or result["nan_value_count"] != EXPECTED_NAN
        or result["total_size_bytes"] != EXPECTED_BYTES
        or result["aggregate_row_order_payload_sha256"]
        != EXPECTED_PAYLOAD_SHA256
    ):
        raise SystemExit("aggregate converted statistics changed")
    return result


def scan_source(
    selection: Path,
    record: Path,
    table: Path,
    consumer: PayloadConsumer | None = None,
) -> dict[str, object]:
    validate_selection(selection)
    validate_record(record)
    result = scan_table(table, consumer)
    result.update(
        {
            "record_id": 17_792_537,
            "doi": "10.5281/zenodo.17792537",
            "license": "CC BY 4.0",
            "record_size_bytes": record.stat().st_size,
            "record_sha256": file_hash(record),
            "table_size_bytes": table.stat().st_size,
            "table_md5": file_hash(table, "md5"),
            "table_sha256": file_hash(table),
        }
    )
    return result


def preflight(args: argparse.Namespace) -> None:
    result = scan_source(args.selection, args.record, args.table)
    args.profile.parent.mkdir(parents=True, exist_ok=True)
    args.profile.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {key: value for key, value in result.items() if key != "cell_profiles"},
            indent=2,
            sort_keys=True,
        )
    )


def build(args: argparse.Namespace) -> None:
    if args.samples_dir.exists():
        shutil.rmtree(args.samples_dir)
    series_dir = args.samples_dir / SERIES_ID
    series_dir.mkdir(parents=True)
    args.index.parent.mkdir(parents=True, exist_ok=True)
    index_rows: list[dict[str, object]] = []

    def emit(cell_id: str, payload: bytes, profile: dict[str, object]) -> None:
        slug = cell_id.lower().replace("-", "_")
        experiment_count = int(profile["experiment_count"])
        output = (
            series_dir
            / f"cell_{slug}_eis_f32_n{experiment_count}x61x2.bin"
        )
        output.write_bytes(payload)
        index_rows.append(
            {
                "dataset_id": DATASET_ID,
                "series_id": SERIES_ID,
                "role": "primary",
                "sample_path": output.relative_to(args.data_root).as_posix(),
                "source_sample": args.table.relative_to(args.data_root).as_posix(),
                "source_field": "paired Z_real/Z_imag columns at 61 aligned frequencies",
                "cell_id": cell_id,
                "numeric_kind": "float",
                "bit_width": 32,
                "endianness": "little",
                "element_size_bytes": 4,
                "value_count": profile["value_count"],
                "sample_size_bytes": profile["sample_size_bytes"],
                "sample_format": (
                    "raw homogeneous IEEE-754 float32 complex EIS history"
                ),
                "sample_geometry": "battery_cell_complex_eis_history_3d",
                "sample_rank": 3,
                "sample_shape": [experiment_count, 61, 2],
                "sample_axes": [
                    "experiment_cycle_soc_order",
                    "frequency",
                    "complex_component_real_imag",
                ],
                "natural_record_kind": (
                    "complete_processed_battery_cell_eis_experiment_history"
                ),
                "first_cycle": profile["first_cycle"],
                "last_cycle": profile["last_cycle"],
                "finite_value_count": profile["finite_value_count"],
                "nan_value_count": profile["nan_value_count"],
                "minimum_finite": profile["minimum_finite"],
                "maximum_finite": profile["maximum_finite"],
                "distinct_words": profile["distinct_words"],
                "sha256": profile["sha256"],
            }
        )

    summary = scan_source(args.selection, args.record, args.table, emit)
    args.index.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in index_rows),
        encoding="utf-8",
    )
    args.stats.parent.mkdir(parents=True, exist_ok=True)
    args.stats.write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {key: value for key, value in summary.items() if key != "cell_profiles"},
            indent=2,
            sort_keys=True,
        )
    )


def verify(args: argparse.Namespace) -> None:
    if not args.index.is_file() or not args.stats.is_file():
        raise SystemExit("missing index or stats; run build first")
    indexed = [
        json.loads(line)
        for line in args.index.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    cursor = 0
    expected_outputs: set[Path] = set()

    def compare(cell_id: str, payload: bytes, profile: dict[str, object]) -> None:
        nonlocal cursor
        if cursor >= len(indexed):
            raise SystemExit("sample index has fewer rows than cell histories")
        entry = indexed[cursor]
        cursor += 1
        required = {
            "dataset_id": DATASET_ID,
            "series_id": SERIES_ID,
            "role": "primary",
            "cell_id": cell_id,
            "numeric_kind": "float",
            "bit_width": 32,
            "endianness": "little",
            "element_size_bytes": 4,
            "value_count": profile["value_count"],
            "sample_size_bytes": profile["sample_size_bytes"],
            "sample_shape": [profile["experiment_count"], 61, 2],
            "first_cycle": profile["first_cycle"],
            "last_cycle": profile["last_cycle"],
            "finite_value_count": profile["finite_value_count"],
            "nan_value_count": profile["nan_value_count"],
            "minimum_finite": profile["minimum_finite"],
            "maximum_finite": profile["maximum_finite"],
            "distinct_words": profile["distinct_words"],
            "sha256": profile["sha256"],
        }
        for key, expected in required.items():
            if entry.get(key) != expected:
                raise SystemExit(f"index mismatch for {cell_id}: {key}")
        output = args.data_root / str(entry.get("sample_path", ""))
        if not output.is_file() or output.read_bytes() != payload:
            raise SystemExit(f"output differs from fresh table conversion: {output}")
        expected_outputs.add(output.resolve())

    summary = scan_source(args.selection, args.record, args.table, compare)
    if cursor != len(indexed):
        raise SystemExit("sample index has extra rows")
    actual_outputs = {path.resolve() for path in args.samples_dir.rglob("*.bin")}
    if actual_outputs != expected_outputs:
        raise SystemExit("sample directory contains missing or stale outputs")
    if json.loads(args.stats.read_text(encoding="utf-8")) != summary:
        raise SystemExit("ingest stats differ from fresh source scan")
    print(
        f"verified_samples={cursor} values={summary['value_count']} "
        f"nan={summary['nan_value_count']} bytes={summary['total_size_bytes']}"
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("preflight", "build", "verify"))
    parser.add_argument("--selection", type=Path, required=True)
    parser.add_argument("--record", type=Path, required=True)
    parser.add_argument("--table", type=Path, required=True)
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
        if any(
            value is None
            for value in (args.samples_dir, args.index, args.stats, args.data_root)
        ):
            parser.error(
                "build requires --samples-dir, --index, --stats, and --data-root"
            )
        build(args)
    else:
        if any(
            value is None
            for value in (args.samples_dir, args.index, args.stats, args.data_root)
        ):
            parser.error(
                "verify requires --samples-dir, --index, --stats, and --data-root"
            )
        verify(args)


if __name__ == "__main__":
    main()
