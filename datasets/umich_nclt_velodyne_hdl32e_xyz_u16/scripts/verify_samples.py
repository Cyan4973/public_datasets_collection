#!/usr/bin/env python3
"""Independently verify the NCLT velodyne_sync x,y,z uint16 samples.

Does not import or reuse the build code and does not trust members.tsv:

* checks the archive SHA-256 pinned at first download, then
* streams the local tarball once (gzip CRC32/ISIZE checked at EOF) and records
  every velodyne_sync member's utime and hit count; members named in the index
  are re-decoded with a different method (array('H') over the whole record
  stream, columns 0..2 of every 4-word record) and compared byte for byte
  with the sample file;
* after the stream, re-derives the selection (sorted utime order, every
  STRIDE-th from rank 0, minus revolutions with fewer than MIN_HITS hits) and
  requires the index to match it exactly;
* checks index fields, file inventory, SHA-256, min/max computed from the
  stored uint16 codes, laser_id 0..31 in the source, codes <= 40000,
  non-constant samples and axes, the stats file, and the manifest's
  sample_count and total_size_bytes.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import math
import re
import sys
import tarfile
import tomllib
from array import array
from pathlib import Path

INDEX_KEYS = {
    "dataset_id", "series_id", "sample_path", "numeric_kind", "bit_width", "endianness",
    "element_size_bytes", "sample_size_bytes", "value_count",
}
MAX_CODE = 40000
MAX_LASER_ID = 31


def fail(message: str) -> None:
    raise SystemExit(f"VERIFY FAILED: {message}")


def rederive(body: bytes) -> tuple[bytes, int]:
    words = array("H")
    words.frombytes(body)
    if sys.byteorder != "little":
        words.byteswap()
    n = len(words) // 4
    out = array("H", bytes(6 * n))
    out[0::3] = words[0::4]
    out[1::3] = words[1::4]
    out[2::3] = words[2::4]
    laser_max = max(words[3::4]) >> 8 if n else -1
    if sys.byteorder != "little":
        out.byteswap()
    return out.tobytes(), laser_max


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--dataset-id", required=True)
    parser.add_argument("--series-id", required=True)
    parser.add_argument("--stride", type=int, required=True)
    parser.add_argument("--min-hits", type=int, required=True)
    parser.add_argument("--stats", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--archive-sha256", help="pinned SHA-256 of the downloaded archive")
    parser.add_argument("--skip-manifest-totals", action="store_true",
                        help="only for synthetic self-tests; the real verify.sh never passes it")
    args = parser.parse_args()

    if args.archive_sha256:
        digest = hashlib.sha256()
        with args.archive.open("rb") as handle:
            while block := handle.read(8 << 20):
                digest.update(block)
        if digest.hexdigest() != args.archive_sha256:
            fail(f"archive SHA-256 {digest.hexdigest()} != pinned {args.archive_sha256}")
        print(f"archive_sha256=ok {args.archive_sha256}")

    data_root = args.data_root.resolve()
    index_path = data_root / "index" / args.dataset_id / "samples.jsonl"
    series_dir = data_root / "samples" / args.dataset_id / args.series_id
    rows = [json.loads(line) for line in index_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not rows:
        fail("empty index")
    by_member: dict[str, dict] = {}
    for number, row in enumerate(rows, 1):
        missing = INDEX_KEYS - set(row)
        if missing:
            fail(f"index row {number} missing {sorted(missing)}")
        if (row["dataset_id"], row["series_id"]) != (args.dataset_id, args.series_id):
            fail(f"index row {number}: wrong dataset/series id")
        if (row["numeric_kind"], row["bit_width"], row["endianness"], row["element_size_bytes"]) != ("uint", 16, "little", 2):
            fail(f"index row {number}: wrong numeric type fields")
        path = data_root / row["sample_path"]
        if path.parent != series_dir or not path.is_file():
            fail(f"index row {number}: bad sample path {row['sample_path']}")
        size = path.stat().st_size
        if size != row["sample_size_bytes"] or size != 2 * row["value_count"] or row["value_count"] != 3 * row["hit_count"]:
            fail(f"index row {number}: size/value_count/hit_count mismatch")
        if row["sample_shape"] != [row["hit_count"], 3]:
            fail(f"index row {number}: sample_shape mismatch")
        if path.name != f"{row['utime']}.bin" or not row["source_member"].endswith(f"/velodyne_sync/{row['utime']}.bin"):
            fail(f"index row {number}: sample name does not match its source member")
        if row["source_member"] in by_member:
            fail(f"duplicate source member {row['source_member']}")
        by_member[row["source_member"]] = row
    utimes = [row["utime"] for row in rows]
    if utimes != sorted(utimes):
        fail("index rows are not in utime order")
    on_disk = sorted(p.name for p in series_dir.iterdir())
    if on_disk != sorted(Path(row["sample_path"]).name for row in rows):
        fail("sample directory inventory differs from the index")

    pattern = re.compile(r"^2013-01-10/velodyne_sync/(\d{16})\.bin$")
    census: dict[int, int] = {}
    checked = 0
    with gzip.open(args.archive, "rb") as gz:
        with tarfile.open(fileobj=gz, mode="r|") as tar:
            for member in tar:
                match = pattern.match(member.name)
                if not member.isfile() or not match:
                    continue
                if member.size % 8:
                    fail(f"{member.name}: size not a multiple of 8")
                utime = int(match.group(1))
                if utime in census:
                    fail(f"duplicate sync utime {utime}")
                census[utime] = member.size // 8
                row = by_member.get(member.name)
                if row is None:
                    continue
                body = tar.extractfile(member).read()
                if hashlib.sha256(body).hexdigest() != row["source_sha256"]:
                    fail(f"{member.name}: source SHA-256 differs from index")
                expected, laser_max = rederive(body)
                if laser_max > MAX_LASER_ID:
                    fail(f"{member.name}: laser_id {laser_max} > {MAX_LASER_ID}")
                stored = (data_root / row["sample_path"]).read_bytes()
                if stored != expected:
                    fail(f"{row['sample_path']}: bytes differ from the re-derived x,y,z of {member.name}")
                if hashlib.sha256(stored).hexdigest() != row["sha256"]:
                    fail(f"{row['sample_path']}: SHA-256 mismatch")
                codes = array("H")
                codes.frombytes(stored)
                axes = [codes[0::3], codes[1::3], codes[2::3]]
                axis_min = [min(a) for a in axes]
                axis_max = [max(a) for a in axes]
                if axis_min != row["axis_min"] or axis_max != row["axis_max"]:
                    fail(f"{row['sample_path']}: per-axis min/max differ from index")
                if min(axis_min) != row["min"] or max(axis_max) != row["max"]:
                    fail(f"{row['sample_path']}: min/max differ from index")
                if max(axis_max) > MAX_CODE:
                    fail(f"{row['sample_path']}: code above {MAX_CODE}")
                if any(lo == hi for lo, hi in zip(axis_min, axis_max)):
                    fail(f"{row['sample_path']}: constant axis")
                if axes[2].count(0) != row["z_code_zero_hits"]:
                    fail(f"{row['sample_path']}: z code zero count differs from index")
                laser_bytes = body[7::8]
                per_laser = [laser_bytes.count(laser) for laser in range(MAX_LASER_ID + 1)]
                busiest = per_laser.index(max(per_laser))
                if (max(per_laser), busiest) != (row["max_hits_per_laser"], row["busiest_laser_id"]):
                    fail(f"{row['sample_path']}: busiest-laser diagnostics differ from index")
                azimuths = [
                    math.atan2(axes[1][i] - 20000, axes[0][i] - 20000)
                    for i in range(len(laser_bytes)) if laser_bytes[i] == busiest
                ]
                wraps = sum(1 for a, b in zip(azimuths, azimuths[1:]) if abs(b - a) > math.pi)
                if wraps != row["busiest_laser_azimuth_wraps"]:
                    fail(f"{row['sample_path']}: azimuth wrap count {wraps} differs from index")
                checked += 1
        while gz.read(1 << 20):
            pass  # EOF read: gzip verifies CRC32 and ISIZE

    if checked != len(rows):
        fail(f"only {checked} of {len(rows)} indexed samples were found in the archive")
    ordered = sorted(census)
    selection = ordered[:: args.stride]
    expected_emitted = [u for u in selection if census[u] >= args.min_hits]
    expected_skipped = [u for u in selection if census[u] < args.min_hits]
    if utimes != expected_emitted:
        fail(f"index selection differs from re-derived stride selection ({len(utimes)} vs {len(expected_emitted)})")
    for row in rows:
        if ordered[row["sync_rank"]] != row["utime"] or row["sync_rank"] % args.stride:
            fail(f"{row['sample_path']}: sync_rank inconsistent with stride")

    stats = json.loads(args.stats.read_text(encoding="utf-8"))
    total_bytes = sum(row["sample_size_bytes"] for row in rows)
    total_values = sum(row["value_count"] for row in rows)
    if (stats["sync_members_total"], stats["stride"], stats["min_hits"], stats["samples"], stats["bytes"], stats["values"]) != (
        len(ordered), args.stride, args.min_hits, len(rows), total_bytes, total_values
    ):
        fail("stats file totals differ from the re-derived output")
    if [item["utime"] for item in stats["skipped_below_min_hits"]] != expected_skipped:
        fail("stats skipped list differs from the re-derived skipped revolutions")
    if stats["samples_multi_revolution"] != [row["utime"] for row in rows if row["busiest_laser_azimuth_wraps"] >= 2]:
        fail("stats multi-revolution sample list differs from the index")
    aggregate = hashlib.sha256()
    for row in rows:
        aggregate.update((data_root / row["sample_path"]).read_bytes())
    if aggregate.hexdigest() != stats["aggregate_sha256_index_order"]:
        fail("aggregate SHA-256 differs from stats")

    if not args.skip_manifest_totals:
        manifest = tomllib.loads(args.manifest.read_text(encoding="utf-8"))
        series = [s for s in manifest.get("series", []) if s.get("id") == args.series_id]
        if len(series) != 1:
            fail("manifest series not found")
        if (series[0].get("sample_count"), series[0].get("total_size_bytes")) != (len(rows), total_bytes):
            fail(
                f"manifest sample_count/total_size_bytes {series[0].get('sample_count')}/{series[0].get('total_size_bytes')} "
                f"!= realized {len(rows)}/{total_bytes}"
            )
    values = sorted(row["value_count"] for row in rows)
    print(
        f"verify=ok sync_members={len(ordered)} stride={args.stride} samples={len(rows)} skipped={len(expected_skipped)} "
        f"values={total_values} bytes={total_bytes} median_values={values[len(values) // 2]} "
        f"aggregate_sha256={aggregate.hexdigest()}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
