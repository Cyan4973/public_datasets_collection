#!/usr/bin/env python3
from __future__ import annotations

from array import array
import argparse
import collections
import hashlib
import io
import json
import math
from pathlib import Path
import pickle
import re
import shutil
import statistics
import struct
import sys
import zipfile


DATASET_ID = "hf_vbvr_wan22_vae_latents_bf16"
SERIES_ID = "wan22_ti2v_vae_latent_bf16"
CACHE_REPO = "Central-Cat/vbvr-latent-cache-832x832x33f-t2v-only"
CACHE_REVISION = "951c2880a946f0a947bc32c9f48df30767102175"
UPSTREAM_REPO = "Video-Reason/VBVR-Dataset"
UPSTREAM_REVISION = "7ef37ad3706c1a146143f9ab7611730487bd8c70"
CACHE_CARD_BYTES = 9_841
CACHE_CARD_SHA256 = "0faf46312369baefe326a66988b1ca786629dae2814e49ded433364dc7aa264c"
UPSTREAM_CARD_BYTES = 9_344
UPSTREAM_CARD_SHA256 = "36d9c18a64b47b80389e520cb4b14f09840995c8fb29dab729716f97438baec2"
ENCODER_CARD_BYTES = 15_935
ENCODER_CARD_SHA256 = "e357cb3ac077f8739755b0fb38fe8424c76534b19b4a84f6138856abb00abf69"
DIFFUSERS_CARD_BYTES = 17_633
DIFFUSERS_CARD_SHA256 = "b7120bb210ab14defe6cabd7ac4bf568d0f5fde42f88ea4ac3cfec9516dc2c0c"
SELECTION = Path(__file__).resolve().parent / "selected_files.tsv"

LATENT_SHAPE = (48, 9, 52, 52)
SOURCE_SHAPE = (1, 3, 33, 832, 832)
LATENT_VALUES = 48 * 9 * 52 * 52
LATENT_BYTES = LATENT_VALUES * 2
EXPECTED_SAMPLES = 216
EXPECTED_GENERATORS = 36
MIN_DISTINCT_VALUES = 1_000


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            value.update(block)
    return value.hexdigest()


