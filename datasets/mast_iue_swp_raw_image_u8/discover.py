#!/usr/bin/env python3
"""Resolve the pinned IUE SWP low-dispersion RILO selection (sources.tsv).

Documentation of how sources.tsv was produced; download.sh does not run this.
All network I/O goes through curl (subprocess) so the environment's curl proxy
configuration applies; Python only parses what curl fetched.

Steps
1. Query the official MAST IUE search interface (archive.stsci.edu/iue/search.php)
   for every SWP (camera 3) LOW-dispersion image, in six image-number chunks,
   as CSV. Object classes 98 (wavelength calibration lamp) and 99 (nulls and
   flat fields) are excluded by the interface unless explicitly requested and
   are filtered again here.
2. Keep catalogue rows with aperture LARGE, observing station GSFC, image type
   S (single exposure), raw data at MAST, full read, standard acquisition, no
   trail/multiple/segmented exposure flags, a positive exposure time, and a
   target name without calibration keywords.
3. Sort by image number and split the eligible list into N equal strata. In each
   stratum, walk forward from its first row and take the first image whose
   NEWSIPS raw-image FITS (swpNNNNN.rilo.gz) passes a header probe: a 16 KiB
   range GET (gunzipped to the complete FITS primary header) plus an 8-byte
   suffix GET of the gzip trailer (CRC32, ISIZE). Header keywords must confirm
   the same homogeneity constraints (see HEADER_REQUIREMENTS).
4. Write sources.tsv with the pinned URL, compressed size, ETag, Last-Modified,
   gzip CRC32/ISIZE and auxiliary header metadata (no observer/PI names).
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import re
import struct
import subprocess
import sys
import tempfile
import zlib
from pathlib import Path

SEARCH_URL = "https://archive.stsci.edu/iue/search.php"
DATA_ROOT = "https://archive.stsci.edu/missions/iue/data/swp"
CHUNKS = [(0, 9999), (10000, 19999), (20000, 29999), (30000, 39999), (40000, 49999), (50000, 59999)]
COLUMNS = [
    "iue_data_id", "iue_cam_no", "iue_image_no", "iue_disp", "iue_aper", "iue_category", "iue_com_exp_time",
    "iue_obs_station", "iue_obs_start_time", "iue_imtype", "iue_raw_flag", "iue_trail_flag",
    "iue_multiple_flag", "iue_segmented_flag", "iue_nonstandard", "iue_readmode", "iue_target_name",
]
CAL_WORDS = re.compile(r"\b(FLAT|FLOOD|NULL|WAVECAL|WAVE\s*CAL|LAMP|DARK|BIAS|TEST|CALIB\w*|PT\s*LAMP|TFLOOD|UVFLOOD)\b", re.I)
EXPECTED_ISIZE = 619200  # 28,800-byte FITS header + 589,824 pixels + 576 bytes FITS zero padding
HEADER_REQUIREMENTS = {
    "SIMPLE": "T",
    "BITPIX": "8",
    "NAXIS": "2",
    "NAXIS1": "768",
    "NAXIS2": "768",
    "CAMERA": "SWP",
    "DISPERSN": "LOW",
    "DISPTYPE": "LOW",
    "APERTURE": "LARGE",
    "READMODE": "FULL",
    "READGAIN": "LOW",
    "EXPOGAIN": "MAXIMUM",
    "UVC-VOLT": "-5.0",
    "STATION": "GSFC",
    "ABNNOSTD": "NO",
    "ABNREAD": "NO",
    "ABNUVC": "NO",
    "ABNHISTR": "NO",
    "ABNOTHER": "NO",
    "ABNMINFR": "NO",
    "LEXPTRMD": "NO-TRAIL",
    "LEXPMULT": "NO",
    "LEXPSEGM": "NO",
}
UA = "openzl-public-datasets-iue-swp-discover/1.0"


def curl(args: list[str], timeout: int = 300) -> bytes:
    cmd = ["curl", "--fail", "--silent", "--show-error", "--location", "--retry", "5",
           "--retry-delay", "2", "--retry-all-errors", "--max-time", str(timeout), "--user-agent", UA] + args
    return subprocess.run(cmd, check=True, capture_output=True).stdout


def parse_fits_header(raw: bytes) -> tuple[dict[str, str], int]:
    cards: dict[str, str] = {}
    offset = 0
    while offset + 2880 <= len(raw):
        block = raw[offset:offset + 2880]
        offset += 2880
        for i in range(0, 2880, 80):
            card = block[i:i + 80].decode("ascii")
            key = card[:8].strip()
            if key == "END":
                return cards, offset
            if card[8:10] != "= " or key in cards:
                continue
            value = card[10:]
            if value.lstrip().startswith("'"):
                match = re.match(r"\s*'((?:[^']|'')*)'", value)
                cards[key] = match.group(1).replace("''", "'").rstrip() if match else ""
            else:
                cards[key] = value.split("/", 1)[0].strip()
    raise ValueError("FITS END card not found in probed bytes")


def fetch_catalogue(cache: Path) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for lo, hi in CHUNKS:
        path = cache / f"catalogue_swp_low_{lo:05d}_{hi:05d}.csv"
        if not path.is_file() or path.stat().st_size == 0:
            url = (f"{SEARCH_URL}?action=Search&iue_cam_no[]=3&iue_disp[]=LOW&iue_image_no={lo}..{hi}"
                   f"&outputformat=CSV&max_records=20000&selectedColumnsCsv={','.join(COLUMNS)}")
            path.write_bytes(curl(["--globoff", url]))
        table = list(csv.reader(io.StringIO(path.read_text(encoding="utf-8"))))
        header = table[0]
        if "Image No" not in header or table[1][0] != "ustring":
            raise SystemExit(f"unexpected catalogue CSV layout in {path}")
        rows += [dict(zip(header, record)) for record in table[2:] if record]
    return rows


def eligible(row: dict[str, str]) -> bool:
    try:
        exposure = int(row["Exp Time"])
    except ValueError:
        return False
    return (
        row["Camera No"] == "3"
        and row["Disp"] == "LOW"
        and row["Aper"] == "LARGE"
        and row["Obs Station"] == "GSFC"
        and row["Image Type"] == "S"
        and row["Raw Data at MAST"] == "R"
        and row["Read Mode"] == "F"
        and row["Non Standard Image"] == "N"
        and row["Trail Flag"] == "N"
        and row["Multiple Flag"] == "N"
        and row["Segmented Flag"] == "N"
        and row["Category"] not in {"98", "99"}
        and exposure > 0
        and not CAL_WORDS.search(row["Target Name"])
    )


def probe(image_no: int) -> tuple[dict | None, str]:
    directory = f"{image_no // 1000 * 1000:05d}"
    name = f"swp{image_no:05d}.rilo.gz"
    url = f"{DATA_ROOT}/{directory}/{name}"
    with tempfile.TemporaryDirectory(prefix="iue_probe_", dir="/tmp") as tmp:
        header_path = Path(tmp) / "headers"
        body_path = Path(tmp) / "body"
        try:
            curl(["--range", "0-16383", "--dump-header", str(header_path), "--output", str(body_path), url], timeout=120)
        except subprocess.CalledProcessError as exc:
            return None, f"fetch_failed:{exc.returncode}"
        headers = header_path.read_text(encoding="iso-8859-1")
        body = body_path.read_bytes()
    if body[:3] != b"\x1f\x8b\x08":
        return None, "no_gzip_magic"
    final = re.split(r"(?=^HTTP/)", headers, flags=re.M)[-1]
    content_range = re.search(r"^Content-Range:\s*bytes\s+0-\d+/(\d+)", final, re.I | re.M)
    etag = re.search(r'^ETag:\s*"?([^"\r\n]+)"?', final, re.I | re.M)
    modified = re.search(r"^Last-Modified:\s*([^\r\n]+)", final, re.I | re.M)
    if not content_range:
        return None, "no_content_range"
    size = int(content_range.group(1))
    try:
        raw = zlib.decompressobj(16 + zlib.MAX_WBITS).decompress(body)
        cards, header_bytes = parse_fits_header(raw)
    except (zlib.error, ValueError, UnicodeDecodeError) as exc:
        return None, f"header_parse:{exc}"
    for key, wanted in HEADER_REQUIREMENTS.items():
        if cards.get(key) != wanted:
            return None, f"header_{key}={cards.get(key)!r}"
    if "BZERO" in cards or "BSCALE" in cards:
        return None, "scaled_pixels"
    if int(cards.get("IMAGE", "-1")) != image_no:
        return None, f"header_IMAGE={cards.get('IMAGE')!r}"
    if int(cards.get("LIUECLAS", "99")) in (98, 99):
        return None, f"header_LIUECLAS={cards.get('LIUECLAS')!r}"
    if float(cards.get("LEXPTIME", "0")) <= 0:
        return None, f"header_LEXPTIME={cards.get('LEXPTIME')!r}"
    if header_bytes != 28800:
        return None, f"header_bytes={header_bytes}"
    trailer = curl(["--range", f"{size - 8}-{size - 1}", url], timeout=60)
    if len(trailer) != 8:
        return None, "trailer_length"
    crc32, isize = struct.unpack("<II", trailer)
    if isize != EXPECTED_ISIZE:
        return None, f"isize={isize}"
    return {
        "image_no": image_no,
        "filename": name,
        "url": url,
        "size_bytes": size,
        "gzip_crc32": f"{crc32:08x}",
        "gzip_isize": isize,
        "etag": etag.group(1) if etag else "",
        "last_modified": modified.group(1).strip() if modified else "",
        "obs_date": cards.get("LDATEOBS", ""),
        "exptime_s": cards.get("LEXPTIME", ""),
        "iue_class": cards.get("LIUECLAS", ""),
        "target": cards.get("LTARGET", "") or cards.get("LOBJECT", ""),
        "readgain": cards.get("READGAIN", ""),
        "expogain": cards.get("EXPOGAIN", ""),
        "uvc_volt": cards.get("UVC-VOLT", ""),
        "thdaread": cards.get("THDAREAD", ""),
    }, "ok"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cache", type=Path, default=Path("/tmp/autocollect/iue/discovery"))
    parser.add_argument("--count", type=int, default=256)
    parser.add_argument("--out", type=Path, default=Path(__file__).resolve().parent / "sources.tsv")
    args = parser.parse_args()
    args.cache.mkdir(parents=True, exist_ok=True)
    rows = fetch_catalogue(args.cache)
    pool = sorted((r for r in rows if eligible(r)), key=lambda r: int(r["Image No"]))
    image_numbers = [int(r["Image No"]) for r in pool]
    if len(set(image_numbers)) != len(image_numbers):
        raise SystemExit("duplicate image numbers in eligible pool")
    print(f"catalogue_rows={len(rows)} eligible={len(pool)}", file=sys.stderr)
    selected = []
    log = []
    total = len(pool)
    for stratum in range(args.count):
        start = stratum * total // args.count
        stop = (stratum + 1) * total // args.count
        chosen = None
        for index in range(start, stop):
            row = pool[index]
            result, reason = probe(int(row["Image No"]))
            log.append({"stratum": stratum, "image_no": int(row["Image No"]), "result": reason})
            if result is not None:
                result["catalogue_category"] = row["Category"]
                result["catalogue_exptime_s"] = row["Exp Time"]
                result["obs_start_time"] = row["Obs Start Time"]
                chosen = result
                break
            print(f"skip stratum={stratum} image={row['Image No']} reason={reason}", file=sys.stderr)
        if chosen is None:
            raise SystemExit(f"stratum {stratum} has no passing image")
        selected.append(chosen)
        print(f"stratum={stratum} image={chosen['image_no']} size={chosen['size_bytes']}", file=sys.stderr)
    (args.cache / "probe_log.json").write_text(json.dumps(log, indent=1), encoding="utf-8")
    fields = ["image_no", "filename", "url", "size_bytes", "gzip_crc32", "gzip_isize", "sha256", "etag",
              "last_modified", "obs_start_time", "obs_date", "exptime_s", "catalogue_exptime_s", "iue_class",
              "catalogue_category", "readgain", "expogain", "uvc_volt", "thdaread", "target"]
    with args.out.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n", extrasaction="ignore")
        writer.writeheader()
        for item in selected:
            item.setdefault("sha256", "")
            item["target"] = re.sub(r"[\t\r\n]+", " ", item["target"]).strip()
            writer.writerow(item)
    print(f"selected={len(selected)} bytes={sum(i['size_bytes'] for i in selected)}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
