#!/usr/bin/env python3
"""MegaScenes COLMAP points3D.bin -> raw little-endian float64 samples.

Pure standard library. Subcommands:

  plan     parse saved S3 ListObjectsV2 XML pages into a pinned sources.tsv
  check    validate that one downloaded points3D.bin parses exactly to EOF
  build    emit XYZ and reprojection-error samples plus the sample index
  verify   independently re-derive every sample from the downloads and compare
  selftest round-trip a synthetic points3D.bin through the parser

COLMAP binary points3D layout (src/colmap/scene/reconstruction_io.cc,
WritePoints3DBinary): uint64 num_points, then per point
  uint64 point3D_id, double x, double y, double z, uint8 r, uint8 g, uint8 b,
  double error, uint64 track_length, track_length * (uint32 image_id,
  uint32 point2D_idx)
all little-endian.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import struct
import sys
from pathlib import Path

DATASET_ID = "megascenes_colmap_sfm_point_xyz_f64"
XYZ_SERIES = "sfm_point_xyz_f64"
ERR_SERIES = "sfm_point_reproj_error_f64"
MIN_POINTS = 334  # 334 points * 3 = 1002 XYZ values: models below this are dropped
BASE_URL = "https://megascenes.s3.us-west-2.amazonaws.com/"
KEY_RE = re.compile(r"^reconstruct/(\d{3})/(\d{3})/colmap/(\d+)/points3D\.bin$")
HEADER = struct.Struct("<Q")
POINT = struct.Struct("<QdddBBBdQ")  # 51 bytes
TRACK_ELEM = 8
SOURCES_HEADER = ["key", "filename", "size_bytes", "md5", "last_modified", "url"]


def parse_points3d(data: bytes):
    """Return (ids, xyz list, err list, track_lengths). Raise on any structural defect."""
    if len(data) < HEADER.size:
        raise ValueError("file shorter than header")
    (count,) = HEADER.unpack_from(data, 0)
    if count * (POINT.size) + HEADER.size > len(data):
        raise ValueError(f"declared {count} points cannot fit in {len(data)} bytes")
    offset = HEADER.size
    ids = []
    xyz = []
    err = []
    tracks = []
    unpack = POINT.unpack_from
    size = len(data)
    for _ in range(count):
        if offset + POINT.size > size:
            raise ValueError("truncated point record")
        pid, x, y, z, _r, _g, _b, e, tlen = unpack(data, offset)
        offset += POINT.size
        if tlen < 1 or offset + tlen * TRACK_ELEM > size:
            raise ValueError(f"bad track length {tlen} at point {pid}")
        offset += tlen * TRACK_ELEM
        ids.append(pid)
        xyz.append(x)
        xyz.append(y)
        xyz.append(z)
        err.append(e)
        tracks.append(tlen)
    if offset != size:
        raise ValueError(f"parse ended at {offset}, file has {size} bytes")
    for v in xyz:
        if not math.isfinite(v):
            raise ValueError("non-finite coordinate")
    for v in err:
        if not math.isfinite(v) or v < 0.0:
            raise ValueError("non-finite or negative reprojection error")
    if len(set(ids)) != len(ids):
        raise ValueError("duplicate point3D_id")
    return ids, xyz, err, tracks


def pack_f64(values) -> bytes:
    return struct.pack(f"<{len(values)}d", *values)


def read_sources(path: Path) -> list[dict]:
    lines = path.read_text(encoding="utf-8").splitlines()
    if not lines or lines[0].split("\t") != SOURCES_HEADER:
        raise RuntimeError("sources.tsv header mismatch")
    rows = []
    for line in lines[1:]:
        if not line.strip():
            continue
        parts = line.split("\t")
        if len(parts) != len(SOURCES_HEADER):
            raise RuntimeError(f"bad sources row: {line!r}")
        row = dict(zip(SOURCES_HEADER, parts))
        row["size_bytes"] = int(row["size_bytes"])
        rows.append(row)
    return rows


def sample_name(key: str) -> str:
    m = KEY_RE.match(key)
    if not m:
        raise RuntimeError(f"unexpected key {key}")
    return f"{m.group(1)}_{m.group(2)}_model{int(m.group(3)):02d}"


# ---------------------------------------------------------------- plan
def cmd_plan(args) -> None:
    pattern = re.compile(
        r"<Contents><Key>([^<]*)</Key><LastModified>([^<]*)</LastModified>"
        r"<ETag>&quot;([0-9a-f]{32})&quot;</ETag><Size>(\d+)</Size>"
    )
    rows = []
    for page in args.pages:
        text = Path(page).read_text(encoding="utf-8")
        for key, modified, etag, size in pattern.findall(text):
            if KEY_RE.match(key):
                rows.append((key, sample_name(key) + ".points3D.bin", size, etag, modified, BASE_URL + key))
    rows.sort()
    if len({r[0] for r in rows}) != len(rows):
        raise RuntimeError("duplicate keys in listing")
    out = ["\t".join(SOURCES_HEADER)] + ["\t".join(r) for r in rows]
    Path(args.out).write_text("\n".join(out) + "\n", encoding="utf-8")
    print(f"planned files={len(rows)} bytes={sum(int(r[2]) for r in rows)}")


# ---------------------------------------------------------------- check
def cmd_check(args) -> None:
    data = Path(args.file).read_bytes()
    ids, xyz, err, tracks = parse_points3d(data)
    print(f"ok points={len(ids)} mean_track={sum(tracks) / max(1, len(tracks)):.3f}")


# ---------------------------------------------------------------- build / verify
def derive(data_root: Path, sources: list[dict], write: bool):
    download_dir = data_root / "downloads" / DATASET_ID / "points3d"
    sample_root = data_root / "samples" / DATASET_ID
    records = []
    stats = {"source_count": 0, "source_bytes": 0, "dropped_small_models": [], "kept_models": 0,
             "points": 0, "track_entries": 0}
    seen_hashes: dict[str, str] = {}
    for src in sources:
        path = download_dir / src["filename"]
        data = path.read_bytes()
        if len(data) != src["size_bytes"]:
            raise RuntimeError(f"size mismatch {src['filename']}")
        if hashlib.md5(data).hexdigest() != src["md5"]:
            raise RuntimeError(f"md5 mismatch {src['filename']}")
        stats["source_count"] += 1
        stats["source_bytes"] += len(data)
        ids, xyz, err, tracks = parse_points3d(data)
        name = sample_name(src["key"])
        if len(ids) < MIN_POINTS:
            stats["dropped_small_models"].append({"key": src["key"], "points": len(ids)})
            continue
        stats["kept_models"] += 1
        stats["points"] += len(ids)
        stats["track_entries"] += sum(tracks)
        for sid, values in ((XYZ_SERIES, xyz), (ERR_SERIES, err)):
            if min(values) == max(values):
                raise RuntimeError(f"constant {sid} in {src['key']}")
            raw = pack_f64(values)
            digest = hashlib.sha256(raw).hexdigest()
            if digest in seen_hashes:
                raise RuntimeError(f"duplicate {sid} output {name} == {seen_hashes[digest]}")
            seen_hashes[digest] = name
            rel = Path("samples") / DATASET_ID / sid / f"{name}.bin"
            out = data_root / rel
            if write:
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_bytes(raw)
            else:
                if not out.is_file():
                    raise RuntimeError(f"missing sample {rel}")
                if hashlib.sha256(out.read_bytes()).hexdigest() != digest:
                    raise RuntimeError(f"sample bytes differ from source-derived values: {rel}")
            stored = struct.unpack(f"<{len(values)}d", raw)
            records.append({
                "dataset_id": DATASET_ID,
                "series_id": sid,
                "sample_path": rel.as_posix(),
                "numeric_kind": "float",
                "bit_width": 64,
                "endianness": "little",
                "element_size_bytes": 8,
                "sample_size_bytes": len(raw),
                "value_count": len(values),
                "source_key": src["key"],
                "source_md5": src["md5"],
                "point_count": len(ids),
                "min": min(stored),
                "max": max(stored),
                "sha256": digest,
            })
    for sid in (XYZ_SERIES, ERR_SERIES):
        rows = [r for r in records if r["series_id"] == sid]
        stats[sid] = {"samples": len(rows), "values": sum(r["value_count"] for r in rows),
                      "bytes": sum(r["sample_size_bytes"] for r in rows)}
    if write:
        # Remove stale samples from earlier builds so the tree matches the index.
        expected = {r["sample_path"] for r in records}
        for sid in (XYZ_SERIES, ERR_SERIES):
            for f in sorted((sample_root / sid).glob("*.bin")):
                if f.relative_to(data_root).as_posix() not in expected:
                    f.unlink()
    else:
        for sid in (XYZ_SERIES, ERR_SERIES):
            present = {f.relative_to(data_root).as_posix() for f in (sample_root / sid).glob("*.bin")}
            expected = {r["sample_path"] for r in records if r["series_id"] == sid}
            if present != expected:
                raise RuntimeError(f"sample tree for {sid} has unexpected files: {sorted(present - expected)[:5]}")
    return records, stats


def cmd_build_verify(args, write: bool) -> None:
    data_root = (Path(args.repo_root) / args.data_dir).resolve()
    sources = read_sources(Path(args.sources))
    if len(sources) != args.expect_files:
        raise RuntimeError(f"expected {args.expect_files} sources, got {len(sources)}")
    index_path = data_root / "index" / DATASET_ID / "samples.jsonl"
    stats_path = data_root / "filtered" / DATASET_ID / "ingest_stats.json"
    records, stats = derive(data_root, sources, write)
    if write:
        index_path.parent.mkdir(parents=True, exist_ok=True)
        stats_path.parent.mkdir(parents=True, exist_ok=True)
        index_path.write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in records), encoding="utf-8")
        stats_path.write_text(json.dumps(stats, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        verb = "built"
    else:
        existing = [json.loads(l) for l in index_path.read_text(encoding="utf-8").splitlines() if l.strip()]
        if existing != records:
            raise RuntimeError("sample index differs from fresh source-derived records")
        if json.loads(stats_path.read_text(encoding="utf-8")) != stats:
            raise RuntimeError("ingest stats differ from fresh source-derived stats")
        if args.manifest:
            import tomllib
            manifest = tomllib.loads(Path(args.manifest).read_text(encoding="utf-8"))
            for series in manifest["series"]:
                got = stats.get(series["id"])
                if got is None:
                    raise RuntimeError(f"manifest series {series['id']} not produced")
                if series["sample_count"] != got["samples"] or series["total_size_bytes"] != got["bytes"]:
                    raise RuntimeError(f"manifest counts for {series['id']} != realized {got}")
        verb = "verified"
    xyz_counts = sorted(r["value_count"] for r in records if r["series_id"] == XYZ_SERIES)
    median = xyz_counts[len(xyz_counts) // 2] if xyz_counts else 0
    print(f"{verb} sources={stats['source_count']} kept_models={stats['kept_models']} "
          f"dropped_small={len(stats['dropped_small_models'])} points={stats['points']} "
          f"xyz={stats[XYZ_SERIES]} err={stats[ERR_SERIES]} median_xyz_values={median}")


# ---------------------------------------------------------------- selftest
def cmd_selftest(_args) -> None:
    import random
    rng = random.Random(7)
    pts = []
    blob = bytearray(HEADER.pack(5))
    for i in range(5):
        x, y, z = (rng.uniform(-10, 10) for _ in range(3))
        e = rng.uniform(0, 2)
        tlen = rng.randint(2, 6)
        pts.append((1000 + i * 3, x, y, z, e, tlen))
        blob += POINT.pack(1000 + i * 3, x, y, z, 1, 2, 3, e, tlen)
        for j in range(tlen):
            blob += struct.pack("<II", j + 1, rng.randint(0, 9999))
    ids, xyz, err, tracks = parse_points3d(bytes(blob))
    assert ids == [p[0] for p in pts]
    assert xyz == [v for p in pts for v in p[1:4]]
    assert err == [p[4] for p in pts]
    assert tracks == [p[5] for p in pts]
    for bad in (bytes(blob[:-1]), bytes(blob) + b"\0"):
        try:
            parse_points3d(bad)
        except ValueError:
            pass
        else:
            raise AssertionError("defective blob accepted")
    assert struct.unpack("<15d", pack_f64(xyz)) == tuple(xyz)
    print("selftest ok")


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("plan")
    p.add_argument("--out", required=True)
    p.add_argument("pages", nargs="+")
    p = sub.add_parser("check")
    p.add_argument("file")
    for name in ("build", "verify"):
        p = sub.add_parser(name)
        p.add_argument("--repo-root", required=True)
        p.add_argument("--data-dir", required=True)
        p.add_argument("--sources", required=True)
        p.add_argument("--expect-files", type=int, required=True)
        p.add_argument("--manifest")
    sub.add_parser("selftest")
    args = parser.parse_args()
    if args.cmd == "plan":
        cmd_plan(args)
    elif args.cmd == "check":
        cmd_check(args)
    elif args.cmd == "build":
        cmd_build_verify(args, True)
    elif args.cmd == "verify":
        cmd_build_verify(args, False)
    else:
        cmd_selftest(args)


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, ValueError, AssertionError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
