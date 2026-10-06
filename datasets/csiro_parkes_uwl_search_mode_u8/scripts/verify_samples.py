#!/usr/bin/env python3
"""Independent verifier for csiro_parkes_uwl_search_mode_u8.

Deliberately does not import the build module. It re-parses each pinned FITS
header range with its own card reader, recomputes the SUBINT DATA column
offset from TFORMn, and compares every emitted polarization plane against the
downloaded row by direct slice comparison (no rebuilt copy is trusted). It
then checks the sample index, manifest totals, and degeneracy rules.
"""
from __future__ import annotations

import argparse
import collections
import csv
import hashlib
import json
import math
import re
import struct
import sys
import tomllib
from pathlib import Path

DATASET_ID = "csiro_parkes_uwl_search_mode_u8"
SERIES_BY_POL = {
    "AA": "parkes_uwl_search_aa_u8",
    "BB": "parkes_uwl_search_bb_u8",
    "CR": "parkes_uwl_search_cr_u8",
    "CI": "parkes_uwl_search_ci_u8",
}
EXPECT_NCHAN = 3328
EXPECT_NPOL = 4
EXPECT_NSBLK = 4096
WIDTH = {"L": 1, "B": 1, "I": 2, "J": 4, "K": 8, "A": 1, "E": 4, "D": 8, "C": 8, "M": 16}
# Degeneracy thresholds (per 13,631,488-value plane).
MIN_DISTINCT_CODES = 64
MAX_MODE_FRACTION = 0.25
MEAN_RANGE = (96.0, 160.0)
MAX_SATURATED_FRACTION = 0.02


def die(message: str) -> None:
    print(f"VERIFY FAIL: {message}", file=sys.stderr)
    raise SystemExit(1)


def cards_of(blob: bytes) -> list[tuple[int, dict]]:
    """Return (header_end_offset, cards) per HDU, scanning 80-byte cards."""
    out = []
    pos = 0
    while pos < len(blob):
        cards: dict[str, str] = {}
        while True:
            if pos + 80 > len(blob):
                die("header range ends inside an HDU header")
            text = blob[pos : pos + 80].decode("ascii")
            pos += 80
            if text.startswith("END") and text[3:].strip() == "":
                break
            m = re.match(r"^([A-Z0-9_\-]{1,8})\s*= (.*)$", text)
            if m and m.group(1) not in cards:
                cards[m.group(1)] = m.group(2)
        pos = (pos + 2879) // 2880 * 2880
        out.append((pos, cards))
        if sval(cards.get("EXTNAME", "''")) == "SUBINT":
            return out
        if "NAXIS1" in cards:
            size = 1
            for k in range(1, int(nval(cards["NAXIS"])) + 1):
                size *= int(nval(cards[f"NAXIS{k}"]))
            pos += (size + 2879) // 2880 * 2880
    die("SUBINT header not found in header range")
    return out


def sval(raw: str) -> str:
    m = re.match(r"^\s*'((?:[^']|'')*)'", raw)
    if not m:
        die(f"expected string card value, got {raw!r}")
    return m.group(1).replace("''", "'").rstrip()


def nval(raw: str) -> float:
    token = raw.split("/")[0].strip()
    return float(token)


