#!/usr/bin/env python3
"""Deterministic day selection for the BATSE CONT recipe (discovery only).

Targets: N_DAYS evenly spaced TJD positions over the full CONT inventory span,
t_k = tjd_min + (k + 0.5) * (tjd_max - tjd_min + 1) / N_DAYS.
For each target, candidate days are ordered by (|tjd - t_k|, tjd); candidates
must clear SIZE_FLOOR (a cheap listing prefilter) and must not already be
chosen. The first candidate whose BATSE_CNTS header (read from a 64 KiB range
GET of the gzip file, fetched with curl) validates and has NAXIS2 >= ROW_FLOOR
is pinned. Partial days are skipped, never padded or merged.

S3 ETags are content MD5s for single-part objects (< 8 MiB) and the composite
MD5-of-part-MD5s with "-2" suffix for the 2-part (8 MiB part size) objects;
download.sh verifies both forms exactly.
"""
from __future__ import annotations

import argparse
import csv
import re
import subprocess
import sys
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from batse_cont import ROW_FLOOR, Truncated, probe_bytes  # noqa: E402

N_DAYS = 50
SIZE_FLOOR = 5_000_000
BASE = "https://nasa-heasarc.s3.amazonaws.com/"
PROBE_BYTES = 65_536


def fetch_head(key: str, cache: Path, size: int) -> bytes:
    if cache.is_file() and cache.stat().st_size == size:
        return cache.read_bytes()
    subprocess.run(
        ["curl", "-fsS", "--retry", "5", "--retry-delay", "3", "--max-time", "120",
         "-r", f"0-{size - 1}", "-o", str(cache), BASE + key],
        check=True,
    )
    data = cache.read_bytes()
    if len(data) != size:
        raise SystemExit(f"range probe for {key} returned {len(data)} bytes")
    return data


def probe(key: str, tjd: int, heads_dir: Path) -> dict[str, object]:
    size = PROBE_BYTES
    while True:
        raw = fetch_head(key, heads_dir / f"{tjd:05d}_{size}.gz", size)
        prefix = zlib.decompressobj(16 + zlib.MAX_WBITS).decompress(raw)
        try:
            return probe_bytes(prefix, tjd)
        except Truncated:
            if size >= 1 << 20:
                raise
            size *= 4


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument("--heads-dir", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    args.heads_dir.mkdir(parents=True, exist_ok=True)
    with args.inventory.open(encoding="utf-8", newline="") as handle:
        inventory = [
            {"tjd": int(row["tjd"]), "key": row["key"], "bytes": int(row["bytes"]), "etag": row["etag"]}
            for row in csv.DictReader(handle, delimiter="\t")
        ]
    tjd_min = min(row["tjd"] for row in inventory)
    tjd_max = max(row["tjd"] for row in inventory)
    eligible = [row for row in inventory if row["bytes"] >= SIZE_FLOOR]
    print(f"inventory={len(inventory)} span={tjd_min}..{tjd_max} eligible_size>={SIZE_FLOOR}: {len(eligible)}")
    chosen: dict[int, dict[str, object]] = {}
    rejected: list[str] = []
    for k in range(N_DAYS):
        target = tjd_min + (k + 0.5) * (tjd_max - tjd_min + 1) / N_DAYS
        for row in sorted(eligible, key=lambda item: (abs(item["tjd"] - target), item["tjd"])):
            if row["tjd"] in chosen:
                continue
            if not re.fullmatch(r"[0-9a-f]{32}(-2)?", row["etag"]):
                rejected.append(f"{row['tjd']}:unverifiable_etag={row['etag']}")
                continue
            info = probe(row["key"], row["tjd"], args.heads_dir)
            if int(info["rows"]) < ROW_FLOOR:
                rejected.append(f"{row['tjd']}:rows={info['rows']}")
                continue
            chosen[row["tjd"]] = {**row, "rows": info["rows"], "target": round(target, 2)}
            break
        else:
            raise SystemExit(f"no eligible day for target {target}")
    with args.out.open("w", encoding="utf-8") as handle:
        handle.write("tjd\tkey\tbytes\ts3_etag\trows\tsha256\n")
        for tjd in sorted(chosen):
            row = chosen[tjd]
            handle.write(f"{tjd}\t{row['key']}\t{row['bytes']}\t{row['etag']}\t{row['rows']}\t\n")
    total_rows = sum(int(row["rows"]) for row in chosen.values())
    print(
        f"selected={len(chosen)} bytes={sum(row['bytes'] for row in chosen.values())} rows={total_rows} "
        f"output_bytes={total_rows * 256} rejected={rejected}"
    )


if __name__ == "__main__":
    main()
