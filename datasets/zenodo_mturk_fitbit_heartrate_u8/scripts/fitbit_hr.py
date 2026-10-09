#!/usr/bin/env python3
"""Fitbit intraday heart rate (Furberg et al., Zenodo 53894) -> uint8 samples.

Subcommands:
  check-download  validate the two pinned zips semantically (member present,
                  pinned size/CRC, CSV header, parseable rows)
  build           emit one uint8 sample per (participant Id, export period)
  verify          independently re-derive every sample and check the index

Pure standard library. Only the heartrate_seconds_merged.csv members are read.
"""
from __future__ import annotations

import argparse
import collections
import datetime
import hashlib
import json
import re
import sys
import tomllib
import zipfile
from pathlib import Path

DATASET_ID = "zenodo_mturk_fitbit_heartrate_u8"
SERIES_ID = "fitbit_heartrate_bpm_u8"
MIN_VALUES = 1000
HEADER = "Id,Time,Value"

# (export tag, zip filename, member name, member uncompressed size, member CRC32,
#  nominal export window as inclusive local dates). Export 1 spills 23,424 rows
#  onto 2016-04-12 that are exact (Id, Time, Value) copies of export-2 rows; rows
#  outside an export's nominal window are dropped so no reading is emitted twice.
EXPORTS = [
    (
        "e1_20160312_20160411",
        "mturkfitbit_export_3.12.16-4.11.16.zip",
        "Fitabase Data 3.12.16-4.11.16/heartrate_seconds_merged.csv",
        41069585,
        0xB5464AE1,
        ("2016-03-12", "2016-04-11"),
    ),
    (
        "e2_20160412_20160512",
        "mturkfitbit_export_4.12.16-5.12.16.zip",
        "Fitabase Data 4.12.16-5.12.16/heartrate_seconds_merged.csv",
        89588303,
        0x8070FBE2,
        ("2016-04-12", "2016-05-12"),
    ),
]


def paths(repo_root: Path, data_dir: str) -> dict[str, Path]:
    root = (repo_root / data_dir).resolve() if not Path(data_dir).is_absolute() else Path(data_dir)
    return {
        "data": root,
        "downloads": root / "downloads" / DATASET_ID,
        "samples": root / "samples" / DATASET_ID / SERIES_ID,
        "index": root / "index" / DATASET_ID,
        "filtered": root / "filtered" / DATASET_ID,
    }


def read_member(zip_path: Path, member: str, size: int, crc: int) -> str:
    with zipfile.ZipFile(zip_path) as zf:
        info = zf.getinfo(member)
        if info.file_size != size or info.CRC != crc:
            raise SystemExit(
                f"{zip_path.name}:{member}: size/CRC {info.file_size}/{info.CRC:08x} != pinned {size}/{crc:08x}"
            )
        raw = zf.read(member)  # zipfile verifies the CRC while reading
    if len(raw) != size:
        raise SystemExit(f"{member}: inflated {len(raw)} bytes, expected {size}")
    return raw.decode("ascii")


# ---------------------------------------------------------------- build path

def parse_rows_build(text: str, label: str, window=None):
    lines = text.splitlines()
    if not lines or lines[0].strip() != HEADER:
        raise SystemExit(f"{label}: unexpected header {lines[:1]!r}")
    seen: set[str] = set()
    exact_dups = 0
    out_of_window = 0
    lo = datetime.date.fromisoformat(window[0]) if window else None
    hi = datetime.date.fromisoformat(window[1]) if window else None
    groups: dict[str, list[tuple[datetime.datetime, int, int]]] = collections.defaultdict(list)
    for order, line in enumerate(lines[1:]):
        line = line.strip()
        if not line:
            continue
        if line in seen:
            exact_dups += 1
            continue
        seen.add(line)
        parts = line.split(",")
        if len(parts) != 3 or not parts[0].isdigit():
            raise SystemExit(f"{label}: malformed row {line!r}")
        ts = datetime.datetime.strptime(parts[1], "%m/%d/%Y %I:%M:%S %p")
        value = int(parts[2])
        if not 1 <= value <= 255:
            raise SystemExit(f"{label}: heart rate {value} outside 1..255 in row {line!r}")
        if window and not lo <= ts.date() <= hi:
            out_of_window += 1
            continue
        groups[parts[0]].append((ts, order, value))
    return groups, exact_dups, len(lines) - 1, out_of_window


def cmd_check_download(args) -> None:
    p = paths(Path(args.repo_root), args.data_dir)
    for tag, zname, member, size, crc, window in EXPORTS:
        text = read_member(p["downloads"] / zname, member, size, crc)
        groups, dups, rows, _ = parse_rows_build(text, f"{zname}:{member}")
        print(f"ok {zname} member_rows={rows} ids={len(groups)} exact_duplicate_rows={dups}")


