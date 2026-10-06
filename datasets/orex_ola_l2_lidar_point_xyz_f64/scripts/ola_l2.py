#!/usr/bin/env python3
"""OSIRIS-REx OLA L2 (data_calibrated_v2) PDS4 label and table helpers.

Standard library only. Network I/O is done by curl in the shell scripts; this
module only parses files that curl already fetched.

Subcommands
  self-test       parse a synthetic label and table and check every rule below
  select          build sources.tsv from fetched phase listings and labels
                  (scope rule: data_calibrated_v2 recon_b + recon_c products
                  whose label file_size is below 200,000,000 bytes)
  check-inventory check that every pinned LIDVID is a primary member of the
                  pinned data_calibrated_v2 collection inventory
  check-label     validate one fetched label against its sources.tsv row
  check-dat       validate one fetched .dat table against its label and row
  sample-flags    tabulate flag_status / laser / scan mode from a multipart
                  byte-range response (discovery evidence only)

Label rules (all fatal when violated): Product_Observational with LID
urn:nasa:pds:orex.ola:data_calibrated_v2:<product>.dat (the LIDVID, including
version_id, is pinned in sources.tsv and must be listed in the pinned
collection inventory);
exactly one Table_Binary at offset 0 with 0 groups, record_length 186 and 23
Field_Binary entries; x, y, z at field_location 115, 123, 131 as
IEEE754LSBDouble, 8 bytes, unit m; file_size == records * 186. The location
and data type of flag_status, laser_selection and scan_mode are read from the
label; the flag_status semantics are parsed from its description and must give
exactly {0, 1, 100, 101} = valid return and {2, 3, 102, 103} = no return or
missing sample.
"""
from __future__ import annotations

import argparse
import collections
import csv
import hashlib
import html
import json
import math
import os
import re
import struct
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

PDS_NS = "http://pds.nasa.gov/pds4/pds/v1"
NS = {"p": PDS_NS}
COLLECTION_LID = "urn:nasa:pds:orex.ola:data_calibrated_v2"
RECORD_LENGTH = 186
FIELD_COUNT = 23
XYZ_LOCATIONS = {"x": 115, "y": 123, "z": 131}
EXPECTED_KEEP = {0, 1, 100, 101}
EXPECTED_DROP = {2, 3, 102, 103}
SCOPE_PHASES = ("recon_b", "recon_c")
SIZE_LIMIT_BYTES = 200_000_000
PRODUCT_RE = re.compile(r"^(\d{8})_ola_scil2id(\d{5})$")
MET_RE = re.compile(rb"^\d/\d{10}\.\d{5}$")
RADIUS_BAND_M = (150.0, 350.0)
MAX_OUT_OF_BAND_FRACTION = 0.01
MIN_VALID_FRACTION = 0.90
SOURCES_COLUMNS = [
    "phase",
    "product",
    "lidvid",
    "records",
    "dat_bytes",
    "label_bytes",
    "label_sha256",
    "start_utc",
    "stop_utc",
]
INT_TYPES = {
    "SignedLSB2": "<h",
    "UnsignedLSB2": "<H",
    "SignedLSB4": "<i",
    "UnsignedLSB4": "<I",
    "SignedByte": "<b",
    "UnsignedByte": "<B",
}


class LabelError(Exception):
    pass


def _text(node, path: str) -> str:
    value = node.findtext(path, namespaces=NS)
    if value is None:
        raise LabelError(f"label element missing: {path}")
    return value.strip()


def parse_codes(description: str) -> dict[int, str]:
    """Parse '(0: valid return 1: ... 103: missing sample, demodulator on)'."""
    match = re.search(r"\(([^()]*)\)\s*$", " ".join(description.split()))
    if not match:
        raise LabelError("no parenthesised code list in description")
    pairs = re.findall(r"(\d+):\s*(.*?)(?=\s+\d+:|$)", match.group(1))
    codes = {int(code): meaning.strip().rstrip(",;").strip().lower() for code, meaning in pairs}
    if not codes:
        raise LabelError("empty code list")
    return codes


def classify_flags(description: str) -> tuple[set[int], set[int]]:
    keep: set[int] = set()
    drop: set[int] = set()
    for code, meaning in parse_codes(description).items():
        if meaning.startswith("valid return"):
            keep.add(code)
        elif meaning.startswith("no return") or meaning.startswith("missing sample"):
            drop.add(code)
        else:
            raise LabelError(f"flag_status code {code} has unrecognised meaning {meaning!r}")
    if keep != EXPECTED_KEEP or drop != EXPECTED_DROP:
        raise LabelError(f"flag_status semantics changed: keep={sorted(keep)} drop={sorted(drop)}")
    return keep, drop


