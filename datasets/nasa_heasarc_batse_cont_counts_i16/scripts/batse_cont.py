#!/usr/bin/env python3
"""Decode CGRO BATSE CONT daily FITS files to little-endian int16 COUNTS samples.

Pure standard library: gzip, array, struct. The FITS header walker locates the
BATSE_CNTS binary table by EXTNAME (never by a hard-coded data offset),
validates the full 13-column schema, and copies the COUNTS column (TFORM 128I,
TDIM (8,16): detector axis fastest) of every row in native row order.

verify_cont.py is a separate, independent implementation used by verify.sh.
"""
from __future__ import annotations

import argparse
import collections
import csv
import gzip
import hashlib
import io
import json
import re
import statistics
import struct
import sys
from array import array
from pathlib import Path
from typing import Callable

DATASET_ID = "nasa_heasarc_batse_cont_counts_i16"
SERIES_ID = "batse_lad_cont_counts_i16"
NATURAL_RECORD_KIND = "batse_cont_daily_file_counts_table"
FITS_BLOCK = 2_880
ROW_BYTES = 336
COUNTS_OFFSET = 28
COUNTS_VALUES = 128
COUNTS_BYTES = COUNTS_VALUES * 2
N_DET = 8
N_CHAN = 16
ROW_FLOOR = 20_000
ROW_CHUNK = 4_096
SPIKE_THRESHOLD = 4_096
MIN_DISTINCT = 256
MAX_REPEATED_ROW_FRACTION = 0.05
EXPECTED_COLUMNS = [
    ("MID_TIME", "1D"),
    ("X_POS", "1E"),
    ("Y_POS", "1E"),
    ("Z_POS", "1E"),
    ("GEO_AZ", "1E"),
    ("GEO_EL", "1E"),
    ("COUNTS", "128I"),
    ("DEADTIME", "8E"),
    ("FLAGS", "4B"),
    ("Z_RA", "1E"),
    ("Z_DEC", "1E"),
    ("X_RA", "1E"),
    ("X_DEC", "1E"),
]
TFORM_WIDTHS = {"L": 1, "B": 1, "I": 2, "J": 4, "K": 8, "A": 1, "E": 4, "D": 8, "C": 8, "M": 16}
MID_TIME = struct.Struct(">d")


class Truncated(ValueError):
    """Raised when a (partial) stream ends inside a header or table."""


# ---------------------------------------------------------------- FITS header


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


def read_header(read: Callable[[int], bytes]) -> dict[str, object] | None:
    """Read one FITS header; return None at a clean end of stream."""
    cards: list[str] = []
    for block_index in range(200):
        block = read(FITS_BLOCK)
        if block_index == 0 and not block:
            return None
        if len(block) != FITS_BLOCK:
            raise Truncated("truncated FITS header block")
        for offset in range(0, FITS_BLOCK, 80):
            card = block[offset:offset + 80].decode("ascii", "strict")
            cards.append(card)
            if card[:8].rstrip() == "END":
                values: dict[str, object] = {}
                comments: list[str] = []
                for item in cards:
                    key = item[:8].strip()
                    if key == "COMMENT":
                        comments.append(item[8:].strip())
                    elif key and item[8:10] == "= ":
                        if key in values:
                            raise ValueError(f"duplicate FITS keyword {key}")
                        values[key] = parse_value(item)
                values["_comments"] = comments
                return values
    raise ValueError("FITS header has no END card")


def hdu_data_bytes(header: dict[str, object]) -> int:
    naxis = int(header.get("NAXIS", 0))
    if naxis == 0:
        return 0
    element = abs(int(header["BITPIX"])) // 8
    count = 1
    for axis in range(1, naxis + 1):
        count *= int(header[f"NAXIS{axis}"])
    return element * int(header.get("GCOUNT", 1)) * (count + int(header.get("PCOUNT", 0)))


def padded(size: int) -> int:
    return (size + FITS_BLOCK - 1) // FITS_BLOCK * FITS_BLOCK


def tform_width(tform: str) -> int:
    match = re.fullmatch(r"(\d*)([LBIJKAEDCMX])", tform.replace(" ", "").upper())
    if not match:
        raise ValueError(f"unsupported TFORM {tform!r}")
    repeat = int(match.group(1) or "1")
    if match.group(2) == "X":
        return (repeat + 7) // 8
    return repeat * TFORM_WIDTHS[match.group(2)]


def validate_primary(header: dict[str, object], tjd: int) -> None:
    expected = {
        "SIMPLE": True,
        "NAXIS": 0,
        "TELESCOP": "COMPTON GRO",
        "INSTRUME": "BATSE",
        "FILETYPE": "BATSE_CONT",
        "TJD": tjd,
        "N_E_CHAN": N_CHAN,
    }
    for key, value in expected.items():
        if header.get(key) != value:
            raise ValueError(f"primary {key}={header.get(key)!r}, expected {value!r}")
    if abs(float(header.get("TIME_RES", 0.0)) - 2.048) > 1e-9:
        raise ValueError(f"primary TIME_RES={header.get('TIME_RES')!r}")


