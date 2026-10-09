#!/usr/bin/env python3
"""Pure-standard-library miniSEED 2 reader with a Steim1/Steim2 decoder.

Adapted from datasets/earthscope_pb_borehole_strain_counts_i32/scripts/mseed.py
(same header/blockette handling and Steim decoder), trimmed to what the
Apollo PSE recipe needs:

* fixed 48-byte data header (station/location/channel/network, BTIME start,
  sample count, sample-rate factor/multiplier, activity flags, time
  correction, data offset, first-blockette offset);
* header byte order detected from the BTIME year/day-of-year plausibility;
* blockette 1000 (encoding, word order, record length exponent) is mandatory;
  blockette 1001 (microsecond offset) is honoured;
* Steim2 (encoding 11) and Steim1 (encoding 10) frames, every record checked
  against its forward (X0) and reverse (Xn) integration constants.

Any structural surprise raises MseedError; callers treat it as fatal.
"""
from __future__ import annotations

import datetime as _dt
import struct
from dataclasses import dataclass, field


class MseedError(ValueError):
    pass


@dataclass
class Record:
    network: str
    station: str
    location: str
    channel: str
    quality: str
    sequence: str
    start_ns: int  # epoch nanoseconds of first sample (corrections applied)
    sample_rate: float
    nsamples: int
    encoding: int
    record_length: int
    samples: list = field(repr=False)


_EPOCH = _dt.datetime(1970, 1, 1, tzinfo=_dt.timezone.utc)


def _btime_ns(year: int, doy: int, hour: int, minute: int, sec: int, tenk: int) -> int:
    if not (1900 <= year <= 2100 and 1 <= doy <= 366 and hour < 24 and minute < 60 and sec <= 60 and tenk < 10000):
        raise MseedError(f"invalid BTIME {year}-{doy} {hour}:{minute}:{sec}.{tenk}")
    day = _dt.datetime(year, 1, 1, tzinfo=_dt.timezone.utc) + _dt.timedelta(days=doy - 1)
    secs = int((day - _EPOCH).total_seconds()) + hour * 3600 + minute * 60 + sec
    return secs * 1_000_000_000 + tenk * 100_000


def _sample_rate(factor: int, mult: int) -> float:
    if factor == 0:
        return 0.0
    rate = float(factor) if factor > 0 else -1.0 / factor
    if mult > 0:
        rate *= mult
    elif mult < 0:
        rate /= -mult
    return rate


def _sign(value: int, bits: int) -> int:
    if value & (1 << (bits - 1)):
        return value - (1 << bits)
    return value


