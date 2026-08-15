#!/usr/bin/env python3
"""Verify pinned inputs and a fresh native-channel decode against the index."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path


def digests(path: Path) -> tuple[str, str]:
    md5 = hashlib.md5()
    sha256 = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(8 * 1024 * 1024):
            md5.update(chunk)
            sha256.update(chunk)
    return md5.hexdigest(), sha256.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--selection", required=True, type=Path)
    parser.add_argument("--eval-root", required=True, type=Path)
    parser.add_argument("--fresh-root", required=True, type=Path)
    args = parser.parse_args()

    selection = list(csv.DictReader(args.selection.open(encoding="utf-8"), delimiter="\t"))
    tool_root = args.eval_root / "tools" / "tinyexr_v1.0.12"
    for selected in selection:
        root = tool_root if selected["kind"] == "tool" else args.eval_root / "downloads"
        source = root / selected["name"]
        if not source.is_file() or source.stat().st_size != int(selected["size_bytes"]):
            raise SystemExit(f"missing or wrong-size pinned input: {source}")
        md5, sha256 = digests(source)
        if md5 != selected["md5"] or sha256 != selected["sha256"]:
            raise SystemExit(f"pinned input hash mismatch: {source}")

    index_path = args.eval_root / "index" / "samples.jsonl"
    rows = [json.loads(line) for line in index_path.read_text().splitlines() if line.strip()]
    if len(rows) != 121:
        raise SystemExit(f"expected 121 index rows, found {len(rows)}")
    expected_paths = {str(row["sample_path"]) for row in rows}
    actual_paths = {
        path.relative_to(args.eval_root).as_posix()
        for path in (args.eval_root / "samples").rglob("*.bin")
    }
    fresh_paths = {
        path.relative_to(args.fresh_root).as_posix()
        for path in (args.fresh_root / "samples").rglob("*.bin")
    }
    if actual_paths != expected_paths or fresh_paths != expected_paths:
        raise SystemExit("stale, missing, or extra evaluation sample output")

    counts = {16: 0, 32: 0}
    constants = {16: 0, 32: 0}
    total_bytes = 0
    total_values = 0
    for row in rows:
        if row.get("intended_use") != "evaluation_only" or row.get("training_eligible") is not False:
            raise SystemExit("training isolation marker mismatch")
        if row.get("redistribution_authorized") is not False or row.get("role") != "evaluation":
            raise SystemExit("rights or role marker mismatch")
        bit_width = int(row["bit_width"])
        if bit_width not in counts or row.get("endianness") != "little":
            raise SystemExit("type or endianness mismatch")
        if bool(row["benchmark_eligible"]) == bool(row["is_constant"]):
            raise SystemExit("constant-plane benchmark eligibility mismatch")
        current = args.eval_root / row["sample_path"]
        fresh = args.fresh_root / row["sample_path"]
        expected_size = int(row["sample_size_bytes"])
        if current.stat().st_size != expected_size or fresh.stat().st_size != expected_size:
            raise SystemExit(f"sample size mismatch: {row['sample_path']}")
        if digests(current)[1] != row["sha256"] or digests(fresh)[1] != row["sha256"]:
            raise SystemExit(f"fresh decode mismatch: {row['sample_path']}")
        counts[bit_width] += 1
        constants[bit_width] += bool(row["is_constant"])
        total_bytes += expected_size
        total_values += int(row["value_count"])

    if counts != {16: 77, 32: 44} or constants != {16: 9, 32: 1}:
        raise SystemExit(f"sample classification mismatch: {counts=} {constants=}")
    if total_bytes != 2_737_152_000 or total_values != 1_003_622_400:
        raise SystemExit(f"aggregate mismatch: {total_bytes=} {total_values=}")

    built_stats = sorted((args.eval_root / "filtered").glob("decode_*.tsv"))
    fresh_stats = sorted((args.fresh_root / "filtered").glob("decode_*.tsv"))
    if [path.name for path in built_stats] != [path.name for path in fresh_stats]:
        raise SystemExit("fresh decode statistics inventory mismatch")
    for built, fresh in zip(built_stats, fresh_stats, strict=True):
        if built.read_bytes() != fresh.read_bytes():
            raise SystemExit(f"fresh decode statistics mismatch: {built.name}")

    print(
        "verified evaluation dataset=aras_blender_openexr_eval "
        "samples=121 benchmark_eligible=111 values=1003622400 bytes=2737152000"
    )


if __name__ == "__main__":
    main()
