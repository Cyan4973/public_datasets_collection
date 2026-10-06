#!/usr/bin/env python3
"""DIODE validation laser-scanner depth maps: inventory, view selection, build, verify.

Pure standard library (numpy is not required). The pinned `val.tar.gz` is
streamed with `tarfile` mode `r|gz` and is never extracted to disk.

Subcommands:
  build     two streaming passes: (1) inventory + MD5, (2) emit selected depth maps
  verify    independent re-check: re-inventory + MD5, greedy-selection property
            check, byte comparison against the archive, mask consistency, and
            value checks on the written samples
  predict   run the view selection on the official data_list.zip enumeration
            (authoring aid; the build never reads data_list.zip)
  selftest  build and verify a small synthetic archive with the same layout
"""
from __future__ import annotations

import argparse
import array
import ast
import collections
import hashlib
import io
import json
import math
import re
import shutil
import struct
import sys
import tarfile
import time
import tomllib
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

DATASET_ID = "diode_val_laser_depth_f32"
SERIES_ID = "diode_laser_depth_m_f32"
ARCHIVE_NAME = "val.tar.gz"
ARCHIVE_BYTES = 2_774_625_282
ARCHIVE_MD5 = "5c895d09201b88973c8fe4552a67dd85"
# Official val statistics (diode-dataset.org "Partitioning" table and
# data_list.zip val_indoors.csv / val_outdoor.csv): 325 + 446 = 771 views.
EXPECTED_VIEWS = {"indoors": 325, "outdoor": 446}
EXPECTED_SCANS = {"indoors": 10, "outdoor": 10}

HEIGHT, WIDTH = 768, 1024
VALUES = HEIGHT * WIDTH
SAMPLE_BYTES = VALUES * 4
DEPTH_SHAPE = (HEIGHT, WIDTH, 1)
MASK_SHAPE = (HEIGHT, WIDTH)

# Computational-camera intrinsics, diode-devkit intrinsics.txt:
# [fx, fy, cx, cy] = [886.81, 927.06, 512, 384]  (60.0 deg x 45.0 deg FOV)
FX, FY, CX, CY = 886.81, 927.06, 512.0, 384.0
GRID_U, GRID_V = 64, 48
GRID_RAYS = GRID_U * GRID_V
MAX_SHARED_RAYS = GRID_RAYS * 5 // 100  # 153 of 3072 rays: at most ~5 % shared field of view

MIN_VALID_FRACTION = 0.01  # a view with < 1 % nonzero pixels is degenerate (fatal)
MAX_DEPTH_SANITY_M = 1000.0  # FARO Focus S350 max range is 350 m; gross-corruption bound
MIN_DISTINCT_VALUES = 1000

MEMBER_RE = re.compile(
    r"^val/(indoors|outdoor)/scene_(\d{5})/scan_(\d{5})/"
    r"((\d{5})_(\d{5})_(indoors|outdoor)_(\d{3})_(\d{3}))(\.png|_depth\.npy|_depth_mask\.npy)$"
)
PART_KINDS = {".png": "png", "_depth.npy": "depth", "_depth_mask.npy": "mask"}
INDEX_KEYS = [
    "dataset_id",
    "series_id",
    "sample_path",
    "numeric_kind",
    "bit_width",
    "endianness",
    "element_size_bytes",
    "sample_size_bytes",
    "value_count",
]


@dataclass
class Config:
    data_root: Path
    archive: Path
    archive_bytes: int = ARCHIVE_BYTES
    archive_md5: str = ARCHIVE_MD5
    expected_views: dict = field(default_factory=lambda: dict(EXPECTED_VIEWS))
    expected_scans: dict = field(default_factory=lambda: dict(EXPECTED_SCANS))
    manifest: Path | None = None

    @property
    def samples_root(self) -> Path:
        return self.data_root / "samples" / DATASET_ID

    @property
    def series_dir(self) -> Path:
        return self.samples_root / SERIES_ID

    @property
    def index_path(self) -> Path:
        return self.data_root / "index" / DATASET_ID / "samples.jsonl"

    @property
    def stats_path(self) -> Path:
        return self.data_root / "filtered" / DATASET_ID / "ingest_stats.json"

    @property
    def verify_path(self) -> Path:
        return self.data_root / "filtered" / DATASET_ID / "verify_summary.json"


