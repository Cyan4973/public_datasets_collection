#!/usr/bin/env python3
"""Shared helpers: sparse FITS header walking, EXTRACT1D layout, range planning and
multipart/byteranges parsing for JWST NIRSpec x1dints products (pure stdlib).

Header pieces of one remote file live in a directory as <offset>.bin files (bytes fetched
with HTTP Range starting at <offset>). The walker follows the HDU chain from byte 0 and
either reports the next byte range it needs or the complete layout.

CLI:
  x1dints.py next-header <piece_dir>            -> "NEED <start> <end>" | "DONE"
  x1dints.py layout <piece_dir>                 -> JSON layout of PRIMARY + EXTRACT1D
  x1dints.py ranges <layout.json> <batch_rows>  -> one line per batch: "<k> <row0> <row1> <range-spec>"
  x1dints.py ingest <layout.json> <k> <row0> <row1> <hdr_file> <body_file> <out_file> <etag> <size>
        exit 0 ok, 3 invalid response (retry), 4 ETag changed (product reprocessed; restart file)
"""
import json
import os
import re
import sys

BLOCK = 2880
CARD = 80
HEADER_CHUNK = 20 * BLOCK  # 57,600 bytes per header fetch
PRIMARY_KEYS = (
    "FILENAME", "DATAMODL", "TELESCOP", "INSTRUME", "DETECTOR", "FILTER", "GRATING",
    "FXD_SLIT", "EXP_TYPE", "SUBARRAY", "READPATT", "NINTS", "INTSTART", "INTEND",
    "NGROUPS", "EXSEGNUM", "EXSEGTOT", "PROGRAM", "OBSERVTN", "VISIT", "EXPOSURE", "TARGNAME",
    "DATE-OBS", "TIME-OBS", "CAL_VER", "SDP_VER", "CRDS_CTX", "CRDS_VER", "TSOVISIT",
)
REGIME = {
    "TELESCOP": "JWST", "INSTRUME": "NIRSPEC", "DATAMODL": "TSOMultiSpecModel",
    "DETECTOR": "NRS1", "FILTER": "F290LP", "GRATING": "G395H", "FXD_SLIT": "S1600A1",
    "EXP_TYPE": "NRS_BRIGHTOBJ", "SUBARRAY": "SUB2048", "EXSEGNUM": 1, "INTSTART": 1,
    "TSOVISIT": True,
}
# Missing-value policy shared by download, build and verify: edge-bin NaN is native fill and
# is kept; every row (integration) must still be at least 90% finite with >= 2 distinct finite
# values, so all-NaN or degenerate integrations reject the product.
MIN_ROW_FINITE_FRACTION = 0.90
TFORM_SIZES = {"L": 1, "X": 1, "B": 1, "I": 2, "J": 4, "K": 8, "A": 1, "E": 4, "D": 8, "C": 8, "M": 16}


class EtagChanged(ValueError):
    pass


class NeedBytes(Exception):
    def __init__(self, start, end):
        super().__init__(f"need {start}-{end}")
        self.start = start
        self.end = end


def load_pieces(piece_dir):
    pieces = []
    for name in os.listdir(piece_dir):
        if name.endswith(".bin") and name[:-4].isdigit():
            with open(os.path.join(piece_dir, name), "rb") as fh:
                pieces.append((int(name[:-4]), fh.read()))
    pieces.sort()
    return pieces


def read_span(pieces, start, length):
    """Return bytes [start, start+length) if covered by the pieces, else raise NeedBytes."""
    out = bytearray()
    pos = start
    end = start + length
    while pos < end:
        hit = None
        for off, data in pieces:
            if off <= pos < off + len(data):
                hit = (off, data)
                break
        if hit is None:
            raise NeedBytes(pos, pos + max(HEADER_CHUNK, end - pos) - 1)
        off, data = hit
        take = min(end, off + len(data)) - pos
        out += data[pos - off:pos - off + take]
        pos += take
    return bytes(out)


def parse_value(raw):
    raw = raw.strip()
    if raw.startswith("'"):
        m = re.match(r"'((?:[^']|'')*)'", raw)
        if not m:
            raise ValueError(f"bad string card value {raw!r}")
        return m.group(1).replace("''", "'").rstrip()
    val = raw.split("/", 1)[0].strip()
    if val in ("T", "F"):
        return val == "T"
    if re.fullmatch(r"[+-]?\d+", val):
        return int(val)
    try:
        return float(val.replace("D", "E"))
    except ValueError:
        return val


