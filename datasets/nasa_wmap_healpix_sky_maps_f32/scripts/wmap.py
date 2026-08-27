#!/usr/bin/env python3
"""Preflight, build, and verify official WMAP HEALPix float32 fields."""
from __future__ import annotations

import argparse
import array
import csv
import hashlib
import html
import json
import math
import mmap
from pathlib import Path
import re
import shutil
import sys
from typing import Any, Callable


BLOCK = 2880
CARD = 80
BANDS = ("K", "Ka", "Q", "V", "W")
COLUMNS = (
    ("TEMPERATURE", "mK,thermodynamic"),
    ("Q_POLARISATION", "mK,thermodynamic"),
    ("U_POLARISATION", "mK,thermodynamic"),
    ("N_OBS", "counts"),
)
WEIGHT_COLUMNS = (
    ("N_OBS", ""),
    ("QQ", "counts"),
    ("QU", "counts"),
    ("UU", "counts"),
)
EXPECTED_ROWS = 3_145_728
EXPECTED_ROW_BYTES = 16
EXPECTED_FILE_BYTES = 100_676_160
EXPECTED_COLUMNS = ("band", "filename", "size_bytes", "source_sha256", "url")
FIELD_ORDER = (
    "TEMPERATURE", "Q_POLARISATION", "U_POLARISATION", "N_OBS",
    "QQ", "QU", "UU",
)
SERIES_IDS = {
    "TEMPERATURE": "wmap_temperature_f32",
    "Q_POLARISATION": "wmap_q_polarisation_f32",
    "U_POLARISATION": "wmap_u_polarisation_f32",
    "N_OBS": "wmap_n_obs_f32",
    "QQ": "wmap_qq_weight_f32",
    "QU": "wmap_qu_weight_f32",
    "UU": "wmap_uu_weight_f32",
}
EXPECTED_PRODUCTS_PAGE = (
    75_543,
    "ba6d9fbe395cc5b032cce70367042a3fa1bc830416472977cff238ea1a960d36",
)
EXPECTED_RIGHTS_PAGE = (
    308_617,
    "3003114a6e2f73365f8824cc08c8b3cb2d6518a7b9f96cb12db6308dc36c10e5",
)
EXPECTED_VALUES_PER_SERIES = EXPECTED_ROWS * len(BANDS)
EXPECTED_BYTES_PER_SERIES = EXPECTED_VALUES_PER_SERIES * 4
EXPECTED_TOTAL_VALUES = EXPECTED_VALUES_PER_SERIES * len(FIELD_ORDER)
EXPECTED_TOTAL_BYTES = EXPECTED_BYTES_PER_SERIES * len(FIELD_ORDER)
EXPECTED_AGGREGATE_SHA256 = {
    "TEMPERATURE": "e1620bb5954f2f8571f3549ba688730ca4a03387042e0574d3c0fe0b9101d735",
    "Q_POLARISATION": "640115c81b319ef9af20b68bcf987bb251f76b2f5a106af8b1c63ff4d26a6584",
    "U_POLARISATION": "99a73fc51a8be92c5beefbafedabc6b4f963cb75a2cf52313d42983bfa60406e",
    "N_OBS": "dc7940d460a74c1eb9ee8f731852b77a1d78831cce425a2b8dda0e64c8d32fd7",
    "QQ": "f6fb2062e73372fa6c41044d72b35502c8485185a5f5c687257e31f4f0c2323e",
    "QU": "fefa0d5c7ba5b6a170fb7823895d33238a397c30ca90f888af03b358c529e931",
    "UU": "61c49d549ffce9b7720cd7d857c558a19106defe4a749823d5fbae0cb75b39ba",
}
FieldConsumer = Callable[
    [dict[str, str], str, bytes, dict[str, object]], None
]


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def normalized_html(path: Path) -> str:
    text = path.read_text(encoding="utf-8", errors="replace")
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", html.unescape(text)).lower()


def validate_identity(path: Path, expected: tuple[int, str], label: str) -> None:
    if not path.is_file():
        raise SystemExit(f"missing {label}: {path}")
    if path.stat().st_size != expected[0] or file_hash(path) != expected[1]:
        raise SystemExit(f"{label} identity mismatch")


