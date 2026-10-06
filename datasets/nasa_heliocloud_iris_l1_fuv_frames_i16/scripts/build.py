#!/usr/bin/env python3
"""Decode the pinned local IRIS level-1 FUV FITS files into little-endian int16 frames.

One sample per FITS file: the whole 1096 x 4144 int16 image (row-major, FITS
order: column fastest), including the native BLANK = -32768 fill outside the
two CCD readout regions. Every frame is cross-checked against its own header
(DATASUM, CHECKSUM, DATAVALS, DATAMIN, DATAMAX, DATAMEDN, DATAMEAN, readout
geometry) before it is written.
"""

from __future__ import annotations

import argparse
import collections
import concurrent.futures as cf
import csv
import hashlib
import json
import os
import struct
import sys
from array import array
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import iris_fits  # noqa: E402
from iris_fits import FitsError  # noqa: E402

DATASET_ID = "nasa_heliocloud_iris_l1_fuv_frames_i16"
SERIES_ID = "iris_fuv_l1_full_readout_dn_i16"
NX, NY = 4144, 1096
BLANK = -32768
EXPECTED_FILES = 40


def decode_frame(blob: bytes) -> tuple[bytes, dict]:
    """Validate and decode one IRIS level-1 FUV tile-compressed FITS file."""
    _primary, table, hdr_start, data_off, nbytes = iris_fits.hdu_layout(blob)
    problems = iris_fits.regime_problems(table)
    if problems:
        raise FitsError("header regime: " + "; ".join(problems))
    end = data_off + iris_fits.padded(nbytes)
    if end != len(blob):
        raise FitsError(f"file length {len(blob)} != end of compressed HDU {end} (extra HDUs?)")
    if any(blob[data_off + nbytes:end]):
        raise FitsError("non-zero fill after the heap")
    datasum = iris_fits.ones_complement_sum(blob[data_off:end])
    if str(table.get("DATASUM")) != str(datasum):
        raise FitsError(f"DATASUM {table.get('DATASUM')} != recomputed {datasum}")
    if "CHECKSUM" not in table:
        raise FitsError("missing CHECKSUM")
    if iris_fits.ones_complement_sum(blob[hdr_start:data_off], datasum) != 0xFFFFFFFF:
        raise FitsError("HDU CHECKSUM does not verify")

    heap0 = data_off + NY * 8
    pcount = int(table["PCOUNT"])
    maxlen = int(str(table["TFORM1"])[4:-1])
    raw = array("H")
    for r in range(NY):
        count, offset = struct.unpack(">ii", blob[data_off + 8 * r:data_off + 8 * r + 8])
        if count < 2 or count > maxlen or offset < 0 or offset + count > pcount:
            raise FitsError(f"row {r}: bad heap descriptor ({count}, {offset})")
        raw.extend(iris_fits.rice_decode_tile(blob[heap0 + offset:heap0 + offset + count], NX))
    if len(raw) != NX * NY:
        raise FitsError("decoded pixel count mismatch")
    image = array("h", raw.tobytes())

    # BLANK must be exactly the complement of the two readout regions.
    regions = []
    for k in (1, 2):
        regions.append((int(table[f"TSR{k}"]) - 1, int(table[f"TER{k}"]) - 1,
                        int(table[f"TSC{k}"]) - 1, int(table[f"TEC{k}"]) - 1))
    blank_row = array("h", [BLANK]) * NX
    for r in range(NY):
        row = image[r * NX:(r + 1) * NX]
        inside_cols = [(c0, c1) for (r0, r1, c0, c1) in regions if r0 <= r <= r1]
        if not inside_cols:
            if row != blank_row:
                raise FitsError(f"row {r} outside readout is not all BLANK")
            continue
        expect_blank = 0
        pos = 0
        for c0, c1 in sorted(inside_cols):
            expect_blank += c0 - pos
            if BLANK in row[c0:c1 + 1]:
                raise FitsError(f"BLANK inside readout region at row {r}")
            if row[pos:c0].count(BLANK) != c0 - pos:
                raise FitsError(f"non-BLANK outside readout at row {r}")
            pos = c1 + 1
        if row[pos:].count(BLANK) != NX - pos:
            raise FitsError(f"non-BLANK outside readout at row {r}")

    hist = collections.Counter(image)
    blank_count = hist.pop(BLANK, 0)
    valid = sum(hist.values())
    if valid != int(table["DATAVALS"]) or blank_count != NX * NY - valid:
        raise FitsError(f"valid pixels {valid} != DATAVALS {table['DATAVALS']}")
    keys = sorted(hist)
    vmin, vmax = keys[0], keys[-1]
    if vmin != int(table["DATAMIN"]) or vmax != int(table["DATAMAX"]):
        raise FitsError(f"min/max {vmin}/{vmax} != DATAMIN/DATAMAX {table['DATAMIN']}/{table['DATAMAX']}")
    lo_rank, hi_rank = (valid - 1) // 2, valid // 2
    cum, med_lo, med_hi = 0, None, None
    for v in keys:
        cum += hist[v]
        if med_lo is None and cum > lo_rank:
            med_lo = v
        if cum > hi_rank:
            med_hi = v
            break
    if int(table["DATAMEDN"]) not in (med_lo, med_hi):
        raise FitsError(f"median {med_lo}/{med_hi} != DATAMEDN {table['DATAMEDN']}")
    mean = sum(v * n for v, n in hist.items()) / valid
    if abs(mean - float(table["DATAMEAN"])) > 1e-3:
        raise FitsError(f"mean {mean} != DATAMEAN {table['DATAMEAN']}")
    if vmin < 0 or vmax > 16383 or len(keys) < 64:
        raise FitsError(f"implausible DN distribution: min {vmin} max {vmax} distinct {len(keys)}")
    # Unit-DN lattice: every integer from DATAMEDN-5 to DATAMEDN+15 must occur. Onboard
    # square-root companded frames (LUTID 4: 110, 112, ..., 126, 129, 132, ...) fail this.
    med = int(table["DATAMEDN"])
    gaps = [v for v in range(med - 5, med + 16) if not hist.get(v)]
    if gaps:
        raise FitsError(f"not a unit-DN lattice near the median: missing values {gaps}")

    if sys.byteorder != "little":
        image.byteswap()
    out = image.tobytes()
    facts = {
        "valid_count": valid, "blank_count": blank_count, "valid_min": vmin, "valid_max": vmax,
        "valid_median": int(table["DATAMEDN"]), "valid_mean": round(mean, 6),
        "distinct_valid_values": len(keys), "datasum": str(datasum),
        "readout_rows": [int(table["TSR1"]), int(table["TER1"])],
        "t_obs": table["T_OBS"], "obsid": int(table["ISQOLTID"]), "fsn": int(table["FSN"]),
        "exptime_s": float(table["EXPTIME"]), "crs_id": table.get("IICRSID"),
        "crs_desc": table.get("CRS_DESC"), "xcen_arcsec": table.get("XCEN"),
        "ycen_arcsec": table.get("YCEN"), "bld_vers": table.get("BLD_VERS"),
        "lutid": int(table["LUTID"]),
    }
    return out, facts


