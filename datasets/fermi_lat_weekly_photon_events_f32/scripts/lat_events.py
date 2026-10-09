#!/usr/bin/env python3
"""Decode Fermi LAT weekly photon FITS files (P305) to float32 column samples.

Pure standard library. The FITS walker reads 80-character header cards in
2880-byte blocks, locates the EVENTS binary table by EXTNAME, validates the full
23-column schema (column byte offsets are derived from the TFORM cards and must
equal the expected layout), verifies every HDU's FITS CHECKSUM (header + data
ones'-complement sum = -0) and DATASUM, requires zero padding and no trailing
bytes, and streams the EVENTS data unit in row-aligned chunks.

For each emitted field (ENERGY, RA, DEC, THETA, PHI; TFORM 'E', big-endian
IEEE-754 float32) the 4 stored bytes of every row are copied, in stored row
order, into a little-endian float32 sample using extended-slice assignment
(which performs the byte swap). Nothing is scaled, rounded, filtered or sorted.

Row-alignment sanity checks (not emitted): every row's EVENT_CLASS has the
SOURCE bit (mask 128, the selection declared by DSTYP2/DSVAL2) set, and every
TIME (TFORM 'D') lies inside the header TSTART..TSTOP window.

verify_events.py is a separate, independent implementation used by verify.sh.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import statistics
import sys
from array import array
from pathlib import Path
from typing import Callable

DATASET_ID = "fermi_lat_weekly_photon_events_f32"
NATURAL_RECORD_KIND = "lat_weekly_photon_file_events_column"
FITS_BLOCK = 2_880
ROW_BYTES = 98
CHUNK_ROWS = 65_536  # 98 * 65536 bytes per chunk: a multiple of 4 (checksum words)
ROW_FLOOR = 100_000
MIN_DISTINCT = 1_000

# (TTYPE, TFORM) of the 23 EVENTS columns, in order.
EXPECTED_COLUMNS = [
    ("ENERGY", "E"), ("RA", "E"), ("DEC", "E"), ("L", "E"), ("B", "E"),
    ("THETA", "E"), ("PHI", "E"), ("ZENITH_ANGLE", "E"), ("EARTH_AZIMUTH_ANGLE", "E"),
    ("TIME", "D"), ("EVENT_ID", "J"), ("RUN_ID", "J"), ("RECON_VERSION", "I"),
    ("CALIB_VERSION", "3I"), ("EVENT_CLASS", "32X"), ("EVENT_TYPE", "32X"),
    ("CONVERSION_TYPE", "I"), ("LIVETIME", "D"),
    ("DIFRSP0", "E"), ("DIFRSP1", "E"), ("DIFRSP2", "E"), ("DIFRSP3", "E"), ("DIFRSP4", "E"),
]
TFORM_BYTES = {"E": 4, "D": 8, "J": 4, "I": 2, "3I": 6, "32X": 4}

# Emitted fields: (TTYPE, series id, expected TUNIT, expected offset, physical lo, hi).
FIELDS = [
    ("ENERGY", "lat_photon_energy_f32", "MeV", 0, 0.0, 10_000_000.0),
    ("RA", "lat_photon_ra_f32", "deg", 4, 0.0, 360.0),
    ("DEC", "lat_photon_dec_f32", "deg", 8, -90.0, 90.0),
    ("THETA", "lat_photon_theta_f32", "deg", 20, 0.0, 180.0),
    ("PHI", "lat_photon_phi_f32", "deg", 24, 0.0, 360.0),
]
TIME_OFFSET = 36
EVENT_CLASS_OFFSET = 60
SOURCE_BIT_BYTE = EVENT_CLASS_OFFSET + 3  # 32X bit array, MSB first: mask 128 = bit 7 of byte 3
SOURCE_BIT = 0x80
NO_SOURCE_BIT = bytes(b for b in range(256) if not b & SOURCE_BIT)
EXPECTED_HDUS = ["PRIMARY", "EVENTS", "GTI"]


class Truncated(ValueError):
    """A (partial) stream ended inside a header or data unit."""


# ---------------------------------------------------------------- checksums


def word_array() -> array:
    for code in ("I", "L"):
        words = array(code)
        if words.itemsize == 4:
            return words
    raise RuntimeError("no 32-bit unsigned array type")


def ones_sum(data: bytes, start: int = 0) -> int:
    """FITS 32-bit ones'-complement sum of big-endian words (len % 4 == 0)."""
    if len(data) % 4:
        raise ValueError("checksum input not word aligned")
    words = word_array()
    words.frombytes(data)
    if sys.byteorder == "little":
        words.byteswap()
    return fold(start + sum(words))


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


