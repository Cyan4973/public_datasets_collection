#!/usr/bin/env python3
"""Build per-orbit int32 samples (kept-spot radius and range, mm) from the
pinned LOLA RDR orbit products. Local files only."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import struct
import sys
from array import array
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import lola_rdr  # noqa: E402

DATASET_ID = "nasa_pds_lola_rdr_spot_radius_range_i32"
SERIES = (("spot_radius_mm_i32", "radius"), ("spot_range_mm_i32", "range"))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-root", type=Path, required=True)
    ap.add_argument("--sources", type=Path, required=True)
    args = ap.parse_args()
    root = args.data_root
    down = root / "downloads" / DATASET_ID
    samples = root / "samples" / DATASET_ID
    index_dir = root / "index" / DATASET_ID
    filtered = root / "filtered" / DATASET_ID
    for p in (index_dir, filtered):
        p.mkdir(parents=True, exist_ok=True)
    for sid, _ in SERIES:
        d = samples / sid
        d.mkdir(parents=True, exist_ok=True)
        for old in d.glob("*.i32"):
            old.unlink()

    lola_rdr.check_fmt_text((down / "lolardr.fmt").read_text(encoding="ascii"))
    rows = lola_rdr.read_sources(args.sources)
    index_rows = []
    stats = []
    for n, src in enumerate(rows, 1):
        phase, name = src["phase"], src["file"]
        stem = name[: -len(".dat")]
        label = down / phase / f"{stem}.lbl"
        if lola_rdr.md5_file(label) != src["lbl_md5"]:
            raise SystemExit(f"{label}: MD5 differs from pin")
        label_text = label.read_text(encoding="ascii", errors="replace")
        fields = lola_rdr.check_label_text(label_text, src)
        lasers = sorted(set(re.findall(r"\bLASER_([12])\b", label_text)))
        if len(lasers) != 1:
            raise SystemExit(f"{label}: expected exactly one LASER_n in INSTRUMENT_MODE_ID, found {lasers}")
        result = lola_rdr.check_dat(down / phase / name, src)
        counts = result["counts"]
        orbit_stat = {
            "phase": phase,
            "source_file": name,
            "source_md5": src["dat_md5"],
            "orbit_number": int(fields.get("ORBIT_NUMBER", "-1")),
            "start_time": fields.get("START_TIME"),
            "stop_time": fields.get("STOP_TIME"),
            "product_version": fields.get("PRODUCT_VERSION_ID"),
            "laser": int(lasers[0]),
            "records": int(src["records"]),
            "spots_total": result["spots"],
            "spots_kept": counts["kept"],
            "spots_missing": counts["missing"],
            "spots_flagged": counts["flagged"],
            "kept_fraction": round(counts["kept"] / result["spots"], 6),
            "kept_per_spot": result["per_spot"],
        }
        stats.append(orbit_stat)
        for sid, key in SERIES:
            values = result[key]
            arr = array("i", values)
            if arr.itemsize != 4:
                raise SystemExit("array('i') is not 32-bit on this platform")
            if sys.byteorder != "little":
                arr.byteswap()
            raw = arr.tobytes()
            out = samples / sid / f"{stem}.i32"
            out.write_bytes(raw)
            index_rows.append(
                {
                    "dataset_id": DATASET_ID,
                    "series_id": sid,
                    "sample_path": str(out.relative_to(root)),
                    "numeric_kind": "int",
                    "bit_width": 32,
                    "endianness": "little",
                    "element_size_bytes": 4,
                    "sample_size_bytes": len(raw),
                    "value_count": len(values),
                    "min": min(values),
                    "max": max(values),
                    "distinct_values": len(set(values)),
                    "sample_sha256": hashlib.sha256(raw).hexdigest(),
                    **orbit_stat,
                }
            )
        print(
            f"built {n}/{len(rows)} {phase}/{name} records={src['records']} kept={counts['kept']} "
            f"missing={counts['missing']} flagged={counts['flagged']} kept_fraction={orbit_stat['kept_fraction']:.4f}",
            flush=True,
        )
    with (index_dir / "samples.jsonl").open("w", encoding="utf-8") as fh:
        for row in index_rows:
            fh.write(json.dumps(row, sort_keys=True) + "\n")
    summary = {}
    for sid, _ in SERIES:
        rs = [r for r in index_rows if r["series_id"] == sid]
        summary[sid] = {
            "samples": len(rs),
            "values": sum(r["value_count"] for r in rs),
            "bytes": sum(r["sample_size_bytes"] for r in rs),
            "min": min(r["min"] for r in rs),
            "max": max(r["max"] for r in rs),
        }
    tot = {k: sum(s[k] for s in stats) for k in ("records", "spots_total", "spots_kept", "spots_missing", "spots_flagged")}
    (filtered / "build_stats.json").write_text(json.dumps({"orbits": stats, "totals": tot, "series": summary}, indent=1) + "\n")
    print(json.dumps({"totals": tot, "series": summary}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
