#!/usr/bin/env python3
"""NOAA NEFSC SBNMS MARU array AIFF recipe helper (pure standard library).

Commands
  discover      re-derive files.tsv rows from GCS listing pages + deployment JSONs
  check-iso     validate the NCEI ISO 19115 record (DOI, citation, constraints)
  check-meta    validate pinned deployment JSONs (md5, 2 kHz / 12-bit, Good channels)
  check-aiff    validate one downloaded AIFF (size, md5, header layout)
  selftest      synthetic AIFF + exclusion-rule self-test
  build         decode AIFF -> one little-endian int16 sample per kept channel
  verify        independent re-decode and full output check

Material: Cornell MARU bottom-mounted recorders, NOAA NEFSC / ONMS Stellwagen
Bank National Marine Sanctuary arrays 2007-2010 (DOI 10.25921/g3vk-v972).
Each AIFF holds 10 time-aligned channels (one per MARU site), 1,800,000
frames at 2000 Hz, 16-bit big-endian codes carrying 12-bit ADC values
MSB-aligned (every value is a multiple of 16).
"""
from __future__ import annotations

import argparse
import array
import base64
import collections
import glob
import hashlib
import json
import math
import os
import re
import struct
import sys
import tomllib

DATASET_ID = "noaa_nefsc_sbnms_maru_hydrophone_i16"
SERIES_ID = "sbnms_maru_2khz_pressure_counts_i16"
RECIPE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# MARU_FILES_TSV / MARU_META_TSV exist only for synthetic end-to-end tests.
FILES_TSV = os.environ.get("MARU_FILES_TSV", os.path.join(RECIPE_DIR, "files.tsv"))
META_TSV = os.environ.get("MARU_META_TSV", os.path.join(RECIPE_DIR, "meta.tsv"))
BUCKET_URL = "https://storage.googleapis.com/noaa-passive-bioacoustic/"

CHANNELS = 10
FRAMES = 1_800_000
BITS = 16
RATE = 2000
FRAME_BYTES = CHANNELS * 2
SSND_BYTES = FRAMES * FRAME_BYTES
FILE_BYTES = 12 + (8 + 18) + (8 + 8 + SSND_BYTES)  # 36,000,054
DATA_OFFSET = FILE_BYTES - SSND_BYTES  # 54
LATTICE = 16

# exclusion thresholds (shared by build and verify)
RAIL_FRACTION = 0.01   # count(min) + count(max) above this share of frames
MODE_FRACTION = 0.50   # one value above this share of frames
MIN_STD = 16.0         # below one 12-bit step
MIN_KEPT = int(os.environ.get("MARU_MIN_KEPT", "100"))  # build fails below this (override: tests only)

ISO_DOI = "10.25921/g3vk-v972"
ISO_CITE = ("Cite as: NOAA Northeast Fisheries Science Center and NOAA Office of National "
            "Marine Sanctuaries. 2020. An Ocean Observing System for Large-Scale Monitoring "
            "and Mapping of Noise Throughout the Stellwagen Bank National Marine Sanctuary.")
ISO_ALLOWED_PREFIXES = ("Distribution liability:", "Use liability:", "Cite as:")
ISO_BUCKET_LINK = "https://console.cloud.google.com/storage/browser/noaa-passive-bioacoustic/nefsc/audio/sbnms"

FILE_FIELDS = ["deployment", "object", "size", "md5_b64", "crc32c_b64", "generation", "good_channels"]
META_FIELDS = ["deployment", "object", "size", "md5_b64"]


def die(msg: str) -> None:
    print(f"FATAL: {msg}", file=sys.stderr)
    sys.exit(1)


def read_tsv(path: str, fields: list[str]) -> list[dict]:
    rows = []
    with open(path, encoding="utf-8") as fh:
        header = fh.readline().rstrip("\n").split("\t")
        if header != fields:
            die(f"{path}: header {header} != {fields}")
        for line in fh:
            if not line.strip() or line.startswith("#"):
                continue
            parts = line.rstrip("\n").split("\t")
            if len(parts) != len(fields):
                die(f"{path}: bad row {line!r}")
            rows.append(dict(zip(fields, parts)))
    return rows


def files_rows() -> list[dict]:
    return read_tsv(FILES_TSV, FILE_FIELDS)


def meta_rows() -> list[dict]:
    return read_tsv(META_TSV, META_FIELDS)


def md5_b64(path: str) -> str:
    h = hashlib.md5()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 22), b""):
            h.update(block)
    return base64.b64encode(h.digest()).decode()


def local_name(obj: str) -> str:
    return obj.split("/")[-1]


def deployment_of(obj: str) -> str:
    m = re.match(r"^nefsc/audio/sbnms/(sbnms_[0-9_]+)/", obj)
    if not m:
        die(f"unexpected object path {obj}")
    return m.group(1)


