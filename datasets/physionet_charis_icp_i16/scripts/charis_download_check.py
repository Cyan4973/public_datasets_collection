#!/usr/bin/env python3
"""Semantic validation of the CHARIS 1.0.0 downloads; writes download_inventory.json.

Checks, in order:
- SHA256SUMS.txt lists exactly RECORDS plus the 13 .hea/.dat pairs, with the
  pinned hashes;
- RECORDS names exactly charis1..charis13 (upstream order starts at charis10);
- every header declares 3 signals ABP/ECG/ICP, WFDB format 16, 50 Hz, and the
  pinned sample count, with .dat size = nsamp * 3 signals * 2 bytes;
- every file's SHA-256 matches SHA256SUMS.txt (a mismatching .dat is deleted
  so the next download.sh run refetches it).
The .dat files of the excluded records (charis9, charis10; see charis_pins.py)
are not downloaded: their SHA256SUMS entries and headers are still checked,
and any copy left over from an earlier run is ignored.
Header comment lines are never copied anywhere.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import charis_pins as pins  # noqa: E402


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--download-dir", type=Path, required=True)
    args = parser.parse_args()
    root: Path = args.download_dir

    sums_path = root / "SHA256SUMS.txt"
    if sha256_file(sums_path) != pins.SHA256SUMS_SHA256:
        raise SystemExit("SHA256SUMS.txt differs from the pinned release checksum list")
    official: dict[str, str] = {}
    for line in sums_path.read_text(encoding="ascii").splitlines():
        if not line.strip():
            continue
        match = re.fullmatch(r"([0-9a-f]{64}) +(\S+)", line.strip())
        if not match:
            raise SystemExit(f"unparseable SHA256SUMS line: {line!r}")
        official[match.group(2)] = match.group(1)
    expected_names = {"RECORDS"} | {
        f"{row['record_id']}{suffix}" for row in pins.record_rows() for suffix in (".hea", ".dat")
    }
    if set(official) != expected_names:
        raise SystemExit(f"SHA256SUMS inventory changed: {sorted(set(official) ^ expected_names)}")
    if official["RECORDS"] != pins.RECORDS_SHA256:
        raise SystemExit("RECORDS checksum differs from pin")

    upstream_order = [line.strip() for line in (root / "RECORDS").read_text(encoding="ascii").splitlines() if line.strip()]
    if len(upstream_order) != 13 or set(upstream_order) != pins.EXPECTED_RECORD_SET:
        raise SystemExit(f"RECORDS lists unexpected records: {upstream_order}")
    if sha256_file(root / "RECORDS") != official["RECORDS"]:
        raise SystemExit("RECORDS SHA-256 mismatch")

    inventory = []
    excluded = []
    for row in pins.record_rows():
        record = row["record_id"]
        hea = root / f"{record}.hea"
        dat = root / f"{record}.dat"
        if official[hea.name] != row["hea_sha256"] or official[dat.name] != row["dat_sha256"]:
            raise SystemExit(f"SHA256SUMS entry for {record} differs from pin")
        if hea.stat().st_size != row["hea_bytes"] or sha256_file(hea) != row["hea_sha256"]:
            raise SystemExit(f"header {hea.name} size/SHA-256 mismatch")
        lines = [
            line for line in hea.read_text(encoding="ascii").splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        ]
        head = lines[0].split()
        if head[:3] != [record, "3", str(pins.SAMPLING_HZ)] or int(head[3]) != row["nsamp"]:
            raise SystemExit(f"header {hea.name}: record line changed: {lines[0]!r}")
        if len(lines) != 4:
            raise SystemExit(f"header {hea.name}: expected 3 signal lines")
        for index, name in enumerate(pins.SIGNALS):
            fields = lines[1 + index].split()
            if fields[0] != dat.name or fields[1] != "16" or fields[-1] != name:
                raise SystemExit(f"header {hea.name}: signal {index} is not {name} in format 16")
        if row["excluded"]:
            excluded.append({
                "record_id": record,
                "header_file": hea.name,
                "header_sha256": row["hea_sha256"],
                "reason": pins.EXCLUDED_RECORDS[record],
            })
            print(f"validated header only {record} (excluded, .dat not used)")
            continue
        expected_bytes = row["nsamp"] * 3 * 2
        actual_bytes = dat.stat().st_size
        if actual_bytes != expected_bytes or actual_bytes != row["dat_bytes"]:
            raise SystemExit(f"{dat.name}: size {actual_bytes} != nsamp*6 = {expected_bytes}")
        actual_sha = sha256_file(dat)
        if actual_sha != official[dat.name]:
            dat.unlink()
            raise SystemExit(f"{dat.name}: SHA-256 mismatch; deleted, rerun download.sh")
        inventory.append({
            "record_id": record,
            "header_file": hea.name,
            "header_bytes": row["hea_bytes"],
            "header_sha256": row["hea_sha256"],
            "data_file": dat.name,
            "data_bytes": actual_bytes,
            "data_sha256": actual_sha,
            "nsamp": row["nsamp"],
        })
        print(f"validated {record}: nsamp={row['nsamp']} dat_bytes={actual_bytes}")

    evidence = {}
    for name in ("charisdb_1.0.0_project_page.html", "charisdb_1.0.0_view_license.html"):
        path = root / "license" / name
        if not path.is_file():
            raise SystemExit(f"missing license evidence {name}")
        evidence[name] = {"bytes": path.stat().st_size, "sha256": sha256_file(path)}

    total = sum(item["data_bytes"] for item in inventory)
    if total != pins.EXPECTED_DAT_BYTES:
        raise SystemExit(f"aggregate .dat bytes {total} != {pins.EXPECTED_DAT_BYTES}")
    payload = {
        "dataset_id": pins.DATASET_ID,
        "base_url": pins.BASE_URL,
        "upstream_records_order": upstream_order,
        "records": inventory,
        "excluded_records": excluded,
        "data_bytes_total": total,
        "license_evidence": evidence,
    }
    (root / "download_inventory.json").write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"records={len(inventory)} excluded={len(excluded)} data_bytes_total={total}")


if __name__ == "__main__":
    main()
