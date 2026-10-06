#!/usr/bin/env python3
"""Deterministic SEVIR STORMEVENTS VIL event selection from CATALOG.csv.

Rule (pinned; the output is committed as ``events.tsv`` and re-derived by
``download.sh`` and ``verify.sh`` from the SHA-256-pinned catalog):

1. Keep catalog rows with ``img_type == "vil"`` whose ``file_name`` is one of
   the six ``SEVIR_VIL_STORMEVENTS_*`` containers (RANDOMEVENTS are excluded).
2. Keep rows with ``pct_missing`` exactly ``0`` (no code-255 missing pixels in
   any of the 49 frames) and ``data_max > 0`` (not an all-zero cube).
3. Within each container, sort by ``(time_utc, id)`` and keep only the first
   event of each NWS Storm Events ``episode_id`` so that two selected cubes
   never come from the same storm episode.
4. From the resulting time-ordered list of ``M`` events, take ``K`` events at
   positions ``floor((k + 0.5) * M / K)`` for ``k = 0..K-1`` (even spacing in
   time across the half-year container).

Usage:
  select_events.py CATALOG.csv [--per-file 10] [--out events.tsv]
  select_events.py CATALOG.csv --check events.tsv
"""
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

CONTAINERS = [
    "SEVIR_VIL_STORMEVENTS_2017_0101_0630",
    "SEVIR_VIL_STORMEVENTS_2017_0701_1231",
    "SEVIR_VIL_STORMEVENTS_2018_0101_0630",
    "SEVIR_VIL_STORMEVENTS_2018_0701_1231",
    "SEVIR_VIL_STORMEVENTS_2019_0101_0630",
    "SEVIR_VIL_STORMEVENTS_2019_0701_1231",
]
PER_FILE = 10
COLUMNS = [
    "container",
    "file_index",
    "sevir_id",
    "time_utc",
    "episode_id",
    "storm_event_id",
    "event_type",
    "llcrnrlat",
    "llcrnrlon",
    "urcrnrlat",
    "urcrnrlon",
    "catalog_data_min",
    "catalog_data_max",
    "minute_offsets",
]


def container_of(file_name: str) -> str:
    return file_name.rsplit("/", 1)[-1].removesuffix(".h5")


def select(catalog_path: Path, per_file: int = PER_FILE) -> list[dict[str, str]]:
    by_container: dict[str, list[dict[str, str]]] = {name: [] for name in CONTAINERS}
    with catalog_path.open(newline="") as handle:
        for row in csv.DictReader(handle):
            if row["img_type"] != "vil":
                continue
            name = container_of(row["file_name"])
            if name not in by_container:
                continue
            if row["file_name"] != f"vil/{name.split('_')[3]}/{name}.h5":
                raise SystemExit(f"unexpected file_name {row['file_name']!r}")
            try:
                pct_missing = float(row["pct_missing"])
                data_max = float(row["data_max"])
            except ValueError:
                continue
            if pct_missing != 0.0 or not data_max > 0.0:
                continue
            if row["size_x"] != "384" or row["size_y"] != "384":
                raise SystemExit(f"unexpected VIL size for {row['id']}")
            by_container[name].append(row)

    selected: list[dict[str, str]] = []
    for name in CONTAINERS:
        rows = sorted(by_container[name], key=lambda r: (r["time_utc"], r["id"]))
        seen_episodes: set[str] = set()
        unique: list[dict[str, str]] = []
        for row in rows:
            episode = row["episode_id"].strip() or f"no_episode:{row['id']}"
            if episode in seen_episodes:
                continue
            seen_episodes.add(episode)
            unique.append(row)
        m = len(unique)
        if m < per_file:
            raise SystemExit(f"{name}: only {m} eligible episodes, need {per_file}")
        for k in range(per_file):
            row = unique[((2 * k + 1) * m) // (2 * per_file)]
            selected.append(
                {
                    "container": name,
                    "file_index": str(int(row["file_index"])),
                    "sevir_id": row["id"],
                    "time_utc": row["time_utc"],
                    "episode_id": row["episode_id"].strip().split(".")[0],
                    "storm_event_id": row["event_id"].strip().split(".")[0],
                    "event_type": row["event_type"],
                    "llcrnrlat": f"{float(row['llcrnrlat']):.4f}",
                    "llcrnrlon": f"{float(row['llcrnrlon']):.4f}",
                    "urcrnrlat": f"{float(row['urcrnrlat']):.4f}",
                    "urcrnrlon": f"{float(row['urcrnrlon']):.4f}",
                    "catalog_data_min": str(int(float(row["data_min"]))),
                    "catalog_data_max": str(int(float(row["data_max"]))),
                    "minute_offsets": row["minute_offsets"],
                }
            )
    return selected


def write_tsv(rows: list[dict[str, str]], out) -> None:
    out.write("\t".join(COLUMNS) + "\n")
    for row in rows:
        out.write("\t".join(row[c] for c in COLUMNS) + "\n")


def read_tsv(path: Path) -> list[dict[str, str]]:
    lines = path.read_text().splitlines()
    header = lines[0].split("\t")
    if header != COLUMNS:
        raise SystemExit(f"{path}: unexpected header {header}")
    return [dict(zip(header, line.split("\t"))) for line in lines[1:] if line]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("catalog", type=Path)
    parser.add_argument("--per-file", type=int, default=PER_FILE)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--check", type=Path, help="fail unless the pinned TSV equals the re-derived selection")
    args = parser.parse_args()
    rows = select(args.catalog, args.per_file)
    if args.check:
        pinned = read_tsv(args.check)
        if pinned != rows:
            for a, b in zip(pinned, rows):
                if a != b:
                    print(f"first difference: pinned={a} derived={b}", file=sys.stderr)
                    break
            raise SystemExit(f"pinned selection {args.check} does not match the rule applied to {args.catalog}")
        print(f"selection_check=ok events={len(rows)}")
        return 0
    if args.out:
        with args.out.open("w") as handle:
            write_tsv(rows, handle)
    else:
        write_tsv(rows, sys.stdout)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
