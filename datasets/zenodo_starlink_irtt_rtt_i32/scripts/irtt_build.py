#!/usr/bin/env python3
"""Stream the Starlink IRTT archive and emit per-session int32 delay samples.

The tar.zst is decompressed by the zstd CLI into a pipe and read with
tarfile mode 'r|' (sequential, nothing written to disk). Only members named
data/<YYYY-MM-DD>/irtt-10ms-2m-<timestamp>.json are parsed; iperf3 JSON and
anything else are skipped.

For each IRTT session and each of the two fields delay.rtt and delay.receive,
the value is taken from every round_trip (in array order)
whose `delay` object carries that field as a JSON integer; probes without
the field (lost upstream/downstream) are dropped and counted, never filled.
Values are nanoseconds; each is range-checked into signed int32 and packed
little-endian. One sample file per session per field.

delay.send is deliberately not emitted: IRTT computes rtt from monotonic
clocks (minus server processing time) and the one-way delays from NTP-synced
wall clocks, so send ~= rtt - receive (within ~1 us for most probes); it is a
near-duplicate view that the breadth gate measured as redundant.
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import tarfile
from pathlib import Path

DATASET_ID = "zenodo_starlink_irtt_rtt_i32"
MEMBER_RE = re.compile(r"^data/(\d{4}-\d{2}-\d{2})/irtt-10ms-2m-(\d{4}-\d{2}-\d{2}-\d{2}-\d{2}-\d{2})\.json$")
EXPECTED_DATES = ["2023-09-13", "2023-09-14", "2023-09-15", "2023-09-16", "2023-09-17"]
LOST_STATES = {"false", "true", "true_down", "true_up"}
# series id -> (delay field, irtt stats key)
SERIES = {
    "irtt_rtt_ns_i32": ("rtt", "rtt"),
    "irtt_receive_delay_ns_i32": ("receive", "receive_delay"),
}
INTERVAL_NS = 10_000_000
DURATION_NS = 120_000_000_000
I32_MIN, I32_MAX = -(2**31), 2**31 - 1


def iter_irtt_members(archive: Path):
    """Yield (member_name, date, stamp, raw_bytes) for every IRTT member."""
    proc = subprocess.Popen(["zstd", "-dc", "--", str(archive)], stdout=subprocess.PIPE)
    assert proc.stdout is not None
    skipped = collections.Counter()
    try:
        with tarfile.open(fileobj=proc.stdout, mode="r|") as tar:
            for member in tar:
                if not member.isfile():
                    continue
                match = MEMBER_RE.match(member.name)
                if not match:
                    base = member.name.rsplit("/", 1)[-1]
                    skipped[base.split("-", 1)[0] if "-" in base else base] += 1
                    continue
                handle = tar.extractfile(member)
                assert handle is not None
                raw = handle.read()
                if len(raw) != member.size:
                    raise SystemExit(f"short read for {member.name}")
                yield member.name, match.group(1), match.group(2), raw
    finally:
        proc.stdout.close()
        code = proc.wait()
    if code != 0:
        raise SystemExit(f"zstd -dc exited with status {code}")
    print(f"skipped_non_irtt_members={dict(skipped)}", flush=True)


def decode_session(name: str, raw: bytes) -> dict:
    doc = json.loads(raw)
    params = doc["config"]["params"]
    if int(params["interval"]) != INTERVAL_NS or int(params["duration"]) != DURATION_NS:
        raise SystemExit(f"{name}: unexpected IRTT params interval={params['interval']} duration={params['duration']}")
    round_trips = doc["round_trips"]
    if not isinstance(round_trips, list) or not round_trips:
        raise SystemExit(f"{name}: no round_trips array")
    lost_counts: collections.Counter = collections.Counter()
    values: dict[str, list[int]] = {sid: [] for sid in SERIES}
    from_lost_rows: collections.Counter = collections.Counter()
    for rt in round_trips:
        lost = rt.get("lost")
        if lost not in LOST_STATES:
            raise SystemExit(f"{name}: unknown lost state {lost!r} at seqno {rt.get('seqno')}")
        lost_counts[lost] += 1
        delay = rt.get("delay") or {}
        if not isinstance(delay, dict):
            raise SystemExit(f"{name}: delay is not an object at seqno {rt.get('seqno')}")
        for sid, (field, _) in SERIES.items():
            if field not in delay:
                continue
            value = delay[field]
            if type(value) is not int:
                raise SystemExit(f"{name}: delay.{field}={value!r} is not a JSON integer")
            if not I32_MIN <= value <= I32_MAX:
                raise SystemExit(f"{name}: delay.{field}={value} ns overflows int32")
            values[sid].append(value)
            if lost != "false":
                from_lost_rows[sid] += 1
    stats = doc.get("stats") or {}
    return {
        "round_trips": len(round_trips),
        "lost_counts": {key: lost_counts.get(key, 0) for key in sorted(LOST_STATES)},
        "values": values,
        "from_lost_rows": dict(from_lost_rows),
        "start_time": stats.get("start_time"),
        "irtt_stats": {stats_key: stats.get(stats_key) for _, stats_key in SERIES.values()},
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive", required=True, type=Path)
    parser.add_argument("--data-root", required=True, type=Path)
    args = parser.parse_args()

    data_root = args.data_root
    samples_root = data_root / "samples" / DATASET_ID
    index_path = data_root / "index" / DATASET_ID / "samples.jsonl"
    stats_path = data_root / "filtered" / DATASET_ID / "ingest_stats.json"
    if samples_root.exists():
        shutil.rmtree(samples_root)
    for sid in SERIES:
        (samples_root / sid).mkdir(parents=True, exist_ok=True)
    index_path.parent.mkdir(parents=True, exist_ok=True)
    stats_path.parent.mkdir(parents=True, exist_ok=True)

    rows: list[dict] = []
    sessions: list[dict] = []
    seen: set[str] = set()
    totals = collections.Counter()
    aggregate = {sid: hashlib.sha256() for sid in SERIES}
    for name, date, stamp, raw in iter_irtt_members(args.archive):
        if name in seen:
            raise SystemExit(f"duplicate member {name}")
        seen.add(name)
        if date not in EXPECTED_DATES or not stamp.startswith(date):
            raise SystemExit(f"{name}: date outside the pinned 2023-09-13..17 scope")
        session = decode_session(name, raw)
        session_id = f"irtt-10ms-2m-{stamp}"
        sessions.append({
            "member": name,
            "member_bytes": len(raw),
            "member_sha256": hashlib.sha256(raw).hexdigest(),
            "session_id": session_id,
            "date": date,
            "round_trips": session["round_trips"],
            "lost_counts": session["lost_counts"],
            "values_per_series": {sid: len(v) for sid, v in session["values"].items()},
            "values_from_lost_rows": session["from_lost_rows"],
        })
        totals["sessions"] += 1
        totals["round_trips"] += session["round_trips"]
        for key, count in session["lost_counts"].items():
            totals[f"lost_{key}"] += count
        for sid, values in session["values"].items():
            if not values:
                totals[f"{sid}_sessions_without_values"] += 1
                continue
            payload = struct.pack(f"<{len(values)}i", *values)
            rel = Path("samples") / DATASET_ID / sid / f"{session_id}.bin"
            out = data_root / rel
            tmp = out.with_suffix(".bin.part")
            tmp.write_bytes(payload)
            os.replace(tmp, out)
            totals[f"{sid}_values"] += len(values)
            totals[f"{sid}_dropped"] += session["round_trips"] - len(values)
            rows.append({
                "dataset_id": DATASET_ID,
                "series_id": sid,
                "sample_path": rel.as_posix(),
                "numeric_kind": "int",
                "bit_width": 32,
                "endianness": "little",
                "element_size_bytes": 4,
                "sample_size_bytes": len(payload),
                "value_count": len(values),
                "unit": "nanoseconds",
                "source_member": name,
                "session_id": session_id,
                "session_date": date,
                "session_start_time": session["start_time"],
                "probes_total": session["round_trips"],
                "probes_dropped": session["round_trips"] - len(values),
                "lost_counts": session["lost_counts"],
                "min": min(values),
                "max": max(values),
                "sha256": hashlib.sha256(payload).hexdigest(),
            })
        print(f"session {session_id} round_trips={session['round_trips']} lost={session['lost_counts']}", flush=True)

    rows.sort(key=lambda row: (row["series_id"], row["session_id"]))
    for row in rows:
        aggregate[row["series_id"]].update(bytes.fromhex(row["sha256"]))
    realized_dates = sorted({s["date"] for s in sessions})
    if realized_dates != EXPECTED_DATES:
        raise SystemExit(f"realized dates {realized_dates} != pinned {EXPECTED_DATES}")
    for sid in SERIES:
        per_date = collections.Counter(r["session_date"] for r in rows if r["series_id"] == sid)
        missing = [d for d in EXPECTED_DATES if not per_date.get(d)]
        if missing:
            raise SystemExit(f"series {sid} has no samples on {missing}")

    with index_path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")
    summary = {
        "dataset_id": DATASET_ID,
        "archive": args.archive.name,
        "dates": realized_dates,
        "sessions_per_date": dict(sorted(collections.Counter(s["date"] for s in sessions).items())),
        "totals": dict(sorted(totals.items())),
        "series": {
            sid: {
                "samples": sum(1 for r in rows if r["series_id"] == sid),
                "values": sum(r["value_count"] for r in rows if r["series_id"] == sid),
                "bytes": sum(r["sample_size_bytes"] for r in rows if r["series_id"] == sid),
                "min": min(r["min"] for r in rows if r["series_id"] == sid),
                "max": max(r["max"] for r in rows if r["series_id"] == sid),
                "aggregate_sha256": aggregate[sid].hexdigest(),
            }
            for sid in SERIES
        },
        "sessions": sorted(sessions, key=lambda s: s["session_id"]),
    }
    stats_path.write_text(json.dumps(summary, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({k: summary[k] for k in ("dates", "sessions_per_date", "totals", "series")}, indent=1, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
