#!/usr/bin/env python3
"""Independent verifier for nrel_resstock2021_state_enduse_load_profiles_f64.

Shares no parsing code with resstock.py. It re-checks every pinned CSV's md5,
re-parses it with a plain byte/line/field splitter and an epoch-based
timestamp lattice, and requires every emitted value's source token to be the
canonical shortest repr of the stored double (lossless print). It then
re-evaluates the global end-use rule with a different rescaling test
(signed-sum-normalized profiles instead of ratio spreads), and checks every
sample's bytes, every index field, the manifest totals, stray files, constant
or degenerate samples and duplicate samples."""
from __future__ import annotations

import argparse
import array
import hashlib
import json
import math
import struct
import sys
import time
import tomllib
from pathlib import Path

DATASET_ID = "nrel_resstock2021_state_enduse_load_profiles_f64"
SERIES_ID = "resstock_sfd_state_enduse_energy_kwh_15min_f64"
N_ROWS = 35040
EPOCH_2018 = 1514764800  # 2018-01-01 00:00:00 on a fixed-offset (no-DST) clock
LEADING = ["in.state", "in.geometry_building_type_recs", "timestamp", "models_used", "units_represented"]
BUILDING_TYPE = "Single-Family Detached"
MIN_DISTINCT = 1000
PROFILE_TOL = 1e-9


class VerifyError(Exception):
    pass


def tsv(path: Path) -> list[dict]:
    lines = path.read_text(encoding="utf-8").splitlines()
    keys = lines[0].split("\t")
    return [dict(zip(keys, line.split("\t"))) for line in lines[1:]]


def lattice(k: int) -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(EPOCH_2018 + 900 * (k + 1)))


def parse_bytes(raw: bytes, state: str, out_columns: list[str], keep_offsets: set[int], store_offsets: list[int], n_rows: int = N_ROWS) -> tuple[dict, tuple[str, str]]:
    """Return ({offset: array('d')} for store_offsets, (models_used,
    units_represented)). Offsets index the out.* columns."""
    if b'"' in raw or b"\r" in raw:
        raise VerifyError(f"{state}: quotes or CR in file")
    lines = raw.decode("ascii").split("\n")
    if lines[-1] != "":
        raise VerifyError(f"{state}: file does not end with a newline")
    lines.pop()
    if lines[0].split(",") != LEADING + out_columns:
        raise VerifyError(f"{state}: header mismatch")
    body = lines[1:]
    if len(body) != n_rows:
        raise VerifyError(f"{state}: {len(body)} data rows, expected {n_rows}")
    width = len(LEADING) + len(out_columns)
    cols = {off: array.array("d") for off in store_offsets}
    keep = sorted(keep_offsets)
    meta = None
    for k, line in enumerate(body):
        f = line.split(",")
        if len(f) != width:
            raise VerifyError(f"{state}: row {k + 1} has {len(f)} fields")
        if f[0] != state or f[1] != BUILDING_TYPE or f[2] != lattice(k):
            raise VerifyError(f"{state}: row {k + 1} identity/timestamp mismatch: {f[:3]}")
        if meta is None:
            meta = (f[3], f[4])
        elif (f[3], f[4]) != meta:
            raise VerifyError(f"{state}: models_used/units_represented change at row {k + 1}")
        tokens = f[5:]
        try:
            values = [float(t) for t in tokens]
        except ValueError:
            raise VerifyError(f"{state}: row {k + 1}: empty or unparsable cell") from None
        for v in values:
            if v != v or v in (math.inf, -math.inf):
                raise VerifyError(f"{state}: row {k + 1}: NaN or infinite value")
        for off in keep:
            if repr(values[off]) != tokens[off]:
                raise VerifyError(f"{state}: row {k + 1}: token {tokens[off]!r} is not the canonical repr of its double")
        for off, arr in cols.items():
            arr.append(values[off])
    return cols, meta


def distinct_count(x) -> int:
    s = sorted(x)
    return 1 + sum(1 for i in range(1, len(s)) if s[i] != s[i - 1]) if s else 0


def profile_key(x) -> tuple[bytes, float, float]:
    """Zero pattern, normalizer (signed sum, or absolute sum if the signed
    sum vanishes) and normalized peak of one series."""
    zeros = bytes(v == 0.0 for v in x)
    norm = math.fsum(x)
    if norm == 0.0:
        norm = math.fsum(abs(v) for v in x)
    peak = max(abs(v) for v in x) / abs(norm)
    return zeros, norm, peak


