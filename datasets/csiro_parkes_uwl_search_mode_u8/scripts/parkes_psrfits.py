#!/usr/bin/env python3
"""PSRFITS SEARCH-mode helpers for csiro_parkes_uwl_search_mode_u8.

Pure standard library. Subcommands:

  check-collection  validate a DAP collection metadata JSON (public, CC BY 4.0)
  resolve-url       pick the presigned link for one pinned file from a DAP
                    /collections/<id>/data JSON (exact id, filename, fileSize)
  check-range       validate a curl --dump-header file for an exact 206 range
  check-header      validate a downloaded FITS header range (bytes 0..25919)
  check-row         validate one downloaded SUBINT row (aux columns + DATA)
  build             de-interleave each pinned row into four uint8 planes

The DATA cell of one SUBINT row has TDIM '(NCHAN,NPOL,NSBLK)'. FITS TDIM is
Fortran-ordered (first axis fastest), so the bytes are laid out as
[time][polarization][channel] with channel fastest.
"""
from __future__ import annotations

import argparse
import collections
import csv
import hashlib
import json
import math
import os
import re
import struct
import sys
from pathlib import Path

DATASET_ID = "csiro_parkes_uwl_search_mode_u8"
BLOCK = 2880
CARD = 80

# Expected instrument configuration for every pinned file.
CONFIG: dict[str, object] = {
    "nchan": 3328,
    "npol": 4,
    "nsblk": 4096,
    "nbits": 8,
    "naxis2": 224,
    "tbin": 0.000128,
    "chan_bw": 1.0,
    "obsfreq": 2368.0,
    "first_chan_freq": 704.5,
    "zero_off": 127.5,
    "pol_type": "AABBCRCI",
    "header_bytes": 25920,
    "row_bytes": 54792232,
    "data_col_offset": 266280,
    "primary_cards": {
        "FITSTYPE": "PSRFITS",
        "TELESCOP": "Parkes",
        "PROJID": "P1018",
        "FRONTEND": "UWL",
        "BACKEND": "Medusa",
        "OBS_MODE": "SEARCH",
        "SRC_NAME": "ProxCen_S",
        "TRK_MODE": "TRACK",
        "CAL_MODE": "OFF",
    },
    "subint_columns": [
        "INDEXVAL", "TSUBINT", "OFFS_SUB", "AUX_DM", "AUX_RM",
        "DAT_FREQ", "DAT_WTS", "DAT_OFFS", "DAT_SCL", "DATA",
    ],
}

POL_SERIES = {
    "AA": "parkes_uwl_search_aa_u8",
    "BB": "parkes_uwl_search_bb_u8",
    "CR": "parkes_uwl_search_cr_u8",
    "CI": "parkes_uwl_search_ci_u8",
}

TFORM_WIDTH = {"L": 1, "B": 1, "I": 2, "J": 4, "K": 8, "A": 1, "E": 4, "D": 8, "C": 8, "M": 16}


def fail(message: str) -> None:
    raise SystemExit(f"FATAL: {message}")


# --------------------------------------------------------------------------
# FITS header parsing
# --------------------------------------------------------------------------

def parse_value(raw: str) -> object:
    text = raw.strip()
    if text.startswith("'"):
        out = []
        i = 1
        while i < len(text):
            ch = text[i]
            if ch == "'":
                if i + 1 < len(text) and text[i + 1] == "'":
                    out.append("'")
                    i += 2
                    continue
                break
            out.append(ch)
            i += 1
        return "".join(out).rstrip()
    text = text.split("/", 1)[0].strip()
    if text in ("T", "F"):
        return text == "T"
    try:
        if re.fullmatch(r"[+-]?\d+", text):
            return int(text)
        return float(text.replace("D", "E"))
    except ValueError:
        return text


