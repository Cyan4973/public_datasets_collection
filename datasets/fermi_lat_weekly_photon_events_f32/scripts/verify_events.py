#!/usr/bin/env python3
"""Independent verification of the Fermi LAT weekly photon float32 samples.

Shares no code with lat_events.py: its own FITS card parser and HDU walker
(over an mmap of the file), TFORM-derived byte offsets of ENERGY/RA/DEC/
THETA/PHI, its own EVENTS DATASUM word sum, and a row decoder based on
struct.iter_unpack with a format built from the derived offsets. Every row's
five big-endian floats are re-packed as '<f' and compared byte-for-byte with
the emitted samples. It then recomputes every index statistic (value count,
min/max from the stored float32, distinct count, first value, SHA-256),
checks physical ranges, the exact sample inventory, the manifest per-series
totals, and the degeneracy rules.

Missing-value policy (same as build): none. The emitted columns carry no
TNULL, TSCAL or TZERO; every stored float is emitted unchanged in stored row
order. Non-finite values or values outside the column's physical range
(ENERGY 0..1e7 MeV, RA 0..360, DEC -90..90, THETA 0..180, PHI 0..360 deg) are
fatal; nothing is masked, clipped, imputed, sorted or dropped.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import mmap
import re
import statistics
import struct
import tomllib
from array import array
from pathlib import Path

DATASET_ID = "fermi_lat_weekly_photon_events_f32"
BLOCK = 2880
WIDTH = {"L": 1, "X": 0, "B": 1, "I": 2, "J": 4, "K": 8, "A": 1, "E": 4, "D": 8, "C": 8, "M": 16}
TFORM = re.compile(r"^(\d*)([A-Z])$")
SERIES = {  # TTYPE -> (series id, low, high)
    "ENERGY": ("lat_photon_energy_f32", 0.0, 1.0e7),
    "RA": ("lat_photon_ra_f32", 0.0, 360.0),
    "DEC": ("lat_photon_dec_f32", -90.0, 90.0),
    "THETA": ("lat_photon_theta_f32", 0.0, 180.0),
    "PHI": ("lat_photon_phi_f32", 0.0, 360.0),
}
ORDER = ["ENERGY", "RA", "DEC", "THETA", "PHI"]
ROW_FLOOR = 100_000
MIN_DISTINCT = 1_000
CHUNK = 65_536
NATURAL_RECORD_KIND = "lat_weekly_photon_file_events_column"


def fail(message: str) -> None:
    raise SystemExit(f"VERIFY FAIL: {message}")


def cards_at(buf, offset: int) -> tuple[dict[str, str], int, int]:
    """Return (raw keyword values, data start, header start)."""
    start = offset
    values: dict[str, str] = {}
    while True:
        if offset + BLOCK > len(buf):
            fail("truncated header")
        block = bytes(buf[offset:offset + BLOCK]).decode("ascii")
        offset += BLOCK
        for i in range(0, BLOCK, 80):
            card = block[i:i + 80]
            if card.startswith("END") and not card[3:].strip():
                return values, offset, start
            if card[8:10] == "= ":
                values[card[:8].rstrip()] = card[10:]


def sval(raw: str) -> str:
    raw = raw.strip()
    if raw.startswith("'"):
        end = raw.index("'", 1)
        while end + 1 < len(raw) and raw[end + 1] == "'":
            end = raw.index("'", end + 2)
        return raw[1:end].replace("''", "'").rstrip()
    return raw.split("/")[0].strip()


def ival(cards: dict[str, str], key: str) -> int:
    return int(sval(cards[key]))


def word_sum(view) -> int:
    words = array("I" if array("I").itemsize == 4 else "L")
    words.frombytes(view)
    words.byteswap()
    total = sum(words)
    while total > 0xFFFFFFFF:
        total = (total >> 32) + (total & 0xFFFFFFFF)
    return total


def locate(buf, filename: str) -> dict[str, object]:
    primary, offset, _ = cards_at(buf, 0)
    if sval(primary.get("INSTRUME", "")) != "LAT" or sval(primary.get("TELESCOP", "")) != "GLAST":
        fail(f"{filename}: not a GLAST/LAT file")
    if ival(primary, "NAXIS") != 0:
        fail(f"{filename}: primary has data")
    hdus = ["PRIMARY"]
    events = None
    while offset < len(buf):
        cards, data_start, _ = cards_at(buf, offset)
        name = sval(cards.get("EXTNAME", ""))
        hdus.append(name)
        nbytes = ival(cards, "NAXIS1") * ival(cards, "NAXIS2")
        if name == "EVENTS":
            events = (cards, data_start, nbytes)
        offset = data_start + (nbytes + BLOCK - 1) // BLOCK * BLOCK
    if offset != len(buf) or hdus != ["PRIMARY", "EVENTS", "GTI"]:
        fail(f"{filename}: HDU layout {hdus}, end {offset} vs size {len(buf)}")
    cards, data_start, nbytes = events
    position = 0
    offsets: dict[str, int] = {}
    for index in range(1, ival(cards, "TFIELDS") + 1):
        ttype = sval(cards[f"TTYPE{index}"])
        match = TFORM.match(sval(cards[f"TFORM{index}"]).replace(" ", ""))
        repeat = int(match.group(1) or 1)
        width = (repeat + 7) // 8 if match.group(2) == "X" else repeat * WIDTH[match.group(2)]
        if ttype in SERIES:
            if match.group(2) != "E" or repeat != 1:
                fail(f"{filename}: {ttype} is not a scalar float32 column")
            for key in ("TSCAL", "TZERO", "TNULL"):
                if f"{key}{index}" in cards:
                    fail(f"{filename}: {ttype} has {key}")
            offsets[ttype] = position
        position += width
    if position != ival(cards, "NAXIS1") or sorted(offsets) != sorted(ORDER):
        fail(f"{filename}: row width {position} or columns {sorted(offsets)} unexpected")
    unit_end = data_start + (nbytes + BLOCK - 1) // BLOCK * BLOCK
    datasum = 0
    for piece in range(data_start, unit_end, BLOCK * 2048):
        datasum += word_sum(buf[piece:min(piece + BLOCK * 2048, unit_end)])
    while datasum > 0xFFFFFFFF:
        datasum = (datasum >> 32) + (datasum & 0xFFFFFFFF)
    if str(datasum) != sval(cards["DATASUM"]):
        fail(f"{filename}: EVENTS DATASUM mismatch ({datasum} vs {sval(cards['DATASUM'])})")
    return {"rows": ival(cards, "NAXIS2"), "row_bytes": position, "data_start": data_start, "offsets": offsets,
            "datasum": str(datasum)}


def row_format(offsets: dict[str, int], row_bytes: int) -> tuple[struct.Struct, list[str]]:
    fields = sorted(ORDER, key=lambda name: offsets[name])
    fmt = ">"
    position = 0
    for name in fields:
        if offsets[name] > position:
            fmt += f"{offsets[name] - position}x"
        fmt += "f"
        position = offsets[name] + 4
    fmt += f"{row_bytes - position}x"
    return struct.Struct(fmt), fields


def verify(args: argparse.Namespace) -> None:
    manifest = tomllib.loads(args.manifest.read_text(encoding="utf-8"))
    declared = {s["id"]: s for s in manifest["series"]}
    if sorted(declared) != sorted(item[0] for item in SERIES.values()):
        fail(f"manifest series {sorted(declared)} unexpected")
    for series in declared.values():
        if series["role"] != "primary" or series["numeric_kind"] != "float" or series["bit_width"] != 32:
            fail(f"manifest series {series['id']} not a primary float32 series")
    with args.sources.open(encoding="utf-8", newline="") as handle:
        sources = list(csv.DictReader(handle, delimiter="\t"))
    index = [json.loads(line) for line in args.index.read_text(encoding="utf-8").splitlines() if line.strip()]
    by_path = {entry["sample_path"]: entry for entry in index}
    if len(by_path) != len(index) or len(index) != len(sources) * len(ORDER):
        fail(f"index has {len(index)} rows, expected {len(sources) * len(ORDER)}")
    expected_paths = set()
    totals = {sid: [0, 0] for sid, _lo, _hi in SERIES.values()}
    counts = {sid: [] for sid, _lo, _hi in SERIES.values()}
    hashes = []
    for row in sources:
        week = int(row["week"])
        path = args.download_dir / row["filename"]
        with path.open("rb") as handle, mmap.mmap(handle.fileno(), 0, access=mmap.ACCESS_READ) as buf:
            info = locate(buf, row["filename"])
            if info["rows"] != int(row["rows"]) or info["datasum"] != row["events_datasum"]:
                fail(f"w{week}: NAXIS2/DATASUM differ from sources.tsv")
            if info["rows"] < ROW_FLOOR:
                fail(f"w{week}: below row floor")
            unpacker, fields = row_format(info["offsets"], info["row_bytes"])
            columns = {name: array("f") for name in fields}
            start = info["data_start"]
            rows = info["rows"]
            row_bytes = info["row_bytes"]
            for chunk_start in range(0, rows, CHUNK):
                n = min(CHUNK, rows - chunk_start)
                view = memoryview(buf)[start + chunk_start * row_bytes:start + (chunk_start + n) * row_bytes]
                decoded = list(unpacker.iter_unpack(view))
                view.release()
                for j, name in enumerate(fields):
                    columns[name].extend(t[j] for t in decoded)
        for name in ORDER:
            series_id, low, high = SERIES[name]
            values = columns[name]
            packed = array("f", values)
            if struct.pack("=f", 1.0) != struct.pack("<f", 1.0):
                packed.byteswap()
            encoded = packed.tobytes()
            rel = f"samples/{DATASET_ID}/{series_id}/w{week:03d}_{name.lower()}.bin"
            expected_paths.add(rel)
            entry = by_path.get(rel)
            if entry is None:
                fail(f"index lacks {rel}")
            sample = (args.data_root / rel).read_bytes()
            if sample != encoded:
                fail(f"{rel}: bytes differ from the independently decoded column")
            if not math.isfinite(math.fsum(values)):
                fail(f"{rel}: non-finite values")
            lo, hi = min(values), max(values)
            if not (low <= lo and hi <= high):
                fail(f"{rel}: range {lo}..{hi} outside {low}..{high}")
            distinct = len(set(values))
            if lo >= hi or distinct < MIN_DISTINCT:
                fail(f"{rel}: degenerate ({distinct} distinct)")
            digest = hashlib.sha256(encoded).hexdigest()
            expect = {
                "dataset_id": DATASET_ID, "series_id": series_id, "numeric_kind": "float", "bit_width": 32,
                "endianness": "little", "element_size_bytes": 4, "sample_size_bytes": len(encoded),
                "value_count": len(values), "minimum": lo, "maximum": hi, "distinct_values": distinct,
                "first_value": values[0], "sha256": digest, "mission_week": week, "role": "primary",
                "natural_record_kind": NATURAL_RECORD_KIND,
            }
            for key, value in expect.items():
                if entry.get(key) != value:
                    fail(f"{rel}: index {key}={entry.get(key)!r}, recomputed {value!r}")
            totals[series_id][0] += 1
            totals[series_id][1] += len(encoded)
            counts[series_id].append(len(values))
            hashes.append(digest)
        print(f"verified w{week:03d} rows={rows}", flush=True)
    if set(by_path) != expected_paths:
        fail("index paths differ from the expected inventory")
    on_disk = {p.relative_to(args.data_root).as_posix() for p in args.samples_root.glob("*/*.bin")}
    if on_disk != expected_paths:
        fail(f"sample files on disk differ from inventory ({len(on_disk)} vs {len(expected_paths)})")
    if len(set(hashes)) != len(hashes):
        fail("duplicate samples")
    grand = 0
    for series_id, (count, size) in totals.items():
        man = declared[series_id]
        if man["sample_count"] != count or man["total_size_bytes"] != size:
            fail(f"{series_id}: manifest {man['sample_count']}/{man['total_size_bytes']} != realized {count}/{size}")
        if statistics.median(counts[series_id]) < 1000:
            fail(f"{series_id}: median below floor")
        grand += size
        print(f"{series_id}: samples={count} bytes={size} median_values={statistics.median(counts[series_id])}")
    if grand > 1_000_000_000:
        fail("primary output exceeds 1 GB")
    print(f"verify ok samples={len(index)} primary_bytes={grand}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--sources", type=Path, required=True)
    parser.add_argument("--download-dir", type=Path, required=True)
    parser.add_argument("--samples-root", type=Path, required=True)
    parser.add_argument("--index", type=Path, required=True)
    parser.add_argument("--data-root", type=Path, required=True)
    verify(parser.parse_args())


if __name__ == "__main__":
    main()
