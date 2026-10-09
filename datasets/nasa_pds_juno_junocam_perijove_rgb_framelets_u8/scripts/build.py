#!/usr/bin/env python3
"""Emit the 8-bit JunoCam IMAGE raster of each selected perijove lossless colour EDR as one raw sample."""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import junocam as jc  # noqa: E402


def stats(data: bytes, lines: int) -> dict:
    counts = collections.Counter(data)
    width = jc.LINE_SAMPLES
    zero_line = bytes(width)
    zero_lines = sum(1 for i in range(lines) if data[i * width:(i + 1) * width] == zero_line)
    framelet = jc.FRAMELET_LINES * width
    zero_framelets = sum(1 for i in range(lines // jc.FRAMELET_LINES) if not any(data[i * framelet:(i + 1) * framelet]))
    mode_value, mode_count = counts.most_common(1)[0]
    return {
        "min": min(counts), "max": max(counts), "distinct": len(counts),
        "zero_fraction": round(counts.get(0, 0) / len(data), 6),
        "mode_value": mode_value, "mode_share": round(mode_count / len(data), 6),
        "zero_lines": zero_lines, "zero_line_fraction": round(zero_lines / lines, 6),
        "zero_framelets": zero_framelets,
    }


def excluded(st: dict) -> str:
    if st["zero_line_fraction"] > jc.MAX_ZERO_LINE_FRACTION:
        return f"zero_line_fraction {st['zero_line_fraction']} > {jc.MAX_ZERO_LINE_FRACTION}"
    if st["mode_share"] > jc.MAX_MODE_SHARE:
        return f"mode_share {st['mode_share']} > {jc.MAX_MODE_SHARE}"
    if st["distinct"] < jc.MIN_DISTINCT_DN:
        return f"distinct DN {st['distinct']} < {jc.MIN_DISTINCT_DN}"
    return ""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--recipe-dir", type=Path, required=True)
    args = parser.parse_args()
    root = args.data_dir
    dl = root / "downloads" / jc.DATASET_ID
    out_dir = root / "samples" / jc.DATASET_ID / jc.SERIES_ID
    index_path = root / "index" / jc.DATASET_ID / "samples.jsonl"
    stats_path = root / "filtered" / jc.DATASET_ID / "ingest_stats.json"
    for path in (out_dir, index_path.parent, stats_path.parent):
        path.mkdir(parents=True, exist_ok=True)

    # Re-derive the selection from local index tables and labels; it must equal the pins.
    sources = jc.read_tsv(args.recipe_dir / "sources.tsv")
    chosen = jc.select(jc.candidates(dl / "index"), dl / "labels")
    if [c["product_id"] for c in chosen] != [s["product_id"] for s in sources]:
        raise SystemExit("FATAL local re-derived selection differs from sources.tsv")

    rows, dropped, seen_md5 = [], [], set()
    for src in sources:
        pid, orbit = src["product_id"], int(src["orbit"])
        label = jc.parse_label((dl / "labels" / f"{pid}.LBL").read_text(encoding="latin-1"))
        problems = jc.label_checks(label, pid, orbit)
        if problems:
            raise SystemExit(f"FATAL {pid}: label deviates: {'; '.join(problems)}")
        lines = int(label["IMAGE.LINES"])
        data = (dl / "img" / f"{pid}.IMG").read_bytes()
        if len(data) != lines * jc.LINE_SAMPLES or len(data) != int(src["img_size"]):
            raise SystemExit(f"FATAL {pid}: IMG size {len(data)} != LINES {lines} x {jc.LINE_SAMPLES}")
        md5 = hashlib.md5(data).hexdigest()
        if md5 != src["img_md5"] or md5 != label["IMAGE.MD5_CHECKSUM"].lower():
            raise SystemExit(f"FATAL {pid}: IMG MD5 mismatch")
        if md5 in seen_md5:
            raise SystemExit(f"FATAL {pid}: duplicate image payload")
        seen_md5.add(md5)
        st = stats(data, lines)
        reason = excluded(st)
        if reason:
            dropped.append({"product_id": pid, "orbit": orbit, "reason": reason, **st})
            print(f"excluded product={pid} orbit={orbit} {reason}")
            continue
        # The IMAGE object starts at byte 0 of the detached-label IMG (^IMAGE = file, record 1),
        # with no line prefix/suffix: the 8-bit DN raster is the file content in line order.
        target = out_dir / f"{pid}.u8"
        tmp = target.with_suffix(".u8.tmp")
        tmp.write_bytes(data)
        os.replace(tmp, target)
        rows.append({
            "dataset_id": jc.DATASET_ID, "series_id": jc.SERIES_ID,
            "sample_path": str(target.relative_to(root)),
            "numeric_kind": "uint", "bit_width": 8, "endianness": "little",
            "element_size_bytes": 1, "sample_size_bytes": len(data), "value_count": len(data),
            "shape": [lines, jc.LINE_SAMPLES], "framelets": lines // jc.FRAMELET_LINES,
            "exposures": lines // jc.EXPOSURE_LINES, "product_id": pid, "volume": src["volume"], "orbit": orbit,
            "rel_minutes_to_perijove": int(src["rel_minutes"]), "start_time": label.get("START_TIME"),
            "tdi_stages": label.get("JNO:TDI_STAGES_COUNT"), "exposure_duration": label.get("EXPOSURE_DURATION"),
            "spacecraft_altitude": label.get("SPACECRAFT_ALTITUDE"), "source_md5": md5, **st,
        })
        print(f"emitted product={pid} orbit={orbit} lines={lines} zero_lines={st['zero_lines']} mode_share={st['mode_share']} distinct={st['distinct']}")

    keep = {Path(row["sample_path"]).name for row in rows}
    for stale in out_dir.iterdir():
        if stale.name not in keep:
            stale.unlink()
    tmp_index = index_path.with_suffix(".jsonl.tmp")
    tmp_index.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in rows), encoding="utf-8")
    os.replace(tmp_index, index_path)
    total = sum(row["sample_size_bytes"] for row in rows)
    stats_path.write_text(json.dumps({
        "dataset_id": jc.DATASET_ID, "pinned_products": len(sources), "emitted": len(rows), "excluded": dropped,
        "total_size_bytes": total, "orbits": [row["orbit"] for row in rows],
        "rule": {"max_zero_line_fraction": jc.MAX_ZERO_LINE_FRACTION, "max_mode_share": jc.MAX_MODE_SHARE,
                 "min_distinct_dn": jc.MIN_DISTINCT_DN},
    }, indent=2) + "\n", encoding="utf-8")
    print(f"build summary pinned={len(sources)} emitted={len(rows)} excluded={len(dropped)} total_bytes={total}")
    if not rows:
        raise SystemExit("FATAL no samples emitted")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