def cmd_build(args) -> None:
    p = paths(Path(args.repo_root), args.data_dir)
    parsed = {}
    all_ids: set[str] = set()
    for tag, zname, member, size, crc, window in EXPORTS:
        text = read_member(p["downloads"] / zname, member, size, crc)
        groups, dups, rows, oow = parse_rows_build(text, f"{zname}:{member}", window)
        parsed[tag] = (groups, dups, rows, oow)
        all_ids.update(groups)
    # Pseudonymous Ids are replaced by an ordinal over the union of HR Ids in
    # both exports (same participant -> same ordinal); Ids are never emitted.
    ordinal = {pid: n for n, pid in enumerate(sorted(all_ids, key=int), 1)}

    p["samples"].mkdir(parents=True, exist_ok=True)
    p["index"].mkdir(parents=True, exist_ok=True)
    p["filtered"].mkdir(parents=True, exist_ok=True)
    for old in p["samples"].glob("*.bin"):
        old.unlink()

    index_rows = []
    stats = {"dataset_id": DATASET_ID, "exports": []}
    for tag, zname, member, size, crc, window in EXPORTS:
        groups, dups, rows, oow = parsed[tag]
        export_stats = {
            "export": tag, "zip": zname, "member": member, "source_rows": rows,
            "nominal_window": list(window), "out_of_window_rows_removed": oow,
            "exact_duplicate_rows_removed": dups, "ids_with_hr": len(groups),
            "kept": [], "dropped_short": [],
        }
        for pid in sorted(groups, key=lambda x: ordinal[x]):
            recs = sorted(groups[pid], key=lambda r: (r[0], r[1]))
            n = len(recs)
            label = f"p{ordinal[pid]:02d}"
            if n < MIN_VALUES:
                export_stats["dropped_short"].append({"participant": label, "values": n})
                continue
            same_ts = sum(1 for a, b in zip(recs, recs[1:]) if a[0] == b[0])
            gaps = sorted(int((b[0] - a[0]).total_seconds()) for a, b in zip(recs, recs[1:]))
            payload = bytes(r[2] for r in recs)
            rel = Path("samples") / DATASET_ID / SERIES_ID / f"{tag}_{label}.bin"
            (p["data"] / rel).write_bytes(payload)
            row = {
                "dataset_id": DATASET_ID,
                "series_id": SERIES_ID,
                "sample_path": rel.as_posix(),
                "numeric_kind": "uint",
                "bit_width": 8,
                "endianness": "little",
                "element_size_bytes": 1,
                "sample_size_bytes": len(payload),
                "value_count": n,
                "export": tag,
                "participant": label,
                "first_local_time": recs[0][0].isoformat(),
                "last_local_time": recs[-1][0].isoformat(),
                "min": min(payload),
                "max": max(payload),
                "distinct_values": len(set(payload)),
                "median_gap_seconds": gaps[len(gaps) // 2],
                "same_timestamp_conflicts": same_ts,
                "sha256": hashlib.sha256(payload).hexdigest(),
            }
            index_rows.append(row)
            export_stats["kept"].append({"participant": label, "values": n, "same_timestamp_conflicts": same_ts})
        stats["exports"].append(export_stats)

    with open(p["index"] / "samples.jsonl", "w", encoding="utf-8") as fh:
        for row in index_rows:
            fh.write(json.dumps(row, sort_keys=True) + "\n")
    stats["sample_count"] = len(index_rows)
    stats["total_values"] = sum(r["value_count"] for r in index_rows)
    (p["filtered"] / "ingest_stats.json").write_text(json.dumps(stats, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: stats[k] for k in ("sample_count", "total_values")}))
    for e in stats["exports"]:
        print(f"{e['export']}: rows={e['source_rows']} ids={e['ids_with_hr']} kept={len(e['kept'])} "
              f"dropped_short={e['dropped_short']} exact_dups={e['exact_duplicate_rows_removed']} "
              f"out_of_window={e['out_of_window_rows_removed']}")


# --------------------------------------------------------------- verify path
# Deliberately a separate implementation: regex timestamp decoding to a sortable
# integer key, a dict-based duplicate filter, and byte-for-byte comparison.

TS_RE = re.compile(r"^(\d{1,2})/(\d{1,2})/(\d{4}) (\d{1,2}):(\d{2}):(\d{2}) (AM|PM)$")


def _us_date(iso: str) -> str:
    y, m, d = iso.split("-")
    return f"{int(m)}/{int(d)}/{y}"


def ts_key(s: str) -> int:
    m = TS_RE.match(s)
    if not m:
        raise SystemExit(f"verify: bad timestamp {s!r}")
    mo, d, y, h, mi, se, ap = m.groups()
    h = int(h) % 12 + (12 if ap == "PM" else 0)
    days = datetime.date(int(y), int(mo), int(d)).toordinal()
    return ((days * 24 + h) * 60 + int(mi)) * 60 + int(se)


