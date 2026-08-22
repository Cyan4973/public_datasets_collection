#!/usr/bin/env python3
"""Decode and verify native uint8 NICER detector-address event columns."""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import math
from pathlib import Path
import re
import shutil
import statistics


DATASET_ID = "nasa_heasarc_nicer_detector_u8"
SOURCE_DATASET_ID = "nasa_heasarc_nicer_pi_i16"
EXPECTED_INVENTORY_SHA256 = "dda1282955970175fef938499abfbbeddc82e1ad239937927896af2cb10de554"
EXPECTED_SOURCE_FILES = 36
EXPECTED_SOURCE_BYTES = 205_174_726
EXPECTED_SELECTED = 31
EXPECTED_VALUES_PER_SERIES = 8_938_390
MIN_ROWS = 1_000
ROW_CHUNK = 65_536
FITS_BLOCK = 2_880
FIELDS = {
    "RAWX": {
        "series_id": "nicer_rawx_u8",
        "unit": "pixel",
        "semantic": "detector X address",
        "format": "raw homogeneous uint8 detector X-address array",
        "natural_record_kind": "nicer_observation_rawx_event_sequence",
    },
    "RAWY": {
        "series_id": "nicer_rawy_u8",
        "unit": "pixel",
        "semantic": "detector Y address",
        "format": "raw homogeneous uint8 detector Y-address array",
        "natural_record_kind": "nicer_observation_rawy_event_sequence",
    },
    "DET_ID": {
        "series_id": "nicer_detector_id_u8",
        "unit": None,
        "semantic": "hardware detector identifier",
        "format": "raw homogeneous uint8 detector-identifier array",
        "natural_record_kind": "nicer_observation_detector_id_event_sequence",
    },
}


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def load_sources(path: Path, download_dir: Path) -> list[dict[str, object]]:
    if file_hash(path) != EXPECTED_INVENTORY_SHA256:
        raise SystemExit("shared NICER sources.tsv identity changed")
    with path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    if len(rows) != EXPECTED_SOURCE_FILES or sum(int(row["bytes"]) for row in rows) != EXPECTED_SOURCE_BYTES:
        raise SystemExit("shared NICER source inventory geometry changed")
    if len({row["obs_id"] for row in rows}) != len(rows):
        raise SystemExit("duplicate observation ID in source inventory")
    result = []
    for row in rows:
        filename = Path(row["filename"])
        if filename.name != row["filename"] or not row["obs_id"].isdigit():
            raise SystemExit("unsafe source inventory identity")
        source = download_dir / filename
        expected_size = int(row["bytes"])
        if not source.is_file() or source.stat().st_size != expected_size:
            raise SystemExit(f"missing or size-mismatched pinned source: {source}")
        if file_hash(source) != row["sha256"]:
            raise SystemExit(f"pinned source SHA-256 mismatch: {source}")
        result.append({**row, "bytes": expected_size, "path": source})
    return result


def parse_card_value(text: str) -> object:
    value = text.split("/", 1)[0].strip()
    if value.startswith("'"):
        end = value.rfind("'")
        return value[1:end].replace("''", "'").strip() if end > 0 else value
    if value in {"T", "F"}:
        return value == "T"
    try:
        return float(value.replace("D", "E")) if any(ch in value for ch in ".EeDd") else int(value)
    except ValueError:
        return value


def read_header(handle: gzip.GzipFile) -> dict[str, object]:
    header: dict[str, object] = {}
    cards = 0
    found_end = False
    while not found_end:
        block = handle.read(FITS_BLOCK)
        if len(block) != FITS_BLOCK:
            raise ValueError("truncated FITS header")
        for offset in range(0, FITS_BLOCK, 80):
            card = block[offset : offset + 80].decode("ascii", errors="strict")
            cards += 1
            keyword = card[:8].strip()
            if keyword == "END":
                found_end = True
                break
            if len(card) >= 10 and card[8:10] == "= ":
                header[keyword] = parse_card_value(card[10:])
        if cards > 100_000:
            raise ValueError("FITS header is unreasonably large")
    return header


