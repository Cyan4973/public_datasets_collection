#!/usr/bin/env python3
"""Independent verifier: re-walks every local FITS prefix with its own card parser, byte-swaps
the IMAGE data with a different method than build.py, byte-compares each sample, recomputes
statistics from the stored little-endian float32, and checks index, manifest and scope."""
from __future__ import annotations

import argparse
import collections
import csv
import hashlib
import json
import math
import re
import sys
import tomllib
from pathlib import Path

DATASET_ID = "irsa_spherex_qr3_l2_spectral_image_f32"
SERIES_ID = "spherex_qr3_d1_l2_image_mjysr_f32"
N_ROWS = N_COLS = 2040
VALUES = N_ROWS * N_COLS
NBYTES = VALUES * 4
EXPECTED_FILES = 30
EXPECTED_GROUPS = 10
PER_GROUP = 3
MAX_NONFINITE = 0.02
MIN_DISTINCT = 100_000
CARD_RE = re.compile(r"^([A-Z0-9_-]{1,8})\s*=\s*('(?:[^']|'')*'|[^/]*)")
INDEX_KEYS = ["dataset_id", "series_id", "sample_path", "numeric_kind", "bit_width", "endianness",
              "element_size_bytes", "sample_size_bytes", "value_count"]

errors: list[str] = []


def err(msg: str) -> None:
    errors.append(msg)
    print(f"ERROR {msg}")