def parse_label(path: Path, product: str | None = None) -> dict:
    root = ET.parse(path).getroot()
    if root.tag != f"{{{PDS_NS}}}Product_Observational":
        raise LabelError(f"root element {root.tag} is not Product_Observational")
    lid = _text(root, "p:Identification_Area/p:logical_identifier")
    vid = _text(root, "p:Identification_Area/p:version_id")
    area = root.find("p:File_Area_Observational", NS)
    if area is None:
        raise LabelError("no File_Area_Observational")
    file_name = _text(area, "p:File/p:file_name")
    stem = file_name[: -len(".dat")] if file_name.endswith(".dat") else ""
    if not PRODUCT_RE.match(stem):
        raise LabelError(f"unexpected file_name {file_name}")
    if product is not None and stem != product:
        raise LabelError(f"file_name {file_name} does not belong to product {product}")
    if lid != f"{COLLECTION_LID}:{file_name}":
        raise LabelError(f"logical_identifier {lid} is not in {COLLECTION_LID}")
    if not re.fullmatch(r"\d+\.\d+", vid):
        raise LabelError(f"malformed version_id {vid}")
    file_size = int(_text(area, "p:File/p:file_size"))
    tables = area.findall("p:Table_Binary", NS)
    if len(tables) != 1 or len(list(area)) != 2:
        raise LabelError("File_Area_Observational must hold exactly one File and one Table_Binary")
    table = tables[0]
    offset = int(_text(table, "p:offset"))
    records = int(_text(table, "p:records"))
    record = table.find("p:Record_Binary", NS)
    if record is None:
        raise LabelError("no Record_Binary")
    n_fields = int(_text(record, "p:fields"))
    groups = int(_text(record, "p:groups"))
    record_length = int(_text(record, "p:record_length"))
    if offset != 0 or groups != 0 or record_length != RECORD_LENGTH or n_fields != FIELD_COUNT:
        raise LabelError(
            f"table layout offset={offset} groups={groups} record_length={record_length} fields={n_fields}"
        )
    fields: dict[str, dict] = {}
    for node in record.findall("p:Field_Binary", NS):
        name = _text(node, "p:name")
        if name in fields:
            raise LabelError(f"duplicate field {name}")
        fields[name] = {
            "number": int(_text(node, "p:field_number")),
            "location": int(_text(node, "p:field_location")),
            "data_type": _text(node, "p:data_type"),
            "length": int(_text(node, "p:field_length")),
            "unit": (node.findtext("p:unit", namespaces=NS) or "").strip(),
            "description": " ".join((node.findtext("p:description", namespaces=NS) or "").split()),
        }
    if len(fields) != n_fields:
        raise LabelError(f"{len(fields)} Field_Binary entries != fields {n_fields}")
    for field in fields.values():
        if field["location"] < 1 or field["location"] + field["length"] - 1 > record_length:
            raise LabelError("field extends beyond the record")
    for axis, location in XYZ_LOCATIONS.items():
        field = fields.get(axis)
        if field is None or (field["location"], field["data_type"], field["length"], field["unit"]) != (
            location,
            "IEEE754LSBDouble",
            8,
            "m",
        ):
            raise LabelError(f"field {axis} is not an 8-byte IEEE754LSBDouble in m at byte {location}: {field}")
    int_fields = {}
    for name in ("flag_status", "laser_selection", "scan_mode"):
        field = fields.get(name)
        if field is None or field["data_type"] not in INT_TYPES:
            raise LabelError(f"field {name} missing or not an integer type: {field}")
        fmt = INT_TYPES[field["data_type"]]
        if struct.calcsize(fmt) != field["length"]:
            raise LabelError(f"field {name} length {field['length']} != {field['data_type']}")
        int_fields[name] = {"offset": field["location"] - 1, "format": fmt}
    keep, drop = classify_flags(fields["flag_status"]["description"])
    scan_codes = parse_codes(fields["scan_mode"]["description"])
    linear = [code for code, meaning in scan_codes.items() if meaning == "linear"]
    laser = re.search(r"High Energy \((\d+)\)", fields["laser_selection"]["description"])
    if len(linear) != 1 or laser is None:
        raise LabelError("cannot resolve the Linear scan_mode code or the High Energy laser code from the label")
    if fields["met"]["location"] != 1 or fields["met"]["length"] != 18 or fields["met"]["data_type"] != "ASCII_String":
        raise LabelError("met is not an 18-byte ASCII_String at byte 1")
    if file_size != records * record_length:
        raise LabelError(f"file_size {file_size} != records {records} * {record_length}")
    return {
        "product": stem,
        "lidvid": f"{lid}::{vid}",
        "file_name": file_name,
        "file_size": file_size,
        "records": records,
        "record_length": record_length,
        "xyz_offset": XYZ_LOCATIONS["x"] - 1,
        "flag": int_fields["flag_status"],
        "laser": int_fields["laser_selection"],
        "scan": int_fields["scan_mode"],
        "keep_flags": keep,
        "drop_flags": drop,
        "linear_scan_code": linear[0],
        "high_energy_laser_code": int(laser.group(1)),
        "start_utc": _text(root, "p:Observation_Area/p:Time_Coordinates/p:start_date_time"),
        "stop_utc": _text(root, "p:Observation_Area/p:Time_Coordinates/p:stop_date_time"),
    }


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 22), b""):
            digest.update(block)
    return digest.hexdigest()