def derive_verify(text: str, window) -> dict[str, list[int]]:
    lo_key = ts_key(_us_date(window[0]) + " 12:00:00 AM")
    hi_key = ts_key(_us_date(window[1]) + " 11:59:59 PM")
    rows = text.splitlines()
    assert rows[0].strip() == HEADER, rows[0]
    unique = dict.fromkeys(r.strip() for r in rows[1:] if r.strip())
    per_id: dict[str, list[tuple[int, int, int]]] = {}
    for pos, line in enumerate(unique):
        pid, ts, val = line.split(",")
        v = int(val)
        if v < 1 or v > 255:
            raise SystemExit(f"verify: value {v} out of range")
        k = ts_key(ts)
        if k < lo_key or k > hi_key:
            continue
        per_id.setdefault(pid, []).append((k, pos, v))
    return {pid: [v for _, _, v in sorted(recs)] for pid, recs in per_id.items()}


def cmd_verify(args) -> None:
    repo_root = Path(args.repo_root)
    p = paths(repo_root, args.data_dir)
    manifest = tomllib.loads(Path(args.manifest).read_text(encoding="utf-8"))
    series = [s for s in manifest["series"] if s["id"] == SERIES_ID]
    assert len(series) == 1, "manifest must declare the primary series once"
    series = series[0]

    derived: dict[str, dict[str, list[int]]] = {}
    ids: set[str] = set()
    for tag, zname, member, size, crc, window in EXPORTS:
        derived[tag] = derive_verify(read_member(p["downloads"] / zname, member, size, crc), window)
        ids.update(derived[tag])
    ordinal = {pid: n for n, pid in enumerate(sorted(ids, key=int), 1)}

    expected: dict[str, bytes] = {}
    for tag, groups in derived.items():
        for pid, vals in groups.items():
            if len(vals) >= MIN_VALUES:
                rel = f"samples/{DATASET_ID}/{SERIES_ID}/{tag}_p{ordinal[pid]:02d}.bin"
                expected[rel] = bytes(vals)

    index_rows = [json.loads(l) for l in (p["index"] / "samples.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    indexed = {r["sample_path"]: r for r in index_rows}
    if len(indexed) != len(index_rows):
        raise SystemExit("verify: duplicate sample_path rows in index")
    if set(indexed) != set(expected):
        raise SystemExit(f"verify: index/sample set mismatch: missing={sorted(set(expected) - set(indexed))} "
                         f"extra={sorted(set(indexed) - set(expected))}")
    on_disk = {f"samples/{DATASET_ID}/{SERIES_ID}/{f.name}" for f in p["samples"].glob("*")}
    if on_disk != set(expected):
        raise SystemExit(f"verify: stray or missing files under samples: {sorted(on_disk ^ set(expected))}")

    hashes = set()
    total_bytes = 0
    for rel, payload in sorted(expected.items()):
        row = indexed[rel]
        disk = (p["data"] / rel).read_bytes()
        if disk != payload:
            raise SystemExit(f"verify: {rel} differs from independent re-derivation")
        for key, want in (("dataset_id", DATASET_ID), ("series_id", SERIES_ID), ("numeric_kind", "uint"),
                          ("bit_width", 8), ("endianness", "little"), ("element_size_bytes", 1),
                          ("sample_size_bytes", len(payload)), ("value_count", len(payload)),
                          ("min", min(payload)), ("max", max(payload)),
                          ("sha256", hashlib.sha256(payload).hexdigest())):
            if row.get(key) != want:
                raise SystemExit(f"verify: {rel} index {key}={row.get(key)!r} expected {want!r}")
        if len(payload) < MIN_VALUES:
            raise SystemExit(f"verify: {rel} below {MIN_VALUES} values")
        if len(set(payload)) < 10:
            raise SystemExit(f"verify: {rel} degenerate ({len(set(payload))} distinct values)")
        if 0 in payload:
            raise SystemExit(f"verify: {rel} contains 0 bpm")
        h = row["sha256"]
        if h in hashes:
            raise SystemExit(f"verify: duplicate sample payload {rel}")
        hashes.add(h)
        total_bytes += len(payload)

    if series["sample_count"] != len(expected) or series["total_size_bytes"] != total_bytes:
        raise SystemExit(f"verify: manifest sample_count/total_size_bytes {series['sample_count']}/"
                         f"{series['total_size_bytes']} != realized {len(expected)}/{total_bytes}")
    sizes = sorted(len(v) for v in expected.values())
    print(f"verify ok samples={len(expected)} values={total_bytes} median={sizes[len(sizes) // 2]} "
          f"min_sample={sizes[0]} max_sample={sizes[-1]}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("command", choices=["check-download", "build", "verify"])
    ap.add_argument("--repo-root", required=True)
    ap.add_argument("--data-dir", default=".data")
    ap.add_argument("--manifest")
    args = ap.parse_args()
    {"check-download": cmd_check_download, "build": cmd_build, "verify": cmd_verify}[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
