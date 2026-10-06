#!/usr/bin/env python3
"""Listing checks, download planning, build and verify for the NOAA
STOFS-2D-Global v2.1 (ADCIRC) fort.61 station water-surface-elevation recipe.

Network I/O is done by download.sh with curl; this script only parses what
curl fetched.  Each primary sample is the complete decoded ``zeta`` variable
(time=1260 x station=1688, IEEE float64) of one 00z cycle's
``stofs_2d_glo_fcst.61.nc`` (NetCDF4/HDF5), written in its native time-major
order as raw little-endian doubles.  No value is changed: the bytes of each
sample are the byte-unshuffled, inflated HDF5 chunks concatenated in time
order.
"""
from __future__ import annotations

import argparse
import array
import collections
import datetime as dt
import hashlib
import html
import json
import math
import re
import shutil
import struct
import sys
import tomllib
import zlib
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import h5lite  # noqa: E402

DATASET_ID = "noaa_stofs2d_glo_adcirc_station_water_level_f64"
SERIES_ID = "stofs2d_glo_fcst61_zeta_f64"
NATURAL_RECORD_KIND = "stofs2d_glo_00z_cycle_fort61_station_zeta_matrix"
SOURCES_HEADER = "date\tkey\tsize_bytes\tetag"
SOURCES_SHA256 = "26338f9530df0c1d6bec2df2a6d2e53df69fdc91c46ed20972aa1e23c7a89d6d"
EXPECTED_FILES = 40
EXPECTED_SOURCE_BYTES = 632_438_615
FIRST_DATE = dt.date(2024, 6, 1)
STEP_DAYS = 20
KEY_RE = re.compile(r"^stofs_2d_glo\.(\d{8})/00/rerun/stofs_2d_glo_fcst\.61\.nc$")
S3_PART_SIZE = 8 * 1024 * 1024  # multipart upload part size behind the "-N" ETags

FILL = -99999.0
FILL_BYTES = struct.pack("<d", FILL)
# Sanity bounds for non-fill values (fatal outside; nothing is clipped).  1687
# stations stay within about -11..+9 m, but station index 1649 ("UJ816 SOUS00
# SA816", 35.44E 46.22N, Sea of Azov coast) carries an unphysical native model
# level of about 46..220 m in every pinned cycle; it is kept as published.
VALID_MIN = -100.0
VALID_MAX = 500.0
F64_LE = bytes.fromhex("11203f000800000000004000340b0034ff030000")
FILTER_SHUFFLE = 2
FILTER_DEFLATE = 1
ZETA_FILTERS = [(FILTER_SHUFFLE, 1, (8,)), (FILTER_DEFLATE, 1, (2,))]
TIME_BASE = dt.datetime(2024, 4, 4, 12, 0, 0)
TIME_STEP_S = 360
NOWCAST_S = 21600
ROOT_LINKS = {"time", "station", "namelen", "station_name", "x", "y", "zeta"}

REAL_SPEC = {
    "n_time": 1260,
    "n_station": 1688,
    "time_chunk": 512,
    "name_len": 50,
    "xy_sha256": "5849e368fab4cd7b016f85daae5e16dbc34cf040c13a1d0c278d95ba50519751",
    # One station label (index 68, NOAA 8725110 Naples FL) was renamed from
    # "Gulf of Mexico" to "Gulf Coast" between the 2025-02-16 and 2025-03-08
    # pinned cycles; coordinates are byte-identical throughout.
    "names_sha256_before": "95ccd6fd25bbfbc538b3d266711b996c913d979dbd87ff6cb7159efb48f69868",
    "names_sha256_after": "228aa2ddb13ecee91b1ac02118ab0425022404c958b0a20a45f79ff0a458f3a0",
    "names_switch_date": "2025-03-08",
    "min_distinct": 100_000,
    "globals": {
        "version": "noaa.stofs.2d.glo.v2.1.0r1.v55.12",
        "model": "ADCIRC",
        "agrid": "OceanMesh2D",
        "title": "STOFS_2D_GLOBAL.V2.1.0     ! NCPROJ - PROJECT TITLE",
        "runid": "STOFS 2D GLOBAL v5.6.5     ! 24 CHARACTER ALPHANUMERIC RUN IDENTIFICATION",
        "grid_type": "Triangular",
        "_NCProperties": "version=2,netcdf=4.7.4,hdf5=1.10.6,",
        "_FillValue": [FILL],
        "dry_Value": [FILL],
        "dt": [6.0],
        "ihot": [568],
    },
}
ZETA_ATTRS = {
    "long_name": "water surface elevation above geoid",
    "standard_name": "sea_surface_height_above_geoid",
    "units": "m",
    "_FillValue": [FILL],
}
TIME_UNITS_PREFIX = "seconds since 2024-04-04 12:00:00"