def load_sources(path: Path) -> list[dict]:
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        if reader.fieldnames != SOURCES_COLUMNS:
            raise SystemExit(f"{path}: columns {reader.fieldnames} != {SOURCES_COLUMNS}")
        rows = list(reader)
    for row in rows:
        for key in ("records", "dat_bytes", "label_bytes"):
            row[key] = int(row[key])
    return rows


def scan_table(label: dict, dat_path: Path, emit=None) -> dict:
    """Iterate every record; apply the shared missing-value policy.

    Returns per-file counts. When `emit` is given it is called with the raw
    24 x/y/z bytes of every kept record, in source order.
    """
    rl = label["record_length"]
    size = dat_path.stat().st_size
    if size != label["file_size"]:
        raise SystemExit(f"{dat_path}: size {size} != label file_size {label['file_size']}")
    flag_s = struct.Struct(label["flag"]["format"])
    laser_s = struct.Struct(label["laser"]["format"])
    scan_s = struct.Struct(label["scan"]["format"])
    xyz_s = struct.Struct("<3d")
    f_off, l_off, s_off, x_off = label["flag"]["offset"], label["laser"]["offset"], label["scan"]["offset"], label["xyz_offset"]
    keep, drop = label["keep_flags"], label["drop_flags"]
    hel, lin = label["high_energy_laser_code"], label["linear_scan_code"]
    lo, hi = RADIUS_BAND_M
    flags: collections.Counter = collections.Counter()
    modes: collections.Counter = collections.Counter()
    kept = out_of_band = 0
    r_min, r_max = math.inf, 0.0
    records = 0
    with dat_path.open("rb") as handle:
        while True:
            chunk = handle.read(rl * 32768)
            if not chunk:
                break
            if len(chunk) % rl:
                raise SystemExit(f"{dat_path}: trailing partial record")
            for off in range(0, len(chunk), rl):
                records += 1
                if not MET_RE.match(chunk[off : off + 18]):
                    raise SystemExit(f"{dat_path}: record {records} has a malformed met field {chunk[off:off + 18]!r}")
                flag = flag_s.unpack_from(chunk, off + f_off)[0]
                mode = (laser_s.unpack_from(chunk, off + l_off)[0], scan_s.unpack_from(chunk, off + s_off)[0])
                modes[mode] += 1
                flags[flag] += 1
                if flag in keep:
                    if mode != (hel, lin):
                        raise SystemExit(f"{dat_path}: record {records} laser/scan mode {mode} is not High Energy Linear")
                    x, y, z = xyz_s.unpack_from(chunk, off + x_off)
                    if not (math.isfinite(x) and math.isfinite(y) and math.isfinite(z)):
                        raise SystemExit(f"{dat_path}: record {records} has non-finite xyz with a valid flag")
                    radius = math.sqrt(x * x + y * y + z * z)
                    r_min = min(r_min, radius)
                    r_max = max(r_max, radius)
                    if not lo <= radius <= hi:
                        out_of_band += 1
                    kept += 1
                    if emit is not None:
                        emit(chunk[off + x_off : off + x_off + 24])
                elif flag not in drop:
                    raise SystemExit(f"{dat_path}: record {records} has undocumented flag_status {flag}")
    if records != label["records"]:
        raise SystemExit(f"{dat_path}: {records} records != label {label['records']}")
    if kept < MIN_VALID_FRACTION * records:
        raise SystemExit(f"{dat_path}: only {kept}/{records} valid returns (< {MIN_VALID_FRACTION:.0%})")
    if out_of_band > MAX_OUT_OF_BAND_FRACTION * kept:
        raise SystemExit(f"{dat_path}: {out_of_band}/{kept} kept points outside |xyz| {RADIUS_BAND_M} m")
    return {
        "records": records,
        "kept_points": kept,
        "flag_counts": {str(k): v for k, v in sorted(flags.items())},
        "mode_counts": {f"{k[0]},{k[1]}": v for k, v in sorted(modes.items())},
        "dropped_no_return": sum(v for k, v in flags.items() if k in (2, 102)),
        "dropped_missing_sample": sum(v for k, v in flags.items() if k in (3, 103)),
        "radius_m_min": r_min,
        "radius_m_max": r_max,
        "out_of_band_points": out_of_band,
    }


