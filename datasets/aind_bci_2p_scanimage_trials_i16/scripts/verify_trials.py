#!/usr/bin/env python3
"""Independent verification for aind_bci_2p_scanimage_trials_i16.

Deliberately does not import the build module. It re-walks every pinned
BigTIFF with its own generic tag reader, re-derives the expected sample bytes
from the strips, and compares them with the emitted samples, the sample index,
and the manifest. Missing-value policy (same as build): no values are
dropped, imputed, or sentinel-coded; every page of every pinned trial must be
present and complete, otherwise verification fails.
"""
from __future__ import annotations

import argparse
import array
import collections
import csv
import hashlib
import json
import struct
import sys
import tomllib
from pathlib import Path

DATASET_ID = "aind_bci_2p_scanimage_trials_i16"
SERIES_ID = "bci_2p_trial_movie_i16"
WIDTH, HEIGHT = 512, 256
FRAME_VALUES = WIDTH * HEIGHT
FRAME_BYTES = 2 * FRAME_VALUES
TYPE_FORMATS = {3: "H", 4: "I", 16: "Q"}


def die(message: str) -> None:
    print(f"VERIFY FAILED: {message}", file=sys.stderr)
    raise SystemExit(1)


def read_tag(handle, entry: bytes) -> tuple[int, list]:
    tag, typ, count = struct.unpack_from("<HHQ", entry, 0)
    if typ == 2:
        return tag, []
    fmt = TYPE_FORMATS.get(typ)
    if fmt is None:
        return tag, []
    width = struct.calcsize(fmt)
    if width * count <= 8:
        raw = entry[12 : 12 + width * count]
    else:
        pointer = struct.unpack_from("<Q", entry, 12)[0]
        here = handle.tell()
        handle.seek(pointer)
        raw = handle.read(width * count)
        handle.seek(here)
    return tag, list(struct.unpack("<" + fmt * count, raw))


def tiff_strips(path: Path) -> list[tuple[int, int]]:
    """Return (offset, byte_count) for the single strip of every page."""
    size = path.stat().st_size
    strips: list[tuple[int, int]] = []
    with path.open("rb") as handle:
        head = handle.read(16)
        if head[:4] != b"II+\x00":
            die(f"{path.name}: not a little-endian BigTIFF")
        ifd = struct.unpack_from("<Q", head, 8)[0]
        while ifd:
            handle.seek(ifd)
            (count,) = struct.unpack("<Q", handle.read(8))
            entries = handle.read(20 * count)
            (next_ifd,) = struct.unpack("<Q", handle.read(8))
            tags = {}
            for index in range(count):
                tag, values = read_tag(handle, entries[20 * index : 20 * index + 20])
                tags[tag] = values
            expect = {256: [WIDTH], 257: [HEIGHT], 258: [16], 259: [1], 277: [1], 279: [FRAME_BYTES], 339: [2]}
            for tag, value in expect.items():
                if tags.get(tag) != value:
                    die(f"{path.name} page {len(strips)}: tag {tag} = {tags.get(tag)}, expected {value}")
            offsets = tags.get(273, [])
            if len(offsets) != 1 or offsets[0] + FRAME_BYTES > size:
                die(f"{path.name} page {len(strips)}: bad strip offsets {offsets}")
            strips.append((offsets[0], FRAME_BYTES))
            if next_ifd and next_ifd <= ifd:
                die(f"{path.name}: IFD chain not monotonic")
            ifd = next_ifd
    if not strips or strips[-1][0] + FRAME_BYTES != size:
        die(f"{path.name}: final page does not end at end of file")
    return strips


