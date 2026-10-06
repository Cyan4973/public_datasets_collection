#!/usr/bin/env python3
"""Independent verification of the IRIS level-1 FUV int16 frames.

Does not import iris_fits.py or build.py. It re-walks each pinned download with
its own FITS card reader, re-checks the S3 MD5/SHA-1 pins, recomputes DATASUM
and CHECKSUM with struct-based word sums, decodes every RICE_1 tile with a
byte-wise port of CFITSIO fits_rdecomp_short (nonzero_count table), recomputes
statistics with a sort-based method, byte-compares each emitted sample and
checks the index, the manifest totals, degeneracy and the realized scope.
"""

from __future__ import annotations

import argparse
import base64
import concurrent.futures as cf
import csv
import hashlib
import json
import os
import struct
import sys
import tomllib
from array import array
from pathlib import Path

DATASET_ID = "nasa_heliocloud_iris_l1_fuv_frames_i16"
SERIES_ID = "iris_fuv_l1_full_readout_dn_i16"
NX, NY = 4144, 1096
BLANK = -32768
EXPECTED_FILES = 40
MIN_OBSIDS = 7
MIN_YEARS = 9

NONZERO_COUNT = [0] + [b.bit_length() for b in range(1, 256)]


class VerifyError(Exception):
    pass


# ------------------------------------------------------------ FITS reading
def cards_at(blob: bytes, offset: int) -> tuple[dict, int]:
    out: dict = {}
    pos = offset
    while pos + 2880 <= len(blob):
        for i in range(36):
            text = blob[pos + 80 * i:pos + 80 * (i + 1)].decode("ascii")
            key = text[:8].strip()
            if key == "END":
                return out, pos + 2880
            if text[8:10] != "= ":
                continue
            val = text[10:].strip()
            if val.startswith("'"):
                end = val.find("'", 1)
                while end != -1 and val[end + 1:end + 2] == "'":
                    end = val.find("'", end + 2)
                out[key] = val[1:end].replace("''", "'").rstrip()
            else:
                token = val.split("/")[0].strip()
                if token in ("T", "F"):
                    out[key] = token == "T"
                else:
                    try:
                        out[key] = int(token)
                    except ValueError:
                        out[key] = float(token)
        pos += 2880
    raise VerifyError("header without END")


def word_sum(buf: bytes, start: int = 0) -> int:
    total = start
    step = 4 * 65536
    for i in range(0, len(buf), step):
        chunk = buf[i:i + step]
        total += sum(struct.unpack(f">{len(chunk) // 4}I", chunk))
    while total > 0xFFFFFFFF:
        total = (total & 0xFFFFFFFF) + (total >> 32)
    return total


# ------------------------------------------------------------ Rice (byte-wise)
def rice_decode_bytewise(c: bytes, nx: int, nblock: int = 32) -> array:
    """Line-by-line port of CFITSIO fits_rdecomp_short (fsbits 4, fsmax 14, bbits 16)."""
    clen = len(c)
    if clen < 3:
        raise VerifyError("tile too short")
    lastpix = (c[0] << 8) | c[1]
    ci = 2
    b = c[ci]
    ci += 1
    nbits = 8
    out = array("H", bytes(2 * nx))
    i = 0
    try:
        while i < nx:
            nbits -= 4
            while nbits < 0:
                b = (b << 8) | c[ci]
                ci += 1
                nbits += 8
            fs = (b >> nbits) - 1
            b &= (1 << nbits) - 1
            imax = i + nblock
            if imax > nx:
                imax = nx
            if fs < 0:
                while i < imax:
                    out[i] = lastpix
                    i += 1
            elif fs == 14:
                while i < imax:
                    k = 16 - nbits
                    diff = b << k
                    k -= 8
                    while k >= 0:
                        b = c[ci]
                        ci += 1
                        diff |= b << k
                        k -= 8
                    if nbits > 0:
                        b = c[ci]
                        ci += 1
                        diff |= b >> (-k)
                        b &= (1 << nbits) - 1
                    else:
                        b = 0
                    if diff & 1:
                        diff = ~(diff >> 1)
                    else:
                        diff >>= 1
                    lastpix = (diff + lastpix) & 0xFFFF
                    out[i] = lastpix
                    i += 1
            else:
                while i < imax:
                    while b == 0:
                        nbits += 8
                        b = c[ci]
                        ci += 1
                    nzero = nbits - NONZERO_COUNT[b]
                    nbits -= nzero + 1
                    b ^= 1 << nbits
                    nbits -= fs
                    while nbits < 0:
                        b = (b << 8) | c[ci]
                        ci += 1
                        nbits += 8
                    diff = (nzero << fs) | (b >> nbits)
                    b &= (1 << nbits) - 1
                    if diff & 1:
                        diff = ~(diff >> 1)
                    else:
                        diff >>= 1
                    lastpix = (diff + lastpix) & 0xFFFF
                    out[i] = lastpix
                    i += 1
    except IndexError as exc:
        raise VerifyError("hit end of compressed byte stream") from exc
    if ci != clen:
        raise VerifyError(f"unused bytes at end of compressed tile ({clen - ci})")
    return out