def parse_hdus(blob: bytes, stop_extname: str = "SUBINT") -> list[dict]:
    """Walk FITS HDUs in ``blob`` until the header of ``stop_extname`` ends."""
    offset = 0
    hdus: list[dict] = []
    while True:
        start = offset
        cards: dict[str, object] = {}
        ended = False
        while not ended:
            block = blob[offset : offset + BLOCK]
            if len(block) != BLOCK:
                fail(f"FITS header truncated at byte {offset}")
            offset += BLOCK
            for i in range(0, BLOCK, CARD):
                card = block[i : i + CARD]
                try:
                    text = card.decode("ascii")
                except UnicodeDecodeError:
                    fail(f"non-ASCII FITS card near byte {offset - BLOCK + i}")
                key = text[:8].rstrip()
                if key == "END":
                    ended = True
                    break
                if text[8:10] == "= " and key not in cards:
                    cards[key] = parse_value(text[10:])
        if not hdus and cards.get("SIMPLE") is not True:
            fail("first HDU is not a FITS primary header (SIMPLE != T)")
        naxis = int(cards.get("NAXIS", 0))
        size = 0
        if naxis:
            size = 1
            for axis in range(1, naxis + 1):
                size *= int(cards[f"NAXIS{axis}"])
            size = abs(int(cards.get("BITPIX", 8))) // 8 * int(cards.get("GCOUNT", 1)) * (
                int(cards.get("PCOUNT", 0)) + size
            )
        hdus.append({"cards": cards, "header_start": start, "data_start": offset, "data_size": size})
        if cards.get("EXTNAME") == stop_extname:
            return hdus
        offset += (size + BLOCK - 1) // BLOCK * BLOCK
        if len(hdus) > 16:
            fail(f"no {stop_extname} HDU within the first 16 HDUs")


def tform_width(tform: str) -> int:
    match = re.fullmatch(r"(\d*)([A-Z])(.*)", tform.strip())
    if not match:
        fail(f"unparseable TFORM {tform!r}")
    repeat = int(match.group(1)) if match.group(1) else 1
    code = match.group(2)
    if code == "X":
        return (repeat + 7) // 8
    if code not in TFORM_WIDTH:
        fail(f"unsupported TFORM type {code!r} in {tform!r}")
    return repeat * TFORM_WIDTH[code]


def subint_layout(cards: dict) -> dict:
    """Column offsets/widths computed from TTYPEn/TFORMn."""
    nfields = int(cards["TFIELDS"])
    columns = {}
    offset = 0
    names = []
    for n in range(1, nfields + 1):
        name = str(cards[f"TTYPE{n}"])
        width = tform_width(str(cards[f"TFORM{n}"]))
        columns[name] = {"offset": offset, "width": width, "tform": str(cards[f"TFORM{n}"]), "n": n}
        names.append(name)
        offset += width
    return {"columns": columns, "names": names, "row_bytes": offset}


def close(a: float, b: float, tol: float = 1e-9) -> bool:
    return abs(float(a) - float(b)) <= tol * max(1.0, abs(float(b)))


