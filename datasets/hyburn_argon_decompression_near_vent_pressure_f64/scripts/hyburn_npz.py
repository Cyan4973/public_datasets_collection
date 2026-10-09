#!/usr/bin/env python3
"""Pure-stdlib helpers for the Hyburn near-vent pressure recipe.

The upstream objects are numpy.savez() ZIP archives (near_vent_NNNNNN.npz) on
Zenodo record 4127362.  Only the `pressure.npy` member is fetched, by exact
HTTP byte range, plus the archive tail (central directory and the tiny
`time.npy` member).  This module parses those byte ranges; all network I/O
happens in the shell scripts with curl.

Subcommands
  discover-parse   build the pinned member table from discovery ranges
  check-tail       validate a downloaded archive tail against the pinned table
  check-member     validate a downloaded pressure.npy member range
  build            inflate members and emit raw little-endian float64 samples
  verify           independently re-derive and check every sample
"""
from __future__ import annotations

import argparse
import ast
import csv
import hashlib
import json
import math
import re
import struct
import sys
import zlib
from collections import Counter
from pathlib import Path

DATASET_ID = "hyburn_argon_decompression_near_vent_pressure_f64"
SERIES_ID = "near_vent_pressure_pa_f64"
MEMBER = "pressure.npy"
TIME_MEMBER = "time.npy"
GRID = 500
VALUES = GRID * GRID
NPY_BYTES = 2_000_080  # 80-byte NPY v1 header + 250,000 float64
EXPECTED_MEMBERS = 33
TAIL_BYTES = 8192
# Sample-selection rule (documented in manifest/README).  Before the jet
# reaches and fills the near-vent window the slice is quiescent ambient air:
# 101325 Pa carrying only ~1e-8 Pa round-off noise (a few hundred distinct
# values), so a single-value test does not catch it.  A snapshot is kept only
# when at most MAX_AMBIENT_FRACTION of its 250,000 cells lie within
# AMBIENT_TOL_PA of AMBIENT_PA, and (generic degeneracy guard) no single
# float64 value covers more than MAX_DOMINANT_FRACTION of the cells.
AMBIENT_PA = 101325.0
AMBIENT_TOL_PA = 1.0
MAX_AMBIENT_FRACTION = 0.5
MAX_DOMINANT_FRACTION = 0.5
STRIDE = 2  # every second output snapshot (even snapshot numbers)

TABLE_FIELDS = [
    "key",
    "snapshot",
    "npz_size",
    "npz_md5",
    "member_count",
    "pressure_offset",
    "pressure_header_bytes",
    "pressure_csize",
    "pressure_usize",
    "pressure_crc32",
    "range_start",
    "range_end",
    "tail_start",
    "time_offset",
    "time_crc32",
    "time_s",
    "dominant_fraction",
    "ambient_fraction",
    "selected",
]


# --------------------------------------------------------------------------
# ZIP / NPY parsing
# --------------------------------------------------------------------------

def parse_central_directory(tail: bytes, tail_start: int, total: int) -> list[dict]:
    eocd = tail.rfind(b"PK\x05\x06")
    if eocd < 0 or eocd + 22 > len(tail):
        raise ValueError("EOCD not found in tail")
    _sig, disk, cd_disk, disk_entries, entries, cd_size, cd_offset, comment = struct.unpack_from(
        "<4s4H2IH", tail, eocd
    )
    if disk or cd_disk or disk_entries != entries:
        raise ValueError("multi-disk ZIP unsupported")
    if eocd + 22 + comment != len(tail):
        raise ValueError("EOCD does not end at the archive end")
    if tail_start + len(tail) != total:
        raise ValueError("tail does not end at the archive end")
    if cd_offset + cd_size != tail_start + eocd:
        raise ValueError("central directory not contiguous with EOCD")
    rel = cd_offset - tail_start
    if rel < 0:
        raise ValueError(f"central directory starts before the tail (need {total - cd_offset} bytes)")
    members = []
    cursor = rel
    while cursor < rel + cd_size:
        if tail[cursor : cursor + 4] != b"PK\x01\x02":
            raise ValueError("bad central directory signature")
        f = struct.unpack_from("<4s6H3I5H2I", tail, cursor)
        name_len, extra_len, comment_len = f[10], f[11], f[12]
        name = tail[cursor + 46 : cursor + 46 + name_len].decode("utf-8")
        members.append(
            {
                "name": name,
                "flags": f[3],
                "method": f[4],
                "crc32": f[7],
                "csize": f[8],
                "usize": f[9],
                "offset": f[16],
            }
        )
        cursor += 46 + name_len + extra_len + comment_len
    if cursor != rel + cd_size or len(members) != entries:
        raise ValueError("central directory entry count mismatch")
    return members


