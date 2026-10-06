#!/usr/bin/env python3
"""FreeSurfer 'new curv' per-vertex thickness maps -> little-endian float32 samples.

Pure standard library. Subcommands:

  selftest         synthetic round-trip and rejection tests for both decoders
  check-downloads  semantic validation of downloaded objects (used by download.sh)
  build            emit one sample per hemisphere thickness file plus the index
  verify           independently re-derive every sample and the index

FreeSurfer new-curv layout (all big-endian):
  bytes 0..2   magic FF FF FF
  int32        nvertices
  int32        nfaces
  int32        values per vertex (must be 1)
  float32[n]   per-vertex values

Two independent decoders are used: build decodes with array('f') plus an
explicit byteswap; verify decodes with struct.unpack('>…f') and re-encodes with
struct.pack('<…f'), and recomputes every statistic from the decoded values.
"""

from __future__ import annotations

import argparse
from array import array
from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
import shutil
import statistics
import struct
import sys

DATASET_ID = "openneuro_ds003097_aomic_cortical_thickness_f32"
SERIES_ID = "aomic_cortical_thickness_f32"
KEY_PREFIX = "ds003097/derivatives/freesurfer/"
MAGIC = b"\xff\xff\xff"
HEADER_BYTES = 15
BUILD_STAMP = b"freesurfer-Linux-centos6_x86_64-stable-pub-v6.0.1-f53a55a\n"
FREESURFER_BUILD = BUILD_STAMP.decode("ascii").strip()
THICKNESS_MIN = 0.0
THICKNESS_MAX = 5.0
MIN_VERTICES = 50_000
MAX_VERTICES = 400_000
MAX_ZERO_FRACTION = 0.15
MAX_CLAMP_FRACTION = 0.05
MIN_DISTINCT_FRACTION = 0.25
EXPECTED_PARTICIPANTS = 200
EXPECTED_SAMPLES = 400
EXPECTED_VALUES = 56_920_347
EXPECTED_BYTES = 227_681_388
MIN_TOTAL_VALUES = 10_000
MIN_MEDIAN_VALUES = 1_000
MAX_PRIMARY_BYTES = 1_000_000_000
NATURAL_RECORD_KIND = "per-hemisphere surface vertex thickness map"
SOURCE_FORMAT = "FreeSurfer 6.0.1 new-curv binary (big-endian float32 per-vertex overlay)"
SOURCE_FIELD = "surf/{lh,rh}.thickness per-vertex cortical thickness (mm)"
SAMPLE_FORMAT = "raw homogeneous little-endian float32 per-vertex cortical thickness map"
SAMPLE_GEOMETRY = "surface_mesh_vertex_scalar_field"


@dataclass(frozen=True)
class Selection:
    kind: str
    subject: str
    key: str
    size: int
    md5: str

    @property
    def local_rel(self) -> str:
        if not self.key.startswith(KEY_PREFIX):
            raise ValueError(f"unexpected key prefix: {self.key}")
        return self.key[len(KEY_PREFIX):]

    @property
    def hemisphere(self) -> str:
        return {"thickness_lh": "lh", "thickness_rh": "rh"}[self.kind]


@dataclass(frozen=True)
class CurvMap:
    nvertices: int
    nfaces: int
    payload_le: bytes
    minimum: float
    maximum: float
    zero_count: int
    clamp_count: int
    distinct_count: int


def load_selection(path: Path) -> list[Selection]:
    rows = []
    lines = path.read_text(encoding="utf-8").splitlines()
    if not lines or lines[0] != "kind\tsubject\tkey\tbytes\tmd5":
        raise ValueError(f"{path}: unexpected header")
    for line in lines[1:]:
        if not line.strip():
            continue
        kind, subject, key, size, md5 = line.split("\t")
        if kind not in {"thickness_lh", "thickness_rh", "build_stamp"}:
            raise ValueError(f"{path}: unknown kind {kind}")
        rows.append(Selection(kind, subject, key, int(size), md5))
    return rows


def thickness_rows(selection: list[Selection]) -> list[Selection]:
    rows = [row for row in selection if row.kind != "build_stamp"]
    rows.sort(key=lambda row: (row.subject, row.hemisphere))
    return rows


