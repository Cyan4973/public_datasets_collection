#!/usr/bin/env python3
"""Decode the WIOD 2016-release World Input-Output Tables (Stata release 118).

Subcommands:
  validate-metadata  check the version-pinned DataverseNL dataset JSON (license, file identity)
  validate-archive   check size, SHA-1, ZIP member table and every member's Stata header
  build              stream each yearly .dta member and emit one float64 matrix per year
  verify             re-decode the source independently and compare it with the samples
  selftest           exercise build/verify on a synthetic Stata-118 archive

Pure standard library. The yearly members are streamed from the ZIP; nothing is
extracted to disk.
"""
from __future__ import annotations

import argparse
import array
import hashlib
import json
import math
import operator
import os
import struct
import sys
import tempfile
import tomllib
import zipfile
from dataclasses import dataclass, field, replace
from pathlib import Path

DATASET_ID = "wiod2016_world_input_output_tables_f64"
SERIES_ID = "wiot_current_price_flows_f64"
NATURAL_RECORD_KIND = "wiod2016_annual_world_input_output_table"
DOI = "doi:10.34894/PJ2M1C"
DATASET_VERSION = (2, 1)
DATAFILE_ID = 199103
ARCHIVE_NAME = "WIOTS_in_STATA.zip"
ARCHIVE_BYTES = 638_963_496
ARCHIVE_SHA1 = "cde6085d4233fec2356877aedf21d950de912b78"
LICENSE_PHRASE = "licensed under a creative commons attribution 4.0 international"
LICENSE_URL = "creativecommons.org/licenses/by/4.0"

YEARS = tuple(range(2000, 2015))
MEMBER_TEMPLATE = "WIOT{year}_October16_ROW.dta"
MEMBER_BYTES = 55_216_235
MEMBER_CRC32 = {
    2000: 0x789841D6, 2001: 0x6EAD41D4, 2002: 0x40E8B823, 2003: 0xABAF15DC,
    2004: 0x3C438A10, 2005: 0xE4DE54A1, 2006: 0x21FCC93D, 2007: 0xFCD88B0E,
    2008: 0xBD2CE024, 2009: 0x4F446CC7, 2010: 0x057FFC65, 2011: 0x8F5B8104,
    2012: 0x73FD8546, 2013: 0xDDB45B8E, 2014: 0xB3730C3E,
}
COUNTRIES = (
    "AUS", "AUT", "BEL", "BGR", "BRA", "CAN", "CHE", "CHN", "CYP", "CZE", "DEU",
    "DNK", "ESP", "EST", "FIN", "FRA", "GBR", "GRC", "HRV", "HUN", "IDN", "IND",
    "IRL", "ITA", "JPN", "KOR", "LTU", "LUX", "LVA", "MEX", "MLT", "NLD", "NOR",
    "POL", "PRT", "ROU", "RUS", "SVK", "SVN", "SWE", "TUR", "TWN", "USA", "ROW",
)
N_INDUSTRIES = 56
N_FINAL_DEMAND = 5
FINAL_DEMAND_LABELS = ("CONS_h", "CONS_np", "GGFC", "GFCF", "INVEN")
SUMMARY_CODES = ("II_fob", "TXSP", "EXP_adj", "PURR", "PURNR", "VA", "IntTTM", "GO")
META_NAMES = ("IndustryCode", "IndustryDescription", "Country", "RNr", "Year")
META_TYPES = (7, 147, 3, 65530, 65529)  # str7, str147, str3, byte, int
META_STRUCT = "<7s147s3sbh"
TOTAL_NAME = "TOT"
ROW_WIDTH = 21_640

T_DOUBLE = 65526
NUMERIC_WIDTH = {65526: 8, 65527: 4, 65528: 4, 65529: 2, 65530: 1}
STATA_MISSING_MIN = 2.0 ** 1023  # 8.98846567431158e307: '.', '.a' .. '.z'
PLAUSIBLE_ABS_MAX = 1.0e9  # million US$; world gross output is ~2e8
HEADER_PREFIX = b"<stata_dta><header><release>118</release><byteorder>LSF</byteorder><K>"
NEG_ZERO_BITS = 1 << 63
HIGH_BYTES = bytes(range(0x80, 0x100))


class DtaError(ValueError):
    """Raised for malformed or semantically unexpected source content."""


@dataclass(frozen=True)
class Spec:
    countries: tuple[str, ...] = COUNTRIES
    n_industries: int = N_INDUSTRIES
    n_final: int = N_FINAL_DEMAND
    summary_codes: tuple[str, ...] = SUMMARY_CODES
    years: tuple[int, ...] = YEARS
    member_template: str = MEMBER_TEMPLATE
    member_bytes: int | None = MEMBER_BYTES
    member_crc32: dict[int, int] | None = field(default_factory=lambda: dict(MEMBER_CRC32))
    row_width: int | None = ROW_WIDTH
    archive_bytes: int | None = ARCHIVE_BYTES
    archive_sha1: str | None = ARCHIVE_SHA1
    dataset_id: str = DATASET_ID
    series_id: str = SERIES_ID

    @property
    def n_rows(self) -> int:
        return len(self.countries) * self.n_industries

    @property
    def n_cols(self) -> int:
        return len(self.countries) * (self.n_industries + self.n_final)

    @property
    def n_source_rows(self) -> int:
        return self.n_rows + len(self.summary_codes)

    def value_names(self) -> list[str]:
        names = [f"v{c}{i}" for c in self.countries for i in range(1, self.n_industries + 1)]
        names += [
            f"v{c}{i}"
            for c in self.countries
            for i in range(self.n_industries + 1, self.n_industries + self.n_final + 1)
        ]
        return names

    def all_names(self) -> list[str]:
        return list(META_NAMES) + self.value_names() + [TOTAL_NAME]

    def member(self, year: int) -> str:
        return self.member_template.format(year=year)

    def sample_rel(self, year: int) -> str:
        return f"samples/{self.dataset_id}/{self.series_id}/wiot{year}.bin"


# ----------------------------------------------------------------------------
# shared helpers


