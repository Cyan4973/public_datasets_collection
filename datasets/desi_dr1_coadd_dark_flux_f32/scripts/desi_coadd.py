#!/usr/bin/env python3
"""DESI DR1 iron main/dark healpix coadd FLUX HDUs: discovery, validation, build, verify.

Pure standard library. Network access happens only in `discover` (metadata
probes through the curl CLI, so the user's curl proxy configuration applies);
download.sh fetches the pinned byte ranges with curl and calls the
`validate-*` subcommands. `build` and `verify` read only local files.

Each downloaded range file holds exactly one FITS extension header (one or
more 2880-byte blocks) followed by the unpadded big-endian float32 data unit
of one `<ARM>_FLUX` image HDU, so the FITS block padding is never fetched.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import struct
import subprocess
import sys
from array import array
from pathlib import Path

DATASET_ID = "desi_dr1_coadd_dark_flux_f32"
BASE_URL = "https://data.desi.lbl.gov/public/dr1/spectro/redux/iron/healpix/main/dark"
ARMS = {"B": 2751, "R": 2326, "Z": 2881}
SERIES = {arm: f"desi_coadd_{arm.lower()}_flux_f32" for arm in ARMS}
FLUX_BUNIT = "10**-17 erg/(s cm2 Angstrom)"
BLOCK = 2880
PIN_COLUMNS = [
    "healpix",
    "group",
    "url",
    "file_bytes",
    "last_modified",
    "etag",
    "primary_header_bytes",
    "primary_header_sha256",
    "arm",
    "extname",
    "header_offset",
    "header_bytes",
    "header_sha256",
    "data_offset",
    "naxis1",
    "naxis2",
    "data_bytes",
    "datasum",
]
# An HDU may keep all-zero rows (targets whose every coadded pixel of that arm
# was masked, e.g. a camera without data). Realized: 689 of 43,287 target rows
# overall; the worst HDU (healpix 49100 R_FLUX, an R-camera dropout) has
# 115/398. More than this fraction marks the HDU as degenerate.
MAX_ZERO_ROW_FRACTION = 0.35


# ---------------------------------------------------------------- FITS helpers

def parse_header(buf: bytes) -> tuple[dict[str, str], int | None]:
    """Return (cards, header_length) for the FITS header at the start of buf.

    header_length is None when no END card occurs inside buf.
    """
    cards: dict[str, str] = {}
    for start in range(0, len(buf) - len(buf) % BLOCK, BLOCK):
        block = buf[start:start + BLOCK]
        for i in range(0, BLOCK, 80):
            card = block[i:i + 80].decode("ascii")
            key = card[:8].strip()
            if key == "END" and card[3:].strip() == "":
                return cards, start + BLOCK
            if card[8:10] != "= ":
                continue
            raw = card[10:].strip()
            if raw.startswith("'"):
                match = re.match(r"'((?:[^']|'')*)'", raw)
                if not match:
                    raise ValueError(f"malformed string card {card!r}")
                value = match.group(1).replace("''", "'").rstrip()
            else:
                value = raw.split("/", 1)[0].strip()
            cards.setdefault(key, value)
    return cards, None


def data_unit_bytes(cards: dict[str, str]) -> int:
    naxis = int(cards["NAXIS"])
    if naxis == 0:
        return 0
    product = 1
    for axis in range(1, naxis + 1):
        product *= int(cards[f"NAXIS{axis}"])
    bitpix = abs(int(cards["BITPIX"]))
    return bitpix // 8 * int(cards.get("GCOUNT", "1")) * (int(cards.get("PCOUNT", "0")) + product)


def padded(n: int) -> int:
    return (n + BLOCK - 1) // BLOCK * BLOCK


def fits_datasum(data: bytes) -> int:
    """FITS 32-bit ones'-complement data checksum; zero padding adds nothing."""
    if len(data) % 4:
        data = data + b"\0" * (4 - len(data) % 4)
    words = array("I")
    if words.itemsize != 4:
        raise SystemExit("array('I') is not 32-bit on this platform")
    words.frombytes(data)
    if sys.byteorder == "little":
        words.byteswap()
    total = sum(words)
    while total >> 32:
        total = (total & 0xFFFFFFFF) + (total >> 32)
    return total