def check_header(data: bytes, name: str) -> tuple[int, int]:
    if len(data) < HEADER_BYTES:
        raise ValueError(f"{name}: shorter than the 15-byte curv header")
    if data[:3] != MAGIC:
        raise ValueError(f"{name}: bad new-curv magic {data[:3].hex()}")
    nvertices, nfaces, per_vertex = struct.unpack_from(">iii", data, 3)
    if not MIN_VERTICES <= nvertices <= MAX_VERTICES:
        raise ValueError(f"{name}: implausible nvertices {nvertices}")
    if nfaces != 2 * nvertices - 4:
        raise ValueError(f"{name}: nfaces {nfaces} != 2*nvertices-4 ({2 * nvertices - 4})")
    if per_vertex != 1:
        raise ValueError(f"{name}: values-per-vertex {per_vertex} != 1")
    if len(data) != HEADER_BYTES + 4 * nvertices:
        raise ValueError(f"{name}: size {len(data)} != 15 + 4*{nvertices}")
    return nvertices, nfaces


def check_values(name: str, nvertices: int, minimum: float, maximum: float,
                 zero_count: int, clamp_count: int, distinct_count: int, bad: int) -> None:
    if bad:
        raise ValueError(f"{name}: {bad} non-finite or out-of-range [0,5] values")
    if minimum == maximum:
        raise ValueError(f"{name}: constant thickness map")
    if zero_count > MAX_ZERO_FRACTION * nvertices:
        raise ValueError(f"{name}: zero fraction {zero_count / nvertices:.4f} > {MAX_ZERO_FRACTION}")
    if clamp_count > MAX_CLAMP_FRACTION * nvertices:
        raise ValueError(f"{name}: 5 mm clamp fraction {clamp_count / nvertices:.4f} > {MAX_CLAMP_FRACTION}")
    if distinct_count < MIN_DISTINCT_FRACTION * nvertices:
        raise ValueError(f"{name}: only {distinct_count} distinct values for {nvertices} vertices")


def decode_build(data: bytes, name: str) -> CurvMap:
    """Build decoder: array('f') + byteswap."""
    nvertices, nfaces = check_header(data, name)
    values = array("f")
    if values.itemsize != 4:
        raise RuntimeError("platform float is not 4 bytes")
    values.frombytes(data[HEADER_BYTES:])
    if sys.byteorder == "little":
        values.byteswap()  # source is big-endian
    bad = 0
    zero_count = 0
    clamp_count = 0
    for value in values:
        if not (THICKNESS_MIN <= value <= THICKNESS_MAX):  # also rejects NaN
            bad += 1
        elif value == 0.0:
            zero_count += 1
        elif value == THICKNESS_MAX:
            clamp_count += 1
    finite = [value for value in values if THICKNESS_MIN <= value <= THICKNESS_MAX]
    minimum = min(finite) if finite else math.nan
    maximum = max(finite) if finite else math.nan
    distinct_count = len(set(values))
    check_values(name, nvertices, minimum, maximum, zero_count, clamp_count, distinct_count, bad)
    if sys.byteorder != "little":
        values.byteswap()
    return CurvMap(nvertices, nfaces, values.tobytes(), minimum, maximum,
                   zero_count, clamp_count, distinct_count)


def decode_verify(data: bytes, name: str) -> CurvMap:
    """Verify decoder: struct big-endian unpack, struct little-endian repack."""
    if data[:3] != MAGIC:
        raise ValueError(f"{name}: bad new-curv magic")
    nvertices = struct.unpack(">i", data[3:7])[0]
    nfaces = struct.unpack(">i", data[7:11])[0]
    per_vertex = struct.unpack(">i", data[11:15])[0]
    if per_vertex != 1 or nfaces != 2 * nvertices - 4:
        raise ValueError(f"{name}: inconsistent curv header")
    if not MIN_VERTICES <= nvertices <= MAX_VERTICES:
        raise ValueError(f"{name}: implausible nvertices {nvertices}")
    if len(data) - HEADER_BYTES != 4 * nvertices:
        raise ValueError(f"{name}: payload length mismatch")
    values = struct.unpack(f">{nvertices}f", data[HEADER_BYTES:])
    bad = sum(1 for v in values if not (math.isfinite(v) and 0.0 <= v <= 5.0))
    in_range = [v for v in values if math.isfinite(v) and 0.0 <= v <= 5.0]
    minimum = min(in_range) if in_range else math.nan
    maximum = max(in_range) if in_range else math.nan
    zero_count = values.count(0.0)
    clamp_count = values.count(5.0)
    distinct_count = len(set(values))
    check_values(name, nvertices, minimum, maximum, zero_count, clamp_count, distinct_count, bad)
    return CurvMap(nvertices, nfaces, struct.pack(f"<{nvertices}f", *values), minimum,
                   maximum, zero_count, clamp_count, distinct_count)