def hdu_data_bytes(header: dict[str, object]) -> int:
    xtension = str(header.get("XTENSION", "")).strip().upper()
    if xtension == "BINTABLE":
        return int(header.get("NAXIS1", 0)) * int(header.get("NAXIS2", 0)) + int(header.get("PCOUNT", 0))
    naxis = int(header.get("NAXIS", 0))
    axes = [int(header[f"NAXIS{i}"]) for i in range(1, naxis + 1)]
    if any(axis < 0 for axis in axes):
        raise ValueError("negative FITS axis")
    elements = math.prod(axes) if axes else 0
    bitpix = abs(int(header.get("BITPIX", 0)))
    if bitpix % 8:
        raise ValueError("non-byte-aligned FITS BITPIX")
    return (bitpix // 8) * int(header.get("GCOUNT", 1)) * (int(header.get("PCOUNT", 0)) + elements)


def padded(size: int) -> int:
    return ((size + FITS_BLOCK - 1) // FITS_BLOCK) * FITS_BLOCK


def tform_bytes(tform: str) -> int:
    match = re.fullmatch(r"(\d*)([LXBIJKAEDCMPQ])(?:\([^)]*\))?", re.sub(r"\s+", "", tform).upper())
    if not match:
        raise ValueError(f"unsupported FITS TFORM: {tform!r}")
    repeat = int(match.group(1) or "1")
    widths = {"L": 1, "B": 1, "I": 2, "J": 4, "K": 8, "A": 1, "E": 4, "D": 8, "C": 8, "M": 16, "P": 8, "Q": 16}
    return (repeat + 7) // 8 if match.group(2) == "X" else repeat * widths[match.group(2)]


def table_columns(header: dict[str, object]) -> tuple[dict[str, dict[str, object]], int]:
    columns = {}
    offset = 0
    for index in range(1, int(header.get("TFIELDS", 0)) + 1):
        name = str(header.get(f"TTYPE{index}", "")).strip().upper()
        tform = str(header.get(f"TFORM{index}", "")).strip()
        width = tform_bytes(tform)
        if name:
            columns[name] = {
                "index": index,
                "offset": offset,
                "tform": tform,
                "width": width,
                "tscal": header.get(f"TSCAL{index}", 1),
                "tzero": header.get(f"TZERO{index}", 0),
                "tnull": header.get(f"TNULL{index}"),
                "tunit": header.get(f"TUNIT{index}"),
            }
        offset += width
    return columns, offset


def decode_source(source: dict[str, object]) -> dict[str, object]:
    primary = None
    with gzip.open(Path(source["path"]), "rb") as handle:
        for hdu_index in range(32):
            header = read_header(handle)
            if hdu_index == 0:
                primary = header
                if str(header.get("TELESCOP", "")).strip() != "NICER" or str(header.get("INSTRUME", "")).strip() != "XTI":
                    raise ValueError("primary HDU is not NICER/XTI")
                if str(header.get("OBS_ID", "")).strip() != source["obs_id"]:
                    raise ValueError("primary OBS_ID differs from pinned inventory")
            if str(header.get("XTENSION", "")).strip().upper() == "BINTABLE" and str(header.get("EXTNAME", "")).strip() == "EVENTS":
                columns, declared_width = table_columns(header)
                row_bytes = int(header.get("NAXIS1", 0))
                rows = int(header.get("NAXIS2", 0))
                if declared_width != row_bytes or rows < 0 or row_bytes <= 0:
                    raise ValueError("invalid EVENTS table geometry")
                for field, spec in FIELDS.items():
                    if field not in columns:
                        raise ValueError(f"missing EVENTS.{field}")
                    column = columns[field]
                    if re.sub(r"\s+", "", str(column["tform"])).upper() not in {"B", "1B"} or column["width"] != 1:
                        raise ValueError(f"EVENTS.{field} is not scalar FITS 1B")
                    if column["tscal"] != 1 or column["tzero"] != 0 or column["tnull"] is not None:
                        raise ValueError(f"EVENTS.{field} scaling/null schema changed")
                    if column["tunit"] != spec["unit"]:
                        raise ValueError(f"EVENTS.{field} unit changed")
                payloads = {field: bytearray() for field in FIELDS}
                for start in range(0, rows, ROW_CHUNK):
                    count = min(ROW_CHUNK, rows - start)
                    block = handle.read(count * row_bytes)
                    if len(block) != count * row_bytes:
                        raise ValueError("truncated FITS EVENTS table")
                    for field in FIELDS:
                        offset = int(columns[field]["offset"])
                        payloads[field].extend(block[offset::row_bytes])
                return {
                    "obs_id": source["obs_id"],
                    "filename": source["filename"],
                    "object": str(header.get("OBJECT", primary.get("OBJECT", "") if primary else "")),
                    "date_obs": str(header.get("DATE-OBS", primary.get("DATE-OBS", "") if primary else "")),
                    "date_end": str(header.get("DATE-END", primary.get("DATE-END", "") if primary else "")),
                    "hdu_index": hdu_index,
                    "row_bytes": row_bytes,
                    "rows": rows,
                    "payloads": {field: bytes(payload) for field, payload in payloads.items()},
                }
            size = hdu_data_bytes(header)
            if size:
                handle.seek(padded(size), 1)
    raise ValueError("no EVENTS binary table found")


def scan(sources_path: Path, download_dir: Path) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    sources = load_sources(sources_path, download_dir)
    selected = []
    excluded = []
    hashes = {field: set() for field in FIELDS}
    for source in sources:
        try:
            record = decode_source(source)
        except (OSError, EOFError, ValueError) as exc:
            raise SystemExit(f"failed to decode {source['filename']}: {exc}") from exc
        if record["rows"] < MIN_ROWS:
            excluded.append({"obs_id": record["obs_id"], "filename": record["filename"], "rows": record["rows"]})
            continue
        for field, payload in record["payloads"].items():
            if len(payload) != record["rows"] or len(set(payload)) < 2:
                raise SystemExit(f"degenerate {field} sequence in observation {record['obs_id']}")
            digest = hashlib.sha256(payload).hexdigest()
            if digest in hashes[field]:
                raise SystemExit(f"duplicate {field} sample")
            hashes[field].add(digest)
        selected.append(record)
    if len(selected) != EXPECTED_SELECTED:
        raise SystemExit(f"selected observation count changed: {len(selected)}")
    for field in FIELDS:
        if sum(len(record["payloads"][field]) for record in selected) != EXPECTED_VALUES_PER_SERIES:
            raise SystemExit(f"{field} aggregate value count changed")
    return selected, excluded


def make_summary(records: list[dict[str, object]], excluded: list[dict[str, object]]) -> dict[str, object]:
    profiles = []
    series = {}
    for field, spec in FIELDS.items():
        payloads = [record["payloads"][field] for record in records]
        lengths = [len(payload) for payload in payloads]
        series[spec["series_id"]] = {
            "field": field,
            "sample_count": len(payloads),
            "value_count": sum(lengths),
            "total_size_bytes": sum(lengths),
            "minimum_sample_value_count": min(lengths),
            "median_sample_value_count": statistics.median(lengths),
            "maximum_sample_value_count": max(lengths),
            "global_minimum": min(min(payload) for payload in payloads),
            "global_maximum": max(max(payload) for payload in payloads),
        }
    for record in records:
        profile = {key: value for key, value in record.items() if key != "payloads"}
        profile["fields"] = {
            field: {
                "minimum": min(payload),
                "maximum": max(payload),
                "distinct_values": len(set(payload)),
                "sha256": hashlib.sha256(payload).hexdigest(),
            }
            for field, payload in record["payloads"].items()
        }
        profiles.append(profile)
    return {
        "dataset_id": DATASET_ID,
        "source_dataset_id": SOURCE_DATASET_ID,
        "selected_observation_count": len(records),
        "excluded_observations": excluded,
        "series": series,
        "primary_sample_count": len(records) * len(FIELDS),
        "primary_value_count": sum(item["value_count"] for item in series.values()),
        "primary_size_bytes": sum(item["total_size_bytes"] for item in series.values()),
        "observation_profiles": profiles,
    }


def preflight(args: argparse.Namespace) -> None:
    records, excluded = scan(args.sources, args.download_dir)
    result = make_summary(records, excluded)
    args.profile.parent.mkdir(parents=True, exist_ok=True)
    args.profile.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in result.items() if key != "observation_profiles"}, indent=2, sort_keys=True))


