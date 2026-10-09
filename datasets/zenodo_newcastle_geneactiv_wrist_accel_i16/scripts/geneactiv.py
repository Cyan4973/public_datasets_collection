#!/usr/bin/env python3
"""GENEActiv .bin (hex text) decoder for zenodo_newcastle_geneactiv_wrist_accel_i16.

Pure standard library. Subcommands:
  check-record  validate the Zenodo record JSON (license, DOI, file size/md5)
  check-cd      parse the ZIP central directory tail, re-derive the selection,
                and compare it with members.tsv
  check-span    validate one downloaded member span (local header, inflate,
                CRC32, GENEActiv page structure); prints only counts
  selftest      synthetic GENEActiv members through both decoders
  build         decode every pinned span into one int16 LE xyz sample
  verify        independent re-decode and checks against the build output

Privacy: GENEActiv file headers carry subject fields (date of birth, sex,
height, weight, notes). They are parsed in memory only to assert the
measurement frequency, accelerometer range, device type and page count, then
discarded. No header value is printed, logged, or written anywhere.
"""
from __future__ import annotations

import argparse
import binascii
import hashlib
import json
import os
import re
import struct
import sys
import tomllib
import zlib
from array import array
from pathlib import Path

DATASET_ID = "zenodo_newcastle_geneactiv_wrist_accel_i16"
SERIES_ID = "geneactiv_wrist_accel_xyz_i16"
RECORD_ID = 1160410
DOI = "10.5281/zenodo.1160410"
ZIP_KEY = "dataset_psgnewcastle2015_v1.0.zip"
ZIP_SIZE = 962798652
ZIP_MD5 = "8ebadbc55cb0e76230f293fc6d53f504"
CD_OFFSET = 962788256
CD_SIZE = 10374
CD_ENTRIES = 87
TAIL_SIZE = ZIP_SIZE - CD_OFFSET  # central directory + 22-byte EOCD, no comment
SELECT_MAX_USIZE = 100_000_000
LEFT_RX = re.compile(
    r"^dataset_psgnewcastle2015_v1\.0/acc/MECSLEEP(\d\d)_left wrist_(\d{6})_"
    r"(\d{4}-\d\d-\d\d \d\d-\d\d-\d\d)\.bin$"
)
SAMPLES_PER_PAGE = 300
HEX_PER_PAGE = SAMPLES_PER_PAGE * 12
FREQ_HZ = 85.7
PAGE_KEYS = (
    "Device Unique Serial Code",
    "Sequence Number",
    "Page Time",
    "Unassigned",
    "Temperature",
    "Battery voltage",
    "Device Status",
    "Measurement Frequency",
)
HEXDIGITS = frozenset(b"0123456789ABCDEFabcdef")
# A page is quasi-static when every axis has population std <= 3.3 counts (13 mg at
# ~256 counts/g, the GGIR non-wear std threshold), tested exactly in integers:
# 300 * sum(x^2) - sum(x)^2 <= 3.3^2 * 300^2 = 980100.
STATIC_VAR_LIMIT = 980100
LONG_STATIC_PAGES = 1029  # >= 60 min of consecutive quasi-static pages (60*60*85.7/300 = 1028.4)
MAX_MODE_FRACTION = 0.5  # fatal: one code holds more than half of a sample
MIN_DISTINCT = 256  # fatal: fewer distinct codes than this in a sample
MAX_LONG_STATIC_FRACTION = 0.5  # fatal: most pages sit in >= 60 min static (non-wear-like) runs


class FormatError(Exception):
    pass


# ----------------------------------------------------------------- helpers
def read_members(path: Path) -> list[dict]:
    lines = [l for l in path.read_text(encoding="utf-8").splitlines() if l and not l.startswith("#")]
    head = lines[0].split("\t")
    rows = []
    for line in lines[1:]:
        row = dict(zip(head, line.split("\t")))
        for k in ("csize", "usize", "range_start", "range_end"):
            row[k] = int(row[k])
        rows.append(row)
    return rows


def sext12(v: int) -> int:
    return v - 4096 if v & 0x800 else v


