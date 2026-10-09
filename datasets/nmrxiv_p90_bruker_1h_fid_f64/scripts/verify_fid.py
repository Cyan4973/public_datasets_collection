#!/usr/bin/env python3
"""Independent verification of the nmrXiv P90 1H zg30 FID samples.

Does not import the build code. Re-parses every downloaded acqus with its own
reader, re-derives the expected sample set, re-decodes each source fid and
byte-compares it with the emitted sample, and checks the index and manifest.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import struct
import tomllib
import zlib
from pathlib import Path

DATASET_ID = "nmrxiv_p90_bruker_1h_fid_f64"
SERIES_ID = "bruker_1h_zg30_fid_f64"
N = 65536
EXPECTED = 152
RULE = {"DTYPA": "2", "NUC1": "<1H>", "PULPROG": "<zg30>", "TD": "65536", "PARMODE": "0", "SOLVENT": "<DMSO>", "INSTRUM": "<Avance Neo 600>"}


def acqus(path: Path) -> dict:
    text = path.read_text(encoding="latin-1")
    params = dict(re.findall(r"^##\$(\w+)=[ \t]*([^\r\n]*?)[ \t]*$", text, flags=re.M))
    m = re.search(r"^##TITLE=.*?TopSpin\s+(\d+\.\d+\.\d+)", text, flags=re.M)
    params["_topspin"] = m.group(1) if m else ""
    return params


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-root", required=True)
    ap.add_argument("--manifest", required=True)
    args = ap.parse_args()
    root = Path(args.data_root)
    members = root / "downloads" / DATASET_ID / "members"
    errors: list[str] = []

    # Expected set straight from the local acqus files.
    expected: dict[str, tuple[Path, dict]] = {}
    tally: dict[str, int] = {}
    for acq in sorted(members.glob("*/*/acqus")):
        p = acqus(acq)
        key = f"{p.get('PULPROG')}|{p.get('NUC1')}|{p['_topspin']}|{p.get('SOLVENT')}"
        tally[key] = tally.get(key, 0) + 1
        if all(p.get(k) == v for k, v in RULE.items()) and p["_topspin"] == "4.0.5":
            fraction, experiment = acq.parent.parent.name, acq.parent.name
            expected[f"{fraction}__{experiment}"] = (acq.parent / "fid", p)
    if len(expected) != EXPECTED:
        errors.append(f"acqus re-derivation found {len(expected)} FIDs, expected {EXPECTED}")

    index_path = root / "index" / DATASET_ID / "samples.jsonl"
    rows = [json.loads(line) for line in index_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    seen_ids = set()
    digests = set()
    total = 0
    global_min, global_max = math.inf, -math.inf
    f32_exact = integral = scanned = 0
    for row in rows:
        sid = row.get("sample_id")
        if sid in seen_ids:
            errors.append(f"duplicate sample id {sid}")
        seen_ids.add(sid)
        if sid not in expected:
            errors.append(f"unexpected sample {sid}")
            continue
        for key, want in (("dataset_id", DATASET_ID), ("series_id", SERIES_ID), ("numeric_kind", "float"), ("bit_width", 64),
                          ("endianness", "little"), ("element_size_bytes", 8), ("value_count", N), ("sample_size_bytes", 8 * N)):
            if row.get(key) != want:
                errors.append(f"{sid}: index {key}={row.get(key)!r} want {want!r}")
        src_path, params = expected[sid]
        src = src_path.read_bytes()
        if len(src) != 8 * N:
            errors.append(f"{sid}: source fid has {len(src)} bytes")
            continue
        if f"{zlib.crc32(src) & 0xFFFFFFFF:08x}" != row.get("source_crc32"):
            errors.append(f"{sid}: source CRC32 differs from the index")
        order = {"0": "<", "1": ">"}.get(params.get("BYTORDA"))
        if order is None:
            errors.append(f"{sid}: bad BYTORDA {params.get('BYTORDA')!r}")
            continue
        values = struct.unpack(f"{order}{N}d", src)
        sample = (root / row["sample_path"]).read_bytes()
        if sample != struct.pack(f"<{N}d", *values):
            errors.append(f"{sid}: sample bytes differ from the decoded source fid")
            continue
        if hashlib.sha256(sample).hexdigest() != row.get("sha256"):
            errors.append(f"{sid}: sha256 mismatch")
        digests.add(row.get("sha256"))
        if not all(math.isfinite(v) for v in values):
            errors.append(f"{sid}: non-finite values")
        distinct = len(set(values))
        if distinct < 0.5 * N:
            errors.append(f"{sid}: degenerate ({distinct} distinct values)")
        if min(values) != row.get("min") or max(values) != row.get("max"):
            errors.append(f"{sid}: min/max mismatch")
        if max(abs(v) for v in values) < 1e6:
            errors.append(f"{sid}: implausibly small FID amplitude")
        global_min, global_max = min(global_min, min(values)), max(global_max, max(values))
        for v in values[::16]:
            scanned += 1
            integral += v == int(v)
            f32_exact += struct.unpack("<f", struct.pack("<f", v))[0] == v
        total += len(sample)
    missing = sorted(set(expected) - seen_ids)
    if missing:
        errors.append(f"{len(missing)} expected samples missing, e.g. {missing[:3]}")
    if len(digests) != len(rows):
        errors.append("duplicate sample payloads")
    on_disk = sorted(p.name for p in (root / "samples" / DATASET_ID / SERIES_ID).glob("*"))
    if len(on_disk) != len(rows):
        errors.append(f"{len(on_disk)} files on disk vs {len(rows)} index rows")

    manifest = tomllib.loads(Path(args.manifest).read_text(encoding="utf-8"))
    series = [s for s in manifest["series"] if s["id"] == SERIES_ID]
    if len(series) != 1:
        errors.append("manifest series missing")
    else:
        if series[0]["sample_count"] != len(rows):
            errors.append(f"manifest sample_count {series[0]['sample_count']} != {len(rows)}")
        if series[0]["total_size_bytes"] != total:
            errors.append(f"manifest total_size_bytes {series[0]['total_size_bytes']} != {total}")

    for key in sorted(tally):
        print(f"acqus_tally {tally[key]:4d} {key}")
    print(
        f"samples={len(rows)} total_bytes={total} min={global_min} max={global_max} "
        f"scanned={scanned} f32_exact={f32_exact / max(scanned, 1):.3f} integral={integral / max(scanned, 1):.3f}"
    )
    if errors:
        for e in errors[:40]:
            print("ERROR", e)
        raise SystemExit(f"verify failed with {len(errors)} errors")
    print("verify ok")


if __name__ == "__main__":
    main()
