#!/usr/bin/env python3
"""Semantic validation of downloaded LAT weekly photon files (used by download.sh).

Modes:
  inventory SOURCES                 check the pinned sources.tsv itself
  file SOURCES WEEK PATH            validate one downloaded file
  summary SOURCES DOWNLOAD_DIR      re-validate all files, write download_inventory.json

Per-file checks: exact pinned size; full FITS walk (lat_events.walk_file with
decode=False): HDU sequence PRIMARY/EVENTS/GTI, primary identity
(GLAST/LAT, PROC_VER 305), the full 23-column EVENTS schema with TFORM-derived
offsets, PASS_VER P8R3 and the SOURCE-class data-subspace keywords, every
HDU's FITS CHECKSUM and (on EVENTS and GTI) DATASUM, zero padding, no trailing
bytes; NAXIS2, EVENTS DATASUM, TSTART, TSTOP and GTI row count equal the pinned
values. HEASARC serves no content hash, so the FITS checksums plus the pinned
DATASUM are the content check; the SHA-256 of every accepted file is recorded
in download_inventory.json and re-checked by build.sh.
"""
from __future__ import annotations

import csv
import hashlib
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lat_events import ROW_FLOOR, walk_file  # noqa: E402

DATASET_ID = "fermi_lat_weekly_photon_events_f32"
EXPECTED_FILES = 18
EXPECTED_BYTES = 3_507_436_800
EXPECTED_ROWS = 35_784_618
NAME_RE = re.compile(r"lat_photon_weekly_w(\d{3})_p305_v001\.fits")


def load_sources(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    if len(rows) != EXPECTED_FILES:
        raise SystemExit(f"sources.tsv has {len(rows)} files, expected {EXPECTED_FILES}")
    if sum(int(row["bytes"]) for row in rows) != EXPECTED_BYTES:
        raise SystemExit("sources.tsv aggregate size changed")
    if sum(int(row["rows"]) for row in rows) != EXPECTED_ROWS:
        raise SystemExit("sources.tsv aggregate row count changed")
    weeks = [int(row["week"]) for row in rows]
    if weeks != sorted(set(weeks)):
        raise SystemExit("sources.tsv weeks must be unique and ascending")
    for row in rows:
        match = NAME_RE.fullmatch(row["filename"])
        if not match or int(match.group(1)) != int(row["week"]):
            raise SystemExit(f"unsafe or inconsistent filename {row['filename']!r}")
        if int(row["rows"]) < ROW_FLOOR or not row["events_datasum"].isdigit():
            raise SystemExit(f"bad pinned row count / DATASUM for w{row['week']}")
        float(row["tstart"])
        float(row["tstop"])
    return rows


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 22), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_file(row: dict[str, str], path: Path) -> dict[str, object]:
    week = row["week"]
    size = path.stat().st_size
    if size != int(row["bytes"]):
        raise SystemExit(f"w{week}: size {size} != pinned {row['bytes']}")
    try:
        info = walk_file(path, row["filename"], decode=False)
    except ValueError as error:
        raise SystemExit(f"w{week}: FITS validation failed: {error}")
    checks = {
        "rows": (int(info["rows"]), int(row["rows"])),
        "events_datasum": (info["events_datasum"], row["events_datasum"]),
        "tstart": (repr(info["tstart"]), row["tstart"]),
        "tstop": (repr(info["tstop"]), row["tstop"]),
        "gti_rows": (int(info["gti_intervals"]), int(row["gti_rows"])),
    }
    for key, (actual, pinned) in checks.items():
        if actual != pinned:
            raise SystemExit(f"w{week}: {key} {actual} != pinned {pinned}")
    return {
        "week": week,
        "filename": row["filename"],
        "bytes": size,
        "sha256": sha256_file(path),
        "rows": int(info["rows"]),
        "events_datasum": info["events_datasum"],
        "tstart": info["tstart"],
        "tstop": info["tstop"],
        "date_obs": info["date_obs"],
        "date_end": info["date_end"],
        "gti_intervals": info["gti_intervals"],
        "gti_ontime": info["gti_ontime"],
        "checksums_verified": info["checksums_verified"],
        "datasums_verified": info["datasums_verified"],
    }


def main() -> None:
    mode = sys.argv[1]
    rows = load_sources(Path(sys.argv[2]))
    if mode == "inventory":
        print(f"source_inventory=ok files={len(rows)} bytes={EXPECTED_BYTES} rows={EXPECTED_ROWS}")
    elif mode == "file":
        row = next(item for item in rows if item["week"] == sys.argv[3])
        record = validate_file(row, Path(sys.argv[4]))
        print(f"validated w{record['week']} rows={record['rows']} checksums={record['checksums_verified']} "
              f"datasums={record['datasums_verified']} sha256={record['sha256']}")
    elif mode == "summary":
        download_dir = Path(sys.argv[3])
        records = [validate_file(row, download_dir / row["filename"]) for row in rows]
        expected = {row["filename"] for row in rows}
        unexpected = sorted(p.name for p in download_dir.glob("*.fits") if p.name not in expected)
        if unexpected:
            raise SystemExit(f"unexpected files in download dir: {unexpected}")
        payload = {
            "dataset_id": DATASET_ID,
            "files": len(records),
            "source_bytes": sum(int(r["bytes"]) for r in records),
            "rows": sum(int(r["rows"]) for r in records),
            "records": records,
        }
        (download_dir / "download_inventory.json").write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n",
                                                              encoding="utf-8")
        print(f"download_inventory=ok files={payload['files']} bytes={payload['source_bytes']} rows={payload['rows']}")
    else:
        raise SystemExit(f"unknown mode {mode}")


if __name__ == "__main__":
    main()
