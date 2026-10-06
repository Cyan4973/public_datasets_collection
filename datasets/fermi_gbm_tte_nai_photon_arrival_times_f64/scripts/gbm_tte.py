#!/usr/bin/env python3
"""Decode Fermi GBM burst TTE (time-tagged event) NaI FITS files to float64 samples.

Pure standard library (array, struct, hashlib). The FITS walker reads 80-char
header cards in 2880-byte blocks, locates the EVENTS binary table by EXTNAME
(never by position or a hard-coded offset), validates its two-column schema
(TIME 1D with TZERO1 = TRIGTIME, PHA 1I, NAXIS1 = 10), and copies the stored
8-byte TIME field of every row in source order, byte-swapped from FITS
big-endian to little-endian. TZERO1 is NOT added: the emitted values are the
stored D values (seconds relative to the trigger time); physical
MET = stored + TZERO1, which is recorded per sample as metadata only.

Every HDU's FITS CHECKSUM (header + data ones'-complement sum = -0) and
DATASUM (data-unit ones'-complement sum) are verified when present.

verify_tte.py is a separate, independent implementation used by verify.sh.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import re
import statistics
import struct
import sys
from array import array
from pathlib import Path
from typing import Callable

DATASET_ID = "fermi_gbm_tte_nai_photon_arrival_times_f64"
SERIES_ID = "gbm_nai_tte_photon_time_f64"
NATURAL_RECORD_KIND = "gbm_burst_tte_file_nai_detector_event_time_column"
FITS_BLOCK = 2_880
ROW_BYTES = 10
ROW_CHUNK = 65_536
ROW_FLOOR = 100_000
DETCHANS = 128
# Plausible burst-TTE window relative to the trigger (seconds). Observed:
# about -36 s .. +300 s before the Nov 2012 flight-software change, about
# -135 s .. +480 s after; bounds are generous sanity limits.
FIRST_MIN, FIRST_MAX = -400.0, 0.0
LAST_MIN, LAST_MAX = 0.0, 2_000.0
MIN_CHANGES = 10_000
# Source-order policy: TIME is emitted in stored row order, never sorted. A
# few early-mission files contain an interleaved run of events whose times
# step back once by ~0.1 s; at most MAX_BACKSTEPS such steps per file, each at
# most MAX_BACKSTEP_S, are tolerated and recorded; anything more is fatal.
MAX_BACKSTEPS = 4
MAX_BACKSTEP_S = 1.0
EXPECTED_HDUS = ["PRIMARY", "EBOUNDS", "EVENTS", "GTI"]
DETECTORS = "0123456789ab"
ROW = struct.Struct(">dh")


class Truncated(ValueError):
    """Raised when a (partial) stream ends inside a header or table."""


# ---------------------------------------------------------------- checksums


def ones_complement_sum(data: bytes, start: int = 0) -> int:
    """FITS 32-bit ones'-complement sum of big-endian words (len % 4 == 0)."""
    if len(data) % 4:
        raise ValueError("checksum input not word aligned")
    words = array("I")
    if words.itemsize != 4:
        words = array("L")
        if words.itemsize != 4:
            raise RuntimeError("no 32-bit array type")
    words.frombytes(data)
    if sys.byteorder == "little":
        words.byteswap()
    total = start + sum(words)
    while total >> 32:
        total = (total & 0xFFFFFFFF) + (total >> 32)
    return total


def fold(total: int) -> int:
    while total >> 32:
        total = (total & 0xFFFFFFFF) + (total >> 32)
    return total


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


def read_header(read: Callable[[int], bytes]) -> tuple[dict[str, object], bytes] | None:
    """Read one FITS header; return (values, raw header bytes) or None at EOF."""
    cards: list[str] = []
    raw = bytearray()
    for block_index in range(64):
        block = read(FITS_BLOCK)
        if block_index == 0 and not block:
            return None
        if len(block) != FITS_BLOCK:
            raise Truncated("truncated FITS header block")
        raw += block
        for offset in range(0, FITS_BLOCK, 80):
            card = block[offset:offset + 80].decode("ascii", "strict")
            cards.append(card)
            if card[:8] == "END     ":
                values: dict[str, object] = {}
                for item in cards:
                    key = item[:8].strip()
                    if key and item[8:10] == "= ":
                        if key in values:
                            raise ValueError(f"duplicate FITS keyword {key}")
                        values[key] = parse_value(item)
                return values, bytes(raw)
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


