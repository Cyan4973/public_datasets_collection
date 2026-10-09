#!/usr/bin/env python3
"""download.sh helpers: semantic validation of fetched payloads.

  check_payload.py header <piece_dir> <sources.tsv> <filename> <layout_out>
        -> walks the freshly fetched header pieces, checks the regime, writes the layout JSON
           and prints "<status> <etag> <size>" (status pinned | reprocessed)
  check_payload.py flux <layout.json> <flux.be>    -> FLUX payload check, prints sha256
  check_payload.py evidence <path>                 -> MAST data-use policy check
"""
import csv
import glob
import hashlib
import html
import json
import math
import os
import re
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import x1dints  # noqa: E402


class PayloadError(Exception):
    pass


def read_sources(path):
    with open(path, newline="") as fh:
        return list(csv.DictReader(fh, delimiter="\t"))


def live_meta(piece_dir):
    """ETag and total size from the header-piece responses; all must agree."""
    seen = set()
    for path in sorted(glob.glob(os.path.join(piece_dir, "*.http"))):
        with open(path, encoding="latin-1") as fh:
            status, headers = x1dints.parse_http_headers(fh.read())
        if status != 206:
            raise PayloadError(f"{path}: header range answered HTTP {status}, expected 206")
        m = re.fullmatch(r"bytes (\d+)-(\d+)/(\d+)", headers.get("content-range", ""))
        if not m:
            raise PayloadError(f"{path}: missing Content-Range")
        seen.add((headers.get("etag", "").strip('"'), int(m.group(3))))
    if len(seen) != 1:
        raise PayloadError(f"{piece_dir}: inconsistent ETag/size across header pieces: {seen}")
    return seen.pop()


def check_header(piece_dir, sources_path, filename, layout_out):
    rows = [r for r in read_sources(sources_path) if r["filename"] == filename]
    if len(rows) != 1:
        raise PayloadError(f"{filename}: not exactly one row in sources.tsv")
    pin = rows[0]
    etag, size = live_meta(piece_dir)
    layout = x1dints.walk(x1dints.load_pieces(piece_dir))
    problems = x1dints.regime_problems(layout, filename, size)
    if problems:
        raise PayloadError(f"{filename}: header regime violated: {'; '.join(problems)}")
    _, nbins, _, _ = x1dints.flux_layout(layout)
    e = layout["extract1d"]
    p = layout["primary"]
    if etag == pin["etag"] and size == int(pin["size_bytes"]):
        status = "pinned"
        expect = {
            "cal_ver": p["CAL_VER"], "crds_ctx": p["CRDS_CTX"], "sdp_ver": p["SDP_VER"],
            "naxis1": e["naxis1"], "naxis2": e["naxis2"], "nbins": nbins,
            "extract1d_data_offset": e["data_offset"],
        }
        bad = [k for k, v in expect.items() if str(v) != pin[k]]
        if bad:
            raise PayloadError(f"{filename}: same ETag but header differs from pin in {bad}")
    else:
        # MAST reprocesses JWST products in place (same file name, new ETag/size/CAL_VER).
        # Re-discovery by name: accept the current product if it still passes the regime.
        status = "reprocessed"
        print(
            f"WARNING {filename} reprocessed since discovery: etag {pin['etag']} -> {etag}, "
            f"size {pin['size_bytes']} -> {size}, CAL_VER {pin['cal_ver']} -> {p['CAL_VER']}, "
            f"NAXIS2 {pin['naxis2']} -> {e['naxis2']}, nbins {pin['nbins']} -> {nbins}",
            file=sys.stderr,
        )
    layout["remote"] = {"etag": etag, "size": size, "status": status}
    with open(layout_out + ".tmp", "w") as fh:
        json.dump(layout, fh, sort_keys=True)
    os.replace(layout_out + ".tmp", layout_out)
    print(status, etag, size)


def check_flux(layout_path, flux_path):
    with open(layout_path) as fh:
        layout = json.load(fh)
    _, nbins, _, _ = x1dints.flux_layout(layout)
    nrows = layout["extract1d"]["naxis2"]
    with open(flux_path, "rb") as fh:
        buf = fh.read()
    if len(buf) != nrows * nbins * 8:
        raise PayloadError(f"{flux_path}: {len(buf)} bytes, expected {nrows} x {nbins} x 8")
    fmt = f">{nbins}d"
    width = nbins * 8
    distinct_all = set()
    for r in range(nrows):
        row = struct.unpack_from(fmt, buf, r * width)
        finite = [v for v in row if math.isfinite(v)]
        if any(math.isinf(v) for v in row):
            raise PayloadError(f"row {r}: infinite value")
        if len(finite) < x1dints.MIN_ROW_FINITE_FRACTION * nbins:
            raise PayloadError(f"row {r}: only {len(finite)}/{nbins} finite values")
        if len(set(finite)) < 2:
            raise PayloadError(f"row {r}: constant row")
        if r < 64:
            distinct_all.update(finite)
    if len(distinct_all) < 1000:
        raise PayloadError(f"only {len(distinct_all)} distinct values in the first rows")
    print(hashlib.sha256(buf).hexdigest())


def check_evidence(path):
    with open(path, encoding="utf-8", errors="replace") as fh:
        text = fh.read()
    text = re.sub(r"<script.*?</script>|<style.*?</style>", " ", text, flags=re.S | re.I)
    text = html.unescape(re.sub(r"<[^>]+>", " ", text))
    text = re.sub(r"\s+", " ", text)
    if "Most data hosted at MAST are in the public domain" not in text:
        raise PayloadError("MAST data-use page no longer states the public-domain default")
    start = text.find("Copyrighted Data")
    stop = text.find("Scientists and educators", start)
    if start < 0 or stop < 0 or stop - start > 2000:
        raise PayloadError("MAST data-use page lacks the copyrighted-collections section")
    section = text[start:stop]
    if "Digitized Sky Survey" not in section or "Guide Star Catalogs" not in section \
            or re.search(r"\bJWST\b|\bWebb\b|NIRSpec", section, flags=re.I):
        raise PayloadError("MAST copyrighted-collections list changed or now names JWST")
    print("evidence_ok public_domain_default=yes jwst_in_copyrighted_list=no")


def main(argv):
    mode = argv[1]
    if mode == "header":
        check_header(argv[2], argv[3], argv[4], argv[5])
    elif mode == "flux":
        check_flux(argv[2], argv[3])
    elif mode == "evidence":
        check_evidence(argv[2])
    else:
        raise SystemExit(f"unknown mode {mode}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv))
    except (PayloadError, x1dints.NeedBytes, KeyError, ValueError) as exc:
        print(f"payload rejected: {exc}", file=sys.stderr)
        sys.exit(3)
