#!/usr/bin/env python3
"""Strict stdlib-only extractor for revised MD17 NPZ float64 tensors."""

from __future__ import annotations

import argparse
import ast
from dataclasses import dataclass
import json
import math
from pathlib import Path
import shutil
import statistics
import struct
import sys
import tarfile
from typing import BinaryIO, Iterator
import zipfile


DATASET_ID = "figshare_rmd17_trajectories_f64"
MOLECULES = ("aspirin", "benzene", "ethanol", "malonaldehyde", "toluene")
FIELDS = ("coordinates", "forces")
MIN_SAMPLE_VALUES = 1_000
MIN_TOTAL_VALUES = 10_000
MAX_PRIMARY_BYTES = 1_000_000_000
COPY_CHUNK = 8 * 1024 * 1024


@dataclass(frozen=True)
class NpzSource:
    molecule: str
    container: Path
    kind: str
    member: str | None


@dataclass(frozen=True)
class NpyInfo:
    member: str
    descr: str
    shape: tuple[int, ...]
    data_bytes: int


def molecule_from_name(name: str) -> str | None:
    basename = Path(name).name.lower()
    if not basename.endswith(".npz"):
        return None
    stem = basename.removesuffix(".npz")
    for prefix in ("rmd17_", "md17_"):
        if stem.startswith(prefix):
            stem = stem.removeprefix(prefix)
            break
    return stem if stem in MOLECULES else None


def discover(download_dir: Path) -> dict[str, NpzSource]:
    found: dict[str, NpzSource] = {}

    def add(source: NpzSource) -> None:
        if source.molecule in found:
            raise ValueError(
                f"duplicate NPZ for {source.molecule}: "
                f"{found[source.molecule]} and {source}"
            )
        found[source.molecule] = source

    for path in sorted(download_dir.iterdir() if download_dir.is_dir() else []):
        if not path.is_file():
            continue
        molecule = molecule_from_name(path.name)
        if molecule:
            add(NpzSource(molecule, path, "direct", None))
            continue
        lower = path.name.lower()
        if lower.endswith((".tar.bz2", ".tar.gz", ".tgz")):
            try:
                with tarfile.open(path, "r:*") as archive:
                    for member in archive.getmembers():
                        if not member.isfile():
                            continue
                        molecule = molecule_from_name(member.name)
                        if molecule:
                            add(NpzSource(molecule, path, "tar", member.name))
            except tarfile.TarError as exc:
                raise ValueError(f"invalid tar archive {path}") from exc
        elif lower.endswith(".zip"):
            try:
                with zipfile.ZipFile(path) as archive:
                    for member in archive.namelist():
                        molecule = molecule_from_name(member)
                        if molecule:
                            add(NpzSource(molecule, path, "zip", member))
            except zipfile.BadZipFile as exc:
                raise ValueError(f"invalid zip archive {path}") from exc
    missing = sorted(set(MOLECULES) - set(found))
    if missing:
        raise ValueError(f"missing configured molecule NPZ files: {missing}")
    return {molecule: found[molecule] for molecule in MOLECULES}


def inventory(download_dir: Path) -> None:
    sources = discover(download_dir)
    for molecule, source in sources.items():
        location = source.container.name
        if source.member:
            location += f"::{source.member}"
        print(f"molecule={molecule} source={location}")
    print(f"semantic_inventory=ok molecules={len(sources)}")