def text(header: dict[str, object], key: str) -> str:
    return str(header.get(key, "")).strip()


def detector_name(detector: str) -> str:
    """'n0'..'n9','na','nb' -> FITS DETNAM 'NAI_00'..'NAI_11'."""
    if len(detector) != 2 or detector[0] != "n" or detector[1] not in DETECTORS:
        raise ValueError(f"not a NaI detector code: {detector!r}")
    return f"NAI_{DETECTORS.index(detector[1]):02d}"


def validate_primary(header: dict[str, object], filename: str, detector: str) -> None:
    expected = {
        "SIMPLE": True,
        "NAXIS": 0,
        "TELESCOP": "GLAST",
        "INSTRUME": "GBM",
        "DATATYPE": "TTE",
        "FILETYPE": "GBM PHOTON LIST",
        "DETNAM": detector_name(detector),
        "FILENAME": filename,
    }
    for key, value in expected.items():
        actual = header.get(key)
        if isinstance(value, str):
            actual = text(header, key)
        if actual != value:
            raise ValueError(f"{filename}: primary {key}={header.get(key)!r}, expected {value!r}")
    if not isinstance(header.get("TRIGTIME"), float):
        raise ValueError(f"{filename}: primary TRIGTIME missing or not a float")


def validate_events(header: dict[str, object], primary: dict[str, object], filename: str) -> dict[str, object]:
    """Validate the EVENTS schema; return rows and time metadata."""
    expected = {
        "XTENSION": "BINTABLE",
        "BITPIX": 8,
        "NAXIS": 2,
        "NAXIS1": ROW_BYTES,
        "PCOUNT": 0,
        "GCOUNT": 1,
        "TFIELDS": 2,
        "TTYPE1": "TIME",
        "TFORM1": "1D",
        "TUNIT1": "s",
        "TTYPE2": "PHA",
        "TFORM2": "1I",
        "DETCHANS": DETCHANS,
    }
    for key, value in expected.items():
        actual = header.get(key)
        if isinstance(value, str):
            actual = text(header, key).replace(" ", "") if key.startswith("TFORM") else text(header, key)
        if actual != value:
            raise ValueError(f"{filename}: EVENTS {key}={header.get(key)!r}, expected {value!r}")
    for key in ("TSCAL1", "TNULL1", "TSCAL2", "TZERO2", "TDIM1", "TDIM2", "THEAP"):
        if key in header:
            raise ValueError(f"{filename}: unexpected EVENTS keyword {key}")
    tzero = header.get("TZERO1")
    if not isinstance(tzero, float) or tzero != primary.get("TRIGTIME") or tzero != header.get("TRIGTIME"):
        raise ValueError(f"{filename}: TZERO1={tzero!r} does not equal TRIGTIME={primary.get('TRIGTIME')!r}")
    rows = int(header["NAXIS2"])
    if rows < 0:
        raise ValueError(f"{filename}: negative NAXIS2")
    tstart = float(header["TSTART"])
    tstop = float(header["TSTOP"])
    return {
        "rows": rows,
        "tzero1": tzero,
        "tstart": tstart,
        "tstop": tstop,
        "tstart_rel": tstart - tzero,
        "tstop_rel": tstop - tzero,
        "has_datasum": "DATASUM" in header,
        "has_checksum": "CHECKSUM" in header,
    }


def locate_events(read: Callable[[int], bytes], skip: Callable[[int], None], filename: str,
                  detector: str) -> dict[str, object]:
    """Walk HDUs to EVENTS by EXTNAME; leave the stream at its data start."""
    found = read_header(read)
    if found is None:
        raise Truncated("empty FITS stream")
    primary, _ = found
    validate_primary(primary, filename, detector)
    skip(padded(hdu_data_bytes(primary)))
    extnames: list[str] = []
    for _ in range(8):
        found = read_header(read)
        if found is None:
            break
        header, _ = found
        extname = text(header, "EXTNAME")
        extnames.append(extname)
        if extname == "EVENTS":
            info = validate_events(header, primary, filename)
            info["extnames_before"] = extnames[:-1]
            info["object"] = text(primary, "OBJECT")
            info["creator"] = text(primary, "CREATOR")
            info["file_date"] = text(primary, "DATE")
            return info
        skip(padded(hdu_data_bytes(header)))
    raise ValueError(f"{filename}: no EVENTS extension (saw {extnames})")