def validate_counts_table(header: dict[str, object]) -> int:
    """Validate the BATSE_CNTS schema and return its row count."""
    if header.get("XTENSION") != "BINTABLE" or header.get("BITPIX") != 8 or header.get("NAXIS") != 2:
        raise ValueError("BATSE_CNTS is not a byte BINTABLE")
    if header.get("NAXIS1") != ROW_BYTES:
        raise ValueError(f"BATSE_CNTS NAXIS1={header.get('NAXIS1')!r}")
    if header.get("PCOUNT", 0) != 0 or header.get("GCOUNT", 1) != 1:
        raise ValueError("BATSE_CNTS has heap or groups")
    if header.get("TFIELDS") != len(EXPECTED_COLUMNS):
        raise ValueError(f"BATSE_CNTS TFIELDS={header.get('TFIELDS')!r}")
    offset = 0
    counts_offset = -1
    for index, (name, tform) in enumerate(EXPECTED_COLUMNS, 1):
        if str(header.get(f"TTYPE{index}", "")).strip() != name:
            raise ValueError(f"TTYPE{index}={header.get(f'TTYPE{index}')!r}, expected {name}")
        actual = str(header.get(f"TFORM{index}", "")).replace(" ", "").upper()
        if actual != tform:
            raise ValueError(f"TFORM{index}={actual!r}, expected {tform}")
        if name == "COUNTS":
            counts_offset = offset
        offset += tform_width(actual)
    if offset != ROW_BYTES or counts_offset != COUNTS_OFFSET:
        raise ValueError(f"column layout changed: row={offset} counts_offset={counts_offset}")
    if str(header.get("TDIM7", "")).replace(" ", "") != "(8,16)":
        raise ValueError(f"TDIM7={header.get('TDIM7')!r}")
    if str(header.get("TUNIT7", "")).strip() != "COUNTS":
        raise ValueError(f"TUNIT7={header.get('TUNIT7')!r}")
    for key in ("TZERO7", "TSCAL7", "TNULL7"):
        if key in header:
            raise ValueError(f"unexpected {key} on COUNTS")
    rows = int(header.get("NAXIS2", -1))
    if rows < 0:
        raise ValueError("negative NAXIS2")
    return rows


def locate_counts(read: Callable[[int], bytes], skip: Callable[[int], None], tjd: int) -> dict[str, object]:
    """Walk HDUs to BATSE_CNTS by EXTNAME; leave the stream at its data start."""
    primary = read_header(read)
    if primary is None:
        raise Truncated("empty FITS stream")
    validate_primary(primary, tjd)
    skip(padded(hdu_data_bytes(primary)))
    extnames: list[str] = []
    calib_rows = None
    for _ in range(16):
        header = read_header(read)
        if header is None:
            break
        extname = str(header.get("EXTNAME", "")).strip()
        extnames.append(extname)
        if extname == "BATSE_E_CALIB":
            calib_rows = int(header.get("NAXIS2", 0))
        if extname == "BATSE_CNTS":
            return {
                "rows": validate_counts_table(header),
                "extnames_before": extnames[:-1],
                "calib_rows": calib_rows,
                "strt_day": str(primary.get("STRT-DAY", "")),
            }
        skip(padded(hdu_data_bytes(header)))
    raise ValueError(f"no BATSE_CNTS extension (saw {extnames})")


def probe_bytes(decompressed_prefix: bytes, tjd: int) -> dict[str, object]:
    """Header probe on a decompressed file prefix (used by select_days.py)."""
    stream = io.BytesIO(decompressed_prefix)

    def skip(count: int) -> None:
        if stream.tell() + count > len(decompressed_prefix):
            raise Truncated("prefix ends inside HDU data")
        stream.seek(count, 1)

    return locate_counts(stream.read, skip, tjd)


# ---------------------------------------------------------------- decode


def check_trailing_hdus(read: Callable[[int], bytes], rows: int) -> int:
    """Only header-only RUN_LOG extensions may follow BATSE_CNTS.

    Some 1994-processed files end with an empty ASCII TABLE extension
    (EXTNAME RUN_LOG, NAXIS 0) whose COMMENT cards log the FITS writer run,
    e.g. '37379 rows of CONTINUOUS data written.'; that count must equal NAXIS2.
    """
    found = 0
    while True:
        header = read_header(read)
        if header is None:
            return found
        if str(header.get("EXTNAME", "")).strip() != "RUN_LOG" or hdu_data_bytes(header) != 0:
            raise ValueError(f"unexpected HDU after BATSE_CNTS: EXTNAME={header.get('EXTNAME')!r}")
        reported = [
            int(match.group(1))
            for comment in header["_comments"]
            for match in [re.search(r"(\d+) rows of CONTINUOUS data written", comment)]
            if match
        ]
        if reported and reported != [rows]:
            raise ValueError(f"RUN_LOG reports {reported} CONTINUOUS rows, table has {rows}")
        found += 1


