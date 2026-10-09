"""Pure-standard-library decoder for the DHM hologram TIFFs of Zenodo record 10632465.

Only the exact layout used by Zenodo record 10632465 is accepted:
little-endian classic TIFF, one IFD, 2048 x 2048, BitsPerSample 8,
SamplesPerPixel 1, Compression 5 (LZW), Predictor 2 (horizontal differencing),
PhotometricInterpretation 1 (BlackIsZero), PlanarConfiguration 1, strips.
Anything else raises TiffFormatError so the caller fails hard.
"""

from __future__ import annotations

from itertools import accumulate
import struct

EXPECTED_WIDTH = 2048
EXPECTED_HEIGHT = 2048

TYPE_SIZES = {1: 1, 2: 1, 3: 2, 4: 4, 5: 8, 6: 1, 7: 1, 8: 2, 9: 4, 10: 8, 11: 4, 12: 8}
TYPE_FORMATS = {1: "B", 3: "H", 4: "I", 6: "b", 8: "h", 9: "i"}


class TiffFormatError(ValueError):
    pass


def parse_ifd(data: bytes) -> dict[int, tuple]:
    """Return {tag: tuple(values)} for the first IFD; reject multi-page files."""
    if len(data) < 8 or data[:4] != b"II*\x00":
        raise TiffFormatError("not a little-endian classic TIFF")
    (ifd_offset,) = struct.unpack_from("<I", data, 4)
    if ifd_offset < 8 or ifd_offset + 2 > len(data):
        raise TiffFormatError("IFD offset out of range")
    (count,) = struct.unpack_from("<H", data, ifd_offset)
    end = ifd_offset + 2 + 12 * count
    if end + 4 > len(data):
        raise TiffFormatError("IFD exceeds file")
    tags: dict[int, tuple] = {}
    for i in range(count):
        tag, typ, n, raw = struct.unpack_from("<HHI4s", data, ifd_offset + 2 + 12 * i)
        size = TYPE_SIZES.get(typ)
        if size is None:
            raise TiffFormatError(f"unknown TIFF field type {typ} for tag {tag}")
        total = size * n
        if total <= 4:
            blob = raw[:total]
        else:
            (off,) = struct.unpack("<I", raw)
            if off + total > len(data):
                raise TiffFormatError(f"tag {tag} data out of range")
            blob = data[off : off + total]
        if typ in TYPE_FORMATS:
            values = struct.unpack(f"<{n}{TYPE_FORMATS[typ]}", blob)
        elif typ == 2:
            values = (blob.rstrip(b"\x00").decode("latin-1"),)
        else:
            values = (blob,)
        tags[tag] = values
    (next_ifd,) = struct.unpack_from("<I", data, end)
    if next_ifd != 0:
        raise TiffFormatError("multi-IFD TIFF is not expected")
    return tags


def check_layout(tags: dict[int, tuple]) -> dict[str, object]:
    def one(tag: int, default=None):
        v = tags.get(tag)
        if v is None:
            if default is None:
                raise TiffFormatError(f"missing required tag {tag}")
            return default
        if len(v) != 1:
            raise TiffFormatError(f"tag {tag} has {len(v)} values")
        return v[0]

    width = one(256)
    height = one(257)
    bps = tags.get(258)
    spp = one(277, 1)
    compression = one(259)
    predictor = one(317, 1)
    photometric = one(262)
    planar = one(284, 1)
    if (width, height) != (EXPECTED_WIDTH, EXPECTED_HEIGHT):
        raise TiffFormatError(f"unexpected frame size {width}x{height}")
    if bps != (8,):
        raise TiffFormatError(f"unexpected BitsPerSample {bps}")
    if spp != 1:
        raise TiffFormatError(f"unexpected SamplesPerPixel {spp}")
    if compression != 5:
        raise TiffFormatError(f"unexpected Compression {compression}")
    if predictor != 2:
        raise TiffFormatError(f"unexpected Predictor {predictor}")
    if photometric != 1:
        raise TiffFormatError(f"unexpected PhotometricInterpretation {photometric}")
    if planar != 1:
        raise TiffFormatError(f"unexpected PlanarConfiguration {planar}")
    if 339 in tags and tags[339] != (1,):
        raise TiffFormatError(f"unexpected SampleFormat {tags[339]}")
    if 322 in tags or 323 in tags:
        raise TiffFormatError("tiled TIFF is not expected")
    rows_per_strip = one(278, height)
    offsets = tags.get(273)
    counts = tags.get(279)
    if not offsets or not counts or len(offsets) != len(counts):
        raise TiffFormatError("missing or inconsistent strip tags")
    n_strips = (height + rows_per_strip - 1) // rows_per_strip
    if len(offsets) != n_strips:
        raise TiffFormatError(f"expected {n_strips} strips, found {len(offsets)}")
    return {
        "width": width,
        "height": height,
        "rows_per_strip": rows_per_strip,
        "strip_offsets": offsets,
        "strip_byte_counts": counts,
    }


