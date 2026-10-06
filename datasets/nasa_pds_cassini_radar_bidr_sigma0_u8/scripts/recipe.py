#!/usr/bin/env python3
"""Plan, download validation, and build for the Cassini RADAR BIBQH recipe.

  plan      emit the curl plan (local name, URL, bytes, MD5) from sources.tsv
  validate  semantically validate every downloaded ZIP (download.sh step)
  build     decode each ZIP's attached-label IMG and emit one raw uint8
            sigma0-dB image per product plus the sample index
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import os
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import bidr  # noqa: E402

CHUNK = 1 << 22
LABEL_PREFIX_BYTES = 65536


def open_member(zip_path: Path, row: dict) -> tuple[zipfile.ZipFile, zipfile.ZipInfo]:
    pid = row["product_id"]
    archive = zipfile.ZipFile(zip_path)
    infos = archive.infolist()
    if len(infos) != 1:
        raise SystemExit(f"{pid}: ZIP must contain exactly one member, found {len(infos)}")
    info = infos[0]
    if info.filename != pid + ".IMG":
        raise SystemExit(f"{pid}: ZIP member {info.filename!r} != {pid}.IMG")
    if info.compress_type != zipfile.ZIP_DEFLATED or info.flag_bits & 0x1:
        raise SystemExit(f"{pid}: ZIP member must be unencrypted DEFLATE")
    if info.file_size != row["img_bytes"]:
        raise SystemExit(f"{pid}: uncompressed size {info.file_size} != pinned {row['img_bytes']}")
    if info.compress_size != row["zip_member_compressed_bytes"]:
        raise SystemExit(f"{pid}: compressed size {info.compress_size} != pinned")
    if f"{info.CRC:08x}" != row["zip_member_crc32"]:
        raise SystemExit(f"{pid}: member CRC32 {info.CRC:08x} != pinned {row['zip_member_crc32']}")
    return archive, info


def decode_product(zip_path: Path, row: dict, sink=None) -> dict:
    """Stream-decode one product. Optionally write the image window to `sink`."""
    pid = row["product_id"]
    archive, info = open_member(zip_path, row)
    img_md5 = hashlib.md5()
    pix_sha = hashlib.sha256()
    histogram: collections.Counter = collections.Counter()
    position = 0  # stream offset of the next byte to be windowed
    geometry = None
    start = length = 0
    pending = b""
    with archive, archive.open(info) as member:  # zipfile verifies CRC32 at EOF
        while True:
            chunk = member.read(CHUNK)
            img_md5.update(chunk)
            if geometry is None:
                pending += chunk
                if chunk and len(pending) < LABEL_PREFIX_BYTES:
                    continue
                if not pending:
                    break
                label = bidr.parse_pds3(bidr.label_text_from_prefix(pending[:LABEL_PREFIX_BYTES]))
                geometry = bidr.validate_attached_label(label, row)
                start, length = bidr.image_window(geometry)
                chunk, pending = pending, b""
            elif not chunk:
                break
            chunk_begin = position
            position += len(chunk)
            lo = max(start, chunk_begin)
            hi = min(start + length, position)
            if lo < hi:
                piece = chunk[lo - chunk_begin : hi - chunk_begin]
                pix_sha.update(piece)
                histogram.update(piece)
                if sink is not None:
                    sink.write(piece)
    if geometry is None:
        raise SystemExit(f"{pid}: empty ZIP member")
    if position != row["img_bytes"]:
        raise SystemExit(f"{pid}: decoded {position} bytes, expected {row['img_bytes']}")
    if img_md5.hexdigest() != row["img_md5"]:
        raise SystemExit(f"{pid}: decoded IMG MD5 != pinned S3 ETag of the uncompressed .IMG")
    value_count = sum(histogram.values())
    if value_count != length:
        raise SystemExit(f"{pid}: image window short: {value_count} of {length}")
    checksum = sum(value * count for value, count in histogram.items())
    if checksum & 0xFFFFFFFF != geometry["image_checksum"]:
        raise SystemExit(f"{pid}: pixel sum {checksum} does not match label CHECKSUM {geometry['image_checksum']}")
    return {"geometry": geometry, "histogram": histogram, "pixel_sha256": pix_sha.hexdigest(), "pixel_sum": checksum}


def summarize(histogram: collections.Counter) -> dict:
    value_count = sum(histogram.values())
    zero = histogram.get(0, 0)
    nonzero = {value: count for value, count in histogram.items() if value != 0}
    nonzero_count = value_count - zero
    return {
        "value_count": value_count,
        "missing_count": zero,
        "missing_fraction": round(zero / value_count, 6),
        "nonzero_count": nonzero_count,
        "distinct_values": len(histogram),
        "distinct_nonzero_values": len(nonzero),
        "min": min(histogram),
        "max": max(histogram),
        "nonzero_min": min(nonzero) if nonzero else None,
        "nonzero_max": max(nonzero) if nonzero else None,
        "nonzero_mean_dn": round(sum(v * c for v, c in nonzero.items()) / nonzero_count, 4) if nonzero_count else None,
        "floor_dn1_count": histogram.get(1, 0),
    }


def reject_degenerate(pid: str, stats: dict) -> None:
    if stats["distinct_values"] < 2:
        raise SystemExit(f"{pid}: constant image")
    if stats["nonzero_count"] == 0:
        raise SystemExit(f"{pid}: image is entirely MISSING_CONSTANT")
    if stats["distinct_nonzero_values"] < 2:
        raise SystemExit(f"{pid}: non-missing pixels are constant")


def cmd_plan(args: argparse.Namespace) -> None:
    rows = bidr.read_plan(Path(args.sources))
    with open(args.out, "w", encoding="utf-8") as handle:
        handle.write("ordinal\tlocal_filename\turl\tzip_bytes\tzip_md5\n")
        for row in rows:
            handle.write(
                f"{row['ordinal']}\t{row['product_id']}.ZIP\t{bidr.zip_url(row)}\t{row['zip_bytes']}\t{row['zip_md5']}\n"
            )
    print(f"source_plan=ok products={len(rows)} zip_bytes={sum(r['zip_bytes'] for r in rows)}")


def cmd_validate(args: argparse.Namespace) -> None:
    rows = bidr.read_plan(Path(args.sources))
    download_dir = Path(args.download_dir)
    records = []
    for row in rows:
        path = download_dir / f"{row['product_id']}.ZIP"
        if path.stat().st_size != row["zip_bytes"] or bidr.md5_file(path) != row["zip_md5"]:
            raise SystemExit(f"{row['product_id']}: ZIP size or MD5 differs from pinned S3 object")
        result = decode_product(path, row)
        stats = summarize(result["histogram"])
        reject_degenerate(row["product_id"], stats)
        records.append({
            "ordinal": row["ordinal"],
            "product_id": row["product_id"],
            "volume": row["volume"],
            "url": bidr.zip_url(row),
            "zip_bytes": row["zip_bytes"],
            "zip_md5": row["zip_md5"],
            "zip_sha256": bidr.sha256_file(path),
            "img_md5": row["img_md5"],
            "pixel_sha256": result["pixel_sha256"],
            **result["geometry"],
            **{key: stats[key] for key in ("value_count", "missing_fraction", "distinct_values", "nonzero_min", "nonzero_max")},
        })
        print(
            f"validated {row['ordinal']:02d} {row['product_id']} {result['geometry']['lines']}x"
            f"{result['geometry']['line_samples']} missing={stats['missing_fraction']:.4f} "
            f"dn={stats['nonzero_min']}..{stats['nonzero_max']}"
        )
    inventory = {
        "dataset_id": bidr.DATASET_ID,
        "sources_sha256": bidr.SOURCES_SHA256,
        "products": len(records),
        "zip_bytes": sum(r["zip_bytes"] for r in records),
        "pixel_bytes": sum(r["value_count"] for r in records),
        "records": records,
    }
    if inventory["pixel_bytes"] != bidr.EXPECTED_PIXEL_BYTES:
        raise SystemExit("pixel aggregate changed")
    (download_dir / "download_inventory.json").write_text(json.dumps(inventory, indent=2) + "\n", encoding="utf-8")
    print(f"semantic_validation=ok products={len(records)} zip_bytes={inventory['zip_bytes']} pixel_bytes={inventory['pixel_bytes']}")


def cmd_build(args: argparse.Namespace) -> None:
    rows = bidr.read_plan(Path(args.sources))
    data_root = Path(args.data_root).resolve()
    download_dir = Path(args.download_dir)
    series_dir = data_root / "samples" / bidr.DATASET_ID / bidr.SERIES_ID
    index_path = data_root / "index" / bidr.DATASET_ID / "samples.jsonl"
    stats_path = data_root / "filtered" / bidr.DATASET_ID / "ingest_stats.json"
    for directory in (series_dir, index_path.parent, stats_path.parent):
        directory.mkdir(parents=True, exist_ok=True)
    expected_names = {f"{row['ordinal']:02d}_{row['product_id']}.u8" for row in rows}
    for stale in series_dir.iterdir():
        if stale.name not in expected_names:
            stale.unlink()
    index_rows = []
    totals = collections.Counter()
    for row in rows:
        zip_path = download_dir / f"{row['product_id']}.ZIP"
        if not zip_path.is_file():
            raise SystemExit(f"missing local download {zip_path}; run download.sh first")
        if zip_path.stat().st_size != row["zip_bytes"] or bidr.md5_file(zip_path) != row["zip_md5"]:
            raise SystemExit(f"{row['product_id']}: local ZIP differs from pinned S3 object")
        out = series_dir / f"{row['ordinal']:02d}_{row['product_id']}.u8"
        part = out.with_name(out.name + ".part")
        with part.open("wb") as sink:
            result = decode_product(zip_path, row, sink)
        os.replace(part, out)
        geometry = result["geometry"]
        stats = summarize(result["histogram"])
        reject_degenerate(row["product_id"], stats)
        size = out.stat().st_size
        if size != geometry["lines"] * geometry["line_samples"]:
            raise SystemExit(f"{row['product_id']}: sample size mismatch")
        index_rows.append({
            "dataset_id": bidr.DATASET_ID,
            "series_id": bidr.SERIES_ID,
            "sample_path": str(out.relative_to(data_root)),
            "numeric_kind": "uint",
            "bit_width": 8,
            "endianness": "little",
            "element_size_bytes": 1,
            "sample_size_bytes": size,
            "value_count": stats["value_count"],
            "sample_shape": [geometry["lines"], geometry["line_samples"]],
            "sample_axes": ["line", "sample"],
            "product_id": row["product_id"],
            "volume": row["volume"],
            "flyby": row["flyby"],
            "segment": row["segment"],
            "start_time": row["start_time"],
            "stop_time": row["stop_time"],
            "label_checksum": geometry["image_checksum"],
            "scaling_factor": float(bidr.SCALING_FACTOR),
            "offset": float(bidr.OFFSET),
            "missing_constant": 0,
            "sha256": result["pixel_sha256"],
            **{key: stats[key] for key in (
                "min", "max", "missing_count", "missing_fraction", "nonzero_count", "distinct_values",
                "distinct_nonzero_values", "nonzero_min", "nonzero_max", "nonzero_mean_dn", "floor_dn1_count",
            )},
        })
        totals["samples"] += 1
        totals["bytes"] += size
        totals["missing"] += stats["missing_count"]
        totals["floor_dn1"] += stats["floor_dn1_count"]
        print(
            f"built {row['ordinal']:02d} {row['product_id']} shape={geometry['lines']}x{geometry['line_samples']} "
            f"missing={stats['missing_fraction']:.4f} distinct_nonzero={stats['distinct_nonzero_values']} "
            f"dn={stats['nonzero_min']}..{stats['nonzero_max']}"
        )
    part = index_path.with_name(index_path.name + ".part")
    part.write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in index_rows), encoding="utf-8")
    os.replace(part, index_path)
    ingest = {
        "dataset_id": bidr.DATASET_ID,
        "series_id": bidr.SERIES_ID,
        "sources_sha256": bidr.SOURCES_SHA256,
        "sample_count": totals["samples"],
        "total_size_bytes": totals["bytes"],
        "missing_fraction": round(totals["missing"] / totals["bytes"], 6),
        "floor_dn1_fraction_of_nonmissing": round(totals["floor_dn1"] / (totals["bytes"] - totals["missing"]), 6),
        "flybys": sorted({r["flyby"] for r in index_rows}, key=lambda f: bidr.flyby_order(f[1:])),
        "median_sample_values": sorted(r["value_count"] for r in index_rows)[len(index_rows) // 2],
    }
    stats_path.write_text(json.dumps(ingest, indent=2) + "\n", encoding="utf-8")
    if totals["bytes"] != bidr.EXPECTED_PIXEL_BYTES or totals["samples"] != bidr.EXPECTED_PRODUCTS:
        raise SystemExit("built totals differ from pinned aggregates")
    print(f"build_ok samples={totals['samples']} bytes={totals['bytes']} missing_fraction={ingest['missing_fraction']}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    for name in ("plan", "validate", "build"):
        cmd = sub.add_parser(name)
        cmd.add_argument("--sources", required=True)
        if name == "plan":
            cmd.add_argument("--out", required=True)
        else:
            cmd.add_argument("--download-dir", required=True)
        if name == "build":
            cmd.add_argument("--data-root", required=True)
    args = parser.parse_args()
    try:
        {"plan": cmd_plan, "validate": cmd_validate, "build": cmd_build}[args.cmd](args)
    except (ValueError, zipfile.BadZipFile) as exc:  # label/ZIP schema violations are fatal
        raise SystemExit(f"{args.cmd} failed: {exc}") from exc


if __name__ == "__main__":
    main()
