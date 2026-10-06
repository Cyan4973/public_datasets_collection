#!/usr/bin/env python3
"""Independently re-derive and check every Voyager ISS raw-frame sample.

Deliberately does not import vgiss.py: INDEX.TAB is parsed as quoted CSV
(not fixed-width), the selection rule is re-implemented, the image offset
is computed from each file's own VICAR label (LBLSIZE + NLB * RECSIZE,
NBB prefix per record) instead of constants, and the exclusion rule
(> 40 all-zero image lines, or < 16 distinct DN) is re-applied. Every emitted
sample is byte-compared with the re-derived frame; index rows, manifest
scope, duplicates and degeneracy are checked.
"""
from __future__ import annotations

import argparse
import collections
import csv
import hashlib
import io
import json
import re
import sys
import tomllib
from pathlib import Path

DATASET_ID = "nasa_pds_voyager_iss_saturn_raw_u8"
SERIES_ID = "vg2_issn_saturn_raw_dn_u8"
SIDE = 800
FRAME = SIDE * SIDE
FILE_BYTES = 823296
FILL_LINE_LIMIT = 40
MIN_DISTINCT = 16
INDEX_KEYS = ["dataset_id", "series_id", "sample_path", "numeric_kind", "bit_width", "endianness",
              "element_size_bytes", "sample_size_bytes", "value_count"]
LABEL_EXPECT = {
    "PRODUCT_TYPE": "DECOMPRESSED_RAW_IMAGE", "SPACECRAFT_ID": "VG2", "INSTRUMENT_ID": '"ISSN"',
    "MISSION_PHASE_NAME": '"SATURN ENCOUNTER"', "SCAN_MODE_ID": '"3:1"', "GAIN_MODE_ID": '"LOW"',
    "EDIT_MODE_ID": '"1:1"', "LINES": "800", "LINE_SAMPLES": "800", "LINE_PREFIX_BYTES": "224",
    "SAMPLE_BITS": "8", "SAMPLE_TYPE": "UNSIGNED_INTEGER", "RECORD_BYTES": "1024", "FILE_RECORDS": "804",
}


def fail(message: str) -> None:
    raise SystemExit(f"VERIFY FAIL: {message}")


def index_selection(path: Path) -> list[tuple[str, str]]:
    text = path.read_bytes().decode("ascii")
    picked = []
    for rec in csv.reader(io.StringIO(text, newline="")):
        if not rec:
            continue
        if len(rec) != 21:
            fail(f"INDEX.TAB row with {len(rec)} fields")
        f = [x.strip() for x in rec]
        (volume, spec, _pid, ptype, craft, phase, target, _imgid, number, _t, _ert, inst, scan, shutter, gain,
         edit, _filt, _fno, exposure, _note, anomaly) = f
        if (volume == "VGISS_0005" and ptype == "DECOMPRESSED_RAW_IMAGE" and craft == "VOYAGER 2"
                and phase == "SATURN ENCOUNTER" and inst == "NARROW ANGLE CAMERA" and scan == "3:1"
                and edit == "1:1" and gain == "LOW" and target in {"SATURN", "S RINGS"} and shutter != "BODARK"
                and not spec.startswith("CALIB/") and anomaly == "NONE" and float(exposure) != -99.999):
            picked.append((float(number), number, spec.removesuffix(".LBL")))
    picked.sort()
    return [(number, stem) for _f, number, stem in picked]


def label_value(text: str, key: str) -> str | None:
    match = re.search(rf"^\s*{key}\s*=\s*(\S[^\r\n]*?)\s*(?:/\*.*)?$", text, flags=re.M)
    if not match:
        return None
    return re.sub(r"\s*<[^>]*>$", "", match.group(1)).strip()


