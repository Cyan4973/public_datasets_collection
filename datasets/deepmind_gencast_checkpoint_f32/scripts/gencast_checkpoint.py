#!/usr/bin/env python3
from __future__ import annotations

from array import array
import argparse
import ast
import hashlib
import json
import math
from pathlib import Path
import re
import shutil
import statistics
import struct
import sys
import zipfile


DATASET_ID = "deepmind_gencast_checkpoint_f32"
REVISION = "9c034db1ff412d5db6cbe6bb0c5c9afc5a267719"
MODEL_BYTES = 230_105_815
MODEL_SHA256 = "a8dc94b616af89cfc01a5c6afbcc8411b594d919f23f3cd962f6f7755735195e"
LICENSE_BYTES = 18_649
LICENSE_SHA256 = "95df2e9564862e51d69683a899b6dcc8218d577057bdf67322880769ff85f29e"
README_BYTES = 9_170
README_SHA256 = "d7c7e7d75ae7c1c53e28ea495be9b79e681a855e35876d8124635c801cf3c5e6"
EXPECTED_ARCHIVE_ENTRIES = 363
EXPECTED_ARCHIVE_MEMBER_BYTES = 230_022_753
EXPECTED_SAMPLES = 160
EXPECTED_VALUES = 57_342_976
EXPECTED_BYTES = 229_371_904
EXPECTED_FAMILY_COUNTS = {
    "gencast_conditioning_weight_f32": (43, 704_512, 2_818_048),
    "gencast_graph_gnn_weight_f32": (21, 6_306_816, 25_227_264),
    "gencast_transformer_attention_weight_f32": (64, 16_777_216, 67_108_864),
    "gencast_transformer_ffn_weight_f32": (32, 33_554_432, 134_217_728),
}
EXCLUDED_FORTRAN_ENTRY = (
    "params:mesh2grid_gnn/~_networks_builder/decoder_nodes_grid_nodes_mlp/~/linear_1:w.npy"
)


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            value.update(block)
    return value.hexdigest()


def validate_file(path: Path, size: int, sha256: str, label: str) -> None:
    if not path.is_file() or path.stat().st_size != size or digest(path) != sha256:
        raise ValueError(f"pinned {label} is missing or changed")


def validate_license(download_dir: Path) -> None:
    license_path = download_dir / "LICENSE"
    readme_path = download_dir / "gencast_README.md"
    validate_file(license_path, LICENSE_BYTES, LICENSE_SHA256, "bucket license")
    validate_file(readme_path, README_BYTES, README_SHA256, "GenCast README")
    if "Creative Commons Attribution 4.0 International Public License" not in license_path.read_text(
        encoding="utf-8", errors="strict"
    ):
        raise ValueError("bucket license no longer contains CC BY 4.0")
    normalized = re.sub(r"\s+", " ", readme_path.read_text(encoding="utf-8", errors="strict"))
    for phrase in (
        "The license for the model weights in this repository",
        "updated to permit commercial use",
        "The previous license is now replaced",
        "Creative Commons Attribution 4.0 International",
    ):
        if phrase not in normalized:
            raise ValueError(f"model-weight supersession statement changed: {phrase!r}")


def parse_npy(raw: bytes, name: str) -> tuple[dict[str, object], bytes]:
    if len(raw) < 10 or not raw.startswith(b"\x93NUMPY"):
        raise ValueError(f"invalid NPY member: {name}")
    major, minor = raw[6], raw[7]
    if major == 1:
        header_size = struct.unpack_from("<H", raw, 8)[0]
        header_start = 10
    elif major in {2, 3}:
        header_size = struct.unpack_from("<I", raw, 8)[0]
        header_start = 12
    else:
        raise ValueError(f"unsupported NPY version {major}.{minor}: {name}")
    header_end = header_start + header_size
    if header_end > len(raw):
        raise ValueError(f"truncated NPY header: {name}")
    header = ast.literal_eval(raw[header_start:header_end].decode("latin1").strip())
    if not isinstance(header, dict):
        raise ValueError(f"invalid NPY header object: {name}")
    shape = header.get("shape")
    if not isinstance(shape, tuple) or not all(isinstance(value, int) and value >= 0 for value in shape):
        raise ValueError(f"invalid NPY shape: {name}")
    dtype = str(header.get("descr") or "")
    item_match = re.fullmatch(r"[<>=|]?[A-Za-z](\d+)", dtype)
    if not item_match:
        raise ValueError(f"unsupported NPY dtype descriptor {dtype!r}: {name}")
    item_size = int(item_match.group(1))
    if dtype.lstrip("<>=|").startswith("U"):
        item_size *= 4
    value_count = math.prod(shape) if shape else 1
    payload = raw[header_end:]
    if len(payload) != value_count * item_size:
        raise ValueError(
            f"NPY payload length mismatch: {name} got={len(payload)} expected={value_count * item_size}"
        )
    return {
        "dtype": dtype,
        "fortran_order": bool(header.get("fortran_order")),
        "shape": list(shape),
        "value_count": value_count,
    }, payload


