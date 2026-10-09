#!/usr/bin/env python3
"""LRO LOLA RDR (LRO-L-LOLA-3-RDR-V1.0) record helpers, pure standard library.

Record layout (lolardr.fmt, v2.42 + 2011 edits): fixed 256-byte little-endian
rows, one per 28 Hz LOLA shot, 5 laser spots per shot. PDS3 START_BYTE is
1-based, so the 0-based offset is START_BYTE - 1:

    RADIUS_k     LSB_INTEGER           START_BYTE 49 + 40 (k-1)  -> offset 48 + 40 (k-1)
    RANGE_k      LSB_UNSIGNED_INTEGER  START_BYTE 53 + 40 (k-1)  -> offset 52 + 40 (k-1)
    SHOT_FLAG_k  LSB_UNSIGNED_INTEGER  START_BYTE 77 + 40 (k-1)  -> offset 76 + 40 (k-1)

(RANGE_3 is declared LSB_INTEGER with MISSING_CONSTANT -1 and RANGE_2 has no
MISSING_CONSTANT line; -1 and 4294967295 are the same 32-bit pattern.)

Spot policy (shared with verify_samples.py, which re-implements it):
    keep spot k of a shot iff RADIUS_k != -1 and RANGE_k != 0xFFFFFFFF and
    (SHOT_FLAG_k & 0xFF) == 0.
lolardr.fmt, SHOT_FLAG_1: "Describes the probability that spot 1 is a lunar
range and its associated quality using flags in the least significant byte.
Any values other than 0 should be regarded as an invalid measurement."
Bits 8-9 (RMU phase) and bits 16-31 (relative range uncertainty) are status /
quality magnitudes, not invalidity flags, and are not used for selection.

Subcommands:
    self-test                       synthetic-record and fmt cross-check tests
    check-fmt   --fmt F             pinned lolardr.fmt agrees with the offsets
    check-label --sources S --file NAME --label L
    check-dat   --sources S --file NAME --dat D [--label L]
"""
from __future__ import annotations

import argparse
import hashlib
import re
import struct
import sys
from pathlib import Path

RECORD_BYTES = 256
SPOTS = 5
SPOT_STRIDE = 40
RADIUS_OFFSET = 48
RANGE_OFFSET = 52
FLAG_OFFSET = 76
RADIUS_MISSING = -1
RANGE_MISSING = 0xFFFFFFFF
FLAG_INVALID_MASK = 0xFF
INT32_MAX = 2**31 - 1

# Physical plausibility bounds used only as fatal sanity checks on KEPT spots
# (never as a filter). Lunar radius extremes are about 1728.3 .. 1748.2 km;
# LRO's quasi-circular mapping orbit is 30 .. 70 km above the surface (wider
# limits leave room for off-nadir pointing and terrain).
RADIUS_SANITY = (1_720_000_000, 1_760_000_000)
RANGE_SANITY = (10_000_000, 250_000_000)
# Orbit-level validity floor: an orbit whose kept-spot fraction is below this
# is not part of the pinned scope (discover.sh probes before pinning; build
# re-checks on the full file).
MIN_VALID_FRACTION = 0.30

EXPECTED_FMT = {}
for _k in range(1, SPOTS + 1):
    EXPECTED_FMT[f"RADIUS_{_k}"] = (RADIUS_OFFSET + 1 + SPOT_STRIDE * (_k - 1), 4, "LSB_INTEGER")
    EXPECTED_FMT[f"RANGE_{_k}"] = (
        RANGE_OFFSET + 1 + SPOT_STRIDE * (_k - 1),
        4,
        "LSB_INTEGER" if _k == 3 else "LSB_UNSIGNED_INTEGER",
    )
    EXPECTED_FMT[f"SHOT_FLAG_{_k}"] = (FLAG_OFFSET + 1 + SPOT_STRIDE * (_k - 1), 4, "LSB_UNSIGNED_INTEGER")

# One struct per record: 5 x (radius int32, range uint32, flag uint32).
_parts = ["<"]
_pos = 0
for _k in range(SPOTS):
    base = SPOT_STRIDE * _k
    for off, code in ((RADIUS_OFFSET, "i"), (RANGE_OFFSET, "I"), (FLAG_OFFSET, "I")):
        target = base + off
        if target > _pos:
            _parts.append(f"{target - _pos}x")
        _parts.append(code)
        _pos = target + 4