def parse_cd(tail: bytes) -> list[dict]:
    if len(tail) != TAIL_SIZE:
        raise FormatError(f"tail is {len(tail)} bytes, expected {TAIL_SIZE}")
    eocd = tail[-22:]
    sig, disk, cdd, n1, n, cdsize, cdoff, clen = struct.unpack("<IHHHHIIH", eocd)
    if sig != 0x06054B50 or clen != 0 or disk or cdd:
        raise FormatError("bad end-of-central-directory record")
    if (n1, n, cdsize, cdoff) != (CD_ENTRIES, CD_ENTRIES, CD_SIZE, CD_OFFSET):
        raise FormatError(f"EOCD changed: entries={n} cdsize={cdsize} cdoff={cdoff}")
    p = 0
    ents = []
    for _ in range(n):
        f = struct.unpack_from("<IHHHHHHIIIHHHHHII", tail, p)
        if f[0] != 0x02014B50:
            raise FormatError("bad central directory entry signature")
        flags, meth, crc, cs, us, nl, el, cl, lho = f[3], f[4], f[7], f[8], f[9], f[10], f[11], f[12], f[16]
        name = tail[p + 46 : p + 46 + nl].decode("utf-8" if flags & 0x800 else "cp437")
        ents.append(dict(name=name, flags=flags, method=meth, crc32=f"{crc:08x}", csize=cs, usize=us, lho=lho))
        p += 46 + nl + el + cl
    if p != CD_SIZE:
        raise FormatError("central directory size mismatch")
    ents.sort(key=lambda e: e["lho"])
    for i, e in enumerate(ents):
        e["range_end"] = (ents[i + 1]["lho"] if i + 1 < len(ents) else CD_OFFSET) - 1
    return ents


def select(ents: list[dict]) -> list[dict]:
    left = [e for e in ents if LEFT_RX.match(e["name"])]
    if len(left) != 28:
        raise FormatError(f"expected 28 left-wrist members, found {len(left)}")
    elig = [e for e in left if e["usize"] <= SELECT_MAX_USIZE]
    elig.sort(key=lambda e: int(LEFT_RX.match(e["name"]).group(1)))
    if len(elig) != 26:
        raise FormatError(f"expected 26 eligible left-wrist members, found {len(elig)}")
    return elig[0::2]


# ------------------------------------------------------ span -> text stream
def iter_inflated(span_path: Path, row: dict):
    """Yield inflated chunks of one member span; check header, size and CRC32."""
    want_len = row["range_end"] - row["range_start"] + 1
    if span_path.stat().st_size != want_len:
        raise FormatError(f"span is {span_path.stat().st_size} bytes, expected {want_len}")
    with open(span_path, "rb") as fh:
        hdr = fh.read(30)
        f = struct.unpack("<4s5H3I2H", hdr)
        if f[0] != b"PK\x03\x04":
            raise FormatError("span does not start with a ZIP local file header")
        flags, method, crc, cs, us, nl, xl = f[2], f[3], f[6], f[7], f[8], f[9], f[10]
        name = fh.read(nl).decode("utf-8" if flags & 0x800 else "cp437")
        fh.read(xl)
        if name != row["member"] or method != 8 or flags & 0x8:
            raise FormatError(f"local header mismatch for {row['sample_id']}")
        if f"{crc:08x}" != row["crc32"] or cs != row["csize"] or us != row["usize"]:
            raise FormatError(f"local header CRC/sizes differ from central directory for {row['sample_id']}")
        if 30 + nl + xl + cs != want_len:
            raise FormatError("span length != header + compressed size")
        dec = zlib.decompressobj(-15)
        crc_acc = 0
        total = 0
        while True:
            chunk = fh.read(1 << 20)
            if not chunk:
                break
            out = dec.decompress(chunk)
            if out:
                crc_acc = zlib.crc32(out, crc_acc)
                total += len(out)
                yield out
            if dec.eof:
                break
        out = dec.flush()
        if out:
            crc_acc = zlib.crc32(out, crc_acc)
            total += len(out)
            yield out
        if not dec.eof or dec.unused_data or fh.read(1):
            raise FormatError("deflate stream truncated or trailing bytes")
        if total != row["usize"] or f"{crc_acc & 0xFFFFFFFF:08x}" != row["crc32"]:
            raise FormatError(f"inflated size/CRC32 mismatch for {row['sample_id']}")


def iter_lines(chunks):
    """CRLF-terminated lines (without terminator)."""
    rest = b""
    for chunk in chunks:
        buf = rest + chunk
        parts = buf.split(b"\r\n")
        rest = parts.pop()
        yield from parts
    if rest:
        yield rest


