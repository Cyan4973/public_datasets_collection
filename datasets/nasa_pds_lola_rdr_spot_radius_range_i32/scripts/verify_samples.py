#!/usr/bin/env python3
"""Independent verification of the LOLA RDR spot radius / range samples.

Does not import lola_rdr.py: it re-reads the column START_BYTEs from the
downloaded lolardr.fmt with its own parser, views each orbit file as a flat
array of little-endian uint32 words, re-applies the spot policy
(RADIUS != -1, RANGE != 0xFFFFFFFF, SHOT_FLAG & 0xFF == 0), and compares the
re-derived arrays byte for byte with the samples. Also checks index and
manifest totals, MD5s, degeneracy, int32 fit, and a geometric consistency
check (SC_RADIUS - RADIUS_k ~ RANGE_k * cos(OFFNADIR_ANGLE)).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
import tomllib
from array import array
from pathlib import Path

DATASET_ID = "nasa_pds_lola_rdr_spot_radius_range_i32"
SERIES = ("spot_radius_mm_i32", "spot_range_mm_i32")
MIN_KEPT_FRACTION = 0.30
MIN_DISTINCT = 1000
# Geometry check: |SC_RADIUS - RADIUS_k - RANGE_k * cos(theta)| below
# GEOM_TOL_MM for at least GEOM_MIN_SHARE of kept spots in every orbit, where
# theta = OFFNADIR_ANGLE / 20000 rad (detector-1 boresight from nadir; the
# other spots differ by < 0.1 deg). LRO's off-nadir slews (e.g. 12-18 deg at
# the end of the pinned lro_no_04 orbit) make the uncorrected residual
# range * (1 - cos theta) reach km scale. A missing angle (65535) is
# treated as theta = 0.
GEOM_TOL_MM = 1_000_000
GEOM_MIN_SHARE = 0.99


def fmt_word_indices(text: str) -> dict[str, int]:
    starts: dict[str, int] = {}
    for block in re.findall(r"OBJECT\s*=\s*COLUMN(.*?)END_OBJECT\s*=\s*COLUMN", text, re.S):
        name = re.search(r"\bNAME\s*=\s*(\S+)", block).group(1)
        start = int(re.search(r"START_BYTE\s*=\s*(\d+)", block).group(1))
        nbytes = int(re.search(r"\bBYTES\s*=\s*(\d+)", block).group(1))
        starts[name] = (start, nbytes)
    on_start, on_bytes = starts["OFFNADIR_ANGLE"]
    if on_bytes != 2 or (on_start - 1) % 4:
        raise SystemExit(f"fmt: OFFNADIR_ANGLE START_BYTE {on_start} BYTES {on_bytes} not the low half of a word")
    out = {"OFFNADIR_ANGLE": (on_start - 1) // 4}
    for name in ["SC_RADIUS"] + [f"{f}_{k}" for k in range(1, 6) for f in ("RADIUS", "RANGE", "SHOT_FLAG")]:
        start, nbytes = starts[name]
        if nbytes != 4 or (start - 1) % 4:
            raise SystemExit(f"fmt: {name} START_BYTE {start} BYTES {nbytes} not word aligned")
        out[name] = (start - 1) // 4
    return out


def rederive(path: Path, w: dict[str, int]) -> tuple[bytes, bytes, dict]:
    words = array("I")
    words.frombytes(path.read_bytes())
    if sys.byteorder != "little":
        words.byteswap()
    if len(words) % 64:
        raise SystemExit(f"{path}: not a whole number of 256-byte records")
    nrec = len(words) // 64
    rad_out = array("I")
    rng_out = array("I")
    missing = flagged = 0
    geom_ok = 0
    max_offnadir = 0
    cos_cache: dict[int, float] = {}
    sc = w["SC_RADIUS"]
    iw_on = w["OFFNADIR_ANGLE"]
    spots = [(w[f"RADIUS_{k}"], w[f"RANGE_{k}"], w[f"SHOT_FLAG_{k}"]) for k in range(1, 6)]
    for r in range(nrec):
        base = r * 64
        on = words[base + iw_on] & 0xFFFF
        if on == 0xFFFF:
            on = 0
        cos_t = cos_cache.get(on)
        if cos_t is None:
            cos_t = cos_cache[on] = math.cos(on / 20000.0)
        for ir, ig, iflag in spots:
            rad = words[base + ir]
            rng = words[base + ig]
            if rad == 0xFFFFFFFF or rng == 0xFFFFFFFF:
                missing += 1
                continue
            if words[base + iflag] & 0xFF:
                flagged += 1
                continue
            if rad >= 2**31 or rng >= 2**31:
                raise SystemExit(f"{path}: kept spot at record {r} does not fit int32 (radius {rad}, range {rng})")
            rad_out.append(rad)
            rng_out.append(rng)
            if abs(words[base + sc] - rad - rng * cos_t) < GEOM_TOL_MM:
                geom_ok += 1
            if on > max_offnadir:
                max_offnadir = on
    if sys.byteorder != "little":
        rad_out.byteswap()
        rng_out.byteswap()
    kept = len(rad_out)
    return rad_out.tobytes(), rng_out.tobytes(), {
        "records": nrec,
        "kept": kept,
        "missing": missing,
        "flagged": flagged,
        "geom_share": geom_ok / kept if kept else 0.0,
        "max_offnadir_deg": math.degrees(max_offnadir / 20000.0),
    }


def md5(path: Path) -> str:
    h = hashlib.md5()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-root", type=Path, required=True)
    ap.add_argument("--sources", type=Path, required=True)
    ap.add_argument("--manifest", type=Path, required=True)
    args = ap.parse_args()
    root = args.data_root
    down = root / "downloads" / DATASET_ID
    lines = args.sources.read_text(encoding="utf-8").splitlines()
    header = lines[0].split("\t")
    sources = [dict(zip(header, l.split("\t"))) for l in lines[1:] if l.strip()]
    w = fmt_word_indices((down / "lolardr.fmt").read_text(encoding="ascii"))
    expect_w = {"SC_RADIUS": 8, "OFFNADIR_ANGLE": 60}
    for k in range(1, 6):
        expect_w[f"RADIUS_{k}"] = 12 + 10 * (k - 1)
        expect_w[f"RANGE_{k}"] = 13 + 10 * (k - 1)
        expect_w[f"SHOT_FLAG_{k}"] = 19 + 10 * (k - 1)
    if w != expect_w:
        raise SystemExit(f"fmt word indices {w} != expected {expect_w}")

    index = [json.loads(l) for l in (root / "index" / DATASET_ID / "samples.jsonl").read_text().splitlines() if l.strip()]
    by_key = {(r["series_id"], Path(r["sample_path"]).stem): r for r in index}
    if len(by_key) != len(index) or len(index) != 2 * len(sources):
        raise SystemExit(f"index has {len(index)} rows ({len(by_key)} unique), expected {2 * len(sources)}")
    if len({s["phase"] for s in sources}) != len(sources):
        raise SystemExit("more than one orbit per phase in sources.tsv")

    totals = {s: [0, 0] for s in SERIES}
    all_kept = all_spots = 0
    for n, src in enumerate(sources, 1):
        stem = src["file"][: -len(".dat")]
        dat = down / src["phase"] / src["file"]
        if dat.stat().st_size != int(src["dat_bytes"]) or md5(dat) != src["dat_md5"]:
            raise SystemExit(f"{dat}: size/MD5 differs from pin")
        if md5(down / src["phase"] / f"{stem}.lbl") != src["lbl_md5"]:
            raise SystemExit(f"{stem}.lbl: MD5 differs from pin")
        rad_b, rng_b, st = rederive(dat, w)
        if st["records"] != int(src["records"]):
            raise SystemExit(f"{dat}: {st['records']} records, pinned {src['records']}")
        spots = st["records"] * 5
        frac = st["kept"] / spots
        if frac < MIN_KEPT_FRACTION:
            raise SystemExit(f"{dat}: kept fraction {frac:.4f} < {MIN_KEPT_FRACTION}")
        if st["kept"] + st["missing"] + st["flagged"] != spots:
            raise SystemExit(f"{dat}: spot accounting mismatch")
        if st["geom_share"] < GEOM_MIN_SHARE:
            raise SystemExit(f"{dat}: only {st['geom_share']:.4f} of kept spots satisfy |SC_RADIUS - RADIUS - RANGE cos(offnadir)| < {GEOM_TOL_MM} mm")
        all_kept += st["kept"]
        all_spots += spots
        for sid, raw in zip(SERIES, (rad_b, rng_b)):
            row = by_key.get((sid, stem))
            if row is None:
                raise SystemExit(f"index row missing for {sid}/{stem}")
            path = root / row["sample_path"]
            got = path.read_bytes()
            if got != raw:
                raise SystemExit(f"{path}: sample bytes differ from independent re-derivation")
            vals = array("i")
            vals.frombytes(got)
            if sys.byteorder != "little":
                vals.byteswap()
            distinct = len(set(vals))
            checks = {
                "value_count": len(vals),
                "sample_size_bytes": len(got),
                "min": min(vals),
                "max": max(vals),
                "distinct_values": distinct,
                "spots_kept": st["kept"],
                "spots_missing": st["missing"],
                "spots_flagged": st["flagged"],
                "records": st["records"],
                "sample_sha256": hashlib.sha256(got).hexdigest(),
            }
            for key, value in checks.items():
                if row.get(key) != value:
                    raise SystemExit(f"{path}: index {key}={row.get(key)!r}, re-derived {value!r}")
            if row["numeric_kind"] != "int" or row["bit_width"] != 32 or row["element_size_bytes"] != 4 or row["endianness"] != "little":
                raise SystemExit(f"{path}: wrong type fields in index")
            if distinct < MIN_DISTINCT or min(vals) == max(vals):
                raise SystemExit(f"{path}: degenerate sample ({distinct} distinct values)")
            if min(vals) <= 0:
                raise SystemExit(f"{path}: non-positive value")
            if max(vals) < 2**24:
                raise SystemExit(f"{path}: values fit 24 bits; not a genuine 32-bit stream")
            totals[sid][0] += 1
            totals[sid][1] += len(got)
        print(
            f"verified {n}/{len(sources)} {src['phase']}/{src['file']} kept={st['kept']} missing={st['missing']} "
            f"flagged={st['flagged']} kept_fraction={frac:.4f} geom_share={st['geom_share']:.5f} "
            f"max_offnadir_deg={st['max_offnadir_deg']:.2f}",
            flush=True,
        )

    manifest = tomllib.loads(args.manifest.read_text(encoding="utf-8"))
    mseries = {s["id"]: s for s in manifest["series"]}
    for sid in SERIES:
        s = mseries[sid]
        if (s["sample_count"], s["total_size_bytes"]) != tuple(totals[sid]):
            raise SystemExit(f"manifest {sid}: sample_count/total_size_bytes {s['sample_count']}/{s['total_size_bytes']} != realized {totals[sid]}")
    concat = hashlib.sha256()
    for row in index:
        concat.update((root / row["sample_path"]).read_bytes())
    print(
        f"verify ok orbits={len(sources)} kept_spots={all_kept} of {all_spots} ({all_kept / all_spots:.4f}) "
        f"series={ {k: v for k, v in totals.items()} } concat_sha256={concat.hexdigest()}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
