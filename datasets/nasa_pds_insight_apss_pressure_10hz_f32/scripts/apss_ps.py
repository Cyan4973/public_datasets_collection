#!/usr/bin/env python3
"""InSight APSS PS calibrated pressure (10 Hz full-sol CSV) -> float32 samples.

Commands:
  plan             write a curl --config for missing/partial files; promote
                   complete .part files whose size and MD5 match files.tsv
  check-downloads  validate every downloaded CSV (size, label MD5, header,
                   9 fields, record count, PRESSURE decimals, 10 Hz cadence)
  build            emit one raw little-endian float32 sample per sol file

Pure standard library.  Row policy (shared with verify_apss.py):
  * a row whose PRESSURE field is empty is dropped (counted);
  * a row with PRESSURE present but PRESSURE_FREQUENCY != "10.0" is dropped
    (counted); more than MAX_NON10_FRACTION of a file's rows is fatal;
  * PRESSURE must match ^[0-9]{3,4}\\.[0-9]{4}$, lie in [PMIN, PMAX] Pa and
    round-trip through float32 to the same 4-decimal string; else fatal.
"""
import argparse
import hashlib
import json
import math
import os
import re
import struct
import sys
from array import array
from pathlib import Path

DATASET_ID = "nasa_pds_insight_apss_pressure_10hz_f32"
SERIES_ID = "insight_apss_pressure_10hz_f32"
BASE_URL = "https://atmos.nmsu.edu/PDS/data/PDS4/InSight/ps_bundle/data_calibrated"
HEADER = b"AOBT,SCLK,LMST,LTST,UTC,PRESSURE,PRESSURE_FREQUENCY,PRESSURE_TEMP,PRESSURE_TEMP_FREQUENCY\r\n"
PRESSURE_RE = re.compile(rb"^[0-9]{3,4}\.[0-9]{4}$")
PMIN, PMAX = 100.0, 1500.0
MAX_NON10_FRACTION = 0.01
MIN_DISTINCT = 1000
PACK = struct.Struct("<f")


class RecipeError(Exception):
    pass


def read_inventory(path):
    rows = []
    with open(path, encoding="utf-8") as fh:
        hdr = fh.readline().rstrip("\n").split("\t")
        for ln in fh:
            if not ln.strip():
                continue
            r = dict(zip(hdr, ln.rstrip("\n").split("\t")))
            r["size_bytes"] = int(r["size_bytes"])
            r["records"] = int(r["records"])
            r["header_bytes"] = int(r["header_bytes"])
            r["sol"] = int(r["sol"])
            rows.append(r)
    if not rows:
        raise RecipeError("empty inventory")
    return rows


def md5_of(path):
    h = hashlib.md5()
    with open(path, "rb") as fh:
        for blk in iter(lambda: fh.read(1 << 22), b""):
            h.update(blk)
    return h.hexdigest()


def file_url(row):
    return f"{BASE_URL}/{row['dir']}/{row['file']}"


def check_bytes(path, row):
    size = path.stat().st_size
    if size != row["size_bytes"]:
        raise RecipeError(f"{row['file']}: size {size} != pinned {row['size_bytes']}")
    got = md5_of(path)
    if got != row["md5"]:
        raise RecipeError(f"{row['file']}: md5 {got} != label md5 {row['md5']}")