def parse_local_header(buf: bytes, pos: int = 0) -> dict:
    if buf[pos : pos + 4] != b"PK\x03\x04":
        raise ValueError("bad local header signature")
    f = struct.unpack_from("<4s5H3I2H", buf, pos)
    name_len, extra_len = f[9], f[10]
    return {
        "flags": f[2],
        "method": f[3],
        "crc32": f[6],
        "csize": f[7],
        "usize": f[8],
        "name": buf[pos + 30 : pos + 30 + name_len].decode("utf-8"),
        "header_bytes": 30 + name_len + extra_len,
    }


def parse_npy(raw: bytes) -> tuple[dict, int]:
    if raw[:6] != b"\x93NUMPY":
        raise ValueError("missing NPY magic")
    major = raw[6]
    if major == 1:
        hlen = struct.unpack_from("<H", raw, 8)[0]
        start = 10
    elif major in (2, 3):
        hlen = struct.unpack_from("<I", raw, 8)[0]
        start = 12
    else:
        raise ValueError(f"unsupported NPY version {major}")
    header = ast.literal_eval(raw[start : start + hlen].decode("latin1"))
    return header, start + hlen


def inflate_member(range_bytes: bytes, expected: dict) -> bytes:
    """Validate a local-header+data range and return the inflated member."""
    lh = parse_local_header(range_bytes)
    if lh["name"] != expected["name"]:
        raise ValueError(f"member name {lh['name']!r} != {expected['name']!r}")
    if lh["flags"] & 0x0008 or lh["flags"] & 0x0001:
        raise ValueError("data-descriptor or encrypted member unsupported")
    if lh["method"] != 8:
        raise ValueError(f"unexpected compression method {lh['method']}")
    for key in ("crc32", "csize", "usize"):
        if lh[key] != expected[key]:
            raise ValueError(f"local header {key} {lh[key]} != {expected[key]}")
    if lh["header_bytes"] != expected["header_bytes"]:
        raise ValueError("local header length differs from pinned value")
    if lh["header_bytes"] + lh["csize"] != len(range_bytes):
        raise ValueError("range length does not match header + compressed size")
    d = zlib.decompressobj(-15)
    raw = d.decompress(range_bytes[lh["header_bytes"] :]) + d.flush()
    if not d.eof or d.unused_data:
        raise ValueError("DEFLATE stream does not end at the member boundary")
    if len(raw) != lh["usize"] or (zlib.crc32(raw) & 0xFFFFFFFF) != lh["crc32"]:
        raise ValueError("inflated size/CRC32 mismatch")
    return raw


def pressure_values_bytes(raw: bytes) -> bytes:
    header, data_off = parse_npy(raw)
    if header != {"descr": "<f8", "fortran_order": False, "shape": (1, GRID, GRID)}:
        raise ValueError(f"unexpected NPY header {header!r}")
    payload = raw[data_off:]
    if len(payload) != VALUES * 8:
        raise ValueError(f"unexpected payload length {len(payload)}")
    return payload


def time_value(raw: bytes) -> float:
    header, data_off = parse_npy(raw)
    if header.get("descr") != "<f8" or header.get("shape") not in ((1,), ()):
        raise ValueError(f"unexpected time.npy header {header!r}")
    (value,) = struct.unpack_from("<d", raw, data_off)
    return value