def check_flux_cards(cards: dict[str, str], arm: str, pin: dict | None = None) -> tuple[int, int]:
    extname = f"{arm}_FLUX"
    problems = []
    if cards.get("XTENSION") != "IMAGE":
        problems.append(f"XTENSION={cards.get('XTENSION')!r}")
    if cards.get("EXTNAME") != extname:
        problems.append(f"EXTNAME={cards.get('EXTNAME')!r} expected {extname}")
    if cards.get("BITPIX") != "-32":
        problems.append(f"BITPIX={cards.get('BITPIX')!r}")
    if cards.get("NAXIS") != "2":
        problems.append(f"NAXIS={cards.get('NAXIS')!r}")
    if cards.get("BUNIT") != FLUX_BUNIT:
        problems.append(f"BUNIT={cards.get('BUNIT')!r}")
    for key in ("BSCALE", "BZERO"):
        if key in cards and float(cards[key]) != (1.0 if key == "BSCALE" else 0.0):
            problems.append(f"{key}={cards[key]}")
    naxis1 = int(cards.get("NAXIS1", "0"))
    naxis2 = int(cards.get("NAXIS2", "0"))
    if naxis1 != ARMS[arm]:
        problems.append(f"NAXIS1={naxis1} expected {ARMS[arm]}")
    if naxis2 < 1:
        problems.append(f"NAXIS2={naxis2}")
    if pin is not None:
        if naxis2 != int(pin["naxis2"]) or naxis1 != int(pin["naxis1"]):
            problems.append(f"shape {naxis1}x{naxis2} differs from pin {pin['naxis1']}x{pin['naxis2']}")
        if cards.get("DATASUM") != pin["datasum"]:
            problems.append(f"DATASUM card {cards.get('DATASUM')!r} differs from pin {pin['datasum']}")
    if problems:
        raise SystemExit(f"{extname}: invalid header: {'; '.join(problems)}")
    return naxis1, naxis2


# ---------------------------------------------------------------- pins

def load_pins(path: Path) -> list[dict]:
    lines = path.read_text(encoding="utf-8").splitlines()
    header = lines[0].split("\t")
    if header != PIN_COLUMNS:
        raise SystemExit(f"{path}: unexpected columns {header}")
    pins = [dict(zip(header, line.split("\t"))) for line in lines[1:] if line.strip()]
    for pin in pins:
        if len(pin) != len(PIN_COLUMNS):
            raise SystemExit(f"{path}: malformed row {pin}")
    return pins


def range_name(pin: dict) -> str:
    return f"coadd-main-dark-{pin['healpix']}.{pin['arm']}_FLUX.range"


def sample_name(pin: dict) -> str:
    return f"coadd-main-dark-{pin['healpix']}_{pin['arm']}_FLUX.f32le"


# ---------------------------------------------------------------- discover

def curl_bytes(url: str, start: int | None = None, length: int | None = None) -> bytes:
    cmd = ["curl", "-fsSL", "--max-time", "120", "--retry", "5", "--retry-delay", "3"]
    if start is not None:
        cmd += ["-r", f"{start}-{start + length - 1}"]
    return subprocess.run(cmd + [url], capture_output=True, check=True).stdout


def curl_head(url: str) -> dict[str, str]:
    out = subprocess.run(
        ["curl", "-fsSIL", "--max-time", "60", "--retry", "5", "--retry-delay", "3", url],
        capture_output=True, check=True, text=True,
    ).stdout
    headers: dict[str, str] = {}
    for line in out.splitlines():
        if ":" in line:
            key, value = line.split(":", 1)
            headers[key.strip().lower()] = value.strip()
    return headers


def list_dirs(url: str) -> list[int]:
    html = curl_bytes(url).decode("utf-8", "replace")
    return sorted(int(x) for x in re.findall(r'href="(\d+)/"', html))


def walk_hdus(url: str, size: int) -> list[dict]:
    hdus = []
    offset = 0
    while offset < size:
        want = BLOCK * 10
        while True:
            buf = curl_bytes(url, offset, min(want, size - offset))
            cards, header_len = parse_header(buf)
            if header_len is not None:
                break
            if want >= size - offset:
                raise SystemExit(f"no END card at offset {offset} in {url}")
            want *= 4
        data_len = data_unit_bytes(cards)
        hdus.append({
            "offset": offset,
            "header_bytes": header_len,
            "header_sha256": hashlib.sha256(buf[:header_len]).hexdigest(),
            "cards": cards,
            "data_bytes": data_len,
        })
        offset += header_len + padded(data_len)
    if offset != size:
        raise SystemExit(f"HDU walk ended at {offset}, file size {size}: {url}")
    return hdus