def hdu_header(buf: bytes, start: int) -> tuple[dict, int]:
    """Second implementation: split into 80-char cards with a regex; stop at the END card."""
    text_cards = {}
    pos = start
    while True:
        if pos + 80 > len(buf) or pos - start > 64 * 2880:
            raise ValueError("no END card")
        card = buf[pos:pos + 80].decode("ascii")
        pos += 80
        if card.rstrip() == "END":
            break
        m = CARD_RE.match(card)
        if m:
            raw = m.group(2).strip()
            text_cards[m.group(1)] = raw[1:-1].replace("''", "'").rstrip() if raw.startswith("'") else raw
    data = ((pos - 1) // 2880 + 1) * 2880
    if buf[pos:data].strip(b" "):
        raise ValueError("non-blank header padding")
    return text_cards, data


def swap_be32(src: bytes) -> bytes:
    out = bytearray(len(src))
    out[0::4] = src[3::4]
    out[1::4] = src[2::4]
    out[2::4] = src[1::4]
    out[3::4] = src[0::4]
    return bytes(out)


def stats(payload: bytes) -> dict:
    mv = memoryview(payload)
    vals = mv.cast("f")
    nan = sum(1 for x in vals if x != x)
    fin = [x for x in vals if x == x and abs(x) != math.inf]
    inf = len(vals) - nan - len(fin)
    return {"nan_count": nan, "inf_count": inf, "finite_min": min(fin) if fin else None,
            "finite_max": max(fin) if fin else None, "finite_mean": math.fsum(fin) / len(fin) if fin else None,
            "distinct_bit_patterns": len(set(mv.cast("I")))}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", required=True)
    ap.add_argument("--recipe-dir", required=True)
    a = ap.parse_args()
    data, recipe = Path(a.data_dir), Path(a.recipe_dir)
    if sys.byteorder != "little":
        raise SystemExit("FATAL little-endian host required")
    manifest = tomllib.loads((recipe / "manifest.toml").read_text(encoding="utf-8"))
    series = [s for s in manifest["series"] if s["id"] == SERIES_ID]
    if len(series) != 1:
        raise SystemExit("FATAL manifest series missing")
    ser = series[0]
    with (recipe / "sources.tsv").open(encoding="utf-8", newline="") as fh:
        sources = {r["name"]: r for r in csv.DictReader(fh, delimiter="\t")}
    with (data / "downloads" / DATASET_ID / "download_plan.tsv").open(encoding="utf-8", newline="") as fh:
        plan = {r["name"]: r for r in csv.DictReader(fh, delimiter="\t")}
    rows = [json.loads(line) for line in (data / "index" / DATASET_ID / "samples.jsonl").read_text().splitlines()]

    if len(sources) != EXPECTED_FILES or len(rows) != EXPECTED_FILES:
        err(f"expected {EXPECTED_FILES} sources and index rows, got {len(sources)} / {len(rows)}")
    out_dir = data / "samples" / DATASET_ID / SERIES_ID
    on_disk = sorted(p.name for p in out_dir.glob("*"))
    if on_disk != sorted(Path(r["sample_path"]).name for r in rows):
        err("sample directory contents differ from the index")

    groups = collections.Counter()
    digests = set()
    total = 0
    for r in rows:
        for k in INDEX_KEYS:
            if k not in r:
                err(f"index row missing {k}")
        name = r.get("source_file", "")
        src = sources.get(name)
        if src is None:
            err(f"index row for unpinned file {name}")
            continue
        if (r["dataset_id"], r["series_id"], r["numeric_kind"], r["bit_width"], r["endianness"],
                r["element_size_bytes"], r["value_count"], r["sample_size_bytes"]) != (
                DATASET_ID, SERIES_ID, "float", 32, "little", 4, VALUES, NBYTES):
            err(f"{name}: index type/size fields wrong")
        if r["sample_path"] != f"samples/{DATASET_ID}/{SERIES_ID}/{name[:-5]}.f32":
            err(f"{name}: unexpected sample_path {r['sample_path']}")
        sample = (data / r["sample_path"]).read_bytes()
        prefix = (data / "downloads" / DATASET_ID / "image_prefix" / f"{name[:-5]}.primary_image.fits").read_bytes()
        if hashlib.sha256(prefix).hexdigest() != plan[name]["sha256"]:
            err(f"{name}: download prefix SHA-256 differs from download_plan.tsv")
        try:
            prim, p_end = hdu_header(prefix, 0)
            img, d_off = hdu_header(prefix, p_end)
        except (ValueError, UnicodeDecodeError) as exc:
            err(f"{name}: header walk failed: {exc}")
            continue
        checks = {"SIMPLE": "T", "NAXIS": "0"}
        for k, v in checks.items():
            if prim.get(k) != v:
                err(f"{name}: PRIMARY {k}={prim.get(k)!r}")
        want = {"XTENSION": "IMAGE", "BITPIX": "-32", "NAXIS": "2", "NAXIS1": str(N_COLS), "NAXIS2": str(N_ROWS),
                "EXTNAME": "IMAGE", "BUNIT": "MJy / sr", "DETECTOR": "1", "PCOUNT": "0", "GCOUNT": "1",
                "L2DQAFLG": "Pass", "OBSID": src["obsid"]}
        for k, v in want.items():
            if img.get(k) != v:
                err(f"{name}: IMAGE {k}={img.get(k)!r} expected {v!r}")
        if any(k in img for k in ("BLANK", "ZIMAGE")) or img.get("BZERO", "0") not in ("0", "0.0") \
                or img.get("BSCALE", "1") not in ("1", "1.0"):
            err(f"{name}: unexpected scaling/compression cards")
        if d_off != int(src["data_offset"]) or d_off + NBYTES != len(prefix):
            err(f"{name}: data offset {d_off} / prefix length {len(prefix)} inconsistent")
        if hashlib.sha256(prefix[:d_off]).hexdigest() != src["header_sha256"]:
            err(f"{name}: header SHA-256 differs from sources.tsv")
        if swap_be32(prefix[d_off:d_off + NBYTES]) != sample:
            err(f"{name}: sample bytes differ from the re-derived IMAGE data")
        digest = hashlib.sha256(sample).hexdigest()
        if digest != r.get("sha256"):
            err(f"{name}: sample SHA-256 differs from index")
        if digest in digests:
            err(f"{name}: duplicate sample")
        digests.add(digest)
        st = stats(sample)
        for k in ("nan_count", "inf_count", "finite_min", "finite_max", "distinct_bit_patterns"):
            if st[k] != r.get(k):
                err(f"{name}: {k} recomputed {st[k]!r} != index {r.get(k)!r}")
        if st["finite_mean"] is None or not math.isclose(st["finite_mean"], r.get("finite_mean"), rel_tol=1e-6,
                                                          abs_tol=1e-8):
            err(f"{name}: finite_mean recomputed {st['finite_mean']!r} != index {r.get('finite_mean')!r}")
        nonfinite = st["nan_count"] + st["inf_count"]
        if nonfinite > MAX_NONFINITE * VALUES:
            err(f"{name}: non-finite fraction {nonfinite / VALUES:.4f} above policy")
        if st["distinct_bit_patterns"] < MIN_DISTINCT or st["finite_min"] == st["finite_max"]:
            err(f"{name}: degenerate image")
        groups[src["week_group"]] += 1
        total += len(sample)
        print(f"ok {name} nan={st['nan_count']} distinct={st['distinct_bit_patterns']} mean={st['finite_mean']:.4f}")

    if len(groups) != EXPECTED_GROUPS or set(groups.values()) != {PER_GROUP}:
        err(f"week-group coverage wrong: {dict(groups)}")
    if ser["sample_count"] != len(rows) or ser["total_size_bytes"] != total:
        err(f"manifest sample_count/total_size_bytes {ser['sample_count']}/{ser['total_size_bytes']} "
            f"!= realized {len(rows)}/{total}")
    if errors:
        raise SystemExit(f"FATAL verify failed with {len(errors)} error(s)")
    print(f"verify_ok samples={len(rows)} total_bytes={total} groups={len(groups)}")


if __name__ == "__main__":
    main()
