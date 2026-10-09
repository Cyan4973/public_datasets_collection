"""Pure-stdlib reader for HDR+ burst DNG files.

Provides:
  * parse_tiff_ifd0(buf)    -- little/big-endian TIFF IFD0 tag dictionary
  * dng_raw_info(tags)       -- validated description of the CFA raw IFD
  * decode_lj92(buf)         -- ITU-T T.81 lossless JPEG (SOF3) decoder:
                                Huffman, predictors 1-7, point transform,
                                any component count with H=V=1, restart markers
  * decode_dng_cfa(buf)      -- full-resolution CFA mosaic as array('H'),
                                row-major, tiles reassembled and cropped to
                                ImageWidth x ImageLength, no black subtraction
  * encode_lj92(...)         -- tiny reference encoder used only by self-tests

No third-party dependencies (numpy/rawpy are not available).
"""
from __future__ import annotations

import struct
import sys
from array import array

TYPE_SIZES = {1: 1, 2: 1, 3: 2, 4: 4, 5: 8, 6: 1, 7: 1, 8: 2, 9: 4, 10: 8, 11: 4, 12: 8, 13: 4, 16: 8}


class DngError(ValueError):
    pass


# --------------------------------------------------------------------------
# TIFF / DNG container
# --------------------------------------------------------------------------

def parse_tiff_ifd0(buf: bytes, allow_truncated: bool = False) -> dict:
    """Return {tag: value} for IFD0. Integer/rational arrays become tuples,
    ASCII becomes str, BYTE/UNDEFINED become bytes. With allow_truncated,
    values lying beyond the buffer are recorded as None instead of failing."""
    if len(buf) < 8:
        raise DngError("buffer too small for TIFF header")
    if buf[:2] == b"II":
        bo = "<"
    elif buf[:2] == b"MM":
        bo = ">"
    else:
        raise DngError("not a TIFF/DNG (bad byte-order mark)")
    if struct.unpack_from(bo + "H", buf, 2)[0] != 42:
        raise DngError("not a TIFF/DNG (bad magic)")
    off = struct.unpack_from(bo + "I", buf, 4)[0]
    if off + 2 > len(buf):
        raise DngError("IFD0 outside buffer")
    n = struct.unpack_from(bo + "H", buf, off)[0]
    if off + 2 + 12 * n + 4 > len(buf):
        raise DngError("IFD0 entries outside buffer")
    tags: dict = {}
    for i in range(n):
        ent = off + 2 + 12 * i
        tag, typ, cnt = struct.unpack_from(bo + "HHI", buf, ent)
        size = TYPE_SIZES.get(typ, 1) * cnt
        voff = ent + 8 if size <= 4 else struct.unpack_from(bo + "I", buf, ent + 8)[0]
        if voff + size > len(buf):
            if allow_truncated:
                tags[tag] = None
                continue
            raise DngError(f"tag {tag} value outside buffer")
        raw = buf[voff:voff + size]
        if typ == 2:
            val = raw.split(b"\0", 1)[0].decode("latin-1")
        elif typ in (1, 7):
            val = bytes(raw)
        elif typ == 6:
            val = struct.unpack(f"{bo}{cnt}b", raw)
        elif typ == 3:
            val = struct.unpack(f"{bo}{cnt}H", raw)
        elif typ == 8:
            val = struct.unpack(f"{bo}{cnt}h", raw)
        elif typ in (4, 13):
            val = struct.unpack(f"{bo}{cnt}I", raw)
        elif typ == 9:
            val = struct.unpack(f"{bo}{cnt}i", raw)
        elif typ == 5:
            v = struct.unpack(f"{bo}{2 * cnt}I", raw)
            val = tuple((v[2 * k], v[2 * k + 1]) for k in range(cnt))
        elif typ == 10:
            v = struct.unpack(f"{bo}{2 * cnt}i", raw)
            val = tuple((v[2 * k], v[2 * k + 1]) for k in range(cnt))
        elif typ == 11:
            val = struct.unpack(f"{bo}{cnt}f", raw)
        elif typ == 12:
            val = struct.unpack(f"{bo}{cnt}d", raw)
        else:
            val = bytes(raw)
        tags[tag] = val
    tags["_byte_order"] = bo
    tags["_next_ifd"] = struct.unpack_from(bo + "I", buf, off + 2 + 12 * n)[0]
    return tags