def data_bytes(header: dict[str, object]) -> int:
    naxis = int(header.get("NAXIS", 0))
    if naxis == 0:
        return 0
    count = 1
    for axis in range(1, naxis + 1):
        count *= int(header[f"NAXIS{axis}"])
    return abs(int(header["BITPIX"])) // 8 * int(header.get("GCOUNT", 1)) * (count + int(header.get("PCOUNT", 0)))


def padded(size: int) -> int:
    return (size + FITS_BLOCK - 1) // FITS_BLOCK * FITS_BLOCK


def text(header: dict[str, object], key: str) -> str:
    return str(header.get(key, "")).strip()


def validate_primary(header: dict[str, object], filename: str) -> None:
    expected = {"SIMPLE": True, "NAXIS": 0, "TELESCOP": "GLAST", "INSTRUME": "LAT", "PROC_VER": 305}
    for key, value in expected.items():
        actual = text(header, key) if isinstance(value, str) else header.get(key)
        if actual != value:
            raise ValueError(f"{filename}: primary {key}={header.get(key)!r}, expected {value!r}")


def column_offsets(header: dict[str, object], filename: str) -> dict[str, int]:
    offsets: dict[str, int] = {}
    position = 0
    for index, (name, form) in enumerate(EXPECTED_COLUMNS, start=1):
        ttype = text(header, f"TTYPE{index}")
        tform = text(header, f"TFORM{index}").replace(" ", "")
        if ttype != name or tform != form:
            raise ValueError(f"{filename}: EVENTS column {index} is {ttype}/{tform}, expected {name}/{form}")
        offsets[name] = position
        position += TFORM_BYTES[form]
    if position != ROW_BYTES:
        raise ValueError(f"{filename}: TFORM widths sum to {position}, expected {ROW_BYTES}")
    return offsets


def validate_events(header: dict[str, object], filename: str) -> dict[str, object]:
    expected = {
        "XTENSION": "BINTABLE", "BITPIX": 8, "NAXIS": 2, "NAXIS1": ROW_BYTES, "PCOUNT": 0, "GCOUNT": 1,
        "TFIELDS": len(EXPECTED_COLUMNS), "EXTNAME": "EVENTS", "TELESCOP": "GLAST", "INSTRUME": "LAT",
        "PASS_VER": "P8R3", "DSTYP2": "BIT_MASK(EVENT_CLASS,128,P8R3)", "DSVAL2": "1:1",
    }
    for key, value in expected.items():
        actual = text(header, key) if isinstance(value, str) else header.get(key)
        if actual != value:
            raise ValueError(f"{filename}: EVENTS {key}={header.get(key)!r}, expected {value!r}")
    offsets = column_offsets(header, filename)
    for name, _series, unit, offset, _lo, _hi in FIELDS:
        index = [c[0] for c in EXPECTED_COLUMNS].index(name) + 1
        if offsets[name] != offset:
            raise ValueError(f"{filename}: {name} offset {offsets[name]} != {offset}")
        if text(header, f"TUNIT{index}") != unit:
            raise ValueError(f"{filename}: {name} TUNIT {header.get(f'TUNIT{index}')!r} != {unit!r}")
        for key in ("TSCAL", "TZERO", "TNULL", "TDIM"):
            if f"{key}{index}" in header:
                raise ValueError(f"{filename}: unexpected {key}{index} on {name}")
    if offsets["TIME"] != TIME_OFFSET or offsets["EVENT_CLASS"] != EVENT_CLASS_OFFSET:
        raise ValueError(f"{filename}: unexpected TIME/EVENT_CLASS offsets")
    if "THEAP" in header:
        raise ValueError(f"{filename}: unexpected THEAP")
    rows = int(header["NAXIS2"])
    if rows < 0:
        raise ValueError(f"{filename}: negative NAXIS2")
    return {
        "rows": rows,
        "tstart": float(header["TSTART"]),
        "tstop": float(header["TSTOP"]),
        "date_obs": text(header, "DATE-OBS"),
        "date_end": text(header, "DATE-END"),
        "events_datasum": text(header, "DATASUM"),
        "has_checksum": "CHECKSUM" in header,
    }


