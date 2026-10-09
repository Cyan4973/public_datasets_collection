#!/usr/bin/env python3
"""Build / verify ISIS-2 SFS average ionograms (ULA Fairbanks, 1974) as raw
uint8 sounder-receiver video amplitude rasters.

Commands:
  validate  check that every downloaded CDF parses and carries the expected
            'ampl' variable (used by download.sh to reject invalid payloads)
  build     decode, apply the declared completeness rule, write samples+index
  verify    independently re-decode every source, re-apply the rule, and check
            the samples, index, manifest totals and degeneracy guards
"""

import argparse
import collections
import hashlib
import json
import math
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cdf26  # noqa: E402

DATASET_ID = "spdf_isis2_topside_ionogram_amplitude_u8"
AMPL_SERIES = "isis2_ula1974_ampl_u8"
FREQ_SERIES = "isis2_ula1974_freq_f64"
N_DELAY = 223
EXPECTED_SOURCES = 1604
EXPECTED_SOURCE_BYTES = 304729594

# Declared completeness rule (see manifest / README).
MIN_ROWS = 500
MAX_ROWS = 1100
MAX_TRAILER = 4
FREQ_FILL_LIMIT = -1.0e30
SWEEP_LOW_MAX_MHZ = 0.11
SWEEP_TOP_MIN_MHZ = 9.5
SWEEP_TOP_MAX_MHZ = 10.6

# Degeneracy guards for primary samples.
MIN_DISTINCT = 32
MAX_MODE_SHARE = 0.5
MAX_ZERO_ROW_SHARE = 0.05


def read_sources(path):
    rows = []
    with open(path) as fh:
        header = fh.readline().rstrip("\n").split("\t")
        if header != ["key", "filename", "size_bytes", "md5", "last_modified"]:
            raise SystemExit(f"unexpected sources.tsv header {header}")
        for line in fh:
            key, fn, size, md5, lm = line.rstrip("\n").split("\t")
            rows.append({"key": key, "filename": fn, "size": int(size), "md5": md5})
    if len(rows) != EXPECTED_SOURCES:
        raise SystemExit(f"sources.tsv has {len(rows)} rows, expected {EXPECTED_SOURCES}")
    if sum(r["size"] for r in rows) != EXPECTED_SOURCE_BYTES:
        raise SystemExit("sources.tsv byte total mismatch")
    return rows


def open_cdf(path):
    with open(path, "rb") as fh:
        data = fh.read()
    return cdf26.CDF(data), data


def check_structure(c):
    """Hard structural expectations for every file of this product."""
    a = c.zvars.get("ampl")
    if a is None:
        raise cdf26.CDFError("no ampl variable")
    if a.data_type != 11 or tuple(a.dims) != (N_DELAY,) or tuple(a.dim_varys) != (-1,):
        raise cdf26.CDFError(f"ampl type/dims {a.data_type} {a.dims} {a.dim_varys}")
    if not a.flags & 1:
        raise cdf26.CDFError("ampl is not record-variant")
    if a.pad_value is not None:
        raise cdf26.CDFError("ampl unexpectedly declares a pad value")
    if a.num_elems != 1:
        raise cdf26.CDFError("ampl NumElems != 1")
    if c.compression(a) != 5:
        raise cdf26.CDFError("ampl is not GZIP-compressed")
    fill = c.zattr_value("FILLVAL", "ampl")
    if fill != -128:
        raise cdf26.CDFError(f"ampl FILLVAL {fill!r} != -128")
    if c.zattr_value("VALIDMIN", "ampl") != 0 or c.zattr_value("VALIDMAX", "ampl") != 255:
        raise cdf26.CDFError("ampl VALIDMIN/VALIDMAX not 0/255")
    for name in ("Epoch", "freq", "vh_num", "f_num", "year"):
        if name not in c.zvars:
            raise cdf26.CDFError(f"missing variable {name}")
    if c.zvars["freq"].max_rec != a.max_rec or c.zvars["Epoch"].max_rec != a.max_rec:
        raise cdf26.CDFError("Epoch/freq/ampl MaxRec disagree")