def cmd_discover(args: argparse.Namespace) -> None:
    groups = list_dirs(f"{BASE_URL}/")
    print(f"groups={len(groups)} first={groups[0]} last={groups[-1]}", flush=True)
    k = args.files
    wanted = sorted({round(i * (len(groups) - 1) / (k - 1)) for i in range(k)})
    rows = []
    used_groups: set[int] = set()
    for index in wanted:
        chosen = None
        probe = index
        while chosen is None and probe < len(groups):
            group = groups[probe]
            probe += 1
            if group in used_groups:
                continue
            for healpix in list_dirs(f"{BASE_URL}/{group}/"):
                if healpix // 100 != group:
                    raise SystemExit(f"healpix {healpix} not in group {group}")
                url = f"{BASE_URL}/{group}/{healpix}/coadd-main-dark-{healpix}.fits"
                head = curl_head(url)
                size = int(head.get("content-length", "0"))
                if args.min_bytes <= size <= args.max_bytes:
                    chosen = (group, healpix, url, size, head)
                    break
            if chosen is None:
                print(f"group={group} no coadd file in size band; trying next group", flush=True)
        if chosen is None:
            continue
        group, healpix, url, size, head = chosen
        used_groups.add(group)
        hdus = walk_hdus(url, size)
        primary = hdus[0]
        pc = primary["cards"]
        if (pc.get("SURVEY"), pc.get("PROGRAM"), pc.get("SPGRP"), pc.get("HPXPIXEL")) != ("main", "dark", "healpix", str(healpix)):
            raise SystemExit(f"{url}: primary header identity mismatch {pc}")
        by_name = {h["cards"].get("EXTNAME"): h for h in hdus[1:]}
        for arm in ARMS:
            hdu = by_name[f"{arm}_FLUX"]
            naxis1, naxis2 = check_flux_cards(hdu["cards"], arm)
            if hdu["data_bytes"] != naxis1 * naxis2 * 4:
                raise SystemExit(f"{url}: {arm}_FLUX data size mismatch")
            rows.append({
                "healpix": str(healpix),
                "group": str(group),
                "url": url,
                "file_bytes": str(size),
                "last_modified": head.get("last-modified", ""),
                "etag": head.get("etag", "").strip('"'),
                "primary_header_bytes": str(primary["header_bytes"]),
                "primary_header_sha256": primary["header_sha256"],
                "arm": arm,
                "extname": f"{arm}_FLUX",
                "header_offset": str(hdu["offset"]),
                "header_bytes": str(hdu["header_bytes"]),
                "header_sha256": hdu["header_sha256"],
                "data_offset": str(hdu["offset"] + hdu["header_bytes"]),
                "naxis1": str(naxis1),
                "naxis2": str(naxis2),
                "data_bytes": str(hdu["data_bytes"]),
                "datasum": hdu["cards"]["DATASUM"],
            })
        print(f"group={group} healpix={healpix} bytes={size} ntarget={rows[-1]['naxis2']}", flush=True)
    out = Path(args.out)
    with out.open("w", encoding="utf-8") as handle:
        handle.write("\t".join(PIN_COLUMNS) + "\n")
        for row in rows:
            handle.write("\t".join(row[c] for c in PIN_COLUMNS) + "\n")
    fetched = sum(int(r["header_bytes"]) + int(r["data_bytes"]) for r in rows)
    fetched += sum(int(r["primary_header_bytes"]) for r in rows if r["arm"] == "B")
    print(f"files={len(rows) // 3} hdus={len(rows)} range_bytes={fetched}")


# ---------------------------------------------------------------- download-time validation

def find_pin(pins: list[dict], healpix: str, arm: str) -> dict:
    for pin in pins:
        if pin["healpix"] == healpix and pin["arm"] == arm:
            return pin
    raise SystemExit(f"no pin for healpix={healpix} arm={arm}")


