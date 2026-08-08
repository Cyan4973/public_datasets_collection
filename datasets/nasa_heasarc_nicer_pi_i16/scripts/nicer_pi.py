#!/usr/bin/env python3
"""Decode and verify native int16 NICER PI event columns without FITS dependencies."""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import math
from pathlib import Path
import re
import statistics


DATASET_ID = "nasa_heasarc_nicer_pi_i16"
SERIES_ID = "nicer_xray_pi_channel_i16"
EXPECTED_SOURCE_FILES = 36
EXPECTED_SOURCE_BYTES = 205_174_726
MIN_ROWS = 1_000
NULL_VALUE = -32_768
FITS_BLOCK = 2_880
ROW_CHUNK = 16_384


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_value(card: str) -> object:
    raw = card[10:80].rstrip()
    if raw.startswith("'"):
        chars: list[str] = []
        position = 1
        while position < len(raw):
            if raw[position] == "'":
                if position + 1 < len(raw) and raw[position + 1] == "'":
                    chars.append("'")
                    position += 2
                    continue
                return "".join(chars).rstrip()
            chars.append(raw[position])
            position += 1
        raise ValueError("unterminated FITS string")
    token = raw.split("/", 1)[0].strip()
    if token == "T":
        return True
    if token == "F":
        return False
    if not token:
        return ""
    try:
        return int(token)
    except ValueError:
        try:
            return float(token.replace("D", "E"))
        except ValueError:
            return token


def read_header(handle: gzip.GzipFile) -> dict[str, object]:
    cards: list[str] = []
    found_end = False
    for _ in range(1_000):
        block = handle.read(FITS_BLOCK)
        if len(block) != FITS_BLOCK:
            raise ValueError("truncated FITS header block")
        for offset in range(0, FITS_BLOCK, 80):
            card = block[offset:offset + 80].decode("ascii", "strict")
            cards.append(card)
            if card[:8].strip() == "END":
                found_end = True
                break
        if found_end:
            break
    if not found_end:
        raise ValueError("FITS header has no END card")
    values: dict[str, object] = {}
    for card in cards:
        key = card[:8].strip()
        if key and card[8:10] == "= ":
            values[key] = parse_value(card)
    return values