def validate_header(blob: bytes, file_size: int, date_obs: str, cfg: dict = CONFIG) -> dict:
    hdus = parse_hdus(blob)
    primary = hdus[0]["cards"]
    subint_hdu = hdus[-1]
    sub = subint_hdu["cards"]
    for key, expected in cfg["primary_cards"].items():
        if primary.get(key) != expected:
            fail(f"primary card {key}={primary.get(key)!r}, expected {expected!r}")
    if date_obs and primary.get("DATE-OBS") != date_obs:
        fail(f"DATE-OBS={primary.get('DATE-OBS')!r}, expected {date_obs!r}")
    if not close(primary.get("OBSFREQ", -1), cfg["obsfreq"]):
        fail(f"OBSFREQ={primary.get('OBSFREQ')!r}")
    if int(primary.get("OBSNCHAN", -1)) != cfg["nchan"]:
        fail(f"OBSNCHAN={primary.get('OBSNCHAN')!r}")
    if sub.get("XTENSION") != "BINTABLE":
        fail("SUBINT HDU is not a BINTABLE")
    nchan, npol, nsblk, nbits = cfg["nchan"], cfg["npol"], cfg["nsblk"], cfg["nbits"]
    int_checks = {"NBITS": nbits, "SIGNINT": 0, "NPOL": npol, "NCHAN": nchan, "NSBLK": nsblk,
                  "NAXIS2": cfg["naxis2"], "PCOUNT": 0, "GCOUNT": 1, "BITPIX": 8}
    for key, expected in int_checks.items():
        if int(sub.get(key, -1)) != expected:
            fail(f"SUBINT card {key}={sub.get(key)!r}, expected {expected}")
    if sub.get("POL_TYPE") != cfg["pol_type"]:
        fail(f"POL_TYPE={sub.get('POL_TYPE')!r}")
    if not close(sub.get("TBIN", -1), cfg["tbin"]):
        fail(f"TBIN={sub.get('TBIN')!r}")
    if not close(sub.get("ZERO_OFF", -1), cfg["zero_off"]):
        fail(f"ZERO_OFF={sub.get('ZERO_OFF')!r}")
    if not close(sub.get("CHAN_BW", -1), cfg["chan_bw"]):
        fail(f"CHAN_BW={sub.get('CHAN_BW')!r}")
    layout = subint_layout(sub)
    if layout["names"] != cfg["subint_columns"]:
        fail(f"SUBINT columns {layout['names']} != {cfg['subint_columns']}")
    if layout["row_bytes"] != int(sub["NAXIS1"]):
        fail(f"sum of TFORM widths {layout['row_bytes']} != NAXIS1 {sub['NAXIS1']}")
    data_col = layout["columns"]["DATA"]
    cell = nchan * npol * nsblk * nbits // 8
    if data_col["tform"].strip() != f"{cell}B" or data_col["width"] != cell:
        fail(f"DATA TFORM {data_col['tform']!r} does not hold {cell} uint8 values")
    tdim = str(sub.get(f"TDIM{data_col['n']}", ""))
    dims = tuple(int(x) for x in re.findall(r"\d+", tdim))
    if dims != (nchan, npol, nsblk):
        fail(f"DATA TDIM {tdim!r} != ({nchan},{npol},{nsblk})")
    for name in ("DAT_FREQ", "DAT_WTS", "DAT_OFFS", "DAT_SCL"):
        col = layout["columns"][name]
        repeat = int(re.match(r"(\d*)", col["tform"]).group(1) or 1)
        if repeat < nchan or (name in ("DAT_OFFS", "DAT_SCL") and repeat < nchan * npol):
            fail(f"{name} TFORM {col['tform']!r} too short")
    if int(sub["NAXIS1"]) != cfg["row_bytes"] or data_col["offset"] != cfg["data_col_offset"]:
        fail(f"row layout changed: NAXIS1={sub['NAXIS1']} DATA offset={data_col['offset']}")
    if subint_hdu["data_start"] != cfg["header_bytes"]:
        fail(f"SUBINT data starts at {subint_hdu['data_start']}, expected {cfg['header_bytes']}")
    predicted = subint_hdu["data_start"] + int(sub["NAXIS1"]) * int(sub["NAXIS2"])
    predicted = (predicted + BLOCK - 1) // BLOCK * BLOCK
    if predicted != file_size:
        fail(f"HDU layout predicts file size {predicted}, DAP fileSize is {file_size}")
    return {
        "primary": primary,
        "subint": sub,
        "layout": layout,
        "data_start": subint_hdu["data_start"],
        "row_bytes": int(sub["NAXIS1"]),
        "nrows": int(sub["NAXIS2"]),
        "pols": [cfg["pol_type"][i : i + 2] for i in range(0, len(cfg["pol_type"]), 2)],
    }


# --------------------------------------------------------------------------
# Row validation and de-interleaving
# --------------------------------------------------------------------------

def unpack_column(row: bytes, layout: dict, name: str, code: str, count: int | None = None) -> tuple:
    col = layout["columns"][name]
    size = struct.calcsize(">" + code)
    n = col["width"] // size if count is None else count
    return struct.unpack_from(f">{n}{code}", row, col["offset"])


