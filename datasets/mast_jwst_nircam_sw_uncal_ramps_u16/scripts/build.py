#!/usr/bin/env python3
"""Emit one little-endian uint16 SCI ramp cube (8 x 2048 x 2048) per pinned NIRCam SW uncal file."""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from array import array
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import jwst_uncal as ju  # noqa: E402

NX = ju.GEOMETRY["NAXIS1"]
NY = ju.GEOMETRY["NAXIS2"]
NG = ju.GEOMETRY["NAXIS3"]
PLANE = NX * NY
REF = 4  # reference-pixel border width (rows/columns) of the H2RG full frame
MIN_DISTINCT = 1024
EXPECTED_SOURCES = 12
NATURAL_RECORD_KIND = "jwst_nircam_sw_full_frame_exposure_sci_ramp"
SAMPLE_AXES = ["group", "dms_row_y", "dms_column_x"]


def cube_stats(values: array) -> dict:
    """Per-group statistics on the stored uint16 values (FITS order: x fastest, then y, group)."""
    groups = []
    interior_lo, interior_hi = REF * NX, (NY - REF) * NX
    for g in range(NG):
        plane = values[g * PLANE:(g + 1) * PLANE]
        interior = plane[interior_lo:interior_hi]
        ref_rows = plane[:interior_lo] + plane[interior_hi:]
        groups.append({
            "min": min(plane),
            "max": max(plane),
            "interior_row_mean": round(sum(interior) / len(interior), 4),
            "reference_row_mean": round(sum(ref_rows) / len(ref_rows), 4),
            "sha256": hashlib.sha256(plane.tobytes()).hexdigest(),
        })
    return {
        "minimum": min(g["min"] for g in groups),
        "maximum": max(g["max"] for g in groups),
        "distinct_values": len(set(values)),
        "saturated_65535": values.count(65535),
        "zero_values": values.count(0),
        "groups": groups,
    }