def iter_pages(lines):
    """Validate the GENEActiv text layout; yield each page's 3600-char hex line.

    Header values are inspected only for the asserted fields and dropped.
    The page count is checked after the last page (raises FormatError).
    """
    lines = iter(lines)
    header_ok = {"freq": False, "range": False, "type": False}
    n_pages_hdr = None
    for line in lines:
        if line == b"Recorded Data":
            break
        key, sep, val = line.partition(b":")
        if not sep:
            continue
        key = key.strip()
        if key == b"Measurement Frequency":
            if val.strip() != b"85.7 Hz":
                raise FormatError("header measurement frequency is not 85.7 Hz")
            header_ok["freq"] = True
        elif key == b"Accelerometer Range":
            if val.strip() != b"-8 to 8":
                raise FormatError("header accelerometer range is not -8 to 8")
            header_ok["range"] = True
        elif key == b"Device Type":
            if val.strip() != b"GENEActiv":
                raise FormatError("header device type is not GENEActiv")
            header_ok["type"] = True
        elif key == b"Number of Pages":
            if n_pages_hdr is not None or not val.strip().isdigit():
                raise FormatError("bad Number of Pages field")
            n_pages_hdr = int(val.strip())
    else:
        raise FormatError("no Recorded Data page found")
    if not all(header_ok.values()) or n_pages_hdr is None:
        raise FormatError(f"header missing required fields {sorted(k for k, v in header_ok.items() if not v)}")
    page = 0
    while True:
        meta = []
        for key in PAGE_KEYS:
            line = next(lines, None)
            if line is None:
                raise FormatError(f"page {page} truncated")
            k, sep, v = line.partition(b":")
            if not sep or k.decode("latin-1") != key:
                raise FormatError(f"page {page}: expected field {key!r}")
            meta.append(v)
        if int(meta[1]) != page:
            raise FormatError(f"page {page}: sequence number {int(meta[1])}")
        if meta[7].strip() != b"85.7":
            raise FormatError(f"page {page}: measurement frequency is not 85.7")
        data = next(lines, None)
        if data is None or len(data) != HEX_PER_PAGE or not HEXDIGITS.issuperset(data):
            raise FormatError(f"page {page}: data line is not {HEX_PER_PAGE} hex characters")
        yield data
        page += 1
        nxt = next(lines, None)
        while nxt == b"":
            nxt = next(lines, None)
            if nxt not in (None, b""):
                raise FormatError("blank line inside page sequence")
        if nxt is None:
            break
        if nxt != b"Recorded Data":
            raise FormatError(f"page {page}: expected 'Recorded Data'")
    if page != n_pages_hdr:
        raise FormatError(f"page count {page} != header Number of Pages {n_pages_hdr}")


# ------------------------------------------------------------- decoders
def _tables():
    tx = array("h", (sext12(((k & 0xFF) << 4) | (k >> 12)) for k in range(65536)))
    ty = array("h", (sext12(((k & 0x0F) << 8) | (k >> 8)) for k in range(65536)))
    return tx, ty


_TX, _TY = None, None


def decode_pages_fast(hex_pages: list[bytes]) -> array:
    """Build decoder: unhexlify, byte-lane slicing and 16-bit lookup tables."""
    global _TX, _TY
    if _TX is None:
        _TX, _TY = _tables()
    raw = binascii.unhexlify(b"".join(hex_pages))
    n = len(raw) // 6
    lanes = [raw[i::6] for i in range(5)]

    def pair(a, b):
        p = bytearray(2 * n)
        p[0::2] = a
        p[1::2] = b
        h = array("H")
        h.frombytes(bytes(p))
        if sys.byteorder != "little":
            h.byteswap()
        return h

    out = array("h", bytes(6 * n))
    out[0::3] = array("h", map(_TX.__getitem__, pair(lanes[0], lanes[1])))
    out[1::3] = array("h", map(_TY.__getitem__, pair(lanes[1], lanes[2])))
    out[2::3] = array("h", map(_TX.__getitem__, pair(lanes[3], lanes[4])))
    return out


def decode_page_ref(hex_line: bytes) -> list[int]:
    """Verify decoder: one 48-bit integer per sample, shifted and masked."""
    s = hex_line.decode("ascii")
    vals = []
    for i in range(0, HEX_PER_PAGE, 12):
        w = int(s[i : i + 12], 16)
        for shift in (36, 24, 12):
            v = (w >> shift) & 0xFFF
            vals.append(v - 4096 if v >= 2048 else v)
    return vals


def to_le_bytes(a: array) -> bytes:
    if sys.byteorder != "little":
        a = array(a.typecode, a)
        a.byteswap()
    return a.tobytes()


# ----------------------------------------------------------- statistics
def summarize(hist, n_values):
    distinct = sum(1 for c in hist if c)
    mode_count = max(hist)
    mode_value = hist.index(mode_count) - 2048
    lo = next(i for i, c in enumerate(hist) if c) - 2048
    hi = 4095 - next(i for i, c in enumerate(reversed(hist)) if c) - 2048
    return dict(min=lo, max=hi, distinct_values=distinct, mode_value=mode_value,
                mode_fraction=round(mode_count / n_values, 6))


