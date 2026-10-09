#!/usr/bin/env python3
"""OpenNeuro ds007738 resting-state CW-fNIRS raw intensity: plan, validate, build.

Subcommands (all local; the network is only touched by curl in download.sh):

  listing-next PAGE.xml        print the URL-encoded S3 continuation token, or nothing
  check-metadata               license / snapshot / listing checks against runs.tsv
  meta-plan                    resolve every run's HDF5 layout over cached 1 MiB blocks;
                               exit 3 after writing block_requests.tsv if blocks are missing,
                               else write layout.tsv and data_requests.tsv
  inventory                    validate the fetched dataTimeSeries ranges, write range_sha256.tsv
  build                        emit one little-endian float64 sample per resting run + index

The emitted quantity is /nirs/data1/dataTimeSeries of each SNIRF file: raw CW
intensity (every measurementList*/dataType must be 1), stored row-major as
time x 1134 channels, copied byte for byte.
"""

from __future__ import annotations

import argparse
import array
import hashlib
import json
import math
import struct
import sys
import urllib.parse
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import nwb_hdf5 as H  # noqa: E402
from scale_test import channel_scale_summary  # noqa: E402

DATASET_ID = "openneuro_ds007738_wholehead_cw_fnirs_intensity_f64"
SERIES_ID = "cw_fnirs_raw_intensity_f64"
BUCKET_URL = "https://s3.amazonaws.com/openneuro.org/"
S3_NS = "{http://s3.amazonaws.com/doc/2006-03-01/}"
META_BLOCK = 1 << 20
CHANNELS = 1134
N_SOURCES = 56
N_DETECTORS = 144
WAVELENGTHS = (760.0, 850.0)
FORMAT_VERSION = "1.0"
ML_FIELDS = ("sourceIndex", "detectorIndex", "wavelengthIndex", "dataType", "dataTypeIndex")
# SHA-256 of channel_table_text() for the probe layout shared by every run
# (verified on sub-01, sub-28 and sub-46 during authoring; enforced for all).
LAYOUT_SHA256 = "d8099a28416f150446e432cbe1363c73b9cca2abfdafe9e15f9fb1a8d3eaf987"
H5T_STD_U64LE = bytes.fromhex("10000000080000000000400000000000")
# The quiet NaN as stored by the upstream (numpy/h5py) export: sign bit set,
# bytes 00 00 00 00 00 00 f8 ff on disk.
CANONICAL_NAN = 0xFFF8000000000000
FLOOR = 1e-6
MIN_TIME_POINTS = 1000
MAX_NAN_FRACTION = 0.005
MIN_DISTINCT_FRACTION = 0.2
EXPECTED_RUNS = 24
LICENSE = "CC0"
DOI = "doi:10.18112/openneuro.ds007738.v1.0.0"
DATASET_NAME = "Whole-Head Cocktail Party fNIRS"


class LayoutError(ValueError):
    pass


# ----------------------------------------------------------------- helpers
def load_runs(recipe_dir: Path) -> list[dict[str, str]]:
    lines = (recipe_dir / "runs.tsv").read_text(encoding="utf-8").splitlines()
    header = lines[0].split("\t")
    runs = [dict(zip(header, line.split("\t"))) for line in lines[1:] if line.strip()]
    if len(runs) != EXPECTED_RUNS or len({r["subject"] for r in runs}) != EXPECTED_RUNS:
        raise SystemExit(f"runs.tsv must list {EXPECTED_RUNS} distinct subjects, found {len(runs)}")
    for run in runs:
        want = f"ds007738/{run['subject']}/nirs/{run['subject']}_task-resting_run-01_nirs.snirf"
        if run["s3_key"] != want:
            raise SystemExit(f"runs.tsv key {run['s3_key']!r} is not the resting run of {run['subject']}")
    return runs


def run_url(run: dict[str, str]) -> str:
    return BUCKET_URL + run["s3_key"]


def run_dir(download_dir: Path, run: dict[str, str]) -> Path:
    return download_dir / "runs" / run["subject"]


def data_path(download_dir: Path, run: dict[str, str]) -> Path:
    return run_dir(download_dir, run) / "dataTimeSeries.f64le"