def time_from_tail(tail: bytes, tail_start: int, member: dict) -> float:
    pos = member["offset"] - tail_start
    if pos < 0:
        raise ValueError("time.npy not inside tail")
    lh = parse_local_header(tail, pos)
    exp = dict(member, header_bytes=lh["header_bytes"])
    raw = inflate_member(tail[pos : pos + lh["header_bytes"] + lh["csize"]], exp)
    return time_value(raw)


def check_content_range(headers_path: Path, start: int, end: int, total: int) -> None:
    text = headers_path.read_text(encoding="iso-8859-1")
    parts = re.split(r"(?=^HTTP/)", text, flags=re.MULTILINE)
    final = next((p for p in reversed(parts) if p.strip()), "")
    status = re.search(r"^HTTP/\S+\s+(\d+)", final, flags=re.MULTILINE)
    cr = re.search(r"^Content-Range:\s*bytes\s+(\d+)-(\d+)/(\d+)\s*$", final, flags=re.IGNORECASE | re.MULTILINE)
    if not status or int(status.group(1)) != 206 or not cr:
        raise ValueError("server did not answer with 206 Partial Content")
    if tuple(map(int, cr.groups())) != (start, end, total):
        raise ValueError(f"unexpected Content-Range {cr.groups()} != {(start, end, total)}")


# --------------------------------------------------------------------------
# Statistics shared by build and verify
# --------------------------------------------------------------------------

def sample_stats(payload: bytes) -> dict:
    values = struct.unpack(f"<{VALUES}d", payload)
    nonfinite = sum(1 for v in values if not math.isfinite(v))
    counts = Counter(payload[i : i + 8] for i in range(0, len(payload), 8))
    top_bytes, top_count = counts.most_common(1)[0]
    finite = [v for v in values if math.isfinite(v)]
    # 2x2 block replication (coarse AMR levels upsampled to the uniform slice)
    rows = [values[r * GRID : (r + 1) * GRID] for r in range(GRID)]
    blocks_total = (GRID // 2) ** 2
    blocks_uniform = 0
    for r in range(0, GRID, 2):
        a, b = rows[r], rows[r + 1]
        for c in range(0, GRID, 2):
            if a[c] == a[c + 1] == b[c] == b[c + 1]:
                blocks_uniform += 1
    ambient = sum(1 for v in finite if abs(v - AMBIENT_PA) <= AMBIENT_TOL_PA)
    return {
        "ambient_fraction": round(ambient / VALUES, 6),
        "nonfinite": nonfinite,
        "distinct": len(counts),
        "dominant_value": struct.unpack("<d", top_bytes)[0],
        "dominant_fraction": round(top_count / VALUES, 6),
        "min": min(finite) if finite else None,
        "max": max(finite) if finite else None,
        "uniform_2x2_block_fraction": round(blocks_uniform / blocks_total, 6),
    }


def read_table(path: Path) -> list[dict]:
    with path.open(encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh, delimiter="\t"))
    for row in rows:
        for key in TABLE_FIELDS:
            if key not in row:
                raise SystemExit(f"pinned table missing column {key}")
    return rows


def member_expectation(row: dict) -> dict:
    return {
        "name": MEMBER,
        "crc32": int(row["pressure_crc32"], 16),
        "csize": int(row["pressure_csize"]),
        "usize": int(row["pressure_usize"]),
        "header_bytes": int(row["pressure_header_bytes"]),
    }


# --------------------------------------------------------------------------
# Subcommands
# --------------------------------------------------------------------------