def decode_steim(data: bytes, nsamples: int, encoding: int, word_big_endian: bool) -> list:
    """Decode Steim1 (10) or Steim2 (11) frames into ``nsamples`` ints.

    Raises MseedError if the frames hold fewer differences than ``nsamples``,
    if a Steim2 control/dnib combination is invalid, or if the last
    reconstructed sample differs from the reverse integration constant Xn.
    """
    if encoding not in (10, 11):
        raise MseedError(f"unsupported encoding {encoding}")
    if len(data) % 64:
        data = data[: len(data) - len(data) % 64]
    nframes = len(data) // 64
    if nframes == 0:
        raise MseedError("no Steim frames")
    fmt = ">16I" if word_big_endian else "<16I"
    diffs: list = []
    x0 = xn = None
    need = nsamples
    for f in range(nframes):
        words = struct.unpack_from(fmt, data, f * 64)
        nib = words[0]
        for w in range(1, 16):
            code = (nib >> (30 - 2 * w)) & 3
            word = words[w]
            if f == 0 and w == 1:
                x0 = _sign(word, 32)
                continue
            if f == 0 and w == 2:
                xn = _sign(word, 32)
                continue
            if code == 0:
                continue
            if encoding == 10:
                if code == 1:
                    diffs.extend(_sign((word >> s) & 0xFF, 8) for s in (24, 16, 8, 0))
                elif code == 2:
                    diffs.append(_sign(word >> 16, 16))
                    diffs.append(_sign(word & 0xFFFF, 16))
                else:
                    diffs.append(_sign(word, 32))
                continue
            # Steim2
            if code == 1:
                diffs.extend(_sign((word >> s) & 0xFF, 8) for s in (24, 16, 8, 0))
                continue
            dnib = word >> 30
            if code == 2:
                if dnib == 1:
                    diffs.append(_sign(word & 0x3FFFFFFF, 30))
                elif dnib == 2:
                    diffs.append(_sign((word >> 15) & 0x7FFF, 15))
                    diffs.append(_sign(word & 0x7FFF, 15))
                elif dnib == 3:
                    diffs.append(_sign((word >> 20) & 0x3FF, 10))
                    diffs.append(_sign((word >> 10) & 0x3FF, 10))
                    diffs.append(_sign(word & 0x3FF, 10))
                else:
                    raise MseedError("Steim2 code 2 with dnib 0")
            else:  # code 3
                if dnib == 0:
                    diffs.extend(_sign((word >> s) & 0x3F, 6) for s in (24, 18, 12, 6, 0))
                elif dnib == 1:
                    diffs.extend(_sign((word >> s) & 0x1F, 5) for s in (25, 20, 15, 10, 5, 0))
                elif dnib == 2:
                    diffs.extend(_sign((word >> s) & 0xF, 4) for s in (24, 20, 16, 12, 8, 4, 0))
                else:
                    raise MseedError("Steim2 code 3 with dnib 3")
        if len(diffs) >= need:
            break
    if x0 is None or xn is None:
        raise MseedError("missing integration constants")
    if len(diffs) < need:
        raise MseedError(f"Steim frames hold {len(diffs)} differences, header says {need}")
    out = [0] * need
    if need:
        acc = x0
        out[0] = acc
        for i in range(1, need):
            acc += diffs[i]
            out[i] = acc
        if acc != xn:
            raise MseedError(f"reverse integration constant mismatch: last={acc} Xn={xn}")
    return out


def iter_records(buf: bytes, decode: bool = True):
    """Yield Record objects from a buffer holding concatenated miniSEED 2 records."""
    pos = 0
    n = len(buf)
    while pos < n:
        if n - pos < 48:
            raise MseedError(f"trailing {n - pos} bytes at offset {pos}")
        hdr = buf[pos: pos + 48]
        seq = hdr[0:6]
        if any(c not in b"0123456789 \x00" for c in seq):
            raise MseedError(f"bad sequence number at offset {pos}: {seq!r}")
        quality = chr(hdr[6])
        if quality not in "DRQM":
            raise MseedError(f"bad quality indicator {quality!r} at offset {pos}")
        be = None
        for endian in (">", "<"):
            year, doy = struct.unpack_from(endian + "HH", hdr, 20)
            if 1900 <= year <= 2100 and 1 <= doy <= 366:
                be = endian
                break
        if be is None:
            raise MseedError(f"cannot determine header byte order at offset {pos}")
        (year, doy, hour, minute, sec, _unused, tenk, nsamp, factor, mult, act, _io, _dq, nblk,
         tcorr, data_off, blk_off) = struct.unpack_from(be + "HHBBBBHHhhBBBBiHH", hdr, 20)
        station = hdr[8:13].decode("ascii").strip()
        location = hdr[13:15].decode("ascii").strip()
        channel = hdr[15:18].decode("ascii").strip()
        network = hdr[18:20].decode("ascii").strip()
        start_ns = _btime_ns(year, doy, hour, minute, sec, tenk)
        if tcorr and not (act & 0x02):
            start_ns += tcorr * 100_000
        encoding = word_order = reclen = None
        boff = blk_off
        seen = 0
        while boff and seen < max(nblk, 1) + 8:
            if boff + 4 > 65536 or pos + boff + 4 > n:
                raise MseedError(f"blockette offset {boff} out of range at offset {pos}")
            btype, bnext = struct.unpack_from(be + "HH", buf, pos + boff)
            if btype == 1000:
                encoding, word_order, rexp = struct.unpack_from("BBB", buf, pos + boff + 4)
                reclen = 1 << rexp
            elif btype == 1001:
                usec = struct.unpack_from("b", buf, pos + boff + 5)[0]
                start_ns += usec * 1000
            seen += 1
            if bnext and bnext <= boff:
                raise MseedError("blockette chain loops")
            boff = bnext
        if reclen is None:
            raise MseedError(f"record at offset {pos} has no blockette 1000")
        if not (256 <= reclen <= 65536) or pos + reclen > n:
            raise MseedError(f"bad record length {reclen} at offset {pos}")
        if data_off < 48 or data_off > reclen:
            raise MseedError(f"bad data offset {data_off} at offset {pos}")
        samples = []
        if decode and nsamp:
            data = buf[pos + data_off: pos + reclen]
            if encoding in (10, 11):
                samples = decode_steim(data, nsamp, encoding, word_order == 1)
            else:
                raise MseedError(f"unsupported data encoding {encoding}")
        yield Record(network, station, location, channel, quality, seq.decode("ascii", "replace"),
                     start_ns, _sample_rate(factor, mult), nsamp, encoding, reclen, samples)
        pos += reclen