def sample_name(run: dict[str, str]) -> str:
    return f"{run['subject']}_task-resting_run-01_dataTimeSeries.bin"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 22), b""):
            digest.update(block)
    return digest.hexdigest()


def write_tsv(path: Path, header: list[str], rows: list[list[object]]) -> None:
    text = "\t".join(header) + "\n" + "".join("\t".join(str(v) for v in row) + "\n" for row in rows)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def read_tsv(path: Path) -> list[dict[str, str]]:
    lines = path.read_text(encoding="utf-8").splitlines()
    header = lines[0].split("\t")
    return [dict(zip(header, line.split("\t"))) for line in lines[1:] if line.strip()]


def channel_table_text(rows: list[tuple[int, ...]]) -> str:
    out = ["channel\tsourceIndex\tdetectorIndex\twavelengthIndex\tdataType\tdataTypeIndex"]
    for number, row in enumerate(rows, 1):
        out.append("\t".join(str(v) for v in (number,) + tuple(row)))
    return "\n".join(out) + "\n"


# ---------------------------------------------------------------- layout
def _is_f64le(dtype: bytes) -> bool:
    return dtype[: len(H.H5T_IEEE_F64LE)] == H.H5T_IEEE_F64LE and not any(dtype[len(H.H5T_IEEE_F64LE):])


def _scalar_u64(f: H.H5File, address: int, what: str) -> int:
    info = f.dataset(address)
    dtype = bytes(info["datatype"])
    if info["shape"] != () or dtype[: len(H5T_STD_U64LE)] != H5T_STD_U64LE or any(dtype[len(H5T_STD_U64LE):]):
        raise LayoutError(f"{what}: expected scalar 64-bit integer, got shape={info['shape']} dtype={dtype.hex()}")
    if info["layout_class"] == 1:
        if int(info["contiguous_size"]) != 8:
            raise LayoutError(f"{what}: contiguous size {info['contiguous_size']} != 8")
        raw = f.read(int(info["contiguous_address"]), 8)
    elif info["layout_class"] == 0:
        raw = bytes(info["compact_data"])[:8]
    else:
        raise LayoutError(f"{what}: chunked scalar")
    return struct.unpack("<q", raw)[0]


def _f64_vector(f: H.H5File, address: int, length: int, what: str) -> tuple[float, ...]:
    info = f.dataset(address)
    if info["shape"] != (length,) or not _is_f64le(bytes(info["datatype"])) or info["layout_class"] != 1 \
            or info["filters"] or int(info["contiguous_size"]) != 8 * length:
        raise LayoutError(f"{what}: expected contiguous f64 vector of {length}")
    return struct.unpack(f"<{length}d", f.read(int(info["contiguous_address"]), 8 * length))