# ------------------------------------------------------ one-member decode
def decode_member_fast(span: Path, row: dict, out_path: Path | None):
    """Decode one span with the build decoder. Returns (stats dict, sha256)."""
    sha = hashlib.sha256()
    hist = [0] * 4096
    axis_min, axis_max = [4096] * 3, [-4096] * 3
    pages = 0
    flags: list[bool] = []
    out = open(out_path, "wb") if out_path else None
    batch: list[bytes] = []

    def flush():
        nonlocal pages
        if not batch:
            return
        a = decode_pages_fast(batch)
        data = to_le_bytes(a)
        sha.update(data)
        if out:
            out.write(data)
        for v in a:
            hist[v + 2048] += 1
        for p in range(len(batch)):
            seg = a[p * 900 : (p + 1) * 900]
            st = True
            for ax in range(3):
                s = seg[ax::3]
                lo, hi = min(s), max(s)
                if lo < axis_min[ax]:
                    axis_min[ax] = lo
                if hi > axis_max[ax]:
                    axis_max[ax] = hi
                if st and 300 * sum(x * x for x in s) - sum(s) ** 2 > STATIC_VAR_LIMIT:
                    st = False
            flags.append(st)
        pages += len(batch)
        batch.clear()

    try:
        for hx in iter_pages(iter_lines(iter_inflated(span, row))):
            batch.append(hx)
            if len(batch) >= 1024:
                flush()
        flush()
    finally:
        if out:
            out.close()
    n_values = pages * SAMPLES_PER_PAGE * 3
    st = summarize(hist, n_values)
    st.update(pages=pages, frames=pages * SAMPLES_PER_PAGE, value_count=n_values,
              clipped_count=hist[0] + hist[4095],
              axis_min=axis_min, axis_max=axis_max, **static_summary(flags))
    return st, sha.hexdigest()


def static_summary(flags: list[bool]) -> dict:
    runs, run = [], 0
    for f in flags:
        if f:
            run += 1
        else:
            if run:
                runs.append(run)
            run = 0
    if run:
        runs.append(run)
    n = len(flags)
    return dict(static_page_fraction=round(sum(flags) / n, 6),
                longest_static_run_pages=max(runs) if runs else 0,
                long_static_run_fraction=round(sum(r for r in runs if r >= LONG_STATIC_PAGES) / n, 6))


def degenerate_reason(st: dict) -> str | None:
    if st["max"] == st["min"]:
        return "constant"
    if st["distinct_values"] < MIN_DISTINCT:
        return f"only {st['distinct_values']} distinct codes"
    if st["mode_fraction"] > MAX_MODE_FRACTION:
        return f"mode code {st['mode_value']} holds {st['mode_fraction']:.3f} of values"
    if st["long_static_run_fraction"] > MAX_LONG_STATIC_FRACTION:
        return f"{st['long_static_run_fraction']:.3f} of pages in >= 60 min quasi-static runs"
    if any(lo == hi for lo, hi in zip(st["axis_min"], st["axis_max"])):
        return "an axis is constant"
    return None


# ------------------------------------------------------------- commands
def cmd_check_record(args):
    doc = json.loads(Path(args.record).read_text(encoding="utf-8"))
    md = doc.get("metadata", {})
    if doc.get("id") != RECORD_ID and str(doc.get("id")) != str(RECORD_ID):
        raise SystemExit(f"unexpected record id {doc.get('id')!r}")
    lic = md.get("license", {})
    lic_id = lic.get("id") if isinstance(lic, dict) else lic
    if lic_id != "cc-by-4.0":
        raise SystemExit(f"license changed: {lic!r}")
    if md.get("access_right") != "open":
        raise SystemExit(f"access_right changed: {md.get('access_right')!r}")
    if (md.get("doi") or doc.get("doi")) != DOI:
        raise SystemExit("DOI changed")
    files = {f["key"]: f for f in doc.get("files", [])}
    f = files.get(ZIP_KEY)
    if f is None or int(f["size"]) != ZIP_SIZE or f.get("checksum") != f"md5:{ZIP_MD5}":
        raise SystemExit(f"ZIP file entry changed: {f!r}")
    print(f"record_validation=ok record={RECORD_ID} license=cc-by-4.0 access=open zip_size={ZIP_SIZE} md5={ZIP_MD5}")


