#!/usr/bin/env python3
"""Semantic validation of the downloaded Phase I LAZ tiles.

usage: validate_downloads.py TILES_TSV DOWNLOAD_DIR REPO_ROOT

Per tile: exact byte size, S3 ETag (plain MD5, or the S3 multipart MD5 with
8 MiB parts for "-N" ETags), pinned sha256 when the TSV has one, and header
layout: LAS 1.2, point data record format 1 with the LASzip compression bit,
record length 28, point count equal to the pinned count, LASzip compressor 2
(point-wise chunked) with items POINT10 v2 + GPSTIME11 v2. Writes
download_inventory.json with the observed sha256 of every tile.
"""
from __future__ import annotations

import csv
import hashlib
import json
import sys
from pathlib import Path

PART = 8 * 1024 * 1024


def main() -> None:
    tiles_tsv, download_dir, repo_root = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
    sys.path.insert(0, str(repo_root / "tools" / "laz"))
    import laszip  # noqa: E402

    with tiles_tsv.open(newline="") as fh:
        tiles = list(csv.DictReader(fh, delimiter="\t"))
    if not tiles:
        raise SystemExit("empty tile list")
    records = []
    total = 0
    for t in tiles:
        key = t["key"]
        if not key.startswith("lidar/phase-1/laz/") or not key.endswith(".laz"):
            raise SystemExit(f"key outside lidar/phase-1/laz/: {key}")
        path = download_dir / "laz" / Path(key).name
        if not path.is_file():
            raise SystemExit(f"missing download {path}")
        size = path.stat().st_size
        if size != int(t["size_bytes"]):
            raise SystemExit(f"{path.name}: size {size} != pinned {t['size_bytes']}")
        sha = hashlib.sha256()
        whole_md5 = hashlib.md5()
        part_md5s = []
        with path.open("rb") as fh:
            while True:
                block = fh.read(PART)
                if not block:
                    break
                sha.update(block)
                whole_md5.update(block)
                part_md5s.append(hashlib.md5(block).digest())
        etag = t["etag"].strip('"')
        if "-" in etag:
            parts = int(etag.split("-", 1)[1])
            observed = hashlib.md5(b"".join(part_md5s)).hexdigest() + f"-{len(part_md5s)}"
            if len(part_md5s) != parts or observed != etag:
                raise SystemExit(f"{path.name}: multipart ETag mismatch {observed} != {etag}")
        elif whole_md5.hexdigest() != etag:
            raise SystemExit(f"{path.name}: MD5 {whole_md5.hexdigest()} != ETag {etag}")
        digest = sha.hexdigest()
        if t.get("sha256") and t["sha256"] != digest:
            raise SystemExit(f"{path.name}: sha256 {digest} != pinned {t['sha256']}")

        hdr = laszip.read_header(str(path))
        lz = hdr["laszip"]
        items = [(i["name"], i["size"], i["version"]) for i in (lz or {}).get("items", [])]
        problems = []
        if hdr["version"] != "1.2":
            problems.append(f"LAS version {hdr['version']}")
        if hdr["point_format"] != 1 or not hdr["compressed"]:
            problems.append(f"point format raw {hdr['point_format_raw']}")
        if hdr["point_record_length"] != 28:
            problems.append(f"record length {hdr['point_record_length']}")
        if hdr["point_count"] != int(t["point_count"]):
            problems.append(f"point count {hdr['point_count']} != pinned {t['point_count']}")
        if lz is None or lz["compressor"] != 2:
            problems.append(f"LASzip compressor {None if lz is None else lz['compressor']}")
        if items != [("POINT10", 20, 2), ("GPSTIME11", 8, 2)]:
            problems.append(f"LASzip items {items}")
        if problems:
            raise SystemExit(f"{path.name}: unexpected layout: {'; '.join(problems)}")
        total += size
        records.append({
            "key": key,
            "local_path": f"laz/{path.name}",
            "size_bytes": size,
            "etag": etag,
            "sha256": digest,
            "point_count": hdr["point_count"],
            "generating_software": hdr["generating_software"],
            "laszip_version": lz["version"],
            "laszip_chunk_size": lz["chunk_size"],
        })
        print(f"ok {path.name} bytes={size} points={hdr['point_count']} sha256={digest[:16]}", flush=True)
    inventory = {"tile_count": len(records), "source_bytes": total, "records": records}
    (download_dir / "download_inventory.json").write_text(json.dumps(inventory, indent=2) + "\n")
    print(f"semantic_validation=ok tiles={len(records)} source_bytes={total}")


if __name__ == "__main__":
    main()
