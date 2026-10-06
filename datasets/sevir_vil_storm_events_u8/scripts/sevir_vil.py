#!/usr/bin/env python3
"""Validation, build and verification for sevir_vil_storm_events_u8.

Subcommands (all local-only; network I/O happens in download.sh with curl):

  check-headers   validate a curl --dump-header file for an exact 206 range of a pinned S3 object
  check-catalog   validate CATALOG.csv and re-derive the pinned event selection
  check-container parse a container's fetched HDF5 metadata head/tail and cross-check ids
  check-event     semantic check of one downloaded VIL event range
  build           emit one raw uint8 sample per selected event plus the sample index
  verify          independently re-derive and check every sample and index row
"""
from __future__ import annotations

import argparse
import collections
import csv
import hashlib
import json
import re
import sys
import tomllib
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import select_events  # noqa: E402
import sevir_hdf5 as h5  # noqa: E402

DATASET_ID = "sevir_vil_storm_events_u8"
SERIES_ID = "sevir_vil_storm_event_cube_u8"
EXPECTED_EVENTS = 60
MISSING_CODE = 255
SAMPLE_AXES = ["grid_row", "grid_column", "frame"]
INDEX_KEYS = [
    "dataset_id",
    "series_id",
    "sample_path",
    "numeric_kind",
    "bit_width",
    "endianness",
    "element_size_bytes",
    "sample_size_bytes",
    "value_count",
]


# --------------------------------------------------------------------------- pins


def read_tsv(path: Path) -> list[dict[str, str]]:
    lines = path.read_text().splitlines()
    header = lines[0].split("\t")
    return [dict(zip(header, line.split("\t"))) for line in lines[1:] if line.strip()]


def containers(recipe_dir: Path) -> dict[str, dict[str, str]]:
    rows = read_tsv(recipe_dir / "containers.tsv")
    out = {row["container"]: row for row in rows}
    if list(out) != select_events.CONTAINERS:
        raise SystemExit(f"containers.tsv rows {list(out)} != {select_events.CONTAINERS}")
    return out


def events(recipe_dir: Path) -> list[dict[str, str]]:
    rows = select_events.read_tsv(recipe_dir / "events.tsv")
    if len(rows) != EXPECTED_EVENTS:
        raise SystemExit(f"events.tsv has {len(rows)} rows, expected {EXPECTED_EVENTS}")
    if len({r["sevir_id"] for r in rows}) != len(rows):
        raise SystemExit("duplicate sevir_id in events.tsv")
    return rows


def sha_pins(recipe_dir: Path) -> dict[str, str]:
    """Optional post-download SHA-256 pins (event_sha256.tsv: sevir_id, sha256)."""
    path = recipe_dir / "event_sha256.tsv"
    if not path.exists():
        return {}
    return {row["sevir_id"]: row["sha256"] for row in read_tsv(path)}


def download_dir(data_root: Path) -> Path:
    return data_root / "downloads" / DATASET_ID


def event_path(data_root: Path, event: dict[str, str]) -> Path:
    return download_dir(data_root) / "events" / event["container"] / f"{int(event['file_index']):04d}_{event['sevir_id']}.vil.u8"


def head_path(data_root: Path, stem: str) -> Path:
    return download_dir(data_root) / "containers" / f"{stem}.head.bin"


def tail_path(data_root: Path, stem: str) -> Path:
    return download_dir(data_root) / "containers" / f"{stem}.tail.bin"


def sample_rel_path(event: dict[str, str]) -> str:
    return f"samples/{DATASET_ID}/{SERIES_ID}/{event['sevir_id']}.u8"


# --------------------------------------------------------------------------- statistics


def histogram(data: bytes) -> list[int]:
    counts = collections.Counter(data)
    return [counts.get(v, 0) for v in range(256)]


def frame_digests(data: bytes, frames: int) -> list[str]:
    return [hashlib.sha1(data[t::frames]).hexdigest() for t in range(frames)]


def event_stats(data: bytes, hist: list[int]) -> dict:
    present = [v for v in range(256) if hist[v]]
    frames = h5.EVENT_SHAPE[2]
    digests = frame_digests(data, frames)
    nonzero_frames = sum(1 for t in range(frames) if data[t::frames].strip(b"\x00"))
    return {
        "min": present[0],
        "max": present[-1],
        "distinct_codes": len(present),
        "missing_code_255_count": hist[MISSING_CODE],
        "zero_fraction": round(hist[0] / len(data), 6),
        "codes_le5_zero_vil": sum(hist[0:6]),
        "codes_6_18_linear": sum(hist[6:19]),
        "codes_19_254_log": sum(hist[19:255]),
        "distinct_frames": len(set(digests)),
        "nonzero_frames": nonzero_frames,
        "sha256": hashlib.sha256(data).hexdigest(),
    }


