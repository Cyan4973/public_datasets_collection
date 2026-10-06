#!/usr/bin/env python3
"""Independent verifier for usgs_grandbay_klein3900_sidescan_xtf_u16.

Does not import the build helper. For every pinned member it re-walks the
extracted XTF file with its own parser, re-derives the ping-major
[port 4096 | starboard 4096] uint16 payload, byte-compares it with the emitted
sample, recomputes value statistics from the stored sample bytes, and checks
the sample index and manifest totals. Fails on any structural deviation, a
constant or degenerate channel, or a mismatch.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import struct
import sys
import tomllib
import zlib
from array import array
from pathlib import Path

DATASET_ID = "usgs_grandbay_klein3900_sidescan_xtf_u16"
SERIES_ID = "klein_sidescan_port_stbd_backscatter_u16"
HEADER = struct.Struct("<HBBHHHI")  # magic, type, subchannel, chans, reserved x2, record bytes
CHAN = struct.Struct("<HHfffffHHHHHIHBBI")  # XTFPINGCHANHEADER prefix up to NumSamples (46 bytes)
EXPECTED_INDEX_KEYS = {
    "dataset_id", "series_id", "sample_path", "numeric_kind", "bit_width", "endianness",
    "element_size_bytes", "sample_size_bytes", "value_count", "sample_shape", "source_member",
    "source_member_crc32", "ping_count", "minimum", "maximum", "sha256",
}


def die(message: str) -> None:
    raise SystemExit(f"VERIFY FAIL: {message}")


def read_sources(path: Path) -> list[dict]:
    lines = path.read_text(encoding="utf-8").splitlines()
    header = lines[0].split("\t")
    rows = []
    for line in lines[1:]:
        if line.strip():
            row = dict(zip(header, line.split("\t")))
            row["uncompressed_bytes"] = int(row["uncompressed_bytes"])
            row["ping_count"] = int(row["ping_count"])
            rows.append(row)
    return rows


def rederive(xtf: Path, row: dict) -> tuple[bytes, int]:
    data = xtf.read_bytes()
    if len(data) != row["uncompressed_bytes"]:
        die(f"{xtf.name}: size {len(data)} != {row['uncompressed_bytes']}")
    if f"{zlib.crc32(data) & 0xFFFFFFFF:08x}" != row["crc32"]:
        die(f"{xtf.name}: CRC32 mismatch against the ZIP central directory")
    if data[0] != 123:
        die(f"{xtf.name}: not an XTF file (FileFormat {data[0]})")
    if struct.unpack_from("<H", data, 166)[0] != 2:
        die(f"{xtf.name}: NumberOfSonarChannels != 2")
    for index, wanted_type in enumerate((1, 2)):
        base = 256 + 128 * index
        if data[base] != wanted_type or struct.unpack_from("<H", data, base + 6)[0] != 2:
            die(f"{xtf.name}: CHANINFO[{index}] is not a 2-byte {'port' if wanted_type == 1 else 'starboard'} channel")
    parts: list[bytes] = []
    offset = 1024
    pings = 0
    while offset < len(data):
        magic, kind, _sub, chans, _a, _b, length = HEADER.unpack_from(data, offset)
        if magic != 0xFACE or length < HEADER.size or offset + length > len(data):
            die(f"{xtf.name}: broken packet framing at {offset}")
        if kind == 0:
            if chans != 2:
                die(f"{xtf.name}: sonar ping with {chans} channels at {offset}")
            cursor = offset + 256
            for expected_channel in (0, 1):
                fields = CHAN.unpack_from(data, cursor)
                channel, slant, frequency, samples = fields[0], fields[2], fields[8], fields[16]
                if (channel, samples, frequency, slant) != (expected_channel, 4096, 100, 100.0):
                    die(f"{xtf.name}: ping at {offset} channel header {(channel, samples, frequency, slant)}")
                parts.append(data[cursor + 64 : cursor + 64 + 2 * samples])
                cursor += 64 + 2 * samples
            if length != -(-(cursor - offset) // 64) * 64:
                die(f"{xtf.name}: ping at {offset} record length {length} inconsistent with channel payloads")
            pings += 1
        offset += length
    if offset != len(data):
        die(f"{xtf.name}: packet walk overran the file")
    if pings != row["ping_count"]:
        die(f"{xtf.name}: {pings} pings != pinned {row['ping_count']}")
    return b"".join(parts), pings


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", required=True)
    parser.add_argument("--data-dir", required=True)
    parser.add_argument("--recipe-dir", required=True)
    args = parser.parse_args()
    repo_root = Path(args.repo_root).resolve()
    data_root = Path(args.data_dir)
    if not data_root.is_absolute():
        data_root = repo_root / data_root
    recipe = Path(args.recipe_dir)
    manifest = tomllib.loads((recipe / "manifest.toml").read_text(encoding="utf-8"))
    if manifest.get("dataset_id") != DATASET_ID:
        die("manifest dataset_id mismatch")
    series = {s["id"]: s for s in manifest.get("series", [])}
    if set(series) != {SERIES_ID}:
        die(f"manifest series {sorted(series)} != [{SERIES_ID}]")
    spec = series[SERIES_ID]
    if (spec.get("role"), spec.get("numeric_kind"), spec.get("bit_width"), spec.get("endianness")) != ("primary", "uint", 16, "little"):
        die("manifest series type/role mismatch")
    sources = read_sources(recipe / "sources.tsv")
    index_path = data_root / "index" / DATASET_ID / "samples.jsonl"
    rows = [json.loads(line) for line in index_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    by_member = {r.get("source_member"): r for r in rows}
    if len(rows) != len(sources) or set(by_member) != {s["member"] for s in sources}:
        die(f"index rows ({len(rows)}) do not match the {len(sources)} pinned members one-to-one")
    sample_dir = data_root / "samples" / DATASET_ID / SERIES_ID
    on_disk = sorted(p.name for p in sample_dir.iterdir())
    if on_disk != sorted(Path(r["sample_path"]).name for r in rows):
        die("sample directory contents differ from the index")
    total_values = total_bytes = 0
    padding_pings_checked = 0
    sizes = []
    digests = set()
    for source in sources:
        row = by_member[source["member"]]
        missing = EXPECTED_INDEX_KEYS - set(row)
        if missing:
            die(f"index row for {source['member']} lacks {sorted(missing)}")
        if (row["dataset_id"], row["series_id"], row["numeric_kind"], row["bit_width"], row["endianness"], row["element_size_bytes"]) != (
            DATASET_ID, SERIES_ID, "uint", 16, "little", 2
        ):
            die(f"index row for {source['member']} has wrong type fields")
        xtf = data_root / "downloads" / DATASET_ID / "xtf" / source["member"]
        expected, pings = rederive(xtf, source)
        sample = data_root / row["sample_path"]
        stored = sample.read_bytes()
        if stored != expected:
            die(f"{sample.name}: bytes differ from the independently re-derived payload")
        values = array("H")
        values.frombytes(stored)
        if sys.byteorder != "little":
            values.byteswap()
        if len(values) != pings * 8192 or row["value_count"] != len(values) or row["sample_size_bytes"] != len(stored):
            die(f"{sample.name}: value_count/sample_size mismatch")
        if row["sample_shape"] != [pings, 2, 4096] or row["ping_count"] != pings:
            die(f"{sample.name}: sample_shape/ping_count mismatch")
        if row["minimum"] != min(values) or row["maximum"] != max(values):
            die(f"{sample.name}: index min/max differ from stored uint16 values")
        digest = hashlib.sha256(stored).hexdigest()
        if row["sha256"] != digest:
            die(f"{sample.name}: sha256 mismatch")
        if digest in digests:
            die(f"{sample.name}: duplicate sample payload")
        digests.add(digest)
        # Documented orientation: port is stored far-to-nadir and starboard nadir-to-far,
        # with 7 zero padding samples at the far-range end of each channel in every ping.
        zero7 = array("H", [0] * 7)
        for ping in range(pings):
            base = ping * 8192
            if values[base : base + 7] != zero7 or values[base + 8185 : base + 8192] != zero7:
                die(f"{sample.name}: ping {ping} lacks the 7-sample far-range zero padding (port[0:7] / stbd[4089:4096])")
        padding_pings_checked += pings
        # Degeneracy: each channel separately must be non-constant, mostly non-zero, and rich.
        for label, start in (("port", 0), ("starboard", 4096)):
            channel = array("H")
            for ping in range(pings):
                base = ping * 8192 + start
                channel.extend(values[base : base + 4096])
            distinct = len(set(channel))
            zeros = channel.count(0)
            if distinct < 64 or max(channel) == 0 or zeros * 2 > len(channel):
                die(f"{sample.name}: degenerate {label} channel (distinct={distinct}, zeros={zeros})")
        total_values += len(values)
        total_bytes += len(stored)
        sizes.append(len(values))
        print(f"ok {sample.name} pings={pings} values={len(values)} min={min(values)} max={max(values)}", flush=True)
    if spec.get("sample_count") != len(rows) or spec.get("total_size_bytes") != total_bytes:
        die(f"manifest sample_count/total_size_bytes ({spec.get('sample_count')}/{spec.get('total_size_bytes')}) != realized ({len(rows)}/{total_bytes})")
    if total_bytes > 1_000_000_000:
        die("primary output exceeds 1,000,000,000 bytes")
    sizes.sort()
    median = sizes[len(sizes) // 2] if len(sizes) % 2 else (sizes[len(sizes) // 2 - 1] + sizes[len(sizes) // 2]) / 2
    if total_values < 10_000 or median < 1_000:
        die("primary floor not met")
    print(f"far_range_padding_ok pings_checked={padding_pings_checked} (port[0:7] == 0 and stbd[4089:4096] == 0 in every ping)")
    print(f"verify_summary samples={len(rows)} values={total_values} bytes={total_bytes} median_values={median}")


if __name__ == "__main__":
    main()
