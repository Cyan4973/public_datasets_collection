#!/usr/bin/env python3
"""Self-test of scripts/mseed.py on synthetic miniSEED 2 DWWSSN records.

An independent encoder below writes 4096-byte miniSEED 2 data records
(fixed header + blockette 1000 [+ blockette 1001]) with encoding 32 (DWWSSN,
signed 16-bit samples) in big- or little-endian word order, then checks that
the reader recovers stream identity, start time, sample rate and every sample
(including the int16 extremes -32768 and 32767), that chain assembly accepts a
contiguous day, drops exact duplicates and rejects gaps, overlaps and
conflicting duplicates, and that truncated payloads, a missing blockette 1000
and a non-DWWSSN encoding are rejected.
"""
from __future__ import annotations

import datetime as dt
import random
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import mseed  # noqa: E402

RECLEN = 4096
DATA_OFF = 64


def make_record(seq, sta, cha, net, start: dt.datetime, samples, *, enc=32, word_be=True,
                hdr_be=True, usec=None, with_b1000=True, rate_factor=1, rate_mult=1):
    e = ">" if hdr_be else "<"
    doy = start.timetuple().tm_yday
    nblk = (1 if with_b1000 else 0) + (1 if usec is not None else 0)
    hdr = bytearray(RECLEN)
    hdr[0:6] = f"{seq:06d}".encode()
    hdr[6:7] = b"M"
    hdr[7:8] = b" "
    hdr[8:13] = sta.ljust(5).encode()
    hdr[13:15] = b"  "
    hdr[15:18] = cha.encode()
    hdr[18:20] = net.ljust(2).encode()
    tenk = start.microsecond // 100
    struct.pack_into(e + "HHBBBBHHhhBBBBiHH", hdr, 20, start.year, doy, start.hour, start.minute,
                     start.second, 0, tenk, len(samples), rate_factor, rate_mult, 0, 0, 0, nblk, 0,
                     DATA_OFF, 48 if nblk else 0)
    off = 48
    if with_b1000:
        nxt = 56 if usec is not None else 0
        struct.pack_into(e + "HHBBBB", hdr, off, 1000, nxt, enc, 1 if word_be else 0, 12, 0)
        off = 56
    if usec is not None:
        struct.pack_into(e + "HHbbBB", hdr, off, 1001, 0, 0, usec, 0, 0)
    struct.pack_into((">" if word_be else "<") + f"{len(samples)}h", hdr, DATA_OFF, *samples)
    return bytes(hdr)


def expect_error(fn, what):
    try:
        fn()
    except mseed.MseedError:
        return
    raise SystemExit(f"selftest: {what} was not rejected")


def main():
    rng = random.Random(20261014)
    per = (RECLEN - DATA_OFF) // 2  # 2016 samples per record
    day = dt.datetime(1985, 1, 1, tzinfo=dt.timezone.utc)
    day_ns = int(day.timestamp()) * 10 ** 9
    values = [rng.randint(-32768, 32767) for _ in range(5000)]
    values[0], values[1], values[2] = -32768, 32767, 0
    chunks = [values[i:i + per] for i in range(0, len(values), per)]
    for word_be in (True, False):
        for hdr_be in (True, False):
            recs = b""
            t = day
            for k, c in enumerate(chunks):
                recs += make_record(k + 1, "AFI", "LHZ", "DW", t, c, word_be=word_be, hdr_be=hdr_be)
                t += dt.timedelta(seconds=len(c))
            got = list(mseed.iter_records(recs))
            if [r.samples for r in got] != chunks:
                raise SystemExit(f"selftest: samples differ (word_be={word_be}, hdr_be={hdr_be})")
            r0 = got[0]
            if (r0.network, r0.station, r0.location, r0.channel, r0.encoding, r0.sample_rate, r0.record_length) != \
                    ("DW", "AFI", "", "LHZ", 32, 1.0, 4096):
                raise SystemExit(f"selftest: header fields wrong: {r0}")
            if got[1].start_ns != day_ns + len(chunks[0]) * 10 ** 9:
                raise SystemExit("selftest: start time wrong")
            vals, status, info = mseed.assemble_chain(got, day_ns, 1.0)
            if status != "contiguous" or vals != values or info["records"] != len(chunks):
                raise SystemExit(f"selftest: chain assembly failed ({status})")
            # shuffled order + exact duplicate is accepted
            vals, status, info = mseed.assemble_chain([got[2], got[0], got[1], got[0]], day_ns, 1.0)
            if status != "contiguous" or vals != values or info["dropped_dupes"] != 1:
                raise SystemExit(f"selftest: dedup/sort failed ({status})")
    # blockette 1001 microseconds and BTIME 1/10000 s
    r = next(mseed.iter_records(make_record(1, "TOL", "LHZ", "DW",
                                            day + dt.timedelta(seconds=10, microseconds=300), [1, 2, 3], usec=-7)))
    if r.start_ns != day_ns + 10 * 10 ** 9 + 300_000 - 7_000 or r.samples != [1, 2, 3]:
        raise SystemExit("selftest: blockette 1001 / tenk handling wrong")
    # gap, overlap, conflicting duplicate
    a = make_record(1, "AFI", "LHZ", "DW", day, [5] * 100)
    b_gap = make_record(2, "AFI", "LHZ", "DW", day + dt.timedelta(seconds=103), [6] * 100)
    b_ovl = make_record(2, "AFI", "LHZ", "DW", day + dt.timedelta(seconds=97), [6] * 100)
    a_conf = make_record(3, "AFI", "LHZ", "DW", day, [7] * 100)
    for buf, want in ((a + b_gap, "gap_"), (a + b_ovl, "overlap_"), (a + a_conf, "conflicting_duplicate")):
        _, status, _ = mseed.assemble_chain(list(mseed.iter_records(buf)), day_ns, 1.0)
        if not status.startswith(want):
            raise SystemExit(f"selftest: expected {want}, got {status}")
    # record outside the day is dropped; wrong rate is reported
    nxt = make_record(4, "AFI", "LHZ", "DW", day + dt.timedelta(days=1), [1] * 10)
    _, status, info = mseed.assemble_chain(list(mseed.iter_records(a + nxt)), day_ns, 1.0)
    if status != "contiguous" or info["dropped_outside"] != 1:
        raise SystemExit("selftest: out-of-day record not dropped")
    fast = make_record(5, "AFI", "LHZ", "DW", day, [1] * 10, rate_factor=20)
    _, status, _ = mseed.assemble_chain(list(mseed.iter_records(fast)), day_ns, 1.0)
    if not status.startswith("rate_"):
        raise SystemExit("selftest: wrong rate not reported")
    # structural rejections
    expect_error(lambda: list(mseed.iter_records(make_record(1, "AFI", "LHZ", "DW", day, [1] * 10, enc=11))),
                 "non-DWWSSN encoding")
    expect_error(lambda: list(mseed.iter_records(make_record(1, "AFI", "LHZ", "DW", day, [1] * 10, with_b1000=False))),
                 "missing blockette 1000")
    over = bytearray(make_record(1, "AFI", "LHZ", "DW", day, [1] * 10))
    struct.pack_into(">H", over, 30, per + 1)  # header claims more samples than fit
    expect_error(lambda: list(mseed.iter_records(bytes(over))), "truncated payload")
    expect_error(lambda: list(mseed.iter_records(a[:2048])), "short record")
    bad = bytearray(a)
    bad[6:7] = b"X"
    expect_error(lambda: list(mseed.iter_records(bytes(bad))), "bad quality byte")
    print("selftest_mseed ok")


if __name__ == "__main__":
    main()
