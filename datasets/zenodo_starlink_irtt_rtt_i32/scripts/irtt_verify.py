#!/usr/bin/env python3
"""Independently re-derive and check the Starlink IRTT int32 samples.

Two primary series: delay.rtt and delay.receive (delay.send is intentionally
not emitted; it is ~= rtt - receive). Re-streams the pinned tar.zst, re-parses
every IRTT session, and checks:
  * every sample file is byte-identical to a fresh decode of the same field,
    with the same missing-value policy (take the field wherever present,
    drop and count probes without it, never fill);
  * per session and field, the count, sum, min and max of the emitted values
    equal IRTT's own summary block (stats.rtt / stats.receive_delay: n, total,
    min, max);
  * index rows are complete and consistent with files and manifest;
  * no sample is constant, all five pinned dates are realized, and there are
    no stray sample files or directories (only the two series directories may
    exist under samples/<id>/).
"""
from __future__ import annotations

import argparse
import collections
import json
import re
import struct
import subprocess
import sys
import tarfile
import tomllib
from pathlib import Path

DATASET_ID = "zenodo_starlink_irtt_rtt_i32"
DATES = ("2023-09-13", "2023-09-14", "2023-09-15", "2023-09-16", "2023-09-17")
FIELDS = {  # series id -> (delay key, IRTT stats key)
    "irtt_rtt_ns_i32": ("rtt", "rtt"),
    "irtt_receive_delay_ns_i32": ("receive", "receive_delay"),
}
NAME = re.compile(r"data/(2023-09-1[3-7])/irtt-10ms-2m-(2023-09-1[3-7]-\d\d-\d\d-\d\d)\.json")
INDEX_KEYS = ("dataset_id", "series_id", "sample_path", "numeric_kind", "bit_width", "endianness",
              "element_size_bytes", "sample_size_bytes", "value_count")


