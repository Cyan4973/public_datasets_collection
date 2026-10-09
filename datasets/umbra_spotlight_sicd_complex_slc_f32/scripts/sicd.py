"""Minimal pure-stdlib NITF 2.1 + SICD XML parser for Umbra SICD products.

Only what the recipe needs: the NITF file header segment table, the image
subheader fields that pin the pixel layout, the SICD XML DES, and a handful
of SICD metadata fields.  All functions take a ``read(offset, n) -> bytes``
callable so they work on a local file or on sparse range-probe fragments.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET

# ---------------------------------------------------------------- NITF header

FHDR_FIXED = [
    ("FHDR", 4), ("FVER", 5), ("CLEVEL", 2), ("STYPE", 4), ("OSTAID", 10),
    ("FDT", 14), ("FTITLE", 80), ("FSCLAS", 1), ("FSCLSY", 2), ("FSCODE", 11),
    ("FSCTLH", 2), ("FSREL", 20), ("FSDCTP", 2), ("FSDCDT", 8), ("FSDCXM", 4),
    ("FSDG", 1), ("FSDGDT", 8), ("FSCLTX", 43), ("FSCATP", 1), ("FSCAUT", 40),
    ("FSCRSN", 1), ("FSSRDT", 8), ("FSCTLN", 15), ("FSCOP", 5), ("FSCPYS", 5),
    ("ENCRYP", 1), ("FBKGC", 3), ("ONAME", 24), ("OPHONE", 18), ("FL", 12),
    ("HL", 6),
]


class NitfError(ValueError):
    pass


class _Cursor:
    def __init__(self, buf: bytes, base: int = 0):
        self.buf = buf
        self.pos = 0
        self.base = base

    def take(self, n: int) -> bytes:
        if self.pos + n > len(self.buf):
            raise NitfError(f"truncated header at offset {self.base + self.pos} (+{n})")
        out = self.buf[self.pos:self.pos + n]
        self.pos += n
        return out

    def s(self, n: int) -> str:
        return self.take(n).decode("ascii", "strict")

    def i(self, n: int) -> int:
        txt = self.s(n)
        if not txt.strip().isdigit():
            raise NitfError(f"non-numeric field {txt!r} at offset {self.base + self.pos - n}")
        return int(txt)


def parse_file_header(read) -> dict:
    head = read(0, 360)
    cur = _Cursor(head)
    hdr = {}
    for name, n in FHDR_FIXED:
        hdr[name] = cur.s(n)
    if hdr["FHDR"] != "NITF" or hdr["FVER"] != "02.10":
        raise NitfError(f"not NITF 2.1: {hdr['FHDR']!r} {hdr['FVER']!r}")
    hl = int(hdr["HL"])
    fl = int(hdr["FL"])
    buf = read(0, hl)
    cur = _Cursor(buf)
    cur.pos = 360

    def table(count_w, sub_w, len_w):
        n = cur.i(count_w)
        return [(cur.i(sub_w), cur.i(len_w)) for _ in range(n)]

    images = table(3, 6, 10)
    graphics = table(3, 4, 6)
    numx = cur.i(3)
    if numx != 0:
        raise NitfError("NUMX must be 0")
    texts = table(3, 4, 5)
    des = table(3, 4, 9)
    res = table(3, 4, 7)
    if cur.pos > hl:
        raise NitfError("segment table overruns HL")
    # Segment offsets.
    off = hl
    segs = {"image": [], "graphic": [], "text": [], "des": [], "res": []}
    for kind, tab in (("image", images), ("graphic", graphics), ("text", texts),
                      ("des", des), ("res", res)):
        for sub_len, data_len in tab:
            segs[kind].append({"subheader_offset": off, "subheader_length": sub_len,
                               "data_offset": off + sub_len, "data_length": data_len})
            off += sub_len + data_len
    if off != fl:
        raise NitfError(f"segment lengths sum to {off}, FL={fl}")
    return {"FL": fl, "HL": hl, "FTITLE": hdr["FTITLE"].strip(), "FDT": hdr["FDT"],
            "OSTAID": hdr["OSTAID"].strip(), "segments": segs}


def parse_image_subheader(read, seg: dict) -> dict:
    buf = read(seg["subheader_offset"], seg["subheader_length"])
    cur = _Cursor(buf, seg["subheader_offset"])
    out = {}
    out["IM"] = cur.s(2)
    if out["IM"] != "IM":
        raise NitfError("image subheader does not start with IM")
    out["IID1"] = cur.s(10).strip()
    out["IDATIM"] = cur.s(14)
    cur.take(17)  # TGTID
    out["IID2"] = cur.s(80).strip()
    # security block ISCLAS..ISCTLN = 1+2+11+2+20+2+8+4+1+8+43+1+40+1+8+15
    cur.take(167)
    out["ENCRYP"] = cur.s(1)
    cur.take(42)  # ISORCE
    out["NROWS"] = cur.i(8)
    out["NCOLS"] = cur.i(8)
    out["PVTYPE"] = cur.s(3).strip()
    out["IREP"] = cur.s(8).strip()
    out["ICAT"] = cur.s(8).strip()
    out["ABPP"] = cur.i(2)
    out["PJUST"] = cur.s(1)
    out["ICORDS"] = cur.s(1)
    if out["ICORDS"] != " ":
        out["IGEOLO"] = cur.s(60)
    nicom = cur.i(1)
    for _ in range(nicom):
        cur.take(80)
    out["IC"] = cur.s(2)
    if out["IC"] not in ("NC", "NM"):
        cur.take(4)  # COMRAT
    nbands = cur.i(1)
    if nbands == 0:
        nbands = cur.i(5)
    out["NBANDS"] = nbands
    bands = []
    for _ in range(nbands):
        irepband = cur.s(2).strip()
        isubcat = cur.s(6).strip()
        cur.take(1)  # IFC
        cur.take(3)  # IMFLT
        nluts = cur.i(1)
        if nluts:
            nelut = cur.i(5)
            cur.take(nluts * nelut)
        bands.append({"IREPBAND": irepband, "ISUBCAT": isubcat, "NLUTS": nluts})
    out["bands"] = bands
    out["ISYNC"] = cur.i(1)
    out["IMODE"] = cur.s(1)
    out["NBPR"] = cur.i(4)
    out["NBPC"] = cur.i(4)
    out["NPPBH"] = cur.i(4)
    out["NPPBV"] = cur.i(4)
    out["NBPP"] = cur.i(2)
    out["IDLVL"] = cur.i(3)
    out["IALVL"] = cur.i(3)
    out["ILOC"] = cur.s(10)
    out["IMAG"] = cur.s(4)
    udidl = cur.i(5)
    if udidl:
        cur.take(udidl)
    ixshdl = cur.i(5)
    if ixshdl:
        cur.take(ixshdl)
    if cur.pos != len(buf):
        raise NitfError(f"image subheader parsed {cur.pos} of {len(buf)} bytes")
    return out


def parse_des_subheader(read, seg: dict) -> dict:
    buf = read(seg["subheader_offset"], seg["subheader_length"])
    cur = _Cursor(buf, seg["subheader_offset"])
    if cur.s(2) != "DE":
        raise NitfError("DES subheader does not start with DE")
    desid = cur.s(25).strip()
    desver = cur.i(2)
    return {"DESID": desid, "DESVER": desver}


# ------------------------------------------------------------------ SICD XML

NS = "{urn:SICD:1.2.1}"


def _find(root, path: str):
    el = root.find("/".join(NS + p for p in path.split("/")))
    if el is None:
        raise NitfError(f"SICD XML lacks {path}")
    return el


def _text(root, path: str) -> str:
    return (_find(root, path).text or "").strip()


def parse_sicd_xml(xml_bytes: bytes) -> dict:
    root = ET.fromstring(xml_bytes)
    if root.tag != NS + "SICD":
        raise NitfError(f"root element {root.tag!r} is not SICD 1.2.1")
    vd = _find(root, "ImageData/ValidData")
    poly = []
    for v in vd.findall(NS + "Vertex"):
        poly.append((int(v.find(NS + "Index").text) if v.find(NS + "Index") is not None else int(v.get("index")),
                     int(v.find(NS + "Row").text), int(v.find(NS + "Col").text)))
    poly.sort()
    out = {
        "collector": _text(root, "CollectionInfo/CollectorName"),
        "core_name": _text(root, "CollectionInfo/CoreName"),
        "collect_type": _text(root, "CollectionInfo/CollectType"),
        "mode_type": _text(root, "CollectionInfo/RadarMode/ModeType"),
        "application": _text(root, "ImageCreation/Application"),
        "pixel_type": _text(root, "ImageData/PixelType"),
        "num_rows": int(_text(root, "ImageData/NumRows")),
        "num_cols": int(_text(root, "ImageData/NumCols")),
        "first_row": int(_text(root, "ImageData/FirstRow")),
        "first_col": int(_text(root, "ImageData/FirstCol")),
        "full_rows": int(_text(root, "ImageData/FullImage/NumRows")),
        "full_cols": int(_text(root, "ImageData/FullImage/NumCols")),
        "image_form_algo": _text(root, "ImageFormation/ImageFormAlgo"),
        "tx_polarization": _text(root, "ImageFormation/TxRcvPolarizationProc"),
        "scp_lat": float(_text(root, "GeoData/SCP/LLH/Lat")),
        "scp_lon": float(_text(root, "GeoData/SCP/LLH/Lon")),
        "row_ss": float(_text(root, "Grid/Row/SS")),
        "col_ss": float(_text(root, "Grid/Col/SS")),
        "row_imp_resp_wid": float(_text(root, "Grid/Row/ImpRespWid")),
        "col_imp_resp_wid": float(_text(root, "Grid/Col/ImpRespWid")),
        "grid_type": _text(root, "Grid/Type"),
        "tx_freq_min": float(_text(root, "RadarCollection/TxFrequency/Min")),
        "tx_freq_max": float(_text(root, "RadarCollection/TxFrequency/Max")),
        "valid_polygon": [(r, c) for _, r, c in poly],
    }
    return out


def processor_version(application: str) -> str:
    m = re.search(r"Umbra (?:Image Formation )?processor (\d+(?:\.\d+)+)", application)
    if not m:
        raise NitfError(f"unexpected ImageCreation/Application {application!r}")
    return m.group(1)


def polygon_area(poly) -> float:
    a = 0.0
    n = len(poly)
    for k in range(n):
        r0, c0 = poly[k]
        r1, c1 = poly[(k + 1) % n]
        a += r0 * c1 - r1 * c0
    return abs(a) / 2.0


def row_spans(poly, nrows: int):
    """Per image row, the [c_lo, c_hi] interval of the (convex) ValidData
    polygon intersected with that row centre line, or None.  Used only for
    the zero-fill diagnostic; never alters samples."""
    spans = []
    n = len(poly)
    for r in range(nrows):
        xs = []
        for k in range(n):
            r0, c0 = poly[k]
            r1, c1 = poly[(k + 1) % n]
            if r0 == r1:
                if r == r0:
                    xs.extend((c0, c1))
                continue
            lo, hi = (r0, r1) if r0 < r1 else (r1, r0)
            if lo <= r <= hi:
                xs.append(c0 + (r - r0) * (c1 - c0) / (r1 - r0))
        spans.append((min(xs), max(xs)) if xs else None)
    return spans


# ----------------------------------------------------------- whole-file check

def inspect(read) -> dict:
    """Parse and return all structure needed to extract the pixel array."""
    fh = parse_file_header(read)
    segs = fh["segments"]
    info = {"FL": fh["FL"], "HL": fh["HL"], "FTITLE": fh["FTITLE"],
            "NUMI": len(segs["image"]), "NUMS": len(segs["graphic"]),
            "NUMT": len(segs["text"]), "NUMDES": len(segs["des"]),
            "NUMRES": len(segs["res"])}
    if info["NUMI"] != 1:
        raise NitfError(f"NUMI={info['NUMI']} (need exactly 1)")
    if info["NUMDES"] != 1:
        raise NitfError(f"NUMDES={info['NUMDES']} (need exactly 1)")
    img = segs["image"][0]
    ish = parse_image_subheader(read, img)
    des = segs["des"][0]
    dsh = parse_des_subheader(read, des)
    if dsh["DESID"] != "XML_DATA_CONTENT":
        raise NitfError(f"DESID={dsh['DESID']!r}")
    xml_raw = read(des["data_offset"], des["data_length"])
    sicd = parse_sicd_xml(xml_raw)
    info.update({
        "image_data_offset": img["data_offset"],
        "image_data_length": img["data_length"],
        "image_subheader": ish,
        "des_data_offset": des["data_offset"],
        "des_data_length": des["data_length"],
        "sicd": sicd,
    })
    return info


def assert_regime(info: dict, version_prefix: str = "0.6.") -> None:
    """Raise NitfError unless the product is the pinned SICD regime."""
    ish = info["image_subheader"]
    s = info["sicd"]
    checks = [
        (ish["IID1"] == "SICD000", f"IID1={ish['IID1']!r}"),
        (ish["ENCRYP"] == "0", "ENCRYP"),
        (ish["PVTYPE"] == "R", f"PVTYPE={ish['PVTYPE']!r}"),
        (ish["IREP"] == "NODISPLY", f"IREP={ish['IREP']!r}"),
        (ish["ICAT"] == "SAR", f"ICAT={ish['ICAT']!r}"),
        (ish["ABPP"] == 32 and ish["NBPP"] == 32, f"ABPP/NBPP={ish['ABPP']}/{ish['NBPP']}"),
        (ish["IC"] == "NC", f"IC={ish['IC']!r}"),
        (ish["NBANDS"] == 2, f"NBANDS={ish['NBANDS']}"),
        ([b["ISUBCAT"] for b in ish["bands"]] == ["I", "Q"],
         f"ISUBCAT={[b['ISUBCAT'] for b in ish['bands']]}"),
        (all(b["NLUTS"] == 0 for b in ish["bands"]), "band LUTs present"),
        (ish["IMODE"] == "P", f"IMODE={ish['IMODE']!r}"),
        (ish["NBPR"] == 1 and ish["NBPC"] == 1, f"NBPR/NBPC={ish['NBPR']}/{ish['NBPC']}"),
        (ish["NPPBH"] in (0, ish["NCOLS"]) and ish["NPPBV"] in (0, ish["NROWS"]),
         f"NPPBH/NPPBV={ish['NPPBH']}/{ish['NPPBV']}"),
        (ish["IALVL"] == 0 and ish["ILOC"] == "0000000000", "attachment/location"),
        (s["pixel_type"] == "RE32F_IM32F", f"PixelType={s['pixel_type']!r}"),
        (s["mode_type"] == "SPOTLIGHT", f"ModeType={s['mode_type']!r}"),
        (s["collect_type"] == "MONOSTATIC", f"CollectType={s['collect_type']!r}"),
        (s["image_form_algo"] == "PFA", f"ImageFormAlgo={s['image_form_algo']!r}"),
        (s["grid_type"] == "RGAZIM", f"Grid/Type={s['grid_type']!r}"),
        (s["collector"].startswith("Umbra-"), f"CollectorName={s['collector']!r}"),
        (processor_version(s["application"]).startswith(version_prefix),
         f"processor={s['application']!r}"),
        (s["first_row"] == 0 and s["first_col"] == 0 and s["full_rows"] == s["num_rows"]
         and s["full_cols"] == s["num_cols"], "not a full image"),
        # SICD rows run along the NITF column axis? No: SICD NumRows == NITF NROWS.
        (ish["NROWS"] == s["num_rows"] and ish["NCOLS"] == s["num_cols"],
         f"NITF {ish['NROWS']}x{ish['NCOLS']} vs SICD {s['num_rows']}x{s['num_cols']}"),
        (info["image_data_length"] == s["num_rows"] * s["num_cols"] * 8,
         f"image bytes {info['image_data_length']} != rows*cols*8"),
        (8.0e9 < s["tx_freq_min"] < s["tx_freq_max"] < 12.0e9, "not X band"),
    ]
    bad = [msg for ok, msg in checks if not ok]
    if bad:
        raise NitfError("regime mismatch: " + "; ".join(bad))


def file_reader(path: str):
    fh = open(path, "rb")

    def read(off: int, n: int) -> bytes:
        fh.seek(off)
        b = fh.read(n)
        if len(b) != n:
            raise NitfError(f"short read at {off}+{n}")
        return b

    read.close = fh.close  # type: ignore[attr-defined]
    return read