def load_sources(path: Path) -> list[dict]:
    with path.open(encoding="utf-8", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle, delimiter="\t")]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--recipe-dir", type=Path, required=True)
    parser.add_argument("--data-root", type=Path, required=True)
    args = parser.parse_args()
    recipe = args.recipe_dir
    root = args.data_root
    manifest = tomllib.loads((recipe / "manifest.toml").read_text(encoding="utf-8"))
    if manifest.get("dataset_id") != DATASET_ID:
        die("manifest dataset_id mismatch")
    series = [s for s in manifest.get("series", []) if s.get("id") == SERIES_ID]
    if len(series) != 1 or len(manifest.get("series", [])) != 1:
        die("manifest must declare exactly the one primary series")
    series = series[0]
    if (series.get("role"), series.get("numeric_kind"), series.get("bit_width"), series.get("endianness")) != (
        "primary",
        "int",
        16,
        "little",
    ):
        die("manifest series type declaration changed")

    sources = load_sources(recipe / "sources.tsv")
    trials = sorted((row for row in sources if row["kind"] == "trial_tiff"), key=lambda row: row["subject_id"])
    downloads = root / "downloads" / DATASET_ID
    for row in sources:
        if row["kind"] == "data_description":
            doc = json.loads((downloads / row["local_name"]).read_text(encoding="utf-8"))
            if doc.get("license") != "CC-BY-4.0" or doc.get("restrictions") not in (None, ""):
                die(f"{row['local_name']}: license/restrictions changed")

    index_path = root / "index" / DATASET_ID / "samples.jsonl"
    index_rows = [json.loads(line) for line in index_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    by_key = {row.get("source_key"): row for row in index_rows}
    if len(index_rows) != len(trials) or len(by_key) != len(trials):
        die(f"index has {len(index_rows)} rows for {len(trials)} pinned trials")
    if len({row["subject_id"] for row in trials}) != len(trials):
        die("pinned trials are not one per subject")

    samples_dir = root / series["output_path"]
    on_disk = sorted(p.name for p in samples_dir.iterdir()) if samples_dir.is_dir() else []
    indexed = sorted(Path(row["sample_path"]).name for row in index_rows)
    if on_disk != indexed:
        die(f"sample directory contents differ from index: {set(on_disk) ^ set(indexed)}")

    total_bytes = 0
    report = []
    for trial in trials:
        row = by_key.get(trial["key"])
        if row is None:
            die(f"no index row for {trial['key']}")
        frames = int(trial["expected_frames"])
        fixed = {
            "dataset_id": DATASET_ID,
            "series_id": SERIES_ID,
            "numeric_kind": "int",
            "bit_width": 16,
            "endianness": "little",
            "element_size_bytes": 2,
            "value_count": frames * FRAME_VALUES,
            "sample_size_bytes": frames * FRAME_BYTES,
            "shape": [frames, HEIGHT, WIDTH],
            "subject_id": trial["subject_id"],
            "source_version_id": trial["version_id"],
        }
        for key, value in fixed.items():
            if row.get(key) != value:
                die(f"{trial['key']}: index {key} = {row.get(key)!r}, expected {value!r}")
        sample = root / row["sample_path"]
        if not sample.is_file() or sample.stat().st_size != frames * FRAME_BYTES:
            die(f"{sample}: missing or wrong size")

        source = downloads / trial["local_name"]
        if source.stat().st_size != int(trial["size_bytes"]):
            die(f"{source.name}: source size changed")
        strips = tiff_strips(source)
        if len(strips) != frames:
            die(f"{source.name}: {len(strips)} pages, pinned {frames}")
        expected = hashlib.sha256()
        actual = hashlib.sha256()
        counts: collections.Counter = collections.Counter()
        with source.open("rb") as src, sample.open("rb") as out:
            for page, (offset, count) in enumerate(strips):
                src.seek(offset)
                want = src.read(count)
                got = out.read(FRAME_BYTES)
                if want != got:
                    die(f"{sample.name}: frame {page} differs from source strip")
                expected.update(want)
                actual.update(got)
                if got == got[:2] * FRAME_VALUES:
                    die(f"{sample.name}: frame {page} is constant")
                values = array.array("h")
                values.frombytes(got)
                if sys.byteorder != "little":
                    values.byteswap()
                counts.update(values)
            if out.read(1):
                die(f"{sample.name}: trailing bytes")
        if expected.hexdigest() != row.get("sample_sha256") or actual.hexdigest() != row.get("sample_sha256"):
            die(f"{sample.name}: SHA-256 differs from index")
        if trial["sha256"] not in ("-", ""):
            source_sha = hashlib.sha256(source.read_bytes()).hexdigest()
            if source_sha != trial["sha256"]:
                die(f"{source.name}: source SHA-256 differs from pin")
        minimum, maximum = min(counts), max(counts)
        if (minimum, maximum, len(counts)) != (row.get("min"), row.get("max"), row.get("distinct_values")):
            die(f"{sample.name}: min/max/distinct differ from index")
        if len(counts) < 256 or not minimum < 0 < maximum:
            die(f"{sample.name}: degenerate or not offset-subtracted (min={minimum} max={maximum} distinct={len(counts)})")
        negative = sum(c for v, c in counts.items() if v < 0) / (frames * FRAME_VALUES)
        total_bytes += frames * FRAME_BYTES
        report.append(
            {"sample": sample.name, "frames": frames, "min": minimum, "max": maximum, "distinct": len(counts), "negative_fraction": round(negative, 6)}
        )
        print(f"verified {sample.name} frames={frames} min={minimum} max={maximum} distinct={len(counts)}", flush=True)

    if series.get("sample_count") != len(index_rows) or series.get("total_size_bytes") != total_bytes:
        die(f"manifest sample_count/total_size_bytes ({series.get('sample_count')}/{series.get('total_size_bytes')}) != realized ({len(index_rows)}/{total_bytes})")
    if total_bytes > 1_000_000_000:
        die("primary output exceeds 1,000,000,000 bytes")
    out_path = root / "filtered" / DATASET_ID / "verify_report.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps({"samples": report, "total_bytes": total_bytes}, indent=1) + "\n", encoding="utf-8")
    print(f"verify_ok samples={len(index_rows)} bytes={total_bytes}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