def build(args: argparse.Namespace) -> None:
    records, excluded = scan(args.sources, args.download_dir)
    if args.samples_dir.exists():
        shutil.rmtree(args.samples_dir)
    rows = []
    for field, spec in FIELDS.items():
        series_dir = args.samples_dir / spec["series_id"]
        series_dir.mkdir(parents=True)
        for record in records:
            payload = record["payloads"][field]
            output = series_dir / f"obs_{record['obs_id']}_{field.lower()}_u8_n{len(payload)}.bin"
            output.write_bytes(payload)
            rows.append({
                "dataset_id": DATASET_ID,
                "series_id": spec["series_id"],
                "role": "primary",
                "sample_path": output.relative_to(args.data_root).as_posix(),
                "source_sample": (args.download_dir / record["filename"]).relative_to(args.data_root).as_posix(),
                "source_observation_id": record["obs_id"],
                "source_field": f"EVENTS.{field}",
                "numeric_kind": "uint",
                "bit_width": 8,
                "endianness": "little",
                "element_size_bytes": 1,
                "value_count": len(payload),
                "sample_size_bytes": len(payload),
                "sample_format": spec["format"],
                "sample_geometry": "variable_length_xray_photon_detector_address_1d",
                "sample_rank": 1,
                "sample_shape": [len(payload)],
                "sample_axes": ["photon_event"],
                "natural_record_kind": spec["natural_record_kind"],
                "minimum": min(payload),
                "maximum": max(payload),
                "distinct_values": len(set(payload)),
                "sha256": hashlib.sha256(payload).hexdigest(),
            })
    args.index.parent.mkdir(parents=True, exist_ok=True)
    args.index.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in rows), encoding="utf-8")
    result = make_summary(records, excluded)
    args.stats.parent.mkdir(parents=True, exist_ok=True)
    args.stats.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in result.items() if key != "observation_profiles"}, indent=2, sort_keys=True))