def profiles_match(xa, xb, ka, kb, tol: float = PROFILE_TOL) -> bool:
    """True when xa and xb have the same zero pattern and the same
    sum-normalized profile, i.e. one is an exact rescaling of the other."""
    if ka[0] != kb[0]:
        return False
    sa, sb = ka[1], kb[1]
    limit = tol * ka[2]
    for va, vb in zip(xa, xb):
        if abs(va / sa - vb / sb) > limit:
            return False
    return True


def evaluate_rule(series: dict, end_use_names: list[str], min_distinct: int = MIN_DISTINCT) -> dict:
    """series: {state: {column: array}}. Returns {column: {flags, pairs}}."""
    states = sorted(series)
    out = {}
    for name in end_use_names:
        zero = [st for st in states if not any(series[st][name])]
        live = [st for st in states if st not in zero]
        low = [st for st in live if distinct_count(series[st][name]) < min_distinct]
        keys = {st: profile_key(series[st][name]) for st in live}
        pairs = 0
        for i, a in enumerate(live):
            for b in live[i + 1 :]:
                if profiles_match(series[a][name], series[b][name], keys[a], keys[b]):
                    pairs += 1
        flags = []
        if zero:
            flags.append("a_all_zero")
        if low:
            flags.append("b_low_distinct")
        if pairs:
            flags.append("c_rescaled_duplicate")
        out[name] = {"flags": flags, "pairs": pairs, "decision": "drop" if flags else "keep", "zero_states": zero}
    return out