# ---------------------------------------------------------------- commands


def cmd_check_label(args) -> int:
    rows = {row["product"]: row for row in load_sources(args.sources)}
    row = rows.get(args.product)
    if row is None:
        raise SystemExit(f"{args.product} not pinned in sources.tsv")
    raw = args.label.read_bytes()
    if len(raw) != row["label_bytes"] or hashlib.sha256(raw).hexdigest() != row["label_sha256"]:
        raise SystemExit(f"{args.label}: label bytes/sha256 differ from sources.tsv")
    label = parse_label(args.label, args.product)
    if (label["records"], label["file_size"], label["lidvid"]) != (row["records"], row["dat_bytes"], row["lidvid"]):
        raise SystemExit(f"{args.label}: records/file_size/lidvid differ from sources.tsv")
    print(f"label_ok product={args.product} records={label['records']} file_size={label['file_size']}")
    return 0


def cmd_check_dat(args) -> int:
    rows = {row["product"]: row for row in load_sources(args.sources)}
    row = rows[args.product]
    label = parse_label(args.label, args.product)
    if args.dat.stat().st_size != row["dat_bytes"]:
        raise SystemExit(f"{args.dat}: size {args.dat.stat().st_size} != pinned {row['dat_bytes']}")
    stats = scan_table(label, args.dat)
    print(
        f"dat_ok product={args.product} records={stats['records']} kept={stats['kept_points']} "
        f"no_return={stats['dropped_no_return']} missing={stats['dropped_missing_sample']} "
        f"radius_m=[{stats['radius_m_min']:.2f},{stats['radius_m_max']:.2f}] out_of_band={stats['out_of_band_points']}"
    )
    return 0


def cmd_check_inventory(args) -> int:
    members = set()
    for line in args.inventory.read_text(encoding="ascii").splitlines():
        kind, _, lidvid = line.strip().partition(",")
        if kind == "P":
            members.add(lidvid)
    rows = load_sources(args.sources)
    missing = [row["lidvid"] for row in rows if row["lidvid"] not in members]
    if missing:
        raise SystemExit(f"pinned LIDVIDs not in the collection inventory: {missing[:5]}")
    print(f"inventory_ok members={len(members)} pinned={len(rows)}")
    return 0


def listing_products(listing: Path) -> list[str]:
    text = listing.read_text(encoding="utf-8", errors="replace")
    names = sorted({html.unescape(m) for m in re.findall(r'href="([^"/?]+)\.dat"', text)})
    bad = [name for name in names if not PRODUCT_RE.match(name)]
    if bad:
        raise SystemExit(f"{listing}: unexpected product names {bad[:5]}")
    return names


def cmd_list(args) -> int:
    for name in listing_products(args.listing):
        print(name)
    return 0


