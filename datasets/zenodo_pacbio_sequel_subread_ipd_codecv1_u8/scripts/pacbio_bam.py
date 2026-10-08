"""Pure-stdlib BGZF/BAM reader for a byte-range prefix of a PacBio subreads BAM.

Used by build.sh (verify.sh has its own independent implementation).

BGZF: concatenated gzip members whose FEXTRA field carries a 'BC' subfield
with BSIZE (total member size - 1). Each member is inflated with raw deflate
and checked against its CRC32 and ISIZE trailer. The first member that does
not fit inside the prefix ends the walk.

BAM: magic 'BAM\\1', l_text, header text, n_ref, references, then records:
block_size(int32) + 32-byte fixed core + read_name + cigar + 4-bit seq +
qual + aux tags. A record that is not complete inside the decompressed
stream (the prefix tail) is dropped.
"""
from __future__ import annotations

import struct
import zlib
from typing import Iterator

BAM_MAGIC = b"BAM\x01"
CORE = struct.Struct("<iiBBHHHiiii")  # 32 bytes after block_size
AUX_FIXED = {"A": 1, "c": 1, "C": 1, "s": 2, "S": 2, "i": 4, "I": 4, "f": 4}
B_SUBTYPE_SIZE = {"c": 1, "C": 1, "s": 2, "S": 2, "i": 4, "I": 4, "f": 4}
MAX_RECORD_BYTES = 64 * 1024 * 1024


def iter_bgzf_payloads(data: bytes | memoryview) -> Iterator[tuple[int, bytes]]:
    """Yield (member_offset, inflated_payload) for each complete BGZF member."""
    mv = memoryview(data)
    n = len(mv)
    off = 0
    while off + 18 <= n:
        if mv[off] != 0x1F or mv[off + 1] != 0x8B or mv[off + 2] != 8 or not (mv[off + 3] & 4):
            raise ValueError(f"bad BGZF member header at offset {off}")
        xlen = struct.unpack_from("<H", mv, off + 10)[0]
        if off + 12 + xlen > n:
            return
        bsize = None
        x = off + 12
        xend = x + xlen
        while x + 4 <= xend:
            si1, si2, slen = mv[x], mv[x + 1], struct.unpack_from("<H", mv, x + 2)[0]
            if si1 == 66 and si2 == 67 and slen == 2:
                bsize = struct.unpack_from("<H", mv, x + 4)[0]
            x += 4 + slen
        if bsize is None:
            raise ValueError(f"BGZF member at {off} lacks BC subfield")
        total = bsize + 1
        if off + total > n:
            return  # truncated final member of the prefix
        cdata = mv[off + 12 + xlen : off + total - 8]
        crc, isize = struct.unpack_from("<II", mv, off + total - 8)
        payload = zlib.decompress(cdata, -15)
        if len(payload) != isize or (zlib.crc32(payload) & 0xFFFFFFFF) != crc:
            raise ValueError(f"BGZF member at {off} failed CRC/ISIZE check")
        yield off, payload
        off += total


def parse_aux(aux: bytes | memoryview) -> dict[str, tuple[str, object]]:
    """Parse BAM aux fields into {tag: (type, value)}.

    B arrays are returned as (\"B\" + subtype, raw little-endian bytes)."""
    mv = memoryview(aux)
    n = len(mv)
    out: dict[str, tuple[str, object]] = {}
    p = 0
    while p < n:
        if p + 3 > n:
            raise ValueError("truncated aux tag header")
        tag = bytes(mv[p : p + 2]).decode("ascii")
        typ = chr(mv[p + 2])
        p += 3
        if typ in AUX_FIXED:
            size = AUX_FIXED[typ]
            if p + size > n:
                raise ValueError(f"truncated aux value {tag}:{typ}")
            raw = bytes(mv[p : p + size])
            if typ == "A":
                val: object = raw.decode("ascii")
            elif typ == "f":
                val = struct.unpack("<f", raw)[0]
            else:
                val = int.from_bytes(raw, "little", signed=typ in "csi")
            p += size
        elif typ in ("Z", "H"):
            end = bytes(mv[p:]).find(b"\x00")
            if end < 0:
                raise ValueError(f"unterminated aux string {tag}:{typ}")
            val = bytes(mv[p : p + end]).decode("ascii")
            p += end + 1
        elif typ == "B":
            if p + 5 > n:
                raise ValueError(f"truncated aux array header {tag}")
            sub = chr(mv[p])
            if sub not in B_SUBTYPE_SIZE:
                raise ValueError(f"bad B subtype {sub!r} for {tag}")
            count = struct.unpack_from("<I", mv, p + 1)[0]
            p += 5
            size = count * B_SUBTYPE_SIZE[sub]
            if p + size > n:
                raise ValueError(f"truncated aux array {tag}")
            val = bytes(mv[p : p + size])
            typ = "B" + sub
            p += size
        else:
            raise ValueError(f"unknown aux type {typ!r} for tag {tag}")
        if tag in out:
            raise ValueError(f"duplicate aux tag {tag}")
        out[tag] = (typ, val)
    return out


