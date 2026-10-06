#!/usr/bin/env python3
"""Independent verifier for igs_final_satellite_clock_bias_f64.

Re-derives every sample from the local gzip RINEX clock files with a
fixed-column parser (it does not import igs_clk.py), then byte-compares the
emitted samples, checks every index row, the manifest totals, the missing-value
policy (present epochs only, satellite-days below 1,000 epochs excluded), and
rejects constant, non-finite, float32-exact or duplicate series.
"""
from __future__ import annotations

import argparse
import datetime
import gzip
import hashlib
import json
import math
import re
import struct
import sys
import tomllib
from collections import defaultdict
from pathlib import Path

DATASET_ID = "igs_final_satellite_clock_bias_f64"
SERIES_ID = "igs_final_gps_satellite_clock_bias_s_f64"
MIN_EPOCHS = 1000
EPOCHS = 2880
TOKEN = re.compile(r"^-?\d\.\d{12}[eEdD][+-]\d\d$")


def fail(message: str) -> None:
    print(f"VERIFY FAILED: {message}", file=sys.stderr)
    sys.exit(1)


def rederive(raw: bytes, doy: int, week: int) -> tuple[dict[str, list[tuple[int, float]]], list[str]]:
    text = gzip.decompress(raw).decode("ascii")
    lines = text.splitlines()
    end = next((i for i, line in enumerate(lines) if line[60:73] == "END OF HEADER"), None)
    if end is None:
        fail(f"doy {doy}: no END OF HEADER")
    header = lines[: end + 1]
    if header[0][60:80].rstrip() != "RINEX VERSION / TYPE" or header[0][0:9].strip() != "3.00" or header[0][20] != "C":
        fail(f"doy {doy}: header is not RINEX 3.00 clock")
    prns: list[str] = []
    nsat = None
    week_ok = False
    acs_line = None
    for position, line in enumerate(header):
        label = line[60:80].rstrip()
        if label == "PRN LIST":
            prns += [line[c : c + 3] for c in range(0, 60, 4) if line[c : c + 3].strip()]
        elif label == "# OF SOLN SATS":
            nsat = int(line[0:6])
        elif label == "TIME SYSTEM ID" and line[3:6] != "GPS":
            fail(f"doy {doy}: time system {line[3:6]!r}")
        elif label == "ANALYSIS CENTER" and line[0:3] != "IGS":
            fail(f"doy {doy}: analysis center {line[0:3]!r}")
        elif label == "COMMENT":
            body = line[0:60]
            m = re.match(r"GPS week:\s+(\d+)\s+Day:\s+(\d)", body)
            if m and (int(m.group(1)), int(m.group(2))) == (week, doy % 7):
                week_ok = True
            if body.startswith("THE COMBINED CLOCKS ARE A WEIGHTED AVERAGE OF:"):
                acs_line = header[position + 1][0:60].strip()
    if not week_ok:
        fail(f"doy {doy}: GPS week/day comment mismatch")
    if not acs_line:
        fail(f"doy {doy}: no contributing AC list")
    if nsat != len(prns) or any(not re.fullmatch(r"G\d\d", prn) for prn in prns):
        fail(f"doy {doy}: # OF SOLN SATS {nsat} vs PRN LIST {prns}")
    month_day = None
    series: dict[str, list[tuple[int, float]]] = defaultdict(list)
    i = end + 1
    while i < len(lines):
        line = lines[i]
        i += 1
        kind = line[0:2]
        if kind not in ("AS", "AR"):
            fail(f"doy {doy}: unexpected record {line[:12]!r}")
        count = int(line[35:37])
        skip = 1 if count > 2 else 0
        if kind == "AR":
            i += skip
            continue
        prn = line[3:6]
        if line[6:8] != "  " or line[8:12] != "2024":
            fail(f"doy {doy}: AS layout {line[:14]!r}")
        stamp = (line[13:15], line[16:18])
        if month_day is None:
            month_day = stamp
        if stamp != month_day:
            fail(f"doy {doy}: AS records span more than one date")
        hour, minute = int(line[19:21]), int(line[22:24])
        sec = line[25:34]
        if sec[-7:] != ".000000" or int(float(sec)) % 30:
            fail(f"doy {doy}: epoch seconds {sec!r}")
        token = line[40:59].strip()
        if not TOKEN.match(token):
            fail(f"doy {doy}: bias token {token!r}")
        canonical = token.lower().replace("d", "e")
        value = float(canonical)
        if not math.isfinite(value) or "%.12e" % value != canonical:
            fail(f"doy {doy}: float64 does not round-trip {token!r}")
        epoch = (hour * 3600 + minute * 60 + int(float(sec))) // 30
        if not 0 <= epoch < EPOCHS:
            fail(f"doy {doy}: epoch {epoch}")
        if series[prn] and series[prn][-1][0] >= epoch:
            fail(f"doy {doy}: {prn} epochs not strictly increasing")
        series[prn].append((epoch, value))
        i += skip
    expected_date = datetime.date(2024, 1, 1) + datetime.timedelta(days=doy - 1)
    if month_day != (f"{expected_date.month:02d}", f"{expected_date.day:02d}"):
        fail(f"doy {doy}: AS date {month_day} != {expected_date}")
    if sorted(series) != sorted(prns):
        fail(f"doy {doy}: AS PRNs {sorted(series)} != PRN LIST {sorted(prns)}")
    return series, acs_line.split()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", required=True)
    parser.add_argument("--data-dir", required=True)
    parser.add_argument("--recipe-dir", required=True)
    args = parser.parse_args()
    data_root = Path(args.data_dir)
    if not data_root.is_absolute():
        data_root = Path(args.repo_root) / data_root
    recipe = Path(args.recipe_dir)
    manifest = tomllib.loads((recipe / "manifest.toml").read_text(encoding="utf-8"))
    series_meta = [s for s in manifest["series"] if s["id"] == SERIES_ID]
    if len(series_meta) != 1 or series_meta[0]["role"] != "primary":
        fail("manifest primary series missing")
    source_lines = (recipe / "sources.tsv").read_text(encoding="utf-8").strip().split("\n")
    columns = source_lines[0].split("\t")
    sources = [dict(zip(columns, line.split("\t"))) for line in source_lines[1:]]
    if [int(s["doy"]) for s in sources] != list(range(1, 183)):
        fail("sources.tsv does not list 2024 doy 001..182")
    observed: dict[str, str] = {}
    plan = data_root / "downloads" / DATASET_ID / "download_plan.tsv"
    if plan.is_file():
        for line in plan.read_text(encoding="utf-8").strip().split("\n")[1:]:
            parts = line.split("\t")
            observed[parts[2]] = parts[6]
    index_path = data_root / "index" / DATASET_ID / "samples.jsonl"
    rows = [json.loads(line) for line in index_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    by_path = {row["sample_path"]: row for row in rows}
    if len(by_path) != len(rows):
        fail("duplicate sample_path in index")
    expected_paths: list[str] = []
    excluded = 0
    gapped = 0
    hashes: set[str] = set()
    for source in sources:
        doy = int(source["doy"])
        path = data_root / "downloads" / DATASET_ID / "clk" / source["filename"]
        raw = path.read_bytes()
        if len(raw) != int(source["size_bytes"]):
            fail(f"{source['filename']}: size mismatch")
        digest = hashlib.sha256(raw).hexdigest()
        pinned = source.get("sha256") or observed.get(source["filename"], "")
        if not pinned or digest != pinned:
            fail(f"{source['filename']}: sha256 {digest} not matching pinned/observed {pinned!r}")
        series, acs = rederive(raw, doy, int(source["gps_week"]))
        for prn in sorted(series):
            records = series[prn]
            if len(records) < MIN_EPOCHS:
                excluded += 1
                continue
            values = [v for _, v in records]
            epochs = [e for e, _ in records]
            rel = f"samples/{DATASET_ID}/{SERIES_ID}/2024_{doy:03d}_{prn}.bin"
            expected_paths.append(rel)
            row = by_path.get(rel)
            if row is None:
                fail(f"missing index row for {rel}")
            payload = b"".join(struct.pack("<d", v) for v in values)
            actual = (data_root / rel).read_bytes()
            if actual != payload:
                fail(f"{rel}: bytes differ from re-derived series")
            if len(set(values)) < 2:
                fail(f"{rel}: constant series")
            if all(struct.unpack("<f", struct.pack("<f", v))[0] == v for v in values):
                fail(f"{rel}: every value is float32-exact")
            sha = hashlib.sha256(actual).hexdigest()
            if sha in hashes:
                fail(f"{rel}: duplicate payload")
            hashes.add(sha)
            missing = EPOCHS - len(epochs)
            gapped += 1 if missing else 0
            checks = {
                "dataset_id": DATASET_ID,
                "series_id": SERIES_ID,
                "numeric_kind": "float",
                "bit_width": 64,
                "endianness": "little",
                "element_size_bytes": 8,
                "value_count": len(values),
                "sample_size_bytes": len(payload),
                "prn": prn,
                "source_doy": doy,
                "source_file": source["filename"],
                "first_epoch_index": epochs[0],
                "last_epoch_index": epochs[-1],
                "missing_epoch_count": missing,
                "contributing_acs": " ".join(acs),
                "min": min(values),
                "max": max(values),
                "sha256": sha,
            }
            for key, want in checks.items():
                if row.get(key) != want:
                    fail(f"{rel}: index {key}={row.get(key)!r} expected {want!r}")
    if sorted(expected_paths) != sorted(by_path):
        extra = sorted(set(by_path) - set(expected_paths))[:5]
        fail(f"index has rows without re-derived samples: {extra}")
    sample_dir = data_root / "samples" / DATASET_ID / SERIES_ID
    on_disk = sorted(f"samples/{DATASET_ID}/{SERIES_ID}/{p.name}" for p in sample_dir.iterdir())
    if on_disk != sorted(expected_paths):
        fail("sample directory contains files not in the index")
    total_bytes = sum(row["sample_size_bytes"] for row in rows)
    total_values = sum(row["value_count"] for row in rows)
    meta = series_meta[0]
    if meta["sample_count"] != len(rows) or meta["total_size_bytes"] != total_bytes:
        fail(f"manifest sample_count/total_size_bytes {meta['sample_count']}/{meta['total_size_bytes']} != {len(rows)}/{total_bytes}")
    counts = sorted(row["value_count"] for row in rows)
    mid = len(counts) // 2
    median = counts[mid] if len(counts) % 2 else (counts[mid - 1] + counts[mid]) / 2
    if total_values < 10_000 or median < 1_000 or total_bytes > 1_000_000_000:
        fail(f"floor/cap: values={total_values} median={median} bytes={total_bytes}")
    print(
        f"verify=ok files={len(sources)} samples={len(rows)} values={total_values} bytes={total_bytes} "
        f"median_values={median} gapped={gapped} excluded_short={excluded}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