def cmd_select(args) -> int:
    out_rows = []
    excluded = []
    for phase in SCOPE_PHASES:
        for product in listing_products(args.discovery_dir / f"{phase}.html"):
            label_path = args.discovery_dir / "labels" / f"{product}.xml"
            label = parse_label(label_path, product)
            raw = label_path.read_bytes()
            if label["file_size"] >= SIZE_LIMIT_BYTES:
                excluded.append((phase, product, label["file_size"]))
                continue
            out_rows.append(
                {
                    "phase": phase,
                    "product": product,
                    "lidvid": label["lidvid"],
                    "records": label["records"],
                    "dat_bytes": label["file_size"],
                    "label_bytes": len(raw),
                    "label_sha256": hashlib.sha256(raw).hexdigest(),
                    "start_utc": label["start_utc"],
                    "stop_utc": label["stop_utc"],
                }
            )
    with args.out.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=SOURCES_COLUMNS, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(out_rows)
    for phase, product, size in excluded:
        print(f"excluded_by_size phase={phase} product={product} file_size={size}")
    print(
        f"selected={len(out_rows)} records={sum(r['records'] for r in out_rows)} "
        f"dat_bytes={sum(r['dat_bytes'] for r in out_rows)} label_bytes={sum(r['label_bytes'] for r in out_rows)}"
    )
    return 0


def cmd_sample_flags(args) -> int:
    label = parse_label(args.label)
    data = args.response.read_bytes()
    flags: collections.Counter = collections.Counter()
    modes: collections.Counter = collections.Counter()
    radii = []
    for match in re.finditer(rb"Content-range: bytes (\d+)-(\d+)/(\d+)\r\n\r\n", data, re.IGNORECASE):
        start = match.end()
        record = data[start : start + label["record_length"]]
        if len(record) < label["record_length"]:
            continue
        flag = struct.unpack_from(label["flag"]["format"], record, label["flag"]["offset"])[0]
        laser = struct.unpack_from(label["laser"]["format"], record, label["laser"]["offset"])[0]
        scan = struct.unpack_from(label["scan"]["format"], record, label["scan"]["offset"])[0]
        flags[flag] += 1
        modes[f"{laser},{scan}"] += 1
        if flag in label["keep_flags"]:
            x, y, z = struct.unpack_from("<3d", record, label["xyz_offset"])
            radii.append(math.sqrt(x * x + y * y + z * z))
    sampled = sum(flags.values())
    valid = sum(v for k, v in flags.items() if k in label["keep_flags"])
    print(
        "\t".join(
            [
                args.phase,
                label["product"],
                str(label["records"]),
                str(label["file_size"]),
                str(sampled),
                f"{valid / sampled:.3f}" if sampled else "nan",
                json.dumps(dict(sorted(flags.items())), separators=(",", ":")),
                json.dumps(dict(sorted(modes.items())), separators=(",", ":")),
                f"{min(radii):.1f}-{max(radii):.1f}" if radii else "-",
            ]
        )
    )
    return 0


# ---------------------------------------------------------------- self-test

SYNTH_FLAG_DESC = (
    "Status of return. Supplemented with additional information from the OLA state of health; "
    "indicating whether or not demodulator was on at the time of return. (0: valid return 1: valid "
    "return with overflow 2: no return 3: missing sample 100: valid return, demodulator on 101: valid "
    "return with overflow, demodulator on 102: no return, demodulator on 103: missing sample, demodulator on)"
)
SYNTH_FIELDS = [
    ("met", 1, "ASCII_String", 18, ""),
    ("met_offset", 19, "IEEE754LSBDouble", 8, "s/c_ticks"),
    ("utc", 27, "ASCII_String", 24, ""),
    ("et", 51, "IEEE754LSBDouble", 8, "s"),
    ("scan_ola_time", 59, "IEEE754LSBDouble", 8, "s"),
    ("power_cycle", 67, "SignedLSB2", 2, ""),
    ("laser_selection", 69, "SignedLSB2", 2, ""),
    ("scan_mode", 71, "SignedLSB2", 2, ""),
    ("flag_status", 73, "SignedLSB2", 2, ""),
    ("range", 75, "IEEE754LSBDouble", 8, "mm"),
    ("azimuth", 83, "IEEE754LSBDouble", 8, "mrad"),
    ("elevation", 91, "IEEE754LSBDouble", 8, "mrad"),
    ("intensity_t0", 99, "IEEE754LSBDouble", 8, "DN"),
    ("intensity_trr", 107, "IEEE754LSBDouble", 8, "DN"),
    ("x", 115, "IEEE754LSBDouble", 8, "m"),
    ("y", 123, "IEEE754LSBDouble", 8, "m"),
    ("z", 131, "IEEE754LSBDouble", 8, "m"),
    ("elongitude", 139, "IEEE754LSBDouble", 8, "deg"),
    ("latitude", 147, "IEEE754LSBDouble", 8, "deg"),
    ("radius", 155, "IEEE754LSBDouble", 8, "km"),
    ("scx", 163, "IEEE754LSBDouble", 8, "m"),
    ("scy", 171, "IEEE754LSBDouble", 8, "m"),
    ("scz", 179, "IEEE754LSBDouble", 8, "m"),
]