def lzw_decode(src: bytes, expected: int) -> tuple[bytes, bool]:
    """TIFF LZW (MSB-first codes, ClearCode 256, EOI 257, early change).

    Returns (decoded bytes, legacy_eoi). Decoding stops once ``expected``
    bytes are produced; the next code must then be EOI (optionally preceded by
    a Clear code). ``legacy_eoi`` is True when the encoder wrote that final EOI
    at the pre-increment code width, i.e. it did not widen after its last data
    code filled the table to a width boundary (pre-4.0 libtiff behaviour, seen
    in a few strips of the 2022.06.09 and 2022.10 source files). That fallback is accepted only in
    exactly that situation.
    """
    out = bytearray()
    table: list[bytes] = [bytes((i,)) for i in range(256)] + [b"", b""]
    width = 9
    next_code = 258
    prev: bytes | None = None
    bitbuf = 0
    nbits = 0
    pos = 0
    n = len(src)
    bumped = False

    def read(w: int, state: tuple[int, int, int]) -> tuple[int, tuple[int, int, int]]:
        p, buf, nb = state
        while nb < w:
            if p >= n:
                raise TiffFormatError("LZW stream ended before EOI")
            buf = (buf << 8) | src[p]
            p += 1
            nb += 8
        nb -= w
        return (buf >> nb) & ((1 << w) - 1), (p, buf & ((1 << nb) - 1), nb)

    while len(out) < expected:
        while nbits < width:
            if pos < n:
                bitbuf = (bitbuf << 8) | src[pos]
                pos += 1
                nbits += 8
            else:
                raise TiffFormatError("LZW stream ended before EOI")
        nbits -= width
        code = (bitbuf >> nbits) & ((1 << width) - 1)
        bitbuf &= (1 << nbits) - 1
        if code == 256:
            del table[258:]
            width = 9
            next_code = 258
            prev = None
            bumped = False
            continue
        if code == 257:
            raise TiffFormatError(f"LZW EOI after {len(out)} of {expected} bytes")
        if prev is None:
            if code > 255:
                raise TiffFormatError("LZW first code after clear is not a literal")
            entry = table[code]
        elif code < next_code:
            entry = table[code]
            table.append(prev + entry[:1])
            next_code += 1
        elif code == next_code:
            entry = prev + prev[:1]
            table.append(entry)
            next_code += 1
        else:
            raise TiffFormatError(f"LZW code {code} beyond table size {next_code}")
        out += entry
        prev = entry
        bumped = False
        # Early change: the decoder widens when its table reaches 2**width - 1.
        if next_code + 1 >= (1 << width):
            if width < 12:
                width += 1
                bumped = True
            elif next_code + 1 > 4096:
                raise TiffFormatError("LZW table overflow without clear code")
    if len(out) != expected:
        raise TiffFormatError(f"LZW strip overran: {len(out)} > {expected}")

    state = (pos, bitbuf, nbits)

    def terminator(w: int) -> tuple[int, tuple[int, int, int]]:
        try:
            code, after = read(w, state)
            if code == 256:
                code, after = read(9, after)
        except TiffFormatError:
            return -1, state
        return code, after

    legacy = False
    code, after = terminator(width)
    if code != 257 and bumped:
        code, after = terminator(width - 1)
        legacy = code == 257
    if code != 257:
        raise TiffFormatError(f"LZW strip does not terminate with EOI (got code {code})")
    if n - after[0] > 1:
        raise TiffFormatError(f"LZW strip has {n - after[0]} trailing bytes after EOI")
    return bytes(out), legacy


_AND255 = (255).__and__


def undo_horizontal_predictor(buf: bytes, width: int) -> bytes:
    """Predictor 2 for 8-bit, 1 sample: running sum modulo 256 within each row."""
    if len(buf) % width:
        raise TiffFormatError("predictor buffer is not a whole number of rows")
    out = bytearray(len(buf))
    for r in range(0, len(buf), width):
        out[r : r + width] = bytes(map(_AND255, accumulate(buf[r : r + width])))
    return bytes(out)


