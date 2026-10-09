#!/usr/bin/env python3
"""Post-download validation for physionet_wearable_exam_stress_e4_acc_i8.

Checks that SHA256SUMS.txt is the pinned release list and names exactly the
30 pinned ACC.csv hashes, re-hashes every local file, checks the two E4 header
rows and the first data row of each ACC.csv, rejects stray files, and writes
download_inventory.json.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

sys.dont_write_bytecode = True  # keep the recipe directory free of __pycache__
sys.path.insert(0, str(Path(__file__).resolve().parent))
import e4acc_pins as pins  # noqa: E402


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def fail(message: str) -> None:
    raise SystemExit(f"download check failed: {message}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--download-dir", type=Path, required=True)
    args = parser.parse_args()
    root = args.download_dir

    sums_path = root / "SHA256SUMS.txt"
    if sha256_file(sums_path) != pins.SHA256SUMS_SHA256:
        fail("SHA256SUMS.txt hash differs from pin")
    listed: dict[str, str] = {}
    for line in sums_path.read_text(encoding="utf-8").splitlines():
        parts = line.split()
        if len(parts) != 2 or not re.fullmatch(r"[0-9a-f]{64}", parts[0]):
            fail(f"malformed SHA256SUMS line {line!r}")
        listed[parts[1]] = parts[0]
    if len(listed) != pins.SHA256SUMS_ENTRIES:
        fail(f"SHA256SUMS lists {len(listed)} entries, expected {pins.SHA256SUMS_ENTRIES}")
    acc_listed = {path for path in listed if path.endswith("/ACC.csv")}
    pinned_paths = {row[2] for row in pins.ACC_FILES}
    if acc_listed != pinned_paths:
        fail(f"SHA256SUMS ACC.csv set differs from pins: {sorted(acc_listed ^ pinned_paths)}")
    if listed.get("LICENSE.txt") != pins.LICENSE_SHA256:
        fail("LICENSE.txt hash in SHA256SUMS differs from pin")

    license_path = root / "LICENSE.txt"
    if license_path.stat().st_size != pins.LICENSE_BYTES or sha256_file(license_path) != pins.LICENSE_SHA256:
        fail("LICENSE.txt size or hash mismatch")

    files = []
    expected_names = set()
    for subject, exam, path, size, sha in pins.ACC_FILES:
        if listed[path] != sha:
            fail(f"{path}: pinned hash differs from SHA256SUMS")
        name = pins.local_name(subject, exam)
        expected_names.add(name)
        local = root / "acc" / name
        if not local.is_file():
            fail(f"missing {local}")
        if local.stat().st_size != size:
            fail(f"{name}: size {local.stat().st_size} != {size}")
        actual = sha256_file(local)
        if actual != sha:
            fail(f"{name}: SHA-256 mismatch")
        with local.open("rb") as fh:
            head = fh.read(4096).split(b"\n")
        if len(head) < 4:
            fail(f"{name}: fewer than three lines")
        start = [field.strip() for field in head[0].split(b",")]
        rate = [field.strip() for field in head[1].split(b",")]
        if len(start) != 3 or len(set(start)) != 1 or not re.fullmatch(rb"[0-9]+\.[0-9]+", start[0]):
            fail(f"{name}: header row 1 is not three equal unix start times: {head[0]!r}")
        if len(rate) != 3 or any(float(value) != float(pins.SAMPLE_RATE_HZ) for value in rate):
            fail(f"{name}: header row 2 is not a {pins.SAMPLE_RATE_HZ} Hz rate row: {head[1]!r}")
        if not re.fullmatch(rb"-?[0-9]{1,3},-?[0-9]{1,3},-?[0-9]{1,3}", head[2]):
            fail(f"{name}: first data row is not three integers: {head[2]!r}")
        files.append({
            "session_id": pins.session_id(subject, exam),
            "subject": subject,
            "exam": exam,
            "release_path": path,
            "local_path": f"acc/{name}",
            "size_bytes": size,
            "sha256": actual,
        })

    stray = sorted(p.name for p in (root / "acc").iterdir() if p.name not in expected_names)
    if stray:
        fail(f"stray files in acc/: {stray}")

    evidence = root / "license" / "wearable_exam_stress_1.0.0_project_page.html"
    inventory = {
        "dataset_id": pins.DATASET_ID,
        "release": pins.RELEASE,
        "sha256sums": {"size_bytes": sums_path.stat().st_size, "sha256": pins.SHA256SUMS_SHA256},
        "license_txt": {"size_bytes": pins.LICENSE_BYTES, "sha256": pins.LICENSE_SHA256},
        "license_evidence": {"path": "license/" + evidence.name, "sha256": sha256_file(evidence)},
        "acc_files": files,
        "acc_total_bytes": sum(row["size_bytes"] for row in files),
    }
    (root / "download_inventory.json").write_text(json.dumps(inventory, indent=2) + "\n", encoding="utf-8")
    print(f"download check ok: {len(files)} ACC.csv files, {inventory['acc_total_bytes']} bytes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