def read_exact(fh, n: int) -> bytes:
    parts = []
    remaining = n
    while remaining:
        chunk = fh.read(remaining)
        if not chunk:
            raise DtaError(f"unexpected end of member (wanted {n} bytes, short by {remaining})")
        parts.append(chunk)
        remaining -= len(chunk)
    return parts[0] if len(parts) == 1 else b"".join(parts)


def cstr(raw: bytes) -> str:
    return raw.split(b"\0", 1)[0].decode("utf-8")


def sha1_file(path: Path) -> str:
    digest = hashlib.sha1()
    with path.open("rb") as handle:
        while block := handle.read(8 * 1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def check_archive_identity(path: Path, spec: Spec) -> None:
    if not path.is_file():
        raise DtaError(f"missing archive {path}")
    size = path.stat().st_size
    if spec.archive_bytes is not None and size != spec.archive_bytes:
        raise DtaError(f"archive size {size} != pinned {spec.archive_bytes}")
    if spec.archive_sha1 is not None:
        actual = sha1_file(path)
        if actual != spec.archive_sha1:
            raise DtaError(f"archive SHA-1 {actual} != pinned {spec.archive_sha1}")
    print(f"archive_identity=ok bytes={size} sha1={spec.archive_sha1 or 'unpinned'}")


def check_member_table(zf: zipfile.ZipFile, spec: Spec) -> dict[int, zipfile.ZipInfo]:
    infos = zf.infolist()
    expected = [spec.member(year) for year in spec.years]
    names = [info.filename for info in infos]
    if names != expected:
        raise DtaError(f"ZIP member list changed: {names}")
    by_year: dict[int, zipfile.ZipInfo] = {}
    for year, info in zip(spec.years, infos):
        if info.compress_type != zipfile.ZIP_DEFLATED or info.flag_bits & 0x1:
            raise DtaError(f"{info.filename}: unexpected compression/encryption")
        if spec.member_bytes is not None and info.file_size != spec.member_bytes:
            raise DtaError(f"{info.filename}: size {info.file_size} != {spec.member_bytes}")
        if spec.member_crc32 is not None and info.CRC != spec.member_crc32[year]:
            raise DtaError(f"{info.filename}: CRC32 {info.CRC:08x} != {spec.member_crc32[year]:08x}")
        by_year[year] = info
    return by_year


def scan_doubles(raw: bytes, where: str) -> None:
    """Reject IEEE inf/NaN and Stata missing doubles (>= 2**1023) in LE bytes."""
    top = raw[7::8]
    if b"\x7f" in top or b"\xff" in top:
        for index, (value,) in enumerate(struct.iter_unpack("<d", raw)):
            if not math.isfinite(value) or abs(value) >= STATA_MISSING_MIN:
                raise DtaError(f"{where}: non-finite or Stata-missing double {value!r} at value {index}")


def doubles(raw: bytes) -> array.array:
    values = array.array("d")
    values.frombytes(raw)
    if sys.byteorder != "little":
        values.byteswap()
    return values


def type_width(code: int) -> int:
    if 1 <= code <= 2045:
        return code
    if code in NUMERIC_WIDTH:
        return NUMERIC_WIDTH[code]
    raise DtaError(f"unsupported Stata type code {code} (strL or unknown)")


@dataclass
class Header:
    k: int
    n: int
    timestamp: str
    offsets: tuple[int, ...]
    types: tuple[int, ...]
    names: tuple[str, ...]
    row_width: int


def check_variables(header: Header, spec: Spec, where: str) -> None:
    if header.k != len(spec.all_names()) or header.n != spec.n_source_rows:
        raise DtaError(f"{where}: K={header.k} N={header.n}, expected K={len(spec.all_names())} N={spec.n_source_rows}")
    if list(header.names) != spec.all_names():
        diffs = [(i, a, b) for i, (a, b) in enumerate(zip(header.names, spec.all_names())) if a != b][:5]
        raise DtaError(f"{where}: variable names differ from the WIOT layout: {diffs}")
    if tuple(header.types[: len(META_TYPES)]) != META_TYPES:
        raise DtaError(f"{where}: metadata column types {header.types[:5]} != {META_TYPES}")
    if any(code != T_DOUBLE for code in header.types[len(META_TYPES):]):
        raise DtaError(f"{where}: value columns are not all Stata double (65526)")
    computed = sum(type_width(code) for code in header.types)
    if computed != header.row_width:
        raise DtaError(f"{where}: row width mismatch {computed} != {header.row_width}")
    if spec.row_width is not None and header.row_width != spec.row_width:
        raise DtaError(f"{where}: row width {header.row_width} != pinned {spec.row_width}")
    if header.row_width != struct.calcsize(META_STRUCT) + 8 * (spec.n_cols + 1):
        raise DtaError(f"{where}: row width inconsistent with metadata + {spec.n_cols + 1} doubles")


# ----------------------------------------------------------------------------
# build path: map-driven header parse


def parse_header_map(fh, member_size: int) -> Header:
    """Parse the release-118 header and jump to <data> using the <map> offsets."""
    pos = 0

    def take(n: int) -> bytes:
        nonlocal pos
        chunk = read_exact(fh, n)
        pos += n
        return chunk

    def tag(expected: bytes) -> None:
        got = take(len(expected))
        if got != expected:
            raise DtaError(f"expected {expected!r} at byte {pos - len(expected)}, found {got!r}")

    tag(HEADER_PREFIX)
    (k,) = struct.unpack("<H", take(2))
    tag(b"</K><N>")
    (n,) = struct.unpack("<Q", take(8))
    tag(b"</N><label>")
    (label_len,) = struct.unpack("<H", take(2))
    take(label_len)
    tag(b"</label><timestamp>")
    ts_len = take(1)[0]
    timestamp = take(ts_len).decode("utf-8", "replace")
    tag(b"</timestamp></header>")
    map_pos = pos
    tag(b"<map>")
    offsets = struct.unpack("<14Q", take(112))
    tag(b"</map>")
    if offsets[0] != 0 or offsets[1] != map_pos or offsets[2] != pos:
        raise DtaError(f"map offsets inconsistent with header: {offsets[:3]} map_pos={map_pos} pos={pos}")
    if list(offsets) != sorted(offsets) or offsets[13] != member_size:
        raise DtaError(f"map offsets not monotonic or EOF offset {offsets[13]} != member size {member_size}")
    base = offsets[2]
    blob = take(offsets[9] - base)

    def section(i: int, open_tag: bytes, close_tag: bytes, length: int) -> bytes:
        start = offsets[i] - base
        if blob[start : start + len(open_tag)] != open_tag:
            raise DtaError(f"missing {open_tag!r} at map offset {offsets[i]}")
        body_end = start + len(open_tag) + length
        if blob[body_end : body_end + len(close_tag)] != close_tag:
            raise DtaError(f"missing {close_tag!r} after {open_tag!r}")
        if base + body_end + len(close_tag) != offsets[i + 1]:
            raise DtaError(f"section {open_tag!r} does not end at the next map offset")
        return blob[start + len(open_tag) : body_end]

    types = struct.unpack(f"<{k}H", section(2, b"<variable_types>", b"</variable_types>", 2 * k))
    names_raw = section(3, b"<varnames>", b"</varnames>", 129 * k)
    section(4, b"<sortlist>", b"</sortlist>", 2 * (k + 1))
    section(5, b"<formats>", b"</formats>", 57 * k)
    section(6, b"<value_label_names>", b"</value_label_names>", 129 * k)
    section(7, b"<variable_labels>", b"</variable_labels>", 321 * k)
    chars = blob[offsets[8] - base :]
    if not chars.startswith(b"<characteristics>") or not chars.endswith(b"</characteristics>"):
        raise DtaError("malformed <characteristics> section")
    names = tuple(cstr(names_raw[129 * i : 129 * (i + 1)]) for i in range(k))
    tag(b"<data>")
    row_width = sum(type_width(code) for code in types)
    if offsets[9] + 6 + n * row_width + 7 != offsets[10]:
        raise DtaError("data section length disagrees with N x row width and the <strls> map offset")
    return Header(k, n, timestamp, offsets, types, names, row_width)


def check_trailer_map(fh, header: Header) -> None:
    tail = fh.read()
    expected_len = header.offsets[13] - (header.offsets[10] - 7)
    if len(tail) != expected_len:
        raise DtaError(f"trailer length {len(tail)} != {expected_len}")
    rel = header.offsets[10] - 7
    if tail[:7] != b"</data>":
        raise DtaError("missing </data>")
    if tail[header.offsets[10] - rel : header.offsets[11] - rel] != b"<strls></strls>":
        raise DtaError("unexpected non-empty <strls> section")
    labels = tail[header.offsets[11] - rel : header.offsets[12] - rel]
    if not labels.startswith(b"<value_labels>") or not labels.endswith(b"</value_labels>"):
        raise DtaError("malformed <value_labels> section")
    if tail[header.offsets[12] - rel :] != b"</stata_dta>":
        raise DtaError("missing </stata_dta> at the map end offset")


def year_build(zf: zipfile.ZipFile, info: zipfile.ZipInfo, year: int, spec: Spec, out_path: Path) -> dict:
    where = info.filename
    meta = struct.Struct(META_STRUCT)
    vstart = meta.size
    kept_bytes = 8 * spec.n_cols
    with zf.open(info) as fh:
        header = parse_header_map(fh, info.file_size)
        check_variables(header, spec, where)
        digest = hashlib.sha256()
        colsum = [0.0] * spec.n_cols
        colabs = [0.0] * spec.n_cols
        totals: list[float] = []
        industry_codes: list[str] = []
        industry_desc: list[str] = []
        summary: dict[str, array.array] = {}
        summary_meta: list[dict] = []
        stats = {
            "zero_count": 0,
            "negative_count": 0,
            "negative_zero_count": 0,
            "min": math.inf,
            "max": -math.inf,
            "max_abs_rowsum_minus_tot": 0.0,
            "max_rel_rowsum_minus_tot": 0.0,
        }
        tmp_path = out_path.with_suffix(".part")
        with tmp_path.open("wb") as out:
            for r in range(header.n):
                row = read_exact(fh, header.row_width)
                code_raw, desc_raw, cty_raw, rnr, row_year = meta.unpack_from(row, 0)
                code, desc, country = cstr(code_raw), cstr(desc_raw), cstr(cty_raw)
                values_raw = row[vstart:]
                scan_doubles(values_raw, f"{where} row {r + 1} ({country} {code})")
                if r < spec.n_rows:
                    c_index, i_index = divmod(r, spec.n_industries)
                    if country != spec.countries[c_index] or rnr != i_index + 1 or row_year != year:
                        raise DtaError(
                            f"{where} row {r + 1}: label ({country},{rnr},{row_year}) != "
                            f"({spec.countries[c_index]},{i_index + 1},{year})"
                        )
                    if c_index == 0:
                        industry_codes.append(code)
                        industry_desc.append(desc)
                    elif code != industry_codes[i_index]:
                        raise DtaError(f"{where} row {r + 1}: industry code {code} != {industry_codes[i_index]}")
                    kept = values_raw[:kept_bytes]
                    out.write(kept)
                    digest.update(kept)
                    vals = doubles(kept)
                    tot = doubles(values_raw[kept_bytes : kept_bytes + 8])[0]
                    totals.append(tot)
                    stats["zero_count"] += vals.count(0.0)
                    neg_zero = array.array("Q", kept).count(NEG_ZERO_BITS) if sys.byteorder == "little" else 0
                    stats["negative_zero_count"] += neg_zero
                    top = kept[7::8]
                    stats["negative_count"] += len(top) - len(top.translate(None, HIGH_BYTES)) - neg_zero
                    stats["min"] = min(stats["min"], min(vals))
                    stats["max"] = max(stats["max"], max(vals))
                    rowsum = math.fsum(vals)
                    diff = abs(rowsum - tot)
                    stats["max_abs_rowsum_minus_tot"] = max(stats["max_abs_rowsum_minus_tot"], diff)
                    stats["max_rel_rowsum_minus_tot"] = max(
                        stats["max_rel_rowsum_minus_tot"], diff / max(1.0, abs(tot))
                    )
                    colsum = list(map(operator.add, colsum, vals))
                    colabs = list(map(operator.add, colabs, map(abs, vals)))
                else:
                    s_index = r - spec.n_rows
                    if code != spec.summary_codes[s_index]:
                        raise DtaError(f"{where} row {r + 1}: summary code {code!r} != {spec.summary_codes[s_index]!r}")
                    summary[code] = doubles(values_raw)
                    summary_meta.append(
                        {"code": code, "description": desc, "country": country, "rnr": rnr, "year": row_year}
                    )
        check_trailer_map(fh, header)
    if stats["min"] < -PLAUSIBLE_ABS_MAX or stats["max"] > PLAUSIBLE_ABS_MAX:
        tmp_path.unlink(missing_ok=True)
        raise DtaError(f"{where}: implausible magnitude min={stats['min']} max={stats['max']}")
    if not stats["min"] < stats["max"]:
        tmp_path.unlink(missing_ok=True)
        raise DtaError(f"{where}: constant matrix")
    ii = summary["II_fob"]
    go = summary["GO"]
    stats["max_abs_colsum_minus_II_fob"] = max(abs(colsum[j] - ii[j]) for j in range(spec.n_cols))
    stats["max_colsum_minus_II_fob_over_column_abs_sum"] = max(
        abs(colsum[j] - ii[j]) / colabs[j] if colabs[j] else abs(ii[j]) for j in range(spec.n_cols)
    )
    stats["all_zero_columns"] = [name for name, total in zip(spec.value_names(), colabs) if total == 0.0]
    stats["max_rel_GO_minus_TOT"] = max(
        abs(go[j] - totals[j]) / max(1.0, abs(totals[j])) for j in range(spec.n_rows)
    )
    os.replace(tmp_path, out_path)
    value_count = spec.n_rows * spec.n_cols
    stats.update(
        {
            "year": year,
            "source_member": info.filename,
            "source_member_crc32": f"{info.CRC:08x}",
            "stata_timestamp": header.timestamp,
            "value_count": value_count,
            "sample_sha256": digest.hexdigest(),
            "zero_fraction": stats["zero_count"] / value_count,
        }
    )
    stats["_axes"] = {
        "industry_codes": industry_codes,
        "industry_descriptions": industry_desc,
        "summary_rows": summary_meta,
    }
    return stats


def index_row(spec: Spec, year: int, stats: dict) -> dict:
    value_count = spec.n_rows * spec.n_cols
    return {
        "dataset_id": spec.dataset_id,
        "series_id": spec.series_id,
        "sample_path": spec.sample_rel(year),
        "numeric_kind": "float",
        "bit_width": 64,
        "endianness": "little",
        "element_size_bytes": 8,
        "sample_size_bytes": value_count * 8,
        "value_count": value_count,
        "role": "primary",
        "natural_record_kind": NATURAL_RECORD_KIND,
        "shape": [spec.n_rows, spec.n_cols],
        "axes": ["supplying_country_industry", "using_country_industry_then_final_demand"],
        "year": year,
        "source_member": stats["source_member"],
        "source_member_crc32": stats["source_member_crc32"],
        "sample_sha256": stats["sample_sha256"],
        "min": stats["min"],
        "max": stats["max"],
        "zero_count": stats["zero_count"],
        "negative_count": stats["negative_count"],
        "negative_zero_count": stats["negative_zero_count"],
    }


def build(archive: Path, data_root: Path, spec: Spec) -> dict:
    check_archive_identity(archive, spec)
    samples_dir = data_root / "samples" / spec.dataset_id / spec.series_id
    index_path = data_root / "index" / spec.dataset_id / "samples.jsonl"
    filtered_dir = data_root / "filtered" / spec.dataset_id
    for directory in (samples_dir, index_path.parent, filtered_dir):
        directory.mkdir(parents=True, exist_ok=True)
    planned = {Path(spec.sample_rel(year)).name for year in spec.years}
    for stale in samples_dir.iterdir():
        if stale.name not in planned:
            stale.unlink()
    rows = []
    per_year = []
    axes_reference = None
    with zipfile.ZipFile(archive) as zf:
        infos = check_member_table(zf, spec)
        for year in spec.years:
            stats = year_build(zf, infos[year], year, spec, data_root / spec.sample_rel(year))
            axes = stats.pop("_axes")
            if axes_reference is None:
                axes_reference = axes
            elif axes["industry_codes"] != axes_reference["industry_codes"] or [
                s["code"] for s in axes["summary_rows"]
            ] != [s["code"] for s in axes_reference["summary_rows"]]:
                raise DtaError(f"{year}: row axis labels differ from {spec.years[0]}")
            rows.append(index_row(spec, year, stats))
            per_year.append(stats)
            print(
                f"year={year} shape={spec.n_rows}x{spec.n_cols} sha256={stats['sample_sha256'][:16]} "
                f"min={stats['min']:.6g} max={stats['max']:.6g} zero_frac={stats['zero_fraction']:.4f} "
                f"neg={stats['negative_count']} negzero={stats['negative_zero_count']} "
                f"rowsum_rel={stats['max_rel_rowsum_minus_tot']:.3g} "
                f"colsum_dev_over_abs={stats['max_colsum_minus_II_fob_over_column_abs_sum']:.3g} "
                f"go_tot_rel={stats['max_rel_GO_minus_TOT']:.3g} zero_cols={len(stats['all_zero_columns'])}",
                flush=True,
            )
    shapes = {tuple(row["shape"]) for row in rows}
    if len(rows) != len(spec.years) or len(shapes) != 1:
        raise DtaError(f"expected {len(spec.years)} samples with one shape, got {len(rows)} {shapes}")
    if len({row["sample_sha256"] for row in rows}) != len(rows):
        raise DtaError("two yearly matrices are byte-identical")
    tmp_index = index_path.with_suffix(".jsonl.part")
    with tmp_index.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n")
    os.replace(tmp_index, index_path)
    assert axes_reference is not None
    axes_doc = {
        "row_axis": [
            {"country": c, "industry_number": i + 1, "industry_code": axes_reference["industry_codes"][i],
             "industry_description": axes_reference["industry_descriptions"][i]}
            for c in spec.countries
            for i in range(spec.n_industries)
        ],
        "column_axis": spec.value_names(),
        "final_demand_suffixes": {
            str(spec.n_industries + 1 + j): label for j, label in enumerate(FINAL_DEMAND_LABELS[: spec.n_final])
        },
        "dropped_source_rows": axes_reference["summary_rows"],
        "dropped_source_columns": [TOTAL_NAME],
    }
    (filtered_dir / "table_axes.json").write_text(json.dumps(axes_doc, indent=1) + "\n", encoding="utf-8")
    aggregate = hashlib.sha256()
    for row in rows:
        aggregate.update(bytes.fromhex(row["sample_sha256"]))
    summary = {
        "dataset_id": spec.dataset_id,
        "series_id": spec.series_id,
        "sample_count": len(rows),
        "total_size_bytes": sum(row["sample_size_bytes"] for row in rows),
        "total_values": sum(row["value_count"] for row in rows),
        "shape": list(shapes.pop()),
        "aggregate_sha256_of_sample_sha256s": aggregate.hexdigest(),
        "per_year": per_year,
    }
    (filtered_dir / "ingest_stats.json").write_text(json.dumps(summary, indent=1) + "\n", encoding="utf-8")
    print(
        f"build_summary samples={summary['sample_count']} bytes={summary['total_size_bytes']} "
        f"values={summary['total_values']} aggregate={summary['aggregate_sha256_of_sample_sha256s']}"
    )
    return summary


# ----------------------------------------------------------------------------
# verify path: sequential tag walk (map used only as a cross-check)


def parse_header_walk(fh, member_size: int) -> Header:
    pos = 0

    def take(n: int) -> bytes:
        nonlocal pos
        chunk = read_exact(fh, n)
        pos += n
        return chunk

    def tag(expected: bytes) -> int:
        start = pos
        if take(len(expected)) != expected:
            raise DtaError(f"walk: expected {expected!r} at byte {start}")
        return start

    starts: dict[str, int] = {}
    tag(b"<stata_dta>")
    tag(b"<header>")
    tag(b"<release>118</release>")
    tag(b"<byteorder>LSF</byteorder>")
    tag(b"<K>")
    k = int.from_bytes(take(2), "little")
    tag(b"</K>")
    tag(b"<N>")
    n = int.from_bytes(take(8), "little")
    tag(b"</N>")
    tag(b"<label>")
    take(int.from_bytes(take(2), "little"))
    tag(b"</label>")
    tag(b"<timestamp>")
    timestamp = take(take(1)[0]).decode("utf-8", "replace")
    tag(b"</timestamp>")
    tag(b"</header>")
    starts["map"] = tag(b"<map>")
    offsets = tuple(int.from_bytes(take(8), "little") for _ in range(14))
    tag(b"</map>")
    starts["variable_types"] = tag(b"<variable_types>")
    types = tuple(int.from_bytes(take(2), "little") for _ in range(k))
    tag(b"</variable_types>")
    starts["varnames"] = tag(b"<varnames>")
    names = tuple(cstr(take(129)) for _ in range(k))
    tag(b"</varnames>")
    starts["sortlist"] = tag(b"<sortlist>")
    take(2 * (k + 1))
    tag(b"</sortlist>")
    starts["formats"] = tag(b"<formats>")
    take(57 * k)
    tag(b"</formats>")
    starts["value_label_names"] = tag(b"<value_label_names>")
    take(129 * k)
    tag(b"</value_label_names>")
    starts["variable_labels"] = tag(b"<variable_labels>")
    take(321 * k)
    tag(b"</variable_labels>")
    starts["characteristics"] = tag(b"<characteristics>")
    while True:
        peek = take(4)
        if peek == b"<ch>":
            take(int.from_bytes(take(4), "little"))
            tag(b"</ch>")
            continue
        rest = take(len(b"</characteristics>") - 4)
        if peek + rest != b"</characteristics>":
            raise DtaError("walk: malformed <characteristics>")
        break
    starts["data"] = tag(b"<data>")
    order = ["map", "variable_types", "varnames", "sortlist", "formats", "value_label_names",
             "variable_labels", "characteristics", "data"]
    walked = tuple([0] + [starts[key] for key in order])
    if walked != offsets[:10]:
        raise DtaError(f"walk: section positions {walked} disagree with <map> {offsets[:10]}")
    if offsets[13] != member_size:
        raise DtaError("walk: map EOF offset disagrees with member size")
    row_width = sum(type_width(code) for code in types)
    return Header(k, n, timestamp, offsets, types, names, row_width)


def verify_year(zf: zipfile.ZipFile, info: zipfile.ZipInfo, year: int, spec: Spec, sample: Path) -> dict:
    where = f"verify {info.filename}"
    ncols = spec.n_cols
    meta = struct.Struct(META_STRUCT)
    row_values = struct.Struct(f"<{ncols + 1}d")
    kept_struct = struct.Struct(f"<{ncols}d")
    expected_size = spec.n_rows * ncols * 8
    if not sample.is_file() or sample.stat().st_size != expected_size:
        raise DtaError(f"{where}: sample {sample} missing or not {expected_size} bytes")
    zeros = negatives = neg_zeros = 0
    vmin, vmax = math.inf, -math.inf
    colsum = [0.0] * ncols
    colabs = [0.0] * ncols
    totals: list[float] = []
    ii_fob = None
    go = None
    digest = hashlib.sha256()
    distinct_probe: set[float] = set()
    probe_step = max(1, spec.n_rows // 25)
    probe_values = 0
    with zf.open(info) as fh, sample.open("rb") as sh:
        header = parse_header_walk(fh, info.file_size)
        check_variables(header, spec, where)
        for r in range(header.n):
            row = read_exact(fh, header.row_width)
            code_raw, _desc, cty_raw, rnr, row_year = meta.unpack_from(row, 0)
            code, country = cstr(code_raw), cstr(cty_raw)
            vals = row_values.unpack_from(row, meta.size)
            if not all(map(math.isfinite, vals)) or max(vals) >= STATA_MISSING_MIN:
                raise DtaError(f"{where} row {r + 1}: non-finite or Stata-missing value")
            if r < spec.n_rows:
                c_index, i_index = divmod(r, spec.n_industries)
                if (country, rnr, row_year) != (spec.countries[c_index], i_index + 1, year):
                    raise DtaError(f"{where} row {r + 1}: unexpected row label {(country, rnr, row_year)}")
                kept = vals[:ncols]
                packed = kept_struct.pack(*kept)
                stored = sh.read(len(packed))
                if stored != packed:
                    raise DtaError(f"{where} row {r + 1}: sample bytes differ from the re-decoded source row")
                digest.update(stored)
                rowsum = math.fsum(kept)
                scale = math.fsum(map(abs, kept))
                if abs(rowsum - vals[ncols]) > 1e-9 * scale + 1e-6:
                    raise DtaError(f"{where} row {r + 1}: row sum {rowsum!r} != TOT {vals[ncols]!r}")
                colsum = list(map(operator.add, colsum, kept))
                colabs = list(map(operator.add, colabs, map(abs, kept)))
                totals.append(vals[ncols])
                for value in kept:
                    if value == 0.0:
                        zeros += 1
                        if math.copysign(1.0, value) < 0:
                            neg_zeros += 1
                    elif value < 0.0:
                        negatives += 1
                vmin = min(vmin, min(kept))
                vmax = max(vmax, max(kept))
                if r % probe_step == 0:
                    distinct_probe.update(kept)
                    probe_values += ncols
            else:
                if code != spec.summary_codes[r - spec.n_rows]:
                    raise DtaError(f"{where} row {r + 1}: unexpected summary row {code!r}")
                if code == "II_fob":
                    ii_fob = vals[:ncols]
                elif code == "GO":
                    go = vals[:ncols]
        if sh.read(1):
            raise DtaError(f"{where}: sample has trailing bytes")
        if read_exact(fh, 7) != b"</data>":
            raise DtaError(f"{where}: missing </data> after {header.n} rows")
        fh.read()
    if ii_fob is None or go is None:
        raise DtaError(f"{where}: no II_fob or GO row")
    # Column alignment: the published II_fob row equals the column sums of the
    # emitted matrix to <= ~2.2e-7 of the column's absolute sum in every year
    # (II_fob was stored at a slightly different rounding stage); a shifted or
    # misaligned column would be off by O(1) relative.
    worst = 0.0
    for j in range(ncols):
        dev = abs(colsum[j] - ii_fob[j])
        worst = max(worst, dev / colabs[j] if colabs[j] else dev)
        if dev > 1e-6 * colabs[j] + 1e-6:
            raise DtaError(f"{where}: column {j} sum {colsum[j]!r} != II_fob {ii_fob[j]!r}")
    # Row/column cross-alignment: gross output GO of using industry j equals the
    # TOT (total use) of supplying row j.
    for j in range(spec.n_rows):
        if abs(go[j] - totals[j]) > 1e-9 * abs(totals[j]) + 1e-6:
            raise DtaError(f"{where}: GO[{j}] {go[j]!r} != TOT of row {j} {totals[j]!r}")
    value_count = spec.n_rows * ncols
    if not vmin < vmax:
        raise DtaError(f"{where}: constant matrix")
    if zeros / value_count > 0.9:
        raise DtaError(f"{where}: degenerate matrix, zero fraction {zeros / value_count:.3f}")
    if len(distinct_probe) < min(1000, probe_values // 4):
        raise DtaError(f"{where}: only {len(distinct_probe)} distinct values in probe rows")
    if vmin < -PLAUSIBLE_ABS_MAX or vmax > PLAUSIBLE_ABS_MAX:
        raise DtaError(f"{where}: implausible magnitudes {vmin} {vmax}")
    return {
        "sha256": digest.hexdigest(),
        "min": vmin,
        "max": vmax,
        "zero_count": zeros,
        "negative_count": negatives,
        "negative_zero_count": neg_zeros,
        "colsum_rel": worst,
        "distinct_probe": len(distinct_probe),
    }


def verify(archive: Path, data_root: Path, spec: Spec, manifest: Path | None) -> None:
    check_archive_identity(archive, spec)
    index_path = data_root / "index" / spec.dataset_id / "samples.jsonl"
    rows = [json.loads(line) for line in index_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if len(rows) != len(spec.years):
        raise DtaError(f"index has {len(rows)} rows, expected exactly {len(spec.years)}")
    if [row.get("year") for row in rows] != list(spec.years):
        raise DtaError("index years are not the expected ordered population")
    samples_dir = data_root / "samples" / spec.dataset_id / spec.series_id
    on_disk = sorted(p.name for p in samples_dir.iterdir())
    expected_files = sorted(Path(spec.sample_rel(year)).name for year in spec.years)
    if on_disk != expected_files:
        raise DtaError(f"sample directory content {on_disk} != {expected_files}")
    value_count = spec.n_rows * spec.n_cols
    hashes = set()
    with zipfile.ZipFile(archive) as zf:
        infos = check_member_table(zf, spec)
        for year, row in zip(spec.years, rows):
            fixed = {
                "dataset_id": spec.dataset_id,
                "series_id": spec.series_id,
                "sample_path": spec.sample_rel(year),
                "numeric_kind": "float",
                "bit_width": 64,
                "endianness": "little",
                "element_size_bytes": 8,
                "sample_size_bytes": value_count * 8,
                "value_count": value_count,
                "role": "primary",
                "shape": [spec.n_rows, spec.n_cols],
            }
            for key, expected in fixed.items():
                if row.get(key) != expected:
                    raise DtaError(f"index {year}: {key}={row.get(key)!r}, expected {expected!r}")
            result = verify_year(zf, infos[year], year, spec, data_root / row["sample_path"])
            for key in ("min", "max", "zero_count", "negative_count", "negative_zero_count"):
                if row.get(key) != result[key]:
                    raise DtaError(f"index {year}: {key}={row.get(key)!r} but recomputed {result[key]!r}")
            if row.get("sample_sha256") != result["sha256"]:
                raise DtaError(f"index {year}: sample_sha256 mismatch")
            hashes.add(result["sha256"])
            print(
                f"verify year={year} ok sha256={result['sha256'][:16]} min={result['min']:.6g} "
                f"max={result['max']:.6g} zeros={result['zero_count']} neg={result['negative_count']} "
                f"negzero={result['negative_zero_count']} colsum_rel={result['colsum_rel']:.3g} "
                f"distinct_probe={result['distinct_probe']}",
                flush=True,
            )
    if len(hashes) != len(rows):
        raise DtaError("two yearly matrices are byte-identical")
    total_bytes = sum(int(row["sample_size_bytes"]) for row in rows)
    if manifest is not None:
        doc = tomllib.loads(manifest.read_text(encoding="utf-8"))
        series = [s for s in doc.get("series", []) if s.get("id") == spec.series_id]
        if len(series) != 1:
            raise DtaError("manifest must declare exactly one primary series")
        if series[0].get("sample_count") != len(rows) or series[0].get("total_size_bytes") != total_bytes:
            raise DtaError(
                f"manifest sample_count/total_size_bytes {series[0].get('sample_count')}/"
                f"{series[0].get('total_size_bytes')} != realized {len(rows)}/{total_bytes}"
            )
    print(f"verify_summary samples={len(rows)} bytes={total_bytes} values={len(rows) * value_count} ok")


# ----------------------------------------------------------------------------
# download-time validation


def validate_metadata(path: Path) -> None:
    doc = json.loads(path.read_text(encoding="utf-8"))
    if doc.get("status") != "OK":
        raise DtaError(f"Dataverse API status {doc.get('status')!r}")
    data = doc["data"]
    if data.get("datasetPersistentId") != DOI:
        raise DtaError(f"unexpected persistent id {data.get('datasetPersistentId')!r}")
    if (data.get("versionNumber"), data.get("versionMinorNumber")) != DATASET_VERSION:
        raise DtaError(f"unexpected dataset version {data.get('versionNumber')}.{data.get('versionMinorNumber')}")
    if data.get("versionState") != "RELEASED":
        raise DtaError("dataset version is not RELEASED")
    terms = " ".join(str(data.get("termsOfUse") or "").lower().split())
    if LICENSE_PHRASE not in terms or LICENSE_URL not in terms:
        raise DtaError(f"termsOfUse no longer grants CC BY 4.0: {terms[:200]!r}")
    if data.get("termsOfAccess") or data.get("fileAccessRequest"):
        raise DtaError("dataset now has access terms or file access requests")
    matches = [f for f in data.get("files", []) if f.get("dataFile", {}).get("id") == DATAFILE_ID]
    if len(matches) != 1:
        raise DtaError(f"datafile {DATAFILE_ID} not listed exactly once")
    entry = matches[0]
    datafile = entry["dataFile"]
    checks = {
        "filename": (datafile.get("filename"), ARCHIVE_NAME),
        "filesize": (datafile.get("filesize"), ARCHIVE_BYTES),
        "checksum": (datafile.get("checksum"), {"type": "SHA-1", "value": ARCHIVE_SHA1}),
        "restricted": (entry.get("restricted"), False),
    }
    for key, (actual, expected) in checks.items():
        if actual != expected:
            raise DtaError(f"datafile {key} changed: {actual!r} != {expected!r}")
    print(
        f"metadata_validation=ok doi={DOI} version={DATASET_VERSION[0]}.{DATASET_VERSION[1]} "
        f"datafile={DATAFILE_ID} bytes={ARCHIVE_BYTES} sha1={ARCHIVE_SHA1} license=CC-BY-4.0"
    )


def validate_archive(path: Path, spec: Spec) -> None:
    check_archive_identity(path, spec)
    with zipfile.ZipFile(path) as zf:
        infos = check_member_table(zf, spec)
        for year in spec.years:
            with zf.open(infos[year]) as fh:
                header = parse_header_map(fh, infos[year].file_size)
            check_variables(header, spec, infos[year].filename)
            print(
                f"member_ok {infos[year].filename} K={header.k} N={header.n} row_width={header.row_width} "
                f"data_offset={header.offsets[9]} timestamp={header.timestamp!r}"
            )
    print(f"archive_validation=ok members={len(spec.years)}")


# ----------------------------------------------------------------------------
# self-test on a synthetic Stata-118 archive


def synth_dta(spec: Spec, year: int, rng_seed: int, poison: str | None = None) -> tuple[bytes, list[list[float]]]:
    import random

    rng = random.Random(rng_seed)
    names = spec.all_names()
    types = list(META_TYPES) + [T_DOUBLE] * (len(names) - len(META_TYPES))
    k = len(names)
    rows_kept: list[list[float]] = []
    for r in range(spec.n_rows):
        row = []
        for j in range(spec.n_cols):
            choice = rng.random()
            if choice < 0.2:
                row.append(0.0)
            elif choice < 0.25:
                row.append(-rng.random() * 50)
            elif choice < 0.3:
                row.append(rng.random() * 1e-6)
            else:
                row.append(rng.random() * 10 ** rng.randint(0, 5))
        rows_kept.append(row)
    rows_kept[1][2] = -0.0
    if poison == "missing":
        rows_kept[2][3] = STATA_MISSING_MIN
    colsum = [math.fsum(rows_kept[r][j] for r in range(spec.n_rows)) for j in range(spec.n_cols)]
    meta = struct.Struct(META_STRUCT)
    body = bytearray()
    industry_codes = [f"I{i:02d}" for i in range(1, spec.n_industries + 1)]
    for r, row in enumerate(rows_kept):
        c_index, i_index = divmod(r, spec.n_industries)
        country = spec.countries[c_index]
        if poison == "label" and r == spec.n_rows - 1:
            country = spec.countries[0]
        body += meta.pack(industry_codes[i_index].encode(), f"Industry {i_index}".encode(), country.encode(),
                          i_index + 1, year)
        body += struct.pack(f"<{spec.n_cols + 1}d", *row, math.fsum(row))
    for s_index, code in enumerate(spec.summary_codes):
        body += meta.pack(code.encode(), f"Summary {code}".encode(), b"TOT", 65 + s_index, year)
        if code == "II_fob":
            vals = colsum
        elif code == "GO":
            vals = [math.fsum(row) for row in rows_kept] + [rng.random() * 100 for _ in range(spec.n_cols - spec.n_rows)]
        else:
            vals = [rng.random() * 100 for _ in range(spec.n_cols)]
        body += struct.pack(f"<{spec.n_cols + 1}d", *vals, math.fsum(vals))

    def fixed(text: str, width: int) -> bytes:
        return text.encode().ljust(width, b"\0")
    sections = [
        b"<variable_types>" + struct.pack(f"<{k}H", *types) + b"</variable_types>",
        b"<varnames>" + b"".join(fixed(n, 129) for n in names) + b"</varnames>",
        b"<sortlist>" + bytes(2 * (k + 1)) + b"</sortlist>",
        b"<formats>" + b"".join(fixed("%15.1f", 57) for _ in names) + b"</formats>",
        b"<value_label_names>" + bytes(129 * k) + b"</value_label_names>",
        b"<variable_labels>" + bytes(321 * k) + b"</variable_labels>",
        b"<characteristics>" + b"<ch>" + struct.pack("<I", 5) + b"hello" + b"</ch>" + b"</characteristics>",
    ]
    ts = b" 3 Nov 2016 11:11"
    head = (HEADER_PREFIX + struct.pack("<H", k) + b"</K><N>" + struct.pack("<Q", spec.n_source_rows)
            + b"</N><label>" + struct.pack("<H", 0) + b"</label><timestamp>" + bytes([len(ts)]) + ts
            + b"</timestamp></header>")
    map_pos = len(head)
    pos = map_pos + 5 + 112 + 6
    offsets = [0, map_pos]
    for sec in sections:
        offsets.append(pos)
        pos += len(sec)
    offsets.append(pos)  # data
    data = b"<data>" + bytes(body) + b"</data>"
    pos += len(data)
    offsets.append(pos)
    strls = b"<strls></strls>"
    pos += len(strls)
    offsets.append(pos)
    vlabels = b"<value_labels></value_labels>"
    pos += len(vlabels)
    offsets.append(pos)
    end = b"</stata_dta>"
    pos += len(end)
    offsets.append(pos)
    blob = (head + b"<map>" + struct.pack("<14Q", *offsets) + b"</map>" + b"".join(sections)
            + data + strls + vlabels + end)
    assert len(blob) == offsets[13]
    return blob, rows_kept


def selftest() -> None:
    work = Path(tempfile.mkdtemp(prefix="wiod_selftest_", dir=os.environ.get("TMPDIR")))
    base = Spec(countries=("AAA", "BBB", "ROW"), n_industries=3, n_final=5, years=(2000, 2001),
                member_bytes=None, member_crc32=None, row_width=None, archive_bytes=None, archive_sha1=None,
                dataset_id="wiod_selftest", series_id="flows")

    def make_archive(name: str, poison: str | None = None) -> tuple[Path, dict[int, list[list[float]]]]:
        path = work / name
        truth = {}
        with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for offset, year in enumerate(base.years):
                blob, rows = synth_dta(base, year, 100 + offset, poison if year == 2001 else None)
                zf.writestr(base.member(year), blob)
                truth[year] = rows
        return path, truth

    archive, truth = make_archive("good.zip")
    root = work / "data"
    validate_archive(archive, base)
    build(archive, root, base)
    for year in base.years:
        expected = b"".join(struct.pack(f"<{base.n_cols}d", *row) for row in truth[year])
        actual = (root / base.sample_rel(year)).read_bytes()
        assert actual == expected, f"sample {year} differs from the synthetic truth"
    neg_zero_offset = (1 * base.n_cols + 2) * 8
    assert (root / base.sample_rel(2000)).read_bytes()[neg_zero_offset:neg_zero_offset + 8] == struct.pack("<d", -0.0)
    verify(archive, root, base, None)

    sample = root / base.sample_rel(2001)
    data = bytearray(sample.read_bytes())
    data[100] ^= 0x01
    sample.write_bytes(bytes(data))
    try:
        verify(archive, root, base, None)
    except DtaError as exc:
        print(f"selftest expected failure (tampered sample): {exc}")
    else:
        raise AssertionError("verify accepted a tampered sample")

    for poison in ("missing", "label"):
        bad, _ = make_archive(f"bad_{poison}.zip", poison)
        try:
            build(bad, work / f"data_{poison}", base)
        except DtaError as exc:
            print(f"selftest expected failure ({poison}): {exc}")
        else:
            raise AssertionError(f"build accepted poisoned archive ({poison})")

    wrong = replace(base, summary_codes=base.summary_codes[:-1] + ("XX",))
    try:
        build(archive, work / "data_wrong", wrong)
    except DtaError as exc:
        print(f"selftest expected failure (layout): {exc}")
    else:
        raise AssertionError("build accepted a layout mismatch")
    print(f"selftest=ok workdir={work}")


# ----------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("validate-metadata")
    p.add_argument("--metadata", type=Path, required=True)
    p = sub.add_parser("validate-archive")
    p.add_argument("--archive", type=Path, required=True)
    for name in ("build", "verify"):
        p = sub.add_parser(name)
        p.add_argument("--archive", type=Path, required=True)
        p.add_argument("--data-root", type=Path, required=True)
        if name == "verify":
            p.add_argument("--manifest", type=Path, required=True)
    sub.add_parser("selftest")
    args = parser.parse_args()
    try:
        if args.command == "validate-metadata":
            validate_metadata(args.metadata)
        elif args.command == "validate-archive":
            validate_archive(args.archive, Spec())
        elif args.command == "build":
            build(args.archive, args.data_root, Spec())
        elif args.command == "verify":
            verify(args.archive, args.data_root, Spec(), args.manifest)
        else:
            selftest()
    except DtaError as exc:
        print(f"FATAL: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