def _one(tags: dict, tag: int, default=None):
    v = tags.get(tag, default)
    if isinstance(v, tuple) and len(v) == 1:
        return v[0]
    return v


CFA_NAMES = {0: "R", 1: "G", 2: "B"}


def dng_raw_info(tags: dict) -> dict:
    """Summarise and validate the raw CFA IFD (IFD0 in HDR+ DNGs)."""
    info = {
        "make": tags.get(271),
        "model": tags.get(272),
        "unique_camera_model": tags.get(50708),
        "new_subfile_type": _one(tags, 254, 0),
        "width": _one(tags, 256),
        "height": _one(tags, 257),
        "bits_per_sample": _one(tags, 258),
        "compression": _one(tags, 259),
        "photometric": _one(tags, 262),
        "samples_per_pixel": _one(tags, 277, 1),
        "planar": _one(tags, 284, 1),
        "orientation": _one(tags, 274, 1),
        "tile_width": _one(tags, 322),
        "tile_length": _one(tags, 323),
        "white_level": _one(tags, 50717),
        "has_linearization_table": 50712 in tags,
        "has_subifds": 330 in tags,
        "datetime": tags.get(306),
    }
    cfa_dim = tags.get(33421)
    cfa_pat = tags.get(33422)
    info["cfa_repeat"] = list(cfa_dim) if cfa_dim else None
    info["cfa_pattern"] = "".join(CFA_NAMES.get(b, "?") for b in cfa_pat) if isinstance(cfa_pat, bytes) else None
    bl = tags.get(50714)
    if bl:
        info["black_level"] = [round(a / b, 4) if b else None for a, b in bl] if isinstance(bl[0], tuple) else list(bl)
    else:
        info["black_level"] = None
    offs = tags.get(324)
    cnts = tags.get(325)
    info["tile_count"] = len(offs) if offs else 0
    info["tile_offsets"] = list(offs) if offs else None
    info["tile_byte_counts"] = list(cnts) if cnts else None
    return info


PIXEL_MODELS = {"sailfish": "pixel", "Pixel": "pixel", "marlin": "pixel_xl", "Pixel XL": "pixel_xl"}


def check_pixel_cfa(info: dict) -> None:
    """Raise DngError unless the IFD is the full-res 10-bit Pixel/Pixel XL
    lossless-JPEG CFA raw this recipe collects."""
    want = {
        "new_subfile_type": 0,
        "width": 4048,
        "height": 3036,
        "bits_per_sample": 16,
        "compression": 7,
        "photometric": 32803,
        "samples_per_pixel": 1,
        "planar": 1,
        "tile_width": 256,
        "tile_length": 256,
        "white_level": 1023,
        "tile_count": 192,
        "has_linearization_table": False,
        "has_subifds": False,
        "cfa_repeat": [2, 2],
    }
    if str(info.get("make") or "").lower() != "google":
        raise DngError(f"make={info.get('make')!r} (want google)")
    for k, v in want.items():
        if info.get(k) != v:
            raise DngError(f"{k}={info.get(k)!r} (want {v!r})")
    # Pixel = sailfish, Pixel XL = marlin; later HDR+ firmware writes the
    # retail names. Both share the Sony IMX378 4048x3036 active array.
    if info.get("model") not in PIXEL_MODELS:
        raise DngError(f"model={info.get('model')!r} (want one of {sorted(PIXEL_MODELS)})")
    # One CFA lattice for the whole family (every Pixel burst probed is BGGR).
    if info.get("cfa_pattern") != "BGGR":
        raise DngError(f"cfa_pattern={info.get('cfa_pattern')!r} (want 'BGGR')")