def read_header(pieces, offset):
    """Parse one FITS header starting at offset; returns (cards dict, ordered list, header_bytes)."""
    cards = {}
    order = []
    nblocks = 0
    while True:
        block = read_span(pieces, offset + nblocks * BLOCK, BLOCK)
        nblocks += 1
        for i in range(0, BLOCK, CARD):
            card = block[i:i + CARD].decode("ascii")
            key = card[:8].rstrip()
            if key == "END":
                return cards, order, nblocks * BLOCK
            if card[8:10] == "= ":
                val = parse_value(card[10:])
                if key not in cards:
                    cards[key] = val
                order.append((key, val))
        if nblocks > 400:
            raise ValueError(f"no END card within 400 blocks at offset {offset}")


def data_size(cards):
    naxis = int(cards.get("NAXIS", 0))
    if naxis == 0:
        return 0
    n = 1
    for i in range(1, naxis + 1):
        n *= int(cards[f"NAXIS{i}"])
    bits = abs(int(cards["BITPIX"]))
    size = (n + int(cards.get("PCOUNT", 0))) * int(cards.get("GCOUNT", 1)) * bits // 8
    return (size + BLOCK - 1) // BLOCK * BLOCK


def parse_tform(tform):
    m = re.fullmatch(r"\s*(\d*)([LXBIJKAEDCMPQ])(.*)", tform)
    if not m:
        raise ValueError(f"unsupported TFORM {tform!r}")
    rep = int(m.group(1)) if m.group(1) else 1
    code = m.group(2)
    if code in "PQ":
        raise ValueError(f"variable-length column TFORM {tform!r} not supported")
    width = (rep + 7) // 8 if code == "X" else rep * TFORM_SIZES[code]
    return rep, code, width


def walk(pieces):
    """Walk HDUs until EXTRACT1D; returns layout dict or raises NeedBytes."""
    offset = 0
    hdus = []
    primary = None
    while True:
        cards, _, hlen = read_header(pieces, offset)
        name = "PRIMARY" if offset == 0 else str(cards.get("EXTNAME", ""))
        dsize = data_size(cards)
        hdus.append({"name": name, "header_offset": offset, "data_offset": offset + hlen, "data_size": dsize})
        if offset == 0:
            if cards.get("SIMPLE") is not True:
                raise ValueError("not a FITS file (SIMPLE != T)")
            primary = {k: cards.get(k) for k in PRIMARY_KEYS}
        elif name == "EXTRACT1D":
            if cards.get("XTENSION") != "BINTABLE":
                raise ValueError("EXTRACT1D is not a BINTABLE")
            tfields = int(cards["TFIELDS"])
            cols = []
            pos = 0
            for i in range(1, tfields + 1):
                rep, code, width = parse_tform(str(cards[f"TFORM{i}"]))
                cols.append({
                    "name": str(cards.get(f"TTYPE{i}", "")), "tform": str(cards[f"TFORM{i}"]).strip(),
                    "unit": str(cards.get(f"TUNIT{i}", "")), "repeat": rep, "code": code,
                    "offset": pos, "width": width,
                })
                pos += width
            naxis1 = int(cards["NAXIS1"])
            if pos != naxis1:
                raise ValueError(f"column widths sum {pos} != NAXIS1 {naxis1}")
            return {
                "primary": primary, "hdus": hdus,
                "extract1d": {
                    "data_offset": offset + hlen, "naxis1": naxis1, "naxis2": int(cards["NAXIS2"]),
                    "pcount": int(cards.get("PCOUNT", 0)), "columns": cols,
                    "bitpix": int(cards["BITPIX"]), "gcount": int(cards.get("GCOUNT", 1)),
                },
            }
        if offset > 0 and name == "":
            raise ValueError(f"unnamed extension at {offset}")
        offset += hlen + dsize
        if len(hdus) > 20:
            raise ValueError("EXTRACT1D not found in first 20 HDUs")


def flux_layout(layout):
    """Locate the FLUX column; returns (flux_offset_in_row, nbins, unit, tform)."""
    cols = {c["name"]: c for c in layout["extract1d"]["columns"]}
    if "FLUX" not in cols:
        raise ValueError("no FLUX column")
    c = cols["FLUX"]
    if c["code"] != "D":
        raise ValueError(f"FLUX column is not float64: {c['tform']}")
    return c["offset"], c["repeat"], c["unit"], c["tform"]


