#!/usr/bin/env python3
"""Independent verification of the built samples.

Does not import x1dints.py: re-walks the downloaded FITS header pieces with its own card
parser, re-derives the FLUX column offset / nbins / row count, re-decodes the big-endian
FLUX payload row by row with struct (build uses array.byteswap), byte-compares every
sample, re-applies the missing-value policy and checks index, manifest totals and scope.
"""
import argparse
import csv
import hashlib
import json
import math
import os
import re
import struct
import sys
import tomllib

DATASET_ID = "mast_jwst_nirspec_g395h_tso_x1dints_flux_f64"
SERIES_ID = "nirspec_g395h_nrs1_x1dints_flux_jy_f64"
MIN_ROW_FINITE_FRACTION = 0.90
MIN_PROGRAMS = 40
REQUIRED_INDEX = ("dataset_id", "series_id", "sample_path", "numeric_kind", "bit_width", "endianness",
                  "element_size_bytes", "sample_size_bytes", "value_count")
EXPECT_PRIMARY = {"TELESCOP": "JWST", "INSTRUME": "NIRSPEC", "DETECTOR": "NRS1", "FILTER": "F290LP",
                  "GRATING": "G395H", "EXP_TYPE": "NRS_BRIGHTOBJ", "SUBARRAY": "SUB2048",
                  "FXD_SLIT": "S1600A1", "DATAMODL": "TSOMultiSpecModel"}


class Sparse:
    """Byte-addressable view over <offset>.bin header pieces."""

    def __init__(self, directory):
        self.pieces = []
        for name in os.listdir(directory):
            m = re.fullmatch(r"(\d+)\.bin", name)
            if m:
                with open(os.path.join(directory, name), "rb") as fh:
                    self.pieces.append((int(m.group(1)), fh.read()))

    def get(self, start, n):
        for off, data in self.pieces:
            if off <= start and start + n <= off + len(data):
                return data[start - off:start - off + n]
        raise SystemExit(f"header bytes {start}+{n} not present in downloaded pieces")


def header_at(sparse, offset):
    cards = {}
    pos = offset
    while True:
        block = sparse.get(pos, 2880)
        pos += 2880
        for i in range(36):
            card = block[80 * i:80 * i + 80].decode("ascii")
            if card.startswith("END") and card[3:].strip() == "":
                return cards, pos - offset
            if card[8:10] != "= ":
                continue
            key = card[:8].strip()
            rest = card[10:].strip()
            if rest.startswith("'"):
                end = rest.find("'", 1)
                while end + 1 < len(rest) and rest[end + 1] == "'":
                    end = rest.find("'", end + 2)
                val = rest[1:end].replace("''", "'").strip()
            else:
                tok = rest.split("/")[0].strip()
                val = {"T": True, "F": False}.get(tok, tok)
                if isinstance(val, str):
                    try:
                        val = int(tok)
                    except ValueError:
                        pass
            cards.setdefault(key, val)