def cmd_validate_primary(args: argparse.Namespace) -> None:
    pin = find_pin(load_pins(Path(args.pins)), args.healpix, "B")
    buf = Path(args.path).read_bytes()
    if len(buf) != int(pin["primary_header_bytes"]):
        raise SystemExit(f"primary header size {len(buf)} != {pin['primary_header_bytes']}")
    if hashlib.sha256(buf).hexdigest() != pin["primary_header_sha256"]:
        raise SystemExit("primary header SHA-256 mismatch")
    cards, header_len = parse_header(buf)
    expected = {"SIMPLE": "T", "NAXIS": "0", "SURVEY": "main", "PROGRAM": "dark", "SPGRP": "healpix", "HPXPIXEL": pin["healpix"]}
    for key, value in expected.items():
        if cards.get(key) != value:
            raise SystemExit(f"primary header {key}={cards.get(key)!r} expected {value!r}")
    if header_len != len(buf):
        raise SystemExit("primary header END position mismatch")
    print(f"primary_ok healpix={pin['healpix']} survey=main program=dark")


def validate_range_bytes(buf: bytes, pin: dict) -> tuple[int, int, bytes]:
    header_bytes = int(pin["header_bytes"])
    data_bytes = int(pin["data_bytes"])
    if len(buf) != header_bytes + data_bytes:
        raise SystemExit(f"{range_name(pin)}: size {len(buf)} != {header_bytes + data_bytes}")
    if hashlib.sha256(buf[:header_bytes]).hexdigest() != pin["header_sha256"]:
        raise SystemExit(f"{range_name(pin)}: header SHA-256 mismatch")
    cards, header_len = parse_header(buf[:header_bytes])
    if header_len != header_bytes:
        raise SystemExit(f"{range_name(pin)}: END card position mismatch")
    naxis1, naxis2 = check_flux_cards(cards, pin["arm"], pin)
    if naxis1 * naxis2 * 4 != data_bytes:
        raise SystemExit(f"{range_name(pin)}: data size mismatch")
    data = buf[header_bytes:]
    datasum = fits_datasum(data)
    if str(datasum) != pin["datasum"]:
        raise SystemExit(f"{range_name(pin)}: DATASUM {datasum} != {pin['datasum']}")
    return naxis1, naxis2, data


def cmd_validate_range(args: argparse.Namespace) -> None:
    pin = find_pin(load_pins(Path(args.pins)), args.healpix, args.arm)
    naxis1, naxis2, _ = validate_range_bytes(Path(args.path).read_bytes(), pin)
    print(f"range_ok {range_name(pin)} shape={naxis2}x{naxis1} datasum={pin['datasum']}")


# ---------------------------------------------------------------- build

def row_profile(values: array, nwave: int, ntarget: int) -> tuple[int, int]:
    zero_rows = constant_rows = 0
    for t in range(ntarget):
        row = values[t * nwave:(t + 1) * nwave]
        if not any(row):
            zero_rows += 1
        elif min(row) == max(row):
            constant_rows += 1
    return zero_rows, constant_rows