def extract_npz_sources(
    sources: dict[str, NpzSource], filtered_dir: Path
) -> dict[str, Path]:
    npz_dir = filtered_dir / "npz"
    if npz_dir.exists():
        shutil.rmtree(npz_dir)
    npz_dir.mkdir(parents=True)
    outputs = {
        molecule: npz_dir / f"rmd17_{molecule}.npz" for molecule in sources
    }
    for molecule, source in sources.items():
        if source.kind == "direct":
            shutil.copyfile(source.container, outputs[molecule])

    tar_groups: dict[Path, dict[str, str]] = {}
    zip_groups: dict[Path, dict[str, str]] = {}
    for molecule, source in sources.items():
        if source.kind == "tar":
            tar_groups.setdefault(source.container, {})[source.member or ""] = molecule
        elif source.kind == "zip":
            zip_groups.setdefault(source.container, {})[source.member or ""] = molecule
        elif source.kind != "direct":
            raise AssertionError(source.kind)

    # Stream each compressed tar exactly once. Reopening a 1 GB tar.bz2 for
    # every molecule would repeat the full bzip2 decompression five times.
    for container, wanted_members in tar_groups.items():
        remaining = dict(wanted_members)
        with tarfile.open(container, "r|*") as archive:
            for member in archive:
                molecule = remaining.get(member.name)
                if molecule is None or not member.isfile():
                    continue
                handle = archive.extractfile(member)
                if handle is None:
                    raise ValueError(f"cannot extract {member.name}")
                with outputs[molecule].open("wb") as target:
                    shutil.copyfileobj(handle, target, COPY_CHUNK)
                del remaining[member.name]
                if not remaining:
                    break
        if remaining:
            raise ValueError(f"archive {container} lacks members {sorted(remaining)}")

    for container, wanted_members in zip_groups.items():
        with zipfile.ZipFile(container) as archive:
            for member, molecule in wanted_members.items():
                with archive.open(member) as handle, outputs[molecule].open(
                    "wb"
                ) as target:
                    shutil.copyfileobj(handle, target, COPY_CHUNK)

    for molecule, output in outputs.items():
        if not output.is_file() or output.stat().st_size <= 0:
            raise ValueError(f"empty extracted NPZ for {molecule}")
    return outputs


def read_exact(handle: BinaryIO, size: int, context: str) -> bytes:
    data = handle.read(size)
    if len(data) != size:
        raise ValueError(f"truncated {context}: expected {size}, found {len(data)}")
    return data


def read_npy_header(handle: BinaryIO, member: str) -> tuple[str, tuple[int, ...]]:
    if read_exact(handle, 6, member) != b"\x93NUMPY":
        raise ValueError(f"{member}: invalid NPY magic")
    major, minor = read_exact(handle, 2, member)
    if major == 1:
        header_size = struct.unpack("<H", read_exact(handle, 2, member))[0]
    elif major in (2, 3):
        header_size = struct.unpack("<I", read_exact(handle, 4, member))[0]
    else:
        raise ValueError(f"{member}: unsupported NPY version {major}.{minor}")
    raw_header = read_exact(handle, header_size, member)
    try:
        header = ast.literal_eval(raw_header.decode("latin1").strip())
    except (SyntaxError, ValueError) as exc:
        raise ValueError(f"{member}: malformed NPY header") from exc
    if not isinstance(header, dict):
        raise ValueError(f"{member}: NPY header is not a dictionary")
    descr = header.get("descr")
    shape = header.get("shape")
    if header.get("fortran_order") is not False:
        raise ValueError(f"{member}: Fortran-order arrays are not accepted")
    if descr not in ("<f8", "=f8"):
        raise ValueError(f"{member}: expected little-endian float64, found {descr!r}")
    if descr == "=f8" and sys.byteorder != "little":
        raise ValueError(f"{member}: native-endian float64 is not little-endian")
    if (
        not isinstance(shape, tuple)
        or not shape
        or any(not isinstance(value, int) or value <= 0 for value in shape)
    ):
        raise ValueError(f"{member}: invalid NPY shape {shape!r}")
    return str(descr), shape


def field_member(archive: zipfile.ZipFile, field: str) -> str:
    candidates = ("coords.npy", "r.npy") if field == "coordinates" else (
        "forces.npy",
        "f.npy",
    )
    matches = [
        name
        for name in archive.namelist()
        if Path(name).name.lower() in candidates and not name.endswith("/")
    ]
    if len(matches) != 1:
        raise ValueError(
            f"NPZ expected one {field} array ({candidates}), found {matches}"
        )
    return matches[0]


def inspect_npz(path: Path) -> dict[str, NpyInfo]:
    try:
        archive = zipfile.ZipFile(path)
    except zipfile.BadZipFile as exc:
        raise ValueError(f"invalid NPZ {path}") from exc
    result = {}
    with archive:
        for field in FIELDS:
            member = field_member(archive, field)
            with archive.open(member) as handle:
                descr, shape = read_npy_header(handle, member)
            if len(shape) != 3 or shape[2] != 3:
                raise ValueError(
                    f"{path.name}:{member}: expected configuration×atom×3, found {shape}"
                )
            data_bytes = math.prod(shape) * 8
            result[field] = NpyInfo(member, descr, shape, data_bytes)
    if result["coordinates"].shape != result["forces"].shape:
        raise ValueError(
            f"{path.name}: coordinate/force shapes differ: "
            f"{result['coordinates'].shape} vs {result['forces'].shape}"
        )
    return result