def probe_bytes(prefix: bytes, filename: str, detector: str) -> dict[str, object]:
    """Header probe on a file prefix fetched by a range GET (select_bursts.py)."""
    stream = io.BytesIO(prefix)

    def skip(count: int) -> None:
        if stream.tell() + count > len(prefix):
            raise Truncated("prefix ends inside HDU data")
        stream.seek(count, 1)

    return locate_events(stream.read, skip, filename, detector)


# ---------------------------------------------------------------- full-file walk


def walk_file(path: Path, filename: str, detector: str, output: Path | None = None,
              decode: bool = True) -> dict[str, object]:
    """Validate the whole file and (optionally) decode/write the TIME column.

    Always (download validation and build): HDU sequence PRIMARY, EBOUNDS,
    EVENTS, GTI; primary identity; EVENTS schema; every present
    CHECKSUM/DATASUM (both are required on EVENTS); zero-filled data padding;
    no trailing bytes. With decode=True (build) the EVENTS rows are unpacked
    and the TIME column is written (see decode_events).
    """
    data = path.read_bytes()
    stream = io.BytesIO(data)
    names: list[str] = []
    checksums_verified = 0
    datasums_verified = 0
    events_integrity = set()
    primary: dict[str, object] | None = None
    events: dict[str, object] | None = None
    result: dict[str, object] = {}
    result_gti: dict[str, object] = {}
    while stream.tell() < len(data):
        found = read_header(stream.read)
        if found is None:
            break
        header, raw_header = found
        name = "PRIMARY" if primary is None else text(header, "EXTNAME")
        names.append(name)
        if primary is None:
            primary = header
            validate_primary(header, filename, detector)
        size = hdu_data_bytes(header)
        unit_start = stream.tell()
        unit = data[unit_start:unit_start + padded(size)]
        if len(unit) != padded(size):
            raise Truncated(f"{filename}: truncated data unit of {name}")
        if unit[size:].strip(b"\x00"):
            raise ValueError(f"{filename}: non-zero padding after {name} data")
        data_sum = ones_complement_sum(unit)
        if "DATASUM" in header:
            declared = int(str(header["DATASUM"]).strip())
            if declared != data_sum:
                raise ValueError(f"{filename}: {name} DATASUM {declared} != computed {data_sum}")
            datasums_verified += 1
            if name == "EVENTS":
                events_integrity.add("DATASUM")
        if "CHECKSUM" in header:
            total = fold(ones_complement_sum(raw_header) + data_sum)
            if total != 0xFFFFFFFF:
                raise ValueError(f"{filename}: {name} CHECKSUM does not verify (sum {total:#x})")
            checksums_verified += 1
            if name == "EVENTS":
                events_integrity.add("CHECKSUM")
        if name == "EVENTS":
            if events is not None:
                raise ValueError(f"{filename}: two EVENTS extensions")
            events = validate_events(header, primary, filename)
            if decode:
                result = decode_events(unit, events, filename, output)
        if name == "GTI":
            result_gti = parse_gti(header, unit, filename)
        stream.seek(unit_start + padded(size))
    if stream.tell() != len(data):
        raise ValueError(f"{filename}: trailing bytes after last HDU")
    if names != EXPECTED_HDUS:
        raise ValueError(f"{filename}: HDU sequence {names}, expected {EXPECTED_HDUS}")
    if events_integrity != {"CHECKSUM", "DATASUM"}:
        raise ValueError(f"{filename}: EVENTS lacks CHECKSUM/DATASUM (have {sorted(events_integrity)})")
    assert events is not None and primary is not None
    return {
        **events,
        **result,
        **result_gti,
        "hdus": names,
        "checksums_verified": checksums_verified,
        "datasums_verified": datasums_verified,
        "object": text(primary, "OBJECT"),
        "creator": text(primary, "CREATOR"),
        "file_date": text(primary, "DATE"),
    }


def parse_gti(header: dict[str, object], unit: bytes, filename: str) -> dict[str, object]:
    """GTI: START/STOP 1D columns; stored values plus their TZERO (= TRIGTIME
    in the probed files), returned as metadata only."""
    if text(header, "TTYPE1") != "START" or text(header, "TTYPE2") != "STOP":
        raise ValueError(f"{filename}: unexpected GTI columns")
    if text(header, "TFORM1") != "1D" or text(header, "TFORM2") != "1D" or int(header["NAXIS1"]) != 16:
        raise ValueError(f"{filename}: unexpected GTI layout")
    intervals = [struct.unpack_from(">dd", unit, 16 * i) for i in range(int(header["NAXIS2"]))]
    return {
        "gti_intervals": len(intervals),
        "gti_stored": [list(pair) for pair in intervals],
        "gti_tzero": [header.get("TZERO1"), header.get("TZERO2")],
    }


