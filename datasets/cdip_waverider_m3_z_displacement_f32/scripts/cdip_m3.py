#!/usr/bin/env python3
"""Validate downloaded CDIP DWR-M3 windows and build little-endian heave samples.

Subcommands:
  check-das  <das_file> <deployment>                 validate DWR-M3 title + license
  check-dods <dods_file> <start_index> <value_count> validate one window response
  build --windows TSV --downloads DIR --data-root DIR --dataset-id ID --series-id SID
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import struct
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cdip_dods  # noqa: E402

M3_PHRASE = "collected in situ by Datawell DWR-M3 directional buoy located near"
LICENSE = "These data may be redistributed and used without restriction."
RATE = struct.unpack(">f", struct.pack(">f", 1.28))[0]
FILL = struct.unpack(">f", struct.pack(">f", -999.99))[0]
ABS_LIMIT_M = 20.47  # DAS valid range is +-20.47 m
GOOD_PRIMARY = (1, 2)  # 1 good, 2 not_evaluated (the archive default for xyz)


def read_windows(path: str) -> list[dict]:
    with open(path, encoding="utf-8") as fh:
        header = fh.readline().rstrip("\n").split("\t")
        rows = [dict(zip(header, ln.rstrip("\n").split("\t"))) for ln in fh if ln.strip()]
    for r in rows:
        for k in ("xyz_count", "start_index", "value_count", "window_start_unix"):
            r[k] = int(r[k])
    return rows


def check_das(path: str, deployment: str) -> dict:
    text = open(path, encoding="utf-8", errors="strict").read()
    if "NC_GLOBAL" not in text:
        raise SystemExit(f"{path}: not a DAS response")
    title = re.search(r'String title "([^"]*)"', text)
    lic = re.search(r'String license "([^"]*)"', text)
    if not title or M3_PHRASE not in title.group(1):
        raise SystemExit(f"{path}: title does not identify a Datawell DWR-M3 buoy")
    if not lic or lic.group(1) != LICENSE:
        raise SystemExit(f"{path}: license attribute differs from pinned grant")
    station = deployment.split("_")[0]
    sid = re.search(r'String cdip_station_id "([^"]*)"', text)
    if not sid or sid.group(1).zfill(3) != station[:3]:
        raise SystemExit(f"{path}: cdip_station_id does not match {station}")
    block = re.search(r"\n\s*xyzZDisplacement \{(.*?)\n\s*\}", text, re.S)
    if not block or not re.search(r"Float32 _FillValue -999\.99;", block.group(1)):
        raise SystemExit(f"{path}: xyzZDisplacement block missing or _FillValue is not -999.99")
    if not re.search(r'String units "m(eter|etre)?s?"', block.group(1)):
        raise SystemExit(f"{path}: xyzZDisplacement units are not metres")
    return {"title": title.group(1)}


def decode_window(path: str, start: int, count: int) -> dict:
    with open(path, "rb") as fh:
        buf = fh.read()
    r = cdip_dods.parse(buf)
    need = {"xyzStartTime", "xyzSampleRate", "xyzFilterDelay", "xyzFlagPrimary", "xyzFlagSecondary", "xyzZDisplacement"}
    if set(r) != need:
        raise ValueError(f"{path}: unexpected variables {sorted(r)}")
    if r["xyzSampleRate"] != RATE:
        raise ValueError(f"{path}: xyzSampleRate {r['xyzSampleRate']} != 1.28")
    typ, zraw = r["xyzZDisplacement"]
    if typ != "Float32" or len(zraw) != 4 * count:
        raise ValueError(f"{path}: xyzZDisplacement is not {count} Float32 values")
    fp, fs = r["xyzFlagPrimary"], r["xyzFlagSecondary"]
    if len(fp) != count or len(fs) != count:
        raise ValueError(f"{path}: flag arrays are not {count} long")
    bad_p = sum(1 for x in fp if x not in GOOD_PRIMARY)
    bad_s = sum(1 for x in fs if x != 0)
    if bad_p or bad_s:
        raise ValueError(f"{path}: {bad_p} primary flags outside {{1,2}}, {bad_s} nonzero secondary flags")
    z = cdip_dods.unpack_be("Float32", zraw)
    nfill = sum(1 for v in z if v == FILL)
    if nfill:
        raise ValueError(f"{path}: {nfill} _FillValue samples")
    if any(v != v or abs(v) > ABS_LIMIT_M for v in z):
        raise ValueError(f"{path}: NaN or |z| > {ABS_LIMIT_M} m")
    # Degeneracy policy (identical to verify_m3.py), evaluated on the whole
    # window: calm sheltered sites legitimately have long low-amplitude
    # stretches, so only stuck/flat sensors are rejected.
    distinct = len(set(zraw[i : i + 4] for i in range(0, len(zraw), 4)))
    if distinct < 50:
        raise ValueError(f"{path}: degenerate ({distinct} distinct values in window)")
    mean = sum(z) / len(z)
    sd = (sum((v - mean) ** 2 for v in z) / len(z)) ** 0.5
    if sd < 0.02 or abs(mean) > 0.5:
        raise ValueError(f"{path}: degenerate heave statistics (mean {mean:.3f} m, sd {sd:.4f} m)")
    longest = run = 1
    for a_, b_ in zip(z, z[1:]):
        run = run + 1 if a_ == b_ else 1
        if run > longest:
            longest = run
    if longest > 256:
        raise ValueError(f"{path}: stuck run of {longest} identical values")
    return {
        "start_time": r["xyzStartTime"],
        "filter_delay": r["xyzFilterDelay"],
        "zraw_be": zraw,
        "z": z,
        "flag_primary_good": sum(1 for x in fp if x == 1),
    }


def build(args: argparse.Namespace) -> None:
    rows = read_windows(args.windows)
    root = os.path.abspath(args.data_root)
    out_dir = os.path.join(root, "samples", args.dataset_id, args.series_id)
    idx_path = os.path.join(root, "index", args.dataset_id, "samples.jsonl")
    stats_path = os.path.join(root, "filtered", args.dataset_id, "ingest_stats.json")
    for p in (out_dir, os.path.dirname(idx_path), os.path.dirname(stats_path)):
        os.makedirs(p, exist_ok=True)
    for name in os.listdir(out_dir):
        if name.endswith(".bin"):
            os.remove(os.path.join(out_dir, name))
    agg = hashlib.sha256()
    index_rows = []
    total_values = 0
    lattice_hits = 0
    for r in rows:
        dep, a, n = r["deployment"], r["start_index"], r["value_count"]
        das = check_das(os.path.join(args.downloads, "das", f"{dep}.das"), dep)
        w = decode_window(os.path.join(args.downloads, "dods", f"{dep}_{a}_{n}.dods"), a, n)
        le = cdip_dods.be32_to_le(w["zraw_be"])
        stored = struct.unpack(f"<{n}f", le)
        if stored != w["z"]:
            raise SystemExit(f"{dep}: byte-swap round trip mismatch")
        rel = f"samples/{args.dataset_id}/{args.series_id}/{dep}.bin"
        with open(os.path.join(root, rel) + ".part", "wb") as fh:
            fh.write(le)
        os.replace(os.path.join(root, rel) + ".part", os.path.join(root, rel))
        sha = hashlib.sha256(le).hexdigest()
        agg.update(sha.encode())
        lattice_hits += sum(1 for v in stored if abs(v * 100 - round(v * 100)) < 1e-3)
        total_values += n
        t_first = w["start_time"] + a / RATE - w["filter_delay"]
        index_rows.append(
            {
                "dataset_id": args.dataset_id,
                "series_id": args.series_id,
                "sample_path": rel,
                "numeric_kind": "float",
                "bit_width": 32,
                "endianness": "little",
                "element_size_bytes": 4,
                "sample_size_bytes": len(le),
                "value_count": n,
                "role": "primary",
                "natural_record_kind": "cdip_dwr_m3_deployment_3day_heave_window",
                "station": r["station"],
                "deployment": dep,
                "site": r["site"],
                "source_url_path": r["url_path"],
                "xyz_start_index": a,
                "deployment_xyz_count": r["xyz_count"],
                "first_sample_time_utc": datetime.fromtimestamp(t_first, timezone.utc).isoformat(timespec="milliseconds"),
                "sample_rate_hz": 1.28,
                "min": min(stored),
                "max": max(stored),
                "sample_sha256": sha,
                "instrument_title": das["title"],
            }
        )
    with open(idx_path + ".part", "w", encoding="utf-8") as fh:
        for row in index_rows:
            fh.write(json.dumps(row, sort_keys=True) + "\n")
    os.replace(idx_path + ".part", idx_path)
    stats = {
        "dataset_id": args.dataset_id,
        "series_id": args.series_id,
        "sample_count": len(index_rows),
        "total_values": total_values,
        "total_size_bytes": 4 * total_values,
        "stations": len({r["station"] for r in rows}),
        "centimetre_lattice_fraction": round(lattice_hits / total_values, 6) if total_values else 0,
        "aggregate_sha256_of_sample_sha256s": agg.hexdigest(),
    }
    with open(stats_path, "w", encoding="utf-8") as fh:
        json.dump(stats, fh, indent=2, sort_keys=True)
        fh.write("\n")
    print(json.dumps(stats, sort_keys=True))


def main() -> None:
    if len(sys.argv) >= 2 and sys.argv[1] == "check-das":
        info = check_das(sys.argv[2], sys.argv[3])
        print(f"das_ok {sys.argv[3]}: {info['title'][:120]}")
        return
    if len(sys.argv) >= 2 and sys.argv[1] == "check-dods":
        try:
            w = decode_window(sys.argv[2], int(sys.argv[3]), int(sys.argv[4]))
        except (ValueError, struct.error) as exc:
            print(f"INVALID: {exc}", file=sys.stderr)
            sys.exit(3)
        print(f"dods_ok values={len(w['z'])} min={min(w['z']):.2f} max={max(w['z']):.2f} flag1={w['flag_primary_good']}")
        return
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["build"])
    ap.add_argument("--windows", required=True)
    ap.add_argument("--downloads", required=True)
    ap.add_argument("--data-root", required=True)
    ap.add_argument("--dataset-id", required=True)
    ap.add_argument("--series-id", required=True)
    build(ap.parse_args())


if __name__ == "__main__":
    main()
