#!/usr/bin/env python3
"""Independent verification of huawei_cloud2025_serverless_request_latency_f64.

Usage: verify_samples.py <data_root> <manifest.toml>

Re-derives every sample from the local R5.zip with a separate parser
(plain comma splitting, no csv module), applies the same missing-value
policy, and checks the written files, the index and the manifest:
byte-exact SHA-256 per sample, value counts, finite non-negative values,
non-constant samples (constant (function, series) samples must be skipped
and listed in build_stats), no duplicate samples, equal row counts across the four
series of one function, and manifest sample_count / total_size_bytes.
"""
import hashlib
import json
import math
import struct
import sys
import tomllib
import zipfile
from array import array
from pathlib import Path

DATASET_ID = "huawei_cloud2025_serverless_request_latency_f64"
MIN_REQUESTS = 1000
FIELDS = {
    "total_cost_frontend_f64": "totalCost_frontend",
    "total_cost_worker_f64": "totalCost_worker",
    "runtime_cost_f64": "runtimeCost",
    "bus_cost_f64": "busCost",
}
SERIES_ORDER = list(FIELDS)


def fail(message: str) -> None:
    raise SystemExit(f"verify: FAIL {message}")


def pool_of(pod: str):
    head, sep, tail = pod.rpartition("-")
    if not sep or not head or not tail.isdigit() or not tail.isascii():
        return None
    return head


def classify(text: str):
    """Missing-value policy: blank -> missing, non-finite -> drop, negative -> drop."""
    if not text.strip():
        return "missing_value", None
    v = float(text)
    if v != v or v in (math.inf, -math.inf):
        return "nonfinite_value", None
    if v < 0:
        return "negative_value", None
    return None, v


def rederive(zip_path: Path):
    funcs: dict = {}
    drops = {"dropped_no_frontend_time": 0, "dropped_bad_key": 0, "dropped_missing_value": 0,
             "dropped_nonfinite_value": 0, "dropped_negative_value": 0}
    data_rows = 0
    with zipfile.ZipFile(zip_path) as zf:
        names = sorted(n for n in zf.namelist() if n.endswith(".csv"))
        if len(names) != 200:
            fail(f"zip has {len(names)} csv members")
        for name in names:
            text = zf.read(name).decode("utf-8")
            lines = text.splitlines()
            header = lines[0].split(",")
            pos = {h: i for i, h in enumerate(header)}
            idx = [pos[FIELDS[s]] for s in SERIES_ORDER]
            t_i, f_i, u_i, p_i = pos["time_frontend"], pos["funcName"], pos["userID"], pos["podID"]
            for line in lines[1:]:
                if not line:
                    continue
                cells = line.split(",")
                if len(cells) != len(header):
                    fail(f"{name}: row with {len(cells)} cells")
                data_rows += 1
                t = cells[t_i].strip()
                if not t or not math.isfinite(float(t)):
                    drops["dropped_no_frontend_time"] += 1
                    continue
                func, user = cells[f_i].strip(), cells[u_i].strip()
                pool = pool_of(cells[p_i].strip())
                if not func or not user or pool is None:
                    drops["dropped_bad_key"] += 1
                    continue
                vals = []
                for i in idx:
                    reason, v = classify(cells[i])
                    if reason:
                        drops["dropped_" + reason] += 1
                        break
                    vals.append(v)
                else:
                    cols = funcs.get((func, user, pool))
                    if cols is None:
                        cols = funcs[(func, user, pool)] = [array("d") for _ in range(5)]
                    cols[0].append(float(t))
                    for arr, v in zip(cols[1:], vals):
                        arr.append(v)
    return funcs, drops, data_rows


