#!/usr/bin/env python3
"""Re-apply the trial selection rule to bucket listings fetched by discover.sh
and compare the result with sources.tsv. Documentation/reproducibility aid:
download.sh never runs it and never discovers keys dynamically.

Rule (see README.md):
  sessions   single-plane-ophys_<subject>_<date> with 2026-01-01 <= date <=
             SESSION_CUTOFF, subject != 123456; session.json rig_id
             442_Bergamo_2p_photostim and exactly one tiff_stem:bci stream with
             one 512x256 FOV at 58.29007 Hz and detectors == ["Red PMT"];
             at least 20 pophys/bci_NNNNN.tif files
  trials     bci_NNNNN.tif in key order minus the session's first and last file
  subjects   at least 3 qualifying sessions
  pick       per subject, sessions in chronological order, trials in key
             order: the first trial with 300 <= frames <= 360, where
             frames = round((size - 63000) / 264528)   (exact for these files:
             header sizes 55-96 KB, every page 264,528 bytes)
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path

SESSION_CUTOFF = "2026-07-31"
PAGE_STRIDE = 264528
NOMINAL_HEADER = 63000


def parse_listing(text: str) -> list[dict]:
    out = []
    for block in re.findall(r"<Contents>(.*?)</Contents>", text, flags=re.S):
        key = re.search(r"<Key>([^<]*)</Key>", block).group(1)
        size = int(re.search(r"<Size>(\d+)</Size>", block).group(1))
        out.append({"key": key, "size": size})
    return out


def eligible(session_json: dict) -> bool:
    if session_json.get("rig_id") != "442_Bergamo_2p_photostim":
        return False
    streams = [s for s in session_json.get("data_streams", []) if (s.get("notes") or "") == "tiff_stem:bci"]
    if len(streams) != 1:
        return False
    stream = streams[0]
    fovs = stream.get("ophys_fovs", [])
    if len(fovs) != 1:
        return False
    fov = fovs[0]
    detectors = [d.get("name") for d in stream.get("detectors", [])]
    return (
        fov.get("fov_width") == 512
        and fov.get("fov_height") == 256
        and abs(float(fov.get("frame_rate") or 0) - 58.29007352941176) < 1e-3
        and detectors == ["Red PMT"]
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--discovery-dir", type=Path, required=True)
    parser.add_argument("--sources", type=Path, required=True)
    args = parser.parse_args()
    root = args.discovery_dir
    sessions = sorted(p.name[: -len(".session.json")] for p in root.glob("*.session.json"))
    qualifying: dict[str, list[tuple[str, list[dict]]]] = {}
    for name in sessions:
        match = re.fullmatch(r"single-plane-ophys_(\d{6})_(2026-\d\d-\d\d)_\d\d-\d\d-\d\d", name)
        if not match or match.group(1) == "123456" or match.group(2) > SESSION_CUTOFF:
            continue
        if not eligible(json.loads((root / f"{name}.session.json").read_text(encoding="utf-8"))):
            continue
        listing = parse_listing((root / f"{name}.pophys.xml").read_text(encoding="utf-8"))
        trials = sorted((o for o in listing if re.search(r"/pophys/bci_\d{5}\.tif$", o["key"])), key=lambda o: o["key"])
        if len(trials) < 20:
            continue
        qualifying.setdefault(match.group(1), []).append((name, trials[1:-1]))
    picks = {}
    for subject, items in sorted(qualifying.items()):
        if len(items) < 3:
            print(f"skip subject {subject}: {len(items)} qualifying session(s)")
            continue
        for _name, trials in items:
            hit = next((t for t in trials if 300 <= round((t["size"] - NOMINAL_HEADER) / PAGE_STRIDE) <= 360), None)
            if hit:
                picks[subject] = hit
                break
    with args.sources.open(encoding="utf-8", newline="") as handle:
        pinned = {row["subject_id"]: row for row in csv.DictReader(handle, delimiter="\t") if row["kind"] == "trial_tiff"}
    ok = True
    for subject in sorted(set(picks) | set(pinned)):
        found = picks.get(subject)
        row = pinned.get(subject)
        same = bool(found and row and found["key"] == row["key"] and found["size"] == int(row["size_bytes"]))
        ok &= same
        print(f"{'match' if same else 'DIFF '} {subject} discovered={found and found['key']} pinned={row and row['key']}")
    print("discover_matches_pins" if ok else "discover_differs_from_pins (bucket changed; pins remain authoritative)")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
