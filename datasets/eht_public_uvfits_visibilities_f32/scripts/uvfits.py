#!/usr/bin/env python3
"""Preflight, build, and verify official public EHT UVFITS visibility fields."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from pathlib import Path
import shutil
import struct
from typing import Callable


DATASET_ID = "eht_public_uvfits_visibilities_f32"
BLOCK = 2880
CARD = 80
FIELDS = ("real", "imaginary", "weight")
SERIES_IDS = {
    "real": "eht_visibility_real_f32",
    "imaginary": "eht_visibility_imaginary_f32",
    "weight": "eht_visibility_weight_f32",
}
EXPECTED_COLUMNS = (
    "source_id", "repository", "commit", "path", "target", "size_bytes",
    "git_blob_sha", "sha256", "object", "date_obs", "hdu_count", "gcount",
    "output_value_count", "duplicate_ll_count", "invalid_zero_weight_count",
    "invalid_inf_weight_count", "calibration", "url",
)
EXPECTED_SOURCE_IDS = (
    "m87_2017_096_hi",
    "threec279_2017_101_hi",
    "cena_2017_100_hi",
    "sgra_2017_097_lo",
    "m87_2018_111_b4",
)
EXPECTED_LICENSE = (
    35_356,
    "9725e2ef4127844b4cf21137a87e61830de0a04ad583ea6ba2229488b5012f1d",
)
LICENSE_TEXT = "data files in this data set are licensed under the odc-pddl license"
EXPECTED_AXES = [0, 3, 4, 1, 1, 1, 1]
EXPECTED_PTYPES = [
    "UU---SIN", "VV---SIN", "WW---SIN", "BASELINE", "DATE", "DATE",
    "INTTIM", "TAU1", "TAU2",
]
EXPECTED_TOTAL_VALUES_PER_SERIES = 58_813
EXPECTED_BYTES_PER_SERIES = 235_252
EXPECTED_TOTAL_BYTES = 705_756
EXPECTED_AGGREGATE_SHA256 = {
    "real": "c95bc0f9b68cee8e278c0468368f9d72e84fe737ed17e9ca379198b4a0a80465",
    "imaginary": "ab6db08610bedde3976e50799e5594b7c2bb6909536631c418a44a9687720572",
    "weight": "a9124261fa13dbb0b0c1f9313b9eba5f78806a6abec9153f6c98e7c485276f31",
}
PayloadConsumer = Callable[
    [dict[str, str], str, bytes, dict[str, object]], None
]


def file_hash(path: Path, algorithm: str = "sha256") -> str:
    digest = hashlib.new(algorithm)
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def git_blob_sha(path: Path) -> str:
    digest = hashlib.sha1()
    digest.update(f"blob {path.stat().st_size}\0".encode("ascii"))
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def load_selection(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        if tuple(reader.fieldnames or ()) != EXPECTED_COLUMNS:
            raise SystemExit("selection.tsv has an unexpected schema")
        rows = list(reader)
    if tuple(row["source_id"] for row in rows) != EXPECTED_SOURCE_IDS:
        raise SystemExit("selected source count or order changed")
    repositories = {row["repository"] for row in rows}
    if len(repositories) != len(rows):
        raise SystemExit("expected one selected file per release repository")
    return rows


def validate_identity(path: Path, size: int, digest: str, label: str) -> None:
    if not path.is_file():
        raise SystemExit(f"missing {label}: {path}")
    if path.stat().st_size != size or file_hash(path) != digest:
        raise SystemExit(f"{label} identity mismatch")


def validate_license(path: Path, repository: str) -> None:
    validate_identity(path, *EXPECTED_LICENSE, f"{repository} license notice")
    normalized = " ".join(path.read_text(encoding="utf-8").lower().split())
    if LICENSE_TEXT not in normalized:
        raise SystemExit(f"{repository}: missing data-specific ODC-PDDL declaration")


def parse_value(card: bytes) -> object:
    raw = card[10:80].decode("ascii", errors="strict").rstrip()
    if raw.startswith("'"):
        chars: list[str] = []
        index = 1
        while index < len(raw):
            if raw[index] == "'":
                if index + 1 < len(raw) and raw[index + 1] == "'":
                    chars.append("'")
                    index += 2
                    continue
                break
            chars.append(raw[index])
            index += 1
        return "".join(chars).strip()
    token = raw.split("/", 1)[0].strip()
    if token in {"T", "F"}:
        return token == "T"
    try:
        return int(token)
    except ValueError:
        try:
            return float(token.replace("D", "E"))
        except ValueError:
            return token


def read_header(data: bytes, offset: int) -> tuple[dict[str, object], int]:
    values: dict[str, object] = {}
    cursor = offset
    while cursor + CARD <= len(data):
        card = data[cursor : cursor + CARD]
        cursor += CARD
        keyword = card[:8].decode("ascii", errors="strict").strip()
        if keyword == "END":
            return values, ((cursor + BLOCK - 1) // BLOCK) * BLOCK
        if card[8:10] == b"= ":
            values[keyword] = parse_value(card)
    raise ValueError(f"unterminated FITS header at byte {offset}")


def product(values: list[int]) -> int:
    result = 1
    for value in values:
        result *= value
    return result


def hdu_data_size(header: dict[str, object]) -> int:
    bitpix = abs(int(header.get("BITPIX", 0)))
    naxis = int(header.get("NAXIS", 0))
    axes = [int(header.get(f"NAXIS{index}", 0)) for index in range(1, naxis + 1)]
    pcount = int(header.get("PCOUNT", 0))
    gcount = int(header.get("GCOUNT", 1))
    if header.get("GROUPS") is True and axes and axes[0] == 0:
        elements = pcount + product(axes[1:])
    elif naxis == 0:
        elements = pcount
    else:
        elements = pcount + product(axes)
    if bitpix == 0 or bitpix % 8:
        raise ValueError(f"invalid FITS BITPIX={header.get('BITPIX')!r}")
    return elements * gcount * (bitpix // 8)


def parse_fits_layout(data: bytes) -> tuple[dict[str, object], int, int, int]:
    offset = 0
    primary_header: dict[str, object] | None = None
    primary_start = 0
    primary_size = 0
    hdu_count = 0
    while offset < len(data):
        header, data_start = read_header(data, offset)
        data_size = hdu_data_size(header)
        if primary_header is None:
            primary_header = header
            primary_start = data_start
            primary_size = data_size
        hdu_count += 1
        offset = data_start + ((data_size + BLOCK - 1) // BLOCK) * BLOCK
    if offset != len(data) or primary_header is None:
        raise ValueError("invalid complete FITS HDU layout")
    return primary_header, primary_start, primary_size, hdu_count


def payload_profile(payload: bytes, field: str) -> dict[str, object]:
    if len(payload) % 4:
        raise ValueError("output payload is not float32 aligned")
    words = [payload[index : index + 4] for index in range(0, len(payload), 4)]
    values = [value[0] for value in struct.iter_unpack("<f", payload)]
    if not values or not all(math.isfinite(value) for value in values):
        raise ValueError(f"{field} output contains no values or non-finite values")
    if field == "weight" and any(value <= 0 for value in values):
        raise ValueError("retained visibility weight is not strictly positive")
    return {
        "value_count": len(values),
        "sample_size_bytes": len(payload),
        "zero_count": sum(value == 0 for value in values),
        "minimum": min(values),
        "maximum": max(values),
        "distinct_words": len(set(words)),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }


def extract_source(path: Path, row: dict[str, str]) -> tuple[dict[str, bytes], dict[str, object]]:
    validate_identity(path, int(row["size_bytes"]), row["sha256"], row["source_id"])
    if git_blob_sha(path) != row["git_blob_sha"]:
        raise SystemExit(f"{row['source_id']}: Git blob identity mismatch")
    data = path.read_bytes()
    try:
        header, data_start, data_size, hdu_count = parse_fits_layout(data)
    except (UnicodeDecodeError, ValueError) as error:
        raise SystemExit(f"{row['source_id']}: {error}") from error
    naxis = int(header.get("NAXIS", 0))
    axes = [int(header.get(f"NAXIS{index}", 0)) for index in range(1, naxis + 1)]
    gcount = int(header.get("GCOUNT", 0))
    pcount = int(header.get("PCOUNT", 0))
    ptypes = [str(header.get(f"PTYPE{index}", "")) for index in range(1, pcount + 1)]
    required = {
        "BITPIX": -32,
        "GROUPS": True,
        "CTYPE2": "COMPLEX",
        "CTYPE3": "STOKES",
        "CRVAL3": -1,
        "CRPIX3": 1,
        "CDELT3": -1,
        "OBJECT": row["object"],
        "DATE-OBS": row["date_obs"],
    }
    for key, expected in required.items():
        if header.get(key) != expected:
            raise SystemExit(
                f"{row['source_id']}: FITS header mismatch {key}={header.get(key)!r}"
            )
    if (
        axes != EXPECTED_AXES
        or pcount != len(EXPECTED_PTYPES)
        or ptypes != EXPECTED_PTYPES
        or gcount != int(row["gcount"])
        or hdu_count != int(row["hdu_count"])
    ):
        raise SystemExit(f"{row['source_id']}: random-groups structure changed")
    values_per_group = product(axes[1:])
    if values_per_group != 12 or data_size != gcount * (pcount + 12) * 4:
        raise SystemExit(f"{row['source_id']}: primary payload size changed")

    output = {field: bytearray() for field in FIELDS}
    duplicate_ll = 0
    invalid_zero = 0
    invalid_inf = 0
    group_stride = (pcount + values_per_group) * 4
    for group in range(gcount):
        group_start = data_start + group * group_stride + pcount * 4
        raw = data[group_start : group_start + 48]
        if len(raw) != 48:
            raise SystemExit(f"{row['source_id']}: truncated group {group}")
        triplets: list[tuple[list[bytes], list[float]]] = []
        for polarization in range(4):
            triplet_start = polarization * 12
            words = [
                raw[triplet_start + index : triplet_start + index + 4]
                for index in (0, 4, 8)
            ]
            values = [struct.unpack(">f", word)[0] for word in words]
            triplets.append((words, values))
        for polarization, (words, values) in enumerate(triplets):
            real, imaginary, weight = values
            if polarization == 0:
                if not (math.isfinite(real) and math.isfinite(imaginary)):
                    raise SystemExit(f"{row['source_id']}: non-finite RR/LL visibility")
                if not math.isfinite(weight) or weight <= 0:
                    raise SystemExit(f"{row['source_id']}: invalid RR/LL weight")
                for field, word in zip(FIELDS, words):
                    output[field].extend(word[::-1])
            elif polarization == 1:
                if not (math.isfinite(real) and math.isfinite(imaginary)):
                    raise SystemExit(f"{row['source_id']}: non-finite RR/LL visibility")
                if not math.isfinite(weight) or weight <= 0:
                    raise SystemExit(f"{row['source_id']}: invalid RR/LL weight")
                if words != triplets[0][0]:
                    raise SystemExit(f"{row['source_id']}: RR/LL Stokes-I copies differ")
                duplicate_ll += 1
            else:
                if real != 0 or imaginary != 0:
                    raise SystemExit(f"{row['source_id']}: populated RL/LR placeholder")
                if weight == 0:
                    invalid_zero += 1
                elif math.isinf(weight) and weight > 0:
                    invalid_inf += 1
                else:
                    raise SystemExit(f"{row['source_id']}: unexpected RL/LR weight")

    payloads = {field: bytes(payload) for field, payload in output.items()}
    expected_values = int(row["output_value_count"])
    if (
        any(len(payload) != expected_values * 4 for payload in payloads.values())
        or duplicate_ll != int(row["duplicate_ll_count"])
        or invalid_zero != int(row["invalid_zero_weight_count"])
        or invalid_inf != int(row["invalid_inf_weight_count"])
    ):
        raise SystemExit(f"{row['source_id']}: retained or rejected count changed")
    field_profiles = {
        field: payload_profile(payload, field) for field, payload in payloads.items()
    }
    if any(int(profile["distinct_words"]) < 100 for profile in field_profiles.values()):
        raise SystemExit(f"{row['source_id']}: degenerate retained field")
    return payloads, {
        "source_id": row["source_id"],
        "repository": row["repository"],
        "commit": row["commit"],
        "source_sha256": row["sha256"],
        "object": row["object"],
        "date_obs": row["date_obs"],
        "hdu_count": hdu_count,
        "random_group_count": gcount,
        "source_parallel_hand_slots": ["RR", "LL"],
        "emitted_parallel_hand": "RR representative of byte-identical RR/LL",
        "duplicate_ll_count": duplicate_ll,
        "invalid_cross_hand_zero_weight_count": invalid_zero,
        "invalid_cross_hand_infinite_weight_count": invalid_inf,
        "field_profiles": field_profiles,
    }


def scan_source(
    selection: Path,
    download_dir: Path,
    consumer: PayloadConsumer | None = None,
) -> dict[str, object]:
    rows = load_selection(selection)
    profiles: list[dict[str, object]] = []
    aggregates = {field: hashlib.sha256() for field in FIELDS}
    output_hashes = {field: set() for field in FIELDS}
    for row in rows:
        license_path = download_dir / f"{row['repository']}__LICENSE.txt"
        validate_license(license_path, row["repository"])
        payloads, profile = extract_source(download_dir / row["target"], row)
        profiles.append(profile)
        for field in FIELDS:
            payload = payloads[field]
            digest = str(profile["field_profiles"][field]["sha256"])
            if digest in output_hashes[field]:
                raise SystemExit(f"duplicate {field} sample: {row['source_id']}")
            output_hashes[field].add(digest)
            aggregates[field].update(payload)
            if consumer is not None:
                consumer(row, field, payload, profile)
    series_profiles = {}
    for field in FIELDS:
        field_profiles = [profile["field_profiles"][field] for profile in profiles]
        series_profile = {
            "series_id": SERIES_IDS[field],
            "sample_count": len(field_profiles),
            "value_count": sum(int(item["value_count"]) for item in field_profiles),
            "total_size_bytes": sum(int(item["sample_size_bytes"]) for item in field_profiles),
            "aggregate_source_order_sha256": aggregates[field].hexdigest(),
        }
        if (
            series_profile["value_count"] != EXPECTED_TOTAL_VALUES_PER_SERIES
            or series_profile["total_size_bytes"] != EXPECTED_BYTES_PER_SERIES
        ):
            raise SystemExit(f"aggregate {field} totals changed")
        pinned = EXPECTED_AGGREGATE_SHA256.get(field)
        if pinned and series_profile["aggregate_source_order_sha256"] != pinned:
            raise SystemExit(f"aggregate {field} payload hash changed")
        series_profiles[field] = series_profile
    result = {
        "dataset_id": DATASET_ID,
        "license": "ODC-PDDL-1.0",
        "license_size_bytes": EXPECTED_LICENSE[0],
        "license_sha256": EXPECTED_LICENSE[1],
        "source_count": len(profiles),
        "series_count": len(FIELDS),
        "sample_count": len(profiles) * len(FIELDS),
        "primary_value_count": EXPECTED_TOTAL_VALUES_PER_SERIES * len(FIELDS),
        "primary_size_bytes": EXPECTED_TOTAL_BYTES,
        "retained_representation": "one value per group after validating byte-identical RR/LL",
        "rejected_polarizations": ["RL", "LR"],
        "series_profiles": series_profiles,
        "source_profiles": profiles,
    }
    return result


def index_entry(
    row: dict[str, str],
    field: str,
    profile: dict[str, object],
    output: Path,
    source: Path,
    data_root: Path,
) -> dict[str, object]:
    metrics = profile["field_profiles"][field]
    source_fields = {
        "real": "random-groups DATA real component; STOKES RR and LL",
        "imaginary": "random-groups DATA imaginary component; STOKES RR and LL",
        "weight": "random-groups DATA statistical weight; STOKES RR and LL",
    }
    return {
        "dataset_id": DATASET_ID,
        "series_id": SERIES_IDS[field],
        "role": "primary",
        "sample_path": output.relative_to(data_root).as_posix(),
        "source_sample": source.relative_to(data_root).as_posix(),
        "source_field": source_fields[field],
        "source_id": row["source_id"],
        "repository": row["repository"],
        "object": row["object"],
        "date_obs": row["date_obs"],
        "numeric_kind": "float",
        "bit_width": 32,
        "endianness": "little",
        "element_size_bytes": 4,
        "value_count": metrics["value_count"],
        "sample_size_bytes": metrics["sample_size_bytes"],
        "sample_format": f"raw homogeneous IEEE-754 float32 visibility {field} field",
        "sample_geometry": "uv_visibility_random_group_sequence_1d",
        "sample_rank": 1,
        "sample_shape": [profile["random_group_count"]],
        "sample_axes": ["random_group_source_order"],
        "polarization_collapse": "RR emitted after byte-exact RR/LL equality check",
        "natural_record_kind": "complete_calibrated_uvfits_observation_field",
        "zero_count": metrics["zero_count"],
        "minimum": metrics["minimum"],
        "maximum": metrics["maximum"],
        "distinct_words": metrics["distinct_words"],
        "sha256": metrics["sha256"],
    }


def preflight(args: argparse.Namespace) -> None:
    result = scan_source(args.selection, args.download_dir)
    args.profile.parent.mkdir(parents=True, exist_ok=True)
    args.profile.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps({key: value for key, value in result.items() if key != "source_profiles"}, indent=2, sort_keys=True))


def build(args: argparse.Namespace) -> None:
    if args.samples_dir.exists():
        shutil.rmtree(args.samples_dir)
    args.samples_dir.mkdir(parents=True)
    args.index.parent.mkdir(parents=True, exist_ok=True)
    index_rows: list[dict[str, object]] = []

    def emit(row: dict[str, str], field: str, payload: bytes, profile: dict[str, object]) -> None:
        series_dir = args.samples_dir / SERIES_IDS[field]
        series_dir.mkdir(exist_ok=True)
        output = series_dir / (
            f"{row['source_id']}__{field}_f32_n{profile['random_group_count']}.bin"
        )
        output.write_bytes(payload)
        source = args.download_dir / row["target"]
        index_rows.append(index_entry(row, field, profile, output, source, args.data_root))

    result = scan_source(args.selection, args.download_dir, emit)
    args.index.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in index_rows),
        encoding="utf-8",
    )
    args.stats.parent.mkdir(parents=True, exist_ok=True)
    args.stats.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps({key: value for key, value in result.items() if key != "source_profiles"}, indent=2, sort_keys=True))


def verify(args: argparse.Namespace) -> None:
    if not args.index.is_file() or not args.stats.is_file():
        raise SystemExit("missing index or statistics; run build first")
    indexed = [
        json.loads(line)
        for line in args.index.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    cursor = 0
    expected_outputs: set[Path] = set()

    def compare(row: dict[str, str], field: str, payload: bytes, profile: dict[str, object]) -> None:
        nonlocal cursor
        if cursor >= len(indexed):
            raise SystemExit("sample index has fewer rows than outputs")
        series_dir = args.samples_dir / SERIES_IDS[field]
        output = series_dir / (
            f"{row['source_id']}__{field}_f32_n{profile['random_group_count']}.bin"
        )
        source = args.download_dir / row["target"]
        expected = index_entry(row, field, profile, output, source, args.data_root)
        if indexed[cursor] != expected:
            raise SystemExit(f"index mismatch at row {cursor + 1}")
        cursor += 1
        if not output.is_file() or output.read_bytes() != payload:
            raise SystemExit(f"output differs from fresh source conversion: {output}")
        expected_outputs.add(output.resolve())

    result = scan_source(args.selection, args.download_dir, compare)
    if cursor != len(indexed):
        raise SystemExit("sample index has extra rows")
    actual_outputs = {path.resolve() for path in args.samples_dir.rglob("*.bin")}
    if actual_outputs != expected_outputs:
        raise SystemExit("sample directory contains missing or stale outputs")
    if json.loads(args.stats.read_text(encoding="utf-8")) != result:
        raise SystemExit("ingest statistics differ from fresh source scan")
    print(
        f"verified_samples={cursor} values={result['primary_value_count']} "
        f"bytes={result['primary_size_bytes']}"
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("preflight", "build", "verify"))
    parser.add_argument("--selection", type=Path, required=True)
    parser.add_argument("--download-dir", type=Path, required=True)
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
