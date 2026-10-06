#!/usr/bin/env python3
"""Semantic validation of downloaded GBM TTE files (used by download.sh).

Modes:
  inventory SOURCES                      check the pinned sources.tsv itself
  file SOURCES BURST PATH                validate one downloaded file
  summary SOURCES DOWNLOAD_DIR           re-validate all files, write inventory

Per-file checks: exact pinned size; exact S3 ETag (content MD5 for
single-part objects, MD5 of the 8 MiB-part MD5s plus "-N" for multipart
objects, with N = ceil(size / 8 MiB)); full FITS walk (gbm_tte.walk_file with
decode=False): HDU sequence PRIMARY/EBOUNDS/EVENTS/GTI, primary identity
(GLAST/GBM/TTE/'GBM PHOTON LIST', DETNAM matching the file's detector,
FILENAME), EVENTS schema (TIME 1D s with TZERO1 = TRIGTIME, PHA 1I,
NAXIS1 = 10, DETCHANS 128), every present FITS CHECKSUM/DATASUM (both
required on EVENTS), zero padding, no trailing bytes; NAXIS2 and TZERO1 equal
the pinned values.
"""
from __future__ import annotations

import csv
import hashlib
import json
import math
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from gbm_tte import ROW_FLOOR, walk_file  # noqa: E402

DATASET_ID = "fermi_gbm_tte_nai_photon_arrival_times_f64"
EXPECTED_BURSTS = 60
EXPECTED_BYTES = 452_992_320
EXPECTED_ROWS = 45_118_967
PART_SIZE = 8 * 1024 * 1024
KEY_RE = re.compile(r"fermi/data/gbm/bursts/(\d{4})/(bn\d{9})/current/glg_tte_(n[0-9ab])_(bn\d{9})_v(\d{2})\.fit")


def load_sources(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    if len(rows) != EXPECTED_BURSTS:
        raise SystemExit(f"sources.tsv has {len(rows)} bursts, expected {EXPECTED_BURSTS}")
    if sum(int(row["bytes"]) for row in rows) != EXPECTED_BYTES:
        raise SystemExit("sources.tsv aggregate size changed")
    if sum(int(row["rows"]) for row in rows) != EXPECTED_ROWS:
        raise SystemExit("sources.tsv aggregate row count changed")
    bursts = [row["burst"] for row in rows]
    if bursts != sorted(set(bursts)):
        raise SystemExit("sources.tsv bursts must be unique and ascending")
    for row in rows:
        match = KEY_RE.fullmatch(row["key"])
        if not match or match.group(1) != row["year"] or match.group(2) != row["burst"] \
                or match.group(4) != row["burst"] or match.group(3) != row["detector"] \
                or int(match.group(5)) != int(row["version"]) or row["burst"][2:4] != row["year"][2:]:
            raise SystemExit(f"unsafe or inconsistent key for {row['burst']}: {row['key']}")
        size = int(row["bytes"])
        etag_match = re.fullmatch(r"[0-9a-f]{32}(?:-(\d+))?", row["s3_etag"])
        if not etag_match:
            raise SystemExit(f"unverifiable ETag for {row['burst']}")
        parts = int(etag_match.group(1) or 1)
        expected_parts = max(1, math.ceil(size / PART_SIZE))
        if (etag_match.group(1) is None) != (size <= PART_SIZE) or (etag_match.group(1) and parts != expected_parts):
            raise SystemExit(f"ETag form does not match size for {row['burst']}")
        if int(row["rows"]) < ROW_FLOOR:
            raise SystemExit(f"pinned burst below row floor: {row['burst']}")
        float(row["tzero1"])
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
    burst = row["burst"]
    size = path.stat().st_size
    if size != int(row["bytes"]):
        raise SystemExit(f"{burst}: size {size} != pinned {row['bytes']}")
    etag, sha256 = digests(path)
    if etag != row["s3_etag"]:
        raise SystemExit(f"{burst}: ETag {etag} != pinned {row['s3_etag']}")
    filename = Path(row["key"]).name
    try:
        info = walk_file(path, filename, row["detector"], output=None, decode=False)
    except ValueError as error:
        raise SystemExit(f"{burst}: FITS validation failed: {error}")
    if int(info["rows"]) != int(row["rows"]):
        raise SystemExit(f"{burst}: NAXIS2 {info['rows']} != pinned {row['rows']}")
    if repr(info["tzero1"]) != row["tzero1"]:
        raise SystemExit(f"{burst}: TZERO1 {info['tzero1']!r} != pinned {row['tzero1']}")
    return {
        "burst": burst,
        "key": row["key"],
        "filename": filename,
        "detector": row["detector"],
        "bytes": size,
        "s3_etag": etag,
        "sha256": sha256,
        "rows": int(info["rows"]),
        "tzero1": info["tzero1"],
        "object": info["object"],
        "creator": info["creator"],
        "file_date": info["file_date"],
        "checksums_verified": info["checksums_verified"],
        "datasums_verified": info["datasums_verified"],
        "gti_intervals": info["gti_intervals"],
    }


def main() -> None:
    mode = sys.argv[1]
    rows = load_sources(Path(sys.argv[2]))
    if mode == "inventory":
        print(f"source_inventory=ok bursts={len(rows)} bytes={EXPECTED_BYTES} rows={EXPECTED_ROWS}")
    elif mode == "file":
        burst = sys.argv[3]
        row = next(item for item in rows if item["burst"] == burst)
        record = validate_file(row, Path(sys.argv[4]))
        print(f"validated {burst} {record['detector']} rows={record['rows']} etag={record['s3_etag']} "
              f"checksums={record['checksums_verified']} datasums={record['datasums_verified']}")
    elif mode == "summary":
        download_dir = Path(sys.argv[3])
        records = [validate_file(row, download_dir / Path(row["key"]).name) for row in rows]
        expected = {Path(row["key"]).name for row in rows}
        unexpected = sorted(p.name for p in download_dir.glob("*.fit") if p.name not in expected)
        if unexpected:
            raise SystemExit(f"unexpected files in download dir: {unexpected}")
        payload = {
            "dataset_id": DATASET_ID,
            "bursts": len(records),
            "source_bytes": sum(int(r["bytes"]) for r in records),
            "rows": sum(int(r["rows"]) for r in records),
            "records": records,
        }
        (download_dir / "download_inventory.json").write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n",
                                                              encoding="utf-8")
        print(f"download_inventory=ok bursts={payload['bursts']} bytes={payload['source_bytes']} rows={payload['rows']}")
    else:
        raise SystemExit(f"unknown mode {mode}")


if __name__ == "__main__":
    main()