def validate_row(row: bytes, info: dict, row_index: int, cfg: dict = CONFIG) -> dict:
    layout = info["layout"]
    nchan, npol, nsblk = cfg["nchan"], cfg["npol"], cfg["nsblk"]
    if len(row) != info["row_bytes"]:
        fail(f"row has {len(row)} bytes, expected {info['row_bytes']}")
    if not 0 <= row_index < info["nrows"]:
        fail(f"row index {row_index} outside 0..{info['nrows'] - 1}")
    (tsubint,) = unpack_column(row, layout, "TSUBINT", "d", 1)
    (offs_sub,) = unpack_column(row, layout, "OFFS_SUB", "d", 1)
    if not close(tsubint, nsblk * cfg["tbin"], 1e-9):
        fail(f"TSUBINT {tsubint} != NSBLK*TBIN")
    if abs(offs_sub - (row_index + 0.5) * tsubint) > 1e-6:
        fail(f"OFFS_SUB {offs_sub} does not match row {row_index}")
    freq = unpack_column(row, layout, "DAT_FREQ", "d", nchan)
    for i, value in enumerate(freq):
        if abs(value - (cfg["first_chan_freq"] + i * cfg["chan_bw"])) > 1e-6:
            fail(f"DAT_FREQ[{i}]={value} breaks the 1 MHz channel grid")
    if abs((freq[0] + freq[-1]) / 2 - cfg["obsfreq"]) > cfg["chan_bw"]:
        fail("DAT_FREQ centre does not match OBSFREQ")
    wts = unpack_column(row, layout, "DAT_WTS", "f", nchan)
    if any(not math.isfinite(w) or w < 0 for w in wts):
        fail("DAT_WTS has non-finite or negative values")
    weighted = sum(1 for w in wts if w > 0)
    if weighted != nchan:
        fail(f"only {weighted}/{nchan} channels carry nonzero DAT_WTS; pinned rows must be fully weighted")
    scl = unpack_column(row, layout, "DAT_SCL", "f", nchan * npol)
    offs = unpack_column(row, layout, "DAT_OFFS", "f", nchan * npol)
    if any(not math.isfinite(v) or v <= 0 for v in scl):
        fail("DAT_SCL has non-finite or non-positive values")
    if any(not math.isfinite(v) for v in offs):
        fail("DAT_OFFS has non-finite values")
    data_off = layout["columns"]["DATA"]["offset"]
    data = memoryview(row)[data_off:]
    if len(data) != nchan * npol * nsblk:
        fail("DATA cell size mismatch")
    return {
        "tsubint": tsubint,
        "offs_sub": offs_sub,
        "weighted_channels": weighted,
        "dat_scl_min": min(scl),
        "dat_scl_max": max(scl),
        "dat_offs_min": min(offs),
        "dat_offs_max": max(offs),
        "freq_first_mhz": freq[0],
        "freq_last_mhz": freq[-1],
        "data_offset_in_row": data_off,
    }


def deinterleave(data: memoryview | bytes, nchan: int, npol: int, nsblk: int) -> list[bytes]:
    """Split a [time][pol][chan] cell into npol planes of [time][chan]."""
    stride = nchan * npol
    planes = []
    for pol in range(npol):
        base = pol * nchan
        planes.append(b"".join(data[t * stride + base : t * stride + base + nchan] for t in range(nsblk)))
    return planes


def code_stats(plane: bytes) -> dict:
    counts = collections.Counter(plane)
    total = len(plane)
    weighted = sum(value * n for value, n in counts.items())
    mode_value, mode_count = counts.most_common(1)[0]
    return {
        "min": min(counts),
        "max": max(counts),
        "mean": round(weighted / total, 6),
        "distinct_codes": len(counts),
        "mode_fraction": round(mode_count / total, 6),
        "code0_fraction": round(counts.get(0, 0) / total, 6),
        "code255_fraction": round(counts.get(255, 0) / total, 6),
    }


# --------------------------------------------------------------------------
# Helpers for download.sh
# --------------------------------------------------------------------------

def read_sources(path: Path) -> list[dict]:
    with path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t", restval=""))
    if not rows:
        fail(f"no sources in {path}")
    return rows


def sha256_bytes(blob: bytes | memoryview) -> str:
    return hashlib.sha256(blob).hexdigest()


def cmd_check_collection(args: argparse.Namespace) -> None:
    meta = json.loads(Path(args.meta).read_text(encoding="utf-8"))
    cid = int(args.collection_id)
    if int(meta.get("dataCollectionId") or 0) != cid:
        fail(f"collection id {meta.get('dataCollectionId')!r} != {cid}")
    if meta.get("doi") != args.doi:
        fail(f"collection {cid} DOI {meta.get('doi')!r} != {args.doi!r}")
    title = str(meta.get("title") or "")
    if not title.startswith("Parkes observations for project P1018 semester 2019APRS"):
        fail(f"collection {cid} title changed: {title!r}")
    if meta.get("licence") != "Creative Commons Attribution 4.0 International Licence":
        fail(f"collection {cid} licence changed: {meta.get('licence')!r}")
    if (meta.get("licenceLink") or {}).get("href") != "https://data.csiro.au/dap/ws/v2/licences/1121":
        fail(f"collection {cid} licence link changed")
    if meta.get("accessLevel") != "Public" or str(meta.get("dataRestricted")).upper() != "FALSE":
        fail(f"collection {cid} is not public/unrestricted")
    if meta.get("withdrawn") or meta.get("blocked") or meta.get("embargoDate"):
        fail(f"collection {cid} is withdrawn, blocked, or embargoed")
    print(f"collection_ok id={cid} doi={args.doi} licence=CC-BY-4.0 access=Public")