_parts.append(f"{RECORD_BYTES - _pos}x")
RECORD_STRUCT = struct.Struct("".join(_parts))
assert RECORD_STRUCT.size == RECORD_BYTES


def parse_fmt(text: str) -> dict[str, dict[str, str]]:
    """Parse PDS3 COLUMN objects of a .fmt file into NAME -> {KEY: value}."""
    columns: dict[str, dict[str, str]] = {}
    current: dict[str, str] | None = None
    for raw in text.splitlines():
        line = raw.strip()
        if re.match(r"^OBJECT\s*=\s*COLUMN$", line):
            current = {}
            continue
        if re.match(r"^END_OBJECT\s*=\s*COLUMN$", line):
            if current is not None and "NAME" in current:
                columns[current["NAME"]] = current
            current = None
            continue
        if current is None:
            continue
        m = re.match(r"^([A-Z_]+)\s*=\s*(.*)$", line)
        if m and m.group(1) in {"NAME", "START_BYTE", "BYTES", "DATA_TYPE", "MISSING_CONSTANT", "UNIT", "COLUMN_NUMBER"}:
            current[m.group(1)] = m.group(2).strip().strip("'\"")
    return columns


def check_fmt_text(text: str) -> None:
    cols = parse_fmt(text)
    if len(cols) != 66:
        raise SystemExit(f"lolardr.fmt: expected 66 columns, parsed {len(cols)}")
    for name, (start, nbytes, dtype) in EXPECTED_FMT.items():
        col = cols.get(name)
        if col is None:
            raise SystemExit(f"lolardr.fmt: column {name} missing")
        if int(col["START_BYTE"]) != start or int(col["BYTES"]) != nbytes or col["DATA_TYPE"] != dtype:
            raise SystemExit(f"lolardr.fmt: {name} is {col}, expected START_BYTE={start} BYTES={nbytes} {dtype}")
        if name.startswith(("RADIUS_", "RANGE_")) and col.get("UNIT") != "MILLIMETERS":
            raise SystemExit(f"lolardr.fmt: {name} unit {col.get('UNIT')!r}, expected MILLIMETERS")
        if name.startswith("RADIUS_") and col.get("MISSING_CONSTANT") != "-1":
            raise SystemExit(f"lolardr.fmt: {name} MISSING_CONSTANT {col.get('MISSING_CONSTANT')!r}")
        if name.startswith("RANGE_") and col.get("MISSING_CONSTANT") not in (None, "-1", "4294967295"):
            raise SystemExit(f"lolardr.fmt: {name} MISSING_CONSTANT {col.get('MISSING_CONSTANT')!r}")
    last = max(int(c["START_BYTE"]) + int(c["BYTES"]) - 1 for c in cols.values())
    if last != RECORD_BYTES:
        raise SystemExit(f"lolardr.fmt: last byte {last} != {RECORD_BYTES}")


def decode_records(data: bytes | memoryview):
    """Yield (radius, range, flag) triples in shot-major, spot 1..5 order."""
    if len(data) % RECORD_BYTES:
        raise ValueError(f"length {len(data)} is not a multiple of {RECORD_BYTES}")
    for rec in RECORD_STRUCT.iter_unpack(data):
        for k in range(SPOTS):
            yield rec[3 * k], rec[3 * k + 1], rec[3 * k + 2]


def classify(radius: int, rng: int, flag: int) -> str:
    if radius == RADIUS_MISSING or rng == RANGE_MISSING:
        return "missing"
    if flag & FLAG_INVALID_MASK:
        return "flagged"
    return "kept"


def extract(data: bytes | memoryview) -> dict:
    """Apply the spot policy to a whole RDR file body."""
    radius_out: list[int] = []
    range_out: list[int] = []
    counts = {"missing": 0, "flagged": 0, "kept": 0}
    per_spot = [0] * SPOTS
    i = 0
    for radius, rng, flag in decode_records(data):
        c = classify(radius, rng, flag)
        counts[c] += 1
        if c == "kept":
            radius_out.append(radius)
            range_out.append(rng)
            per_spot[i % SPOTS] += 1
        i += 1
    return {"radius": radius_out, "range": range_out, "counts": counts, "per_spot": per_spot, "spots": i}


