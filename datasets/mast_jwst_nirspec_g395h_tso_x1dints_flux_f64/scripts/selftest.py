#!/usr/bin/env python3
"""Self-test on a synthetic x1dints-like FITS file (no network, stdlib only).

Checks: the sparse header walker (x1dints.py) and the independent walker (verify.py) on
header pieces split at awkward offsets and with a multi-block INT_TIMES table in between;
FLUX column location from TTYPE/TFORM; range planning; multipart/byteranges parsing with
CRLF and LF framing; single-range 206 fallback; rejection of HTTP 200, missing/extra parts,
wrong extents, ETag and size changes; the FLUX payload policy; byte order conversion.
"""
import array
import json
import math
import os
import random
import struct
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import check_payload  # noqa: E402
import verify  # noqa: E402
import x1dints  # noqa: E402


def card(key, value=None, comment=""):
    if value is None:
        return f"{key:<80}"[:80]
    if isinstance(value, bool):
        v = f"{'T' if value else 'F':>20}"
    elif isinstance(value, int):
        v = f"{value:>20}"
    else:
        esc = value.replace("'", "''")
        v = f"'{esc:<8}'"
        v = f"{v:<20}"
    return f"{key:<8}= {v} / {comment}"[:80].ljust(80)


def header(cards):
    text = "".join(cards) + "END".ljust(80)
    pad = (-len(text)) % 2880
    return (text + " " * pad).encode("ascii")


def pad_data(b):
    return b + b"\0" * ((-len(b)) % 2880)


