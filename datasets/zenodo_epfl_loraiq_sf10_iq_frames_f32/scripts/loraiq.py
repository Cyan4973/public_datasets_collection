#!/usr/bin/env python3
"""LoRaIQ SF10 SigMF members: range validation (download) and sample build.

Each downloaded `.zipr` file is an exact byte range of the pinned Zenodo
`sigmfs.zip` (v1.0.0): the local header + deflated `.sigmf-data` member,
immediately followed by the local header + deflated `.sigmf-meta` member.
Local headers are parsed with their own name/extra lengths (they differ from
the central directory's extra length), members are inflated with raw DEFLATE
(wbits -15) and checked against the pinned central-directory CRC32/sizes.

Subcommands:
  validate  one range file (+ curl header dump) -> exit 0 if fully valid
  build     all selected range files -> raw cf32_le samples + samples.jsonl
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
import struct
import sys
import zlib
from array import array
from pathlib import Path

DATASET_ID = "zenodo_epfl_loraiq_sf10_iq_frames_f32"
SERIES_ID = "loraiq_sf10_iq_cf32"
ARCHIVE_BYTES = 49_746_561_196
EXPECTED_ANNOTATION = {"sf": "10", "cr": "1", "fc": "862.5", "bandwidth": "250000", "rx_sample_rate": "500000"}
GRID = 32768.0
MAX_GRID_FRACTION = 0.01
MIN_UNIQUE_FRACTION = 0.5


def read_selection(path: Path) -> list[dict]:
    with path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    if not rows:
        raise SystemExit("empty selection")
    return rows


def range_name(row: dict) -> str:
    return f"{row['session']}_{row['rrh']}_{row['file_no']}.zipr"


def sample_name(row: dict) -> str:
    return f"{row['session']}_{row['rrh']}_{row['file_no']}.f32"


def check_headers(headers_path: Path, start: int, end: int) -> None:
    text = headers_path.read_text(encoding="iso-8859-1")
    responses = [p for p in re.split(r"(?=^HTTP/)", text, flags=re.MULTILINE) if p.strip()]
    if not responses:
        raise ValueError("empty header dump")
    final = responses[-1]
    status = re.search(r"^HTTP/\S+\s+(\d+)", final, flags=re.MULTILINE)
    cr = re.search(r"^Content-Range:\s*bytes\s+(\d+)-(\d+)/(\d+)\s*$", final, flags=re.IGNORECASE | re.MULTILINE)
    if not status or int(status.group(1)) != 206 or not cr:
        raise ValueError(f"server did not honor range request: {final.splitlines()[:1]}")
    if tuple(map(int, cr.groups())) != (start, end, ARCHIVE_BYTES):
        raise ValueError(f"unexpected Content-Range {cr.groups()}")


def read_member(buf: bytes, rel: int, name: str, crc: int, csize: int, usize: int) -> tuple[bytes, int]:
    """Parse the local header at rel using its own lengths; return (raw, end_rel)."""
    if rel < 0 or rel + 30 > len(buf):
        raise ValueError(f"local header out of range for {name}")
    sig, _ver, flags, method, _mt, _md, l_crc, l_cs, l_us, nlen, elen = struct.unpack_from("<IHHHHHIIIHH", buf, rel)
    if sig != 0x04034B50:
        raise ValueError(f"bad local header signature for {name}")
    l_name = buf[rel + 30:rel + 30 + nlen].decode("utf-8" if flags & 0x800 else "cp437")
    if l_name != name:
        raise ValueError(f"local header name {l_name!r} != {name!r}")
    if flags & 0x1 or flags & 0x8 or method != 8:
        raise ValueError(f"unsupported flags/method {flags:#x}/{method} for {name}")
    extra = buf[rel + 30 + nlen:rel + 30 + nlen + elen]
    if l_cs == 0xFFFFFFFF or l_us == 0xFFFFFFFF:
        q = 0
        while q + 4 <= len(extra):
            hid, hsz = struct.unpack_from("<HH", extra, q)
            if hid == 1:
                r = q + 4
                if l_us == 0xFFFFFFFF:
                    l_us = struct.unpack_from("<Q", extra, r)[0]
                    r += 8
                if l_cs == 0xFFFFFFFF:
                    l_cs = struct.unpack_from("<Q", extra, r)[0]
            q += 4 + hsz
    if (l_crc, l_cs, l_us) != (crc, csize, usize):
        raise ValueError(f"local header CRC/sizes {(l_crc, l_cs, l_us)} != pinned {(crc, csize, usize)} for {name}")
    data_start = rel + 30 + nlen + elen
    data_end = data_start + csize
    if data_end > len(buf):
        raise ValueError(f"truncated member {name}")
    inflater = zlib.decompressobj(-15)
    raw = inflater.decompress(buf[data_start:data_end]) + inflater.flush()
    if not inflater.eof or inflater.unused_data:
        raise ValueError(f"DEFLATE stream of {name} does not end at the member boundary")
    if len(raw) != usize or (zlib.crc32(raw) & 0xFFFFFFFF) != crc:
        raise ValueError(f"inflated size/CRC32 mismatch for {name}")
    return raw, data_end


def parse_annotation(comment: str) -> dict:
    out = {}
    for line in comment.splitlines():
        if "\t" in line:
            k, v = line.split("\t", 1)
            out[k] = v
    return out


def decode_pair(range_path: Path, row: dict) -> tuple[bytes, dict, dict]:
    start, end = int(row["range_start"]), int(row["range_end"])
    buf = range_path.read_bytes()
    if len(buf) != end - start + 1:
        raise ValueError(f"range length {len(buf)} != {end - start + 1}")
    if int(row["data_offset"]) != start:
        raise ValueError("selection data_offset != range_start")
    data, d_end = read_member(buf, 0, row["data_name"], int(row["data_crc32"], 16),
                              int(row["data_csize"]), int(row["data_usize"]))
    meta_rel = int(row["meta_offset"]) - start
    if d_end != meta_rel:
        raise ValueError("meta local header does not directly follow the data member")
    meta_raw, m_end = read_member(buf, meta_rel, row["meta_name"], int(row["meta_crc32"], 16),
                                  int(row["meta_csize"]), int(row["meta_usize"]))
    if m_end != len(buf):
        raise ValueError("range has trailing bytes after the meta member")
    meta = json.loads(meta_raw.decode("utf-8"))
    g = meta.get("global", {})
    if g.get("core:datatype") != "cf32_le":
        raise ValueError(f"datatype {g.get('core:datatype')!r} != cf32_le")
    if g.get("core:sample_rate") != 500000:
        raise ValueError(f"sample_rate {g.get('core:sample_rate')!r} != 500000")
    if g.get("core:num_channels", 1) != 1:
        raise ValueError("num_channels != 1")
    if float(g.get("core:frequency", 0)) != 862.5:
        raise ValueError(f"frequency {g.get('core:frequency')!r} != 862.5")
    sha = g.get("core:sha512")
    if sha and hashlib.sha512(data).hexdigest() != sha.lower():
        raise ValueError("core:sha512 mismatch")
    caps = meta.get("captures", [])
    if len(caps) != 1 or caps[0].get("core:sample_start") != 0:
        raise ValueError(f"unexpected captures {caps!r}")
    anns = meta.get("annotations", [])
    if len(anns) != 1:
        raise ValueError(f"expected exactly one annotation, got {len(anns)}")
    ann = parse_annotation(str(anns[0].get("core:comment", "")))
    for k, v in EXPECTED_ANNOTATION.items():
        if ann.get(k) != v:
            raise ValueError(f"annotation {k}={ann.get(k)!r} != {v}")
    expected_file = "./" + row["data_name"][: -len(".sigmf-data")]
    if ann.get("sigmf_file") != expected_file:
        raise ValueError(f"annotation sigmf_file {ann.get('sigmf_file')!r} != {expected_file!r}")
    if len(data) % 8:
        raise ValueError("data length is not a whole number of cf32 complex samples")
    return data, meta, ann


def value_stats(data: bytes) -> dict:
    vals = array("f")
    vals.frombytes(data)
    if sys.byteorder != "little":
        vals.byteswap()
    n = len(vals)
    for v in vals:
        if not math.isfinite(v):
            raise ValueError("non-finite value")
    i_vals, q_vals = vals[0::2], vals[1::2]
    if min(i_vals) == max(i_vals) or min(q_vals) == max(q_vals):
        raise ValueError("constant I or Q component")
    on_grid = sum(1 for v in vals if v * GRID == round(v * GRID))
    unique = len({data[k:k + 4] for k in range(0, len(data), 4)})
    stats = {
        "min": min(vals), "max": max(vals),
        "grid_32768_fraction": on_grid / n, "unique_fraction": unique / n,
    }
    if stats["grid_32768_fraction"] > MAX_GRID_FRACTION:
        raise ValueError(f"{stats['grid_32768_fraction']:.4f} of values on the 1/32768 grid (widened int16?)")
    if stats["unique_fraction"] < MIN_UNIQUE_FRACTION:
        raise ValueError(f"unique fraction {stats['unique_fraction']:.4f} too low")
    return stats


def cmd_validate(args: argparse.Namespace) -> None:
    name = args.name or args.range.name
    rows = [r for r in read_selection(args.selection) if range_name(r) == name]
    if len(rows) != 1:
        raise SystemExit(f"{name} is not exactly one selection row")
    row = rows[0]
    try:
        if args.headers:
            check_headers(args.headers, int(row["range_start"]), int(row["range_end"]))
        data, _meta, _ann = decode_pair(args.range, row)
        stats = value_stats(data)
    except ValueError as exc:
        raise SystemExit(f"INVALID {name}: {exc}")
    print(f"valid {name} data_bytes={len(data)} grid={stats['grid_32768_fraction']:.5f} "
          f"unique={stats['unique_fraction']:.4f}")


def cmd_build(args: argparse.Namespace) -> None:
    rows = read_selection(args.selection)
    with args.csv.open(encoding="utf-8", newline="") as handle:
        csv_rows = {r["sigmf_file"]: r for r in csv.DictReader(handle)}
    out_dir = args.samples_dir / SERIES_ID
    out_dir.mkdir(parents=True, exist_ok=True)
    for stale in out_dir.glob("*.f32"):
        stale.unlink()
    args.index.parent.mkdir(parents=True, exist_ok=True)
    total = 0
    sessions, rrhs = set(), set()
    index_rows = []
    for row in rows:
        try:
            data, meta, ann = decode_pair(args.download_dir / "members" / range_name(row), row)
            stats = value_stats(data)
        except ValueError as exc:
            raise SystemExit(f"build failed for {range_name(row)}: {exc}")
        crow = csv_rows.get(ann["sigmf_file"])
        if crow is None:
            raise SystemExit(f"{ann['sigmf_file']} missing from dataset.csv")
        for k in ("sf", "cr", "fc", "bandwidth", "rx_sample_rate", "rrh_idx", "area_type",
                  "sigmf_file_offset", "sigmf_file_n_samples", "snr"):
            if crow[k] != ann.get(k):
                raise SystemExit(f"dataset.csv/{k} disagrees with sigmf-meta for {ann['sigmf_file']}")
        if f"rrh{crow['rrh_idx']}" != row["rrh"]:
            raise SystemExit("rrh mismatch")
        out = out_dir / sample_name(row)
        out.write_bytes(data)
        total += len(data)
        sessions.add(row["session"])
        rrhs.add(row["rrh"])
        index_rows.append({
            "dataset_id": DATASET_ID,
            "series_id": SERIES_ID,
            "sample_path": str(out.relative_to(args.data_root)),
            "numeric_kind": "float",
            "bit_width": 32,
            "endianness": "little",
            "element_size_bytes": 4,
            "sample_size_bytes": len(data),
            "value_count": len(data) // 4,
            "complex_sample_count": len(data) // 8,
            "layout": "interleaved I,Q float32 (SigMF cf32_le)",
            "source_member": row["data_name"],
            "source_sha512": meta["global"].get("core:sha512", ""),
            "session": row["session"],
            "rrh": row["rrh"],
            "area_type": row["area_type"],
            "sample_rate_hz": 500000,
            "center_frequency_mhz": 862.5,
            "frame_offset_samples": float(ann["sigmf_file_offset"]),
            "frame_n_samples": int(ann["sigmf_file_n_samples"]),
            "snr_db": float(ann["snr"]),
            "min": stats["min"],
            "max": stats["max"],
            "grid_32768_fraction": round(stats["grid_32768_fraction"], 6),
            "unique_fraction": round(stats["unique_fraction"], 6),
        })
    if total > 1_000_000_000:
        raise SystemExit(f"primary output {total} exceeds 1 GB")
    with args.index.open("w", encoding="utf-8") as handle:
        for r in index_rows:
            handle.write(json.dumps(r, sort_keys=True) + "\n")
    sizes = sorted(r["value_count"] for r in index_rows)
    summary = {
        "samples": len(index_rows), "total_bytes": total, "sessions": len(sessions), "rrhs": sorted(rrhs),
        "median_values": sizes[len(sizes) // 2], "min_values": sizes[0], "max_values": sizes[-1],
        "global_min": min(r["min"] for r in index_rows), "global_max": max(r["max"] for r in index_rows),
        "max_grid_32768_fraction": max(r["grid_32768_fraction"] for r in index_rows),
        "min_unique_fraction": min(r["unique_fraction"] for r in index_rows),
    }
    args.stats.parent.mkdir(parents=True, exist_ok=True)
    args.stats.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary))


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    v = sub.add_parser("validate")
    v.add_argument("--selection", type=Path, required=True)
    v.add_argument("--range", type=Path, required=True)
    v.add_argument("--headers", type=Path)
    v.add_argument("--name", help="selection range name when --range is a temporary path")
    b = sub.add_parser("build")
    b.add_argument("--selection", type=Path, required=True)
    b.add_argument("--download-dir", type=Path, required=True)
    b.add_argument("--csv", type=Path, required=True)
    b.add_argument("--samples-dir", type=Path, required=True)
    b.add_argument("--index", type=Path, required=True)
    b.add_argument("--stats", type=Path, required=True)
    b.add_argument("--data-root", type=Path, required=True)
    args = ap.parse_args()
    {"validate": cmd_validate, "build": cmd_build}[args.cmd](args)


if __name__ == "__main__":
    main()