class DecodeError(ValueError):
    """Semantic validation failure (wrong product, version, lattice, values)."""


DECODE_ERRORS = (h5lite.H5Error, DecodeError, struct.error, KeyError, IndexError, zlib.error, OverflowError)


def fail(message: str) -> None:
    raise SystemExit(f"FATAL: {message}")


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# --------------------------------------------------------------------------
# pinned sources
def load_sources(path: Path) -> list[dict]:
    raw = path.read_bytes()
    digest = sha256_hex(raw)
    if digest != SOURCES_SHA256:
        fail(f"{path.name} SHA-256 {digest} != pinned {SOURCES_SHA256}")
    lines = raw.decode("utf-8").splitlines()
    if lines[0] != SOURCES_HEADER:
        fail("sources.tsv header changed")
    rows = []
    for number, line in enumerate(lines[1:]):
        date, key, size, etag = line.split("\t")
        match = KEY_RE.match(key)
        expected_date = FIRST_DATE + dt.timedelta(days=STEP_DAYS * number)
        if not match or match.group(1) != date.replace("-", "") or date != expected_date.isoformat():
            fail(f"sources.tsv row {number + 1}: {date} {key} breaks the 00z / {STEP_DAYS}-day lattice")
        if not re.fullmatch(r"[0-9a-f]{32}-\d+", etag):
            fail(f"sources.tsv row {number + 1}: unexpected ETag {etag}")
        rows.append({"date": date, "key": key, "size": int(size), "etag": etag})
    if len(rows) != EXPECTED_FILES or sum(r["size"] for r in rows) != EXPECTED_SOURCE_BYTES:
        fail("sources.tsv row count or byte total changed")
    return rows


def source_path(downloads: Path, row: dict) -> Path:
    return downloads / "nc" / f"stofs_2d_glo_fcst.61.{row['date'].replace('-', '')}_00z.nc"


def listing_path(downloads: Path, row: dict) -> Path:
    return downloads / "listings" / f"{row['date'].replace('-', '')}.xml"


def s3_multipart_etag(data: bytes, parts: int, part_size: int = S3_PART_SIZE) -> str:
    """S3 multipart ETag: md5 over the concatenated binary md5 of each part."""
    if parts < 1 or not (parts - 1) * part_size < len(data) <= parts * part_size:
        return "part-count-mismatch"
    digests = b"".join(
        hashlib.md5(data[offset:offset + part_size]).digest() for offset in range(0, len(data), part_size)
    )
    return f"{hashlib.md5(digests).hexdigest()}-{parts}"


def check_source_bytes(data: bytes, row: dict) -> str | None:
    if len(data) != row["size"]:
        return f"size {len(data)} != {row['size']}"
    if data[:8] != h5lite.HDF5_SIGNATURE:
        return "missing HDF5 signature"
    parts = int(row["etag"].rsplit("-", 1)[1])
    etag = s3_multipart_etag(data, parts)
    if etag != row["etag"]:
        return f"multipart ETag {etag} != listed {row['etag']}"
    return None


def cmd_check_listings(args: argparse.Namespace) -> None:
    rows = load_sources(args.sources)
    for row in rows:
        path = listing_path(args.downloads, row)
        if not path.is_file():
            fail(f"missing listing {path}")
        text = path.read_text(encoding="utf-8")
        if "<ListBucketResult" not in text:
            fail(f"{path.name}: not an S3 ListBucketResult document")
        truncated = re.search(r"<IsTruncated>(\w+)</IsTruncated>", text)
        if not truncated or truncated.group(1) != "false":
            fail(f"{path.name}: listing truncated")
        blocks = re.findall(r"<Contents>(.*?)</Contents>", text, flags=re.S)
        if len(blocks) != 1:
            fail(f"{path.name}: expected exactly one object for {row['key']}, got {len(blocks)}")
        key = html.unescape(re.search(r"<Key>([^<]+)</Key>", blocks[0]).group(1))
        size = int(re.search(r"<Size>(\d+)</Size>", blocks[0]).group(1))
        etag = html.unescape(re.search(r"<ETag>([^<]+)</ETag>", blocks[0]).group(1)).strip('"')
        if (key, size, etag) != (row["key"], row["size"], row["etag"]):
            fail(f"{row['key']}: upstream object changed: listed ({key}, {size}, {etag}) != pinned ({row['size']}, {row['etag']})")
    print(f"listings=ok objects={len(rows)} bytes={EXPECTED_SOURCE_BYTES}")