def cmd_check_cd(args):
    ents = parse_cd(Path(args.tail).read_bytes())
    sel = select(ents)
    rows = read_members(Path(args.members))
    if len(sel) != len(rows):
        raise SystemExit(f"selection size {len(sel)} != members.tsv {len(rows)}")
    for e, r in zip(sel, rows):
        sid = "MECSLEEP%s_left" % LEFT_RX.match(e["name"]).group(1)
        got = (sid, e["name"], e["crc32"], e["csize"], e["usize"], e["lho"], e["range_end"], e["method"], e["flags"] & 0x8)
        want = (r["sample_id"], r["member"], r["crc32"], r["csize"], r["usize"], r["range_start"], r["range_end"], 8, 0)
        if got != want:
            raise SystemExit(f"central directory / selection mismatch for {r['sample_id']}")
    print(f"central_directory_validation=ok entries={len(ents)} selected={len(sel)}")


def cmd_check_span(args):
    rows = {r["sample_id"]: r for r in read_members(Path(args.members))}
    row = rows[args.sample_id]
    pages = 0
    for _ in iter_pages(iter_lines(iter_inflated(Path(args.span), row))):
        pages += 1
    print(f"span_validation=ok sample={args.sample_id} pages={pages} frames={pages * SAMPLES_PER_PAGE}")


def synth_member(words_pages, header_pages=None, freq=b"85.7 Hz", rng=b"-8 to 8", page_freq=b"85.7",
                 seq_skip=False, bad_hex=False):
    hdr = [b"Device Identity", b"Device Unique Serial Code:000000", b"Device Type:GENEActiv           ",
           b"", b"Device Capabilities", b"Accelerometer Range:" + rng + b"             ",
           b"", b"Configuration Info", b"Measurement Frequency:" + freq,
           b"", b"Subject Info", b"Date of Birth:1900-01-01", b"Sex:x", b"Subject Notes:synthetic",
           b"", b"Memory Status",
           b"Number of Pages:%d" % (len(words_pages) if header_pages is None else header_pages), b""]
    body = []
    for i, words in enumerate(words_pages):
        seq = i + 1 if (seq_skip and i == 1) else i
        body += [b"Recorded Data", b"Device Unique Serial Code:000000", b"Sequence Number:%d" % seq,
                 b"Page Time:2000-01-01 00:00:00:000", b"Unassigned:", b"Temperature:20.0",
                 b"Battery voltage:4.0", b"Device Status:Recording", b"Measurement Frequency:" + page_freq,
                 b"".join(b"%012X" % w for w in words)]
        if bad_hex and i == 0:
            body[-1] = b"G" + body[-1][1:]
    return b"\r\n".join(hdr + body) + b"\r\n"


def zip_span(name: str, text: bytes, corrupt_crc=False):
    c = zlib.compressobj(9, zlib.DEFLATED, -15)
    comp = c.compress(text) + c.flush()
    crc = zlib.crc32(text) ^ (1 if corrupt_crc else 0)
    nb = name.encode()
    hdr = struct.pack("<4s5H3I2H", b"PK\x03\x04", 20, 0, 8, 0, 0, crc, len(comp), len(text), len(nb), 0)
    span = hdr + nb + comp
    row = dict(sample_id="SYN", member=name, crc32=f"{zlib.crc32(text):08x}", csize=len(comp), usize=len(text),
               range_start=0, range_end=len(span) - 1)
    return span, row