def cmd_discover_parse(args: argparse.Namespace) -> None:
    files = json.loads(Path(args.files_json).read_text(encoding="utf-8"))["entries"]
    entries = sorted(
        (e for e in files if re.fullmatch(r"near_vent_\d{6}\.npz", e["key"])), key=lambda e: e["key"]
    )
    out_rows = []
    for e in entries:
        key = e["key"]
        stem = key[:-4]
        total = int(e["size"])
        tail = (Path(args.ranges_dir) / f"{stem}.tail").read_bytes()
        tail_start = total - len(tail)
        members = {m["name"]: m for m in parse_central_directory(tail, tail_start, total)}
        if len(members) != EXPECTED_MEMBERS:
            raise SystemExit(f"{key}: {len(members)} members")
        p = members[MEMBER]
        t = members[TIME_MEMBER]
        if p["method"] != 8 or p["flags"] or p["usize"] != NPY_BYTES:
            raise SystemExit(f"{key}: unexpected pressure.npy entry {p}")
        lh = parse_local_header((Path(args.ranges_dir) / f"{stem}.lh").read_bytes())
        if (lh["name"], lh["crc32"], lh["csize"], lh["usize"]) != (MEMBER, p["crc32"], p["csize"], p["usize"]):
            raise SystemExit(f"{key}: local header disagrees with central directory")
        time_s = time_from_tail(tail, tail_start, t)
        rng_start = p["offset"]
        rng_end = p["offset"] + lh["header_bytes"] + p["csize"] - 1
        row = {
            "key": key,
            "snapshot": int(stem.split("_")[-1]),
            "npz_size": total,
            "npz_md5": str(e["checksum"]).removeprefix("md5:"),
            "member_count": len(members),
            "pressure_offset": p["offset"],
            "pressure_header_bytes": lh["header_bytes"],
            "pressure_csize": p["csize"],
            "pressure_usize": p["usize"],
            "pressure_crc32": f"{p['crc32']:08x}",
            "range_start": rng_start,
            "range_end": rng_end,
            "tail_start": min(t["offset"], total - TAIL_BYTES),
            "time_offset": t["offset"],
            "time_crc32": f"{t['crc32']:08x}",
            "time_s": repr(time_s),
            "dominant_fraction": "",
            "ambient_fraction": "",
            "selected": "",
        }
        member_path = Path(args.ranges_dir) / f"{stem}.pressure"
        if member_path.is_file():
            raw = inflate_member(member_path.read_bytes(), member_expectation(row))
            st = sample_stats(pressure_values_bytes(raw))
            row["dominant_fraction"] = f"{st['dominant_fraction']:.6f}"
            row["ambient_fraction"] = f"{st['ambient_fraction']:.6f}"
        # Selection: even snapshot numbers; probed (early) snapshots must pass
        # the ambient/dominant rule.  Unprobed snapshots are all later than
        # every probed one; build.sh enforces the same rule on them and fails
        # loudly if a selected snapshot violates it.
        keep = int(row["snapshot"]) % STRIDE == 0
        if row["ambient_fraction"]:
            keep = keep and float(row["ambient_fraction"]) <= MAX_AMBIENT_FRACTION
            keep = keep and float(row["dominant_fraction"]) <= MAX_DOMINANT_FRACTION
        row["selected"] = "1" if keep else "0"
        out_rows.append(row)
    with Path(args.out).open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=TABLE_FIELDS, delimiter="\t", lineterminator="\n")
        w.writeheader()
        w.writerows(out_rows)
    print(f"pinned {len(out_rows)} near_vent archives -> {args.out}")


def cmd_check_tail(args: argparse.Namespace) -> None:
    rows = {r["key"]: r for r in read_table(Path(args.table))}
    row = rows[args.key]
    total = int(row["npz_size"])
    start = int(row["tail_start"])
    check_content_range(Path(args.headers), start, total - 1, total)
    tail = Path(args.tail).read_bytes()
    if len(tail) != total - start:
        raise SystemExit(f"{args.key}: tail length {len(tail)} != {total - start}")
    members = {m["name"]: m for m in parse_central_directory(tail, start, total)}
    p = members.get(MEMBER)
    if len(members) != int(row["member_count"]) or p is None:
        raise SystemExit(f"{args.key}: central directory changed")
    if (p["offset"], p["csize"], p["usize"], f"{p['crc32']:08x}") != (
        int(row["pressure_offset"]),
        int(row["pressure_csize"]),
        int(row["pressure_usize"]),
        row["pressure_crc32"],
    ):
        raise SystemExit(f"{args.key}: pressure.npy entry differs from pinned table")
    t = members[TIME_MEMBER]
    time_s = time_from_tail(tail, start, t)
    if repr(time_s) != row["time_s"]:
        raise SystemExit(f"{args.key}: time.npy {time_s!r} != pinned {row['time_s']}")