def semantic_check(data: bytes, event: dict[str, str], pins: dict[str, str]) -> tuple[dict, list[int]]:
    """Shared missing-value / degeneracy policy for download, build and verify."""
    sid = event["sevir_id"]
    if len(data) != h5.EVENT_BYTES:
        raise SystemExit(f"{sid}: {len(data)} bytes, expected {h5.EVENT_BYTES}")
    hist = histogram(data)
    stats = event_stats(data, hist)
    problems = []
    if stats["missing_code_255_count"]:
        problems.append(f"{stats['missing_code_255_count']} missing-data code-255 pixels although catalog pct_missing == 0")
    if stats["max"] != int(event["catalog_data_max"]):
        problems.append(f"max code {stats['max']} != catalog data_max {event['catalog_data_max']}")
    if stats["min"] != int(event["catalog_data_min"]):
        problems.append(f"min code {stats['min']} != catalog data_min {event['catalog_data_min']}")
    if stats["distinct_codes"] < 16:
        problems.append(f"only {stats['distinct_codes']} distinct codes")
    if stats["zero_fraction"] >= 0.9999:
        problems.append("cube is (almost) entirely zero")
    if stats["distinct_frames"] < 2:
        problems.append("all 49 frames are identical")
    if sid in pins and stats["sha256"] != pins[sid]:
        problems.append(f"sha256 {stats['sha256']} != pinned {pins[sid]}")
    if problems:
        raise SystemExit(f"{sid}: " + "; ".join(problems))
    return stats, hist


# --------------------------------------------------------------------------- catalog


def catalog_rows(catalog: Path) -> dict[str, dict[str, str]]:
    """All STORMEVENTS VIL rows keyed by SEVIR id."""
    out: dict[str, dict[str, str]] = {}
    with catalog.open(newline="") as handle:
        for row in csv.DictReader(handle):
            if row["img_type"] != "vil":
                continue
            stem = select_events.container_of(row["file_name"])
            if stem in select_events.CONTAINERS:
                out[row["id"]] = row
    return out


def check_catalog(recipe_dir: Path, catalog: Path) -> None:
    pinned = events(recipe_dir)
    derived = select_events.select(catalog, select_events.PER_FILE)
    if derived != pinned:
        raise SystemExit("events.tsv differs from the selection rule applied to CATALOG.csv")
    rows = catalog_rows(catalog)
    pins = containers(recipe_dir)
    for stem, pin in pins.items():
        count = sum(1 for r in rows.values() if select_events.container_of(r["file_name"]) == stem)
        if count != int(pin["event_count"]):
            raise SystemExit(f"{stem}: catalog lists {count} VIL events, container pin says {pin['event_count']}")
    for event in pinned:
        row = rows.get(event["sevir_id"])
        if row is None or select_events.container_of(row["file_name"]) != event["container"] or int(row["file_index"]) != int(event["file_index"]):
            raise SystemExit(f"{event['sevir_id']}: catalog location mismatch")
        if float(row["pct_missing"]) != 0.0 or row["proj"].strip() != "+proj=laea +lat_0=38 +lon_0=-98 +units=m +a=6370997.0 +ellps=sphere":
            raise SystemExit(f"{event['sevir_id']}: catalog pct_missing/projection mismatch")
    print(f"catalog_check=ok storm_vil_rows={len(rows)} selected={len(pinned)}")


# --------------------------------------------------------------------------- headers


