#!/usr/bin/env python3
"""Protomaps z15 building-vertex recipe: download validation, build, and verify.

Subcommands
  check-header  DOWNLOAD_DIR                  validate pinned header/root/metadata
  check-span    DOWNLOAD_DIR BLOCK_ID FILE    validate one fetched tile-data span
  build         --recipe-dir --data-root
  verify        --recipe-dir --data-root
"""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pmtiles_mvt as P  # noqa: E402

DATASET_ID = "protomaps_osm_z15_building_coords_i16"
SERIES_ID = "osm_building_vertex_xy_i16"
ARCHIVE_SIZE = 129605595792
HEADER_REGION = 16384
HEADER_SHA256 = "89ebe8c69835d5b5de67d3d27a93881291bf4e9b22dd76e5fdf61ee7c5d65419"
METADATA_SHA256 = "d75a89d6d0c10133836a49c7150e875cc463e196c48fb98737ff4284b1db130b"
EXPECTED_HEADER = {
    "root_dir_offset": 127, "root_dir_length": 15525,
    "metadata_offset": 129274242420, "metadata_length": 1155,
    "leaf_dirs_offset": 129274243575, "leaf_dirs_length": 331352217,
    "tile_data_offset": 16384, "tile_data_length": 129274226036,
    "clustered": 1, "internal_compression": 2, "tile_compression": 2, "tile_type": 1,
    "min_zoom": 0, "max_zoom": 15,
}
LAYER = "buildings"
EXTENT = 4096
BUFFER_MIN, BUFFER_MAX = -64, 4160  # 4096 extent + 64-unit planetiler tile buffer
MIN_VALUES = 1000  # tiles whose building layer has fewer values are skipped
ZOOM = 15
BLOCK = 8


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def pinned_span_sha(block: dict) -> str:
    v = (block.get("span_sha256") or "").strip()
    return "" if v in ("", "-") else v


def read_tsv(path: Path) -> list[dict]:
    with open(path, newline="") as f:
        return list(csv.DictReader(f, delimiter="\t"))


# --------------------------------------------------------------------------- archive access
class Archive:
    def __init__(self, download_dir: Path, recipe_dir: Path):
        self.dl = download_dir
        self.recipe_dir = recipe_dir
        region = (download_dir / "header_root.bin").read_bytes()
        if len(region) != HEADER_REGION or sha256_bytes(region) != HEADER_SHA256:
            raise SystemExit("header_root.bin does not match the pinned 20250120 header region")
        self.h = P.parse_header(region)
        for k, v in EXPECTED_HEADER.items():
            if self.h[k] != v:
                raise SystemExit(f"header field {k}={self.h[k]} != pinned {v}")
        s = self.h["root_dir_offset"]
        self.root = P.deserialize_directory(P.decompress(region[s:s + self.h["root_dir_length"]], 2))
        self.leaf_rows = {int(r["leaf_rel_offset"]): r for r in read_tsv(recipe_dir / "leaves.tsv")}
        self._leaves: dict[int, list] = {}

    def leaf(self, rel: int):
        if rel not in self._leaves:
            row = self.leaf_rows.get(rel)
            if row is None:
                raise SystemExit(f"leaf directory at {rel} is not pinned in leaves.tsv")
            raw = (self.dl / "leaves" / f"leaf_{rel}.gz").read_bytes()
            if len(raw) != int(row["length"]) or sha256_bytes(raw) != row["sha256"]:
                raise SystemExit(f"leaf directory {rel} fails pinned size/sha256")
            self._leaves[rel] = P.deserialize_directory(P.decompress(raw, 2))
        return self._leaves[rel]

    def entry(self, tile_id: int):
        le = P.find_entry(self.root, tile_id)
        if le is None or le[3] != 0:
            raise SystemExit(f"root entry for tile {tile_id} is not a leaf pointer")
        e = P.find_entry(self.leaf(le[1]), tile_id)
        if e is not None and e[3] == 0:
            raise SystemExit("unexpected nested leaf directory")
        return e

    def block_tiles(self, block: dict):
        """Yield (tile_id, x, y, entry_or_None, span_slice_or_None) in tile-id order."""
        x0, y0 = int(block["x0"]), int(block["y0"])
        if int(block["z"]) != ZOOM or x0 % BLOCK or y0 % BLOCK:
            raise SystemExit(f"block {block['block_id']} is not an aligned z15 8x8 block")
        span_abs = int(block["span_offset"])
        span_len = int(block["span_length"])
        rel0 = span_abs - self.h["tile_data_offset"]
        ids = sorted((P.zxy_to_tileid(ZOOM, x0 + dx, y0 + dy), x0 + dx, y0 + dy)
                     for dx in range(BLOCK) for dy in range(BLOCK))
        if ids[0][0] != int(block["first_tile_id"]) or ids[-1][0] != ids[0][0] + BLOCK * BLOCK - 1:
            raise SystemExit(f"block {block['block_id']} tile ids are not the pinned contiguous range")
        for tid, x, y in ids:
            e = self.entry(tid)
            if e is None:
                yield tid, x, y, None, None
                continue
            if rel0 <= e[1] and e[1] + e[2] <= rel0 + span_len:
                yield tid, x, y, e, (e[1] - rel0, e[1] - rel0 + e[2])
            else:
                yield tid, x, y, e, None


