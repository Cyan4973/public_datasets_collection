#!/usr/bin/env python3
"""Decode OOI CE04OSPS-SF01B OPTAAD105 (WET Labs AC-S) raw port-agent day files.

Pure standard library. Subcommands:
  check-file  validate one downloaded day file (port-agent framing, XOR
              checksums, timestamps inside the file's UTC day, AC-S packet
              yield and header identity)
  build       decode every pinned day file and emit the uint16 spectral-count
              block of every accepted AC-S packet plus the sample index
  selftest    run the decoder on synthetic port-agent framed AC-S packets

Layers:
  1. OOI port-agent frames: sync a3 9d 7a, type (1 byte), length (2 bytes BE,
     includes the 16-byte header), checksum (2 bytes BE; XOR of every frame
     byte with the checksum field excluded), NTP timestamp (8 bytes BE).
     Only type-1 (data from instrument) payloads are kept and concatenated in
     file order; AC-S packets straddle frame boundaries.
  2. AC-S binary packets in the reassembled serial stream (layout as in the
     OOI mi-instrument driver mi/instrument/wetlabs/ac_s/ooicore/driver.py):
       0  registration ff 00 ff 00
       4  record length u16 BE (bytes before the checksum; 32 + 8N = 704)
       6  packet type (5)        7 reserved (1)        8 meter type (0x53)
       9  serial number high byte, 10 serial low u16 BE (serial 128)
       12 a-ref dark, pressure, a-sig dark, ext temp, int temp, c-ref dark,
          c-sig dark (7 x u16 BE)
       26 elapsed time u32 BE ms   30 reserved   31 number of wavelengths N
       32 N x (c-ref, a-ref, c-sig, a-sig) u16 BE spectral counts
       L  checksum u16 BE = sum(bytes[0:L]) & 0xffff ; L+2 pad byte 0x00
     A candidate is accepted only if: L == 704, checksum valid, pad byte 0,
     no registration pattern inside bytes [4, L) (a packet whose tail was lost
     upstream is followed ~480-495 bytes later by the next registration; this
     rule keeps such splices out even when the 16-bit checksum collides), and
     the header constants equal the deployment identity. After an accepted
     packet the scan resumes at q + L + 3.
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import os
import struct
import sys
from array import array
from datetime import datetime, timedelta, timezone
from pathlib import Path

DATASET_ID = "ooi_ce04osps_optaa_acs_spectral_counts_u16"
SERIES = "acs_spectral_counts_u16"
PA_SYNC = b"\xa3\x9d\x7a"
PA_HEADER = 16
PA_TYPE_DATA = 1
NTP_EPOCH_OFFSET = 2208988800
REG = b"\xff\x00\xff\x00"
N_WAVE = 84
REC_LEN = 32 + 8 * N_WAVE  # 704
PKT_TOTAL = REC_LEN + 3  # checksum + pad
# Deployment identity (AC-S serial 128, 84 wavelengths), probed 2026-10-14 on
# 2019-01-02, 01-31, 03-15, 05-24 and 06-01; the unit installed after the
# 2019-06-14..25 gap reports serial 221 with 88 wavelengths.
IDENTITY = {"packet_type": 5, "reserved": 1, "meter_type": 0x53, "serial": 128, "num_wavelengths": N_WAVE}
# Files open 07:20-07:21 UTC and close 21:43-21:44 UTC on their own date.
FIRST_TS_WINDOW = (7 * 3600 + 10 * 60, 7 * 3600 + 45 * 60)
LAST_TS_WINDOW = (21 * 3600 + 30 * 60, 22 * 3600)
MIN_PACKETS = 15_000
MIN_ACCEPT_FRACTION = 0.50  # parser-sanity floor: accepted / (accepted + rejected L == 704 candidates); probes show 0.79-1.00
MIN_DISTINCT = 64
MAX_MODE_SHARE = 0.5
CHANNELS = ("c_ref", "a_ref", "c_sig", "a_sig")


class DecodeError(Exception):
    pass


def data_root(repo_root: Path, data_dir: str) -> Path:
    p = Path(data_dir)
    return p if p.is_absolute() else repo_root / p


def deframe(raw: bytes) -> tuple[bytes, dict]:
    """Walk port-agent frames from offset 0 to EOF; return the type-1 payload stream."""
    pos = 0
    n = len(raw)
    parts = []
    types = collections.Counter()
    first_ts = last_ts = None
    while pos < n:
        if pos + PA_HEADER > n:
            raise DecodeError(f"truncated port-agent header at {pos}")
        if raw[pos:pos + 3] != PA_SYNC:
            raise DecodeError(f"port-agent sync lost at {pos}")
        ftype = raw[pos + 3]
        (length,) = struct.unpack_from(">H", raw, pos + 4)
        (stored,) = struct.unpack_from(">H", raw, pos + 6)
        if length < PA_HEADER or pos + length > n:
            raise DecodeError(f"bad port-agent length {length} at {pos}")
        x = 0
        for b in raw[pos:pos + 6]:
            x ^= b
        for b in raw[pos + 8:pos + length]:
            x ^= b
        if x != stored:
            raise DecodeError(f"port-agent checksum mismatch at {pos}")
        types[ftype] += 1
        if ftype == PA_TYPE_DATA:
            (ts,) = struct.unpack_from(">Q", raw, pos + 8)
            if first_ts is None:
                first_ts = ts
            last_ts = ts
            parts.append(raw[pos + PA_HEADER:pos + length])
        pos += length
    info = {
        "frame_types": {str(k): v for k, v in sorted(types.items())},
        "first_ntp_utc": None if first_ts is None else first_ts / 2**32 - NTP_EPOCH_OFFSET,
        "last_ntp_utc": None if last_ts is None else last_ts / 2**32 - NTP_EPOCH_OFFSET,
    }
    return b"".join(parts), info


def header_identity(s: bytes, q: int) -> dict:
    return {
        "packet_type": s[q + 6],
        "reserved": s[q + 7],
        "meter_type": s[q + 8],
        "serial": (s[q + 9] << 16) | struct.unpack_from(">H", s, q + 10)[0],
        "num_wavelengths": s[q + 31],
    }


def scan_stream(s: bytes) -> dict:
    """Return accepted packet offsets and candidate statistics."""
    n = len(s)
    offsets = []
    reject = collections.Counter()
    identities = collections.Counter()
    p = 0
    while True:
        q = s.find(REG, p)
        if q < 0:
            break
        if q + 6 > n:
            reject["tail"] += 1
            break
        (length,) = struct.unpack_from(">H", s, q + 4)
        if length != REC_LEN:
            reject["length"] += 1
            p = q + 1
            continue
        if q + PKT_TOTAL > n:
            reject["tail"] += 1
            p = q + 1
            continue
        if (sum(s[q:q + REC_LEN]) & 0xFFFF) != struct.unpack_from(">H", s, q + REC_LEN)[0]:
            reject["checksum"] += 1
            p = q + 1
            continue
        if s[q + REC_LEN + 2] != 0:
            reject["pad"] += 1
            p = q + 1
            continue
        if s.find(REG, q + 4, q + REC_LEN) >= 0:
            reject["internal_registration"] += 1
            p = q + 1
            continue
        ident = header_identity(s, q)
        identities[tuple(sorted(ident.items()))] += 1
        offsets.append(q)
        p = q + PKT_TOTAL
    return {"offsets": offsets, "reject": reject, "identities": identities, "stream_bytes": n}


def spectral_block_le(s: bytes, offsets: list[int]) -> bytes:
    """Concatenate the N x 4 u16 spectral blocks and convert BE -> LE."""
    be = b"".join(s[q + 32:q + REC_LEN] for q in offsets)
    a = array("H")
    a.frombytes(be)
    if sys.byteorder == "little":
        a.byteswap()
    out = a.tobytes()
    if sys.byteorder == "big":
        out_a = array("H", out)
        out_a.byteswap()
        out = out_a.tobytes()
    return out


def day_bounds(day: str) -> float:
    return datetime.strptime(day, "%Y%m%d").replace(tzinfo=timezone.utc).timestamp()


def check_frames(finfo: dict, day: str) -> None:
    d0 = day_bounds(day)
    if finfo["first_ntp_utc"] is None:
        raise DecodeError("no data frames")
    f = finfo["first_ntp_utc"] - d0
    l = finfo["last_ntp_utc"] - d0
    if not (FIRST_TS_WINDOW[0] <= f <= FIRST_TS_WINDOW[1]):
        raise DecodeError(f"first timestamp {f:.0f} s after midnight outside {FIRST_TS_WINDOW}")
    if not (LAST_TS_WINDOW[0] <= l <= LAST_TS_WINDOW[1]):
        raise DecodeError(f"last timestamp {l:.0f} s after midnight outside {LAST_TS_WINDOW}")


def check_scan(r: dict) -> dict:
    npk = len(r["offsets"])
    if npk < MIN_PACKETS:
        raise DecodeError(f"only {npk} accepted AC-S packets (< {MIN_PACKETS})")
    want = tuple(sorted(IDENTITY.items()))
    if set(r["identities"]) != {want}:
        raise DecodeError(f"header identity differs from deployment: {dict(r['identities'])}")
    cands = npk + sum(v for k, v in r["reject"].items() if k not in ("length",))
    frac = npk / cands
    if frac < MIN_ACCEPT_FRACTION:
        raise DecodeError(f"accepted fraction {frac:.3f} < {MIN_ACCEPT_FRACTION}")
    return {"accepted_packets": npk, "accept_fraction": round(frac, 6)}


def channel_stats(sample_le: bytes) -> dict:
    a = array("H")
    a.frombytes(sample_le)
    if sys.byteorder == "big":
        a.byteswap()
    out = {}
    for c, name in enumerate(CHANNELS):
        hist = collections.Counter(a[c::4])
        total = sum(hist.values())
        mode_value, mode_count = hist.most_common(1)[0]
        share = mode_count / total
        if len(hist) < MIN_DISTINCT:
            raise DecodeError(f"{name}: only {len(hist)} distinct values")
        if share > MAX_MODE_SHARE:
            raise DecodeError(f"{name}: value {mode_value} dominates ({share:.3f})")
        out[name] = {"min": min(hist), "max": max(hist), "distinct": len(hist),
                     "mode": mode_value, "mode_share": round(share, 6)}
    return out


def decode_day(path: Path, day: str) -> tuple[bytes, dict]:
    raw = path.read_bytes()
    stream, finfo = deframe(raw)
    check_frames(finfo, day)
    r = scan_stream(stream)
    summary = check_scan(r)
    sample = spectral_block_le(stream, r["offsets"])
    stats = {
        "day": day,
        "source_bytes": len(raw),
        "frame_types": finfo["frame_types"],
        "first_ntp_utc": round(finfo["first_ntp_utc"], 3),
        "last_ntp_utc": round(finfo["last_ntp_utc"], 3),
        "stream_bytes": r["stream_bytes"],
        "rejected_candidates": dict(sorted(r["reject"].items())),
        "bytes_in_accepted_packets": PKT_TOTAL * summary["accepted_packets"],
        **summary,
        "channel_stats": channel_stats(sample),
    }
    return sample, stats


def read_tsv(path: Path) -> list[dict]:
    rows = []
    with path.open() as fh:
        header = fh.readline().rstrip("\n").split("\t")
        for line in fh:
            if line.strip():
                rows.append(dict(zip(header, line.rstrip("\n").split("\t"))))
    return rows


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def cmd_check_file(args) -> int:
    raw = Path(args.file).read_bytes()
    if len(raw) != args.size:
        raise DecodeError(f"size {len(raw)} != pinned {args.size}")
    stream, finfo = deframe(raw)
    check_frames(finfo, args.day)
    r = scan_stream(stream)
    summary = check_scan(r)
    print(f"check_ok day={args.day} frames={finfo['frame_types']} stream_bytes={len(stream)} "
          f"packets={summary['accepted_packets']} accept_fraction={summary['accept_fraction']} "
          f"rejected={dict(r['reject'])}")
    return 0


def cmd_build(args) -> int:
    repo_root = Path(args.repo_root)
    root = data_root(repo_root, args.data_dir)
    sources = read_tsv(Path(args.sources))
    dl = root / "downloads" / DATASET_ID
    plan = {r["filename"]: r for r in read_tsv(dl / "download_plan.tsv")}
    samples = root / "samples" / DATASET_ID / SERIES
    index_dir = root / "index" / DATASET_ID
    filtered = root / "filtered" / DATASET_ID
    for d in (samples, index_dir, filtered):
        d.mkdir(parents=True, exist_ok=True)
    for old in samples.glob("*.bin*"):
        old.unlink()
    rows = []
    per_day = []
    for src in sources:
        day = src["day"]
        path = dl / src["filename"]
        if not path.is_file():
            raise DecodeError(f"missing download {path}")
        if path.stat().st_size != int(src["size_bytes"]):
            raise DecodeError(f"{path.name}: size differs from pinned {src['size_bytes']}")
        recorded = plan.get(src["filename"])
        if recorded is None:
            raise DecodeError(f"{path.name}: absent from download_plan.tsv")
        digest = sha256_file(path)
        if digest != recorded["sha256"]:
            raise DecodeError(f"{path.name}: sha256 differs from download_plan.tsv")
        sample, stats = decode_day(path, day)
        stats["source_sha256"] = digest
        npk = stats["accepted_packets"]
        out = samples / f"{day}.bin"
        tmp = out.with_suffix(".bin.part")
        tmp.write_bytes(sample)
        os.replace(tmp, out)
        cs = stats["channel_stats"]
        rows.append({
            "dataset_id": DATASET_ID,
            "series_id": SERIES,
            "sample_path": f"samples/{DATASET_ID}/{SERIES}/{day}.bin",
            "numeric_kind": "uint",
            "bit_width": 16,
            "endianness": "little",
            "element_size_bytes": 2,
            "sample_size_bytes": len(sample),
            "value_count": len(sample) // 2,
            "shape": [npk, N_WAVE, 4],
            "axes": ["packet", "wavelength", "channel"],
            "channel_order": list(CHANNELS),
            "min": min(v["min"] for v in cs.values()),
            "max": max(v["max"] for v in cs.values()),
            "sha256": hashlib.sha256(sample).hexdigest(),
            "utc_day": day,
            "source_file": src["filename"],
            "source_sha256": digest,
        })
        per_day.append(stats)
        print(f"day={day} packets={npk} accept_fraction={stats['accept_fraction']} "
              f"rejected={stats['rejected_candidates']} range={rows[-1]['min']}..{rows[-1]['max']}", flush=True)
    with (index_dir / "samples.jsonl").open("w") as fh:
        for row in rows:
            fh.write(json.dumps(row, sort_keys=True) + "\n")
    totals = {"sample_count": len(rows), "total_size_bytes": sum(r["sample_size_bytes"] for r in rows),
              "value_count": sum(r["value_count"] for r in rows)}
    (filtered / "ingest_stats.json").write_text(
        json.dumps({"dataset_id": DATASET_ID, "series_id": SERIES, "totals": totals, "days": per_day},
                   indent=1, sort_keys=True) + "\n")
    print("totals", json.dumps(totals, sort_keys=True))
    return 0


# ---------------------------------------------------------------- selftest
def _pa_frame(payload: bytes, ftype: int = 1, ts: int = 0) -> bytes:
    hdr = bytearray(PA_SYNC + bytes([ftype]) + struct.pack(">H", PA_HEADER + len(payload)) + b"\x00\x00"
                    + struct.pack(">Q", ts))
    x = 0
    for b in bytes(hdr[:6]) + bytes(hdr[8:]) + payload:
        x ^= b
    hdr[6:8] = struct.pack(">H", x)
    return bytes(hdr) + payload


def _acs_packet(i: int, serial: int = 128, n: int = N_WAVE) -> tuple[bytes, list[int]]:
    vals = []
    for w in range(n):
        vals += [600 + 7 * w + i % 13, 700 + 5 * w + i % 11, 320 + 9 * w + i % 17, 380 + 3 * w + i % 19]
    hdr = REG + struct.pack(">HBBB", 32 + 8 * n, 5, 1, 0x53) + bytes([serial >> 16]) + struct.pack(">H", serial & 0xFFFF)
    hdr += struct.pack(">7HIBB", 300, 0, 310, 40000, 41000, 290, 280, 1000 * i, 0, n)
    body = hdr + struct.pack(">%dH" % len(vals), *vals)
    assert len(body) == 32 + 8 * n
    return body + struct.pack(">H", sum(body) & 0xFFFF) + b"\x00", vals


def synthetic(nrec: int = 30):
    stream = bytearray(b"\r\nAC-Spectra Version 1.11\r\n")
    expected = []
    t0 = int((day_bounds("20190601") + 7 * 3600 + 21 * 60 + NTP_EPOCH_OFFSET) * 2**32)
    for i in range(nrec):
        pkt, vals = _acs_packet(i)
        if i == 7:
            stream += pkt[:470]  # tail lost upstream -> next registration inside
            continue
        if i == 12:
            bad = bytearray(pkt)
            bad[100] ^= 0x01  # checksum failure
            stream += bad
            continue
        if i == 18:
            stream += b"\r\n14 A/D samples per bin\r\n"
        stream += pkt
        expected += vals
    raw = bytearray()
    pos = 0
    sizes = [8, 16, 240, 248, 232, 11, 272, 224]
    k = 0
    while pos < len(stream):
        chunk = bytes(stream[pos:pos + sizes[k % len(sizes)]])
        raw += _pa_frame(chunk, 1, t0 + (k << 28))
        pos += len(chunk)
        k += 1
    exp = array("H", expected)
    if sys.byteorder == "big":
        exp.byteswap()
    return bytes(raw), exp.tobytes()


def cmd_selftest(args) -> int:
    raw, expected = synthetic()
    stream, info = deframe(raw)
    r = scan_stream(stream)
    got = spectral_block_le(stream, r["offsets"])
    assert got == expected, "spectral block mismatch"
    assert len(r["offsets"]) == 28, len(r["offsets"])
    assert r["reject"]["checksum"] >= 1, r["reject"]
    assert set(r["identities"]) == {tuple(sorted(IDENTITY.items()))}
    # A splice whose 16-bit checksum collides must still be rejected.
    pkt, _ = _acs_packet(3)
    nxt, _ = _acs_packet(4)
    splice = bytearray(pkt[:480] + nxt)
    splice[REC_LEN:REC_LEN + 2] = struct.pack(">H", sum(splice[:REC_LEN]) & 0xFFFF)
    splice[REC_LEN + 2] = 0
    clean, clean_vals = _acs_packet(5)
    r2 = scan_stream(bytes(splice) + clean)
    assert r2["reject"]["internal_registration"] == 1, r2
    assert r2["offsets"] == [len(splice)], r2
    bad = bytearray(raw)
    bad[40] ^= 0x01
    try:
        deframe(bytes(bad))
    except DecodeError:
        pass
    else:
        raise AssertionError("port-agent corruption not detected")
    print(f"selftest_ok frames={info['frame_types']} accepted={len(r['offsets'])} rejected={dict(r['reject'])}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check-file")
    c.add_argument("--file", required=True)
    c.add_argument("--day", required=True)
    c.add_argument("--size", type=int, required=True)
    b = sub.add_parser("build")
    b.add_argument("--repo-root", required=True)
    b.add_argument("--data-dir", required=True)
    b.add_argument("--sources", required=True)
    sub.add_parser("selftest")
    args = ap.parse_args()
    try:
        return {"check-file": cmd_check_file, "build": cmd_build, "selftest": cmd_selftest}[args.cmd](args)
    except DecodeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
