#!/usr/bin/env python3
"""Semantic validation of downloaded BATSE CONT files (used by download.sh).

Modes:
  inventory SOURCES                      check the pinned sources.tsv itself
  file SOURCES TJD PATH                  validate one downloaded file
  summary SOURCES DOWNLOAD_DIR           re-validate all files, write inventory

Per-file checks: exact pinned size; exact S3 ETag (content MD5 for single-part
objects, MD5 of the two 8 MiB-part MD5s plus "-2" for multipart objects);
pinned SHA-256 when sources.tsv carries one; complete gzip stream; FITS
primary identity (COMPTON GRO / BATSE / BATSE_CONT / TJD); BATSE_CNTS schema
(found by EXTNAME) with NAXIS2 equal to the pinned row count.
"""
from __future__ import annotations

import csv
import gzip
import hashlib
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from batse_cont import ROW_FLOOR, locate_counts  # noqa: E402

EXPECTED_DAYS = 50
EXPECTED_BYTES = 377_862_785
EXPECTED_ROWS = 1_496_816
PART_SIZE = 8 * 1024 * 1024
KEY_RE = re.compile(r"compton/data/batse/daily/(\d{5})_(\d{5})/(\d{5})_(\d{5})/dds(\d{5})/cont_(\d{5})\.fits\.gz")


def load_sources(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    if len(rows) != EXPECTED_DAYS:
        raise SystemExit(f"sources.tsv has {len(rows)} days, expected {EXPECTED_DAYS}")
    if sum(int(row["bytes"]) for row in rows) != EXPECTED_BYTES:
        raise SystemExit("sources.tsv aggregate size changed")
    if sum(int(row["rows"]) for row in rows) != EXPECTED_ROWS:
        raise SystemExit("sources.tsv aggregate row count changed")
    tjds = [int(row["tjd"]) for row in rows]
    if tjds != sorted(set(tjds)):
        raise SystemExit("sources.tsv TJDs must be unique and ascending")
    for row in rows:
        match = KEY_RE.fullmatch(row["key"])
        if not match or int(match.group(5)) != int(row["tjd"]) or int(match.group(6)) != int(row["tjd"]):
            raise SystemExit(f"unsafe or inconsistent key for TJD {row['tjd']}: {row['key']}")
        if not re.fullmatch(r"[0-9a-f]{32}(-2)?", row["s3_etag"]):
            raise SystemExit(f"unverifiable ETag for TJD {row['tjd']}")
        multipart = row["s3_etag"].endswith("-2")
        if multipart != (int(row["bytes"]) > PART_SIZE) or int(row["bytes"]) > 2 * PART_SIZE:
            raise SystemExit(f"ETag form does not match size for TJD {row['tjd']}")
        if int(row["rows"]) < ROW_FLOOR:
            raise SystemExit(f"pinned day below row floor: TJD {row['tjd']}")
        if row.get("sha256") and not re.fullmatch(r"[0-9a-f]{64}", row["sha256"]):
            raise SystemExit(f"malformed pinned SHA-256 for TJD {row['tjd']}")
    return rows


def digests(path: Path) -> tuple[str, str]:
    sha = hashlib.sha256()
    whole = hashlib.md5()
    part_md5s: list[bytes] = []
    with path.open("rb") as handle:
        while True:
            part = handle.read(PART_SIZE)
            if not part:
                break
            sha.update(part)
            whole.update(part)
            part_md5s.append(hashlib.md5(part).digest())
    if len(part_md5s) <= 1:
        etag = whole.hexdigest()
    else:
        etag = hashlib.md5(b"".join(part_md5s)).hexdigest() + f"-{len(part_md5s)}"
    return etag, sha.hexdigest()


def validate_file(row: dict[str, str], path: Path) -> dict[str, object]:
    tjd = int(row["tjd"])
    size = path.stat().st_size
    if size != int(row["bytes"]):
        raise SystemExit(f"TJD {tjd}: size {size} != pinned {row['bytes']}")
    etag, sha256 = digests(path)
    if etag != row["s3_etag"]:
        raise SystemExit(f"TJD {tjd}: ETag {etag} != pinned {row['s3_etag']}")
    if row.get("sha256") and sha256 != row["sha256"]:
        raise SystemExit(f"TJD {tjd}: SHA-256 {sha256} != pinned {row['sha256']}")
    with gzip.open(path, "rb") as handle:
        def skip(count: int) -> None:
            if count and len(handle.read(count)) != count:
                raise SystemExit(f"TJD {tjd}: truncated HDU data")

        info = locate_counts(handle.read, skip, tjd)
        if int(info["rows"]) != int(row["rows"]):
            raise SystemExit(f"TJD {tjd}: NAXIS2 {info['rows']} != pinned {row['rows']}")
        while handle.read(1 << 20):  # full gzip CRC/length check
            pass
    return {
        "tjd": tjd,
        "key": row["key"],
        "filename": Path(row["key"]).name,
        "bytes": size,
        "s3_etag": etag,
        "sha256": sha256,
        "rows": int(info["rows"]),
        "calib_rows": info["calib_rows"],
        "strt_day": info["strt_day"],
    }


def main() -> None:
    mode = sys.argv[1]
    rows = load_sources(Path(sys.argv[2]))
    if mode == "inventory":
        print(f"source_inventory=ok days={len(rows)} bytes={EXPECTED_BYTES} rows={EXPECTED_ROWS}")
    elif mode == "file":
        tjd = int(sys.argv[3])
        row = next(item for item in rows if int(item["tjd"]) == tjd)
        record = validate_file(row, Path(sys.argv[4]))
        print(f"validated tjd={tjd} rows={record['rows']} etag={record['s3_etag']} sha256={record['sha256']}")
    elif mode == "summary":
        download_dir = Path(sys.argv[3])
        records = [validate_file(row, download_dir / Path(row["key"]).name) for row in rows]
        expected = {Path(row["key"]).name for row in rows}
        unexpected = sorted(p.name for p in download_dir.glob("*.fits.gz") if p.name not in expected)
        if unexpected:
            raise SystemExit(f"unexpected files in download dir: {unexpected}")
        payload = {
            "dataset_id": "nasa_heasarc_batse_cont_counts_i16",
            "days": len(records),
            "source_bytes": sum(int(r["bytes"]) for r in records),
            "rows": sum(int(r["rows"]) for r in records),
            "records": records,
        }
        (download_dir / "download_inventory.json").write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"download_inventory=ok days={payload['days']} bytes={payload['source_bytes']} rows={payload['rows']}")
    else:
        raise SystemExit(f"unknown mode {mode}")


if __name__ == "__main__":
    main()
