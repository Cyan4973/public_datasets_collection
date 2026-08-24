#!/usr/bin/env python3
"""Decode and verify accepted uint8 measurement blocks from fixed-layout RDI PD0."""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import shutil
import struct


DATASET_ID = "zenodo_adcp_pd0_backscatter_quality_u8"
ENSEMBLE_BYTES = 1172
TOTAL_ENSEMBLE_BYTES = 1174
BEAMS = 4
CELLS = 51
VALUES_PER_ENSEMBLE = BEAMS * CELLS
OFFSETS = (18, 77, 142, 552, 758, 964)
BLOCK_IDS = (0x0000, 0x0080, 0x0100, 0x0200, 0x0300, 0x0400)
FIELDS = {
    "correlation": {
        "series_id": "adcp_correlation_magnitude_u8",
        "block_id": 0x0200,
        "start": OFFSETS[3] + 2,
        "end": OFFSETS[4],
        "meaning": "correlation_magnitude",
    },
    "echo_intensity": {
        "series_id": "adcp_echo_intensity_u8",
        "block_id": 0x0300,
        "start": OFFSETS[4] + 2,
        "end": OFFSETS[5],
        "meaning": "echo_intensity",
    },
    "percent_good": {
        "series_id": "adcp_percent_good_u8",
        "block_id": 0x0400,
        "start": OFFSETS[5] + 2,
        "end": OFFSETS[5] + 2 + VALUES_PER_ENSEMBLE,
        "meaning": "percent_good",
    },
}
SOURCES = (
    {"name": "line2_ADCP1000.000", "size": 24_813_664, "md5": "04c27147b68aecb5e6feef84702d9b5e", "ensembles": 21_136},
    {"name": "line2_ADCP1001.000", "size": 46_960_000, "md5": "8e1631f12dd8caa61c2dc76a31efb642", "ensembles": 40_000},
    {"name": "line3_ADCP2001.000", "size": 10_962_812, "md5": "3f8da2d38e4f6783f5fdff1dff82f3a1", "ensembles": 9_338},
)
EXPECTED_AGGREGATE_SHA256 = "8b60f7c7aeb54d06b6317ae52e578d1a94867f09fa8fbdc9e09f2ef9394a2d6b"


def file_hash(path: Path, algorithm: str) -> str:
    digest = hashlib.new(algorithm)
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def validate_record_metadata(download_dir: Path) -> None:
    path = download_dir / "zenodo_record_5015459.json"
    if not path.is_file():
        raise SystemExit(f"missing Zenodo metadata: {path}")
    record = json.loads(path.read_text(encoding="utf-8"))
    metadata = record.get("metadata", {})
    license_obj = metadata.get("license", {}) if isinstance(metadata, dict) else {}
    if (int(record.get("id", 0)) != 5015459
            or metadata.get("title") != "Salinity and Velocity in Lower South San Francisco Bay"
            or not isinstance(license_obj, dict) or license_obj.get("id") != "cc-by-4.0"):
        raise SystemExit("unexpected Zenodo record identity, title, or license")


def measure(payload: bytes) -> dict[str, object]:
    counts = Counter(payload)
    dominant_value, dominant_count = counts.most_common(1)[0]
    transitions = sum(left != right for left, right in zip(payload, payload[1:]))
    if len(counts) < 4 or dominant_count / len(payload) > 0.999 or transitions < 10_000:
        raise ValueError("degenerate byte field")
    return {
        "minimum": min(counts),
        "maximum": max(counts),
        "distinct_values": len(counts),
        "dominant_value": dominant_value,
        "dominant_value_count": dominant_count,
        "zero_count": counts[0],
        "value_255_count": counts[255],
        "transitions": transitions,
        "decoded_sha256": hashlib.sha256(payload).hexdigest(),
    }


