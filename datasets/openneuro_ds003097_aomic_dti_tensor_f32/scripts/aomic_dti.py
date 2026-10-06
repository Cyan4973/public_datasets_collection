#!/usr/bin/env python3
"""Validate, extract and verify AOMIC-ID1000 WLS diffusion-tensor volumes.

Source: OpenNeuro ds003097 derivatives/dwipreproc, one NIfTI-1 gzip volume
per participant, sub-NNNN_model-DTI_desc-WLS_diffmodel.nii.gz, written by the
AOMIC pipeline from MRtrix3 dwi2tensor (weighted linear least squares, two
iterations). Shape (112, 112, 60, 6) float32, NIfTI order (i fastest, then j,
k, tensor component). Component order is the MRtrix3 convention
D11, D22, D33, D12, D13, D23 (Dxx, Dyy, Dzz, Dxy, Dxz, Dyz); every volume is
cross-checked against the companion published FA map (sub-NNNN_model-DTI_
desc-WLS_FA.nii.gz) by recomputing FA from the tensor invariants.

Subcommands:
  check-downloads  semantic validation of the downloaded objects
  build            emit one raw little-endian float32 sample per participant
  verify           independently re-derive and compare every sample
"""

from __future__ import annotations

import argparse
from array import array
import gzip
import hashlib
import json
import math
from pathlib import Path
import shutil
import statistics
import struct
import sys

DATASET_ID = "openneuro_ds003097_aomic_dti_tensor_f32"
SERIES_ID = "aomic_dti_wls_tensor_f32"
KEY_PREFIX = "ds003097/derivatives/dwipreproc/"
GRID = (112, 112, 60)
COMPONENTS = 6
VOXELS = GRID[0] * GRID[1] * GRID[2]
TENSOR_VALUES = VOXELS * COMPONENTS
HEADER_BYTES = 352
EXPECTED_SAMPLES = 32
COMPONENT_ORDER = ["Dxx", "Dyy", "Dzz", "Dxy", "Dxz", "Dyz"]
FA_TOLERANCE = 1e-5
MIN_BRAIN_VOXELS = 100_000
MIN_DIAGONAL_POSITIVE_FRACTION = 0.99
MD_MEDIAN_RANGE = (2e-4, 3e-3)  # mm^2/s, b = 1000 s/mm^2 brain tissue
MIN_TOTAL_VALUES = 10_000
MIN_MEDIAN_VALUES = 1_000
MAX_PRIMARY_BYTES = 1_000_000_000


class RecipeError(ValueError):
    pass


def read_selection(path: Path) -> list[dict[str, dict[str, object]]]:
    """Return per-subject dicts {kind: {key, bytes, md5}} sorted by subject."""
    lines = path.read_text(encoding="utf-8").splitlines()
    if not lines or lines[0].split("\t") != ["kind", "subject", "key", "bytes", "md5"]:
        raise RecipeError("selection.tsv header mismatch")
    subjects: dict[str, dict[str, dict[str, object]]] = {}
    for line in lines[1:]:
        if not line.strip():
            continue
        kind, subject, key, size, md5 = line.split("\t")
        if kind not in ("diffmodel", "FA"):
            raise RecipeError(f"unexpected selection kind {kind!r}")
        expected_key = f"{KEY_PREFIX}{subject}/dwi/{subject}_model-DTI_desc-WLS_{kind}.nii.gz"
        if key != expected_key:
            raise RecipeError(f"unexpected selection key {key!r}")
        entry = subjects.setdefault(subject, {})
        if kind in entry:
            raise RecipeError(f"duplicate selection row {subject} {kind}")
        entry[kind] = {"key": key, "bytes": int(size), "md5": md5}
    ordered = []
    for subject in sorted(subjects):
        entry = subjects[subject]
        if set(entry) != {"diffmodel", "FA"}:
            raise RecipeError(f"{subject}: selection needs both diffmodel and FA")
        ordered.append({"subject": subject, **entry})
    if len(ordered) != EXPECTED_SAMPLES:
        raise RecipeError(f"selection has {len(ordered)} subjects, expected {EXPECTED_SAMPLES}")
    return ordered


def local_path(download_dir: Path, key: str) -> Path:
    return download_dir / "dwipreproc" / key[len(KEY_PREFIX):]