def cmd_resolve_url(args: argparse.Namespace) -> None:
    listing = json.loads(Path(args.data_json).read_text(encoding="utf-8"))
    if listing.get("licence") != "Creative Commons Attribution 4.0 International Licence":
        fail(f"data listing licence changed: {listing.get('licence')!r}")
    matches = [f for f in listing.get("file", []) if f.get("filename") == args.filename]
    if len(matches) != 1:
        fail(f"expected exactly one {args.filename!r} in listing, found {len(matches)}")
    entry = matches[0]
    if int(entry.get("id") or 0) != int(args.file_id):
        fail(f"{args.filename}: file id {entry.get('id')!r} != {args.file_id}")
    if int(entry.get("fileSize") or 0) != int(args.file_size):
        fail(f"{args.filename}: fileSize {entry.get('fileSize')!r} != {args.file_size}")
    href = ((entry.get("presignedLink") or {}).get("href")) or ""
    if not href.startswith("https://s3.data.csiro.au/") or "X-Amz-Signature=" not in href:
        fail(f"{args.filename}: missing anonymous presigned link")
    sys.stdout.write(href + "\n")


def cmd_check_range(args: argparse.Namespace) -> None:
    if not Path(args.headers).is_file():
        print("no response headers (connection failure)", file=sys.stderr)
        raise SystemExit(2)
    text = Path(args.headers).read_text(encoding="iso-8859-1")
    blocks = [b for b in re.split(r"(?=^HTTP/)", text, flags=re.MULTILINE) if b.strip()]
    final = blocks[-1] if blocks else ""
    status_match = re.search(r"^HTTP/\S+\s+(\d+)", final, flags=re.MULTILINE)
    status = int(status_match.group(1)) if status_match else 0
    if status in (401, 403, 404, 410):
        print(f"range_status={status} fatal", file=sys.stderr)
        raise SystemExit(3)
    rng = re.search(r"^Content-Range:\s*bytes\s+(\d+)-(\d+)/(\d+)\s*$", final, flags=re.IGNORECASE | re.MULTILINE)
    if status != 206 or not rng:
        print(f"range_status={status} not an exact 206 range", file=sys.stderr)
        raise SystemExit(2)
    got = tuple(map(int, rng.groups()))
    want = (int(args.start), int(args.end), int(args.total))
    if got != want:
        print(f"Content-Range {got} != {want}", file=sys.stderr)
        raise SystemExit(2)


def cmd_check_header(args: argparse.Namespace) -> None:
    blob = Path(args.header).read_bytes()
    if len(blob) != CONFIG["header_bytes"]:
        fail(f"header range has {len(blob)} bytes, expected {CONFIG['header_bytes']}")
    digest = sha256_bytes(blob)
    if digest != args.sha256:
        fail(f"header SHA-256 {digest} != pinned {args.sha256}")
    info = validate_header(blob, int(args.file_size), args.date_obs)
    p, s = info["primary"], info["subint"]
    print(
        f"header_ok file={args.label} src={p['SRC_NAME']} date_obs={p['DATE-OBS']} "
        f"nchan={s['NCHAN']} npol={s['NPOL']} nsblk={s['NSBLK']} nbits={s['NBITS']} "
        f"naxis1={s['NAXIS1']} naxis2={s['NAXIS2']} data_start={info['data_start']} "
        f"data_col_offset={info['layout']['columns']['DATA']['offset']}"
    )