def read_layout(store, size: int) -> dict[str, object]:
    """Resolve /nirs/data1/dataTimeSeries and check the SNIRF measurement layout.

    Raises nwb_hdf5.MissingBlock when a needed metadata block is not cached and
    LayoutError/ValueError when the file is not the expected material.
    """
    f = H.H5File(store, expected_size=size)
    root = f.group_links(f.root_header)
    if set(root) != {"formatVersion", "nirs"}:
        raise LayoutError(f"unexpected root links {sorted(root)}")
    version = f.scalar_string(root["formatVersion"])
    if version != FORMAT_VERSION:
        raise LayoutError(f"SNIRF formatVersion {version!r} != {FORMAT_VERSION!r}")
    nirs = f.group_links(root["nirs"])
    data_groups = sorted(name for name in nirs if name.startswith("data"))
    if data_groups != ["data1"] or "probe" not in nirs:
        raise LayoutError(f"expected exactly /nirs/data1 and /nirs/probe, have {sorted(nirs)}")
    data1 = f.group_links(nirs["data1"])
    want = {"dataTimeSeries", "time"} | {f"measurementList{i}" for i in range(1, CHANNELS + 1)}
    if set(data1) != want:
        extra = sorted(set(data1) - want)[:5]
        missing = sorted(want - set(data1))[:5]
        raise LayoutError(f"/nirs/data1 links differ: extra={extra} missing={missing} count={len(data1)}")
    info = f.dataset(data1["dataTimeSeries"])
    shape = tuple(info["shape"])
    if not _is_f64le(bytes(info["datatype"])):
        raise LayoutError(f"dataTimeSeries datatype {bytes(info['datatype']).hex()} is not H5T_IEEE_F64LE")
    if info["filters"]:
        raise LayoutError(f"dataTimeSeries has filters {info['filters']}")
    if info["layout_class"] != 1:
        raise LayoutError(f"dataTimeSeries layout class {info['layout_class']} is not contiguous")
    if len(shape) != 2 or shape[1] != CHANNELS or shape[0] < MIN_TIME_POINTS:
        raise LayoutError(f"dataTimeSeries shape {shape} is not (T>={MIN_TIME_POINTS}, {CHANNELS})")
    time_points = int(shape[0])
    address = int(info["contiguous_address"])
    nbytes = int(info["contiguous_size"])
    if nbytes != time_points * CHANNELS * 8:
        raise LayoutError(f"contiguous size {nbytes} != {time_points}*{CHANNELS}*8")
    if address == H.UNDEFINED_ADDRESS or address < 96 or address + nbytes > size:
        raise LayoutError(f"dataTimeSeries range {address}+{nbytes} outside file of {size}")
    tinfo = f.dataset(data1["time"])
    if tuple(tinfo["shape"]) != (time_points,) or not _is_f64le(bytes(tinfo["datatype"])):
        raise LayoutError(f"time vector shape {tinfo['shape']} does not match {time_points} time points")
    rows = []
    for channel in range(1, CHANNELS + 1):
        ml = f.group_links(data1[f"measurementList{channel}"])
        missing = [name for name in ML_FIELDS if name not in ml]
        if missing:
            raise LayoutError(f"measurementList{channel} lacks {missing}")
        rows.append(tuple(_scalar_u64(f, ml[name], f"measurementList{channel}/{name}") for name in ML_FIELDS))
    bad_type = [n for n, row in enumerate(rows, 1) if row[3] != 1]
    if bad_type:
        raise LayoutError(f"measurementList dataType != 1 (raw CW amplitude) for channels {bad_type[:8]}")
    if any(not (1 <= r[0] <= N_SOURCES and 1 <= r[1] <= N_DETECTORS and r[2] in (1, 2)) for r in rows):
        raise LayoutError("source/detector/wavelength index outside 56 x 144 x 2")
    table = channel_table_text(rows)
    layout_sha = hashlib.sha256(table.encode()).hexdigest()
    if layout_sha != LAYOUT_SHA256:
        raise LayoutError(f"channel layout sha256 {layout_sha} != pinned {LAYOUT_SHA256} (channel order differs)")
    probe = f.group_links(nirs["probe"])
    wavelengths = _f64_vector(f, probe["wavelengths"], 2, "/nirs/probe/wavelengths")
    if wavelengths != WAVELENGTHS:
        raise LayoutError(f"wavelengths {wavelengths} != {WAVELENGTHS}")
    return {
        "data_address": address,
        "data_bytes": nbytes,
        "time_points": time_points,
        "channels": CHANNELS,
        "layout_sha256": layout_sha,
        "format_version": version,
    }


