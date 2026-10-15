#!/usr/bin/env python3
"""Decode pinned byte-range fragments of AnyCam MCV Wan2.1 latent archives (pure stdlib).

Each upstream file is an uncompressed torch.save zip archive. download.sh fetches only three
byte ranges per archive (pinned in selected_files.tsv):

  head.bin    bytes [0, head_stop): local headers + data.pkl, .format_version,
              .storage_alignment, byteorder (everything before the first tensor storage)
  target.bin  bytes [target_start, target_stop): local header + stored bytes (+ data
              descriptor) of the storage that backs latents['target']
  tail.bin    bytes [cd_start, file_size): central directory, zip64 records, end record

build decodes these with a hand-written zip reader; verify reassembles a sparse copy of the
archive and reads it with the standard-library zipfile module instead.
"""
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
import tempfile
import zipfile
import zlib


DATASET_ID = "hf_anycam_mcv_wan21_vae_latents_bf16"
SERIES_ID = "wan21_vae_target_latent_bf16"
CACHE_REPO = "wlyu/AnyCam_MCV_480p_wan21_latent"
CACHE_REVISION = "acb9cc2a3851b1e987a9dbf02895a311d263d5a8"
SELECTION = Path(__file__).resolve().parent / "selected_files.tsv"
SELECTION_HEADER = (
    "scene_id\tsize_bytes\tlfs_sha256\tcd_start\thead_stop\ttarget_key\t"
    "target_start\ttarget_stop\ttarget_crc32\tpkl_crc32"
)

# (file name, bytes, sha256, label) of the pinned license cards, relative to the download dir.
CARDS = (
    ("cards/latent_cache_card.md", 1_259, "3d8a0eb6a8ee3f4686400d03711f659d2f5cc8ab9ef30e42ca921ea30d755af1", "latent cache"),
    ("cards/anycam_pairs_card.md", 4_144, "1ea2b98afab68aeccf473592b23763c132843fcc95afce6d3ff991ea59800fcf", "AnyCam_MCV_480p"),
    ("cards/multicamvideo_card.md", 9_009, "97bc2df4c3fc8fe5fbb48e3350810778a3bf432ba5700497bcd5def79a54456d", "MultiCamVideo"),
    ("cards/encoder_card.md", 13_018, "c3441cf796d4aa326a2887978ec81c66177a4e9d38842a38d3e472dbdc7158ed", "Wan2.1-Fun-1.3B-InP"),
)

LATENT_SHAPE = (16, 21, 60, 104)
LATENT_VALUES = 16 * 21 * 60 * 104
LATENT_BYTES = LATENT_VALUES * 2
FOCAL_GROUPS = ("f18", "f24", "f35", "f50")
PER_GROUP = 30
EXPECTED_SAMPLES = PER_GROUP * len(FOCAL_GROUPS)
MIN_DISTINCT_VALUES = 1_000
LATENT_KEYS = ("source", "source_cond", "target", "target_cond")


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            value.update(block)
    return value.hexdigest()


# --- selection ------------------------------------------------------------------------------

def read_selection() -> list[dict[str, object]]:
    lines = SELECTION.read_text(encoding="utf-8").splitlines()
    if lines[0] != SELECTION_HEADER:
        raise ValueError("selection header changed")
    entries = []
    for line in lines[1:]:
        fields = line.split("\t")
        if len(fields) != 10:
            raise ValueError(f"malformed selection row: {line}")
        scene, size, sha, cd_start, head_stop, key, t_start, t_stop, t_crc, p_crc = fields
        if not re.fullmatch(r"mcv_f(18|24|35|50)_scene[0-9]{4}", scene) or not re.fullmatch(r"[0-9a-f]{64}", sha):
            raise ValueError(f"malformed selection row: {line}")
        entry = {
            "scene_id": scene,
            "size_bytes": int(size),
            "lfs_sha256": sha,
            "cd_start": int(cd_start),
            "head_stop": int(head_stop),
            "target_key": key,
            "target_start": int(t_start),
            "target_stop": int(t_stop),
            "target_crc32": int(t_crc, 16),
            "pkl_crc32": int(p_crc, 16),
        }
        if not (0 < entry["head_stop"] <= entry["target_start"] < entry["target_stop"] <= entry["cd_start"] < entry["size_bytes"]):
            raise ValueError(f"inconsistent ranges for {scene}")
        entries.append(entry)
    if len(entries) != EXPECTED_SAMPLES or len({e["scene_id"] for e in entries}) != EXPECTED_SAMPLES:
        raise ValueError(f"selection must list {EXPECTED_SAMPLES} distinct scenes")
    groups = collections.Counter(str(e["scene_id"]).split("_")[1] for e in entries)
    if any(groups[g] != PER_GROUP for g in FOCAL_GROUPS):
        raise ValueError(f"selection is not {PER_GROUP} scenes per focal group: {dict(groups)}")
    return entries


