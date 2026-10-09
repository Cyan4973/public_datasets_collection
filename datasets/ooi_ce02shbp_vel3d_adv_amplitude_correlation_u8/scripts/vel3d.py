#!/usr/bin/env python3
"""Decode OOI VEL3D-C (Nortek Vector ADV) raw port-agent day files.

Pure standard library. Subcommands:
  check-file  validate one downloaded day file (port-agent framing, XOR
              checksums, timestamps inside the UTC day, velocity-packet yield)
  build       decode every pinned day file and emit beam-planar uint8
              amplitude and correlation samples plus the sample index
  selftest    run the decoder on synthetic port-agent frames

Layers:
  1. OOI port-agent frames: sync a3 9d 7a, type (1 byte), length (2 bytes BE,
     includes the 16-byte header), checksum (2 bytes BE; XOR of every frame
     byte with the checksum field zeroed), NTP timestamp (8 bytes BE).
     Only type 1 (data from instrument) payloads are kept and concatenated in
     file order; Nortek packets may straddle frame boundaries.
  2. Nortek Vector binary packets in the reassembled stream: 0xA5, id.
     Velocity Data (id 0x10) is a fixed 24-byte packet; every other packet
     carries its size in 16-bit words at bytes 2-3 (LE). Checksum:
     (0xB58C + sum of all LE uint16 words except the last) & 0xFFFF == last.
     Velocity Data bytes 16..18 = AmpB1..B3 (counts), 19..21 = CorrB1..B3 (%).
     System Data (id 0x11, 28 bytes) supplies heading/pitch/roll and the
     status byte used as the deployment-identity guard.
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import os
import struct
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

DATASET_ID = "ooi_ce02shbp_vel3d_adv_amplitude_correlation_u8"
SERIES_AMP = "vel3d_beam_amplitude_u8"
SERIES_COR = "vel3d_beam_correlation_u8"
PA_SYNC = b"\xa3\x9d\x7a"
PA_HEADER = 16
PA_TYPE_DATA = 1
NTP_EPOCH_OFFSET = 2208988800
NORTEK_SYNC = 0xA5
VEL_ID = 0x10
SYS_ID = 0x11
VEL_LEN = 24
SYS_LEN = 28
MAX_NORTEK_LEN = 1024

# Deployment-identity guard for the 2025-08-28 .. 2026-08-08 VEL3D-C deployment
# (probed 2026-10-09; the 2026-08-09 swap moves heading to ~265 deg and the
# 2024-2025 deployment reports status 0x53).
EXPECTED_STATUS = 0x63
HEADING_RANGE = (128.0, 140.0)
PITCH_RANGE = (-3.0, 7.0)
ROLL_RANGE = (-3.0, 6.0)
RECORDS_PER_DAY = 8 * 86400
MIN_RECORDS = 690_000
MAX_RECORDS = 692_000
MAX_BAD_VEL_FRACTION = 1e-4
MAX_JUNK_FRACTION = 1e-3
MAX_COUNT_GAPS = 20
# Degeneracy guard: a beam fails if one value exceeds 75% of its records. Clear-water
# days legitimately sit at the amplitude noise floor (beam 3 value 90 holds 53.6%
# of 2026-07-04 with 56 distinct values), so 50% would reject real signal.
MAX_MODE_SHARE = 0.75
MIN_DISTINCT = 8


class DecodeError(Exception):
    pass


def data_root(repo_root: Path, data_dir: str) -> Path:
    p = Path(data_dir)
    return p if p.is_absolute() else repo_root / p


def deframe(raw: bytes) -> tuple[bytes, dict]:
    """Walk port-agent frames from offset 0 to EOF; return type-1 payload stream."""
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


def nortek_ok(s: bytes, p: int, length: int) -> bool:
    words = length // 2 - 1
    total = 0xB58C + sum(struct.unpack_from("<%dH" % words, s, p))
    (stored,) = struct.unpack_from("<H", s, p + 2 * words)
    return (total & 0xFFFF) == stored


def scan_stream(s: bytes) -> dict:
    """Scan the reassembled instrument stream for checksum-valid Nortek packets."""
    n = len(s)
    amp = [bytearray(), bytearray(), bytearray()]
    cor = [bytearray(), bytearray(), bytearray()]
    ids = collections.Counter()
    junk = 0
    bad_vel = 0
    gaps = 0
    prev_count = None
    heading, pitch, roll = [], [], []
    status = collections.Counter()
    p = 0
    while p < n:
        if s[p] == NORTEK_SYNC and p + 4 <= n:
            pid = s[p + 1]
            if pid == VEL_ID:
                length = VEL_LEN
            else:
                length = 2 * struct.unpack_from("<H", s, p + 2)[0]
            if 6 <= length <= MAX_NORTEK_LEN and p + length <= n and nortek_ok(s, p, length):
                ids[pid] += 1
                if pid == VEL_ID:
                    for b in range(3):
                        amp[b].append(s[p + 16 + b])
                        cor[b].append(s[p + 19 + b])
                    c = s[p + 3]
                    if prev_count is not None and c != (prev_count + 1) & 0xFF:
                        gaps += 1
                    prev_count = c
                elif pid == SYS_ID and length == SYS_LEN:
                    h, pi, r = struct.unpack_from("<hhh", s, p + 14)
                    heading.append(h)
                    pitch.append(pi)
                    roll.append(r)
                    status[s[p + 23]] += 1
                p += length
                continue
            if pid == VEL_ID and p + VEL_LEN <= n:
                bad_vel += 1
        junk += 1
        p += 1
    return {
        "amp": amp, "cor": cor, "ids": ids, "junk": junk, "bad_vel": bad_vel,
        "count_gaps": gaps, "heading": heading, "pitch": pitch, "roll": roll,
        "status": status, "stream_bytes": n,
    }


def median(v):
    v = sorted(v)
    if not v:
        raise DecodeError("empty median")
    return v[len(v) // 2]


def day_bounds(day: str) -> tuple[float, float]:
    d0 = datetime.strptime(day, "%Y%m%d").replace(tzinfo=timezone.utc)
    return d0.timestamp(), (d0 + timedelta(days=1)).timestamp()


def check_series_values(name: str, values: bytes) -> dict:
    hist = collections.Counter(values)
    mode_value, mode_count = hist.most_common(1)[0]
    share = mode_count / len(values)
    if len(hist) < MIN_DISTINCT:
        raise DecodeError(f"{name}: only {len(hist)} distinct values")
    if share > MAX_MODE_SHARE:
        raise DecodeError(f"{name}: value {mode_value} dominates ({share:.3f})")
    return {"min": min(hist), "max": max(hist), "distinct": len(hist),
            "mode": mode_value, "mode_share": round(share, 6)}


def decode_day(path: Path, day: str) -> tuple[bytes, bytes, dict]:
    raw = path.read_bytes()
    stream, finfo = deframe(raw)
    lo, hi = day_bounds(day)
    if finfo["first_ntp_utc"] is None:
        raise DecodeError("no data frames")
    if not (lo - 5 <= finfo["first_ntp_utc"] < lo + 600):
        raise DecodeError(f"first timestamp {finfo['first_ntp_utc']} not at start of {day}")
    if not (hi - 600 <= finfo["last_ntp_utc"] < hi + 60):
        raise DecodeError(f"last timestamp {finfo['last_ntp_utc']} not at end of {day}")
    r = scan_stream(stream)
    nrec = len(r["amp"][0])
    if not (MIN_RECORDS <= nrec <= MAX_RECORDS):
        raise DecodeError(f"velocity record count {nrec} outside [{MIN_RECORDS},{MAX_RECORDS}]")
    if r["bad_vel"] > MAX_BAD_VEL_FRACTION * nrec:
        raise DecodeError(f"too many checksum-failed velocity packets: {r['bad_vel']}")
    if r["junk"] > MAX_JUNK_FRACTION * r["stream_bytes"]:
        raise DecodeError(f"too many unparsed stream bytes: {r['junk']}")
    if r["count_gaps"] > MAX_COUNT_GAPS:
        raise DecodeError(f"too many velocity count gaps: {r['count_gaps']}")
    nsys = sum(r["status"].values())
    if nsys < 80000:
        raise DecodeError(f"too few system packets: {nsys}")
    st_share = r["status"][EXPECTED_STATUS] / nsys
    if st_share < 0.999:
        raise DecodeError(f"status byte 0x{EXPECTED_STATUS:02x} share {st_share:.4f}")
    hdg = median(r["heading"]) / 10
    pit = median(r["pitch"]) / 10
    rol = median(r["roll"]) / 10
    for label, val, (a, b) in (("heading", hdg, HEADING_RANGE), ("pitch", pit, PITCH_RANGE), ("roll", rol, ROLL_RANGE)):
        if not (a <= val <= b):
            raise DecodeError(f"{label} median {val} outside deployment range [{a},{b}]")
    beam_stats = {}
    for b in range(3):
        beam_stats[f"amp_b{b + 1}"] = check_series_values(f"amp beam {b + 1}", bytes(r["amp"][b]))
        beam_stats[f"cor_b{b + 1}"] = check_series_values(f"cor beam {b + 1}", bytes(r["cor"][b]))
    amp_sample = bytes(r["amp"][0] + r["amp"][1] + r["amp"][2])
    cor_sample = bytes(r["cor"][0] + r["cor"][1] + r["cor"][2])
    stats = {
        "day": day,
        "source_bytes": len(raw),
        "frame_types": finfo["frame_types"],
        "first_ntp_utc": round(finfo["first_ntp_utc"], 3),
        "last_ntp_utc": round(finfo["last_ntp_utc"], 3),
        "stream_bytes": r["stream_bytes"],
        "nortek_packet_ids": {f"0x{k:02x}": v for k, v in sorted(r["ids"].items())},
        "velocity_records": nrec,
        "checksum_failed_velocity_candidates": r["bad_vel"],
        "unparsed_stream_bytes": r["junk"],
        "velocity_count_gaps": r["count_gaps"],
        "system_packets": nsys,
        "status_byte_counts": {f"0x{k:02x}": v for k, v in sorted(r["status"].items())},
        "median_heading_deg": hdg,
        "median_pitch_deg": pit,
        "median_roll_deg": rol,
        "beam_stats": beam_stats,
    }
    return amp_sample, cor_sample, stats


def read_sources(path: Path) -> list[dict]:
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
    lo, hi = day_bounds(args.day)
    if finfo["first_ntp_utc"] is None or not (lo - 5 <= finfo["first_ntp_utc"] < lo + 600):
        raise DecodeError(f"first timestamp {finfo['first_ntp_utc']} not at start of {args.day}")
    if not (hi - 600 <= finfo["last_ntp_utc"] < hi + 60):
        raise DecodeError(f"last timestamp {finfo['last_ntp_utc']} not at end of {args.day}")
    approx_vel = stream.count(b"\xa5\x10")
    if approx_vel < MIN_RECORDS:
        raise DecodeError(f"only {approx_vel} velocity sync candidates")
    print(f"check_ok day={args.day} frames={finfo['frame_types']} stream_bytes={len(stream)} vel_candidates={approx_vel}")
    return 0


def cmd_build(args) -> int:
    repo_root = Path(args.repo_root)
    root = data_root(repo_root, args.data_dir)
    sources = read_sources(Path(args.sources))
    dl = root / "downloads" / DATASET_ID
    plan = {r["filename"]: r for r in read_sources(dl / "download_plan.tsv")}
    samples = root / "samples" / DATASET_ID
    index_dir = root / "index" / DATASET_ID
    filtered = root / "filtered" / DATASET_ID
    for d in (samples / SERIES_AMP, samples / SERIES_COR, index_dir, filtered):
        d.mkdir(parents=True, exist_ok=True)
    for series in (SERIES_AMP, SERIES_COR):
        for old in (samples / series).glob("*.bin"):
            old.unlink()
    rows = []
    per_day = []
    for src in sources:
        day = src["day"]
        path = dl / src["filename"]
        if not path.is_file():
            raise DecodeError(f"missing download {path}")
        size = path.stat().st_size
        if size != int(src["size_bytes"]):
            raise DecodeError(f"{path.name}: size {size} != pinned {src['size_bytes']}")
        recorded = plan.get(src["filename"])
        if recorded is None:
            raise DecodeError(f"{path.name}: absent from download_plan.tsv")
        digest = sha256_file(path)
        if digest != recorded["sha256"]:
            raise DecodeError(f"{path.name}: sha256 differs from download_plan.tsv")
        amp, cor, stats = decode_day(path, day)
        stats["source_sha256"] = digest
        nrec = stats["velocity_records"]
        for series, blob in ((SERIES_AMP, amp), (SERIES_COR, cor)):
            out = samples / series / f"{day}.bin"
            tmp = out.with_suffix(".bin.part")
            tmp.write_bytes(blob)
            os.replace(tmp, out)
            rows.append({
                "dataset_id": DATASET_ID,
                "series_id": series,
                "sample_path": f"samples/{DATASET_ID}/{series}/{day}.bin",
                "numeric_kind": "uint",
                "bit_width": 8,
                "endianness": "little",
                "element_size_bytes": 1,
                "sample_size_bytes": len(blob),
                "value_count": len(blob),
                "shape": [3, nrec],
                "axes": ["beam", "velocity_record"],
                "min": min(blob),
                "max": max(blob),
                "sha256": hashlib.sha256(blob).hexdigest(),
                "utc_day": day,
                "source_file": src["filename"],
                "source_sha256": digest,
            })
        per_day.append(stats)
        print(f"day={day} records={nrec} junk={stats['unparsed_stream_bytes']} bad_vel={stats['checksum_failed_velocity_candidates']} "
              f"gaps={stats['velocity_count_gaps']} hdg={stats['median_heading_deg']} pitch={stats['median_pitch_deg']} roll={stats['median_roll_deg']}",
              flush=True)
    with (index_dir / "samples.jsonl").open("w") as fh:
        for row in rows:
            fh.write(json.dumps(row, sort_keys=True) + "\n")
    totals = {}
    for series in (SERIES_AMP, SERIES_COR):
        sel = [r for r in rows if r["series_id"] == series]
        totals[series] = {"sample_count": len(sel), "total_size_bytes": sum(r["sample_size_bytes"] for r in sel)}
    (filtered / "ingest_stats.json").write_text(json.dumps({"dataset_id": DATASET_ID, "totals": totals, "days": per_day}, indent=1, sort_keys=True) + "\n")
    print("totals", json.dumps(totals, sort_keys=True))
    return 0


def _pa_frame(payload: bytes, ftype: int = 1, ts: int = 0) -> bytes:
    hdr = bytearray(PA_SYNC + bytes([ftype]) + struct.pack(">H", PA_HEADER + len(payload)) + b"\x00\x00" + struct.pack(">Q", ts))
    x = 0
    for b in bytes(hdr) + payload:
        x ^= b
    hdr[6:8] = struct.pack(">H", x)
    return bytes(hdr) + payload


def _nortek(pid: int, body: bytes, sized: bool) -> bytes:
    if sized:
        length = 4 + len(body) + 2
        pkt = bytes([NORTEK_SYNC, pid]) + struct.pack("<H", length // 2) + body
    else:
        pkt = bytes([NORTEK_SYNC, pid]) + body
    words = len(pkt) // 2
    ck = (0xB58C + sum(struct.unpack("<%dH" % words, pkt))) & 0xFFFF
    return pkt + struct.pack("<H", ck)


def synthetic_stream(nrec: int = 40):
    """Return (port-agent bytes, expected amp sample, expected cor sample)."""
    stream = bytearray()
    amp = [[], [], []]
    cor = [[], [], []]
    for i in range(nrec):
        if i % 8 == 0:
            body = bytes(6) + struct.pack("<HHhhhh", 115, 14843, 1335, 20, 25, 900) + bytes([0, EXPECTED_STATUS]) + b"\x00\x00"
            stream += _nortek(SYS_ID, body, sized=True)
        a = [(17 * i + 5 * b) % 256 for b in range(3)]
        c = [(29 * i + 3 * b + 1) % 100 for b in range(3)]
        body = bytes([0, i & 0xFF, 0, 0]) + struct.pack("<hhhhh", 1000 + i, 0, -i, i, 2 * i) + bytes(a) + bytes(c)
        pkt = _nortek(VEL_ID, body, sized=False)
        assert len(pkt) == VEL_LEN
        stream += pkt
        for b in range(3):
            amp[b].append(a[b])
            cor[b].append(c[b])
        if i == 10:
            stream += b"\xa5\x10\x00"  # junk / partial packet
        if i == 20:
            bad = bytearray(_nortek(VEL_ID, body, sized=False))
            bad[17] ^= 0xFF  # corrupt -> must be skipped
            stream += bad
    raw = bytearray()
    pos = 0
    sizes = [7, 24, 31, 3, 50, 24, 13]
    k = 0
    while pos < len(stream):
        chunk = bytes(stream[pos:pos + sizes[k % len(sizes)]])
        raw += _pa_frame(chunk, 1, k << 32)
        if k % 5 == 2:
            raw += _pa_frame(b"driver command", 3, k << 32)
        pos += len(chunk)
        k += 1
    return bytes(raw), bytes(sum(amp, [])), bytes(sum(cor, []))


def cmd_selftest(args) -> int:
    raw, exp_amp, exp_cor = synthetic_stream()
    stream, info = deframe(raw)
    r = scan_stream(stream)
    got_amp = bytes(r["amp"][0] + r["amp"][1] + r["amp"][2])
    got_cor = bytes(r["cor"][0] + r["cor"][1] + r["cor"][2])
    assert got_amp == exp_amp, "amplitude mismatch"
    assert got_cor == exp_cor, "correlation mismatch"
    assert r["bad_vel"] >= 1, "corrupt packet not detected"
    assert r["ids"][VEL_ID] == 40 and r["ids"][SYS_ID] == 5, r["ids"]
    assert r["status"][EXPECTED_STATUS] == 5 and median(r["heading"]) == 1335
    assert info["frame_types"].get("3", 0) > 0
    bad = bytearray(raw)
    bad[20] ^= 0x01
    try:
        deframe(bytes(bad))
    except DecodeError:
        pass
    else:
        raise AssertionError("port-agent checksum corruption not detected")
    print(f"selftest_ok frames={info['frame_types']} vel={r['ids'][VEL_ID]} junk={r['junk']} bad_vel={r['bad_vel']}")
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