def decode(path):
    """Return a dict describing one ionogram and the keep/drop decision."""
    c, data = open_cdf(path)
    check_structure(c)
    raw, nrec = c.read_raw("ampl")
    vh = c.read_values("vh_num")[0]
    fnum = c.read_values("f_num")[0]
    year = c.read_values("year")[0]
    epoch = c.read_values("Epoch")
    freq = c.read_values("freq")
    if fnum != N_DELAY:
        raise cdf26.CDFError(f"f_num {fnum} != {N_DELAY}")
    if year not in (74, 1974):  # stored as two-digit year in this product
        raise cdf26.CDFError(f"year {year} is not 1974")
    info = {"records": nrec, "vh_num": vh, "trimmed_trailer": 0}
    reason = None
    if nrec == vh:
        rows = vh
    elif 0 < vh < nrec <= vh + MAX_TRAILER:
        # Writer artifact: records written past vh_num carry an all-zero
        # amplitude row, freq 0.0 and an Epoch reset to the ionogram start.
        tail = raw[vh * N_DELAY:]
        if (tail.count(0) != len(tail)
                or any(x != 0.0 for x in freq[vh:])
                or any(x != epoch[0] for x in epoch[vh:])):
            reason = "trailing_records_not_zero_artifact"
        rows = vh
        info["trimmed_trailer"] = nrec - vh
    else:
        reason = "maxrec_vh_num_mismatch"
        rows = min(vh, nrec)
    info["rows"] = rows
    f = freq[:rows]
    e = epoch[:rows]
    if reason is None and not MIN_ROWS <= rows <= MAX_ROWS:
        reason = "row_count_out_of_range"
    if reason is None and any(x < FREQ_FILL_LIMIT for x in f):
        reason = "freq_fill"
    if reason is None and not all(math.isfinite(x) and 0.0 < x <= SWEEP_TOP_MAX_MHZ for x in f):
        reason = "freq_out_of_range"
    if reason is None and min(f) > SWEEP_LOW_MAX_MHZ:
        reason = "sweep_start_missing"
    if reason is None and max(f) < SWEEP_TOP_MIN_MHZ:
        reason = "sweep_truncated"
    if reason is None and not all(b > a for a, b in zip(e, e[1:])):
        reason = "epoch_not_increasing"
    if reason is None and zero_rows(raw[:rows * N_DELAY]) > MAX_ZERO_ROW_SHARE * rows:
        # heavy telemetry dropout / interleaved empty frames (e.g. day-079
        # 1.95 MHz runs with every other fixed-frequency row empty)
        reason = "too_many_zero_rows"
    info["reason"] = reason or "kept"
    info["keep"] = reason is None
    info["ampl"] = raw[:rows * N_DELAY]
    info["freq"] = f
    info["source_sha256"] = hashlib.sha256(data).hexdigest()
    if info["keep"]:
        info["fmin"], info["fmax"] = min(f), max(f)
        info["duration_s"] = (e[-1] - e[0]) / 1000.0
    return info


def zero_rows(ampl):
    z = bytes(N_DELAY)
    return sum(1 for i in range(0, len(ampl), N_DELAY) if ampl[i:i + N_DELAY] == z)


