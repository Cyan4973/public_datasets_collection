#!/usr/bin/env python3
"""EPFL RGL material database: isotropic spectral BRDF `spectra` tensors.

Subcommands
  plan         print material, pinned size and URL for download.sh
  check-pages  validate the CC0 grant and the pinned material list on the
               official license and materials pages (used by download.sh)
  check-file   validate one downloaded *_spec.bsdf tensor file (download.sh)
  build        emit one little-endian float32 sample per material
  verify       independently re-derive and check every sample

Pure standard library. The Mitsuba/RGL `tensor_file` layout follows the
official reader (rgl-epfl/brdf-loader, powitacq.inl `Tensor::Tensor`):
  char[12] "tensor_file\\0", u8 major, u8 minor, u32 n_fields, then per field
  u16 name_length, name bytes, u16 ndim, u8 dtype, u64 offset, u64 shape[ndim]
with field payloads stored at absolute `offset`, little-endian, C order.
"""
from __future__ import annotations

import argparse
from array import array
import hashlib
import html
import json
import math
from pathlib import Path
import re
import shutil
import statistics
import struct
import sys
import tomllib

DATASET_ID = "rgl_epfl_isotropic_spectral_brdf_f32"
SERIES_ID = "rgl_isotropic_spectral_brdf_spectra_f32"
NATURAL_RECORD_KIND = "rgl_material_spectral_bsdf_spectra_tensor"
BASE_URL = "https://d38rqfq1h7iukm.cloudfront.net/media/materials"
MAGIC = b"tensor_file\x00"
FLOAT32 = 10
UINT8 = 1
UINT32 = 5
# powitacq.inl Tensor::Type: Invalid, UInt8, Int8, UInt16, Int16, UInt32,
# Int32, UInt64, Int64, Float16, Float32, Float64
DTYPE_SIZES = {1: 1, 2: 1, 3: 2, 4: 2, 5: 4, 6: 4, 7: 8, 8: 8, 9: 2, 10: 4, 11: 8}
EXPECTED_FIELDS = (
    "version",
    "description",
    "phi_i",
    "theta_i",
    "wavelengths",
    "sigma",
    "ndf",
    "vndf",
    "luminance",
    "spectra",
    "jacobian",
    "valid",
)
N_THETA_I = 8
N_WAVELENGTHS = 195
EXPECTED_MATERIALS = 51
EXPECTED_RESOLUTIONS = {32: 49, 48: 1, 64: 1}
EXPECTED_DOWNLOAD_BYTES = 397553744
EXPECTED_VALUES = 88258560
EXPECTED_SAMPLE_BYTES = 353034240
MIN_DISTINCT_VALUES = 1000
# SHA-256 over all samples concatenated in materials.tsv order (first build 2026-10-06)
EXPECTED_AGGREGATE_SHA256 = "468bf9defd2410df5c18237703d3665d0c0e477b50d567172b10dd53dff06ff9"
AXES = ["phi_i", "theta_i", "wavelength", "outgoing_sample_row", "outgoing_sample_col"]
LICENSE_SENTENCE = (
    "Unless otherwise noted, all material data is licensed under the "
    "Creative Commons Zero ( CC0 ) license."
)
CC0_URL = "https://creativecommons.org/publicdomain/zero/1.0/"
TSV_COLUMNS = [
    "material",
    "outgoing_resolution",
    "size_bytes",
    "md5_etag",
    "sha256",
    "last_modified",
    "spectra_offset",
    "pipeline_version",
    "tags",
    "description",
]


# --------------------------------------------------------------------------
# pinned material table