def fragment_paths(download_dir: Path, scene: str) -> dict[str, Path]:
    base = download_dir / "fragments" / scene
    return {"head": base / "head.bin", "target": base / "target.bin", "tail": base / "tail.bin"}


def validate_cards(download_dir: Path) -> None:
    for name, size, sha, label in CARDS:
        path = download_dir / name
        if not path.is_file() or path.stat().st_size != size or digest(path) != sha:
            raise ValueError(f"pinned {label} card is missing or changed")
        parts = path.read_text(encoding="utf-8", errors="strict").split("---", 2)
        if len(parts) < 3 or not re.search(r"(?mi)^license:\s*apache-2\.0\s*$", parts[1]):
            raise ValueError(f"pinned {label} card no longer declares Apache-2.0")


# --- restricted reader for torch.save pickles -----------------------------------------------
# Only the globals torch.save emits for a dict of tensors, strings and numbers are resolved.
# Anything else aborts decoding, so no code from the archive can run. torch.load is never used.

class StorageType:
    def __init__(self, name: str, itemsize: int) -> None:
        self.name = name
        self.itemsize = itemsize


STORAGE_TYPES = {"BFloat16Storage": StorageType("bfloat16", 2)}


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


def parse_record(pkl: bytes, scene: str) -> tuple[TensorRef, dict]:
    """Return (target tensor reference, meta dict) from one data.pkl, checking every latent."""
    record = RestrictedUnpickler(io.BytesIO(pkl)).load()
    if not isinstance(record, dict) or record.get("scene_id") != scene:
        raise ValueError(f"{scene}: record scene_id mismatch")
    if record.get("vae") != "Wan2.1_VAE" or record.get("tiled") is not False:
        raise ValueError(f"{scene}: encoder metadata changed (vae={record.get('vae')!r}, tiled={record.get('tiled')!r})")
    latents = record.get("latents")
    if not isinstance(latents, dict) or tuple(sorted(latents)) != tuple(sorted(LATENT_KEYS)):
        raise ValueError(f"{scene}: latents dict keys changed")
    keys = set()
    for name in LATENT_KEYS:
        tensor = latents[name]
        if not isinstance(tensor, TensorRef) or tensor.storage.storage_type.name != "bfloat16":
            raise ValueError(f"{scene}: latents[{name!r}] is not a bfloat16 tensor")
        if tensor.size != LATENT_SHAPE or tensor.stride != contiguous_strides(LATENT_SHAPE) or tensor.offset != 0:
            raise ValueError(f"{scene}: latents[{name!r}] is not a contiguous {LATENT_SHAPE} tensor")
        if tensor.storage.numel != LATENT_VALUES:
            raise ValueError(f"{scene}: latents[{name!r}] storage numel {tensor.storage.numel}")
        keys.add(tensor.storage.key)
    if len(keys) != len(LATENT_KEYS):
        raise ValueError(f"{scene}: latent tensors share storage")
    meta = record.get("meta")
    if not isinstance(meta, dict) or meta.get("scene_id") != scene:
        raise ValueError(f"{scene}: meta row missing")
    return latents["target"], meta


# --- hand-written zip reader over the three fragments ----------------------------------------

def _zip64_extra(extra: bytes, need: list[str], values: dict[str, int]) -> None:
    pos = 0
    while pos + 4 <= len(extra):
        tag, length = struct.unpack_from("<HH", extra, pos)
        body = extra[pos + 4 : pos + 4 + length]
        if tag == 0x0001:
            for i, name in enumerate(need):
                values[name] = struct.unpack_from("<Q", body, 8 * i)[0]
            return
        pos += 4 + length
    if need:
        raise ValueError("zip64 extra field missing")