# --------------------------------------------------------------- payload
def payload_stats(raw: bytes, time_points: int, with_scale: bool = True) -> dict[str, object]:
    """Statistics and missing-value policy for one stored dataTimeSeries matrix.

    Policy: values are kept bit for bit. NaN is allowed only as the canonical
    stored quiet NaN 0xFFF8000000000000 and at most MAX_NAN_FRACTION of the values;
    +-Inf, any other NaN payload, a constant or low-distinct matrix are fatal.
    """
    count = time_points * CHANNELS
    if len(raw) != 8 * count:
        raise ValueError(f"payload has {len(raw)} bytes, expected {8 * count}")
    bits = array.array("Q")
    bits.frombytes(raw)
    values = array.array("d")
    values.frombytes(raw)
    if sys.byteorder != "little":
        bits.byteswap()
        values.byteswap()
    nan_count = zero_count = floor_count = below_floor = negative = f32_exact = 0
    finite_min = math.inf
    finite_max = -math.inf
    total = 0.0
    nan_rows = set()
    pack_f = struct.Struct("<f")
    for index, value in enumerate(values):
        if value != value:
            if bits[index] != CANONICAL_NAN:
                raise ValueError(f"non-canonical NaN payload {bits[index]:#018x} at value {index}")
            nan_count += 1
            nan_rows.add(index // CHANNELS)
            continue
        if value in (math.inf, -math.inf):
            raise ValueError(f"infinite value at value {index}")
        if value < finite_min:
            finite_min = value
        if value > finite_max:
            finite_max = value
        total += value
        if value == 0.0:
            zero_count += 1
        elif value == FLOOR:
            floor_count += 1
        elif value < 0.0:
            negative += 1
        elif value < FLOOR:
            below_floor += 1
        try:
            if pack_f.unpack(pack_f.pack(value))[0] == value:
                f32_exact += 1
        except OverflowError:
            pass
    if nan_count > MAX_NAN_FRACTION * count:
        raise ValueError(f"{nan_count} NaN values exceed {MAX_NAN_FRACTION:.1%} of {count}")
    finite = count - nan_count
    distinct = len(set(bits))
    if finite_min == finite_max:
        raise ValueError("constant matrix")
    if distinct < MIN_DISTINCT_FRACTION * count:
        raise ValueError(f"only {distinct} distinct values of {count}")
    stats: dict[str, object] = {
        "time_points": time_points,
        "channels": CHANNELS,
        "nan_count": nan_count,
        "nan_rows": sorted(nan_rows)[:16],
        "nan_row_count": len(nan_rows),
        "zero_count": zero_count,
        "floor_1e-6_count": floor_count,
        "positive_below_floor_count": below_floor,
        "negative_count": negative,
        "finite_count": finite,
        "finite_min": finite_min,
        "finite_max": finite_max,
        "finite_mean": total / finite,
        "distinct_count": distinct,
        "float32_exact_count": f32_exact,
    }
    if with_scale:
        stats.update(channel_scale_summary((values[c::CHANNELS] for c in range(CHANNELS)), FLOOR))
    return stats


# -------------------------------------------------------------- commands
def cmd_listing_next(args: argparse.Namespace) -> int:
    root = ET.fromstring(Path(args.page).read_bytes())
    truncated = root.findtext(f"{S3_NS}IsTruncated")
    token = root.findtext(f"{S3_NS}NextContinuationToken")
    if truncated == "true":
        if not token:
            raise SystemExit("truncated listing page without NextContinuationToken")
        print(urllib.parse.quote(token, safe=""))
    elif truncated != "false":
        raise SystemExit(f"listing page without IsTruncated: {args.page}")
    return 0


def parse_listing(meta_dir: Path) -> dict[str, tuple[int, str]]:
    keys: dict[str, tuple[int, str]] = {}
    pages = sorted(meta_dir.glob("listing_*.xml"))
    if not pages:
        raise SystemExit("no S3 listing pages")
    for page in pages:
        root = ET.fromstring(page.read_bytes())
        if root.findtext(f"{S3_NS}Prefix") != "ds007738/":
            raise SystemExit(f"{page.name}: wrong listing prefix")
        for item in root.findall(f"{S3_NS}Contents"):
            key = item.findtext(f"{S3_NS}Key")
            size = int(item.findtext(f"{S3_NS}Size"))
            etag = item.findtext(f"{S3_NS}ETag").strip('"')
            if key in keys:
                raise SystemExit(f"duplicate key {key} across listing pages")
            keys[key] = (size, etag)
    if root.findtext(f"{S3_NS}IsTruncated") != "false":
        raise SystemExit("last listing page is still truncated")
    return keys


def cmd_check_metadata(args: argparse.Namespace) -> int:
    download_dir, recipe_dir = Path(args.download_dir), Path(args.recipe_dir)
    meta = download_dir / "metadata"
    runs = load_runs(recipe_dir)
    desc = json.loads((meta / "dataset_description.json").read_text(encoding="utf-8"))
    if desc.get("License") != LICENSE or desc.get("DatasetDOI") != DOI or desc.get("Name") != DATASET_NAME:
        raise SystemExit(f"dataset_description.json mismatch: License={desc.get('License')!r} "
                         f"DOI={desc.get('DatasetDOI')!r} Name={desc.get('Name')!r}")
    changes = (meta / "CHANGES").read_text(encoding="utf-8")
    if not changes.startswith("1.0.0 2026-05-01"):
        raise SystemExit(f"CHANGES does not start with snapshot 1.0.0: {changes[:60]!r}")
    readme = (meta / "README.txt").read_text(encoding="utf-8")
    for needle in ("56 sources, 144 detectors, 1134 measurement channels", "resting:"):
        if needle not in readme:
            raise SystemExit(f"README.txt lacks {needle!r}")
    participants = set((meta / "participants.tsv").read_text(encoding="utf-8").split())
    keys = parse_listing(meta)
    resting = {k: v for k, v in keys.items() if k.endswith("_task-resting_run-01_nirs.snirf")}
    other_resting = [k for k in keys if "_task-resting_" in k and k.endswith(".snirf") and k not in resting]
    if other_resting:
        raise SystemExit(f"unexpected extra resting SNIRF runs {other_resting[:4]}")
    pinned = {r["s3_key"]: r for r in runs}
    if set(resting) != set(pinned):
        raise SystemExit(f"resting SNIRF set changed: new={sorted(set(resting) - set(pinned))} "
                         f"gone={sorted(set(pinned) - set(resting))}")
    for key, (size, etag) in sorted(resting.items()):
        run = pinned[key]
        if size != int(run["size_bytes"]) or etag != run["etag"]:
            raise SystemExit(f"{key}: listing size/etag {size}/{etag} != pinned {run['size_bytes']}/{run['etag']}")
        if run["subject"] not in participants:
            raise SystemExit(f"{run['subject']} not in participants.tsv")
    snirf = [v for k, v in keys.items() if k.endswith(".snirf")]
    print(f"metadata_ok license={LICENSE} doi={DOI} keys={len(keys)} snirf_runs={len(snirf)} "
          f"snirf_bytes={sum(s for s, _ in snirf)} resting_runs={len(resting)} "
          f"resting_file_bytes={sum(s for s, _ in resting.values())}")
    return 0


def check_pins(run: dict[str, str], layout: dict[str, object]) -> None:
    for column, key in (("data_address", "data_address"), ("data_bytes", "data_bytes"), ("time_points", "time_points")):
        if run[column] != "-" and int(run[column]) != int(layout[key]):
            raise SystemExit(f"{run['subject']}: {column} {layout[key]} != pinned {run[column]}")


def cmd_meta_plan(args: argparse.Namespace) -> int:
    download_dir, recipe_dir = Path(args.download_dir), Path(args.recipe_dir)
    runs = load_runs(recipe_dir)
    requests = []
    layouts = []
    for run in runs:
        size = int(run["size_bytes"])
        store = H.BlockStore(run_dir(download_dir, run) / "meta", size, META_BLOCK)
        try:
            layout = read_layout(store, size)
        except H.MissingBlock as missing:
            start, end = store.block_span(missing.index)
            requests.append([run["subject"], missing.index, start, end - 1, run_url(run), size, run["etag"]])
            continue
        check_pins(run, layout)
        layouts.append((run, layout, sorted(store.used)))
    write_tsv(download_dir / "block_requests.tsv",
              ["subject", "block", "start", "end", "url", "total", "etag"], requests)
    if requests:
        print(f"meta_plan missing_blocks={len(requests)} resolved_runs={len(layouts)}")
        return 3
    rows = []
    data_rows = []
    for run, layout, used in layouts:
        rows.append([run["subject"], layout["data_address"], layout["data_bytes"], layout["time_points"],
                     layout["channels"], layout["layout_sha256"], ",".join(str(b) for b in used)])
        start = int(layout["data_address"])
        data_rows.append([run["subject"], start, start + int(layout["data_bytes"]) - 1, run_url(run),
                          run["size_bytes"], run["etag"],
                          str(data_path(download_dir, run).relative_to(download_dir))])
        print(f"layout subject={run['subject']} address={layout['data_address']} shape=({layout['time_points']},"
              f"{layout['channels']}) bytes={layout['data_bytes']} meta_blocks={len(used)}")
    write_tsv(download_dir / "layout.tsv",
              ["subject", "data_address", "data_bytes", "time_points", "channels", "layout_sha256", "meta_blocks"], rows)
    write_tsv(download_dir / "data_requests.tsv",
              ["subject", "start", "end", "url", "total", "etag", "local_path"], data_rows)
    print(f"meta_plan_ok runs={len(rows)} data_bytes={sum(int(r[2]) for r in rows)}")
    return 0


def cmd_inventory(args: argparse.Namespace) -> int:
    download_dir, recipe_dir = Path(args.download_dir), Path(args.recipe_dir)
    runs = {r["subject"]: r for r in load_runs(recipe_dir)}
    layout = {row["subject"]: row for row in read_tsv(download_dir / "layout.tsv")}
    if set(layout) != set(runs):
        raise SystemExit("layout.tsv does not cover every run")
    out = []
    for subject, run in sorted(runs.items()):
        row = layout[subject]
        path = data_path(download_dir, run)
        size = path.stat().st_size if path.is_file() else -1
        if size != int(row["data_bytes"]):
            raise SystemExit(f"{subject}: data range has {size} bytes, expected {row['data_bytes']}")
        digest = sha256_file(path)
        if run["data_sha256"] != "-" and digest != run["data_sha256"]:
            path.unlink()
            raise SystemExit(f"{subject}: data sha256 {digest} != pinned {run['data_sha256']} (deleted; re-run)")
        try:
            stats = payload_stats(path.read_bytes(), int(row["time_points"]), with_scale=False)
        except ValueError as exc:
            path.unlink()
            raise SystemExit(f"{subject}: semantically invalid dataTimeSeries ({exc}); deleted, re-run download.sh")
        start = int(row["data_address"])
        out.append(["data", subject, "-", start, start + int(row["data_bytes"]) - 1, row["data_bytes"], digest])
        for block in row["meta_blocks"].split(","):
            blk = run_dir(download_dir, run) / "meta" / f"blk_{int(block):06d}.bin"
            b0 = int(block) * META_BLOCK
            out.append(["meta", subject, block, b0, b0 + blk.stat().st_size - 1, blk.stat().st_size, sha256_file(blk)])
        print(f"inventory subject={subject} bytes={size} sha256={digest} nan={stats['nan_count']} "
              f"floor={stats['floor_1e-6_count']} zero={stats['zero_count']}")
    write_tsv(download_dir / "range_sha256.tsv", ["kind", "subject", "block", "start", "end", "bytes", "sha256"], out)
    print(f"inventory_ok runs={len(runs)} ranges={len(out)}")
    return 0


def cmd_build(args: argparse.Namespace) -> int:
    data_root, recipe_dir = Path(args.data_root), Path(args.recipe_dir)
    download_dir = data_root / "downloads" / DATASET_ID
    sample_dir = data_root / "samples" / DATASET_ID / SERIES_ID
    index_dir = data_root / "index" / DATASET_ID
    filtered_dir = data_root / "filtered" / DATASET_ID
    runs = load_runs(recipe_dir)
    hashes = {(r["kind"], r["subject"], r["block"]): r for r in read_tsv(download_dir / "range_sha256.tsv")}
    sample_dir.mkdir(parents=True, exist_ok=True)
    index_dir.mkdir(parents=True, exist_ok=True)
    filtered_dir.mkdir(parents=True, exist_ok=True)
    expected_names = {sample_name(run) for run in runs}
    for stray in sample_dir.iterdir():
        if stray.name not in expected_names:
            stray.unlink()
            print(f"removed stray sample {stray.name}")
    rows = []
    totals = {"values": 0, "bytes": 0, "nan": 0, "zero": 0, "floor": 0, "below_floor": 0, "negative": 0, "f32": 0}
    for run in runs:
        subject = run["subject"]
        size = int(run["size_bytes"])
        store = H.BlockStore(run_dir(download_dir, run) / "meta", size, META_BLOCK)
        try:
            layout = read_layout(store, size)
        except H.MissingBlock as missing:
            raise SystemExit(f"{subject}: metadata block {missing.index} not cached; run download.sh")
        check_pins(run, layout)
        for block in sorted(store.used):
            pin = hashes.get(("meta", subject, str(block)))
            if pin is None or sha256_file(store.block_path(block)) != pin["sha256"]:
                raise SystemExit(f"{subject}: metadata block {block} differs from range_sha256.tsv")
        path = data_path(download_dir, run)
        raw = path.read_bytes()
        if len(raw) != int(layout["data_bytes"]):
            raise SystemExit(f"{subject}: data range size {len(raw)} != {layout['data_bytes']}")
        digest = hashlib.sha256(raw).hexdigest()
        pin = hashes.get(("data", subject, "-"))
        if pin is None or pin["sha256"] != digest or int(pin["start"]) != int(layout["data_address"]):
            raise SystemExit(f"{subject}: data range differs from range_sha256.tsv")
        if run["data_sha256"] != "-" and digest != run["data_sha256"]:
            raise SystemExit(f"{subject}: data sha256 {digest} != pinned {run['data_sha256']}")
        stats = payload_stats(raw, int(layout["time_points"]))
        out = sample_dir / sample_name(run)
        tmp = out.with_suffix(".tmp")
        tmp.write_bytes(raw)
        tmp.replace(out)
        count = len(raw) // 8
        row = {
            "dataset_id": DATASET_ID,
            "series_id": SERIES_ID,
            "sample_path": str(out.relative_to(data_root)),
            "numeric_kind": "float",
            "bit_width": 64,
            "endianness": "little",
            "element_size_bytes": 8,
            "sample_size_bytes": len(raw),
            "value_count": count,
            "subject": subject,
            "source_key": run["s3_key"],
            "source_etag": run["etag"],
            "source_offset": int(layout["data_address"]),
            "sample_shape": [int(layout["time_points"]), CHANNELS],
            "sample_order": "row-major (time, channel) as stored",
            "layout_sha256": layout["layout_sha256"],
            "sha256": digest,
        }
        row.update(stats)
        rows.append(row)
        totals["values"] += count
        totals["bytes"] += len(raw)
        totals["nan"] += stats["nan_count"]
        totals["zero"] += stats["zero_count"]
        totals["floor"] += stats["floor_1e-6_count"]
        totals["below_floor"] += stats["positive_below_floor_count"]
        totals["negative"] += stats["negative_count"]
        totals["f32"] += stats["float32_exact_count"]
        print(f"sample subject={subject} shape=({layout['time_points']},{CHANNELS}) bytes={len(raw)} "
              f"nan={stats['nan_count']} (rows {stats['nan_rows']}) zero={stats['zero_count']} "
              f"floor={stats['floor_1e-6_count']} negative={stats['negative_count']} "
              f"range=[{stats['finite_min']!r},{stats['finite_max']!r}] distinct={stats['distinct_count'] / count:.4f} "
              f"f32_exact={stats['float32_exact_count']} int24_like_channels={stats['scale_channels_int24_like']}/"
              f"{stats['scale_channels_tested']} lcm_bits_median={stats['scale_lcm_bits_median']}")
    index_path = index_dir / "samples.jsonl"
    tmp = index_path.with_suffix(".tmp")
    tmp.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in rows), encoding="utf-8")
    tmp.replace(index_path)
    aggregate = hashlib.sha256("".join(row["sha256"] for row in rows).encode()).hexdigest()
    summary = {"samples": len(rows), "aggregate_sha256": aggregate, **totals,
               "nan_share": totals["nan"] / totals["values"], "zero_share": totals["zero"] / totals["values"],
               "floor_share": totals["floor"] / totals["values"]}
    (filtered_dir / "ingest_stats.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n",
                                                    encoding="utf-8")
    print(f"build_ok samples={len(rows)} values={totals['values']} bytes={totals['bytes']} "
          f"nan_share={summary['nan_share']:.6f} zero_share={summary['zero_share']:.6f} "
          f"floor_share={summary['floor_share']:.6f} aggregate_sha256={aggregate}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("listing-next")
    p.add_argument("page")
    p.set_defaults(func=cmd_listing_next)
    for name, func in (("check-metadata", cmd_check_metadata), ("meta-plan", cmd_meta_plan),
                       ("inventory", cmd_inventory)):
        p = sub.add_parser(name)
        p.add_argument("--download-dir", required=True)
        p.add_argument("--recipe-dir", required=True)
        p.set_defaults(func=func)
    p = sub.add_parser("build")
    p.add_argument("--data-root", required=True)
    p.add_argument("--recipe-dir", required=True)
    p.set_defaults(func=cmd_build)
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