def decode_tile(payload: bytes) -> dict:
    tile = gzip.decompress(payload)
    d = P.decode_layer(tile, LAYER)
    if d is None:
        return {"present": False, "coords": [], "layer_names": None}
    if d["extent"] != EXTENT:
        raise SystemExit(f"buildings layer extent {d['extent']} != {EXTENT}")
    if d["version"] != 2:
        raise SystemExit(f"buildings layer MVT version {d['version']} != 2")
    c = d["coords"]
    if c and (min(c) < BUFFER_MIN or max(c) > BUFFER_MAX):
        raise SystemExit(f"building coordinate outside {BUFFER_MIN}..{BUFFER_MAX}: {min(c)}..{max(c)}")
    d["present"] = True
    return d


# --------------------------------------------------------------------------- download checks
def check_header(download_dir: Path, recipe_dir: Path) -> None:
    Archive(download_dir, recipe_dir)
    meta_raw = (download_dir / "metadata.json.gz").read_bytes()
    if len(meta_raw) != EXPECTED_HEADER["metadata_length"] or sha256_bytes(meta_raw) != METADATA_SHA256:
        raise SystemExit("metadata.json.gz fails pinned size/sha256")
    meta = json.loads(gzip.decompress(meta_raw))
    if meta.get("version") != "4.0.4" or "OpenStreetMap" not in meta.get("attribution", ""):
        raise SystemExit("unexpected Protomaps metadata version/attribution")
    if not any(layer.get("id") == LAYER and layer.get("maxzoom") == 15 for layer in meta.get("vector_layers", [])):
        raise SystemExit("metadata lacks the z15 buildings layer")
    print(f"header, root directory and metadata verified (basemap version {meta['version']}, "
          f"OSM replication {meta.get('planetiler:osm:osmosisreplicationtime')})")


