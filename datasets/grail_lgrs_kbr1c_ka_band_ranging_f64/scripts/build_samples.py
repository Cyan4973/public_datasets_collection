#!/usr/bin/env python3
"""Build little-endian samples from the pinned extended-mission KBR1C products.

Per product (one UTC day), four samples from the same records in source order:
  kbr1c_biased_range_f64   column 2, biased dual one-way range (m)      primary
  kbr1c_range_rate_f64     column 3, range rate (m/s)                   primary
  kbr1c_range_accl_f64     column 4, range acceleration (m/s^2)         primary
  kbr1c_tdb_seconds_i64    column 1, TDB seconds past J2000 noon         auxiliary
Uses only files under $DATA_ROOT/downloads/<id>/.
"""
import argparse
import hashlib
import json
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import kbr1c  # noqa: E402

DATASET_ID = "grail_lgrs_kbr1c_ka_band_ranging_f64"
PRIMARY = [("kbr1c_biased_range_f64", "range"), ("kbr1c_range_rate_f64", "rate"), ("kbr1c_range_accl_f64", "accl")]
AUX = "kbr1c_tdb_seconds_i64"


def write_atomic(path, data):
    tmp = path + ".part"
    with open(tmp, "wb") as fh:
        fh.write(data)
    os.replace(tmp, path)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-root", required=True)
    ap.add_argument("--sources", required=True)
    a = ap.parse_args()
    root = a.data_root
    dl = os.path.join(root, "downloads", DATASET_ID)
    sample_root = os.path.join(root, "samples", DATASET_ID)
    index_dir = os.path.join(root, "index", DATASET_ID)
    filtered = os.path.join(root, "filtered", DATASET_ID)
    for d in [index_dir, filtered] + [os.path.join(sample_root, s) for s, _ in PRIMARY] + [os.path.join(sample_root, AUX)]:
        os.makedirs(d, exist_ok=True)
    sources = kbr1c.read_sources(a.sources)
    if len(sources) != 107:
        sys.exit(f"FATAL: expected 107 pinned products, found {len(sources)}")
    kbr1c.check_md5_manifest(sources, os.path.join(dl, "grail_0101_230316.md5"))

    rows = []
    stats = {"products": 0, "records": 0, "gap_count": 0, "missing_epochs": 0, "rebias_steps": 0,
             "calslew_flag_records": 0, "other_flag_records": 0, "partial_days": [], "per_product": []}
    expected_files = set()
    for src in sources:
        date = src["date"]
        asc = os.path.join(dl, date, src["file"])
        kbr1c.check_label(sources, date, os.path.join(dl, date, src["file"][:-4] + ".lbl"))
        rec = kbr1c.check_asc(sources, date, asc)
        summ = kbr1c.summarize(rec)
        n = summ["record_count"]
        common = {"date": date, "source_file": f"grail_0101/level_1b/{date}/{src['file']}",
                  "source_md5": src["asc_md5"]}
        common.update({k: v for k, v in summ.items() if k != "gaps"})
        for sid, key in PRIMARY:
            vals = rec[key]
            data = struct.pack(f"<{n}d", *vals)
            stored = struct.unpack(f"<{n}d", data)
            if len(set(stored[: min(n, 5000)])) < 2:
                sys.exit(f"FATAL: {sid} {date} is constant in its first records")
            rel = f"samples/{DATASET_ID}/{sid}/{date}.f64"
            write_atomic(os.path.join(root, rel), data)
            expected_files.add(rel)
            row = {"dataset_id": DATASET_ID, "series_id": sid, "sample_path": rel, "role": "primary",
                   "numeric_kind": "float", "bit_width": 64, "endianness": "little",
                   "element_size_bytes": 8, "sample_size_bytes": len(data), "value_count": n,
                   "sample_shape": [n], "min": min(stored), "max": max(stored),
                   "distinct_values": len(set(stored)), "sample_sha256": hashlib.sha256(data).hexdigest()}
            row.update(common)
            rows.append(row)
        data = struct.pack(f"<{n}q", *rec["tdb"])
        rel = f"samples/{DATASET_ID}/{AUX}/{date}.i64"
        write_atomic(os.path.join(root, rel), data)
        expected_files.add(rel)
        row = {"dataset_id": DATASET_ID, "series_id": AUX, "sample_path": rel, "role": "auxiliary",
               "numeric_kind": "int", "bit_width": 64, "endianness": "little",
               "element_size_bytes": 8, "sample_size_bytes": len(data), "value_count": n,
               "sample_shape": [n], "min": rec["tdb"][0], "max": rec["tdb"][-1],
               "sample_sha256": hashlib.sha256(data).hexdigest()}
        row.update(common)
        rows.append(row)
        stats["products"] += 1
        stats["records"] += n
        for k in ("gap_count", "missing_epochs", "rebias_steps", "calslew_flag_records", "other_flag_records"):
            stats[k] += summ[k]
        if summ["partial_day"]:
            stats["partial_days"].append(date)
        stats["per_product"].append({"date": date, **summ})
        print(f"built {date} records={n} gaps={summ['gap_count']} missing={summ['missing_epochs']} "
              f"rebias={summ['rebias_steps']} calslew={summ['calslew_flag_records']} partial={summ['partial_day']}")

    # Remove stale sample files not produced by this build.
    for sid in [s for s, _ in PRIMARY] + [AUX]:
        d = os.path.join(sample_root, sid)
        for name in os.listdir(d):
            rel = f"samples/{DATASET_ID}/{sid}/{name}"
            if rel not in expected_files:
                os.remove(os.path.join(d, name))
                print(f"removed stale {rel}")

    with open(os.path.join(index_dir, "samples.jsonl.part"), "w", encoding="ascii") as fh:
        for row in rows:
            fh.write(json.dumps(row, sort_keys=True) + "\n")
    os.replace(os.path.join(index_dir, "samples.jsonl.part"), os.path.join(index_dir, "samples.jsonl"))
    prim = [r for r in rows if r["role"] == "primary"]
    stats["primary_samples"] = len(prim)
    stats["primary_values"] = sum(r["value_count"] for r in prim)
    stats["primary_bytes"] = sum(r["sample_size_bytes"] for r in prim)
    stats["auxiliary_bytes"] = sum(r["sample_size_bytes"] for r in rows if r["role"] == "auxiliary")
    h = hashlib.sha256()
    for r in prim:
        with open(os.path.join(root, r["sample_path"]), "rb") as fh:
            h.update(fh.read())
    stats["primary_concat_sha256"] = h.hexdigest()
    with open(os.path.join(filtered, "build_stats.json"), "w", encoding="ascii") as fh:
        json.dump(stats, fh, indent=1, sort_keys=True)
    print(f"products={stats['products']} records={stats['records']} primary_samples={stats['primary_samples']} "
          f"primary_values={stats['primary_values']} primary_bytes={stats['primary_bytes']} "
          f"aux_bytes={stats['auxiliary_bytes']} gaps={stats['gap_count']} missing={stats['missing_epochs']} "
          f"rebias={stats['rebias_steps']} calslew={stats['calslew_flag_records']} other_flags={stats['other_flag_records']} "
          f"partial_days={','.join(stats['partial_days'])} concat_sha256={stats['primary_concat_sha256']}")


if __name__ == "__main__":
    try:
        main()
    except kbr1c.KbrError as exc:
        sys.exit(f"FATAL: {exc}")
