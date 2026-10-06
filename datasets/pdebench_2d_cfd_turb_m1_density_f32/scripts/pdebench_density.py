#!/usr/bin/env python3
"""PDEBench 2D CFD Turb M1.0 density trajectories: download checks and build.

Subcommands (all local-only; network I/O stays in download.sh/curl):
  catalog FILE                      validate the DaRUS dataset JSON (license, file identity)
  range-headers HDR START END       validate the final HTTP response of one Range fetch
  metadata PREFIX ISLAND            validate the pinned HDF5 metadata ranges and /density layout
  trajectory PATH INDEX             validate one fetched trajectory (size, values, pinned hash)
  build                             emit samples, index and ingest statistics
"""

from __future__ import annotations

import argparse
import array
import hashlib
import json
import math
from pathlib import Path
import re
import shutil
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pdebench_h5 as h5  # noqa: E402

DATASET_ID = "pdebench_2d_cfd_turb_m1_density_f32"
SERIES_ID = "cfd_turb_m1_density_trajectory_f32"
NATURAL_RECORD_KIND = "pdebench_2d_cfd_turb_m1_simulation_trajectory_density_field"

DOI = "doi:10.18419/darus-2986"
PERSISTENT_URL = "https://doi.org/10.18419/DARUS-2986"
VERSION = (8, 0)
FILE_ID = 164686
FILE_NAME = "2D_CFD_Turb_M1.0_Eta1e-08_Zeta1e-08_periodic_512_Train.hdf5"
FILE_DIRECTORY = "2D/CFD/2D_Train_Turb"
FILE_SIZE = 88_080_392_528
FILE_MD5 = "3f2c7376cde5fb072db0f9814f1c6992"
S3_ETAG = "c094ed9959bb5a60411550403524df31-10000"

SOURCE_SHAPE = (1000, 21, 512, 512)
DENSITY_ADDRESS = 2048
FRAMES = SOURCE_SHAPE[1]
FRAME_VALUES = SOURCE_SHAPE[2] * SOURCE_SHAPE[3]
TRAJ_VALUES = FRAMES * FRAME_VALUES
TRAJ_BYTES = TRAJ_VALUES * 4
SELECTED = tuple(range(0, SOURCE_SHAPE[0], 25))
MIN_DISTINCT_PER_FRAME = 10_000

EXPECTED_ROOT = {"Vx", "Vy", "density", "pressure", "t-coordinate", "x-coordinate", "y-coordinate"}
METADATA_RANGES = (
    # (name, first byte, last byte, sha256)
    ("hdf5_prefix", 0, 2047, "4b901a23ac2c49174a8726031b60eba8953127bc29c0a1bf7438fde63b0e8b09"),
    ("hdf5_island", 66_060_290_048, 66_060_292_095, "ac53bc506b485b7de64f97a6e1740ad2e934480dee9c5e9e1d102b98526b99ba"),
)


def traj_range(index: int) -> tuple[int, int]:
    start = DENSITY_ADDRESS + index * TRAJ_BYTES
    return start, start + TRAJ_BYTES - 1


