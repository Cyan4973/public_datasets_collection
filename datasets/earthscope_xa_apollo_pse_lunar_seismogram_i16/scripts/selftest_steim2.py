#!/usr/bin/env python3
"""Self-test for scripts/mseed.py on synthetic miniSEED 2 / Steim2 records.

An independent minimal Steim2 *encoder* packs difference sequences chosen to
exercise every Steim2 sub-format (4x8-bit; 1x30, 2x15, 3x10 bits; 5x6, 6x5,
7x4 bits), wraps them in 4096-byte big-endian miniSEED 2 records with
blockettes 1000 and 1001, and checks that the decoder

* reproduces the samples exactly (including -1 gap markers and 0..1023);
* honours BTIME + blockette 1001 microseconds;
* rejects a corrupted reverse integration constant Xn;
* rejects a header claiming more samples than the frames hold;
* assemble_chain concatenates contiguous records, drops exact duplicates and
  records starting outside the day, and rejects gaps and conflicts.

Exit status 0 on success; raises AssertionError otherwise. Run by build.sh and
verify.sh before any real decoding.
"""
from __future__ import annotations

import datetime as dt
import random
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import mseed  # noqa: E402

# (control code, dnib or None, count, bits)
FORMATS = [
    (1, None, 4, 8),
    (2, 1, 1, 30), (2, 2, 2, 15), (2, 3, 3, 10),
    (3, 0, 5, 6), (3, 1, 6, 5), (3, 2, 7, 4),
]


def fits(v, bits):
    return -(1 << (bits - 1)) <= v < (1 << (bits - 1))


def pack_word(diffs, bits, dnib):
    w = 0
    for d in diffs:
        w = (w << bits) | (d & ((1 << bits) - 1))
    if dnib is not None:
        w |= dnib << 30
    return w


def encode_steim2(samples, rng, force_cycle=False):
    """Return (frames bytes, number of samples encoded) for up to 63 frames."""
    diffs = [samples[0]] + [b - a for a, b in zip(samples, samples[1:])]
    words = []  # (code, word)
    i = 0
    cyc = 0
    while i < len(diffs):
        cands = []
        for code, dnib, cnt, bits in FORMATS:
            chunk = diffs[i:i + cnt]
            if len(chunk) == cnt and all(fits(d, bits) for d in chunk):
                cands.append((code, dnib, cnt, bits))
        if not cands:
            raise ValueError("difference too large for synthetic encoder")
        if force_cycle:
            pick = cands[cyc % len(cands)]
            cyc += 1
        else:
            pick = max(cands, key=lambda c: c[2])
        code, dnib, cnt, bits = pick
        words.append((code, pack_word(diffs[i:i + cnt], bits, dnib)))
        i += cnt
    # frames: frame 0 has W0, X0, Xn, then 13 data words; others W0 + 15
    frames = []
    pos = 0
    nsamp_encoded = 0
    consumed = 0
    first = True
    while pos < len(words) and len(frames) < 63:
        slots = 13 if first else 15
        chunk = words[pos:pos + slots]
        pos += len(chunk)
        frames.append((first, chunk))
        first = False
    # samples covered = sum of counts of words used
    used = words[:pos]
    for code, w in used:
        if code == 1:
            consumed += 4
        elif code == 2:
            consumed += {1: 1, 2: 2, 3: 3}[w >> 30]
        else:
            consumed += {0: 5, 1: 6, 2: 7}[w >> 30]
    nsamp_encoded = min(consumed, len(samples))
    x0 = samples[0]
    xn = samples[nsamp_encoded - 1]
    out = bytearray()
    for first, chunk in frames:
        ctrl = 0
        body = []
        if first:
            body = [x0 & 0xFFFFFFFF, xn & 0xFFFFFFFF]
            base = 3
        else:
            base = 1
        for k, (code, w) in enumerate(chunk):
            ctrl |= code << (30 - 2 * (base + k))
            body.append(w)
        while len(body) < 15:
            body.append(0)
        out += struct.pack(">16I", ctrl, *body)
    return bytes(out), nsamp_encoded


def make_record(samples, start: dt.datetime, seq=1, sta="S15", loc="00", cha="MHZ",
                net="XA", rng=None, force_cycle=False, bad_xn=False, claim_extra=0):
    frames, n = encode_steim2(samples, rng, force_cycle)
    if bad_xn:
        b = bytearray(frames)
        xn = struct.unpack_from(">i", b, 8)[0]
        struct.pack_into(">i", b, 8, xn + 1)
        frames = bytes(b)
    reclen = 4096
    data_off = 64
    usec = start.microsecond % 100
    tenk = start.microsecond // 100
    doy = start.timetuple().tm_yday
    hdr = bytearray(64)
    hdr[0:6] = f"{seq:06d}".encode()
    hdr[6:7] = b"M"
    hdr[7:8] = b" "
    hdr[8:13] = sta.ljust(5).encode()
    hdr[13:15] = loc.ljust(2).encode()
    hdr[15:18] = cha.ljust(3).encode()
    hdr[18:20] = net.ljust(2).encode()
    # 6.625 sps = factor 53, multiplier -8
    struct.pack_into(">HHBBBBHHhhBBBBiHH", hdr, 20, start.year, doy, start.hour, start.minute,
                     start.second, 0, tenk, n + claim_extra, 53, -8, 0, 0, 0, 2, 0, data_off, 48)
    struct.pack_into(">HHBBBB", hdr, 48, 1000, 56, 11, 1, 12, 0)
    struct.pack_into(">HHBbBB", hdr, 56, 1001, 0, 0, usec, 0, 0)
    body = frames[: reclen - data_off]
    rec = bytes(hdr) + body + bytes(reclen - data_off - len(body))
    return rec, n