def family_for(name: str) -> str | None:
    if "/mha_" in name and name.endswith(":w.npy"):
        return "gencast_transformer_attention_weight_f32"
    if "/ffw_" in name and name.endswith(":w.npy"):
        return "gencast_transformer_ffn_weight_f32"
    if "norm_conditioning" in name and name.endswith(":w.npy"):
        return "gencast_conditioning_weight_f32"
    if (
        "grid2mesh_gnn" in name or "mesh2grid_gnn" in name
    ) and name.endswith(":w.npy"):
        return "gencast_graph_gnn_weight_f32"
    return None


def safe_name(name: str) -> str:
    stem = name.removesuffix(".npy")
    normalized = re.sub(r"[^a-z0-9]+", "_", stem.lower()).strip("_")
    return f"{normalized}_f32le.bin"


def decode_text(header: dict[str, object], payload: bytes, name: str) -> str:
    dtype = str(header["dtype"])
    if not dtype.startswith("<U") or header["shape"] != []:
        raise ValueError(f"unexpected embedded text representation: {name}")
    return payload.decode("utf-32-le", errors="strict").rstrip("\0")


def materialize(download_dir: Path) -> tuple[list[dict[str, object]], dict[str, object], list[tuple[str, str, bytes]]]:
    validate_license(download_dir)
    model_path = download_dir / "gencast_1p0deg_mini_2019.npz"
    validate_file(model_path, MODEL_BYTES, MODEL_SHA256, "GenCast checkpoint")

    rows: list[dict[str, object]] = []
    outputs: list[tuple[str, str, bytes]] = []
    excluded: list[dict[str, object]] = []
    archive_member_bytes = 0
    embedded_license = ""
    embedded_description = ""
    archive_names: set[str] = set()
    with zipfile.ZipFile(model_path) as archive:
        infos = archive.infolist()
        if len(infos) != EXPECTED_ARCHIVE_ENTRIES:
            raise ValueError(f"archive entry count changed: {len(infos)}")
        if archive.testzip() is not None:
            raise ValueError("checkpoint member CRC validation failed")
        for info in infos:
            if info.filename in archive_names:
                raise ValueError(f"duplicate archive member name: {info.filename}")
            archive_names.add(info.filename)
            if info.compress_type != zipfile.ZIP_STORED or not info.filename.endswith(".npy"):
                raise ValueError(f"unexpected archive member framing: {info.filename}")
            archive_member_bytes += info.file_size
            header, payload = parse_npy(archive.read(info), info.filename)
            if info.filename == "license.npy":
                embedded_license = decode_text(header, payload, info.filename)
            elif info.filename == "description.npy":
                embedded_description = decode_text(header, payload, info.filename)

            family = family_for(info.filename)
            if family is None:
                continue
            if header["dtype"] != "<f4" or len(header["shape"]) != 2:
                raise ValueError(f"selected matrix is not rank-2 little-endian float32: {info.filename}")
            if header["fortran_order"]:
                excluded.append(
                    {
                        "entry": info.filename,
                        "reason": "fortran_order_matrix",
                        "shape": header["shape"],
                        "value_count": header["value_count"],
                    }
                )
                continue
            value_count = int(header["value_count"])
            if value_count < 1_000 or len(payload) != value_count * 4:
                raise ValueError(f"selected matrix is too small or malformed: {info.filename}")
            values = array("f")
            values.frombytes(payload)
            if sys.byteorder != "little":
                values.byteswap()
            if any(not math.isfinite(value) for value in values):
                raise ValueError(f"non-finite selected matrix: {info.filename}")
            minimum = min(values)
            maximum = max(values)
            distinct: set[float] = set()
            for value in values:
                if len(distinct) >= 10_000:
                    break
                distinct.add(value)
            if minimum == maximum or len(distinct) < 32:
                raise ValueError(f"degenerate selected matrix: {info.filename}")
            filename = safe_name(info.filename)
            payload_sha256 = hashlib.sha256(payload).hexdigest()
            row = {
                "dataset_id": DATASET_ID,
                "series_id": family,
                "role": "primary",
                "sample_path": f"samples/{DATASET_ID}/{family}/{filename}",
                "numeric_kind": "float",
                "bit_width": 32,
                "endianness": "little",
                "element_size_bytes": 4,
                "sample_size_bytes": len(payload),
                "value_count": value_count,
                "sample_format": "raw homogeneous IEEE-754 float32 learned parameter matrix",
                "sample_geometry": "neural_network_parameter_matrix_2d",
                "sample_rank": 2,
                "sample_shape": header["shape"],
                "sample_axes": ["input_feature", "output_feature"],
                "natural_record_kind": "complete_gencast_parameter_tensor",
                "source_sample": f"downloads/{DATASET_ID}/gencast_1p0deg_mini_2019.npz",
                "source_sha256": MODEL_SHA256,
                "source_entry_name": info.filename,
                "source_entry_crc32": f"{info.CRC:08x}",
                "source_entry_header_offset": info.header_offset,
                "model": "GenCast 1p0deg Mini <2019",
                "model_revision": REVISION,
                "minimum": minimum,
                "maximum": maximum,
                "zero_count": values.count(0.0),
                "distinct_values_capped": len(distinct),
                "sha256": payload_sha256,
            }
            rows.append(row)
            outputs.append((family, filename, payload))

    if archive_member_bytes != EXPECTED_ARCHIVE_MEMBER_BYTES:
        raise ValueError(f"archive aggregate member bytes changed: {archive_member_bytes}")
    if "Attribution-NonCommercial-ShareAlike 4.0" not in embedded_license:
        raise ValueError("embedded legacy model license changed unexpectedly")
    if "GenCast model at lower, 1deg, resolution" not in embedded_description:
        raise ValueError("embedded model description changed unexpectedly")
    if excluded != [
        {
            "entry": EXCLUDED_FORTRAN_ENTRY,
            "reason": "fortran_order_matrix",
            "shape": [512, 84],
            "value_count": 43_008,
        }
    ]:
        raise ValueError(f"Fortran-order exclusion inventory changed: {excluded}")

    rows.sort(key=lambda row: (str(row["series_id"]), int(row["source_entry_header_offset"])))
    output_by_path = {(family, filename): payload for family, filename, payload in outputs}
    outputs = [
        (str(row["series_id"]), Path(str(row["sample_path"])).name, output_by_path[(str(row["series_id"]), Path(str(row["sample_path"])).name)])
        for row in rows
    ]
    if len({str(row["sample_path"]) for row in rows}) != len(rows):
        raise ValueError("selected matrix filenames collide")
    if len({str(row["sha256"]) for row in rows}) != len(rows):
        raise ValueError("duplicate selected matrix payload")
    if (
        len(rows) != EXPECTED_SAMPLES
        or sum(int(row["value_count"]) for row in rows) != EXPECTED_VALUES
        or sum(int(row["sample_size_bytes"]) for row in rows) != EXPECTED_BYTES
    ):
        raise ValueError("selected matrix inventory changed")

    family_stats: dict[str, dict[str, object]] = {}
    for family, (expected_count, expected_values, expected_bytes) in EXPECTED_FAMILY_COUNTS.items():
        family_rows = [row for row in rows if row["series_id"] == family]
        counts = sorted(int(row["value_count"]) for row in family_rows)
        actual = (len(family_rows), sum(counts), sum(int(row["sample_size_bytes"]) for row in family_rows))
        if actual != (expected_count, expected_values, expected_bytes):
            raise ValueError(f"family inventory changed for {family}: {actual}")
        family_stats[family] = {
            "samples": len(family_rows),
            "primary_values": sum(counts),
            "primary_sample_bytes": actual[2],
            "min_value_count": counts[0],
            "median_value_count": statistics.median(counts),
            "max_value_count": counts[-1],
            "shapes": sorted({"x".join(str(value) for value in row["sample_shape"]) for row in family_rows}),
        }
    stats = {
        "dataset_id": DATASET_ID,
        "model": "GenCast 1p0deg Mini <2019",
        "model_domain": "probabilistic_global_weather_forecasting",
        "model_revision": REVISION,
        "source_sha256": MODEL_SHA256,
        "samples": len(rows),
        "primary_values": sum(int(row["value_count"]) for row in rows),
        "primary_sample_bytes": sum(int(row["sample_size_bytes"]) for row in rows),
        "families": family_stats,
        "excluded": excluded,
        "embedded_license": embedded_license.strip(),
        "external_license_supersedes_embedded": True,
        "records": [
            {
                "series_id": row["series_id"],
                "tensor_name": row["source_entry_name"],
                "shape": row["sample_shape"],
                "value_count": row["value_count"],
                "sample_bytes": row["sample_size_bytes"],
                "sample_sha256": row["sha256"],
                "minimum": row["minimum"],
                "maximum": row["maximum"],
                "zero_count": row["zero_count"],
            }
            for row in rows
        ],
    }
    return rows, stats, outputs