def load_selection(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        if tuple(reader.fieldnames or ()) != EXPECTED_COLUMNS:
            raise SystemExit("selection.tsv schema changed")
        rows = list(reader)
    if tuple(row["band"] for row in rows) != BANDS:
        raise SystemExit("band selection count or order changed")
    if any(int(row["size_bytes"]) != EXPECTED_FILE_BYTES for row in rows):
        raise SystemExit("selected remote size changed")
    return rows


def validate_pages(download_dir: Path) -> dict[str, dict[str, object]]:
    products = download_dir / "wmap_products.html"
    rights = download_dir / "nasa_media_usage.html"
    validate_identity(products, EXPECTED_PRODUCTS_PAGE, "WMAP product page")
    validate_identity(rights, EXPECTED_RIGHTS_PAGE, "NASA rights page")
    product_text = normalized_html(products)
    for phrase in (
        "wmap dr5 data products",
        "full resolution coadded nine year sky maps",
        "i,q,u maps per frequency band",
        "healpix nside=512",
    ):
        if phrase not in product_text:
            raise SystemExit(f"WMAP product page lacks expected phrase: {phrase}")
    rights_text = normalized_html(rights)
    for phrase in (
        "nasa is committed to transparency, open science, and making data available to everyone",
        "use of nasa content to train ai models does not constitute endorsement by nasa",
        "generally are not subject to copyright in the united states",
    ):
        if phrase not in rights_text:
            raise SystemExit(f"NASA guidance lacks expected phrase: {phrase}")
    return {
        "wmap_products": {
            "size_bytes": products.stat().st_size,
            "sha256": file_hash(products),
        },
        "nasa_media_usage": {
            "size_bytes": rights.stat().st_size,
            "sha256": file_hash(rights),
        },
    }


def parse_value(card: bytes) -> object:
    raw = card[10:80].decode("ascii", errors="strict").rstrip()
    if raw.startswith("'"):
        chars: list[str] = []
        index = 1
        while index < len(raw):
            if raw[index] == "'":
                if index + 1 < len(raw) and raw[index + 1] == "'":
                    chars.append("'")
                    index += 2
                    continue
                break
            chars.append(raw[index])
            index += 1
        return "".join(chars).strip()
    token = raw.split("/", 1)[0].strip()
    if token in {"T", "F"}:
        return token == "T"
    try:
        return int(token)
    except ValueError:
        try:
            return float(token.replace("D", "E"))
        except ValueError:
            return token


def read_header(data: mmap.mmap, offset: int) -> tuple[dict[str, object], int]:
    header: dict[str, object] = {}
    cursor = offset
    while cursor + CARD <= len(data):
        card = data[cursor : cursor + CARD]
        cursor += CARD
        keyword = card[:8].decode("ascii", errors="strict").strip()
        if keyword == "END":
            return header, ((cursor + BLOCK - 1) // BLOCK) * BLOCK
        if card[8:10] == b"= ":
            header[keyword] = parse_value(card)
    raise ValueError(f"unterminated FITS header at byte {offset}")


def product(values: list[int]) -> int:
    result = 1
    for value in values:
        result *= value
    return result


def hdu_data_size(header: dict[str, object]) -> int:
    bitpix = abs(int(header.get("BITPIX", 0)))
    naxis = int(header.get("NAXIS", 0))
    axes = [int(header.get(f"NAXIS{index}", 0)) for index in range(1, naxis + 1)]
    pcount = int(header.get("PCOUNT", 0))
    gcount = int(header.get("GCOUNT", 1))
    elements = pcount + (product(axes) if axes else 0)
    if bitpix == 0 or bitpix % 8:
        raise ValueError(f"invalid BITPIX={header.get('BITPIX')!r}")
    return elements * gcount * (bitpix // 8)


def hdu_layout(data: mmap.mmap) -> list[dict[str, Any]]:
    hdus = []
    offset = 0
    while offset < len(data):
        header, data_start = read_header(data, offset)
        data_size = hdu_data_size(header)
        hdus.append({
            "header": header,
            "header_offset": offset,
            "data_offset": data_start,
            "data_size_bytes": data_size,
        })
        offset = data_start + ((data_size + BLOCK - 1) // BLOCK) * BLOCK
    if offset != len(data):
        raise ValueError(f"HDU layout ends at {offset}, file has {len(data)} bytes")
    return hdus


def public_hdu_profile(hdu: dict[str, Any]) -> dict[str, object]:
    header = hdu["header"]
    naxis = int(header.get("NAXIS", 0))
    return {
        "header_offset": hdu["header_offset"],
        "data_offset": hdu["data_offset"],
        "data_size_bytes": hdu["data_size_bytes"],
        "xtension": header.get("XTENSION", "PRIMARY"),
        "extname": header.get("EXTNAME", ""),
        "bitpix": header.get("BITPIX"),
        "naxis": naxis,
        "axes": [header.get(f"NAXIS{index}") for index in range(1, naxis + 1)],
        "pcount": header.get("PCOUNT", 0),
        "gcount": header.get("GCOUNT", 1),
    }


def profile_column(
    values: array.array, index: int
) -> tuple[dict[str, object], bytes]:
    field = values[index::4]
    finite = [value for value in field if math.isfinite(value)]
    if not finite:
        raise ValueError("column has no finite values")
    little = array.array("f", field)
    if sys.byteorder != "little":
        little.byteswap()
    distinct_probe: set[bytes] = set()
    raw_little = little.tobytes()
    for offset in range(0, len(raw_little), 4):
        if len(distinct_probe) >= 10_000:
            break
        distinct_probe.add(raw_little[offset : offset + 4])
    return {
        "value_count": len(field),
        "size_bytes": len(raw_little),
        "finite_count": len(finite),
        "nonfinite_count": len(field) - len(finite),
        "healpix_unseen_like_count": sum(value <= -1.0e30 for value in finite),
        "zero_count": field.count(0.0),
        "integer_valued_count": sum(value.is_integer() for value in finite),
        "minimum_finite": min(finite),
        "maximum_finite": max(finite),
        "distinct_words_at_least": len(distinct_probe),
        "little_endian_sha256": hashlib.sha256(raw_little).hexdigest(),
    }, raw_little


def inspect_source(
    path: Path,
    row: dict[str, str],
    consumer: Callable[[str, bytes, dict[str, object]], None] | None = None,
) -> dict[str, object]:
    validate_identity(
        path,
        (int(row["size_bytes"]), row["source_sha256"]),
        f"WMAP {row['band']} map",
    )
    with path.open("rb") as handle:
        with mmap.mmap(handle.fileno(), 0, access=mmap.ACCESS_READ) as data:
            try:
                hdus = hdu_layout(data)
            except (UnicodeDecodeError, ValueError) as error:
                raise SystemExit(f"{path.name}: {error}") from error
            if len(hdus) != 3:
                raise SystemExit(f"{path.name}: expected exactly three HDUs")
            primary = hdus[0]["header"]
            table_hdu = hdus[1]
            table = table_hdu["header"]
            if (
                primary.get("SIMPLE") is not True
                or primary.get("TELESCOP") != "WMAP"
                or primary.get("FREQ") != f"{row['band']} band"
                or int(primary.get("NAXIS", -1)) != 0
            ):
                raise SystemExit(f"{path.name}: primary identity changed")
            if (
                table.get("XTENSION") != "BINTABLE"
                or table.get("EXTNAME") != "Stokes Maps"
                or int(table.get("NAXIS1", 0)) != EXPECTED_ROW_BYTES
                or int(table.get("NAXIS2", 0)) != EXPECTED_ROWS
                or int(table.get("TFIELDS", 0)) != len(COLUMNS)
                or table.get("PIXTYPE") != "HEALPIX"
                or table.get("ORDERING") != "NESTED"
                or int(table.get("NSIDE", 0)) != 512
                or int(table.get("FIRSTPIX", -1)) != 0
                or int(table.get("LASTPIX", -1)) != EXPECTED_ROWS - 1
            ):
                raise SystemExit(f"{path.name}: Stokes-map layout changed")
            for column_index, (name, unit) in enumerate(COLUMNS, 1):
                if (
                    table.get(f"TTYPE{column_index}") != name
                    or table.get(f"TFORM{column_index}") != "E"
                    or table.get(f"TUNIT{column_index}") != unit
                ):
                    raise SystemExit(f"{path.name}: column {column_index} changed")
            start = int(table_hdu["data_offset"])
            size = int(table_hdu["data_size_bytes"])
            if size != EXPECTED_ROWS * EXPECTED_ROW_BYTES:
                raise SystemExit(f"{path.name}: Stokes table byte count changed")
            values = array.array("f")
            values.frombytes(data[start : start + size])
            if sys.byteorder == "little":
                values.byteswap()
            if len(values) != EXPECTED_ROWS * 4:
                raise SystemExit(f"{path.name}: decoded value count changed")
            column_profiles: dict[str, dict[str, object]] = {}
            first_n_obs = b""
            for index, (name, _) in enumerate(COLUMNS):
                metrics, payload = profile_column(values, index)
                column_profiles[name] = metrics
                if (
                    int(metrics["distinct_words_at_least"]) < 100
                    or int(metrics["nonfinite_count"]) != 0
                    or int(metrics["healpix_unseen_like_count"]) != 0
                ):
                    raise SystemExit(f"{path.name}: invalid or degenerate {name} field")
                if name == "N_OBS":
                    first_n_obs = payload
                if consumer is not None:
                    consumer(name, payload, metrics)
            del values

            weight_hdu = hdus[2]
            weight = weight_hdu["header"]
            if (
                weight.get("XTENSION") != "BINTABLE"
                or weight.get("EXTNAME") != "Weight Arrays"
                or int(weight.get("NAXIS1", 0)) != EXPECTED_ROW_BYTES
                or int(weight.get("NAXIS2", 0)) != EXPECTED_ROWS
                or int(weight.get("TFIELDS", 0)) != len(WEIGHT_COLUMNS)
                or weight.get("PIXTYPE") != "HEALPIX"
                or weight.get("ORDERING") != "NESTED"
                or int(weight.get("NSIDE", 0)) != 512
                or int(weight.get("FIRSTPIX", -1)) != 0
                or int(weight.get("LASTPIX", -1)) != EXPECTED_ROWS - 1
            ):
                raise SystemExit(f"{path.name}: weight-array layout changed")
            for column_index, (name, unit) in enumerate(WEIGHT_COLUMNS, 1):
                if (
                    weight.get(f"TTYPE{column_index}") != name
                    or weight.get(f"TFORM{column_index}") != "E"
                    or str(weight.get(f"TUNIT{column_index}", "")) != unit
                ):
                    raise SystemExit(
                        f"{path.name}: weight column {column_index} changed"
                    )
            weight_start = int(weight_hdu["data_offset"])
            weight_size = int(weight_hdu["data_size_bytes"])
            if weight_size != EXPECTED_ROWS * EXPECTED_ROW_BYTES:
                raise SystemExit(f"{path.name}: weight table byte count changed")
            weight_values = array.array("f")
            weight_values.frombytes(data[weight_start : weight_start + weight_size])
            if sys.byteorder == "little":
                weight_values.byteswap()
            if len(weight_values) != EXPECTED_ROWS * 4:
                raise SystemExit(f"{path.name}: decoded weight count changed")
            weight_profiles: dict[str, dict[str, object]] = {}
            for index, (name, _) in enumerate(WEIGHT_COLUMNS):
                metrics, payload = profile_column(weight_values, index)
                weight_profiles[name] = metrics
                if (
                    int(metrics["distinct_words_at_least"]) < 100
                    or int(metrics["nonfinite_count"]) != 0
                    or int(metrics["healpix_unseen_like_count"]) != 0
                ):
                    raise SystemExit(f"{path.name}: invalid or degenerate {name} field")
                if name == "N_OBS":
                    if payload != first_n_obs:
                        raise SystemExit(f"{path.name}: repeated N_OBS columns differ")
                elif consumer is not None:
                    consumer(name, payload, metrics)
    return {
        "band": row["band"],
        "filename": path.name,
        "size_bytes": path.stat().st_size,
        "sha256": row["source_sha256"],
        "hdu_count": len(hdus),
        "hdus": [public_hdu_profile(hdu) for hdu in hdus],
        "stokes_map": {
            "nside": 512,
            "ordering": "NESTED",
            "pixel_count": EXPECTED_ROWS,
            "column_profiles": column_profiles,
        },
        "weight_arrays": {
            "nside": 512,
            "ordering": "NESTED",
            "pixel_count": EXPECTED_ROWS,
            "repeated_n_obs_byte_identical": True,
            "column_profiles": weight_profiles,
        },
    }


def scan_source(
    selection: Path,
    download_dir: Path,
    consumer: FieldConsumer | None = None,
) -> dict[str, object]:
    rows = load_selection(selection)
    pages = validate_pages(download_dir)
    aggregates = {field: hashlib.sha256() for field in FIELD_ORDER}
    output_hashes = {field: set() for field in FIELD_ORDER}
    sources = []
    for row in rows:
        def observe(field: str, payload: bytes, metrics: dict[str, object]) -> None:
            digest = str(metrics["little_endian_sha256"])
            if digest in output_hashes[field]:
                raise SystemExit(f"duplicate {field} payload for band {row['band']}")
            output_hashes[field].add(digest)
            aggregates[field].update(payload)
            if consumer is not None:
                consumer(row, field, payload, metrics)

        sources.append(
            inspect_source(download_dir / row["filename"], row, observe)
        )
    series_profiles = {}
    for field in FIELD_ORDER:
        profile = {
            "series_id": SERIES_IDS[field],
            "sample_count": len(BANDS),
            "value_count": EXPECTED_VALUES_PER_SERIES,
            "total_size_bytes": EXPECTED_BYTES_PER_SERIES,
            "aggregate_band_order_sha256": aggregates[field].hexdigest(),
        }
        pinned = EXPECTED_AGGREGATE_SHA256.get(field)
        if pinned and profile["aggregate_band_order_sha256"] != pinned:
            raise SystemExit(f"aggregate {field} payload hash changed")
        series_profiles[field] = profile
    return {
        "dataset_id": "nasa_wmap_healpix_sky_maps_f32",
        "pages": pages,
        "source_count": len(sources),
        "source_size_bytes": sum(int(source["size_bytes"]) for source in sources),
        "healpix_nside": 512,
        "healpix_ordering": "NESTED",
        "pixels_per_sample": EXPECTED_ROWS,
        "series_count": len(FIELD_ORDER),
        "sample_count": len(FIELD_ORDER) * len(BANDS),
        "primary_value_count": EXPECTED_TOTAL_VALUES,
        "primary_size_bytes": EXPECTED_TOTAL_BYTES,
        "series_profiles": series_profiles,
        "sources": sources,
    }


def index_entry(
    row: dict[str, str],
    field: str,
    metrics: dict[str, object],
    output: Path,
    source: Path,
    data_root: Path,
) -> dict[str, object]:
    source_fields = {
        "TEMPERATURE": "Stokes Maps.TEMPERATURE",
        "Q_POLARISATION": "Stokes Maps.Q_POLARISATION",
        "U_POLARISATION": "Stokes Maps.U_POLARISATION",
        "N_OBS": "Stokes Maps.N_OBS (duplicate Weight Arrays.N_OBS excluded)",
        "QQ": "Weight Arrays.QQ",
        "QU": "Weight Arrays.QU",
        "UU": "Weight Arrays.UU",
    }
    units = {
        "TEMPERATURE": "mK,thermodynamic",
        "Q_POLARISATION": "mK,thermodynamic",
        "U_POLARISATION": "mK,thermodynamic",
        "N_OBS": "counts",
        "QQ": "counts",
        "QU": "counts",
        "UU": "counts",
    }
    return {
        "dataset_id": "nasa_wmap_healpix_sky_maps_f32",
        "series_id": SERIES_IDS[field],
        "role": "primary",
        "sample_path": output.relative_to(data_root).as_posix(),
        "source_sample": source.relative_to(data_root).as_posix(),
        "source_field": source_fields[field],
        "band": row["band"],
        "units": units[field],
        "numeric_kind": "float",
        "bit_width": 32,
        "endianness": "little",
        "element_size_bytes": 4,
        "value_count": metrics["value_count"],
        "sample_size_bytes": metrics["size_bytes"],
        "sample_format": "raw homogeneous IEEE-754 float32 HEALPix field",
        "sample_geometry": "full_sky_healpix_nested_sphere_1d",
        "sample_rank": 1,
        "sample_shape": [EXPECTED_ROWS],
        "sample_axes": ["healpix_nested_pixel_index"],
        "healpix_nside": 512,
        "healpix_ordering": "NESTED",
        "natural_record_kind": "complete_wmap_frequency_band_healpix_field",
        "finite_count": metrics["finite_count"],
        "nonfinite_count": metrics["nonfinite_count"],
        "healpix_unseen_like_count": metrics["healpix_unseen_like_count"],
        "zero_count": metrics["zero_count"],
        "minimum_finite": metrics["minimum_finite"],
        "maximum_finite": metrics["maximum_finite"],
        "distinct_words_at_least": metrics["distinct_words_at_least"],
        "sha256": metrics["little_endian_sha256"],
    }


def preflight(args: argparse.Namespace) -> None:
    result = scan_source(args.selection, args.download_dir)
    args.profile.parent.mkdir(parents=True, exist_ok=True)
    args.profile.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps({key: value for key, value in result.items() if key != "sources"}, indent=2, sort_keys=True))


def build(args: argparse.Namespace) -> None:
    if args.samples_dir.exists():
        shutil.rmtree(args.samples_dir)
    args.samples_dir.mkdir(parents=True)
    args.index.parent.mkdir(parents=True, exist_ok=True)
    index_rows: list[dict[str, object]] = []

    def emit(
        row: dict[str, str], field: str, payload: bytes, metrics: dict[str, object]
    ) -> None:
        series_dir = args.samples_dir / SERIES_IDS[field]
        series_dir.mkdir(exist_ok=True)
        slug = field.lower()
        output = series_dir / f"wmap_9yr_{row['band'].lower()}_{slug}_f32_n3145728.bin"
        output.write_bytes(payload)
        source = args.download_dir / row["filename"]
        index_rows.append(
            index_entry(row, field, metrics, output, source, args.data_root)
        )

    result = scan_source(args.selection, args.download_dir, emit)
    args.index.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in index_rows),
        encoding="utf-8",
    )
    args.stats.parent.mkdir(parents=True, exist_ok=True)
    args.stats.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps({key: value for key, value in result.items() if key != "sources"}, indent=2, sort_keys=True))


