#!/usr/bin/env python3
"""Validate the Zenodo record metadata and the .txt volume descriptors that
download.sh fetched, against the pins in volumes.tsv (no network access).

Usage:
  check_metadata.py records     volumes.tsv downloads/<id>/records
  check_metadata.py descriptors volumes.tsv downloads/<id>/descriptors
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

SIDE = 1381
TITLE_STEM = "CT data; freeze cast aerogel as-cast and following compressive strain; upload"
RECORDS = {4761663: "1 of 3", 4764282: "2 of 3", 4766087: "3 of 3"}


def load_volumes(path: Path) -> list[dict]:
    cols = ["strain", "record", "raw_key", "raw_url_key", "raw_bytes", "raw_md5",
            "z_slices", "txt_key", "txt_bytes", "txt_md5", "txt_sha256"]
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        fields = line.split("\t")
        if len(fields) != len(cols):
            raise SystemExit(f"volumes.tsv: bad line {line!r}")
        row = dict(zip(cols, fields))
        for key in ("record", "raw_bytes", "z_slices", "txt_bytes"):
            row[key] = int(row[key])
        rows.append(row)
    if [r["strain"] for r in rows] != [f"{s:02d}" for s in range(0, 55, 5)]:
        raise SystemExit("volumes.tsv must list strain states 00..50 in 5% steps")
    return rows


def check_records(volumes: list[dict], folder: Path) -> None:
    for record_id, part in RECORDS.items():
        record = json.loads((folder / f"{record_id}.json").read_text(encoding="utf-8"))
        if int(record.get("id") or 0) != record_id:
            raise SystemExit(f"{record_id}: unexpected record id {record.get('id')!r}")
        meta = record.get("metadata") or {}
        title = str(meta.get("title") or "")
        if title != f"{TITLE_STEM} {part}":
            raise SystemExit(f"{record_id}: title changed: {title!r}")
        lic = meta.get("license")
        lic_id = str((lic.get("id") if isinstance(lic, dict) else lic) or "").lower()
        if lic_id != "cc-by-4.0":
            raise SystemExit(f"{record_id}: license changed: {lic!r}")
        access = meta.get("access_right") or (record.get("access") or {}).get("record")
        if access not in ("open", "public"):
            raise SystemExit(f"{record_id}: access changed: {access!r}")
        description = str(meta.get("description") or "")
        if "ID15" not in description or "European Synchrotron Radiation Facility" not in description:
            raise SystemExit(f"{record_id}: description no longer names ESRF ID15")
        files = {f.get("key"): f for f in record.get("files") or [] if isinstance(f, dict)}
        for vol in volumes:
            if vol["record"] != record_id:
                continue
            for key, size, md5 in ((vol["raw_key"], vol["raw_bytes"], vol["raw_md5"]),
                                   (vol["txt_key"], vol["txt_bytes"], vol["txt_md5"])):
                item = files.get(key)
                if item is None:
                    raise SystemExit(f"{record_id}: no longer lists {key!r}")
                if int(item.get("size") or -1) != size:
                    raise SystemExit(f"{record_id}/{key}: size {item.get('size')!r} != pinned {size}")
                if str(item.get("checksum") or "").lower() != f"md5:{md5}":
                    raise SystemExit(f"{record_id}/{key}: checksum {item.get('checksum')!r} != md5:{md5}")
        print(f"record_validation=ok record={record_id} license=cc-by-4.0 access={access} title={title!r}")


def check_descriptors(volumes: list[dict], folder: Path) -> None:
    for vol in volumes:
        path = folder / vol["txt_key"]
        data = path.read_bytes()
        if len(data) != vol["txt_bytes"]:
            raise SystemExit(f"{path.name}: {len(data)} bytes != pinned {vol['txt_bytes']}")
        if hashlib.md5(data).hexdigest() != vol["txt_md5"]:
            raise SystemExit(f"{path.name}: md5 mismatch")
        if hashlib.sha256(data).hexdigest() != vol["txt_sha256"]:
            raise SystemExit(f"{path.name}: sha256 mismatch")
        text = data.decode("ascii")
        lattice = re.search(r"(\d+)\s*x\s*(\d+)\s*x\s*(\d+)", text)
        if not lattice:
            raise SystemExit(f"{path.name}: no lattice 'X x Y x Z' in {text!r}")
        nx, ny, nz = map(int, lattice.groups())
        if (nx, ny, nz) != (SIDE, SIDE, vol["z_slices"]):
            raise SystemExit(f"{path.name}: lattice {nx}x{ny}x{nz} != pinned {SIDE}x{SIDE}x{vol['z_slices']}")
        if not re.search(r"\b8\s*bit\b", text, re.IGNORECASE):
            raise SystemExit(f"{path.name}: does not declare 8 bit")
        if not re.search(r"little\s+endian", text, re.IGNORECASE):
            raise SystemExit(f"{path.name}: does not declare little endian")
        if not re.search(r"(?<![\d.])3\.1(?![\d.])", text):
            raise SystemExit(f"{path.name}: does not declare the 3.1 micron voxel size")
        if nx * ny * nz != vol["raw_bytes"]:
            raise SystemExit(f"{path.name}: lattice does not tile pinned {vol['raw_key']} size {vol['raw_bytes']}")
        print(f"descriptor_validation=ok {path.name} -> {vol['raw_key']!r} lattice={nx}x{ny}x{nz} 8bit little-endian 3.1um")


def main() -> int:
    if len(sys.argv) != 4 or sys.argv[1] not in ("records", "descriptors"):
        raise SystemExit(__doc__)
    volumes = load_volumes(Path(sys.argv[2]))
    if sys.argv[1] == "records":
        check_records(volumes, Path(sys.argv[3]))
    else:
        check_descriptors(volumes, Path(sys.argv[3]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
