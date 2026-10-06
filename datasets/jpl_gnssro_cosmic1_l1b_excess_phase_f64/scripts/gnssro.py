#!/usr/bin/env python3
"""Discovery, download planning, download validation and build for the
JPL COSMIC-1 GNSS radio-occultation L1b calibrated excess-phase recipe.

Network I/O is done by discover.sh / download.sh with curl; this script only
parses what curl fetched.  The primary sample of one occultation sounding is
the GPS L1 row of the NetCDF4 variable ``excess_phase`` (float64, metres),
trimmed of leading/trailing ``_FillValue`` and emitted as the exact native
little-endian IEEE-754 bytes stored in the file.
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import math
import re
import shutil
import statistics
import struct
import sys
import tomllib
from collections import Counter
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import h5lite  # noqa: E402

DATASET_ID = "jpl_gnssro_cosmic1_l1b_excess_phase_f64"
SERIES_ID = "cosmic1_jpl_l1b_l1_excess_phase_f64"
BASE_URL = "https://gnss-ro-data.s3.amazonaws.com"
ROOT_PREFIX = "contributed/v2.0/gnssro_cosmic1_jpl_l1b/"
FIRST_YEAR, LAST_YEAR = 2007, 2016
TARGET_DAY = 15
PER_DAY = 20

SOURCES_HEADER = "month\tday\tkey\tsize_bytes\tmd5\tday_key_count\tday_index\n"
# Pinned by discover.sh on 2026-10-06 (see README); download/build/verify refuse any other list.
SOURCES_SHA256 = "5debe8b2bad08a9f38427568b37c7b62a3ec79852c56de572f4cc26648a56c75"
EXPECTED_SOURCES = 2393
EXPECTED_SOURCE_BYTES = 1_702_213_576

KEY_RE = re.compile(
    r"^contributed/v2\.0/gnssro_cosmic1_jpl_l1b/(\d{4})/(\d{2})/(\d{2})/"
    r"(gnssro_cosmic1_jpl_l1b_v2\.6_(cosmic1c[1-6])-(G\d{2})-(\d{12}))\.nc4$"
)

FILL = -9.99e20
# HDF5 datatype message: class 1 (float) version 1, little-endian, IEEE
# implied-mantissa, sign bit 63, size 8, offset 0, precision 64, exponent at
# bit 52 (11 bits), mantissa at bit 0 (52 bits), bias 1023.
F64_LE = bytes.fromhex("11203f000800000000004000340b0034ff030000")
CHAR_TYPE = bytes.fromhex("1300000001000000")  # class 3 fixed string, size 1, null-terminated ASCII
L1_FREQUENCY_HZ = 1575420000.0
TIME_STEP_RANGE = (0.0199, 0.0201)  # 50 Hz open-loop sampling
MIN_SPAN = 1000

EXPECTED_GLOBALS = {
    "mission": "cosmic1",
    "institution": "jpl",
    "institution_version": "v2.6",
    "VersionID": "2.0",
    "ShortName": "gnssro_cosmic1_jpl_l1b",
    "ProcessingLevel": "1B",
    "data_use_license": "http://creativecommons.org/licenses/by/4.0/",
    "Format": "NetCDF4",
    "source": "GNSS radio occultation",
}
EXPECTED_EXCESS_PHASE_ATTRS = {
    "long_name": "excess phase",
    "units": "meter",
    "_FillValue": [FILL],
}


class SoundingFatal(Exception):
    """The file is not the pinned JPL COSMIC-1 v2.6 L1b product: abort."""


class SoundingDropped(Exception):
    """The file is the right product but fails the documented sample policy."""

    def __init__(self, reason: str, detail: str = ""):
        super().__init__(f"{reason}: {detail}" if detail else reason)
        self.reason = reason


def fail(message: str) -> None:
    raise SystemExit(f"FATAL: {message}")


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def months() -> list[str]:
    return [f"{y:04d}-{m:02d}" for y in range(FIRST_YEAR, LAST_YEAR + 1) for m in range(1, 13)]


# --------------------------------------------------------------------------
# S3 listing parsing (discovery)
def parse_listing(path: Path, prefix: str) -> dict:
    text = path.read_text(encoding="utf-8")
    if "<ListBucketResult" not in text:
        fail(f"{path.name}: not an S3 ListBucketResult document")
    prefix_match = re.search(r"<ListBucketResult[^>]*>.*?<Prefix>([^<]*)</Prefix>", text, flags=re.S)
    if not prefix_match or html.unescape(prefix_match.group(1)) != prefix:
        fail(f"{path.name}: listing prefix mismatch")
    truncated = re.search(r"<IsTruncated>(\w+)</IsTruncated>", text)
    if not truncated:
        fail(f"{path.name}: listing lacks IsTruncated")
    token = re.search(r"<NextContinuationToken>([^<]+)</NextContinuationToken>", text)
    items = []
    for block in re.findall(r"<Contents>(.*?)</Contents>", text, flags=re.S):
        key = re.search(r"<Key>([^<]+)</Key>", block)
        etag = re.search(r"<ETag>([^<]+)</ETag>", block)
        size = re.search(r"<Size>(\d+)</Size>", block)
        if not (key and etag and size):
            fail(f"{path.name}: malformed Contents element")
        items.append(
            {
                "key": html.unescape(key.group(1)),
                "etag": html.unescape(etag.group(1)).strip('"'),
                "size": int(size.group(1)),
            }
        )
    prefixes = [html.unescape(p) for p in re.findall(r"<CommonPrefixes><Prefix>([^<]+)</Prefix></CommonPrefixes>", text)]
    count = re.search(r"<KeyCount>(\d+)</KeyCount>", text)
    if count and int(count.group(1)) != len(items) + len(prefixes):
        fail(f"{path.name}: KeyCount {count.group(1)} != parsed {len(items) + len(prefixes)}")
    return {
        "truncated": truncated.group(1) == "true",
        "token": html.unescape(token.group(1)) if token else None,
        "items": items,
        "prefixes": prefixes,
    }


def cmd_pick_day(args: argparse.Namespace) -> None:
    """Print the available day of the month nearest TARGET_DAY (ties: earlier)."""
    year, month = args.month.split("-")
    prefix = f"{ROOT_PREFIX}{year}/{month}/"
    listing = parse_listing(args.listing, prefix)
    if listing["truncated"] or listing["items"]:
        fail(f"{args.listing.name}: unexpected month listing shape")
    days = []
    for p in listing["prefixes"]:
        m = re.fullmatch(re.escape(prefix) + r"(\d{2})/", p)
        if not m:
            fail(f"unexpected prefix {p}")
        days.append(int(m.group(1)))
    if not days:
        print("")
        return
    best = min(days, key=lambda d: (abs(d - TARGET_DAY), d))
    print(f"{best:02d}")


def cmd_next_token(args: argparse.Namespace) -> None:
    listing = parse_listing(args.listing, args.prefix)
    if listing["truncated"]:
        if not listing["token"]:
            fail(f"{args.listing.name}: truncated listing without continuation token")
        print(listing["token"])
    else:
        print("")


def cmd_select(args: argparse.Namespace) -> None:
    """Deterministic spread: PER_DAY evenly spaced keys of each chosen day."""
    choices = {}
    for line in (args.listings / "chosen_days.tsv").read_text(encoding="utf-8").splitlines():
        month, day = line.split("\t")
        choices[month] = day
    rows = []
    skipped = []
    for month in months():
        day = choices.get(month, "")
        if not day:
            skipped.append(month)
            continue
        year, mon = month.split("-")
        prefix = f"{ROOT_PREFIX}{year}/{mon}/{day}/"
        pages = sorted(args.listings.glob(f"day_{month}-{day}.p*.xml"))
        if not pages:
            fail(f"no listing pages for {month}-{day}")
        items = []
        for number, page in enumerate(pages, 1):
            listing = parse_listing(page, prefix)
            if page.name != f"day_{month}-{day}.p{number:02d}.xml":
                fail(f"listing page sequence broken at {page.name}")
            if listing["truncated"] != (number < len(pages)):
                fail(f"{page.name}: truncation flag inconsistent with page sequence")
            items.extend(listing["items"])
        keys = sorted(items, key=lambda it: it["key"])
        if len({it["key"] for it in keys}) != len(keys):
            fail(f"duplicate keys in {month}-{day}")
        for it in keys:
            m = KEY_RE.match(it["key"])
            if not m or f"{m.group(1)}-{m.group(2)}" != month or m.group(3) != day:
                fail(f"unexpected key in {prefix}: {it['key']}")
            if m.group(7)[:8] != f"{year}{mon}{day}":
                fail(f"key timestamp outside its day directory: {it['key']}")
            if not re.fullmatch(r"[0-9a-f]{32}", it["etag"]):
                fail(f"{it['key']}: ETag is not a single-part MD5: {it['etag']}")
            if not 50_000 <= it["size"] <= 5_000_000:
                fail(f"{it['key']}: implausible size {it['size']}")
        n = len(keys)
        if n <= PER_DAY:
            picks = list(range(n))
        else:
            picks = [((2 * i + 1) * n) // (2 * PER_DAY) for i in range(PER_DAY)]
        for index in picks:
            it = keys[index]
            rows.append((month, day, it["key"], it["size"], it["etag"], n, index))
    text = SOURCES_HEADER + "".join(
        f"{mo}\t{d}\t{k}\t{s}\t{e}\t{n}\t{i}\n" for mo, d, k, s, e, n, i in rows
    )
    args.out.write_text(text, encoding="utf-8")
    total = sum(r[3] for r in rows)
    print(
        f"sources={len(rows)} source_bytes={total} months={len(set(r[0] for r in rows))} "
        f"skipped_months={skipped} sha256={sha256_hex(text.encode('utf-8'))}"
    )


# --------------------------------------------------------------------------
# pinned source list
def load_sources(path: Path, check_pin: bool = True) -> list[dict]:
    if not path.is_file():
        fail(f"missing source list {path}")
    text = path.read_text(encoding="utf-8")
    digest = sha256_hex(text.encode("utf-8"))
    if check_pin and digest != SOURCES_SHA256:
        fail(f"source list SHA-256 {digest} != pinned {SOURCES_SHA256}")
    lines = text.splitlines()
    if not lines or lines[0] + "\n" != SOURCES_HEADER:
        fail("source list header changed")
    rows = []
    for line in lines[1:]:
        month, day, key, size, md5, day_count, day_index = line.split("\t")
        m = KEY_RE.match(key)
        if not m:
            fail(f"bad key in source list: {key}")
        rows.append(
            {
                "month": month,
                "day": day,
                "key": key,
                "size": int(size),
                "md5": md5,
                "day_key_count": int(day_count),
                "day_index": int(day_index),
                "granule": m.group(4),
                "receiver": m.group(5),
                "transmitter": m.group(6),
                "stamp": m.group(7),
            }
        )
    if check_pin:
        if len(rows) != EXPECTED_SOURCES:
            fail(f"source list has {len(rows)} rows, expected {EXPECTED_SOURCES}")
        if sum(r["size"] for r in rows) != EXPECTED_SOURCE_BYTES:
            fail("source list byte total changed")
    if len({r["key"] for r in rows}) != len(rows):
        fail("duplicate keys in source list")
    return rows


def source_path(downloads: Path, row: dict) -> Path:
    return downloads / "files" / row["key"][len(ROOT_PREFIX):]


def check_source_bytes(data: bytes, row: dict) -> str | None:
    if len(data) != row["size"]:
        return f"size {len(data)} != {row['size']}"
    if data[:8] != h5lite.HDF5_SIGNATURE:
        return "missing HDF5 signature"
    digest = hashlib.md5(data).hexdigest()
    if digest != row["md5"]:
        return f"md5 {digest} != {row['md5']}"
    return None


def cmd_plan(args: argparse.Namespace) -> None:
    rows = load_sources(args.sources)
    pending = []
    promoted = rejected = 0
    for row in rows:
        final = source_path(args.downloads, row)
        part = final.with_name(final.name + ".part")
        if final.is_file():
            problem = check_source_bytes(final.read_bytes(), row)
            if problem is None:
                continue
            print(f"rejecting cached {final.name}: {problem}")
            final.unlink()
            rejected += 1
        if part.is_file():
            data = part.read_bytes()
            problem = check_source_bytes(data, row)
            if problem is None:
                part.replace(final)
                promoted += 1
                continue
            if len(data) >= row["size"]:
                print(f"rejecting partial {part.name}: {problem}")
                part.unlink()
                rejected += 1
        final.parent.mkdir(parents=True, exist_ok=True)
        pending.append((f"{BASE_URL}/{row['key']}", part))
    with args.config.open("w", encoding="utf-8") as handle:
        for url, part in pending:
            handle.write(f'url = "{url}"\noutput = "{part}"\n')
    print(f"plan pending={len(pending)} promoted={promoted} rejected={rejected} total={len(rows)}")


# --------------------------------------------------------------------------
# decoding
def contiguous_bytes(h5: h5lite.H5File, info: dict, what: str) -> bytes:
    if info["layout_class"] != 1:
        raise SoundingDropped("layout_not_contiguous", f"{what} layout class {info['layout_class']}")
    if info["filters"]:
        raise SoundingDropped("filter_pipeline_present", f"{what} filters {info['filters']}")
    addr, size = info["data_addr"], info["data_size"]
    if addr == h5lite.UNDEF or addr + size > len(h5.raw):
        raise SoundingFatal(f"{what} raw data extent outside file")
    return h5.raw[addr:addr + size]


def check_identity(h5: h5lite.H5File, row: dict) -> dict:
    attrs = h5.attributes(h5.root_addr)
    for name, expected in EXPECTED_GLOBALS.items():
        if attrs.get(name) != expected:
            raise SoundingFatal(f"global attribute {name}={attrs.get(name)!r}, expected {expected!r}")
    if attrs.get("GranuleID") != row["granule"]:
        raise SoundingFatal(f"GranuleID {attrs.get('GranuleID')!r} != {row['granule']!r}")
    if attrs.get("receiver") != row["receiver"] or attrs.get("transmitter") != row["transmitter"]:
        raise SoundingFatal("receiver/transmitter attributes disagree with the file name")
    # The integer calendar attributes are not usable for cross-checks (the
    # upstream writer leaves `minute` at 0, and the file-name stamp is the
    # start time rounded to the minute), so record the ISO range strings.
    date, clock = attrs.get("RangeBeginningDate"), attrs.get("RangeBeginningTime")
    if not (isinstance(date, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", date)
            and isinstance(clock, str) and re.fullmatch(r"\d{2}:\d{2}:\d{2}", clock)):
        raise SoundingFatal(f"RangeBeginningDate/Time malformed: {date!r} {clock!r}")
    return attrs


def decode_sounding(raw: bytes, row: dict, link_index: str = "name") -> tuple[bytes, dict]:
    """Return (sample bytes, metadata) or raise SoundingDropped / SoundingFatal."""
    h5 = h5lite.H5File(raw)
    links = h5.links(h5.root_addr, link_index)
    attrs = check_identity(h5, row)
    for name in ("excess_phase", "phase_observation_code", "carrier_frequency", "time"):
        if name not in links:
            raise SoundingFatal(f"missing variable {name}")
    ep = h5.dataset(links["excess_phase"])
    ep_attrs = h5.attributes(links["excess_phase"])
    for name, expected in EXPECTED_EXCESS_PHASE_ATTRS.items():
        if ep_attrs.get(name) != expected:
            raise SoundingFatal(f"excess_phase attribute {name}={ep_attrs.get(name)!r}")
    if ep["datatype"] != F64_LE:
        raise SoundingDropped("excess_phase_not_f64_le", ep["datatype"].hex())
    if len(ep["shape"]) != 2:
        raise SoundingFatal(f"excess_phase rank {len(ep['shape'])}")
    nsig, ntimes = ep["shape"]
    if not 1 <= nsig <= 4 or ntimes < 1:
        raise SoundingFatal(f"excess_phase shape {ep['shape']}")
    ep_bytes = contiguous_bytes(h5, ep, "excess_phase")
    if len(ep_bytes) != 8 * nsig * ntimes:
        raise SoundingFatal("excess_phase storage size disagrees with its shape")

    poc = h5.dataset(links["phase_observation_code"])
    if poc["datatype"] != CHAR_TYPE or poc["shape"] != (nsig, 3):
        raise SoundingFatal(f"phase_observation_code type/shape {poc['datatype'].hex()} {poc['shape']}")
    codes_raw = contiguous_bytes(h5, poc, "phase_observation_code")
    codes = [codes_raw[3 * i:3 * i + 3].decode("ascii", "replace") for i in range(nsig)]
    l1_rows = [i for i, code in enumerate(codes) if code.startswith("L1")]
    if len(l1_rows) != 1:
        raise SoundingDropped("no_unique_l1_row", f"codes {codes}")
    l1 = l1_rows[0]

    cf = h5.dataset(links["carrier_frequency"])
    if cf["datatype"] != F64_LE or cf["shape"] != (nsig,):
        raise SoundingFatal("carrier_frequency type/shape")
    freqs = struct.unpack(f"<{nsig}d", contiguous_bytes(h5, cf, "carrier_frequency"))
    if freqs[l1] != L1_FREQUENCY_HZ:
        raise SoundingDropped("l1_row_not_1575_42_mhz", f"{freqs[l1]}")

    tv = h5.dataset(links["time"])
    if tv["datatype"] != F64_LE or tv["shape"] != (ntimes,):
        raise SoundingFatal("time type/shape")
    times = struct.unpack(f"<{ntimes}d", contiguous_bytes(h5, tv, "time"))

    values = struct.unpack_from(f"<{ntimes}d", ep_bytes, 8 * l1 * ntimes)
    valid = [x != FILL and math.isfinite(x) for x in values]
    if not any(valid):
        raise SoundingDropped("l1_all_fill")
    start = valid.index(True)
    end = ntimes - valid[::-1].index(True)  # exclusive
    if not all(valid[start:end]):
        raise SoundingDropped("l1_interior_fill", f"{end - start - sum(valid[start:end])} gaps")
    length = end - start
    if length < MIN_SPAN:
        raise SoundingDropped("l1_span_below_1000", f"{length}")
    span = values[start:end]
    if min(span) == max(span):
        raise SoundingDropped("l1_constant")
    steps = [times[i + 1] - times[i] for i in range(start, end - 1)]
    step = statistics.median(steps)
    if not TIME_STEP_RANGE[0] <= step <= TIME_STEP_RANGE[1] or min(steps) <= 0:
        raise SoundingDropped("not_50hz_monotonic", f"median step {step}")
    offset = 8 * (l1 * ntimes + start)
    payload = ep_bytes[offset:offset + 8 * length]
    meta = {
        "phase_observation_code": codes[l1],
        "phase_observation_codes": codes,
        "l1_row": l1,
        "signals": nsig,
        "ntimes": ntimes,
        "span_start": start,
        "span_end": end,
        "time_step_s": round(step, 9),
        "duration_s": round(times[end - 1] - times[start], 6),
        "occultation_start": f"{attrs['RangeBeginningDate']}T{attrs['RangeBeginningTime']}Z",
        "start_time_gps_s": None,
        "min": min(span),
        "max": max(span),
        "first": span[0],
        "last": span[-1],
        "sha256": sha256_hex(payload),
        "reference_transmitter": attrs.get("reference_transmitter"),
    }
    if "start_time" in links:
        st = h5.dataset(links["start_time"])
        if st["datatype"] == F64_LE and st["shape"] == ():
            meta["start_time_gps_s"] = struct.unpack("<d", contiguous_bytes(h5, st, "start_time"))[0]
    return payload, meta


def sample_rel(row: dict) -> str:
    return f"samples/{DATASET_ID}/{SERIES_ID}/{row['month'][:4]}/{row['granule']}_L1.f64le.bin"


def index_row(row: dict, meta: dict, payload: bytes) -> dict:
    count = len(payload) // 8
    return {
        "dataset_id": DATASET_ID,
        "series_id": SERIES_ID,
        "role": "primary",
        "sample_path": sample_rel(row),
        "numeric_kind": "float",
        "bit_width": 64,
        "endianness": "little",
        "element_size_bytes": 8,
        "sample_size_bytes": len(payload),
        "value_count": count,
        "sample_shape": [count],
        "sample_axes": ["time_50hz"],
        "natural_record_kind": "gnss_radio_occultation_sounding_l1_excess_phase_profile",
        "source_field": "excess_phase[L1 row selected by phase_observation_code]",
        "source_key": row["key"],
        "source_md5": row["md5"],
        "source_size_bytes": row["size"],
        "granule_id": row["granule"],
        "receiver": row["receiver"],
        "transmitter": row["transmitter"],
        "month": row["month"],
        "day": row["day"],
        "units": "meter",
        **{k: v for k, v in meta.items() if k not in ("phase_observation_codes",)},
    }


def scan_sources(rows: list[dict], downloads: Path, consumer, link_index: str = "name") -> dict:
    drops: Counter = Counter()
    dropped_keys: list[list[str]] = []
    per_year: Counter = Counter()
    per_receiver: Counter = Counter()
    codes: Counter = Counter()
    lengths: list[int] = []
    aggregate = hashlib.sha256()
    total_bytes = 0
    for number, row in enumerate(rows, 1):
        path = source_path(downloads, row)
        raw = path.read_bytes() if path.is_file() else b""
        problem = check_source_bytes(raw, row)
        if problem:
            fail(f"{path}: {problem} (run download.sh)")
        try:
            payload, meta = decode_sounding(raw, row, link_index)
        except SoundingDropped as drop:
            drops[drop.reason] += 1
            dropped_keys.append([row["granule"], str(drop)])
            continue
        except (SoundingFatal, h5lite.H5Error, struct.error, KeyError, IndexError, UnicodeDecodeError) as error:
            fail(f"{row['key']}: {error}")
        consumer(row, payload, meta)
        aggregate.update(payload)
        total_bytes += len(payload)
        lengths.append(len(payload) // 8)
        per_year[row["month"][:4]] += 1
        per_receiver[row["receiver"]] += 1
        codes[meta["phase_observation_code"]] += 1
        if number % 250 == 0:
            print(f"scanned={number}/{len(rows)} kept={len(lengths)}", flush=True)
    if not lengths:
        fail("no samples survived the policy")
    lengths_sorted = sorted(lengths)
    return {
        "dataset_id": DATASET_ID,
        "series_id": SERIES_ID,
        "source_files": len(rows),
        "source_bytes": sum(r["size"] for r in rows),
        "sample_count": len(lengths),
        "value_count": sum(lengths),
        "total_size_bytes": total_bytes,
        "min_values_per_sample": lengths_sorted[0],
        "median_values_per_sample": statistics.median(lengths_sorted),
        "max_values_per_sample": lengths_sorted[-1],
        "dropped": dict(sorted(drops.items())),
        "dropped_granules": dropped_keys,
        "samples_per_year": dict(sorted(per_year.items())),
        "samples_per_receiver": dict(sorted(per_receiver.items())),
        "l1_phase_observation_codes": dict(sorted(codes.items())),
        "aggregate_sha256": aggregate.hexdigest(),
    }


def cmd_check_downloads(args: argparse.Namespace) -> None:
    """Semantic download check: every pinned file is the JPL COSMIC-1 v2.6 L1b product."""
    rows = load_sources(args.sources)
    total = 0
    drops: Counter = Counter()
    for number, row in enumerate(rows, 1):
        path = source_path(args.downloads, row)
        raw = path.read_bytes() if path.is_file() else b""
        problem = check_source_bytes(raw, row)
        if problem:
            fail(f"{path.name}: {problem}")
        try:
            decode_sounding(raw, row)
        except SoundingDropped as drop:
            drops[drop.reason] += 1
        except (SoundingFatal, h5lite.H5Error, struct.error, KeyError, IndexError, UnicodeDecodeError) as error:
            fail(f"{path.name}: semantically invalid: {error}")
        total += len(raw)
        if number % 500 == 0:
            print(f"checked={number}/{len(rows)}", flush=True)
    print(f"download_check=ok files={len(rows)} bytes={total} policy_drops={dict(sorted(drops.items()))}")


def run_selftest() -> None:
    import selftest_gnssro

    selftest_gnssro.main(quiet=True)


def cmd_build(args: argparse.Namespace) -> None:
    run_selftest()
    rows = load_sources(args.sources)
    out_dir = args.data_root / "samples" / DATASET_ID
    tmp_dir = args.data_root / "samples" / f".{DATASET_ID}.tmp"
    if tmp_dir.exists():
        shutil.rmtree(tmp_dir)
    rows_out: list[dict] = []

    def emit(row: dict, payload: bytes, meta: dict) -> None:
        rel = sample_rel(row)
        target = tmp_dir / Path(rel).relative_to(f"samples/{DATASET_ID}")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)
        rows_out.append(index_row(row, meta, payload))

    try:
        summary = scan_sources(rows, args.downloads, emit)
    except BaseException:
        if tmp_dir.exists():
            shutil.rmtree(tmp_dir)
        raise
    if out_dir.exists():
        shutil.rmtree(out_dir)
    tmp_dir.replace(out_dir)
    index = args.data_root / "index" / DATASET_ID / "samples.jsonl"
    index.parent.mkdir(parents=True, exist_ok=True)
    index.write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in rows_out), encoding="utf-8")
    stats = args.data_root / "filtered" / DATASET_ID / "ingest_stats.json"
    stats.parent.mkdir(parents=True, exist_ok=True)
    stats.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    brief = {k: v for k, v in summary.items() if k != "dropped_granules"}
    print(json.dumps(brief, indent=2, sort_keys=True))
    manifest = tomllib.loads(args.manifest.read_text(encoding="utf-8"))
    series = [s for s in manifest.get("series", []) if s.get("id") == SERIES_ID]
    if len(series) != 1 or series[0].get("sample_count") != summary["sample_count"] or series[0].get(
        "total_size_bytes"
    ) != summary["total_size_bytes"]:
        print("WARNING: manifest sample_count/total_size_bytes do not match this build yet")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("pick-day")
    p.add_argument("--month", required=True)
    p.add_argument("--listing", type=Path, required=True)
    p.set_defaults(func=cmd_pick_day)
    p = sub.add_parser("next-token")
    p.add_argument("--prefix", required=True)
    p.add_argument("--listing", type=Path, required=True)
    p.set_defaults(func=cmd_next_token)
    p = sub.add_parser("select")
    p.add_argument("--listings", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    p.set_defaults(func=cmd_select)
    p = sub.add_parser("plan")
    p.add_argument("--sources", type=Path, required=True)
    p.add_argument("--downloads", type=Path, required=True)
    p.add_argument("--config", type=Path, required=True)
    p.set_defaults(func=cmd_plan)
    p = sub.add_parser("check-downloads")
    p.add_argument("--sources", type=Path, required=True)
    p.add_argument("--downloads", type=Path, required=True)
    p.set_defaults(func=cmd_check_downloads)
    p = sub.add_parser("build")
    p.add_argument("--sources", type=Path, required=True)
    p.add_argument("--downloads", type=Path, required=True)
    p.add_argument("--data-root", type=Path, required=True)
    p.add_argument("--manifest", type=Path, required=True)
    p.set_defaults(func=cmd_build)
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