def load_sources(recipe_dir: Path) -> list[dict]:
    with open(recipe_dir / "sources.tsv", newline="") as fh:
        rows = list(csv.DictReader(fh, delimiter="\t"))
    if len(rows) != EXPECTED_FILES or len({r["filename"] for r in rows}) != EXPECTED_FILES:
        raise SystemExit("sources.tsv does not list the expected unique files")
    return rows


def load_plan(download_dir: Path) -> dict[str, str]:
    plan = download_dir / "download_plan.tsv"
    if not plan.exists():
        raise SystemExit(f"missing {plan}; run download.sh first")
    with open(plan, newline="") as fh:
        return {r["filename"]: r["sha256"] for r in csv.DictReader(fh, delimiter="\t")}


def process(args_tuple) -> dict:
    src, path, out_path = args_tuple
    blob = Path(path).read_bytes()
    if len(blob) != int(src["size_bytes"]):
        raise SystemExit(f"{src['filename']}: size {len(blob)} != pinned {src['size_bytes']}")
    if hashlib.md5(blob).hexdigest() != src["md5_etag"]:
        raise SystemExit(f"{src['filename']}: MD5 differs from pinned S3 ETag")
    sha256 = hashlib.sha256(blob).hexdigest()
    try:
        out, facts = decode_frame(blob)
    except FitsError as exc:
        raise SystemExit(f"{src['filename']}: {exc}") from exc
    for key, fact in (("obsid", "obsid"), ("fsn", "fsn"), ("t_obs", "t_obs"),
                      ("datasum", "datasum"), ("datavals", "valid_count"),
                      ("datamin", "valid_min"), ("datamax", "valid_max"),
                      ("datamedn", "valid_median")):
        if str(src[key]) != str(facts[fact]):
            raise SystemExit(f"{src['filename']}: {key} {facts[fact]} != pinned {src[key]}")
    tmp = Path(out_path + ".part")
    tmp.write_bytes(out)
    os.replace(tmp, out_path)
    facts.update({"source_sha256": sha256, "sample_sha256": hashlib.sha256(out).hexdigest()})
    return facts


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", required=True)
    ap.add_argument("--recipe-dir", required=True)
    ap.add_argument("--jobs", type=int, default=min(8, os.cpu_count() or 1))
    args = ap.parse_args()
    data = Path(args.data_dir)
    recipe = Path(args.recipe_dir)
    download_dir = data / "downloads" / DATASET_ID / "fits"
    samples_dir = data / "samples" / DATASET_ID / SERIES_ID
    index_path = data / "index" / DATASET_ID / "samples.jsonl"
    stats_path = data / "filtered" / DATASET_ID / "ingest_stats.json"
    sources = load_sources(recipe)
    plan = load_plan(data / "downloads" / DATASET_ID)
    samples_dir.mkdir(parents=True, exist_ok=True)
    index_path.parent.mkdir(parents=True, exist_ok=True)
    stats_path.parent.mkdir(parents=True, exist_ok=True)
    expected_names = {Path(s["filename"]).stem + ".i16" for s in sources}
    for stale in samples_dir.iterdir():
        if stale.name not in expected_names:
            stale.unlink()

    jobs = []
    for src in sources:
        path = download_dir / src["filename"]
        if not path.is_file():
            raise SystemExit(f"missing download {path}")
        jobs.append((src, str(path), str(samples_dir / (Path(src["filename"]).stem + ".i16"))))
    with cf.ProcessPoolExecutor(max_workers=max(1, args.jobs)) as pool:
        results = list(pool.map(process, jobs))

    rows = []
    for (src, _path, out_path), facts in zip(jobs, results):
        if plan.get(src["filename"]) != facts["source_sha256"]:
            raise SystemExit(f"{src['filename']}: SHA-256 differs from download_plan.tsv")
        if src.get("sha256") and src["sha256"] != facts["source_sha256"]:
            raise SystemExit(f"{src['filename']}: SHA-256 differs from pinned sources.tsv")
        rel = Path(out_path).relative_to(data).as_posix()
        rows.append({
            "dataset_id": DATASET_ID, "series_id": SERIES_ID, "sample_path": rel,
            "numeric_kind": "int", "bit_width": 16, "endianness": "little",
            "element_size_bytes": 2, "sample_size_bytes": NX * NY * 2, "value_count": NX * NY,
            "shape": [NY, NX], "axes": ["slit_row_y", "wavelength_column"],
            "missing_value": BLANK, "source_key": src["key"], "source_date": src["date"],
            **{k: facts[k] for k in ("t_obs", "obsid", "fsn", "exptime_s", "crs_id", "crs_desc", "lutid",
                                     "xcen_arcsec", "ycen_arcsec", "readout_rows", "valid_count",
                                     "blank_count", "valid_min", "valid_max", "valid_median",
                                     "valid_mean", "distinct_valid_values", "source_sha256",
                                     "sample_sha256")},
            "min_value": BLANK, "max_value": facts["valid_max"],
        })
        print(f"sample {Path(out_path).name} obsid={facts['obsid']} exptime={facts['exptime_s']:.1f} "
              f"valid={facts['valid_count']} blank={facts['blank_count']} "
              f"min={facts['valid_min']} median={facts['valid_median']} max={facts['valid_max']} "
              f"distinct={facts['distinct_valid_values']}")
    if len({r["sample_sha256"] for r in rows}) != len(rows):
        raise SystemExit("duplicate decoded frames")
    tmp = index_path.with_suffix(".jsonl.part")
    with open(tmp, "w") as fh:
        for r in rows:
            fh.write(json.dumps(r, sort_keys=True) + "\n")
    os.replace(tmp, index_path)
    total = sum(r["sample_size_bytes"] for r in rows)
    stats = {
        "dataset_id": DATASET_ID, "series_id": SERIES_ID, "samples": len(rows),
        "total_size_bytes": total, "value_count": sum(r["value_count"] for r in rows),
        "valid_values": sum(r["valid_count"] for r in rows),
        "blank_values": sum(r["blank_count"] for r in rows),
        "obsids": sorted({r["obsid"] for r in rows}),
        "years": dict(sorted(collections.Counter(r["source_date"][:4] for r in rows).items())),
        "source_bytes": sum(int(s["size_bytes"]) for s in sources),
    }
    stats_path.write_text(json.dumps(stats, indent=2) + "\n")
    print(f"build samples={len(rows)} bytes={total} blank_fraction="
          f"{stats['blank_values'] / stats['value_count']:.4f} obsids={len(stats['obsids'])}")


if __name__ == "__main__":
    main()
