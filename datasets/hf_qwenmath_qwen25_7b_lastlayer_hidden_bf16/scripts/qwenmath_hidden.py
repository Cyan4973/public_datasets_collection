#!/usr/bin/env python3
"""Pinned Qwen2.5-7B-Instruct GSM8K last-layer hidden states: selection, validation, build, verify.

Pure standard library. Each selected safetensors file holds one sampled GSM8K solution trace;
the `bytoken_lastlayer` BF16 tensor [T_gen, 3584] is emitted verbatim as one sample.
"""
from __future__ import annotations

from array import array
import argparse
import collections
import hashlib
import json
import math
from pathlib import Path
import re
import shutil
import statistics
import struct
import sys


DATASET_ID = "hf_qwenmath_qwen25_7b_lastlayer_hidden_bf16"
SERIES_ID = "qwen25_7b_gsm8k_lastlayer_hidden_bf16"
REPO = "lzhang472/qwen-math-hidden-states"
REVISION = "1b8d08c6c6bca2c3ebad597f3ea0802c9d420910"
MODEL = "Qwen/Qwen2.5-7B-Instruct"
MODEL_REVISION = "a09a35458c702b33eeacc393d103063234e8bc28"
GSM8K_REVISION = "740312add88f781978c0658806c59bc2815b9866"

PINNED_FILES = {
    # name: (bytes, sha256, frontmatter license regex, label)
    "dataset_card.md": (1_377, "dffacb6b78de90f74ff097eb6e21453c462cdd3549f1eb8fd55d073a73446061",
                        r"(?m)^license:\s*apache-2\.0\s*$", "hidden-state cache"),
    "model_card.md": (6_240, "f366f33bbf6bcadbb7d87f0a21a7b65584a56b8d58b0743c77c88bee625b93a6",
                      r"(?m)^license:\s*apache-2\.0\s*$", "Qwen2.5-7B-Instruct"),
    "gsm8k_card.md": (7_935, "a17e882503578c9e324560630e31017617714ee025c87cf4fea6fd916895f3c1",
                      r"(?m)^license:\s*\n-\s*mit\s*$", "openai/gsm8k"),
}
MANIFEST_NAME = "manifest.jsonl"
MANIFEST_BYTES = 10_649_660
MANIFEST_SHA256 = "17b44c8f5c8915fe2612e404b3c82241923cad9b351b6a97387cbf9eab308631"
SELECTION = Path(__file__).resolve().parent / "selected_files.tsv"
PATH_RE = re.compile(r"mdl-qwen25_inst__ds-gsm8k__pid-(gsm8k-[0-9]+)__k([0-9]+)\.safetensors")

HIDDEN = 3584
LAYERS_PLUS_ONE = 29
TENSOR = "bytoken_lastlayer"
EXPECTED_TENSORS = {"bytoken_lastlayer", "bylayer_mean_gen", "bytoken_proj"}
EXPECTED_SELECTED = 300
EXPECTED_PROBLEMS = 100
SAMPLE_INDICES = (0, 1, 2)
SAMPLING = {"temperature": 0.7, "top_p": 0.8, "top_k": 20, "min_p": 0.0, "config_hash": "429b665ea67a"}
MIN_DISTINCT_VALUES = 1_000
MIN_LAYER_MEAN_COSINE = 0.9999
MAX_HEADER_BYTES = 1 << 20

BF16_TO_FLOAT = [struct.unpack("<f", struct.pack("<I", code << 16))[0] for code in range(1 << 16)]


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            value.update(block)
    return value.hexdigest()


