#!/usr/bin/env python3
"""Independent verifier for openneuro_ds004212_things_meg_ctf_i32.

Deliberately shares no code with ctf_meg.py: it walks each res4 with its own
reader, re-locates the selected gradiometers, re-converts every downloaded
big-endian channel block with struct (not array.byteswap), and compares the
result byte-for-byte with the emitted samples, the sample index, the ingest
statistics, and the manifest. Missing-value policy is the same as build:
nothing is dropped or imputed; any degenerate stream is fatal.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
import struct
import tomllib

DATASET_ID = "openneuro_ds004212_things_meg_ctf_i32"
SERIES_ID = "ctf275_axial_gradiometer_counts_i32"
LABELS = ["MLF32", "MRF32", "MLC32", "MRC32", "MLT33", "MRT33", "MLO32", "MRO32"]
NSAMP, NCHAN, SFREQ = 417_600, 310, 1200.0
STREAM_BYTES = NSAMP * 4
SECOND = 1200
INDEX_KEYS = ["dataset_id", "series_id", "sample_path", "numeric_kind", "bit_width", "endianness",
              "element_size_bytes", "sample_size_bytes", "value_count"]


def fail(message: str) -> None:
    raise SystemExit(f"verify failed: {message}")


def res4_gradiometers(raw: bytes) -> tuple[dict[str, tuple[int, int, int]], list[str]]:
    """Return label -> (index, sensor_type, grad_order) using an independent walk."""
    if not raw.startswith(b"MEG42RS\x00"):
        fail("res4 magic")
    nsamp = int.from_bytes(raw[1288:1292], "big", signed=True)
    nchan = int.from_bytes(raw[1292:1294], "big", signed=True)
    sfreq = struct.unpack(">d", raw[1296:1304])[0]
    trials = int.from_bytes(raw[1312:1314], "big", signed=True)
    if (nsamp, nchan, sfreq, trials) != (NSAMP, NCHAN, SFREQ, 1):
        fail(f"res4 geometry {(nsamp, nchan, sfreq, trials)}")
    cursor = 1844 + int.from_bytes(raw[1836:1840], "big", signed=True)
    nfilt = int.from_bytes(raw[cursor:cursor + 2], "big", signed=True)
    cursor += 2
    for _ in range(nfilt):
        npar = int.from_bytes(raw[cursor + 16:cursor + 18], "big", signed=True)
        cursor += 18 + 8 * npar
    labels = [raw[cursor + 32 * k:cursor + 32 * k + 32].split(b"\x00")[0].decode("latin-1").split("-")[0]
              for k in range(nchan)]
    table = cursor + 32 * nchan
    info = {}
    for k, label in enumerate(labels):
        record = raw[table + 1328 * k:table + 1328 * (k + 1)]
        sensor_type = int.from_bytes(record[0:2], "big", signed=True)
        grad_order = int.from_bytes(record[42:44], "big", signed=True)
        info[label] = (k, sensor_type, grad_order)
    comp = table + 1328 * nchan
    ncomp = int.from_bytes(raw[comp:comp + 2], "big", signed=True)
    if comp + 2 + 1992 * ncomp != len(raw):
        fail("res4 compensation table does not end at file end")
    types = [t for _k, t, _g in info.values()]
    if types.count(5) != 272 or {g for _k, t, g in info.values() if t == 5} != {3}:
        fail("res4 gradiometer self-check (272 grade-3 type-5 channels)")
    return info, labels


def longest_run(values: tuple[int, ...]) -> int:
    best = run = 1
    previous = values[0]
    for value in values[1:]:
        run = run + 1 if value == previous else 1
        best = max(best, run)
        previous = value
    return best


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--recipe-dir", type=Path, required=True)
    parser.add_argument("--data-root", type=Path, required=True)
    args = parser.parse_args()
    root = args.data_root
    downloads = root / "downloads" / DATASET_ID
    manifest = tomllib.loads((args.recipe_dir / "manifest.toml").read_text(encoding="utf-8"))
    series = [s for s in manifest["series"] if s["id"] == SERIES_ID]
    if manifest["dataset_id"] != DATASET_ID or len(series) != 1 or series[0]["role"] != "primary":
        fail("manifest identity")
    series = series[0]

    with (args.recipe_dir / "selection.tsv").open(newline="") as handle:
        runs = list(csv.DictReader(handle, delimiter="\t"))
    with (args.recipe_dir / "streams.tsv").open(newline="") as handle:
        pins = {row["stream_id"]: row for row in csv.DictReader(handle, delimiter="\t")}
    if len(runs) != 24 or len({r["subject"] for r in runs}) != 4 or len(pins) != 24 * len(LABELS):
        fail("selection/stream pin counts")

    index_path = root / "index" / DATASET_ID / "samples.jsonl"
    rows = [json.loads(line) for line in index_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    by_path = {row["sample_path"]: row for row in rows}
    if len(by_path) != len(rows):
        fail("duplicate sample paths in index")

    reference_labels = None
    expected_paths = set()
    payload_hashes = set()
    block_hashes = set()
    total_values = total_bytes = 0
    global_min, global_max = 2**31, -(2**31)
    beyond16 = 0
    for run in runs:
        res4 = (downloads / "res4" / Path(run["res4_key"]).name).read_bytes()
        if hashlib.md5(res4).hexdigest() != run["res4_md5"]:
            fail(f"res4 md5 {run['subject']} {run['session']}")
        info, labels = res4_gradiometers(res4)
        if reference_labels is None:
            reference_labels = labels
        elif labels != reference_labels:
            fail("channel order differs between runs")
        for label in LABELS:
            index, sensor_type, grad_order = info[label]
            if (sensor_type, grad_order) != (5, 3):
                fail(f"{label} is not a grade-3 axial gradiometer")
            stream_id = f"{run['subject']}_{run['session']}_{run['run']}_{label}"
            pin = pins.get(stream_id)
            start = 8 + index * NSAMP * 4
            if pin is None or (int(pin["channel_index"]), int(pin["byte_start"]), int(pin["byte_end"])) != (index, start, start + STREAM_BYTES - 1):
                fail(f"stream layout pin for {stream_id}")
            source = (downloads / "streams" / f"{stream_id}.i32be").read_bytes()
            if len(source) != STREAM_BYTES or hashlib.sha256(source).hexdigest() != pin["sha256_be"]:
                fail(f"source block identity {stream_id}")
            values = struct.unpack(f">{NSAMP}i", source)
            expected = struct.pack(f"<{NSAMP}i", *values)
            sample_rel = f"samples/{DATASET_ID}/{SERIES_ID}/{stream_id}.bin"
            expected_paths.add(sample_rel)
            row = by_path.get(sample_rel)
            if row is None or any(key not in row for key in INDEX_KEYS):
                fail(f"index row for {stream_id}")
            sample = (root / sample_rel).read_bytes()
            if sample != expected:
                fail(f"sample bytes are not the LE re-encoding of {stream_id}")
            stored = struct.unpack(f"<{NSAMP}i", sample)
            lo, hi = min(stored), max(stored)
            checks = {
                "dataset_id": DATASET_ID, "series_id": SERIES_ID, "numeric_kind": "int",
                "bit_width": 32, "endianness": "little", "element_size_bytes": 4,
                "value_count": NSAMP, "sample_size_bytes": STREAM_BYTES,
                "minimum": lo, "maximum": hi, "channel_label": label, "channel_index": index,
                "subject": run["subject"], "session": run["session"],
                "sha256": hashlib.sha256(sample).hexdigest(), "role": "primary",
            }
            for key, value in checks.items():
                if row.get(key) != value:
                    fail(f"index field {key} for {stream_id}: {row.get(key)!r} != {value!r}")
            # Degeneracy policy (same thresholds as build).
            if len(set(stored)) < 1000 or hi - lo < 1000 or longest_run(stored) > 120:
                fail(f"degenerate stream {stream_id}")
            if -(2**31) in stored or 2**31 - 1 in stored:
                fail(f"int32 saturation in {stream_id}")
            for b in range(NSAMP // SECOND):
                block = sample[b * SECOND * 4:(b + 1) * SECOND * 4]
                if block == block[:4] * SECOND:
                    fail(f"constant 1-s block in {stream_id}")
                digest = hashlib.sha256(block).digest()
                if digest in block_hashes:
                    fail(f"duplicate 1-s block in {stream_id}")
                block_hashes.add(digest)
            digest = hashlib.sha256(sample).digest()
            if digest in payload_hashes:
                fail(f"duplicate payload {stream_id}")
            payload_hashes.add(digest)
            total_values += NSAMP
            total_bytes += len(sample)
            global_min, global_max = min(global_min, lo), max(global_max, hi)
            beyond16 += sum(1 for v in stored if v < -32768 or v > 32767)

    if set(by_path) != expected_paths:
        fail("index rows do not match the pinned stream set")
    on_disk = {p.relative_to(root).as_posix() for p in (root / "samples" / DATASET_ID).rglob("*") if p.is_file()}
    if on_disk != expected_paths:
        fail("unexpected or missing files under samples/")
    if (series["sample_count"], series["total_size_bytes"]) != (len(expected_paths), total_bytes):
        fail(f"manifest sample_count/total_size_bytes {series['sample_count']}/{series['total_size_bytes']} != {len(expected_paths)}/{total_bytes}")
    stats = json.loads((root / "filtered" / DATASET_ID / "ingest_stats.json").read_text(encoding="utf-8"))
    for key, value in {"sample_count": len(expected_paths), "total_size_bytes": total_bytes,
                       "value_count": total_values, "global_minimum": global_min,
                       "global_maximum": global_max}.items():
        if stats.get(key) != value:
            fail(f"ingest stats {key}: {stats.get(key)!r} != {value!r}")
    print(json.dumps({
        "dataset_id": DATASET_ID, "verified_samples": len(expected_paths),
        "verified_values": total_values, "verified_bytes": total_bytes,
        "global_minimum": global_min, "global_maximum": global_max,
        "beyond_int16_fraction": round(beyond16 / total_values, 6),
        "unique_1s_blocks": len(block_hashes),
    }, indent=1, sort_keys=True))


if __name__ == "__main__":
    main()