def vicar_items(blob: bytes) -> dict[str, str]:
    out: dict[str, str] = {}
    text = blob.split(b"\x00", 1)[0].decode("ascii")
    pos = 0
    while pos < len(text):
        eq = text.find("=", pos)
        if eq < 0:
            break
        key = text[pos:eq].strip()
        if text[eq + 1:eq + 2] == "'":
            end = eq + 2
            while True:
                end = text.index("'", end)
                if text[end + 1:end + 2] == "'":
                    end += 2
                    continue
                break
            value = text[eq + 2:end].replace("''", "'")
            pos = end + 1
        else:
            end = text.find(" ", eq + 1)
            end = len(text) if end < 0 else end
            value = text[eq + 1:end]
            pos = end
        while pos < len(text) and text[pos] == " ":
            pos += 1
        out.setdefault(key, value)
    return out


def rederive(raw: bytes, number: str, name: str) -> tuple[bytes, int]:
    if len(raw) != FILE_BYTES:
        fail(f"{name}: file size {len(raw)}")
    v = vicar_items(raw[:1024])
    lblsize, recsize, nlb, nbb = int(v["LBLSIZE"]), int(v["RECSIZE"]), int(v["NLB"]), int(v["NBB"])
    if (v.get("FORMAT"), v.get("ORG"), v.get("NL"), v.get("NS"), v.get("NB"), v.get("EOL")) != ("BYTE", "BSQ", "800", "800", "1", "1"):
        fail(f"{name}: unexpected VICAR geometry")
    if recsize - nbb != SIDE:
        fail(f"{name}: RECSIZE-NBB != 800")
    if not v.get("LAB02", "").startswith("VGR-2") or f"FDS {number}" not in v.get("LAB02", ""):
        fail(f"{name}: VICAR LAB02 does not identify VGR-2 FDS {number}")
    if not v.get("LAB03", "").startswith("NA CAMERA") or "3:1" not in v.get("LAB03", ""):
        fail(f"{name}: VICAR LAB03 is not NA camera scan 3:1")
    start = lblsize + nlb * recsize
    eol = start + SIDE * recsize
    if eol + lblsize != len(raw) or not raw[eol:].startswith(b"LBLSIZE="):
        fail(f"{name}: VICAR extension label not where NL*RECSIZE puts it")
    whole, frac = number.split(".")
    pre = raw[start:start + nbb]
    if int.from_bytes(pre[22:24], "little") != int(whole) or pre[24] != int(frac):
        fail(f"{name}: first line prefix does not carry FDS {number}")
    rows = [raw[start + i * recsize + nbb:start + (i + 1) * recsize] for i in range(SIDE)]
    fill = sum(1 for r in rows if r.count(0) == SIDE)
    return b"".join(rows), fill


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--recipe-dir", type=Path, required=True)
    args = parser.parse_args()
    data_dir = args.data_dir
    manifest = tomllib.loads((args.recipe_dir / "manifest.toml").read_text(encoding="utf-8"))
    if manifest.get("dataset_id") != DATASET_ID:
        fail("manifest dataset_id mismatch")
    series = [s for s in manifest.get("series", []) if s.get("id") == SERIES_ID]
    if len(series) != 1 or series[0].get("role") != "primary":
        fail("manifest must declare exactly one primary series with the expected id")
    series = series[0]
    if (series.get("numeric_kind"), series.get("bit_width")) != ("uint", 8):
        fail("manifest series must be uint8")

    with (args.recipe_dir / "sources.tsv").open(encoding="utf-8", newline="") as handle:
        sources = list(csv.DictReader(handle, delimiter="\t"))
    downloads = data_dir / "downloads" / DATASET_ID
    selection = index_selection(downloads / "index" / "INDEX.TAB")
    if selection != [(s["image_number"], s["volume_path"]) for s in sources]:
        fail("selection re-derived from INDEX.TAB (CSV parse) differs from sources.tsv")

    expected_emitted = []
    excluded = []
    derived: dict[str, bytes] = {}
    for s in sources:
        name, number = s["product"], s["image_number"]
        lbl = (downloads / "raw" / f"{name}_RAW.LBL").read_bytes()
        if len(lbl) != int(s["lbl_size"]) or hashlib.md5(lbl).hexdigest() != s["lbl_md5"]:
            fail(f"{name}: label differs from pin")
        text = lbl.decode("ascii")
        for key, value in LABEL_EXPECT.items():
            if label_value(text, key) != value:
                fail(f"{name}: label {key}={label_value(text, key)!r}, expected {value!r}")
        if label_value(text, "IMAGE_NUMBER") != number or label_value(text, "TARGET_NAME") not in ('"SATURN"', '"S RINGS"'):
            fail(f"{name}: label IMAGE_NUMBER/TARGET_NAME check failed")
        raw = (downloads / "raw" / f"{name}_RAW.IMG").read_bytes()
        if hashlib.md5(raw).hexdigest() != s["img_md5"]:
            fail(f"{name}: image MD5 differs from pin")
        frame, fill = rederive(raw, number, name)
        distinct = len(set(frame))
        if fill > FILL_LINE_LIMIT or distinct < MIN_DISTINCT:
            excluded.append(name)
            continue
        expected_emitted.append(s)
        derived[name] = frame

    if series["sample_count"] != len(expected_emitted):
        fail(f"manifest sample_count {series['sample_count']} != re-derived kept frames {len(expected_emitted)}")
    index_path = data_dir / "index" / DATASET_ID / "samples.jsonl"
    rows = [json.loads(line) for line in index_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if len(rows) != len(expected_emitted):
        fail(f"index rows {len(rows)} != kept frames {len(expected_emitted)}")
    output_dir = data_dir / series["output_path"]
    on_disk = sorted(p.name for p in output_dir.iterdir())
    if on_disk != sorted(f"{s['product']}.u8" for s in expected_emitted):
        fail("sample directory contents do not match the kept selection (stale or missing files)")

    hashes: set[str] = set()
    total = 0
    histogram = [0] * 256
    targets: dict[str, int] = {}
    for s, row in zip(expected_emitted, rows):
        name = s["product"]
        for key in INDEX_KEYS:
            if key not in row:
                fail(f"index row for {name} lacks {key}")
        want = {"dataset_id": DATASET_ID, "series_id": SERIES_ID, "sample_path": f"{series['output_path']}{name}.u8",
                "numeric_kind": "uint", "bit_width": 8, "endianness": "little", "element_size_bytes": 1,
                "sample_size_bytes": FRAME, "value_count": FRAME}
        for key, value in want.items():
            if row[key] != value:
                fail(f"index row for {name}: {key}={row[key]!r}, expected {value!r}")
        sample = (data_dir / row["sample_path"]).read_bytes()
        if sample != derived[name]:
            fail(f"{name}: emitted sample differs from the re-derived frame")
        digest = hashlib.sha256(sample).hexdigest()
        if row.get("sha256") != digest or digest in hashes:
            fail(f"{name}: index sha256 mismatch or duplicate frame")
        hashes.add(digest)
        lo, hi, distinct = min(sample), max(sample), len(set(sample))
        if (row.get("minimum"), row.get("maximum"), row.get("distinct_values")) != (lo, hi, distinct):
            fail(f"{name}: index min/max/distinct mismatch")
        if lo == hi:
            fail(f"{name}: constant frame")
        for value, count in collections.Counter(sample).items():
            histogram[value] += count
        targets[s["target_name"]] = targets.get(s["target_name"], 0) + 1
        total += len(sample)
    if total != series["total_size_bytes"]:
        fail(f"total bytes {total} != manifest total_size_bytes {series['total_size_bytes']}")
    levels = sum(1 for c in histogram if c)
    if levels < 200:
        fail(f"aggregate DN histogram uses only {levels} levels")
    if max(histogram) > 0.5 * total:
        fail("a single DN value holds more than half of all pixels")
    print(f"verify ok samples={len(rows)} excluded={len(excluded)} bytes={total} dn_levels={levels} "
          f"targets={json.dumps(targets, sort_keys=True)} excluded_products={excluded}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
