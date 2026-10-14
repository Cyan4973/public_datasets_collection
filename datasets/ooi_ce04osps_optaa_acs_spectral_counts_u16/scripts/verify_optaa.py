#!/usr/bin/env python3
"""Independent verifier for ooi_ce04osps_optaa_acs_spectral_counts_u16.

Does not import the build decoder. Re-derives every sample from the pinned
downloads with a separately written port-agent deframer and AC-S packet
scanner (same acceptance rules: L == 704, sum checksum, zero pad byte, no
registration inside bytes [4, L), deployment header identity), then checks
byte equality, index fields, manifest totals and per-channel degeneracy.
Same missing-value policy as the build: nothing is imputed; rejected
(truncated or corrupt) packets are skipped.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import struct
import sys
import tomllib
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

DATASET_ID = "ooi_ce04osps_optaa_acs_spectral_counts_u16"
SERIES = "acs_spectral_counts_u16"
NTP_UNIX = 2208988800
REG_RE = re.compile(b"(?=\xff\x00\xff\x00)")
NW = 84
RLEN = 704
WANT_HEADER = (5, 1, 0x53, 128, NW)  # type, reserved, meter, serial, N


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
        acc = 0
        for v in hdr[:6]:
            acc ^= v
        for v in hdr[8:]:
            acc ^= v
        for v in mv[pos + 16:pos + plen]:
            acc ^= v
        if acc != pck:
            fail(f"port-agent XOR checksum mismatch at {pos}")
        if ptype == 1:
            out.append(raw[pos + 16:pos + plen])
            t_first = pts if t_first is None else t_first
            t_last = pts
        pos += plen
    if t_first is None:
        fail("no type-1 frames")
    return b"".join(out), t_first / 4294967296.0 - NTP_UNIX, t_last / 4294967296.0 - NTP_UNIX


def packets(stream: bytes):
    """Yield (start, header tuple) of accepted packets; return rejected count via list."""
    accepted = []
    rejected = 0
    resume = 0
    n = len(stream)
    for m in REG_RE.finditer(stream):
        q = m.start()
        if q < resume:
            continue
        if q + 6 > n:
            break
        if int.from_bytes(stream[q + 4:q + 6], "big") != RLEN:
            continue
        if q + RLEN + 3 > n:
            continue
        body = stream[q:q + RLEN]
        if sum(body) & 0xFFFF != int.from_bytes(stream[q + RLEN:q + RLEN + 2], "big") \
                or stream[q + RLEN + 2] != 0 or b"\xff\x00\xff\x00" in body[4:]:
            rejected += 1
            continue
        serial = int.from_bytes(body[9:12], "big")
        accepted.append((q, (body[6], body[7], body[8], serial, body[31])))
        resume = q + RLEN + 3
    return accepted, rejected


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
    lines = [l for l in path.read_text().splitlines() if l.strip()]
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
    rows = [json.loads(l) for l in (root / "index" / DATASET_ID / "samples.jsonl").read_text().splitlines() if l.strip()]
    by_path = {r["sample_path"]: r for r in rows}
    if len(by_path) != len(rows) or len(rows) != len(sources):
        fail(f"index rows {len(rows)} (unique {len(by_path)}) vs {len(sources)} sources")
    days = [s["day"] for s in sources]
    if len(set(days)) != len(days) or days != sorted(days):
        fail("sources.tsv days not unique and sorted")
    if not ("20190101" <= days[0] and days[-1] <= "20190613"):
        fail("selected days leave the pinned serial-128 window 2019-01-01..2019-06-13")
    seen = set()
    total_bytes = 0
    total_values = 0
    for src in sources:
        day = src["day"]
        f = root / "downloads" / DATASET_ID / src["filename"]
        if f.stat().st_size != int(src["size_bytes"]):
            fail(f"{f.name}: size mismatch")
        digest = sha256_path(f)
        if plan.get(src["filename"], {}).get("sha256") != digest:
            fail(f"{f.name}: sha256 not equal to download_plan.tsv")
        stream, t0, t1 = frames_to_stream(f.read_bytes())
        midnight = datetime.strptime(day, "%Y%m%d").replace(tzinfo=timezone.utc).timestamp()
        if not (25800 <= t0 - midnight <= 27900 and 77400 <= t1 - midnight <= 79200):
            fail(f"{day}: data frames span {t0 - midnight:.0f}..{t1 - midnight:.0f} s, not the 07:20-21:44 file window")
        acc, rejected = packets(stream)
        if len(acc) < 15000:
            fail(f"{day}: only {len(acc)} accepted packets")
        headers = Counter(h for _, h in acc)
        if set(headers) != {WANT_HEADER}:
            fail(f"{day}: header identity {dict(headers)}")
        if len(acc) < 0.5 * (len(acc) + rejected):
            fail(f"{day}: accepted {len(acc)} vs rejected {rejected}")
        chunks = []
        chans = ([], [], [], [])
        for q, _ in acc:
            vals = struct.unpack(">%dH" % (4 * NW), stream[q + 32:q + RLEN])
            chunks.append(struct.pack("<%dH" % (4 * NW), *vals))
            for c in range(4):
                chans[c].extend(vals[c::4])
        expected = b"".join(chunks)
        rel = f"samples/{DATASET_ID}/{SERIES}/{day}.bin"
        row = by_path.get(rel)
        if row is None:
            fail(f"index lacks {rel}")
        actual = (root / rel).read_bytes()
        if actual != expected:
            fail(f"{rel}: bytes differ from independent re-derivation")
        lo = hi = None
        for c, vals in enumerate(chans):
            hist = Counter(vals)
            if len(hist) < 64 or hist.most_common(1)[0][1] > 0.5 * len(vals):
                fail(f"{rel}: channel {c} degenerate (distinct={len(hist)})")
            lo = min(hist) if lo is None else min(lo, min(hist))
            hi = max(hist) if hi is None else max(hi, max(hist))
        want = {
            "dataset_id": DATASET_ID, "series_id": SERIES, "numeric_kind": "uint", "bit_width": 16,
            "endianness": "little", "element_size_bytes": 2, "sample_size_bytes": len(actual),
            "value_count": len(actual) // 2, "shape": [len(acc), NW, 4], "min": lo, "max": hi,
            "sha256": hashlib.sha256(actual).hexdigest(), "source_sha256": digest, "utc_day": day,
        }
        for k, v in want.items():
            if row.get(k) != v:
                fail(f"{rel}: index field {k}={row.get(k)!r} expected {v!r}")
        if want["sha256"] in seen:
            fail(f"{rel}: duplicate sample content")
        seen.add(want["sha256"])
        total_bytes += len(actual)
        total_values += len(actual) // 2
        print(f"verified day={day} packets={len(acc)} rejected={rejected} range={lo}..{hi}", flush=True)
    files = sorted((root / "samples" / DATASET_ID / SERIES).glob("*"))
    if len(files) != len(sources):
        fail(f"{len(files)} files on disk vs {len(sources)} verified")
    m = {x["id"]: x for x in manifest["series"]}.get(SERIES)
    if m is None:
        fail(f"manifest lacks series {SERIES}")
    if m["sample_count"] != len(sources) or m["total_size_bytes"] != total_bytes:
        fail(f"manifest {m['sample_count']}/{m['total_size_bytes']} != realized {len(sources)}/{total_bytes}")
    print("verify_ok", json.dumps({"sample_count": len(sources), "total_size_bytes": total_bytes,
                                   "value_count": total_values}, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
