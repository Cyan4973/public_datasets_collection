#!/usr/bin/env python3
"""HUTUBS measured HRIR SOFA files -> raw little-endian float64 samples.

Subcommands
  validate  check one downloaded ppN_HRIRs_measured.sofa (used by download.sh)
  license   check the saved DepositOnce item page for the CC BY 4.0 grant
  build     decode all 96 local files, write samples + index + stats
  verify    independently re-derive every sample and check index/manifest

Each sample is the SOFA variable Data.IR of one subject, shape [M=440, R=2,
N=256] (measurement direction, ear, tap) in native C order, written as the
stored IEEE-754 float64 little-endian bytes after inflate + HDF5 byte
unshuffle.  No value is changed, reordered, resampled or windowed.

Pure standard library (h5lite.py is the repository's stdlib HDF5 reader).
"""
from __future__ import annotations

import argparse
import array
import hashlib
import itertools
import json
import math
import os
import re
import shutil
import struct
import sys
import zlib
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import h5lite  # noqa: E402
from h5lite import H5Error  # noqa: E402

DATASET_ID = "hutubs_measured_hrir_f64"
SERIES_ID = "measured_hrir_f64"

# H5T_IEEE_F64LE exactly as netCDF-4 writes it (class 1 version 1, byte-order
# bit 0 clear = little-endian, sign bit 63, exponent 52..62 (11 bits), mantissa
# 0..51, bias 1023).  Read from pp1_HRIRs_measured.sofa Data.IR.
F64LE = bytes.fromhex("11203f000800000000004000340b0034ff030000")
NC_FILL_DOUBLE = 9.969209968386869e36
FILTER_SHUFFLE, FILTER_DEFLATE = 2, 1

GLOBAL_ATTRS = {
    "DatabaseName": "HUTUBS",
    "License": "cc-by 4.0 (https://creativecommons.org/licenses/by/4.0/)",
    "Conventions": "SOFA",
    "SOFAConventions": "SimpleFreeFieldHRIR",
    "SOFAConventionsVersion": "1.0",
    "DataType": "FIR",
    "RoomType": "free field",
    "Title": "head-related impulse responses",
}
EXPECTED_LINKS = {
    "C", "Data.Delay", "Data.IR", "Data.SamplingRate", "E", "EmitterPosition", "I", "ListenerPosition",
    "ListenerUp", "ListenerView", "M", "N", "R", "ReceiverPosition", "S", "SourcePosition",
}
# Data.IR attributes that would change the meaning of the stored numbers.
FORBIDDEN_VAR_ATTRS = {"_FillValue", "missing_value", "scale_factor", "add_offset", "valid_min", "valid_max", "valid_range"}

SPEC = {
    "n_subjects": 96,
    "M": 440,
    "R": 2,
    "N": 256,
    "sampling_rate": 44100.0,
    "min_distinct_values": 100_000,  # of 225,280 per sample; probe pp1: 223,521
    "max_abs_value": 1e3,            # probe pp1: |x| <= 2.1; anything near 1e36 is a fill
    "global_attrs": GLOBAL_ATTRS,
    "expected_links": EXPECTED_LINKS,
    "check_grid": True,
}
SUBJECT_NOTES = {
    1: "FABIAN head-and-torso simulator (dummy head); repeated in subject 96",
    96: "FABIAN head-and-torso simulator (dummy head); repeat of subject 1",
    22: "human subject measured twice; repeated in subject 88",
    88: "human subject measured twice; repeat of subject 22",
}

DEPOSITONCE_HANDLE = "https://depositonce.tu-berlin.de/handle/11303/9429"
DEPOSITONCE_TITLE = "The HUTUBS head-related transfer function (HRTF) database"
CC_BY_40 = "https://creativecommons.org/licenses/by/4.0/"


