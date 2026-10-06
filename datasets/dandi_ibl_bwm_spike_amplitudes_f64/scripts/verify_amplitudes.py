#!/usr/bin/env python3
"""Independent verification of the IBL spike-amplitude samples.

Re-derives everything from the local cached ranges with a different decode
strategy than build (each session's whole float64 vector is assembled by
placing every inflated chunk at its B-tree offset, instead of streaming unit
slices), then checks every sample byte for byte, every index field, the
ingest statistics, the manifest totals and the missing-value policy
(non-finite values are fatal; constant or duplicate samples are fatal; units
below the spike threshold must be absent).
"""

from __future__ import annotations

import argparse
import array
import csv
import hashlib
import json
import math
import struct
import sys
import tomllib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import nwb_hdf5 as H  # noqa: E402
from scale_test import float32_scale_test  # noqa: E402

DATASET_ID = "dandi_ibl_bwm_spike_amplitudes_f64"
SERIES_ID = "ibl_unit_spike_amplitudes_uv_f64"
CHUNK_LENGTH = 1_250_000
MIN_SPIKES = 1000
EXPECTED_AGGREGATE_SHA256 = "0ac190be63de4d8ddcad0208bf8ccbbef068a2c0eabf6e0f4323f1131aca1f9f"


def fail(message: str) -> None:
    raise SystemExit(f"verify FAILED: {message}")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def decode_session(download_dir: Path, session: dict[str, str]) -> tuple[bytearray, list[int], dict[str, object]]:
    asset = session["asset_id"]
    size = int(session["size_bytes"])
    sdir = download_dir / "sessions" / asset
    h5 = H.H5File(H.BlockStore(sdir / "meta", size), size)
    for path, key in (("/general/lab", "lab"), ("/general/session_id", "session_eid"),
                      ("/general/subject/subject_id", "subject_id"), ("/identifier", "nwb_identifier")):
        if h5.scalar_string(h5.resolve(path)) != session[key]:
            fail(f"{asset}: {path} differs from sessions.tsv")
    amp = h5.dataset(h5.resolve("/units/spike_amplitudes_uV"))
    spikes, chunk_length = H.validate_1d_deflate(amp, H.H5T_IEEE_F64LE, 8)
    index_info = h5.dataset(h5.resolve("/units/spike_amplitudes_uV_index"))
    units, index_chunk = H.validate_1d_deflate(index_info, H.H5T_STD_U32LE, 4)
    if spikes != int(session["spikes"]) or units != int(session["units"]) or chunk_length != CHUNK_LENGTH:
        fail(f"{asset}: shape/chunking differs from pins")
    amp_chunks = H.chunk_plan_1d(h5.chunks(int(amp["chunk_btree"]), 1), spikes, chunk_length)
    if len(amp_chunks) != math.ceil(spikes / CHUNK_LENGTH) or len(amp_chunks) != int(session["amp_chunks"]):
        fail(f"{asset}: chunk count {len(amp_chunks)} != ceil({spikes}/{CHUNK_LENGTH})")
    index_chunks = H.chunk_plan_1d(h5.chunks(int(index_info["chunk_btree"]), 1), units, index_chunk)
    if len(index_chunks) != 1:
        fail(f"{asset}: expected one index chunk")
    chunk_dir = sdir / "chunks"
    vector = bytearray(8 * spikes)
    filled = 0
    for chunk in amp_chunks:
        path = chunk_dir / f"amp_{chunk['element_offset']:09d}.bin"
        payload = path.read_bytes()
        if len(payload) != chunk["stored_bytes"]:
            fail(f"{path}: stored size mismatch")
        data = H.inflate_exact(payload, CHUNK_LENGTH * 8)
        offset = chunk["element_offset"] * 8
        valid = chunk["valid_elements"] * 8
        vector[offset : offset + valid] = data[:valid]
        filled += valid
    if filled != 8 * spikes or len(vector) != 8 * spikes:
        fail(f"{asset}: decompressed valid size {filled} != 8 x {spikes}")
    raw_index = H.inflate_exact((chunk_dir / "index_000000000.bin").read_bytes(), index_chunk * 4)
    index = list(struct.unpack(f"<{units}I", raw_index[: units * 4]))
    if any(b < a for a, b in zip(index, index[1:])):
        fail(f"{asset}: index not monotone")
    if index[-1] != spikes:
        fail(f"{asset}: last index entry {index[-1]} != {spikes}")
    return vector, index, {"spikes": spikes, "units": units, "chunks": len(amp_chunks)}


