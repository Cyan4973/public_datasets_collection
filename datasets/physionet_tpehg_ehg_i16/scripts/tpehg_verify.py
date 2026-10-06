#!/usr/bin/env python3
"""Independently verify the TPEHG DB unfiltered EHG int16 output.

Does not import the build helpers. Starting from the official SHA256SUMS.txt
and RECORDS, it re-hashes every source file, re-parses each WFDB header with
its own parser, re-decodes the interleaved .dat with explicit little-endian
struct unpacking, checks all 12 per-signal WFDB checksums, re-checks each kept
channel's ADC code lattice against its series, and compares every sample byte
and every index field with the re-derived values. It also checks the
manifest's per-series sample_count and total_size_bytes and applies the same
non-degeneracy rules as the build (no values are dropped or imputed).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import struct
import tomllib
from pathlib import Path

DATASET_ID = "physionet_tpehg_ehg_i16"
PINNED_SUMS = "6da37c0d996bf7706964f291282861449ccb84005500a1c16aefda3d8fcdbf3e"
# header sampling-frequency string -> (series id, lattice, expected records)
REGIMES = {
    "20.000000": ("tpehg_ehg_unfiltered_adc_step1_i16", "step1", 174),
    "20.000110": ("tpehg_ehg_unfiltered_adc_step16_i16", "step16", 126),
}
KEEP = ((0, "1", "S1=E2-E1"), (4, "2", "S2=E2-E3"), (8, "3", "S3=E4-E3"))
FILTERED_SUFFIXES = ("_DOCFILT-4-0.08-4", "_DOCFILT-4-0.3-3", "_DOCFILT-4-0.3-4")
ALLOWED_INDEX_KEYS = {
    "adc_code_lattice", "adc_gain_per_mv", "adc_resolution_bits", "adc_zero", "bipolar_lead",
    "bit_width", "channel", "dataset_id", "distinct_values", "element_size_bytes", "endianness",
    "longest_constant_run", "maximum", "minimum", "mod16_residue_count", "mod16_top2_fraction",
    "natural_record_kind", "numeric_kind", "record_id", "role", "sample_axes", "sample_path",
    "sample_rank", "sample_shape", "sample_size_bytes", "sampling_frequency_header",
    "saturated_high_count", "saturated_low_count", "series_id", "sha256", "source_sample",
    "source_signal_index", "transition_count", "value_count",
}


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fail(message: str) -> None:
    raise SystemExit(f"verify failed: {message}")


def expected_names() -> list[str]:
    names = []
    for channel in ("1", "2", "3"):
        names.append(channel)
        names.extend(channel + suffix for suffix in FILTERED_SUFFIXES)
    return names


def header_info(path: Path, record_id: str) -> tuple[str, int, list[tuple[int, int]]]:
    rows = [line.split() for line in path.read_text(encoding="ascii").splitlines()
            if line.strip() and not line.lstrip().startswith("#")]
    head = rows[0]
    if head[:2] != [record_id, "12"] or len(head) != 4 or head[2] not in REGIMES:
        fail(f"{record_id}: record line {head}")
    names = expected_names()
    if len(rows) != 13:
        fail(f"{record_id}: {len(rows) - 1} signal lines")
    pairs = []
    for position, fields in enumerate(rows[1:]):
        if fields[:5] != [f"{record_id}.dat", "16", "13107/mV", "16", "0"] or fields[7:] != ["0", names[position]]:
            fail(f"{record_id}: signal line {position} {fields}")
        pairs.append((int(fields[5]), int(fields[6])))
    return head[2], int(head[3]), pairs


def lattice_profile(column: tuple[int, ...]) -> tuple[int, float, bool]:
    tally = [0] * 16
    for value in column:
        tally[value % 16] += 1
    present = [residue for residue in range(16) if tally[residue]]
    top_two = sorted(tally, reverse=True)[:2]
    share = round((top_two[0] + top_two[1]) / len(column), 6)
    adjacent = len(present) == 1 or (len(present) == 2 and (present[1] - present[0]) in (1, 15))
    return len(present), share, adjacent


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args()
    data_root: Path = args.data_root.resolve()
    downloads = data_root / "downloads" / DATASET_ID
    samples_root = data_root / "samples" / DATASET_ID
    index_path = data_root / "index" / DATASET_ID / "samples.jsonl"

    manifest = tomllib.loads(args.manifest.read_text(encoding="utf-8"))
    if manifest.get("dataset_id") != DATASET_ID:
        fail("manifest dataset_id")
    specs = {entry.get("id"): entry for entry in manifest.get("series", [])}
    if set(specs) != {series_id for series_id, _, _ in REGIMES.values()}:
        fail(f"manifest series {sorted(specs)} differ from the two regime series")
    natural_kinds = set()
    for series_id, spec in specs.items():
        if (spec.get("role"), spec.get("numeric_kind"), spec.get("bit_width"), spec.get("endianness")) != ("primary", "int", 16, "little"):
            fail(f"manifest series {series_id} type fields")
        if spec.get("output_path") != f"samples/{DATASET_ID}/{series_id}/":
            fail(f"manifest series {series_id} output_path")
        natural_kinds.add(spec.get("natural_record_kind"))
    if len(natural_kinds) != 1:
        fail("both series must share one natural_record_kind")
    natural_kind = natural_kinds.pop()

    sums_path = downloads / "SHA256SUMS.txt"
    if file_sha256(sums_path) != PINNED_SUMS:
        fail("SHA256SUMS.txt is not the pinned official list")
    sums = {}
    for line in sums_path.read_text(encoding="ascii").splitlines():
        if line.strip():
            digest, name = line.split()
            sums[name] = digest
    if file_sha256(downloads / "RECORDS") != sums["RECORDS"]:
        fail("RECORDS checksum")
    entries = [line.strip() for line in (downloads / "RECORDS").read_text(encoding="ascii").splitlines() if line.strip()]
    if len(entries) != 300 or len(set(entries)) != 300 or not all(entry.startswith("tpehgdb/tpehg") for entry in entries):
        fail("RECORDS inventory")

    expected_rows = []
    record_tally = {series_id: 0 for series_id, _, _ in REGIMES.values()}
    for entry in entries:
        record_id = entry.split("/", 1)[1]
        hea = downloads / f"{entry}.hea"
        dat = downloads / f"{entry}.dat"
        if file_sha256(hea) != sums[f"{entry}.hea"] or file_sha256(dat) != sums[f"{entry}.dat"]:
            fail(f"{record_id}: source checksum")
        frequency, frames, pairs = header_info(hea, record_id)
        series_id, lattice, _ = REGIMES[frequency]
        record_tally[series_id] += 1
        blob = dat.read_bytes()
        if len(blob) != frames * 24:
            fail(f"{record_id}: .dat length {len(blob)} != {frames} * 24")
        decoded = struct.unpack(f"<{frames * 12}h", blob)
        for signal, (initial, checksum) in enumerate(pairs):
            column = decoded[signal::12]
            if column[0] != initial or (sum(column) & 0xFFFF) != (checksum & 0xFFFF):
                fail(f"{record_id}: signal {signal} initial value or checksum")
        for signal, channel, lead in KEEP:
            column = decoded[signal::12]
            payload = struct.pack(f"<{frames}h", *column)
            relative = f"samples/{DATASET_ID}/{series_id}/{record_id}_ch{channel}.bin"
            if not (data_root / relative).is_file():
                fail(f"{relative}: missing sample (wrong series or not built)")
            if (data_root / relative).read_bytes() != payload:
                fail(f"{relative}: bytes differ from source decode")
            residue_count, share, adjacent = lattice_profile(column)
            if lattice == "step1" and not (residue_count == 16 and share <= 0.5):
                fail(f"{record_id} channel {channel}: not a full step-1 code lattice ({residue_count}, {share})")
            if lattice == "step16" and not (residue_count <= 2 and adjacent):
                fail(f"{record_id} channel {channel}: not a two-adjacent-residue step-16 lattice ({residue_count})")
            distinct = len(set(column))
            changes = 0
            run = best = 1
            previous = column[0]
            for value in column[1:]:
                if value != previous:
                    changes += 1
                    run = 1
                else:
                    run += 1
                    best = max(best, run)
                previous = value
            low = column.count(-32768)
            high = column.count(32767)
            lo, hi = min(column), max(column)
            if lo == hi or distinct < 32 or changes < 0.05 * frames or (low + high) > 0.5 * frames:
                fail(f"{record_id} channel {channel}: degenerate waveform")
            expected_rows.append({
                "adc_code_lattice": lattice,
                "adc_gain_per_mv": 13107,
                "adc_resolution_bits": 16,
                "adc_zero": 0,
                "bipolar_lead": lead,
                "bit_width": 16,
                "channel": channel,
                "dataset_id": DATASET_ID,
                "distinct_values": distinct,
                "element_size_bytes": 2,
                "endianness": "little",
                "longest_constant_run": best,
                "maximum": hi,
                "minimum": lo,
                "mod16_residue_count": residue_count,
                "mod16_top2_fraction": share,
                "natural_record_kind": natural_kind,
                "numeric_kind": "int",
                "record_id": record_id,
                "role": "primary",
                "sample_axes": ["time_sample"],
                "sample_path": relative,
                "sample_rank": 1,
                "sample_shape": [frames],
                "sample_size_bytes": 2 * frames,
                "sampling_frequency_header": frequency,
                "saturated_high_count": high,
                "saturated_low_count": low,
                "series_id": series_id,
                "sha256": hashlib.sha256(payload).hexdigest(),
                "source_sample": f"downloads/{DATASET_ID}/{entry}.dat",
                "source_signal_index": signal,
                "transition_count": changes,
                "value_count": frames,
            })

    for series_id, _, expected_records in REGIMES.values():
        if record_tally[series_id] != expected_records:
            fail(f"{series_id}: {record_tally[series_id]} records != {expected_records}")

    actual_rows = [json.loads(line) for line in index_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    for row in actual_rows:
        if set(row) != ALLOWED_INDEX_KEYS:
            fail(f"index row keys differ: {sorted(set(row) ^ ALLOWED_INDEX_KEYS)}")
    if actual_rows != expected_rows:
        fail("sample index differs from the independent re-derivation")
    on_disk = sorted(path.relative_to(data_root).as_posix() for path in samples_root.rglob("*") if path.is_file())
    if on_disk != sorted(str(row["sample_path"]) for row in expected_rows):
        fail("sample tree contains missing or extra files")
    digests = [row["sha256"] for row in expected_rows]
    if len(set(digests)) != len(digests):
        fail("duplicate samples")

    summary = []
    for series_id, spec in specs.items():
        series_rows = [row for row in expected_rows if row["series_id"] == series_id]
        total_bytes = sum(int(row["sample_size_bytes"]) for row in series_rows)
        if spec.get("sample_count") != len(series_rows) or spec.get("total_size_bytes") != total_bytes:
            fail(f"manifest {series_id} sample_count={spec.get('sample_count')} total_size_bytes={spec.get('total_size_bytes')} "
                 f"!= realized {len(series_rows)} / {total_bytes}")
        counts = sorted(int(row["value_count"]) for row in series_rows)
        summary.append(f"{series_id}: samples={len(series_rows)} values={sum(counts)} bytes={total_bytes} "
                       f"median_values={counts[len(counts) // 2]}")
    total_bytes = sum(int(row["sample_size_bytes"]) for row in expected_rows)
    if len(expected_rows) != 900 or total_bytes != 63_935_406:
        fail("realized scope differs from the pinned 300-record population")
    print(f"verify ok: records={len(entries)} samples={len(expected_rows)} bytes={total_bytes}")
    for line in summary:
        print("  " + line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