def check_headers(headers: Path, start: int, end: int, size: int, etag: str) -> None:
    text = headers.read_text(encoding="iso-8859-1")
    blocks = [b for b in re.split(r"\r?\n\r?\n", text) if b.strip()]
    final = None
    for block in blocks:
        if re.match(r"HTTP/\S+\s+\d+", block) and not re.match(r"HTTP/\S+\s+200 Connection established", block, re.I):
            final = block
    if final is None:
        raise SystemExit(f"{headers}: no HTTP response block")
    status = int(re.match(r"HTTP/\S+\s+(\d+)", final).group(1))
    fields = {}
    for line in final.splitlines()[1:]:
        if ":" in line:
            key, value = line.split(":", 1)
            fields[key.strip().lower()] = value.strip()
    expected_range = f"bytes {start}-{end}/{size}"
    problems = []
    if status != 206:
        problems.append(f"status {status} != 206")
    if fields.get("content-range") != expected_range:
        problems.append(f"Content-Range {fields.get('content-range')!r} != {expected_range!r}")
    if fields.get("etag") != f'"{etag}"':
        problems.append(f"ETag {fields.get('etag')!r} != pinned {etag!r}")
    if fields.get("content-length") not in (None, str(end - start + 1)):
        problems.append(f"Content-Length {fields.get('content-length')} != {end - start + 1}")
    if problems:
        raise SystemExit(f"{headers.name}: " + "; ".join(problems))


# --------------------------------------------------------------------------- containers


def load_container(recipe_dir: Path, data_root: Path, stem: str) -> tuple[h5.Container, list[str]]:
    pin = containers(recipe_dir)[stem]
    size = int(pin["size_bytes"])
    head = head_path(data_root, stem).read_bytes()
    tail = tail_path(data_root, stem).read_bytes()
    n, tail_offset = h5.tail_offset_from_head(head, size)
    if n != int(pin["event_count"]) or tail_offset != int(pin["tail_offset"]):
        raise SystemExit(f"{stem}: head gives N={n} tail_offset={tail_offset}, pins say {pin['event_count']}/{pin['tail_offset']}")
    if len(tail) != int(pin["tail_bytes"]):
        raise SystemExit(f"{stem}: tail has {len(tail)} bytes, pin says {pin['tail_bytes']}")
    container = h5.parse_container(head, tail, tail_offset, size)
    ids = h5.read_event_ids(container, head, tail)
    return container, ids


def check_container(recipe_dir: Path, data_root: Path, stem: str, catalog: Path) -> None:
    container, ids = load_container(recipe_dir, data_root, stem)
    rows = [r for r in catalog_rows(catalog).values() if select_events.container_of(r["file_name"]) == stem]
    mismatched = [r["id"] for r in rows if ids[int(r["file_index"])] != r["id"]]
    if len(rows) != len(ids) or mismatched:
        raise SystemExit(f"{stem}: catalog/id dataset mismatch ({len(rows)} rows, {len(ids)} ids, {len(mismatched)} mismatched)")
    for event in events(recipe_dir):
        if event["container"] == stem and ids[int(event["file_index"])] != event["sevir_id"]:
            raise SystemExit(f"{stem}: id[{event['file_index']}] = {ids[int(event['file_index'])]} != {event['sevir_id']}")
    out = download_dir(data_root) / "containers" / f"{stem}.ids.txt"
    out.write_text("\n".join(ids) + "\n")
    vil = container.vil
    print(
        f"container_ok {stem} vil_shape={vil.shape} dtype=u{8 * vil.dtype_size} layout=contiguous@{vil.data_address} "
        f"size={vil.data_size} filters={vil.has_filter_pipeline} id_dtype=S{container.id_ds.dtype_size} catalog_rows={len(rows)}"
    )


# --------------------------------------------------------------------------- events


def find_event(recipe_dir: Path, sevir_id: str) -> dict[str, str]:
    for event in events(recipe_dir):
        if event["sevir_id"] == sevir_id:
            return event
    raise SystemExit(f"{sevir_id} is not a pinned event")


def check_event(recipe_dir: Path, data_root: Path, sevir_id: str) -> None:
    event = find_event(recipe_dir, sevir_id)
    data = event_path(data_root, event).read_bytes()
    stats, _hist = semantic_check(data, event, sha_pins(recipe_dir))
    print(
        f"event_ok {sevir_id} bytes={len(data)} min={stats['min']} max={stats['max']} distinct={stats['distinct_codes']} "
        f"zero_fraction={stats['zero_fraction']} distinct_frames={stats['distinct_frames']} sha256={stats['sha256']}"
    )


# --------------------------------------------------------------------------- build / verify