def decode_frame(data: bytes) -> tuple[bytes, dict[str, object]]:
    """Decode a whole hologram TIFF to row-major uint8 pixels."""
    tags = parse_ifd(data)
    layout = check_layout(tags)
    width = layout["width"]
    height = layout["height"]
    rps = layout["rows_per_strip"]
    pixels = bytearray()
    legacy_eoi = 0
    for i, (off, cnt) in enumerate(zip(layout["strip_offsets"], layout["strip_byte_counts"])):
        if off + cnt > len(data):
            raise TiffFormatError(f"strip {i} out of range")
        rows = min(rps, height - i * rps)
        raw, legacy = lzw_decode(data[off : off + cnt], rows * width)
        legacy_eoi += legacy
        pixels += undo_horizontal_predictor(raw, width)
    if len(pixels) != width * height:
        raise TiffFormatError("decoded pixel count mismatch")
    meta = {
        "width": width,
        "height": height,
        "rows_per_strip": rps,
        "strips": len(layout["strip_offsets"]),
        "legacy_eoi_strips": legacy_eoi,
        "image_description": tags.get(270, ("",))[0] if 270 in tags else "",
        "software": tags.get(305, ("",))[0] if 305 in tags else "",
        "tags": sorted(tags),
    }
    return bytes(pixels), meta


# ---------------------------------------------------------------------------
# Encoder used only by the self-test (synthetic TIFF round trip).


def lzw_encode(data: bytes, legacy_eoi: bool = False) -> bytes:
    codes: list[tuple[int, int]] = []
    width = 9
    table: dict[bytes, int] = {bytes((i,)): i for i in range(256)}
    next_code = 258
    codes.append((256, width))
    w = b""
    for b in data:
        wc = w + bytes((b,))
        if wc in table:
            w = wc
            continue
        codes.append((table[w], width))
        table[wc] = next_code
        next_code += 1
        if next_code >= (1 << width) and width < 12:
            width += 1
        if next_code >= 4093:
            codes.append((256, width))
            table = {bytes((i,)): i for i in range(256)}
            next_code = 258
            width = 9
        w = bytes((b,))
    if w:
        codes.append((table[w], width))
        next_code += 1
        if not legacy_eoi and next_code >= (1 << width) and width < 12:
            width += 1
    codes.append((257, width))
    out = bytearray()
    acc = 0
    nb = 0
    for code, wd in codes:
        acc = (acc << wd) | code
        nb += wd
        while nb >= 8:
            nb -= 8
            out.append((acc >> nb) & 255)
        acc &= (1 << nb) - 1
    if nb:
        out.append((acc << (8 - nb)) & 255)
    return bytes(out)


def build_synthetic_tiff(
    pixels: bytes, width: int, height: int, rows_per_strip: int, legacy_eoi: bool = False
) -> bytes:
    strips = []
    for r0 in range(0, height, rows_per_strip):
        rows = min(rows_per_strip, height - r0)
        block = pixels[r0 * width : (r0 + rows) * width]
        diff = bytearray(len(block))
        for r in range(rows):
            row = block[r * width : (r + 1) * width]
            prev = 0
            for c, v in enumerate(row):
                diff[r * width + c] = (v - prev) & 255
                prev = v
        strips.append(lzw_encode(bytes(diff), legacy_eoi))
    n = len(strips)
    entries = 12
    ifd_off = 8
    data_off = ifd_off + 2 + 12 * entries + 4
    offs_off = data_off
    cnts_off = offs_off + 4 * n
    strip_data_off = cnts_off + 4 * n
    offsets = []
    cur = strip_data_off
    for s in strips:
        offsets.append(cur)
        cur += len(s)

    def ent(tag, typ, count, value):
        return struct.pack("<HHII", tag, typ, count, value)

    def short(tag, value):
        return struct.pack("<HHIHH", tag, 3, 1, value, 0)

    ifd = struct.pack("<H", entries)
    ifd += ent(256, 4, 1, width)
    ifd += ent(257, 4, 1, height)
    ifd += short(258, 8)
    ifd += short(259, 5)
    ifd += short(262, 1)
    ifd += ent(273, 4, n, offs_off) if n > 1 else ent(273, 4, 1, offsets[0])
    ifd += short(277, 1)
    ifd += ent(278, 4, 1, rows_per_strip)
    ifd += ent(279, 4, n, cnts_off) if n > 1 else ent(279, 4, 1, len(strips[0]))
    ifd += short(284, 1)
    ifd += short(317, 2)
    ifd += short(339, 1)
    ifd += struct.pack("<I", 0)
    body = b"II*\x00" + struct.pack("<I", ifd_off) + ifd
    assert len(body) == data_off
    body += struct.pack(f"<{n}I", *offsets) + struct.pack(f"<{n}I", *(len(s) for s in strips))
    return body + b"".join(strips)