def decode_events(unit: bytes, events: dict[str, object], filename: str, output: Path | None) -> dict[str, object]:
    """Copy every stored TIME double (row bytes 0..7) to little-endian float64.

    Statistics: first/last value, min/max, number of decreasing steps
    (backsteps), equal consecutive values, smallest positive step, PHA
    values outside 0..DETCHANS-1 (fatal: would indicate row misalignment),
    and events outside the header TSTART/TSTOP window (metadata).
    """
    rows = int(events["rows"])
    if array("d").itemsize != 8:
        raise RuntimeError("array('d') is not 8 bytes")
    pha_bad = 0
    out = output.open("wb") if output else None
    digest = hashlib.sha256()
    first = last = None
    minimum = math.inf
    maximum = -math.inf
    backsteps = equal_steps = 0
    max_backstep = 0.0
    min_step = math.inf
    try:
        done = 0
        while done < rows:
            count = min(ROW_CHUNK, rows - done)
            base = done * ROW_BYTES
            block = unit[base:base + count * ROW_BYTES]
            chunk = array("d", b"".join(block[i:i + 8] for i in range(0, len(block), ROW_BYTES)))
            pha = array("h", b"".join(block[i + 8:i + 10] for i in range(0, len(block), ROW_BYTES)))
            if sys.byteorder == "little":
                chunk.byteswap()  # FITS big-endian -> host (little-endian) doubles
                pha.byteswap()
            pha_bad += sum(1 for p in pha if p < 0 or p >= DETCHANS)
            for value in chunk:
                if not math.isfinite(value):
                    raise ValueError(f"{filename}: non-finite TIME value")
                if last is None:
                    first = value
                else:
                    step = value - last
                    if step < 0:
                        backsteps += 1
                        if -step > max_backstep:
                            max_backstep = -step
                    elif step == 0:
                        equal_steps += 1
                    elif step < min_step:
                        min_step = step
                last = value
            minimum = min(minimum, min(chunk))
            maximum = max(maximum, max(chunk))
            if sys.byteorder == "little":
                encoded = chunk.tobytes()
            else:
                swapped = array("d", chunk)
                swapped.byteswap()
                encoded = swapped.tobytes()
            digest.update(encoded)
            if out:
                out.write(encoded)
            done += count
    finally:
        if out:
            out.close()
    if pha_bad:
        raise ValueError(f"{filename}: {pha_bad} PHA values outside 0..{DETCHANS - 1} (row misalignment?)")
    return {
        "value_count": rows,
        "first_time": first,
        "last_time": last,
        "minimum": minimum if rows else None,
        "maximum": maximum if rows else None,
        "backsteps": backsteps,
        "max_backstep_s": max_backstep,
        "equal_steps": equal_steps,
        "value_changes": rows - equal_steps,
        "min_positive_step": min_step if min_step != math.inf else None,
        "first_before_tstart_s": max(0.0, float(events["tstart_rel"]) - first) if rows else None,
        "last_after_tstop_s": max(0.0, last - float(events["tstop_rel"])) if rows else None,
        "sha256": digest.hexdigest(),
    }


def check_nondegenerate(label: str, result: dict[str, object]) -> None:
    rows = int(result["value_count"])
    if rows < ROW_FLOOR:
        raise ValueError(f"{label}: {rows} events below floor {ROW_FLOOR}")
    if int(result["backsteps"]) > MAX_BACKSTEPS or float(result["max_backstep_s"]) > MAX_BACKSTEP_S:
        raise ValueError(f"{label}: TIME decreases {result['backsteps']} times "
                         f"(largest {result['max_backstep_s']} s); beyond the source-order tolerance")
    first, last = float(result["first_time"]), float(result["last_time"])
    low, high = float(result["minimum"]), float(result["maximum"])
    if not (FIRST_MIN <= low <= first < FIRST_MAX and LAST_MIN < last <= high <= LAST_MAX):
        raise ValueError(f"{label}: implausible TIME span {first}..{last} (min {low}, max {high})")
    if first >= last or int(result["value_changes"]) < MIN_CHANGES:
        raise ValueError(f"{label}: degenerate TIME column")


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