def traj_name(index: int) -> str:
    return f"density_traj_{index:04d}.f32"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while block := handle.read(8 * 1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def load_pins(path: Path | None) -> dict[int, str]:
    if path is None or not path.is_file():
        return {}
    pins: dict[int, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.startswith("#") or line.startswith("trajectory_index"):
            continue
        index, start, end, digest = line.split("\t")
        if (int(start), int(end)) != traj_range(int(index)):
            raise ValueError(f"pin file byte range mismatch for trajectory {index}")
        pins[int(index)] = digest
    if set(pins) != set(SELECTED):
        raise ValueError(f"pin file covers {sorted(pins)} instead of the selected trajectories")
    return pins


# ---------------------------------------------------------------- catalog


def cmd_catalog(args: argparse.Namespace) -> None:
    record = json.loads(Path(args.path).read_text(encoding="utf-8"))
    if record.get("status") != "OK":
        raise ValueError(f"DaRUS API status {record.get('status')!r}")
    data = record["data"]
    if str(data.get("persistentUrl", "")).lower() != PERSISTENT_URL.lower():
        raise ValueError(f"unexpected persistent URL {data.get('persistentUrl')!r}")
    latest = data["latestVersion"]
    if latest.get("versionState") != "RELEASED":
        raise ValueError(f"latest version is not released: {latest.get('versionState')!r}")
    version = (latest.get("versionNumber"), latest.get("versionMinorNumber"))
    if version != VERSION:
        print(f"WARNING: DaRUS dataset version changed from {VERSION} to {version}; file identity is checked below")
    license_info = latest.get("license") or {}
    if license_info.get("name") != "CC BY 4.0" or "creativecommons.org/licenses/by/4.0" not in str(license_info.get("uri", "")):
        raise ValueError(f"dataset license changed: {license_info!r}")
    if str(latest.get("termsOfUse") or "").strip() or str(latest.get("termsOfAccess") or "").strip():
        raise ValueError("dataset now carries additional terms of use/access")
    matches = [f for f in latest.get("files", []) if f.get("dataFile", {}).get("id") == FILE_ID]
    if len(matches) != 1:
        raise ValueError(f"file id {FILE_ID} not listed exactly once")
    entry = matches[0]
    datafile = entry["dataFile"]
    identity = (
        datafile.get("filename"),
        datafile.get("filesize"),
        (datafile.get("checksum") or {}).get("value"),
        entry.get("directoryLabel"),
        bool(entry.get("restricted")),
    )
    expected = (FILE_NAME, FILE_SIZE, FILE_MD5, FILE_DIRECTORY, False)
    if identity != expected:
        raise ValueError(f"file identity changed: {identity} != {expected}")
    print(
        f"catalog=ok doi={DOI} version={version[0]}.{version[1]} license=CC-BY-4.0 "
        f"file_id={FILE_ID} name={FILE_NAME} size={FILE_SIZE} md5={FILE_MD5}"
    )


# ---------------------------------------------------------- range headers


def final_response(text: str) -> str:
    blocks = [b for b in re.split(r"(?=^HTTP/)", text, flags=re.MULTILINE) if b.strip()]
    if not blocks:
        raise ValueError("no HTTP response headers recorded")
    return blocks[-1]


def cmd_range_headers(args: argparse.Namespace) -> None:
    final = final_response(Path(args.headers).read_text(encoding="iso-8859-1"))
    status = re.search(r"^HTTP/\S+\s+(\d+)", final, flags=re.MULTILINE)
    if not status or status.group(1) != "206":
        raise ValueError(f"expected HTTP 206, got {status.group(1) if status else 'none'}")
    rng = re.search(r"^content-range:\s*bytes\s+(\d+)-(\d+)/(\d+)\s*$", final, flags=re.IGNORECASE | re.MULTILINE)
    if not rng or tuple(map(int, rng.groups())) != (args.start, args.end, FILE_SIZE):
        raise ValueError(f"unexpected Content-Range {rng.groups() if rng else None}; wanted {args.start}-{args.end}/{FILE_SIZE}")
    ctype = re.search(r"^content-type:\s*(\S+)", final, flags=re.IGNORECASE | re.MULTILINE)
    if ctype and ctype.group(1).lower() not in {"application/x-hdf5", "application/octet-stream"}:
        raise ValueError(f"unexpected Content-Type {ctype.group(1)!r}")
    etag = re.search(r'^etag:\s*"?([^"\r\n]+)"?\s*$', final, flags=re.IGNORECASE | re.MULTILINE)
    seen = etag.group(1) if etag else None
    if seen != S3_ETAG:
        message = f"storage ETag {seen!r} != pinned {S3_ETAG!r}"
        if args.require_etag:
            raise ValueError(message + " (no trajectory SHA-256 pins available to prove identity)")
        print(f"WARNING: {message}; content SHA-256 pins remain authoritative")


# --------------------------------------------------------------- metadata


def parse_metadata(prefix: Path, island: Path) -> dict:
    segments = []
    for (name, first, last, digest), path in zip(METADATA_RANGES, (prefix, island)):
        payload = path.read_bytes()
        if len(payload) != last - first + 1:
            raise ValueError(f"{name}: expected {last - first + 1} bytes, got {len(payload)}")
        actual = hashlib.sha256(payload).hexdigest()
        if actual != digest:
            raise ValueError(f"{name}: SHA-256 {actual} != pinned {digest}")
        segments.append((first, payload))
    report = h5.describe(h5.Sparse(segments))
    h5.validate_density(
        report,
        file_size=FILE_SIZE,
        shape=SOURCE_SHAPE,
        address=DENSITY_ADDRESS,
        expected_root=EXPECTED_ROOT,
    )
    return report


def cmd_metadata(args: argparse.Namespace) -> None:
    report = parse_metadata(Path(args.prefix), Path(args.island))
    layout = report["datasets"]["density"]["layout"]
    print(
        f"hdf5_metadata=ok root={sorted(report['datasets'])} density_shape={list(SOURCE_SHAPE)} "
        f"dtype=H5T_IEEE_F32LE layout=contiguous address={layout['address']} size={layout['size']} filters=none"
    )


# ------------------------------------------------------------- trajectory


def trajectory_stats(payload: bytes) -> dict:
    """Validate one stored trajectory and return statistics from the stored float32."""
    if len(payload) != TRAJ_BYTES:
        raise ValueError(f"trajectory has {len(payload)} bytes, expected {TRAJ_BYTES}")
    values = array.array("f")
    values.frombytes(payload)
    if sys.byteorder != "little":
        values.byteswap()
    # Every |value| < 3.4e38 and there are 5.5e6 values, so the float64 sum is
    # finite exactly when every value is finite.
    if not math.isfinite(sum(values)):
        raise ValueError("trajectory contains NaN or infinite values")
    minimum = min(values)
    maximum = max(values)
    if not minimum > 0.0:
        raise ValueError(f"non-positive density {minimum}")
    frame0 = values[:FRAME_VALUES]
    distinct = []
    for frame in range(1, FRAMES):
        part = values[frame * FRAME_VALUES : (frame + 1) * FRAME_VALUES]
        count = len(set(part))
        if count < MIN_DISTINCT_PER_FRAME:
            raise ValueError(f"frame t={frame} is degenerate: {count} distinct values")
        distinct.append(count)
    return {
        "min": minimum,
        "max": maximum,
        "t0_min": min(frame0),
        "t0_max": max(frame0),
        "t0_uniform_one": min(frame0) == 1.0 and max(frame0) == 1.0,
        "min_distinct_per_frame_t_ge_1": min(distinct),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }


def cmd_trajectory(args: argparse.Namespace) -> None:
    if args.index not in SELECTED:
        raise ValueError(f"trajectory {args.index} is not in the pinned selection")
    stats = trajectory_stats(Path(args.path).read_bytes())
    pins = load_pins(Path(args.pins) if args.pins else None)
    if pins and pins[args.index] != stats["sha256"]:
        raise ValueError(f"trajectory {args.index} SHA-256 {stats['sha256']} != pinned {pins[args.index]}")
    start, end = traj_range(args.index)
    print(
        f"trajectory=ok index={args.index} bytes={start}-{end} sha256={stats['sha256']} "
        f"pinned={'yes' if pins else 'no'} min={stats['min']!r} max={stats['max']!r} "
        f"t0_uniform_one={stats['t0_uniform_one']} min_distinct_t_ge_1={stats['min_distinct_per_frame_t_ge_1']}"
    )
    if args.observed:
        with open(args.observed, "a", encoding="utf-8") as handle:
            handle.write(f"{args.index}\t{start}\t{end}\t{stats['sha256']}\n")


# ------------------------------------------------------------------ build


def index_row(data_root: Path, path: Path, index: int, stats: dict) -> dict:
    start, end = traj_range(index)
    return {
        "dataset_id": DATASET_ID,
        "series_id": SERIES_ID,
        "role": "primary",
        "sample_path": path.relative_to(data_root).as_posix(),
        "numeric_kind": "float",
        "bit_width": 32,
        "endianness": "little",
        "element_size_bytes": 4,
        "sample_size_bytes": TRAJ_BYTES,
        "value_count": TRAJ_VALUES,
        "shape": [FRAMES, SOURCE_SHAPE[2], SOURCE_SHAPE[3]],
        "sample_axes": ["time_step", "x", "y"],
        "natural_record_kind": NATURAL_RECORD_KIND,
        "source_file_id": FILE_ID,
        "source_dataset": "/density",
        "source_trajectory_index": index,
        "source_byte_start": start,
        "source_byte_end": end,
        "sample_sha256": stats["sha256"],
        "min": stats["min"],
        "max": stats["max"],
        "t0_uniform_one": stats["t0_uniform_one"],
        "min_distinct_per_frame_t_ge_1": stats["min_distinct_per_frame_t_ge_1"],
    }


def cmd_build(args: argparse.Namespace) -> None:
    data_root = Path(args.data_root).resolve()
    downloads = data_root / "downloads" / DATASET_ID
    samples_root = data_root / "samples" / DATASET_ID
    output_dir = samples_root / SERIES_ID
    temporary = samples_root / f".{SERIES_ID}.tmp"
    index_path = data_root / "index" / DATASET_ID / "samples.jsonl"
    stats_path = data_root / "filtered" / DATASET_ID / "ingest_stats.json"
    pins = load_pins(Path(args.pins) if args.pins else None)

    report = parse_metadata(downloads / "hdf5_prefix.bin", downloads / "hdf5_island.bin")
    print(f"hdf5_metadata=ok density_layout={report['datasets']['density']['layout']}")
    if temporary.exists():
        shutil.rmtree(temporary)
    temporary.mkdir(parents=True)
    rows = []
    aggregate = hashlib.sha256()
    try:
        for number, index in enumerate(SELECTED, 1):
            source = downloads / traj_name(index)
            payload = source.read_bytes()
            stats = trajectory_stats(payload)
            if pins and pins[index] != stats["sha256"]:
                raise ValueError(f"trajectory {index} SHA-256 {stats['sha256']} != pinned {pins[index]}")
            final = output_dir / traj_name(index)
            (temporary / final.name).write_bytes(payload)
            rows.append(index_row(data_root, final, index, stats))
            aggregate.update(payload)
            print(f"sample {number}/{len(SELECTED)} trajectory={index} min={stats['min']!r} max={stats['max']!r} "
                  f"t0_uniform_one={stats['t0_uniform_one']} min_distinct={stats['min_distinct_per_frame_t_ge_1']}", flush=True)
        if len({row["sample_sha256"] for row in rows}) != len(rows):
            raise ValueError("duplicate trajectory payloads")
        if output_dir.exists():
            shutil.rmtree(output_dir)
        temporary.replace(output_dir)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise

    index_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = index_path.with_suffix(".jsonl.tmp")
    with tmp.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n")
    tmp.replace(index_path)

    summary = {
        "dataset_id": DATASET_ID,
        "series_id": SERIES_ID,
        "source_file_id": FILE_ID,
        "source_file_name": FILE_NAME,
        "source_file_bytes": FILE_SIZE,
        "source_file_md5": FILE_MD5,
        "source_shape": list(SOURCE_SHAPE),
        "selected_trajectories": list(SELECTED),
        "sample_count": len(rows),
        "values_per_sample": TRAJ_VALUES,
        "sample_size_bytes": TRAJ_BYTES,
        "total_values": TRAJ_VALUES * len(rows),
        "total_size_bytes": TRAJ_BYTES * len(rows),
        "minimum": min(row["min"] for row in rows),
        "maximum": max(row["max"] for row in rows),
        "samples_with_uniform_one_t0_frame": sum(row["t0_uniform_one"] for row in rows),
        "min_distinct_per_frame_t_ge_1": min(row["min_distinct_per_frame_t_ge_1"] for row in rows),
        "aggregate_sha256": aggregate.hexdigest(),
        "trajectory_hashes_pinned": bool(pins),
    }
    stats_path.parent.mkdir(parents=True, exist_ok=True)
    stats_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2, sort_keys=True))


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("catalog")
    p.add_argument("path")
    p = sub.add_parser("range-headers")
    p.add_argument("headers")
    p.add_argument("start", type=int)
    p.add_argument("end", type=int)
    p.add_argument("--require-etag", action="store_true")
    p = sub.add_parser("metadata")
    p.add_argument("prefix")
    p.add_argument("island")
    p = sub.add_parser("trajectory")
    p.add_argument("path")
    p.add_argument("index", type=int)
    p.add_argument("--pins")
    p.add_argument("--observed")
    p = sub.add_parser("build")
    p.add_argument("--data-root", required=True)
    p.add_argument("--pins")
    p = sub.add_parser("selection")
    args = parser.parse_args()
    if args.command == "selection":
        for index in SELECTED:
            start, end = traj_range(index)
            print(f"{index}\t{start}\t{end}\t{traj_name(index)}")
        return 0
    {
        "catalog": cmd_catalog,
        "range-headers": cmd_range_headers,
        "metadata": cmd_metadata,
        "trajectory": cmd_trajectory,
        "build": cmd_build,
    }[args.command](args)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, KeyError, h5.H5Error) as exc:
        raise SystemExit(f"{DATASET_ID}: {exc}") from exc
