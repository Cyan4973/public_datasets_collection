#!/usr/bin/env python3
"""Build per-function float64 latency samples from the local R5.zip.

Usage: build_samples.py <data_root>

Sample = one deployed function, keyed by (funcName, userID, pool prefix of
podID), holding its day-30 requests sorted by time_frontend (stable over the
source order, which is time_worker ascending). One sample file per function
per latency field: totalCost_frontend, totalCost_worker, runtimeCost, busCost.
A (function, series) sample whose values are all identical is skipped and
listed in build_stats.json (constant_samples_skipped); the function's other
series are still emitted.
"""
import csv
import hashlib
import io
import json
import math
import re
import shutil
import struct
import sys
import zipfile
from array import array
from pathlib import Path

DATASET_ID = "huawei_cloud2025_serverless_request_latency_f64"
MIN_REQUESTS = 1000
MAX_PRIMARY_BYTES = 1_000_000_000
SERIES = [
    ("total_cost_frontend_f64", "totalCost_frontend"),
    ("total_cost_worker_f64", "totalCost_worker"),
    ("runtime_cost_f64", "runtimeCost"),
    ("bus_cost_f64", "busCost"),
]
POD_RE = re.compile(r"^(.+)-(\d+)$")
SAFE_RE = re.compile(r"[^A-Za-z0-9-]")


def parse_value(text: str):
    """Return (value, reason). reason is None for a kept value."""
    if text.strip() == "":
        return None, "missing_value"
    value = float(text)  # unexpected tokens raise ValueError: fatal by design
    if not math.isfinite(value):
        return None, "nonfinite_value"
    if value < 0.0:
        return None, "negative_value"
    return value, None