def central_directory(tail: bytes, tail_start: int, file_size: int) -> dict[str, dict[str, int]]:
    """Parse the end records and central directory held in tail (file bytes [tail_start, file_size))."""
    if tail_start + len(tail) != file_size:
        raise ValueError("tail fragment does not end at the archive end")
    eocd = tail.rfind(b"PK\x05\x06")
    if eocd < 0 or eocd + 22 > len(tail):
        raise ValueError("end of central directory record not found")
    _, disk, cd_disk, n_disk, n_total, cd_size, cd_offset, comment_len = struct.unpack_from("<IHHHHIIH", tail, eocd)
    if eocd + 22 + comment_len != len(tail) or disk != 0 or cd_disk != 0 or n_disk != n_total:
        raise ValueError("unsupported end of central directory record")
    if cd_offset == 0xFFFFFFFF or n_total == 0xFFFF or cd_size == 0xFFFFFFFF:
        locator = eocd - 20
        if locator < 0 or tail[locator : locator + 4] != b"PK\x06\x07":
            raise ValueError("zip64 locator missing")
        z64_offset = struct.unpack_from("<Q", tail, locator + 8)[0]
        rel = z64_offset - tail_start
        if rel < 0 or tail[rel : rel + 4] != b"PK\x06\x06":
            raise ValueError("zip64 end record missing")
        n_total, cd_size, cd_offset = struct.unpack_from("<QQQ", tail, rel + 32)
    pos = cd_offset - tail_start
    if pos < 0 or pos + cd_size > len(tail):
        raise ValueError("central directory outside tail fragment")
    entries: dict[str, dict[str, int]] = {}
    for _ in range(n_total):
        if tail[pos : pos + 4] != b"PK\x01\x02":
            raise ValueError("bad central directory entry signature")
        (_, _, _, flags, method, _, _, crc, csize, usize, nlen, elen, clen, _, _, _, lho) = struct.unpack_from(
            "<IHHHHHHIIIHHHHHII", tail, pos
        )
        name = tail[pos + 46 : pos + 46 + nlen].decode("utf-8")
        extra = tail[pos + 46 + nlen : pos + 46 + nlen + elen]
        values = {"usize": usize, "csize": csize, "lho": lho}
        need = [k for k in ("usize", "csize", "lho") if values[k] == 0xFFFFFFFF]
        _zip64_extra(extra, need, values)
        if method != 0 or values["usize"] != values["csize"] or flags & 0x1:
            raise ValueError(f"member {name} is not stored uncompressed")
        entries[name] = {"crc32": crc, "size": values["usize"], "lho": values["lho"]}
        pos += 46 + nlen + elen + clen
    return {"cd_start": cd_offset, "entries": entries}  # type: ignore[return-value]


def member_bytes(fragment: bytes, fragment_start: int, entry: dict[str, int], name: str) -> bytes:
    """Read a stored member from a fragment that starts at file offset fragment_start."""
    rel = entry["lho"] - fragment_start
    if rel < 0 or fragment[rel : rel + 4] != b"PK\x03\x04":
        raise ValueError(f"local header of {name} not in fragment")
    method, = struct.unpack_from("<H", fragment, rel + 8)
    nlen, elen = struct.unpack_from("<HH", fragment, rel + 26)
    if method != 0 or fragment[rel + 30 : rel + 30 + nlen].decode("utf-8") != name:
        raise ValueError(f"local header of {name} does not match central directory")
    start = rel + 30 + nlen + elen
    data = fragment[start : start + entry["size"]]
    if len(data) != entry["size"]:
        raise ValueError(f"member {name} truncated in fragment")
    if zlib.crc32(data) != entry["crc32"]:
        raise ValueError(f"member {name} CRC-32 mismatch")
    return data