def load_materials(path: Path) -> list[dict]:
    lines = path.read_text(encoding="utf-8").splitlines()
    header = lines[0].split("\t")
    if header != TSV_COLUMNS:
        raise SystemExit(f"{path}: unexpected columns {header}")
    rows = []
    seen = set()
    for number, line in enumerate(lines[1:], 2):
        parts = line.split("\t")
        if len(parts) != len(TSV_COLUMNS):
            raise SystemExit(f"{path}:{number}: expected {len(TSV_COLUMNS)} columns")
        row = dict(zip(TSV_COLUMNS, parts))
        if not re.fullmatch(r"[a-z0-9_]+", row["material"]):
            raise SystemExit(f"{path}:{number}: bad material name {row['material']!r}")
        if row["material"] in seen:
            raise SystemExit(f"{path}:{number}: duplicate material {row['material']}")
        seen.add(row["material"])
        if not re.fullmatch(r"[0-9a-f]{32}", row["md5_etag"]):
            raise SystemExit(f"{path}:{number}: bad md5 {row['md5_etag']!r}")
        if not re.fullmatch(r"[0-9a-f]{64}", row["sha256"]):
            raise SystemExit(f"{path}:{number}: missing or bad pinned sha256 {row['sha256']!r}")
        for key in ("outgoing_resolution", "size_bytes", "spectra_offset"):
            row[key] = int(row[key])
        row["url"] = f"{BASE_URL}/{row['material']}/{row['material']}_spec.bsdf"
        row["filename"] = f"{row['material']}_spec.bsdf"
        rows.append(row)
    names = [row["material"] for row in rows]
    if names != sorted(names):
        raise SystemExit(f"{path}: materials must be sorted")
    if len(rows) != EXPECTED_MATERIALS:
        raise SystemExit(f"{path}: expected {EXPECTED_MATERIALS} materials, found {len(rows)}")
    resolutions: dict[int, int] = {}
    for row in rows:
        resolutions[row["outgoing_resolution"]] = resolutions.get(row["outgoing_resolution"], 0) + 1
    if resolutions != EXPECTED_RESOLUTIONS:
        raise SystemExit(f"{path}: resolution census {resolutions} != {EXPECTED_RESOLUTIONS}")
    if sum(row["size_bytes"] for row in rows) != EXPECTED_DOWNLOAD_BYTES:
        raise SystemExit(f"{path}: pinned sizes do not sum to {EXPECTED_DOWNLOAD_BYTES}")
    return rows


def spectra_shape(resolution: int) -> tuple[int, ...]:
    return (1, N_THETA_I, N_WAVELENGTHS, resolution, resolution)


def product(shape) -> int:
    total = 1
    for dim in shape:
        total *= dim
    return total


# --------------------------------------------------------------------------
# build-side tensor_file parser (streaming reads)


def read_exact(fh, count: int, context: str) -> bytes:
    data = fh.read(count)
    if len(data) != count:
        raise ValueError(f"truncated tensor header while reading {context}")
    return data


def parse_header_stream(path: Path) -> dict[str, dict]:
    file_size = path.stat().st_size
    fields: dict[str, dict] = {}
    with path.open("rb") as fh:
        if read_exact(fh, 12, "magic") != MAGIC:
            raise ValueError(f"{path.name}: not a tensor_file")
        major, minor = read_exact(fh, 2, "version")
        if (major, minor) != (1, 0):
            raise ValueError(f"{path.name}: tensor_file version {major}.{minor} != 1.0")
        (n_fields,) = struct.unpack("<I", read_exact(fh, 4, "n_fields"))
        if not 1 <= n_fields <= 64:
            raise ValueError(f"{path.name}: implausible field count {n_fields}")
        for _ in range(n_fields):
            (name_length,) = struct.unpack("<H", read_exact(fh, 2, "name length"))
            name = read_exact(fh, name_length, "name").decode("ascii")
            (ndim,) = struct.unpack("<H", read_exact(fh, 2, "ndim"))
            dtype = read_exact(fh, 1, "dtype")[0]
            (offset,) = struct.unpack("<Q", read_exact(fh, 8, "offset"))
            shape = struct.unpack(f"<{ndim}Q", read_exact(fh, 8 * ndim, "shape"))
            if dtype not in DTYPE_SIZES:
                raise ValueError(f"{path.name}: field {name} has unknown dtype {dtype}")
            nbytes = DTYPE_SIZES[dtype] * product(shape)
            if offset + nbytes > file_size:
                raise ValueError(f"{path.name}: field {name} extends past end of file")
            if name in fields:
                raise ValueError(f"{path.name}: duplicate field {name}")
            fields[name] = {"dtype": dtype, "offset": offset, "shape": tuple(shape), "nbytes": nbytes}
        header_end = fh.tell()
    if tuple(fields) != EXPECTED_FIELDS:
        raise ValueError(f"{path.name}: field list {tuple(fields)} != {EXPECTED_FIELDS}")
    spans = sorted((f["offset"], f["offset"] + f["nbytes"], n) for n, f in fields.items())
    if spans[0][0] < header_end:
        raise ValueError(f"{path.name}: field payload overlaps the header")
    for (_, end, left), (start, _, right) in zip(spans, spans[1:]):
        if start < end:
            raise ValueError(f"{path.name}: fields {left} and {right} overlap")
    return fields


