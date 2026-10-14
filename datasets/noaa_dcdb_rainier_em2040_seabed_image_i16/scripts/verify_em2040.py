#!/usr/bin/env python3
"""Independent verifier for noaa_dcdb_rainier_em2040_seabed_image_i16.

Re-reads every pinned raw .all file with a separate datagram reader (it does
not import em2040_all.py), re-derives the per-file seabed-image int16 payload
and the per-beam sample-count layout, and checks them byte for byte against
the emitted samples, the index, the ingest stats and the manifest totals.
Statistics are recomputed from the stored sample files.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import struct
import sys
import tomllib
from array import array
from pathlib import Path

DATASET_ID = "noaa_dcdb_rainier_em2040_seabed_image_i16"
PRIMARY = "em2040_seabed_image_backscatter_i16"
AUX = "em2040_beam_sample_count_u16"
MODEL = 2040
SERIAL = 40129
BEAMS = 400


def pinned_files(script: Path) -> list[tuple[str, int, str]]:
    """Read the FILES literal from em2040_all.py without importing it."""
    tree = ast.parse(script.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(getattr(t, "id", None) == "FILES" for t in node.targets):
            files = ast.literal_eval(node.value)
            return sorted(files, key=lambda item: item[0][5:20])
    raise SystemExit("FILES table not found")


def md5_etag(path: Path, expected: str) -> bool:
    part = 5 * 1024 * 1024
    with path.open("rb") as handle:
        if "-" not in expected:
            return hashlib.md5(handle.read()).hexdigest() == expected
        digests = []
        while True:
            block = handle.read(part)
            if not block:
                break
            digests.append(hashlib.md5(block).digest())
    return f"{hashlib.md5(b''.join(digests)).hexdigest()}-{len(digests)}" == expected


def valid(view: memoryview, pos: int) -> int:
    n = len(view)
    if pos + 4 > n:
        return 0
    length = int.from_bytes(view[pos : pos + 4], "little")
    end = pos + 4 + length
    if not 19 <= length <= (1 << 24) or end > n or view[pos + 4] != 2 or view[end - 3] != 3:
        return 0
    if sum(view[pos + 5 : end - 3].tobytes()) & 0xFFFF != int.from_bytes(view[end - 2 : end], "little"):
        return 0
    return end


def rederive(raw: bytes) -> tuple[bytes, bytes, int, int]:
    view = memoryview(raw)
    pos = 0
    skipped = 0
    events = 0
    pieces = []
    layout = array("H")
    pings = 0
    last = None
    while pos < len(raw):
        end = valid(view, pos)
        if not end:
            events += 1
            nxt = pos + 1
            while nxt < len(raw) and not valid(view, nxt):
                nxt = raw.find(b"\x02", nxt + 5)
                nxt = len(raw) if nxt < 0 else nxt - 4
            skipped += nxt - pos
            pos = nxt
            continue
        model = int.from_bytes(view[pos + 6 : pos + 8], "little")
        if model != MODEL:
            raise SystemExit(f"model {model} at {pos}")
        if view[pos + 5] == 0x59:
            date, ms, counter, serial = struct.unpack_from("<IIHH", raw, pos + 8)
            if serial != SERIAL:
                raise SystemExit(f"serial {serial} at {pos}")
            if last is not None and (date, ms) < last:
                raise SystemExit(f"Y timestamps decrease at {pos}")
            last = (date, ms)
            nbeams = int.from_bytes(view[pos + 34 : pos + 36], "little")
            if nbeams != BEAMS:
                raise SystemExit(f"{nbeams} beams at {pos}")
            table = view[pos + 36 : pos + 36 + 6 * nbeams]
            counts = [entry[2] for entry in struct.iter_unpack("<bBHH", table)]
            start = pos + 36 + 6 * nbeams
            body = 2 * sum(counts)
            pad = (end - 3) - (start + body)
            if pad not in (0, 1) or (pad and raw[start + body] != 0):
                raise SystemExit(f"Y layout mismatch at {pos}")
            pieces.append(view[start : start + body])
            layout.extend(counts)
            pings += 1
        pos = end
    if events > 16 or skipped > max(0.001 * len(raw), 65536):
        raise SystemExit(f"too much unframed data ({events} events, {skipped} bytes)")
    if sys.byteorder != "little":
        layout.byteswap()
    return b"".join(pieces), layout.tobytes(), pings, events


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--download-dir", type=Path, required=True)
    parser.add_argument("--index", type=Path, required=True)
    parser.add_argument("--stats", type=Path, required=True)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args()

    files = pinned_files(Path(__file__).with_name("em2040_all.py"))
    rows = [json.loads(line) for line in args.index.read_text(encoding="utf-8").splitlines() if line.strip()]
    by_key = {(row["series_id"], row["source_file"]): row for row in rows}
    if len(rows) != 2 * len(files) or len(by_key) != len(rows):
        raise SystemExit(f"index has {len(rows)} rows for {len(files)} files")
    stats = json.loads(args.stats.read_text(encoding="utf-8"))
    stat_files = {item["source_file"]: item for item in stats["files"]}
    totals = {PRIMARY: [0, 0], AUX: [0, 0]}
    hashes = set()
    for name, size, etag in files:
        path = args.download_dir / name
        if not path.is_file() or path.stat().st_size != size or not md5_etag(path, etag):
            raise SystemExit(f"source {name} missing or not matching pinned size/ETag")
        payload, layout, pings, events = rederive(path.read_bytes())
        for series, expected, kind in ((PRIMARY, payload, "int"), (AUX, layout, "uint")):
            row = by_key.get((series, name))
            if row is None:
                raise SystemExit(f"index lacks {series} for {name}")
            stored = (args.data_root / row["sample_path"]).read_bytes()
            if stored != expected:
                raise SystemExit(f"{series} {name}: stored bytes differ from re-derived payload")
            checks = {
                "dataset_id": DATASET_ID,
                "numeric_kind": kind,
                "bit_width": 16,
                "endianness": "little",
                "element_size_bytes": 2,
                "sample_size_bytes": len(stored),
                "value_count": len(stored) // 2,
                "ping_count": pings,
                "sha256": hashlib.sha256(stored).hexdigest(),
            }
            for key, value in checks.items():
                if row.get(key) != value:
                    raise SystemExit(f"{series} {name}: index {key}={row.get(key)!r} != {value!r}")
            totals[series][0] += 1
            totals[series][1] += len(stored)
        values = array("h")
        values.frombytes(payload)
        if sys.byteorder != "little":
            values.byteswap()
        layout_values = array("H")
        layout_values.frombytes(layout)
        if sys.byteorder != "little":
            layout_values.byteswap()
        if len(layout_values) != BEAMS * pings or 2 * sum(layout_values) != len(payload):
            raise SystemExit(f"{name}: layout does not account for the payload")
        distinct = len(set(values))
        recomputed = {
            "minimum": min(values),
            "maximum": max(values),
            "distinct_values": distinct,
            "zero_count": values.count(0),
            "minus32768_count": values.count(-32768),
        }
        row = by_key[(PRIMARY, name)]
        for key, value in recomputed.items():
            if row.get(key) != value or stat_files[name].get(key) != value:
                raise SystemExit(f"{name}: {key} index/stats disagree with recomputed {value}")
        if distinct < 64 or recomputed["maximum"] - recomputed["minimum"] < 100:
            raise SystemExit(f"{name}: degenerate seabed-image payload ({distinct} distinct values)")
        if stat_files[name]["y_pings"] != pings or len(stat_files[name]["unframed_events"]) != events:
            raise SystemExit(f"{name}: ingest stats ping/event accounting differs")
        digest = row["sha256"]
        if digest in hashes:
            raise SystemExit(f"{name}: duplicate payload")
        hashes.add(digest)
        print(f"ok {name}: pings={pings} values={len(values)} min={recomputed['minimum']} "
              f"max={recomputed['maximum']} distinct={distinct} unframed_events={events}", flush=True)

    manifest = tomllib.loads(args.manifest.read_text(encoding="utf-8"))
    declared = {series["id"]: series for series in manifest["series"]}
    for series, (count, size) in totals.items():
        if series not in declared:
            raise SystemExit(f"manifest lacks series {series}")
        if declared[series]["sample_count"] != count or declared[series]["total_size_bytes"] != size:
            raise SystemExit(
                f"manifest {series}: sample_count/total_size_bytes "
                f"{declared[series]['sample_count']}/{declared[series]['total_size_bytes']} != realized {count}/{size}"
            )
        if stats["series"][series] != {"sample_count": count, "total_size_bytes": size}:
            raise SystemExit(f"ingest stats totals for {series} disagree")
    if totals[PRIMARY][1] > 1_000_000_000:
        raise SystemExit("primary output exceeds 1,000,000,000 bytes")
    print(f"verify ok: {totals}")


if __name__ == "__main__":
    main()