def check_span(download_dir: Path, recipe_dir: Path, block_id: str, span_file: Path) -> None:
    arc = Archive(download_dir, recipe_dir)
    block = {r["block_id"]: r for r in read_tsv(recipe_dir / "blocks.tsv")}[block_id]
    data = span_file.read_bytes()
    if len(data) != int(block["span_length"]):
        raise SystemExit(f"{block_id}: span size {len(data)} != {block['span_length']}")
    pinned = pinned_span_sha(block)
    digest = sha256_bytes(data)
    if pinned and digest != pinned:
        raise SystemExit(f"{block_id}: span sha256 {digest} != pinned {pinned}")
    n_in = 0
    with_buildings = 0
    for tid, x, y, e, sl in arc.block_tiles(block):
        if sl is None:
            continue
        n_in += 1
        payload = data[sl[0]:sl[1]]
        if payload[:2] != b"\x1f\x8b":
            raise SystemExit(f"{block_id}: tile {x}/{y} payload is not gzip")
        # Transport/semantic check only (strict geometry decoding happens in build):
        # the payload must gunzip to a protobuf MVT Tile whose fields are all layers.
        tile = gzip.decompress(payload)
        names = []
        for field, wt, val in P.iter_fields(tile):
            if field != 3 or wt != 2:
                raise SystemExit(f"{block_id}: tile {x}/{y} has non-layer top-level field {field}")
            for f2, w2, v2 in P.iter_fields(tile, val[0], val[1]):
                if f2 == 1 and w2 == 2:
                    names.append(tile[v2[0]:v2[1]])
        if not names:
            raise SystemExit(f"{block_id}: tile {x}/{y} has no layers")
        with_buildings += LAYER.encode() in names
    if n_in != int(block["tiles_in_span"]):
        raise SystemExit(f"{block_id}: {n_in} tiles in span != pinned {block['tiles_in_span']}")
    print(f"{block_id}\t{digest}\ttiles={n_in}\twith_buildings={with_buildings}")


# --------------------------------------------------------------------------- build
def collect(arc: Archive, blocks: list[dict], download_dir: Path):
    """Yield per-tile records (kept or skipped) in deterministic block/tile-id order."""
    for block in blocks:
        span = (download_dir / "spans" / f"{block['block_id']}.bin").read_bytes()
        if len(span) != int(block["span_length"]):
            raise SystemExit(f"span size mismatch for {block['block_id']}")
        if pinned_span_sha(block) and sha256_bytes(span) != pinned_span_sha(block):
            raise SystemExit(f"span sha256 mismatch for {block['block_id']}")
        for tid, x, y, e, sl in arc.block_tiles(block):
            rec = {"block": block, "tile_id": tid, "x": x, "y": y}
            if e is None:
                rec["skip"] = "absent_from_archive"
            elif sl is None:
                rec["skip"] = "deduplicated_payload_outside_span"
            else:
                d = decode_tile(span[sl[0]:sl[1]])
                rec["decoded"] = d
                if not d["present"]:
                    rec["skip"] = "no_buildings_layer"
                elif len(d["coords"]) < MIN_VALUES:
                    rec["skip"] = "below_1000_values"
            yield rec


def sample_relpath(block: dict, x: int, y: int) -> str:
    return f"samples/{DATASET_ID}/{SERIES_ID}/{block['city']}__z15_x{x}_y{y}.bin"