def synth(nrows, nbins, filename, rng):
    prim = header([
        card("SIMPLE", True), card("BITPIX", 8), card("NAXIS", 0), card("EXTEND", True),
        card("FILENAME", filename), card("DATAMODL", "TSOMultiSpecModel"), card("TELESCOP", "JWST"),
        card("INSTRUME", "NIRSPEC"), card("DETECTOR", "NRS1"), card("FILTER", "F290LP"),
        card("GRATING", "G395H"), card("FXD_SLIT", "S1600A1"), card("EXP_TYPE", "NRS_BRIGHTOBJ"),
        card("SUBARRAY", "SUB2048"), card("READPATT", "NRSRAPID"), card("NINTS", nrows * 3),
        card("INTSTART", 1), card("INTEND", nrows), card("NGROUPS", 7), card("EXSEGNUM", 1),
        card("EXSEGTOT", 3), card("PROGRAM", "09999"), card("OBSERVTN", "001"), card("VISIT", "001"),
        card("EXPOSURE", "1"), card("TARGNAME", "SYNTH O'STAR"), card("DATE-OBS", "2026-01-01"),
        card("TIME-OBS", "00:00:00"), card("CAL_VER", "3.0.0"), card("SDP_VER", "2026_2a"),
        card("CRDS_CTX", "jwst_1584.pmap"), card("CRDS_VER", "13.1.13"), card("TSOVISIT", True),
    ] + [card("COMMENT", None) for _ in range(60)])
    it_rows = nrows * 3
    it_hdr = header([
        card("XTENSION", "BINTABLE"), card("BITPIX", 8), card("NAXIS", 2), card("NAXIS1", 12),
        card("NAXIS2", it_rows), card("PCOUNT", 0), card("GCOUNT", 1), card("TFIELDS", 2),
        card("EXTNAME", "INT_TIMES"), card("TTYPE1", "integration_number"), card("TFORM1", "J"),
        card("TTYPE2", "int_mid_MJD_UTC"), card("TFORM2", "D"),
    ])
    it_data = pad_data(b"".join(struct.pack(">id", i + 1, 60000.0 + i) for i in range(it_rows)))
    cols = [("INT_NUM", "J", ""), ("WAVELENGTH", f"{nbins}D", "um"), ("FLUX", f"{nbins}D", "Jy"),
            ("FLUX_ERROR", f"{nbins}D", "Jy"), ("DQ", f"{nbins}J", ""), ("SEGMENT", "J", ""),
            ("MJD-AVG", "D", "")]
    naxis1 = 4 + 8 * nbins * 3 + 4 * nbins + 4 + 8
    e_cards = [card("XTENSION", "BINTABLE"), card("BITPIX", 8), card("NAXIS", 2), card("NAXIS1", naxis1),
               card("NAXIS2", nrows), card("PCOUNT", 0), card("GCOUNT", 1), card("TFIELDS", len(cols)),
               card("EXTNAME", "EXTRACT1D")]
    for i, (name, form, unit) in enumerate(cols, 1):
        e_cards += [card(f"TTYPE{i}", name), card(f"TFORM{i}", form)]
        if unit:
            e_cards.append(card(f"TUNIT{i}", unit))
    e_hdr = header(e_cards)
    flux_rows = []
    rows = bytearray()
    for r in range(nrows):
        flux = [float("nan") if (b < 3 or b >= nbins - 2) else 0.03 + rng.gauss(0, 1e-4) for b in range(nbins)]
        if r == 1:
            flux[nbins // 2] = -5494.8  # native outlier, must survive untouched
        flux_rows.append(flux)
        rows += struct.pack(">i", r + 1)
        rows += struct.pack(f">{nbins}d", *[2.87 + 0.0007 * b for b in range(nbins)])
        rows += struct.pack(f">{nbins}d", *flux)
        rows += struct.pack(f">{nbins}d", *[1e-4] * nbins)
        rows += struct.pack(f">{nbins}i", *[0] * nbins)
        rows += struct.pack(">id", 1, 60000.5)
    assert len(rows) == naxis1 * nrows
    blob = prim + it_hdr + it_data + e_hdr + pad_data(bytes(rows))
    return blob, flux_rows, len(prim) + len(it_hdr) + len(it_data) + len(e_hdr)


def fetch_headers(blob, piece_dir):
    """Emulate download.sh's walk loop (truncated last piece like a server near EOF)."""
    for _ in range(20):
        try:
            x1dints.walk(x1dints.load_pieces(piece_dir))
            return
        except x1dints.NeedBytes as need:
            with open(os.path.join(piece_dir, f"{need.start}.bin"), "wb") as fh:
                fh.write(blob[need.start:need.end + 1])
    raise AssertionError("walker did not converge")


def multipart(blob, spec, boundary, newline=b"\r\n", total=None, reorder=False):
    parts = []
    for rng_ in spec.split(","):
        a, b = (int(x) for x in rng_.split("-"))
        parts.append((a, b))
    if reorder:
        parts.reverse()
    out = bytearray()
    for a, b in parts:
        out += newline + b"--" + boundary.encode() + newline
        out += b"Content-Type: application/octet-stream" + newline
        out += f"Content-Range: bytes {a}-{b}/{total or len(blob)}".encode() + newline + newline
        out += blob[a:b + 1]
    out += newline + b"--" + boundary.encode() + b"--" + newline
    return bytes(out)


def expect_fail(fn, *a, exc=ValueError):
    try:
        fn(*a)
    except exc:
        return
    raise AssertionError(f"{fn.__name__} accepted invalid input")


def main():
    rng = random.Random(1234)
    fn = "jw09999001001_04102_00001-seg001_nrs1_x1dints.fits"
    nrows, nbins = 37, 1273
    blob, flux_rows, data_off = synth(nrows, nbins, fn, rng)
    with tempfile.TemporaryDirectory() as tmp:
        pdir = os.path.join(tmp, "hdr")
        os.mkdir(pdir)
        fetch_headers(blob, pdir)
        lay = x1dints.walk(x1dints.load_pieces(pdir))
        assert lay["extract1d"]["data_offset"] == data_off, lay["extract1d"]["data_offset"]
        assert [h["name"] for h in lay["hdus"]] == ["PRIMARY", "INT_TIMES", "EXTRACT1D"]
        assert lay["primary"]["TARGNAME"] == "SYNTH O'STAR"
        foff, nb, unit, _ = x1dints.flux_layout(lay)
        assert (foff, nb, unit) == (4 + 8 * nbins, nbins, "Jy")
        assert x1dints.regime_problems(lay, fn, len(blob)) == [], x1dints.regime_problems(lay, fn, len(blob))
        bad = json.loads(json.dumps(lay))
        bad["primary"]["DETECTOR"] = "NRS2"
        assert x1dints.regime_problems(bad, fn, len(blob))
        # independent walker agrees
        prim, geo = verify.extract1d_geometry(pdir)
        assert geo == {"data_offset": data_off, "naxis1": lay["extract1d"]["naxis1"], "naxis2": nrows,
                       "flux_offset": foff, "nbins": nbins}, geo
        assert prim["FILENAME"] == fn and prim["INTEND"] == nrows
        etag, size = "abc-123", len(blob)
        hdrs_mp = {"content-type": "multipart/byteranges; boundary=00000000000000169733", "etag": f'"{etag}"'}
        out = bytearray()
        batches = x1dints.plan_ranges(lay, 10)
        assert len(batches) == 4 and batches[-1][1:3] == (30, 37)
        for k, row0, row1, spec in batches:
            body = multipart(blob, spec, "00000000000000169733", reorder=(k == 1),
                             newline=b"\n" if k == 2 else b"\r\n")
            out += x1dints.ingest(lay, row0, row1, 206, hdrs_mp, body, etag, size)
        expected = b"".join(struct.pack(f">{nbins}d", *r) for r in flux_rows)
        assert bytes(out) == expected
        # single-range fallback (a one-row batch answered without multipart)
        k, row0, row1, spec = x1dints.plan_ranges(lay, 1)[5]
        a, b = (int(x) for x in spec.split("-"))
        single = {"content-type": "application/octet-stream", "content-range": f"bytes {a}-{b}/{size}",
                  "etag": f'"{etag}"'}
        assert x1dints.ingest(lay, row0, row1, 206, single, blob[a:b + 1], etag, size) == expected[
            5 * 8 * nbins:6 * 8 * nbins]
        # rejections
        k, row0, row1, spec = batches[0]
        good = multipart(blob, spec, "00000000000000169733")
        expect_fail(x1dints.ingest, lay, row0, row1, 200, hdrs_mp, good, etag, size)
        expect_fail(x1dints.ingest, lay, row0, row1, 206, hdrs_mp, good, "other", size, exc=x1dints.EtagChanged)
        expect_fail(x1dints.ingest, lay, row0, row1, 206, hdrs_mp, good, etag, size + 46080)
        expect_fail(x1dints.ingest, lay, row0, row1 + 1, 206, hdrs_mp, good, etag, size)  # missing row
        expect_fail(x1dints.ingest, lay, row0 + 1, row1, 206, hdrs_mp, good, etag, size)  # extra part
        expect_fail(x1dints.ingest, lay, row0, row1, 206, hdrs_mp, good[:-200], etag, size)  # truncated
        shifted = ",".join(f"{int(r.split('-')[0]) + 8}-{int(r.split('-')[1]) + 8}" for r in spec.split(","))
        expect_fail(x1dints.ingest, lay, row0, row1, 206, hdrs_mp, multipart(blob, shifted, "00000000000000169733"),
                    etag, size)
        expect_fail(x1dints.ingest, lay, row0, row1, 206, {"content-type": "multipart/byteranges", "etag": etag},
                    good, etag, size)
        # http header dump parsing (proxy CONNECT block first, then the real response)
        dump = ("HTTP/1.1 200 Connection established\r\nVia: proxy\r\n\r\n"
                "HTTP/2 206 \r\ncontent-type: multipart/byteranges; boundary=xyz\r\netag: \"e1\"\r\n\r\n")
        st, h = x1dints.parse_http_headers(dump)
        assert st == 206 and h["etag"] == '"e1"' and h["content-type"].endswith("boundary=xyz")
        # payload policy + byte-order conversion
        fpath = os.path.join(tmp, "f.be")
        with open(fpath, "wb") as fh:
            fh.write(expected)
        lpath = os.path.join(tmp, "layout.json")
        with open(lpath, "w") as fh:
            json.dump(lay, fh)
        check_payload.check_flux(lpath, fpath)
        allnan = bytearray(expected)
        allnan[0:8 * nbins] = struct.pack(f">{nbins}d", *[float("nan")] * nbins)
        with open(fpath, "wb") as fh:
            fh.write(allnan)
        expect_fail(check_payload.check_flux, lpath, fpath, exc=check_payload.PayloadError)
        vals = array.array("d")
        vals.frombytes(expected)
        if sys.byteorder == "little":
            vals.byteswap()
        le = vals.tobytes()
        ref = b"".join(struct.pack(f"<{nbins}d", *r) for r in flux_rows)
        assert le == ref
        assert struct.unpack_from("<d", le, (1 * nbins + nbins // 2) * 8)[0] == -5494.8
        assert math.isnan(struct.unpack_from("<d", le, 0)[0])
    print("selftest ok: header walkers, range plan, multipart/single-range ingest, rejections, payload policy, byte order")


if __name__ == "__main__":
    main()