# ---------------------------------------------------------------- AIFF

def ext80_to_float(b: bytes) -> float:
    if len(b) != 10:
        raise ValueError("extended must be 10 bytes")
    se, mant = struct.unpack(">HQ", b)
    sign = -1.0 if se & 0x8000 else 1.0
    exp = se & 0x7FFF
    if exp == 0 and mant == 0:
        return 0.0
    if exp == 0x7FFF:
        raise ValueError("inf/nan sample rate")
    return sign * mant * 2.0 ** (exp - 16383 - 63)


def parse_aiff_header(head: bytes, file_size: int) -> dict:
    """Generic IFF chunk walk over the header bytes (build path)."""
    if head[0:4] != b"FORM" or head[8:12] != b"AIFF":
        raise ValueError("not a FORM/AIFF file")
    form_size = struct.unpack(">I", head[4:8])[0]
    if form_size + 8 != file_size:
        raise ValueError(f"FORM size {form_size} + 8 != file size {file_size}")
    pos = 12
    chunks = []
    comm = None
    ssnd = None
    while pos < file_size:
        if pos + 8 > len(head):
            raise ValueError("chunk header beyond provided header bytes")
        cid = head[pos:pos + 4]
        csize = struct.unpack(">I", head[pos + 4:pos + 8])[0]
        chunks.append(cid.decode("latin-1"))
        body = pos + 8
        if cid == b"COMM":
            if csize != 18:
                raise ValueError(f"COMM size {csize} != 18")
            ch, frames, bits = struct.unpack(">hIh", head[body:body + 8])
            rate = ext80_to_float(head[body + 8:body + 18])
            comm = {"channels": ch, "frames": frames, "bits": bits, "rate": rate}
        elif cid == b"SSND":
            offset, block = struct.unpack(">II", head[body:body + 8])
            ssnd = {"size": csize, "offset": offset, "blocksize": block,
                    "data_start": body + 8 + offset, "data_bytes": csize - 8 - offset}
        pos = body + csize + (csize & 1)
    if pos != file_size:
        raise ValueError(f"chunk walk ended at {pos}, file size {file_size}")
    if comm is None or ssnd is None:
        raise ValueError(f"missing COMM or SSND (chunks {chunks})")
    if chunks != ["COMM", "SSND"]:
        raise ValueError(f"unexpected chunk list {chunks}")
    return {"comm": comm, "ssnd": ssnd, "chunks": chunks}


def check_layout(info: dict, file_size: int) -> None:
    c, s = info["comm"], info["ssnd"]
    if c["channels"] != CHANNELS:
        raise ValueError(f"channels {c['channels']} != {CHANNELS}")
    if c["bits"] != BITS:
        raise ValueError(f"bits {c['bits']} != {BITS}")
    if c["rate"] != float(RATE):
        raise ValueError(f"rate {c['rate']} != {RATE}")
    if c["frames"] != FRAMES:
        raise ValueError(f"frames {c['frames']} != {FRAMES}")
    if s["offset"] != 0 or s["blocksize"] != 0:
        raise ValueError(f"SSND offset/blocksize {s['offset']}/{s['blocksize']} != 0/0")
    if s["data_bytes"] != SSND_BYTES or s["data_start"] != DATA_OFFSET:
        raise ValueError(f"SSND data {s['data_start']}+{s['data_bytes']} != {DATA_OFFSET}+{SSND_BYTES}")
    if file_size != FILE_BYTES:
        raise ValueError(f"file size {file_size} != {FILE_BYTES}")


def build_decode(raw: bytes) -> list[array.array]:
    """Build path: generic header parse, array('h') + byteswap, strided slices."""
    info = parse_aiff_header(raw[:4096], len(raw))
    check_layout(info, len(raw))
    start = info["ssnd"]["data_start"]
    a = array.array("h")
    if a.itemsize != 2:
        die("array('h') itemsize != 2")
    a.frombytes(raw[start:start + info["ssnd"]["data_bytes"]])
    if sys.byteorder == "little":
        a.byteswap()  # big-endian source -> native
    return [a[c::CHANNELS] for c in range(CHANNELS)]


def to_le_bytes(chan: array.array) -> bytes:
    if sys.byteorder == "little":
        return chan.tobytes()
    b = array.array("h", chan)
    b.byteswap()
    return b.tobytes()


EXPECTED_HEADER = (b"FORM" + struct.pack(">I", FILE_BYTES - 8) + b"AIFF"
                   + b"COMM" + struct.pack(">I", 18) + struct.pack(">hIh", CHANNELS, FRAMES, BITS)
                   + bytes.fromhex("4009FA00000000000000")
                   + b"SSND" + struct.pack(">I", SSND_BYTES + 8) + struct.pack(">II", 0, 0))


