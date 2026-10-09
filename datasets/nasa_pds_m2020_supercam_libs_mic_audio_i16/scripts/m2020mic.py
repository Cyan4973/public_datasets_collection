#!/usr/bin/env python3
"""Mars 2020 SuperCam raw microphone audio (PDS4 FITS SOUND HDU) helper.

Pure standard library. Subcommands:

  candidates  parse the data_raw_audio sol directory listings -> candidates.tsv
  round       print the next (filename, url, size) to probe for each unresolved
              selection slot, given the probe files already fetched
  finalize    resolve every slot from the probed headers and write sources.tsv
  build       decode the SOUND HDU of every pinned product into raw uint16 LE
"""
from __future__ import annotations

import argparse
import collections
import csv
import hashlib
import json
import math
import re
import struct
import sys
from pathlib import Path

DATASET_ID = "nasa_pds_m2020_supercam_libs_mic_audio_i16"
SERIES_ID = "supercam_mic_libs_100khz_gain2_u16"
BASE_HOST = "https://pds-geosciences.wustl.edu"
COLLECTION_PATH = "/m2020/urn-nasa-pds-mars2020_supercam/data_raw_audio/"
BLOCK = 2880
CARD = 80
PRIMARY_HEADER_BYTES = 17280          # probed with a range GET during discovery
SOUND_RECORDS = 174000                # 1.74 s at 100 kHz
SOUND_DATA_BYTES = 2 * SOUND_RECORDS  # 348,000 bytes of big-endian int16
SOUND_HDU_TAIL = BLOCK + ((SOUND_DATA_BYTES + BLOCK - 1) // BLOCK) * BLOCK  # 351,360
MAX_CANDIDATE_FILE_BYTES = 1_000_000  # short LIBS recordings; long recordings are 2-23 MB
SLOTS = 800

# Primary-header keywords that define the single recording configuration kept.
REQUIRED_PRIMARY = {
    "MIC_SAMP": "100000",   # Data Sampling (Hz)
    "MIC_SAMC": "21",       # Microphone Sample Code
    "MIC_DOWN": "F",        # not downsampled from 100 kHz
    "MIC_GAIN": "2",        # dominant microphone gain setting
    "MIC_DURA": "1",
    "HSS_NUMW": "174000",   # words sent by MU_SEND_HSS_DATA
    "LIBS_MIC": "T",        # LIBS+MIC activity
    "LASDNS00": "30",       # 30-shot laser burst
    "SCMDTYPE": "9",
}
REQUIRED_SOUND = {
    "XTENSION": "BINTABLE",
    "BITPIX": "8",
    "NAXIS": "2",
    "NAXIS1": "2",
    "NAXIS2": str(SOUND_RECORDS),
    "PCOUNT": "0",
    "GCOUNT": "1",
    "TFIELDS": "1",
    "EXTNAME": "SOUND",
    "TTYPE1": "Sound",
    "TFORM1": "I",
    "TZERO1": "32768",
}
# Quality policy shared with verify: a dead or stuck microphone recording is
# rejected (dropped and logged), never patched.
MIN_DISTINCT = 64
MAX_DOMINANT_FRACTION = 0.5

NAME_RE = re.compile(r"^LS__(\d{4})_(\d{10})_(\d{3})E[A-Z0-9]{2}__\d{7}SCAM\d{5}_(\d{3})_LUJ(\d{2})\.fits$")


def parse_header(raw: bytes, start: int = 0) -> tuple[dict[str, str], int]:
    """Parse FITS header cards from `start`; return (cards, header_bytes)."""
    cards: dict[str, str] = {}
    pos = start
    while True:
        block = raw[pos:pos + BLOCK]
        if len(block) != BLOCK:
            raise ValueError(f"truncated FITS header at byte {pos}")
        pos += BLOCK
        for i in range(0, BLOCK, CARD):
            card = block[i:i + CARD].decode("ascii")
            key = card[:8].rstrip()
            if key == "END":
                return cards, pos - start
            if card[8:10] == "= ":
                value = card[10:]
                if value.lstrip().startswith("'"):
                    body = value.lstrip()[1:]
                    value = body[:body.index("'")].rstrip()
                else:
                    value = value.split("/")[0].strip()
                if key in cards:
                    raise ValueError(f"duplicate FITS keyword {key}")
                cards[key] = value


def data_bytes(cards: dict[str, str]) -> int:
    naxis = int(cards.get("NAXIS", "0"))
    if naxis == 0:
        return 0
    n = abs(int(cards["BITPIX"])) // 8
    for axis in range(1, naxis + 1):
        n *= int(cards[f"NAXIS{axis}"])
    return int(cards.get("GCOUNT", "1")) * (n + int(cards.get("PCOUNT", "0")))


def walk_hdus(raw: bytes) -> list[dict]:
    hdus = []
    pos = 0
    while pos < len(raw):
        cards, hlen = parse_header(raw, pos)
        size = data_bytes(cards)
        hdus.append({"header_offset": pos, "data_offset": pos + hlen, "data_bytes": size, "cards": cards})
        pos += hlen + ((size + BLOCK - 1) // BLOCK) * BLOCK
    if pos != len(raw):
        raise ValueError(f"FITS HDU walk ended at {pos}, file has {len(raw)} bytes")
    return hdus


def primary_ok(cards: dict[str, str]) -> list[str]:
    return [f"{k}={cards.get(k)!r}" for k, v in REQUIRED_PRIMARY.items() if cards.get(k) != v]


def sound_ok(cards: dict[str, str]) -> list[str]:
    bad = [f"{k}={cards.get(k)!r}" for k, v in REQUIRED_SOUND.items() if cards.get(k) != v]
    if cards.get("TSCAL1", "1") not in ("1", "1.0"):
        bad.append(f"TSCAL1={cards.get('TSCAL1')!r}")
    return bad


def decode_sound(raw: bytes) -> bytes:
    """Big-endian int16 stored codes -> little-endian uint16 physical (stored + 32768)."""
    if len(raw) != SOUND_DATA_BYTES:
        raise ValueError("SOUND data length mismatch")
    stored = struct.unpack(f">{SOUND_RECORDS}h", raw)
    return struct.pack(f"<{SOUND_RECORDS}H", *(v + 32768 for v in stored))


def quality(values: tuple[int, ...] | list[int]) -> dict:
    counts = collections.Counter(values)
    n = len(values)
    mean = sum(values) / n
    sd = math.sqrt(sum((v - mean) ** 2 for v in values) / n)
    top_value, top_count = counts.most_common(1)[0]
    return {
        "min": min(values),
        "max": max(values),
        "mean": round(mean, 4),
        "std": round(sd, 4),
        "distinct_values": len(counts),
        "dominant_value": top_value,
        "dominant_fraction": round(top_count / n, 6),
    }


def quality_reject(q: dict) -> str:
    if q["distinct_values"] < MIN_DISTINCT:
        return f"distinct_values {q['distinct_values']} < {MIN_DISTINCT}"
    if q["dominant_fraction"] > MAX_DOMINANT_FRACTION:
        return f"dominant_fraction {q['dominant_fraction']} > {MAX_DOMINANT_FRACTION}"
    return ""


# ---------------------------------------------------------------- discovery

def cmd_candidates(args: argparse.Namespace) -> None:
    rows = []
    pattern = re.compile(r"(\d+) <A HREF=\"(" + re.escape(COLLECTION_PATH) + r"sol_(\d{5})/([^\"/]+\.fits))\">", re.I)
    listings = sorted(Path(args.listings).glob("sol_*.html"))
    if len(listings) < 1000:
        raise SystemExit(f"only {len(listings)} sol listings")
    for listing in listings:
        text = listing.read_text(encoding="latin-1")
        for m in pattern.finditer(text):
            size, href, sol, name = int(m.group(1)), m.group(2), m.group(3), m.group(4)
            if listing.stem != f"sol_{sol}":
                raise SystemExit(f"listing {listing.name} links outside its sol: {href}")
            mm = NAME_RE.match(name)
            if not mm:
                raise SystemExit(f"unexpected raw-audio product name {name}")
            if int(mm.group(1)) != int(sol):
                raise SystemExit(f"sol mismatch {name}")
            rows.append((name, BASE_HOST + href, size, int(sol)))
    names = [r[0] for r in rows]
    if len(set(names)) != len(names):
        raise SystemExit("duplicate product file names across listings")
    print(f"listed_fits={len(rows)} listings={len(listings)}")
    kept = sorted((r for r in rows if r[2] < MAX_CANDIDATE_FILE_BYTES), key=lambda r: r[0])
    with open(args.out, "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh, delimiter="\t", lineterminator="\n")
        w.writerow(["position", "fits_filename", "fits_url", "file_bytes", "sol"])
        for i, r in enumerate(kept):
            w.writerow([i, *r])
    print(f"candidates={len(kept)} (file_bytes < {MAX_CANDIDATE_FILE_BYTES})")


def load_candidates(path: str) -> list[dict]:
    with open(path, encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh, delimiter="\t"))


def probe_status(probe_dir: Path, cand: dict) -> tuple[str, dict]:
    """'missing' | 'reject:<why>' | 'accept' for one probed candidate."""
    name = cand["fits_filename"]
    if int(cand["file_bytes"]) < PRIMARY_HEADER_BYTES + SOUND_HDU_TAIL:
        return "reject:file too small for a 174000-record SOUND HDU", {}
    hdr = probe_dir / f"{name}.primary"
    tail = probe_dir / f"{name}.soundhdr"
    if not hdr.is_file() or not tail.is_file():
        return "missing", {}
    raw = hdr.read_bytes()
    if len(raw) != PRIMARY_HEADER_BYTES:
        return f"reject:primary probe {len(raw)} bytes", {}
    try:
        pcards, plen = parse_header(raw)
    except (ValueError, UnicodeDecodeError) as exc:
        return f"reject:primary parse {exc}", {}
    if pcards.get("SIMPLE") != "T" or plen != PRIMARY_HEADER_BYTES:
        return f"reject:primary header length {plen}", {}
    bad = primary_ok(pcards)
    if bad:
        return "reject:" + ",".join(bad), {}
    sraw = tail.read_bytes()
    if len(sraw) != BLOCK:
        return f"reject:sound probe {len(sraw)} bytes", {}
    try:
        scards, slen = parse_header(sraw)
    except (ValueError, UnicodeDecodeError) as exc:
        return f"reject:sound parse {exc}", {}
    bad = sound_ok(scards)
    if bad or slen != BLOCK:
        return "reject:sound " + ",".join(bad), {}
    return "accept", {
        "primary_header_sha256": hashlib.sha256(raw).hexdigest(),
        "sound_header_sha256": hashlib.sha256(sraw).hexdigest(),
        "mic_gain": pcards["MIC_GAIN"],
        "mic_samp_hz": pcards["MIC_SAMP"],
        "emd_sclk": pcards.get("EMD_SCLK", ""),
        "emd_scet": pcards.get("EMD_SCET", ""),
        "laser_power": pcards.get("LASPOWER", ""),
    }


def slot_windows(n_cand: int, slots: int) -> list[range]:
    return [range(k * n_cand // slots, (k + 1) * n_cand // slots) for k in range(slots)]


def cmd_round(args: argparse.Namespace) -> None:
    cands = load_candidates(args.candidates)
    probe_dir = Path(args.probe_dir)
    for window in slot_windows(len(cands), args.slots):
        for pos in window:
            status, _ = probe_status(probe_dir, cands[pos])
            if status == "accept":
                break
            if status == "missing":
                c = cands[pos]
                print(f"{c['fits_filename']}\t{c['fits_url']}\t{c['file_bytes']}")
                break


def cmd_finalize(args: argparse.Namespace) -> None:
    cands = load_candidates(args.candidates)
    probe_dir = Path(args.probe_dir)
    md5 = {}
    for line in Path(args.md5).read_text(encoding="latin-1").splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[1].lower().startswith("data_raw_audio\\"):
            md5[parts[1].split("\\")[-1]] = parts[0].lower()
    inventory = {}
    for line in Path(args.inventory).read_text(encoding="ascii").splitlines():
        lidvid = line.split(",")[1]
        lid, vid = lidvid.split("::")
        inventory[lid.rsplit(":", 1)[1]] = vid
    print(f"md5_entries_raw_audio={len(md5)} inventory_products={len(inventory)}")
    out = []
    reasons = collections.Counter()
    unresolved = 0
    for k, window in enumerate(slot_windows(len(cands), args.slots)):
        chosen = None
        for pos in window:
            status, meta = probe_status(probe_dir, cands[pos])
            if status == "missing":
                raise SystemExit(f"slot {k} not fully probed (position {pos})")
            if status == "accept":
                chosen = (cands[pos], meta)
                break
            reasons[status.split(",")[0][:60]] += 1
        if chosen is None:
            unresolved += 1
            continue
        c, meta = chosen
        name = c["fits_filename"]
        if name not in md5:
            raise SystemExit(f"no bundle MD5 for {name}")
        mm = NAME_RE.match(name)
        lid_tail = name[:-7].lower() + ".fits"   # LUJ03.fits -> luj.fits
        if inventory.get(lid_tail, "").split(".")[0] != str(int(mm.group(5))):
            raise SystemExit(f"{name}: collection inventory LIDVID {inventory.get(lid_tail)!r} does not match file version")
        out.append({
            "ordinal": len(out) + 1,
            "product_id": name[:-5].lower(),
            "fits_filename": name,
            "fits_url": c["fits_url"],
            "file_bytes": int(c["file_bytes"]),
            "md5": md5[name],
            "sol": int(c["sol"]),
            "sclk": int(mm.group(2)),
            "sound_header_offset": int(c["file_bytes"]) - SOUND_HDU_TAIL,
            **meta,
        })
    print(f"slots={args.slots} resolved={len(out)} unresolved={unresolved}")
    for r, n in reasons.most_common(10):
        print(f"  probe_reject {n} {r}")
    cols = list(out[0].keys())
    with open(args.out, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, delimiter="\t", lineterminator="\n")
        w.writeheader()
        w.writerows(out)
    sols = sorted({r["sol"] for r in out})
    print(f"products={len(out)} distinct_sols={len(sols)} sol_range={sols[0]}-{sols[-1]} "
          f"fits_bytes={sum(r['file_bytes'] for r in out)}")


# -------------------------------------------------------------------- build

def load_sources(path: str) -> list[dict]:
    with open(path, encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh, delimiter="\t"))


def cmd_build(args: argparse.Namespace) -> None:
    sources = load_sources(args.sources)
    download_dir = Path(args.download_dir)
    samples_dir = Path(args.samples_dir)
    data_root = Path(args.data_root).resolve()
    samples_dir.mkdir(parents=True, exist_ok=True)
    for stale in samples_dir.glob("*.bin"):
        stale.unlink()
    Path(args.index).parent.mkdir(parents=True, exist_ok=True)
    Path(args.stats).parent.mkdir(parents=True, exist_ok=True)
    rows = []
    rejected = []
    for src in sources:
        name = src["fits_filename"]
        raw = (download_dir / name).read_bytes()
        if len(raw) != int(src["file_bytes"]):
            raise SystemExit(f"{name}: size {len(raw)} != pinned {src['file_bytes']}")
        if hashlib.md5(raw).hexdigest() != src["md5"]:
            raise SystemExit(f"{name}: MD5 mismatch")
        hdus = walk_hdus(raw)
        bad = primary_ok(hdus[0]["cards"])
        if bad:
            raise SystemExit(f"{name}: primary header outside configuration: {bad}")
        sound = [h for h in hdus if h["cards"].get("EXTNAME") == "SOUND"]
        if len(sound) != 1 or sound[0] is not hdus[-1]:
            raise SystemExit(f"{name}: expected exactly one SOUND HDU, last in file")
        s = sound[0]
        bad = sound_ok(s["cards"])
        if bad:
            raise SystemExit(f"{name}: SOUND header outside configuration: {bad}")
        if s["header_offset"] != int(src["sound_header_offset"]) or s["data_bytes"] != SOUND_DATA_BYTES:
            raise SystemExit(f"{name}: SOUND HDU at {s['header_offset']} != pinned {src['sound_header_offset']}")
        if raw[s["data_offset"] + SOUND_DATA_BYTES:].strip(b"\x00"):
            raise SystemExit(f"{name}: non-zero FITS padding after SOUND data")
        payload = decode_sound(raw[s["data_offset"]:s["data_offset"] + SOUND_DATA_BYTES])
        values = struct.unpack(f"<{SOUND_RECORDS}H", payload)
        q = quality(values)
        why = quality_reject(q)
        if why:
            rejected.append({"product_id": src["product_id"], "reason": why, **q})
            print(f"quality_reject {src['product_id']} {why}")
            continue
        out = samples_dir / f"{int(src['ordinal']):04d}_{src['product_id']}.bin"
        out.write_bytes(payload)
        rows.append({
            "dataset_id": DATASET_ID,
            "series_id": SERIES_ID,
            "sample_path": str(out.resolve().relative_to(data_root)),
            "numeric_kind": "uint",
            "bit_width": 16,
            "endianness": "little",
            "element_size_bytes": 2,
            "sample_size_bytes": len(payload),
            "value_count": SOUND_RECORDS,
            "sample_rate_hz": 100000,
            "product_id": src["product_id"],
            "sol": int(src["sol"]),
            "sclk": int(src["sclk"]),
            "mic_gain": int(src["mic_gain"]),
            "source_md5": src["md5"],
            "sha256": hashlib.sha256(payload).hexdigest(),
            **q,
        })
    with open(args.index, "w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, sort_keys=True) + "\n")
    summary = {
        "dataset_id": DATASET_ID,
        "series_id": SERIES_ID,
        "pinned_products": len(sources),
        "samples": len(rows),
        "quality_rejected": rejected,
        "total_values": sum(r["value_count"] for r in rows),
        "total_bytes": sum(r["sample_size_bytes"] for r in rows),
        "distinct_sols": len({r["sol"] for r in rows}),
        "sol_min": min(r["sol"] for r in rows),
        "sol_max": max(r["sol"] for r in rows),
        "value_min": min(r["min"] for r in rows),
        "value_max": max(r["max"] for r in rows),
        "median_distinct_values": sorted(r["distinct_values"] for r in rows)[len(rows) // 2],
        "max_dominant_fraction": max(r["dominant_fraction"] for r in rows),
        "sources_sha256": hashlib.sha256(Path(args.sources).read_bytes()).hexdigest(),
    }
    Path(args.stats).write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in summary.items() if k != "quality_rejected"}, sort_keys=True))
    print(f"quality_rejected={len(rejected)}")


def main() -> None:
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("candidates")
    a.add_argument("--listings", required=True)
    a.add_argument("--out", required=True)
    for name in ("round", "finalize"):
        a = sub.add_parser(name)
        a.add_argument("--candidates", required=True)
        a.add_argument("--probe-dir", required=True)
        a.add_argument("--slots", type=int, default=SLOTS)
        if name == "finalize":
            a.add_argument("--md5", required=True)
            a.add_argument("--inventory", required=True)
            a.add_argument("--out", required=True)
    a = sub.add_parser("build")
    for opt in ("--sources", "--download-dir", "--samples-dir", "--index", "--stats", "--data-root"):
        a.add_argument(opt, required=True)
    args = p.parse_args()
    {"candidates": cmd_candidates, "round": cmd_round, "finalize": cmd_finalize, "build": cmd_build}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