def cmd_build(args: argparse.Namespace) -> None:
    pins = load_pins(Path(args.pins))
    downloads = Path(args.downloads)
    samples = Path(args.samples_dir)
    data_root = Path(args.data_root)
    index_path = Path(args.index)
    stats_path = Path(args.stats)
    expected_names = {sample_name(p) for p in pins}
    for arm in ARMS:
        series_dir = samples / SERIES[arm]
        series_dir.mkdir(parents=True, exist_ok=True)
        for stale in series_dir.glob("*.f32le"):
            if stale.name not in expected_names:
                stale.unlink()
    index_path.parent.mkdir(parents=True, exist_ok=True)
    stats_path.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    series_stats = {SERIES[a]: {"samples": 0, "values": 0, "bytes": 0, "zero_rows": 0, "targets": 0} for a in ARMS}
    for pin in pins:
        buf = (downloads / range_name(pin)).read_bytes()
        nwave, ntarget, data = validate_range_bytes(buf, pin)
        values = array("f")
        if values.itemsize != 4:
            raise SystemExit("array('f') is not 32-bit on this platform")
        values.frombytes(data)
        if sys.byteorder == "little":
            values.byteswap()
        if not math.isfinite(sum(values)):
            raise SystemExit(f"{range_name(pin)}: non-finite flux values")
        lo, hi = min(values), max(values)
        if lo == hi:
            raise SystemExit(f"{range_name(pin)}: constant HDU")
        zero_rows, constant_rows = row_profile(values, nwave, ntarget)
        if zero_rows > MAX_ZERO_ROW_FRACTION * ntarget:
            raise SystemExit(f"{range_name(pin)}: {zero_rows}/{ntarget} all-zero rows exceeds limit")
        out_values = values
        if sys.byteorder != "little":
            out_values = array("f", values)
            out_values.byteswap()
        payload = out_values.tobytes()
        sid = SERIES[pin["arm"]]
        out = samples / sid / sample_name(pin)
        tmp = out.with_suffix(".tmp")
        tmp.write_bytes(payload)
        tmp.replace(out)
        rows.append({
            "dataset_id": DATASET_ID,
            "series_id": sid,
            "sample_path": str(out.relative_to(data_root)),
            "numeric_kind": "float",
            "bit_width": 32,
            "endianness": "little",
            "element_size_bytes": 4,
            "sample_size_bytes": len(payload),
            "value_count": len(values),
            "sample_shape": [ntarget, nwave],
            "sample_axes": ["target", "wavelength_pixel"],
            "healpix": int(pin["healpix"]),
            "extname": pin["extname"],
            "source_url": pin["url"],
            "source_data_offset": int(pin["data_offset"]),
            "source_datasum": pin["datasum"],
            "all_zero_rows": zero_rows,
            "constant_nonzero_rows": constant_rows,
            "min": lo,
            "max": hi,
            "sha256": hashlib.sha256(payload).hexdigest(),
        })
        st = series_stats[sid]
        st["samples"] += 1
        st["values"] += len(values)
        st["bytes"] += len(payload)
        st["zero_rows"] += zero_rows
        st["targets"] += ntarget
        print(f"sample {sid} healpix={pin['healpix']} shape={ntarget}x{nwave} zero_rows={zero_rows} min={lo:.6g} max={hi:.6g}", flush=True)
    rows.sort(key=lambda r: (r["series_id"], r["healpix"]))
    tmp_index = index_path.with_suffix(".tmp")
    with tmp_index.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")
    tmp_index.replace(index_path)
    stats = {
        "dataset_id": DATASET_ID,
        "healpix_files": len({p["healpix"] for p in pins}),
        "groups": len({p["group"] for p in pins}),
        "series": series_stats,
        "primary_samples": len(rows),
        "primary_values": sum(r["value_count"] for r in rows),
        "primary_bytes": sum(r["sample_size_bytes"] for r in rows),
    }
    stats_path.write_text(json.dumps(stats, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(stats, sort_keys=True))


# ---------------------------------------------------------------- verify

def cmd_verify(args: argparse.Namespace) -> None:
    import tomllib

    pins = load_pins(Path(args.pins))
    downloads = Path(args.downloads)
    data_root = Path(args.data_root)
    manifest = tomllib.loads(Path(args.manifest).read_text(encoding="utf-8"))
    rows = [json.loads(line) for line in Path(args.index).read_text(encoding="utf-8").splitlines() if line.strip()]
    if len(rows) != len(pins):
        raise SystemExit(f"index rows {len(rows)} != pinned HDUs {len(pins)}")
    by_key = {(r["series_id"], str(r["healpix"])): r for r in rows}
    if len(by_key) != len(rows):
        raise SystemExit("duplicate index rows")
    healpix_by_arm: dict[str, set[str]] = {arm: set() for arm in ARMS}
    sha_seen: set[str] = set()
    totals = {SERIES[a]: [0, 0] for a in ARMS}
    for pin in pins:
        sid = SERIES[pin["arm"]]
        row = by_key.get((sid, pin["healpix"]))
        if row is None:
            raise SystemExit(f"missing index row for {sid} healpix {pin['healpix']}")
        buf = (downloads / range_name(pin)).read_bytes()
        header_bytes = int(pin["header_bytes"])
        # Independent re-parse of the header cards with a fixed-column reader.
        header = buf[:header_bytes]
        card_map = {}
        for i in range(0, header_bytes, 80):
            card = header[i:i + 80].decode("ascii")
            if card.startswith("END     "):
                break
            if card[8:10] == "= ":
                card_map.setdefault(card[:8].rstrip(), card[10:])
        extname = card_map["EXTNAME"].split("'")[1].strip()
        bunit = card_map["BUNIT"].split("'")[1].strip()
        nwave = int(card_map["NAXIS1"].split("/")[0])
        ntarget = int(card_map["NAXIS2"].split("/")[0])
        if extname != f"{pin['arm']}_FLUX" or bunit != FLUX_BUNIT or nwave != ARMS[pin["arm"]]:
            raise SystemExit(f"{range_name(pin)}: header re-check failed ({extname}, {bunit}, {nwave})")
        if int(card_map["BITPIX"].split("/")[0]) != -32:
            raise SystemExit(f"{range_name(pin)}: BITPIX is not -32")
        data = buf[header_bytes:]
        if len(data) != nwave * ntarget * 4 or ntarget != int(pin["naxis2"]):
            raise SystemExit(f"{range_name(pin)}: data unit size mismatch")
        if str(fits_datasum(data)) != pin["datasum"]:
            raise SystemExit(f"{range_name(pin)}: DATASUM mismatch")
        n = nwave * ntarget
        decoded = struct.unpack(f">{n}f", data)
        expected = struct.pack(f"<{n}f", *decoded)
        sample_path = data_root / row["sample_path"]
        payload = sample_path.read_bytes()
        if payload != expected:
            raise SystemExit(f"{sample_path}: bytes differ from independent big-endian decode")
        digest = hashlib.sha256(payload).hexdigest()
        if digest != row["sha256"] or digest in sha_seen:
            raise SystemExit(f"{sample_path}: sha256 mismatch or duplicate sample")
        sha_seen.add(digest)
        if row["value_count"] != n or row["sample_size_bytes"] != 4 * n or row["sample_shape"] != [ntarget, nwave]:
            raise SystemExit(f"{sample_path}: index geometry mismatch")
        if (row["numeric_kind"], row["bit_width"], row["endianness"], row["element_size_bytes"]) != ("float", 32, "little", 4):
            raise SystemExit(f"{sample_path}: index dtype mismatch")
        if row["dataset_id"] != DATASET_ID or not row["sample_path"].startswith(f"samples/{DATASET_ID}/{sid}/"):
            raise SystemExit(f"{sample_path}: index identity mismatch")
        finite = [v for v in decoded if math.isfinite(v)]
        if len(finite) != n:
            raise SystemExit(f"{sample_path}: non-finite values")
        lo, hi = min(decoded), max(decoded)
        if lo == hi:
            raise SystemExit(f"{sample_path}: constant sample")
        if (lo, hi) != (row["min"], row["max"]):
            raise SystemExit(f"{sample_path}: min/max mismatch index={row['min']},{row['max']} recomputed={lo},{hi}")
        zero_rows = sum(1 for t in range(ntarget) if not any(decoded[t * nwave:(t + 1) * nwave]))
        if zero_rows != row["all_zero_rows"] or zero_rows > MAX_ZERO_ROW_FRACTION * ntarget:
            raise SystemExit(f"{sample_path}: all-zero rows {zero_rows} (index {row['all_zero_rows']})")
        nonzero = sum(1 for v in decoded if v != 0.0)
        if nonzero < 0.5 * n:
            raise SystemExit(f"{sample_path}: only {nonzero}/{n} nonzero values")
        distinct = len(set(decoded[: min(n, 200000)]))
        if distinct < 1000:
            raise SystemExit(f"{sample_path}: only {distinct} distinct values in first 200k")
        healpix_by_arm[pin["arm"]].add(pin["healpix"])
        totals[sid][0] += 1
        totals[sid][1] += 4 * n
        print(f"verified {sid} healpix={pin['healpix']} shape={ntarget}x{nwave} zero_rows={zero_rows} nonzero={nonzero}", flush=True)
    if not (healpix_by_arm["B"] == healpix_by_arm["R"] == healpix_by_arm["Z"]):
        raise SystemExit("arms do not cover the same healpix files")
    if len(healpix_by_arm["B"]) < 20:
        raise SystemExit(f"only {len(healpix_by_arm['B'])} healpix files")
    declared = {s["id"]: s for s in manifest["series"]}
    for sid, (count, size) in totals.items():
        series = declared.get(sid)
        if series is None or series.get("role") != "primary":
            raise SystemExit(f"manifest lacks primary series {sid}")
        if series["sample_count"] != count or series["total_size_bytes"] != size:
            raise SystemExit(f"manifest {sid}: declared {series['sample_count']}/{series['total_size_bytes']} realized {count}/{size}")
    total = sum(size for _, size in totals.values())
    if total > 1_000_000_000:
        raise SystemExit(f"primary bytes {total} exceed cap")
    print(f"verify_ok healpix_files={len(healpix_by_arm['B'])} samples={len(rows)} primary_bytes={total}")


# ---------------------------------------------------------------- self-test

def cmd_selftest(_: argparse.Namespace) -> None:
    """Round-trip a synthetic FITS image HDU through the parser and checksum."""
    nwave, ntarget = ARMS["R"], 3
    values = [((i * 37) % 101 - 50) / 7.0 for i in range(nwave * ntarget)]
    for i in range(nwave):
        values[nwave + i] = 0.0  # one all-zero row
    data = struct.pack(f">{len(values)}f", *values)
    datasum = 0
    for (word,) in struct.iter_unpack(">I", data):
        datasum = datasum + word
        datasum = (datasum & 0xFFFFFFFF) + (datasum >> 32)
    cards = [
        "XTENSION= 'IMAGE   '", "BITPIX  =                  -32", "NAXIS   =                    2",
        f"NAXIS1  = {nwave:20d}", f"NAXIS2  = {ntarget:20d}", "PCOUNT  =                    0",
        "GCOUNT  =                    1", "EXTNAME = 'R_FLUX  '", f"BUNIT   = '{FLUX_BUNIT}'",
        f"DATASUM = '{datasum}'", "END",
    ]
    header = b"".join(c.ljust(80).encode("ascii") for c in cards)
    header += b" " * (padded(len(header)) - len(header))
    parsed, header_len = parse_header(header + data)
    assert header_len == BLOCK, header_len
    assert data_unit_bytes(parsed) == len(data)
    assert fits_datasum(data) == datasum, (fits_datasum(data), datasum)
    pin = {"naxis1": str(nwave), "naxis2": str(ntarget), "datasum": str(datasum), "header_bytes": str(BLOCK),
           "data_bytes": str(len(data)), "header_sha256": hashlib.sha256(header).hexdigest(), "arm": "R",
           "healpix": "0", "extname": "R_FLUX"}
    n1, n2, raw = validate_range_bytes(header + data, pin)
    arr = array("f")
    arr.frombytes(raw)
    if sys.byteorder == "little":
        arr.byteswap()
    assert arr.tobytes() == struct.pack(f"<{len(values)}f", *values)
    assert row_profile(arr, n1, n2) == (1, 0)
    bad = bytearray(header + data)
    bad[-1] ^= 1
    try:
        validate_range_bytes(bytes(bad), pin)
    except SystemExit:
        pass
    else:
        raise AssertionError("corrupted data passed DATASUM")
    print("selftest_ok")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("discover")
    p.add_argument("--out", required=True)
    p.add_argument("--files", type=int, default=36)
    p.add_argument("--min-bytes", type=int, default=100_000_000)
    p.add_argument("--max-bytes", type=int, default=250_000_000)
    p = sub.add_parser("validate-primary")
    for name in ("--pins", "--healpix", "--path"):
        p.add_argument(name, required=True)
    p = sub.add_parser("validate-range")
    for name in ("--pins", "--healpix", "--arm", "--path"):
        p.add_argument(name, required=True)
    for name in ("build", "verify"):
        p = sub.add_parser(name)
        for opt in ("--pins", "--downloads", "--samples-dir", "--index", "--stats", "--data-root"):
            p.add_argument(opt, required=True)
        if name == "verify":
            p.add_argument("--manifest", required=True)
    sub.add_parser("selftest")
    args = parser.parse_args()
    {
        "discover": cmd_discover,
        "validate-primary": cmd_validate_primary,
        "validate-range": cmd_validate_range,
        "build": cmd_build,
        "verify": cmd_verify,
        "selftest": cmd_selftest,
    }[args.cmd](args)


if __name__ == "__main__":
    main()