def cmd_plan(args: argparse.Namespace) -> None:
    """Promote validated files and list missing ones for the next curl pass.

    A complete-size file that fails the size/ETag/signature check is kept as
    ``<name>.unverified`` and the plan stops with an error instead of
    re-downloading it: refetching identical bytes cannot fix a mismatch, and a
    corrected check can re-validate the kept file without a new download.
    Delete the ``.unverified`` file to force a fresh fetch.
    """
    rows = load_sources(args.sources)
    pending = []
    problems = []
    promoted = 0
    for row in rows:
        final = source_path(args.downloads, row)
        part = final.with_name(final.name + ".part")
        unverified = final.with_name(final.name + ".unverified")
        if final.is_file():
            problem = check_source_bytes(final.read_bytes(), row)
            if problem is None:
                continue
            final.replace(unverified)
        for candidate in (unverified, part):
            if not candidate.is_file():
                continue
            size = candidate.stat().st_size
            if candidate is part and size < row["size"]:
                break  # incomplete; curl resumes it
            if size > row["size"]:
                print(f"discarding oversized {candidate.name}: {size} > {row['size']}")
                candidate.unlink()
                continue
            problem = check_source_bytes(candidate.read_bytes(), row)
            if problem is None:
                candidate.replace(final)
                promoted += 1
                break
            if candidate is part:
                part.replace(unverified)
            problems.append(f"{unverified.name}: {problem}")
            break
        if final.is_file() or unverified.is_file():
            continue
        final.parent.mkdir(parents=True, exist_ok=True)
        pending.append((args.base_url.rstrip("/") + "/" + row["key"], part))
    if problems:
        for problem in problems:
            print(f"integrity failure: {problem}")
        fail(f"{len(problems)} complete download(s) fail size/ETag/signature checks (kept as .unverified)")
    with args.config.open("w", encoding="utf-8") as handle:
        for url, part in pending:
            handle.write(f'url = "{url}"\noutput = "{part}"\n')
    print(f"plan pending={len(pending)} promoted={promoted}")


# --------------------------------------------------------------------------
# HDF5 decoding
def unshuffle(payload: bytes, count: int, size: int = 8) -> bytes:
    """Inverse of the HDF5 shuffle filter: byte j of element k is stored at j*count + k."""
    out = bytearray(count * size)
    for j in range(size):
        out[j::size] = payload[j * count:(j + 1) * count]
    return bytes(out)


def shuffle(values: bytes, size: int = 8) -> bytes:
    """Forward HDF5 shuffle (used by verify to re-encode samples)."""
    return b"".join(values[j::size] for j in range(size))


def chunks_by_descent(h5: h5lite.H5File, btree: int) -> list[tuple[int, int, tuple[int, ...], int]]:
    """Build route: recursive descent from the root (h5lite.chunk_index)."""
    chunks, _final = h5.chunk_index(btree, 3)
    return chunks