def check_source(source: dict, downloads: Path) -> dict:
    base = Path(source["filename"]).name
    row_index = int(source["subint_row"])
    header = (downloads / "headers" / f"{base}.header").read_bytes()
    if hashlib.sha256(header).hexdigest() != source["header_sha256"]:
        die(f"{base}: header SHA-256 mismatch")
    hdus = cards_of(header)
    primary = hdus[0][1]
    sub_end, sub = hdus[-1]
    if sub_end != len(header):
        die(f"{base}: SUBINT header ends at {sub_end}, header range has {len(header)} bytes")
    want_str = {
        "FRONTEND": "UWL", "BACKEND": "Medusa", "OBS_MODE": "SEARCH", "SRC_NAME": "ProxCen_S",
        "PROJID": "P1018", "TELESCOP": "Parkes", "DATE-OBS": source["date_obs_utc"],
    }
    for key, want in want_str.items():
        if sval(primary[key]) != want:
            die(f"{base}: {key}={sval(primary[key])!r} expected {want!r}")
    if sval(sub["POL_TYPE"]) != "AABBCRCI":
        die(f"{base}: POL_TYPE changed")
    want_num = {"NBITS": 8, "SIGNINT": 0, "NPOL": EXPECT_NPOL, "NCHAN": EXPECT_NCHAN,
                "NSBLK": EXPECT_NSBLK, "TBIN": 0.000128, "ZERO_OFF": 127.5}
    for key, want in want_num.items():
        if not math.isclose(nval(sub[key]), want, rel_tol=1e-12, abs_tol=1e-12):
            die(f"{base}: {key}={sub[key]!r} expected {want}")
    offset = 0
    data_offset = None
    for n in range(1, int(nval(sub["TFIELDS"])) + 1):
        tform = sval(sub[f"TFORM{n}"])
        m = re.match(r"^(\d*)([A-Z])", tform)
        repeat = int(m.group(1) or 1)
        width = (repeat + 7) // 8 if m.group(2) == "X" else repeat * WIDTH[m.group(2)]
        if sval(sub[f"TTYPE{n}"]) == "DATA":
            data_offset = offset
            if width != EXPECT_NCHAN * EXPECT_NPOL * EXPECT_NSBLK:
                die(f"{base}: DATA width {width}")
            dims = [int(x) for x in re.findall(r"\d+", sval(sub[f"TDIM{n}"]))]
            if dims != [EXPECT_NCHAN, EXPECT_NPOL, EXPECT_NSBLK]:
                die(f"{base}: TDIM {dims}")
        offset += width
    naxis1 = int(nval(sub["NAXIS1"]))
    if data_offset is None or offset != naxis1:
        die(f"{base}: TFORM widths {offset} != NAXIS1 {naxis1}")
    expected_size = sub_end + naxis1 * int(nval(sub["NAXIS2"]))
    if (expected_size + 2879) // 2880 * 2880 != int(source["file_size"]):
        die(f"{base}: header does not predict pinned file size")
    row_path = downloads / "rows" / f"{base}.subint{row_index:04d}.row"
    row = row_path.read_bytes()
    if len(row) != naxis1:
        die(f"{base}: row length {len(row)} != NAXIS1")
    row_sha = hashlib.sha256(row).hexdigest()
    if source.get("row_sha256") and row_sha != source["row_sha256"]:
        die(f"{base}: row SHA-256 {row_sha} != pinned")
    if hashlib.sha256(row[:data_offset]).hexdigest() != source["row_aux_prefix_sha256"]:
        die(f"{base}: aux-prefix SHA-256 mismatch")
    # Spot-check aux columns independently: TSUBINT, OFFS_SUB, weights.
    tsubint, offs_sub = struct.unpack_from(">2d", row, 8)
    if abs(offs_sub - (row_index + 0.5) * tsubint) > 1e-6:
        die(f"{base}: OFFS_SUB does not identify row {row_index}")
    wts_off = 40 + 8 * EXPECT_NCHAN * EXPECT_NPOL
    wts = struct.unpack_from(f">{EXPECT_NCHAN}f", row, wts_off)
    if min(wts) <= 0:
        die(f"{base}: zero-weight channels present; policy requires fully weighted rows")
    return {"base": base, "row": row, "data_offset": data_offset, "row_sha256": row_sha}


