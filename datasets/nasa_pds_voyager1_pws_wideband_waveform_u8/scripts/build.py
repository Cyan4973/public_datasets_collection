#!/usr/bin/env python3
"""Build raw uint8 samples for nasa_pds_voyager1_pws_wideband_waveform_u8 from local downloads only.

One sample per pinned 48-second Voyager 1 PWS waveform frame: the 4-bit codes
(0..15, one per byte) of every kept line, samples 17..1600 of each line, in
line order. See vgpws.py for the line and frame rules.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import vgpws  # noqa: E402


def entropy(counts: list[int]) -> float:
    n = sum(counts)
    return -sum(c / n * math.log2(c / n) for c in counts if c)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", type=Path, required=True)
    ap.add_argument("--recipe-dir", type=Path, required=True)
    args = ap.parse_args()
    data_dir = args.data_dir
    dl = data_dir / "downloads" / vgpws.DATASET_ID
    out_dir = data_dir / "samples" / vgpws.DATASET_ID / vgpws.SERIES_ID
    index_dir = data_dir / "index" / vgpws.DATASET_ID
    filtered_dir = data_dir / "filtered" / vgpws.DATASET_ID
    for d in (out_dir, index_dir, filtered_dir):
        d.mkdir(parents=True, exist_ok=True)
    for stale in out_dir.glob("*.u8"):
        stale.unlink()

    plan_path = dl / "download_plan.tsv"
    if not plan_path.exists():
        raise SystemExit(f"missing {plan_path}; run download.sh first")
    with plan_path.open(encoding="utf-8") as fh:
        plan = {r["product_id"]: r for r in csv.DictReader(fh, delimiter="\t")}
    with (args.recipe_dir / "sources.tsv").open(encoding="utf-8") as fh:
        sources = list(csv.DictReader(fh, delimiter="\t"))

    rows, frames, excluded = [], [], []
    hist = [0] * 16
    seen = set()
    aggregate = hashlib.sha256()
    for src in sources:
        product = src["product_id"]
        dat_path = dl / "frames" / f"{src['path_stem']}.DAT"
        lbl_path = dl / "frames" / f"{src['path_stem']}.LBL"
        data = dat_path.read_bytes()
        if len(data) != int(src["dat_size"]):
            raise SystemExit(f"{product}: size {len(data)} != pinned {src['dat_size']}")
        if product not in plan or plan[product]["dat_sha256"] != hashlib.sha256(data).hexdigest():
            raise SystemExit(f"{product}: SHA-256 differs from download_plan.tsv")
        meta = vgpws.check_label(lbl_path.read_text(encoding="latin-1"), product, len(data), src["start_time"])
        payload, stats = vgpws.extract(data)
        info = {"product_id": product, "stratum": src["stratum"], "start_time": src["start_time"],
                "mission_phase": meta["mission_phase"], "label_data_lines": meta["data_lines"],
                "values": len(payload), **stats}
        reason = vgpws.frame_rule(payload, stats["kept_lines"])
        if reason:
            info["excluded_reason"] = reason
            excluded.append(info)
            print(f"exclude {product} ({src['stratum']}): {reason}")
            continue
        digest = hashlib.sha256(payload).hexdigest()
        if digest in seen:
            raise SystemExit(f"{product}: duplicate sample payload")
        seen.add(digest)
        counts = [payload.count(bytes([c])) for c in range(16)]
        for c in range(16):
            hist[c] += counts[c]
        rel = f"samples/{vgpws.DATASET_ID}/{vgpws.SERIES_ID}/{product}.u8"
        (data_dir / rel).write_bytes(payload)
        aggregate.update(payload)
        mode = max(counts) / len(payload)
        h0 = entropy(counts)
        rows.append({
            "dataset_id": vgpws.DATASET_ID,
            "series_id": vgpws.SERIES_ID,
            "sample_path": rel,
            "numeric_kind": "uint",
            "bit_width": 8,
            "endianness": "little",
            "element_size_bytes": 1,
            "sample_size_bytes": len(payload),
            "value_count": len(payload),
            "sha256": digest,
            "min": min(payload),
            "max": max(payload),
            "distinct_values": sum(1 for c in counts if c),
            "mode_fraction": round(mode, 6),
            "product_id": product,
            "stratum": src["stratum"],
            "start_time": src["start_time"],
            "mission_phase": meta["mission_phase"],
            "kept_lines": stats["kept_lines"],
            "data_records": stats["data_records"],
            "repeat_lines": stats["repeat"],
            "zero_fill_lines": stats["zero_fill"],
            "bad_line_records": stats["bad_line"],
            "samples_per_line": vgpws.SAMPLES_PER_LINE,
            "sampling_interval_s": 3.472222e-05,
            "code_zero_offset": -7.5,
        })
        info["entropy_bits"] = round(h0, 4)
        info["mode_fraction"] = round(mode, 4)
        frames.append(info)
        print(f"sample {product} {src['stratum']} lines={stats['kept_lines']}/{stats['data_records']} "
              f"repeat={stats['repeat']} zero={stats['zero_fill']} bad={stats['bad_line']} "
              f"values={len(payload)} H0={h0:.2f} mode={mode:.3f}")

    if not rows:
        raise SystemExit("no samples emitted")
    with (index_dir / "samples.jsonl").open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, sort_keys=True) + "\n")
    total = sum(r["sample_size_bytes"] for r in rows)
    sizes = sorted(r["value_count"] for r in rows)
    per_stratum: dict[str, dict] = {}
    for r in rows:
        s = per_stratum.setdefault(r["stratum"], {"samples": 0, "values": 0})
        s["samples"] += 1
        s["values"] += r["value_count"]
    summary = {
        "dataset_id": vgpws.DATASET_ID, "series_id": vgpws.SERIES_ID,
        "pinned_frames": len(sources), "sample_count": len(rows), "excluded_count": len(excluded),
        "total_size_bytes": total, "median_sample_values": sizes[len(sizes) // 2],
        "min_sample_values": sizes[0], "max_sample_values": sizes[-1],
        "per_stratum": per_stratum, "code_histogram": hist,
        "aggregate_entropy_bits": round(entropy(hist), 4),
        "aggregate_sample_sha256": aggregate.hexdigest(),
        "excluded": excluded, "frames": frames,
    }
    (filtered_dir / "ingest_stats.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
    print(f"build summary samples={len(rows)} excluded={len(excluded)} bytes={total} "
          f"median={summary['median_sample_values']} per_stratum={json.dumps(per_stratum)} "
          f"hist={hist} aggregate_sha256={aggregate.hexdigest()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