def verify_decode(raw: bytes) -> list[bytes]:
    """Verify path: fixed-byte header comparison and byte-lane de-interleave."""
    if len(raw) != FILE_BYTES:
        raise ValueError(f"size {len(raw)} != {FILE_BYTES}")
    if raw[:DATA_OFFSET] != EXPECTED_HEADER:
        raise ValueError("header bytes differ from the fixed 10ch/1.8M/16-bit/2000 Hz layout")
    out = []
    for c in range(CHANNELS):
        hi = raw[DATA_OFFSET + 2 * c::FRAME_BYTES]
        lo = raw[DATA_OFFSET + 2 * c + 1::FRAME_BYTES]
        if len(hi) != FRAMES or len(lo) != FRAMES:
            raise ValueError("lane length mismatch")
        le = bytearray(2 * FRAMES)
        le[0::2] = lo
        le[1::2] = hi
        out.append(bytes(le))
    return out


# ---------------------------------------------------------------- stats / rules

def hist_stats(hist: collections.Counter, n: int) -> dict:
    mn, mx = min(hist), max(hist)
    s = sum(v * c for v, c in hist.items())
    mean = s / n
    var = sum(c * (v - mean) ** 2 for v, c in hist.items()) / n
    mode_val, mode_cnt = hist.most_common(1)[0]
    return {
        "min": mn, "max": mx, "mean": mean, "std": math.sqrt(var),
        "distinct_values": len(hist),
        "mode_value": mode_val, "mode_fraction": mode_cnt / n,
        "rail_fraction": (hist[mn] + (hist[mx] if mx != mn else 0)) / n,
        "zero_fraction": hist.get(0, 0) / n,
        "full_scale_count": hist.get(-32768, 0) + hist.get(32752, 0),
        "off_lattice_count": sum(c for v, c in hist.items() if v % LATTICE),
    }


def exclusion_reason(st: dict, good: bool) -> str | None:
    if not good:
        return "publisher_quality_not_good"
    if st["min"] == 0 and st["max"] == 0:
        return "blank_all_zero"
    if st["rail_fraction"] > RAIL_FRACTION:
        return "railed_min_max_share_gt_1pct"
    if st["mode_fraction"] > MODE_FRACTION:
        return "dominated_single_value_gt_50pct"
    if st["std"] < MIN_STD:
        return "near_constant_std_lt_16"
    return None


def good_channels_from_meta(meta: dict) -> list[int]:
    """Channels (1-based) flagged quality 'Good' over the whole deployment."""
    dep = meta["DEPLOYMENT"]
    a_start, a_end = dep["AUDIO_START"], dep["AUDIO_END"]
    good: set[int] = set()
    seen: set[int] = set()
    for q in meta["QUALITY_DETAILS"]["quality_details"]:
        chans = [int(x) for x in str(q["channels"]).split(",") if x.strip()]
        if q["quality"] == "Good" and (q["start"] > a_start or q["end"] < a_end):
            die(f"Good quality entry {q['start']}..{q['end']} does not span the deployment {a_start}..{a_end}")
        for ch in chans:
            if ch in seen:
                die(f"channel {ch} listed in several quality entries")
            seen.add(ch)
            if q["quality"] == "Good":
                good.add(ch)
    return sorted(good)


def check_meta_doc(meta: dict, deployment: str) -> list[int]:
    if meta.get("DATA_COLLECTION_NAME") != "NEFSC_" + deployment.upper():
        die(f"{deployment}: DATA_COLLECTION_NAME {meta.get('DATA_COLLECTION_NAME')}")
    if meta.get("INSTRUMENT_TYPE") != "MARU" or meta.get("SITE") != "SBNMS":
        die(f"{deployment}: instrument/site {meta.get('INSTRUMENT_TYPE')}/{meta.get('SITE')}")
    chans = meta["CHANNELS"]
    if sorted(int(k) for k in chans) != list(range(1, CHANNELS + 1)):
        die(f"{deployment}: channels {sorted(chans)}")
    for k, v in chans.items():
        for s in v["SAMPLING_DETAILS"]["SAMPLING"]:
            if s["SAMPLE_RATE"] != "2" or s["SAMPLE_BITS"] != "12":
                die(f"{deployment} ch{k}: sampling {s['SAMPLE_RATE']} kHz / {s['SAMPLE_BITS']} bit")
    return good_channels_from_meta(meta)


# ---------------------------------------------------------------- discover

SELECT_TIMES = ("000000", "120000")