def decode_file(path: Path, tjd: int, output: Path | None) -> dict[str, object]:
    histogram: collections.Counter = collections.Counter()
    digest = hashlib.sha256()
    repeated_rows = 0
    previous_counts = None
    mid_first = mid_last = None
    mid_backsteps = 0
    with gzip.open(path, "rb") as handle:
        def skip(count: int) -> None:
            if count and len(handle.read(count)) != count:
                raise Truncated("truncated HDU data")

        info = locate_counts(handle.read, skip, tjd)
        if info["extnames_before"] != ["BATSE_E_CALIB"]:
            raise ValueError(f"unexpected HDUs before BATSE_CNTS: {info['extnames_before']}")
        rows = int(info["rows"])
        out = output.open("wb") if output else None
        try:
            done = 0
            while done < rows:
                count = min(ROW_CHUNK, rows - done)
                block = handle.read(count * ROW_BYTES)
                if len(block) != count * ROW_BYTES:
                    raise Truncated("truncated BATSE_CNTS table")
                parts = []
                for row in range(count):
                    base = row * ROW_BYTES
                    counts = block[base + COUNTS_OFFSET:base + COUNTS_OFFSET + COUNTS_BYTES]
                    if counts == previous_counts:
                        repeated_rows += 1
                    previous_counts = counts
                    parts.append(counts)
                    (mid,) = MID_TIME.unpack_from(block, base)
                    if mid_first is None:
                        mid_first = mid
                    elif mid <= mid_last:
                        mid_backsteps += 1
                    mid_last = mid
                values = array("h")
                values.frombytes(b"".join(parts))
                if sys.byteorder == "little":
                    values.byteswap()  # FITS big-endian -> host little-endian values
                    encoded = values.tobytes()
                else:
                    swapped = array("h", values)
                    swapped.byteswap()
                    encoded = swapped.tobytes()
                histogram.update(values)
                digest.update(encoded)
                if out:
                    out.write(encoded)
                done += count
            expected_padding = padded(rows * ROW_BYTES) - rows * ROW_BYTES
            padding = handle.read(expected_padding)
            if len(padding) != expected_padding or padding.strip(b"\x00"):
                raise ValueError("BATSE_CNTS data padding is not zero-filled")
            run_log_hdus = check_trailing_hdus(handle.read, rows)
        finally:
            if out:
                out.close()
    value_count = rows * COUNTS_VALUES
    if sum(histogram.values()) != value_count:
        raise ValueError("histogram does not cover every value")
    return {
        "rows": rows,
        "value_count": value_count,
        "minimum": min(histogram),
        "maximum": max(histogram),
        "distinct_values": len(histogram),
        "negative_count": sum(n for v, n in histogram.items() if v < 0),
        "zero_count": histogram.get(0, 0),
        "spike_count": sum(n for v, n in histogram.items() if v >= SPIKE_THRESHOLD),
        "repeated_rows": repeated_rows,
        "mid_time_first_tjd": mid_first,
        "mid_time_last_tjd": mid_last,
        "mid_time_nonincreasing_steps": mid_backsteps,
        "calib_rows": info["calib_rows"],
        "strt_day": info["strt_day"],
        "trailing_run_log_hdus": run_log_hdus,
        "sha256": digest.hexdigest(),
    }


def check_nondegenerate(tjd: int, result: dict[str, object]) -> None:
    if int(result["rows"]) < ROW_FLOOR:
        raise ValueError(f"TJD {tjd}: {result['rows']} rows below floor {ROW_FLOOR}")
    if int(result["minimum"]) >= int(result["maximum"]):
        raise ValueError(f"TJD {tjd}: constant COUNTS")
    if int(result["distinct_values"]) < MIN_DISTINCT:
        raise ValueError(f"TJD {tjd}: only {result['distinct_values']} distinct values")
    if int(result["repeated_rows"]) > MAX_REPEATED_ROW_FRACTION * int(result["rows"]):
        raise ValueError(f"TJD {tjd}: {result['repeated_rows']} rows repeat their predecessor")


# ---------------------------------------------------------------- build