def sample_checks(name, ampl):
    if len(ampl) % N_DELAY or not ampl:
        raise SystemExit(f"{name}: ampl length {len(ampl)} not a multiple of {N_DELAY}")
    cnt = collections.Counter(ampl)
    if len(cnt) < MIN_DISTINCT:
        raise SystemExit(f"{name}: only {len(cnt)} distinct amplitude codes")
    mode_share = cnt.most_common(1)[0][1] / len(ampl)
    if mode_share > MAX_MODE_SHARE:
        raise SystemExit(f"{name}: one code covers {mode_share:.3f} of the sample")
    if zero_rows(ampl) > MAX_ZERO_ROW_SHARE * (len(ampl) // N_DELAY):
        raise SystemExit(f"{name}: too many all-zero amplitude rows")
    return cnt


def paths(args):
    root = os.path.join(args.repo_root, args.data_dir)
    return {
        "root": root,
        "src": os.path.join(root, "downloads", DATASET_ID, "cdf"),
        "samples": os.path.join(root, "samples", DATASET_ID),
        "index": os.path.join(root, "index", DATASET_ID),
        "filtered": os.path.join(root, "filtered", DATASET_ID),
    }


def cmd_validate(args):
    p = paths(args)
    sources = read_sources(args.sources)
    bad = 0
    for s in sources:
        fp = os.path.join(p["src"], s["filename"])
        try:
            c, _ = open_cdf(fp)
            check_structure(c)
            c.read_raw("ampl")
        except (cdf26.CDFError, OSError, struct.error) as exc:
            bad += 1
            print(f"INVALID {s['filename']}: {exc}", file=sys.stderr)
    if bad:
        raise SystemExit(f"{bad} invalid CDF payloads")
    print(f"validated {len(sources)} CDF payloads: ampl CDF_UINT1 [223], GZIP CVVR, MaxRec coverage ok")


def iter_decoded(p, sources):
    for s in sources:
        fp = os.path.join(p["src"], s["filename"])
        if os.path.getsize(fp) != s["size"]:
            raise SystemExit(f"size mismatch {s['filename']}")
        yield s, decode(fp)


def cmd_build(args):
    p = paths(args)
    sources = read_sources(args.sources)
    for d in (p["index"], p["filtered"]):
        os.makedirs(d, exist_ok=True)
    adir = os.path.join(p["samples"], AMPL_SERIES)
    fdir = os.path.join(p["samples"], FREQ_SERIES)
    for d in (adir, fdir):
        os.makedirs(d, exist_ok=True)
        for fn in os.listdir(d):
            os.remove(os.path.join(d, fn))
    index_rows = []
    sel_lines = ["filename\tsource_sha256\trecords\tvh_num\trows\ttrimmed_trailer\tdecision"]
    reasons = collections.Counter()
    hist = collections.Counter()
    total_vals = 0
    for s, info in iter_decoded(p, sources):
        reasons[info["reason"]] += 1
        sel_lines.append("\t".join(str(x) for x in (
            s["filename"], info["source_sha256"], info["records"], info["vh_num"],
            info["rows"], info["trimmed_trailer"], info["reason"])))
        if not info["keep"]:
            continue
        stem = s["filename"][:-len(".cdf")]
        ampl = info["ampl"]
        cnt = sample_checks(stem, ampl)
        hist.update(cnt)
        rel_a = f"samples/{DATASET_ID}/{AMPL_SERIES}/{stem}.u8"
        with open(os.path.join(p["root"], rel_a), "wb") as fh:
            fh.write(ampl)
        freq_le = struct.pack("<%dd" % len(info["freq"]), *info["freq"])
        rel_f = f"samples/{DATASET_ID}/{FREQ_SERIES}/{stem}.f64"
        with open(os.path.join(p["root"], rel_f), "wb") as fh:
            fh.write(freq_le)
        rows = info["rows"]
        total_vals += len(ampl)
        index_rows.append({
            "dataset_id": DATASET_ID, "series_id": AMPL_SERIES, "role": "primary",
            "sample_path": rel_a, "numeric_kind": "uint", "bit_width": 8,
            "endianness": "little", "element_size_bytes": 1,
            "sample_size_bytes": len(ampl), "value_count": len(ampl),
            "shape": [rows, N_DELAY], "source_key": s["key"],
            "source_sha256": info["source_sha256"],
            "sha256": hashlib.sha256(ampl).hexdigest(),
            "min": min(cnt), "max": max(cnt), "distinct": len(cnt),
            "share_255": round(cnt[255] / len(ampl), 6), "share_0": round(cnt[0] / len(ampl), 6),
            "zero_rows": zero_rows(ampl), "trimmed_trailer": info["trimmed_trailer"],
        })
        index_rows.append({
            "dataset_id": DATASET_ID, "series_id": FREQ_SERIES, "role": "auxiliary",
            "sample_path": rel_f, "numeric_kind": "float", "bit_width": 64,
            "endianness": "little", "element_size_bytes": 8,
            "sample_size_bytes": len(freq_le), "value_count": rows,
            "shape": [rows], "source_key": s["key"],
            "source_sha256": info["source_sha256"],
            "sha256": hashlib.sha256(freq_le).hexdigest(),
            "min": info["fmin"], "max": info["fmax"],
        })
    with open(os.path.join(p["index"], "samples.jsonl"), "w") as fh:
        for r in index_rows:
            fh.write(json.dumps(r, sort_keys=True) + "\n")
    with open(os.path.join(p["filtered"], "selection.tsv"), "w") as fh:
        fh.write("\n".join(sel_lines) + "\n")
    prim = [r for r in index_rows if r["role"] == "primary"]
    aux = [r for r in index_rows if r["role"] == "auxiliary"]
    sizes = sorted(r["value_count"] for r in prim)
    n_all = sum(hist.values())
    stats = {
        "sources": len(sources), "decisions": dict(reasons),
        "primary_samples": len(prim), "primary_bytes": sum(r["sample_size_bytes"] for r in prim),
        "aux_samples": len(aux), "aux_bytes": sum(r["sample_size_bytes"] for r in aux),
        "median_values": sizes[len(sizes) // 2] if sizes else 0,
        "min_values": sizes[0] if sizes else 0, "max_values": sizes[-1] if sizes else 0,
        "share_0": hist[0] / n_all if n_all else 0, "share_255": hist[255] / n_all if n_all else 0,
        "distinct_codes": len(hist),
    }
    with open(os.path.join(p["filtered"], "ingest_stats.json"), "w") as fh:
        json.dump(stats, fh, indent=2, sort_keys=True)
    print(json.dumps(stats, indent=2, sort_keys=True))
    if not prim:
        raise SystemExit("no ionograms kept")


def manifest_series(path):
    """Tiny TOML subset reader: pull id/sample_count/total_size_bytes per [[series]]."""
    out = {}
    cur = None
    with open(path) as fh:
        for line in fh:
            line = line.strip()
            if line == "[[series]]":
                cur = {}
                continue
            if line.startswith("[") and line != "[[series]]":
                cur = None
                continue
            if cur is None or "=" not in line:
                continue
            k, v = (x.strip() for x in line.split("=", 1))
            if k == "id":
                cur["id"] = v.strip('"')
                out[cur["id"]] = cur
            elif k in ("sample_count", "total_size_bytes"):
                cur[k] = int(v)
    return out


def cmd_verify(args):
    p = paths(args)
    sources = read_sources(args.sources)
    idx_path = os.path.join(p["index"], "samples.jsonl")
    with open(idx_path) as fh:
        index = [json.loads(l) for l in fh if l.strip()]
    by_path = {r["sample_path"]: r for r in index}
    if len(by_path) != len(index):
        raise SystemExit("duplicate sample_path in index")
    required = ["dataset_id", "series_id", "sample_path", "numeric_kind", "bit_width",
                "endianness", "element_size_bytes", "sample_size_bytes", "value_count"]
    for r in index:
        for k in required:
            if k not in r:
                raise SystemExit(f"index row missing {k}: {r.get('sample_path')}")
        if r["dataset_id"] != DATASET_ID:
            raise SystemExit("index dataset_id mismatch")
    expected = set()
    seen_hashes = set()
    totals = collections.Counter()
    counts = collections.Counter()
    kept = 0
    for s, info in iter_decoded(p, sources):
        stem = s["filename"][:-len(".cdf")]
        rel_a = f"samples/{DATASET_ID}/{AMPL_SERIES}/{stem}.u8"
        rel_f = f"samples/{DATASET_ID}/{FREQ_SERIES}/{stem}.f64"
        if not info["keep"]:
            if rel_a in by_path or rel_f in by_path:
                raise SystemExit(f"{stem}: dropped by rule ({info['reason']}) but present in index")
            continue
        kept += 1
        expected.update((rel_a, rel_f))
        ampl = info["ampl"]
        with open(os.path.join(p["root"], rel_a), "rb") as fh:
            got = fh.read()
        if got != ampl:
            raise SystemExit(f"{stem}: ampl sample differs from re-decoded CDF")
        cnt = sample_checks(stem, got)
        ra = by_path.get(rel_a)
        if ra is None:
            raise SystemExit(f"{stem}: kept ionogram missing from index")
        h = hashlib.sha256(got).hexdigest()
        if (ra["series_id"], ra["numeric_kind"], ra["bit_width"], ra["element_size_bytes"]) != (AMPL_SERIES, "uint", 8, 1):
            raise SystemExit(f"{stem}: bad ampl index typing")
        if ra["sample_size_bytes"] != len(got) or ra["value_count"] != len(got) or ra["sha256"] != h:
            raise SystemExit(f"{stem}: ampl index size/hash mismatch")
        if ra["min"] != min(cnt) or ra["max"] != max(cnt) or ra["shape"] != [info["rows"], N_DELAY]:
            raise SystemExit(f"{stem}: ampl index stats mismatch")
        if h in seen_hashes:
            raise SystemExit(f"{stem}: duplicate sample content")
        seen_hashes.add(h)
        # rare interior all-zero rows are telemetry dropouts kept as source;
        # many of them would mean a degenerate ionogram
        zr = zero_rows(ampl)
        if zr > MAX_ZERO_ROW_SHARE * info["rows"] or ra.get("zero_rows") != zr:
            raise SystemExit(f"{stem}: {zr} all-zero rows (index says {ra.get('zero_rows')})")
        with open(os.path.join(p["root"], rel_f), "rb") as fh:
            fgot = fh.read()
        fexp = struct.pack("<%dd" % len(info["freq"]), *info["freq"])
        rf = by_path.get(rel_f)
        if fgot != fexp or rf is None or rf["sha256"] != hashlib.sha256(fgot).hexdigest() \
                or rf["value_count"] != info["rows"] or rf["role"] != "auxiliary":
            raise SystemExit(f"{stem}: freq auxiliary sample/index mismatch")
        totals[AMPL_SERIES] += len(got)
        counts[AMPL_SERIES] += 1
        totals[FREQ_SERIES] += len(fgot)
        counts[FREQ_SERIES] += 1
    extra = set(by_path) - expected
    if extra:
        raise SystemExit(f"index has {len(extra)} unexpected rows, e.g. {sorted(extra)[0]}")
    for series in (AMPL_SERIES, FREQ_SERIES):
        d = os.path.join(p["samples"], series)
        on_disk = {f"samples/{DATASET_ID}/{series}/{fn}" for fn in os.listdir(d)}
        if on_disk != {x for x in expected if f"/{series}/" in x}:
            raise SystemExit(f"{series}: stray or missing sample files on disk")
    man = manifest_series(args.manifest)
    for series in (AMPL_SERIES, FREQ_SERIES):
        m = man.get(series)
        if m is None:
            raise SystemExit(f"manifest lacks series {series}")
        if m.get("sample_count") != counts[series] or m.get("total_size_bytes") != totals[series]:
            raise SystemExit(f"manifest {series}: sample_count/total_size_bytes {m.get('sample_count')}/"
                             f"{m.get('total_size_bytes')} != realized {counts[series]}/{totals[series]}")
    prim_sizes = sorted(r["value_count"] for r in index if r["series_id"] == AMPL_SERIES)
    median = prim_sizes[len(prim_sizes) // 2]
    if totals[AMPL_SERIES] < 100_000 or median < 1000:
        raise SystemExit("primary payload below repository floor")
    if totals[AMPL_SERIES] > 1_000_000_000:
        raise SystemExit("primary payload exceeds 1 GB cap")
    print(f"verify ok: kept {kept}/{len(sources)} ionograms; primary {counts[AMPL_SERIES]} samples "
          f"{totals[AMPL_SERIES]} bytes (median {median} values); auxiliary freq "
          f"{counts[FREQ_SERIES]} samples {totals[FREQ_SERIES]} bytes")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("command", choices=["validate", "build", "verify"])
    ap.add_argument("--repo-root", required=True)
    ap.add_argument("--data-dir", required=True)
    ap.add_argument("--sources", required=True)
    ap.add_argument("--manifest")
    args = ap.parse_args()
    {"validate": cmd_validate, "build": cmd_build, "verify": cmd_verify}[args.command](args)


if __name__ == "__main__":
    main()
