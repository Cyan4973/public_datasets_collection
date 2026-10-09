#!/usr/bin/env python3
"""Pure-standard-library miniSEED 2 reader with a Steim1/Steim2 decoder.

Only what the PB strainmeter recipe needs:

* fixed 48-byte data header (station/location/channel/network, BTIME start,
  sample count, sample-rate factor/multiplier, activity flags, time correction,
  data offset, first-blockette offset);
* header byte order detected from the BTIME year/day-of-year plausibility;
* blockette 1000 (encoding, word order, record length exponent) is mandatory,
  so 512-byte and any other power-of-two record lengths are handled; blockette
  1001 (microsecond offset) is honoured;
* Steim2 (encoding 11) and Steim1 (encoding 10) frames, with every record
  checked against its forward (X0) and reverse (Xn) integration constants.

Any structural surprise raises MseedError; callers decide whether that is
fatal (download/build/verify treat it as fatal).
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

    Raises MseedError if the frames hold fewer differences than ``nsamples``
    or if the last reconstructed sample differs from the reverse integration
    constant Xn of frame 0.
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
        hdr = buf[pos : pos + 48]
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
            if boff + 4 > 4096 or pos + boff + 4 > n:
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
            data = buf[pos + data_off : pos + reclen]
            if encoding in (10, 11):
                samples = decode_steim(data, nsamp, encoding, word_order == 1)
            elif encoding == 3:  # 32-bit integers
                e = ">" if word_order == 1 else "<"
                if 4 * nsamp > len(data):
                    raise MseedError("int32 payload shorter than sample count")
                samples = list(struct.unpack_from(f"{e}{nsamp}i", data, 0))
            else:
                raise MseedError(f"unsupported data encoding {encoding}")
        yield Record(network, station, location, channel, quality, start_ns,
                     _sample_rate(factor, mult), nsamp, encoding, reclen, samples)
        pos += reclen


def assemble_day(records, day_start_ns: int, rate: float = 1.0):
    """Assemble one channel's records into a gap-free day.

    Returns (values, status). ``values`` is a list of exactly 86400*rate ints
    when status == "complete"; otherwise values is None and status names the
    defect (no_data, gap, overlap, off_lattice, rate, short, ...).
    Exact duplicate records (same start, same samples) are dropped; any other
    overlap or any gap rejects the whole day (no splicing, no fill).
    """
    period_ns = int(round(1e9 / rate))
    nday = int(round(86400 * rate))
    day_end_ns = day_start_ns + nday * period_ns
    recs = [r for r in records if r.nsamples > 0]
    if not recs:
        return None, "no_data"
    for r in recs:
        if abs(r.sample_rate - rate) > 1e-9:
            return None, f"rate_{r.sample_rate}"
    recs.sort(key=lambda r: (r.start_ns, r.nsamples))
    dedup = []
    for r in recs:
        if dedup and dedup[-1].start_ns == r.start_ns and dedup[-1].samples == r.samples:
            continue
        dedup.append(r)
    out = [None] * nday
    filled = 0
    tol = period_ns // 20  # 5% of a sample period
    for r in dedup:
        rel = r.start_ns - day_start_ns
        idx0 = (rel + period_ns // 2) // period_ns
        if abs(rel - idx0 * period_ns) > tol:
            return None, "off_lattice"
        for k, v in enumerate(r.samples):
            idx = idx0 + k
            if idx < 0 or idx >= nday:
                continue
            if out[idx] is not None:
                if out[idx] != v:
                    return None, "overlap_conflict"
                continue
            out[idx] = v
            filled += 1
    if filled != nday:
        return None, f"gap_{nday - filled}_missing"
    return out, "complete"
