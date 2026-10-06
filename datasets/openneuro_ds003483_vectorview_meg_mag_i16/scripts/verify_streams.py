#!/usr/bin/env python3
"""Independent verifier for openneuro_ds003483_vectorview_meg_mag_i16.

Deliberately shares no code with fif_meg.py. Where build follows the FIFF
tag chain's next pointers, this verifier navigates every file through its
trailing FIFF_DIR directory (located via FIFF_DIR_POINTER), re-reads each
tag header to confirm it agrees with the directory, re-derives the
measurement info, magnetometer set, processing-history signature and raw
buffer layout, then re-converts every FIFFT_DAU_PACK16 buffer with struct
(not array.byteswap) and compares the result byte-for-byte with the emitted
samples, the sample index, the ingest statistics and the manifest.
Missing-value policy is the same as build: nothing is dropped, clipped or
imputed; inner FIFF_DATA_SKIP gaps and degenerate streams are fatal.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
import struct
import tomllib

DATASET_ID = "openneuro_ds003483_vectorview_meg_mag_i16"
SERIES_ID = "vectorview_magnetometer_tsss_i16"
NCHAN = 320
BUFFER_SAMPLES = 1000
MAG_RANGE_BITS = struct.pack(">f", 1.9073486328125e-05)
MAG_CAL_BITS = struct.pack(">f", 4.14e-11)
MAGNETOMETERS = 102
RUNS = 6
# Degeneracy policy (same thresholds as build).
SECOND = 1000
MIN_DISTINCT, MIN_PTP, MAX_FLAT = 1000, 1000, 100
INDEX_KEYS = ["dataset_id", "series_id", "sample_path", "numeric_kind", "bit_width", "endianness",
              "element_size_bytes", "sample_size_bytes", "value_count"]


def fail(message: str) -> None:
    raise SystemExit(f"verify failed: {message}")


def read_at(fh, pos: int, length: int) -> bytes:
    fh.seek(pos)
    data = fh.read(length)
    if len(data) != length:
        fail(f"short read at {pos}")
    return data


def be_int(data: bytes) -> int:
    return int.from_bytes(data[:4], "big", signed=True)


def parse_run(path: Path) -> dict:
    """Directory-driven FIFF reader."""
    size = path.stat().st_size
    with path.open("rb") as fh:
        head = read_at(fh, 0, 56)
        if struct.unpack(">iii", head[0:12]) != (100, 31, 20):
            fail(f"{path.name}: no FIFF_FILE_ID")
        if struct.unpack(">iii", head[36:48]) != (101, 3, 4):
            fail(f"{path.name}: no FIFF_DIR_POINTER")
        dir_pos = be_int(head[52:56])
        dkind, dtype, dsize, dnext = struct.unpack(">iiii", read_at(fh, dir_pos, 16))
        if (dkind, dtype, dnext) != (102, 32, -1) or dir_pos + 16 + dsize != size:
            fail(f"{path.name}: FIFF_DIR is not the final tag")
        body = read_at(fh, dir_pos + 16, dsize)
        entries = [struct.unpack(">iiii", body[i:i + 16]) for i in range(0, dsize, 16)]
        if entries[-1] != (-1, -1, -1, -1):
            fail(f"{path.name}: directory terminator missing")
        entries = entries[:-1]
        expected_pos = 0
        stack: list[int] = []
        chans: list[bytes] = []
        meas: dict[str, object] = {}
        creators, ct_creators, sss_jobs, st_jobs, raw = [], [], [], [], []
        for kind, typ, length, pos in entries:
            if pos != expected_pos:
                fail(f"{path.name}: directory entry at {pos} is not contiguous")
            expected_pos = pos + 16 + length
            # Every chained tag has next = 0 except the last one (a FIFF_NOP
            # right before FIFF_DIR), which ends the chain with next = -1.
            want_next = -1 if expected_pos == dir_pos else 0
            if struct.unpack(">iiii", read_at(fh, pos, 16)) != (kind, typ, length, want_next):
                fail(f"{path.name}: tag header at {pos} disagrees with the directory")
            parent = stack[-1] if stack else None
            if kind == 104:
                stack.append(be_int(read_at(fh, pos + 16, 4)))
            elif kind == 105:
                if not stack or stack.pop() != be_int(read_at(fh, pos + 16, 4)):
                    fail(f"{path.name}: unbalanced block at {pos}")
            elif parent == 101 and kind == 200:
                meas["nchan"] = be_int(read_at(fh, pos + 16, 4))
            elif parent == 101 and kind == 201:
                meas["sfreq"] = struct.unpack(">f", read_at(fh, pos + 16, 4))[0]
            elif parent == 101 and kind == 202:
                meas["pack"] = be_int(read_at(fh, pos + 16, 4))
            elif parent == 101 and kind == 203:
                chans.append(read_at(fh, pos + 16, length))
            elif parent == 901 and kind == 113:
                creators.append(read_at(fh, pos + 16, length).decode("latin-1"))
            elif parent == 501 and kind == 113:
                ct_creators.append(read_at(fh, pos + 16, length).decode("latin-1"))
            elif parent == 502 and kind == 264:
                sss_jobs.append(be_int(read_at(fh, pos + 16, 4)))
            elif parent == 504 and kind == 264:
                st_jobs.append(be_int(read_at(fh, pos + 16, 4)))
            elif parent == 102:
                raw.append((kind, typ, length, pos))
        if expected_pos != dir_pos or stack:
            fail(f"{path.name}: directory does not tile the file up to FIFF_DIR")
    if meas != {"nchan": NCHAN, "sfreq": 1000.0, "pack": 16} or len(chans) != NCHAN:
        fail(f"{path.name}: measurement info {meas} with {len(chans)} channels")
    if creators != ["maxfilter 2.2.10"] * 2 or ct_creators != ["create_ct_matrix 1.0"] * 2 \
            or sss_jobs != [5, 5] or st_jobs != [10, 10]:
        fail(f"{path.name}: processing history {creators} {ct_creators} {sss_jobs} {st_jobs}")
    names, mags = [], []
    for index, record in enumerate(chans):
        if len(record) != 96:
            fail(f"{path.name}: channel record size")
        names.append(record[80:96].split(b"\x00")[0].decode("latin-1"))
        if be_int(record[8:12]) == 1 and be_int(record[20:24]) == 3024:
            if record[12:16] != MAG_RANGE_BITS or record[16:20] != MAG_CAL_BITS or be_int(record[72:76]) != 112:
                fail(f"{path.name}: magnetometer {names[-1]} scale")
            mags.append(index)
    if len(mags) != MAGNETOMETERS:
        fail(f"{path.name}: {len(mags)} magnetometers")
    if not raw or raw[0][:3] != (301, 3, 4):
        fail(f"{path.name}: raw block does not open with a data skip")
    with path.open("rb") as fh:
        skip = be_int(read_at(fh, raw[0][3] + 16, 4))
    buffers = raw[1:]
    for k, (kind, typ, length, pos) in enumerate(buffers):
        if kind != 300 or typ != 16:
            fail(f"{path.name}: raw-block tag kind={kind} type={typ} at {pos} (inner skip or foreign tag)")
        if length % (2 * NCHAN) or not (length == 2 * NCHAN * BUFFER_SAMPLES or (k == len(buffers) - 1 and length < 2 * NCHAN * BUFFER_SAMPLES)):
            fail(f"{path.name}: buffer size {length} at {pos}")
    return {"size": size, "dir_pointer": dir_pos, "names": names, "chans": chans, "mags": mags,
            "skip": skip, "buffers": buffers, "first_sample": skip * buffers[0][2] // (2 * NCHAN),
            "nsamp": sum(b[2] for b in buffers) // (2 * NCHAN)}


def longest_run(values: tuple[int, ...]) -> int:
    best = run = 1
    for a, b in zip(values, values[1:]):
        run = run + 1 if a == b else 1
        if run > best:
            best = run
    return best


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--recipe-dir", type=Path, required=True)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--selection", type=Path, help="override selection.tsv (self-tests only)")
    parser.add_argument("--manifest", type=Path, help="override manifest.toml (self-tests only)")
    args = parser.parse_args()
    root = args.data_root
    downloads = root / "downloads" / DATASET_ID / "fif"
    manifest = tomllib.loads((args.manifest or args.recipe_dir / "manifest.toml").read_text(encoding="utf-8"))
    series = [s for s in manifest["series"] if s["id"] == SERIES_ID]
    if manifest["dataset_id"] != DATASET_ID or len(series) != 1 or series[0]["role"] != "primary" \
            or (series[0]["numeric_kind"], series[0]["bit_width"], series[0]["endianness"]) != ("int", 16, "little"):
        fail("manifest identity")
    series = series[0]
    with (args.selection or args.recipe_dir / "selection.tsv").open(newline="") as handle:
        runs = list(csv.DictReader(handle, delimiter="\t"))
    if len(runs) != RUNS or len({r["subject"] for r in runs}) != RUNS:
        fail("selection must list six distinct subjects")

    rows = [json.loads(line) for line in (root / "index" / DATASET_ID / "samples.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    by_path = {row["sample_path"]: row for row in rows}
    if len(by_path) != len(rows):
        fail("duplicate sample paths in index")

    reference_names = None
    expected_paths: set[str] = set()
    payloads: set[bytes] = set()
    blocks: set[bytes] = set()
    total_values = total_bytes = 0
    global_min, global_max = 32767, -32768
    per_run = []
    for run in runs:
        fif = downloads / Path(run["key"]).name
        digest = hashlib.md5()
        with fif.open("rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 22), b""):
                digest.update(chunk)
        if digest.hexdigest() != run["md5"]:
            fail(f"{fif.name}: MD5 differs from pinned {run['md5']}")
        info = parse_run(fif)
        pinned = (int(run["size_bytes"]), int(run["dir_pointer"]), int(run["n_buffers"]), int(run["leading_skip_buffers"]))
        if (info["size"], info["dir_pointer"], len(info["buffers"]), info["skip"]) != pinned:
            fail(f"{fif.name}: structure differs from pins {pinned}")
        if reference_names is None:
            reference_names = info["names"]
        elif info["names"] != reference_names:
            fail(f"{fif.name}: channel order differs between runs")
        stem = f"{run['subject']}_{run['session']}_task-{run['task']}_{run['run']}"
        rels = [f"samples/{DATASET_ID}/{SERIES_ID}/{stem}_{info['names'][k]}.bin" for k in info["mags"]]
        handles = [(root / rel).open("rb") for rel in rels]
        try:
            with fif.open("rb") as fh:
                for _kind, _typ, length, pos in info["buffers"]:
                    values = struct.unpack(f">{length // 2}h", read_at(fh, pos + 16, length))
                    m = length // (2 * NCHAN)
                    for handle, k in zip(handles, info["mags"]):
                        if handle.read(2 * m) != struct.pack(f"<{m}h", *values[k::NCHAN]):
                            fail(f"{handle.name}: bytes differ from re-converted buffer at {pos}")
            for handle in handles:
                if handle.read(1):
                    fail(f"{handle.name}: trailing bytes beyond the raw stream")
        finally:
            for handle in handles:
                handle.close()
        for rel, k in zip(rels, info["mags"]):
            expected_paths.add(rel)
            row = by_path.get(rel)
            if row is None or any(key not in row for key in INDEX_KEYS):
                fail(f"index row for {rel}")
            sample = (root / rel).read_bytes()
            n = len(sample) // 2
            stored = struct.unpack(f"<{n}h", sample)
            lo, hi = min(stored), max(stored)
            distinct, flat = len(set(stored)), longest_run(stored)
            record = info["chans"][k]
            rng = struct.unpack(">f", record[12:16])[0]
            cal = struct.unpack(">f", record[16:20])[0]
            checks = {
                "dataset_id": DATASET_ID, "series_id": SERIES_ID, "numeric_kind": "int", "bit_width": 16,
                "endianness": "little", "element_size_bytes": 2, "sample_size_bytes": len(sample),
                "value_count": info["nsamp"], "role": "primary", "subject": run["subject"],
                "source_key": run["key"], "source_version_id": run["version_id"],
                "channel_name": info["names"][k], "ch_info_index": k, "coil_type": 3024,
                "range": rng, "cal": cal, "tesla_per_code": rng * cal, "sample_rate_hz": 1000.0,
                "fiff_leading_skip_buffers": info["skip"], "fiff_first_sample": info["first_sample"],
                "minimum": lo, "maximum": hi, "distinct_values": distinct, "longest_identical_run": flat,
                "sha256": hashlib.sha256(sample).hexdigest(),
            }
            for key, value in checks.items():
                if row.get(key) != value:
                    fail(f"index field {key} for {rel}: {row.get(key)!r} != {value!r}")
            if distinct < MIN_DISTINCT or hi - lo < MIN_PTP or flat > MAX_FLAT or lo == -32768 or hi == 32767:
                fail(f"degenerate stream {rel}: distinct={distinct} ptp={hi - lo} flat={flat}")
            for start in range(0, len(sample) - 2 * SECOND + 1, 2 * SECOND):
                block = sample[start:start + 2 * SECOND]
                if len(set(stored[start // 2:start // 2 + SECOND])) == 1:
                    fail(f"constant 1-s block in {rel}")
                key = hashlib.sha256(block).digest()
                if key in blocks:
                    fail(f"duplicate 1-s block in {rel}")
                blocks.add(key)
            key = hashlib.sha256(sample).digest()
            if key in payloads:
                fail(f"duplicate payload {rel}")
            payloads.add(key)
            total_values += n
            total_bytes += len(sample)
            global_min, global_max = min(global_min, lo), max(global_max, hi)
        per_run.append({"subject": run["subject"], "samples": info["nsamp"], "leading_skip": info["skip"]})

    if set(by_path) != expected_paths:
        fail("index rows do not match the expected stream set")
    on_disk = {p.relative_to(root).as_posix() for p in (root / "samples" / DATASET_ID).rglob("*") if p.is_file()}
    if on_disk != expected_paths:
        fail("unexpected or missing files under samples/")
    if (series["sample_count"], series["total_size_bytes"]) != (len(expected_paths), total_bytes):
        fail(f"manifest sample_count/total_size_bytes {series['sample_count']}/{series['total_size_bytes']} "
             f"!= realized {len(expected_paths)}/{total_bytes}")
    if total_bytes > 1_000_000_000:
        fail("primary output exceeds 1,000,000,000 bytes")
    stats = json.loads((root / "filtered" / DATASET_ID / "ingest_stats.json").read_text(encoding="utf-8"))
    for key, value in {"sample_count": len(expected_paths), "total_size_bytes": total_bytes,
                       "value_count": total_values, "global_minimum": global_min,
                       "global_maximum": global_max, "unique_1s_blocks": len(blocks)}.items():
        if stats.get(key) != value:
            fail(f"ingest stats {key}: {stats.get(key)!r} != {value!r}")
    print(json.dumps({
        "dataset_id": DATASET_ID, "verified_samples": len(expected_paths), "verified_values": total_values,
        "verified_bytes": total_bytes, "global_minimum": global_min, "global_maximum": global_max,
        "unique_1s_blocks": len(blocks), "runs": per_run,
    }, indent=1, sort_keys=True))


if __name__ == "__main__":
    main()