def regime_problems(layout, filename, size=None):
    """Header-regime check shared by discover.py and the download-time check."""
    p = layout["primary"]
    e = layout["extract1d"]
    problems = [f"{k}={p.get(k)!r}" for k, v in REGIME.items() if p.get(k) != v]
    if p.get("FILENAME") != filename:
        problems.append(f"FILENAME={p.get('FILENAME')!r}")
    if not filename.endswith("-seg001_nrs1_x1dints.fits"):
        problems.append("not a seg001 nrs1 x1dints product")
    try:
        _, nbins, unit, _ = flux_layout(layout)
    except ValueError as exc:
        return problems + [str(exc)]
    if unit != "Jy":
        problems.append(f"TUNIT FLUX={unit!r}")
    cols = {c["name"]: c for c in e["columns"]}
    if cols.get("WAVELENGTH", {}).get("repeat") != nbins or cols.get("WAVELENGTH", {}).get("unit") != "um":
        problems.append("WAVELENGTH column does not match FLUX length / unit um")
    if not 1000 <= nbins <= 2048:
        problems.append(f"nbins {nbins} outside 1000..2048")
    if e["bitpix"] != 8 or e["gcount"] != 1:
        problems.append("EXTRACT1D BITPIX/GCOUNT")
    if not isinstance(p.get("INTEND"), int) or e["naxis2"] != p["INTEND"] - p["INTSTART"] + 1:
        problems.append(f"NAXIS2 {e['naxis2']} != INTEND-INTSTART+1")
    if e["naxis2"] < 1:
        problems.append("empty EXTRACT1D table")
    if size is not None and e["data_offset"] + e["naxis1"] * e["naxis2"] > size:
        problems.append("EXTRACT1D extends past end of file")
    return problems


def plan_ranges(layout, batch_rows):
    e = layout["extract1d"]
    foff, nbins, _, _ = flux_layout(layout)
    width = 8 * nbins
    batches = []
    k = 0
    for row0 in range(0, e["naxis2"], batch_rows):
        row1 = min(e["naxis2"], row0 + batch_rows)
        spec = []
        for r in range(row0, row1):
            s = e["data_offset"] + r * e["naxis1"] + foff
            spec.append(f"{s}-{s + width - 1}")
        batches.append((k, row0, row1, ",".join(spec)))
        k += 1
    return batches


def parse_http_headers(text):
    """Return (status, headers dict) of the LAST response block in a curl -D dump."""
    blocks = [b for b in re.split(r"\r?\n\r?\n", text) if b.strip()]
    status = None
    headers = {}
    for block in blocks:
        lines = block.splitlines()
        m = re.match(r"HTTP/[\d.]+\s+(\d+)", lines[0])
        if not m:
            continue
        st = int(m.group(1))
        if st == 200 and "connection established" in lines[0].lower():
            continue  # proxy CONNECT response
        status = st
        headers = {}
        for line in lines[1:]:
            if ":" in line:
                k, v = line.split(":", 1)
                headers[k.strip().lower()] = v.strip()
    return status, headers


def parse_multipart_byteranges(body, boundary):
    """Split a multipart/byteranges body; returns list of (start, end, total, payload)."""
    delim = b"--" + boundary.encode("ascii")
    parts = []
    pos = body.find(delim)
    if pos < 0:
        raise ValueError("boundary not found in body")
    while True:
        pos += len(delim)
        if body[pos:pos + 2] == b"--":
            break
        if body[pos:pos + 2] == b"\r\n":
            pos += 2
        elif body[pos:pos + 1] == b"\n":
            pos += 1
        else:
            raise ValueError(f"malformed boundary line at {pos}")
        hend = body.find(b"\r\n\r\n", pos)
        sep = 4
        alt = body.find(b"\n\n", pos)
        if hend < 0 or (0 <= alt < hend):
            hend, sep = alt, 2
        if hend < 0:
            raise ValueError("unterminated part header")
        head = body[pos:hend].decode("latin-1")
        m = re.search(r"(?im)^content-range:\s*bytes\s+(\d+)-(\d+)/(\d+|\*)\s*$", head)
        if not m:
            raise ValueError(f"part without Content-Range: {head!r}")
        start, end = int(m.group(1)), int(m.group(2))
        total = int(m.group(3)) if m.group(3) != "*" else -1
        dstart = hend + sep
        dend = dstart + (end - start + 1)
        if dend > len(body):
            raise ValueError("truncated part payload")
        parts.append((start, end, total, body[dstart:dend]))
        pos = body.find(delim, dend)
        if pos < 0:
            raise ValueError("missing closing boundary")
        between = body[dend:pos]
        if between not in (b"\r\n", b"\n", b""):
            raise ValueError("unexpected bytes between parts")
    return parts