def cmd_selftest(args):
    import random
    tmp = Path(args.tmp) if args.tmp else Path(os.environ.get("TMPDIR", "/tmp")) / f"{DATASET_ID}_selftest_{os.getpid()}"
    tmp.mkdir(parents=True, exist_ok=True)
    rnd = random.Random(1160410)
    # Known word from the real file: FF30F8F96000 -> (-13, 248, -106)
    assert decode_page_ref(b"FF30F8F96000" * 300)[:3] == [-13, 248, -106]
    assert list(decode_pages_fast([b"FF30F8F96000" * 300])[:3]) == [-13, 248, -106]
    pages, expect = [], []
    corners = [(-2048, 2047, 0), (2047, -2048, -1), (-1, 1, 2048 - 1), (0, 0, 0)]
    for p in range(5):
        words = []
        for i in range(SAMPLES_PER_PAGE):
            if p == 0 and i < len(corners):
                x, y, z = corners[i]
            else:
                x, y, z = (rnd.randint(-2048, 2047) for _ in range(3))
            low = rnd.getrandbits(12)  # light 10 + button 1 + reserved 1: must be ignored
            words.append(((x & 0xFFF) << 36) | ((y & 0xFFF) << 24) | ((z & 0xFFF) << 12) | low)
            expect += [x, y, z]
        pages.append(words)
    name = "syn/MECSLEEP99_left wrist_000000_2000-01-01 00-00-00.bin"
    span, row = zip_span(name, synth_member(pages))
    sp = tmp / "ok.span"
    sp.write_bytes(span)
    st, sha = decode_member_fast(sp, row, tmp / "ok.bin")
    got = array("h")
    got.frombytes((tmp / "ok.bin").read_bytes())
    if sys.byteorder != "little":
        got.byteswap()
    assert list(got) == expect, "fast decoder mismatch"
    ref = []
    for hx in iter_pages(iter_lines(iter_inflated(sp, row))):
        ref += decode_page_ref(hx)
    assert ref == expect, "reference decoder mismatch"
    assert st["pages"] == 5 and st["value_count"] == 4500 and st["min"] == -2048 and st["max"] == 2047
    assert st["static_page_fraction"] == 0.0 and st["clipped_count"] >= 2
    # quasi-static metric: +/-3 alternating (std 3.0) is static, +/-4 (std 4.0) is not
    qs = [[(((100 + (3 if i % 2 else -3)) & 0xFFF) << 36) | ((5 & 0xFFF) << 24) | ((0xF00) << 12)
           for i in range(SAMPLES_PER_PAGE)] for _ in range(2)]
    qs.append([(((100 + (4 if i % 2 else -4)) & 0xFFF) << 36) | ((5 & 0xFFF) << 24) | ((0xF00) << 12)
               for i in range(SAMPLES_PER_PAGE)])
    s2, r2 = zip_span(name, synth_member(qs))
    (tmp / "qs.span").write_bytes(s2)
    st2, _ = decode_member_fast(tmp / "qs.span", r2, None)
    vflags = []
    for hx in iter_pages(iter_lines(iter_inflated(tmp / "qs.span", r2))):
        v = decode_page_ref(hx)
        vflags.append(all(300 * sum(x * x for x in v[a::3]) - sum(v[a::3]) ** 2 <= STATIC_VAR_LIMIT for a in range(3)))
    assert vflags == [True, True, False] and st2["longest_static_run_pages"] == 2
    assert st2["static_page_fraction"] == round(2 / 3, 6) and degenerate_reason(st2) is not None
    # rejection cases
    bad = {
        "page_count": synth_member(pages, header_pages=6),
        "freq": synth_member(pages, freq=b"100 Hz"),
        "range": synth_member(pages, rng=b"-6 to 6"),
        "page_freq": synth_member(pages, page_freq=b"100"),
        "seq": synth_member(pages, seq_skip=True),
        "hex": synth_member(pages, bad_hex=True),
        "short_line": synth_member(pages).replace(b"%012X\r\n" % pages[-1][-1], b"\r\n"),
    }
    for label, text in bad.items():
        s, r = zip_span(name, text)
        (tmp / "bad.span").write_bytes(s)
        try:
            for _ in iter_pages(iter_lines(iter_inflated(tmp / "bad.span", r))):
                pass
        except FormatError:
            continue
        raise SystemExit(f"selftest: {label} corruption not rejected")
    s, r = zip_span(name, synth_member(pages), corrupt_crc=True)
    (tmp / "bad.span").write_bytes(s)
    try:
        list(iter_inflated(tmp / "bad.span", r))
        raise SystemExit("selftest: CRC corruption not rejected")
    except FormatError:
        pass
    for f in tmp.iterdir():
        f.unlink()
    tmp.rmdir()
    print("selftest=ok (fast and reference decoders agree on 1,500 synthetic frames incl. 12-bit extremes; "
          "quasi-static threshold exact; page-count, frequency, range, sequence, hex, line-length and CRC corruption rejected)")


def paths(data_root: Path):
    return dict(
        downloads=data_root / "downloads" / DATASET_ID,
        samples=data_root / "samples" / DATASET_ID / SERIES_ID,
        index=data_root / "index" / DATASET_ID / "samples.jsonl",
        filtered=data_root / "filtered" / DATASET_ID / "ingest_stats.json",
    )