def read_selection() -> list[dict[str, object]]:
    lines = SELECTION.read_text(encoding="utf-8").splitlines()
    if not lines or lines[0] != "path\tsize_bytes\tsha256":
        raise ValueError("selection header changed")
    entries = []
    for line in lines[1:]:
        path, size, sha = line.split("\t")
        match = PATH_RE.fullmatch(path)
        if not match or not re.fullmatch(r"[0-9a-f]{64}", sha) or not size.isdigit():
            raise ValueError(f"malformed selection row: {line}")
        entries.append({"path": path, "size_bytes": int(size), "sha256": sha,
                        "problem_id": match.group(1), "sample_idx": int(match.group(2))})
    problems = collections.Counter(str(e["problem_id"]) for e in entries)
    if (len(entries) != EXPECTED_SELECTED or len(problems) != EXPECTED_PROBLEMS
            or set(problems.values()) != {len(SAMPLE_INDICES)}
            or {e["sample_idx"] for e in entries} != set(SAMPLE_INDICES)
            or len({e["path"] for e in entries}) != len(entries)):
        raise ValueError("selection no longer covers samples k0..k2 of all 100 GSM8K problems")
    return entries


def validate_pinned(download_dir: Path) -> None:
    for name, (size, sha, license_re, label) in PINNED_FILES.items():
        path = download_dir / name
        if not path.is_file() or path.stat().st_size != size or digest(path) != sha:
            raise ValueError(f"pinned {label} card is missing or changed")
        parts = path.read_text(encoding="utf-8").split("---", 2)
        if len(parts) < 3 or not re.search(license_re, parts[1]):
            raise ValueError(f"pinned {label} card no longer declares the expected license")
    path = download_dir / MANIFEST_NAME
    if not path.is_file() or path.stat().st_size != MANIFEST_BYTES or digest(path) != MANIFEST_SHA256:
        raise ValueError("pinned manifest.jsonl is missing or changed")


def load_manifest(download_dir: Path) -> dict[str, dict]:
    rows = {}
    for line in (download_dir / MANIFEST_NAME).read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            rows[row["x_path"]] = row
    return rows


def check_manifest_row(entry: dict, row: dict | None) -> int:
    """Check the upstream manifest row of one selected trace and return its stored token count."""
    name = str(entry["path"])
    if row is None:
        raise ValueError(f"{name}: not listed in manifest.jsonl")
    if (row.get("model") != MODEL or row.get("model_tag") != "qwen25_inst" or row.get("dataset") != "gsm8k"
            or row.get("problem_id") != entry["problem_id"] or row.get("sample_idx") != entry["sample_idx"]
            or row.get("is_greedy") is not False or row.get("is_thinking") is not False):
        raise ValueError(f"{name}: manifest row does not describe a sampled qwen25_inst GSM8K trace")
    if any(row.get(key) != value for key, value in SAMPLING.items()):
        raise ValueError(f"{name}: sampling configuration changed")
    shape = row.get("shapes", {}).get(TENSOR)
    t_gen = int(row.get("T_gen", 0))
    if shape != [t_gen, HIDDEN] or t_gen < 1 or t_gen > 1024:
        raise ValueError(f"{name}: manifest shape {shape} disagrees with T_gen {t_gen}")
    return t_gen


def read_tensors(path: Path) -> tuple[dict, int, bytes]:
    """Parse a safetensors file; return (header, data start offset, whole file bytes)."""
    blob = path.read_bytes()
    if len(blob) < 8:
        raise ValueError(f"{path.name}: truncated safetensors file")
    (header_len,) = struct.unpack("<Q", blob[:8])
    if header_len < 2 or header_len > MAX_HEADER_BYTES or 8 + header_len > len(blob):
        raise ValueError(f"{path.name}: implausible safetensors header length {header_len}")
    header = json.loads(blob[8 : 8 + header_len].decode("utf-8"))
    if not isinstance(header, dict):
        raise ValueError(f"{path.name}: safetensors header is not an object")
    base = 8 + header_len
    tensors = {k: v for k, v in header.items() if k != "__metadata__"}
    if set(tensors) != EXPECTED_TENSORS:
        raise ValueError(f"{path.name}: unexpected tensors {sorted(tensors)}")
    spans = sorted(tuple(v["data_offsets"]) for v in tensors.values())
    cursor = 0
    for start, end in spans:
        if start != cursor or end < start:
            raise ValueError(f"{path.name}: tensor data offsets are not contiguous")
        cursor = end
    if base + cursor != len(blob):
        raise ValueError(f"{path.name}: data region {cursor} does not end at file size")
    return header, base, blob