def parse_nifti(path: Path, dims: tuple[int, ...]) -> tuple[bytes, dict]:
    """Decode a little-endian NIfTI-1 single-file float32 volume.

    Returns the canonical little-endian float32 payload and header facts.
    """
    try:
        data = gzip.decompress(path.read_bytes())
    except (OSError, EOFError, gzip.BadGzipFile) as exc:
        raise RecipeError(f"{path.name}: invalid gzip stream ({exc})") from exc
    if len(data) < HEADER_BYTES:
        raise RecipeError(f"{path.name}: decompressed file shorter than NIfTI header")
    if struct.unpack_from("<i", data, 0)[0] != 348:
        raise RecipeError(f"{path.name}: sizeof_hdr is not little-endian 348")
    if data[344:348] != b"n+1\0":
        raise RecipeError(f"{path.name}: expected single-file NIfTI-1 magic 'n+1'")
    dim = struct.unpack_from("<8h", data, 40)
    if tuple(dim[: len(dims)]) != dims or any(d not in (0, 1) for d in dim[len(dims):]):
        raise RecipeError(f"{path.name}: dim {dim} != expected {dims}")
    datatype, bitpix = struct.unpack_from("<2h", data, 70)
    if datatype != 16 or bitpix != 32:
        raise RecipeError(f"{path.name}: datatype={datatype} bitpix={bitpix}, expected 16/32")
    pixdim = struct.unpack_from("<8f", data, 76)
    if pixdim[1:4] != (2.0, 2.0, 2.0):
        raise RecipeError(f"{path.name}: voxel size {pixdim[1:4]} != 2 mm isotropic")
    vox_offset = struct.unpack_from("<f", data, 108)[0]
    if vox_offset != float(HEADER_BYTES):
        raise RecipeError(f"{path.name}: vox_offset {vox_offset} != 352")
    slope, inter = struct.unpack_from("<2f", data, 112)
    if slope not in (0.0, 1.0) or inter != 0.0:
        raise RecipeError(f"{path.name}: non-identity scaling slope={slope} inter={inter}")
    count = math.prod(dims[1:])
    payload = data[HEADER_BYTES:]
    if len(payload) != count * 4:
        raise RecipeError(f"{path.name}: payload {len(payload)} B != {count * 4} B")
    if sys.byteorder != "little":
        swapped = array("f")
        swapped.frombytes(payload)
        swapped.byteswap()
        payload = swapped.tobytes()
    facts = {
        "dim": list(dim[1 : 1 + dim[0]]),
        "pixdim_qfac": pixdim[0],
        "descrip": data[148:228].split(b"\0", 1)[0].decode("ascii", "replace"),
        "scl_slope": slope,
    }
    return payload, facts


def as_floats(payload_le: bytes) -> array:
    values = array("f")
    values.frombytes(payload_le)
    if sys.byteorder != "little":
        values.byteswap()
    return values