def cmd_check_member(args: argparse.Namespace) -> None:
    rows = {r["key"]: r for r in read_table(Path(args.table))}
    row = rows[args.key]
    check_content_range(Path(args.headers), int(row["range_start"]), int(row["range_end"]), int(row["npz_size"]))
    data = Path(args.member).read_bytes()
    raw = inflate_member(data, member_expectation(row))
    payload = pressure_values_bytes(raw)
    values = struct.unpack(f"<{VALUES}d", payload)
    if any(not math.isfinite(v) for v in values):
        raise SystemExit(f"{args.key}: non-finite pressure values")
    if min(values) <= 0:
        raise SystemExit(f"{args.key}: non-positive pressure")


def selected_rows(table: Path) -> list[dict]:
    rows = [r for r in read_table(table) if r["selected"] == "1"]
    rows.sort(key=lambda r: int(r["snapshot"]))
    return rows


def rel_to(path: Path, root: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def cmd_build(args: argparse.Namespace) -> None:
    data_root = Path(args.data_root)
    downloads = Path(args.downloads)
    samples_dir = Path(args.samples_dir) / SERIES_ID
    index_path = Path(args.index)
    stats_path = Path(args.stats)
    samples_dir.mkdir(parents=True, exist_ok=True)
    index_path.parent.mkdir(parents=True, exist_ok=True)
    stats_path.parent.mkdir(parents=True, exist_ok=True)
    for old in samples_dir.glob("*.f64"):
        old.unlink()
    rows = selected_rows(Path(args.table))
    index_rows = []
    per_sample = []
    for row in rows:
        stem = row["key"][:-4]
        data = (downloads / f"{stem}.pressure.zipmember").read_bytes()
        raw = inflate_member(data, member_expectation(row))
        payload = pressure_values_bytes(raw)
        st = sample_stats(payload)
        if st["nonfinite"]:
            raise SystemExit(f"{stem}: non-finite values")
        if st["dominant_fraction"] > MAX_DOMINANT_FRACTION:
            raise SystemExit(f"{stem}: dominant fraction {st['dominant_fraction']} exceeds rule")
        if st["ambient_fraction"] > MAX_AMBIENT_FRACTION:
            raise SystemExit(f"{stem}: ambient fraction {st['ambient_fraction']} exceeds rule")
        if row["dominant_fraction"] and f"{st['dominant_fraction']:.6f}" != row["dominant_fraction"]:
            raise SystemExit(f"{stem}: dominant fraction differs from pinned table")
        if row["ambient_fraction"] and f"{st['ambient_fraction']:.6f}" != row["ambient_fraction"]:
            raise SystemExit(f"{stem}: ambient fraction differs from pinned table")
        out = samples_dir / f"{stem}_pressure.f64"
        out.write_bytes(payload)
        index_rows.append(
            {
                "dataset_id": DATASET_ID,
                "series_id": SERIES_ID,
                "sample_path": rel_to(out, data_root),
                "numeric_kind": "float",
                "bit_width": 64,
                "endianness": "little",
                "element_size_bytes": 8,
                "sample_size_bytes": len(payload),
                "value_count": VALUES,
                "shape": [GRID, GRID],
                "axes": ["slice_row", "slice_col"],
                "source_key": row["key"],
                "source_member": MEMBER,
                "snapshot": int(row["snapshot"]),
                "time_s": float(row["time_s"]),
                "sha256": hashlib.sha256(payload).hexdigest(),
                "min": st["min"],
                "max": st["max"],
                "distinct_values": st["distinct"],
                "dominant_value": st["dominant_value"],
                "dominant_fraction": st["dominant_fraction"],
                "ambient_fraction": st["ambient_fraction"],
                "uniform_2x2_block_fraction": st["uniform_2x2_block_fraction"],
            }
        )
        per_sample.append(st)
        print(f"built {stem} distinct={st['distinct']} dom={st['dominant_fraction']} min={st['min']:.1f} max={st['max']:.1f}")
    with index_path.open("w", encoding="utf-8") as fh:
        for r in index_rows:
            fh.write(json.dumps(r, sort_keys=True) + "\n")
    summary = {
        "dataset_id": DATASET_ID,
        "series_id": SERIES_ID,
        "pinned_archives": len(read_table(Path(args.table))),
        "selected_samples": len(index_rows),
        "total_size_bytes": sum(r["sample_size_bytes"] for r in index_rows),
        "total_values": sum(r["value_count"] for r in index_rows),
        "max_dominant_fraction_rule": MAX_DOMINANT_FRACTION,
        "max_ambient_fraction_rule": MAX_AMBIENT_FRACTION,
        "ambient_fraction_max": max(s["ambient_fraction"] for s in per_sample),
        "dominant_fraction_max": max(s["dominant_fraction"] for s in per_sample),
        "uniform_2x2_block_fraction_mean": round(
            sum(s["uniform_2x2_block_fraction"] for s in per_sample) / len(per_sample), 6
        ),
        "pressure_min": min(s["min"] for s in per_sample),
        "pressure_max": max(s["max"] for s in per_sample),
    }
    stats_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2, sort_keys=True))