def index_row(event: dict[str, str], stats: dict) -> dict:
    return {
        "dataset_id": DATASET_ID,
        "series_id": SERIES_ID,
        "sample_path": sample_rel_path(event),
        "numeric_kind": "uint",
        "bit_width": 8,
        "endianness": "little",
        "element_size_bytes": 1,
        "sample_size_bytes": h5.EVENT_BYTES,
        "value_count": h5.EVENT_BYTES,
        "sample_shape": list(h5.EVENT_SHAPE),
        "sample_axes": SAMPLE_AXES,
        "min": stats["min"],
        "max": stats["max"],
        "sha256": stats["sha256"],
        "sevir_id": event["sevir_id"],
        "source_container": event["container"],
        "source_file_index": int(event["file_index"]),
        "source_byte_offset": h5.event_offset(int(event["file_index"])),
        "time_utc": event["time_utc"],
        "storm_event_id": event["storm_event_id"],
        "episode_id": event["episode_id"],
        "event_type": event["event_type"],
    }


def build(recipe_dir: Path, data_root: Path) -> None:
    catalog = download_dir(data_root) / "CATALOG.csv"
    check_catalog(recipe_dir, catalog)
    pins = sha_pins(recipe_dir)
    selected = events(recipe_dir)
    ids_by_container = {stem: load_container(recipe_dir, data_root, stem)[1] for stem in select_events.CONTAINERS}

    sample_dir = data_root / "samples" / DATASET_ID / SERIES_ID
    sample_dir.mkdir(parents=True, exist_ok=True)
    expected_names = {Path(sample_rel_path(e)).name for e in selected}
    for stale in sample_dir.iterdir():
        if stale.name not in expected_names:
            stale.unlink()
    index_path = data_root / "index" / DATASET_ID / "samples.jsonl"
    stats_path = data_root / "filtered" / DATASET_ID / "ingest_stats.json"
    index_path.parent.mkdir(parents=True, exist_ok=True)
    stats_path.parent.mkdir(parents=True, exist_ok=True)

    rows, per_event = [], []
    total_hist = [0] * 256
    for event in selected:
        ids = ids_by_container[event["container"]]
        if ids[int(event["file_index"])] != event["sevir_id"]:
            raise SystemExit(f"{event['sevir_id']}: HDF5 id dataset mismatch")
        data = event_path(data_root, event).read_bytes()
        stats, hist = semantic_check(data, event, pins)
        for v, count in enumerate(hist):
            total_hist[v] += count
        out = data_root / sample_rel_path(event)
        tmp = out.with_suffix(".part")
        tmp.write_bytes(data)
        tmp.replace(out)
        rows.append(index_row(event, stats))
        per_event.append({"sevir_id": event["sevir_id"], "container": event["container"], "file_index": int(event["file_index"]), **stats})
        print(f"sample {event['sevir_id']} {event['container']}[{event['file_index']}] max={stats['max']} distinct={stats['distinct_codes']} zero_fraction={stats['zero_fraction']}")

    tmp_index = index_path.with_suffix(".part")
    with tmp_index.open("w") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")
    tmp_index.replace(index_path)
    total_values = sum(r["value_count"] for r in rows)
    summary = {
        "dataset_id": DATASET_ID,
        "series_id": SERIES_ID,
        "sample_count": len(rows),
        "total_values": total_values,
        "total_bytes": total_values,
        "code_histogram": total_hist,
        "missing_code_255_total": total_hist[MISSING_CODE],
        "zero_fraction": round(total_hist[0] / total_values, 6),
        "distinct_codes": sum(1 for c in total_hist if c),
        "events": per_event,
    }
    stats_path.write_text(json.dumps(summary, indent=1) + "\n")
    print(f"build_ok samples={len(rows)} bytes={total_values} distinct_codes={summary['distinct_codes']} zero_fraction={summary['zero_fraction']}")