def chunks_by_siblings(raw: bytes, btree: int) -> list[tuple[int, int, tuple[int, ...], int]]:
    """Verify route: descend the leftmost path, then walk the leaf level through
    the right-sibling pointers, checking each left-sibling back pointer."""
    key_size = 8 + 8 * 3

    def node(addr: int) -> tuple[int, int, int, int]:
        if addr == h5lite.UNDEF or addr + 24 > len(raw) or raw[addr:addr + 4] != b"TREE" or raw[addr + 4] != 1:
            raise h5lite.H5Error(f"no raw-data chunk B-tree node at {addr}")
        level = raw[addr + 5]
        used = struct.unpack_from("<H", raw, addr + 6)[0]
        left, right = struct.unpack_from("<QQ", raw, addr + 8)
        return level, used, left, right

    level, used, left, right = node(btree)
    if left != h5lite.UNDEF or right != h5lite.UNDEF:
        raise h5lite.H5Error("chunk B-tree root has siblings")
    addr = btree
    while level > 0:
        if used == 0:
            raise h5lite.H5Error("empty internal chunk B-tree node")
        addr = struct.unpack_from("<Q", raw, addr + 24 + key_size)[0]
        child_level, used, child_left, _right = node(addr)
        if child_level != level - 1 or child_left != h5lite.UNDEF:
            raise h5lite.H5Error("leftmost chunk B-tree path is inconsistent")
        level = child_level
    out = []
    previous = h5lite.UNDEF
    visited = set()
    while addr != h5lite.UNDEF:
        if addr in visited:
            raise h5lite.H5Error("chunk B-tree sibling loop")
        visited.add(addr)
        level, used, left, right = node(addr)
        if level != 0 or left != previous:
            raise h5lite.H5Error("broken chunk B-tree leaf sibling chain")
        pos = addr + 24
        for _ in range(used):
            size, mask = struct.unpack_from("<II", raw, pos)
            offsets = struct.unpack_from("<3Q", raw, pos + 8)
            child = struct.unpack_from("<Q", raw, pos + key_size)[0]
            out.append((size, mask, offsets, child))
            pos += key_size + 8
        previous = addr
        addr = right
    return out


def contiguous_bytes(h5: h5lite.H5File, addr: int, expected_size: int) -> bytes:
    info = h5.dataset(addr)
    layout = info["layout_raw"]
    if info["filters"] or layout[1] != 1 or len(layout) != 18:
        raise DecodeError("expected an unfiltered contiguous dataset")
    data_addr, size = struct.unpack_from("<QQ", layout, 2)
    if size != expected_size or data_addr + size > len(h5.raw):
        raise DecodeError(f"contiguous extent {size} != {expected_size} or outside file")
    return h5.raw[data_addr:data_addr + size]


def cycle_seconds(date: str) -> int:
    cycle = dt.datetime.fromisoformat(date + "T00:00:00")
    return int((cycle - TIME_BASE).total_seconds())