def sample_name(row: dict[str, str]) -> str:
    return f"{row['burst']}_{row['detector']}_v{int(row['version']):02d}_time.bin"


def build(args: argparse.Namespace) -> None:
    sources = read_sources(args.sources)
    inventory = json.loads((args.download_dir / "download_inventory.json").read_text(encoding="utf-8"))
    by_burst = {record["burst"]: record for record in inventory["records"]}
    if sorted(by_burst) != sorted(row["burst"] for row in sources):
        raise SystemExit("download inventory does not match sources.tsv")
    args.samples_dir.mkdir(parents=True, exist_ok=True)
    for stale in args.samples_dir.glob("*.bin"):
        stale.unlink()
    entries = []
    details = []
    for row in sources:
        burst = row["burst"]
        filename = Path(row["key"]).name
        source = args.download_dir / filename
        record = by_burst[burst]
        if source.stat().st_size != int(row["bytes"]) or sha256_file(source) != record["sha256"]:
            raise SystemExit(f"{burst}: source differs from download inventory")
        output = args.samples_dir / sample_name(row)
        result = walk_file(source, filename, row["detector"], output)
        if int(result["rows"]) != int(row["rows"]):
            raise SystemExit(f"{burst}: NAXIS2 {result['rows']} != pinned {row['rows']}")
        if repr(result["tzero1"]) != row["tzero1"]:
            raise SystemExit(f"{burst}: TZERO1 {result['tzero1']!r} != pinned {row['tzero1']}")
        check_nondegenerate(burst, result)
        size = output.stat().st_size
        if size != int(result["value_count"]) * 8:
            raise SystemExit(f"{burst}: output size mismatch")
        details.append({"burst": burst, "source_file": filename, "source_sha256": record["sha256"],
                        **{k: v for k, v in result.items() if k != "hdus"}})
        entries.append({
            "dataset_id": DATASET_ID,
            "series_id": SERIES_ID,
            "role": "primary",
            "sample_path": output.relative_to(args.data_root).as_posix(),
            "numeric_kind": "float",
            "bit_width": 64,
            "endianness": "little",
            "element_size_bytes": 8,
            "sample_size_bytes": size,
            "value_count": result["value_count"],
            "sample_rank": 1,
            "sample_shape": [result["value_count"]],
            "sample_axes": ["photon_event"],
            "natural_record_kind": NATURAL_RECORD_KIND,
            "source_variable": "EVENTS.TIME (stored 1D value, TZERO1 not applied)",
            "source_file": filename,
            "source_key": row["key"],
            "source_sha256": record["sha256"],
            "burst": burst,
            "detector": row["detector"],
            "detnam": detector_name(row["detector"]),
            "object": result["object"],
            "tzero1_trigtime_met": result["tzero1"],
            "tstart_rel": result["tstart_rel"],
            "tstop_rel": result["tstop_rel"],
            "minimum": result["minimum"],
            "maximum": result["maximum"],
            "equal_steps": result["equal_steps"],
            "value_changes": result["value_changes"],
            "backsteps": result["backsteps"],
            "max_backstep_s": result["max_backstep_s"],
            "first_time": result["first_time"],
            "last_time": result["last_time"],
            "min_positive_step": result["min_positive_step"],
            "sha256": result["sha256"],
        })
        print(f"built {burst} {row['detector']} rows={result['value_count']} "
              f"span={result['first_time']:.6f}..{result['last_time']:.6f} eq={result['equal_steps']} "
              f"backsteps={result['backsteps']} "
              f"checksums={result['checksums_verified']} datasums={result['datasums_verified']}")
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
        "global_minimum": min(float(entry["minimum"]) for entry in entries),
        "global_maximum": max(float(entry["maximum"]) for entry in entries),
        "total_equal_steps": sum(int(entry["equal_steps"]) for entry in entries),
        "total_backsteps": sum(int(entry["backsteps"]) for entry in entries),
        "samples_with_backsteps": [entry["burst"] for entry in entries if int(entry["backsteps"])],
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
        f"range={stats['global_minimum']}..{stats['global_maximum']} equal_steps={stats['total_equal_steps']} "
        f"backsteps={stats['total_backsteps']} in {stats['samples_with_backsteps']}"
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