def decode_frame(blob: bytes) -> tuple[bytes, dict]:
    prim, table_off = cards_at(blob, 0)
    if not (prim.get("SIMPLE") is True and prim.get("NAXIS") == 0 and prim.get("EXTEND") is True):
        raise VerifyError("unexpected primary header")
    t, data_off = cards_at(blob, table_off)
    want = {"XTENSION": "BINTABLE", "NAXIS1": 8, "NAXIS2": NY, "TFIELDS": 1, "ZIMAGE": True,
            "ZCMPTYPE": "RICE_1", "ZBITPIX": 16, "ZNAXIS": 2, "ZNAXIS1": NX, "ZNAXIS2": NY,
            "ZTILE1": NX, "ZTILE2": 1, "ZVAL1": 32, "ZVAL2": 2, "BLANK": BLANK,
            "INSTRUME": "FUV", "IMG_PATH": "FUV", "IMG_TYPE": "LIGHT", "SUMSPTRL": 1,
            "SUMSPAT": 1, "CRS_NREG": 2, "MISSVALS": 0, "TELESCOP": "IRIS", "LUTID": 0}
    for k, v in want.items():
        if t.get(k) != v:
            raise VerifyError(f"{k}={t.get(k)!r} expected {v!r}")
    for k in ("ZSCALE", "ZZERO", "ZBLANK", "ZQUANTIZ", "BZERO", "BSCALE", "THEAP"):
        if k in t:
            raise VerifyError(f"unexpected {k}")
    if float(t["LVL_NUM"]) != 1.0 or not str(t["TFORM1"]).startswith("1PB("):
        raise VerifyError("not a level-1 1PB-descriptor RICE table")
    nbytes = 8 * NY + int(t["PCOUNT"])
    end = data_off + (nbytes + 2879) // 2880 * 2880
    if end != len(blob):
        raise VerifyError("file does not end with the compressed image HDU")
    dsum = word_sum(blob[data_off:end])
    if str(dsum) != str(t["DATASUM"]):
        raise VerifyError("DATASUM mismatch")
    if word_sum(blob[table_off:data_off], dsum) != 0xFFFFFFFF:
        raise VerifyError("CHECKSUM mismatch")

    heap = data_off + 8 * NY
    descriptors = struct.unpack(f">{2 * NY}i", blob[data_off:heap])
    image = array("h")
    for r in range(NY):
        n, off = descriptors[2 * r], descriptors[2 * r + 1]
        if n <= 0 or off < 0 or off + n > int(t["PCOUNT"]):
            raise VerifyError(f"bad descriptor row {r}")
        image.frombytes(rice_decode_bytewise(blob[heap + off:heap + off + n], NX).tobytes())

    # Readout geometry: BLANK exactly outside the two regions (computed per pixel).
    inside_cols = bytearray(NX)
    rows_in = []
    for k in (1, 2):
        c0, c1 = t[f"TSC{k}"] - 1, t[f"TEC{k}"] - 1
        r0, r1 = t[f"TSR{k}"] - 1, t[f"TER{k}"] - 1
        for c in range(c0, c1 + 1):
            inside_cols[c] = 1
        rows_in.append((r0, r1))
    if rows_in[0] != rows_in[1]:
        raise VerifyError("readout regions have different row spans")
    r0, r1 = rows_in[0]
    if not (0 <= r0 <= r1 < NY):
        raise VerifyError("readout rows outside the frame")
    if (t["TSC1"], t["TEC1"], t["TSC2"], t["TEC2"]) != (1, 2048, 2097, 4112):
        raise VerifyError("unexpected readout columns")
    blank_mask = bytes(1 - x for x in inside_cols)
    for r in range(NY):
        row = image[r * NX:(r + 1) * NX]
        got = bytes(1 if v == BLANK else 0 for v in row)
        exp = blank_mask if r0 <= r <= r1 else b"\x01" * NX
        if got != exp:
            raise VerifyError(f"BLANK layout mismatch in row {r}")
    valid = sorted(v for v in image if v != BLANK)
    n = len(valid)
    if n != t["DATAVALS"] or n != (r1 - r0 + 1) * sum(inside_cols):
        raise VerifyError("valid pixel count mismatch")
    if valid[0] != t["DATAMIN"] or valid[-1] != t["DATAMAX"]:
        raise VerifyError("DATAMIN/DATAMAX mismatch")
    if t["DATAMEDN"] not in (valid[(n - 1) // 2], valid[n // 2]):
        raise VerifyError("DATAMEDN mismatch")
    mean = sum(valid) / n
    if abs(mean - float(t["DATAMEAN"])) > 1e-3:
        raise VerifyError("DATAMEAN mismatch")
    present = set(valid)
    distinct = len(present)
    if distinct < 64 or valid[0] == valid[-1]:
        raise VerifyError("degenerate frame")
    # Unit-DN lattice near the pedestal (rejects onboard square-root companding, LUTID 4).
    med = t["DATAMEDN"]
    if not all(v in present for v in range(med - 5, med + 16)):
        raise VerifyError("value lattice is not unit-DN around DATAMEDN")
    if sys.byteorder != "little":
        image.byteswap()
    facts = {"obsid": t["ISQOLTID"], "t_obs": t["T_OBS"], "fsn": t["FSN"], "valid": n,
             "blank": NX * NY - n, "min": valid[0], "max": valid[-1], "median": t["DATAMEDN"],
             "distinct": distinct, "exptime": t["EXPTIME"]}
    return image.tobytes(), facts


# ------------------------------------------------------------ main
def check_one(job) -> dict:
    src, fits_path, sample_path = job
    blob = Path(fits_path).read_bytes()
    if len(blob) != int(src["size_bytes"]):
        raise VerifyError(f"{src['filename']}: size mismatch")
    if hashlib.md5(blob).hexdigest() != src["md5_etag"]:
        raise VerifyError(f"{src['filename']}: MD5 != pinned ETag")
    if base64.b64encode(hashlib.sha1(blob).digest()).decode() != src["sha1_b64"]:
        raise VerifyError(f"{src['filename']}: SHA-1 != pinned x-amz-checksum-sha1")
    raw, facts = decode_frame(blob)
    sample = Path(sample_path).read_bytes()
    if sample != raw:
        raise VerifyError(f"{src['filename']}: emitted sample differs from independent decode")
    for key, fk in (("obsid", "obsid"), ("t_obs", "t_obs"), ("fsn", "fsn"), ("datavals", "valid"),
                    ("datamin", "min"), ("datamax", "max"), ("datamedn", "median")):
        if str(src[key]) != str(facts[fk]):
            raise VerifyError(f"{src['filename']}: {key} differs from pin")
    facts["source_sha256"] = hashlib.sha256(blob).hexdigest()
    facts["sample_sha256"] = hashlib.sha256(sample).hexdigest()
    return facts


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", required=True)
    ap.add_argument("--recipe-dir", required=True)
    ap.add_argument("--jobs", type=int, default=min(8, os.cpu_count() or 1))
    args = ap.parse_args()
    data, recipe = Path(args.data_dir), Path(args.recipe_dir)
    manifest = tomllib.loads((recipe / "manifest.toml").read_text())
    series = [s for s in manifest["series"] if s["id"] == SERIES_ID]
    if len(series) != 1 or series[0]["role"] != "primary":
        raise SystemExit("manifest primary series missing")
    series = series[0]
    with open(recipe / "sources.tsv", newline="") as fh:
        sources = list(csv.DictReader(fh, delimiter="\t"))
    index_rows = [json.loads(line) for line in
                  (data / "index" / DATASET_ID / "samples.jsonl").read_text().splitlines() if line]
    if len(sources) != EXPECTED_FILES or len(index_rows) != EXPECTED_FILES:
        raise SystemExit(f"expected {EXPECTED_FILES} sources and index rows")
    by_path = {r["sample_path"]: r for r in index_rows}
    jobs = []
    sample_dir = data / "samples" / DATASET_ID / SERIES_ID
    for src in sources:
        rel = f"samples/{DATASET_ID}/{SERIES_ID}/{Path(src['filename']).stem}.i16"
        row = by_path.get(rel)
        if row is None:
            raise SystemExit(f"index lacks {rel}")
        want = {"dataset_id": DATASET_ID, "series_id": SERIES_ID, "numeric_kind": "int",
                "bit_width": 16, "endianness": "little", "element_size_bytes": 2,
                "sample_size_bytes": 2 * NX * NY, "value_count": NX * NY, "source_key": src["key"]}
        for k, v in want.items():
            if row.get(k) != v:
                raise SystemExit(f"index {rel}: {k}={row.get(k)!r} expected {v!r}")
        jobs.append((src, str(data / "downloads" / DATASET_ID / "fits" / src["filename"]),
                     str(data / rel)))
    extra = {p.name for p in sample_dir.iterdir()} - {Path(j[2]).name for j in jobs}
    if extra:
        raise SystemExit(f"unexpected files in samples dir: {sorted(extra)[:5]}")
    with cf.ProcessPoolExecutor(max_workers=max(1, args.jobs)) as pool:
        results = list(pool.map(check_one, jobs))
    for (src, _f, spath), facts in zip(jobs, results):
        row = by_path[Path(spath).relative_to(data).as_posix()]
        for k, fk in (("valid_count", "valid"), ("blank_count", "blank"), ("valid_min", "min"),
                      ("valid_max", "max"), ("obsid", "obsid"), ("sample_sha256", "sample_sha256"),
                      ("source_sha256", "source_sha256"), ("distinct_valid_values", "distinct")):
            if row.get(k) != facts[fk]:
                raise SystemExit(f"index {spath}: {k}={row.get(k)!r} recomputed {facts[fk]!r}")
        if row.get("min_value") != BLANK or row.get("max_value") != facts["max"]:
            raise SystemExit(f"index {spath}: min_value/max_value disagree with stored values")
        if src.get("sha256") and src["sha256"] != facts["source_sha256"]:
            raise SystemExit(f"{src['filename']}: SHA-256 differs from pinned sources.tsv")
        print(f"ok {Path(spath).name} obsid={facts['obsid']} valid={facts['valid']} "
              f"min={facts['min']} median={facts['median']} max={facts['max']} distinct={facts['distinct']}")
    if len({f["sample_sha256"] for f in results}) != len(results):
        raise SystemExit("duplicate samples")
    total = sum(r["sample_size_bytes"] for r in index_rows)
    if series["sample_count"] != len(index_rows) or series["total_size_bytes"] != total:
        raise SystemExit("manifest sample_count/total_size_bytes disagree with output")
    obsids = {f["obsid"] for f in results}
    years = {s["date"][:4] for s in sources}
    if len(obsids) < MIN_OBSIDS or len(years) < MIN_YEARS:
        raise SystemExit(f"scope too narrow: obsids={len(obsids)} years={len(years)}")
    blank = sum(f["blank"] for f in results)
    print(f"verify ok samples={len(results)} bytes={total} obsids={len(obsids)} years={len(years)} "
          f"blank_fraction={blank / (len(results) * NX * NY):.4f}")


if __name__ == "__main__":
    try:
        main()
    except VerifyError as exc:
        raise SystemExit(f"verify failed: {exc}")
