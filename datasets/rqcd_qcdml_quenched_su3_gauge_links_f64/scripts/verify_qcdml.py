#!/usr/bin/env python3
"""Independent verifier for rqcd_qcdml_quenched_su3_gauge_links_f64.

Re-derives every sample from the downloaded outer-zip members with a separate code
path (stdlib zipfile for the inner torch archive, pickletools.genops for the tensor
header; never unpickles), byte-compares it with the emitted sample, and checks SU(3)
structure: |entries| <= 1, U U^dagger = 1 and det U = 1 to ~1e-12.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import pickletools
import re
import struct
import sys
import tomllib
import zipfile
import zlib
from pathlib import Path

DATASET_ID = "rqcd_qcdml_quenched_su3_gauge_links_f64"
SERIES_ID = "qcdml_ens001_su3_gauge_links_f64"
SAMPLE_BYTES = 4 * 8 * 8 * 8 * 16 * 9 * 16
VALUES = SAMPLE_BYTES // 8
TOL = 1e-12


def fail(msg: str) -> None:
    raise SystemExit(f"VERIFY FAIL: {msg}")


def rederive(member_path: Path, row: dict) -> bytes:
    blob = member_path.read_bytes()
    if blob[:4] != b"PK\x03\x04":
        fail(f"{member_path.name}: not a zip local header")
    nlen, xlen = struct.unpack_from("<2H", blob, 26)
    method = struct.unpack_from("<H", blob, 8)[0]
    crc = struct.unpack_from("<I", blob, 14)[0]
    name = blob[30 : 30 + nlen].decode()
    if name != row["member"] or method != 8 or crc != int(row["crc32"], 16):
        fail(f"{member_path.name}: local header mismatch")
    comp = blob[30 + nlen + xlen :]
    if len(comp) != int(row["compressed_size"]):
        fail(f"{member_path.name}: compressed length mismatch")
    inner = zlib.decompress(comp, -15)
    if len(inner) != int(row["uncompressed_size"]) or zlib.crc32(inner) != crc:
        fail(f"{member_path.name}: inflated CRC/size mismatch")
    cfg = int(row["config"])
    with zipfile.ZipFile(io.BytesIO(inner)) as z:
        prefix = f"config_{cfg}/"
        if z.read(prefix + "byteorder") != b"little":
            fail(f"config {cfg}: not little-endian")
        pkl = z.read(prefix + "data.pkl")
        data = z.read(prefix + "data/0")
    ops = list(pickletools.genops(pkl))
    names = [op.name for op, _, _ in ops]
    args = [a for _, a, _ in ops]
    if "torch ComplexDoubleStorage" not in args:
        fail(f"config {cfg}: storage is not ComplexDoubleStorage")
    # shape tuple follows the storage-offset int; locate (4,8,8,8,16,3,3) as consecutive ints
    ints = [a for op, a, _ in ops if op.name.startswith("BININT")]
    if ints[:9] != [294912, 0, 4, 8, 8, 8, 16, 3, 3]:
        fail(f"config {cfg}: shape/offset {ints[:9]}")
    if ints[9:] != [73728, 9216, 1152, 144, 9, 3, 1]:
        fail(f"config {cfg}: non-contiguous stride {ints[9:]}")
    if "REDUCE" not in names or len(data) != SAMPLE_BYTES:
        fail(f"config {cfg}: data/0 size {len(data)}")
    return data


def su3_check(data: bytes, cfg: int) -> tuple[float, float, float, float, float]:
    v = struct.unpack(f"<{VALUES}d", data)
    if not all(math.isfinite(x) for x in v):
        fail(f"config {cfg}: non-finite value")
    lo, hi = min(v), max(v)
    if lo == hi or len(set(v[:4096])) < 1000:
        fail(f"config {cfg}: constant or degenerate links")
    worst_abs = worst_unit = worst_det = 0.0
    for b in range(0, VALUES, 18):
        u = [complex(v[b + 2 * k], v[b + 2 * k + 1]) for k in range(9)]
        worst_abs = max(worst_abs, max(abs(z) for z in u))
        for p in range(3):
            for q in range(3):
                s = sum(u[3 * p + k] * u[3 * q + k].conjugate() for k in range(3))
                worst_unit = max(worst_unit, abs(s - (1.0 if p == q else 0.0)))
        det = (
            u[0] * (u[4] * u[8] - u[5] * u[7])
            - u[1] * (u[3] * u[8] - u[5] * u[6])
            + u[2] * (u[3] * u[7] - u[4] * u[6])
        )
        worst_det = max(worst_det, abs(det - 1.0))
    if worst_abs > 1.0 + TOL:
        fail(f"config {cfg}: |entry| {worst_abs} > 1")
    if worst_unit > TOL or worst_det > TOL:
        fail(f"config {cfg}: not SU(3) (unitarity {worst_unit:.2e}, det {worst_det:.2e})")
    return lo, hi, worst_abs, worst_unit, worst_det


def main() -> None:
    ap = argparse.ArgumentParser()
    for flag in ("--manifest", "--members", "--downloads", "--index", "--data-root"):
        ap.add_argument(flag, required=True)
    a = ap.parse_args()
    data_root = Path(a.data_root)
    manifest = tomllib.loads(Path(a.manifest).read_text(encoding="utf-8"))
    series = [s for s in manifest["series"] if s["id"] == SERIES_ID]
    if manifest["dataset_id"] != DATASET_ID or len(series) != 1:
        fail("manifest identity")
    series = series[0]
    with Path(a.members).open(encoding="utf-8", newline="") as h:
        members = list(csv.DictReader(h, delimiter="\t"))
    configs = [int(r["config"]) for r in members]
    if configs != [300 + 47 * k for k in range(100)]:
        fail("pinned config schedule changed")
    rows = [json.loads(line) for line in Path(a.index).read_text(encoding="utf-8").splitlines() if line]
    if len(rows) != len(members) or len(rows) != series["sample_count"]:
        fail(f"index rows {len(rows)} vs members {len(members)} vs manifest {series['sample_count']}")
    out_dir = data_root / "samples" / DATASET_ID / SERIES_ID
    on_disk = sorted(p.name for p in out_dir.glob("*"))
    expected_names = sorted(f"config_{c:04d}.bin" for c in configs)
    if on_disk != expected_names:
        fail("sample directory contents differ from the pinned schedule")
    total = 0
    digests = set()
    worst = [0.0, 0.0, 0.0]
    for row, mem in zip(rows, members):
        cfg = int(mem["config"])
        want_path = f"samples/{DATASET_ID}/{SERIES_ID}/config_{cfg:04d}.bin"
        fixed = {
            "dataset_id": DATASET_ID,
            "series_id": SERIES_ID,
            "sample_path": want_path,
            "numeric_kind": "float",
            "bit_width": 64,
            "endianness": "little",
            "element_size_bytes": 8,
            "sample_size_bytes": SAMPLE_BYTES,
            "value_count": VALUES,
            "config": cfg,
            "source_member": mem["member"],
        }
        for k, val in fixed.items():
            if row.get(k) != val:
                fail(f"index field {k} for config {cfg}: {row.get(k)!r} != {val!r}")
        sample = (data_root / want_path).read_bytes()
        derived = rederive(Path(a.downloads) / "members" / f"config_{cfg}.zipmember", mem)
        if sample != derived:
            fail(f"config {cfg}: sample bytes differ from re-derived data/0")
        sha = hashlib.sha256(sample).hexdigest()
        if sha != row["sha256"] or sha in digests:
            fail(f"config {cfg}: sha mismatch or duplicate sample")
        digests.add(sha)
        lo, hi, wa, wu, wd = su3_check(sample, cfg)
        if lo != row["min"] or hi != row["max"]:
            fail(f"config {cfg}: index min/max mismatch")
        worst = [max(worst[0], wa), max(worst[1], wu), max(worst[2], wd)]
        total += len(sample)
        print(f"ok config={cfg} |U|max={wa:.15f} unit={wu:.2e} det={wd:.2e}", flush=True)
    if total != series["total_size_bytes"]:
        fail(f"total bytes {total} != manifest {series['total_size_bytes']}")
    print(
        f"verify_ok samples={len(rows)} bytes={total} values={total // 8} "
        f"worst_abs={worst[0]:.15f} worst_unitarity={worst[1]:.2e} worst_det={worst[2]:.2e}"
    )


if __name__ == "__main__":
    main()
