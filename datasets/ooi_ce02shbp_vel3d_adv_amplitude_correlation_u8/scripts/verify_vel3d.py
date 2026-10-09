#!/usr/bin/env python3
"""Independent verifier for ooi_ce02shbp_vel3d_adv_amplitude_correlation_u8.

Does not import the build decoder. Re-derives every sample from the pinned
downloads with a separately written port-agent deframer and Nortek scanner,
then checks byte equality, index fields, manifest totals, the deployment
identity guard, and degeneracy rules (same missing-value policy as build:
nothing is imputed; checksum-failed packets are skipped within tight bounds).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import struct
import sys
import tomllib
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

DATASET_ID = "ooi_ce02shbp_vel3d_adv_amplitude_correlation_u8"
SERIES = ("vel3d_beam_amplitude_u8", "vel3d_beam_correlation_u8")
FIELD_OFFSET = {"vel3d_beam_amplitude_u8": 16, "vel3d_beam_correlation_u8": 19}
NTP_UNIX = 2208988800


def fail(msg: str) -> None:
    print(f"VERIFY FAILED: {msg}", file=sys.stderr)
    sys.exit(1)


def frames_to_stream(raw: bytes) -> tuple[bytes, float, float]:
    mv = memoryview(raw)
    out = []
    pos = 0
    t_first = t_last = None
    while pos < len(raw):
        hdr = raw[pos:pos + 16]
        if len(hdr) < 16 or hdr[:3] != b"\xa3\x9d\x7a":
            fail(f"port-agent framing broken at byte {pos}")
        ptype, plen, pck, pts = struct.unpack(">BHHQ", hdr[3:16])
        if plen < 16 or pos + plen > len(raw):
            fail(f"port-agent length {plen} invalid at {pos}")
        body = mv[pos + 16:pos + plen]
        acc = 0
        for v in hdr[:6]:
            acc ^= v
        for v in hdr[8:]:
            acc ^= v
        for v in body:
            acc ^= v
        if acc != pck:
            fail(f"port-agent XOR checksum mismatch at {pos}")
        if ptype == 1:
            out.append(bytes(body))
            t_first = pts if t_first is None else t_first
            t_last = pts
        pos += plen
    if t_first is None:
        fail("no type-1 frames")
    return b"".join(out), t_first / 4294967296.0 - NTP_UNIX, t_last / 4294967296.0 - NTP_UNIX


def nortek_sum_ok(buf: bytes, start: int, nbytes: int) -> bool:
    words = struct.unpack("<%dH" % (nbytes // 2), buf[start:start + nbytes])
    return (0xB58C + sum(words[:-1])) & 0xFFFF == words[-1]


def extract(stream: bytes):
    """Jump between 0xA5 candidates; same acceptance rules as the build decoder."""
    beams = {s: ([], [], []) for s in SERIES}
    n = len(stream)
    p = 0
    unparsed = 0
    failed_vel = 0
    sys_heading, sys_pitch, sys_roll, sys_status = [], [], [], Counter()
    while True:
        q = stream.find(b"\xa5", p)
        if q < 0:
            unparsed += n - p
            break
        unparsed += q - p
        p = q
        if p + 4 > n:
            unparsed += n - p
            break
        ident = stream[p + 1]
        size = 24 if ident == 0x10 else 2 * int.from_bytes(stream[p + 2:p + 4], "little")
        if 6 <= size <= 1024 and p + size <= n and nortek_sum_ok(stream, p, size):
            if ident == 0x10:
                for s in SERIES:
                    off = FIELD_OFFSET[s]
                    for b in range(3):
                        beams[s][b].append(stream[p + off + b])
            elif ident == 0x11 and size == 28:
                h, pi, r = struct.unpack("<3h", stream[p + 14:p + 20])
                sys_heading.append(h)
                sys_pitch.append(pi)
                sys_roll.append(r)
                sys_status[stream[p + 23]] += 1
            p += size
            continue
        if ident == 0x10 and p + 24 <= n:
            failed_vel += 1
        unparsed += 1
        p += 1
    return beams, unparsed, failed_vel, sys_heading, sys_pitch, sys_roll, sys_status


def mid(values):
    s = sorted(values)
    return s[len(s) // 2]


def sha256_path(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        while True:
            chunk = fh.read(1 << 20)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def load_tsv(path: Path) -> list[dict]:
    lines = [l.rstrip("\n") for l in path.read_text().splitlines() if l.strip()]
    keys = lines[0].split("\t")
    return [dict(zip(keys, l.split("\t"))) for l in lines[1:]]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo-root", required=True)
    ap.add_argument("--data-dir", required=True)
    ap.add_argument("--recipe-dir", required=True)
    args = ap.parse_args()
    recipe = Path(args.recipe_dir)
    root = Path(args.data_dir) if Path(args.data_dir).is_absolute() else Path(args.repo_root) / args.data_dir
    manifest = tomllib.loads((recipe / "manifest.toml").read_text())
    sources = load_tsv(recipe / "sources.tsv")
    plan = {r["filename"]: r for r in load_tsv(root / "downloads" / DATASET_ID / "download_plan.tsv")}
    index_path = root / "index" / DATASET_ID / "samples.jsonl"
    rows = [json.loads(l) for l in index_path.read_text().splitlines() if l.strip()]
    by_path = {r["sample_path"]: r for r in rows}
    if len(by_path) != len(rows):
        fail("duplicate sample_path in index")
    if len(rows) != 2 * len(sources):
        fail(f"index rows {len(rows)} != 2 x {len(sources)} sources")
    days = [s["day"] for s in sources]
    if len(set(days)) != len(days) or days != sorted(days):
        fail("sources.tsv days not unique and sorted")
    if not ("20250828" < days[0] and days[-1] < "20260809"):
        fail("selected days leave the pinned deployment window")
    seen_hashes = set()
    totals = {s: [0, 0] for s in SERIES}
    for src in sources:
        day = src["day"]
        f = root / "downloads" / DATASET_ID / src["filename"]
        if f.stat().st_size != int(src["size_bytes"]):
            fail(f"{f.name}: size mismatch")
        digest = sha256_path(f)
        if plan.get(src["filename"], {}).get("sha256") != digest:
            fail(f"{f.name}: sha256 not equal to download_plan.tsv")
        stream, t0, t1 = frames_to_stream(f.read_bytes())
        start = datetime.strptime(day, "%Y%m%d").replace(tzinfo=timezone.utc).timestamp()
        if not (start - 5 <= t0 < start + 600 and start + 86400 - 600 <= t1 < start + 86460):
            fail(f"{day}: timestamps {t0}..{t1} outside the UTC day")
        beams, unparsed, failed_vel, hd, pt, rl, status = extract(stream)
        nrec = len(beams[SERIES[0]][0])
        if not (690000 <= nrec <= 692000):
            fail(f"{day}: {nrec} velocity records")
        if failed_vel > 1e-4 * nrec or unparsed > 1e-3 * len(stream):
            fail(f"{day}: failed={failed_vel} unparsed={unparsed}")
        nsys = sum(status.values())
        if nsys < 80000 or status[0x63] < 0.999 * nsys:
            fail(f"{day}: status byte guard failed {dict(status)}")
        h, p_, r_ = mid(hd) / 10, mid(pt) / 10, mid(rl) / 10
        if not (128 <= h <= 140 and -3 <= p_ <= 7 and -3 <= r_ <= 6):
            fail(f"{day}: orientation {h},{p_},{r_} outside deployment guard")
        for s in SERIES:
            expected = bytes(beams[s][0]) + bytes(beams[s][1]) + bytes(beams[s][2])
            rel = f"samples/{DATASET_ID}/{s}/{day}.bin"
            row = by_path.get(rel)
            if row is None:
                fail(f"index lacks {rel}")
            actual = (root / rel).read_bytes()
            if actual != expected:
                fail(f"{rel}: bytes differ from independent re-derivation")
            for b in range(3):
                beam = beams[s][b]
                hist = Counter(beam)
                if len(hist) < 8 or hist.most_common(1)[0][1] > 0.75 * len(beam):
                    fail(f"{rel}: beam {b + 1} degenerate (distinct={len(hist)})")
            want = {
                "dataset_id": DATASET_ID, "series_id": s, "numeric_kind": "uint", "bit_width": 8,
                "endianness": "little", "element_size_bytes": 1, "sample_size_bytes": len(actual),
                "value_count": len(actual), "shape": [3, nrec], "min": min(actual), "max": max(actual),
                "sha256": hashlib.sha256(actual).hexdigest(), "source_sha256": digest,
            }
            for k, v in want.items():
                if row.get(k) != v:
                    fail(f"{rel}: index field {k}={row.get(k)!r} expected {v!r}")
            if want["sha256"] in seen_hashes:
                fail(f"{rel}: duplicate sample content")
            seen_hashes.add(want["sha256"])
            totals[s][0] += 1
            totals[s][1] += len(actual)
        print(f"verified day={day} records={nrec} hdg={h} pitch={p_} roll={r_}", flush=True)
    for s in SERIES:
        files = sorted((root / "samples" / DATASET_ID / s).glob("*"))
        if len(files) != totals[s][0]:
            fail(f"{s}: {len(files)} files on disk vs {totals[s][0]} verified")
    mseries = {x["id"]: x for x in manifest["series"]}
    for s in SERIES:
        m = mseries.get(s)
        if m is None:
            fail(f"manifest lacks series {s}")
        if m["sample_count"] != totals[s][0] or m["total_size_bytes"] != totals[s][1]:
            fail(f"{s}: manifest {m['sample_count']}/{m['total_size_bytes']} != realized {totals[s][0]}/{totals[s][1]}")
    print("verify_ok", json.dumps({s: {"sample_count": v[0], "total_size_bytes": v[1]} for s, v in totals.items()}, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