def decode_trace(path: Path, t_gen: int, trace_id: str) -> tuple[bytes, bytes]:
    """Return (bytoken_lastlayer bytes, bylayer_mean_gen bytes) after structural checks."""
    header, base, blob = read_tensors(path)
    meta = header.get("__metadata__") or {}
    if meta.get("T_gen") != str(t_gen) or meta.get("trace_id") != trace_id:
        raise ValueError(f"{path.name}: safetensors metadata {meta} disagrees with manifest")
    spec = header[TENSOR]
    if spec.get("dtype") != "BF16" or spec.get("shape") != [t_gen, HIDDEN]:
        raise ValueError(f"{path.name}: {TENSOR} is {spec.get('dtype')} {spec.get('shape')}, expected BF16 [{t_gen}, {HIDDEN}]")
    start, end = spec["data_offsets"]
    if end - start != t_gen * HIDDEN * 2:
        raise ValueError(f"{path.name}: {TENSOR} byte length {end - start} != T*{HIDDEN}*2")
    layer = header["bylayer_mean_gen"]
    if layer.get("dtype") != "BF16" or layer.get("shape") != [LAYERS_PLUS_ONE, HIDDEN]:
        raise ValueError(f"{path.name}: bylayer_mean_gen layout changed")
    lstart, lend = layer["data_offsets"]
    return blob[base + start : base + end], blob[base + lstart : base + lend]


def codes_of(payload: bytes) -> array:
    codes = array("H")
    codes.frombytes(payload)
    if sys.byteorder != "little":
        codes.byteswap()
    return codes


def trace_statistics(payload: bytes, layer_means: bytes, t_gen: int, name: str) -> dict[str, object] | str:
    """Return statistics, or a drop reason string for non-finite traces. Degenerate data is fatal."""
    codes = codes_of(payload)
    histogram = collections.Counter(codes)
    if any((code & 0x7F80) == 0x7F80 for code in histogram):
        return "non_finite"
    if len(histogram) < MIN_DISTINCT_VALUES:
        raise ValueError(f"{name}: degenerate trace ({len(histogram)} distinct values)")
    for row in range(t_gen):
        if len(set(codes[row * HIDDEN : row * HIDDEN + 64])) < 2 and len(set(codes[row * HIDDEN : (row + 1) * HIDDEN])) < 2:
            raise ValueError(f"{name}: constant hidden-state row {row}")
    lut = BF16_TO_FLOAT
    total = len(codes)
    mean = sum(lut[c] * n for c, n in histogram.items()) / total
    variance = sum((lut[c] - mean) ** 2 * n for c, n in histogram.items()) / total
    std = math.sqrt(variance)
    minimum = min(lut[c] for c in histogram)
    maximum = max(lut[c] for c in histogram)
    if not (0.5 < std < 50.0) or max(abs(minimum), abs(maximum)) > 10_000.0:
        raise ValueError(f"{name}: implausible hidden-state distribution std={std} range=({minimum}, {maximum})")
    # Independent check that the tensor is the final hidden state: its per-dimension mean over
    # generated tokens must match the last row (index 28) of the stored per-layer means.
    values = [lut[c] for c in codes]
    token_mean = [sum(values[d::HIDDEN]) / t_gen for d in range(HIDDEN)]
    layer = codes_of(layer_means)[(LAYERS_PLUS_ONE - 1) * HIDDEN :]
    stored = [lut[c] for c in layer]
    dot = sum(a * b for a, b in zip(token_mean, stored))
    norm = math.sqrt(sum(a * a for a in token_mean) * sum(b * b for b in stored))
    cosine = dot / norm if norm else 0.0
    if cosine < MIN_LAYER_MEAN_COSINE:
        raise ValueError(f"{name}: token mean does not match final-layer mean (cosine {cosine})")
    return {
        "minimum": minimum,
        "maximum": maximum,
        "mean": round(mean, 9),
        "std": round(std, 9),
        "zero_count": histogram.get(0x0000, 0) + histogram.get(0x8000, 0),
        "distinct_values": len(histogram),
        "final_layer_mean_cosine": round(cosine, 6),
    }