def read_field(path: Path, field: dict) -> bytes:
    with path.open("rb") as fh:
        fh.seek(field["offset"])
        return read_exact(fh, field["nbytes"], "field payload")


def floats(raw: bytes) -> array:
    values = array("f")
    values.frombytes(raw)
    if sys.byteorder != "little":
        values.byteswap()
    return values


def validate_tensor(path: Path, material: dict) -> dict:
    """Semantic checks shared by download.sh and build; returns field table."""
    fields = parse_header_stream(path)
    name = material["material"]
    spectra = fields["spectra"]
    want_shape = spectra_shape(material["outgoing_resolution"])
    if spectra["dtype"] != FLOAT32 or spectra["shape"] != want_shape:
        raise ValueError(f"{name}: spectra dtype/shape {spectra['dtype']}/{spectra['shape']} != {FLOAT32}/{want_shape}")
    if spectra["offset"] != material["spectra_offset"]:
        raise ValueError(f"{name}: spectra offset {spectra['offset']} != pinned {material['spectra_offset']}")
    checks = {
        "version": (UINT32, (2,)),
        "phi_i": (FLOAT32, (1,)),
        "theta_i": (FLOAT32, (N_THETA_I,)),
        "wavelengths": (FLOAT32, (N_WAVELENGTHS,)),
        "luminance": (FLOAT32, (1, N_THETA_I, material["outgoing_resolution"], material["outgoing_resolution"])),
        "jacobian": (UINT8, (1,)),
        "valid": (UINT8, (material["outgoing_resolution"] ** 2,)),
    }
    for field_name, (dtype, shape) in checks.items():
        field = fields[field_name]
        if (field["dtype"], field["shape"]) != (dtype, shape):
            raise ValueError(f"{name}: field {field_name} dtype/shape {field['dtype']}/{field['shape']} != {dtype}/{shape}")
    description = read_field(path, fields["description"]).decode("utf-8")
    if description != material["description"]:
        raise ValueError(f"{name}: description {description!r} != pinned {material['description']!r}")
    wavelengths = floats(read_field(path, fields["wavelengths"]))
    if not (350.0 < wavelengths[0] < 365.0 and 995.0 < wavelengths[-1] < 1010.0):
        raise ValueError(f"{name}: wavelength grid {wavelengths[0]}..{wavelengths[-1]} outside 358..1002 nm")
    if any(b <= a for a, b in zip(wavelengths, wavelengths[1:])):
        raise ValueError(f"{name}: wavelength grid not strictly increasing")
    theta = floats(read_field(path, fields["theta_i"]))
    if theta[0] != 0.0 or any(b <= a for a, b in zip(theta, theta[1:])) or theta[-1] > math.pi / 2 + 1e-5:
        raise ValueError(f"{name}: theta_i grid {list(theta)} is not increasing within [0, pi/2]")
    if read_field(path, fields["jacobian"]) != b"\x01":
        raise ValueError(f"{name}: jacobian flag is not 1 (spectra convention changed)")
    return {"fields": fields, "wavelengths": wavelengths, "theta_i": theta}


# --------------------------------------------------------------------------
# download-time checks


