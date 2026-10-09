#!/usr/bin/env python3
"""Semantic check of the downloaded MIMIC-III files against the pins.

Re-hashes every pinned file, parses every segment header and requires the
pinned geometry (frames, nsig, 125 Hz, all signals format 80 in <seg>.dat),
the ABP signal index, gain string 1.25(-100)/mmHg, 8-bit resolution, ADC
zero 0, and the pinned ABP initial value and checksum; requires each .dat to
be exactly frames x nsig bytes; checks RECORDS-adults lists every pinned
record directory. Writes download_inventory.json.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import mimic_pins as P  # noqa: E402


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 22), b""):
            h.update(block)
    return h.hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--download-dir", required=True, type=Path)
    args = ap.parse_args()
    d = args.download_dir

    adults = (d / "RECORDS-adults").read_text().split()
    adults_set = set(adults)
    if len(adults) != len(adults_set):
        raise SystemExit("RECORDS-adults has duplicates")
    positions = []
    total_dat = 0
    for seg in P.segment_rows():
        name, recdir = seg["segment"], seg["record_dir"]
        if recdir not in adults_set:
            raise SystemExit(f"{recdir} not in RECORDS-adults")
        positions.append(adults.index(recdir))
        hea = d / recdir / f"{name}.hea"
        dat = d / recdir / f"{name}.dat"
        if hea.stat().st_size != seg["hea_bytes"] or sha256(hea) != seg["hea_sha256"]:
            raise SystemExit(f"{name}.hea pin mismatch")
        if dat.stat().st_size != seg["dat_bytes"] or sha256(dat) != seg["dat_sha256"]:
            raise SystemExit(f"{name}.dat pin mismatch")
        if seg["dat_bytes"] != seg["frames"] * seg["nsig"]:
            raise SystemExit(f"{name}.dat size != frames x nsig")
        if seg["frames"] < P.MIN_FRAMES:
            raise SystemExit(f"{name}: below MIN_FRAMES")
        lines = [ln for ln in hea.read_text().splitlines() if ln.strip() and not ln.startswith("#")]
        head = lines[0].split()
        if head[0] != name or int(head[1]) != seg["nsig"] or head[2] != str(P.SAMPLING_HZ) or int(head[3]) != seg["frames"]:
            raise SystemExit(f"{name}: header geometry {head[:4]}")
        sigs = [ln.split() for ln in lines[1 : 1 + seg["nsig"]]]
        if any(s[0] != f"{name}.dat" or s[1] != "80" for s in sigs):
            raise SystemExit(f"{name}: not all signals format 80 in {name}.dat")
        names = [" ".join(s[8:]) for s in sigs]
        if names.count("ABP") != 1 or names.index("ABP") != seg["abp_index"]:
            raise SystemExit(f"{name}: ABP index {names}")
        a = sigs[seg["abp_index"]]
        if a[2] != P.ABP_GAIN_STRING or a[3] != "8" or a[4] != "0":
            raise SystemExit(f"{name}: ABP calibration {a[2:5]}")
        if int(a[5]) != seg["abp_init"] or int(a[6]) != seg["abp_checksum"]:
            raise SystemExit(f"{name}: ABP init/checksum differ from pins")
        total_dat += seg["dat_bytes"]
    if positions != sorted(positions):
        raise SystemExit("pinned segments are not in RECORDS-adults order")
    inv = {
        "dataset_id": P.DATASET_ID,
        "segments": len(P.SEGMENTS),
        "dat_bytes_total": total_dat,
        "abp_frames_total": sum(s["frames"] for s in P.segment_rows()),
        "records_adults_bytes": P.RECORDS_ADULTS_BYTES,
    }
    (d / "download_inventory.json").write_text(json.dumps(inv, indent=1) + "\n")
    print(f"download check ok: {inv}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
