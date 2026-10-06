#!/usr/bin/env python3
"""Semantic check of a Landsat Collection 2 Level-1 MTL.json (no network I/O).

Usage:
    mtl_check.py <MTL.json> <product_id> <wrs_path> <wrs_row> <rows> <cols>

Exits 1 unless the metadata describe exactly the pinned product: Landsat-5
MSS, L1TP, collection 02, Tier 1, the pinned WRS-2 path/row and acquisition
date, REFLECTIVE_LINES x REFLECTIVE_SAMPLES equal to the pinned raster shape,
bands 1-4 present as UINT8 with the expected file names and a quantized
calibration range of 1..255 (0 is therefore fill only), 60 m north-up UTM.
On success prints one JSON object with the per-band radiance/reflectance
rescaling coefficients and saturation flags (recorded in the index as
documentation; never applied to the samples).
"""
from __future__ import annotations

import json
import re
import sys

BANDS = (1, 2, 3, 4)


def load(path: str) -> dict:
    doc = json.load(open(path, encoding="utf-8"))
    root = doc.get("LANDSAT_METADATA_FILE")
    if not isinstance(root, dict):
        raise ValueError("missing LANDSAT_METADATA_FILE")
    return root


def summarize(path: str, product_id: str, wrs_path: str, wrs_row: str, rows: int, cols: int) -> dict:
    root = load(path)
    pc = root.get("PRODUCT_CONTENTS", {})
    ia = root.get("IMAGE_ATTRIBUTES", {})
    pa = root.get("PROJECTION_ATTRIBUTES", {})
    pr = root.get("LEVEL1_PROCESSING_RECORD", {})
    mm = root.get("LEVEL1_MIN_MAX_PIXEL_VALUE", {})
    rr = root.get("LEVEL1_RADIOMETRIC_RESCALING", {})
    problems = []

    def expect(section: dict, key: str, want) -> None:
        got = section.get(key)
        if str(got) != str(want):
            problems.append(f"{key}={got!r} expected {want!r}")

    expect(pc, "LANDSAT_PRODUCT_ID", product_id)
    expect(pc, "PROCESSING_LEVEL", "L1TP")
    expect(pc, "COLLECTION_NUMBER", "02")
    expect(pc, "COLLECTION_CATEGORY", "T1")
    expect(ia, "SPACECRAFT_ID", "LANDSAT_5")
    expect(ia, "SENSOR_ID", "MSS")
    expect(ia, "WRS_TYPE", "2")
    for key, want in (("WRS_PATH", wrs_path), ("WRS_ROW", wrs_row)):
        try:  # MTL writes e.g. "186"/"041"; compare as integers (zero padding varies)
            same = int(str(ia.get(key))) == int(want)
        except ValueError:
            same = False
        if not same:
            problems.append(f"{key}={ia.get(key)!r} expected {want!r}")
    date = product_id.split("_")[3]
    expect(ia, "DATE_ACQUIRED", f"{date[:4]}-{date[4:6]}-{date[6:]}")
    expect(pa, "MAP_PROJECTION", "UTM")
    expect(pa, "ORIENTATION", "NORTH_UP")
    expect(pa, "GRID_CELL_SIZE_REFLECTIVE", "60.00")
    expect(pa, "REFLECTIVE_LINES", str(rows))
    expect(pa, "REFLECTIVE_SAMPLES", str(cols))
    for b in BANDS:
        expect(pc, f"FILE_NAME_BAND_{b}", f"{product_id}_B{b}.TIF")
        expect(pc, f"DATA_TYPE_BAND_{b}", "UINT8")
        expect(pc, f"PRESENT_BAND_{b}", "Y")
        expect(mm, f"QUANTIZE_CAL_MIN_BAND_{b}", "1")
        expect(mm, f"QUANTIZE_CAL_MAX_BAND_{b}", "255")
        for key in (f"RADIANCE_MULT_BAND_{b}", f"RADIANCE_ADD_BAND_{b}"):
            try:
                float(rr[key])
            except (KeyError, TypeError, ValueError):
                problems.append(f"{key} missing or not numeric")
    # Some C2 MTL.json files write ORIGIN with its spaces stripped
    # ("ImagecourtesyoftheU.S.GeologicalSurvey"); compare without whitespace.
    if "u.s.geologicalsurvey" not in re.sub(r"\s+", "", str(pc.get("ORIGIN", ""))).lower():
        problems.append(f"ORIGIN={pc.get('ORIGIN')!r} does not credit the U.S. Geological Survey")
    if problems:
        raise ValueError("; ".join(problems))
    return {
        "landsat_product_id": product_id,
        "landsat_scene_id": pr.get("LANDSAT_SCENE_ID"),
        "station_id": ia.get("STATION_ID"),
        "date_acquired": ia.get("DATE_ACQUIRED"),
        "scene_center_time": ia.get("SCENE_CENTER_TIME"),
        "date_product_generated": pr.get("DATE_PRODUCT_GENERATED"),
        "processing_software_version": pr.get("PROCESSING_SOFTWARE_VERSION"),
        "cpf": pr.get("FILE_NAME_CPF"),
        "geometric_rmse_model": pr.get("GEOMETRIC_RMSE_MODEL"),
        "utm_zone": pa.get("UTM_ZONE"),
        "origin": pc.get("ORIGIN"),
        "bands": {
            f"B{b}": {
                "radiance_mult": float(rr[f"RADIANCE_MULT_BAND_{b}"]),
                "radiance_add": float(rr[f"RADIANCE_ADD_BAND_{b}"]),
                "reflectance_mult": float(rr[f"REFLECTANCE_MULT_BAND_{b}"]) if f"REFLECTANCE_MULT_BAND_{b}" in rr else None,
                "reflectance_add": float(rr[f"REFLECTANCE_ADD_BAND_{b}"]) if f"REFLECTANCE_ADD_BAND_{b}" in rr else None,
                "saturation_flag": ia.get(f"SATURATION_BAND_{b}"),
                "quantize_cal_min": int(mm[f"QUANTIZE_CAL_MIN_BAND_{b}"]),
                "quantize_cal_max": int(mm[f"QUANTIZE_CAL_MAX_BAND_{b}"]),
            }
            for b in BANDS
        },
    }


def main(argv: list[str]) -> int:
    if len(argv) != 7:
        print(__doc__, file=sys.stderr)
        return 2
    path, product_id, wrs_path, wrs_row, rows, cols = argv[1:]
    try:
        info = summarize(path, product_id, wrs_path, wrs_row, int(rows), int(cols))
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        print(f"INVALID {path}: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(info, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
