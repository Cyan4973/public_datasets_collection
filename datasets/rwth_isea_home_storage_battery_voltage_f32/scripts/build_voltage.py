#!/usr/bin/env python3
"""Build float32 pack-voltage samples from pinned ISEA system-month CSV members.

Input: raw ZIP member spans (local header + deflate data) fetched by download.sh.
Output: one little-endian float32 sample per complete system-month, holding the
V_in_V column in file order (one value per second), plus samples.jsonl.

Policy (verify_voltage.py re-checks every point independently):
  * the month must be complete: exactly days*86400 rows whose Time field is
    every second of the month in order (no gaps, duplicates or DST shifts);
  * V_in_V must be a finite decimal in [25, 65] V; blank or NaN is fatal;
  * Interpolated must be 0 or 1, with at most 1% of rows set to 1; interpolated rows stay in
    place (they keep the 1 Hz lattice) and their runs are recorded;
  * logged (Interpolated=0) tokens must round-trip exactly through float32
    (%.6g of the stored float32 equals the source decimal);
  * at least half of the logged tokens must carry six significant digits, the
    shared logger lattice of the kept systems (system 13 prints 1 mV steps and
    system 17 10 mV steps; both are excluded from the selection);
  * the selected system must be a 46-51.8 V nominal pack per Metadata_Systems.xlsx.
"""
from __future__ import annotations

import argparse
import calendar
import concurrent.futures
import csv
import hashlib
import io
import json
import math
import os
import re
import struct
import sys
import zipfile
import zlib
from array import array
from pathlib import Path

DATASET_ID = "rwth_isea_home_storage_battery_voltage_f32"
SERIES_ID = "isea_hss_pack_terminal_voltage_f32"
HEADER = b"Time,P_in_W,V_in_V,I_in_A,T_Bat_in_C,T_Room_in_C,Interpolated"
MONTH_ABBR = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
V_MIN, V_MAX = 25.0, 65.0
MAX_INTERPOLATED_SHARE = 0.01
MIN_SIX_DIGIT_SHARE = 0.5
NOMINAL_RANGE = (46.0, 51.8)
LOCAL_HEADER = struct.Struct("<IHHHHHIIIHH")


