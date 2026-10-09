#!/usr/bin/env python3
"""Independently re-derive and check DFL person position/speed samples.

Uses xml.etree.ElementTree.iterparse (a different code path from the
line-oriented build parser) to re-read every pinned XML, re-encodes X/Y/S of
every non-ball FrameSet with struct '<f', and byte-compares against the
emitted samples. Also checks the index rows, stored-f32 min/max, finiteness,
non-constancy, manifest counts and repository floors.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import statistics
import struct
import tomllib
import xml.etree.ElementTree as ET
from pathlib import Path

DATASET_ID = "figshare_dfl_bundesliga_position_tracking_f32"
FIELDS = {"person_x_f32": "X", "person_y_f32": "Y", "person_speed_f32": "S"}
NUM_RE = re.compile(r"^-?\d+\.\d\d$")
# Physical plausibility envelopes (pitch 105 x 68 m, centred; speed km/h).
ENVELOPE = {"X": (-75.0, 75.0), "Y": (-55.0, 55.0), "S": (0.0, 60.0)}
REQUIRED = (
    "dataset_id", "series_id", "sample_path", "numeric_kind", "bit_width", "endianness",
    "element_size_bytes", "sample_size_bytes", "value_count",
)


def derive(path: Path, match: str) -> dict[str, dict[str, bytes]]:
    """Return {stem: {field: le_f32_bytes}} plus metadata for non-ball framesets."""
    out: dict[str, dict] = {}
    current = None
    ball = 0
    for event, elem in ET.iterparse(str(path), events=("start", "end")):
        tag = elem.tag
        if event == "start" and tag == "FrameSet":
            a = elem.attrib
            if a.get("MatchId") != match:
                raise SystemExit(f"{path.name}: MatchId mismatch {a.get('MatchId')}")
            is_ball = a.get("TeamId") == "BALL"
            stem = f"{match}__{a['GameSection']}__{a['PersonId']}"
            if not is_ball and stem in out:
                raise SystemExit(f"duplicate FrameSet {stem}")
            current = {"stem": stem, "ball": is_ball, "team": a.get("TeamId"), "N": [],
                       "X": [], "Y": [], "S": []}
        elif event == "end" and tag == "Frame":
            if current is not None and not current["ball"]:
                a = elem.attrib
                if "Z" in a or "BallStatus" in a:
                    raise SystemExit(f"{current['stem']}: ball attributes in person frame")
                current["N"].append(int(a["N"]))
                for f in ("X", "Y", "S"):
                    v = a[f]
                    if not NUM_RE.match(v):
                        raise SystemExit(f"{current['stem']}: malformed {f}={v!r}")
                    current[f].append(float(v))
            elem.clear()
        elif event == "end" and tag == "FrameSet":
            if current["ball"]:
                ball += 1
            else:
                ns = current["N"]
                if not ns or any(b <= a for a, b in zip(ns, ns[1:])):
                    raise SystemExit(f"{current['stem']}: empty or non-increasing frames")
                gaps = sum(1 for a, b in zip(ns, ns[1:]) if b != a + 1)
                out[current["stem"]] = {
                    "team": current["team"],
                    "first": ns[0],
                    "last": ns[-1],
                    "gaps": gaps,
                    **{f: struct.pack(f"<{len(current[f])}f", *current[f]) for f in ("X", "Y", "S")},
                }
            current = None
            elem.clear()
    if ball == 0:
        raise SystemExit(f"{path.name}: no BALL FrameSet")
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo-root", required=True)
    ap.add_argument("--data-dir", required=True)
    ap.add_argument("--sources", required=True)
    ap.add_argument("--manifest", required=True)
    args = ap.parse_args()
    data_root = Path(args.repo_root) / args.data_dir
    downloads = data_root / "downloads" / DATASET_ID
    index_path = data_root / "index" / DATASET_ID / "samples.jsonl"
    manifest = tomllib.loads(Path(args.manifest).read_text(encoding="utf-8"))
    if manifest.get("dataset_id") != DATASET_ID:
        raise SystemExit("manifest dataset_id mismatch")

    rows = [json.loads(line) for line in index_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    by_path: dict[str, dict] = {}
    for row in rows:
        for key in REQUIRED:
            if key not in row:
                raise SystemExit(f"index row missing {key}: {row.get('sample_path')}")
        if row["dataset_id"] != DATASET_ID or row["series_id"] not in FIELDS:
            raise SystemExit(f"bad index row identity: {row['sample_path']}")
        if (row["numeric_kind"], row["bit_width"], row["endianness"], row["element_size_bytes"]) != ("float", 32, "little", 4):
            raise SystemExit(f"bad dtype fields: {row['sample_path']}")
        if row["sample_size_bytes"] != 4 * row["value_count"]:
            raise SystemExit(f"size/value_count mismatch: {row['sample_path']}")
        if row["sample_path"] in by_path:
            raise SystemExit(f"duplicate index row {row['sample_path']}")
        by_path[row["sample_path"]] = row

    # Every file on disk must be indexed.
    for sid in FIELDS:
        for p in (data_root / "samples" / DATASET_ID / sid).glob("*"):
            rel = p.relative_to(data_root).as_posix()
            if rel not in by_path:
                raise SystemExit(f"unindexed sample file {rel}")

    checked = 0
    lengths: list[int] = []
    referee = 0
    for line in Path(args.sources).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        fid, name, size, md5 = line.split("\t")
        path = downloads / name
        if not path.is_file() or path.stat().st_size != int(size):
            raise SystemExit(f"missing/wrong-sized local {name}")
        match = name.rsplit("_", 1)[1][:-4]
        derived = derive(path, match)
        print(f"re-derived {name}: {len(derived)} person framesets", flush=True)
        for stem, d in derived.items():
            lengths.append(len(d["X"]) // 4)
            referee += d["team"] == "referee"
            for sid, field in FIELDS.items():
                rel = f"samples/{DATASET_ID}/{sid}/{stem}.bin"
                row = by_path.get(rel)
                if row is None:
                    raise SystemExit(f"missing index row {rel}")
                data = (data_root / rel).read_bytes()
                if data != d[field]:
                    raise SystemExit(f"sample bytes differ from re-derivation: {rel}")
                n = len(data) // 4
                if row["value_count"] != n or row["sample_size_bytes"] != len(data):
                    raise SystemExit(f"index size mismatch {rel}")
                values = struct.unpack(f"<{n}f", data)
                if not all(math.isfinite(v) for v in values):
                    raise SystemExit(f"non-finite value in {rel}")
                lo, hi = min(values), max(values)
                if lo == hi:
                    raise SystemExit(f"constant sample {rel}")
                if row.get("min") != lo or row.get("max") != hi:
                    raise SystemExit(f"index min/max mismatch {rel}: {row.get('min')},{row.get('max')} vs {lo},{hi}")
                elo, ehi = ENVELOPE[field]
                if lo < elo or hi > ehi:
                    raise SystemExit(f"{rel}: values outside plausibility envelope [{elo},{ehi}]: {lo}..{hi}")
                if (row.get("frame_first"), row.get("frame_last"), row.get("frame_gaps")) != (d["first"], d["last"], d["gaps"]):
                    raise SystemExit(f"frame bookkeeping mismatch {rel}")
                checked += 1
    if checked != len(rows):
        raise SystemExit(f"index has {len(rows)} rows but {checked} were re-derived")

    for series in manifest.get("series", []):
        sid = series["id"]
        srows = [r for r in rows if r["series_id"] == sid]
        count, total = len(srows), sum(r["sample_size_bytes"] for r in srows)
        if series.get("sample_count") != count or series.get("total_size_bytes") != total:
            raise SystemExit(
                f"manifest mismatch for {sid}: manifest={series.get('sample_count')},{series.get('total_size_bytes')} realized={count},{total}"
            )
        values = sum(r["value_count"] for r in srows)
        median = statistics.median(r["value_count"] for r in srows)
        if values < 10000 or median < 1000:
            raise SystemExit(f"{sid}: below floor values={values} median={median}")
        print(f"series {sid}: samples={count} bytes={total} values={values} median_values={median}")
    if {s["id"] for s in manifest.get("series", [])} != set(FIELDS):
        raise SystemExit("manifest series set mismatch")
    total_bytes = sum(r["sample_size_bytes"] for r in rows)
    if total_bytes > 1_000_000_000:
        raise SystemExit(f"primary output exceeds 1 GB: {total_bytes}")
    digest = hashlib.sha256(index_path.read_bytes()).hexdigest()
    print(
        f"verify ok: rows={len(rows)} framesets={len(lengths)} referee_framesets={referee} "
        f"median_frames={statistics.median(lengths)} min_frames={min(lengths)} max_frames={max(lengths)} "
        f"total_bytes={total_bytes} index_sha256={digest}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