def main() -> None:
    data_root = Path(sys.argv[1])
    zip_path = data_root / "downloads" / DATASET_ID / "R5.zip"
    samples_root = data_root / "samples" / DATASET_ID
    index_dir = data_root / "index" / DATASET_ID
    filtered_dir = data_root / "filtered" / DATASET_ID
    if not zip_path.is_file():
        raise SystemExit(f"missing {zip_path}; run download.sh first")

    groups: dict = {}
    counts = {
        "data_rows": 0,
        "kept_rows": 0,
        "dropped_no_frontend_time": 0,
        "dropped_bad_key": 0,
        "dropped_missing_value": 0,
        "dropped_nonfinite_value": 0,
        "dropped_negative_value": 0,
    }
    with zipfile.ZipFile(zip_path) as zf:
        members = sorted(n for n in zf.namelist() if n.endswith(".csv"))
        if len(members) != 200:
            raise SystemExit(f"expected 200 csv members, found {len(members)}")
        for member in members:
            with zf.open(member) as raw:
                reader = csv.reader(io.TextIOWrapper(raw, encoding="utf-8", newline=""))
                header = next(reader)
                col = {name: i for i, name in enumerate(header)}
                if len(header) != 18:
                    raise SystemExit(f"{member}: unexpected header width {len(header)}")
                i_tf = col["time_frontend"]
                i_fn, i_user, i_pod = col["funcName"], col["userID"], col["podID"]
                value_cols = [col[field] for _, field in SERIES]
                for line_no, row in enumerate(reader, 2):
                    if len(row) != 18:
                        raise SystemExit(f"{member}:{line_no}: malformed row with {len(row)} fields")
                    counts["data_rows"] += 1
                    tf_text = row[i_tf].strip()
                    if tf_text == "":
                        counts["dropped_no_frontend_time"] += 1
                        continue
                    tf = float(tf_text)
                    if not math.isfinite(tf):
                        counts["dropped_no_frontend_time"] += 1
                        continue
                    func, user, pod = row[i_fn].strip(), row[i_user].strip(), row[i_pod].strip()
                    pod_match = POD_RE.match(pod)
                    if not func or not user or not pod_match:
                        counts["dropped_bad_key"] += 1
                        continue
                    values = []
                    reason = None
                    for c in value_cols:
                        value, why = parse_value(row[c])
                        if why is not None:
                            reason = why
                            break
                        values.append(value)
                    if reason is not None:
                        counts["dropped_" + reason] += 1
                        continue
                    key = (func, user, pod_match.group(1))
                    group = groups.get(key)
                    if group is None:
                        group = groups[key] = (array("d"), [array("d") for _ in SERIES])
                    group[0].append(tf)
                    for arr, value in zip(group[1], values):
                        arr.append(value)
                    counts["kept_rows"] += 1
            print(f"read {member} kept_rows={counts['kept_rows']} functions={len(groups)}", flush=True)

    if samples_root.exists():
        shutil.rmtree(samples_root)
    index_dir.mkdir(parents=True, exist_ok=True)
    filtered_dir.mkdir(parents=True, exist_ok=True)
    for series_id, _ in SERIES:
        (samples_root / series_id).mkdir(parents=True, exist_ok=True)

    def sort_key(key):
        func, user, pool = key
        return (func.zfill(12), user.zfill(12), pool)

    selected = [k for k in sorted(groups, key=sort_key) if len(groups[k][0]) >= MIN_REQUESTS]
    below = [k for k in groups if len(groups[k][0]) < MIN_REQUESTS]
    index_rows = []
    total_bytes = 0
    constant_skipped = []
    per_series_counts = {series_id: [0, 0] for series_id, _ in SERIES}
    for key in selected:
        tf, cols = groups[key]
        order = sorted(range(len(tf)), key=tf.__getitem__)
        func, user, pool = key
        stem = f"f{SAFE_RE.sub('_', func)}_u{SAFE_RE.sub('_', user)}_{SAFE_RE.sub('_', pool)}"
        for (series_id, field), arr in zip(SERIES, cols):
            ordered = array("d", (arr[i] for i in order))
            if min(ordered) == max(ordered):
                # Degenerate (e.g. runtimeCost logged as 0.0 for every request
                # of a function whose runtime is not instrumented): skip this
                # (function, series) sample only; the other series stay.
                constant_skipped.append({"series_id": series_id, "sample": f"{stem}.bin",
                                         "value": ordered[0], "value_count": len(ordered)})
                continue
            if sys.byteorder != "little":
                ordered.byteswap()
            payload = ordered.tobytes()
            rel = f"samples/{DATASET_ID}/{series_id}/{stem}.bin"
            (data_root / rel).write_bytes(payload)
            total_bytes += len(payload)
            per_series_counts[series_id][0] += 1
            per_series_counts[series_id][1] += len(payload)
            stored = struct.unpack(f"<{len(ordered)}d", payload)
            index_rows.append(
                {
                    "dataset_id": DATASET_ID,
                    "series_id": series_id,
                    "sample_path": rel,
                    "numeric_kind": "float",
                    "bit_width": 64,
                    "endianness": "little",
                    "element_size_bytes": 8,
                    "sample_size_bytes": len(payload),
                    "value_count": len(ordered),
                    "source_field": field,
                    "func_name": func,
                    "user_id": user,
                    "pool": pool,
                    "first_time_frontend": tf[order[0]],
                    "last_time_frontend": tf[order[-1]],
                    "min": min(stored),
                    "max": max(stored),
                    "distinct_values": len(set(stored)),
                    "sha256": hashlib.sha256(payload).hexdigest(),
                }
            )
    if total_bytes > MAX_PRIMARY_BYTES:
        raise SystemExit(f"primary output {total_bytes} exceeds {MAX_PRIMARY_BYTES}")
    index_rows.sort(key=lambda r: (r["series_id"], r["sample_path"]))
    with (index_dir / "samples.jsonl").open("w", encoding="utf-8") as fh:
        for row in index_rows:
            fh.write(json.dumps(row, sort_keys=True) + "\n")

    sizes = sorted(len(groups[k][0]) for k in selected)
    stats = dict(counts)
    stats.update(
        {
            "functions_total": len(groups),
            "functions_selected": len(selected),
            "functions_below_min": len(below),
            "rows_in_selected_functions": sum(sizes),
            "rows_in_functions_below_min": sum(len(groups[k][0]) for k in below),
            "min_requests": MIN_REQUESTS,
            "sample_value_count_min": sizes[0] if sizes else 0,
            "sample_value_count_median": sizes[len(sizes) // 2] if sizes else 0,
            "sample_value_count_max": sizes[-1] if sizes else 0,
            "constant_samples_skipped": constant_skipped,
            "per_series_sample_count": {k: v[0] for k, v in per_series_counts.items()},
            "per_series_total_bytes": {k: v[1] for k, v in per_series_counts.items()},
            "primary_total_bytes": total_bytes,
        }
    )
    (filtered_dir / "build_stats.json").write_text(json.dumps(stats, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(stats, sort_keys=True))


if __name__ == "__main__":
    main()