def sanity_errors(radius: list[int], rng: list[int]) -> list[str]:
    errors = []
    if radius:
        lo, hi = min(radius), max(radius)
        if lo < RADIUS_SANITY[0] or hi > RADIUS_SANITY[1]:
            errors.append(f"kept RADIUS outside {RADIUS_SANITY}: {lo}..{hi}")
    if rng:
        lo, hi = min(rng), max(rng)
        if hi > INT32_MAX:
            errors.append(f"kept RANGE {hi} does not fit int32")
        if lo < RANGE_SANITY[0] or hi > RANGE_SANITY[1]:
            errors.append(f"kept RANGE outside {RANGE_SANITY}: {lo}..{hi}")
    return errors


def read_sources(path: Path) -> list[dict[str, str]]:
    lines = path.read_text(encoding="utf-8").splitlines()
    header = lines[0].split("\t")
    rows = [dict(zip(header, line.split("\t"))) for line in lines[1:] if line.strip()]
    for row in rows:
        if len(row) != len(header):
            raise SystemExit(f"{path}: malformed row {row}")
    return rows


def source_row(sources: Path, name: str) -> dict[str, str]:
    for row in read_sources(sources):
        if row["file"] == name:
            return row
    raise SystemExit(f"{name} not pinned in {sources}")