def decode_cycle(raw: bytes, date: str, spec: dict, route: str) -> tuple[list[bytes], dict]:
    """Validate one fort.61 file and return the inflated (still shuffled) zeta
    chunk payloads in time order plus provenance metadata."""
    n_time, n_station = spec["n_time"], spec["n_station"]
    h5 = h5lite.H5File(raw)
    if h5.superblock_version != 0:
        raise DecodeError(f"superblock version {h5.superblock_version} != 0")
    links = h5.links(h5.root_addr)
    if set(links) != ROOT_LINKS:
        raise DecodeError(f"root links {sorted(links)} != {sorted(ROOT_LINKS)}")
    attrs = h5.attributes(h5.root_addr)
    for key, expected in spec["globals"].items():
        if attrs.get(key) != expected:
            raise DecodeError(f"global {key}={attrs.get(key)!r} != {expected!r}")
    stamp = date.replace("-", "") + "00"
    if not str(attrs.get("rundes", "")).startswith(f"{stamp} :-6 hr nowcast and +180 hr forecast"):
        raise DecodeError(f"rundes {attrs.get('rundes')!r} does not name cycle {stamp}")
    base = cycle_seconds(date)
    if attrs.get("rnday") != [base / 86400.0]:
        raise DecodeError(f"rnday {attrs.get('rnday')} != cycle day {base / 86400.0}")

    # zeta (time, station) float64, chunked (1, station), shuffle(8) + deflate
    zeta = links["zeta"]
    zattrs = h5.attributes(zeta)
    for key, expected in ZETA_ATTRS.items():
        if zattrs.get(key) != expected:
            raise DecodeError(f"zeta.{key}={zattrs.get(key)!r} != {expected!r}")
    info = h5.dataset(zeta)
    if info["shape"] != (n_time, n_station):
        raise DecodeError(f"zeta shape {info['shape']} != {(n_time, n_station)}")
    if info["datatype"] != F64_LE:
        raise DecodeError(f"zeta datatype {info['datatype'].hex()} is not little-endian IEEE float64")
    if info["layout_class"] != 2 or tuple(info["chunk_dims"]) != (1, n_station, 8):
        raise DecodeError(f"zeta layout is not (1, {n_station}) chunks: {info['layout_raw'].hex()}")
    if info["filters"] != ZETA_FILTERS:
        raise DecodeError(f"zeta filter pipeline {info['filters']} != {ZETA_FILTERS}")
    if route == "descent":
        chunks = chunks_by_descent(h5, info["chunk_btree"])
    elif route == "siblings":
        chunks = chunks_by_siblings(raw, info["chunk_btree"])
    else:
        raise ValueError(route)
    if len(chunks) != n_time:
        raise DecodeError(f"chunk B-tree holds {len(chunks)} chunks, expected {n_time}")
    row_bytes = n_station * 8
    extents = []
    payloads = []
    stored_total = 0
    for t, (stored, mask, offsets, addr) in enumerate(chunks):
        if offsets != (t, 0, 0):
            raise DecodeError(f"chunk {t} has offsets {offsets}")
        if mask != 0:
            raise DecodeError(f"chunk {t} skipped filters (mask {mask})")
        if stored <= 0 or addr + stored > len(raw):
            raise DecodeError(f"chunk {t} extent outside file")
        extents.append((addr, addr + stored))
        inflater = zlib.decompressobj()
        payload = inflater.decompress(raw[addr:addr + stored], row_bytes + 1)
        if not inflater.eof or inflater.unused_data or inflater.unconsumed_tail or len(payload) != row_bytes:
            raise DecodeError(f"chunk {t} does not inflate to exactly {row_bytes} bytes")
        payloads.append(payload)
        stored_total += stored
    extents.sort()
    for (_s0, e0), (s1, _e1) in zip(extents, extents[1:]):
        if s1 < e0:
            raise DecodeError("zeta chunks overlap")

    # time: chunked, unfiltered, must equal the fixed 6-minute lattice of this cycle
    tinfo = h5.dataset(links["time"])
    tattrs = h5.attributes(links["time"])
    if not str(tattrs.get("units", "")).startswith(TIME_UNITS_PREFIX):
        raise DecodeError(f"time units {tattrs.get('units')!r}")
    tc = spec["time_chunk"]
    if (tinfo["shape"] != (n_time,) or tinfo["datatype"] != F64_LE or tinfo["filters"]
            or tinfo["layout_class"] != 2 or tuple(tinfo["chunk_dims"]) != (tc, 8)):
        raise DecodeError("time variable layout changed")
    tchunks, _final = h5.chunk_index(tinfo["chunk_btree"], 2)
    n_tchunks = -(-n_time // tc)
    if [c[2] for c in tchunks] != [(k * tc, 0) for k in range(n_tchunks)]:
        raise DecodeError("time chunk offsets changed")
    times: list[float] = []
    for stored, mask, _offsets, addr in tchunks:
        if mask != 0 or stored != tc * 8 or addr + stored > len(raw):
            raise DecodeError("unexpected time chunk")
        times.extend(struct.unpack_from(f"<{tc}d", raw, addr))
    times = times[:n_time]
    expected_times = [float(base - NOWCAST_S + TIME_STEP_S * (i + 1)) for i in range(n_time)]
    if times != expected_times:
        raise DecodeError("time axis is not the cycle's 6-minute lattice (-5.9 h .. +120 h)")

    # fixed station set
    for dim in ("station", "namelen"):
        if h5.dataset(links[dim])["shape"] != ((n_station,) if dim == "station" else (spec["name_len"],)):
            raise DecodeError(f"dimension {dim} changed")
    xy = contiguous_bytes(h5, links["x"], n_station * 8) + contiguous_bytes(h5, links["y"], n_station * 8)
    if sha256_hex(xy) != spec["xy_sha256"]:
        raise DecodeError("station coordinates differ from the pinned station set")
    names = contiguous_bytes(h5, links["station_name"], n_station * spec["name_len"])
    expected_names = spec["names_sha256_before"] if date < spec["names_switch_date"] else spec["names_sha256_after"]
    names_sha = sha256_hex(names)
    if names_sha != expected_names:
        raise DecodeError(f"station_name SHA-256 {names_sha} != pinned {expected_names}")
    meta = {
        "rundes": attrs["rundes"],
        "creation_date": attrs.get("creation_date"),
        "stored_chunk_bytes": stored_total,
        "time_first_s": times[0],
        "time_last_s": times[-1],
        "station_names_sha256": names_sha,
        "checked_metadata_blocks": h5.checked_blocks,
    }
    return payloads, meta


def sample_profile(sample: bytes, spec: dict) -> dict:
    """Value statistics under the native-fill policy (identical in build and verify)."""
    n_time, n_station = spec["n_time"], spec["n_station"]
    if len(sample) != n_time * n_station * 8:
        raise DecodeError("sample size mismatch")
    values = array.array("d")
    values.frombytes(sample)
    if sys.byteorder != "little":
        values.byteswap()
    fill_positions = [i for i, v in enumerate(values) if v == FILL]
    nonfill = [v for v in values if v != FILL]
    if not nonfill:
        raise DecodeError("sample is entirely fill")
    try:
        total = math.fsum(nonfill)
    except (ValueError, OverflowError):
        raise DecodeError("sample holds infinities") from None
    if not math.isfinite(total):
        raise DecodeError("sample holds NaN or infinite values")
    low, high = min(nonfill), max(nonfill)
    if not (VALID_MIN < low and high < VALID_MAX):
        raise DecodeError(f"non-fill values {low}..{high} outside sanity bounds ({VALID_MIN}, {VALID_MAX})")
    distinct = len(set(nonfill))
    if distinct < spec["min_distinct"]:
        raise DecodeError(f"degenerate sample: only {distinct} distinct values")
    first_row, last_row = sample[:n_station * 8], sample[-n_station * 8:]
    if first_row == last_row:
        raise DecodeError("first and last time steps are identical")
    per_station = collections.Counter(i % n_station for i in fill_positions)
    return {
        "fill_count": len(fill_positions),
        "stations_with_fill": len(per_station),
        "always_fill_stations": sum(1 for n in per_station.values() if n == n_time),
        "min": low,
        "max": high,
        "mean": total / len(nonfill),
        "distinct_values": distinct,
        "sha256": sha256_hex(sample),
    }


# --------------------------------------------------------------------------
# build / verify
def sample_rel(row: dict) -> str:
    stamp = row["date"].replace("-", "")
    return f"samples/{DATASET_ID}/{SERIES_ID}/stofs2d_glo_fcst61_zeta_{stamp}_00z.bin"


def index_row(row: dict, meta: dict, profile: dict, spec: dict) -> dict:
    n_time, n_station = spec["n_time"], spec["n_station"]
    return {
        "dataset_id": DATASET_ID,
        "series_id": SERIES_ID,
        "role": "primary",
        "sample_path": sample_rel(row),
        "numeric_kind": "float",
        "bit_width": 64,
        "endianness": "little",
        "element_size_bytes": 8,
        "sample_size_bytes": n_time * n_station * 8,
        "value_count": n_time * n_station,
        "sample_shape": [n_time, n_station],
        "sample_axes": ["time", "station"],
        "natural_record_kind": NATURAL_RECORD_KIND,
        "source_field": "zeta",
        "source_key": row["key"],
        "source_size_bytes": row["size"],
        "source_etag": row["etag"],
        "cycle": f"{row['date']}T00:00Z",
        "rundes": meta["rundes"],
        "creation_date": meta["creation_date"],
        "time_first_s_since_2024-04-04T12": meta["time_first_s"],
        "time_last_s_since_2024-04-04T12": meta["time_last_s"],
        "station_names_sha256": meta["station_names_sha256"],
        "fill_value": FILL,
        **profile,
    }


def run_selftest() -> None:
    import selftest_stofs

    selftest_stofs.main(quiet=True)


def scan(downloads: Path, sources: Path, route: str, consumer) -> dict:
    rows = load_sources(sources)
    spec = REAL_SPEC
    aggregate = hashlib.sha256()
    hashes = set()
    totals = collections.Counter()
    names = collections.Counter()
    low, high = math.inf, -math.inf
    for number, row in enumerate(rows, 1):
        path = source_path(downloads, row)
        if not path.is_file():
            fail(f"missing source file {path}; run download.sh")
        raw = path.read_bytes()
        problem = check_source_bytes(raw, row)
        if problem:
            fail(f"{path.name}: {problem}")
        try:
            payloads, meta = decode_cycle(raw, row["date"], spec, route)
            sample = consumer.sample(row, payloads)
            profile = sample_profile(sample, spec)
        except DECODE_ERRORS as error:
            fail(f"{path.name}: {error}")
        if profile["sha256"] in hashes:
            fail(f"{row['date']}: sample duplicates an earlier cycle")
        hashes.add(profile["sha256"])
        aggregate.update(sample)
        totals["fill_count"] += profile["fill_count"]
        totals["values"] += len(sample) // 8
        names[meta["station_names_sha256"]] += 1
        low, high = min(low, profile["min"]), max(high, profile["max"])
        consumer.emit(row, sample, index_row(row, meta, profile, spec))
        print(
            f"[{number}/{len(rows)}] {row['date']} fill={profile['fill_count']} "
            f"stations_with_fill={profile['stations_with_fill']} min={profile['min']:.4f} max={profile['max']:.4f}",
            flush=True,
        )
    return {
        "dataset_id": DATASET_ID,
        "series_id": SERIES_ID,
        "sources_sha256": SOURCES_SHA256,
        "sample_count": len(rows),
        "value_count": totals["values"],
        "total_size_bytes": totals["values"] * 8,
        "fill_value": FILL,
        "fill_count_total": totals["fill_count"],
        "fill_fraction": totals["fill_count"] / totals["values"],
        "nonfill_min": low,
        "nonfill_max": high,
        "station_names_sha256_counts": dict(sorted(names.items())),
        "aggregate_sha256": aggregate.hexdigest(),
    }


class BuildConsumer:
    def __init__(self, tmp_dir: Path, n_station: int):
        self.tmp_dir = tmp_dir
        self.n_station = n_station
        self.rows: list[dict] = []

    def sample(self, row: dict, payloads: list[bytes]) -> bytes:
        return b"".join(unshuffle(p, self.n_station) for p in payloads)

    def emit(self, row: dict, sample: bytes, entry: dict) -> None:
        target = self.tmp_dir / Path(sample_rel(row)).relative_to(f"samples/{DATASET_ID}")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(sample)
        self.rows.append(entry)


class VerifyConsumer:
    def __init__(self, data_root: Path, indexed: list[dict], n_station: int):
        self.data_root = data_root
        self.indexed = indexed
        self.n_station = n_station
        self.position = 0
        self.seen: set[Path] = set()

    def sample(self, row: dict, payloads: list[bytes]) -> bytes:
        path = self.data_root / sample_rel(row)
        if not path.is_file():
            fail(f"missing sample {path}")
        sample = path.read_bytes()
        row_bytes = self.n_station * 8
        if len(sample) != row_bytes * len(payloads):
            fail(f"{path.name}: size {len(sample)} != {row_bytes * len(payloads)}")
        for t, payload in enumerate(payloads):
            if shuffle(sample[t * row_bytes:(t + 1) * row_bytes]) != payload:
                fail(f"{path.name}: time step {t} does not re-shuffle to the inflated source chunk")
        self.seen.add(path.resolve())
        return sample

    def emit(self, row: dict, sample: bytes, entry: dict) -> None:
        if self.position >= len(self.indexed):
            fail("index has fewer rows than sources")
        stored = self.indexed[self.position]
        self.position += 1
        if stored != entry:
            diff = sorted(k for k in set(stored) | set(entry) if stored.get(k) != entry.get(k))
            fail(f"index row for {row['date']} differs from fresh decode: {diff}")


def cmd_build(args: argparse.Namespace) -> None:
    run_selftest()
    out_dir = args.data_root / "samples" / DATASET_ID
    tmp_dir = args.data_root / "samples" / f".{DATASET_ID}.tmp"
    if tmp_dir.exists():
        shutil.rmtree(tmp_dir)
    consumer = BuildConsumer(tmp_dir, REAL_SPEC["n_station"])
    try:
        summary = scan(args.downloads, args.sources, "descent", consumer)
    except BaseException:
        if tmp_dir.exists():
            shutil.rmtree(tmp_dir)
        raise
    if out_dir.exists():
        shutil.rmtree(out_dir)
    tmp_dir.replace(out_dir)
    index = args.data_root / "index" / DATASET_ID / "samples.jsonl"
    index.parent.mkdir(parents=True, exist_ok=True)
    index.write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in consumer.rows), encoding="utf-8")
    stats = args.data_root / "filtered" / DATASET_ID / "ingest_stats.json"
    stats.parent.mkdir(parents=True, exist_ok=True)
    stats.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2, sort_keys=True))