def probe_prefix(prefix: bytes, filename: str) -> dict[str, object]:
    """Header probe on a file prefix fetched with a range GET (select_weeks.py)."""
    stream = io.BytesIO(prefix)
    found = read_header(stream.read)
    if found is None:
        raise Truncated("empty prefix")
    primary, _ = found
    validate_primary(primary, filename)
    stream.seek(padded(data_bytes(primary)), 1)
    found = read_header(stream.read)
    if found is None:
        raise Truncated("prefix ends before EVENTS")
    header, raw = found
    info = validate_events(header, filename)
    info["events_header_end"] = stream.tell()
    info["creator"] = text(primary, "CREATOR")
    info["file_date"] = text(primary, "DATE")
    return info


# ---------------------------------------------------------------- column extraction


def extract_le32(rows_data: bytes, offset: int) -> bytearray:
    """Big-endian 4-byte field at `offset` of every 98-byte row -> little-endian bytes."""
    count = len(rows_data) // ROW_BYTES
    out = bytearray(4 * count)
    out[0::4] = rows_data[offset + 3::ROW_BYTES]
    out[1::4] = rows_data[offset + 2::ROW_BYTES]
    out[2::4] = rows_data[offset + 1::ROW_BYTES]
    out[3::4] = rows_data[offset::ROW_BYTES]
    return out


def extract_le64(rows_data: bytes, offset: int) -> bytearray:
    count = len(rows_data) // ROW_BYTES
    out = bytearray(8 * count)
    for k in range(8):
        out[k::8] = rows_data[offset + 7 - k::ROW_BYTES]
    return out


def as_floats(raw: bytes, code: str) -> array:
    values = array(code)
    values.frombytes(raw)
    if sys.byteorder != "little":
        values.byteswap()
    return values


class FieldStats:
    def __init__(self, name: str, out_path: Path | None) -> None:
        self.name = name
        self.out = out_path.open("wb") if out_path else None
        self.sha = hashlib.sha256()
        self.count = 0
        self.minimum = math.inf
        self.maximum = -math.inf
        self.first: float | None = None

    def add(self, raw: bytearray) -> None:
        values = as_floats(raw, "f")
        if not values:
            return
        if not math.isfinite(math.fsum(values)):
            raise ValueError(f"{self.name}: non-finite value")
        if self.first is None:
            self.first = values[0]
        self.minimum = min(self.minimum, min(values))
        self.maximum = max(self.maximum, max(values))
        self.count += len(values)
        self.sha.update(raw)
        if self.out:
            self.out.write(raw)

    def close(self) -> None:
        if self.out:
            self.out.close()


# ---------------------------------------------------------------- full-file walk


