#!/usr/bin/env python3
from __future__ import annotations

from array import array
import argparse
import hashlib
import json
import math
from pathlib import Path
import re
import shutil
import statistics
import struct
import sys


DATASET_ID = "hf_timm_resnet18_conv_f32"
SERIES_ID = "resnet18_convolution_kernel_f32"
REVISION = "491b427b45c94c7fb0e78b5474cc919aff584bbf"
MODEL_BYTES = 46_807_446
MODEL_SHA256 = "80c49dee3da4822c009c5a7fe591e9223c5a2cfcf95a4067ca4dfb5a7b89c612"
MODEL_CARD_BYTES = 38_416
MODEL_CARD_SHA256 = "e96d7547dfaff6f0a0d74209819c461ec2d66556a9d6b059f1c2a50d413da5bb"
HEADER_BYTES = 10_830
PAYLOAD_BYTES = 46_796_608
EXPECTED_ALL_TENSORS = 122
EXPECTED_SAMPLES = 20
EXPECTED_VALUES = 11_166_912
EXPECTED_BYTES = 44_667_648


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            value.update(block)
    return value.hexdigest()


def safe_name(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


def validate_card(path: Path) -> None:
    if not path.is_file() or path.stat().st_size != MODEL_CARD_BYTES or digest(path) != MODEL_CARD_SHA256:
        raise ValueError("pinned model card is missing or changed")
    text = path.read_text(encoding="utf-8", errors="strict")
    frontmatter = text.split("---", 2)
    if len(frontmatter) < 3 or not re.search(
        r"(?mi)^license:\s*apache-2\.0\s*$", frontmatter[1]
    ):
        raise ValueError("pinned model card no longer declares Apache-2.0")


def parse_checkpoint(path: Path) -> tuple[list[dict[str, object]], list[tuple[str, bytes]]]:
    if not path.is_file() or path.stat().st_size != MODEL_BYTES or digest(path) != MODEL_SHA256:
        raise ValueError("pinned SafeTensors checkpoint is missing or changed")
    data = path.read_bytes()
    header_length = struct.unpack_from("<Q", data, 0)[0]
    if header_length != HEADER_BYTES:
        raise ValueError(f"SafeTensors header length changed: {header_length}")
    header = json.loads(data[8 : 8 + header_length].rstrip(b" ").decode("utf-8"))
    if not isinstance(header, dict):
        raise ValueError("SafeTensors header is not an object")
    payload_start = 8 + header_length
    if len(data) - payload_start != PAYLOAD_BYTES:
        raise ValueError("SafeTensors payload length changed")

    spans: list[tuple[int, int, str]] = []
    selected: list[dict[str, object]] = []
    outputs: list[tuple[str, bytes]] = []
    for name, metadata in header.items():
        if name == "__metadata__":
            continue
        if not isinstance(metadata, dict):
            raise ValueError(f"invalid tensor metadata: {name}")
        dtype = str(metadata.get("dtype") or "")
        shape = metadata.get("shape")
        offsets = metadata.get("data_offsets")
        if not isinstance(shape, list) or not all(isinstance(value, int) and value >= 0 for value in shape):
            raise ValueError(f"invalid tensor shape: {name}")
        if not isinstance(offsets, list) or len(offsets) != 2 or not all(isinstance(value, int) for value in offsets):
            raise ValueError(f"invalid tensor offsets: {name}")
        start, end = offsets
        if start < 0 or end <= start or end > PAYLOAD_BYTES:
            raise ValueError(f"tensor offsets outside payload: {name}")
        spans.append((start, end, name))
        if dtype != "F32" or len(shape) != 4:
            continue
        value_count = math.prod(shape)
        if value_count < 1_000 or end - start != value_count * 4:
            raise ValueError(f"invalid selected tensor geometry: {name}")
        raw = data[payload_start + start : payload_start + end]
        values = array("f")
        values.frombytes(raw)
        if sys.byteorder != "little":
            values.byteswap()
        if len(values) != value_count or any(not math.isfinite(value) for value in values):
            raise ValueError(f"invalid selected float32 values: {name}")
        minimum = min(values)
        maximum = max(values)
        distinct: set[float] = set()
        for value in values:
            if len(distinct) >= 10_000:
                break
            distinct.add(value)
        if minimum == maximum or len(distinct) < 32:
            raise ValueError(f"degenerate selected tensor: {name}")
        filename = f"{safe_name(name)}_f32le.bin"
        selected.append(
            {
                "tensor_name": name,
                "dtype": dtype,
                "shape": shape,
                "value_count": value_count,
                "payload_bytes": len(raw),
                "data_offset_start": start,
                "data_offset_end": end,
                "minimum": minimum,
                "maximum": maximum,
                "zero_count": values.count(0.0),
                "distinct_values_capped": len(distinct),
                "payload_sha256": hashlib.sha256(raw).hexdigest(),
                "filename": filename,
            }
        )
        outputs.append((filename, raw))

    cursor = 0
    for start, end, name in sorted(spans):
        if start != cursor:
            raise ValueError(f"SafeTensors payload gap or overlap before {name}")
        cursor = end
    if cursor != PAYLOAD_BYTES or len(spans) != EXPECTED_ALL_TENSORS:
        raise ValueError("SafeTensors complete tensor inventory changed")
    selected.sort(key=lambda row: int(row["data_offset_start"]))
    output_by_name = dict(outputs)
    outputs = [(str(row["filename"]), output_by_name[str(row["filename"])]) for row in selected]
    if (
        len(selected) != EXPECTED_SAMPLES
        or sum(int(row["value_count"]) for row in selected) != EXPECTED_VALUES
        or sum(int(row["payload_bytes"]) for row in selected) != EXPECTED_BYTES
    ):
        raise ValueError("selected convolution tensor inventory changed")
    if len({str(row["payload_sha256"]) for row in selected}) != len(selected):
        raise ValueError("duplicate selected convolution tensor payload")
    return selected, outputs


def materialize(download_dir: Path) -> tuple[list[dict[str, object]], dict[str, object], list[tuple[str, bytes]]]:
    validate_card(download_dir / "model_card.md")
    tensors, outputs = parse_checkpoint(download_dir / "model.safetensors")
    rows: list[dict[str, object]] = []
    records: list[dict[str, object]] = []
    for tensor in tensors:
        shape = list(tensor["shape"])
        filename = str(tensor["filename"])
        row = {
            "dataset_id": DATASET_ID,
            "series_id": SERIES_ID,
            "role": "primary",
            "sample_path": f"samples/{DATASET_ID}/{SERIES_ID}/{filename}",
            "numeric_kind": "float",
            "bit_width": 32,
            "endianness": "little",
            "element_size_bytes": 4,
            "sample_size_bytes": tensor["payload_bytes"],
            "value_count": tensor["value_count"],
            "sample_format": "raw homogeneous IEEE-754 float32 convolution tensor",
            "sample_geometry": "convolution_kernel_bank_4d",
            "sample_rank": 4,
            "sample_shape": shape,
            "sample_axes": ["output_channel", "input_channel", "kernel_y", "kernel_x"],
            "natural_record_kind": "complete_neural_network_convolution_parameter_tensor",
            "source_sample": f"downloads/{DATASET_ID}/model.safetensors",
            "source_sha256": MODEL_SHA256,
            "model_id": "timm/resnet18.a1_in1k",
            "model_revision": REVISION,
            "tensor_name": tensor["tensor_name"],
            "tensor_data_offsets": [tensor["data_offset_start"], tensor["data_offset_end"]],
            "minimum": tensor["minimum"],
            "maximum": tensor["maximum"],
            "zero_count": tensor["zero_count"],
            "distinct_values_capped": tensor["distinct_values_capped"],
            "sha256": tensor["payload_sha256"],
        }
        rows.append(row)
        records.append(
            {
                "tensor_name": tensor["tensor_name"],
                "shape": shape,
                "value_count": tensor["value_count"],
                "sample_bytes": tensor["payload_bytes"],
                "sample_sha256": tensor["payload_sha256"],
                "minimum": tensor["minimum"],
                "maximum": tensor["maximum"],
                "zero_count": tensor["zero_count"],
            }
        )
    counts = sorted(int(row["value_count"]) for row in rows)
    stats = {
        "dataset_id": DATASET_ID,
        "model_id": "timm/resnet18.a1_in1k",
        "model_revision": REVISION,
        "samples": len(rows),
        "primary_values": sum(counts),
        "primary_sample_bytes": sum(int(row["sample_size_bytes"]) for row in rows),
        "median_value_count": statistics.median(counts),
        "min_value_count": counts[0],
        "max_value_count": counts[-1],
        "kernel_shapes": sorted({f"{row['sample_shape'][2]}x{row['sample_shape'][3]}" for row in rows}),
        "records": records,
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
    out_dir = samples_dir / SERIES_ID
    out_dir.mkdir(parents=True)
    for filename, data in outputs:
        (out_dir / filename).write_bytes(data)
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
        f"primary_bytes={stats['primary_sample_bytes']} median_values={stats['median_value_count']}"
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
        raise ValueError("sample index differs from independent SafeTensors decode")
    if actual_stats != stats:
        raise ValueError("ingest stats differ from independent SafeTensors decode")
    out_dir = Path(args.samples_dir) / SERIES_ID
    if {path.name for path in out_dir.glob("*.bin")} != {name for name, _ in outputs}:
        raise ValueError("sample file inventory mismatch")
    for filename, expected in outputs:
        if (out_dir / filename).read_bytes() != expected:
            raise ValueError(f"source/output byte mismatch: {filename}")
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