def cmd_check_row(args: argparse.Namespace) -> None:
    header = Path(args.header).read_bytes()
    info = validate_header(header, int(args.file_size), args.date_obs)
    row = Path(args.row).read_bytes()
    aux_bytes = info["layout"]["columns"]["DATA"]["offset"]
    aux_digest = sha256_bytes(memoryview(row)[:aux_bytes])
    if aux_digest != args.aux_sha256:
        fail(f"row aux-prefix SHA-256 {aux_digest} != pinned {args.aux_sha256}")
    summary = validate_row(row, info, int(args.row_index))
    data = memoryview(row)[aux_bytes:]
    planes = deinterleave(data, CONFIG["nchan"], CONFIG["npol"], CONFIG["nsblk"])
    for pol, plane in zip(info["pols"], planes):
        first = plane[0]
        if plane.count(first) == len(plane):
            fail(f"{pol} plane is constant")
    digest = sha256_bytes(row)
    if args.row_sha256 and digest != args.row_sha256:
        fail(f"row SHA-256 {digest} != pinned {args.row_sha256}")
    Path(args.row + ".sha256").write_text(f"{digest}  {Path(args.row).name}\n", encoding="utf-8")
    pin = "pinned" if args.row_sha256 else "UNPINNED"
    print(
        f"row_ok file={args.label} row={args.row_index} bytes={len(row)} sha256={digest} ({pin}) "
        f"weighted={summary['weighted_channels']} tsubint={summary['tsubint']}"
    )


# --------------------------------------------------------------------------
# Build
# --------------------------------------------------------------------------

def local_names(source: dict) -> tuple[str, str]:
    base = Path(source["filename"]).name
    row = int(source["subint_row"])
    return f"headers/{base}.header", f"rows/{base}.subint{row:04d}.row"


