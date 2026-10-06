#!/usr/bin/env python3
"""Validate the downloaded TPEHG DB files and write download_inventory.json.

Rejects the download unless every RECORDS entry has a .hea/.dat pair whose
SHA-256 matches the pinned official SHA256SUMS.txt, every header has the
expected 12-signal format-16 layout, and every .dat holds exactly
frames * 24 bytes. Files with a checksum mismatch are deleted so that a re-run
of download.sh fetches them again.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))

from tpehg_common import (  # noqa: E402
    BYTES_PER_FRAME,
    DATASET_ID,
    EXPECTED_DAT_BYTES,
    EXPECTED_HEA_BYTES,
    EXPECTED_RECORDS,
    EXPECTED_SHA256_ENTRIES,
    EXPECTED_TOTAL_FRAMES,
    SHA256SUMS_SHA256,
    parse_header,
    read_records,
    read_sha256sums,
    sha256_file,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--download-dir", type=Path, required=True)
    args = parser.parse_args()
    root: Path = args.download_dir

    sums_path = root / "SHA256SUMS.txt"
    if sha256_file(sums_path) != SHA256SUMS_SHA256:
        raise SystemExit("SHA256SUMS.txt does not match the pinned checksum")
    sums = read_sha256sums(sums_path)
    if len(sums) != EXPECTED_SHA256_ENTRIES:
        raise SystemExit(f"SHA256SUMS.txt entry count {len(sums)} != {EXPECTED_SHA256_ENTRIES}")
    if sha256_file(root / "RECORDS") != sums.get("RECORDS"):
        raise SystemExit("RECORDS does not match SHA256SUMS.txt")
    record_ids = read_records(root / "RECORDS")
    if len(record_ids) != EXPECTED_RECORDS:
        raise SystemExit(f"RECORDS count {len(record_ids)} != {EXPECTED_RECORDS}")
    listed = {name for name in sums if name.startswith("tpehgdb/")}
    expected_listed = {f"tpehgdb/{rid}{suffix}" for rid in record_ids for suffix in (".hea", ".dat")}
    if listed != expected_listed:
        raise SystemExit("SHA256SUMS.txt record files differ from RECORDS")

    bad: list[str] = []
    records = []
    for record_id in record_ids:
        item: dict[str, object] = {"record_id": record_id}
        for kind, suffix in (("header", ".hea"), ("data", ".dat")):
            relative = f"tpehgdb/{record_id}{suffix}"
            path = root / relative
            if not path.is_file():
                bad.append(f"missing {relative}")
                continue
            actual = sha256_file(path)
            if actual != sums[relative]:
                bad.append(f"sha256 mismatch {relative}")
                path.unlink()
                continue
            item[f"{kind}_file"] = relative
            item[f"{kind}_bytes"] = path.stat().st_size
            item[f"{kind}_sha256"] = actual
        if "header_file" in item and "data_file" in item:
            header = parse_header(root / str(item["header_file"]), record_id)
            frames = int(header["frames"])
            if int(item["data_bytes"]) != frames * BYTES_PER_FRAME:
                raise SystemExit(f"{record_id}: .dat size {item['data_bytes']} != frames*24 ({frames * BYTES_PER_FRAME})")
            item["frames"] = frames
            item["sampling_frequency_header"] = header["frequency"]
        records.append(item)
    if bad:
        for message in bad[:20]:
            print(message, file=sys.stderr)
        raise SystemExit(f"{len(bad)} invalid or missing files; corrupt files were removed, re-run download.sh")

    dat_bytes = sum(int(item["data_bytes"]) for item in records)
    hea_bytes = sum(int(item["header_bytes"]) for item in records)
    frames = sum(int(item["frames"]) for item in records)
    if dat_bytes != EXPECTED_DAT_BYTES:
        raise SystemExit(f"aggregate .dat bytes {dat_bytes} != {EXPECTED_DAT_BYTES}")
    if hea_bytes != EXPECTED_HEA_BYTES:
        raise SystemExit(f"aggregate .hea bytes {hea_bytes} != {EXPECTED_HEA_BYTES}")
    if frames != EXPECTED_TOTAL_FRAMES:
        raise SystemExit(f"aggregate frames {frames} != {EXPECTED_TOTAL_FRAMES}")

    inventory = {
        "dataset_id": DATASET_ID,
        "source": "https://physionet-open.s3.amazonaws.com/tpehgdb/1.0.1/",
        "sha256sums_sha256": SHA256SUMS_SHA256,
        "record_count": len(records),
        "data_bytes": dat_bytes,
        "header_bytes": hea_bytes,
        "total_frames": frames,
        "records": records,
    }
    out = root / "download_inventory.json"
    tmp = out.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(inventory, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(out)
    print(f"validated records={len(records)} data_bytes={dat_bytes} header_bytes={hea_bytes} frames={frames}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