def iter_npy_payload(path: Path, info: NpyInfo) -> Iterator[bytes]:
    with zipfile.ZipFile(path) as archive:
        with archive.open(info.member) as handle:
            descr, shape = read_npy_header(handle, info.member)
            if descr != info.descr or shape != info.shape:
                raise ValueError(f"{path.name}:{info.member}: header changed")
            remaining = info.data_bytes
            while remaining:
                chunk = handle.read(min(COPY_CHUNK, remaining))
                if not chunk:
                    raise ValueError(f"{path.name}:{info.member}: truncated data")
                if len(chunk) % 8:
                    raise ValueError(f"{path.name}:{info.member}: unaligned data")
                remaining -= len(chunk)
                yield chunk
            if handle.read(1):
                raise ValueError(f"{path.name}:{info.member}: trailing NPY data")


def copy_and_scan(path: Path, info: NpyInfo, output: Path) -> tuple[float, float]:
    minimum = math.inf
    maximum = -math.inf
    first = None
    nonconstant = False
    with output.open("wb") as target:
        for chunk in iter_npy_payload(path, info):
            for (value,) in struct.iter_unpack("<d", chunk):
                if not math.isfinite(value):
                    raise ValueError(f"{path.name}:{info.member}: non-finite value")
                minimum = min(minimum, value)
                maximum = max(maximum, value)
                if first is None:
                    first = value
                elif value != first:
                    nonconstant = True
            target.write(chunk)
    if not nonconstant:
        raise ValueError(f"{path.name}:{info.member}: constant tensor")
    if output.stat().st_size != info.data_bytes:
        raise ValueError(f"{output}: wrong output size")
    return minimum, maximum


def build(
    download_dir: Path,
    filtered_dir: Path,
    samples_dir: Path,
    index_path: Path,
    stats_path: Path,
) -> None:
    sources = discover(download_dir)
    npz_paths = extract_npz_sources(sources, filtered_dir)
    if samples_dir.exists():
        shutil.rmtree(samples_dir)
    samples_dir.mkdir(parents=True)
    index_path.parent.mkdir(parents=True, exist_ok=True)

    rows = []
    records = []
    for molecule in MOLECULES:
        npz_path = npz_paths[molecule]
        infos = inspect_npz(npz_path)
        for field in FIELDS:
            info = infos[field]
            series_id = (
                "rmd17_coordinates_f64"
                if field == "coordinates"
                else "rmd17_forces_f64"
            )
            output_dir = samples_dir / series_id
            output_dir.mkdir(exist_ok=True)
            value_count = math.prod(info.shape)
            output = output_dir / f"{molecule}_{field}_f64_n{value_count:09d}.bin"
            minimum, maximum = copy_and_scan(npz_path, info, output)
            rows.append(
                {
                    "dataset_id": DATASET_ID,
                    "series_id": series_id,
                    "role": "primary",
                    "sample_path": output.relative_to(samples_dir.parents[1]).as_posix(),
                    "numeric_kind": "float",
                    "bit_width": 64,
                    "endianness": "little",
                    "element_size_bytes": 8,
                    "sample_size_bytes": info.data_bytes,
                    "value_count": value_count,
                    "sample_format": f"raw row-major float64 molecular {field} tensor",
                    "sample_geometry": "molecular_trajectory_tensor",
                    "sample_rank": 3,
                    "sample_shape": list(info.shape),
                    "sample_axes": ["configuration", "atom", "xyz_component"],
                    "natural_record_kind": f"rmd17_molecule_{field}_trajectory",
                    "source_field": info.member.removesuffix(".npy"),
                    "source_sample": npz_path.name,
                    "source_container": sources[molecule].container.name,
                    "molecule": molecule,
                    "min": minimum,
                    "max": maximum,
                }
            )
        records.append(
            {
                "molecule": molecule,
                "npz_file": npz_path.name,
                "shape": list(infos["coordinates"].shape),
                "coordinate_bytes": infos["coordinates"].data_bytes,
                "force_bytes": infos["forces"].data_bytes,
            }
        )

    counts = [int(row["value_count"]) for row in rows]
    total_values = sum(counts)
    total_bytes = sum(int(row["sample_size_bytes"]) for row in rows)
    median_values = statistics.median(counts)
    if total_values < MIN_TOTAL_VALUES:
        raise ValueError(f"total values below floor: {total_values}")
    if median_values < MIN_SAMPLE_VALUES:
        raise ValueError(f"median sample below floor: {median_values}")
    if total_bytes > MAX_PRIMARY_BYTES:
        raise ValueError(f"primary output exceeds cap: {total_bytes}")
    with index_path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")
    stats = {
        "dataset_id": DATASET_ID,
        "molecule_count": len(MOLECULES),
        "sample_count": len(rows),
        "primary_values": total_values,
        "primary_bytes": total_bytes,
        "median_value_count": median_values,
        "records": records,
    }
    stats_path.write_text(json.dumps(stats, indent=2, sort_keys=True) + "\n")
    print(
        f"built molecules={len(MOLECULES)} samples={len(rows)} "
        f"primary_values={total_values} primary_bytes={total_bytes} "
        f"median={median_values:g}"
    )


