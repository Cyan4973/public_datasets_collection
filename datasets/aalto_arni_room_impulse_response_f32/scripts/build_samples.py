#!/usr/bin/env python3
"""Build Arni impulse-response samples from locally downloaded WAV members.

Local files only.  For each row of the pinned selection.tsv the downloaded
WAV member is size/CRC-32 checked, its RIFF/WAVE structure validated (mono
44.1 kHz IEEE float32, fact length, PEAK consistency) and its `data` chunk
written as one raw little-endian float32 sample (105,840 values).
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import shutil
import sys
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import arni_zip as az  # noqa: E402

DATASET_ID = "aalto_arni_room_impulse_response_f32"
SERIES_ID = "arni_room_impulse_response_f32"
NATURAL_RECORD_KIND = "single_receiver_swept_sine_room_impulse_response_measurement"


def read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def load_panel_states(path: Path) -> dict[int, str]:
    rows = list(csv.reader(io.StringIO(path.read_text(encoding="utf-8-sig")), delimiter=";"))
    if len(rows[0]) != 56 or rows[0][1:] != [str(i) for i in range(1, 56)]:
        raise SystemExit("combinations_setup.csv header is not panels 1..55")
    states: dict[int, str] = {}
    for row in rows[1:]:
        if not row:
            continue
        if len(row) != 56:
            raise SystemExit(f"combinations_setup.csv row has {len(row)} fields")
        combo = int(row[0])
        mapping = {"0.0": "0", "1.0": "1"}
        try:
            states[combo] = "".join(mapping[value] for value in row[1:])
        except KeyError as exc:
            raise SystemExit(f"combination {combo}: unexpected panel state {exc}") from exc
    if sorted(states) != list(range(len(states))) or len(states) != 5342:
        raise SystemExit("combinations_setup.csv does not hold combinations 0..5341")
    return states


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--selection", required=True)
    parser.add_argument("--wav-dir", required=True)
    parser.add_argument("--csv", required=True)
    parser.add_argument("--data-root", required=True)
    args = parser.parse_args()

    data_root = Path(args.data_root)
    wav_dir = Path(args.wav_dir)
    series_dir = data_root / "samples" / DATASET_ID / SERIES_ID
    index_path = data_root / "index" / DATASET_ID / "samples.jsonl"
    stats_path = data_root / "filtered" / DATASET_ID / "ingest_stats.json"
    rows = read_tsv(Path(args.selection))
    states = load_panel_states(Path(args.csv))
    if len(rows) != 265:
        raise SystemExit(f"selection holds {len(rows)} rows, expected 265")

    if series_dir.exists():
        shutil.rmtree(series_dir)
    series_dir.mkdir(parents=True)
    index_path.parent.mkdir(parents=True, exist_ok=True)
    stats_path.parent.mkdir(parents=True, exist_ok=True)

    aggregate = hashlib.sha256()
    index_rows = []
    global_min = float("inf")
    global_max = float("-inf")
    total_bytes = 0
    for row in rows:
        key = (int(row["num_closed"]), int(row["num_comb"]), int(row["mic"]), int(row["sweep"]))
        wav = (wav_dir / row["member"]).read_bytes()
        if len(wav) != int(row["uncompressed_size"]):
            raise SystemExit(f"{row['member']}: size {len(wav)} != {row['uncompressed_size']}")
        if f"{zlib.crc32(wav) & 0xFFFFFFFF:08x}" != row["crc32"]:
            raise SystemExit(f"{row['member']}: CRC-32 mismatch")
        data, chunk_ids = az.parse_wav_float32(wav, row["member"])
        stats = az.float32_stats(data, row["member"])
        state = states[key[1]]
        if state.count("0") != key[0]:
            raise SystemExit(f"{row['member']}: panel table has {state.count('0')} reflective panels, name says {key[0]}")
        out = series_dir / f"{az.sample_stem(key)}.bin"
        out.write_bytes(data)
        aggregate.update(data)
        total_bytes += len(data)
        global_min = min(global_min, stats["min"])
        global_max = max(global_max, stats["max"])
        index_rows.append(
            {
                "dataset_id": DATASET_ID,
                "series_id": SERIES_ID,
                "sample_path": out.relative_to(data_root).as_posix(),
                "numeric_kind": "float",
                "bit_width": 32,
                "endianness": "little",
                "element_size_bytes": 4,
                "sample_size_bytes": len(data),
                "value_count": stats["value_count"],
                "role": "primary",
                "natural_record_kind": NATURAL_RECORD_KIND,
                "sample_rate_hz": az.WAV_RATE,
                "num_closed": key[0],
                "num_comb": key[1],
                "mic": key[2],
                "sweep": key[3],
                "panel_state_reflective0_absorptive1": state,
                "source_archive": row["archive"],
                "source_member": row["member"],
                "source_member_crc32": row["crc32"],
                "source_chunks": chunk_ids,
                "sample_sha256": hashlib.sha256(data).hexdigest(),
                "min": stats["min"],
                "max": stats["max"],
                "peak_abs": stats["peak_abs"],
                "peak_index": stats["peak_index"],
                "zero_count": stats["zero_count"],
                "int16_lattice_fraction": stats["int16_lattice_fraction"],
                "distinct_bit_patterns": stats["distinct_bit_patterns"],
            }
        )
    with index_path.open("w", encoding="utf-8") as handle:
        for entry in index_rows:
            handle.write(json.dumps(entry, sort_keys=True) + "\n")
    summary = {
        "dataset_id": DATASET_ID,
        "series_id": SERIES_ID,
        "sample_count": len(index_rows),
        "total_values": sum(r["value_count"] for r in index_rows),
        "total_size_bytes": total_bytes,
        "num_closed_values": sorted({r["num_closed"] for r in index_rows}),
        "mics": sorted({r["mic"] for r in index_rows}),
        "global_min": global_min,
        "global_max": global_max,
        "aggregate_sha256": aggregate.hexdigest(),
        "max_int16_lattice_fraction": max(r["int16_lattice_fraction"] for r in index_rows),
        "min_distinct_bit_patterns": min(r["distinct_bit_patterns"] for r in index_rows),
    }
    stats_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(summary, sort_keys=True))


if __name__ == "__main__":
    main()