def label_fields(text: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    for raw in text.splitlines():
        m = re.match(r"^\s*(\^?[A-Z_:]+)\s*=\s*(.*?)\s*$", raw)
        if m and m.group(1) not in fields:
            fields[m.group(1)] = m.group(2).strip('"').strip()
    return fields


def check_label_text(text: str, row: dict[str, str]) -> dict[str, str]:
    f = label_fields(text)
    stem = row["file"][: -len(".dat")].upper()
    expect = {
        "PDS_VERSION_ID": "PDS3",
        "FILE_NAME": f"{stem}.DAT",
        "RECORD_TYPE": "FIXED_LENGTH",
        "RECORD_BYTES": "256",
        "FILE_RECORDS": row["records"],
        "ROWS": row["records"],
        "ROW_BYTES": "256",
        "COLUMNS": "66",
        "DATA_SET_ID": "LRO-L-LOLA-3-RDR-V1.0",
        "INSTRUMENT_ID": "LOLA",
        "TARGET_NAME": "MOON",
        "INTERCHANGE_FORMAT": "BINARY",
        "^STRUCTURE": "LOLARDR.FMT",
        "MISSION_PHASE_NAME": row["mission_phase_name"],
    }
    for key, value in expect.items():
        if f.get(key) != value:
            raise SystemExit(f"{row['file']} label: {key}={f.get(key)!r}, expected {value!r}")
    return f


def md5_file(path: Path) -> str:
    h = hashlib.md5()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def check_dat(path: Path, row: dict[str, str]) -> dict:
    size = path.stat().st_size
    if size != int(row["dat_bytes"]):
        raise SystemExit(f"{row['file']}: {size} bytes, pinned {row['dat_bytes']}")
    if size != int(row["records"]) * RECORD_BYTES:
        raise SystemExit(f"{row['file']}: size is not records * 256")
    digest = md5_file(path)
    if digest != row["dat_md5"]:
        raise SystemExit(f"{row['file']}: MD5 {digest}, pinned {row['dat_md5']}")
    result = extract(path.read_bytes())
    frac = result["counts"]["kept"] / result["spots"]
    if frac < MIN_VALID_FRACTION:
        raise SystemExit(f"{row['file']}: kept-spot fraction {frac:.4f} < {MIN_VALID_FRACTION}")
    errors = sanity_errors(result["radius"], result["range"])
    if errors:
        raise SystemExit(f"{row['file']}: " + "; ".join(errors))
    result["valid_fraction"] = frac
    return result


# ----------------------------------------------------------------- self-test

def _synthetic_record(spots: list[tuple[int, int, int]], filler: int) -> bytes:
    """Build one 256-byte record by writing each field at START_BYTE - 1 taken
    from the expected fmt table (independent of RECORD_STRUCT), with every
    other byte set to a filler pattern."""
    rec = bytearray((filler + i) & 0xFF for i in range(RECORD_BYTES))
    for k, (radius, rng, flag) in enumerate(spots, 1):
        struct.pack_into("<i", rec, EXPECTED_FMT[f"RADIUS_{k}"][0] - 1, radius)
        struct.pack_into("<I", rec, EXPECTED_FMT[f"RANGE_{k}"][0] - 1, rng & 0xFFFFFFFF)
        struct.pack_into("<I", rec, EXPECTED_FMT[f"SHOT_FLAG_{k}"][0] - 1, flag)
    return bytes(rec)


SYNTHETIC_FMT = "\n".join(
    "OBJECT = COLUMN\n NAME = {n}\n START_BYTE = {s}\n BYTES = {b}\n DATA_TYPE = {t}\n{u}{m}END_OBJECT = COLUMN".format(
        n=name,
        s=s,
        b=b,
        t=t,
        u=" UNIT = 'MILLIMETERS'\n" if name.startswith(("RADIUS", "RANGE")) else "",
        m=" MISSING_CONSTANT = -1\n" if name.startswith("RADIUS") else "",
    )
    for name, (s, b, t) in EXPECTED_FMT.items()
)


def self_test() -> None:
    shots = [
        [(1737400000, 50000000, 0), (-1, 0xFFFFFFFF, 0x5F), (1737400123, 50000456, 0x10000), (1737401000, 50001000, 0x40), (1737402000, 0xFFFFFFFF, 0)],
        [(1748200000, 30000000, 0x300), (1728300000, 70000000, 0), (-1, 50000000, 0), (1737000000, 51000000, 0x01), (1736000000, 52000000, 0xFFFF0000)],
    ]
    data = b"".join(_synthetic_record(s, 7 * i) for i, s in enumerate(shots))
    triples = list(decode_records(data))
    flat = [(r, g & 0xFFFFFFFF, f) for shot in shots for (r, g, f) in shot]
    assert triples == flat, (triples, flat)
    out = extract(data)
    assert out["radius"] == [1737400000, 1737400123, 1748200000, 1728300000, 1736000000], out
    assert out["range"] == [50000000, 50000456, 30000000, 70000000, 52000000], out
    assert out["counts"] == {"missing": 3, "flagged": 2, "kept": 5}, out
    assert out["per_spot"] == [2, 1, 1, 0, 1], out
    assert sanity_errors(out["radius"], out["range"]) == []
    assert sanity_errors([1810000000], [50000000]), "off-surface radius must fail sanity"
    assert sanity_errors([1737000000], [2**31]), "range >= 2^31 must fail"
    # Offsets cross-check against an fmt-shaped column table.
    cols = parse_fmt(SYNTHETIC_FMT)
    for name, (s, b, t) in EXPECTED_FMT.items():
        assert int(cols[name]["START_BYTE"]) == s and cols[name]["DATA_TYPE"] == t
    assert EXPECTED_FMT["RADIUS_1"][0] == 49 and EXPECTED_FMT["RANGE_1"][0] == 53 and EXPECTED_FMT["SHOT_FLAG_1"][0] == 77
    assert EXPECTED_FMT["RADIUS_5"][0] == 209 and EXPECTED_FMT["RANGE_5"][0] == 213 and EXPECTED_FMT["SHOT_FLAG_5"][0] == 237
    try:
        list(decode_records(data[:-1]))
    except ValueError:
        pass
    else:
        raise AssertionError("truncated record accepted")
    print("lola_rdr self-test ok")


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("self-test")
    p = sub.add_parser("check-fmt")
    p.add_argument("--fmt", type=Path, required=True)
    p = sub.add_parser("check-label")
    p.add_argument("--sources", type=Path, required=True)
    p.add_argument("--file", required=True)
    p.add_argument("--label", type=Path, required=True)
    p = sub.add_parser("check-dat")
    p.add_argument("--sources", type=Path, required=True)
    p.add_argument("--file", required=True)
    p.add_argument("--dat", type=Path, required=True)
    args = ap.parse_args(argv)
    if args.cmd == "self-test":
        self_test()
    elif args.cmd == "check-fmt":
        check_fmt_text(args.fmt.read_text(encoding="ascii"))
        print(f"check-fmt ok {args.fmt.name}")
    elif args.cmd == "check-label":
        row = source_row(args.sources, args.file)
        if md5_file(args.label) != row["lbl_md5"]:
            raise SystemExit(f"{args.label}: MD5 differs from pin {row['lbl_md5']}")
        check_label_text(args.label.read_text(encoding="ascii", errors="replace"), row)
    elif args.cmd == "check-dat":
        row = source_row(args.sources, args.file)
        r = check_dat(args.dat, row)
        print(
            f"check-dat ok {args.file} spots={r['spots']} kept={r['counts']['kept']} "
            f"missing={r['counts']['missing']} flagged={r['counts']['flagged']} valid_fraction={r['valid_fraction']:.4f}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