def materialize(download_dir: Path, drops: list[dict] | None = None):
    """Yield (row, filename, payload) for every kept trace, in selection order."""
    validate_pinned(download_dir)
    manifest = load_manifest(download_dir)
    for entry in read_selection():
        source = download_dir / "traces" / str(entry["path"])
        if not source.is_file() or source.stat().st_size != entry["size_bytes"]:
            raise ValueError(f"missing or truncated source {entry['path']}")
        if digest(source) != entry["sha256"]:
            raise ValueError(f"source hash changed {entry['path']}")
        upstream = manifest.get(str(entry["path"]))
        t_gen = check_manifest_row(entry, upstream)
        payload, layer_means = decode_trace(source, t_gen, upstream["trace_id"])
        stats = trace_statistics(payload, layer_means, t_gen, str(entry["path"]))
        if isinstance(stats, str):
            if drops is not None:
                drops.append({"path": entry["path"], "reason": stats})
            continue
        filename = f"{entry['problem_id'].replace('-', '_')}__k{entry['sample_idx']}.bin"
        row = {
            "dataset_id": DATASET_ID,
            "series_id": SERIES_ID,
            "role": "primary",
            "sample_path": f"samples/{DATASET_ID}/{SERIES_ID}/{filename}",
            "numeric_kind": "float",
            "bit_width": 16,
            "endianness": "little",
            "element_size_bytes": 2,
            "value_encoding": "bfloat16",
            "sample_size_bytes": len(payload),
            "value_count": t_gen * HIDDEN,
            "sample_format": "raw homogeneous bfloat16 LLM hidden-state matrix",
            "sample_geometry": "token_by_hidden_dim_matrix",
            "sample_rank": 2,
            "sample_shape": [t_gen, HIDDEN],
            "sample_axes": ["generated_token", "hidden_dim"],
            "natural_record_kind": "sampled_solution_trace_last_layer_hidden_states",
            "source_sample": f"downloads/{DATASET_ID}/traces/{entry['path']}",
            "source_sha256": entry["sha256"],
            "repository": REPO,
            "revision": REVISION,
            "trace_id": upstream["trace_id"],
            "problem_id": entry["problem_id"],
            "sample_idx": entry["sample_idx"],
            "correct": bool(upstream.get("correct")),
            "sha256": hashlib.sha256(payload).hexdigest(),
            **stats,
        }
        yield row, filename, payload


def summarize(rows: list[dict[str, object]], drops: list[dict]) -> dict[str, object]:
    if len(rows) + len(drops) != EXPECTED_SELECTED or not rows:
        raise ValueError(f"expected {EXPECTED_SELECTED} traces, got {len(rows)} kept + {len(drops)} dropped")
    if len({row["sha256"] for row in rows}) != len(rows):
        raise ValueError("duplicate hidden-state payloads")
    counts = [int(row["value_count"]) for row in rows]
    return {
        "dataset_id": DATASET_ID,
        "repository": REPO,
        "revision": REVISION,
        "model": MODEL,
        "model_revision": MODEL_REVISION,
        "selected_traces": EXPECTED_SELECTED,
        "samples": len(rows),
        "dropped": drops,
        "problems": len({row["problem_id"] for row in rows}),
        "primary_values": sum(counts),
        "primary_sample_bytes": sum(int(row["sample_size_bytes"]) for row in rows),
        "min_tokens": min(counts) // HIDDEN,
        "median_tokens": statistics.median(counts) / HIDDEN,
        "max_tokens": max(counts) // HIDDEN,
        "min_std": min(float(row["std"]) for row in rows),
        "max_std": max(float(row["std"]) for row in rows),
        "minimum": min(float(row["minimum"]) for row in rows),
        "maximum": max(float(row["maximum"]) for row in rows),
        "min_distinct_values": min(int(row["distinct_values"]) for row in rows),
        "min_final_layer_mean_cosine": min(float(row["final_layer_mean_cosine"]) for row in rows),
    }