def log(message: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {message}", flush=True)


def fail(message: str) -> None:
    raise SystemExit(f"FATAL: {message}")


# --------------------------------------------------------------------------
# Archive inventory (streaming, with MD5 over the exact compressed bytes)


class HashingReader:
    """File wrapper that MD5-hashes every byte tarfile pulls from the archive."""

    def __init__(self, handle):
        self.handle = handle
        self.md5 = hashlib.md5()
        self.count = 0

    def read(self, size: int = -1) -> bytes:
        data = self.handle.read(size)
        self.md5.update(data)
        self.count += len(data)
        return data

    def drain(self) -> None:
        while self.read(8 << 20):
            pass


def scan_inventory(cfg: Config) -> dict[str, dict]:
    """Stream the archive once; return {view_id: record}; check size, MD5 and layout."""
    if not cfg.archive.is_file():
        fail(f"missing archive {cfg.archive}; run download.sh first")
    size = cfg.archive.stat().st_size
    if size != cfg.archive_bytes:
        fail(f"archive size {size} != pinned {cfg.archive_bytes}")
    views: dict[str, dict] = {}
    unexpected: list[str] = []
    directories = 0
    with cfg.archive.open("rb") as raw:
        reader = HashingReader(raw)
        with tarfile.open(fileobj=reader, mode="r|gz", bufsize=1 << 20) as tf:
            for member in tf:
                if member.isdir():
                    directories += 1
                    continue
                if not member.isfile():
                    fail(f"unexpected non-regular tar member {member.name!r}")
                match = MEMBER_RE.match(member.name)
                if not match:
                    unexpected.append(member.name)
                    continue
                env, scene, scan, view_id, v_scene, v_scan, v_env, yaw, pitch, suffix = match.groups()
                if (v_scene, v_scan, v_env) != (scene, scan, env):
                    fail(f"view name disagrees with its directory: {member.name}")
                record = views.setdefault(
                    view_id,
                    {
                        "environment": env,
                        "scene": f"scene_{scene}",
                        "scan": f"scan_{scan}",
                        "view_id": view_id,
                        "yaw_deg": int(yaw),
                        "pitch_deg": int(pitch),
                        "member_prefix": f"val/{env}/scene_{scene}/scan_{scan}/{view_id}",
                        "parts": {},
                    },
                )
                kind = PART_KINDS[suffix]
                if kind in record["parts"]:
                    fail(f"duplicate tar member {member.name}")
                record["parts"][kind] = member.size
        reader.drain()
    if reader.count != cfg.archive_bytes:
        fail(f"hashed {reader.count} bytes, expected {cfg.archive_bytes}")
    md5 = reader.md5.hexdigest()
    if md5 != cfg.archive_md5:
        fail(f"archive MD5 {md5} != pinned {cfg.archive_md5}")
    if unexpected:
        fail(f"{len(unexpected)} unexpected regular members, e.g. {unexpected[:3]}")
    for record in views.values():
        parts = record["parts"]
        if set(parts) != {"png", "depth", "mask"}:
            fail(f"view {record['view_id']} lacks parts: has {sorted(parts)}")
        if parts["depth"] <= SAMPLE_BYTES or parts["depth"] > SAMPLE_BYTES + 4096:
            fail(f"view {record['view_id']} depth member size {parts['depth']} is implausible")
    per_env = collections.Counter(r["environment"] for r in views.values())
    scans = collections.defaultdict(set)
    for record in views.values():
        scans[record["environment"]].add((record["scene"], record["scan"]))
    if dict(per_env) != cfg.expected_views:
        fail(f"view counts {dict(per_env)} != expected {cfg.expected_views}")
    if {env: len(s) for env, s in scans.items()} != cfg.expected_scans:
        fail(f"scan counts {({e: len(s) for e, s in scans.items()})} != expected {cfg.expected_scans}")
    log(
        f"inventory ok: bytes={reader.count} md5={md5} directories={directories} "
        f"views={dict(per_env)} scans={({e: len(s) for e, s in scans.items()})}"
    )
    return views


# --------------------------------------------------------------------------
# View selection: deterministic greedy packing with a field-of-view overlap cap


def camera_basis(yaw_deg: float, pitch_deg: float):
    """Forward, right and down unit vectors (world Z up) for a yaw/pitch view, no roll."""
    yaw = math.radians(yaw_deg)
    pitch = math.radians(pitch_deg)
    forward = (math.cos(pitch) * math.cos(yaw), math.cos(pitch) * math.sin(yaw), math.sin(pitch))
    right = (math.sin(yaw), -math.cos(yaw), 0.0)
    down = (
        forward[1] * right[2] - forward[2] * right[1],
        forward[2] * right[0] - forward[0] * right[2],
        forward[0] * right[1] - forward[1] * right[0],
    )
    return forward, right, down


_SHARED_CACHE: dict[tuple[int, int, int], int] = {}


def shared_rays(yaw_a: int, pitch_a: int, yaw_b: int, pitch_b: int) -> int:
    """How many of view A's GRID_U x GRID_V pixel-centre rays fall inside view B's image."""
    key = ((yaw_b - yaw_a) % 360, pitch_a, pitch_b)
    cached = _SHARED_CACHE.get(key)
    if cached is not None:
        return cached
    fa, ra, da = camera_basis(0, pitch_a)
    fb, rb, db = camera_basis(key[0], pitch_b)
    count = 0
    for j in range(GRID_V):
        b = ((j + 0.5) * HEIGHT / GRID_V - CY) / FY
        for i in range(GRID_U):
            a = ((i + 0.5) * WIDTH / GRID_U - CX) / FX
            ray = (fa[0] + a * ra[0] + b * da[0], fa[1] + a * ra[1] + b * da[1], fa[2] + a * ra[2] + b * da[2])
            z = ray[0] * fb[0] + ray[1] * fb[1] + ray[2] * fb[2]
            if z <= 0.0:
                continue
            u = FX * (ray[0] * rb[0] + ray[1] * rb[1] + ray[2] * rb[2]) / z + CX
            v = FY * (ray[0] * db[0] + ray[1] * db[1] + ray[2] * db[2]) / z + CY
            if 0.0 <= u < WIDTH and 0.0 <= v < HEIGHT:
                count += 1
    _SHARED_CACHE[key] = count
    return count


def views_overlap(a: dict, b: dict) -> bool:
    shared = max(
        shared_rays(a["yaw_deg"], a["pitch_deg"], b["yaw_deg"], b["pitch_deg"]),
        shared_rays(b["yaw_deg"], b["pitch_deg"], a["yaw_deg"], a["pitch_deg"]),
    )
    return shared > MAX_SHARED_RAYS


def selection_rank(view_id: str) -> tuple[str, str]:
    return hashlib.sha256(view_id.encode("ascii")).hexdigest(), view_id


def scan_key(record: dict) -> tuple[str, str, str]:
    return record["environment"], record["scene"], record["scan"]


def select_views(views: dict[str, dict]) -> list[dict]:
    """Per scan, visit views in SHA-256(view_id) order and keep a view only when it
    shares at most MAX_SHARED_RAYS rays (both directions) with every view kept so far."""
    by_scan: dict[tuple, list[dict]] = collections.defaultdict(list)
    for record in views.values():
        by_scan[scan_key(record)].append(record)
    selected: list[dict] = []
    for key in sorted(by_scan):
        kept: list[dict] = []
        for record in sorted(by_scan[key], key=lambda r: selection_rank(r["view_id"])):
            if not any(views_overlap(record, other) for other in kept):
                kept.append(record)
        selected.extend(kept)
    selected.sort(key=lambda r: (*scan_key(r), r["view_id"]))
    return selected


# --------------------------------------------------------------------------
# NPY parsing (build: ast.literal_eval; verify: independent regex parser)


def parse_npy_build(blob: bytes) -> tuple[dict, bytes]:
    if blob[:6] != b"\x93NUMPY":
        fail("member lacks the NPY magic")
    major, minor = blob[6], blob[7]
    if (major, minor) == (1, 0):
        header_len = struct.unpack_from("<H", blob, 8)[0]
        start = 10
    elif major in (2, 3):
        header_len = struct.unpack_from("<I", blob, 8)[0]
        start = 12
    else:
        fail(f"unsupported NPY version {major}.{minor}")
    header = ast.literal_eval(blob[start : start + header_len].decode("latin1"))
    if not isinstance(header, dict) or set(header) != {"descr", "fortran_order", "shape"}:
        fail(f"unexpected NPY header {header!r}")
    return header, blob[start + header_len :]


NPY_HEADER_RE = re.compile(
    r"^\{'descr': '(?P<descr>[<>|=][a-z]\d+)', 'fortran_order': (?P<fortran>True|False), "
    r"'shape': \((?P<shape>[0-9, ]*)\), *\}\s*$"
)


def parse_npy_verify(blob: bytes) -> tuple[str, bool, tuple[int, ...], memoryview]:
    view = memoryview(blob)
    if bytes(view[:8]) != b"\x93NUMPY\x01\x00":
        fail("verify: member is not NPY format 1.0")
    (header_len,) = struct.unpack("<H", bytes(view[8:10]))
    if (10 + header_len) % 64:
        fail("verify: NPY header is not 64-byte aligned")
    text = bytes(view[10 : 10 + header_len]).decode("ascii")
    match = NPY_HEADER_RE.match(text)
    if not match:
        fail(f"verify: unparsed NPY header {text!r}")
    shape = tuple(int(part) for part in match.group("shape").replace(" ", "").split(",") if part)
    return match.group("descr"), match.group("fortran") == "True", shape, view[10 + header_len :]


def floats_from(payload: bytes) -> array.array:
    values = array.array("f")
    values.frombytes(payload)
    if sys.byteorder != "little":
        values.byteswap()
    return values


def depth_stats(values: array.array) -> dict:
    if len(values) != VALUES:
        fail(f"depth map has {len(values)} values, expected {VALUES}")
    finite = sum(map(math.isfinite, values))
    if finite != VALUES:
        fail(f"depth map has {VALUES - finite} non-finite values")
    minimum = min(values)
    if minimum < 0.0:
        fail(f"depth map has negative depth {minimum}")
    zeros = values.count(0.0)
    if (VALUES - zeros) < MIN_VALID_FRACTION * VALUES:
        fail(f"depth map has only {VALUES - zeros} nonzero pixels")
    maximum = max(values)
    if maximum > MAX_DEPTH_SANITY_M:
        fail(f"depth map maximum {maximum} m exceeds sanity bound {MAX_DEPTH_SANITY_M}")
    distinct = len(set(values))
    if distinct < MIN_DISTINCT_VALUES:
        fail(f"depth map has only {distinct} distinct values")
    positive_min = min(v for v in values if v > 0.0)
    return {
        "zero_count": zeros,
        "positive_min": positive_min,
        "max": maximum,
        "distinct_values": distinct,
    }


# --------------------------------------------------------------------------
# Build


def build(cfg: Config) -> None:
    log(f"pass 1/2: inventory {cfg.archive}")
    views = scan_inventory(cfg)
    selected = select_views(views)
    wanted = {f"{r['member_prefix']}_depth.npy": r for r in selected}
    log(f"selected {len(selected)} of {len(views)} views")

    if cfg.samples_root.exists():
        shutil.rmtree(cfg.samples_root)
    cfg.series_dir.mkdir(parents=True, exist_ok=True)
    cfg.index_path.parent.mkdir(parents=True, exist_ok=True)
    cfg.stats_path.parent.mkdir(parents=True, exist_ok=True)
    if cfg.index_path.exists():
        cfg.index_path.unlink()

    log("pass 2/2: emit selected depth maps")
    rows: dict[str, dict] = {}
    with tarfile.open(cfg.archive, mode="r|gz", bufsize=1 << 20) as tf:
        for member in tf:
            record = wanted.get(member.name)
            if record is None:
                continue
            handle = tf.extractfile(member)
            if handle is None:
                fail(f"cannot read {member.name}")
            blob = handle.read()
            if len(blob) != member.size:
                fail(f"short read of {member.name}")
            header, payload = parse_npy_build(blob)
            if header["descr"] != "<f4" or header["fortran_order"] is not False or tuple(header["shape"]) != DEPTH_SHAPE:
                fail(f"{member.name}: unexpected header {header!r}")
            if len(payload) != SAMPLE_BYTES:
                fail(f"{member.name}: payload {len(payload)} bytes, expected {SAMPLE_BYTES}")
            stats = depth_stats(floats_from(payload))
            out = cfg.series_dir / f"{record['view_id']}_depth.f32"
            tmp = out.with_suffix(".f32.part")
            tmp.write_bytes(payload)
            tmp.replace(out)
            rows[record["view_id"]] = {
                "dataset_id": DATASET_ID,
                "series_id": SERIES_ID,
                "sample_path": str(out.relative_to(cfg.data_root)),
                "numeric_kind": "float",
                "bit_width": 32,
                "endianness": "little",
                "element_size_bytes": 4,
                "sample_size_bytes": SAMPLE_BYTES,
                "value_count": VALUES,
                "shape": [HEIGHT, WIDTH],
                "axes": ["image_row", "image_column"],
                "unit": "m",
                "environment": record["environment"],
                "scene": record["scene"],
                "scan": record["scan"],
                "view_id": record["view_id"],
                "yaw_deg": record["yaw_deg"],
                "pitch_deg": record["pitch_deg"],
                "source_member": member.name,
                "sha256": hashlib.sha256(payload).hexdigest(),
                **stats,
            }
            log(
                f"  {record['view_id']}: zeros={stats['zero_count']} "
                f"range=({stats['positive_min']:.6g}, {stats['max']:.6g}) distinct={stats['distinct_values']}"
            )
    missing = sorted(set(r["view_id"] for r in selected) - set(rows))
    if missing:
        fail(f"{len(missing)} selected depth maps not found in pass 2: {missing[:5]}")

    ordered = [rows[r["view_id"]] for r in selected]
    with cfg.index_path.open("w", encoding="utf-8") as handle:
        for row in ordered:
            handle.write(json.dumps(row, sort_keys=False) + "\n")

    per_scan = collections.OrderedDict()
    for key in sorted({scan_key(r) for r in views.values()}):
        label = "/".join(key)
        per_scan[label] = {
            "views": sum(1 for r in views.values() if scan_key(r) == key),
            "selected": sum(1 for r in selected if scan_key(r) == key),
        }
    total_values = VALUES * len(ordered)
    stats_doc = {
        "dataset_id": DATASET_ID,
        "series_id": SERIES_ID,
        "archive": {"name": cfg.archive.name, "bytes": cfg.archive_bytes, "md5": cfg.archive_md5},
        "inventory_views": dict(collections.Counter(r["environment"] for r in views.values())),
        "selection_rule": {
            "order": "per scan, ascending SHA-256 hex digest of the view id",
            "camera_intrinsics": [FX, FY, CX, CY],
            "ray_grid": [GRID_U, GRID_V],
            "max_shared_rays": MAX_SHARED_RAYS,
        },
        "per_scan": per_scan,
        "selected_by_environment": dict(collections.Counter(r["environment"] for r in selected)),
        "selected_by_pitch_deg": {str(k): v for k, v in sorted(collections.Counter(r["pitch_deg"] for r in selected).items())},
        "sample_count": len(ordered),
        "total_values": total_values,
        "total_bytes": SAMPLE_BYTES * len(ordered),
        "zero_values": sum(r["zero_count"] for r in ordered),
        "zero_fraction": round(sum(r["zero_count"] for r in ordered) / total_values, 6),
        "global_positive_min": min(r["positive_min"] for r in ordered),
        "global_max": max(r["max"] for r in ordered),
        "selected_views": [r["view_id"] for r in ordered],
    }
    cfg.stats_path.write_text(json.dumps(stats_doc, indent=1) + "\n", encoding="utf-8")
    log(
        f"build done: samples={len(ordered)} bytes={SAMPLE_BYTES * len(ordered)} "
        f"by_env={stats_doc['selected_by_environment']} by_pitch={stats_doc['selected_by_pitch_deg']}"
    )


# --------------------------------------------------------------------------
# Verify (independent code paths where practical)


def verify(cfg: Config) -> None:
    if not cfg.index_path.is_file():
        fail(f"missing index {cfg.index_path}")
    rows = [json.loads(line) for line in cfg.index_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not rows:
        fail("empty index")
    by_view: dict[str, dict] = {}
    paths = set()
    for row in rows:
        missing = [key for key in INDEX_KEYS if key not in row]
        if missing:
            fail(f"index row lacks {missing}")
        expected = {
            "dataset_id": DATASET_ID,
            "series_id": SERIES_ID,
            "numeric_kind": "float",
            "bit_width": 32,
            "endianness": "little",
            "element_size_bytes": 4,
            "sample_size_bytes": SAMPLE_BYTES,
            "value_count": VALUES,
        }
        for key, value in expected.items():
            if row[key] != value:
                fail(f"index row {row.get('view_id')}: {key}={row[key]!r}, expected {value!r}")
        if row["view_id"] in by_view or row["sample_path"] in paths:
            fail(f"duplicate index row for {row['view_id']}")
        by_view[row["view_id"]] = row
        paths.add(row["sample_path"])
        path = cfg.data_root / row["sample_path"]
        if not path.is_file() or path.stat().st_size != SAMPLE_BYTES:
            fail(f"missing or wrong-sized sample {path}")
    on_disk = {p.name for p in cfg.series_dir.iterdir()} if cfg.series_dir.is_dir() else set()
    indexed = {Path(r["sample_path"]).name for r in rows}
    if on_disk != indexed:
        fail(f"sample directory and index disagree: extra={sorted(on_disk - indexed)[:3]} missing={sorted(indexed - on_disk)[:3]}")

    log("verify pass 1/2: re-inventory archive (size, MD5, layout)")
    views = scan_inventory(cfg)
    unknown = sorted(set(by_view) - set(views))
    if unknown:
        fail(f"indexed views absent from the archive: {unknown[:5]}")
    for view_id, row in by_view.items():
        record = views[view_id]
        for key in ("environment", "scene", "scan", "yaw_deg", "pitch_deg"):
            if row[key] != record[key]:
                fail(f"{view_id}: index {key}={row[key]!r} but archive says {record[key]!r}")

    # Greedy-selection property: walking each scan in SHA-256 order, a view is
    # selected exactly when it does not overlap any earlier selected view.
    by_scan: dict[tuple, list[dict]] = collections.defaultdict(list)
    for record in views.values():
        by_scan[scan_key(record)].append(record)
    for key, members in sorted(by_scan.items()):
        earlier_selected: list[dict] = []
        for record in sorted(members, key=lambda r: selection_rank(r["view_id"])):
            clear = all(not views_overlap(record, other) for other in earlier_selected)
            chosen = record["view_id"] in by_view
            if clear != chosen:
                fail(f"selection property violated at {record['view_id']} (clear={clear}, indexed={chosen})")
            if chosen:
                earlier_selected.append(record)
        if not earlier_selected:
            fail(f"scan {'/'.join(key)} contributes no sample")
    selected_scans = {scan_key(views[v]) for v in by_view}
    if selected_scans != set(by_scan):
        fail("not every scan is represented")
    log(f"selection property ok: {len(by_view)} views over {len(selected_scans)} scans")

    log("verify pass 2/2: compare samples with archive depth maps and check validity masks")
    wanted = {}
    for view_id in by_view:
        prefix = views[view_id]["member_prefix"]
        wanted[f"{prefix}_depth.npy"] = (view_id, "depth")
        wanted[f"{prefix}_depth_mask.npy"] = (view_id, "mask")
    pending_depth: dict[str, bytes] = {}
    pending_mask: dict[str, tuple[str, memoryview]] = {}
    compared = set()
    mask_stats = collections.Counter()
    mask_descrs = collections.Counter()

    def check_pair(view_id: str, depth_payload: bytes, mask_descr: str, mask_payload: memoryview) -> None:
        depth = floats_from(depth_payload)
        code = {"<f4": "f", "<f8": "d"}[mask_descr]
        mask = array.array(code)
        mask.frombytes(bytes(mask_payload))
        if sys.byteorder != "little":
            mask.byteswap()
        if len(mask) != VALUES:
            fail(f"{view_id}: mask has {len(mask)} values")
        ones = mask.count(1.0)
        zeros = mask.count(0.0)
        if ones + zeros != VALUES:
            fail(f"{view_id}: mask values other than 0/1")
        zero_depth_valid = sum(1 for d, m in zip(depth, mask) if d == 0.0 and m != 0.0)
        if zero_depth_valid:
            fail(f"{view_id}: {zero_depth_valid} zero-depth pixels are marked valid by the mask")
        masked_nonzero = zeros - depth.count(0.0)
        mask_stats["mask_valid"] += ones
        mask_stats["mask_invalid"] += zeros
        mask_stats["mask_invalid_nonzero_depth"] += masked_nonzero
        mask_descrs[mask_descr] += 1

    with tarfile.open(cfg.archive, mode="r|gz", bufsize=1 << 20) as tf:
        for member in tf:
            target = wanted.get(member.name)
            if target is None:
                continue
            view_id, kind = target
            blob = tf.extractfile(member).read()
            descr, fortran, shape, payload = parse_npy_verify(blob)
            if fortran:
                fail(f"{member.name}: Fortran order")
            if kind == "depth":
                if descr != "<f4" or shape != DEPTH_SHAPE or len(payload) != SAMPLE_BYTES:
                    fail(f"{member.name}: descr={descr} shape={shape} bytes={len(payload)}")
                sample = (cfg.data_root / by_view[view_id]["sample_path"]).read_bytes()
                if sample != payload:
                    fail(f"{view_id}: sample bytes differ from the archive payload")
                if hashlib.sha256(sample).hexdigest() != by_view[view_id]["sha256"]:
                    fail(f"{view_id}: index sha256 mismatch")
                compared.add(view_id)
                depth_payload = bytes(payload)
                if view_id in pending_mask:
                    check_pair(view_id, depth_payload, *pending_mask.pop(view_id))
                else:
                    pending_depth[view_id] = depth_payload
            else:
                if descr not in ("<f4", "<f8") or shape != MASK_SHAPE:
                    fail(f"{member.name}: mask descr={descr} shape={shape}")
                if len(payload) != VALUES * int(descr[2]):
                    fail(f"{member.name}: mask payload size {len(payload)}")
                if view_id in pending_depth:
                    check_pair(view_id, pending_depth.pop(view_id), descr, payload)
                else:
                    pending_mask[view_id] = (descr, payload)
    if compared != set(by_view) or pending_depth or pending_mask:
        fail(f"unmatched members: compared={len(compared)} pending_depth={len(pending_depth)} pending_mask={len(pending_mask)}")

    log("value checks on written samples")
    zero_total = 0
    global_max = 0.0
    global_min_pos = math.inf
    for view_id, row in by_view.items():
        values = floats_from((cfg.data_root / row["sample_path"]).read_bytes())
        stats = depth_stats(values)
        for key in ("zero_count", "positive_min", "max", "distinct_values"):
            if stats[key] != row[key]:
                fail(f"{view_id}: recomputed {key}={stats[key]!r} != index {row[key]!r}")
        zero_total += stats["zero_count"]
        global_max = max(global_max, stats["max"])
        global_min_pos = min(global_min_pos, stats["positive_min"])
    digests = collections.Counter(row["sha256"] for row in rows)
    if max(digests.values()) > 1:
        fail("duplicate sample payloads")

    total_bytes = SAMPLE_BYTES * len(rows)
    if cfg.manifest is not None:
        manifest = tomllib.loads(cfg.manifest.read_text(encoding="utf-8"))
        series = [s for s in manifest.get("series", []) if s.get("id") == SERIES_ID]
        if len(series) != 1:
            fail("manifest does not declare the series exactly once")
        if series[0].get("sample_count") != len(rows) or series[0].get("total_size_bytes") != total_bytes:
            fail(
                f"manifest sample_count/total_size_bytes {series[0].get('sample_count')}/{series[0].get('total_size_bytes')} "
                f"!= realized {len(rows)}/{total_bytes}"
            )
    summary = {
        "dataset_id": DATASET_ID,
        "samples": len(rows),
        "total_bytes": total_bytes,
        "by_environment": dict(collections.Counter(r["environment"] for r in rows)),
        "scans": len(selected_scans),
        "zero_fraction": round(zero_total / (VALUES * len(rows)), 6),
        "global_positive_min": global_min_pos,
        "global_max": global_max,
        "mask_descr_counts": dict(mask_descrs),
        **dict(mask_stats),
    }
    cfg.verify_path.parent.mkdir(parents=True, exist_ok=True)
    cfg.verify_path.write_text(json.dumps(summary, indent=1) + "\n", encoding="utf-8")
    log(f"verify ok: {json.dumps(summary)}")


# --------------------------------------------------------------------------
# Authoring aid and synthetic self-test


def predict(data_list: Path) -> None:
    views: dict[str, dict] = {}
    with zipfile.ZipFile(data_list) as archive:
        for name in ("data_list/val_indoors.csv", "data_list/val_outdoor.csv"):
            for line in archive.read(name).decode("utf-8").splitlines():
                depth = line.split(",")[1].removeprefix("./")
                match = MEMBER_RE.match(depth)
                if not match or match.group(10) != "_depth.npy":
                    fail(f"unexpected data_list entry {depth!r}")
                env, scene, scan, view_id, _, _, _, yaw, pitch, _ = match.groups()
                views[view_id] = {
                    "environment": env,
                    "scene": f"scene_{scene}",
                    "scan": f"scan_{scan}",
                    "view_id": view_id,
                    "yaw_deg": int(yaw),
                    "pitch_deg": int(pitch),
                }
    selected = select_views(views)
    per_env = collections.Counter(r["environment"] for r in selected)
    per_pitch = collections.Counter(r["pitch_deg"] for r in selected)
    per_scan = collections.Counter("/".join(scan_key(r)) for r in selected)
    print(json.dumps({
        "views": len(views),
        "selected": len(selected),
        "bytes": len(selected) * SAMPLE_BYTES,
        "by_environment": dict(per_env),
        "by_pitch_deg": {str(k): v for k, v in sorted(per_pitch.items())},
        "per_scan": dict(sorted(per_scan.items())),
    }, indent=1))


def npy_bytes(descr: str, shape: tuple[int, ...], payload: bytes) -> bytes:
    shape_text = "(" + ", ".join(str(s) for s in shape) + ("," if len(shape) == 1 else "") + ")"
    header = "{'descr': '%s', 'fortran_order': False, 'shape': %s, }" % (descr, shape_text)
    pad = 64 - (10 + len(header) + 1) % 64
    header = header + " " * (pad % 64) + "\n"
    return b"\x93NUMPY\x01\x00" + struct.pack("<H", len(header)) + header.encode("latin1") + payload


def selftest(workdir: Path) -> None:
    if workdir.exists():
        shutil.rmtree(workdir)
    data_root = workdir / "data"
    archive = data_root / "downloads" / DATASET_ID / ARCHIVE_NAME
    archive.parent.mkdir(parents=True)
    layout = {
        ("outdoor", "00090", "00900"): [(0, 0), (10, 0), (60, 10), (120, 20), (180, 0), (190, 10), (240, 50), (300, 30)],
        ("indoors", "00091", "00901"): [(0, 0), (0, 40), (50, 0), (90, 10), (150, 20), (270, 0), (330, 50)],
    }
    members: list[tuple[str, bytes]] = []
    seed = 12345
    for (env, scene, scan), angles in layout.items():
        for index, (yaw, pitch) in enumerate(angles):
            view_id = f"{scene}_{scan}_{env}_{yaw:03d}_{pitch:03d}"
            prefix = f"val/{env}/scene_{scene}/scan_{scan}/{view_id}"
            depth = array.array("f", bytes(SAMPLE_BYTES))
            mask = array.array("f" if index % 2 else "d", bytes(VALUES * (4 if index % 2 else 8)))
            for k in range(VALUES):
                seed = (seed * 1103515245 + 12345) & 0x7FFFFFFF
                if seed % 17 == 0:
                    continue  # no return: depth 0, mask 0
                depth[k] = 0.6 + (seed % 2_000_000) / 10_000.0
                mask[k] = 0.0 if seed % 31 == 0 else 1.0  # some nonzero depths masked invalid
            if sys.byteorder != "little":
                depth.byteswap()
                mask.byteswap()
            members.append((prefix + ".png", b"\x89PNG\r\n\x1a\n" + bytes(64)))
            members.append((prefix + "_depth_mask.npy", npy_bytes("<f4" if index % 2 else "<f8", MASK_SHAPE, mask.tobytes())))
            members.append((prefix + "_depth.npy", npy_bytes("<f4", DEPTH_SHAPE, depth.tobytes())))
    with tarfile.open(archive, "w:gz", format=tarfile.GNU_FORMAT) as tf:
        dirs = sorted({"/".join(name.split("/")[:k]) for name, _ in members for k in range(1, 5)})
        for directory in dirs:
            info = tarfile.TarInfo(directory)
            info.type = tarfile.DIRTYPE
            tf.addfile(info)
        for name, blob in members:
            info = tarfile.TarInfo(name)
            info.size = len(blob)
            tf.addfile(info, io.BytesIO(blob))
    blob = archive.read_bytes()
    cfg = Config(
        data_root=data_root,
        archive=archive,
        archive_bytes=len(blob),
        archive_md5=hashlib.md5(blob).hexdigest(),
        expected_views={"outdoor": 8, "indoors": 7},
        expected_scans={"outdoor": 1, "indoors": 1},
    )
    build(cfg)
    verify(cfg)
    rows = [json.loads(line) for line in cfg.index_path.read_text().splitlines()]
    chosen = sorted(r["view_id"] for r in rows)
    print("selftest selected:", chosen)
    # independent check of the overlap model: same pitch, 60 deg apart -> disjoint; 10 deg -> overlapping
    assert shared_rays(0, 0, 60, 0) == 0, shared_rays(0, 0, 60, 0)
    assert shared_rays(0, 0, 10, 0) > MAX_SHARED_RAYS
    assert shared_rays(0, 0, 0, 50) == 0
    # corruption must be caught: flip one byte of one sample
    victim = cfg.data_root / rows[0]["sample_path"]
    raw = bytearray(victim.read_bytes())
    raw[1000] ^= 0x01
    victim.write_bytes(bytes(raw))
    try:
        verify(cfg)
    except SystemExit as exc:
        print("selftest corruption detected:", str(exc)[:120])
    else:
        fail("selftest: verify accepted a corrupted sample")
    # md5 pin must be enforced
    bad = Config(data_root=data_root, archive=archive, archive_bytes=len(blob), archive_md5="0" * 32,
                 expected_views=cfg.expected_views, expected_scans=cfg.expected_scans)
    try:
        scan_inventory(bad)
    except SystemExit as exc:
        print("selftest md5 mismatch detected:", str(exc)[:120])
    else:
        fail("selftest: inventory accepted a wrong MD5")
    print("selftest ok")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("build", "verify"):
        p = sub.add_parser(name)
        p.add_argument("--data-root", type=Path, required=True)
        p.add_argument("--manifest", type=Path)
    p = sub.add_parser("predict")
    p.add_argument("--data-list", type=Path, required=True)
    p = sub.add_parser("selftest")
    p.add_argument("--workdir", type=Path, required=True)
    args = parser.parse_args()
    if args.command in ("build", "verify"):
        data_root = args.data_root.resolve()
        cfg = Config(
            data_root=data_root,
            archive=data_root / "downloads" / DATASET_ID / ARCHIVE_NAME,
            manifest=args.manifest,
        )
        (build if args.command == "build" else verify)(cfg)
    elif args.command == "predict":
        predict(args.data_list)
    else:
        selftest(args.workdir.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