def safe_name(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


def read_selection() -> list[dict[str, object]]:
    lines = SELECTION.read_text(encoding="utf-8").splitlines()
    if lines[0] != "path\tsize_bytes\tsha256":
        raise ValueError("selection header changed")
    entries = []
    for line in lines[1:]:
        path, size, sha = line.split("\t")
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+\.pt", path) or not re.fullmatch(r"[0-9a-f]{64}", sha):
            raise ValueError(f"malformed selection row: {line}")
        entries.append({"path": path, "size_bytes": int(size), "sha256": sha})
    generators = {str(entry["path"]).split("/")[0] for entry in entries}
    if len(entries) != EXPECTED_SAMPLES or len(generators) != EXPECTED_GENERATORS:
        raise ValueError("selection no longer covers 6 samples for each of 36 generators")
    if len({entry["path"] for entry in entries}) != len(entries):
        raise ValueError("duplicate selection rows")
    return entries


def validate_card(path: Path, size: int, sha256: str, label: str) -> None:
    if not path.is_file() or path.stat().st_size != size or digest(path) != sha256:
        raise ValueError(f"pinned {label} card is missing or changed")
    frontmatter = path.read_text(encoding="utf-8", errors="strict").split("---", 2)
    if len(frontmatter) < 3 or not re.search(r"(?mi)^license:\s*apache-2\.0\s*$", frontmatter[1]):
        raise ValueError(f"pinned {label} card no longer declares Apache-2.0")


# --- Restricted reader for torch.save zip archives -------------------------------------------
# Only the globals torch.save emits for a dict of contiguous tensors, strings and int tuples are
# resolved; any other global aborts decoding, so no code from the archive can run.

class StorageType:
    def __init__(self, name: str, itemsize: int) -> None:
        self.name = name
        self.itemsize = itemsize


STORAGE_TYPES = {
    "BFloat16Storage": StorageType("bfloat16", 2),
    "HalfStorage": StorageType("float16", 2),
    "FloatStorage": StorageType("float32", 4),
    "DoubleStorage": StorageType("float64", 8),
    "LongStorage": StorageType("int64", 8),
    "IntStorage": StorageType("int32", 4),
    "ByteStorage": StorageType("uint8", 1),
}


class StorageRef:
    def __init__(self, storage_type: StorageType, key: str, numel: int) -> None:
        self.storage_type = storage_type
        self.key = key
        self.numel = numel


class TensorRef:
    def __init__(self, storage: StorageRef, offset: int, size: tuple, stride: tuple) -> None:
        self.storage = storage
        self.offset = offset
        self.size = tuple(size)
        self.stride = tuple(stride)


def rebuild_tensor_v2(storage, storage_offset, size, stride, requires_grad=False, backward_hooks=None, metadata=None):
    if not isinstance(storage, StorageRef):
        raise pickle.UnpicklingError("tensor without storage reference")
    return TensorRef(storage, storage_offset, size, stride)


class RestrictedUnpickler(pickle.Unpickler):
    def find_class(self, module: str, name: str):
        if (module, name) == ("torch._utils", "_rebuild_tensor_v2"):
            return rebuild_tensor_v2
        if (module, name) == ("collections", "OrderedDict"):
            return collections.OrderedDict
        if module == "torch" and name in STORAGE_TYPES:
            return STORAGE_TYPES[name]
        raise pickle.UnpicklingError(f"forbidden global {module}.{name}")

    def persistent_load(self, pid):
        if not (isinstance(pid, tuple) and len(pid) == 5 and pid[0] == "storage"):
            raise pickle.UnpicklingError("unexpected persistent id")
        _, storage_type, key, _location, numel = pid
        if not isinstance(storage_type, StorageType) or not isinstance(key, str) or not isinstance(numel, int):
            raise pickle.UnpicklingError("malformed storage reference")
        return StorageRef(storage_type, key, numel)


def contiguous_strides(size: tuple) -> tuple:
    strides = []
    step = 1
    for dim in reversed(size):
        strides.append(step)
        step *= dim
    return tuple(reversed(strides))


def decode_latent(path: Path) -> bytes:
    """Return the x0 latent tensor of one cache file as raw little-endian BF16 bytes (C,T,H,W)."""
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        pickles = [name for name in names if name.endswith("/data.pkl")]
        if len(pickles) != 1:
            raise ValueError(f"{path.name}: expected one data.pkl")
        prefix = pickles[0][: -len("data.pkl")]
        byteorder = prefix + "byteorder"
        if byteorder in names and archive.read(byteorder) != b"little":
            raise ValueError(f"{path.name}: archive is not little-endian")
        record = RestrictedUnpickler(io.BytesIO(archive.read(pickles[0]))).load()
        if not isinstance(record, dict) or "x0" not in record:
            raise ValueError(f"{path.name}: missing x0 latent")
        if tuple(record.get("latent_shape", ())) != LATENT_SHAPE or tuple(record.get("source_shape", ())) != SOURCE_SHAPE:
            raise ValueError(f"{path.name}: latent/source shape metadata changed")
        x0 = record["x0"]
        if not isinstance(x0, TensorRef) or x0.storage.storage_type.name != "bfloat16":
            raise ValueError(f"{path.name}: x0 is not a bfloat16 tensor")
        if x0.size != LATENT_SHAPE or x0.stride != contiguous_strides(LATENT_SHAPE) or x0.offset != 0:
            raise ValueError(f"{path.name}: x0 is not a contiguous {LATENT_SHAPE} tensor")
        payload = archive.read(prefix + "data/" + x0.storage.key)
    if len(payload) != LATENT_BYTES or x0.storage.numel != LATENT_VALUES:
        raise ValueError(f"{path.name}: x0 storage size {len(payload)} != {LATENT_BYTES}")
    return payload


def bf16_to_float(code: int) -> float:
    return struct.unpack("<f", struct.pack("<I", code << 16))[0]


def latent_statistics(payload: bytes, name: str) -> dict[str, object]:
    codes = array("H")
    codes.frombytes(payload)
    if sys.byteorder != "little":
        codes.byteswap()
    histogram = collections.Counter(codes)
    if any((code & 0x7F80) == 0x7F80 for code in histogram):
        raise ValueError(f"{name}: non-finite BF16 value")
    if len(histogram) < MIN_DISTINCT_VALUES:
        raise ValueError(f"{name}: degenerate latent ({len(histogram)} distinct values)")
    values = {code: bf16_to_float(code) for code in histogram}
    total = len(codes)
    mean = sum(values[c] * n for c, n in histogram.items()) / total
    variance = sum((values[c] - mean) ** 2 * n for c, n in histogram.items()) / total
    std = math.sqrt(variance)
    minimum, maximum = min(values.values()), max(values.values())
    # The cache normalizes latents per channel; a sane payload stays within a few standard units.
    if not (0.05 < std < 20.0) or max(abs(minimum), abs(maximum)) > 100.0:
        raise ValueError(f"{name}: implausible latent distribution std={std} range=({minimum}, {maximum})")
    plane = LATENT_VALUES // LATENT_SHAPE[0]
    for channel in range(LATENT_SHAPE[0]):
        if len(set(codes[channel * plane : (channel + 1) * plane])) < 2:
            raise ValueError(f"{name}: constant latent channel {channel}")
    zero_count = histogram.get(0x0000, 0) + histogram.get(0x8000, 0)
    return {
        "minimum": minimum,
        "maximum": maximum,
        "mean": round(mean, 9),
        "std": round(std, 9),
        "zero_count": zero_count,
        "distinct_values": len(histogram),
    }


def materialize(download_dir: Path, verify_inputs: bool = True):
    """Yield (row, output filename, payload) for every selected sample, in selection order."""
    validate_card(download_dir / "cache_card.md", CACHE_CARD_BYTES, CACHE_CARD_SHA256, "latent cache")
    validate_card(download_dir / "upstream_card.md", UPSTREAM_CARD_BYTES, UPSTREAM_CARD_SHA256, "upstream VBVR")
    validate_card(download_dir / "encoder_card.md", ENCODER_CARD_BYTES, ENCODER_CARD_SHA256, "Wan2.2 encoder")
    validate_card(download_dir / "encoder_diffusers_card.md", DIFFUSERS_CARD_BYTES, DIFFUSERS_CARD_SHA256, "Wan2.2 Diffusers encoder")
    for entry in read_selection():
        source = download_dir / "cache" / str(entry["path"])
        if not source.is_file() or source.stat().st_size != entry["size_bytes"]:
            raise ValueError(f"missing or truncated source {entry['path']}")
        if verify_inputs and digest(source) != entry["sha256"]:
            raise ValueError(f"source hash changed {entry['path']}")
        payload = decode_latent(source)
        generator, stem = str(entry["path"]).split("/")
        filename = f"{safe_name(generator)}__{safe_name(Path(stem).stem)}.bin"
        stats = latent_statistics(payload, str(entry["path"]))
        row = {
            "dataset_id": DATASET_ID,
            "series_id": SERIES_ID,
            "role": "primary",
            "sample_path": f"samples/{DATASET_ID}/{SERIES_ID}/{filename}",
            "numeric_kind": "float",
            "bit_width": 16,
            "endianness": "little",
            "element_size_bytes": 2,
            "sample_size_bytes": LATENT_BYTES,
            "value_count": LATENT_VALUES,
            "sample_format": "raw homogeneous bfloat16 video VAE latent tensor",
            "sample_geometry": "video_latent_4d",
            "sample_rank": 4,
            "sample_shape": list(LATENT_SHAPE),
            "sample_axes": ["latent_channel", "latent_frame", "latent_y", "latent_x"],
            "natural_record_kind": "complete_video_clip_vae_latent_tensor",
            "source_sample": f"downloads/{DATASET_ID}/cache/{entry['path']}",
            "source_sha256": entry["sha256"],
            "cache_repository": CACHE_REPO,
            "cache_revision": CACHE_REVISION,
            "generator": generator,
            "sha256": hashlib.sha256(payload).hexdigest(),
            **stats,
        }
        yield row, filename, payload


def summarize(rows: list[dict[str, object]]) -> dict[str, object]:
    if len(rows) != EXPECTED_SAMPLES:
        raise ValueError(f"expected {EXPECTED_SAMPLES} samples, got {len(rows)}")
    if len({row["sha256"] for row in rows}) != len(rows):
        raise ValueError("duplicate latent payloads")
    counts = [int(row["value_count"]) for row in rows]
    return {
        "dataset_id": DATASET_ID,
        "cache_repository": CACHE_REPO,
        "cache_revision": CACHE_REVISION,
        "upstream_repository": UPSTREAM_REPO,
        "upstream_revision": UPSTREAM_REVISION,
        "samples": len(rows),
        "generators": len({row["generator"] for row in rows}),
        "primary_values": sum(counts),
        "primary_sample_bytes": sum(int(row["sample_size_bytes"]) for row in rows),
        "median_value_count": statistics.median(counts),
        "min_std": min(float(row["std"]) for row in rows),
        "max_std": max(float(row["std"]) for row in rows),
        "min_distinct_values": min(int(row["distinct_values"]) for row in rows),
    }


def command_validate(args: argparse.Namespace) -> None:
    rows = [row for row, _, _ in materialize(Path(args.download_dir))]
    stats = summarize(rows)
    print(
        f"validated dataset={DATASET_ID} samples={stats['samples']} "
        f"primary_values={stats['primary_values']} primary_bytes={stats['primary_sample_bytes']}"
    )


def command_build(args: argparse.Namespace) -> None:
    samples_dir = Path(args.samples_dir)
    if samples_dir.exists():
        shutil.rmtree(samples_dir)
    out_dir = samples_dir / SERIES_ID
    out_dir.mkdir(parents=True)
    rows = []
    for row, filename, payload in materialize(Path(args.download_dir)):
        (out_dir / filename).write_bytes(payload)
        rows.append(row)
    stats = summarize(rows)
    index = Path(args.index)
    index.parent.mkdir(parents=True, exist_ok=True)
    index.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in rows), encoding="utf-8")
    stats_path = Path(args.stats)
    stats_path.parent.mkdir(parents=True, exist_ok=True)
    stats_path.write_text(json.dumps(stats, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        f"built samples={len(rows)} primary_values={stats['primary_values']} "
        f"primary_bytes={stats['primary_sample_bytes']} median_values={stats['median_value_count']}"
    )


def command_verify(args: argparse.Namespace) -> None:
    out_dir = Path(args.samples_dir) / SERIES_ID
    actual_rows = [
        json.loads(line) for line in Path(args.index).read_text(encoding="utf-8").splitlines() if line.strip()
    ]
    rows = []
    names = set()
    for row, filename, payload in materialize(Path(args.download_dir)):
        sample = out_dir / filename
        if not sample.is_file() or sample.read_bytes() != payload:
            raise ValueError(f"source/output byte mismatch: {filename}")
        rows.append(row)
        names.add(filename)
    if {path.name for path in out_dir.glob("*.bin")} != names:
        raise ValueError("sample file inventory mismatch")
    if actual_rows != rows:
        raise ValueError("sample index differs from independent decode")
    stats = summarize(rows)
    if json.loads(Path(args.stats).read_text(encoding="utf-8")) != stats:
        raise ValueError("ingest stats differ from independent decode")
    print(
        f"verified dataset={DATASET_ID} samples={len(rows)} "
        f"primary_values={stats['primary_values']} primary_bytes={stats['primary_sample_bytes']}"
    )


def command_urls(args: argparse.Namespace) -> None:
    """Print '<size> <sha256> <relative path>' for download.sh."""
    for entry in read_selection():
        print(f"{entry['size_bytes']} {entry['sha256']} {entry['path']}")


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser()
    commands = root.add_subparsers(dest="command", required=True)
    commands.add_parser("selection").set_defaults(func=command_urls)
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