def verify(args: argparse.Namespace) -> None:
    records, excluded = scan(args.sources, args.download_dir)
    if not args.index.is_file() or not args.stats.is_file():
        raise SystemExit("missing index or ingest stats; run build first")
    rows = [json.loads(line) for line in args.index.read_text(encoding="utf-8").splitlines() if line.strip()]
    if len(rows) != len(records) * len(FIELDS):
        raise SystemExit("index row count differs from expected field/observation count")
    expected_outputs = set()
    cursor = 0
    for field, spec in FIELDS.items():
        for record in records:
            row = rows[cursor]
            cursor += 1
            payload = record["payloads"][field]
            if row.get("dataset_id") != DATASET_ID or row.get("series_id") != spec["series_id"] or row.get("role") != "primary":
                raise SystemExit("dataset/series/role mismatch")
            if row.get("source_observation_id") != record["obs_id"] or row.get("source_field") != f"EVENTS.{field}":
                raise SystemExit("source observation/field mismatch")
            if row.get("numeric_kind") != "uint" or row.get("bit_width") != 8 or row.get("endianness") != "little" or row.get("element_size_bytes") != 1:
                raise SystemExit("numeric schema mismatch")
            if row.get("value_count") != len(payload) or row.get("sample_shape") != [len(payload)]:
                raise SystemExit("sample length mismatch")
            output = args.data_root / row["sample_path"]
            if not output.is_file() or output.read_bytes() != payload:
                raise SystemExit(f"output differs from fresh FITS parse: {output}")
            if row.get("sha256") != hashlib.sha256(payload).hexdigest():
                raise SystemExit(f"indexed hash mismatch: {output}")
            expected_outputs.add(output.resolve())
    actual_outputs = {path.resolve() for path in (args.data_root / "samples" / DATASET_ID).glob("*/*.bin")}
    if actual_outputs != expected_outputs:
        raise SystemExit("sample directory contains missing, stale, or extra outputs")
    expected_summary = make_summary(records, excluded)
    if json.loads(args.stats.read_text(encoding="utf-8")) != expected_summary:
        raise SystemExit("ingest stats differ from fresh FITS parse")
    print(json.dumps({
        "dataset_id": DATASET_ID,
        "verified_observations": len(records),
        "verified_samples": len(rows),
        "verified_values": expected_summary["primary_value_count"],
        "verified_bytes": expected_summary["primary_size_bytes"],
    }, indent=2, sort_keys=True))


def main() -> None:
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    pre = commands.add_parser("preflight")
    pre.add_argument("--sources", type=Path, required=True)
    pre.add_argument("--download-dir", type=Path, required=True)
    pre.add_argument("--profile", type=Path, required=True)
    for command in ("build", "verify"):
        sub = commands.add_parser(command)
        sub.add_argument("--sources", type=Path, required=True)
        sub.add_argument("--download-dir", type=Path, required=True)
        sub.add_argument("--index", type=Path, required=True)
        sub.add_argument("--stats", type=Path, required=True)
        sub.add_argument("--data-root", type=Path, required=True)
        if command == "build":
            sub.add_argument("--samples-dir", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "preflight":
        preflight(args)
    elif args.command == "build":
        build(args)
    else:
        verify(args)


if __name__ == "__main__":
    main()