def check_stamp(path: Path) -> None:
    if path.read_bytes() != BUILD_STAMP:
        raise ValueError(f"{path}: build stamp is not {FREESURFER_BUILD}")


def check_object(path: Path, row: Selection) -> bytes:
    data = path.read_bytes()
    if len(data) != row.size:
        raise ValueError(f"{path}: size {len(data)} != pinned {row.size}")
    digest = hashlib.md5(data).hexdigest()
    if digest != row.md5:
        raise ValueError(f"{path}: md5 {digest} != pinned {row.md5}")
    return data


# --------------------------------------------------------------------------- selftest

def synth_curv(values: list[float], nvertices: int | None = None, nfaces: int | None = None,
               per_vertex: int = 1, magic: bytes = MAGIC) -> bytes:
    n = len(values) if nvertices is None else nvertices
    f = 2 * n - 4 if nfaces is None else nfaces
    return magic + struct.pack(">iii", n, f, per_vertex) + struct.pack(f">{len(values)}f", *values)


def selftest() -> None:
    n = MIN_VERTICES + 17
    values = [((i * 7919) % 49999) / 49999.0 * 4.9 + 0.05 for i in range(n)]
    values[0] = 0.0
    values[1] = 0.0
    values[2] = 5.0
    values[3] = 0.30000001192092896
    values = [struct.unpack(">f", struct.pack(">f", v))[0] for v in values]  # f32-exact
    good = synth_curv(values)
    expected = struct.pack(f"<{n}f", *values)
    for decoder in (decode_build, decode_verify):
        got = decoder(good, "synthetic")
        assert got.payload_le == expected, decoder.__name__
        assert got.nvertices == n and got.nfaces == 2 * n - 4
        assert got.zero_count == 2 and got.clamp_count == 1, (got.zero_count, got.clamp_count)
        assert got.minimum == 0.0 and got.maximum == 5.0
        assert got.distinct_count == len(set(values))
    # explicit byte-level check for one value: 1.5f BE = 3F C0 00 00, LE = 00 00 C0 3F
    one = list(values)
    one[10] = 1.5
    got = decode_build(synth_curv(one), "synthetic")
    assert got.payload_le[40:44] == b"\x00\x00\xc0\x3f"
    bad_cases = {
        "magic": synth_curv(values, magic=b"\xff\xff\xfe"),
        "nfaces": synth_curv(values, nfaces=2 * n - 3),
        "per_vertex": synth_curv(values, per_vertex=3),
        "truncated": synth_curv(values)[:-4],
        "trailing": synth_curv(values) + b"\x00\x00\x00\x00",
        "nan": synth_curv([math.nan] + values[1:]),
        "negative": synth_curv([-0.5] + values[1:]),
        "over_clamp": synth_curv([5.5] + values[1:]),
        "constant": synth_curv([2.5] * n),
        "mostly_zero": synth_curv([0.0] * (n // 2) + values[n // 2:]),
        "too_small": synth_curv(values[:1000]),
    }
    for label, blob in bad_cases.items():
        for decoder in (decode_build, decode_verify):
            try:
                decoder(blob, label)
            except ValueError:
                continue
            raise AssertionError(f"{decoder.__name__} accepted bad case {label}")
    print(f"selftest ok: synthetic n={n}, {len(bad_cases)} rejection cases x 2 decoders")


# --------------------------------------------------------------------------- commands

def check_downloads(selection_path: Path, download_dir: Path) -> None:
    selection = load_selection(selection_path)
    stamps = 0
    maps = 0
    for row in selection:
        path = download_dir / "freesurfer" / row.local_rel
        data = check_object(path, row)
        if row.kind == "build_stamp":
            check_stamp(path)
            stamps += 1
        else:
            check_header(data, str(path))
            decode_build(data, str(path))
            maps += 1
    print(f"download_semantic_check=ok thickness_maps={maps} build_stamps={stamps}")


def sample_name(row: Selection, nvertices: int) -> str:
    return f"{row.subject}_{row.hemisphere}_thickness_n{nvertices}.bin"


def index_row(row: Selection, curv: CurvMap, sample_rel: str) -> dict:
    return {
        "dataset_id": DATASET_ID,
        "series_id": SERIES_ID,
        "role": "primary",
        "sample_path": sample_rel,
        "numeric_kind": "float",
        "bit_width": 32,
        "endianness": "little",
        "element_size_bytes": 4,
        "sample_size_bytes": len(curv.payload_le),
        "value_count": curv.nvertices,
        "sample_format": SAMPLE_FORMAT,
        "sample_geometry": SAMPLE_GEOMETRY,
        "sample_rank": 1,
        "sample_shape": [curv.nvertices],
        "sample_axes": ["surface_vertex"],
        "natural_record_kind": NATURAL_RECORD_KIND,
        "source_sample": row.key,
        "source_md5": row.md5,
        "source_bytes": row.size,
        "source_format": SOURCE_FORMAT,
        "source_field": SOURCE_FIELD,
        "source_endianness": "big",
        "source_nfaces": curv.nfaces,
        "participant": row.subject,
        "hemisphere": row.hemisphere,
        "freesurfer_build": FREESURFER_BUILD,
        "unit": "mm",
        "min": curv.minimum,
        "max": curv.maximum,
        "zero_count": curv.zero_count,
        "clamp_5mm_count": curv.clamp_count,
        "distinct_count": curv.distinct_count,
    }


def check_floors(counts: list[int], total_bytes: int) -> float:
    median_values = statistics.median(counts)
    if sum(counts) < MIN_TOTAL_VALUES or median_values < MIN_MEDIAN_VALUES:
        raise ValueError("acceptance floor failed")
    if total_bytes > MAX_PRIMARY_BYTES:
        raise ValueError(f"primary output exceeds cap: {total_bytes}")
    if len(counts) != EXPECTED_SAMPLES or sum(counts) != EXPECTED_VALUES or total_bytes != EXPECTED_BYTES:
        raise ValueError(
            f"realized scope mismatch samples={len(counts)} values={sum(counts)} bytes={total_bytes} "
            f"expected {EXPECTED_SAMPLES}/{EXPECTED_VALUES}/{EXPECTED_BYTES}"
        )
    return median_values


def build(selection_path: Path, download_dir: Path, data_root: Path, samples_dir: Path,
          index_path: Path, stats_path: Path) -> None:
    selection = load_selection(selection_path)
    subjects = sorted({row.subject for row in selection})
    if len(subjects) != EXPECTED_PARTICIPANTS:
        raise ValueError(f"expected {EXPECTED_PARTICIPANTS} participants, found {len(subjects)}")
    stamps = {row.subject for row in selection if row.kind == "build_stamp"}
    if stamps != set(subjects):
        raise ValueError("every selected participant needs a pinned build stamp")
    for row in selection:
        if row.kind == "build_stamp":
            path = download_dir / "freesurfer" / row.local_rel
            check_object(path, row)
            check_stamp(path)

    if samples_dir.exists():
        shutil.rmtree(samples_dir)
    output_dir = samples_dir / SERIES_ID
    output_dir.mkdir(parents=True)
    index_path.parent.mkdir(parents=True, exist_ok=True)
    stats_path.parent.mkdir(parents=True, exist_ok=True)

    rows = []
    for row in thickness_rows(selection):
        path = download_dir / "freesurfer" / row.local_rel
        data = check_object(path, row)
        curv = decode_build(data, str(path))
        output = output_dir / sample_name(row, curv.nvertices)
        output.write_bytes(curv.payload_le)
        rows.append(index_row(row, curv, output.relative_to(data_root).as_posix()))

    counts = [r["value_count"] for r in rows]
    total_bytes = sum(r["sample_size_bytes"] for r in rows)
    median_values = check_floors(counts, total_bytes)
    with index_path.open("w", encoding="utf-8") as handle:
        for r in rows:
            handle.write(json.dumps(r, sort_keys=True) + "\n")
    zeros = sum(r["zero_count"] for r in rows)
    clamps = sum(r["clamp_5mm_count"] for r in rows)
    stats = {
        "dataset_id": DATASET_ID,
        "participants": len(subjects),
        "sample_count": len(rows),
        "primary_values": sum(counts),
        "primary_bytes": total_bytes,
        "median_value_count": median_values,
        "min_value_count": min(counts),
        "max_value_count": max(counts),
        "zero_values": zeros,
        "zero_fraction": zeros / sum(counts),
        "clamp_5mm_values": clamps,
        "clamp_5mm_fraction": clamps / sum(counts),
        "freesurfer_build": FREESURFER_BUILD,
        "global_min": min(r["min"] for r in rows),
        "global_max": max(r["max"] for r in rows),
    }
    stats_path.write_text(json.dumps(stats, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(stats, indent=2, sort_keys=True))


def verify(selection_path: Path, download_dir: Path, data_root: Path, index_path: Path) -> None:
    selection = load_selection(selection_path)
    expected = thickness_rows(selection)
    index = [json.loads(line) for line in index_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if [r.get("source_sample") for r in index] != [row.key for row in expected]:
        raise ValueError("index source set/order differs from pinned selection")
    for row in selection:
        if row.kind == "build_stamp":
            path = download_dir / "freesurfer" / row.local_rel
            if path.read_bytes() != BUILD_STAMP or hashlib.md5(path.read_bytes()).hexdigest() != row.md5:
                raise ValueError(f"{path}: build stamp mismatch")
    counts = []
    total_bytes = 0
    seen_hashes = set()
    sample_files = set()
    for r, row in zip(index, expected, strict=True):
        if r.get("dataset_id") != DATASET_ID or r.get("series_id") != SERIES_ID or r.get("role") != "primary":
            raise ValueError("index identity mismatch")
        if (r.get("numeric_kind"), r.get("bit_width"), r.get("endianness"), r.get("element_size_bytes")) != ("float", 32, "little", 4):
            raise ValueError("index dtype mismatch")
        if r.get("participant") != row.subject or r.get("hemisphere") != row.hemisphere:
            raise ValueError(f"{row.key}: participant/hemisphere mismatch")
        source = (download_dir / "freesurfer" / row.local_rel).read_bytes()
        if len(source) != row.size or hashlib.md5(source).hexdigest() != row.md5:
            raise ValueError(f"{row.key}: source size/md5 mismatch")
        curv = decode_verify(source, row.key)
        sample_path = data_root / r["sample_path"]
        actual = sample_path.read_bytes()
        if actual != curv.payload_le:
            raise ValueError(f"{sample_path}: sample bytes differ from independently decoded source")
        # statistics recomputed from the STORED little-endian float32 sample
        stored = struct.unpack(f"<{len(actual) // 4}f", actual)
        if len(stored) != curv.nvertices or r["value_count"] != curv.nvertices:
            raise ValueError(f"{sample_path}: value-count mismatch")
        if r["sample_size_bytes"] != len(actual) or r["sample_shape"] != [curv.nvertices]:
            raise ValueError(f"{sample_path}: size/shape mismatch")
        if r["source_nfaces"] != curv.nfaces:
            raise ValueError(f"{sample_path}: nfaces mismatch")
        if float(r["min"]) != min(stored) or float(r["max"]) != max(stored):
            raise ValueError(f"{sample_path}: min/max mismatch")
        if r["zero_count"] != stored.count(0.0) or r["clamp_5mm_count"] != stored.count(5.0):
            raise ValueError(f"{sample_path}: zero/clamp count mismatch")
        if r["distinct_count"] != len(set(stored)):
            raise ValueError(f"{sample_path}: distinct-count mismatch")
        digest = hashlib.sha256(actual).hexdigest()
        if digest in seen_hashes:
            raise ValueError(f"{sample_path}: duplicate sample payload")
        seen_hashes.add(digest)
        sample_files.add(sample_path.resolve())
        counts.append(len(stored))
        total_bytes += len(actual)
    on_disk = {p.resolve() for p in (data_root / "samples" / DATASET_ID).rglob("*") if p.is_file()}
    if on_disk != sample_files:
        raise ValueError(f"sample directory has {len(on_disk)} files but index lists {len(sample_files)}")
    median_values = check_floors(counts, total_bytes)
    print(
        f"verified dataset={DATASET_ID} samples={len(counts)} participants={len({r['participant'] for r in index})} "
        f"total_values={sum(counts)} total_bytes={total_bytes} median={median_values}"
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("selftest")
    p = sub.add_parser("check-downloads")
    p.add_argument("--selection", required=True, type=Path)
    p.add_argument("--download-dir", required=True, type=Path)
    p = sub.add_parser("build")
    p.add_argument("--selection", required=True, type=Path)
    p.add_argument("--download-dir", required=True, type=Path)
    p.add_argument("--data-root", required=True, type=Path)
    p.add_argument("--samples-dir", required=True, type=Path)
    p.add_argument("--index", required=True, type=Path)
    p.add_argument("--stats", required=True, type=Path)
    p = sub.add_parser("verify")
    p.add_argument("--selection", required=True, type=Path)
    p.add_argument("--download-dir", required=True, type=Path)
    p.add_argument("--data-root", required=True, type=Path)
    p.add_argument("--index", required=True, type=Path)
    args = parser.parse_args()
    if args.command == "selftest":
        selftest()
    elif args.command == "check-downloads":
        check_downloads(args.selection, args.download_dir)
    elif args.command == "build":
        selftest()
        build(args.selection, args.download_dir, args.data_root, args.samples_dir, args.index, args.stats)
    else:
        selftest()
        verify(args.selection, args.download_dir, args.data_root, args.index)


if __name__ == "__main__":
    main()