def cmd_build(args: argparse.Namespace) -> None:
    data_root = Path(args.data_root).resolve()
    downloads = Path(args.downloads)
    samples_dir = Path(args.samples_dir)
    index_path = Path(args.index)
    stats_path = Path(args.stats)
    sources = read_sources(Path(args.sources))
    for series_id in POL_SERIES.values():
        (samples_dir / series_id).mkdir(parents=True, exist_ok=True)
    index_path.parent.mkdir(parents=True, exist_ok=True)
    stats_path.parent.mkdir(parents=True, exist_ok=True)
    rows_out: list[dict] = []
    per_row: list[dict] = []
    expected_files: set[Path] = set()
    for source in sources:
        header_rel, row_rel = local_names(source)
        header = (downloads / header_rel).read_bytes()
        if sha256_bytes(header) != source["header_sha256"]:
            fail(f"{header_rel}: header SHA-256 mismatch")
        info = validate_header(header, int(source["file_size"]), source["date_obs_utc"])
        row_index = int(source["subint_row"])
        row = (downloads / row_rel).read_bytes()
        aux_bytes = info["layout"]["columns"]["DATA"]["offset"]
        if sha256_bytes(memoryview(row)[:aux_bytes]) != source["row_aux_prefix_sha256"]:
            fail(f"{row_rel}: aux-prefix SHA-256 mismatch")
        row_digest = sha256_bytes(row)
        if source.get("row_sha256") and row_digest != source["row_sha256"]:
            fail(f"{row_rel}: row SHA-256 {row_digest} != pinned {source['row_sha256']}")
        summary = validate_row(row, info, row_index)
        planes = deinterleave(memoryview(row)[aux_bytes:], CONFIG["nchan"], CONFIG["npol"], CONFIG["nsblk"])
        primary, sub = info["primary"], info["subint"]
        absolute_subint = int(sub["NSUBOFFS"]) + row_index
        row_start_mjd = int(primary["STT_IMJD"]) + (
            float(primary["STT_SMJD"]) + float(primary["STT_OFFS"]) + absolute_subint * summary["tsubint"]
        ) / 86400.0
        base = Path(source["filename"]).stem
        for pol, plane in zip(info["pols"], planes):
            series_id = POL_SERIES[pol]
            name = f"{base}_subint{row_index:04d}_{pol}.u8"
            final = samples_dir / series_id / name
            tmp = final.with_suffix(".u8.tmp")
            tmp.write_bytes(plane)
            os.replace(tmp, final)
            expected_files.add(final)
            stats = code_stats(plane)
            if stats["distinct_codes"] < 2:
                fail(f"{name}: constant plane")
            rows_out.append(
                {
                    "dataset_id": DATASET_ID,
                    "series_id": series_id,
                    "sample_path": str(final.relative_to(data_root)),
                    "numeric_kind": "uint",
                    "bit_width": 8,
                    "endianness": "little",
                    "element_size_bytes": 1,
                    "sample_size_bytes": len(plane),
                    "value_count": len(plane),
                    "sample_shape": [CONFIG["nsblk"], CONFIG["nchan"]],
                    "sample_axes": ["time_sample", "frequency_channel"],
                    "pol_product": pol,
                    "observation_id": source["observation_id"],
                    "collection_id": int(source["collection_id"]),
                    "collection_doi": source["collection_doi"],
                    "source_filename": source["filename"],
                    "subint_row": row_index,
                    "absolute_subint": absolute_subint,
                    "row_start_mjd_utc": round(row_start_mjd, 9),
                    "freq_first_mhz": summary["freq_first_mhz"],
                    "chan_bw_mhz": CONFIG["chan_bw"],
                    "tbin_s": CONFIG["tbin"],
                    "zero_off": CONFIG["zero_off"],
                    "sha256": sha256_bytes(plane),
                    **stats,
                }
            )
        per_row.append({"observation_id": source["observation_id"], "source_filename": source["filename"],
                        "subint_row": row_index, "row_sha256": row_digest, **summary})
        print(f"built {base} row={row_index} sha256={row_digest}")
    # Remove stale sample files from previous runs.
    for series_id in POL_SERIES.values():
        for path in (samples_dir / series_id).iterdir():
            if path not in expected_files:
                path.unlink()
    rows_out.sort(key=lambda r: (r["series_id"], r["sample_path"]))
    tmp_index = index_path.with_suffix(".jsonl.tmp")
    with tmp_index.open("w", encoding="utf-8") as handle:
        for row in rows_out:
            handle.write(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n")
    os.replace(tmp_index, index_path)
    totals = collections.defaultdict(lambda: {"samples": 0, "bytes": 0})
    for row in rows_out:
        totals[row["series_id"]]["samples"] += 1
        totals[row["series_id"]]["bytes"] += row["sample_size_bytes"]
    stats = {
        "dataset_id": DATASET_ID,
        "rows": per_row,
        "series_totals": dict(sorted(totals.items())),
        "primary_samples": len(rows_out),
        "primary_bytes": sum(r["sample_size_bytes"] for r in rows_out),
    }
    tmp_stats = stats_path.with_suffix(".json.tmp")
    tmp_stats.write_text(json.dumps(stats, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp_stats, stats_path)
    print(json.dumps({"series_totals": stats["series_totals"], "primary_samples": stats["primary_samples"],
                      "primary_bytes": stats["primary_bytes"]}, sort_keys=True))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("check-collection")
    p.add_argument("--meta", required=True)
    p.add_argument("--collection-id", required=True)
    p.add_argument("--doi", required=True)
    p.set_defaults(func=cmd_check_collection)
    p = sub.add_parser("resolve-url")
    p.add_argument("--data-json", required=True)
    p.add_argument("--filename", required=True)
    p.add_argument("--file-id", required=True)
    p.add_argument("--file-size", required=True)
    p.set_defaults(func=cmd_resolve_url)
    p = sub.add_parser("check-range")
    p.add_argument("--headers", required=True)
    p.add_argument("--start", required=True)
    p.add_argument("--end", required=True)
    p.add_argument("--total", required=True)
    p.set_defaults(func=cmd_check_range)
    p = sub.add_parser("check-header")
    p.add_argument("--header", required=True)
    p.add_argument("--sha256", required=True)
    p.add_argument("--file-size", required=True)
    p.add_argument("--date-obs", required=True)
    p.add_argument("--label", default="")
    p.set_defaults(func=cmd_check_header)
    p = sub.add_parser("check-row")
    p.add_argument("--header", required=True)
    p.add_argument("--row", required=True)
    p.add_argument("--row-index", required=True)
    p.add_argument("--file-size", required=True)
    p.add_argument("--date-obs", required=True)
    p.add_argument("--aux-sha256", required=True)
    p.add_argument("--row-sha256", default="")
    p.add_argument("--label", default="")
    p.set_defaults(func=cmd_check_row)
    p = sub.add_parser("build")
    p.add_argument("--sources", required=True)
    p.add_argument("--downloads", required=True)
    p.add_argument("--samples-dir", required=True)
    p.add_argument("--index", required=True)
    p.add_argument("--stats", required=True)
    p.add_argument("--data-root", required=True)
    p.set_defaults(func=cmd_build)
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