def synth_label(product: str, records: int, flag_desc: str = SYNTH_FLAG_DESC, x_location: int = 115) -> str:
    descriptions = {
        "flag_status": flag_desc,
        "laser_selection": "Specifies whether scan command applies to High Energy (0) or Low Energy Laser (1)",
        "scan_mode": "Selected Scan Pattern (0: Raster, 1: Linear, 2: Fixed)",
    }
    parts = []
    for number, (name, location, dtype, length, unit) in enumerate(SYNTH_FIELDS, start=1):
        if name == "x":
            location = x_location
        unit_xml = f"<unit>{unit}</unit>" if unit else ""
        parts.append(
            f"<Field_Binary><name>{name}</name><field_number>{number}</field_number>"
            f"<field_location unit=\"byte\">{location}</field_location><data_type>{dtype}</data_type>"
            f"<field_length unit=\"byte\">{length}</field_length>{unit_xml}"
            f"<description>{descriptions.get(name, name)}</description></Field_Binary>"
        )
    return (
        f'<?xml version="1.0" encoding="UTF-8"?>\n<Product_Observational xmlns="{PDS_NS}">'
        f"<Identification_Area><logical_identifier>{COLLECTION_LID}:{product}.dat</logical_identifier>"
        f"<version_id>2.0</version_id></Identification_Area>"
        f"<Observation_Area><Time_Coordinates><start_date_time>2020-01-01T00:00:00.000Z</start_date_time>"
        f"<stop_date_time>2020-01-01T00:10:00.000Z</stop_date_time></Time_Coordinates></Observation_Area>"
        f"<File_Area_Observational><File><file_name>{product}.dat</file_name>"
        f"<file_size unit=\"byte\">{records * RECORD_LENGTH}</file_size></File>"
        f"<Table_Binary><name>calibrated</name><offset unit=\"byte\">0</offset><records>{records}</records>"
        f"<Record_Binary><fields>23</fields><groups>0</groups><record_length unit=\"byte\">186</record_length>"
        + "".join(parts)
        + "</Record_Binary></Table_Binary></File_Area_Observational></Product_Observational>\n"
    )


def synth_record(index: int, flag: int, xyz: tuple[float, float, float], laser: int = 0, scan: int = 1) -> bytes:
    record = bytearray(RECORD_LENGTH)
    record[0:18] = f"3/{633430149 + index:010d}.{index % 100000:05d}".encode()
    record[26:50] = b"2020-027T20:50:04.903961"
    struct.pack_into("<hhhh", record, 66, 7, laser, scan, flag)
    struct.pack_into("<d", record, 74, -1128.922153 if flag in (2, 3, 102, 103) else 761552.47)
    struct.pack_into("<3d", record, 114, *xyz)
    struct.pack_into("<3d", record, 162, 500.0, -400.0, 300.0)
    return bytes(record)