def extract1d_geometry(hdr_dir):
    sparse = Sparse(hdr_dir)
    primary, plen = header_at(sparse, 0)
    offset = 0
    hlen = plen
    cards = primary
    for _ in range(20):
        naxis = int(cards.get("NAXIS", 0))
        size = 0
        if naxis:
            size = abs(int(cards["BITPIX"])) // 8
            for i in range(1, naxis + 1):
                size *= int(cards[f"NAXIS{i}"])
            size += int(cards.get("PCOUNT", 0))
        offset += hlen + -(-size // 2880) * 2880
        cards, hlen = header_at(sparse, offset)
        if cards.get("EXTNAME") == "EXTRACT1D":
            break
    else:
        raise SystemExit(f"{hdr_dir}: no EXTRACT1D")
    widths = {"J": 4, "D": 8, "E": 4, "I": 2, "K": 8, "B": 1, "L": 1, "A": 1}
    pos = 0
    flux = None
    for i in range(1, int(cards["TFIELDS"]) + 1):
        m = re.fullmatch(r"(\d*)([A-Z])", str(cards[f"TFORM{i}"]).strip())
        rep = int(m.group(1) or 1)
        if cards.get(f"TTYPE{i}") == "FLUX":
            if m.group(2) != "D" or cards.get(f"TUNIT{i}") != "Jy":
                raise SystemExit(f"{hdr_dir}: FLUX is {cards[f'TFORM{i}']} [{cards.get(f'TUNIT{i}')}]")
            flux = (pos, rep)
        pos += rep * widths[m.group(2)]
    if pos != int(cards["NAXIS1"]) or flux is None:
        raise SystemExit(f"{hdr_dir}: row width mismatch or no FLUX column")
    return primary, {"data_offset": offset + hlen, "naxis1": int(cards["NAXIS1"]),
                     "naxis2": int(cards["NAXIS2"]), "flux_offset": flux[0], "nbins": flux[1]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", required=True)
    ap.add_argument("--recipe-dir", required=True)
    args = ap.parse_args()
    data = args.data_dir
    dl = os.path.join(data, "downloads", DATASET_ID)
    with open(os.path.join(args.recipe_dir, "sources.tsv"), newline="") as fh:
        sources = list(csv.DictReader(fh, delimiter="\t"))
    with open(os.path.join(dl, "download_plan.tsv"), newline="") as fh:
        plan = {r["filename"]: r for r in csv.DictReader(fh, delimiter="\t")}
    with open(os.path.join(data, "index", DATASET_ID, "samples.jsonl")) as fh:
        index = [json.loads(line) for line in fh if line.strip()]
    with open(os.path.join(args.recipe_dir, "manifest.toml"), "rb") as fh:
        manifest = tomllib.load(fh)

    if len(index) != len(sources):
        raise SystemExit(f"index has {len(index)} rows, sources.tsv {len(sources)}")
    by_file = {r["source_filename"]: r for r in index}
    out_dir = os.path.join(data, "samples", DATASET_ID, SERIES_ID)
    expected_names = {s["filename"][:-5] + ".f64" for s in sources}
    if set(os.listdir(out_dir)) != expected_names:
        raise SystemExit("sample directory contents differ from the selection")

    digests = set()
    total_bytes = 0
    total_values = 0
    total_nan = 0
    programs = set()
    targets = set()
    for src in sources:
        fn = src["filename"]
        stem = fn[:-5]
        row = by_file.get(fn)
        if row is None:
            raise SystemExit(f"{fn}: no index row")
        for k in REQUIRED_INDEX:
            if k not in row:
                raise SystemExit(f"{fn}: index row lacks {k}")
        primary, geo = extract1d_geometry(os.path.join(dl, "headers", fn))
        for k, v in EXPECT_PRIMARY.items():
            if primary.get(k) != v:
                raise SystemExit(f"{fn}: header {k}={primary.get(k)!r}, expected {v!r}")
        if primary.get("FILENAME") != fn or primary.get("INTSTART") != 1 or primary.get("EXSEGNUM") != 1:
            raise SystemExit(f"{fn}: not the seg001 product named in sources.tsv")
        if geo["naxis2"] != primary["INTEND"] - primary["INTSTART"] + 1:
            raise SystemExit(f"{fn}: NAXIS2 does not match INTSTART..INTEND")
        with open(os.path.join(dl, "layouts", stem + ".json")) as fh:
            layout = json.load(fh)
        lflux = [c for c in layout["extract1d"]["columns"] if c["name"] == "FLUX"][0]
        if (layout["extract1d"]["data_offset"], layout["extract1d"]["naxis2"], lflux["offset"], lflux["repeat"]) != \
                (geo["data_offset"], geo["naxis2"], geo["flux_offset"], geo["nbins"]):
            raise SystemExit(f"{fn}: download layout disagrees with independent header walk")
        nbins, nrows = geo["nbins"], geo["naxis2"]
        with open(os.path.join(dl, "flux", stem + ".flux.be"), "rb") as fh:
            raw = fh.read()
        if hashlib.sha256(raw).hexdigest() != plan[fn]["sha256"] or len(raw) != 8 * nbins * nrows:
            raise SystemExit(f"{fn}: FLUX payload size/sha256 mismatch")
        with open(os.path.join(data, row["sample_path"]), "rb") as fh:
            sample = fh.read()
        if row["sample_path"] != os.path.join("samples", DATASET_ID, SERIES_ID, stem + ".f64"):
            raise SystemExit(f"{fn}: unexpected sample_path")
        nan = 0
        fmin, fmax = math.inf, -math.inf
        distinct = set()
        row_hashes = set()
        width = 8 * nbins
        for r in range(nrows):
            vals = struct.unpack(f">{nbins}d", raw[r * width:(r + 1) * width])
            if struct.pack(f"<{nbins}d", *vals) != sample[r * width:(r + 1) * width]:
                raise SystemExit(f"{fn}: sample row {r} differs from re-decoded FLUX")
            finite = [v for v in vals if not (math.isnan(v) or math.isinf(v))]
            if any(math.isinf(v) for v in vals):
                raise SystemExit(f"{fn}: row {r} contains inf")
            if len(finite) < MIN_ROW_FINITE_FRACTION * nbins:
                raise SystemExit(f"{fn}: row {r} has only {len(finite)}/{nbins} finite values")
            if max(finite) == min(finite):
                raise SystemExit(f"{fn}: row {r} is constant")
            h = hashlib.blake2b(raw[r * width:(r + 1) * width], digest_size=16).digest()
            if h in row_hashes:
                raise SystemExit(f"{fn}: duplicate integration row {r}")
            row_hashes.add(h)
            nan += nbins - len(finite)
            fmin = min(fmin, min(finite))
            fmax = max(fmax, max(finite))
            if len(distinct) < 100000:
                distinct.update(finite)
        if len(sample) != width * nrows:
            raise SystemExit(f"{fn}: sample size {len(sample)} != {width * nrows}")
        if len(distinct) < min(1000, (nbins * nrows) // 2):
            raise SystemExit(f"{fn}: only {len(distinct)} distinct finite values")
        checks = {
            "dataset_id": DATASET_ID, "series_id": SERIES_ID, "numeric_kind": "float", "bit_width": 64,
            "endianness": "little", "element_size_bytes": 8, "sample_size_bytes": len(sample),
            "value_count": nbins * nrows, "sample_shape": [nrows, nbins], "nan_count": nan,
            "finite_min": fmin, "finite_max": fmax, "cal_ver": primary.get("CAL_VER"),
            "program": primary.get("PROGRAM"), "flux_unit": "Jy",
        }
        for k, v in checks.items():
            if row.get(k) != v:
                raise SystemExit(f"{fn}: index {k}={row.get(k)!r}, re-derived {v!r}")
        digest = hashlib.sha256(sample).hexdigest()
        if digest != row.get("sample_sha256") or digest in digests:
            raise SystemExit(f"{fn}: sample sha256 mismatch or duplicate sample")
        digests.add(digest)
        total_bytes += len(sample)
        total_values += nbins * nrows
        total_nan += nan
        programs.add(primary["PROGRAM"])
        targets.add(src["target_key"])
        print(f"ok {stem} rows={nrows} nbins={nbins} nan={nan} min={fmin:.6g} max={fmax:.6g}")

    series = [s for s in manifest["series"] if s["id"] == SERIES_ID]
    if len(series) != 1:
        raise SystemExit("manifest lacks the primary series")
    s = series[0]
    if s["sample_count"] != len(index) or s["total_size_bytes"] != total_bytes:
        raise SystemExit(f"manifest sample_count/total_size_bytes {s['sample_count']}/{s['total_size_bytes']} "
                         f"!= realized {len(index)}/{total_bytes}")
    if total_bytes > 1_000_000_000:
        raise SystemExit("primary output exceeds 1 GB")
    if len(targets) != len(sources):
        raise SystemExit("selection has more than one product per target")
    if len(programs) < MIN_PROGRAMS:
        raise SystemExit(f"only {len(programs)} programs (claimed scope >= {MIN_PROGRAMS})")
    median = sorted(r["value_count"] for r in index)[len(index) // 2]
    print(f"verify summary samples={len(index)} bytes={total_bytes} values={total_values} "
          f"nan_fraction={total_nan / total_values:.4f} programs={len(programs)} targets={len(targets)} "
          f"median_values={median}")


if __name__ == "__main__":
    main()
