#!/usr/bin/env python3
"""Build raw uint8 samples for nasa_pds_cassini_rpws_wbr_10khz_waveform_u8 from local downloads only.

One sample per pinned hourly 10-kHz WBR product file: the valid SAMPLES bytes
of every record with FREQUENCY_BAND 2, ANTENNA 0 (Ex), the WBR validity bit
set and neither TIMEOUT nor SUSPECT set, concatenated in file order and
written unchanged.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import rpws  # noqa: E402

MIN_SAMPLE_VALUES = 100_000
MIN_DISTINCT = 16


def read_sources(recipe_dir: Path) -> list[dict]:
    with (recipe_dir / "sources.tsv").open(encoding="utf-8") as fh:
        return list(csv.DictReader(fh, delimiter="\t"))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", type=Path, required=True)
    ap.add_argument("--recipe-dir", type=Path, required=True)
    args = ap.parse_args()
    data_dir = args.data_dir
    dl = data_dir / "downloads" / rpws.DATASET_ID
    out_dir = data_dir / "samples" / rpws.DATASET_ID / rpws.SERIES_ID
    index_dir = data_dir / "index" / rpws.DATASET_ID
    filtered_dir = data_dir / "filtered" / rpws.DATASET_ID
    for d in (out_dir, index_dir, filtered_dir):
        d.mkdir(parents=True, exist_ok=True)
    for stale in out_dir.glob("*.u8"):
        stale.unlink()

    plan = {}
    plan_path = dl / "download_plan.tsv"
    if not plan_path.exists():
        raise SystemExit(f"missing {plan_path}; run download.sh first")
    with plan_path.open(encoding="utf-8") as fh:
        for row in csv.DictReader(fh, delimiter="\t"):
            plan[row["product"]] = row

    rows, products, excluded = [], [], []
    aggregate = hashlib.sha256()
    histogram = [0] * 256
    seen_hashes = set()
    for src in read_sources(args.recipe_dir):
        product = src["product"]
        dat_path = dl / src["volume"] / f"{product}.DAT"
        lbl_path = dl / src["volume"] / f"{product}.LBL"
        data = dat_path.read_bytes()
        if len(data) != int(src["dat_size"]):
            raise SystemExit(f"{product}: size {len(data)} != pinned {src['dat_size']}")
        sha = hashlib.sha256(data).hexdigest()
        if product not in plan or plan[product]["dat_sha256"] != sha:
            raise SystemExit(f"{product}: SHA-256 differs from download_plan.tsv")
        meta = rpws.check_label(lbl_path.read_text(encoding="latin-1"), product, len(data))
        if meta["record_bytes"] != int(src["record_bytes"]):
            raise SystemExit(f"{product}: RECORD_BYTES changed")
        payload, stats = rpws.extract(data, meta["record_bytes"])
        distinct = len(set(payload))
        info = {"volume": src["volume"], "product": product, "start_time": src["start_time"],
                "record_bytes": meta["record_bytes"], "kept_values": len(payload), "distinct_dn": distinct, **stats}
        if len(payload) < MIN_SAMPLE_VALUES or distinct < MIN_DISTINCT:
            info["excluded_reason"] = (f"kept_values {len(payload)} < {MIN_SAMPLE_VALUES}"
                                       if len(payload) < MIN_SAMPLE_VALUES else f"distinct {distinct} < {MIN_DISTINCT}")
            excluded.append(info)
            print(f"exclude {product}: {info['excluded_reason']}")
            continue
        digest = hashlib.sha256(payload).hexdigest()
        if digest in seen_hashes:
            raise SystemExit(f"{product}: duplicate sample payload")
        seen_hashes.add(digest)
        sample_rel = f"samples/{rpws.DATASET_ID}/{rpws.SERIES_ID}/{product}.u8"
        (data_dir / sample_rel).write_bytes(payload)
        aggregate.update(payload)
        for b, c in enumerate(_hist(payload)):
            histogram[b] += c
        rows.append({
            "dataset_id": rpws.DATASET_ID,
            "series_id": rpws.SERIES_ID,
            "sample_path": sample_rel,
            "numeric_kind": "uint",
            "bit_width": 8,
            "endianness": "little",
            "element_size_bytes": 1,
            "sample_size_bytes": len(payload),
            "value_count": len(payload),
            "sha256": digest,
            "min": min(payload),
            "max": max(payload),
            "distinct_values": distinct,
            "volume_id": src["volume"],
            "product_id": product + "_V1",
            "start_time": src["start_time"],
            "source_record_bytes": meta["record_bytes"],
            "kept_records": stats["kept_records"],
            "source_records": stats["records"],
            "sampling_interval_s": 3.6e-05,
            "dn_zero_offset": -127.5,
        })
        products.append(info)
        print(f"sample {product} values={len(payload)} kept_records={stats['kept_records']}/{stats['records']} "
              f"distinct={distinct} dropped_antenna={stats['dropped_antenna']} dropped_flag={stats['dropped_flag']}")

    if not rows:
        raise SystemExit("no samples emitted")
    with (index_dir / "samples.jsonl").open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, sort_keys=True) + "\n")
    total = sum(r["sample_size_bytes"] for r in rows)
    sizes = sorted(r["value_count"] for r in rows)
    summary = {
        "dataset_id": rpws.DATASET_ID, "series_id": rpws.SERIES_ID,
        "pinned_products": len(products) + len(excluded), "sample_count": len(rows),
        "excluded_count": len(excluded), "total_size_bytes": total,
        "median_sample_values": sizes[len(sizes) // 2], "min_sample_values": sizes[0], "max_sample_values": sizes[-1],
        "volumes": sorted({r["volume_id"] for r in rows}),
        "aggregate_sample_sha256": aggregate.hexdigest(), "dn_histogram": histogram,
        "excluded": excluded, "products": products,
    }
    (filtered_dir / "ingest_stats.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
    print(f"build summary samples={len(rows)} excluded={len(excluded)} bytes={total} "
          f"median={summary['median_sample_values']} volumes={len(summary['volumes'])} "
          f"aggregate_sha256={aggregate.hexdigest()}")
    return 0


def _hist(payload: bytes) -> list[int]:
    c = Counter(payload)
    return [c.get(b, 0) for b in range(256)]


if __name__ == "__main__":
    sys.exit(main())
