#!/usr/bin/env python3
"""Build and independently verify TESS PDCSAP float32 light curves."""
from __future__ import annotations

import argparse
import csv
import hashlib
import html
import json
import math
from pathlib import Path
import re
import shutil
import struct
from typing import Callable


DATASET_ID = "nasa_tess_lightcurves_f32"
SERIES_ID = "tess_pdcsap_flux_f32"
EXPECTED_SAMPLES = 64
EXPECTED_TARGETS = 8
EXPECTED_SECTORS = set(range(61, 69))
EXPECTED_SOURCE_BYTES = 126_650_880
EXPECTED_SOURCE_ROWS = 1_247_392
EXPECTED_VALUES = 1_015_204
EXPECTED_OUTPUT_BYTES = 4_060_816
EXPECTED_DROPPED_QUALITY = 224_940
EXPECTED_DROPPED_NONFINITE = 7_248
EXPECTED_RIGHTS = {
    "mast_page": (
        117_080,
        "a1ea1aafb7cf964dae869eac88ce3bfc33acf322cf511f62fd53dc34cca3cfa3",
    ),
    "nasa_guidelines": (
        314_701,
        "178d06d54ef9d5309798e77a1cc412d398ef06ee2c798144787604f5ad6047b2",
    ),
}
Consumer = Callable[[dict[str, object], bytes, dict[str, object]], None]


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def load_selection(path: Path) -> list[dict[str, object]]:
    with path.open(encoding="utf-8", newline="") as handle:
        raw = list(csv.DictReader(handle, delimiter="\t"))
    required = {
        "obsid", "target_name", "sector", "data_uri", "filename",
        "size_bytes", "sha256", "source_row_count",
    }
    if len(raw) != EXPECTED_SAMPLES or not raw or not required.issubset(raw[0]):
        raise SystemExit("selection count or schema changed")
    rows: list[dict[str, object]] = []
    for source in raw:
        row = {
            **source,
            "obsid": int(source["obsid"]),
            "target_name": int(source["target_name"]),
            "sector": int(source["sector"]),
            "size_bytes": int(source["size_bytes"]),
            "source_row_count": int(source["source_row_count"]),
        }
        if not str(row["data_uri"]).startswith("mast:TESS/product/"):
            raise SystemExit(f"invalid MAST URI: {row['data_uri']}")
        if Path(str(row["data_uri"])).name != row["filename"]:
            raise SystemExit(f"URI/filename mismatch: {row['filename']}")
        rows.append(row)
    if sum(int(row["size_bytes"]) for row in rows) != EXPECTED_SOURCE_BYTES:
        raise SystemExit("selected source byte total changed")
    if sum(int(row["source_row_count"]) for row in rows) != EXPECTED_SOURCE_ROWS:
        raise SystemExit("selected source row total changed")
    if len({row["target_name"] for row in rows}) != EXPECTED_TARGETS:
        raise SystemExit("selected target count changed")
    if {row["sector"] for row in rows} != EXPECTED_SECTORS:
        raise SystemExit("selected sector coverage changed")
    if len({row["data_uri"] for row in rows}) != EXPECTED_SAMPLES:
        raise SystemExit("duplicate selected MAST URI")
    if len({row["filename"] for row in rows}) != EXPECTED_SAMPLES:
        raise SystemExit("duplicate selected filename")
    return rows


def validate_rights(mast_page: Path, nasa_guidelines: Path) -> None:
    for label, path in (("mast_page", mast_page), ("nasa_guidelines", nasa_guidelines)):
        if not path.is_file():
            raise SystemExit(f"missing rights/provenance evidence: {path}")
        size, digest = EXPECTED_RIGHTS[label]
        if path.stat().st_size != size or file_hash(path) != digest:
            raise SystemExit(f"rights/provenance evidence identity mismatch: {path}")
    mast = re.sub(r"\s+", " ", html.unescape(mast_page.read_text(errors="replace"))).lower()
    nasa = re.sub(r"\s+", " ", html.unescape(nasa_guidelines.read_text(errors="replace"))).lower()
    if "transiting exoplanet survey satellite" not in mast or "mikulski archive" not in mast:
        raise SystemExit("pinned MAST page lacks expected TESS archive identity")
    if "generally are not subject to copyright in the united states" not in nasa:
        raise SystemExit("pinned NASA page lacks expected copyright statement")


def card_value(card: str) -> str:
    field = card[10:80].lstrip()
    if field.startswith("'"):
        chars: list[str] = []
        index = 1
        while index < len(field):
            if field[index] == "'":
                if index + 1 < len(field) and field[index + 1] == "'":
                    chars.append("'")
                    index += 2
                    continue
                break
            chars.append(field[index])
            index += 1
        return "".join(chars).rstrip()
    return field.split("/", 1)[0].strip()


