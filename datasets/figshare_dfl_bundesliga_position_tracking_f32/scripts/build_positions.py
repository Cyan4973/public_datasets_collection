#!/usr/bin/env python3
"""Build DFL person position/speed samples from local positions_raw_observed XML.

Line-oriented streaming parser (each <FrameSet ...>, <Frame .../> and
</FrameSet> occupies its own line in the DFL files). One sample per person
FrameSet (person x GameSection x match) per series:

  person_x_f32      Frame@X  pitch-centred x coordinate, metres
  person_y_f32      Frame@Y  pitch-centred y coordinate, metres
  person_speed_f32  Frame@S  speed, km/h (as published by DFL)

The ball FrameSet (TeamId="BALL", which carries Z/BallPossession/BallStatus)
is excluded. Frame@D, Frame@A, Frame@M, Frame@T and Frame@N are not emitted.
Any person frame lacking X/Y/S, or whose value is not a plain decimal with two
fraction digits, is fatal.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import statistics
import sys
from array import array
from pathlib import Path

DATASET_ID = "figshare_dfl_bundesliga_position_tracking_f32"
SERIES = (("person_x_f32", "X"), ("person_y_f32", "Y"), ("person_speed_f32", "S"))
ATTR_RE = re.compile(r'(\w+)="([^"]*)"')
FAST_RE = re.compile(
    r'^<Frame N="(\d+)" T="[^"]*" X="([^"]*)" Y="([^"]*)" D="[^"]*" S="([^"]*)" A="[^"]*" M="[^"]*"\s*/>$'
)
NUM_RE = re.compile(r"^-?\d+\.\d\d$")
CLU_RE = re.compile(r"^DFL-CLU-[0-9A-Z]+$")
OBJ_RE = re.compile(r"^DFL-OBJ-[0-9A-Z]+$")
MAT_RE = re.compile(r"^DFL-MAT-[0-9A-Z]+$")


def read_sources(path: Path) -> list[tuple[str, str, int, str]]:
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            fid, name, size, md5 = line.split("\t")
            rows.append((fid, name, int(size), md5))
    return rows


def f32(values: list[str], where: str) -> array:
    for v in values:
        if not NUM_RE.match(v):
            raise SystemExit(f"{where}: malformed value {v!r}")
    arr = array("f", map(float, values))
    if sys.byteorder != "little":
        arr.byteswap()
    return arr


def parse_file(path: Path, match_expected: str):
    """Yield (attrs, frames_n, xs, ys, ss) for every non-ball FrameSet."""
    current = None
    ball_sets = 0
    with path.open("r", encoding="utf-8", newline="\n") as handle:
        for lineno, raw in enumerate(handle, 1):
            line = raw.strip()
            if not line:
                continue
            if current is not None and line.startswith("<Frame "):
                if current["ball"]:
                    continue
                m = FAST_RE.match(line)
                if m:
                    n, x, y, s = m.groups()
                else:
                    attrs = dict(ATTR_RE.findall(line))
                    if any(k in attrs for k in ("Z", "BallStatus", "BallPossession")):
                        raise SystemExit(f"{path.name}:{lineno}: ball attributes in person frame")
                    try:
                        n, x, y, s = attrs["N"], attrs["X"], attrs["Y"], attrs["S"]
                    except KeyError as exc:
                        raise SystemExit(f"{path.name}:{lineno}: frame missing {exc}") from None
                current["n"].append(int(n))
                current["x"].append(x)
                current["y"].append(y)
                current["s"].append(s)
            elif line.startswith("<FrameSet "):
                if current is not None:
                    raise SystemExit(f"{path.name}:{lineno}: nested FrameSet")
                attrs = dict(ATTR_RE.findall(line))
                for key in ("GameSection", "MatchId", "TeamId", "PersonId"):
                    if key not in attrs:
                        raise SystemExit(f"{path.name}:{lineno}: FrameSet missing {key}")
                if attrs["MatchId"] != match_expected:
                    raise SystemExit(f"{path.name}:{lineno}: MatchId {attrs['MatchId']} != {match_expected}")
                if not OBJ_RE.match(attrs["PersonId"]):
                    raise SystemExit(f"{path.name}:{lineno}: unexpected PersonId {attrs['PersonId']!r}")
                ball = attrs["TeamId"] == "BALL"
                if not ball and attrs["TeamId"] != "referee" and not CLU_RE.match(attrs["TeamId"]):
                    raise SystemExit(f"{path.name}:{lineno}: unexpected TeamId {attrs['TeamId']!r}")
                if not re.match(r"^[A-Za-z]+$", attrs["GameSection"]):
                    raise SystemExit(f"{path.name}:{lineno}: unexpected GameSection {attrs['GameSection']!r}")
                current = {"attrs": attrs, "ball": ball, "n": [], "x": [], "y": [], "s": [], "line": lineno}
            elif line == "</FrameSet>":
                if current is None:
                    raise SystemExit(f"{path.name}:{lineno}: unmatched </FrameSet>")
                if current["ball"]:
                    ball_sets += 1
                else:
                    yield current
                current = None
            elif line.startswith("<Frame "):
                raise SystemExit(f"{path.name}:{lineno}: Frame outside FrameSet")
    if current is not None:
        raise SystemExit(f"{path.name}: unterminated FrameSet")
    if ball_sets == 0:
        raise SystemExit(f"{path.name}: no BALL FrameSet found (unexpected layout)")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo-root", required=True)
    ap.add_argument("--data-dir", required=True)
    ap.add_argument("--sources", required=True)
    args = ap.parse_args()
    data_root = Path(args.repo_root) / args.data_dir
    downloads = data_root / "downloads" / DATASET_ID
    samples_root = data_root / "samples" / DATASET_ID
    index_dir = data_root / "index" / DATASET_ID
    filtered_dir = data_root / "filtered" / DATASET_ID
    for sid, _ in SERIES:
        d = samples_root / sid
        d.mkdir(parents=True, exist_ok=True)
        for old in d.glob("*.bin"):
            old.unlink()
    index_dir.mkdir(parents=True, exist_ok=True)
    filtered_dir.mkdir(parents=True, exist_ok=True)

    rows: list[dict] = []
    seen: set[tuple[str, str, str]] = set()
    per_match: dict[str, dict] = {}
    lengths: list[int] = []
    for fid, name, size, _md5 in read_sources(Path(args.sources)):
        path = downloads / name
        if not path.is_file() or path.stat().st_size != size:
            raise SystemExit(f"missing or wrong-sized local file {path}; run download.sh")
        match = name.rsplit("_", 1)[1][:-4]
        if not MAT_RE.match(match):
            raise SystemExit(f"bad match id in {name}")
        stats = {"framesets": 0, "frames": 0, "referee_framesets": 0, "sections": {}}
        for fs in parse_file(path, match):
            a = fs["attrs"]
            key = (match, a["GameSection"], a["PersonId"])
            if key in seen:
                raise SystemExit(f"duplicate FrameSet {key}")
            seen.add(key)
            ns = fs["n"]
            count = len(ns)
            if count == 0:
                raise SystemExit(f"empty FrameSet {key}")
            gaps = 0
            for prev, cur in zip(ns, ns[1:]):
                if cur <= prev:
                    raise SystemExit(f"non-increasing frame numbers in {key}: {prev} -> {cur}")
                if cur != prev + 1:
                    gaps += 1
            stem = f"{match}__{a['GameSection']}__{a['PersonId']}"
            where = f"{name}:{stem}"
            arrays = {"X": f32(fs["x"], where), "Y": f32(fs["y"], where), "S": f32(fs["s"], where)}
            for sid, field in SERIES:
                arr = arrays[field]
                rel = Path("samples") / DATASET_ID / sid / f"{stem}.bin"
                with (data_root / rel).open("wb") as out:
                    arr.tofile(out)
                rows.append(
                    {
                        "dataset_id": DATASET_ID,
                        "series_id": sid,
                        "sample_path": rel.as_posix(),
                        "numeric_kind": "float",
                        "bit_width": 32,
                        "endianness": "little",
                        "element_size_bytes": 4,
                        "sample_size_bytes": 4 * count,
                        "value_count": count,
                        "source_field": f"Frame@{field}",
                        "source_file_id": int(fid),
                        "match_id": match,
                        "game_section": a["GameSection"],
                        "person_id": a["PersonId"],
                        "person_kind": "referee" if a["TeamId"] == "referee" else "player",
                        "team_id": a["TeamId"],
                        "frame_first": ns[0],
                        "frame_last": ns[-1],
                        "frame_gaps": gaps,
                        "min": min(arr),
                        "max": max(arr),
                    }
                )
            lengths.append(count)
            stats["framesets"] += 1
            stats["frames"] += count
            stats["referee_framesets"] += a["TeamId"] == "referee"
            stats["sections"][a["GameSection"]] = stats["sections"].get(a["GameSection"], 0) + 1
        per_match[match] = stats
        print(f"parsed {name}: {stats}", flush=True)

    rows.sort(key=lambda r: (r["series_id"], r["sample_path"]))
    tmp = index_dir / "samples.jsonl.tmp"
    with tmp.open("w", encoding="utf-8") as out:
        for row in rows:
            out.write(json.dumps(row, sort_keys=True) + "\n")
    os.replace(tmp, index_dir / "samples.jsonl")
    summary = {
        "dataset_id": DATASET_ID,
        "framesets_per_series": len(lengths),
        "frames_total_per_series": sum(lengths),
        "frameset_length_min": min(lengths),
        "frameset_length_median": statistics.median(lengths),
        "frameset_length_max": max(lengths),
        "series": {
            sid: {
                "sample_count": sum(1 for r in rows if r["series_id"] == sid),
                "total_size_bytes": sum(r["sample_size_bytes"] for r in rows if r["series_id"] == sid),
            }
            for sid, _ in SERIES
        },
        "per_match": per_match,
    }
    (filtered_dir / "build_stats.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    print(json.dumps({k: v for k, v in summary.items() if k != "per_match"}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