def self_test() -> int:
    product = "20200101_ola_scil2id09999"
    points = [
        (0, (4.866024005, -201.2610081, -127.4323749)),
        (2, (1745.7065789795117, -852.4969938542159, 7425.275372880368)),
        (100, (-126.80654191803927, -79.98739186023187, -171.8057632788475)),
        (1, (63.29494977049649, 78.18588359471445, 200.88953328474395)),
        (102, (0.0, 0.0, 0.0)),
        (101, (-117.62690825545724, -84.13723609118415, 178.31523059647316)),
        (3, (9e9, 9e9, 9e9)),
    ]
    points += [(0, (200.0 + i * 0.001, -100.0 - i * 0.002, 50.0 + i * 0.003)) for i in range(40)]
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        label_path = tmp_path / f"{product}.xml"
        dat_path = tmp_path / f"{product}.dat"
        label_path.write_text(synth_label(product, len(points)), encoding="utf-8")
        dat_path.write_bytes(b"".join(synth_record(i, flag, xyz) for i, (flag, xyz) in enumerate(points)))
        label = parse_label(label_path, product)
        assert label["flag"] == {"offset": 72, "format": "<h"}, label["flag"]
        assert label["keep_flags"] == EXPECTED_KEEP and label["drop_flags"] == EXPECTED_DROP
        assert (label["high_energy_laser_code"], label["linear_scan_code"]) == (0, 1)
        emitted: list[bytes] = []
        stats = scan_table(label, dat_path, emitted.append)
        expected = [struct.pack("<3d", *xyz) for flag, xyz in points if flag in EXPECTED_KEEP]
        assert emitted == expected, "kept xyz bytes differ"
        assert stats["kept_points"] == len(expected) == 44, stats
        assert stats["dropped_no_return"] == 2 and stats["dropped_missing_sample"] == 1, stats
        # Rejections: undocumented flag, moved x field, changed semantics, wrong mode, short file.
        cases = []
        bad = dat_path.read_bytes()
        cases.append(("undocumented flag", label_path, bad[:72] + struct.pack("<h", 5) + bad[74:]))
        cases.append(("low energy raster record", label_path, synth_record(0, 0, (200.0, 1.0, 2.0), 1, 0) + bad[186:]))
        cases.append(("truncated table", label_path, bad[:-10]))
        for name, lpath, payload in cases:
            dat_path.write_bytes(payload)
            try:
                scan_table(parse_label(lpath, product), dat_path)
            except SystemExit:
                continue
            raise AssertionError(f"self-test: {name} was not rejected")
        dat_path.write_bytes(bad)
        for name, text in (
            ("moved x field", synth_label(product, len(points), x_location=114)),
            ("changed flag semantics", synth_label(product, len(points), SYNTH_FLAG_DESC.replace("2: no return", "2: valid return"))),
            ("wrong product", synth_label("20200101_ola_scil2id09998", len(points))),
        ):
            label_path.write_text(text, encoding="utf-8")
            try:
                parse_label(label_path, product)
            except LabelError:
                continue
            raise AssertionError(f"self-test: {name} was not rejected")
        # sample-flags parser on a synthetic multipart body.
        label_path.write_text(synth_label(product, len(points)), encoding="utf-8")
        body = b""
        for i in (0, 1, 2):
            body += b"--b\r\nContent-type: application/octet-stream\r\nContent-range: bytes %d-%d/%d\r\n\r\n" % (
                i * 186,
                i * 186 + 185,
                len(bad),
            )
            body += bad[i * 186 : (i + 1) * 186] + b"\r\n"
        (tmp_path / "mr.bin").write_bytes(body)
        captured = tmp_path / "flags.txt"
        saved = sys.stdout
        with captured.open("w", encoding="utf-8") as sink:
            sys.stdout = sink
            try:
                cmd_sample_flags(argparse.Namespace(phase="synthetic", label=label_path, response=tmp_path / "mr.bin"))
            finally:
                sys.stdout = saved
        columns = captured.read_text(encoding="utf-8").rstrip("\n").split("\t")
        assert columns[4] == "3" and columns[6] == '{"0":1,"2":1,"100":1}', columns
    print("self_test_ok kept=44 dropped=3 rejections=6 multipart=3")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("self-test")
    p = sub.add_parser("list")
    p.add_argument("--listing", type=Path, required=True)
    p = sub.add_parser("select")
    p.add_argument("--discovery-dir", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    p = sub.add_parser("check-inventory")
    p.add_argument("--sources", type=Path, required=True)
    p.add_argument("--inventory", type=Path, required=True)
    p = sub.add_parser("check-label")
    p.add_argument("--sources", type=Path, required=True)
    p.add_argument("--product", required=True)
    p.add_argument("--label", type=Path, required=True)
    p = sub.add_parser("check-dat")
    p.add_argument("--sources", type=Path, required=True)
    p.add_argument("--product", required=True)
    p.add_argument("--label", type=Path, required=True)
    p.add_argument("--dat", type=Path, required=True)
    p = sub.add_parser("sample-flags")
    p.add_argument("--phase", required=True)
    p.add_argument("--label", type=Path, required=True)
    p.add_argument("--response", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command == "self-test":
            return self_test()
        handler = {
            "list": cmd_list,
            "select": cmd_select,
            "check-inventory": cmd_check_inventory,
            "check-label": cmd_check_label,
            "check-dat": cmd_check_dat,
            "sample-flags": cmd_sample_flags,
        }[args.command]
        return handler(args)
    except LabelError as exc:
        raise SystemExit(f"label error: {exc}")


if __name__ == "__main__":
    sys.exit(main())
