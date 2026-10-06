#!/usr/bin/env python3
"""Independent verification of the UK-DALE IAM real-power samples.

Does not import the build code. It
  * re-derives the channel selection from the downloaded in-archive metadata
    (every elec_meter with device_model EcoManagerTxPlug in building2-5.yaml)
    and requires it to equal the pinned table and the emitted index;
  * re-parses each ZIP local header, inflates, and checks CRC32/size;
  * re-parses every text line with a line-by-line partition parser (same
    policy as build: two ASCII decimal integers separated by one space; any
    other line, a watt value above 65535 or a timestamp at or above 2^32 is
    fatal; nothing is dropped);
  * re-encodes uint16/uint32 little-endian and byte-compares every sample,
    and checks index fields, manifest counts/sizes and acceptance floors;
  * rejects constant samples and structurally degenerate output.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import statistics
import struct
import sys
import tomllib
import zlib
from pathlib import Path

DATASET_ID = "ceda_ukdale_iam_appliance_power_u16"
PRIMARY = "ukdale_iam_active_power_w_u16"
AUX = "ukdale_iam_unix_time_s_u32"
HOUSES = (2, 3, 4, 5)
INDEX_KEYS = (
    "dataset_id",
    "series_id",
    "sample_path",
    "numeric_kind",
    "bit_width",
    "endianness",
    "element_size_bytes",
    "sample_size_bytes",
    "value_count",
)


def die(message: str) -> None:
    raise SystemExit(f"VERIFY FAILED: {message}")


def iam_channels_from_metadata(metadata_dir: Path) -> set[tuple[int, int]]:
    selected: set[tuple[int, int]] = set()
    for house in HOUSES:
        text = (metadata_dir / f"building{house}.yaml").read_text(encoding="utf-8")
        block = text.split("\nelec_meters:\n", 1)
        if len(block) != 2:
            die(f"building{house}.yaml has no elec_meters block")
        body = re.split(r"\n(?=[A-Za-z_])", block[1], maxsplit=1)[0]
        for number, meter in re.findall(r"(?m)^  (\d+):\n((?:    .*\n?)+)", body):
            model = re.search(r"(?m)^    device_model: (\S+)", meter)
            location = re.search(r"(?m)^    data_location: (\S+)", meter)
            if model and model.group(1) == "EcoManagerTxPlug":
                if not location or location.group(1) != f"house_{house}/channel_{number}.dat":
                    die(f"house {house} meter {number}: unexpected data_location")
                selected.add((house, int(number)))
    return selected


def inflate_member(blob: bytes, name: str, crc: int, csz: int, usz: int) -> bytes:
    if blob[:4] != b"PK\x03\x04":
        die(f"{name}: no local header")
    flags, method = struct.unpack_from("<HH", blob, 6)
    name_len, extra_len = struct.unpack_from("<HH", blob, 26)
    if blob[30 : 30 + name_len].decode("ascii") != name or method != 8 or flags & 0x9:
        die(f"{name}: local header name/method/flags mismatch")
    start = 30 + name_len + extra_len
    if len(blob) - start != csz:
        die(f"{name}: compressed span {len(blob) - start} != {csz}")
    engine = zlib.decompressobj(-15)
    text = engine.decompress(blob[start:])
    text += engine.flush()
    if not engine.eof or engine.unused_data or len(text) != usz or zlib.crc32(text) != crc:
        die(f"{name}: inflate/CRC32/size check failed")
    return text


def parse_lines(text: bytes, name: str) -> tuple[list[int], list[int]]:
    if not text.endswith(b"\n"):
        die(f"{name}: missing final newline")
    stamps: list[int] = []
    watts: list[int] = []
    for number, line in enumerate(text.split(b"\n")[:-1], 1):
        left, space, right = line.partition(b" ")
        if not (space and left.isdigit() and right.isdigit() and left.isascii() and right.isascii()):
            die(f"{name}: malformed line {number}: {line[:40]!r}")
        stamp, watt = int(left), int(right)
        if watt > 0xFFFF or stamp > 0xFFFFFFFF:
            die(f"{name}: line {number} out of range for uint16/uint32")
        stamps.append(stamp)
        watts.append(watt)
    return stamps, watts


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--pinned", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args()
    root = args.data_root
    downloads = root / "downloads" / DATASET_ID

    pinned = list(csv.DictReader(args.pinned.open(encoding="utf-8", newline=""), delimiter="\t"))
    pinned_set = {(int(r["house"]), int(r["channel"])) for r in pinned}
    derived = iam_channels_from_metadata(downloads / "metadata")
    if derived != pinned_set:
        die(f"metadata-derived IAM channels differ from pinned table: {sorted(derived ^ pinned_set)}")

    index_rows = [json.loads(line) for line in (root / "index" / DATASET_ID / "samples.jsonl").read_text().splitlines() if line]
    by_key: dict[tuple[str, int, int], dict] = {}
    for entry in index_rows:
        missing = [key for key in INDEX_KEYS if key not in entry]
        if missing or entry["dataset_id"] != DATASET_ID or entry["endianness"] != "little":
            die(f"bad index row {entry.get('sample_path')}: missing={missing}")
        key = (entry["series_id"], int(entry["house"]), int(entry["channel"]))
        if key in by_key:
            die(f"duplicate index row {key}")
        by_key[key] = entry
    expected_keys = {(series, h, c) for series in (PRIMARY, AUX) for h, c in pinned_set}
    if set(by_key) != expected_keys:
        die(f"index rows do not match the selection: {sorted(set(by_key) ^ expected_keys)[:6]}")
    for series in (PRIMARY, AUX):
        on_disk = {p.name for p in (root / "samples" / DATASET_ID / series).glob("*")}
        wanted = {Path(by_key[(series, h, c)]["sample_path"]).name for h, c in pinned_set}
        if on_disk != wanted:
            die(f"{series}: stray or missing sample files {sorted(on_disk ^ wanted)[:6]}")

    totals = {PRIMARY: [0, 0], AUX: [0, 0]}
    counts: list[int] = []
    zero_heavy = 0
    for row in pinned:
        house, channel, name = int(row["house"]), int(row["channel"]), row["member"]
        blob = (downloads / "members" / f"house_{house}_channel_{channel:02d}.zipmember").read_bytes()
        if len(blob) != int(row["range_bytes"]):
            die(f"{name}: range size changed")
        text = inflate_member(blob, name, int(row["crc32"], 16), int(row["compressed_size"]), int(row["uncompressed_size"]))
        stamps, watts = parse_lines(text, name)
        del text
        count = len(watts)
        if count < 2 or len(set(watts)) < 2:
            die(f"{name}: constant or trivially short watt series ({count} values)")
        if len(set(stamps)) < 2:
            die(f"{name}: constant timestamps")
        for series, values, code, width in ((PRIMARY, watts, "H", 16), (AUX, stamps, "I", 32)):
            entry = by_key[(series, house, channel)]
            payload = struct.pack(f"<{count}{code}", *values)
            sample = (root / entry["sample_path"]).read_bytes()
            if sample != payload:
                die(f"{entry['sample_path']}: bytes differ from re-derived values")
            checks = {
                "numeric_kind": "uint",
                "bit_width": width,
                "element_size_bytes": width // 8,
                "value_count": count,
                "sample_size_bytes": len(payload),
                "min": min(values),
                "max": max(values),
                "sha256": hashlib.sha256(payload).hexdigest(),
                "source_member": name,
            }
            for key, value in checks.items():
                if entry.get(key) != value:
                    die(f"{entry['sample_path']}: index {key}={entry.get(key)!r}, re-derived {value!r}")
            totals[series][0] += 1
            totals[series][1] += len(payload)
        counts.append(count)
        if watts.count(0) / count > 0.99:
            zero_heavy += 1
        print(f"ok {name} values={count} watts={min(watts)}..{max(watts)}")

    manifest = tomllib.loads(args.manifest.read_text(encoding="utf-8"))
    declared = {series["id"]: series for series in manifest.get("series", [])}
    for series in (PRIMARY, AUX):
        spec = declared.get(series)
        if spec is None:
            die(f"manifest lacks series {series}")
        if spec.get("sample_count") != totals[series][0] or spec.get("total_size_bytes") != totals[series][1]:
            die(
                f"manifest {series}: sample_count={spec.get('sample_count')} total_size_bytes={spec.get('total_size_bytes')}"
                f" but realized {totals[series][0]} / {totals[series][1]}"
            )
    primary_values = sum(counts)
    median = statistics.median(counts)
    if not (primary_values >= 10_000 or totals[PRIMARY][1] >= 100_000) or median < 1_000:
        die(f"below acceptance floor: values={primary_values} median={median}")
    if totals[PRIMARY][1] > 1_000_000_000:
        die("primary output exceeds 1,000,000,000 bytes")
    print(
        f"verify=ok samples={len(counts)} primary_values={primary_values} primary_bytes={totals[PRIMARY][1]} "
        f"aux_bytes={totals[AUX][1]} median={median} min={min(counts)} max={max(counts)} "
        f"channels_over_99pct_zero={zero_heavy}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
