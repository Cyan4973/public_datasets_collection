#!/usr/bin/env python3
"""Pure-stdlib helpers for the RQCD qcdML ens_001 gauge-link recipe.

Subcommands:
  check-record  validate the Zenodo record JSON (identity, license, archive size/md5)
  check-tail    parse the Zip64 EOCD locator, Zip64 EOCD and central directory of the
                outer ens_001_pt.zip tail and compare them with the pinned member table
  trim-member   validate one range-fetched outer member (local header, DEFLATE, CRC32,
                inner .pt structure) and write the exact local-header+data bytes
  build         inflate every pinned member, validate the inner torch .pt (stored zip,
                pickle opcodes via pickletools.genops only) and emit data/0 as LE f64

The torch pickle is never unpickled: only pickletools.genops is used to read opcodes.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import html
import json
import math
import pickletools
import re
import struct
import sys
import zlib
from pathlib import Path

DATASET_ID = "rqcd_qcdml_quenched_su3_gauge_links_f64"
SERIES_ID = "qcdml_ens001_su3_gauge_links_f64"
RECORD_ID = 15018324
ARCHIVE_NAME = "ens_001_pt.zip"
ARCHIVE_BYTES = 22571455882
ARCHIVE_MD5 = "58d0a6911c07480ff914417d4498d8bc"
ZIP_ENTRIES = 5002
CD_OFFSET = 22570933132
CD_SIZE = 522652
SHAPE = (4, 8, 8, 8, 16, 3, 3)
STRIDE = (73728, 9216, 1152, 144, 9, 3, 1)
NUMEL = 294912  # complex elements
DATA_BYTES = NUMEL * 16  # 4,718,592
VALUE_COUNT = NUMEL * 2  # float64 values (re, im interleaved)
DATA_PKL_SHA256 = "ed1bd2bd50b7bf96cd6024e7cd3addba6e31564edd4089ae4386260af1c96d2c"

LOCAL_FMT = "<4s5H3I2H"  # sig, ver, flags, method, time, date, crc, csize, usize, nlen, xlen
CENTRAL_FMT = "<4s6H3I5H2I"


def read_members(path: Path) -> list[dict]:
    with path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    out = []
    for row in rows:
        out.append(
            {
                "config": int(row["config"]),
                "member": row["member"],
                "offset": int(row["local_header_offset"]),
                "csize": int(row["compressed_size"]),
                "usize": int(row["uncompressed_size"]),
                "crc32": int(row["crc32"], 16),
            }
        )
    configs = [m["config"] for m in out]
    if len(out) != 100 or configs != sorted(set(configs)):
        raise SystemExit("pinned member table must hold 100 distinct sorted configs")
    for m in out:
        if m["member"] != f"ens_001_pt/config_{m['config']}.pt":
            raise SystemExit(f"member name/config mismatch: {m}")
    return out


def check_content_range(headers_path: Path, start: int, end: int) -> None:
    headers = headers_path.read_text(encoding="iso-8859-1")
    responses = [p for p in re.split(r"(?=^HTTP/)", headers, flags=re.MULTILINE) if p.strip()]
    final = responses[-1] if responses else ""
    status = re.search(r"^HTTP/\S+\s+(\d+)", final, flags=re.MULTILINE)
    rng = re.search(r"^Content-Range:\s*bytes\s+(\d+)-(\d+)/(\d+)\s*$", final, flags=re.I | re.M)
    if not status or int(status.group(1)) != 206 or not rng:
        raise SystemExit(f"server did not honor byte range ({headers_path.name})")
    got = tuple(map(int, rng.groups()))
    if got != (start, end, ARCHIVE_BYTES):
        raise SystemExit(f"unexpected Content-Range {got}, expected {(start, end, ARCHIVE_BYTES)}")


# ---------------------------------------------------------------- record

def cmd_check_record(args: argparse.Namespace) -> None:
    record = json.loads(Path(args.record).read_text(encoding="utf-8"))
    if int(record.get("id") or 0) != RECORD_ID:
        raise SystemExit(f"unexpected record id {record.get('id')!r}")
    meta = record.get("metadata") or {}
    title = str(meta.get("title", ""))
    if title != "ldg/rqcd/qcdML/ens_001":
        raise SystemExit(f"record title changed: {title!r}")
    desc = html.unescape(re.sub(r"<[^>]+>", " ", str(meta.get("description", ""))))
    for needle in ("plaquetteGluonAction", "beta: 6.0", "SU(2) heat bath", "t: 16"):
        if needle not in desc:
            raise SystemExit(f"record description lacks {needle!r}")
    lic = meta.get("license")
    lic_id = str(lic.get("id") if isinstance(lic, dict) else lic or "").lower()
    if lic_id != "cc-by-4.0":
        raise SystemExit(f"record license changed: {lic_id!r}")
    files = [f for f in record.get("files") or [] if f.get("key") == ARCHIVE_NAME]
    if len(files) != 1:
        raise SystemExit(f"expected one {ARCHIVE_NAME} in record")
    item = files[0]
    if int(item.get("size") or 0) != ARCHIVE_BYTES or item.get("checksum") != f"md5:{ARCHIVE_MD5}":
        raise SystemExit(f"archive size/checksum changed: {item.get('size')} {item.get('checksum')}")
    print(f"record_ok id={RECORD_ID} license=cc-by-4.0 archive_bytes={ARCHIVE_BYTES} md5={ARCHIVE_MD5}")


# ---------------------------------------------------------------- outer zip tail

def parse_central_directory(tail: bytes, tail_start: int) -> dict[str, dict]:
    eocd = tail.rfind(b"PK\x05\x06")
    if eocd < 0 or eocd + 22 != len(tail):
        raise SystemExit("EOCD not found at the archive end")
    _, disk, cd_disk, n_disk, n_total, cd_size32, cd_off32, comment_len = struct.unpack_from(
        "<4s4H2IH", tail, eocd
    )
    if disk or cd_disk or comment_len or cd_off32 != 0xFFFFFFFF:
        raise SystemExit("unexpected classic EOCD (expected Zip64 offset sentinel)")
    loc = eocd - 20
    sig, loc_disk, z64_off, n_disks = struct.unpack_from("<4sIQI", tail, loc)
    if sig != b"PK\x06\x07" or loc_disk or n_disks != 1:
        raise SystemExit("Zip64 EOCD locator missing or malformed")
    rel = z64_off - tail_start
    if rel < 0 or rel + 56 > len(tail):
        raise SystemExit("Zip64 EOCD outside fetched tail")
    f = struct.unpack_from("<4sQ2H2I4Q", tail, rel)
    if f[0] != b"PK\x06\x06":
        raise SystemExit("Zip64 EOCD signature mismatch")
    n_entries, cd_size, cd_off = f[7], f[8], f[9]
    if (n_entries, cd_size, cd_off) != (ZIP_ENTRIES, CD_SIZE, CD_OFFSET):
        raise SystemExit(f"central directory geometry changed: {(n_entries, cd_size, cd_off)}")
    if cd_off + cd_size != z64_off:
        raise SystemExit("central directory not contiguous with Zip64 EOCD")
    cur = cd_off - tail_start
    end = cur + cd_size
    if cur < 0:
        raise SystemExit("central directory not fully inside fetched tail")
    members: dict[str, dict] = {}
    while cur < end:
        c = struct.unpack_from(CENTRAL_FMT, tail, cur)
        if c[0] != b"PK\x01\x02":
            raise SystemExit(f"bad central header at tail offset {cur}")
        flags, method, crc, csize, usize = c[3], c[4], c[7], c[8], c[9]
        nlen, xlen, clen, disk_start, offset = c[10], c[11], c[12], c[13], c[16]
        name = tail[cur + 46 : cur + 46 + nlen].decode("utf-8" if flags & 0x800 else "cp437")
        extra = tail[cur + 46 + nlen : cur + 46 + nlen + xlen]
        p = 0
        while p + 4 <= len(extra):
            hid, hsz = struct.unpack_from("<2H", extra, p)
            body = extra[p + 4 : p + 4 + hsz]
            if hid == 0x0001:
                q = 0
                if usize == 0xFFFFFFFF:
                    usize = struct.unpack_from("<Q", body, q)[0]
                    q += 8
                if csize == 0xFFFFFFFF:
                    csize = struct.unpack_from("<Q", body, q)[0]
                    q += 8
                if offset == 0xFFFFFFFF:
                    offset = struct.unpack_from("<Q", body, q)[0]
                    q += 8
            p += 4 + hsz
        if disk_start not in (0, 0xFFFF):
            raise SystemExit(f"multi-disk member {name}")
        members[name] = {
            "flags": flags,
            "method": method,
            "crc32": crc,
            "csize": csize,
            "usize": usize,
            "offset": offset,
        }
        cur += 46 + nlen + xlen + clen
    if cur != end or len(members) != ZIP_ENTRIES:
        raise SystemExit(f"central directory parse mismatch: {len(members)} entries")
    return members


def cmd_check_tail(args: argparse.Namespace) -> None:
    tail = Path(args.tail).read_bytes()
    tail_start = ARCHIVE_BYTES - len(tail)
    check_content_range(Path(args.headers), tail_start, ARCHIVE_BYTES - 1)
    central = parse_central_directory(tail, tail_start)
    configs = sorted(
        int(m.group(1))
        for n in central
        if (m := re.fullmatch(r"ens_001_pt/config_(\d+)\.pt", n))
    )
    if configs != list(range(5000)):
        raise SystemExit("archive no longer holds exactly config_0..config_4999")
    for m in read_members(Path(args.members)):
        c = central.get(m["member"])
        if c is None:
            raise SystemExit(f"pinned member missing: {m['member']}")
        got = (c["method"], c["flags"], c["offset"], c["csize"], c["usize"], c["crc32"])
        want = (8, 0, m["offset"], m["csize"], m["usize"], m["crc32"])
        if got != want:
            raise SystemExit(f"pinned member changed: {m['member']} got={got} want={want}")
    print(f"tail_ok entries={len(central)} configs=0..4999 pinned=100 matched")


# ---------------------------------------------------------------- members

def inflate_member(blob: bytes, m: dict) -> tuple[bytes, int]:
    """Validate the outer local header and return (inner .pt bytes, exact member length)."""
    f = struct.unpack_from(LOCAL_FMT, blob, 0)
    if f[0] != b"PK\x03\x04":
        raise SystemExit(f"{m['member']}: missing local header signature")
    flags, method, crc, csize, usize, nlen, xlen = f[2], f[3], f[6], f[7], f[8], f[9], f[10]
    name = blob[30 : 30 + nlen].decode("utf-8" if flags & 0x800 else "cp437")
    if name != m["member"] or method != 8 or flags & 0x08:
        raise SystemExit(f"{m['member']}: local header mismatch name={name!r} method={method} flags={flags}")
    if crc != m["crc32"] or csize not in (m["csize"], 0xFFFFFFFF) or usize not in (m["usize"], 0xFFFFFFFF):
        raise SystemExit(f"{m['member']}: local header crc/size mismatch")
    start = 30 + nlen + xlen
    stop = start + m["csize"]
    if stop > len(blob):
        raise SystemExit(f"{m['member']}: truncated member payload")
    d = zlib.decompressobj(-zlib.MAX_WBITS)
    inner = d.decompress(blob[start:stop]) + d.flush()
    if not d.eof or d.unused_data:
        raise SystemExit(f"{m['member']}: DEFLATE stream does not end at csize")
    if len(inner) != m["usize"] or zlib.crc32(inner) & 0xFFFFFFFF != m["crc32"]:
        raise SystemExit(f"{m['member']}: inflated size/CRC32 mismatch")
    return inner, stop


def parse_inner_pt(inner: bytes, config: int) -> bytes:
    """Validate the stored torch zip via its central directory; return data/0 bytes."""
    eocd = inner.rfind(b"PK\x05\x06")
    if eocd < 0:
        raise SystemExit(f"config {config}: inner .pt has no EOCD")
    _, _, _, _, n_total, cd_size, cd_off, _ = struct.unpack_from("<4s4H2IH", inner, eocd)
    entries: dict[str, tuple[int, int, int, int]] = {}
    cur = cd_off
    for _ in range(n_total):
        c = struct.unpack_from(CENTRAL_FMT, inner, cur)
        if c[0] != b"PK\x01\x02":
            raise SystemExit(f"config {config}: bad inner central header")
        method, crc, csize, usize, nlen, xlen, clen, off = c[4], c[7], c[8], c[9], c[10], c[11], c[12], c[16]
        name = inner[cur + 46 : cur + 46 + nlen].decode("utf-8")
        if method != 0 or csize != usize:
            raise SystemExit(f"config {config}: inner member {name} is not stored")
        entries[name] = (off, usize, crc, method)
        cur += 46 + nlen + xlen + clen
    prefix = f"config_{config}/"
    expected = {prefix + s for s in ("data.pkl", "byteorder", "data/0", "version", ".data/serialization_id")}
    if set(entries) != expected:
        raise SystemExit(f"config {config}: unexpected inner members {sorted(entries)}")

    def payload(name: str) -> bytes:
        off, size, crc, _ = entries[name]
        lf = struct.unpack_from(LOCAL_FMT, inner, off)
        if lf[0] != b"PK\x03\x04":
            raise SystemExit(f"config {config}: bad inner local header for {name}")
        start = off + 30 + lf[9] + lf[10]
        data = inner[start : start + size]
        if len(data) != size or zlib.crc32(data) & 0xFFFFFFFF != crc:
            raise SystemExit(f"config {config}: inner CRC mismatch for {name}")
        return data

    if payload(prefix + "byteorder") != b"little":
        raise SystemExit(f"config {config}: byteorder is not little")
    if payload(prefix + "version") != b"3\n":
        raise SystemExit(f"config {config}: unexpected torch archive version")
    pkl = payload(prefix + "data.pkl")
    validate_pickle(pkl, config)
    data = payload(prefix + "data/0")
    if len(data) != DATA_BYTES:
        raise SystemExit(f"config {config}: data/0 is {len(data)} bytes, expected {DATA_BYTES}")
    return data


def validate_pickle(pkl: bytes, config: int) -> None:
    ops = [(op.name, arg) for op, arg, _ in pickletools.genops(pkl)]
    globals_ = [arg for name, arg in ops if name == "GLOBAL"]
    if globals_ != ["torch._utils _rebuild_tensor_v2", "torch ComplexDoubleStorage", "collections OrderedDict"]:
        raise SystemExit(f"config {config}: unexpected pickle globals {globals_}")
    strings = [arg for name, arg in ops if name == "BINUNICODE"]
    if strings != ["storage", "0", "cpu"]:
        raise SystemExit(f"config {config}: unexpected pickle strings {strings}")
    ints = [arg for name, arg in ops if name in ("BININT", "BININT1", "BININT2")]
    # numel, storage_offset, shape..., stride...
    if ints != [NUMEL, 0, *SHAPE, *STRIDE]:
        raise SystemExit(f"config {config}: unexpected tensor geometry {ints}")
    if not any(name == "NEWFALSE" for name, _ in ops):
        raise SystemExit(f"config {config}: requires_grad flag missing")
    if hashlib.sha256(pkl).hexdigest() != DATA_PKL_SHA256:
        raise SystemExit(f"config {config}: data.pkl differs from the pinned tensor header")


def cmd_trim_member(args: argparse.Namespace) -> None:
    members = {m["config"]: m for m in read_members(Path(args.members))}
    m = members[int(args.config)]
    blob = Path(args.part).read_bytes()
    first = m["offset"]
    check_content_range(Path(args.headers), first, first + len(blob) - 1)
    inner, stop = inflate_member(blob, m)
    parse_inner_pt(inner, m["config"])
    Path(args.output).write_bytes(blob[:stop])
    print(f"member_ok config={m['config']} member_bytes={stop} crc32={m['crc32']:08x}")


def cmd_check_member(args: argparse.Namespace) -> None:
    members = {m["config"]: m for m in read_members(Path(args.members))}
    m = members[int(args.config)]
    blob = Path(args.path).read_bytes()
    inner, stop = inflate_member(blob, m)
    if stop != len(blob):
        raise SystemExit(f"config {m['config']}: cached member has trailing bytes")
    parse_inner_pt(inner, m["config"])


# ---------------------------------------------------------------- build

def link_stats(data: bytes) -> tuple[float, float, float, float]:
    """Return (min, max, max |entry|, max unitarity residual |U U^dagger - 1|)."""
    v = struct.unpack(f"<{VALUE_COUNT}d", data)
    lo, hi = min(v), max(v)
    max_abs = 0.0
    max_res = 0.0
    for base in range(0, VALUE_COUNT, 18):
        r = v[base : base + 18 : 2]
        i = v[base + 1 : base + 18 : 2]
        for k in range(9):
            a = math.hypot(r[k], i[k])
            if a > max_abs:
                max_abs = a
        for p in range(3):
            for q in range(p, 3):
                sr = 0.0
                si = 0.0
                for k in range(3):
                    ar, ai = r[3 * p + k], i[3 * p + k]
                    br, bi = r[3 * q + k], -i[3 * q + k]
                    sr += ar * br - ai * bi
                    si += ar * bi + ai * br
                if p == q:
                    sr -= 1.0
                res = abs(sr) + abs(si)
                if res > max_res:
                    max_res = res
    return lo, hi, max_abs, max_res


def cmd_build(args: argparse.Namespace) -> None:
    data_root = Path(args.data_root)
    members = read_members(Path(args.members))
    downloads = Path(args.downloads)
    out_dir = Path(args.samples_dir) / SERIES_ID
    out_dir.mkdir(parents=True, exist_ok=True)
    for stale in out_dir.glob("*.bin"):
        stale.unlink()
    index_path = Path(args.index)
    index_path.parent.mkdir(parents=True, exist_ok=True)
    stats_path = Path(args.stats)
    stats_path.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    per = []
    for m in members:
        blob = (downloads / "members" / f"config_{m['config']}.zipmember").read_bytes()
        inner, stop = inflate_member(blob, m)
        if stop != len(blob):
            raise SystemExit(f"config {m['config']}: member file has trailing bytes")
        data = parse_inner_pt(inner, m["config"])
        lo, hi, max_abs, max_res = link_stats(data)
        if not (math.isfinite(lo) and math.isfinite(hi)) or lo == hi:
            raise SystemExit(f"config {m['config']}: non-finite or constant links")
        if max_abs > 1.0 + 1e-9 or max_res > 1e-10:
            raise SystemExit(f"config {m['config']}: links not SU(3)-unitary (|U|max={max_abs}, res={max_res})")
        out = out_dir / f"config_{m['config']:04d}.bin"
        out.write_bytes(data)  # complex128 little-endian == interleaved (re, im) LE float64
        sha = hashlib.sha256(data).hexdigest()
        rows.append(
            {
                "dataset_id": DATASET_ID,
                "series_id": SERIES_ID,
                "sample_path": str(out.relative_to(data_root)),
                "numeric_kind": "float",
                "bit_width": 64,
                "endianness": "little",
                "element_size_bytes": 8,
                "sample_size_bytes": DATA_BYTES,
                "value_count": VALUE_COUNT,
                "config": m["config"],
                "source_member": m["member"],
                "shape": list(SHAPE) + [2],
                "axes": ["mu", "x", "y", "z", "t", "row", "col", "re_im"],
                "min": lo,
                "max": hi,
                "max_abs_entry": max_abs,
                "max_unitarity_residual": max_res,
                "sha256": sha,
            }
        )
        per.append({"config": m["config"], "max_unitarity_residual": max_res, "max_abs_entry": max_abs})
        print(f"config={m['config']} min={lo:.6f} max={hi:.6f} |U|max={max_abs:.15f} unit_res={max_res:.2e}", flush=True)
    with index_path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")
    stats = {
        "dataset_id": DATASET_ID,
        "series_id": SERIES_ID,
        "sample_count": len(rows),
        "total_size_bytes": DATA_BYTES * len(rows),
        "total_values": VALUE_COUNT * len(rows),
        "configs": [m["config"] for m in members],
        "worst_unitarity_residual": max(p["max_unitarity_residual"] for p in per),
        "worst_abs_entry": max(p["max_abs_entry"] for p in per),
    }
    stats_path.write_text(json.dumps(stats, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in stats.items() if k != "configs"}))


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("check-record")
    p.add_argument("record")
    p = sub.add_parser("check-tail")
    p.add_argument("--tail", required=True)
    p.add_argument("--headers", required=True)
    p.add_argument("--members", required=True)
    p = sub.add_parser("trim-member")
    p.add_argument("--members", required=True)
    p.add_argument("--config", required=True)
    p.add_argument("--part", required=True)
    p.add_argument("--headers", required=True)
    p.add_argument("--output", required=True)
    p = sub.add_parser("check-member")
    p.add_argument("--members", required=True)
    p.add_argument("--config", required=True)
    p.add_argument("--path", required=True)
    p = sub.add_parser("build")
    for flag in ("--members", "--downloads", "--samples-dir", "--index", "--stats", "--data-root"):
        p.add_argument(flag, required=True)
    args = ap.parse_args()
    {
        "check-record": cmd_check_record,
        "check-tail": cmd_check_tail,
        "trim-member": cmd_trim_member,
        "check-member": cmd_check_member,
        "build": cmd_build,
    }[args.cmd](args)


if __name__ == "__main__":
    main()