def plane_checks(name: str, sample: bytes) -> dict:
    counts = collections.Counter(sample)
    total = len(sample)
    mean = sum(v * n for v, n in counts.items()) / total
    mode_fraction = counts.most_common(1)[0][1] / total
    saturated = (counts.get(0, 0) + counts.get(255, 0)) / total
    if len(counts) < MIN_DISTINCT_CODES:
        die(f"{name}: only {len(counts)} distinct codes")
    if mode_fraction > MAX_MODE_FRACTION:
        die(f"{name}: mode fraction {mode_fraction:.4f} too high")
    if not MEAN_RANGE[0] <= mean <= MEAN_RANGE[1]:
        die(f"{name}: mean {mean:.3f} outside {MEAN_RANGE}")
    if saturated > MAX_SATURATED_FRACTION:
        die(f"{name}: saturated fraction {saturated:.4f} too high")
    # Structural: spectra must vary over time and channels must vary within a spectrum.
    first = sample[:EXPECT_NCHAN]
    last = sample[-EXPECT_NCHAN:]
    if first == last or len(set(first)) < 8:
        die(f"{name}: structurally degenerate spectra")
    return {"min": min(counts), "max": max(counts), "mean": round(mean, 6),
            "distinct_codes": len(counts), "mode_fraction": round(mode_fraction, 6)}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--sources", required=True)
    ap.add_argument("--downloads", required=True)
    ap.add_argument("--index", required=True)
    ap.add_argument("--data-root", required=True)
    args = ap.parse_args()
    data_root = Path(args.data_root).resolve()
    downloads = Path(args.downloads)
    manifest = tomllib.loads(Path(args.manifest).read_text(encoding="utf-8"))
    if manifest.get("dataset_id") != DATASET_ID:
        die("manifest dataset_id mismatch")
    series_meta = {s["id"]: s for s in manifest["series"] if s.get("role") == "primary"}
    if set(series_meta) != set(SERIES_BY_POL.values()):
        die(f"manifest primary series {sorted(series_meta)} != {sorted(SERIES_BY_POL.values())}")
    with open(args.sources, encoding="utf-8", newline="") as handle:
        sources = list(csv.DictReader(handle, delimiter="\t", restval=""))
    index_rows = [json.loads(line) for line in Path(args.index).read_text(encoding="utf-8").splitlines() if line.strip()]
    by_path = {}
    for row in index_rows:
        for key in ("dataset_id", "series_id", "sample_path", "numeric_kind", "bit_width", "endianness",
                    "element_size_bytes", "sample_size_bytes", "value_count"):
            if key not in row:
                die(f"index row missing {key}")
        if row["dataset_id"] != DATASET_ID or row["numeric_kind"] != "uint" or row["bit_width"] != 8:
            die(f"index row has wrong identity/type: {row['sample_path']}")
        if row["element_size_bytes"] != 1 or row["endianness"] != "little":
            die(f"index row element/endianness wrong: {row['sample_path']}")
        if row["sample_path"] in by_path:
            die(f"duplicate index path {row['sample_path']}")
        by_path[row["sample_path"]] = row
    expected_count = len(sources) * len(SERIES_BY_POL)
    if len(index_rows) != expected_count:
        die(f"index has {len(index_rows)} rows, expected {expected_count}")
    plane_bytes = EXPECT_NCHAN * EXPECT_NSBLK
    stride = EXPECT_NCHAN * EXPECT_NPOL
    digests: dict[str, str] = {}
    totals = collections.defaultdict(lambda: [0, 0])
    seen_obs = set()
    for source in sources:
        if source["observation_id"] in seen_obs:
            die(f"observation {source['observation_id']} pinned twice")
        seen_obs.add(source["observation_id"])
        got = check_source(source, downloads)
        row, data_offset = got["row"], got["data_offset"]
        stem = Path(source["filename"]).stem
        row_index = int(source["subint_row"])
        for pol_idx, (pol, series_id) in enumerate(SERIES_BY_POL.items()):
            rel = f"samples/{DATASET_ID}/{series_id}/{stem}_subint{row_index:04d}_{pol}.u8"
            entry = by_path.get(rel)
            if entry is None:
                die(f"index lacks {rel}")
            if entry["series_id"] != series_id or entry.get("pol_product") != pol:
                die(f"{rel}: series/pol label mismatch")
            sample = (data_root / rel).read_bytes()
            if len(sample) != plane_bytes or entry["sample_size_bytes"] != plane_bytes or entry["value_count"] != plane_bytes:
                die(f"{rel}: size {len(sample)} / index {entry['sample_size_bytes']} != {plane_bytes}")
            base = data_offset + pol_idx * EXPECT_NCHAN
            mv_row = memoryview(row)
            mv_sample = memoryview(sample)
            for t in range(EXPECT_NSBLK):
                if mv_sample[t * EXPECT_NCHAN : (t + 1) * EXPECT_NCHAN] != mv_row[base + t * stride : base + t * stride + EXPECT_NCHAN]:
                    die(f"{rel}: time sample {t} differs from source row")
            digest = hashlib.sha256(sample).hexdigest()
            if entry.get("sha256") != digest:
                die(f"{rel}: index sha256 mismatch")
            if digest in digests:
                die(f"{rel}: identical to {digests[digest]}")
            digests[digest] = rel
            stats = plane_checks(rel, sample)
            for key in ("min", "max", "distinct_codes"):
                if entry.get(key) != stats[key]:
                    die(f"{rel}: index {key}={entry.get(key)} != recomputed {stats[key]}")
            totals[series_id][0] += 1
            totals[series_id][1] += len(sample)
            print(f"ok {rel} {stats}")
        print(f"row_ok {got['base']} row={row_index} sha256={got['row_sha256']}")
    if len(by_path) != len(digests):
        die("index lists samples not derived from pinned sources")
    # Stray files in the samples tree.
    for series_id in SERIES_BY_POL.values():
        for path in (data_root / "samples" / DATASET_ID / series_id).iterdir():
            if str(path.relative_to(data_root)) not in by_path:
                die(f"stray sample file {path}")
    for series_id, meta in series_meta.items():
        count, size = totals[series_id]
        if meta["sample_count"] != count or meta["total_size_bytes"] != size:
            die(f"{series_id}: manifest {meta['sample_count']}/{meta['total_size_bytes']} != realized {count}/{size}")
        if meta["numeric_kind"] != "uint" or meta["bit_width"] != 8:
            die(f"{series_id}: manifest type mismatch")
    total_bytes = sum(v[1] for v in totals.values())
    if total_bytes > 1_000_000_000:
        die("primary bytes exceed 1 GB cap")
    print(json.dumps({"verified_samples": len(digests), "primary_bytes": total_bytes,
                      "series": {k: {"samples": v[0], "bytes": v[1]} for k, v in sorted(totals.items())}}, sort_keys=True))


if __name__ == "__main__":
    main()