def extract_parts(status, headers, body):
    """Turn one HTTP response into a list of (start, end, total, payload)."""
    if status != 206:
        raise ValueError(f"expected HTTP 206, got {status}")
    ctype = headers.get("content-type", "")
    m = re.search(r'boundary="?([^";\s]+)"?', ctype)
    if ctype.lower().startswith("multipart/byteranges"):
        if not m:
            raise ValueError("multipart response without boundary")
        return parse_multipart_byteranges(body, m.group(1))
    m = re.fullmatch(r"bytes\s+(\d+)-(\d+)/(\d+|\*)", headers.get("content-range", "").strip())
    if not m:
        raise ValueError("single-part 206 without Content-Range")
    start, end = int(m.group(1)), int(m.group(2))
    total = int(m.group(3)) if m.group(3) != "*" else -1
    if len(body) != end - start + 1:
        raise ValueError("single-part body length mismatch")
    return [(start, end, total, body)]


def ingest(layout, row0, row1, status, headers, body, etag, size):
    """Validate one batch response and return the FLUX bytes of rows [row0, row1) in order."""
    if etag and headers.get("etag", "").strip('"') != etag.strip('"'):
        raise EtagChanged(f"ETag changed: {headers.get('etag')!r} != {etag!r} (product reprocessed?)")
    e = layout["extract1d"]
    foff, nbins, _, _ = flux_layout(layout)
    width = 8 * nbins
    got = {}
    for start, end, total, payload in extract_parts(status, headers, body):
        if total not in (-1, size):
            raise ValueError(f"Content-Range total {total} != pinned size {size}")
        if start in got:
            raise ValueError(f"duplicate part at {start}")
        got[start] = (end, payload)
    out = bytearray()
    for r in range(row0, row1):
        s = e["data_offset"] + r * e["naxis1"] + foff
        if s not in got:
            raise ValueError(f"row {r} (byte {s}) missing from response")
        end, payload = got.pop(s)
        if end != s + width - 1 or len(payload) != width:
            raise ValueError(f"row {r} part has wrong extent")
        out += payload
    if got:
        raise ValueError(f"unexpected extra parts: {sorted(got)[:5]}")
    return bytes(out)


def main(argv):
    cmd = argv[1]
    if cmd == "next-header":
        try:
            walk(load_pieces(argv[2]))
        except NeedBytes as need:
            print(f"NEED {need.start} {need.end}")
            return 0
        print("DONE")
        return 0
    if cmd == "layout":
        print(json.dumps(walk(load_pieces(argv[2])), sort_keys=True))
        return 0
    if cmd == "ranges":
        with open(argv[2]) as fh:
            layout = json.load(fh)
        for k, row0, row1, spec in plan_ranges(layout, int(argv[3])):
            print(k, row0, row1, spec)
        return 0
    if cmd == "ingest":
        layout_path, k, row0, row1, hdr_file, body_file, out_file, etag, size = argv[2:11]
        with open(layout_path) as fh:
            layout = json.load(fh)
        with open(hdr_file, encoding="latin-1") as fh:
            status, headers = parse_http_headers(fh.read())
        with open(body_file, "rb") as fh:
            body = fh.read()
        try:
            data = ingest(layout, int(row0), int(row1), status, headers, body, etag, int(size))
        except EtagChanged as exc:
            print(f"ingest rejected: {exc}", file=sys.stderr)
            return 4
        except ValueError as exc:
            print(f"ingest rejected: {exc}", file=sys.stderr)
            return 3
        with open(out_file + ".tmp", "wb") as fh:
            fh.write(data)
        os.replace(out_file + ".tmp", out_file)
        print(f"ingested batch={k} rows={row0}-{row1} bytes={len(data)}")
        return 0
    raise SystemExit(f"unknown command {cmd}")


if __name__ == "__main__":
    sys.exit(main(sys.argv))