def cmd_verify(args: argparse.Namespace) -> None:
    run_selftest()
    index = args.data_root / "index" / DATASET_ID / "samples.jsonl"
    stats = args.data_root / "filtered" / DATASET_ID / "ingest_stats.json"
    if not index.is_file() or not stats.is_file():
        fail("missing index or ingest stats; run build.sh first")
    indexed = [json.loads(line) for line in index.read_text(encoding="utf-8").splitlines() if line.strip()]
    consumer = VerifyConsumer(args.data_root, indexed, REAL_SPEC["n_station"])
    # Independent route: chunk list from the leaf sibling chain instead of the
    # recursive descent used by build; samples are re-shuffled and compared
    # with the inflated chunks instead of being unshuffled again.
    summary = scan(args.downloads, args.sources, "siblings", consumer)
    if consumer.position != len(indexed):
        fail("index has extra rows")
    on_disk = {p.resolve() for p in (args.data_root / "samples" / DATASET_ID).rglob("*") if p.is_file()}
    if on_disk != consumer.seen:
        fail(f"sample directory has {len(on_disk - consumer.seen)} stale and {len(consumer.seen - on_disk)} missing files")
    if json.loads(stats.read_text(encoding="utf-8")) != summary:
        fail("ingest stats differ from fresh scan")
    manifest = tomllib.loads(args.manifest.read_text(encoding="utf-8"))
    series = [s for s in manifest.get("series", []) if s.get("id") == SERIES_ID]
    if len(series) != 1:
        fail("manifest series missing")
    if series[0].get("sample_count") != summary["sample_count"] or series[0].get("total_size_bytes") != summary["total_size_bytes"]:
        fail("manifest sample_count/total_size_bytes disagree with realized output")
    print(
        f"verified samples={summary['sample_count']} values={summary['value_count']} "
        f"bytes={summary['total_size_bytes']} fill={summary['fill_count_total']} "
        f"aggregate_sha256={summary['aggregate_sha256']}"
    )