def decode_scene(download_dir: Path, entry: dict[str, object]) -> tuple[bytes, dict]:
    """Hand-parse one scene's fragments; return (target latent bytes, meta)."""
    scene = str(entry["scene_id"])
    paths = fragment_paths(download_dir, scene)
    head = paths["head"].read_bytes()
    target = paths["target"].read_bytes()
    tail = paths["tail"].read_bytes()
    if len(head) != entry["head_stop"] or len(target) != int(entry["target_stop"]) - int(entry["target_start"]):
        raise ValueError(f"{scene}: fragment sizes differ from the pinned ranges")
    cd = central_directory(tail, int(entry["cd_start"]), int(entry["size_bytes"]))
    if cd["cd_start"] != entry["cd_start"]:
        raise ValueError(f"{scene}: central directory offset changed")
    members = cd["entries"]
    prefix = f"{scene}.pt/"
    pkl_entry = members.get(prefix + "data.pkl")
    order_entry = members.get(prefix + "byteorder")
    if pkl_entry is None or order_entry is None:
        raise ValueError(f"{scene}: data.pkl or byteorder member missing")
    if pkl_entry["crc32"] != entry["pkl_crc32"]:
        raise ValueError(f"{scene}: data.pkl CRC-32 differs from the pinned value")
    if member_bytes(head, 0, order_entry, prefix + "byteorder") != b"little":
        raise ValueError(f"{scene}: archive is not little-endian")
    tensor, meta = parse_record(member_bytes(head, 0, pkl_entry, prefix + "data.pkl"), scene)
    if tensor.storage.key != entry["target_key"]:
        raise ValueError(f"{scene}: target storage key changed")
    name = prefix + "data/" + tensor.storage.key
    target_entry = members.get(name)
    if target_entry is None or target_entry["lho"] != entry["target_start"] or target_entry["crc32"] != entry["target_crc32"]:
        raise ValueError(f"{scene}: target member offset or CRC-32 differs from the pinned value")
    later = [m["lho"] for m in members.values() if m["lho"] > target_entry["lho"]]
    if not later or min(later) != entry["target_stop"]:
        raise ValueError(f"{scene}: target range does not end at the next member")
    data_members = [m["lho"] for n, m in members.items() if n.startswith(prefix + "data/")]
    if min(data_members) != entry["head_stop"]:
        raise ValueError(f"{scene}: head range does not end at the first storage")
    payload = member_bytes(target, int(entry["target_start"]), target_entry, name)
    if len(payload) != LATENT_BYTES:
        raise ValueError(f"{scene}: target storage holds {len(payload)} bytes")
    return payload, meta


def decode_scene_zipfile(download_dir: Path, entry: dict[str, object], scratch: Path) -> tuple[bytes, dict]:
    """Independent path: reassemble a sparse archive and read it with the stdlib zipfile module."""
    scene = str(entry["scene_id"])
    paths = fragment_paths(download_dir, scene)
    sparse = scratch / f"{scene}.pt"
    with sparse.open("wb") as handle:
        handle.truncate(int(entry["size_bytes"]))
        for key, offset in (("head", 0), ("target", entry["target_start"]), ("tail", entry["cd_start"])):
            handle.seek(int(offset))
            handle.write(paths[key].read_bytes())
    try:
        with zipfile.ZipFile(sparse) as archive:
            prefix = f"{scene}.pt/"
            if archive.read(prefix + "byteorder") != b"little":
                raise ValueError(f"{scene}: archive is not little-endian")
            tensor, meta = parse_record(archive.read(prefix + "data.pkl"), scene)
            info = archive.getinfo(prefix + "data/" + tensor.storage.key)
            if info.compress_type != zipfile.ZIP_STORED or info.header_offset != entry["target_start"]:
                raise ValueError(f"{scene}: target member layout changed")
            payload = archive.read(info)  # zipfile checks the CRC-32
    finally:
        sparse.unlink()
    return payload, meta


# --- statistics -----------------------------------------------------------------------------

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
    if not (0.05 < std < 20.0) or max(abs(minimum), abs(maximum)) > 100.0:
        raise ValueError(f"{name}: implausible latent distribution std={std} range=({minimum}, {maximum})")
    plane = LATENT_VALUES // LATENT_SHAPE[0]
    for channel in range(LATENT_SHAPE[0]):
        if len(set(codes[channel * plane : (channel + 1) * plane])) < 2:
            raise ValueError(f"{name}: constant latent channel {channel}")
    top_code, top_count = histogram.most_common(1)[0]
    return {
        "minimum": minimum,
        "maximum": maximum,
        "mean": round(mean, 9),
        "std": round(std, 9),
        "zero_count": histogram.get(0x0000, 0) + histogram.get(0x8000, 0),
        "distinct_values": len(histogram),
        "most_common_fraction": round(top_count / total, 6),
    }