def decode_csv(raw, row):
    """Return (array('f') of kept pressures, stats dict).  Fatal on structure errors."""
    name = row["file"]
    if not raw.startswith(HEADER) or len(HEADER) != row["header_bytes"]:
        raise RecipeError(f"{name}: unexpected header")
    if not raw.endswith(b"\r\n"):
        raise RecipeError(f"{name}: file does not end with CRLF")
    body = raw[len(HEADER):-2].split(b"\r\n")
    if len(body) != row["records"]:
        raise RecipeError(f"{name}: {len(body)} records != label {row['records']}")
    out = array("f")
    blank = non10 = 0
    freq_counts = {}
    prev_aobt = None
    nonincreasing = 0
    for i, line in enumerate(body):
        f = line.split(b",")
        if len(f) != 9:
            raise RecipeError(f"{name}: record {i} has {len(f)} fields")
        try:
            aobt = float(f[0])
        except ValueError:
            raise RecipeError(f"{name}: record {i} malformed AOBT {f[0]!r}")
        if prev_aobt is not None and aobt <= prev_aobt:
            nonincreasing += 1
        prev_aobt = aobt
        p = f[5]
        if not p:
            blank += 1
            continue
        fq = f[6]
        if fq != b"10.0":
            non10 += 1
            key = fq.decode("ascii", "replace")
            freq_counts[key] = freq_counts.get(key, 0) + 1
            continue
        if not PRESSURE_RE.match(p):
            raise RecipeError(f"{name}: record {i} malformed PRESSURE {p!r}")
        v = float(p)
        if not (PMIN <= v <= PMAX):
            raise RecipeError(f"{name}: record {i} PRESSURE {v} outside [{PMIN},{PMAX}]")
        out.append(v)
    if non10 > MAX_NON10_FRACTION * len(body):
        raise RecipeError(f"{name}: {non10} non-10 Hz rows ({freq_counts}); not a 10 Hz file")
    if sys.byteorder != "little":
        out.byteswap()
    # float32 round trip to the source 4-decimal lattice (checked on every value)
    payload = out.tobytes()
    if sys.byteorder != "little":
        out.byteswap()
    j = 0
    for line in body:
        f = line.split(b",")
        if not f[5] or f[6] != b"10.0":
            continue
        if ("%.4f" % out[j]).encode() != f[5]:
            raise RecipeError(f"{name}: float32 {out[j]!r} does not round-trip to {f[5]!r}")
        j += 1
    n = len(out)
    if n < 1000:
        raise RecipeError(f"{name}: only {n} kept values")
    distinct = len(set(out))
    if distinct < MIN_DISTINCT:
        raise RecipeError(f"{name}: degenerate ({distinct} distinct values)")
    mean = math.fsum(out) / n
    std = math.sqrt(math.fsum((x - mean) ** 2 for x in out) / n)
    if std <= 0.0:
        raise RecipeError(f"{name}: constant series")
    stats = {
        "file": name, "sol": row["sol"], "records": len(body),
        "kept": n, "blank_pressure_rows": blank, "non_10hz_rows": non10,
        "non_10hz_frequencies": freq_counts, "aobt_nonincreasing_steps": nonincreasing,
        "min": min(out), "max": max(out), "mean": round(mean, 6), "std": round(std, 6),
        "distinct": distinct,
    }
    return payload, stats


def cmd_plan(a):
    rows = read_inventory(a.inventory)
    d = Path(a.downloads) / "csv"
    d.mkdir(parents=True, exist_ok=True)
    pending = []
    for r in rows:
        final = d / r["file"]
        part = d / (r["file"] + ".part")
        if final.exists():
            if final.stat().st_size == r["size_bytes"]:
                continue
            print(f"removing wrong-size {final.name}")
            final.unlink()
        if part.exists():
            sz = part.stat().st_size
            if sz == r["size_bytes"]:
                if md5_of(part) == r["md5"]:
                    part.rename(final)
                    continue
                print(f"removing {part.name}: md5 mismatch")
                part.unlink()
            elif sz > r["size_bytes"]:
                print(f"removing oversized {part.name}")
                part.unlink()
        pending.append(r)
    with open(a.config, "w", encoding="utf-8") as fh:
        for r in pending:
            fh.write(f'url = "{file_url(r)}"\n')
            fh.write(f'output = "{d / (r["file"] + ".part")}"\n')
    print(f"plan: {len(rows) - len(pending)} complete, {len(pending)} pending")