def cmd_discover(args) -> None:
    items_by_dep: dict[str, list[dict]] = collections.defaultdict(list)
    for path in sorted(glob.glob(os.path.join(args.listings, "*.json"))):
        page = json.load(open(path, encoding="utf-8"))
        for it in page.get("items", []):
            items_by_dep[deployment_of(it["name"])].append(it)
    out_files = [FILE_FIELDS]
    out_meta = [META_FIELDS]
    for dep in sorted(items_by_dep):
        items = items_by_dep[dep]
        aif = sorted((i for i in items if i["name"].endswith(".aif") and "/audio/" in i["name"]),
                     key=lambda i: i["name"])
        if not aif or any(int(i["size"]) != FILE_BYTES for i in aif):
            print(f"# skip {dep}: {len(aif)} aif, sizes {sorted(set(i['size'] for i in aif))[:3]}", file=sys.stderr)
            continue
        jname = f"nefsc/audio/sbnms/{dep}/metadata/NEFSC_{dep.upper()}.json"
        jit = [i for i in items if i["name"] == jname]
        if len(jit) != 1:
            die(f"{dep}: metadata JSON {jname} not listed")
        meta = json.load(open(os.path.join(args.meta, f"{dep}.json"), encoding="utf-8"))
        good = check_meta_doc(meta, dep)
        if not good:
            print(f"# skip {dep}: no channel flagged Good by the publisher", file=sys.stderr)
            continue
        mid = aif[len(aif) // 2]["name"]
        date = re.search(r"_(\d{8})_\d{6}\.aif$", mid).group(1)
        chosen = [i for i in aif if re.search(rf"_{date}_({'|'.join(SELECT_TIMES)})\.aif$", i["name"])]
        if len(chosen) != len(SELECT_TIMES):
            die(f"{dep}: expected {len(SELECT_TIMES)} files on {date}, got {[c['name'] for c in chosen]}")
        out_meta.append([dep, jname, jit[0]["size"], jit[0]["md5Hash"]])
        for c in chosen:
            out_files.append([dep, c["name"], c["size"], c["md5Hash"], c["crc32c"], c["generation"],
                              ",".join(str(g) for g in good)])
        print(f"# {dep}: {len(aif)} aif, middle {local_name(mid)}, good {good}", file=sys.stderr)
    with open(args.out_files, "w", encoding="utf-8") as fh:
        fh.writelines("\t".join(map(str, r)) + "\n" for r in out_files)
    with open(args.out_meta, "w", encoding="utf-8") as fh:
        fh.writelines("\t".join(map(str, r)) + "\n" for r in out_meta)


# ---------------------------------------------------------------- checks

def iso_constraints(text: str) -> list[str]:
    vals = []
    for m in re.finditer(r"<gmd:(otherConstraints|useLimitation)>(.*?)</gmd:\1>", text, re.S):
        inner = re.sub(r"<[^>]+>", " ", m.group(2))
        inner = re.sub(r"\s+", " ", inner).strip()
        if inner:
            vals.append(inner)
    return vals


def cmd_check_iso(args) -> None:
    text = open(args.file, encoding="utf-8", errors="replace").read()
    if "<gmi:MI_Metadata" not in text and "<gmd:MD_Metadata" not in text:
        die("ISO record is not an ISO 19115 XML document")
    for needle in (ISO_DOI, ISO_BUCKET_LINK, "NEFSC_SBNMS_Raw_Data"):
        if needle not in text:
            die(f"ISO record lacks {needle!r}")
    cons = iso_constraints(text)
    if not any(c.startswith(ISO_CITE) for c in cons):
        die("ISO record lacks the expected 'Cite as' constraint")
    extra = [c for c in cons if c != "otherRestrictions" and not c.startswith(ISO_ALLOWED_PREFIXES)]
    if extra:
        die(f"ISO record carries unexpected constraints: {extra}")
    print(f"iso_ok constraints={len(cons)} doi={ISO_DOI}")


def cmd_check_meta(args) -> None:
    rows = meta_rows()
    good_by_dep = {}
    for r in rows:
        path = os.path.join(args.dir, local_name(r["object"]))
        if os.path.getsize(path) != int(r["size"]):
            die(f"{path}: size {os.path.getsize(path)} != {r['size']}")
        if md5_b64(path) != r["md5_b64"]:
            die(f"{path}: md5 mismatch")
        meta = json.load(open(path, encoding="utf-8"))
        good_by_dep[r["deployment"]] = check_meta_doc(meta, r["deployment"])
    for f in files_rows():
        want = [int(x) for x in f["good_channels"].split(",")]
        if good_by_dep.get(f["deployment"]) != want:
            die(f"{f['object']}: pinned good channels {want} != metadata {good_by_dep.get(f['deployment'])}")
    print(f"meta_ok deployments={len(rows)} good={good_by_dep}")


def cmd_check_aiff(args) -> None:
    rows = {local_name(r["object"]): r for r in files_rows()}
    name = os.path.basename(args.file)
    if args.name:
        name = args.name
    r = rows.get(name)
    if r is None:
        die(f"{name} not pinned in files.tsv")
    size = os.path.getsize(args.file)
    if size != int(r["size"]):
        die(f"{args.file}: size {size} != {r['size']}")
    with open(args.file, "rb") as fh:
        head = fh.read(4096)
    info = parse_aiff_header(head, size)
    check_layout(info, size)
    if md5_b64(args.file) != r["md5_b64"]:
        die(f"{args.file}: md5 mismatch (pinned {r['md5_b64']})")
    print(f"aiff_ok {name} channels=10 frames={FRAMES} bits=16 rate=2000")


# ---------------------------------------------------------------- build

def sample_rel(row: dict, ch: int) -> str:
    stem = local_name(row["object"])[:-4]
    return f"samples/{DATASET_ID}/{SERIES_ID}/{row['deployment']}__{stem}__ch{ch:02d}.bin"


def file_time(obj: str) -> str:
    m = re.search(r"_(\d{4})(\d{2})(\d{2})_(\d{2})(\d{2})(\d{2})\.aif$", obj)
    return f"{m.group(1)}-{m.group(2)}-{m.group(3)}T{m.group(4)}:{m.group(5)}:{m.group(6)}"


def cmd_build(args) -> None:
    selftest(quiet=True)
    rows = files_rows()
    meta_alias = {}
    for m in meta_rows():
        meta = json.load(open(os.path.join(args.download_dir, "metadata", local_name(m["object"])), encoding="utf-8"))
        good = check_meta_doc(meta, m["deployment"])
        meta_alias[m["deployment"]] = (meta.get("DEPLOYMENT_ALIAS", ""), good)
    out_dir = os.path.join(args.data_root, "samples", DATASET_ID, SERIES_ID)
    os.makedirs(out_dir, exist_ok=True)
    for old in glob.glob(os.path.join(out_dir, "*.bin")):
        os.remove(old)
    index_rows, exclusions = [], []
    total_bytes = 0
    for r in rows:
        alias, good = meta_alias[r["deployment"]]
        if good != [int(x) for x in r["good_channels"].split(",")]:
            die(f"{r['object']}: good channel pin differs from metadata")
        path = os.path.join(args.download_dir, "audio", local_name(r["object"]))
        raw = open(path, "rb").read()
        if len(raw) != int(r["size"]):
            die(f"{path}: size mismatch")
        chans = build_decode(raw)
        del raw
        kept_bytes: dict[bytes, int] = {}
        for c in range(CHANNELS):
            ch = c + 1
            hist = collections.Counter(chans[c])
            st = hist_stats(hist, FRAMES)
            reason = exclusion_reason(st, ch in good)
            payload = to_le_bytes(chans[c])
            if reason is None:
                if st["off_lattice_count"]:
                    die(f"{r['object']} ch{ch}: {st['off_lattice_count']} values off the 16-count lattice")
                digest = hashlib.sha256(payload).digest()
                if digest in kept_bytes:
                    reason = f"duplicate_of_ch{kept_bytes[digest]:02d}"
                else:
                    kept_bytes[digest] = ch
            if reason is not None:
                exclusions.append({"object": r["object"], "channel": ch, "reason": reason,
                                   "min": st["min"], "max": st["max"], "std": round(st["std"], 3),
                                   "rail_fraction": round(st["rail_fraction"], 6),
                                   "mode_fraction": round(st["mode_fraction"], 6)})
                print(f"exclude {local_name(r['object'])} ch{ch:02d} {reason} std={st['std']:.1f} "
                      f"min={st['min']} max={st['max']} rail={st['rail_fraction']:.4f}")
                continue
            rel = sample_rel(r, ch)
            with open(os.path.join(args.data_root, rel), "wb") as fh:
                fh.write(payload)
            total_bytes += len(payload)
            index_rows.append({
                "dataset_id": DATASET_ID, "series_id": SERIES_ID, "sample_path": rel,
                "numeric_kind": "int", "bit_width": 16, "endianness": "little",
                "element_size_bytes": 2, "sample_size_bytes": len(payload), "value_count": FRAMES,
                "deployment": r["deployment"], "deployment_alias": alias,
                "source_object": r["object"], "source_md5_b64": r["md5_b64"],
                "channel": ch, "file_time_from_name": file_time(r["object"]),
                "sample_rate_hz": RATE, "min": st["min"], "max": st["max"],
                "mean": round(st["mean"], 6), "std": round(st["std"], 6),
                "distinct_values": st["distinct_values"],
                "mode_fraction": round(st["mode_fraction"], 6),
                "rail_fraction": round(st["rail_fraction"], 6),
                "zero_fraction": round(st["zero_fraction"], 6),
                "full_scale_count": st["full_scale_count"],
                "sha256": hashlib.sha256(payload).hexdigest(),
            })
            print(f"keep {local_name(r['object'])} ch{ch:02d} std={st['std']:.1f} min={st['min']} "
                  f"max={st['max']} distinct={st['distinct_values']}")
        del chans
    if len(index_rows) < MIN_KEPT:
        die(f"only {len(index_rows)} channel samples kept (< {MIN_KEPT})")
    os.makedirs(os.path.dirname(args.index), exist_ok=True)
    with open(args.index, "w", encoding="utf-8") as fh:
        for row in index_rows:
            fh.write(json.dumps(row, sort_keys=True) + "\n")
    agg = hashlib.sha256()
    for row in index_rows:
        agg.update(row["sha256"].encode())
    stds = sorted(row["std"] for row in index_rows)
    stats = {
        "dataset_id": DATASET_ID, "files": len(rows), "channels_seen": len(rows) * CHANNELS,
        "samples": len(index_rows), "total_bytes": total_bytes, "values": len(index_rows) * FRAMES,
        "excluded": exclusions,
        "exclusion_counts": dict(collections.Counter(e["reason"].split("_of_")[0] for e in exclusions)),
        "std_min": stds[0], "std_median": stds[len(stds) // 2], "std_max": stds[-1],
        "aggregate_sha256": agg.hexdigest(),
    }
    os.makedirs(os.path.dirname(args.stats), exist_ok=True)
    with open(args.stats, "w", encoding="utf-8") as fh:
        json.dump(stats, fh, indent=2, sort_keys=True)
    print(f"build_ok samples={len(index_rows)} bytes={total_bytes} excluded={len(exclusions)} "
          f"std[min/median/max]={stats['std_min']:.1f}/{stats['std_median']:.1f}/{stats['std_max']:.1f} "
          f"aggregate_sha256={stats['aggregate_sha256']}")


# ---------------------------------------------------------------- verify

def verify_stats(le: bytes) -> dict:
    mv = memoryview(le).cast("h") if sys.byteorder == "little" else None
    if mv is None:
        vals = struct.unpack(f"<{len(le) // 2}h", le)
    else:
        vals = mv
    hist = collections.Counter(vals)
    return hist_stats(hist, len(le) // 2)


def cmd_verify(args) -> None:
    selftest(quiet=True)
    rows = files_rows()
    manifest = tomllib.load(open(args.manifest, "rb"))
    good_by_dep = {}
    for m in meta_rows():
        p = os.path.join(args.download_dir, "metadata", local_name(m["object"]))
        if md5_b64(p) != m["md5_b64"]:
            die(f"{p}: md5 mismatch")
        meta = json.load(open(p, encoding="utf-8"))
        # independent re-derivation of the Good channel set
        good = set()
        for q in meta["QUALITY_DETAILS"]["quality_details"]:
            if q["quality"] == "Good":
                good.update(int(x) for x in str(q["channels"]).split(",") if x.strip())
        good_by_dep[m["deployment"]] = good
    index = [json.loads(line) for line in open(args.index, encoding="utf-8")]
    by_path = {row["sample_path"]: row for row in index}
    if len(by_path) != len(index):
        die("duplicate sample_path in index")
    stats = json.load(open(args.stats, encoding="utf-8"))
    expected_paths, expected_excl = [], []
    for r in rows:
        path = os.path.join(args.download_dir, "audio", local_name(r["object"]))
        if md5_b64(path) != r["md5_b64"]:
            die(f"{path}: md5 mismatch")
        raw = open(path, "rb").read()
        lanes = verify_decode(raw)
        del raw
        seen = {}
        for c, le in enumerate(lanes):
            ch = c + 1
            st = verify_stats(le)
            reason = exclusion_reason(st, ch in good_by_dep[r["deployment"]])
            if reason is None:
                if st["off_lattice_count"]:
                    die(f"{r['object']} ch{ch}: off-lattice values")
                if le in seen:
                    reason = f"duplicate_of_ch{seen[le]:02d}"
                else:
                    seen[le] = ch
            if reason is not None:
                expected_excl.append((r["object"], ch, reason))
                continue
            rel = sample_rel(r, ch)
            expected_paths.append(rel)
            row = by_path.get(rel)
            if row is None:
                die(f"index lacks {rel}")
            out = open(os.path.join(args.data_root, rel), "rb").read()
            if out != le:
                die(f"{rel}: bytes differ from independent re-decode")
            want = {"dataset_id": DATASET_ID, "series_id": SERIES_ID, "numeric_kind": "int",
                    "bit_width": 16, "endianness": "little", "element_size_bytes": 2,
                    "sample_size_bytes": 2 * FRAMES, "value_count": FRAMES,
                    "channel": ch, "source_object": r["object"], "deployment": r["deployment"],
                    "min": st["min"], "max": st["max"], "distinct_values": st["distinct_values"],
                    "sha256": hashlib.sha256(out).hexdigest()}
            for k, v in want.items():
                if row.get(k) != v:
                    die(f"{rel}: index {k}={row.get(k)!r} != {v!r}")
            if abs(row["std"] - st["std"]) > 1e-3 or abs(row["mean"] - st["mean"]) > 1e-3:
                die(f"{rel}: index mean/std mismatch")
            if st["max"] == st["min"] or st["std"] < MIN_STD:
                die(f"{rel}: degenerate channel")
        del lanes
    if sorted(expected_paths) != sorted(by_path):
        die(f"index paths differ from re-derived set ({len(expected_paths)} vs {len(by_path)})")
    got_excl = sorted((e["object"], e["channel"], e["reason"]) for e in stats["excluded"])
    if got_excl != sorted(expected_excl):
        die(f"exclusions differ: build {got_excl} vs verify {sorted(expected_excl)}")
    on_disk = sorted(os.path.relpath(p, args.data_root) for p in
                     glob.glob(os.path.join(args.data_root, "samples", DATASET_ID, SERIES_ID, "*.bin")))
    if on_disk != sorted(by_path):
        die("sample directory holds files not in the index")
    n = len(index)
    total = sum(row["sample_size_bytes"] for row in index)
    values = sum(row["value_count"] for row in index)
    med = sorted(row["value_count"] for row in index)[n // 2]
    if not (values >= 10_000 or total >= 100_000) or med < 1000:
        die("acceptance floor not met")
    if total > 1_000_000_000:
        die("primary output above 1 GB")
    series = [s for s in manifest["series"] if s["id"] == SERIES_ID]
    if len(series) != 1:
        die("manifest series missing")
    if series[0]["sample_count"] != n or series[0]["total_size_bytes"] != total:
        die(f"manifest sample_count/total_size_bytes {series[0]['sample_count']}/{series[0]['total_size_bytes']} "
            f"!= realized {n}/{total}")
    agg = hashlib.sha256()
    for row in index:
        agg.update(row["sha256"].encode())
    if agg.hexdigest() != stats["aggregate_sha256"]:
        die("aggregate sha256 mismatch")
    deps = sorted({row["deployment"] for row in index})
    stds = sorted(row["std"] for row in index)
    print(f"verify_ok samples={n} bytes={total} values={values} deployments={len(deps)} "
          f"excluded={len(expected_excl)} std[min/median/max]={stds[0]:.1f}/{stds[n // 2]:.1f}/{stds[-1]:.1f}")


# ---------------------------------------------------------------- selftest

def float_to_ext80(x: float) -> bytes:
    if x == 0:
        return b"\0" * 10
    m, e = math.frexp(x)  # x = m * 2**e, 0.5 <= m < 1
    mant = int(m * (1 << 64))
    return struct.pack(">HQ", (e - 1 + 16383) & 0x7FFF, mant)


def synth_aiff(chans: list[list[int]], rate: float = RATE, frames: int | None = None, bits: int = 16) -> bytes:
    n = len(chans[0])
    frames = n if frames is None else frames
    inter = array.array("h", [chans[c][t] for t in range(n) for c in range(len(chans))])
    if sys.byteorder == "little":
        inter.byteswap()
    data = inter.tobytes()
    comm = struct.pack(">hIh", len(chans), frames, bits) + float_to_ext80(rate)
    ssnd = struct.pack(">II", 0, 0) + data
    body = b"AIFF" + b"COMM" + struct.pack(">I", len(comm)) + comm + b"SSND" + struct.pack(">I", len(ssnd)) + ssnd
    return b"FORM" + struct.pack(">I", len(body)) + body


def selftest(quiet: bool = False) -> None:
    global FRAMES, SSND_BYTES, FILE_BYTES, EXPECTED_HEADER
    saved = (FRAMES, SSND_BYTES, FILE_BYTES, EXPECTED_HEADER)
    try:
        assert float_to_ext80(2000.0) == bytes.fromhex("4009FA00000000000000"), float_to_ext80(2000.0).hex()
        assert ext80_to_float(bytes.fromhex("4009FA00000000000000")) == 2000.0
        assert ext80_to_float(bytes.fromhex("400C9C40000000000000")) == 10000.0
        n = 1000
        FRAMES, SSND_BYTES = n, n * FRAME_BYTES
        FILE_BYTES = 12 + 26 + 16 + SSND_BYTES
        EXPECTED_HEADER = (b"FORM" + struct.pack(">I", FILE_BYTES - 8) + b"AIFF"
                           + b"COMM" + struct.pack(">I", 18) + struct.pack(">hIh", CHANNELS, n, BITS)
                           + bytes.fromhex("4009FA00000000000000")
                           + b"SSND" + struct.pack(">I", SSND_BYTES + 8) + struct.pack(">II", 0, 0))
        import random
        rng = random.Random(7)
        chans = []
        for c in range(CHANNELS):
            chans.append([16 * int(rng.gauss(-40, 12)) for _ in range(n)])
        chans[1] = [0] * n                                         # blank
        chans[3] = [-32768 if (t // 50) % 2 else 25520 for t in range(n)]  # railed
        chans[5] = [-640 if t % 10 < 7 else chans[0][t] for t in range(n)]  # dominated
        chans[7] = list(chans[6])                                  # duplicate
        chans[8][0], chans[8][1] = -32768, 32752                  # full scale extremes, single hits
        raw = synth_aiff(chans)
        assert len(raw) == FILE_BYTES
        assert raw[:DATA_OFFSET] == EXPECTED_HEADER
        b = build_decode(raw)
        v = verify_decode(raw)
        for c in range(CHANNELS):
            assert list(b[c]) == chans[c], f"build decode ch{c}"
            assert to_le_bytes(b[c]) == v[c], f"verify decode ch{c}"
            assert struct.unpack(f"<{n}h", v[c]) == tuple(chans[c])
        reasons = []
        seen = {}
        for c in range(CHANNELS):
            st = hist_stats(collections.Counter(b[c]), n)
            r = exclusion_reason(st, c != 9)
            if r is None:
                assert st["off_lattice_count"] == 0
                key = v[c]
                if key in seen:
                    r = "duplicate"
                else:
                    seen[key] = c
            reasons.append(r)
        assert reasons == [None, "blank_all_zero", None, "railed_min_max_share_gt_1pct", None,
                           "dominated_single_value_gt_50pct", None, "duplicate", None,
                           "publisher_quality_not_good"], reasons
        # near-constant
        vals = [-640] * 600 + [-624] * 199 + [-656] * 199 + [-608, -672]
        st = hist_stats(collections.Counter(vals), len(vals))
        assert exclusion_reason(st, True) == "dominated_single_value_gt_50pct", st
        vals = [-640] * 450 + [-624] * 274 + [-656] * 274 + [-608, -672]
        st = hist_stats(collections.Counter(vals), len(vals))
        assert exclusion_reason(st, True) == "near_constant_std_lt_16", st
        vals = [-640] * 300 + [-624] * 250 + [-656] * 250 + [-608] * 100 + [-672] * 98 + [-592, -688]
        st = hist_stats(collections.Counter(vals), len(vals))
        assert exclusion_reason(st, True) is None and st["std"] > 16, st
        st = hist_stats(collections.Counter([-640] * 499 + [-624] * 2 + [-656] * 499), 1000)
        assert exclusion_reason(st, True) == "railed_min_max_share_gt_1pct"
        # header rejections
        for bad, why in ((synth_aiff(chans[:9]), "9 channels"),
                         (synth_aiff(chans, rate=10000.0), "10 kHz"),
                         (synth_aiff(chans, bits=12), "12 bits declared")):
            for fn in (lambda x: check_layout(parse_aiff_header(x[:4096], len(x)), len(x)), verify_decode):
                try:
                    fn(bad)
                except ValueError:
                    pass
                else:
                    raise AssertionError(f"accepted {why}")
        trunc = raw[:-20]
        for fn in (build_decode, verify_decode):
            try:
                fn(trunc)
            except ValueError:
                pass
            else:
                raise AssertionError("accepted truncated file")
        odd = list(chans[0]); odd[5] += 1
        st = hist_stats(collections.Counter(odd), n)
        assert st["off_lattice_count"] == 1
    finally:
        FRAMES, SSND_BYTES, FILE_BYTES, EXPECTED_HEADER = saved
    if not quiet:
        print("selftest_ok")


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("discover"); p.add_argument("--listings", required=True); p.add_argument("--meta", required=True)
    p.add_argument("--out-files", required=True); p.add_argument("--out-meta", required=True)
    p = sub.add_parser("check-iso"); p.add_argument("--file", required=True)
    p = sub.add_parser("check-meta"); p.add_argument("--dir", required=True)
    p = sub.add_parser("check-aiff"); p.add_argument("--file", required=True); p.add_argument("--name")
    sub.add_parser("selftest")
    sub.add_parser("list-files")
    sub.add_parser("list-meta")
    for name in ("build", "verify"):
        p = sub.add_parser(name)
        p.add_argument("--download-dir", required=True); p.add_argument("--data-root", required=True)
        p.add_argument("--index", required=True); p.add_argument("--stats", required=True)
        if name == "verify":
            p.add_argument("--manifest", required=True)
    args = ap.parse_args()
    if args.cmd == "discover":
        cmd_discover(args)
    elif args.cmd == "check-iso":
        cmd_check_iso(args)
    elif args.cmd == "check-meta":
        cmd_check_meta(args)
    elif args.cmd == "check-aiff":
        cmd_check_aiff(args)
    elif args.cmd == "selftest":
        selftest()
    elif args.cmd == "list-files":
        for r in files_rows():
            print(r["object"], r["size"])
    elif args.cmd == "list-meta":
        for r in meta_rows():
            print(r["object"], r["size"])
    elif args.cmd == "build":
        cmd_build(args)
    elif args.cmd == "verify":
        cmd_verify(args)


if __name__ == "__main__":
    main()