def stats_for(raw: bytes) -> dict[str, object]:
    values = array.array("d")
    values.frombytes(raw)
    if sys.byteorder != "little":
        values.byteswap()
    if not all(math.isfinite(v) for v in values):
        fail("non-finite amplitude in a sample")
    narrowed = array.array("f", values)
    lcm_bits, max_err = float32_scale_test(values)
    return {
        "min": min(values),
        "max": max(values),
        "distinct_values": len(set(values)),
        "nonpositive_values": sum(1 for v in values if v <= 0.0),
        "float32_exact_values": sum(1 for a, b in zip(values, narrowed) if a == b),
        "f32_ratio_lcm_bits": lcm_bits,
        "f32_ratio_max_rel_err": max_err,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--recipe-dir", type=Path, required=True)
    args = parser.parse_args()
    root = args.data_root
    download_dir = root / "downloads" / DATASET_ID
    series_dir = root / "samples" / DATASET_ID / SERIES_ID
    sessions = read_tsv(args.recipe_dir / "sessions.tsv")
    manifest = tomllib.loads((args.recipe_dir / "manifest.toml").read_text(encoding="utf-8"))
    series = [s for s in manifest["series"] if s["id"] == SERIES_ID]
    if len(series) != 1 or series[0]["role"] != "primary" or series[0]["bit_width"] != 64:
        fail("manifest series entry missing or wrong")

    # Every fetched range still matches the SHA-256 recorded at download time.
    recorded = read_tsv(download_dir / "range_sha256.tsv")
    listed = set()
    for row in recorded:
        path = download_dir / row["local_path"]
        if not path.is_file() or path.stat().st_size != int(row["length"]) or sha256_file(path) != row["sha256"]:
            fail(f"range {row['local_path']} missing or changed since download")
        listed.add(row["local_path"])
    on_disk = {str(p.relative_to(download_dir)) for p in (download_dir / "sessions").glob("*/chunks/*.bin")}
    if not on_disk <= listed:
        fail(f"unrecorded chunk files: {sorted(on_disk - listed)[:3]}")

    index_rows = [json.loads(line) for line in
                  (root / "index" / DATASET_ID / "samples.jsonl").read_text(encoding="utf-8").splitlines() if line]
    expected_rows = []
    hashes = set()
    session_summaries = []
    for session in sessions:
        vector, index, info = decode_session(download_dir, session)
        bounds = [0] + index
        label = f"{session['subject_id']}_ses-{session['session_eid'][:8]}"
        kept = dropped = 0
        for row_number in range(len(index)):
            start, end = bounds[row_number], bounds[row_number + 1]
            if end - start < MIN_SPIKES:
                dropped += 1
                continue
            name = f"{label}_unit{row_number:04d}.bin"
            raw = bytes(vector[start * 8 : end * 8])
            path = series_dir / name
            if not path.is_file() or path.read_bytes() != raw:
                fail(f"sample {name} missing or differs from the re-decoded unit slice")
            digest = hashlib.sha256(raw).hexdigest()
            if digest in hashes:
                fail(f"duplicate sample content {name}")
            hashes.add(digest)
            stats = stats_for(raw)
            if stats["distinct_values"] < 2:
                fail(f"constant sample {name}")
            expected_rows.append({
                "sample_path": f"samples/{DATASET_ID}/{SERIES_ID}/{name}",
                "value_count": end - start,
                "sample_size_bytes": 8 * (end - start),
                "unit_row": row_number,
                "ragged_start": start,
                "asset_id": session["asset_id"],
                "lab": session["lab"],
                "subject_id": session["subject_id"],
                "session_eid": session["session_eid"],
                "sha256": digest,
                **stats,
            })
            kept += 1
        if kept != int(session["kept_units"]):
            fail(f"{label}: kept {kept} units, pinned {session['kept_units']}")
        session_summaries.append((session["lab"], info["units"], kept, dropped))
        del vector

    if len(index_rows) != len(expected_rows):
        fail(f"index has {len(index_rows)} rows, expected {len(expected_rows)}")
    for row, expected in zip(index_rows, expected_rows):
        fixed = {"dataset_id": DATASET_ID, "series_id": SERIES_ID, "numeric_kind": "float", "bit_width": 64,
                 "endianness": "little", "element_size_bytes": 8}
        for key, value in {**fixed, **expected}.items():
            if row.get(key) != value:
                fail(f"index row {row.get('sample_path')}: {key}={row.get(key)!r}, expected {value!r}")
    files = {p.name for p in series_dir.iterdir()}
    if files != {Path(r["sample_path"]).name for r in expected_rows}:
        fail("stray or missing files in the series directory")

    total_bytes = sum(r["sample_size_bytes"] for r in expected_rows)
    if series[0]["sample_count"] != len(expected_rows) or series[0]["total_size_bytes"] != total_bytes:
        fail(f"manifest sample_count/total_size_bytes {series[0]['sample_count']}/{series[0]['total_size_bytes']} "
             f"!= realized {len(expected_rows)}/{total_bytes}")
    stats = json.loads((root / "filtered" / DATASET_ID / "ingest_stats.json").read_text(encoding="utf-8"))
    aggregate = hashlib.sha256("".join(r["sha256"] + "\n" for r in expected_rows).encode()).hexdigest()
    totals = stats["totals"]
    if totals["aggregate_sha256"] != aggregate or totals["samples"] != len(expected_rows) \
            or totals["bytes"] != total_bytes:
        fail("ingest_stats.json totals disagree with the re-derived output")
    if aggregate != EXPECTED_AGGREGATE_SHA256:
        fail(f"aggregate sample hash {aggregate} != pinned {EXPECTED_AGGREGATE_SHA256}")
    consistent = sum(1 for r in expected_rows if r["f32_ratio_lcm_bits"] <= 24 and r["f32_ratio_max_rel_err"] < 1e-15)
    if totals["f32_scale_consistent_units"] != consistent:
        fail("ingest_stats.json float32-scale disclosure count disagrees")
    for lab, units, kept, dropped in session_summaries:
        print(f"verify session lab={lab} units={units} kept={kept} dropped={dropped}")
    values = sum(r["value_count"] for r in expected_rows)
    print(f"verify ok samples={len(expected_rows)} values={values} bytes={total_bytes} "
          f"f32_scale_consistent_units={consistent}/{len(expected_rows)} "
          f"float32_exact_values={sum(r['float32_exact_values'] for r in expected_rows)} "
          f"min={min(r['min'] for r in expected_rows)!r} max={max(r['max'] for r in expected_rows)!r} "
          f"aggregate_sha256={aggregate}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