def file_digest(path: Path, algorithm: str) -> str:
    digest = hashlib.new(algorithm)
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def page_text(path: Path) -> str:
    text = path.read_text(encoding="utf-8", errors="replace")
    text = re.sub(r"<script.*?</script>", " ", text, flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def cmd_plan(args: argparse.Namespace) -> None:
    for material in load_materials(args.materials):
        print(f"{material['material']}\t{material['size_bytes']}\t{material['url']}")


def cmd_check_pages(args: argparse.Namespace) -> None:
    materials = load_materials(args.materials)
    license_text = page_text(args.license_page)
    if LICENSE_SENTENCE not in license_text:
        raise SystemExit("license page no longer contains the CC0 grant sentence")
    raw = args.materials_page.read_text(encoding="utf-8", errors="replace")
    if CC0_URL not in raw:
        raise SystemExit("materials page no longer links the CC0 1.0 deed in the per-material panel")
    listed = re.findall(r"dl_spec:\s*'([^']+)'", raw)
    missing = [m["material"] for m in materials if m["url"] not in listed]
    if missing:
        raise SystemExit(f"materials page no longer lists pinned spec files: {missing}")
    print(f"license_ok=1 cc0_link_ok=1 page_spec_files={len(listed)} pinned_listed={len(materials)}")


def cmd_check_file(args: argparse.Namespace) -> None:
    materials = {m["material"]: m for m in load_materials(args.materials)}
    material = materials[args.material]
    path = args.path
    size = path.stat().st_size
    if size != material["size_bytes"]:
        raise SystemExit(f"{args.material}: size {size} != pinned {material['size_bytes']}")
    md5 = file_digest(path, "md5")
    if md5 != material["md5_etag"]:
        raise SystemExit(f"{args.material}: md5 {md5} != pinned ETag {material['md5_etag']}")
    sha256 = file_digest(path, "sha256")
    if sha256 != material["sha256"]:
        raise SystemExit(f"{args.material}: sha256 {sha256} != pinned {material['sha256']}")
    info = validate_tensor(path, material)
    spectra = floats(read_field(path, info["fields"]["spectra"]))
    bad = sum(1 for value in spectra if not math.isfinite(value))
    if bad:
        raise SystemExit(f"{args.material}: {bad} non-finite spectra values")
    if max(spectra) <= 0.0:
        raise SystemExit(f"{args.material}: spectra tensor has no positive value")
    print(f"{sha256}")


# --------------------------------------------------------------------------
# build


def relative_to_data(path: Path, data_root: Path) -> str:
    return path.resolve().relative_to(data_root.resolve()).as_posix()


def cmd_build(args: argparse.Namespace) -> None:
    materials = load_materials(args.materials)
    data_root = args.data_root.resolve()
    output_dir = args.samples_dir / SERIES_ID
    temporary_dir = args.samples_dir / f".{SERIES_ID}.tmp"
    if temporary_dir.exists():
        shutil.rmtree(temporary_dir)
    temporary_dir.mkdir(parents=True)
    rows = []
    per_material = []
    aggregate = hashlib.sha256()
    wavelength_grid = None
    try:
        for material in materials:
            name = material["material"]
            source = args.downloads / "spec" / material["filename"]
            if not source.is_file():
                raise SystemExit(f"missing local source {source}; run download.sh first")
            if source.stat().st_size != material["size_bytes"]:
                raise SystemExit(f"{name}: local size differs from pinned size")
            source_md5 = file_digest(source, "md5")
            if source_md5 != material["md5_etag"]:
                raise SystemExit(f"{name}: local md5 differs from pinned ETag")
            source_sha256 = file_digest(source, "sha256")
            if source_sha256 != material["sha256"]:
                raise SystemExit(f"{name}: local sha256 differs from pinned value")
            info = validate_tensor(source, material)
            if wavelength_grid is None:
                wavelength_grid = info["wavelengths"]
            elif info["wavelengths"] != wavelength_grid:
                raise SystemExit(f"{name}: wavelength grid differs from the first material")
            spectra_field = info["fields"]["spectra"]
            payload = read_field(source, spectra_field)
            values = floats(payload)
            nonfinite = sum(1 for value in values if not math.isfinite(value))
            if nonfinite:
                raise SystemExit(f"{name}: {nonfinite} NaN/Inf spectra values")
            minimum = min(values)
            maximum = max(values)
            if maximum <= 0.0 or minimum == maximum:
                raise SystemExit(f"{name}: degenerate spectra tensor (min={minimum}, max={maximum})")
            zeros = values.count(0.0)
            negatives = sum(1 for value in values if value < 0.0)
            distinct = len(set(array("I", payload)))
            filename = f"{name}.bin"
            (temporary_dir / filename).write_bytes(payload)
            digest = hashlib.sha256(payload).hexdigest()
            aggregate.update(payload)
            shape = list(spectra_field["shape"])
            row = {
                "dataset_id": DATASET_ID,
                "series_id": SERIES_ID,
                "role": "primary",
                "sample_path": relative_to_data(output_dir, data_root) + "/" + filename,
                "numeric_kind": "float",
                "bit_width": 32,
                "endianness": "little",
                "element_size_bytes": 4,
                "sample_size_bytes": len(payload),
                "value_count": len(values),
                "shape": shape,
                "axes": AXES,
                "natural_record_kind": NATURAL_RECORD_KIND,
                "material": name,
                "description": material["description"],
                "tags": material["tags"],
                "pipeline_version": material["pipeline_version"],
                "outgoing_resolution": material["outgoing_resolution"],
                "source_url": material["url"],
                "source_size_bytes": material["size_bytes"],
                "source_md5": source_md5,
                "source_sha256": source_sha256,
                "spectra_offset": spectra_field["offset"],
                "sample_sha256": digest,
                "zero_count": zeros,
                "zero_fraction": round(zeros / len(values), 6),
                "negative_count": negatives,
                "distinct_bit_patterns": distinct,
                "min": minimum,
                "max": maximum,
            }
            rows.append(row)
            per_material.append({k: row[k] for k in ("material", "outgoing_resolution", "pipeline_version", "zero_fraction", "negative_count", "distinct_bit_patterns", "min", "max")})
            print(
                f"material={name} res={material['outgoing_resolution']} values={len(values)} "
                f"zero_fraction={zeros / len(values):.4f} negatives={negatives} distinct={distinct} "
                f"min={minimum:.6g} max={maximum:.6g}",
                flush=True,
            )
        total_values = sum(int(r["value_count"]) for r in rows)
        total_bytes = sum(int(r["sample_size_bytes"]) for r in rows)
        if (len(rows), total_values, total_bytes) != (EXPECTED_MATERIALS, EXPECTED_VALUES, EXPECTED_SAMPLE_BYTES):
            raise SystemExit(f"aggregate mismatch: samples={len(rows)} values={total_values} bytes={total_bytes}")
        if aggregate.hexdigest() != EXPECTED_AGGREGATE_SHA256:
            raise SystemExit(f"aggregate sample sha256 {aggregate.hexdigest()} != pinned {EXPECTED_AGGREGATE_SHA256}")
        if output_dir.exists():
            shutil.rmtree(output_dir)
        temporary_dir.replace(output_dir)
    except BaseException:
        if temporary_dir.exists():
            shutil.rmtree(temporary_dir)
        raise

    args.index.parent.mkdir(parents=True, exist_ok=True)
    index_tmp = args.index.with_suffix(".jsonl.tmp")
    with index_tmp.open("w", encoding="utf-8") as out:
        for row in rows:
            out.write(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n")
    index_tmp.replace(args.index)

    zero_fractions = [r["zero_fraction"] for r in rows]
    stats = {
        "dataset_id": DATASET_ID,
        "series_id": SERIES_ID,
        "sample_count": len(rows),
        "total_values": total_values,
        "total_size_bytes": total_bytes,
        "median_sample_values": statistics.median(int(r["value_count"]) for r in rows),
        "aggregate_sample_sha256": aggregate.hexdigest(),
        "wavelength_nm_first_last": [wavelength_grid[0], wavelength_grid[-1]],
        "zero_fraction_min_median_max": [min(zero_fractions), statistics.median(zero_fractions), max(zero_fractions)],
        "global_min": min(r["min"] for r in rows),
        "global_max": max(r["max"] for r in rows),
        "per_material": per_material,
    }
    args.stats.parent.mkdir(parents=True, exist_ok=True)
    stats_tmp = args.stats.with_suffix(".json.tmp")
    stats_tmp.write_text(json.dumps(stats, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    stats_tmp.replace(args.stats)
    print(json.dumps({k: v for k, v in stats.items() if k != "per_material"}, indent=2, sort_keys=True))


# --------------------------------------------------------------------------
# verify: independent re-derivation from the whole source file in memory


def parse_header_buffer(buf: bytes) -> dict[str, tuple[int, int, tuple[int, ...]]]:
    view = memoryview(buf)
    if bytes(view[:12]) != MAGIC or tuple(view[12:14]) != (1, 0):
        raise ValueError("bad tensor_file magic/version")
    (count,) = struct.unpack_from("<I", buf, 14)
    position = 18
    table = {}
    for _ in range(count):
        (length,) = struct.unpack_from("<H", buf, position)
        position += 2
        name = bytes(view[position:position + length]).decode("ascii")
        position += length
        ndim, dtype, offset = struct.unpack_from("<HBQ", buf, position)
        position += 11
        shape = struct.unpack_from("<" + "Q" * ndim, buf, position)
        position += 8 * ndim
        table[name] = (dtype, offset, tuple(shape))
    if tuple(table) != EXPECTED_FIELDS:
        raise ValueError(f"field list {tuple(table)} != {EXPECTED_FIELDS}")
    return table


def cmd_verify(args: argparse.Namespace) -> None:
    materials = load_materials(args.materials)
    data_root = args.data_root.resolve()
    manifest = tomllib.loads(args.manifest.read_text(encoding="utf-8"))
    series = [s for s in manifest["series"] if s["id"] == SERIES_ID]
    if len(series) != 1 or series[0]["role"] != "primary":
        raise SystemExit("manifest must declare exactly one primary series " + SERIES_ID)
    series = series[0]
    rows = [json.loads(line) for line in args.index.read_text(encoding="utf-8").splitlines() if line.strip()]
    if [r.get("material") for r in rows] != [m["material"] for m in materials]:
        raise SystemExit("index materials do not match the pinned list in order")
    sample_dir = args.samples_dir / SERIES_ID
    on_disk = sorted(p.name for p in sample_dir.iterdir())
    if on_disk != sorted(f"{m['material']}.bin" for m in materials):
        raise SystemExit(f"unexpected files in {sample_dir}")
    required = ["dataset_id", "series_id", "sample_path", "numeric_kind", "bit_width", "endianness", "element_size_bytes", "sample_size_bytes", "value_count"]
    exponent_mask = 0x7F800000
    total_values = total_bytes = 0
    digests = set()
    aggregate = hashlib.sha256()
    for material, row in zip(materials, rows):
        name = material["material"]
        for key in required:
            if key not in row:
                raise SystemExit(f"{name}: index row missing {key}")
        expected_meta = {"dataset_id": DATASET_ID, "series_id": SERIES_ID, "numeric_kind": "float", "bit_width": 32, "endianness": "little", "element_size_bytes": 4}
        for key, value in expected_meta.items():
            if row[key] != value:
                raise SystemExit(f"{name}: index {key}={row[key]!r} != {value!r}")
        source_bytes = (args.downloads / "spec" / material["filename"]).read_bytes()
        if len(source_bytes) != material["size_bytes"] or hashlib.md5(source_bytes).hexdigest() != material["md5_etag"]:
            raise SystemExit(f"{name}: source file differs from pinned size/ETag")
        if hashlib.sha256(source_bytes).hexdigest() != material["sha256"]:
            raise SystemExit(f"{name}: source file differs from pinned sha256")
        table = parse_header_buffer(source_bytes)
        dtype, offset, shape = table["spectra"]
        want_shape = spectra_shape(material["outgoing_resolution"])
        if dtype != FLOAT32 or shape != want_shape or offset != material["spectra_offset"]:
            raise SystemExit(f"{name}: spectra header {dtype}/{shape}/{offset} unexpected")
        count = product(shape)
        expected_payload = source_bytes[offset:offset + 4 * count]
        if len(expected_payload) != 4 * count:
            raise SystemExit(f"{name}: spectra payload truncated in source")
        sample_path = data_root / row["sample_path"]
        if sample_path.parent.resolve() != sample_dir.resolve() or sample_path.name != f"{name}.bin":
            raise SystemExit(f"{name}: unexpected sample path {row['sample_path']}")
        payload = sample_path.read_bytes()
        if payload != expected_payload:
            raise SystemExit(f"{name}: sample bytes differ from the source spectra field")
        if row["value_count"] != count or row["sample_size_bytes"] != len(payload) or row["shape"] != list(shape):
            raise SystemExit(f"{name}: index count/size/shape mismatch")
        digest = hashlib.sha256(payload).hexdigest()
        if row.get("sample_sha256") != digest:
            raise SystemExit(f"{name}: index sample_sha256 mismatch")
        if digest in digests:
            raise SystemExit(f"{name}: duplicate sample payload")
        digests.add(digest)
        aggregate.update(payload)
        words = array("I")
        words.frombytes(payload)
        if sys.byteorder != "little":
            words.byteswap()
        nonfinite = sum(1 for w in words if (w & exponent_mask) == exponent_mask)
        if nonfinite:
            raise SystemExit(f"{name}: {nonfinite} NaN/Inf values")
        zero_words = sum(1 for w in words if not (w & 0x7FFFFFFF))
        negative_words = sum(1 for w in words if (w >> 31) and (w & 0x7FFFFFFF))
        if zero_words != row["zero_count"] or negative_words != row["negative_count"]:
            raise SystemExit(f"{name}: zero/negative counts {zero_words}/{negative_words} != index {row['zero_count']}/{row['negative_count']}")
        if zero_words == count:
            raise SystemExit(f"{name}: all-zero tensor")
        values = struct.unpack(f"<{count}f", payload)
        minimum, maximum = min(values), max(values)
        if minimum != row["min"] or maximum != row["max"]:
            raise SystemExit(f"{name}: stored float32 min/max {minimum}/{maximum} != index {row['min']}/{row['max']}")
        if minimum == maximum or maximum <= 0.0:
            raise SystemExit(f"{name}: constant or non-positive tensor")
        if len(set(words)) < MIN_DISTINCT_VALUES:
            raise SystemExit(f"{name}: fewer than {MIN_DISTINCT_VALUES} distinct values; degenerate tensor")
        total_values += count
        total_bytes += len(payload)
        print(f"verified material={name} values={count} zero_fraction={zero_words / count:.4f} min={minimum:.6g} max={maximum:.6g}", flush=True)
    if (len(rows), total_values, total_bytes) != (EXPECTED_MATERIALS, EXPECTED_VALUES, EXPECTED_SAMPLE_BYTES):
        raise SystemExit(f"aggregate mismatch samples={len(rows)} values={total_values} bytes={total_bytes}")
    if aggregate.hexdigest() != EXPECTED_AGGREGATE_SHA256:
        raise SystemExit(f"aggregate sample sha256 {aggregate.hexdigest()} != pinned {EXPECTED_AGGREGATE_SHA256}")
    if series["sample_count"] != len(rows) or series["total_size_bytes"] != total_bytes:
        raise SystemExit("manifest sample_count/total_size_bytes disagree with realized output")
    print(f"verify_ok samples={len(rows)} values={total_values} bytes={total_bytes}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    plan = sub.add_parser("plan")
    plan.add_argument("--materials", type=Path, required=True)
    pages = sub.add_parser("check-pages")
    pages.add_argument("--materials", type=Path, required=True)
    pages.add_argument("--license-page", type=Path, required=True)
    pages.add_argument("--materials-page", type=Path, required=True)
    one = sub.add_parser("check-file")
    one.add_argument("--materials", type=Path, required=True)
    one.add_argument("--material", required=True)
    one.add_argument("--path", type=Path, required=True)
    for name in ("build", "verify"):
        cmd = sub.add_parser(name)
        cmd.add_argument("--materials", type=Path, required=True)
        cmd.add_argument("--downloads", type=Path, required=True)
        cmd.add_argument("--samples-dir", type=Path, required=True)
        cmd.add_argument("--index", type=Path, required=True)
        cmd.add_argument("--stats", type=Path, required=True)
        cmd.add_argument("--data-root", type=Path, required=True)
        if name == "verify":
            cmd.add_argument("--manifest", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    {
        "plan": cmd_plan,
        "check-pages": cmd_check_pages,
        "check-file": cmd_check_file,
        "build": cmd_build,
        "verify": cmd_verify,
    }[args.command](args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