def cmd_check_downloads(a):
    rows = read_inventory(a.inventory)
    d = Path(a.downloads) / "csv"
    for k, r in enumerate(rows, 1):
        p = d / r["file"]
        if not p.is_file():
            raise RecipeError(f"missing download {r['file']}")
        check_bytes(p, r)
        _, st = decode_csv(p.read_bytes(), r)
        print(f"checked {k}/{len(rows)} {r['file']} kept={st['kept']} blank={st['blank_pressure_rows']} "
              f"non10={st['non_10hz_rows']} range=[{st['min']:.4f},{st['max']:.4f}]")
    print(f"check-downloads: {len(rows)} files valid")


def cmd_build(a):
    root = Path(a.data_root)
    rows = read_inventory(a.inventory)
    dl = root / "downloads" / DATASET_ID / "csv"
    sdir = root / "samples" / DATASET_ID / SERIES_ID
    idir = root / "index" / DATASET_ID
    fdir = root / "filtered" / DATASET_ID
    for p in (sdir, idir, fdir):
        p.mkdir(parents=True, exist_ok=True)
    for old in sdir.glob("*"):
        old.unlink()
    index, stats_all = [], []
    for k, r in enumerate(rows, 1):
        p = dl / r["file"]
        if not p.is_file():
            raise RecipeError(f"missing download {r['file']}")
        check_bytes(p, r)
        payload, st = decode_csv(p.read_bytes(), r)
        out = sdir / (r["file"][:-4] + ".f32")
        tmp = out.with_suffix(".f32.tmp")
        tmp.write_bytes(payload)
        tmp.rename(out)
        index.append({
            "dataset_id": DATASET_ID, "series_id": SERIES_ID,
            "sample_path": str(out.relative_to(root)),
            "numeric_kind": "float", "bit_width": 32, "endianness": "little",
            "element_size_bytes": 4, "sample_size_bytes": len(payload),
            "value_count": st["kept"],
            "source_file": r["file"], "source_md5": r["md5"], "sol": r["sol"],
            "source_records": st["records"], "blank_pressure_rows": st["blank_pressure_rows"],
            "non_10hz_rows": st["non_10hz_rows"],
            "min": st["min"], "max": st["max"],
            "sha256": hashlib.sha256(payload).hexdigest(),
        })
        stats_all.append(st)
        print(f"[{k}/{len(rows)}] {out.name} values={st['kept']} blank={st['blank_pressure_rows']} "
              f"non10={st['non_10hz_rows']} range=[{st['min']:.4f},{st['max']:.4f}] std={st['std']}")
    with open(idir / "samples.jsonl", "w", encoding="utf-8") as fh:
        for e in index:
            fh.write(json.dumps(e, sort_keys=True) + "\n")
    summary = {
        "dataset_id": DATASET_ID, "files": len(rows),
        "samples": len(index),
        "total_values": sum(e["value_count"] for e in index),
        "total_bytes": sum(e["sample_size_bytes"] for e in index),
        "blank_pressure_rows": sum(s["blank_pressure_rows"] for s in stats_all),
        "non_10hz_rows": sum(s["non_10hz_rows"] for s in stats_all),
        "per_file": stats_all,
    }
    (fdir / "ingest_stats.json").write_text(json.dumps(summary, indent=1, sort_keys=True) + "\n")
    vals = sorted(e["value_count"] for e in index)
    print(f"build: samples={summary['samples']} values={summary['total_values']} "
          f"bytes={summary['total_bytes']} median_values={vals[len(vals) // 2]} "
          f"blank_dropped={summary['blank_pressure_rows']} non10_dropped={summary['non_10hz_rows']}")


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("plan")
    p.add_argument("--inventory", required=True)
    p.add_argument("--downloads", required=True)
    p.add_argument("--config", required=True)
    p = sub.add_parser("check-downloads")
    p.add_argument("--inventory", required=True)
    p.add_argument("--downloads", required=True)
    p = sub.add_parser("build")
    p.add_argument("--inventory", required=True)
    p.add_argument("--data-root", required=True)
    a = ap.parse_args()
    try:
        {"plan": cmd_plan, "check-downloads": cmd_check_downloads, "build": cmd_build}[a.cmd](a)
    except RecipeError as e:
        print(f"FATAL: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