def analyze(tensor: array, fa: array, label: str) -> dict:
    """Semantic checks shared by download validation, build and verify."""
    if len(tensor) != TENSOR_VALUES or len(fa) != VOXELS:
        raise RecipeError(f"{label}: unexpected value counts {len(tensor)} / {len(fa)}")
    minimum = math.inf
    maximum = -math.inf
    for value in tensor:
        if value != value or value in (math.inf, -math.inf):
            raise RecipeError(f"{label}: non-finite tensor value")
        if value < minimum:
            minimum = value
        if value > maximum:
            maximum = value
    comps = [tensor[c * VOXELS : (c + 1) * VOXELS] for c in range(COMPONENTS)]
    for name, comp in zip(COMPONENT_ORDER, comps):
        if min(comp) == max(comp):
            raise RecipeError(f"{label}: constant {name} component")
    brain = 0
    diag_positive = [0, 0, 0]
    md_values: list[float] = []
    fa_max_err = 0.0
    fa_bad = 0
    for xx, yy, zz, xy, xz, yz, fa_ref in zip(*comps, fa):
        if fa_ref != fa_ref:
            raise RecipeError(f"{label}: non-finite FA value")
        if xx == 0.0 and yy == 0.0 and zz == 0.0 and xy == 0.0 and xz == 0.0 and yz == 0.0:
            err = abs(fa_ref)
        else:
            brain += 1
            if xx > 0.0:
                diag_positive[0] += 1
            if yy > 0.0:
                diag_positive[1] += 1
            if zz > 0.0:
                diag_positive[2] += 1
            t1 = xx + yy + zz
            t2 = xx * xx + yy * yy + zz * zz + 2.0 * (xy * xy + xz * xz + yz * yz)
            md_values.append(t1 / 3.0)
            fa_calc = math.sqrt(max(0.0, 1.5 - 0.5 * t1 * t1 / t2)) if t2 > 0.0 else 0.0
            err = abs(fa_calc - fa_ref)
        if err > fa_max_err:
            fa_max_err = err
        if err > FA_TOLERANCE:
            fa_bad += 1
    if fa_bad:
        raise RecipeError(
            f"{label}: tensor inconsistent with published FA under order {COMPONENT_ORDER} "
            f"({fa_bad} voxels exceed {FA_TOLERANCE}, max err {fa_max_err:.3g})"
        )
    if brain < MIN_BRAIN_VOXELS:
        raise RecipeError(f"{label}: only {brain} nonzero tensor voxels (degenerate mask)")
    fractions = [count / brain for count in diag_positive]
    if min(fractions) < MIN_DIAGONAL_POSITIVE_FRACTION:
        raise RecipeError(f"{label}: diagonal positive fractions {fractions} below {MIN_DIAGONAL_POSITIVE_FRACTION}")
    md_median = statistics.median(md_values)
    if not (MD_MEDIAN_RANGE[0] <= md_median <= MD_MEDIAN_RANGE[1]):
        raise RecipeError(f"{label}: median mean diffusivity {md_median:.3g} outside {MD_MEDIAN_RANGE}")
    zero_values = sum(1 for value in tensor if value == 0.0)
    return {
        "min": minimum,
        "max": maximum,
        "zero_values": zero_values,
        "zero_fraction": round(zero_values / TENSOR_VALUES, 6),
        "brain_voxels": brain,
        "diagonal_positive_fraction": [round(f, 6) for f in fractions],
        "median_mean_diffusivity_mm2_per_s": md_median,
        "fa_max_abs_err": fa_max_err,
    }


def load_subject(download_dir: Path, entry: dict) -> tuple[bytes, dict, array]:
    subject = entry["subject"]
    tensor_path = local_path(download_dir, entry["diffmodel"]["key"])
    fa_path = local_path(download_dir, entry["FA"]["key"])
    for kind, path in (("diffmodel", tensor_path), ("FA", fa_path)):
        if not path.is_file():
            raise RecipeError(f"{subject}: missing {kind} file {path}")
        if path.stat().st_size != entry[kind]["bytes"]:
            raise RecipeError(f"{subject}: {kind} size {path.stat().st_size} != pinned {entry[kind]['bytes']}")
    payload, facts = parse_nifti(tensor_path, (4, *GRID, COMPONENTS))
    fa_payload, _ = parse_nifti(fa_path, (3, *GRID))
    return payload, facts, as_floats(fa_payload)


def check_downloads(selection: Path, download_dir: Path) -> None:
    for entry in read_selection(selection):
        payload, facts, fa = load_subject(download_dir, entry)
        stats = analyze(as_floats(payload), fa, entry["subject"])
        print(
            f"ok {entry['subject']} brain_voxels={stats['brain_voxels']} "
            f"zero_fraction={stats['zero_fraction']:.4f} fa_max_err={stats['fa_max_abs_err']:.2e} "
            f"md_median={stats['median_mean_diffusivity_mm2_per_s']:.3e} descrip={facts['descrip']!r}"
        )


def sample_name(subject: str) -> str:
    return f"{subject}_model-DTI_desc-WLS_diffmodel_f32_112x112x60x6.bin"