def verify(filtered_dir: Path, index_path: Path, data_root: Path) -> None:
    npz_dir = filtered_dir / "npz"
    rows = [
        json.loads(line)
        for line in index_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if len(rows) != len(MOLECULES) * len(FIELDS):
        raise ValueError(f"expected 10 samples, found {len(rows)}")
    seen = set()
    counts = []
    total_bytes = 0
    for row in rows:
        if row.get("dataset_id") != DATASET_ID or row.get("role") != "primary":
            raise ValueError("invalid index identity or role")
        if row.get("numeric_kind") != "float" or row.get("bit_width") != 64:
            raise ValueError("indexed sample is not float64")
        molecule = row.get("molecule")
        if molecule not in MOLECULES:
            raise ValueError(f"unexpected molecule {molecule!r}")
        field = (
            "coordinates"
            if row.get("series_id") == "rmd17_coordinates_f64"
            else "forces"
            if row.get("series_id") == "rmd17_forces_f64"
            else None
        )
        key = (molecule, field)
        if field is None or key in seen:
            raise ValueError(f"unexpected or duplicate sample {key}")
        seen.add(key)
        npz_path = npz_dir / f"rmd17_{molecule}.npz"
        info = inspect_npz(npz_path)[field]
        if row.get("sample_shape") != list(info.shape) or row.get("sample_rank") != 3:
            raise ValueError(f"shape mismatch for {key}")
        sample = data_root / row["sample_path"]
        with sample.open("rb") as actual:
            for expected in iter_npy_payload(npz_path, info):
                if actual.read(len(expected)) != expected:
                    raise ValueError(f"source byte mismatch for {key}")
            if actual.read(1):
                raise ValueError(f"trailing output bytes for {key}")
        value_count = math.prod(info.shape)
        if row.get("value_count") != value_count or row.get(
            "sample_size_bytes"
        ) != info.data_bytes:
            raise ValueError(f"indexed size/count mismatch for {key}")
        counts.append(value_count)
        total_bytes += info.data_bytes
    if sum(counts) < MIN_TOTAL_VALUES or statistics.median(counts) < MIN_SAMPLE_VALUES:
        raise ValueError("acceptance floor failed")
    if total_bytes > MAX_PRIMARY_BYTES:
        raise ValueError("primary output cap failed")
    print(
        f"verified dataset={DATASET_ID} samples={len(rows)} "
        f"total_values={sum(counts)} total_bytes={total_bytes} "
        f"median={statistics.median(counts):g}"
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    inventory_parser = subparsers.add_parser("inventory")
    inventory_parser.add_argument("--download-dir", required=True, type=Path)
    build_parser = subparsers.add_parser("build")
    build_parser.add_argument("--download-dir", required=True, type=Path)
    build_parser.add_argument("--filtered-dir", required=True, type=Path)
    build_parser.add_argument("--samples-dir", required=True, type=Path)
    build_parser.add_argument("--index", required=True, type=Path)
    build_parser.add_argument("--stats", required=True, type=Path)
    verify_parser = subparsers.add_parser("verify")
    verify_parser.add_argument("--filtered-dir", required=True, type=Path)
    verify_parser.add_argument("--index", required=True, type=Path)
    verify_parser.add_argument("--data-root", required=True, type=Path)
    args = parser.parse_args()
    if args.command == "inventory":
        inventory(args.download_dir)
    elif args.command == "build":
        build(
            args.download_dir,
            args.filtered_dir,
            args.samples_dir,
            args.index,
            args.stats,
        )
    else:
        verify(args.filtered_dir, args.index, args.data_root)


if __name__ == "__main__":
    main()