def cmd_build(args):
    data_root = Path(args.data_root)
    P = paths(data_root)
    rows = read_members(Path(args.members))
    P["samples"].mkdir(parents=True, exist_ok=True)
    P["index"].parent.mkdir(parents=True, exist_ok=True)
    P["filtered"].parent.mkdir(parents=True, exist_ok=True)
    for old in P["samples"].glob("*.bin"):
        if old.stem not in {r["sample_id"] for r in rows}:
            old.unlink()
    index_rows, total_values, total_bytes = [], 0, 0
    agg_hist_static = agg_long = agg_clipped = 0
    agg_pages = 0
    for r in rows:
        span = P["downloads"] / "members" / f"{r['sample_id']}.zipspan"
        out = P["samples"] / f"{r['sample_id']}.bin"
        tmp = out.with_suffix(".bin.part")
        st, sha = decode_member_fast(span, r, tmp)
        why = degenerate_reason(st)
        if why:
            tmp.unlink()
            raise SystemExit(f"FATAL: {r['sample_id']} degenerate: {why}")
        os.replace(tmp, out)
        size = out.stat().st_size
        assert size == st["value_count"] * 2
        row = dict(
            dataset_id=DATASET_ID, series_id=SERIES_ID, sample_id=r["sample_id"],
            sample_path=str(out.relative_to(data_root)), numeric_kind="int", bit_width=16,
            endianness="little", element_size_bytes=2, sample_size_bytes=size,
            value_count=st["value_count"], frames=st["frames"], channels=3, channel_order="x,y,z",
            sample_rate_hz=FREQ_HZ, pages=st["pages"], source_member=r["member"],
            source_crc32=r["crc32"], sha256=sha, min=st["min"], max=st["max"],
            axis_min=st["axis_min"], axis_max=st["axis_max"], distinct_values=st["distinct_values"],
            mode_value=st["mode_value"], mode_fraction=st["mode_fraction"],
            static_page_fraction=st["static_page_fraction"],
            longest_static_run_pages=st["longest_static_run_pages"],
            long_static_run_fraction=st["long_static_run_fraction"], clipped_count=st["clipped_count"],
        )
        index_rows.append(row)
        total_values += st["value_count"]
        total_bytes += size
        agg_pages += st["pages"]
        agg_hist_static += round(st["static_page_fraction"] * st["pages"])
        agg_long += round(st["long_static_run_fraction"] * st["pages"])
        agg_clipped += st["clipped_count"]
        print(f"sample={r['sample_id']} pages={st['pages']} values={st['value_count']} bytes={size} "
              f"min={st['min']} max={st['max']} distinct={st['distinct_values']} "
              f"mode_fraction={st['mode_fraction']} static_page_fraction={st['static_page_fraction']} "
              f"longest_static_h={st['longest_static_run_pages'] * 300 / FREQ_HZ / 3600:.2f} "
              f"long_static_run_fraction={st['long_static_run_fraction']} clipped={st['clipped_count']}", flush=True)
    with open(P["index"], "w", encoding="utf-8") as fh:
        for row in index_rows:
            fh.write(json.dumps(row, sort_keys=True) + "\n")
    agg = hashlib.sha256()
    for row in index_rows:
        agg.update(bytes.fromhex(row["sha256"]))
    stats = dict(dataset_id=DATASET_ID, samples=len(index_rows), total_values=total_values,
                 total_bytes=total_bytes, total_pages=agg_pages,
                 static_page_fraction=round(agg_hist_static / agg_pages, 6),
                 long_static_run_fraction=round(agg_long / agg_pages, 6), clipped_count=agg_clipped,
                 aggregate_sha256_of_sample_sha256=agg.hexdigest(), excluded=[])
    P["filtered"].write_text(json.dumps(stats, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"build_total samples={len(index_rows)} values={total_values} bytes={total_bytes} aggregate={agg.hexdigest()}")


def cmd_verify(args):
    data_root = Path(args.data_root)
    P = paths(data_root)
    rows = read_members(Path(args.members))
    manifest = tomllib.loads(Path(args.manifest).read_text(encoding="utf-8"))
    series = [s for s in manifest["series"] if s["id"] == SERIES_ID]
    assert len(series) == 1
    series = series[0]
    idx = [json.loads(l) for l in P["index"].read_text(encoding="utf-8").splitlines() if l.strip()]
    if [i["sample_id"] for i in idx] != [r["sample_id"] for r in rows]:
        raise SystemExit("index rows do not match members.tsv order")
    on_disk = sorted(p.name for p in P["samples"].iterdir())
    if on_disk != sorted(f"{r['sample_id']}.bin" for r in rows):
        raise SystemExit(f"unexpected files in sample directory: {on_disk}")
    total_bytes = total_values = 0
    values_per_sample = []
    for r, ix in zip(rows, idx):
        span = P["downloads"] / "members" / f"{r['sample_id']}.zipspan"
        out = data_root / ix["sample_path"]
        expected_path = f"samples/{DATASET_ID}/{SERIES_ID}/{r['sample_id']}.bin"
        if ix["sample_path"] != expected_path:
            raise SystemExit(f"bad sample_path {ix['sample_path']}")
        # independent decode: per-word integer arithmetic, compared page by page
        hist = {}
        n = 0
        vflags = []
        amin, amax = [4096] * 3, [-4096] * 3
        sha = hashlib.sha256()
        with open(out, "rb") as fh:
            for hx in iter_pages(iter_lines(iter_inflated(span, r))):
                vals = decode_page_ref(hx)
                blob = struct.pack("<900h", *vals)
                if fh.read(1800) != blob:
                    raise SystemExit(f"{r['sample_id']}: page {n // 900} differs from reference decode")
                sha.update(blob)
                for v in vals:
                    hist[v] = hist.get(v, 0) + 1
                s1 = [0, 0, 0]
                s2 = [0, 0, 0]
                for i, v in enumerate(vals):
                    ax = i % 3
                    s1[ax] += v
                    s2[ax] += v * v
                    if v < amin[ax]:
                        amin[ax] = v
                    if v > amax[ax]:
                        amax[ax] = v
                vflags.append(all(300 * s2[ax] - s1[ax] * s1[ax] <= STATIC_VAR_LIMIT for ax in range(3)))
                n += 900
            if fh.read(1):
                raise SystemExit(f"{r['sample_id']}: sample file longer than decoded data")
        size = out.stat().st_size
        mode_value, mode_count = max(hist.items(), key=lambda kv: (kv[1], -kv[0]))
        checks = {
            "dataset_id": DATASET_ID, "series_id": SERIES_ID, "numeric_kind": "int", "bit_width": 16,
            "endianness": "little", "element_size_bytes": 2, "sample_size_bytes": size, "value_count": n,
            "frames": n // 3, "pages": n // 900, "sha256": sha.hexdigest(), "min": min(hist), "max": max(hist),
            "distinct_values": len(hist), "mode_value": mode_value, "mode_fraction": round(mode_count / n, 6),
            "axis_min": amin, "axis_max": amax, "clipped_count": hist.get(-2048, 0) + hist.get(2047, 0),
            "source_crc32": r["crc32"], "channels": 3, "sample_rate_hz": FREQ_HZ,
            "source_member": r["member"],
            **static_summary(vflags),
        }
        for k, v in checks.items():
            if ix.get(k) != v:
                raise SystemExit(f"{r['sample_id']}: index field {k}={ix.get(k)!r}, recomputed {v!r}")
        if size != 2 * n:
            raise SystemExit(f"{r['sample_id']}: size mismatch")
        if min(hist) < -2048 or max(hist) > 2047:
            raise SystemExit(f"{r['sample_id']}: value outside 12-bit range")
        why = degenerate_reason(ix)
        if why:
            raise SystemExit(f"{r['sample_id']}: degenerate: {why}")
        total_bytes += size
        total_values += n
        values_per_sample.append(n)
        print(f"verified sample={r['sample_id']} values={n} sha256={sha.hexdigest()[:16]}", flush=True)
    vps = sorted(values_per_sample)
    median = vps[len(vps) // 2] if len(vps) % 2 else (vps[len(vps) // 2 - 1] + vps[len(vps) // 2]) / 2
    if total_values < 10_000 or median < 1_000:
        raise SystemExit("acceptance floor not met")
    if total_bytes > 1_000_000_000:
        raise SystemExit("primary output exceeds 1 GB cap")
    if series["sample_count"] != len(rows) or series["total_size_bytes"] != total_bytes:
        raise SystemExit(f"manifest totals stale: sample_count={series['sample_count']} total_size_bytes="
                         f"{series['total_size_bytes']}; realized {len(rows)} / {total_bytes}")
    print(f"verify_total samples={len(rows)} values={total_values} bytes={total_bytes} median_values={median}")


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("check-record"); a.add_argument("record"); a.set_defaults(fn=cmd_check_record)
    a = sub.add_parser("check-cd"); a.add_argument("tail"); a.add_argument("members"); a.set_defaults(fn=cmd_check_cd)
    a = sub.add_parser("check-span"); a.add_argument("span"); a.add_argument("members"); a.add_argument("sample_id")
    a.set_defaults(fn=cmd_check_span)
    a = sub.add_parser("selftest"); a.add_argument("--tmp"); a.set_defaults(fn=cmd_selftest)
    for name, fn in (("build", cmd_build), ("verify", cmd_verify)):
        a = sub.add_parser(name)
        a.add_argument("--data-root", required=True)
        a.add_argument("--members", required=True)
        if name == "verify":
            a.add_argument("--manifest", required=True)
        a.set_defaults(fn=fn)
    args = ap.parse_args()
    try:
        args.fn(args)
    except FormatError as exc:
        raise SystemExit(f"FATAL: {exc}")


if __name__ == "__main__":
    main()
