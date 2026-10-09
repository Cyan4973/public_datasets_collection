#!/usr/bin/env python3
"""Shared helpers for nasa_pds_cassini_iss_nac_lut8_raw_u8 (pure standard library).

- PDS3 volume index parsing (fixed-width, column geometry read from index.lbl)
- the frame selection rule (applied identically by discover, download, build)
- VICAR label parsing and image decode for Cassini ISS EDR frames
- the deterministic per-frame exclusion rule shared by build and verify
"""
from __future__ import annotations

import hashlib
import re
from collections import Counter
from pathlib import Path

DATASET_ID = "nasa_pds_cassini_iss_nac_lut8_raw_u8"
SERIES_ID = "cassini_issna_table8_full_dn_u8"
VOLUMES = ["COISS_2050", "COISS_2051", "COISS_2052"]
BASE = "https://planetarydata.jpl.nasa.gov/img/data/cassini/cassini_orbiter"
INDEX_ROW_BYTES = 3057
LINES = 1024
SAMPLES = 1024
FRAME_VALUES = LINES * SAMPLES
PER_OBSERVATION_CAP = 10
# Exclusion rule (build and verify): drop a frame if one DN value holds more than
# half of its pixels, or if it has fewer than 16 distinct DN values.
MAX_MODE_SHARE = 0.5
MIN_DISTINCT = 16

SOURCE_FIELDS = [
    "volume", "file_specification_name", "product", "image_number", "observation_id", "target_name",
    "target_desc", "filter_name", "exposure_ms", "image_time", "img_url", "img_size", "img_md5",
]


class FrameError(Exception):
    pass


def volume_url(volume: str) -> str:
    return f"{BASE}/{volume.lower()}"


# --------------------------------------------------------------------------- index


def index_columns(label_text: str) -> tuple[int, int, list[tuple[str, int, int]]]:
    """Return (rows, row_bytes, [(name, start_byte_1based, bytes)]) from a PDS3 index.lbl."""
    rows = int(re.search(r"^\s*ROWS\s*=\s*(\d+)", label_text, re.M).group(1))
    row_bytes = int(re.search(r"^\s*ROW_BYTES\s*=\s*(\d+)", label_text, re.M).group(1))
    cols = []
    for block in re.findall(r"OBJECT\s*=\s*COLUMN(.*?)END_OBJECT\s*=\s*COLUMN", label_text, flags=re.S):
        name = re.search(r"\bNAME\s*=\s*(\S+)", block).group(1)
        start = int(re.search(r"\bSTART_BYTE\s*=\s*(\d+)", block).group(1))
        width = int(re.search(r"\bBYTES\s*=\s*(\d+)", block).group(1))
        cols.append((name, start, width))
    return rows, row_bytes, cols


def parse_index(tab: bytes, label_text: str, volume: str) -> list[dict]:
    rows, row_bytes, cols = index_columns(label_text)
    if row_bytes != INDEX_ROW_BYTES:
        raise FrameError(f"{volume} index ROW_BYTES {row_bytes} != {INDEX_ROW_BYTES}")
    if len(tab) != rows * row_bytes:
        raise FrameError(f"{volume} index.tab is {len(tab)} bytes, label says {rows} x {row_bytes}")
    out = []
    for i in range(rows):
        record = tab[i * row_bytes:(i + 1) * row_bytes]
        if record[-2:] != b"\r\n":
            raise FrameError(f"{volume} index row {i} lacks CRLF terminator")
        text = record.decode("ascii")
        row = {name: text[start - 1:start - 1 + width].strip().strip('"').strip() for name, start, width in cols}
        if row["VOLUME_ID"] != volume:
            raise FrameError(f"{volume} index row {i} has VOLUME_ID {row['VOLUME_ID']!r}")
        row["_volume"] = volume
        row["_row"] = i
        out.append(row)
    return out


def eligible(row: dict) -> bool:
    return (
        row["INSTRUMENT_ID"] == "ISSNA"
        and row["DATA_CONVERSION_TYPE"] == "TABLE"
        and row["INSTRUMENT_MODE_ID"] == "FULL"
        and row["INST_CMPRS_TYPE"] == "LOSSLESS"
        and row["MISSING_LINES"] == "0"
        and row["MISSING_PACKET_FLAG"] == "NO"
        and row["GAIN_MODE_ID"] == "29 ELECTRONS PER DN"
        and row["IMAGE_OBSERVATION_TYPE"] == "SCIENCE"
        and row["PRODUCT_TYPE"] == "EDR"
        and row["TARGET_NAME"] != "SKY"
        and "SATELLORB" not in row["OBSERVATION_ID"]
        and row["OBSERVATION_ID"] not in ("", "N/A")
    )