def decode_source(path: Path, expected: dict[str, object]) -> tuple[dict[str, bytes], dict[str, object]]:
    if path.stat().st_size != expected["size"] or file_hash(path, "md5") != expected["md5"]:
        raise ValueError(f"{path.name}: source size or MD5 mismatch")
    data = path.read_bytes()
    if len(data) % TOTAL_ENSEMBLE_BYTES:
        raise ValueError(f"{path.name}: source is not an exact sequence of fixed PD0 ensembles")
    payloads = {field_id: bytearray() for field_id in FIELDS}
    checksum_sum = 0
    ensemble_count = 0
    for position in range(0, len(data), TOTAL_ENSEMBLE_BYTES):
        if data[position:position + 2] != b"\x7f\x7f":
            raise ValueError(f"{path.name}: missing PD0 header at byte {position}")
        ensemble_bytes = struct.unpack_from("<H", data, position + 2)[0]
        if ensemble_bytes != ENSEMBLE_BYTES or data[position + 5] != len(OFFSETS):
            raise ValueError(f"{path.name}: ensemble {ensemble_count} framing changed")
        offsets = struct.unpack_from(f"<{len(OFFSETS)}H", data, position + 6)
        block_ids = tuple(struct.unpack_from("<H", data, position + offset)[0] for offset in offsets)
        if offsets != OFFSETS or block_ids != BLOCK_IDS:
            raise ValueError(f"{path.name}: ensemble {ensemble_count} block layout changed")
        fixed = position + OFFSETS[0]
        geometry = (
            data[fixed + 8], data[fixed + 9],
            struct.unpack_from("<H", data, fixed + 12)[0],
            struct.unpack_from("<H", data, fixed + 14)[0],
            data[fixed + 25],
        )
        if geometry != (4, 51, 25, 44, 31):
            raise ValueError(f"{path.name}: ensemble {ensemble_count} geometry changed: {geometry}")
        ensemble_end = position + ENSEMBLE_BYTES
        stored_checksum = struct.unpack_from("<H", data, ensemble_end)[0]
        if stored_checksum != (sum(data[position:ensemble_end]) & 0xFFFF):
            raise ValueError(f"{path.name}: ensemble {ensemble_count} checksum mismatch")
        checksum_sum = (checksum_sum + stored_checksum) & 0xFFFFFFFFFFFFFFFF
        for field_id, field in FIELDS.items():
            block = data[position + int(field["start"]):position + int(field["end"])]
            if len(block) != VALUES_PER_ENSEMBLE:
                raise ValueError(f"{path.name}: short {field_id} block")
            payloads[field_id].extend(block)
        ensemble_count += 1
    if ensemble_count != expected["ensembles"]:
        raise ValueError(f"{path.name}: ensemble count {ensemble_count} != {expected['ensembles']}")
    final = {field_id: bytes(payload) for field_id, payload in payloads.items()}
    reports = {field_id: measure(payload) for field_id, payload in final.items()}
    return final, {
        "source_file": path.name,
        "source_bytes": path.stat().st_size,
        "source_md5": expected["md5"],
        "ensemble_count": ensemble_count,
        "ensemble_bytes": ENSEMBLE_BYTES,
        "data_type_offsets": list(OFFSETS),
        "block_ids": [f"0x{value:04x}" for value in BLOCK_IDS],
        "depth_cells": CELLS,
        "beams": BEAMS,
        "cell_length_cm": 25,
        "blank_after_transmit_cm": 44,
        "coordinate_transform_byte": 31,
        "checksum_sum_mod_u64": checksum_sum,
        "fields": reports,
    }


def decode_all(download_dir: Path):
    validate_record_metadata(download_dir)
    decoded = []
    for expected in SOURCES:
        path = download_dir / str(expected["name"])
        if not path.is_file():
            raise SystemExit(f"missing source: {path}")
        payloads, report = decode_source(path, expected)
        decoded.append((path, payloads, report))
    aggregate = hashlib.sha256()
    for _path, payloads, _report in decoded:
        for field_id in FIELDS:
            aggregate.update(payloads[field_id])
    if aggregate.hexdigest() != EXPECTED_AGGREGATE_SHA256:
        raise ValueError("aggregate decoded byte-field hash changed")
    return decoded


def make_summary(decoded) -> dict[str, object]:
    aggregate = hashlib.sha256()
    for _path, payloads, _report in decoded:
        for field_id in FIELDS:
            aggregate.update(payloads[field_id])
    return {
        "dataset_id": DATASET_ID,
        "source_count": len(decoded),
        "series_count": len(FIELDS),
        "sample_count": len(decoded) * len(FIELDS),
        "ensemble_count": sum(int(report["ensemble_count"]) for _p, _b, report in decoded),
        "value_count": sum(len(payload) for _p, payloads, _r in decoded for payload in payloads.values()),
        "total_size_bytes": sum(len(payload) for _p, payloads, _r in decoded for payload in payloads.values()),
        "aggregate_payload_sha256": aggregate.hexdigest(),
        "source_inspections": [report for _p, _b, report in decoded],
    }


def inspect(args: argparse.Namespace) -> None:
    result = make_summary(decode_all(args.download_dir))
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2, sort_keys=True))