# --------------------------------------------------------------------------
# Lossless JPEG (ITU-T T.81 process 14, SOF3)
# --------------------------------------------------------------------------

_LUT_CACHE: dict = {}


def _build_lut(bits: bytes, vals: bytes):
    """Build 16-bit-peek lookup tables for one DC Huffman table.

    Returns (tl, dv): for a 16-bit peek p,
      tl[p] > 0  -> consume tl[p] bits; difference = dv[p]  (code+extra fit)
      tl[p] < 0  -> code length is -tl[p]; SSSS = dv[p]; read extras slowly
      tl[p] == 0 -> invalid code
    """
    key = (bits, vals)
    hit = _LUT_CACHE.get(key)
    if hit is not None:
        return hit
    tl = [0] * 65536
    dv = [0] * 65536
    code = 0
    k = 0
    for length in range(1, 17):
        for _ in range(bits[length - 1]):
            if k >= len(vals):
                raise DngError("DHT value count mismatch")
            s = vals[k]
            k += 1
            if s > 16:
                raise DngError(f"DHT SSSS {s} > 16")
            if code >= (1 << length):
                raise DngError("DHT code overflow")
            base = code << (16 - length)
            span = 1 << (16 - length)
            if s == 0 or s == 16:
                d = 0 if s == 0 else 32768
                for p in range(base, base + span):
                    tl[p] = length
                    dv[p] = d
            elif length + s <= 16:
                shift = 16 - length - s
                mask = (1 << s) - 1
                half = 1 << (s - 1)
                full = (1 << s) - 1
                for p in range(base, base + span):
                    v = (p >> shift) & mask
                    if v < half:
                        v -= full
                    tl[p] = length + s
                    dv[p] = v
            else:
                for p in range(base, base + span):
                    tl[p] = -length
                    dv[p] = s
            code += 1
        code <<= 1
    _LUT_CACHE[key] = (tl, dv)
    return tl, dv