class BamPrefixReader:
    """Streams header and complete records from a BAM byte-range prefix."""

    def __init__(self, data: bytes | memoryview):
        self._members = iter_bgzf_payloads(data)
        self._buf = bytearray()
        self._pos = 0
        self.members_used = 0
        self.header_text = ""
        self.references: list[tuple[str, int]] = []
        self.leftover_bytes = 0

    def _fill(self, need: int) -> bool:
        while len(self._buf) - self._pos < need:
            try:
                _, payload = next(self._members)
            except StopIteration:
                return False
            self.members_used += 1
            if self._pos > (1 << 22):
                del self._buf[: self._pos]
                self._pos = 0
            self._buf += payload
        return True

    def _take(self, size: int) -> bytes:
        if not self._fill(size):
            raise ValueError("BAM header truncated inside prefix")
        out = bytes(self._buf[self._pos : self._pos + size])
        self._pos += size
        return out

    def read_header(self) -> str:
        if self._take(4) != BAM_MAGIC:
            raise ValueError("not a BAM stream (bad magic)")
        l_text = struct.unpack("<i", self._take(4))[0]
        self.header_text = self._take(l_text).split(b"\x00", 1)[0].decode("ascii")
        n_ref = struct.unpack("<i", self._take(4))[0]
        for _ in range(n_ref):
            l_name = struct.unpack("<i", self._take(4))[0]
            name = self._take(l_name).rstrip(b"\x00").decode("ascii")
            l_ref = struct.unpack("<i", self._take(4))[0]
            self.references.append((name, l_ref))
        return self.header_text

    def records(self) -> Iterator[dict]:
        """Yield complete records: name, flag, l_seq, aux (parsed)."""
        while True:
            if not self._fill(4):
                break
            block_size = struct.unpack_from("<i", self._buf, self._pos)[0]
            if block_size < 32 or block_size > MAX_RECORD_BYTES:
                raise ValueError(f"implausible BAM block_size {block_size}")
            if not self._fill(4 + block_size):
                break  # truncated final record of the prefix
            start = self._pos + 4
            body = memoryview(self._buf)[start : start + block_size]
            (ref_id, pos, l_name, mapq, _bin, n_cigar, flag, l_seq, _nref, _npos, _tlen) = CORE.unpack_from(body, 0)
            p = 32
            name = bytes(body[p : p + l_name]).rstrip(b"\x00").decode("ascii")
            p += l_name + 4 * n_cigar + (l_seq + 1) // 2 + l_seq
            if p > block_size:
                body.release()
                raise ValueError(f"record {name} overruns its block")
            aux = parse_aux(body[p:])
            body.release()
            self._pos = start + block_size
            yield {"name": name, "flag": flag, "ref_id": ref_id, "pos": pos, "mapq": mapq, "l_seq": l_seq, "aux": aux}
        self.leftover_bytes = len(self._buf) - self._pos


# --- synthetic encoders used only by the self-test -------------------------


def encode_aux(fields: list[tuple[str, str, object]]) -> bytes:
    out = bytearray()
    for tag, typ, val in fields:
        out += tag.encode("ascii")
        if typ.startswith("B"):
            sub = typ[1]
            vals = list(val)  # type: ignore[arg-type]
            out += b"B" + sub.encode() + struct.pack("<I", len(vals))
            fmt = {"c": "b", "C": "B", "s": "h", "S": "H", "i": "i", "I": "I", "f": "f"}[sub]
            out += struct.pack("<" + fmt * len(vals), *vals)
            continue
        out += typ.encode("ascii")
        if typ == "A":
            out += str(val).encode("ascii")
        elif typ in ("Z", "H"):
            out += str(val).encode("ascii") + b"\x00"
        elif typ == "f":
            out += struct.pack("<f", val)
        else:
            fmt = {"c": "b", "C": "B", "s": "h", "S": "H", "i": "i", "I": "I"}[typ]
            out += struct.pack("<" + fmt, val)
    return bytes(out)


def encode_record(name: str, seq_len: int, aux: bytes, flag: int = 4) -> bytes:
    rn = name.encode("ascii") + b"\x00"
    body = CORE.pack(-1, -1, len(rn), 255, 4680, 0, flag, seq_len, -1, -1, 0)
    body += rn + bytes((seq_len + 1) // 2) + bytes([255]) * seq_len + aux
    return struct.pack("<i", len(body)) + body


def bgzf_compress(payload: bytes, block: int = 65280) -> bytes:
    out = bytearray()
    for i in range(0, max(1, len(payload)), block):
        chunk = payload[i : i + block]
        co = zlib.compressobj(6, zlib.DEFLATED, -15)
        cdata = co.compress(chunk) + co.flush()
        bsize = 12 + 6 + len(cdata) + 8 - 1
        out += b"\x1f\x8b\x08\x04" + bytes(4) + b"\x00\xff" + struct.pack("<H", 6)
        out += b"BC" + struct.pack("<HH", 2, bsize) + cdata
        out += struct.pack("<II", zlib.crc32(chunk) & 0xFFFFFFFF, len(chunk))
    return bytes(out)