def walk_file(path: Path, filename: str, outputs: dict[str, Path] | None = None,
              decode: bool = True) -> dict[str, object]:
    """Validate the whole file; with decode=True also decode (and optionally write) the fields."""
    names: list[str] = []
    checksums = datasums = 0
    events: dict[str, object] | None = None
    gti: dict[str, object] = {}
    fields: dict[str, FieldStats] = {}
    alignment: dict[str, object] = {}
    size = path.stat().st_size
    with path.open("rb") as handle:
        while handle.tell() < size:
            found = read_header(handle.read)
            if found is None:
                break
            header, raw_header = found
            name = "PRIMARY" if not names else text(header, "EXTNAME")
            names.append(name)
            if name == "PRIMARY":
                validate_primary(header, filename)
            nbytes = data_bytes(header)
            unit_len = padded(nbytes)
            is_events = name == "EVENTS"
            if is_events:
                if events is not None:
                    raise ValueError(f"{filename}: two EVENTS extensions")
                events = validate_events(header, filename)
                if decode:
                    fields = {f[0]: FieldStats(f[0], (outputs or {}).get(f[0])) for f in FIELDS}
                    alignment = {"time_min": math.inf, "time_max": -math.inf, "no_source_bit": 0,
                                 "time_backsteps": 0, "last_time": None}
            data_sum = 0
            consumed = 0
            chunk_bytes = ROW_BYTES * CHUNK_ROWS
            tail_unit = b""
            while consumed < unit_len:
                want = min(chunk_bytes, unit_len - consumed)
                chunk = handle.read(want)
                if len(chunk) != want:
                    raise Truncated(f"{filename}: truncated data unit of {name}")
                data_sum = ones_sum(chunk, data_sum)
                data_end = max(0, min(want, nbytes - consumed))
                if chunk[data_end:].strip(b"\x00"):
                    raise ValueError(f"{filename}: non-zero padding after {name} data")
                if is_events and decode and data_end:
                    decode_chunk(chunk[:data_end], fields, alignment)
                if name == "GTI":
                    tail_unit += chunk[:data_end]
                consumed += want
            if "DATASUM" in header:
                if int(text(header, "DATASUM")) != data_sum:
                    raise ValueError(f"{filename}: {name} DATASUM {text(header, 'DATASUM')} != computed {data_sum}")
                datasums += 1
            elif name != "PRIMARY":
                raise ValueError(f"{filename}: {name} lacks DATASUM")
            if "CHECKSUM" not in header:
                raise ValueError(f"{filename}: {name} lacks CHECKSUM")
            total = fold(ones_sum(raw_header) + data_sum)
            if total != 0xFFFFFFFF:
                raise ValueError(f"{filename}: {name} CHECKSUM does not verify (sum {total:#x})")
            checksums += 1
            if name == "GTI":
                gti = parse_gti(header, tail_unit, filename)
    for stats in fields.values():
        stats.close()
    if names != EXPECTED_HDUS:
        raise ValueError(f"{filename}: HDU sequence {names}, expected {EXPECTED_HDUS}")
    assert events is not None
    result: dict[str, object] = {**events, **gti, "hdus": names, "checksums_verified": checksums,
                                 "datasums_verified": datasums}
    if decode:
        rows = int(events["rows"])
        if alignment["no_source_bit"]:
            raise ValueError(f"{filename}: {alignment['no_source_bit']} rows lack the EVENT_CLASS SOURCE bit")
        if rows and not (events["tstart"] <= alignment["time_min"] <= alignment["time_max"] <= events["tstop"]):
            raise ValueError(f"{filename}: TIME {alignment['time_min']}..{alignment['time_max']} outside "
                             f"TSTART..TSTOP {events['tstart']}..{events['tstop']} (row misalignment?)")
        result["time_min"] = alignment["time_min"]
        result["time_max"] = alignment["time_max"]
        result["time_backsteps"] = alignment["time_backsteps"]
        result["fields"] = {}
        for name, _series, _unit, _offset, low, high in FIELDS:
            stats = fields[name]
            if stats.count != rows:
                raise ValueError(f"{filename}: {name} decoded {stats.count} values, expected {rows}")
            if rows and not (low <= stats.minimum and stats.maximum <= high):
                raise ValueError(f"{filename}: {name} range {stats.minimum}..{stats.maximum} outside {low}..{high}")
            result["fields"][name] = {
                "value_count": stats.count,
                "minimum": stats.minimum,
                "maximum": stats.maximum,
                "first_value": stats.first,
                "sha256": stats.sha.hexdigest(),
            }
    return result