def build(recipe_dir: Path, data_root: Path) -> None:
    dl = data_root / "downloads" / DATASET_ID
    arc = Archive(dl, recipe_dir)
    blocks = read_tsv(recipe_dir / "blocks.tsv")
    out_dir = data_root / "samples" / DATASET_ID / SERIES_ID
    out_dir.mkdir(parents=True, exist_ok=True)
    for old in out_dir.glob("*.bin"):
        old.unlink()
    index_path = data_root / "index" / DATASET_ID / "samples.jsonl"
    stats_path = data_root / "filtered" / DATASET_ID / "ingest_stats.json"
    index_path.parent.mkdir(parents=True, exist_ok=True)
    stats_path.parent.mkdir(parents=True, exist_ok=True)
    skips: dict[str, int] = {}
    per_block: dict[str, int] = {}
    per_continent: dict[str, int] = {}
    rows = []
    agg = hashlib.sha256()
    gmin, gmax = 1 << 20, -(1 << 20)
    other_types: dict[str, int] = {}
    for rec in collect(arc, blocks, dl):
        d = rec.get("decoded")
        if d and d.get("present"):
            for k, v in d["other_type_counts"].items():
                other_types[str(k)] = other_types.get(str(k), 0) + v
        if "skip" in rec:
            skips[rec["skip"]] = skips.get(rec["skip"], 0) + 1
            continue
        c = d["coords"]
        raw = struct.pack(f"<{len(c)}h", *c)
        rel = sample_relpath(rec["block"], rec["x"], rec["y"])
        (data_root / rel).write_bytes(raw)
        digest = sha256_bytes(raw)
        agg.update(digest.encode())
        lo, hi = min(c), max(c)
        gmin, gmax = min(gmin, lo), max(gmax, hi)
        b = rec["block"]
        per_block[b["block_id"]] = per_block.get(b["block_id"], 0) + 1
        per_continent[b["continent"]] = per_continent.get(b["continent"], 0) + 1
        rows.append({
            "dataset_id": DATASET_ID, "series_id": SERIES_ID, "sample_path": rel,
            "numeric_kind": "int", "bit_width": 16, "endianness": "little",
            "element_size_bytes": 2, "sample_size_bytes": len(raw), "value_count": len(c),
            "block_id": b["block_id"], "city": b["city"], "continent": b["continent"],
            "z": ZOOM, "x": rec["x"], "y": rec["y"], "tile_id": rec["tile_id"],
            "polygon_features": d["polygon_features"], "rings": d["rings"], "vertices": len(c) // 2,
            "min": lo, "max": hi, "sha256": digest,
        })
    with open(index_path, "w") as f:
        for r in rows:
            f.write(json.dumps(r, sort_keys=True) + "\n")
    vals = sorted(r["value_count"] for r in rows)
    stats = {
        "dataset_id": DATASET_ID, "series_id": SERIES_ID,
        "blocks": len(blocks), "tiles_considered": len(blocks) * BLOCK * BLOCK,
        "samples": len(rows), "total_values": sum(vals), "total_bytes": 2 * sum(vals),
        "median_values": vals[len(vals) // 2] if vals else 0,
        "min_values": vals[0] if vals else 0, "max_values": vals[-1] if vals else 0,
        "skipped": skips, "non_polygon_features_ignored": other_types,
        "samples_per_continent": per_continent, "blocks_with_samples": len(per_block),
        "coordinate_min": gmin, "coordinate_max": gmax,
        "aggregate_sha256_of_sample_sha256s": agg.hexdigest(),
    }
    stats_path.write_text(json.dumps(stats, indent=1, sort_keys=True) + "\n")
    print(json.dumps(stats, indent=1, sort_keys=True))


# --------------------------------------------------------------------------- verify
def parse_manifest_series(recipe_dir: Path) -> dict:
    try:
        import tomllib
    except ModuleNotFoundError:  # pragma: no cover
        return {}
    path = recipe_dir / "manifest.toml"
    if not path.exists():
        return {}
    m = tomllib.loads(path.read_text())
    return {s["id"]: s for s in m.get("series", [])}


def verify(recipe_dir: Path, data_root: Path) -> None:
    dl = data_root / "downloads" / DATASET_ID
    index_path = data_root / "index" / DATASET_ID / "samples.jsonl"
    stats = json.loads((data_root / "filtered" / DATASET_ID / "ingest_stats.json").read_text())
    rows = [json.loads(line) for line in index_path.read_text().splitlines() if line.strip()]
    if not rows:
        raise SystemExit("empty sample index")
    by_path = {r["sample_path"]: r for r in rows}
    if len(by_path) != len(rows):
        raise SystemExit("duplicate sample paths in index")
    on_disk = sorted(p.relative_to(data_root).as_posix()
                     for p in (data_root / "samples" / DATASET_ID / SERIES_ID).glob("*.bin"))
    if on_disk != sorted(by_path):
        raise SystemExit("sample files on disk do not match the index")
    # 1) Independent re-derivation from the downloaded archive pieces.
    arc = Archive(dl, recipe_dir)
    blocks = read_tsv(recipe_dir / "blocks.tsv")
    expected = []
    for rec in collect(arc, blocks, dl):
        if "skip" in rec:
            continue
        c = rec["decoded"]["coords"]
        expected.append((sample_relpath(rec["block"], rec["x"], rec["y"]), c))
    if [p for p, _ in expected] != [r["sample_path"] for r in rows]:
        raise SystemExit("re-derived sample list/order differs from the index")
    seen_hashes = set()
    total_values = 0
    for (rel, c), r in zip(expected, rows):
        raw = (data_root / rel).read_bytes()
        if raw != struct.pack(f"<{len(c)}h", *c):
            raise SystemExit(f"{rel}: bytes differ from re-decoded tile")
        # 2) Structural checks on the stored bytes themselves.
        n = len(raw) // 2
        if len(raw) % 4 or n != r["value_count"] or len(raw) != r["sample_size_bytes"]:
            raise SystemExit(f"{rel}: size/value_count mismatch or odd vertex count")
        if n < MIN_VALUES:
            raise SystemExit(f"{rel}: below {MIN_VALUES} values")
        vals = struct.unpack(f"<{n}h", raw)
        xs, ys = vals[0::2], vals[1::2]
        if min(vals) != r["min"] or max(vals) != r["max"]:
            raise SystemExit(f"{rel}: min/max mismatch")
        if min(vals) < BUFFER_MIN or max(vals) > BUFFER_MAX:
            raise SystemExit(f"{rel}: values outside tile buffer")
        if len(set(xs)) < 50 or len(set(ys)) < 50:
            raise SystemExit(f"{rel}: degenerate coordinate set")
        if sha256_bytes(raw) != r["sha256"]:
            raise SystemExit(f"{rel}: sha256 mismatch")
        if r["sha256"] in seen_hashes:
            raise SystemExit(f"{rel}: duplicate sample content")
        seen_hashes.add(r["sha256"])
        for k, v in (("dataset_id", DATASET_ID), ("series_id", SERIES_ID), ("numeric_kind", "int"),
                     ("bit_width", 16), ("endianness", "little"), ("element_size_bytes", 2)):
            if r[k] != v:
                raise SystemExit(f"{rel}: index field {k}={r[k]!r} != {v!r}")
        total_values += n
    vc = sorted(r["value_count"] for r in rows)
    median = vc[len(vc) // 2]
    if total_values < 10000 or median < 1000:
        raise SystemExit("acceptance floors not met")
    if stats["samples"] != len(rows) or stats["total_values"] != total_values:
        raise SystemExit("ingest_stats disagree with the index")
    series = parse_manifest_series(recipe_dir).get(SERIES_ID)
    if series is not None:
        if series["sample_count"] != len(rows) or series["total_size_bytes"] != 2 * total_values:
            raise SystemExit(f"manifest sample_count/total_size_bytes {series['sample_count']}/"
                             f"{series['total_size_bytes']} != realized {len(rows)}/{2 * total_values}")
    print(f"verified {len(rows)} samples, {total_values} int16 values ({2 * total_values} bytes), "
          f"median {median} values, blocks with samples {stats['blocks_with_samples']}")


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("check-header")
    a.add_argument("download_dir", type=Path)
    a.add_argument("recipe_dir", type=Path)
    a = sub.add_parser("check-span")
    a.add_argument("download_dir", type=Path)
    a.add_argument("recipe_dir", type=Path)
    a.add_argument("block_id")
    a.add_argument("span_file", type=Path)
    for name in ("build", "verify"):
        a = sub.add_parser(name)
        a.add_argument("--recipe-dir", type=Path, required=True)
        a.add_argument("--data-root", type=Path, required=True)
    args = ap.parse_args()
    if args.cmd == "check-header":
        check_header(args.download_dir, args.recipe_dir)
    elif args.cmd == "check-span":
        check_span(args.download_dir, args.recipe_dir, args.block_id, args.span_file)
    elif args.cmd == "build":
        build(args.recipe_dir, args.data_root)
    else:
        verify(args.recipe_dir, args.data_root)


if __name__ == "__main__":
    main()