def cmd_verify(args: argparse.Namespace) -> None:
    data_root = Path(args.data_root)
    downloads = Path(args.downloads)
    samples_dir = Path(args.samples_dir) / SERIES_ID
    rows = selected_rows(Path(args.table))
    index = [json.loads(line) for line in Path(args.index).read_text(encoding="utf-8").splitlines() if line.strip()]
    if len(index) != len(rows):
        raise SystemExit(f"index rows {len(index)} != selected snapshots {len(rows)}")
    on_disk = sorted(p.name for p in samples_dir.glob("*"))
    expected_names = sorted(f"{r['key'][:-4]}_pressure.f64" for r in rows)
    if on_disk != expected_names:
        raise SystemExit("sample directory contents differ from the selected snapshot list")
    seen_hashes = set()
    total = 0
    for row, entry in zip(rows, index):
        stem = row["key"][:-4]
        # independent re-derivation from the downloaded compressed member
        data = (downloads / f"{stem}.pressure.zipmember").read_bytes()
        lh = parse_local_header(data)
        d = zlib.decompressobj(-15)
        raw = d.decompress(data[lh["header_bytes"] :]) + d.flush()
        if zlib.crc32(raw) & 0xFFFFFFFF != int(row["pressure_crc32"], 16):
            raise SystemExit(f"{stem}: CRC32 mismatch on re-inflate")
        header, data_off = parse_npy(raw)
        if header["descr"] != "<f8" or header["fortran_order"] or header["shape"] != (1, GRID, GRID):
            raise SystemExit(f"{stem}: unexpected NPY header")
        expected = raw[data_off:]
        sample_path = data_root / entry["sample_path"]
        actual = sample_path.read_bytes()
        if actual != expected:
            raise SystemExit(f"{stem}: sample bytes differ from re-derived NPY payload")
        if entry["source_key"] != row["key"] or entry["series_id"] != SERIES_ID or entry["dataset_id"] != DATASET_ID:
            raise SystemExit(f"{stem}: index identity mismatch")
        if (entry["numeric_kind"], entry["bit_width"], entry["endianness"], entry["element_size_bytes"]) != (
            "float",
            64,
            "little",
            8,
        ):
            raise SystemExit(f"{stem}: index dtype mismatch")
        if entry["sample_size_bytes"] != len(actual) or entry["value_count"] != VALUES or len(actual) != VALUES * 8:
            raise SystemExit(f"{stem}: index size mismatch")
        digest = hashlib.sha256(actual).hexdigest()
        if digest != entry["sha256"]:
            raise SystemExit(f"{stem}: sha256 mismatch")
        if digest in seen_hashes:
            raise SystemExit(f"{stem}: duplicate sample payload")
        seen_hashes.add(digest)
        # same missing-value / degeneracy policy as build
        values = struct.unpack(f"<{VALUES}d", actual)
        if any(not math.isfinite(v) for v in values):
            raise SystemExit(f"{stem}: non-finite values")
        if min(values) <= 0:
            raise SystemExit(f"{stem}: non-positive pressure")
        counts = Counter(values)
        top = counts.most_common(1)[0][1] / VALUES
        if top > MAX_DOMINANT_FRACTION:
            raise SystemExit(f"{stem}: dominant-value fraction {top:.4f} > {MAX_DOMINANT_FRACTION}")
        if len(counts) < 1000:
            raise SystemExit(f"{stem}: only {len(counts)} distinct values (degenerate)")
        ambient = sum(1 for v in values if abs(v - AMBIENT_PA) <= AMBIENT_TOL_PA) / VALUES
        if ambient > MAX_AMBIENT_FRACTION:
            raise SystemExit(f"{stem}: ambient fraction {ambient:.4f} > {MAX_AMBIENT_FRACTION}")
        if abs(ambient - entry["ambient_fraction"]) > 1e-6:
            raise SystemExit(f"{stem}: ambient fraction disagrees with index")
        if abs(top - entry["dominant_fraction"]) > 1e-6:
            raise SystemExit(f"{stem}: dominant fraction disagrees with index")
        if min(values) != entry["min"] or max(values) != entry["max"]:
            raise SystemExit(f"{stem}: min/max disagree with index")
        total += len(actual)
    manifest_path = Path(__file__).resolve().parent.parent / "manifest.toml"
    import tomllib

    manifest = tomllib.loads(manifest_path.read_text(encoding="utf-8"))
    series = [s for s in manifest["series"] if s["id"] == SERIES_ID]
    if len(series) != 1:
        raise SystemExit("manifest must declare exactly one primary pressure series")
    if series[0]["sample_count"] != len(index) or series[0]["total_size_bytes"] != total:
        raise SystemExit(
            f"manifest scope mismatch: manifest={series[0]['sample_count']}/{series[0]['total_size_bytes']} "
            f"realized={len(index)}/{total}"
        )
    print(f"verify ok samples={len(index)} total_bytes={total}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("discover-parse")
    p.add_argument("--files-json", required=True)
    p.add_argument("--ranges-dir", required=True)
    p.add_argument("--out", required=True)
    p.set_defaults(func=cmd_discover_parse)
    p = sub.add_parser("check-tail")
    for a in ("--table", "--key", "--tail", "--headers"):
        p.add_argument(a, required=True)
    p.set_defaults(func=cmd_check_tail)
    p = sub.add_parser("check-member")
    for a in ("--table", "--key", "--member", "--headers"):
        p.add_argument(a, required=True)
    p.set_defaults(func=cmd_check_member)
    for name, func in (("build", cmd_build), ("verify", cmd_verify)):
        p = sub.add_parser(name)
        for a in ("--table", "--downloads", "--samples-dir", "--index", "--stats", "--data-root"):
            p.add_argument(a, required=True)
        p.set_defaults(func=func)
    args = ap.parse_args()
    try:
        args.func(args)
    except (ValueError, KeyError, zlib.error, struct.error, SyntaxError) as exc:
        raise SystemExit(f"FATAL: {type(exc).__name__}: {exc}")


if __name__ == "__main__":
    main()