def decode_chunk(rows_data: bytes, fields: dict[str, FieldStats], alignment: dict[str, object]) -> None:
    if len(rows_data) % ROW_BYTES:
        raise ValueError("EVENTS chunk not row aligned")
    for name, _series, _unit, offset, _lo, _hi in FIELDS:
        fields[name].add(extract_le32(rows_data, offset))
    times = as_floats(extract_le64(rows_data, TIME_OFFSET), "d")
    if not math.isfinite(math.fsum(times)):
        raise ValueError("non-finite TIME")
    alignment["time_min"] = min(alignment["time_min"], min(times))
    alignment["time_max"] = max(alignment["time_max"], max(times))
    last = alignment["last_time"]
    previous = times[:-1]
    if last is not None:
        previous = array("d", [last]) + previous
        current = times
    else:
        current = times[1:]
    alignment["time_backsteps"] += sum(1 for a, b in zip(previous, current) if b < a)
    alignment["last_time"] = times[-1]
    flags = rows_data[SOURCE_BIT_BYTE::ROW_BYTES]
    alignment["no_source_bit"] += len(flags) - len(flags.translate(None, NO_SOURCE_BIT))


def parse_gti(header: dict[str, object], unit: bytes, filename: str) -> dict[str, object]:
    if (text(header, "TTYPE1"), text(header, "TFORM1"), text(header, "TTYPE2"), text(header, "TFORM2")) != \
            ("START", "D", "STOP", "D") or int(header["NAXIS1"]) != 16:
        raise ValueError(f"{filename}: unexpected GTI layout")
    count = int(header["NAXIS2"])
    values = as_floats(extract_gti(unit, count), "d")
    return {"gti_intervals": count, "gti_ontime": float(header.get("ONTIME", 0.0)),
            "gti_first_start": values[0] if count else None, "gti_last_stop": values[-1] if count else None}


def extract_gti(unit: bytes, count: int) -> bytes:
    """START/STOP doubles of a (tiny) GTI table, byte-swapped to little-endian."""
    raw = unit[:16 * count]
    if len(raw) != 16 * count:
        raise ValueError("truncated GTI table")
    return b"".join(raw[i:i + 8][::-1] for i in range(0, len(raw), 8))


# ---------------------------------------------------------------- build


def read_sources(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 22), b""):
            digest.update(chunk)
    return digest.hexdigest()


def distinct_count(path: Path) -> int:
    values = array("f")
    values.frombytes(path.read_bytes())
    return len(set(values))


def sample_name(week: str, field: str) -> str:
    return f"w{int(week):03d}_{field.lower()}.bin"