def build(selection: Path, download_dir: Path, samples_dir: Path, index_path: Path, stats_path: Path) -> None:
    entries = read_selection(selection)
    if samples_dir.exists():
        shutil.rmtree(samples_dir)
    output_dir = samples_dir / SERIES_ID
    output_dir.mkdir(parents=True)
    index_path.parent.mkdir(parents=True, exist_ok=True)
    stats_path.parent.mkdir(parents=True, exist_ok=True)
    data_root = samples_dir.parents[1]
    rows = []
    digests = set()
    for entry in entries:
        subject = entry["subject"]
        payload, facts, fa = load_subject(download_dir, entry)
        stats = analyze(as_floats(payload), fa, subject)
        digest = hashlib.sha256(payload).hexdigest()
        if digest in digests:
            raise RecipeError(f"{subject}: duplicate tensor payload")
        digests.add(digest)
        output = output_dir / sample_name(subject)
        output.write_bytes(payload)
        rows.append(
            {
                "dataset_id": DATASET_ID,
                "series_id": SERIES_ID,
                "role": "primary",
                "sample_path": output.relative_to(data_root).as_posix(),
                "numeric_kind": "float",
                "bit_width": 32,
                "endianness": "little",
                "element_size_bytes": 4,
                "sample_size_bytes": len(payload),
                "value_count": TENSOR_VALUES,
                "sample_format": "raw homogeneous little-endian float32 diffusion-tensor field",
                "sample_geometry": "3d_voxel_grid_x_6_tensor_components",
                "sample_rank": 4,
                "sample_shape": [*GRID, COMPONENTS],
                "sample_axes": ["i", "j", "k", "tensor_component"],
                "axis_order_note": "NIfTI order, first axis fastest-varying",
                "tensor_component_order": COMPONENT_ORDER,
                "units": "mm^2/s",
                "natural_record_kind": "participant_dti_wls_tensor_nifti_volume",
                "subject": subject,
                "source_sample": entry["diffmodel"]["key"],
                "source_md5": entry["diffmodel"]["md5"],
                "source_format": "NIfTI-1 single-file gzip (MRtrix3 dwi2tensor output)",
                "source_field": "4D float32 voxel payload: six diffusion-tensor elements per voxel",
                "source_descrip": facts["descrip"],
                "sha256": digest,
                **stats,
            }
        )
        print(
            f"built {subject} brain_voxels={stats['brain_voxels']} zero_fraction={stats['zero_fraction']:.4f} "
            f"min={stats['min']:.4g} max={stats['max']:.4g} fa_max_err={stats['fa_max_abs_err']:.2e}"
        )
    counts = [row["value_count"] for row in rows]
    total_values = sum(counts)
    total_bytes = sum(row["sample_size_bytes"] for row in rows)
    median_values = statistics.median(counts)
    if total_values < MIN_TOTAL_VALUES or median_values < MIN_MEDIAN_VALUES:
        raise RecipeError("acceptance floor failed")
    if total_bytes > MAX_PRIMARY_BYTES:
        raise RecipeError(f"primary output exceeds cap: {total_bytes}")
    with index_path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")
    zero_total = sum(row["zero_values"] for row in rows)
    summary = {
        "dataset_id": DATASET_ID,
        "series_id": SERIES_ID,
        "sample_count": len(rows),
        "primary_values": total_values,
        "primary_bytes": total_bytes,
        "median_value_count": median_values,
        "zero_fraction": round(zero_total / total_values, 6),
        "nonzero_values": total_values - zero_total,
        "brain_voxels_range": [min(r["brain_voxels"] for r in rows), max(r["brain_voxels"] for r in rows)],
        "value_range": [min(r["min"] for r in rows), max(r["max"] for r in rows)],
        "fa_max_abs_err": max(r["fa_max_abs_err"] for r in rows),
        "aggregate_sha256": hashlib.sha256("".join(r["sha256"] for r in rows).encode()).hexdigest(),
        "records": [
            {k: r[k] for k in ("subject", "sha256", "brain_voxels", "zero_fraction", "min", "max", "fa_max_abs_err")}
            for r in rows
        ],
    }
    stats_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        f"built samples={len(rows)} primary_values={total_values} primary_bytes={total_bytes} "
        f"median={median_values:g} zero_fraction={summary['zero_fraction']:.4f} "
        f"aggregate_sha256={summary['aggregate_sha256']}"
    )