def verify(args: argparse.Namespace) -> None:
    if not args.index.is_file() or not args.stats.is_file():
        raise SystemExit("missing index or statistics; run build first")
    indexed = [
        json.loads(line)
        for line in args.index.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    cursor = 0
    expected_outputs: set[Path] = set()

    def compare(
        row: dict[str, str], field: str, payload: bytes, metrics: dict[str, object]
    ) -> None:
        nonlocal cursor
        if cursor >= len(indexed):
            raise SystemExit("sample index has fewer rows than fields")
        series_dir = args.samples_dir / SERIES_IDS[field]
        output = series_dir / (
            f"wmap_9yr_{row['band'].lower()}_{field.lower()}_f32_n3145728.bin"
        )
        source = args.download_dir / row["filename"]
        expected = index_entry(row, field, metrics, output, source, args.data_root)
        if indexed[cursor] != expected:
            raise SystemExit(f"index mismatch at row {cursor + 1}")
        cursor += 1
        if not output.is_file() or output.read_bytes() != payload:
            raise SystemExit(f"output differs from fresh FITS extraction: {output}")
        expected_outputs.add(output.resolve())

    result = scan_source(args.selection, args.download_dir, compare)
    if cursor != len(indexed):
        raise SystemExit("sample index has extra rows")
    actual_outputs = {path.resolve() for path in args.samples_dir.rglob("*.bin")}
    if actual_outputs != expected_outputs:
        raise SystemExit("sample directory contains missing or stale outputs")
    if json.loads(args.stats.read_text(encoding="utf-8")) != result:
        raise SystemExit("ingest statistics differ from fresh source scan")
    print(
        f"verified_samples={cursor} values={result['primary_value_count']} "
        f"bytes={result['primary_size_bytes']}"
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("preflight", "build", "verify"))
    parser.add_argument("--selection", type=Path, required=True)
    parser.add_argument("--download-dir", type=Path, required=True)
    parser.add_argument("--profile", type=Path)
    parser.add_argument("--samples-dir", type=Path)
    parser.add_argument("--index", type=Path)
    parser.add_argument("--stats", type=Path)
    parser.add_argument("--data-root", type=Path)
    args = parser.parse_args()
    if args.command == "preflight":
        if args.profile is None:
            parser.error("preflight requires --profile")
        preflight(args)
    elif args.command == "build":
        if any(value is None for value in (args.samples_dir, args.index, args.stats, args.data_root)):
            parser.error("build requires --samples-dir, --index, --stats, and --data-root")
        build(args)
    else:
        if any(value is None for value in (args.samples_dir, args.index, args.stats, args.data_root)):
            parser.error("verify requires --samples-dir, --index, --stats, and --data-root")
        verify(args)


if __name__ == "__main__":
    main()