def read_header(data: bytes, offset: int, source: Path) -> tuple[dict[str, str], int]:
    start = offset
    cards: dict[str, str] = {}
    while offset + 80 <= len(data):
        raw = data[offset:offset + 80]
        try:
            card = raw.decode("ascii")
        except UnicodeDecodeError as error:
            raise SystemExit(f"non-ASCII FITS header in {source}") from error
        offset += 80
        key = card[:8].strip()
        if key == "END":
            header_end = start + math.ceil((offset - start) / 2880) * 2880
            if header_end > len(data):
                raise SystemExit(f"truncated FITS header: {source}")
            return cards, header_end
        if card[8:10] == "= ":
            cards[key] = card_value(card)
    raise SystemExit(f"missing FITS END card: {source}")


def fixed_tform_width(tform: str) -> tuple[int, str, int]:
    match = re.fullmatch(r"\s*(\d*)([A-Z])(?:\([^)]*\))?\s*", tform)
    if not match:
        raise SystemExit(f"unsupported FITS TFORM: {tform!r}")
    repeat = int(match.group(1) or "1")
    code = match.group(2)
    widths = {"L": 1, "B": 1, "I": 2, "J": 4, "K": 8, "A": 1, "E": 4, "D": 8, "C": 8, "M": 16}
    if code == "X":
        return math.ceil(repeat / 8), code, repeat
    if code not in widths or code in {"P", "Q"}:
        raise SystemExit(f"variable or unsupported FITS TFORM: {tform!r}")
    return repeat * widths[code], code, repeat


def extract_lightcurve(path: Path, expected_rows: int) -> tuple[bytes, dict[str, object]]:
    data = path.read_bytes()
    primary, primary_data = read_header(data, 0, path)
    if primary.get("SIMPLE") != "T" or primary.get("BITPIX") != "8" or primary.get("NAXIS") != "0":
        raise SystemExit(f"unexpected TESS primary HDU: {path}")
    if primary.get("TELESCOP") != "TESS" or primary.get("ORIGIN") != "NASA/Ames":
        raise SystemExit(f"unexpected TESS origin metadata: {path}")
    table, table_data = read_header(data, primary_data, path)
    expected = {"XTENSION": "BINTABLE", "EXTNAME": "LIGHTCURVE", "BITPIX": "8", "NAXIS": "2", "PCOUNT": "0", "GCOUNT": "1"}
    for key, value in expected.items():
        if table.get(key) != value:
            raise SystemExit(f"unexpected FITS {key}={table.get(key)!r}: {path}")
    row_width = int(table["NAXIS1"])
    row_count = int(table["NAXIS2"])
    field_count = int(table["TFIELDS"])
    if row_count != expected_rows:
        raise SystemExit(f"source row count changed for {path.name}: {row_count}")
    offsets: dict[str, tuple[int, str, int, int]] = {}
    cursor = 0
    for index in range(1, field_count + 1):
        name = table.get(f"TTYPE{index}")
        tform = table.get(f"TFORM{index}")
        if name is None or tform is None:
            raise SystemExit(f"incomplete FITS column declaration: {path}")
        width, code, repeat = fixed_tform_width(tform)
        offsets[name] = (cursor, code, repeat, width)
        cursor += width
    if cursor != row_width:
        raise SystemExit(f"declared columns total {cursor}, row width {row_width}: {path}")
    if offsets.get("PDCSAP_FLUX", (None, None, None, None))[1:3] != ("E", 1):
        raise SystemExit(f"PDCSAP_FLUX is not scalar float32: {path}")
    if offsets.get("QUALITY", (None, None, None, None))[1:3] != ("J", 1):
        raise SystemExit(f"QUALITY is not scalar int32: {path}")
    table_bytes = row_width * row_count
    if table_data + table_bytes > len(data):
        raise SystemExit(f"truncated FITS binary table: {path}")
    flux_offset = offsets["PDCSAP_FLUX"][0]
    quality_offset = offsets["QUALITY"][0]
    output = bytearray()
    dropped_quality = 0
    dropped_nonfinite = 0
    minimum = math.inf
    maximum = -math.inf
    distinct_words: set[bytes] = set()
    for row_index in range(row_count):
        start = table_data + row_index * row_width
        quality = struct.unpack_from(">i", data, start + quality_offset)[0]
        if quality != 0:
            dropped_quality += 1
            continue
        raw = data[start + flux_offset:start + flux_offset + 4]
        value = struct.unpack(">f", raw)[0]
        if not math.isfinite(value):
            dropped_nonfinite += 1
            continue
        output.extend(raw[::-1])
        distinct_words.add(raw)
        minimum = min(minimum, value)
        maximum = max(maximum, value)
    retained = len(output) // 4
    if retained < 1_000 or len(distinct_words) < 2:
        raise SystemExit(f"too short or constant retained light curve: {path}")
    return bytes(output), {
        "source_row_count": row_count,
        "value_count": retained,
        "sample_size_bytes": len(output),
        "dropped_nonzero_quality": dropped_quality,
        "dropped_nonfinite_flux": dropped_nonfinite,
        "minimum": minimum,
        "maximum": maximum,
        "distinct_values": len(distinct_words),
        "date_obs": primary.get("DATE-OBS", ""),
        "date_end": primary.get("DATE-END", ""),
    }