def parse_lj92(buf: bytes) -> dict:
    if buf[:2] != b"\xff\xd8":
        raise DngError("LJ92: missing SOI")
    pos = 2
    n = len(buf)
    tables: dict = {}
    frame = None
    restart_interval = 0
    while pos + 4 <= n:
        if buf[pos] != 0xFF:
            raise DngError(f"LJ92: expected marker at {pos}")
        marker = buf[pos + 1]
        if marker == 0xFF:
            pos += 1
            continue
        length = struct.unpack_from(">H", buf, pos + 2)[0]
        seg = buf[pos + 4:pos + 2 + length]
        if marker == 0xC3:
            p, y, x, nf = struct.unpack_from(">BHHB", seg, 0)
            comps = []
            for c in range(nf):
                cid, hv, tq = struct.unpack_from(">BBB", seg, 6 + 3 * c)
                comps.append((cid, hv >> 4, hv & 15))
            frame = {"precision": p, "height": y, "width": x, "components": comps}
        elif marker in (0xC0, 0xC1, 0xC2, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
            raise DngError(f"LJ92: unsupported SOF marker 0x{marker:02x}")
        elif marker == 0xC4:
            q = 0
            while q < len(seg):
                tc_th = seg[q]
                bits = bytes(seg[q + 1:q + 17])
                cnt = sum(bits)
                vals = bytes(seg[q + 17:q + 17 + cnt])
                if tc_th >> 4 != 0:
                    raise DngError("LJ92: AC Huffman table in lossless stream")
                tables[tc_th & 15] = (bits, vals)
                q += 17 + cnt
        elif marker == 0xDD:
            restart_interval = struct.unpack_from(">H", seg, 0)[0]
        elif marker == 0xDA:
            ns = seg[0]
            sel = []
            for c in range(ns):
                cid, tsel = seg[1 + 2 * c], seg[2 + 2 * c]
                sel.append((cid, tsel >> 4))
            ss = seg[1 + 2 * ns]
            ahal = seg[3 + 2 * ns]
            if frame is None:
                raise DngError("LJ92: SOS before SOF3")
            return {
                "frame": frame,
                "tables": tables,
                "scan": sel,
                "predictor": ss,
                "point_transform": ahal & 15,
                "restart_interval": restart_interval,
                "data_start": pos + 2 + length,
            }
        pos += 2 + length
    raise DngError("LJ92: no SOS marker")


def _entropy_segments(buf: bytes, start: int) -> list:
    """Split the entropy-coded data at RSTn markers, stop at any other marker,
    and remove 0xFF00 byte stuffing."""
    segs = []
    cur = start
    i = start
    n = len(buf)
    while True:
        j = buf.find(b"\xff", i)
        if j < 0 or j + 1 >= n:
            segs.append(buf[cur:n])
            break
        m = buf[j + 1]
        if m == 0x00 or m == 0xFF:
            i = j + 1 if m == 0xFF else j + 2
            continue
        segs.append(buf[cur:j])
        if 0xD0 <= m <= 0xD7:
            cur = i = j + 2
            continue
        break
    return [bytes(s).replace(b"\xff\x00", b"\xff") for s in segs]


def decode_lj92(buf: bytes):
    """Decode a lossless-JPEG stream. Returns (hdr, values) where values is
    array('H') of height * width * ncomp samples, row-major with components
    interleaved within each row (the DNG CFA convention).

    Prediction follows ITU-T T.81 H.1.2.1: on the first row of the scan and
    on the first row after each restart, the first sample of each component
    is predicted by 2^(P-Pt-1) and the rest by Ra (left); on every other row
    the first sample uses Rb (above) and the rest use the selected predictor.
    """
    hdr = parse_lj92(buf)
    fr = hdr["frame"]
    P = fr["precision"]
    Y = fr["height"]
    X = fr["width"]
    comps = fr["components"]
    nc = len(comps)
    pred = hdr["predictor"]
    pt = hdr["point_transform"]
    if not (2 <= P <= 16):
        raise DngError(f"LJ92: precision {P}")
    if any(h != 1 or v != 1 for _, h, v in comps):
        raise DngError("LJ92: only H=V=1 sampling supported")
    if len(hdr["scan"]) != nc:
        raise DngError("LJ92: non-interleaved scans unsupported")
    if not (1 <= pred <= 7):
        raise DngError(f"LJ92: predictor {pred} unsupported")
    order = {cid: k for k, (cid, _, _) in enumerate(comps)}
    luts = [None] * nc
    for cid, tsel in hdr["scan"]:
        if cid not in order or tsel not in hdr["tables"]:
            raise DngError("LJ92: bad scan component/table")
        luts[order[cid]] = _build_lut(*hdr["tables"][tsel])
    ri = hdr["restart_interval"]
    if ri and ri % X:
        raise DngError("LJ92: restart interval not a multiple of the MCU row")
    rows_per_seg = (ri // X) if ri else Y
    R = X * nc
    total = R * Y
    out = array("H", bytes(2 * total))
    segs = _entropy_segments(buf, hdr["data_start"])
    need = -(-Y // rows_per_seg)
    if len(segs) < need:
        raise DngError(f"LJ92: {len(segs)} entropy segments < {need}")
    init = 1 << (P - pt - 1)
    tl_of = [luts[k % nc][0] for k in range(R)]
    dv_of = [luts[k % nc][1] for k in range(R)]
    data = b""
    dn = dpos = bitbuf = bitcnt = 0
    i = 0
    for y in range(Y):
        reset_row = (y % rows_per_seg) == 0
        if reset_row:
            data = segs[y // rows_per_seg]
            dn = len(data)
            dpos = bitbuf = bitcnt = 0
        for xi in range(R):
            if bitcnt < 32:
                while bitcnt < 32:
                    if dpos < dn:
                        bitbuf = ((bitbuf << 8) | data[dpos]) & 0xFFFFFFFFFF
                        dpos += 1
                    else:
                        bitbuf = (bitbuf << 8) & 0xFFFFFFFFFF
                    bitcnt += 8
            peek = (bitbuf >> (bitcnt - 16)) & 0xFFFF
            t = tl_of[xi][peek]
            if t > 0:
                bitcnt -= t
                diff = dv_of[xi][peek]
            elif t < 0:
                bitcnt += t
                s = dv_of[xi][peek]
                v = (bitbuf >> (bitcnt - s)) & ((1 << s) - 1)
                bitcnt -= s
                if v < (1 << (s - 1)):
                    v -= (1 << s) - 1
                diff = v
            else:
                raise DngError(f"LJ92: invalid Huffman code at sample {i}")
            if xi < nc:
                px = init if reset_row else out[i - R]
            elif reset_row or pred == 1:
                px = out[i - nc]
            elif pred == 2:
                px = out[i - R]
            elif pred == 3:
                px = out[i - R - nc]
            elif pred == 4:
                px = out[i - nc] + out[i - R] - out[i - R - nc]
            elif pred == 5:
                px = out[i - nc] + ((out[i - R] - out[i - R - nc]) >> 1)
            elif pred == 6:
                px = out[i - R] + ((out[i - nc] - out[i - R - nc]) >> 1)
            else:
                px = (out[i - nc] + out[i - R]) >> 1
            out[i] = (px + diff) & 0xFFFF
            i += 1
        if dpos > dn + 4:
            raise DngError(f"LJ92: entropy data exhausted at row {y}")
    if pt:
        for k in range(total):
            out[k] = (out[k] << pt) & 0xFFFF
    return hdr, out


# --------------------------------------------------------------------------
# DNG tile reassembly
# --------------------------------------------------------------------------

def decode_dng_cfa(buf: bytes, info: dict | None = None, tile_filter=None):
    """Decode the full CFA mosaic. Returns (info, array('H') of W*H).
    tile_filter(index) -> bool limits which tiles are decoded (others zero)."""
    if info is None:
        info = dng_raw_info(parse_tiff_ifd0(buf))
    W, H = info["width"], info["height"]
    TW, TL = info["tile_width"], info["tile_length"]
    if info["compression"] != 7:
        raise DngError("not lossless-JPEG compressed")
    tiles_across = -(-W // TW)
    tiles_down = -(-H // TL)
    offs, cnts = info["tile_offsets"], info["tile_byte_counts"]
    if len(offs) != tiles_across * tiles_down or len(cnts) != len(offs):
        raise DngError("tile table size mismatch")
    frame = array("H", bytes(2 * W * H))
    for t, (off, cnt) in enumerate(zip(offs, cnts)):
        if tile_filter is not None and not tile_filter(t):
            continue
        if off + cnt > len(buf):
            raise DngError(f"tile {t} beyond file end")
        hdr, vals = decode_lj92(buf[off:off + cnt])
        fr = hdr["frame"]
        nc = len(fr["components"])
        if fr["width"] * nc != TW or fr["height"] != TL:
            raise DngError(f"tile {t}: LJ92 geometry {fr['width']}x{nc}x{fr['height']} != {TW}x{TL}")
        ty, tx = divmod(t, tiles_across)
        y0, x0 = ty * TL, tx * TW
        cw = min(TW, W - x0)
        for r in range(min(TL, H - y0)):
            dst = (y0 + r) * W + x0
            frame[dst:dst + cw] = vals[r * TW:r * TW + cw]
    return info, frame


def frame_le_bytes(frame) -> bytes:
    a = array("H", frame)
    if sys.byteorder == "big":
        a.byteswap()
    return a.tobytes()


# --------------------------------------------------------------------------
# Reference encoder (self-test only)
# --------------------------------------------------------------------------

def _ssss(d: int) -> int:
    return 0 if d == 0 else abs(d).bit_length()


def encode_lj92(values, width: int, height: int, ncomp: int, precision: int,
                predictor: int, point_transform: int = 0, restart_interval: int = 0,
                tables=None) -> bytes:
    """Encode samples (row-major, comps interleaved) as SOF3 lossless JPEG.
    Uses one canonical Huffman table per component (all SSSS 0..16) unless
    `tables` gives (bits, vals) per component."""
    R = width * ncomp
    vals = [v >> point_transform for v in values]
    if tables is None:
        # canonical table: SSSS 0..16 -> 17 symbols, lengths chosen so codes
        # reach 16 bits (exercise slow path), deliberately non-trivial
        bits = bytes([0, 1, 3, 2, 2, 2, 2, 1, 1, 1, 1, 0, 0, 0, 0, 1])
        order = bytes([2, 1, 3, 0, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16])
        assert sum(bits) == len(order)
        tables = [(bits, order)] * ncomp
    codebooks = []
    for bits, order in tables:
        cb = {}
        code = 0
        k = 0
        for length in range(1, 17):
            for _ in range(bits[length - 1]):
                cb[order[k]] = (code, length)
                k += 1
                code += 1
            code <<= 1
        codebooks.append(cb)
    init = 1 << (precision - point_transform - 1)
    if restart_interval and restart_interval % width:
        raise ValueError("restart interval must be a multiple of width")
    rows_per_seg = restart_interval // width if restart_interval else height
    segments = []
    bitstr = []
    out = bytearray()

    def flush(bitstr):
        s = "".join(bitstr)
        s += "1" * (-len(s) % 8)
        b = bytearray()
        for q in range(0, len(s), 8):
            byte = int(s[q:q + 8], 2)
            b.append(byte)
            if byte == 0xFF:
                b.append(0)
        return bytes(b)

    i = 0
    for y in range(height):
        reset_row = y % rows_per_seg == 0
        if reset_row and y:
            segments.append(flush(bitstr))
            bitstr = []
        for xi in range(R):
            c = xi % ncomp
            if xi < ncomp:
                px = init if reset_row else vals[i - R]
            elif reset_row:
                px = vals[i - ncomp]
            else:
                a, b, cc = vals[i - ncomp], vals[i - R], vals[i - R - ncomp]
                px = {1: a, 2: b, 3: cc, 4: a + b - cc, 5: a + ((b - cc) >> 1),
                      6: b + ((a - cc) >> 1), 7: (a + b) >> 1}[predictor]
            d = (vals[i] - px) & 0xFFFF
            if d >= 32768:
                d -= 65536
            s = 16 if d == -32768 else _ssss(d)
            code, length = codebooks[c][s]
            bitstr.append(format(code, f"0{length}b"))
            if 0 < s < 16:
                e = d if d > 0 else d + (1 << s) - 1
                bitstr.append(format(e, f"0{s}b"))
            i += 1
    segments.append(flush(bitstr))
    out += b"\xff\xd8"
    sof = struct.pack(">BHHB", precision, height, width, ncomp)
    for c in range(ncomp):
        sof += struct.pack(">BBB", c, 0x11, 0)
    out += b"\xff\xc3" + struct.pack(">H", len(sof) + 2) + sof
    for c, (bits, order) in enumerate(tables):
        body = bytes([c]) + bits + order
        out += b"\xff\xc4" + struct.pack(">H", len(body) + 2) + body
    if restart_interval:
        out += b"\xff\xdd" + struct.pack(">HH", 4, restart_interval)
    sos = bytes([ncomp]) + b"".join(bytes([c, c << 4]) for c in range(ncomp)) + bytes([predictor, 0, point_transform])
    out += b"\xff\xda" + struct.pack(">H", len(sos) + 2) + sos
    for k, seg in enumerate(segments):
        if k:
            out += bytes([0xFF, 0xD0 + ((k - 1) % 8)])
        out += seg
    out += b"\xff\xd9"
    return bytes(out)