def cmd_check_downloads(args: argparse.Namespace) -> None:
    """Semantic download check: every file is the pinned object and decodes to a valid zeta matrix."""
    run_selftest()
    rows = load_sources(args.sources)
    total = 0
    for row in rows:
        path = source_path(args.downloads, row)
        raw = path.read_bytes() if path.is_file() else b""
        problem = check_source_bytes(raw, row)
        if problem:
            fail(f"{path.name}: {problem}")
        try:
            payloads, _meta = decode_cycle(raw, row["date"], REAL_SPEC, "descent")
            sample_profile(b"".join(unshuffle(p, REAL_SPEC["n_station"]) for p in payloads), REAL_SPEC)
        except DECODE_ERRORS as error:
            fail(f"{path.name}: semantically invalid: {error}")
        total += len(raw)
    print(f"download_check=ok files={len(rows)} bytes={total}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("check-listings")
    p.add_argument("--sources", type=Path, required=True)
    p.add_argument("--downloads", type=Path, required=True)
    p.set_defaults(func=cmd_check_listings)
    p = sub.add_parser("plan")
    p.add_argument("--sources", type=Path, required=True)
    p.add_argument("--downloads", type=Path, required=True)
    p.add_argument("--base-url", required=True)
    p.add_argument("--config", type=Path, required=True)
    p.set_defaults(func=cmd_plan)
    p = sub.add_parser("check-downloads")
    p.add_argument("--sources", type=Path, required=True)
    p.add_argument("--downloads", type=Path, required=True)
    p.set_defaults(func=cmd_check_downloads)
    for name, func in (("build", cmd_build), ("verify", cmd_verify)):
        p = sub.add_parser(name)
        p.add_argument("--sources", type=Path, required=True)
        p.add_argument("--downloads", type=Path, required=True)
        p.add_argument("--data-root", type=Path, required=True)
        p.add_argument("--manifest", type=Path, required=True)
        p.set_defaults(func=func)
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