def verify(recipe_dir: Path, data_root: Path) -> None:
    catalog = download_dir(data_root) / "CATALOG.csv"
    check_catalog(recipe_dir, catalog)
    pins = sha_pins(recipe_dir)
    selected = events(recipe_dir)
    if set(pins) != {e["sevir_id"] for e in selected}:
        raise SystemExit("event_sha256.tsv must pin exactly the 60 selected events")

    manifest = tomllib.loads((recipe_dir / "manifest.toml").read_text())
    series = [s for s in manifest["series"] if s["id"] == SERIES_ID]
    if len(series) != 1 or series[0].get("role") != "primary":
        raise SystemExit("manifest must declare exactly one primary series " + SERIES_ID)
    series = series[0]

    index_path = data_root / "index" / DATASET_ID / "samples.jsonl"
    rows = [json.loads(line) for line in index_path.read_text().splitlines() if line.strip()]
    if len(rows) != len(selected):
        raise SystemExit(f"index has {len(rows)} rows, expected {len(selected)}")
    by_path = {}
    for row in rows:
        missing = [k for k in INDEX_KEYS if k not in row]
        if missing:
            raise SystemExit(f"index row lacks {missing}")
        if row["sample_path"] in by_path:
            raise SystemExit(f"duplicate sample_path {row['sample_path']}")
        by_path[row["sample_path"]] = row

    sample_dir = data_root / "samples" / DATASET_ID / SERIES_ID
    on_disk = sorted(p.name for p in sample_dir.iterdir())
    expected = sorted(Path(sample_rel_path(e)).name for e in selected)
    if on_disk != expected:
        raise SystemExit(f"sample directory content mismatch: extra={set(on_disk) - set(expected)} missing={set(expected) - set(on_disk)}")

    seen_digests = set()
    total = 0
    union_hist = [0] * 256
    for event in selected:
        _container, ids = load_container(recipe_dir, data_root, event["container"])
        if ids[int(event["file_index"])] != event["sevir_id"]:
            raise SystemExit(f"{event['sevir_id']}: HDF5 id dataset mismatch")
        rel = sample_rel_path(event)
        row = by_path.get(rel)
        if row is None:
            raise SystemExit(f"index lacks {rel}")
        source = event_path(data_root, event).read_bytes()
        sample = (data_root / rel).read_bytes()
        if sample != source:
            raise SystemExit(f"{rel}: bytes differ from the source range of {event['container']}[{event['file_index']}]")
        stats, hist = semantic_check(sample, event, pins)
        want = index_row(event, stats)
        if row != want:
            diff = {k: (row.get(k), want[k]) for k in want if row.get(k) != want[k]}
            raise SystemExit(f"{rel}: index row mismatch {diff}")
        if stats["sha256"] in seen_digests:
            raise SystemExit(f"{rel}: duplicate sample content")
        seen_digests.add(stats["sha256"])
        for v, count in enumerate(hist):
            union_hist[v] += count
        total += len(sample)

    if series["sample_count"] != len(rows) or series["total_size_bytes"] != total:
        raise SystemExit(
            f"manifest sample_count/total_size_bytes {series['sample_count']}/{series['total_size_bytes']} != realized {len(rows)}/{total}"
        )
    distinct = sum(1 for c in union_hist if c)
    if distinct < 200:
        raise SystemExit(f"only {distinct} distinct codes across the corpus")
    containers_hit = {e["container"] for e in selected}
    if containers_hit != set(select_events.CONTAINERS):
        raise SystemExit("selection does not span all six STORMEVENTS containers")
    print(
        f"verify_ok samples={len(rows)} bytes={total} distinct_codes={distinct} "
        f"zero_fraction={union_hist[0] / total:.6f} missing_255={union_hist[MISSING_CODE]}"
    )


# --------------------------------------------------------------------------- cli


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("check-headers")
    p.add_argument("headers", type=Path)
    p.add_argument("start", type=int)
    p.add_argument("end", type=int)
    p.add_argument("size", type=int)
    p.add_argument("etag")

    for name in ("check-catalog", "check-container", "check-event", "build", "verify"):
        q = sub.add_parser(name)
        q.add_argument("--recipe-dir", type=Path, required=True)
        q.add_argument("--data-root", type=Path, required=True)
        if name == "check-container":
            q.add_argument("--container", required=True)
        if name == "check-event":
            q.add_argument("--sevir-id", required=True)

    args = parser.parse_args()
    if args.cmd == "check-headers":
        check_headers(args.headers, args.start, args.end, args.size, args.etag)
        return 0
    recipe_dir = args.recipe_dir.resolve()
    data_root = args.data_root.resolve()
    catalog = download_dir(data_root) / "CATALOG.csv"
    if args.cmd == "check-catalog":
        check_catalog(recipe_dir, catalog)
    elif args.cmd == "check-container":
        check_container(recipe_dir, data_root, args.container, catalog)
    elif args.cmd == "check-event":
        check_event(recipe_dir, data_root, args.sevir_id)
    elif args.cmd == "build":
        build(recipe_dir, data_root)
    elif args.cmd == "verify":
        verify(recipe_dir, data_root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
