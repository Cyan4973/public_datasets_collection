#!/usr/bin/env python3
"""Build: one raw little-endian float64 sample per selected Bruker 1H zg30 fid.

Re-derives the selection from the local acqus files (does not trust the
download-time list blindly), decodes each fid as DTYPA=2 IEEE float64 with the
byte order given by BYTORDA, checks it, and writes it unchanged in value
(interleaved real/imaginary, group-delay points included).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from nmrxiv_zip import FID_BYTES, FID_VALUES, acqus_matches, local_relpath, parse_acqus, read_tsv  # noqa: E402

DATASET_ID = "nmrxiv_p90_bruker_1h_fid_f64"
SERIES_ID = "bruker_1h_zg30_fid_f64"
EXPECTED = 152


def sample_name(rel: str) -> str:
    fraction, experiment, leaf = rel.split("/")
    assert leaf == "fid"
    return f"{fraction}__{experiment}"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-root", required=True)
    args = ap.parse_args()
    root = Path(args.data_root)
    dl = root / "downloads" / DATASET_ID
    members = dl / "members"
    out_dir = root / "samples" / DATASET_ID / SERIES_ID
    index_path = root / "index" / DATASET_ID / "samples.jsonl"
    stats_path = root / "filtered" / DATASET_ID / "build_stats.json"
    out_dir.mkdir(parents=True, exist_ok=True)
    index_path.parent.mkdir(parents=True, exist_ok=True)
    stats_path.parent.mkdir(parents=True, exist_ok=True)

    all_rows = {r["name"]: r for r in read_tsv(dl / "zip" / "all_members.tsv")}
    candidates = read_tsv(dl / "zip" / "acqus_candidates.tsv")
    chosen = []
    excluded: dict[str, int] = {}
    for row in candidates:
        rel_acqus = local_relpath(row["name"])
        params = parse_acqus((members / rel_acqus).read_text(encoding="latin-1"))
        if not acqus_matches(params):
            key = f"{params.get('PULPROG')} {params.get('NUC1')} TopSpin {params['TOPSPIN']} {params.get('SOLVENT')}"
            excluded[key] = excluded.get(key, 0) + 1
            continue
        fid_name = row["name"].rsplit("/", 1)[0] + "/fid"
        chosen.append((local_relpath(fid_name), all_rows[fid_name], params))
    chosen.sort(key=lambda item: item[0])
    download_list = [r["name"] for r in read_tsv(dl / "zip" / "selected_fids.tsv")]
    if [local_relpath(n) for n in download_list] != [c[0] for c in chosen]:
        raise SystemExit("acqus-derived selection disagrees with the download-time selection")
    if len(chosen) != EXPECTED:
        raise SystemExit(f"selected {len(chosen)} FIDs, expected {EXPECTED}")

    for stale in out_dir.glob("*.f64"):
        stale.unlink()
    rows = []
    total = 0
    for rel, entry, params in chosen:
        raw = (members / rel).read_bytes()
        if len(raw) != FID_BYTES:
            raise SystemExit(f"{rel}: {len(raw)} bytes, expected {FID_BYTES}")
        order = {"0": "<", "1": ">"}[params["BYTORDA"]]
        values = struct.unpack(f"{order}{FID_VALUES}d", raw)
        if not all(math.isfinite(v) for v in values):
            raise SystemExit(f"{rel}: non-finite value")
        if len(set(values)) < 1000:
            raise SystemExit(f"{rel}: degenerate FID ({len(set(values))} distinct values)")
        payload = struct.pack(f"<{FID_VALUES}d", *values)
        name = sample_name(rel)
        path = out_dir / f"{name}.f64"
        path.write_bytes(payload)
        total += len(payload)
        rows.append(
            {
                "dataset_id": DATASET_ID,
                "series_id": SERIES_ID,
                "sample_id": name,
                "sample_path": str(path.relative_to(root)),
                "numeric_kind": "float",
                "bit_width": 64,
                "endianness": "little",
                "element_size_bytes": 8,
                "sample_size_bytes": len(payload),
                "value_count": FID_VALUES,
                "complex_points": FID_VALUES // 2,
                "layout": "interleaved_real_imaginary",
                "min": min(values),
                "max": max(values),
                "sha256": hashlib.sha256(payload).hexdigest(),
                "source_member": entry["name"],
                "source_crc32": f"{entry['crc32']:08x}",
                "bytorda": int(params["BYTORDA"]),
                "rg": float(params["RG"]),
                "grpdly": float(params["GRPDLY"]),
                "acq_date_unix": int(params["DATE"]),
            }
        )
    with index_path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, sort_keys=True) + "\n")
    stats = {
        "dataset_id": DATASET_ID,
        "acqus_candidates": len(candidates),
        "selected": len(rows),
        "excluded_by_acqus": excluded,
        "total_size_bytes": total,
        "total_values": FID_VALUES * len(rows),
    }
    stats_path.write_text(json.dumps(stats, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(stats, sort_keys=True))


if __name__ == "__main__":
    main()
