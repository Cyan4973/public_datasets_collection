#!/usr/bin/env python3
"""Build UK-DALE IAM real-power samples from locally fetched ZIP member ranges.

For every pinned EcoManagerTxPlug channel of houses 2-5:
  * re-check the ZIP local header and inflate with CRC32/size checks;
  * require the whole text to be newline-terminated '<unix_ts> <watts>' lines
    made of ASCII decimal digits (strict regular-expression full match);
  * emit watts as uint16 little-endian (primary) and the unix timestamps as
    uint32 little-endian (auxiliary), one sample per channel file, same order.
Any malformed line, a watt value above 65535, or a timestamp at or above 2^32
is fatal; nothing is dropped, clipped or imputed.
"""
from __future__ import annotations

import argparse
import array
import csv
import hashlib
import json
import re
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ukdale_zip import inflate_checked, local_member_data  # noqa: E402

DATASET_ID = "ceda_ukdale_iam_appliance_power_u16"
PRIMARY = "ukdale_iam_active_power_w_u16"
AUX = "ukdale_iam_unix_time_s_u32"
DEVICE_UPPER_LIMIT_W = 3300
MAX_SAMPLE_PERIOD_S = 120
LINES = re.compile(rb"(?:[0-9]+ [0-9]+\n)+")


def to_le_bytes(values: array.array) -> bytes:
    if sys.byteorder != "little":
        values = array.array(values.typecode, values)
        values.byteswap()
    return values.tobytes()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--pinned", type=Path, required=True)
    args = parser.parse_args()
    if array.array("H").itemsize != 2 or array.array("I").itemsize != 4:
        raise SystemExit("FATAL: unexpected array item sizes on this platform")

    root = args.data_root
    member_dir = root / "downloads" / DATASET_ID / "members"
    samples_root = root / "samples" / DATASET_ID
    index_path = root / "index" / DATASET_ID / "samples.jsonl"
    stats_path = root / "filtered" / DATASET_ID / "ingest_stats.json"
    rows = list(csv.DictReader(args.pinned.open(encoding="utf-8", newline=""), delimiter="\t"))
    for series in (PRIMARY, AUX):
        target = samples_root / series
        target.mkdir(parents=True, exist_ok=True)
        for stale in target.glob("*.bin"):
            stale.unlink()
    index_path.parent.mkdir(parents=True, exist_ok=True)
    stats_path.parent.mkdir(parents=True, exist_ok=True)

    index_rows: list[dict] = []
    per_channel: list[dict] = []
    for row in rows:
        house, channel, member = int(row["house"]), int(row["channel"]), row["member"]
        stem = f"house_{house}_channel_{channel:02d}"
        blob = (member_dir / f"{stem}.zipmember").read_bytes()
        crc = int(row["crc32"], 16)
        usz = int(row["uncompressed_size"])
        data = local_member_data(blob, member, 8, crc, int(row["compressed_size"]), usz)
        text = inflate_checked(data, member, 8, crc, usz)
        if not LINES.fullmatch(text):
            first_bad = next(
                (n for n, line in enumerate(text.split(b"\n")[:-1], 1) if not re.fullmatch(rb"[0-9]+ [0-9]+", line)),
                None,
            )
            raise SystemExit(f"FATAL: {member}: malformed line {first_bad} (or missing final newline)")
        tokens = text.split()
        del text
        try:
            watts = array.array("H", map(int, tokens[1::2]))
        except OverflowError:
            raise SystemExit(f"FATAL: {member}: watt value above 65535") from None
        try:
            stamps = array.array("I", map(int, tokens[0::2]))
        except OverflowError:
            raise SystemExit(f"FATAL: {member}: timestamp at or above 2^32") from None
        del tokens
        count = len(watts)
        if count != len(stamps) or count == 0:
            raise SystemExit(f"FATAL: {member}: token count mismatch")

        steps = [b - a for a, b in zip(stamps, stamps[1:])]
        nonincreasing = sum(1 for step in steps if step <= 0)
        long_gaps = sum(1 for step in steps if step > MAX_SAMPLE_PERIOD_S)
        distinct = len(set(watts))
        zeros = watts.count(0)
        over_limit = sum(1 for value in watts if value > DEVICE_UPPER_LIMIT_W)

        for series, values, kind, width in ((PRIMARY, watts, "uint", 16), (AUX, stamps, "uint", 32)):
            payload = to_le_bytes(values)
            relative = f"samples/{DATASET_ID}/{series}/{stem}.bin"
            (root / relative).write_bytes(payload)
            entry = {
                "dataset_id": DATASET_ID,
                "series_id": series,
                "role": "primary" if series == PRIMARY else "auxiliary",
                "sample_path": relative,
                "numeric_kind": kind,
                "bit_width": width,
                "endianness": "little",
                "element_size_bytes": width // 8,
                "sample_size_bytes": len(payload),
                "value_count": count,
                "min": min(values),
                "max": max(values),
                "sha256": hashlib.sha256(payload).hexdigest(),
                "house": house,
                "channel": channel,
                "appliance": row["appliance"],
                "source_member": member,
                "source_member_crc32": row["crc32"],
            }
            index_rows.append(entry)
        per_channel.append(
            {
                "house": house,
                "channel": channel,
                "appliance": row["appliance"],
                "values": count,
                "min_w": min(watts),
                "max_w": max(watts),
                "distinct_w": distinct,
                "zero_fraction": round(zeros / count, 6),
                "values_above_3300_w": over_limit,
                "first_ts": stamps[0],
                "last_ts": stamps[-1],
                "median_step_s": statistics.median(steps) if steps else None,
                "nonincreasing_steps": nonincreasing,
                "gaps_over_120_s": long_gaps,
            }
        )
        print(
            f"{stem} {row['appliance']}: values={count} watts={min(watts)}..{max(watts)} distinct={distinct} "
            f"zero_frac={zeros / count:.3f} >3300W={over_limit} gaps>120s={long_gaps} nonincreasing={nonincreasing}"
        )

    with index_path.open("w", encoding="utf-8") as handle:
        for entry in index_rows:
            handle.write(json.dumps(entry, sort_keys=True) + "\n")
    counts = sorted(item["values"] for item in per_channel)
    summary = {
        "dataset_id": DATASET_ID,
        "samples_per_series": len(per_channel),
        "primary_values": sum(counts),
        "primary_bytes": 2 * sum(counts),
        "auxiliary_bytes": 4 * sum(counts),
        "median_values_per_sample": statistics.median(counts),
        "min_values_per_sample": counts[0],
        "max_values_per_sample": counts[-1],
        "observed_max_w": max(item["max_w"] for item in per_channel),
        "device_upper_limit_w": DEVICE_UPPER_LIMIT_W,
        "values_above_device_limit": sum(item["values_above_3300_w"] for item in per_channel),
        "channels_with_values_above_device_limit": sum(1 for item in per_channel if item["values_above_3300_w"]),
        "nonincreasing_timestamp_steps": sum(item["nonincreasing_steps"] for item in per_channel),
        "gaps_over_120_s": sum(item["gaps_over_120_s"] for item in per_channel),
        "channels": per_channel,
    }
    stats_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        f"build=ok samples={len(per_channel)} primary_values={summary['primary_values']} "
        f"primary_bytes={summary['primary_bytes']} median={summary['median_values_per_sample']} "
        f"observed_max_w={summary['observed_max_w']} above_3300={summary['values_above_device_limit']}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