def command_validate(args: argparse.Namespace) -> None:
    rows, stats, _ = materialize(Path(args.download_dir))
    print(
        f"validated dataset={DATASET_ID} samples={len(rows)} "
        f"primary_values={stats['primary_values']} primary_bytes={stats['primary_sample_bytes']}"
    )


def command_build(args: argparse.Namespace) -> None:
    rows, stats, outputs = materialize(Path(args.download_dir))
    samples_dir = Path(args.samples_dir)
    if samples_dir.exists():
        shutil.rmtree(samples_dir)
    for family, filename, payload in outputs:
        out_dir = samples_dir / family
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / filename).write_bytes(payload)
    index = Path(args.index)
    index.parent.mkdir(parents=True, exist_ok=True)
    index.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )
    stats_path = Path(args.stats)
    stats_path.parent.mkdir(parents=True, exist_ok=True)
    stats_path.write_text(json.dumps(stats, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        f"built samples={len(rows)} primary_values={stats['primary_values']} "
        f"primary_bytes={stats['primary_sample_bytes']}"
    )


def command_verify(args: argparse.Namespace) -> None:
    rows, stats, outputs = materialize(Path(args.download_dir))
    actual_rows = [
        json.loads(line)
        for line in Path(args.index).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    actual_stats = json.loads(Path(args.stats).read_text(encoding="utf-8"))
    if actual_rows != rows:
        raise ValueError("sample index differs from independent NPZ decode")
    if actual_stats != stats:
        raise ValueError("ingest stats differ from independent NPZ decode")
    expected_paths = {
        Path(str(row["sample_path"])).relative_to(f"samples/{DATASET_ID}") for row in rows
    }
    samples_dir = Path(args.samples_dir)
    actual_paths = {path.relative_to(samples_dir) for path in samples_dir.rglob("*.bin")}
    if actual_paths != expected_paths:
        raise ValueError("sample file inventory mismatch")
    for family, filename, expected in outputs:
        actual = samples_dir / family / filename
        if actual.read_bytes() != expected:
            raise ValueError(f"source/output byte mismatch: {family}/{filename}")
    print(
        f"verified dataset={DATASET_ID} samples={len(rows)} "
        f"primary_values={stats['primary_values']} primary_bytes={stats['primary_sample_bytes']}"
    )


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser()
    commands = root.add_subparsers(dest="command", required=True)
    validate = commands.add_parser("validate")
    validate.add_argument("--download-dir", required=True)
    validate.set_defaults(func=command_validate)
    for name, function in (("build", command_build), ("verify", command_verify)):
        command = commands.add_parser(name)
        command.add_argument("--download-dir", required=True)
        command.add_argument("--samples-dir", required=True)
        command.add_argument("--index", required=True)
        command.add_argument("--stats", required=True)
        command.set_defaults(func=function)
    return root


if __name__ == "__main__":
    arguments = parser().parse_args()
    arguments.func(arguments)