def fail(errors: list[str], message: str) -> None:
    errors.append(message)
    print(f"ERROR {message}", flush=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--archive", required=True, type=Path)
    ap.add_argument("--data-root", required=True, type=Path)
    ap.add_argument("--manifest", required=True, type=Path)
    a = ap.parse_args()
    root = a.data_root
    errors: list[str] = []

    index_path = root / "index" / DATASET_ID / "samples.jsonl"
    rows = [json.loads(line) for line in index_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    by_key: dict[tuple[str, str], dict] = {}
    for n, row in enumerate(rows, 1):
        missing = [k for k in INDEX_KEYS if k not in row]
        if missing:
            fail(errors, f"index line {n} missing {missing}")
            continue
        if (row["dataset_id"], row["numeric_kind"], row["bit_width"], row["endianness"], row["element_size_bytes"]) != (
                DATASET_ID, "int", 32, "little", 4):
            fail(errors, f"index line {n} has wrong type fields")
        if row["series_id"] not in FIELDS:
            fail(errors, f"index line {n} unknown series {row['series_id']}")
        key = (row["series_id"], row["session_id"])
        if key in by_key:
            fail(errors, f"duplicate index row {key}")
        by_key[key] = row

    series_root = root / "samples" / DATASET_ID
    extra_dirs = sorted(p.name for p in series_root.iterdir() if p.name not in FIELDS)
    if extra_dirs:
        fail(errors, f"unexpected entries under samples/{DATASET_ID}/: {extra_dirs}")
    for sid in FIELDS:
        if not (series_root / sid).is_dir():
            fail(errors, f"missing series directory {sid}")
    on_disk = {p.relative_to(root).as_posix() for p in (root / "samples" / DATASET_ID).rglob("*") if p.is_file()}
    indexed = {r["sample_path"] for r in rows}
    if on_disk != indexed:
        fail(errors, f"sample files vs index differ: stray={sorted(on_disk - indexed)[:5]} missing={sorted(indexed - on_disk)[:5]}")

    proc = subprocess.Popen(["zstd", "-dc", "--", str(a.archive)], stdout=subprocess.PIPE)
    matched: set[tuple[str, str]] = set()
    sessions_by_date = collections.Counter()
    checked_values = 0
    with tarfile.open(fileobj=proc.stdout, mode="r|") as tar:
        for member in tar:
            m = NAME.fullmatch(member.name)
            if not member.isfile() or not m:
                if member.isfile() and "/irtt" in member.name:
                    fail(errors, f"unexpected IRTT-like member name {member.name}")
                continue
            if not m.group(2).startswith(m.group(1)):
                fail(errors, f"{member.name}: timestamp outside its day folder")
            session_id = f"irtt-10ms-2m-{m.group(2)}"
            doc = json.load(tar.extractfile(member))
            sessions_by_date[m.group(1)] += 1
            trips = doc["round_trips"]
            lost = collections.Counter(t["lost"] for t in trips)
            if set(lost) - {"false", "true", "true_down", "true_up"}:
                fail(errors, f"{session_id}: unknown lost states {sorted(lost)}")
            for sid, (dkey, skey) in FIELDS.items():
                expect = [t["delay"][dkey] for t in trips if isinstance(t.get("delay"), dict) and dkey in t["delay"]]
                summary = (doc.get("stats") or {}).get(skey) or {}
                n_src = int(summary.get("n") or 0)
                if n_src != len(expect):
                    fail(errors, f"{session_id} {sid}: decoded {len(expect)} values but IRTT stats n={n_src}")
                if expect:
                    if (sum(expect), min(expect), max(expect)) != (summary.get("total"), summary.get("min"), summary.get("max")):
                        fail(errors, f"{session_id} {sid}: sum/min/max disagree with IRTT stats block")
                row = by_key.get((sid, session_id))
                if not expect:
                    if row is not None:
                        fail(errors, f"{session_id} {sid}: indexed although source has no values")
                    continue
                if row is None:
                    fail(errors, f"{session_id} {sid}: source has {len(expect)} values but no sample")
                    continue
                matched.add((sid, session_id))
                blob = (root / row["sample_path"]).read_bytes()
                if len(blob) != 4 * len(expect) or row["value_count"] != len(expect) or row["sample_size_bytes"] != len(blob):
                    fail(errors, f"{session_id} {sid}: size/count mismatch")
                    continue
                got = list(struct.unpack(f"<{len(expect)}i", blob))
                if got != expect:
                    fail(errors, f"{session_id} {sid}: sample bytes differ from source decode")
                if min(got) == max(got):
                    fail(errors, f"{session_id} {sid}: constant sample")
                if (row.get("min"), row.get("max")) != (min(got), max(got)):
                    fail(errors, f"{session_id} {sid}: index min/max stale")
                if row.get("probes_total") != len(trips) or row.get("probes_dropped") != len(trips) - len(expect):
                    fail(errors, f"{session_id} {sid}: dropped-probe accounting mismatch")
                if row.get("lost_counts", {}).get("false") != lost.get("false", 0):
                    fail(errors, f"{session_id} {sid}: lost_counts mismatch")
                checked_values += len(expect)
    proc.stdout.close()
    if proc.wait() != 0:
        fail(errors, "zstd -dc failed")

    if set(by_key) != matched:
        fail(errors, f"index rows without a source session: {sorted(set(by_key) - matched)[:5]}")
    if tuple(sorted(sessions_by_date)) != DATES:
        fail(errors, f"realized dates {sorted(sessions_by_date)} != {DATES}")

    manifest = tomllib.loads(a.manifest.read_text(encoding="utf-8"))
    declared = {s["id"]: s for s in manifest.get("series", [])}
    for sid in FIELDS:
        srows = [r for r in rows if r["series_id"] == sid]
        dates = {r["session_date"] for r in srows}
        if tuple(sorted(dates)) != DATES:
            fail(errors, f"{sid}: dates {sorted(dates)} != {DATES}")
        counts = sorted(r["value_count"] for r in srows)
        size = sum(r["sample_size_bytes"] for r in srows)
        spec = declared.get(sid, {})
        if spec.get("sample_count") != len(srows) or spec.get("total_size_bytes") != size:
            fail(errors, f"{sid}: manifest sample_count/total_size_bytes {spec.get('sample_count')}/{spec.get('total_size_bytes')} != realized {len(srows)}/{size}")
        median = counts[len(counts) // 2] if counts else 0
        print(f"series {sid}: samples={len(srows)} values={sum(counts)} bytes={size} median_values={median} "
              f"min_values={counts[0] if counts else 0}", flush=True)
        if median < 1000:
            fail(errors, f"{sid}: median sample below 1000 values")

    print(f"sessions_by_date={dict(sorted(sessions_by_date.items()))} checked_values={checked_values}")
    if errors:
        print(f"verify FAILED with {len(errors)} errors", file=sys.stderr)
        return 1
    print("verify ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