def read_selection(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    keys = [(row["system_id"], row["month"]) for row in rows]
    if len(set(keys)) != len(keys):
        raise SystemExit("selection.tsv lists a system-month twice")
    return rows


def read_system_metadata(meta_zip: Path) -> dict[int, dict]:
    with zipfile.ZipFile(meta_zip) as outer:
        inner_bytes = outer.read("00_Data/00_Metadata/Metadata_Systems.xlsx")
    with zipfile.ZipFile(io.BytesIO(inner_bytes)) as book:
        shared_xml = book.read("xl/sharedStrings.xml").decode("utf-8")
        sheet_xml = book.read("xl/worksheets/sheet1.xml").decode("utf-8")
    shared = [re.sub(r"<[^>]+>", "", item) for item in re.findall(r"<si>(.*?)</si>", shared_xml, re.S)]
    table: list[list[str]] = []
    for row_xml in re.findall(r"<row[^>]*>(.*?)</row>", sheet_xml, re.S):
        cells = []
        for attrs, inner in re.findall(r"<c ([^>]*?)(?:/>|>(.*?)</c>)", row_xml, re.S):
            value = re.search(r"<v>(.*?)</v>", inner or "")
            text = value.group(1) if value else ""
            if 't="s"' in attrs and text:
                text = shared[int(text)]
            cells.append(text)
        table.append(cells)
    header = table[0]
    out: dict[int, dict] = {}
    for cells in table[1:]:
        row = dict(zip(header, cells))
        out[int(row["ID"])] = {
            "voltage_nominal_v": float(row["Voltage_nominal_in_V"]),
            "cells_in_series": int(float(row["Cell_number_in_series"])),
            "manufacturer": row["Manufacturer"],
            "chemistry": row["Chemistry"],
            "capacity_nominal_ah": float(row["Capacity_nominal_in_Ah"]),
        }
    return out


def member_lines(span_path: Path, member_name: str, compressed: int):
    """Yield CSV lines (bytes, without newline) of one raw ZIP member span."""
    with span_path.open("rb") as handle:
        sig, _v, flags, method, _t, _d, _crc, _cs, _us, name_len, extra_len = LOCAL_HEADER.unpack(handle.read(LOCAL_HEADER.size))
        name = handle.read(name_len).decode("utf-8" if flags & 0x800 else "cp437")
        handle.read(extra_len)
        if sig != 0x04034B50 or method != 8 or name != member_name:
            raise ValueError(f"{span_path}: not the expected deflated member {member_name}")
        inflater = zlib.decompressobj(-zlib.MAX_WBITS)
        remaining = compressed
        tail = b""
        while remaining:
            block = handle.read(min(remaining, 8 * 1024 * 1024))
            if not block:
                raise ValueError(f"{span_path}: truncated deflate data")
            remaining -= len(block)
            lines = (tail + inflater.decompress(block)).split(b"\n")
            tail = lines.pop()
            yield from lines
        lines = (tail + inflater.flush()).split(b"\n")
        tail = lines.pop()
        yield from lines
        if tail:
            raise ValueError(f"{span_path}: last line lacks a newline")
        if not inflater.eof or inflater.unused_data:
            raise ValueError(f"{span_path}: deflate stream does not end at the member boundary")


def significant_digits(token: bytes) -> int:
    digits = token.lstrip(b"+-").replace(b".", b"").lstrip(b"0")
    return len(digits)


def process_member(task: dict) -> dict:
    row = task["row"]
    sid = int(row["system_id"])
    year, month = (int(part) for part in row["month"].split("_"))
    days = calendar.monthrange(year, month)[1]
    expected_rows = days * 86400
    if expected_rows != int(row["expected_rows"]):
        raise ValueError(f"{row['member_name']}: expected_rows column disagrees with calendar")
    hms = [f"{h:02d}:{m:02d}:{s:02d}".encode() for h in range(24) for m in range(60) for s in range(60)]
    prefixes = [f"{d:02d}-{MONTH_ABBR[month - 1]}-{year:04d} ".encode() for d in range(1, days + 1)]

    lines = member_lines(Path(task["span_path"]), row["member_name"], int(row["compressed_bytes"]))
    first = next(lines)
    if first != HEADER:
        raise ValueError(f"{row['member_name']}: header {first[:80]!r}")

    out = bytearray()
    cache: dict[bytes, bytes] = {}
    logged_cache: set[bytes] = set()
    interpolated = 0
    runs: list[list[int]] = []
    run_start = -1
    six_digit = 0
    logged = 0
    interp_inexact = 0
    index = 0
    pack = struct.Struct("<f").pack
    unpack = struct.Struct("<f").unpack
    for line in lines:
        if index >= expected_rows:
            raise ValueError(f"{row['member_name']}: more than {expected_rows} rows")
        fields = line.split(b",")
        if len(fields) != 7:
            raise ValueError(f"{row['member_name']}: row {index} has {len(fields)} fields")
        if fields[0] != prefixes[index // 86400] + hms[index % 86400]:
            raise ValueError(f"{row['member_name']}: row {index} time {fields[0]!r} breaks the 1 s lattice")
        token = fields[2]
        packed = cache.get(token)
        if packed is None:
            if not token or b"n" in token.lower() or b"e" in token.lower():
                raise ValueError(f"{row['member_name']}: row {index} V_in_V token {token!r} (blank/NaN/exponent)")
            value = float(token)
            if not (math.isfinite(value) and V_MIN <= value <= V_MAX):
                raise ValueError(f"{row['member_name']}: row {index} V_in_V {token!r} outside [{V_MIN}, {V_MAX}]")
            packed = pack(value)
            cache[token] = packed
        flag = fields[6]
        if flag == b"0":
            logged += 1
            if significant_digits(token) == 6:
                six_digit += 1
            if token not in logged_cache:
                stored = unpack(packed)[0]
                if float("%.6g" % stored) != float(token):
                    raise ValueError(f"{row['member_name']}: logged token {token!r} does not round-trip through float32")
                logged_cache.add(token)
            if run_start >= 0:
                runs.append([run_start, index - run_start])
                run_start = -1
        elif flag == b"1":
            interpolated += 1
            if significant_digits(token) > 6:
                interp_inexact += 1
            if run_start < 0:
                run_start = index
        else:
            raise ValueError(f"{row['member_name']}: row {index} Interpolated flag {flag!r}")
        out += packed
        index += 1
    if run_start >= 0:
        runs.append([run_start, index - run_start])
    if index != expected_rows:
        raise ValueError(f"{row['member_name']}: incomplete month, {index} rows != {expected_rows}")
    share = interpolated / expected_rows
    if share > MAX_INTERPOLATED_SHARE:
        raise ValueError(f"{row['member_name']}: interpolated share {share:.4%} > {MAX_INTERPOLATED_SHARE:.0%}")
    six_share = six_digit / logged if logged else 0.0
    if six_share < MIN_SIX_DIGIT_SHARE:
        raise ValueError(f"{row['member_name']}: six-significant-digit share {six_share:.3f} < {MIN_SIX_DIGIT_SHARE} (different logger lattice)")

    values = array("f")
    values.frombytes(bytes(out))
    if sys.byteorder != "little":
        values.byteswap()
    distinct = len(set(values))
    vmin, vmax = min(values), max(values)
    if distinct < 100 or vmax - vmin < 0.5:
        raise ValueError(f"{row['member_name']}: degenerate series distinct={distinct} range={vmax - vmin:.4f}")

    sample_path = Path(task["sample_path"])
    sample_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = sample_path.with_suffix(".part")
    tmp.write_bytes(out)
    tmp.replace(sample_path)
    runs_path = Path(task["runs_path"])
    runs_path.parent.mkdir(parents=True, exist_ok=True)
    runs_path.write_text(json.dumps({"member": row["member_name"], "interpolated_runs_start_length": runs}, separators=(",", ":")) + "\n", encoding="utf-8")
    return {
        "system_id": sid,
        "month": row["month"],
        "member": row["member_name"],
        "rows": index,
        "interpolated_rows": interpolated,
        "interpolated_share": round(share, 8),
        "interpolated_runs": len(runs),
        "interpolated_tokens_over_6_sig_digits": interp_inexact,
        "logged_rows": logged,
        "logged_six_sig_digit_share": round(six_share, 6),
        "distinct_values": distinct,
        "min": vmin,
        "max": vmax,
        "sha256": hashlib.sha256(out).hexdigest(),
        "bytes": len(out),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--selection", required=True, type=Path)
    parser.add_argument("--data-root", required=True, type=Path)
    parser.add_argument("--workers", type=int, default=0)
    args = parser.parse_args()

    root = args.data_root
    downloads = root / "downloads" / DATASET_ID
    samples_dir = root / "samples" / DATASET_ID / SERIES_ID
    filtered = root / "filtered" / DATASET_ID
    index_path = root / "index" / DATASET_ID / "samples.jsonl"
    selection = read_selection(args.selection)
    metadata = read_system_metadata(downloads / "Metadata_and_Code.zip")

    tasks = []
    for row in selection:
        sid = int(row["system_id"])
        meta = metadata.get(sid)
        if meta is None or not (NOMINAL_RANGE[0] <= meta["voltage_nominal_v"] <= NOMINAL_RANGE[1]):
            raise SystemExit(f"system {sid}: nominal voltage {meta and meta['voltage_nominal_v']} outside the 48 V class")
        if not 13 <= meta["cells_in_series"] <= 16:
            raise SystemExit(f"system {sid}: {meta['cells_in_series']} cells in series")
        if sid in (13, 17):
            raise SystemExit(f"system {sid} uses a coarser voltage lattice and is excluded")
        if sid == 18:
            raise SystemExit("system 18 has no complete month free of disconnection readings and is excluded")
        stem = f"system_{row['system_id']}_{row['month']}"
        span_path = downloads / "members" / row["system_id"] / f"{row['month']}_System_ID_{row['system_id']}.zipmember"
        if not span_path.is_file() or span_path.stat().st_size != int(row["span_bytes"]):
            raise SystemExit(f"missing or wrong-sized download {span_path}; run download.sh")
        tasks.append({
            "row": row,
            "span_path": str(span_path),
            "sample_path": str(samples_dir / f"{stem}.f32"),
            "runs_path": str(filtered / "interpolated_runs" / f"{stem}.json"),
        })

    if samples_dir.exists():
        expected = {Path(task["sample_path"]).name for task in tasks}
        for stale in samples_dir.iterdir():
            if stale.name not in expected:
                stale.unlink()
    workers = args.workers or min(len(tasks), os.cpu_count() or 1, 16)
    results: dict[tuple[str, str], dict] = {}
    with concurrent.futures.ProcessPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(process_member, task): task for task in tasks}
        for future in concurrent.futures.as_completed(futures):
            task = futures[future]
            result = future.result()
            results[(task["row"]["system_id"], task["row"]["month"])] = result
            print(
                f"built system={result['system_id']:02d} month={result['month']} rows={result['rows']} "
                f"interp={result['interpolated_rows']} ({result['interpolated_share']:.4%}) "
                f"six_digit_share={result['logged_six_sig_digit_share']:.3f} distinct={result['distinct_values']} "
                f"range={result['min']:.4f}..{result['max']:.4f}",
                flush=True,
            )

    index_path.parent.mkdir(parents=True, exist_ok=True)
    filtered.mkdir(parents=True, exist_ok=True)
    total_values = total_bytes = 0
    with index_path.with_suffix(".jsonl.part").open("w", encoding="utf-8") as handle:
        for task in tasks:
            row = task["row"]
            result = results[(row["system_id"], row["month"])]
            meta = metadata[int(row["system_id"])]
            sample_path = Path(task["sample_path"])
            entry = {
                "dataset_id": DATASET_ID,
                "series_id": SERIES_ID,
                "sample_path": str(sample_path.relative_to(root)),
                "numeric_kind": "float",
                "bit_width": 32,
                "endianness": "little",
                "element_size_bytes": 4,
                "sample_size_bytes": result["bytes"],
                "value_count": result["rows"],
                "system_id": int(row["system_id"]),
                "month": row["month"].replace("_", "-"),
                "source_member": row["member_name"],
                "source_archive": row["zip_key"],
                "manufacturer": meta["manufacturer"],
                "chemistry": meta["chemistry"],
                "voltage_nominal_v": meta["voltage_nominal_v"],
                "cells_in_series": meta["cells_in_series"],
                "sample_rate_hz": 1,
                "interpolated_rows": result["interpolated_rows"],
                "interpolated_share": result["interpolated_share"],
                "min": result["min"],
                "max": result["max"],
                "sha256": result["sha256"],
            }
            handle.write(json.dumps(entry, sort_keys=True) + "\n")
            total_values += result["rows"]
            total_bytes += result["bytes"]
    index_path.with_suffix(".jsonl.part").replace(index_path)
    stats = {
        "dataset_id": DATASET_ID,
        "series_id": SERIES_ID,
        "samples": len(tasks),
        "systems": sorted({int(task["row"]["system_id"]) for task in tasks}),
        "total_values": total_values,
        "total_bytes": total_bytes,
        "policy": {
            "complete_month_rows": "days*86400, every second in order",
            "v_range": [V_MIN, V_MAX],
            "max_interpolated_share": MAX_INTERPOLATED_SHARE,
            "min_logged_six_sig_digit_share": MIN_SIX_DIGIT_SHARE,
            "nominal_voltage_range": list(NOMINAL_RANGE),
        },
        "months": [results[(task["row"]["system_id"], task["row"]["month"])] for task in tasks],
    }
    (filtered / "ingest_stats.json").write_text(json.dumps(stats, indent=1) + "\n", encoding="utf-8")
    print(f"build_summary samples={len(tasks)} values={total_values} bytes={total_bytes}")


if __name__ == "__main__":
    main()