def assemble_chain(records, day_start_ns: int, rate: float, tol_samples: float = 1.0):
    """Concatenate one channel's records of one UTC day in time order.

    Records are assigned to the day of their (rounded) start time: a record is
    kept when day_start - P/2 <= start < day_start + 86400 s - P/2 (P = sample
    period); dataselect may return a neighbouring day's record that merely
    overlaps the window, and such records are dropped (counted). Records are
    sorted by (start, nsamples); exact duplicates (same start, same samples)
    are dropped. Every following record must start within ``tol_samples``
    periods of the previous record's nominal end; otherwise the day has a gap
    (positive) or an overlap (negative) and is rejected (no splicing, no fill).

    Returns (values|None, status, info) where info = dict(records, dropped_dupes,
    dropped_outside, max_abs_chain_dev).
    """
    period = 1e9 / rate
    day_end_ns = day_start_ns + 86400 * 1_000_000_000
    half = period / 2
    info = {"records": 0, "dropped_dupes": 0, "dropped_outside": 0, "max_abs_chain_dev": 0.0}
    recs = []
    for r in records:
        if r.nsamples <= 0:
            continue
        if abs(r.sample_rate - rate) > 1e-9:
            return None, f"rate_{r.sample_rate}", info
        if not (day_start_ns - half <= r.start_ns < day_end_ns - half):
            info["dropped_outside"] += 1
            continue
        recs.append(r)
    if not recs:
        return None, "no_data", info
    recs.sort(key=lambda r: (r.start_ns, r.nsamples))
    dedup = []
    for r in recs:
        if dedup and dedup[-1].start_ns == r.start_ns:
            if dedup[-1].samples == r.samples:
                info["dropped_dupes"] += 1
                continue
            return None, "conflicting_duplicate", info
        dedup.append(r)
    info["records"] = len(dedup)
    out = list(dedup[0].samples)
    for a, b in zip(dedup, dedup[1:]):
        dev = (b.start_ns - a.start_ns - a.nsamples * period) / period
        info["max_abs_chain_dev"] = max(info["max_abs_chain_dev"], abs(dev))
        if dev > tol_samples:
            return None, f"gap_{dev:.1f}_samples", info
        if dev < -tol_samples:
            return None, f"overlap_{-dev:.1f}_samples", info
        out.extend(b.samples)
    info["max_abs_chain_dev"] = round(info["max_abs_chain_dev"], 4)
    return out, "contiguous", info