def hdu_data_bytes(header: dict[str, object]) -> int:
    naxis = int(header.get("NAXIS", 0))
    axes = [int(header[f"NAXIS{i}"]) for i in range(1, naxis + 1)]
    if any(axis < 0 for axis in axes):
        raise ValueError("negative FITS axis")
    elements = math.prod(axes) if axes else 0
    pcount = int(header.get("PCOUNT", 0))
    gcount = int(header.get("GCOUNT", 1))
    bitpix = abs(int(header.get("BITPIX", 0)))
    if bitpix % 8:
        raise ValueError("non-byte-aligned FITS BITPIX")
    return (bitpix // 8) * gcount * (pcount + elements)


def padded(size: int) -> int:
    return ((size + FITS_BLOCK - 1) // FITS_BLOCK) * FITS_BLOCK


def tform_bytes(tform: str) -> int:
    normalized = re.sub(r"\s+", "", tform).upper()
    match = re.fullmatch(r"(\d*)([LXBIJKAEDCMPQ])(?:\([^)]*\))?", normalized)
    if not match:
        raise ValueError(f"unsupported FITS TFORM: {tform!r}")
    repeat = int(match.group(1) or "1")
    code = match.group(2)
    if repeat <= 0:
        raise ValueError(f"invalid FITS TFORM repeat: {tform!r}")
    widths = {
        "L": 1, "B": 1, "I": 2, "J": 4, "K": 8, "A": 1,
        "E": 4, "D": 8, "C": 8, "M": 16, "P": 8, "Q": 16,
    }
    if code == "X":
        return (repeat + 7) // 8
    return repeat * widths[code]


def table_columns(header: dict[str, object]) -> tuple[dict[str, dict[str, object]], int]:
    fields = int(header.get("TFIELDS", 0))
    columns: dict[str, dict[str, object]] = {}
    offset = 0
    for index in range(1, fields + 1):
        name = str(header.get(f"TTYPE{index}", "")).strip()
        tform = str(header.get(f"TFORM{index}", "")).strip()
        width = tform_bytes(tform)
        if name:
            columns[name.upper()] = {
                "index": index,
                "name": name,
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


def write_or_compare(
    handle: gzip.GzipFile,
    *,
    row_bytes: int,
    rows: int,
    column_offset: int,
    output_path: Path | None,
    expected_path: Path | None,
) -> dict[str, object]:
    output = output_path.open("wb") if output_path else None
    expected = expected_path.open("rb") if expected_path else None
    digest = hashlib.sha256()
    minimum = 32_767
    maximum = -32_768
    valid_minimum = 32_767
    valid_maximum = -32_768
    null_count = 0
    zero_count = 0
    transition_count = 0
    previous: int | None = None
    distinct: set[int] = set()
    processed = 0
    try:
        while processed < rows:
            count = min(ROW_CHUNK, rows - processed)
            block = handle.read(count * row_bytes)
            if len(block) != count * row_bytes:
                raise ValueError("truncated FITS event table")
            encoded = bytearray(count * 2)
            for row in range(count):
                position = row * row_bytes + column_offset
                word = int.from_bytes(block[position:position + 2], "big", signed=True)
                unsigned = word & 0xFFFF
                encoded[2 * row] = unsigned & 0xFF
                encoded[2 * row + 1] = unsigned >> 8
                minimum = min(minimum, word)
                maximum = max(maximum, word)
                distinct.add(word)
                if word == NULL_VALUE:
                    null_count += 1
                else:
                    valid_minimum = min(valid_minimum, word)
                    valid_maximum = max(valid_maximum, word)
                if word == 0:
                    zero_count += 1
                if previous is not None and word != previous:
                    transition_count += 1
                previous = word
            if output:
                output.write(encoded)
            if expected:
                actual = expected.read(len(encoded))
                if actual != encoded:
                    raise ValueError("emitted PI sample differs from source table")
            digest.update(encoded)
            processed += count
        if expected and expected.read(1):
            raise ValueError("emitted PI sample has trailing bytes")
    finally:
        if output:
            output.close()
        if expected:
            expected.close()
    valid_count = rows - null_count
    if valid_count <= 0 or valid_minimum >= valid_maximum or transition_count == 0:
        raise ValueError("PI sequence has no nondegenerate valid signal")
    return {
        "distinct_values": len(distinct),
        "maximum": maximum,
        "minimum": minimum,
        "null_count": null_count,
        "sha256": digest.hexdigest(),
        "transition_count": transition_count,
        "valid_count": valid_count,
        "valid_maximum": valid_maximum,
        "valid_minimum": valid_minimum,
        "value_count": rows,
        "zero_count": zero_count,
    }


def decode_source(
    source_path: Path,
    *,
    expected_obs_id: str,
    output_path: Path | None,
    expected_path: Path | None,
) -> dict[str, object]:
    primary: dict[str, object] | None = None
    with gzip.open(source_path, "rb") as handle:
        for hdu_index in range(32):
            header = read_header(handle)
            if hdu_index == 0:
                primary = header
                if str(header.get("TELESCOP", "")).strip() != "NICER":
                    raise ValueError("primary HDU is not NICER")
                if str(header.get("INSTRUME", "")).strip() != "XTI":
                    raise ValueError("primary HDU is not XTI")
                if str(header.get("OBS_ID", "")).strip() != expected_obs_id:
                    raise ValueError("primary OBS_ID differs from pinned source")
            xtension = str(header.get("XTENSION", "")).strip().upper()
            if xtension == "BINTABLE":
                columns, declared_row_bytes = table_columns(header)
                row_bytes = int(header.get("NAXIS1", 0))
                rows = int(header.get("NAXIS2", 0))
                if declared_row_bytes != row_bytes:
                    raise ValueError("FITS column widths do not equal NAXIS1")
                if "PI" in columns:
                    pi = columns["PI"]
                    normalized = re.sub(r"\s+", "", str(pi["tform"])).upper()
                    if normalized not in {"I", "1I"} or int(pi["width"]) != 2:
                        raise ValueError("PI is not a scalar signed-int16 FITS column")
                    if pi["tscal"] != 1 or pi["tzero"] != 0:
                        raise ValueError("PI does not have identity scaling")
                    if pi["tnull"] != NULL_VALUE or str(pi["tunit"]).strip() != "chan":
                        raise ValueError("PI null sentinel or unit changed")
                    if str(header.get("EXTNAME", "")).strip() != "EVENTS":
                        raise ValueError("PI column is not in EVENTS extension")
                    if rows < 0 or row_bytes <= 0:
                        raise ValueError("invalid EVENTS table geometry")
                    result: dict[str, object] = {
                        "date_end": str(header.get("DATE-END", primary.get("DATE-END", "") if primary else "")),
                        "date_obs": str(header.get("DATE-OBS", primary.get("DATE-OBS", "") if primary else "")),
                        "hdu_index": hdu_index,
                        "object": str(header.get("OBJECT", primary.get("OBJECT", "") if primary else "")),
                        "pi_column_index": int(pi["index"]),
                        "pi_column_offset": int(pi["offset"]),
                        "row_bytes": row_bytes,
                        "rows": rows,
                    }
                    if rows >= MIN_ROWS:
                        result.update(write_or_compare(
                            handle,
                            row_bytes=row_bytes,
                            rows=rows,
                            column_offset=int(pi["offset"]),
                            output_path=output_path,
                            expected_path=expected_path,
                        ))
                        result["selected"] = True
                    else:
                        handle.seek(rows * row_bytes, 1)
                        result["selected"] = False
                    return result
            size = hdu_data_bytes(header)
            if size:
                handle.seek(padded(size), 1)
    raise ValueError("no native-int16 PI EVENTS column found")


def load_inventory(download_dir: Path) -> list[dict[str, object]]:
    inventory_path = download_dir / "download_inventory.json"
    payload = json.loads(inventory_path.read_text(encoding="utf-8"))
    records = payload.get("records", [])
    if not isinstance(records, list) or len(records) != EXPECTED_SOURCE_FILES:
        raise SystemExit("download inventory source count changed")
    if int(payload.get("source_bytes", 0)) != EXPECTED_SOURCE_BYTES:
        raise SystemExit("download inventory aggregate size changed")
    obs_ids = {str(record.get("obs_id", "")) for record in records}
    if len(obs_ids) != len(records):
        raise SystemExit("duplicate source observation ID")
    for record in records:
        path = download_dir / str(record["filename"])
        if path.stat().st_size != int(record["bytes"]):
            raise SystemExit(f"source size mismatch: {path.name}")
        if sha256_file(path) != record["sha256"]:
            raise SystemExit(f"source SHA256 mismatch: {path.name}")
    return sorted(records, key=lambda record: str(record["obs_id"]))


def collect(
    *,
    mode: str,
    download_dir: Path,
    samples_dir: Path,
    data_root: Path,
) -> tuple[list[dict[str, object]], dict[str, object]]:
    records = load_inventory(download_dir)
    entries: list[dict[str, object]] = []
    details: list[dict[str, object]] = []
    output_hashes: set[str] = set()
    for record in records:
        obs_id = str(record["obs_id"])
        source = download_dir / str(record["filename"])
        output = samples_dir / f"{obs_id}_pi.bin"
        result = decode_source(
            source,
            expected_obs_id=obs_id,
            output_path=output if mode == "build" else None,
            expected_path=output if mode == "verify" else None,
        )
        detail = {
            "date_end": result["date_end"],
            "date_obs": result["date_obs"],
            "object": result["object"],
            "obs_id": obs_id,
            "rows": result["rows"],
            "selected": result["selected"],
            "source_bytes": record["bytes"],
            "source_file": record["filename"],
            "source_sha256": record["sha256"],
        }
        if not result["selected"]:
            details.append(detail)
            continue
        digest = str(result["sha256"])
        if digest in output_hashes:
            raise SystemExit(f"duplicate complete PI sample: {obs_id}")
        output_hashes.add(digest)
        detail.update({
            key: result[key] for key in (
                "distinct_values", "maximum", "minimum", "null_count", "sha256",
                "transition_count", "valid_count", "valid_maximum", "valid_minimum",
                "value_count", "zero_count",
            )
        })
        details.append(detail)
        sample_size = int(result["value_count"]) * 2
        entries.append({
            "bit_width": 16,
            "dataset_id": DATASET_ID,
            "distinct_values": result["distinct_values"],
            "element_size_bytes": 2,
            "endianness": "little",
            "maximum": result["maximum"],
            "minimum": result["minimum"],
            "natural_record_kind": "complete_nicer_cleaned_observation_pi_event_sequence",
            "null_count": result["null_count"],
            "null_value": NULL_VALUE,
            "numeric_kind": "int",
            "object": result["object"],
            "obs_id": obs_id,
            "role": "primary",
            "sample_axes": ["photon_event"],
            "sample_format": "raw homogeneous little-endian signed-int16 PI channel array",
            "sample_geometry": "variable_length_xray_photon_event_channel_1d",
            "sample_path": output.relative_to(data_root).as_posix(),
            "sample_rank": 1,
            "sample_shape": [result["value_count"]],
            "sample_size_bytes": sample_size,
            "semantic_field": "pulse_invariant_xray_energy_channel",
            "series_id": SERIES_ID,
            "sha256": digest,
            "source_sample": source.relative_to(data_root).as_posix(),
            "source_variable": "EVENTS.PI",
            "transition_count": result["transition_count"],
            "valid_count": result["valid_count"],
            "value_count": result["value_count"],
            "zero_count": result["zero_count"],
        })
    expected_names = {f"{entry['obs_id']}_pi.bin" for entry in entries}
    actual_names = {path.name for path in samples_dir.glob("*.bin")}
    if actual_names != expected_names:
        raise SystemExit("sample directory differs from selected observation inventory")
    counts = [int(entry["value_count"]) for entry in entries]
    if not entries or statistics.median(counts) < MIN_ROWS:
        raise SystemExit("selected PI family does not meet median sample floor")
    stats: dict[str, object] = {
        "candidate_id": DATASET_ID,
        "global_maximum": max(int(entry["maximum"]) for entry in entries),
        "global_minimum": min(int(entry["minimum"]) for entry in entries),
        "maximum_values_per_observation": max(counts),
        "median_values_per_observation": int(statistics.median(counts)),
        "minimum_rows": MIN_ROWS,
        "minimum_values_per_observation": min(counts),
        "null_value": NULL_VALUE,
        "primary_bytes": sum(int(entry["sample_size_bytes"]) for entry in entries),
        "primary_values": sum(counts),
        "records": details,
        "selected_observations": len(entries),
        "series_id": SERIES_ID,
        "skipped_below_minimum_rows": len(records) - len(entries),
        "source_bytes": sum(int(record["bytes"]) for record in records),
        "source_files": len(records),
        "total_null_count": sum(int(entry["null_count"]) for entry in entries),
        "total_transition_count": sum(int(entry["transition_count"]) for entry in entries),
        "unique_objects": len({str(entry["object"]) for entry in entries}),
    }
    if int(stats["primary_values"]) < 10_000 or int(stats["primary_bytes"]) > 1_000_000_000:
        raise SystemExit("selected PI family violates aggregate acceptance bounds")
    return entries, stats


def write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")
    temporary.replace(path)


def write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def read_jsonl(path: Path) -> list[dict[str, object]]:
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("build", "verify"))
    parser.add_argument("--download-dir", type=Path, required=True)
    parser.add_argument("--samples-dir", type=Path, required=True)
    parser.add_argument("--index", type=Path, required=True)
    parser.add_argument("--stats", type=Path, required=True)
    parser.add_argument("--data-root", type=Path, required=True)
    args = parser.parse_args()

    if args.mode == "build":
        if args.samples_dir.exists():
            for path in args.samples_dir.glob("*.bin"):
                path.unlink()
        args.samples_dir.mkdir(parents=True, exist_ok=True)
    elif not args.samples_dir.is_dir():
        raise SystemExit("missing built sample directory")

    entries, stats = collect(
        mode=args.mode,
        download_dir=args.download_dir,
        samples_dir=args.samples_dir,
        data_root=args.data_root,
    )
    if args.mode == "build":
        write_jsonl(args.index, entries)
        write_json(args.stats, stats)
    else:
        if read_jsonl(args.index) != entries:
            raise SystemExit("sample index differs from independently decoded source")
        if json.loads(args.stats.read_text(encoding="utf-8")) != stats:
            raise SystemExit("ingest stats differ from independently decoded source")
    print(
        f"mode={args.mode} samples={stats['selected_observations']} "
        f"primary_values={stats['primary_values']} primary_bytes={stats['primary_bytes']} "
        f"median_values={stats['median_values_per_observation']} "
        f"skipped={stats['skipped_below_minimum_rows']}"
    )


if __name__ == "__main__":
    main()