def build(args: argparse.Namespace) -> None:
    sources = read_sources(args.sources)
    inventory = json.loads((args.download_dir / "download_inventory.json").read_text(encoding="utf-8"))
    by_week = {record["week"]: record for record in inventory["records"]}
    if sorted(by_week) != sorted(row["week"] for row in sources):
        raise SystemExit("download inventory does not match sources.tsv")
    for _name, series, *_ in FIELDS:
        directory = args.samples_root / series
        directory.mkdir(parents=True, exist_ok=True)
        for stale in directory.glob("*.bin"):
            stale.unlink()
    entries: list[dict[str, object]] = []
    details: list[dict[str, object]] = []
    for row in sources:
        week = row["week"]
        filename = row["filename"]
        source = args.download_dir / filename
        record = by_week[week]
        if source.stat().st_size != int(row["bytes"]) or sha256_file(source) != record["sha256"]:
            raise SystemExit(f"w{week}: source differs from download inventory")
        outputs = {name: args.samples_root / series / sample_name(week, name) for name, series, *_ in FIELDS}
        result = walk_file(source, filename, outputs)
        if int(result["rows"]) != int(row["rows"]) or result["events_datasum"] != row["events_datasum"]:
            raise SystemExit(f"w{week}: NAXIS2/DATASUM differ from pinned values")
        if int(result["rows"]) < ROW_FLOOR:
            raise SystemExit(f"w{week}: {result['rows']} rows below floor {ROW_FLOOR}")
        for name, series, unit, offset, _lo, _hi in FIELDS:
            stats = result["fields"][name]
            output = outputs[name]
            size = output.stat().st_size
            if size != int(stats["value_count"]) * 4:
                raise SystemExit(f"w{week} {name}: output size mismatch")
            stats["distinct_values"] = distinct_count(output)
            if stats["minimum"] >= stats["maximum"] or int(stats["distinct_values"]) < MIN_DISTINCT:
                raise SystemExit(f"w{week} {name}: degenerate column ({stats['distinct_values']} distinct)")
            entries.append({
                "dataset_id": DATASET_ID,
                "series_id": series,
                "role": "primary",
                "sample_path": output.relative_to(args.data_root).as_posix(),
                "numeric_kind": "float",
                "bit_width": 32,
                "endianness": "little",
                "element_size_bytes": 4,
                "sample_size_bytes": size,
                "value_count": stats["value_count"],
                "sample_rank": 1,
                "sample_shape": [stats["value_count"]],
                "sample_axes": ["photon_event"],
                "natural_record_kind": NATURAL_RECORD_KIND,
                "source_variable": f"EVENTS.{name} (TFORM E, TUNIT {unit}, row byte offset {offset})",
                "source_file": filename,
                "source_sha256": record["sha256"],
                "mission_week": int(week),
                "date_obs": result["date_obs"],
                "date_end": result["date_end"],
                "tstart_met": result["tstart"],
                "tstop_met": result["tstop"],
                "minimum": stats["minimum"],
                "maximum": stats["maximum"],
                "distinct_values": stats["distinct_values"],
                "first_value": stats["first_value"],
                "sha256": stats["sha256"],
            })
        details.append({"week": week, "source_file": filename, "source_sha256": record["sha256"],
                        **{k: v for k, v in result.items() if k != "hdus"}})
        energy = result["fields"]["ENERGY"]
        print(f"built w{week} rows={result['rows']} energy={energy['minimum']:.3f}..{energy['maximum']:.1f} "
              f"time_backsteps={result['time_backsteps']} gti={result['gti_intervals']} "
              f"checksums={result['checksums_verified']} datasums={result['datasums_verified']}", flush=True)
    hashes = [entry["sha256"] for entry in entries]
    if len(set(hashes)) != len(hashes):
        raise SystemExit("duplicate output samples")
    per_series = {}
    for _name, series, *_ in FIELDS:
        mine = [entry for entry in entries if entry["series_id"] == series]
        counts = [int(entry["value_count"]) for entry in mine]
        per_series[series] = {
            "samples": len(mine),
            "values": sum(counts),
            "bytes": sum(int(entry["sample_size_bytes"]) for entry in mine),
            "median_values": statistics.median(counts),
            "global_minimum": min(float(entry["minimum"]) for entry in mine),
            "global_maximum": max(float(entry["maximum"]) for entry in mine),
        }
    total_bytes = sum(int(entry["sample_size_bytes"]) for entry in entries)
    if total_bytes > 1_000_000_000:
        raise SystemExit("primary output exceeds 1 GB cap")
    stats = {"dataset_id": DATASET_ID, "samples": len(entries), "primary_bytes": total_bytes,
             "primary_values": sum(int(entry["value_count"]) for entry in entries),
             "series": per_series, "records": details}
    args.index.parent.mkdir(parents=True, exist_ok=True)
    with args.index.open("w", encoding="utf-8") as handle:
        for entry in entries:
            handle.write(json.dumps(entry, sort_keys=True) + "\n")
    args.stats.parent.mkdir(parents=True, exist_ok=True)
    args.stats.write_text(json.dumps(stats, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"build samples={stats['samples']} primary_values={stats['primary_values']} primary_bytes={total_bytes}")
    for series, item in per_series.items():
        print(f"  {series}: {item}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sources", type=Path, required=True)
    parser.add_argument("--download-dir", type=Path, required=True)
    parser.add_argument("--samples-root", type=Path, required=True)
    parser.add_argument("--index", type=Path, required=True)
    parser.add_argument("--stats", type=Path, required=True)
    parser.add_argument("--data-root", type=Path, required=True)
    build(parser.parse_args())


if __name__ == "__main__":
    main()