def scan(selection: Path, fits_dir: Path, consumer: Consumer | None = None) -> dict[str, object]:
    rows = load_selection(selection)
    profiles: list[dict[str, object]] = []
    payload_hashes: set[str] = set()
    for row in rows:
        source = fits_dir / str(row["filename"])
        if not source.is_file():
            raise SystemExit(f"missing selected FITS source: {source}")
        digest = file_hash(source)
        if source.stat().st_size != row["size_bytes"] or digest != row["sha256"]:
            raise SystemExit(f"selected source identity mismatch: {source.name}")
        payload, metrics = extract_lightcurve(source, int(row["source_row_count"]))
        payload_hash = hashlib.sha256(payload).hexdigest()
        if payload_hash in payload_hashes:
            raise SystemExit(f"duplicate retained light curve: {source.name}")
        payload_hashes.add(payload_hash)
        profile = {
            "obsid": row["obsid"],
            "target_name": row["target_name"],
            "sector": row["sector"],
            "source_name": source.name,
            "source_size_bytes": row["size_bytes"],
            "source_sha256": digest,
            "sha256": payload_hash,
            **metrics,
        }
        profiles.append(profile)
        if consumer is not None:
            consumer(row, payload, profile)
    summary = {
        "dataset_id": DATASET_ID,
        "series_id": SERIES_ID,
        "sample_count": len(profiles),
        "target_count": len({profile["target_name"] for profile in profiles}),
        "sectors": sorted({profile["sector"] for profile in profiles}),
        "source_size_bytes": sum(int(profile["source_size_bytes"]) for profile in profiles),
        "source_row_count": sum(int(profile["source_row_count"]) for profile in profiles),
        "value_count": sum(int(profile["value_count"]) for profile in profiles),
        "total_size_bytes": sum(int(profile["sample_size_bytes"]) for profile in profiles),
        "dropped_nonzero_quality": sum(int(profile["dropped_nonzero_quality"]) for profile in profiles),
        "dropped_nonfinite_flux": sum(int(profile["dropped_nonfinite_flux"]) for profile in profiles),
        "lightcurves": profiles,
    }
    exact = {
        "sample_count": EXPECTED_SAMPLES,
        "target_count": EXPECTED_TARGETS,
        "sectors": sorted(EXPECTED_SECTORS),
        "source_size_bytes": EXPECTED_SOURCE_BYTES,
        "source_row_count": EXPECTED_SOURCE_ROWS,
        "value_count": EXPECTED_VALUES,
        "total_size_bytes": EXPECTED_OUTPUT_BYTES,
        "dropped_nonzero_quality": EXPECTED_DROPPED_QUALITY,
        "dropped_nonfinite_flux": EXPECTED_DROPPED_NONFINITE,
    }
    for key, value in exact.items():
        if summary[key] != value:
            raise SystemExit(f"aggregate {key} changed: {summary[key]} != {value}")
    return summary


