#!/usr/bin/env python3
"""Build / verify / self-test for stereo_a_impact_mag_rtn_bfield_f32.

Source: STEREO-A IMPACT/MAG Level-1 normal-mode daily CDFs
(STA_L1_MAG_RTN_YYYYMMDD_V06.cdf). The BFIELD zVariable is CDF_FLOAT with
dims (4,) = [BR, BT, BN, BTotal] in nT. Each daily file yields four separate
little-endian float32 samples, one per component.

Missing-value policy (shared by build and verify): a record is dropped from
all four series when any BFIELD component equals FILLVAL (float32 -1e31) or
is non-finite, or its Epoch equals the Epoch FILLVAL. Non-fill values outside
the CDF VALIDMIN/VALIDMAX are fatal. More than 5% dropped records in a day
is fatal.
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import math
import os
import struct
import sys
import tomllib
from array import array

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cdfread  # noqa: E402

DATASET_ID = "stereo_a_impact_mag_rtn_bfield_f32"
COMPONENTS = [
    ("sta_mag_rtn_br_f32", "BR"),
    ("sta_mag_rtn_bt_f32", "BT"),
    ("sta_mag_rtn_bn_f32", "BN"),
    ("sta_mag_rtn_btotal_f32", "BTotal"),
]
FILL_F32 = struct.unpack("<f", struct.pack("<f", -1e31))[0]
MAX_DROP_FRACTION = 0.05
MIN_KEPT_RECORDS = 100_000
EXPECTED_CADENCE_MS = (124.0, 126.0)
BTOTAL_ABS_TOL = 1e-3
BTOTAL_REL_TOL = 1e-5
BTOTAL_MIN_AGREEMENT = 0.999
MAX_OUTSIDE_DAY_RECORDS = 2400  # 5 minutes at 8 Hz
MS_PER_DAY = 86_400_000.0
SPILL = 10  # self-test only: synthetic next-day records


def day_bounds(utc_date: str) -> tuple[float, float]:
    """CDF_EPOCH (ms since 0000-01-01T00:00) bounds [lo, hi) of a YYYYMMDD UTC day."""
    d = datetime.date(int(utc_date[:4]), int(utc_date[4:6]), int(utc_date[6:8]))
    lo = (d.toordinal() - 1 + 366) * MS_PER_DAY
    return lo, lo + MS_PER_DAY


def log(msg: str) -> None:
    print(msg, flush=True)


def read_sources(path: str) -> list[dict]:
    rows = []
    with open(path) as f:
        header = f.readline().rstrip("\n").split("\t")
        for line in f:
            if line.strip():
                rows.append(dict(zip(header, line.rstrip("\n").split("\t"))))
    return rows


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def load_source(data_dir: str, row: dict) -> bytes:
    p = os.path.join(data_dir, "downloads", DATASET_ID, "cdf", row["filename"])
    raw = open(p, "rb").read()
    if len(raw) != int(row["size_bytes"]):
        raise SystemExit(f"size mismatch {row['filename']}: {len(raw)} != {row['size_bytes']}")
    if row.get("sha256") and sha256_bytes(raw) != row["sha256"]:
        raise SystemExit(f"sha256 mismatch {row['filename']}")
    return raw


def check_identity(c: cdfread.CDF, row: dict) -> dict:
    stem = row["filename"][:-4]
    g = c.global_attrs

    def g1(k):
        v = g.get(k)
        return v[0] if v else None

    problems = []
    if g1("Data_version") != "6":
        problems.append(f"Data_version={g1('Data_version')!r}")
    # CDF 3.x files written since late 2021 omit Logical_file_id; check it when present.
    if "Logical_file_id" in g and not (g1("Logical_file_id") or "").endswith(stem):
        problems.append(f"Logical_file_id={g1('Logical_file_id')!r}")
    if not (g1("Source_name") or "").startswith("Ahead"):
        problems.append(f"Source_name={g1('Source_name')!r}")
    if not (g1("Descriptor") or "").startswith("IMPACT_MAG"):
        problems.append(f"Descriptor={g1('Descriptor')!r}")
    for key in g:
        if key.lower() in ("rules_of_use", "license", "licence", "rights") and any(
                x not in (None, "", []) for x in g[key]):
            problems.append(f"restrictive-notice attribute {key}={g[key]!r}")
    for name in ("Epoch", "BFIELD", "CART_LABL_1"):
        if name not in c.zvars:
            problems.append(f"missing zVar {name}")
    if problems:
        raise SystemExit(f"{row['filename']}: identity check failed: {problems}")
    bf = c.zvars["BFIELD"]
    ep = c.zvars["Epoch"]
    va = c.var_attrs["BFIELD"]
    if bf.data_type != 44 or bf.dims != [4] or bf.num_elems != 1 or bf.dim_varys != [True]:
        raise SystemExit(f"{row['filename']}: BFIELD layout {bf.data_type} {bf.dims} {bf.num_elems}")
    if ep.data_type != 31 or ep.dims != []:
        raise SystemExit(f"{row['filename']}: Epoch layout {ep.data_type} {ep.dims}")
    if ep.max_rec != bf.max_rec:
        raise SystemExit(f"{row['filename']}: Epoch/BFIELD MaxRec differ {ep.max_rec} {bf.max_rec}")
    if va.get("UNITS") != "nT":
        raise SystemExit(f"{row['filename']}: BFIELD UNITS={va.get('UNITS')!r}")
    fv = va.get("FILLVAL")
    if not fv or struct.unpack("<f", struct.pack("<f", fv[0]))[0] != FILL_F32:
        raise SystemExit(f"{row['filename']}: BFIELD FILLVAL={fv!r}")
    labels = c.read_chars("CART_LABL_1")
    if labels != [lab for _, lab in COMPONENTS]:
        raise SystemExit(f"{row['filename']}: CART_LABL_1={labels!r}")
    vmin = va.get("VALIDMIN", [-1e4])[0]
    vmax = va.get("VALIDMAX", [1e6])[0]
    efill = (c.var_attrs["Epoch"].get("FILLVAL") or [-1e31])[0]
    return {"validmin": vmin, "validmax": vmax, "epoch_fill": efill,
            "max_rec": bf.max_rec, "labels": labels}


def apply_policy(fname: str, comps: list, epoch, meta: dict, utc_date: str) -> dict:
    """comps: four equal-length sequences (BR, BT, BN, BTotal) of float32 values.

    Records whose Epoch lies outside the file's UTC day [day_lo, day_hi) are
    dropped first (the CDF 3.7 files carry a few records of the next day, and
    at the 2023->2024 rollover those are a non-physical offset step). Then
    fill / non-finite records are dropped. Returns kept index list and
    statistics. Raises SystemExit on fatal issues.
    """
    n = len(epoch)
    vmin, vmax, efill = meta["validmin"], meta["validmax"], meta["epoch_fill"]
    day_lo, day_hi = day_bounds(utc_date)
    keep = []
    dropped_fill = 0
    dropped_outside_day = 0
    out_of_range = 0
    br, bt, bn, bm = comps
    for i in range(n):
        a, b, c, d = br[i], bt[i], bn[i], bm[i]
        if epoch[i] != efill and not (day_lo <= epoch[i] < day_hi):
            dropped_outside_day += 1
            continue
        if (a == FILL_F32 or b == FILL_F32 or c == FILL_F32 or d == FILL_F32
                or not (math.isfinite(a) and math.isfinite(b) and math.isfinite(c) and math.isfinite(d))
                or epoch[i] == efill):
            dropped_fill += 1
            continue
        if not (vmin <= a <= vmax and vmin <= b <= vmax and vmin <= c <= vmax and vmin <= d <= vmax):
            out_of_range += 1
            continue
        keep.append(i)
    if dropped_outside_day > MAX_OUTSIDE_DAY_RECORDS:
        raise SystemExit(f"{fname}: {dropped_outside_day} records outside UTC day {utc_date} "
                         f"(> {MAX_OUTSIDE_DAY_RECORDS})")
    if out_of_range:
        raise SystemExit(f"{fname}: {out_of_range} non-fill records outside VALIDMIN/VALIDMAX")
    if dropped_fill > MAX_DROP_FRACTION * n:
        raise SystemExit(f"{fname}: dropped {dropped_fill}/{n} fill records (> {MAX_DROP_FRACTION:.0%})")
    if len(keep) < MIN_KEPT_RECORDS:
        raise SystemExit(f"{fname}: only {len(keep)} kept records")
    # |B| consistency and cadence
    agree = 0
    for i in keep:
        s = math.sqrt(br[i] * br[i] + bt[i] * bt[i] + bn[i] * bn[i])
        if abs(bm[i] - s) <= BTOTAL_ABS_TOL + BTOTAL_REL_TOL * abs(bm[i]):
            agree += 1
    agreement = agree / len(keep)
    if agreement < BTOTAL_MIN_AGREEMENT:
        raise SystemExit(f"{fname}: BTotal agrees with |(BR,BT,BN)| for only {agreement:.5f}")
    deltas = sorted(epoch[keep[j + 1]] - epoch[keep[j]] for j in range(len(keep) - 1))
    median_dt = deltas[len(deltas) // 2]
    nonincreasing = sum(1 for x in deltas if x <= 0)
    if not (EXPECTED_CADENCE_MS[0] <= median_dt <= EXPECTED_CADENCE_MS[1]):
        raise SystemExit(f"{fname}: median cadence {median_dt} ms outside {EXPECTED_CADENCE_MS}")
    if nonincreasing > 0.001 * len(keep):
        raise SystemExit(f"{fname}: {nonincreasing} non-increasing Epoch steps")
    if not (day_lo <= epoch[keep[0]] < day_hi and day_lo <= epoch[keep[-1]] < day_hi):
        raise SystemExit(f"{fname}: kept Epoch range escapes UTC day {utc_date}")
    return {"keep": keep, "records": n, "dropped_fill": dropped_fill,
            "dropped_outside_day": dropped_outside_day,
            "btotal_agreement": agreement, "median_dt_ms": median_dt,
            "nonincreasing_epoch_steps": nonincreasing,
            "max_dt_ms": deltas[-1],
            "epoch_first": epoch[keep[0]], "epoch_last": epoch[keep[-1]]}


def decode_fast(c: cdfread.CDF):
    b = c.read_array("BFIELD")
    comps = [b[k::4] for k in range(4)]
    return comps, c.read_array("Epoch")


def decode_independent(c: cdfread.CDF):
    """Second decode path for verify: per-record struct unpacking of VVR bytes."""
    comps = [array("f") for _ in range(4)]
    for first, last, doff in c.segments("BFIELD"):
        n = last - first + 1
        chunk = c.data[doff: doff + 16 * n]
        for rec in struct.iter_unpack(">4f", chunk):
            for k in range(4):
                comps[k].append(rec[k])
    epoch = array("d")
    for first, last, doff in c.segments("Epoch"):
        n = last - first + 1
        epoch.extend(struct.unpack_from(f">{n}d", c.data, doff))
    return comps, epoch


def sample_rel(series_id: str, stem: str) -> str:
    return f"samples/{DATASET_ID}/{series_id}/{stem}.f32le.bin"


def series_bytes(comp, keep) -> bytes:
    a = array("f", (comp[i] for i in keep))
    if sys.byteorder != "little":
        a.byteswap()
    return a.tobytes()


def stats_of(raw: bytes) -> dict:
    a = array("f")
    a.frombytes(raw)
    if sys.byteorder != "little":
        a.byteswap()
    return {"min": min(a), "max": max(a), "distinct": len(set(a)), "n": len(a)}


# ---------------------------------------------------------------------------

def cmd_build(args) -> None:
    data_dir = os.path.join(args.repo_root, args.data_dir)
    rows = read_sources(args.sources)
    index_dir = os.path.join(data_dir, "index", DATASET_ID)
    filt_dir = os.path.join(data_dir, "filtered", DATASET_ID)
    os.makedirs(index_dir, exist_ok=True)
    os.makedirs(filt_dir, exist_ok=True)
    for sid, _ in COMPONENTS:
        d = os.path.join(data_dir, "samples", DATASET_ID, sid)
        os.makedirs(d, exist_ok=True)
        for f in os.listdir(d):
            os.remove(os.path.join(d, f))
    index_rows = []
    per_file = []
    agg = hashlib.sha256()
    for row in rows:
        raw = load_source(data_dir, row)
        c = cdfread.CDF(raw)
        meta = check_identity(c, row)
        comps, epoch = decode_fast(c)
        if len(epoch) != meta["max_rec"] + 1 or any(len(x) != len(epoch) for x in comps):
            raise SystemExit(f"{row['filename']}: record count mismatch vs MaxRec")
        st = apply_policy(row["filename"], comps, epoch, meta, row["date"])
        stem = row["filename"][:-4]
        keep = st.pop("keep")
        for k, (sid, label) in enumerate(COMPONENTS):
            out = series_bytes(comps[k], keep)
            s = stats_of(out)
            if s["min"] == s["max"] or s["distinct"] < 1000:
                raise SystemExit(f"{stem} {sid}: degenerate (distinct={s['distinct']})")
            rel = sample_rel(sid, stem)
            with open(os.path.join(data_dir, rel), "wb") as f:
                f.write(out)
            h = sha256_bytes(out)
            agg.update(h.encode())
            index_rows.append({
                "dataset_id": DATASET_ID, "series_id": sid, "sample_path": rel,
                "numeric_kind": "float", "bit_width": 32, "endianness": "little",
                "element_size_bytes": 4, "sample_size_bytes": len(out),
                "value_count": len(out) // 4, "source_file": row["filename"],
                "source_field": f"BFIELD[{k}] ({label})", "utc_date": row["date"],
                "min": s["min"], "max": s["max"], "sha256": h,
            })
        st.update({"filename": row["filename"], "kept": len(keep),
                   "cdf_version": "%d.%d" % c.version,
                   "bfield_catdesc": c.var_attrs["BFIELD"].get("CATDESC")})
        per_file.append(st)
        log(f"built {stem}: records={st['records']} kept={len(keep)} dropped_fill={st['dropped_fill']} "
            f"dropped_outside_day={st['dropped_outside_day']} "
            f"median_dt={st['median_dt_ms']:.3f}ms btotal_agree={st['btotal_agreement']:.6f}")
    with open(os.path.join(index_dir, "samples.jsonl"), "w") as f:
        for r in index_rows:
            f.write(json.dumps(r, sort_keys=True) + "\n")
    totals = {}
    for r in index_rows:
        t = totals.setdefault(r["series_id"], {"sample_count": 0, "total_size_bytes": 0, "value_count": 0})
        t["sample_count"] += 1
        t["total_size_bytes"] += r["sample_size_bytes"]
        t["value_count"] += r["value_count"]
    summary = {"dataset_id": DATASET_ID, "files": len(rows), "per_series": totals,
               "total_records": sum(p["records"] for p in per_file),
               "total_kept": sum(p["kept"] for p in per_file),
               "total_dropped_fill": sum(p["dropped_fill"] for p in per_file),
               "total_dropped_outside_day": sum(p["dropped_outside_day"] for p in per_file),
               "aggregate_sha256": agg.hexdigest(), "per_file": per_file}
    with open(os.path.join(filt_dir, "ingest_stats.json"), "w") as f:
        json.dump(summary, f, indent=1, sort_keys=True)
    log(json.dumps({k: v for k, v in summary.items() if k != "per_file"}, sort_keys=True))


def cmd_verify(args) -> None:
    data_dir = os.path.join(args.repo_root, args.data_dir)
    rows = read_sources(args.sources)
    manifest = tomllib.load(open(args.manifest, "rb"))
    idx_path = os.path.join(data_dir, "index", DATASET_ID, "samples.jsonl")
    index = [json.loads(x) for x in open(idx_path) if x.strip()]
    by_path = {r["sample_path"]: r for r in index}
    if len(by_path) != len(index):
        raise SystemExit("duplicate sample paths in index")
    expected_paths = set()
    hashes = set()
    totals = {sid: [0, 0] for sid, _ in COMPONENTS}
    for row in rows:
        raw = load_source(data_dir, row)
        c = cdfread.CDF(raw)
        meta = check_identity(c, row)
        comps, epoch = decode_independent(c)
        if len(epoch) != meta["max_rec"] + 1 or any(len(x) != len(epoch) for x in comps):
            raise SystemExit(f"{row['filename']}: record count mismatch vs MaxRec")
        st = apply_policy(row["filename"], comps, epoch, meta, row["date"])
        keep = st["keep"]
        stem = row["filename"][:-4]
        day_lo, day_hi = day_bounds(row["date"])
        if not (day_lo <= epoch[keep[0]] < day_hi and day_lo <= epoch[keep[-1]] < day_hi):
            raise SystemExit(f"{stem}: first/last kept Epoch outside UTC day {row['date']}")
        for k, (sid, _) in enumerate(COMPONENTS):
            rel = sample_rel(sid, stem)
            expected_paths.add(rel)
            r = by_path.get(rel)
            if r is None:
                raise SystemExit(f"missing index row {rel}")
            out = open(os.path.join(data_dir, rel), "rb").read()
            want = struct.pack(f"<{len(keep)}f", *(comps[k][i] for i in keep))
            if out != want:
                raise SystemExit(f"{rel}: bytes differ from independent re-decode")
            s = stats_of(out)
            if s["min"] == s["max"] or s["distinct"] < 1000:
                raise SystemExit(f"{rel}: degenerate")
            h = sha256_bytes(out)
            if h in hashes:
                raise SystemExit(f"{rel}: duplicate sample content")
            hashes.add(h)
            checks = {"dataset_id": DATASET_ID, "series_id": sid, "numeric_kind": "float",
                      "bit_width": 32, "endianness": "little", "element_size_bytes": 4,
                      "sample_size_bytes": len(out), "value_count": len(keep),
                      "min": s["min"], "max": s["max"], "sha256": h}
            for key, val in checks.items():
                if r.get(key) != val:
                    raise SystemExit(f"{rel}: index {key}={r.get(key)!r} expected {val!r}")
            totals[sid][0] += 1
            totals[sid][1] += len(out)
        log(f"verified {stem}: kept={len(keep)} dropped_fill={st['dropped_fill']} "
            f"dropped_outside_day={st['dropped_outside_day']}")
    if set(by_path) != expected_paths:
        raise SystemExit(f"index has unexpected rows: {sorted(set(by_path) - expected_paths)[:5]}")
    for sid, _ in COMPONENTS:
        d = os.path.join(data_dir, "samples", DATASET_ID, sid)
        on_disk = {f"samples/{DATASET_ID}/{sid}/{f}" for f in os.listdir(d)}
        if on_disk != {p for p in expected_paths if f"/{sid}/" in p}:
            raise SystemExit(f"{sid}: stray or missing sample files")
    mseries = {s["id"]: s for s in manifest["series"]}
    for sid, (cnt, size) in totals.items():
        m = mseries.get(sid)
        if m is None:
            raise SystemExit(f"manifest lacks series {sid}")
        if m["sample_count"] != cnt or m["total_size_bytes"] != size:
            raise SystemExit(f"{sid}: manifest sample_count/total_size_bytes {m['sample_count']}/"
                             f"{m['total_size_bytes']} != realized {cnt}/{size}")
    total = sum(v[1] for v in totals.values())
    if total > 1_000_000_000:
        raise SystemExit(f"primary output {total} exceeds 1 GB")
    log(f"verify ok: files={len(rows)} samples={len(index)} bytes={total}")


# ---------------------------------------------------------------------------

def cmd_selftest(args) -> None:
    import random
    rng = random.Random(1234)
    nrec = 1000
    recs = bytearray()
    exp = [[], [], [], []]
    epoch_be = bytearray()
    fill_rows = {17, 500, 999}

    for i in range(nrec):
        br, bt, bn = (rng.uniform(-8, 8) for _ in range(3))
        r = [struct.unpack(">f", struct.pack(">f", x))[0] for x in (br, bt, bn)]
        r.append(struct.unpack(">f", struct.pack(">f", math.sqrt(sum(x * x for x in r))))[0])
        if i in fill_rows:
            r[i % 4] = FILL_F32
        recs += struct.pack(">4f", *r)
        for k in range(4):
            exp[k].append(r[k])
        # The last SPILL records fall into the next UTC day and must be trimmed.
        epoch_be += struct.pack(">d", day_bounds("20990101")[1] - 125.0 * (nrec - SPILL) + 125.0 * i)
    labels = b"BR    BT    BN    BTotal"
    split = [100, 1, 250, 64, 300, 285]
    vars_spec = [
        {"name": "Epoch", "dtype": 31, "dims": [], "records": bytes(epoch_be), "nrec": nrec},
        {"name": "BFIELD", "dtype": 44, "dims": [4], "records": bytes(recs), "nrec": nrec},
        {"name": "CART_LABL_1", "dtype": 51, "dims": [4], "records": labels, "nrec": 1},
    ]
    vars_spec[2]["num_elems"] = 6

    def be(fmt, *v):
        return struct.pack(">" + fmt, *v)

    attrs = [
        {"name": "Data_version", "scope": 1, "entries": [(None, 51, b"6", 1)]},
        {"name": "Logical_file_id", "scope": 1,
         "entries": [(None, 51, b"work/STA_L1_MAG_RTN_20990101_V06", 32)]},
        {"name": "Source_name", "scope": 1, "entries": [(None, 51, b"Ahead>test", 10)]},
        {"name": "Descriptor", "scope": 1, "entries": [(None, 51, b"IMPACT_MAG>test", 15)]},
        {"name": "FILLVAL", "scope": 2,
         "entries": [(0, 31, be("d", -1e31), 1), (1, 44, be("f", -1e31), 1)]},
        {"name": "UNITS", "scope": 2, "entries": [(0, 51, b"ms", 2), (1, 51, b"nT", 2)]},
        {"name": "VALIDMIN", "scope": 2, "entries": [(1, 44, be("f", -10000.0), 1)]},
        {"name": "VALIDMAX", "scope": 2, "entries": [(1, 44, be("f", 1e6), 1)]},
    ]
    vars_spec[2]["nrv"] = True
    for v3 in (False, True):
        _selftest_layout(v3, vars_spec, attrs, split, nrec, exp, fill_rows)


def _selftest_layout(v3, vars_spec, attrs, split, nrec, exp, fill_rows) -> None:
    tag = "v3" if v3 else "v2"
    data = cdfread.write_synthetic(vars_spec, attrs, [split, split[::-1], [1]], v3=v3)
    c = cdfread.CDF(data)
    assert c.v3 == v3 and c.version[0] == (3 if v3 else 2)
    segs = c.segments("BFIELD")
    starts = [sum(split[::-1][:j]) for j in range(len(split))]
    assert [s[0] for s in segs] == starts, segs
    assert [s[0] for s in c.segments("Epoch")] == [sum(split[:j]) for j in range(len(split))]
    assert c.allocated_records["BFIELD"] == nrec
    assert c.read_chars("CART_LABL_1") == ["BR", "BT", "BN", "BTotal"], c.read_chars("CART_LABL_1")
    row = {"filename": "STA_L1_MAG_RTN_20990101_V06.cdf"}
    meta = check_identity(c, row)
    comps_a, ep_a = decode_fast(c)
    comps_b, ep_b = decode_independent(c)
    for k in range(4):
        assert list(comps_a[k]) == exp[k] == list(comps_b[k]), (tag, k)
    assert list(ep_a) == list(ep_b) and len(ep_a) == nrec
    global MIN_KEPT_RECORDS
    saved, MIN_KEPT_RECORDS = MIN_KEPT_RECORDS, 10
    try:
        st = apply_policy("synthetic", comps_a, ep_a, meta, "20990101")
    finally:
        MIN_KEPT_RECORDS = saved
    spill_fill = sum(1 for r in fill_rows if r >= nrec - SPILL)
    assert st["dropped_outside_day"] == SPILL, st["dropped_outside_day"]
    assert st["dropped_fill"] == len(fill_rows) - spill_fill, st["dropped_fill"]
    assert len(st["keep"]) == nrec - SPILL - len(fill_rows) + spill_fill
    assert max(st["keep"]) == nrec - SPILL - 1
    try:
        apply_policy("synthetic", comps_a, ep_a, meta, "20990102")  # wrong day: 990 outside
    except SystemExit:
        pass
    else:
        raise AssertionError("wrong-day trim not fatal")
    assert abs(st["median_dt_ms"] - 125.0) < 1e-9
    out = series_bytes(comps_a[0], st["keep"])
    want = struct.pack(f"<{len(st['keep'])}f", *(exp[0][i] for i in st["keep"]))
    assert out == want
    # Corruptions must be rejected.
    ofmt, osz = (">q", 8) if v3 else (">i", 4)
    hdr = osz + 4
    bad = bytearray(data)
    struct.pack_into(ofmt, bad, c.gdr_offset + hdr + 3 * osz, len(data) + 4)  # GDR eof
    for mutated, label in ((bytes(bad), "eof"), (data[:-10], "truncated")):
        try:
            cdfread.CDF(mutated)
        except cdfread.CDFError:
            pass
        else:
            raise AssertionError(f"{tag}: corruption not detected: {label}")
    bf = c.zvars["BFIELD"]
    bad = bytearray(data)
    struct.pack_into(">i", bad, bf.offset + hdr + osz + 4, nrec + 50)  # MaxRec beyond coverage
    assert cdfread.CDF(bytes(bad)).zvars["BFIELD"].max_rec == nrec + 50
    try:
        cdfread.CDF(bytes(bad)).segments("BFIELD")
    except cdfread.CDFError:
        pass
    else:
        raise AssertionError(f"{tag}: coverage shortfall not detected")
    log(f"selftest ok ({tag} layout): {len(segs)} VVR segments across chained+child VXRs, "
        f"{nrec} records, {st['dropped_outside_day']} next-day records trimmed, "
        f"{st['dropped_fill']} fill records dropped, both decode paths agree")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("command", choices=["build", "verify", "selftest"])
    ap.add_argument("--repo-root", default=".")
    ap.add_argument("--data-dir", default=".data")
    ap.add_argument("--sources")
    ap.add_argument("--manifest")
    args = ap.parse_args()
    {"build": cmd_build, "verify": cmd_verify, "selftest": cmd_selftest}[args.command](args)


if __name__ == "__main__":
    main()