class RecipeError(ValueError):
    """Semantic violation of the recipe's expectations."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RecipeError(message)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def sample_rel_path(subject: int) -> str:
    return f"samples/{DATASET_ID}/{SERIES_ID}/pp{subject:03d}.bin"


# ------------------------------------------------------------------ files.tsv
def read_files_tsv(path: Path, spec: dict) -> list[dict]:
    lines = path.read_text(encoding="utf-8").splitlines()
    require(lines and lines[0].split("\t") == ["subject", "file", "size_bytes", "last_modified", "sha256"],
            f"{path}: unexpected header")
    rows = []
    for line in lines[1:]:
        subject, name, size, last_modified, digest = line.split("\t")
        require(name == f"pp{int(subject)}_HRIRs_measured.sofa", f"{path}: bad row {line!r}")
        require(digest == "-" or re.fullmatch(r"[0-9a-f]{64}", digest) is not None, f"{path}: bad sha256 {digest!r}")
        rows.append({"subject": int(subject), "file": name, "size_bytes": int(size),
                     "last_modified": last_modified, "sha256": None if digest == "-" else digest})
    require([r["subject"] for r in rows] == list(range(1, spec["n_subjects"] + 1)),
            f"{path}: subjects must be exactly 1..{spec['n_subjects']}")
    return rows


# --------------------------------------------------------------- SOFA decode
def read_single_chunk_f64(f: h5lite.H5File, name: str, addr: int, shape: tuple[int, ...]) -> tuple[bytes, dict]:
    """Decode a chunked float64 variable stored as exactly one full chunk."""
    messages = f.messages(addr)
    info = f.dataset(addr, messages)
    require(tuple(info["shape"]) == shape, f"{name}: shape {info['shape']} != {shape}")
    require(bytes(info["datatype"]) == F64LE, f"{name}: datatype {bytes(info['datatype']).hex()} is not IEEE f64 LE")
    require(info["layout_class"] == 2, f"{name}: layout class {info['layout_class']} is not chunked")
    require(tuple(info["chunk_dims"]) == shape + (8,), f"{name}: chunk dims {info['chunk_dims']} != one full chunk")
    ids = [fid for fid, _flags, _values in info["filters"]]
    require(ids == [FILTER_SHUFFLE, FILTER_DEFLATE], f"{name}: filter pipeline {info['filters']} is not shuffle+deflate")
    require(info["filters"][0][2] == (8,), f"{name}: shuffle element size {info['filters'][0][2]} != 8")
    entries, final = f.chunk_index(info["chunk_btree"], len(shape) + 1)
    require(len(entries) == 1, f"{name}: {len(entries)} chunks, expected 1")
    size, mask, offsets, chunk_addr = entries[0]
    require(offsets == (0,) * (len(shape) + 1), f"{name}: chunk offsets {offsets}")
    require(tuple(final) == shape + (8,), f"{name}: final chunk key {final}")
    require(chunk_addr + size <= len(f.raw), f"{name}: chunk exceeds file")
    count = math.prod(shape)
    data = h5lite.decode_chunk(f.raw[chunk_addr:chunk_addr + size], info["filters"], mask, 8, count * 8)
    return data, {"messages": messages, "info": info, "chunk": (size, mask, chunk_addr)}


def decode_sofa(raw: bytes, subject: int, spec: dict) -> dict:
    f = h5lite.H5File(raw)
    attrs = f.attributes(f.root_addr)
    for key, want in spec["global_attrs"].items():
        require(attrs.get(key) == want, f"global attribute {key}={attrs.get(key)!r}, expected {want!r}")
    require(attrs.get("ListenerShortName") == f"pp{subject}",
            f"ListenerShortName {attrs.get('ListenerShortName')!r} != pp{subject}")
    links = f.links(f.root_addr, "name")
    require(set(links) == spec["expected_links"], f"root variables {sorted(links)} differ from the SOFA FIR set")
    require(f.links(f.root_addr, "creation_order") == links, "name and creation-order link indexes disagree")
    M, R, N = spec["M"], spec["R"], spec["N"]
    ir, ir_meta = read_single_chunk_f64(f, "Data.IR", links["Data.IR"], (M, R, N))
    ir_attrs = f.attributes(links["Data.IR"], ir_meta["messages"])
    bad = FORBIDDEN_VAR_ATTRS & set(ir_attrs)
    require(not bad, f"Data.IR carries value-changing attributes {sorted(bad)}")
    rate, _ = read_single_chunk_f64(f, "Data.SamplingRate", links["Data.SamplingRate"], (1,))
    require(struct.unpack("<d", rate) == (spec["sampling_rate"],), f"Data.SamplingRate {struct.unpack('<d', rate)}")
    delay_b, _ = read_single_chunk_f64(f, "Data.Delay", links["Data.Delay"], (1, R))
    grid, _ = read_single_chunk_f64(f, "SourcePosition", links["SourcePosition"], (M, 3))
    sp_attrs = f.attributes(links["SourcePosition"])
    require(sp_attrs.get("Type") == "spherical" and sp_attrs.get("Units") == "degree, degree, metre",
            f"SourcePosition Type/Units {sp_attrs.get('Type')!r}/{sp_attrs.get('Units')!r}")
    return {
        "ir": ir,
        "delay": list(struct.unpack(f"<{R}d", delay_b)),
        "grid": grid,
        "grid_sha256": sha256_bytes(grid),
        "attrs": attrs,
        "checked_blocks": f.checked_blocks,
    }


def ir_stats(data: bytes, spec: dict) -> dict:
    M, R, N = spec["M"], spec["R"], spec["N"]
    count = M * R * N
    require(len(data) == count * 8, f"IR has {len(data)} bytes, expected {count * 8}")
    vals = struct.unpack(f"<{count}d", data)
    finite = [v for v in vals if math.isfinite(v)]
    nan = sum(1 for v in vals if v != v)
    inf = sum(1 for v in vals if v == v and not math.isfinite(v))
    huge = sum(1 for v in finite if abs(v) >= spec["max_abs_value"])
    zero_rows = constant_rows = 0
    for row in range(M * R):
        seg = vals[row * N:(row + 1) * N]
        if all(v == 0.0 for v in seg):
            zero_rows += 1
        elif min(seg) == max(seg):
            constant_rows += 1
    f32_exact = sum(1 for v in finite if struct.unpack("<f", struct.pack("<f", v))[0] == v) if not (nan or inf or huge) else -1
    return {
        "value_count": count,
        "min": min(finite) if finite else None,
        "max": max(finite) if finite else None,
        "nan_values": nan,
        "inf_values": inf,
        "fill_or_huge_values": huge,
        "zero_values": sum(1 for v in vals if v == 0.0),
        "all_zero_rows": zero_rows,
        "constant_nonzero_rows": constant_rows,
        "distinct_values": len(set(data[i:i + 8] for i in range(0, len(data), 8))),
        "float32_exact_values": f32_exact,
        "sha256": sha256_bytes(data),
    }


def missing_policy_violations(stats: dict, spec: dict) -> list[str]:
    out = []
    if stats["nan_values"]:
        out.append(f"{stats['nan_values']} NaN values")
    if stats["inf_values"]:
        out.append(f"{stats['inf_values']} infinite values")
    if stats["fill_or_huge_values"]:
        out.append(f"{stats['fill_or_huge_values']} values with |x| >= {spec['max_abs_value']} (netCDF fill or corrupt)")
    if stats["all_zero_rows"]:
        out.append(f"{stats['all_zero_rows']} all-zero (direction, ear) rows = missing measurements")
    if stats["constant_nonzero_rows"]:
        out.append(f"{stats['constant_nonzero_rows']} constant (direction, ear) rows")
    if stats["distinct_values"] < spec["min_distinct_values"]:
        out.append(f"only {stats['distinct_values']} distinct values (< {spec['min_distinct_values']})")
    return out


def check_subject_file(path: Path, subject: int, spec: dict) -> tuple[dict, dict]:
    raw = path.read_bytes()
    decoded = decode_sofa(raw, subject, spec)
    stats = ir_stats(decoded["ir"], spec)
    problems = missing_policy_violations(stats, spec)
    require(not problems, f"{path.name}: missing-value policy violated: {'; '.join(problems)}")
    return decoded, stats


# ----------------------------------------------------------------- commands
def cmd_validate(args) -> int:
    path = Path(args.file)
    try:
        decoded, stats = check_subject_file(path, args.subject, SPEC)
    except (RecipeError, H5Error) as exc:
        print(f"validate FAILED {path.name}: {exc}", file=sys.stderr)
        return 1
    print(f"validate ok pp{args.subject}: DatabaseName=HUTUBS License='{decoded['attrs']['License']}' "
          f"Data.IR f64LE {SPEC['M']}x{SPEC['R']}x{SPEC['N']} min={stats['min']:.6g} max={stats['max']:.6g} "
          f"distinct={stats['distinct_values']} delay={decoded['delay']} metadata_checksums={decoded['checked_blocks']}")
    return 0


def check_license_page(text: str) -> None:
    """The DepositOnce item page embeds its DSpace metadata as JSON; require the
    HUTUBS item block (handle 11303/9429) to carry dc.rights.uri = CC BY 4.0."""
    anchor = text.find(f'"value":"{DEPOSITONCE_HANDLE}"')
    require(anchor >= 0, f"DepositOnce page lacks the item handle {DEPOSITONCE_HANDLE}")
    block = text[anchor:anchor + 4000]
    m = re.search(r'"dc\.rights\.uri":\[\{[^\]]*?"value":"([^"]+)"', block)
    require(m is not None and m.group(1) == CC_BY_40, f"dc.rights.uri near the item handle is {m.group(1) if m else None!r}")
    m = re.search(r'"dc\.title":\[\{[^\]]*?"value":"([^"]+)"', block)
    require(m is not None and m.group(1) == DEPOSITONCE_TITLE, f"dc.title near the item handle is {m.group(1) if m else None!r}")


def cmd_license(args) -> int:
    try:
        check_license_page(Path(args.file).read_text(encoding="utf-8", errors="replace"))
    except RecipeError as exc:
        print(f"license check FAILED: {exc}", file=sys.stderr)
        return 1
    print(f"license ok: DepositOnce {DEPOSITONCE_HANDLE} '{DEPOSITONCE_TITLE}' dc.rights.uri={CC_BY_40}")
    return 0


def build(downloads: Path, files_tsv: Path, data_root: Path, spec: dict, log=print) -> dict:
    rows = read_files_tsv(files_tsv, spec)
    out_dir = data_root / "samples" / DATASET_ID / SERIES_ID
    index_dir = data_root / "index" / DATASET_ID
    filtered_dir = data_root / "filtered" / DATASET_ID
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)
    index_dir.mkdir(parents=True, exist_ok=True)
    filtered_dir.mkdir(parents=True, exist_ok=True)
    index_rows, grid_ref, seen = [], None, {}
    for row in rows:
        subject = row["subject"]
        path = downloads / row["file"]
        require(path.is_file(), f"missing local file {path}")
        require(path.stat().st_size == row["size_bytes"], f"{path.name}: size {path.stat().st_size} != pinned {row['size_bytes']}")
        source_sha = sha256_file(path)
        if row["sha256"]:
            require(source_sha == row["sha256"], f"{path.name}: sha256 {source_sha} != pinned {row['sha256']}")
        decoded, stats = check_subject_file(path, subject, spec)
        if spec["check_grid"]:
            if grid_ref is None:
                grid_ref = decoded["grid_sha256"]
            require(decoded["grid_sha256"] == grid_ref, f"{path.name}: SourcePosition grid differs from pp1's")
        require(stats["sha256"] not in seen, f"{path.name}: Data.IR identical to subject {seen.get(stats['sha256'])}")
        seen[stats["sha256"]] = subject
        rel = sample_rel_path(subject)
        tmp = data_root / (rel + ".tmp")
        tmp.write_bytes(decoded["ir"])
        os.replace(tmp, data_root / rel)
        index_rows.append({
            "dataset_id": DATASET_ID,
            "series_id": SERIES_ID,
            "sample_path": rel,
            "numeric_kind": "float",
            "bit_width": 64,
            "endianness": "little",
            "element_size_bytes": 8,
            "sample_size_bytes": len(decoded["ir"]),
            "value_count": stats["value_count"],
            "shape": [spec["M"], spec["R"], spec["N"]],
            "axes": ["measurement_direction", "receiver_ear", "tap"],
            "subject": subject,
            "listener_short_name": decoded["attrs"]["ListenerShortName"],
            "subject_note": SUBJECT_NOTES.get(subject, "human subject"),
            "source_file": row["file"],
            "source_sha256": source_sha,
            "sampling_rate_hz": spec["sampling_rate"],
            "data_delay_samples": decoded["delay"],
            "source_position_grid_sha256": decoded["grid_sha256"],
            "min": stats["min"],
            "max": stats["max"],
            "distinct_values": stats["distinct_values"],
            "zero_values": stats["zero_values"],
            "float32_exact_values": stats["float32_exact_values"],
            "sha256": stats["sha256"],
        })
        log(f"pp{subject}: min={stats['min']:.6g} max={stats['max']:.6g} distinct={stats['distinct_values']} "
            f"zeros={stats['zero_values']} f32exact={stats['float32_exact_values']} delay={decoded['delay']}")
    index_path = index_dir / "samples.jsonl"
    tmp = index_path.with_suffix(".jsonl.tmp")
    tmp.write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in index_rows), encoding="utf-8")
    os.replace(tmp, index_path)
    summary = {
        "dataset_id": DATASET_ID,
        "series_id": SERIES_ID,
        "samples": len(index_rows),
        "total_values": sum(r["value_count"] for r in index_rows),
        "total_size_bytes": sum(r["sample_size_bytes"] for r in index_rows),
        "min": min(r["min"] for r in index_rows),
        "max": max(r["max"] for r in index_rows),
        "nonzero_delay_subjects": [r["subject"] for r in index_rows if any(r["data_delay_samples"])],
        "source_position_grid_sha256": grid_ref,
        "float32_exact_fraction": sum(r["float32_exact_values"] for r in index_rows) / sum(r["value_count"] for r in index_rows),
    }
    (filtered_dir / "build_summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    log(f"build summary: {json.dumps(summary, sort_keys=True)}")
    return summary


# ------------------------------------------------- independent verify path
def verify_unshuffle8(data: bytes) -> bytes:
    """Per-element HDF5 unshuffle written independently of h5lite.unshuffle."""
    require(len(data) % 8 == 0, "shuffled IR length is not a multiple of 8")
    n = len(data) // 8
    planes = [data[j * n:(j + 1) * n] for j in range(8)]
    return bytes(itertools.chain.from_iterable(zip(*planes)))


def verify_decode_ir(raw: bytes, subject: int, spec: dict) -> bytes:
    """Locate Data.IR's chunk with h5lite's metadata walk, then inflate and
    unshuffle it with independent code (zlib.decompress + verify_unshuffle8)."""
    f = h5lite.H5File(raw)
    attrs = f.attributes(f.root_addr)
    require(attrs.get("DatabaseName") == "HUTUBS" and attrs.get("License") == GLOBAL_ATTRS["License"],
            "verify: DatabaseName/License attribute mismatch")
    require(attrs.get("ListenerShortName") == f"pp{subject}", "verify: ListenerShortName mismatch")
    links = f.links(f.root_addr, "creation_order")
    info = f.dataset(links["Data.IR"])
    require(bytes(info["datatype"]) == F64LE, "verify: Data.IR datatype is not f64 LE")
    entries, _final = f.chunk_index(info["chunk_btree"], 4)
    require(len(entries) == 1 and entries[0][1] == 0, "verify: Data.IR is not one unmasked chunk")
    size, _mask, _off, addr = entries[0]
    inflated = zlib.decompress(bytes(raw[addr:addr + size]))
    require(len(inflated) == spec["M"] * spec["R"] * spec["N"] * 8, "verify: inflated Data.IR has the wrong size")
    return verify_unshuffle8(inflated)


def verify_stats(data: bytes, spec: dict) -> dict:
    """Statistics recomputed with array('d') instead of struct (independent of ir_stats)."""
    vals = array.array("d")
    vals.frombytes(data)
    if sys.byteorder != "little":
        vals.byteswap()
    N = spec["N"]
    bad = [v for v in vals if not math.isfinite(v) or abs(v) >= spec["max_abs_value"]]
    rows_degenerate = 0
    for start in range(0, len(vals), N):
        seg = vals[start:start + N]
        if max(seg) == min(seg):
            rows_degenerate += 1
    return {"min": min(vals), "max": max(vals), "bad": len(bad), "degenerate_rows": rows_degenerate,
            "distinct": len({data[i:i + 8] for i in range(0, len(data), 8)})}


def parse_manifest_series(manifest: Path) -> dict:
    import tomllib
    doc = tomllib.loads(manifest.read_text(encoding="utf-8"))
    require(doc.get("dataset_id") == DATASET_ID, "manifest dataset_id mismatch")
    series = {s["id"]: s for s in doc.get("series", [])}
    require(SERIES_ID in series, f"manifest lacks series {SERIES_ID}")
    return series[SERIES_ID]


def verify(downloads: Path, files_tsv: Path, data_root: Path, manifest: Path | None, spec: dict, log=print) -> dict:
    rows = read_files_tsv(files_tsv, spec)
    index_path = data_root / "index" / DATASET_ID / "samples.jsonl"
    require(index_path.is_file(), f"missing index {index_path}")
    index_rows = [json.loads(line) for line in index_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    require(len(index_rows) == spec["n_subjects"], f"index has {len(index_rows)} rows, expected {spec['n_subjects']}")
    require([r["subject"] for r in index_rows] == [r["subject"] for r in rows], "index subjects/order differ from files.tsv")
    sample_dir = data_root / "samples" / DATASET_ID / SERIES_ID
    on_disk = sorted(p.name for p in sample_dir.iterdir())
    expected_names = sorted(Path(sample_rel_path(r["subject"])).name for r in rows)
    require(on_disk == expected_names, f"sample directory holds unexpected files: {sorted(set(on_disk) ^ set(expected_names))[:5]}")
    count = spec["M"] * spec["R"] * spec["N"]
    digests = set()
    total_bytes = 0
    for src_row, row in zip(rows, index_rows):
        subject = src_row["subject"]
        require(row["dataset_id"] == DATASET_ID and row["series_id"] == SERIES_ID, f"pp{subject}: ids")
        require(row["sample_path"] == sample_rel_path(subject), f"pp{subject}: sample_path {row['sample_path']}")
        require((row["numeric_kind"], row["bit_width"], row["endianness"], row["element_size_bytes"]) == ("float", 64, "little", 8),
                f"pp{subject}: dtype fields")
        require(row["value_count"] == count and row["sample_size_bytes"] == count * 8, f"pp{subject}: counts")
        require(row["shape"] == [spec["M"], spec["R"], spec["N"]], f"pp{subject}: shape")
        src = downloads / src_row["file"]
        raw = src.read_bytes()
        require(len(raw) == src_row["size_bytes"], f"{src.name}: size differs from files.tsv")
        src_sha = sha256_bytes(raw)
        require(src_sha == row["source_sha256"], f"{src.name}: source sha256 differs from index")
        if src_row["sha256"]:
            require(src_sha == src_row["sha256"], f"{src.name}: source sha256 differs from files.tsv pin")
        sample = (data_root / row["sample_path"]).read_bytes()
        require(len(sample) == count * 8, f"pp{subject}: sample size {len(sample)}")
        rederived = verify_decode_ir(raw, subject, spec)
        require(rederived == sample, f"pp{subject}: sample bytes differ from independently re-decoded Data.IR")
        digest = sha256_bytes(sample)
        require(digest == row["sha256"], f"pp{subject}: sample sha256 differs from index")
        require(digest not in digests, f"pp{subject}: duplicate sample")
        digests.add(digest)
        st = verify_stats(sample, spec)
        require(st["bad"] == 0, f"pp{subject}: {st['bad']} NaN/inf/fill values")
        require(st["degenerate_rows"] == 0, f"pp{subject}: {st['degenerate_rows']} constant or all-zero (direction, ear) rows")
        require(st["distinct"] >= spec["min_distinct_values"], f"pp{subject}: only {st['distinct']} distinct values")
        require(st["distinct"] == row["distinct_values"], f"pp{subject}: distinct count differs from index")
        require(st["min"] == row["min"] and st["max"] == row["max"], f"pp{subject}: min/max differ from index")
        total_bytes += len(sample)
    if manifest is not None:
        series = parse_manifest_series(manifest)
        require(series.get("sample_count") == len(index_rows), f"manifest sample_count {series.get('sample_count')} != {len(index_rows)}")
        require(series.get("total_size_bytes") == total_bytes, f"manifest total_size_bytes {series.get('total_size_bytes')} != {total_bytes}")
        require(series.get("bit_width") == 64 and series.get("numeric_kind") == "float" and series.get("role") == "primary",
                "manifest series dtype/role")
    summary = {"samples": len(index_rows), "total_size_bytes": total_bytes}
    log(f"verify ok: {json.dumps(summary, sort_keys=True)}")
    return summary


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    v = sub.add_parser("validate")
    v.add_argument("--file", required=True)
    v.add_argument("--subject", type=int, required=True)
    lic = sub.add_parser("license")
    lic.add_argument("--file", required=True)
    for name in ("build", "verify"):
        s = sub.add_parser(name)
        s.add_argument("--downloads", required=True)
        s.add_argument("--files-tsv", required=True)
        s.add_argument("--data-root", required=True)
        if name == "verify":
            s.add_argument("--manifest")
    args = p.parse_args(argv)
    if args.cmd == "validate":
        return cmd_validate(args)
    if args.cmd == "license":
        return cmd_license(args)
    try:
        if args.cmd == "build":
            build(Path(args.downloads), Path(args.files_tsv), Path(args.data_root), SPEC)
        else:
            verify(Path(args.downloads), Path(args.files_tsv), Path(args.data_root),
                   Path(args.manifest) if args.manifest else None, SPEC)
    except (RecipeError, H5Error) as exc:
        print(f"{args.cmd} FAILED: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