def build(args: argparse.Namespace) -> None:
    validate_rights(args.mast_page, args.nasa_guidelines)
    if args.samples_dir.exists():
        shutil.rmtree(args.samples_dir)
    series_dir = args.samples_dir / SERIES_ID
    series_dir.mkdir(parents=True)
    index_rows: list[dict[str, object]] = []

    def emit(row: dict[str, object], payload: bytes, profile: dict[str, object]) -> None:
        output = series_dir / f"tic_{int(row['target_name']):016d}_sector_{int(row['sector']):04d}.bin"
        output.write_bytes(payload)
        index_rows.append({
            "dataset_id": DATASET_ID,
            "series_id": SERIES_ID,
            "role": "primary",
            "sample_path": output.relative_to(args.data_root).as_posix(),
            "source_sample": (args.fits_dir / str(row["filename"])).relative_to(args.data_root).as_posix(),
            "source_uri": row["data_uri"],
            "source_sha256": profile["source_sha256"],
            "obsid": row["obsid"],
            "tic_id": row["target_name"],
            "sector": row["sector"],
            "date_obs": profile["date_obs"],
            "date_end": profile["date_end"],
            "numeric_kind": "float",
            "bit_width": 32,
            "endianness": "little",
            "element_size_bytes": 4,
            "value_count": profile["value_count"],
            "sample_size_bytes": profile["sample_size_bytes"],
            "sample_format": "raw homogeneous IEEE-754 float32 stellar light curve",
            "sample_geometry": "tess_target_sector_lightcurve_1d",
            "sample_rank": 1,
            "sample_shape": [profile["value_count"]],
            "sample_axes": ["valid_cadence_time"],
            "natural_record_kind": "complete_tess_target_sector_pdcsap_lightcurve",
            "source_row_count": profile["source_row_count"],
            "dropped_nonzero_quality": profile["dropped_nonzero_quality"],
            "dropped_nonfinite_flux": profile["dropped_nonfinite_flux"],
            "minimum": profile["minimum"],
            "maximum": profile["maximum"],
            "distinct_values": profile["distinct_values"],
            "sha256": profile["sha256"],
        })

    summary = scan(args.selection, args.fits_dir, emit)
    args.index.parent.mkdir(parents=True, exist_ok=True)
    args.index.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in index_rows), encoding="utf-8")
    args.stats.parent.mkdir(parents=True, exist_ok=True)
    args.stats.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in summary.items() if key != "lightcurves"}, indent=2, sort_keys=True))


def verify(args: argparse.Namespace) -> None:
    validate_rights(args.mast_page, args.nasa_guidelines)
    if not args.index.is_file() or not args.stats.is_file():
        raise SystemExit("missing index or stats; run build first")
    indexed = [json.loads(line) for line in args.index.read_text().splitlines() if line.strip()]
    cursor = 0
    expected_outputs: set[Path] = set()

    def compare(row: dict[str, object], payload: bytes, profile: dict[str, object]) -> None:
        nonlocal cursor
        if cursor >= len(indexed):
            raise SystemExit("sample index has fewer rows than selected FITS files")
        entry = indexed[cursor]
        cursor += 1
        required = {
            "dataset_id": DATASET_ID, "series_id": SERIES_ID, "role": "primary",
            "source_sha256": profile["source_sha256"], "obsid": row["obsid"],
            "tic_id": row["target_name"], "sector": row["sector"],
            "numeric_kind": "float", "bit_width": 32, "endianness": "little",
            "element_size_bytes": 4, "value_count": profile["value_count"],
            "sample_size_bytes": profile["sample_size_bytes"],
            "source_row_count": profile["source_row_count"],
            "dropped_nonzero_quality": profile["dropped_nonzero_quality"],
            "dropped_nonfinite_flux": profile["dropped_nonfinite_flux"],
            "minimum": profile["minimum"], "maximum": profile["maximum"],
            "distinct_values": profile["distinct_values"], "sha256": profile["sha256"],
        }
        for key, expected in required.items():
            if entry.get(key) != expected:
                raise SystemExit(f"index mismatch for {row['filename']}: {key}")
        output = args.data_root / str(entry.get("sample_path", ""))
        if not output.is_file() or output.read_bytes() != payload:
            raise SystemExit(f"output differs from fresh FITS-table extraction: {output}")
        expected_outputs.add(output.resolve())

    summary = scan(args.selection, args.fits_dir, compare)
    if cursor != len(indexed):
        raise SystemExit("sample index has extra rows")
    actual_outputs = {path.resolve() for path in args.samples_dir.rglob("*.bin")}
    if actual_outputs != expected_outputs:
        raise SystemExit("sample directory contains missing or stale outputs")
    recorded = json.loads(args.stats.read_text())
    if recorded != summary:
        raise SystemExit("ingest stats differ from fresh source scan")
    print(f"verified_samples={cursor} values={summary['value_count']} bytes={summary['total_size_bytes']}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("build", "verify"))
    parser.add_argument("--selection", type=Path, required=True)
    parser.add_argument("--fits-dir", type=Path, required=True)
    parser.add_argument("--mast-page", type=Path, required=True)
    parser.add_argument("--nasa-guidelines", type=Path, required=True)
    parser.add_argument("--samples-dir", type=Path, required=True)
    parser.add_argument("--index", type=Path, required=True)
    parser.add_argument("--stats", type=Path, required=True)
    parser.add_argument("--data-root", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "build":
        build(args)
    else:
        verify(args)


if __name__ == "__main__":
    main()