def command_selection(args: argparse.Namespace) -> None:
    """Print '<size> <sha256> <path>' for download.sh."""
    for entry in read_selection():
        print(f"{entry['size_bytes']} {entry['sha256']} {entry['path']}")


def command_validate(args: argparse.Namespace) -> None:
    drops: list[dict] = []
    rows = [row for row, _, _ in materialize(Path(args.download_dir), drops)]
    stats = summarize(rows, drops)
    print(f"validated dataset={DATASET_ID} samples={stats['samples']} dropped={len(drops)} "
          f"primary_values={stats['primary_values']} primary_bytes={stats['primary_sample_bytes']}")


def command_build(args: argparse.Namespace) -> None:
    samples_dir = Path(args.samples_dir)
    if samples_dir.exists():
        shutil.rmtree(samples_dir)
    out_dir = samples_dir / SERIES_ID
    out_dir.mkdir(parents=True)
    rows: list[dict] = []
    drops: list[dict] = []
    for row, filename, payload in materialize(Path(args.download_dir), drops):
        (out_dir / filename).write_bytes(payload)
        rows.append(row)
    stats = summarize(rows, drops)
    index = Path(args.index)
    index.parent.mkdir(parents=True, exist_ok=True)
    index.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in rows), encoding="utf-8")
    stats_path = Path(args.stats)
    stats_path.parent.mkdir(parents=True, exist_ok=True)
    stats_path.write_text(json.dumps(stats, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"built samples={len(rows)} dropped={len(drops)} primary_values={stats['primary_values']} "
          f"primary_bytes={stats['primary_sample_bytes']} tokens={stats['min_tokens']}..{stats['max_tokens']}")


def command_verify(args: argparse.Namespace) -> None:
    out_dir = Path(args.samples_dir) / SERIES_ID
    actual_rows = [json.loads(line) for line in Path(args.index).read_text(encoding="utf-8").splitlines() if line.strip()]
    rows: list[dict] = []
    drops: list[dict] = []
    names = set()
    for row, filename, payload in materialize(Path(args.download_dir), drops):
        sample = out_dir / filename
        if not sample.is_file() or sample.read_bytes() != payload:
            raise ValueError(f"source/output byte mismatch: {filename}")
        rows.append(row)
        names.add(filename)
    if {path.name for path in out_dir.glob("*.bin")} != names or {p.name for p in out_dir.iterdir()} != names:
        raise ValueError("sample file inventory mismatch")
    if actual_rows != rows:
        raise ValueError("sample index differs from independent decode")
    stats = summarize(rows, drops)
    if json.loads(Path(args.stats).read_text(encoding="utf-8")) != stats:
        raise ValueError("ingest stats differ from independent decode")
    if args.manifest:
        import tomllib
        manifest = tomllib.loads(Path(args.manifest).read_text(encoding="utf-8"))
        series = [s for s in manifest["series"] if s["id"] == SERIES_ID][0]
        if series["sample_count"] != len(rows) or series["total_size_bytes"] != stats["primary_sample_bytes"]:
            raise ValueError("manifest sample_count/total_size_bytes differ from realized output")
    print(f"verified dataset={DATASET_ID} samples={len(rows)} dropped={len(drops)} "
          f"primary_values={stats['primary_values']} primary_bytes={stats['primary_sample_bytes']}")


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser()
    commands = root.add_subparsers(dest="command", required=True)
    commands.add_parser("selection").set_defaults(func=command_selection)
    validate = commands.add_parser("validate")
    validate.add_argument("--download-dir", required=True)
    validate.set_defaults(func=command_validate)
    for name, function in (("build", command_build), ("verify", command_verify)):
        command = commands.add_parser(name)
        command.add_argument("--download-dir", required=True)
        command.add_argument("--samples-dir", required=True)
        command.add_argument("--index", required=True)
        command.add_argument("--stats", required=True)
        if name == "verify":
            command.add_argument("--manifest")
        command.set_defaults(func=function)
    return root


if __name__ == "__main__":
    arguments = parser().parse_args()
    arguments.func(arguments)