def verify(selection: Path, download_dir: Path, index_path: Path, data_root: Path, manifest_path: Path) -> None:
    import tomllib

    entries = read_selection(selection)
    rows = [json.loads(line) for line in index_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if [row.get("subject") for row in rows] != [entry["subject"] for entry in entries]:
        raise RecipeError("index subject set/order differs from selection.tsv")
    digests = set()
    total_bytes = 0
    counts = []
    for row, entry in zip(rows, entries):
        subject = entry["subject"]
        expected_fixed = {
            "dataset_id": DATASET_ID, "series_id": SERIES_ID, "role": "primary",
            "numeric_kind": "float", "bit_width": 32, "endianness": "little",
            "element_size_bytes": 4, "value_count": TENSOR_VALUES,
            "sample_size_bytes": TENSOR_VALUES * 4, "sample_shape": [*GRID, COMPONENTS],
            "tensor_component_order": COMPONENT_ORDER, "source_sample": entry["diffmodel"]["key"],
            "sample_path": f"samples/{DATASET_ID}/{SERIES_ID}/{sample_name(subject)}",
        }
        for key, value in expected_fixed.items():
            if row.get(key) != value:
                raise RecipeError(f"{subject}: index field {key}={row.get(key)!r} != {value!r}")
        sample = data_root / row["sample_path"]
        actual = sample.read_bytes()
        if len(actual) != TENSOR_VALUES * 4:
            raise RecipeError(f"{subject}: sample size {len(actual)}")
        # Re-decode the source independently and require a bit-exact copy.
        payload, _, fa = load_subject(download_dir, entry)
        if actual != payload:
            raise RecipeError(f"{subject}: sample bytes differ from re-decoded source payload")
        digest = hashlib.sha256(actual).hexdigest()
        if digest != row.get("sha256") or digest in digests:
            raise RecipeError(f"{subject}: sha256 mismatch or duplicate sample")
        digests.add(digest)
        # Recompute statistics from the stored sample (not from build output).
        stats = analyze(as_floats(actual), fa, subject)
        for key in ("min", "max", "zero_values", "brain_voxels"):
            if row.get(key) != stats[key]:
                raise RecipeError(f"{subject}: index {key}={row.get(key)!r} != recomputed {stats[key]!r}")
        total_bytes += len(actual)
        counts.append(TENSOR_VALUES)
        print(f"verified {subject} zero_fraction={stats['zero_fraction']:.4f} fa_max_err={stats['fa_max_abs_err']:.2e}")
    if sum(counts) < MIN_TOTAL_VALUES or statistics.median(counts) < MIN_MEDIAN_VALUES:
        raise RecipeError("acceptance floor failed")
    if total_bytes > MAX_PRIMARY_BYTES:
        raise RecipeError("primary output cap failed")
    manifest = tomllib.loads(manifest_path.read_text(encoding="utf-8"))
    series = [s for s in manifest.get("series", []) if s.get("id") == SERIES_ID]
    if len(series) != 1:
        raise RecipeError("manifest must declare exactly one primary tensor series")
    if series[0].get("sample_count") != len(rows) or series[0].get("total_size_bytes") != total_bytes:
        raise RecipeError(
            f"manifest scope mismatch: sample_count={series[0].get('sample_count')} total_size_bytes="
            f"{series[0].get('total_size_bytes')} realized {len(rows)} / {total_bytes}"
        )
    print(
        f"verified dataset={DATASET_ID} samples={len(rows)} total_values={sum(counts)} "
        f"total_bytes={total_bytes} median={statistics.median(counts):g}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    check = sub.add_parser("check-downloads")
    check.add_argument("--selection", type=Path, required=True)
    check.add_argument("--download-dir", type=Path, required=True)
    bld = sub.add_parser("build")
    bld.add_argument("--selection", type=Path, required=True)
    bld.add_argument("--download-dir", type=Path, required=True)
    bld.add_argument("--samples-dir", type=Path, required=True)
    bld.add_argument("--index", type=Path, required=True)
    bld.add_argument("--stats", type=Path, required=True)
    ver = sub.add_parser("verify")
    ver.add_argument("--selection", type=Path, required=True)
    ver.add_argument("--download-dir", type=Path, required=True)
    ver.add_argument("--index", type=Path, required=True)
    ver.add_argument("--data-root", type=Path, required=True)
    ver.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command == "check-downloads":
            check_downloads(args.selection, args.download_dir)
        elif args.command == "build":
            build(args.selection, args.download_dir, args.samples_dir, args.index, args.stats)
        else:
            verify(args.selection, args.download_dir, args.index, args.data_root, args.manifest)
    except RecipeError as exc:
        raise SystemExit(f"FATAL: {exc}") from None


if __name__ == "__main__":
    main()