def make_row(entry: dict[str, object], payload: bytes, meta: dict) -> tuple[dict[str, object], str]:
    scene = str(entry["scene_id"])
    filename = f"{scene}.bin"
    target = meta.get("target") if isinstance(meta.get("target"), dict) else {}
    row = {
        "dataset_id": DATASET_ID,
        "series_id": SERIES_ID,
        "role": "primary",
        "sample_path": f"samples/{DATASET_ID}/{SERIES_ID}/{filename}",
        "numeric_kind": "float",
        "float_format": "bfloat16",
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
        "scene_id": scene,
        "focal_group": scene.split("_")[1],
        "target_camera": target.get("cam"),
        "source_file": f"{scene}.pt",
        "source_lfs_sha256": entry["lfs_sha256"],
        "source_member": f"{scene}.pt/data/{entry['target_key']}",
        "source_member_crc32": f"{int(entry['target_crc32']):08x}",
        "cache_repository": CACHE_REPO,
        "cache_revision": CACHE_REVISION,
        "sha256": hashlib.sha256(payload).hexdigest(),
        **latent_statistics(payload, scene),
    }
    return row, filename


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
        "samples": len(rows),
        "focal_groups": dict(sorted(collections.Counter(str(r["focal_group"]) for r in rows).items())),
        "primary_values": sum(counts),
        "primary_sample_bytes": sum(int(row["sample_size_bytes"]) for row in rows),
        "median_value_count": statistics.median(counts),
        "min_std": min(float(row["std"]) for row in rows),
        "max_std": max(float(row["std"]) for row in rows),
        "min_value": min(float(row["minimum"]) for row in rows),
        "max_value": max(float(row["maximum"]) for row in rows),
        "min_distinct_values": min(int(row["distinct_values"]) for row in rows),
        "max_most_common_fraction": max(float(row["most_common_fraction"]) for row in rows),
    }


# --- commands -------------------------------------------------------------------------------

def command_selection(args: argparse.Namespace) -> None:
    """Print '<scene> <size> <cd_start> <head_stop> <target_start> <target_stop>' for download.sh."""
    for e in read_selection():
        print(e["scene_id"], e["size_bytes"], e["cd_start"], e["head_stop"], e["target_start"], e["target_stop"])


def command_check_scene(args: argparse.Namespace) -> None:
    entry = next((e for e in read_selection() if e["scene_id"] == args.scene), None)
    if entry is None:
        raise ValueError(f"scene {args.scene} is not selected")
    payload, _ = decode_scene(Path(args.download_dir), entry)
    latent_statistics(payload, args.scene)


def command_validate(args: argparse.Namespace) -> None:
    download_dir = Path(args.download_dir)
    validate_cards(download_dir)
    rows = []
    for entry in read_selection():
        payload, meta = decode_scene(download_dir, entry)
        rows.append(make_row(entry, payload, meta)[0])
    stats = summarize(rows)
    print(f"validated dataset={DATASET_ID} samples={stats['samples']} primary_bytes={stats['primary_sample_bytes']}")


def command_build(args: argparse.Namespace) -> None:
    download_dir = Path(args.download_dir)
    validate_cards(download_dir)
    samples_dir = Path(args.samples_dir)
    if samples_dir.exists():
        shutil.rmtree(samples_dir)
    out_dir = samples_dir / SERIES_ID
    out_dir.mkdir(parents=True)
    rows = []
    for entry in read_selection():
        payload, meta = decode_scene(download_dir, entry)
        row, filename = make_row(entry, payload, meta)
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
    download_dir = Path(args.download_dir)
    validate_cards(download_dir)
    out_dir = Path(args.samples_dir) / SERIES_ID
    actual_rows = [json.loads(line) for line in Path(args.index).read_text(encoding="utf-8").splitlines() if line.strip()]
    rows = []
    names = set()
    scratch_root = Path(args.scratch)
    scratch_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=scratch_root) as scratch:
        for entry in read_selection():
            payload, meta = decode_scene_zipfile(download_dir, entry, Path(scratch))
            row, filename = make_row(entry, payload, meta)
            sample = out_dir / filename
            if not sample.is_file() or sample.read_bytes() != payload:
                raise ValueError(f"source/output byte mismatch: {filename}")
            rows.append(row)
            names.add(filename)
    if {path.name for path in out_dir.iterdir()} != names:
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


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser()
    commands = root.add_subparsers(dest="command", required=True)
    commands.add_parser("selection").set_defaults(func=command_selection)
    check = commands.add_parser("check-scene")
    check.add_argument("--download-dir", required=True)
    check.add_argument("--scene", required=True)
    check.set_defaults(func=command_check_scene)
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
            command.add_argument("--scratch", required=True)
        command.set_defaults(func=function)
    return root


if __name__ == "__main__":
    arguments = parser().parse_args()
    arguments.func(arguments)
