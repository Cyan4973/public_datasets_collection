#!/usr/bin/env python3
"""TDiG Evo 2 7B final-norm hidden states (chr22 tier-3 raw_h_norm) helper.

Subcommands
  plan    parse the fetched HDF5 head, validate the raw_h_norm object header
          and print the byte ranges download.sh must fetch (TSV)
  check   semantic validation of the downloaded ranges (download.sh gate)
  build   emit one little-endian float16 sample per genomic window + index
  verify  independent re-derivation of every sample, index row and total

Pure standard library. Network I/O stays in download.sh (curl).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import h5meta  # noqa: E402

DATASET_ID = "hf_tdig_evo2_7b_hg38_final_norm_hidden_f16"
SERIES_ID = "evo2_7b_final_norm_hidden_f16"
REPO = "darejinn/TDiG-evo2-hidden-states"
REVISION = "9f0d2a6a31ddd08ca4e3defab714dc7665634501"
CHROM = "chr22"
H5_NAME = f"{CHROM}_tier3_raw.h5"
H5_SIZE = 47_677_466_172
HEAD_BYTES = 65_536
HEAD_SHA256 = "2c6772344c10254fc7f6dda71dd1621e165b4769f0d3762b9ac42782ffce6599"
TARGET = "raw_h_norm"
N_WINDOWS, N_TOKENS, HIDDEN = 100, 600, 4096
WINDOW_VALUES = N_TOKENS * HIDDEN
WINDOW_BYTES = WINDOW_VALUES * 2
# Pinned expectations cross-checked against what the object headers say.
EXPECT_RAW_ADDR = 471_870_248
EXPECT_TOKEN_STRIDE = 10

# Degeneracy thresholds (per window).
MIN_DISTINCT_CODES = 1000
MIN_ROW_SPREAD = 0.005      # rms of (x - per-channel mean over the 600 tokens)
MAX_DUP_ROWS = 6            # consecutive identical token rows (1%)
MIN_ROW_STD = 0.05          # every token row must vary across its 4096 channels

HALF_NONFINITE = bytes(1 if (b & 0x7C) == 0x7C else 0 for b in range(256))


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def fail(msg: str) -> None:
    raise SystemExit(f"ERROR: {msg}")


# ----------------------------------------------------------------- metadata
def load_layout(head_path: Path) -> dict:
    head = head_path.read_bytes()
    if len(head) != HEAD_BYTES:
        fail(f"head has {len(head)} bytes, expected {HEAD_BYTES}")
    if sha256_bytes(head) != HEAD_SHA256:
        fail("HDF5 head sha256 differs from the pinned revision")
    desc = h5meta.describe_file(head)
    if desc["eof"] != H5_SIZE:
        fail(f"superblock EOF {desc['eof']} != pinned file size {H5_SIZE}")
    ds = desc["datasets"]
    for name in (TARGET, "window_idx", "token_stride", "done_mask"):
        if name not in ds:
            fail(f"dataset {name} missing from root group")
    t = ds[TARGET]
    dt = t["dtype"]
    ieee_half = dict(kind="float", size=2, byte_order="little", precision=16, bit_offset=0,
                     sign_location=15, exp_location=10, exp_size=5, mant_location=0,
                     mant_size=10, exp_bias=15)
    for k, v in ieee_half.items():
        if dt.get(k) != v:
            fail(f"{TARGET} datatype {k}={dt.get(k)!r}, expected {v!r} (IEEE binary16 LE)")
    if t["shape"] != [N_WINDOWS, N_TOKENS, HIDDEN]:
        fail(f"{TARGET} shape {t['shape']}")
    if t["filters"]:
        fail(f"{TARGET} has a filter pipeline")
    lay = t["layout"]
    if lay["class"] != "contiguous" or lay["size"] != N_WINDOWS * WINDOW_BYTES:
        fail(f"{TARGET} layout {lay}")
    if lay["address"] != EXPECT_RAW_ADDR:
        fail(f"{TARGET} address {lay['address']} != pinned {EXPECT_RAW_ADDR}")
    if lay["address"] + lay["size"] > H5_SIZE:
        fail("raw_h_norm extends past EOF")
    aux = {}
    for name, kind, size in (("window_idx", "int", 8), ("token_stride", "int", 4), ("done_mask", "uint", 1)):
        d = ds[name]
        if d["shape"] != [N_WINDOWS] or d["dtype"]["kind"] != kind or d["dtype"]["size"] != size \
                or d["dtype"]["byte_order"] != "little" or d["layout"]["class"] != "contiguous" \
                or d["layout"]["size"] != N_WINDOWS * size or d["filters"]:
            fail(f"unexpected {name} metadata: {d}")
        aux[name] = (d["layout"]["address"], d["layout"]["size"])
    wa, ws = aux["window_idx"]
    if wa + ws > HEAD_BYTES:
        fail("window_idx is not inside the fetched head")
    window_idx = list(struct.unpack_from(f"<{N_WINDOWS}q", head, wa))
    return {"raw_address": lay["address"], "aux": aux, "window_idx": window_idx}


def tail_range(layout: dict) -> tuple[int, int]:
    (ta, tsz), (da, dsz) = layout["aux"]["token_stride"], layout["aux"]["done_mask"]
    if da != ta + tsz:
        fail("token_stride and done_mask are not adjacent")
    return ta, tsz + dsz


def read_tail(download_dir: Path, layout: dict) -> tuple[list[int], list[int]]:
    _, tlen = tail_range(layout)
    tail = (download_dir / "chr22_token_stride_done_mask.bin").read_bytes()
    if len(tail) != tlen:
        fail(f"metadata tail has {len(tail)} bytes, expected {tlen}")
    ts = list(struct.unpack_from(f"<{N_WINDOWS}i", tail, 0))
    dm = list(tail[N_WINDOWS * 4:N_WINDOWS * 5])
    return ts, dm


def window_path(download_dir: Path, w: int) -> Path:
    return download_dir / "chr22_raw_h_norm" / f"window_{w:03d}.f16"


def check_meta(layout: dict, ts: list[int], dm: list[int]) -> None:
    wi = layout["window_idx"]
    if any(b <= a for a, b in zip(wi, wi[1:])) or wi[0] < 0:
        fail("window_idx is not strictly increasing and non-negative")
    if set(dm) != {1}:
        fail(f"done_mask not all 1: {sorted(set(dm))}")
    if set(ts) != {EXPECT_TOKEN_STRIDE}:
        fail(f"token_stride not all {EXPECT_TOKEN_STRIDE}: {sorted(set(ts))}")


# --------------------------------------------------------------- statistics
def window_stats(data: bytes) -> dict:
    """Degeneracy and summary statistics of one (600, 4096) float16 window."""
    if len(data) != WINDOW_BYTES:
        fail(f"window has {len(data)} bytes, expected {WINDOW_BYTES}")
    nonfinite = data[1::2].translate(HALF_NONFINITE).count(1)
    codes = memoryview(data).cast("H")
    distinct = len(set(codes))
    low3 = sum(1 for c in codes if c & 7)
    vals = memoryview(data).cast("e")
    s = [0.0] * HIDDEN
    s2 = [0.0] * HIDDEN
    total = total2 = 0.0
    vmin, vmax = math.inf, -math.inf
    min_row_std = math.inf
    dup_rows = 0
    zeros = 0
    prev = None
    for r in range(N_TOKENS):
        row = vals[r * HIDDEN:(r + 1) * HIDDEN].tolist()
        raw = data[r * HIDDEN * 2:(r + 1) * HIDDEN * 2]
        if prev is not None and raw == prev:
            dup_rows += 1
        prev = raw
        rs = math.fsum(row)
        rs2 = math.fsum(x * x for x in row)
        total += rs
        total2 += rs2
        var = rs2 / HIDDEN - (rs / HIDDEN) ** 2
        min_row_std = min(min_row_std, math.sqrt(max(var, 0.0)))
        lo, hi = min(row), max(row)
        vmin, vmax = min(vmin, lo), max(vmax, hi)
        zeros += row.count(0.0)
        s = [a + b for a, b in zip(s, row)]
        s2 = [a + b * b for a, b in zip(s2, row)]
    n = float(N_TOKENS)
    spread_var = sum(max(q / n - (p / n) ** 2, 0.0) for p, q in zip(s, s2)) / HIDDEN
    return {
        "nonfinite": nonfinite,
        "distinct_codes": distinct,
        "low3_mantissa_nonzero": low3,
        "zeros": zeros,
        "min": vmin,
        "max": vmax,
        "mean": total / WINDOW_VALUES,
        "rms": math.sqrt(total2 / WINDOW_VALUES),
        "row_spread": math.sqrt(spread_var),
        "min_row_std": min_row_std,
        "dup_consecutive_rows": dup_rows,
    }


def check_stats(label: str, st: dict) -> None:
    if st["nonfinite"]:
        fail(f"{label}: {st['nonfinite']} non-finite float16 values")
    if st["distinct_codes"] < MIN_DISTINCT_CODES:
        fail(f"{label}: only {st['distinct_codes']} distinct codes")
    if st["row_spread"] < MIN_ROW_SPREAD:
        fail(f"{label}: near-constant token rows (row_spread {st['row_spread']:.5f})")
    if st["dup_consecutive_rows"] > MAX_DUP_ROWS:
        fail(f"{label}: {st['dup_consecutive_rows']} duplicated consecutive token rows")
    if st["min_row_std"] < MIN_ROW_STD:
        fail(f"{label}: a token row is near-constant (std {st['min_row_std']:.5f})")
    if not (0.1 < st["rms"] < 5.0) or st["max"] > 1000 or st["min"] < -1000:
        fail(f"{label}: implausible distribution rms={st['rms']:.4f} min={st['min']} max={st['max']}")


# --------------------------------------------------------------- commands
def cmd_plan(a) -> None:
    layout = load_layout(Path(a.head))
    ta, tlen = tail_range(layout)
    print(f"meta\t{ta}\t{tlen}\tchr22_token_stride_done_mask.bin")
    for w in range(N_WINDOWS):
        start = layout["raw_address"] + w * WINDOW_BYTES
        print(f"window\t{start}\t{WINDOW_BYTES}\tchr22_raw_h_norm/window_{w:03d}.f16")


def cmd_check(a) -> None:
    dd = Path(a.download_dir)
    layout = load_layout(dd / "chr22_tier3_raw.head.bin")
    ts, dm = read_tail(dd, layout)
    check_meta(layout, ts, dm)
    hashes = set()
    for w in range(N_WINDOWS):
        p = window_path(dd, w)
        if not p.is_file():
            fail(f"missing {p}")
        data = p.read_bytes()
        st = window_stats(data)
        check_stats(f"window {w} (window_idx {layout['window_idx'][w]})", st)
        hashes.add(sha256_bytes(data))
        print(f"ok window {w:03d} window_idx={layout['window_idx'][w]} rms={st['rms']:.4f} "
              f"row_spread={st['row_spread']:.4f} distinct={st['distinct_codes']}", flush=True)
    if len(hashes) != N_WINDOWS:
        fail("duplicate windows")
    print(f"download check passed: {N_WINDOWS} windows")


def index_row(rel: str, w: int, wid: int, stride: int, digest: str, st: dict) -> dict:
    return {
        "dataset_id": DATASET_ID,
        "series_id": SERIES_ID,
        "sample_path": rel,
        "numeric_kind": "float",
        "bit_width": 16,
        "endianness": "little",
        "element_size_bytes": 2,
        "sample_size_bytes": WINDOW_BYTES,
        "value_count": WINDOW_VALUES,
        "shape": [N_TOKENS, HIDDEN],
        "axes": ["token_position", "hidden_channel"],
        "chrom": CHROM,
        "window_local_index": w,
        "window_idx": wid,
        "token_stride": stride,
        "sha256": digest,
        "min": st["min"],
        "max": st["max"],
        "mean": round(st["mean"], 6),
        "rms": round(st["rms"], 6),
        "row_spread": round(st["row_spread"], 6),
        "distinct_codes": st["distinct_codes"],
        "zeros": st["zeros"],
        "low3_mantissa_nonzero": st["low3_mantissa_nonzero"],
    }


def cmd_build(a) -> None:
    dd = Path(a.download_dir)
    data_dir = Path(a.data_dir)
    out = Path(a.samples_dir) / SERIES_ID
    layout = load_layout(dd / "chr22_tier3_raw.head.bin")
    ts, dm = read_tail(dd, layout)
    check_meta(layout, ts, dm)
    out.mkdir(parents=True, exist_ok=True)
    for old in out.glob("*.f16"):
        old.unlink()
    rows = []
    for w in range(N_WINDOWS):
        data = window_path(dd, w).read_bytes()
        wid = layout["window_idx"][w]
        st = window_stats(data)
        check_stats(f"window {w} (window_idx {wid})", st)
        dest = out / f"{CHROM}_window{wid:05d}.f16"
        tmp = dest.with_suffix(".tmp")
        tmp.write_bytes(data)  # HDF5 stores IEEE binary16 little-endian: emitted verbatim
        os.replace(tmp, dest)
        rel = os.path.relpath(dest, data_dir)
        rows.append(index_row(rel, w, wid, ts[w], sha256_bytes(data), st))
        print(f"wrote {rel} rms={st['rms']:.4f} row_spread={st['row_spread']:.4f}", flush=True)
    if len({r["sha256"] for r in rows}) != N_WINDOWS:
        fail("duplicate windows")
    idx = Path(a.index)
    idx.parent.mkdir(parents=True, exist_ok=True)
    with open(idx, "w") as fh:
        for r in rows:
            fh.write(json.dumps(r, sort_keys=True) + "\n")
    stats = {
        "dataset_id": DATASET_ID,
        "revision": REVISION,
        "h5_file": H5_NAME,
        "raw_h_norm_address": layout["raw_address"],
        "sample_count": len(rows),
        "total_values": WINDOW_VALUES * len(rows),
        "total_size_bytes": WINDOW_BYTES * len(rows),
        "low3_mantissa_nonzero_total": sum(r["low3_mantissa_nonzero"] for r in rows),
        "zeros_total": sum(r["zeros"] for r in rows),
        "rms_range": [min(r["rms"] for r in rows), max(r["rms"] for r in rows)],
        "row_spread_range": [min(r["row_spread"] for r in rows), max(r["row_spread"] for r in rows)],
        "min": min(r["min"] for r in rows),
        "max": max(r["max"] for r in rows),
    }
    st_path = Path(a.stats)
    st_path.parent.mkdir(parents=True, exist_ok=True)
    st_path.write_text(json.dumps(stats, indent=1, sort_keys=True) + "\n")
    print(json.dumps(stats, sort_keys=True))


def cmd_verify(a) -> None:
    import tomllib

    dd = Path(a.download_dir)
    data_dir = Path(a.data_dir)
    manifest = tomllib.loads(Path(a.manifest).read_text())
    series = [s for s in manifest["series"] if s["id"] == SERIES_ID]
    if len(series) != 1:
        fail("manifest series missing")
    ms = series[0]
    # Independent re-derivation of the metadata straight from the head bytes.
    head = (dd / "chr22_tier3_raw.head.bin").read_bytes()
    desc = h5meta.describe_file(head)
    t = desc["datasets"][TARGET]
    if (t["dtype"]["kind"], t["dtype"]["size"], t["dtype"]["byte_order"], t["dtype"]["mant_size"],
            t["dtype"]["exp_size"]) != ("float", 2, "little", 10, 5):
        fail("raw_h_norm is not IEEE binary16 little-endian")
    if t["layout"]["class"] != "contiguous" or t["filters"]:
        fail("raw_h_norm is not contiguous/unfiltered")
    wa = desc["datasets"]["window_idx"]["layout"]["address"]
    window_idx = struct.unpack_from(f"<{N_WINDOWS}q", head, wa)
    ts, dm = read_tail(dd, {"aux": {k: (desc["datasets"][k]["layout"]["address"],
                                         desc["datasets"][k]["layout"]["size"])
                                     for k in ("token_stride", "done_mask")}})
    rows = [json.loads(line) for line in Path(a.index).read_text().splitlines() if line.strip()]
    if len(rows) != N_WINDOWS:
        fail(f"index has {len(rows)} rows")
    out = Path(a.samples_dir) / SERIES_ID
    files = sorted(out.glob("*.f16"))
    if len(files) != N_WINDOWS:
        fail(f"{len(files)} sample files in {out}")
    seen = set()
    total_bytes = 0
    for w, r in enumerate(rows):
        wid = window_idx[w]
        expect_rel = os.path.relpath(out / f"{CHROM}_window{wid:05d}.f16", data_dir)
        if r["sample_path"] != expect_rel or r["window_idx"] != wid or r["window_local_index"] != w:
            fail(f"index row {w} does not match window_idx {wid}")
        if dm[w] != 1 or ts[w] != EXPECT_TOKEN_STRIDE or r["token_stride"] != ts[w]:
            fail(f"window {w}: done_mask/token_stride mismatch")
        for k, v in (("dataset_id", DATASET_ID), ("series_id", SERIES_ID), ("numeric_kind", "float"),
                     ("bit_width", 16), ("endianness", "little"), ("element_size_bytes", 2),
                     ("sample_size_bytes", WINDOW_BYTES), ("value_count", WINDOW_VALUES)):
            if r[k] != v:
                fail(f"index row {w}: {k}={r[k]!r}")
        sample = (data_dir / r["sample_path"]).read_bytes()
        source = window_path(dd, w).read_bytes()
        if sample != source:
            fail(f"sample {w} differs from its downloaded HDF5 range")
        digest = sha256_bytes(sample)
        if digest != r["sha256"] or digest in seen:
            fail(f"sample {w}: sha256 mismatch or duplicate")
        seen.add(digest)
        st = window_stats(sample)
        check_stats(f"sample {w}", st)
        for k in ("min", "max", "distinct_codes", "zeros", "low3_mantissa_nonzero"):
            if st[k] != r[k]:
                fail(f"sample {w}: recomputed {k}={st[k]} != index {r[k]}")
        for k in ("mean", "rms", "row_spread"):
            if abs(round(st[k], 6) - r[k]) > 1e-6:
                fail(f"sample {w}: recomputed {k} {st[k]} != index {r[k]}")
        total_bytes += len(sample)
        print(f"verified {r['sample_path']}", flush=True)
    if ms["sample_count"] != N_WINDOWS or ms["total_size_bytes"] != total_bytes:
        fail(f"manifest totals {ms['sample_count']}/{ms['total_size_bytes']} != realized {N_WINDOWS}/{total_bytes}")
    if (ms["numeric_kind"], ms["bit_width"], ms["endianness"]) != ("float", 16, "little"):
        fail("manifest dtype mismatch")
    stats = json.loads(Path(a.stats).read_text())
    if stats["sample_count"] != N_WINDOWS or stats["total_size_bytes"] != total_bytes:
        fail("ingest stats totals do not match realized output")
    print(f"verify passed: {N_WINDOWS} samples, {total_bytes} bytes")


def cmd_selftest(a) -> None:
    """Exercise the HDF5 reader and the window statistics on synthetic data."""
    import random

    # float16 round trip and non-finite detection
    vals = [0.0, -0.0, 1.0, -2.5, 65504.0, 6.1e-05, 3.0e-08]
    b = struct.pack(f"<{len(vals)}e", *vals)
    assert list(memoryview(b).cast("e")) == list(struct.unpack(f"<{len(vals)}e", b))
    assert b.translate(HALF_NONFINITE)[1::2].count(1) == 0
    bad = struct.pack("<3e", 1.0, float("inf"), float("nan"))
    assert bad[1::2].translate(HALF_NONFINITE).count(1) == 2
    # statistics on a synthetic window: mean vector plus per-token noise
    rng = random.Random(7)
    base = [rng.gauss(0, 0.5) for _ in range(HIDDEN)]
    win = bytearray()
    for _ in range(N_TOKENS):
        win += struct.pack(f"<{HIDDEN}e", *[x + rng.gauss(0, 0.05) for x in base])
    st = window_stats(bytes(win))
    check_stats("synthetic", st)
    assert 0.04 < st["row_spread"] < 0.06, st
    flat = struct.pack(f"<{HIDDEN}e", *base) * N_TOKENS
    try:
        check_stats("flat", window_stats(flat))
    except SystemExit:
        pass
    else:
        raise AssertionError("constant-row window accepted")
    print("selftest ok")


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("plan")
    p.add_argument("--head", required=True)
    p = sub.add_parser("check")
    p.add_argument("--download-dir", required=True)
    for name in ("build", "verify"):
        p = sub.add_parser(name)
        p.add_argument("--data-dir", required=True)
        p.add_argument("--download-dir", required=True)
        p.add_argument("--samples-dir", required=True)
        p.add_argument("--index", required=True)
        p.add_argument("--stats", required=True)
        if name == "verify":
            p.add_argument("--manifest", required=True)
    sub.add_parser("selftest")
    a = ap.parse_args()
    {"plan": cmd_plan, "check": cmd_check, "build": cmd_build, "verify": cmd_verify,
     "selftest": cmd_selftest}[a.cmd](a)


if __name__ == "__main__":
    main()
