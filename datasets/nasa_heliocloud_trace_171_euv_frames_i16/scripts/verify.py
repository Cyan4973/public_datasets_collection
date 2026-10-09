#!/usr/bin/env python3
"""Independent verification of the TRACE 171 A full-frame samples.

Does not import trace_fits.py or build.py. Re-implements the FITS header walk, the
header regime, struct-based pixel decoding, the tick-lattice and JPEG-cell metrics and
the degeneracy checks; re-derives the kept set over the whole pinned pool and requires
it to equal the index; byte-compares every sample; checks index rows, manifest totals,
uniqueness and scope.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import statistics
import struct
import tomllib
from pathlib import Path

DATASET_ID = "nasa_heliocloud_trace_171_euv_frames_i16"
SERIES_ID = "trace_171_full_frame_dn_i16"
W = H = 1024
N = W * H
FILE_SIZE = 2_105_280
MIN_SAMPLES = 20
MIN_MONTHS = 5

CARD_RE = re.compile(r"^([A-Z0-9_-]{1,8})\s*= +(.*)$")
HIST_OK = [
    re.compile(r"^HISTORY trace_prep\s+Replaced\s+\d+ saturated pixels with value > 4100\s*$"),
    re.compile(r"^HISTORY tr_dark_sub VERSION:\s+2\.10 Subtracted dark pedestal and current\s*$"),
    re.compile(r"^HISTORY tr_flat_sub VERSION:\s+1\.60 Image divided by corrected flat field\s*$"),
    re.compile(r"^HISTORY trace_wave2point\s+XYOffsets:\s+-?\d+\.\d+\s+-?\d+\.\d+\s*$"),
]


def walk_header(blob: bytes):
    kw, hist = {}, []
    for blk in range(0, len(blob), 2880):
        block = blob[blk:blk + 2880].decode("ascii")
        for j in range(36):
            card = block[80 * j:80 * (j + 1)]
            if card.rstrip() == "END":
                return kw, hist, blk + 2880
            if card.startswith("HISTORY"):
                hist.append(card.rstrip())
                continue
            m = CARD_RE.match(card)
            if not m:
                continue
            raw = m.group(2).strip()
            if raw.startswith("'"):
                kw[m.group(1)] = raw[1:raw.index("'", 1)].strip()
            else:
                kw[m.group(1)] = raw.split("/")[0].strip()
    raise ValueError("no END card")


def program_kind(name: str) -> str:
    if name == "cjs.caldc171" or "lossless" in name or name.endswith("Q0"):
        return "allowlisted"
    return "conditional" if name == "ras.jpeg171.aecm4" else "excluded"


def header_ok(kw: dict, hist: list[str]) -> list[str]:
    bad = []
    if program_kind(kw.get("FRM_NAM", "")) == "excluded":
        bad.append(f"FRM_NAM {kw.get('FRM_NAM')!r} not near-lossless")
    expect = {"SIMPLE": "T", "BITPIX": "16", "NAXIS": "2", "NAXIS1": "1024", "NAXIS2": "1024",
              "TELESCOP": "TRACE", "INSTRUME": "TRACE", "WAVE_LEN": "171", "AMP": "A",
              "SUM_CCDX": "1", "SUM_CCDY": "1", "BIN_CCD": "1", "TBIN_CCD": "1", "SOU_AREA": "0"}
    for k, v in expect.items():
        if kw.get(k) != v:
            bad.append(f"{k}={kw.get(k)!r}")
    for k in ("BZERO", "BSCALE", "BLANK", "NAXIS3", "PBADPIX"):
        if k in kw:
            bad.append(f"has {k}")
    if float(kw.get("SRI_LLEX", "nan")) != 0 or float(kw.get("SRI_LLEY", "nan")) != 0:
        bad.append("SRI extract offset")
    if abs(float(kw.get("PERCENTD", "0")) - 100) > 1e-6:
        bad.append("PERCENTD")
    if float(kw.get("SHT_MDUR", "0")) < 1.0 or float(kw.get("IMG_MAX", "0")) < 300:
        bad.append("exposure/IMG_MAX")
    d = kw.get("DATE_OBS", "")
    if not ("1998-04-20" <= d[:10] <= "1998-10-31"):
        bad.append(f"DATE_OBS {d}")
    names = []
    for line in hist:
        for idx, rx in enumerate(HIST_OK):
            if rx.match(line):
                names.append(idx)
                break
        else:
            bad.append(f"history {line[:40]!r}")
    if names not in ([0, 1, 2, 3], [1, 2, 3]):
        bad.append(f"history order {names}")
    return bad


def metrics(vals) -> dict:
    hist = [0] * 65536
    for v in vals:
        hist[v + 32768] += 1
    c = lambda k: hist[k + 32768]
    elig = 0
    holes = []
    worst = (None, None)
    for k in range(-60, 1501):
        m = min(c(k - 1), c(k + 1))
        if m >= 300:
            elig += 1
            if worst[1] is None or c(k) / m < worst[1]:
                worst = (k, c(k) / m)
            if 2 * c(k) < m:
                holes.append(k)
    # ringing: 8x8 cells with origin rows/cols 8..1008 step 8
    spikes = []
    for y0 in range(8, 1016, 8):
        for x0 in range(8, 1016, 8):
            cell = [vals[y * W + x] for y in range(y0, y0 + 8) for x in range(x0, x0 + 8)]
            if max(cell) > 400:
                med = statistics.median(cell)
                if med < 60:
                    spikes.append(min(cell) - med)
    ring_d = statistics.median(spikes) if spikes else None
    below = sum(hist[:32768 - 15])
    distinct = sum(1 for x in hist if x)
    dom = max(hist)
    # horizontal cell-boundary ratio, column-pair decomposition
    hb = hi = 0
    cols = [vals[x::W] for x in range(W)]
    for x in range(W - 1):
        s = sum(abs(p - q) for p, q in zip(cols[x], cols[x + 1]))
        if x % 8 == 7:
            hb += s
        else:
            hi += s
    hr = (hb / (127 * H)) / (hi / (896 * H))
    # vertical ratio, row-pair decomposition
    vb = vi = 0
    for y in range(H - 1):
        a = vals[y * W:(y + 1) * W]
        b = vals[(y + 1) * W:(y + 2) * W]
        s = sum(abs(p - q) for p, q in zip(a, b))
        if y % 8 == 7:
            vb += s
        else:
            vi += s
    vr = (vb / (127 * W)) / (vi / (896 * W))
    const_rows = sum(1 for y in range(H) if len(set(vals[y * W:(y + 1) * W])) == 1)
    const_cols = sum(1 for col in cols if len(set(col)) == 1)
    return {"elig": elig, "holes": holes, "distinct": distinct, "dom": dom / N,
            "zero": c(0) / N, "hr": hr, "vr": vr, "const": const_rows + const_cols,
            "min": min(vals), "max": max(vals), "worst_k": worst[0], "worst_r": worst[1],
            "spikes": len(spikes), "ring_d": ring_d, "below": below}


def passes(m: dict, program: str) -> bool:
    kind = program_kind(program)
    if kind == "excluded":
        return False
    need = 20 if kind == "conditional" else 5
    if m["spikes"] >= 5 and not m["ring_d"] > -15:
        return False
    if m["spikes"] < need and (kind != "allowlisted" or m["below"] > 0):
        return False
    return (m["elig"] >= 8 and not m["holes"] and 0.80 <= m["hr"] <= 1.06 and 0.80 <= m["vr"] <= 1.06
            and m["dom"] <= 0.15 and m["zero"] <= 0.15 and m["distinct"] >= 256
            and m["const"] == 0)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", type=Path, required=True)
    ap.add_argument("--recipe-dir", type=Path, required=True)
    a = ap.parse_args()
    root = a.data_dir
    manifest = tomllib.loads((a.recipe_dir / "manifest.toml").read_text())
    series = [s for s in manifest["series"] if s["id"] == SERIES_ID]
    if len(series) != 1 or len(manifest["series"]) != 1:
        raise SystemExit("manifest must declare exactly the one primary series")
    series = series[0]
    pins = list(csv.DictReader(open(a.recipe_dir / "sources.tsv", newline=""), delimiter="\t"))
    plan = {r["filename"]: r for r in csv.DictReader(
        open(root / "downloads" / DATASET_ID / "download_plan.tsv", newline=""), delimiter="\t")}
    rows = [json.loads(line) for line in open(root / "index" / DATASET_ID / "samples.jsonl")]
    by_path = {r["sample_path"]: r for r in rows}
    if len(by_path) != len(rows):
        raise SystemExit("duplicate sample_path in index")

    derived = {}
    for i, pin in enumerate(pins, 1):
        name = pin["filename"]
        blob = (root / "downloads" / DATASET_ID / "fits" / name).read_bytes()
        if len(blob) != FILE_SIZE or hashlib.md5(blob).hexdigest() != pin["md5_etag"]:
            raise SystemExit(f"{name}: size/MD5 mismatch")
        if hashlib.sha256(blob).hexdigest() != plan[name]["sha256"]:
            raise SystemExit(f"{name}: SHA-256 mismatch")
        kw, hist, off = walk_header(blob)
        bad = header_ok(kw, hist)
        stamp = name[15:30]
        d = kw.get("DATE_OBS", "")
        if d[:19].replace("-", "").replace("T", "_").replace(":", "") != stamp:
            bad.append("filename stamp != DATE_OBS")
        if off != 5760:
            bad.append(f"data offset {off}")
        if bad:
            raise SystemExit(f"{name}: header regime violated: {bad}")
        vals = struct.unpack(">%dh" % N, blob[off:off + 2 * N])
        if any(blob[off + 2 * N:]):
            raise SystemExit(f"{name}: non-zero padding")
        m = metrics(vals)
        if passes(m, kw.get("FRM_NAM", "")):
            derived[f"samples/{DATASET_ID}/{SERIES_ID}/{name[:-4]}.i16"] = (pin, vals, m)
        if i % 25 == 0:
            print(f"progress {i}/{len(pins)} derived_kept={len(derived)}", flush=True)

    if set(derived) != set(by_path):
        raise SystemExit(f"selection mismatch: only_derived={sorted(set(derived) - set(by_path))[:5]} "
                         f"only_index={sorted(set(by_path) - set(derived))[:5]}")
    total = 0
    months = set()
    for path, (pin, vals, m) in sorted(derived.items()):
        r = by_path[path]
        expect = {"dataset_id": DATASET_ID, "series_id": SERIES_ID, "numeric_kind": "int",
                  "bit_width": 16, "endianness": "little", "element_size_bytes": 2,
                  "sample_size_bytes": 2 * N, "value_count": N, "source_key": pin["key"],
                  "date_obs": pin["date_obs"], "min": m["min"], "max": m["max"],
                  "n_spike_cells": m["spikes"], "ring_d": m["ring_d"],
                  "lattice_worst_k": m["worst_k"], "lattice_tested_bins": m["elig"]}
        for k, v in expect.items():
            if r.get(k) != v:
                raise SystemExit(f"{path}: index {k}={r.get(k)!r} != {v!r}")
        if abs(r["lattice_worst_ratio"] - round(m["worst_r"], 6)) > 1e-9:
            raise SystemExit(f"{path}: lattice_worst_ratio mismatch")
        payload = (root / path).read_bytes()
        if payload != struct.pack("<%dh" % N, *vals):
            raise SystemExit(f"{path}: sample bytes differ from re-decoded FITS pixels")
        if hashlib.sha256(payload).hexdigest() != r["sha256"]:
            raise SystemExit(f"{path}: sha256 mismatch")
        if m["max"] == m["min"] or m["distinct"] < 256:
            raise SystemExit(f"{path}: degenerate sample")
        total += len(payload)
        months.add(pin["date_obs"][:7])
    extra = {p.name for p in (root / "samples" / DATASET_ID / SERIES_ID).iterdir()} - \
            {Path(p).name for p in by_path}
    if extra:
        raise SystemExit(f"unindexed files in sample dir: {sorted(extra)[:5]}")
    hashes = [r["sha256"] for r in rows]
    if len(set(hashes)) != len(hashes):
        raise SystemExit("duplicate sample payloads")
    if series["sample_count"] != len(rows) or series["total_size_bytes"] != total:
        raise SystemExit(f"manifest totals {series['sample_count']}/{series['total_size_bytes']} "
                         f"!= realized {len(rows)}/{total}")
    if len(rows) < MIN_SAMPLES or len(months) < MIN_MONTHS:
        raise SystemExit(f"scope too thin: {len(rows)} samples over {len(months)} months")
    print(f"verify_ok samples={len(rows)} bytes={total} months={sorted(months)} pool={len(pins)}")


if __name__ == "__main__":
    main()