def read_sources(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build(args: argparse.Namespace) -> None:
    sources = read_sources(args.sources)
    inventory = json.loads((args.download_dir / "download_inventory.json").read_text(encoding="utf-8"))
    by_tjd = {int(record["tjd"]): record for record in inventory["records"]}
    if sorted(by_tjd) != sorted(int(row["tjd"]) for row in sources):
        raise SystemExit("download inventory does not match sources.tsv")
    args.samples_dir.mkdir(parents=True, exist_ok=True)
    for stale in args.samples_dir.glob("*.bin"):
        stale.unlink()
    entries = []
    details = []
    for row in sorted(sources, key=lambda item: int(item["tjd"])):
        tjd = int(row["tjd"])
        source = args.download_dir / Path(row["key"]).name
        record = by_tjd[tjd]
        if source.stat().st_size != int(row["bytes"]) or sha256_file(source) != record["sha256"]:
            raise SystemExit(f"TJD {tjd}: source differs from download inventory")
        if row.get("sha256") and row["sha256"] != record["sha256"]:
            raise SystemExit(f"TJD {tjd}: source SHA-256 differs from sources.tsv pin")
        output = args.samples_dir / f"cont_{tjd:05d}_counts.bin"
        result = decode_file(source, tjd, output)
        if int(result["rows"]) != int(row["rows"]):
            raise SystemExit(f"TJD {tjd}: NAXIS2 {result['rows']} != pinned {row['rows']}")
        check_nondegenerate(tjd, result)
        size = output.stat().st_size
        if size != int(result["value_count"]) * 2:
            raise SystemExit(f"TJD {tjd}: output size mismatch")
        details.append({"tjd": tjd, "source_file": source.name, "source_sha256": record["sha256"], **result})
        entries.append({
            "dataset_id": DATASET_ID,
            "series_id": SERIES_ID,
            "role": "primary",
            "sample_path": output.relative_to(args.data_root).as_posix(),
            "numeric_kind": "int",
            "bit_width": 16,
            "endianness": "little",
            "element_size_bytes": 2,
            "sample_size_bytes": size,
            "value_count": result["value_count"],
            "sample_rank": 3,
            "sample_shape": [result["rows"], N_CHAN, N_DET],
            "sample_axes": ["cont_accumulation_2048ms", "energy_channel", "lad_detector"],
            "natural_record_kind": NATURAL_RECORD_KIND,
            "source_variable": "BATSE_CNTS.COUNTS",
            "source_file": source.name,
            "source_sha256": record["sha256"],
            "tjd": tjd,
            "strt_day": result["strt_day"],
            "minimum": result["minimum"],
            "maximum": result["maximum"],
            "distinct_values": result["distinct_values"],
            "negative_count": result["negative_count"],
            "spike_count": result["spike_count"],
            "zero_count": result["zero_count"],
            "sha256": result["sha256"],
        })
    hashes = [entry["sha256"] for entry in entries]
    if len(set(hashes)) != len(hashes):
        raise SystemExit("duplicate output samples")
    counts = [int(entry["value_count"]) for entry in entries]
    stats = {
        "dataset_id": DATASET_ID,
        "series_id": SERIES_ID,
        "samples": len(entries),
        "primary_values": sum(counts),
        "primary_bytes": sum(int(entry["sample_size_bytes"]) for entry in entries),
        "median_values_per_sample": statistics.median(counts),
        "min_values_per_sample": min(counts),
        "max_values_per_sample": max(counts),
        "global_minimum": min(int(entry["minimum"]) for entry in entries),
        "global_maximum": max(int(entry["maximum"]) for entry in entries),
        "total_negative_values": sum(int(entry["negative_count"]) for entry in entries),
        "total_spike_values_ge_4096": sum(int(entry["spike_count"]) for entry in entries),
        "total_zero_values": sum(int(entry["zero_count"]) for entry in entries),
        "row_floor": ROW_FLOOR,
        "records": details,
    }
    if stats["primary_bytes"] > 1_000_000_000:
        raise SystemExit("primary output exceeds 1 GB cap")
    args.index.parent.mkdir(parents=True, exist_ok=True)
    with args.index.open("w", encoding="utf-8") as handle:
        for entry in entries:
            handle.write(json.dumps(entry, sort_keys=True) + "\n")
    args.stats.parent.mkdir(parents=True, exist_ok=True)
    args.stats.write_text(json.dumps(stats, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        f"build samples={stats['samples']} primary_values={stats['primary_values']} "
        f"primary_bytes={stats['primary_bytes']} median_values={stats['median_values_per_sample']} "
        f"range={stats['global_minimum']}..{stats['global_maximum']} "
        f"negatives={stats['total_negative_values']} spikes={stats['total_spike_values_ge_4096']}"
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sources", type=Path, required=True)
    parser.add_argument("--download-dir", type=Path, required=True)
    parser.add_argument("--samples-dir", type=Path, required=True)
    parser.add_argument("--index", type=Path, required=True)
    parser.add_argument("--stats", type=Path, required=True)
    parser.add_argument("--data-root", type=Path, required=True)
    build(parser.parse_args())


if __name__ == "__main__":
    main()