def main():
    rng = random.Random(12345)
    # synthetic 10-bit telemetry: DC level, slow drift, bursts, -1 markers, 1023 spikes
    vals = []
    v = 480
    for i in range(20000):
        v = min(1023, max(0, v + rng.choice([-1, 0, 0, 1]) + (rng.randint(-200, 200) if i % 997 == 0 else 0)))
        r = rng.random()
        vals.append(-1 if r < 0.02 else (1023 if r < 0.021 else v))
    # also a few large jumps for the 30-bit and 15-bit paths
    vals[100] = 600000
    vals[101] = -500000
    vals[102] = 70000
    t0 = dt.datetime(1973, 6, 10, 0, 0, 0, 160037, tzinfo=dt.timezone.utc)
    period_us = 1e6 / 6.625
    # 1) exact round trip, both greedy and format-cycling encoders
    for cyc in (False, True):
        buf = bytearray()
        pos = 0
        seq = 1
        starts = []
        while pos < len(vals):
            st = t0 + dt.timedelta(microseconds=round(pos * period_us))
            rec, n = make_record(vals[pos:], st, seq=seq, rng=rng, force_cycle=cyc)
            starts.append(st)
            buf += rec
            pos += n
            seq += 1
        recs = list(mseed.iter_records(bytes(buf)))
        got = [x for r in recs for x in r.samples]
        assert got == vals, f"round trip mismatch (cycle={cyc})"
        assert all(r.encoding == 11 and r.record_length == 4096 and r.sample_rate == 6.625 for r in recs)
        for r, st in zip(recs, starts):
            exp_ns = int(st.timestamp()) * 1_000_000_000 + st.microsecond * 1000
            assert r.start_ns == exp_ns, (r.start_ns, exp_ns)
        assert (recs[0].network, recs[0].station, recs[0].location, recs[0].channel) == ("XA", "S15", "00", "MHZ")
        # 2) chain assembly
        day0 = int(dt.datetime(1973, 6, 10, tzinfo=dt.timezone.utc).timestamp()) * 1_000_000_000
        out, status, info = mseed.assemble_chain(recs, day0, 6.625)
        assert status == "contiguous" and out == vals, status
        dup = recs[:3] + [recs[1]] + recs[3:]
        out, status, info = mseed.assemble_chain(dup, day0, 6.625)
        assert status == "contiguous" and out == vals and info["dropped_dupes"] == 1
        out, status, _ = mseed.assemble_chain(recs[:2] + recs[3:], day0, 6.625)
        assert out is None and status.startswith("gap_"), status
        prev_day = mseed.Record("XA", "S15", "00", "MHZ", "M", "000000", day0 - 10 ** 9 * 600, 6.625, 50, 11, 4096, [1] * 50)
        out, status, info = mseed.assemble_chain([prev_day] + recs, day0, 6.625)
        assert status == "contiguous" and out == vals and info["dropped_outside"] == 1
        bad = mseed.Record("XA", "S15", "00", "MHZ", "M", "000000", recs[1].start_ns, 6.625,
                           recs[1].nsamples, 11, 4096, [x + 1 for x in recs[1].samples])
        out, status, _ = mseed.assemble_chain(recs + [bad], day0, 6.625)
        assert out is None and status == "conflicting_duplicate", status
    # 3) corrupted Xn must be rejected
    rec, _ = make_record(vals[:3000], t0, rng=rng, bad_xn=True)
    try:
        list(mseed.iter_records(rec))
        raise AssertionError("Xn corruption not detected")
    except mseed.MseedError as exc:
        assert "reverse integration constant" in str(exc)
    # 4) header claiming more samples than frames hold must be rejected
    rec, n = make_record(vals[:500], t0, rng=rng, claim_extra=5)
    try:
        list(mseed.iter_records(rec))
        raise AssertionError("short frames not detected")
    except mseed.MseedError:
        pass
    # 5) non-miniSEED payload (FDSN 'Info:' text) must be rejected
    try:
        list(mseed.iter_records(b"Info: No Data Selected\n" + bytes(100)))
        raise AssertionError("text payload not rejected")
    except mseed.MseedError:
        pass
    print("steim2_selftest_ok values=%d" % len(vals))


if __name__ == "__main__":
    main()