def md5_of(path: Path) -> str:
    h = hashlib.md5(usedforsecurity=False)
    with path.open("rb") as fh:
        while True:
            chunk = fh.read(1 << 22)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def verify(recipe_dir: Path, download_dir: Path, data_root: Path, manifest_path: Path) -> None:
    columns = tsv(recipe_dir / "columns.tsv")
    sources = tsv(recipe_dir / "sources.tsv")
    out_columns = [c["column"] for c in columns]
    end_use_offsets = [i for i, c in enumerate(columns) if c["kind"] == "end_use"]
    end_use_names = [out_columns[i] for i in end_use_offsets]
    pinned_keep = [c["column"] for c in columns if c["expected"] == "keep"]
    keep_offsets = {out_columns.index(name) for name in pinned_keep}
    if len(sources) != 49 or len(columns) != 54:
        raise VerifyError("pins must list 49 states and 54 out.* columns")

    series: dict[str, dict[str, array.array]] = {}
    meta: dict[str, tuple[str, str]] = {}
    for src in sources:
        st = src["state"]
        path = download_dir / "by_state" / f"{st.lower()}-single-family_detached.csv"
        if path.stat().st_size != int(src["size_bytes"]) or md5_of(path) != src["etag_md5"]:
            raise VerifyError(f"{st}: downloaded file differs from pinned size/md5")
        cols, meta[st] = parse_bytes(path.read_bytes(), st, out_columns, keep_offsets, end_use_offsets)
        series[st] = {out_columns[off]: arr for off, arr in cols.items()}
        print(f"verify: parsed {st}", flush=True)

    rule = evaluate_rule(series, end_use_names)
    build_rule = json.loads((data_root / "filtered" / DATASET_ID / "column_selection.json").read_text(encoding="utf-8"))
    for name in end_use_names:
        mine, theirs = rule[name], build_rule[name]
        if mine["flags"] != theirs["reasons"] or mine["pairs"] != theirs["rescaled_pair_count"] or mine["zero_states"] != theirs["all_zero_states"]:
            raise VerifyError(f"rule disagreement for {name}: verify={mine} build={theirs['reasons']}/{theirs['rescaled_pair_count']}/{theirs['all_zero_states']}")
    realized_keep = [name for name in end_use_names if rule[name]["decision"] == "keep"]
    if realized_keep != pinned_keep:
        raise VerifyError(f"realized keep list {realized_keep} != pinned {pinned_keep}")
    print(f"verify: rule re-derived; {len(realized_keep)} end uses kept of {len(end_use_names)}")

    by_column = {c["column"]: c for c in columns}
    expected_rows = []
    for src in sources:
        for name in pinned_keep:
            expected_rows.append((src, by_column[name]))

    index_path = data_root / "index" / DATASET_ID / "samples.jsonl"
    rows = [json.loads(line) for line in index_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if len(rows) != len(expected_rows):
        raise VerifyError(f"index has {len(rows)} rows, expected {len(expected_rows)}")
    series_dir = data_root / "samples" / DATASET_ID / SERIES_ID
    seen_hashes = set()
    expected_files = set()
    total_bytes = 0
    for row, (src, col) in zip(rows, expected_rows):
        st = src["state"]
        name = col["column"]
        x = series[st][name]
        n = len(x)
        want = struct.pack(f"<{n}d", *x)
        fname = f"{st}__{col['fuel']}.{col['end_use']}.f64le.bin"
        expected_files.add(fname)
        rel = f"samples/{DATASET_ID}/{SERIES_ID}/{fname}"
        got = (data_root / rel).read_bytes()
        if got != want:
            raise VerifyError(f"{rel}: bytes differ from the re-derived column")
        stored = struct.unpack(f"<{n}d", got)
        digest = hashlib.sha256(got).hexdigest()
        if digest in seen_hashes:
            raise VerifyError(f"{rel}: duplicate sample")
        seen_hashes.add(digest)
        distinct = distinct_count(stored)
        if distinct < MIN_DISTINCT:
            raise VerifyError(f"{rel}: degenerate ({distinct} distinct values)")
        models_used, units = meta[st]
        expect = {
            "dataset_id": DATASET_ID,
            "series_id": SERIES_ID,
            "sample_path": rel,
            "numeric_kind": "float",
            "bit_width": 64,
            "endianness": "little",
            "element_size_bytes": 8,
            "sample_size_bytes": len(got),
            "value_count": n,
            "state": st,
            "source_column": name,
            "fuel": col["fuel"],
            "end_use": col["end_use"],
            "first_timestamp_est": lattice(0),
            "last_timestamp_est": lattice(n - 1),
            "interval_minutes": 15,
            "models_used": int(models_used),
            "units_represented": float(units),
            "source_key": src["key"],
            "source_md5": src["etag_md5"],
            "min": min(stored),
            "max": max(stored),
            "distinct_values": distinct,
            "zero_values": sum(1 for v in stored if v == 0.0),
            "negative_values": sum(1 for v in stored if v < 0.0),
            "sha256": digest,
        }
        for key, value in expect.items():
            if row.get(key) != value:
                raise VerifyError(f"{rel}: index field {key}={row.get(key)!r}, expected {value!r}")
        total_bytes += len(got)
    on_disk = {p.name for p in series_dir.iterdir()}
    if on_disk != expected_files:
        raise VerifyError(f"stray or missing sample files: extra={sorted(on_disk - expected_files)[:5]} missing={sorted(expected_files - on_disk)[:5]}")
    others = [p.name for p in (data_root / "samples" / DATASET_ID).iterdir() if p.name != SERIES_ID]
    if others:
        raise VerifyError(f"unexpected entries under samples/{DATASET_ID}: {others}")

    manifest = tomllib.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("dataset_id") != DATASET_ID:
        raise VerifyError("manifest dataset_id mismatch")
    series_entries = {s["id"]: s for s in manifest.get("series", [])}
    if set(series_entries) != {SERIES_ID}:
        raise VerifyError(f"manifest series {sorted(series_entries)} != [{SERIES_ID}]")
    entry = series_entries[SERIES_ID]
    for key, value in {"role": "primary", "numeric_kind": "float", "bit_width": 64, "endianness": "little",
                       "sample_count": len(rows), "total_size_bytes": total_bytes}.items():
        if entry.get(key) != value:
            raise VerifyError(f"manifest {key}={entry.get(key)!r}, realized {value!r}")
    if total_bytes > 1_000_000_000:
        raise VerifyError("primary output exceeds 1 GB")
    print(f"verify: OK {len(rows)} samples, {sum(r['value_count'] for r in rows)} values, {total_bytes} bytes")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--recipe-dir", type=Path, required=True)
    parser.add_argument("--download-dir", type=Path, required=True)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args()
    try:
        verify(args.recipe_dir, args.download_dir, args.data_root, args.manifest)
    except (VerifyError, OSError, KeyError, json.JSONDecodeError) as exc:
        print(f"FATAL: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