def select(rows: list[dict]) -> list[dict]:
    """Eligible rows (volume order, then index row order), at most PER_OBSERVATION_CAP per
    OBSERVATION_ID, taken at evenly spaced positions within each observation."""
    pool = [r for r in rows if eligible(r)]
    groups: dict[str, list[int]] = {}
    for pos, row in enumerate(pool):
        groups.setdefault(row["OBSERVATION_ID"], []).append(pos)
    keep: set[int] = set()
    for positions in groups.values():
        n = len(positions)
        m = min(n, PER_OBSERVATION_CAP)
        for j in range(m):
            keep.add(positions[((2 * j + 1) * n) // (2 * m)])
    return [pool[p] for p in sorted(keep)]


def product_of(row: dict) -> str:
    name = row["FILE_NAME"]
    if not name.endswith(".IMG"):
        raise FrameError(f"unexpected FILE_NAME {name!r}")
    return name[:-4]


def selection_keys(rows: list[dict]) -> list[tuple[str, str, str]]:
    return [(r["_volume"], r["FILE_SPECIFICATION_NAME"], r["IMAGE_NUMBER"]) for r in rows]


def read_sources(path: Path) -> list[dict]:
    lines = path.read_text(encoding="utf-8").splitlines()
    header = lines[0].split("\t")
    if header != SOURCE_FIELDS:
        raise FrameError(f"{path.name}: unexpected header {header}")
    return [dict(zip(header, line.split("\t"))) for line in lines[1:] if line]


# --------------------------------------------------------------------------- VICAR

_TOKEN = re.compile(r"\s*([A-Z0-9_]+)=('(?:[^']|'')*'|\([^)]*\)|[^\s]+)")


def vicar_label(raw: bytes) -> dict:
    head = raw[:64].decode("ascii", errors="replace")
    m = re.match(r"LBLSIZE=\s*(\d+)\s", head)
    if not m:
        raise FrameError("no VICAR LBLSIZE at file start")
    lblsize = int(m.group(1))
    if lblsize <= 0 or lblsize > len(raw):
        raise FrameError(f"bad LBLSIZE {lblsize}")
    text = raw[:lblsize].split(b"\x00", 1)[0].decode("ascii")
    label: dict = {}
    pos = 0
    while True:
        tm = _TOKEN.match(text, pos)
        if not tm:
            break
        key, value = tm.group(1), tm.group(2)
        if value.startswith("'"):
            value = value[1:-1].replace("''", "'")
        label.setdefault(key, value)  # first occurrence wins (system label precedes history)
        pos = tm.end()
    if text[pos:].strip():
        raise FrameError(f"unparsed VICAR label tail {text[pos:pos + 40]!r}")
    label["LBLSIZE"] = str(lblsize)
    return label


def expect(label: dict, key: str, value: str, where: str) -> None:
    if label.get(key) != value:
        raise FrameError(f"{where}: VICAR {key}={label.get(key)!r}, expected {value!r}")


def decode(raw: bytes, product: str, image_number: str) -> tuple[bytes, dict]:
    """Return (1,048,576 uint8 DN bytes, stats) for one Cassini ISS NAC TABLE/FULL EDR."""
    lab = vicar_label(raw)
    for key, value in (("FORMAT", "BYTE"), ("TYPE", "IMAGE"), ("ORG", "BSQ"), ("NB", "1"), ("EOL", "0"),
                       ("INSTRUMENT_ID", "ISSNA"), ("INSTRUMENT_MODE_ID", "FULL"),
                       ("DATA_CONVERSION_TYPE", "TABLE"), ("INST_CMPRS_TYPE", "LOSSLESS"),
                       ("MISSING_LINES", "0"), ("GAIN_MODE_ID", "29 ELECTRONS PER DN"),
                       ("BINTFMT", "HIGH"), ("IMAGE_NUMBER", image_number)):
        expect(lab, key, value, product)
    lblsize = int(lab["LBLSIZE"])
    recsize, nl, ns = int(lab["RECSIZE"]), int(lab["NL"]), int(lab["NS"])
    nbb, nlb = int(lab["NBB"]), int(lab["NLB"])
    if (nl, ns) != (LINES, SAMPLES):
        raise FrameError(f"{product}: NL x NS = {nl} x {ns}")
    if recsize != nbb + ns:
        raise FrameError(f"{product}: RECSIZE {recsize} != NBB {nbb} + NS {ns}")
    if nbb < 2:
        raise FrameError(f"{product}: NBB {nbb} too small for a line-number prefix")
    start = lblsize + nlb * recsize
    if len(raw) != start + nl * recsize:
        raise FrameError(f"{product}: file is {len(raw)} bytes, VICAR layout implies {start + nl * recsize}")
    pixels = bytearray()
    bad_prefix = 0
    for line in range(nl):
        rec = raw[start + line * recsize:start + (line + 1) * recsize]
        if int.from_bytes(rec[0:2], "big") != line + 1:
            bad_prefix += 1
        pixels += rec[nbb:]
    if bad_prefix:
        raise FrameError(f"{product}: {bad_prefix} line prefixes do not carry the expected line number")
    pixels = bytes(pixels)
    if len(pixels) != FRAME_VALUES:
        raise FrameError(f"{product}: decoded {len(pixels)} bytes")
    hist = Counter(pixels)
    mode_value, mode_count = hist.most_common(1)[0]
    stats = {
        "lblsize": lblsize,
        "recsize": recsize,
        "nbb": nbb,
        "nlb": nlb,
        "minimum": min(hist),
        "maximum": max(hist),
        "mean": round(sum(v * c for v, c in hist.items()) / FRAME_VALUES, 4),
        "distinct_values": len(hist),
        "mode_value": mode_value,
        "mode_share": round(mode_count / FRAME_VALUES, 6),
        "zero_pixels": hist.get(0, 0),
        "saturated_pixels": hist.get(255, 0),
        "histogram": [hist.get(v, 0) for v in range(256)],
        "exposure_ms": lab.get("EXPOSURE_DURATION"),
        "filter_name": lab.get("FILTER_NAME"),
        "observation_id": lab.get("OBSERVATION_ID"),
        "target_name": lab.get("TARGET_NAME"),
    }
    return pixels, stats


def excluded_reason(stats: dict) -> str:
    if stats["mode_share"] > MAX_MODE_SHARE:
        return f"mode_share {stats['mode_share']} > {MAX_MODE_SHARE} (DN {stats['mode_value']})"
    if stats["distinct_values"] < MIN_DISTINCT:
        return f"distinct_values {stats['distinct_values']} < {MIN_DISTINCT}"
    return ""


def digests(blob: bytes) -> tuple[str, str]:
    return hashlib.md5(blob).hexdigest(), hashlib.sha256(blob).hexdigest()