def main() -> None:
    data_root = Path(sys.argv[1])
    manifest = tomllib.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
    zip_path = data_root / "downloads" / DATASET_ID / "R5.zip"
    index_path = data_root / "index" / DATASET_ID / "samples.jsonl"
    stats_path = data_root / "filtered" / DATASET_ID / "build_stats.json"
    for p in (zip_path, index_path, stats_path):
        if not p.is_file():
            fail(f"missing {p}")

    funcs, drops, data_rows = rederive(zip_path)
    expected = {}
    constant = []
    for key, cols in funcs.items():
        n_rows = len(cols[0])
        if n_rows < MIN_REQUESTS:
            continue
        times = cols[0]
        order = sorted(range(n_rows), key=lambda i: (times[i], i))
        func, user, pool = key
        stem = "f" + func + "_u" + user + "_" + "".join(c if c.isalnum() or c == "-" else "_" for c in pool)
        for j, sid in enumerate(SERIES_ORDER):
            src = cols[j + 1]
            if min(src) == max(src):
                constant.append((sid, stem + ".bin", src[0], n_rows))
                continue
            payload = struct.pack(f"<{n_rows}d", *(src[i] for i in order))
            rel = f"samples/{DATASET_ID}/{sid}/{stem}.bin"
            expected[rel] = (sid, n_rows, hashlib.sha256(payload).hexdigest())
        cols.clear()
    print(f"rederived data_rows={data_rows} functions={len(funcs)} samples={len(expected)} constant_skipped={len(constant)}", flush=True)

    stats = json.loads(stats_path.read_text(encoding="utf-8"))
    for k, v in drops.items():
        if stats.get(k) != v:
            fail(f"build_stats {k}={stats.get(k)} but re-derived {v}")
    got_constant = sorted((c["series_id"], c["sample"], c["value"], c["value_count"])
                          for c in stats.get("constant_samples_skipped", []))
    if got_constant != sorted(constant):
        fail(f"build_stats constant_samples_skipped={got_constant} but re-derived {sorted(constant)}")
    if stats.get("data_rows") != data_rows:
        fail(f"build_stats data_rows={stats.get('data_rows')} but re-derived {data_rows}")

    rows = [json.loads(l) for l in index_path.read_text(encoding="utf-8").splitlines() if l.strip()]
    paths = [r["sample_path"] for r in rows]
    if len(set(paths)) != len(paths):
        fail("duplicate sample_path in index")
    if set(paths) != set(expected):
        fail(f"index/rederived sample set mismatch: missing={len(set(expected) - set(paths))} extra={len(set(paths) - set(expected))}")
    on_disk = {str(p.relative_to(data_root)) for p in (data_root / "samples" / DATASET_ID).rglob("*") if p.is_file()}
    if on_disk != set(expected):
        fail(f"stray or missing files under samples/: {sorted(on_disk ^ set(expected))[:5]}")

    per_series = {sid: [0, 0] for sid in SERIES_ORDER}
    hashes = {sid: set() for sid in SERIES_ORDER}
    counts_by_stem: dict = {}
    for r in rows:
        sid = r["series_id"]
        exp_sid, exp_n, exp_sha = expected[r["sample_path"]]
        if sid != exp_sid or r["dataset_id"] != DATASET_ID:
            fail(f"{r['sample_path']}: wrong series/dataset in index")
        if (r["numeric_kind"], r["bit_width"], r["endianness"], r["element_size_bytes"]) != ("float", 64, "little", 8):
            fail(f"{r['sample_path']}: wrong dtype fields")
        raw = (data_root / r["sample_path"]).read_bytes()
        n = len(raw) // 8
        if len(raw) != r["sample_size_bytes"] or n != r["value_count"] or n != exp_n or len(raw) % 8:
            fail(f"{r['sample_path']}: size/count mismatch")
        sha = hashlib.sha256(raw).hexdigest()
        if sha != exp_sha or sha != r["sha256"]:
            fail(f"{r['sample_path']}: content differs from re-derivation")
        if n < MIN_REQUESTS:
            fail(f"{r['sample_path']}: only {n} values")
        vals = struct.unpack(f"<{n}d", raw)
        lo, hi = min(vals), max(vals)
        if not all(math.isfinite(v) and v >= 0 for v in vals):
            fail(f"{r['sample_path']}: non-finite or negative value")
        if lo == hi:
            fail(f"{r['sample_path']}: constant sample")
        if lo != r["min"] or hi != r["max"]:
            fail(f"{r['sample_path']}: index min/max mismatch")
        if sha in hashes[sid]:
            fail(f"{r['sample_path']}: duplicate sample content")
        hashes[sid].add(sha)
        stem = Path(r["sample_path"]).name
        counts_by_stem.setdefault(stem, set()).add(n)
        per_series[sid][0] += 1
        per_series[sid][1] += len(raw)
    if any(len(s) != 1 for s in counts_by_stem.values()):
        fail("series of one function disagree on row count")
    for sid in SERIES_ORDER:
        n_expected = sum(1 for v in expected.values() if v[0] == sid)
        if per_series[sid][0] != n_expected or n_expected == 0:
            fail(f"{sid}: {per_series[sid][0]} samples but re-derived {n_expected}")

    declared = {s["id"]: s for s in manifest.get("series", [])}
    for sid, (n_samples, n_bytes) in per_series.items():
        s = declared.get(sid)
        if s is None:
            fail(f"manifest lacks series {sid}")
        if s.get("sample_count") != n_samples or s.get("total_size_bytes") != n_bytes:
            fail(f"manifest {sid}: sample_count={s.get('sample_count')} total_size_bytes={s.get('total_size_bytes')} "
                 f"but realized {n_samples} / {n_bytes}")
    values = sorted(r["value_count"] for r in rows)
    total_bytes = sum(v[1] for v in per_series.values())
    if total_bytes > 1_000_000_000:
        fail(f"primary bytes {total_bytes} exceed 1 GB")
    print(f"verify: OK samples_per_series={ {k: v[0] for k, v in per_series.items()} } primary_bytes={total_bytes} "
          f"primary_values={sum(values)} median_values={values[len(values) // 2]} drops={json.dumps(drops, sort_keys=True)}")


if __name__ == "__main__":
    main()