def build(args: argparse.Namespace) -> None:
    decoded = decode_all(args.download_dir)
    if args.samples_dir.exists():
        shutil.rmtree(args.samples_dir)
    rows = []
    for source, payloads, report in decoded:
        stem = source.name.removesuffix(".000")
        ensembles = int(report["ensemble_count"])
        for field_id, field in FIELDS.items():
            payload = payloads[field_id]
            series_id = str(field["series_id"])
            output_dir = args.samples_dir / series_id
            output_dir.mkdir(parents=True, exist_ok=True)
            output = output_dir / f"{stem}_e{ensembles}_c{CELLS}_b{BEAMS}_u8.bin"
            output.write_bytes(payload)
            measured = report["fields"][field_id]
            rows.append({
                "dataset_id": DATASET_ID,
                "series_id": series_id,
                "role": "primary",
                "sample_path": output.relative_to(args.data_root).as_posix(),
                "source_sample": source.relative_to(args.data_root).as_posix(),
                "source_file": source.name,
                "source_block_id": f"0x{int(field['block_id']):04x}",
                "numeric_kind": "uint",
                "bit_width": 8,
                "endianness": "little",
                "element_size_bytes": 1,
                "value_count": len(payload),
                "sample_size_bytes": len(payload),
                "sample_format": f"raw homogeneous uint8 ADCP {field['meaning']} field",
                "sample_geometry": "3d_adcp_beam_field",
                "sample_rank": 3,
                "sample_shape": [ensembles, CELLS, BEAMS],
                "sample_axes": ["measurement_ensemble", "depth_cell", "beam"],
                "natural_record_kind": "complete_adcp_recording",
                "minimum": measured["minimum"],
                "maximum": measured["maximum"],
                "distinct_values": measured["distinct_values"],
                "sha256": measured["decoded_sha256"],
            })
    args.index.parent.mkdir(parents=True, exist_ok=True)
    args.index.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in rows), encoding="utf-8")
    result = make_summary(decoded)
    args.stats.parent.mkdir(parents=True, exist_ok=True)
    args.stats.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in result.items() if key != "source_inspections"}, indent=2, sort_keys=True))


def verify(args: argparse.Namespace) -> None:
    decoded = decode_all(args.download_dir)
    if not args.index.is_file() or not args.stats.is_file():
        raise SystemExit("missing index or stats; run build first")
    rows = [json.loads(line) for line in args.index.read_text(encoding="utf-8").splitlines() if line.strip()]
    expected = []
    for source, payloads, report in decoded:
        for field_id, field in FIELDS.items():
            expected.append((source, field_id, field, payloads[field_id], report))
    if len(rows) != len(expected) or json.loads(args.stats.read_text(encoding="utf-8")) != make_summary(decoded):
        raise SystemExit("index/stats differ from fresh source decode")
    outputs = set()
    for row, (source, field_id, field, payload, report) in zip(rows, expected, strict=True):
        if row.get("source_file") != source.name or row.get("series_id") != field["series_id"]:
            raise SystemExit(f"sample identity mismatch for {source.name}/{field_id}")
        if row.get("numeric_kind") != "uint" or row.get("bit_width") != 8 or row.get("endianness") != "little":
            raise SystemExit(f"numeric schema mismatch for {source.name}/{field_id}")
        if row.get("sample_shape") != [int(report["ensemble_count"]), CELLS, BEAMS]:
            raise SystemExit(f"shape mismatch for {source.name}/{field_id}")
        output = args.data_root / row["sample_path"]
        if not output.is_file() or output.read_bytes() != payload:
            raise SystemExit(f"output differs from fresh decode: {output}")
        if row.get("sha256") != hashlib.sha256(payload).hexdigest():
            raise SystemExit(f"indexed hash mismatch: {output}")
        outputs.add(output.resolve())
    actual = {path.resolve() for path in (args.data_root / "samples" / DATASET_ID).glob("*/*.bin")}
    if actual != outputs:
        raise SystemExit("sample directory contains missing, stale, or extra outputs")
    result = make_summary(decoded)
    print(json.dumps({
        "dataset_id": DATASET_ID,
        "verified_samples": len(expected),
        "verified_values": result["value_count"],
        "verified_bytes": result["total_size_bytes"],
        "aggregate_payload_sha256": result["aggregate_payload_sha256"],
    }, indent=2, sort_keys=True))


def main() -> None:
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    inspect_parser = commands.add_parser("inspect")
    inspect_parser.add_argument("--download-dir", type=Path, required=True)
    inspect_parser.add_argument("--report", type=Path, required=True)
    for command in ("build", "verify"):
        sub = commands.add_parser(command)
        sub.add_argument("--download-dir", type=Path, required=True)
        sub.add_argument("--index", type=Path, required=True)
        sub.add_argument("--stats", type=Path, required=True)
        sub.add_argument("--data-root", type=Path, required=True)
        if command == "build":
            sub.add_argument("--samples-dir", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "inspect":
        inspect(args)
    elif args.command == "build":
        build(args)
    else:
        verify(args)


if __name__ == "__main__":
    main()
