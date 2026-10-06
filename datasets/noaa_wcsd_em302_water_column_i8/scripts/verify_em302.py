#!/usr/bin/env python3
"""Independently re-decode the pinned EM302 .wcd files and check every emitted sample.

This verifier does not reuse the build decoder: it streams each file through
its own datagram reader (int.from_bytes field access, explicit offsets), applies
the same selection policy (complete pings only; partial pings allowed only at
the first/last water-column ping of a file; pings whose amplitudes are all one
value are dropped), and then compares sample bytes, index rows, ingest stats,
and manifest totals.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tomllib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from em302_wcd import DATASET_ID, FILES, etag_matches  # noqa: E402  (pinned identity table only)

PRIMARY = "em302_ping_water_column_amplitude_i8"
AUX_SAMPLE_COUNT = "em302_ping_beam_sample_count_u16"
AUX_POINTING = "em302_ping_beam_pointing_angle_i16"
BEAMS = 288
MIN_DISTINCT = 16


def u16(buf: bytes, at: int) -> int:
    return int.from_bytes(buf[at : at + 2], "little")


def i16(buf: bytes, at: int) -> int:
    return int.from_bytes(buf[at : at + 2], "little", signed=True)


def u32(buf: bytes, at: int) -> int:
    return int.from_bytes(buf[at : at + 4], "little")


def fail(message: str) -> None:
    raise SystemExit(f"verify failed: {message}")


def read_pings(path: Path) -> tuple[list[dict], int, int]:
    pings: dict[tuple[int, int, int], dict] = {}
    order: list[tuple[int, int, int]] = []
    with path.open("rb") as handle:
        offset = 0
        while True:
            head = handle.read(4)
            if not head:
                break
            if len(head) != 4:
                fail(f"{path.name}: trailing bytes at {offset}")
            length = int.from_bytes(head, "little")
            body = handle.read(length)
            if len(body) != length or length < 19:
                fail(f"{path.name}: truncated datagram at {offset}")
            if body[0] != 2 or body[-3] != 3:
                fail(f"{path.name}: STX/ETX framing error at {offset}")
            if sum(body[1:-3]) % 65536 != u16(body, length - 2):
                fail(f"{path.name}: checksum error at {offset}")
            if u16(body, 2) != 302:
                fail(f"{path.name}: non-EM302 datagram at {offset}")
            if body[1] == ord("k"):
                date, time_ms, counter, serial = u32(body, 4), u32(body, 8), u16(body, 12), u16(body, 14)
                n_dgrams, dgram_no, n_tx, n_rx_total, n_rx = (u16(body, 16 + 2 * i) for i in range(5))
                tvg_function, tvg_offset = body[34], int.from_bytes(body[35:36], "little", signed=True)
                if serial != 101 or tvg_function != 30 or tvg_offset != 20 or n_rx_total != BEAMS:
                    fail(f"{path.name}: unexpected serial/TVG/beam count at {offset}")
                # Per-ping invariant header bytes: Nd, Ntx, Nrx-total, sound speed, sample
                # frequency, TX heave, TVG function/offset, scan info (not datagram# / Nrx / spare).
                fixed = body[16:18] + body[20:24] + body[26:37]
                at = 40
                tx = b"".join(body[at + 6 * i : at + 6 * i + 5] for i in range(n_tx))  # skip spare byte
                if any(body[at + 6 * i + 4] >= n_tx for i in range(n_tx)):
                    fail(f"{path.name}: transmit sector out of range at {offset}")
                at += 6 * n_tx
                beams = []
                chunks = []
                for _ in range(n_rx):
                    angle, start, count = i16(body, at), u16(body, at + 2), u16(body, at + 4)
                    if start != 0 or body[at + 8] >= n_tx:
                        fail(f"{path.name}: unexpected beam start/sector at {offset}")
                    at += 10
                    chunks.append(body[at : at + count])
                    if len(chunks[-1]) != count:
                        fail(f"{path.name}: truncated beam at {offset}")
                    beams.append((angle, count))
                    at += count
                if length - 3 - at not in (0, 1) or any(body[at : length - 3]):
                    fail(f"{path.name}: water-column datagram length mismatch at {offset}")
                key = (date, time_ms, counter)
                if key not in pings:
                    pings[key] = {"parts": {}, "fixed": fixed + tx, "n": n_dgrams, "offsets": []}
                    order.append(key)
                entry = pings[key]
                if entry["fixed"] != fixed + tx or entry["n"] != n_dgrams or dgram_no in entry["parts"]:
                    fail(f"{path.name}: inconsistent or duplicate datagram in ping {key}")
                entry["parts"][dgram_no] = (beams, b"".join(chunks), offset)
            offset += 4 + length
    kept = []
    partial = blank = 0
    for position, key in enumerate(order):
        entry = pings[key]
        if sorted(entry["parts"]) != list(range(1, entry["n"] + 1)):
            if position not in (0, len(order) - 1):
                fail(f"{path.name}: interior incomplete ping {key}")
            partial += 1
            continue
        parts = [entry["parts"][number] for number in range(1, entry["n"] + 1)]
        beams = [beam for part in parts for beam in part[0]]
        payload = b"".join(part[1] for part in parts)
        if len(beams) != BEAMS or any(a <= b for (a, _), (b, _) in zip(beams, beams[1:])):
            fail(f"{path.name}: ping {key} beam geometry invalid")
        if len(set(payload)) <= 1:
            blank += 1
            continue
        kept.append({"key": key, "beams": beams, "payload": payload, "offsets": [part[2] for part in parts]})
    return kept, partial, blank


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--download-dir", type=Path, required=True)
    parser.add_argument("--index", type=Path, required=True)
    parser.add_argument("--stats", type=Path, required=True)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args()

    if not args.index.is_file() or not args.stats.is_file():
        fail("missing index or ingest stats; run build.sh first")
    rows = [json.loads(line) for line in args.index.read_text(encoding="utf-8").splitlines() if line.strip()]
    stats = json.loads(args.stats.read_text(encoding="utf-8"))
    manifest = tomllib.loads(args.manifest.read_text(encoding="utf-8"))
    by_series: dict[str, list[dict]] = {PRIMARY: [], AUX_SAMPLE_COUNT: [], AUX_POINTING: []}
    for row in rows:
        if row.get("dataset_id") != DATASET_ID or row.get("series_id") not in by_series:
            fail(f"unexpected index row {row.get('sample_path')}")
        by_series[row["series_id"]].append(row)

    cursor = 0
    expected_paths = set()
    totals = {series: [0, 0] for series in by_series}
    file_stats = {item["source_file"]: item for item in stats.get("files", [])}
    hashes = set()
    global_min, global_max = 127, -128
    for name, size, etag in FILES:
        path = args.download_dir / name
        if not path.is_file() or path.stat().st_size != size or not etag_matches(path, etag):
            fail(f"source {name} missing or not matching pinned size/ETag")
        pings, partial, blank = read_pings(path)
        recorded = file_stats.get(name)
        if recorded is None or recorded.get("emitted_pings") != len(pings):
            fail(f"{name}: emitted ping count differs from independent decode ({len(pings)})")
        if len(recorded.get("dropped_edge_partial_pings", [])) != partial or len(recorded.get("dropped_blank_pings", [])) != blank:
            fail(f"{name}: dropped-ping accounting differs (partial={partial}, blank={blank})")
        for ordinal, ping in enumerate(pings, 1):
            primary = by_series[PRIMARY][cursor]
            counts_row = by_series[AUX_SAMPLE_COUNT][cursor]
            angle_row = by_series[AUX_POINTING][cursor]
            cursor += 1
            date, time_ms, counter = ping["key"]
            for row in (primary, counts_row, angle_row):
                if (row.get("source_file"), row.get("ping_ordinal_in_file"), row.get("ping_counter"), row.get("ping_date"), row.get("ping_time_ms")) != (
                    name, ordinal, counter, date, time_ms
                ):
                    fail(f"{name}: index ordering mismatch at ping {ordinal}")
                if row.get("source_datagram_offsets") != ping["offsets"]:
                    fail(f"{name}: datagram offsets mismatch at ping {ordinal}")
            payload = ping["payload"]
            counts_bytes = b"".join(count.to_bytes(2, "little") for _, count in ping["beams"])
            angle_bytes = b"".join(angle.to_bytes(2, "little", signed=True) for angle, _ in ping["beams"])
            for row, data, kind, width in (
                (primary, payload, "int", 8),
                (counts_row, counts_bytes, "uint", 16),
                (angle_row, angle_bytes, "int", 16),
            ):
                sample = args.data_root / row["sample_path"]
                expected_paths.add(sample.resolve())
                if not sample.is_file() or sample.read_bytes() != data:
                    fail(f"{row['sample_path']} differs from the independent decode")
                element = width // 8
                if (row.get("numeric_kind"), row.get("bit_width"), row.get("endianness"), row.get("element_size_bytes")) != (kind, width, "little", element):
                    fail(f"{row['sample_path']}: numeric metadata mismatch")
                if row.get("sample_size_bytes") != len(data) or row.get("value_count") != len(data) // element:
                    fail(f"{row['sample_path']}: size metadata mismatch")
                totals[row["series_id"]][0] += 1
                totals[row["series_id"]][1] += len(data)
            stored = (args.data_root / primary["sample_path"]).read_bytes()
            values = memoryview(stored).cast("b")
            low, high = min(values), max(values)
            distinct = len(set(stored))
            if distinct < MIN_DISTINCT or len(stored) < 1000:
                fail(f"{primary['sample_path']}: degenerate ping ({distinct} distinct values, {len(stored)} values)")
            if (primary.get("minimum"), primary.get("maximum"), primary.get("distinct_values")) != (low, high, distinct):
                fail(f"{primary['sample_path']}: stored int8 min/max/distinct mismatch")
            if primary.get("floor_count") != stored.count(b"\x80"):
                fail(f"{primary['sample_path']}: floor count mismatch")
            digest = hashlib.sha256(stored).hexdigest()
            if primary.get("sha256") != digest or digest in hashes:
                fail(f"{primary['sample_path']}: hash mismatch or duplicate ping payload")
            hashes.add(digest)
            if primary.get("beam_sample_count_min") != min(c for _, c in ping["beams"]) or primary.get("beam_sample_count_max") != max(c for _, c in ping["beams"]):
                fail(f"{primary['sample_path']}: beam sample-count range mismatch")
            global_min, global_max = min(global_min, low), max(global_max, high)
    for series, series_rows in by_series.items():
        if len(series_rows) != cursor:
            fail(f"{series}: {len(series_rows)} index rows, expected {cursor}")
    actual_paths = {path.resolve() for path in (args.data_root / "samples" / DATASET_ID).glob("*/*.bin")}
    if actual_paths != expected_paths:
        fail("sample directory contents do not exactly match the index")
    if (stats.get("primary_global_minimum"), stats.get("primary_global_maximum")) != (global_min, global_max):
        fail("ingest stats global min/max mismatch")
    if global_max - global_min < 64:
        fail(f"primary amplitude range is degenerate ({global_min}..{global_max})")
    manifest_series = {item["id"]: item for item in manifest.get("series", [])}
    for series, (count, size) in totals.items():
        declared = manifest_series.get(series)
        if declared is None:
            fail(f"manifest lacks series {series}")
        if declared.get("sample_count") != count or declared.get("total_size_bytes") != size:
            fail(f"manifest {series} declares {declared.get('sample_count')}/{declared.get('total_size_bytes')}, realized {count}/{size}")
        if stats["series"][series] != {"sample_count": count, "total_size_bytes": size}:
            fail(f"ingest stats totals mismatch for {series}")
    print(json.dumps({
        "dataset_id": DATASET_ID,
        "verified_pings": cursor,
        "primary_bytes": totals[PRIMARY][1],
        "auxiliary_bytes": totals[AUX_SAMPLE_COUNT][1] + totals[AUX_POINTING][1],
        "primary_global_range": [global_min, global_max],
    }, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