def check_stats(stats: dict, name: str) -> None:
    if stats["distinct_values"] < MIN_DISTINCT:
        raise SystemExit(f"{name}: only {stats['distinct_values']} distinct values")
    for g, group in enumerate(stats["groups"]):
        if group["min"] == group["max"]:
            raise SystemExit(f"{name}: group {g + 1} is constant")
    hashes = [g["sha256"] for g in stats["groups"]]
    if len(set(hashes)) != len(hashes):
        raise SystemExit(f"{name}: two groups of the ramp are identical")
    first, last = stats["groups"][0]["interior_row_mean"], stats["groups"][-1]["interior_row_mean"]
    if not last > first:
        raise SystemExit(f"{name}: no accumulated signal up the ramp (group 1 mean {first}, group {NG} mean {last})")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--recipe-dir", type=Path, required=True)
    args = parser.parse_args()
    data_dir = args.data_dir
    sources = ju.read_sources(args.recipe_dir / "sources.tsv")
    if len(sources) != EXPECTED_SOURCES:
        raise SystemExit(f"expected {EXPECTED_SOURCES} sources, found {len(sources)}")
    download_dir = data_dir / "downloads" / ju.DATASET_ID / "uncal"
    sample_root = data_dir / "samples" / ju.DATASET_ID
    series_dir = sample_root / ju.SERIES_ID
    index_dir = data_dir / "index" / ju.DATASET_ID
    filtered_dir = data_dir / "filtered" / ju.DATASET_ID
    for path in (sample_root, index_dir):
        if path.exists():
            shutil.rmtree(path)
    series_dir.mkdir(parents=True)
    index_dir.mkdir(parents=True)
    filtered_dir.mkdir(parents=True, exist_ok=True)

    rows = []
    records = []
    seen: dict[str, str] = {}
    aggregate = hashlib.sha256()
    for source in sources:
        name = source["filename"]
        path = download_dir / name
        if not path.is_file():
            raise SystemExit(f"missing local download {path}; run download.sh first")
        buf = path.read_bytes()
        if len(buf) != int(source["size_bytes"]):
            raise SystemExit(f"{name}: size {len(buf)} != pinned {source['size_bytes']}")
        if source.get("sha256"):
            digest = hashlib.sha256(buf).hexdigest()
            if digest != source["sha256"]:
                raise SystemExit(f"{name}: SHA-256 {digest} != pinned {source['sha256']}")
            content_pin = "sha256"
        else:
            crc = ju.crc64nvme_b64(buf)
            if crc != source["crc64nvme"]:
                raise SystemExit(f"{name}: CRC64-NVME {crc} != pinned {source['crc64nvme']}")
            content_pin = "crc64nvme"
        try:
            sci = ju.validate(buf, source)
        except ju.UncalError as exc:
            raise SystemExit(f"{name}: {exc}") from exc
        sample = ju.decode_sci_le(buf, sci)
        del buf
        if len(sample) != NG * PLANE * 2:
            raise SystemExit(f"{name}: decoded {len(sample)} bytes, expected {NG * PLANE * 2}")
        values = array("H")
        values.frombytes(sample)
        if sys.byteorder == "big":
            values.byteswap()
        stats = cube_stats(values)
        del values
        check_stats(stats, name)
        sample_hash = hashlib.sha256(sample).hexdigest()
        if sample_hash in seen:
            raise SystemExit(f"{name} duplicates {seen[sample_hash]}")
        seen[sample_hash] = name
        stem = name[: -len("_uncal.fits")]
        sample_path = series_dir / f"{stem}.u16"
        tmp = sample_path.with_suffix(".u16.part")
        tmp.write_bytes(sample)
        tmp.rename(sample_path)
        aggregate.update(sample_hash.encode("ascii"))
        rows.append({
            "dataset_id": ju.DATASET_ID,
            "series_id": ju.SERIES_ID,
            "sample_path": str(sample_path.relative_to(data_dir)),
            "numeric_kind": "uint",
            "bit_width": 16,
            "endianness": "little",
            "element_size_bytes": 2,
            "sample_size_bytes": len(sample),
            "value_count": len(sample) // 2,
            "role": "primary",
            "sample_shape": [NG, NY, NX],
            "sample_axes": SAMPLE_AXES,
            "natural_record_kind": NATURAL_RECORD_KIND,
            "source_file": name,
            "source_url": source["url"],
            "source_content_pin": content_pin,
            "detector": source["detector"],
            "filter": source["filter"],
            "act_id": source["act_id"],
            "exposure": int(source["exposure"]),
            "date_obs": source["date_obs"],
            "time_obs": source["time_obs"],
            "sdp_ver": source["sdp_ver"],
            "minimum": stats["minimum"],
            "maximum": stats["maximum"],
            "distinct_values": stats["distinct_values"],
            "saturated_65535": stats["saturated_65535"],
            "group_interior_row_mean": [g["interior_row_mean"] for g in stats["groups"]],
            "sha256": sample_hash,
        })
        records.append({"file": name, "detector": source["detector"], "filter": source["filter"],
                        **{k: v for k, v in stats.items() if k != "groups"},
                        "groups": [{k: v for k, v in g.items() if k != "sha256"} for g in stats["groups"]]})
        g1, g8 = stats["groups"][0], stats["groups"][-1]
        print(f"emitted {stem} bytes={len(sample)} min={stats['minimum']} max={stats['maximum']} "
              f"distinct={stats['distinct_values']} sat={stats['saturated_65535']} "
              f"interior_mean g1={g1['interior_row_mean']} g{NG}={g8['interior_row_mean']} "
              f"ref_mean g1={g1['reference_row_mean']} g{NG}={g8['reference_row_mean']} pin={content_pin}")
        del sample

    with (index_dir / "samples.jsonl").open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")
    total = sum(r["sample_size_bytes"] for r in rows)
    summary = {
        "dataset_id": ju.DATASET_ID,
        "series_id": ju.SERIES_ID,
        "sample_count": len(rows),
        "total_size_bytes": total,
        "aggregate_sample_sha256": aggregate.hexdigest(),
        "records": records,
    }
    (filtered_dir / "ingest_stats.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
    print(f"build summary samples={len(rows)} bytes={total} aggregate_sha256={aggregate.hexdigest()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
