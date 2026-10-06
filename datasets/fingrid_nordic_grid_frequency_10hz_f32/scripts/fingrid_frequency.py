#!/usr/bin/env python3
"""Fingrid Nordic grid frequency (10 Hz) -> one little-endian float32 sample per day.

Subcommands
  validate-download  check one downloaded monthly .7z (size, Content-MD5, pinned
                     member list, full decode with per-member CRC32)
  discover-members   decode a 7z header from range-fetched pieces (discover.sh)
  build              decode the pinned archives and emit samples + index
  verify             independently re-derive every sample and check the index

Pure standard library. Network I/O lives in download.sh / discover.sh (curl).
"""
from __future__ import annotations

import argparse
import base64
import csv
import datetime as dt
import hashlib
import io
import json
import math
import os
import re
import shutil
import struct
import sys
import tomllib
from array import array
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import sevenzip  # noqa: E402

DATASET_ID = "fingrid_nordic_grid_frequency_10hz_f32"
SERIES_ID = "nordic_grid_frequency_10hz_f32"
NATURAL_RECORD_KIND = "fingrid_daily_frequency_csv_file"
TICKS_PER_DAY = 864_000  # 24 h at 10 Hz
# Keep a day only when at least 90 % of its 0.1 s ticks carry a value.
MIN_COVERED_TICKS = 777_600
# Resolution rule: the primary chain publishes 10 uHz (5-decimal) values, of
# which ~1 % print with <= 3 decimals because trailing zeros are stripped
# (measured 0.0099-0.0103 on clean days).  Hours from the smoothed 1 mHz
# backup chain (3 decimals) push a day to >= 0.051.  Days above this share
# are excluded by build and rejected by verify.
MAX_COARSE_TOKEN_SHARE = 0.02
VALUE_MIN_HZ = 45.0
VALUE_MAX_HZ = 55.0
MAX_DECIMALS = 5
MAX_LISTED_GAPS = 1000
HEADER_LINE = b"Time,Value"
MEMBER_RE = re.compile(r"^(?:(\d{4}-\d{2})/)?Taajuusdata(\d{4}-\d{2}-\d{2})\.csv$")
TOKEN_RE = re.compile(rb"^(?:0|[1-9][0-9]*)(?:\.([0-9]{1,5}))?$")
DATASET_PAGE_ID = 339
LICENSE_NAME = "Creative Commons Attribution"
LICENSE_TERMS = "https://creativecommons.org/licenses/by/4.0/"
FILES_BASE = "https://data.fingrid.fi"
HMS_RE = re.compile(rb"^([01][0-9]|2[0-3]):([0-5][0-9]):([0-5][0-9])$")

RECIPE_DIR = Path(__file__).resolve().parents[1]


class RecipeError(RuntimeError):
    pass


# --------------------------------------------------------------------------- pins


def load_sources(recipe_dir: Path = RECIPE_DIR) -> list[dict]:
    rows = []
    with (recipe_dir / "sources.tsv").open(encoding="utf-8") as handle:
        header = handle.readline().rstrip("\n").split("\t")
        for line in handle:
            if not line.strip() or line.startswith("#"):
                continue
            rows.append(dict(zip(header, line.rstrip("\n").split("\t"))))
    for row in rows:
        row["size_bytes"] = int(row["size_bytes"])
        if row.get("sha256") in ("", "-"):
            row["sha256"] = ""
    return rows


def load_members(recipe_dir: Path = RECIPE_DIR) -> dict[str, list[tuple[str, int, int]]]:
    members: dict[str, list[tuple[str, int, int]]] = {}
    with (recipe_dir / "members.tsv").open(encoding="utf-8") as handle:
        header = handle.readline().rstrip("\n").split("\t")
        if header != ["month", "member", "size_bytes", "crc32"]:
            raise RecipeError(f"unexpected members.tsv header {header}")
        for line in handle:
            if not line.strip():
                continue
            month, member, size, crc = line.rstrip("\n").split("\t")
            members.setdefault(month, []).append((member, int(size), int(crc, 16)))
    return members


def archive_path(data_root: Path, source: dict) -> Path:
    return data_root / "downloads" / DATASET_ID / source["filename"]


def file_digests(path: Path) -> tuple[str, str]:
    md5 = hashlib.md5()
    sha = hashlib.sha256()
    with path.open("rb") as handle:
        while block := handle.read(8 * 1024 * 1024):
            md5.update(block)
            sha.update(block)
    return base64.b64encode(md5.digest()).decode("ascii"), sha.hexdigest()


def check_archive_identity(path: Path, source: dict) -> str:
    if not path.is_file():
        raise RecipeError(f"missing archive {path}; run download.sh first")
    size = path.stat().st_size
    if size != source["size_bytes"]:
        raise RecipeError(f"{path.name}: size {size} != pinned {source['size_bytes']}")
    md5_b64, sha256 = file_digests(path)
    if md5_b64 != source["content_md5_b64"]:
        raise RecipeError(f"{path.name}: MD5 {md5_b64} != pinned Content-MD5 {source['content_md5_b64']}")
    if source.get("sha256") and sha256 != source["sha256"]:
        raise RecipeError(f"{path.name}: SHA-256 {sha256} != pinned {source['sha256']}")
    return sha256


def open_checked_archive(path: Path, month: str, members: dict) -> sevenzip.Archive:
    archive = sevenzip.open_archive(path)
    expected = members.get(month)
    if not expected:
        raise RecipeError(f"no pinned members for {month}")
    actual = [(entry.name, entry.size, entry.crc32) for entry in archive.entries]
    if actual != expected:
        raise RecipeError(f"{path.name}: 7z member list differs from members.tsv")
    for name, _, _ in expected:
        match = MEMBER_RE.match(name)
        if not match or not match.group(2).startswith(month):
            raise RecipeError(f"{path.name}: unexpected member name {name!r}")
    for directory in archive.directories:
        if directory != month:
            raise RecipeError(f"{path.name}: unexpected directory entry {directory!r}")
    return archive


def member_date(name: str) -> str:
    match = MEMBER_RE.match(name)
    if not match:
        raise RecipeError(f"unexpected member name {name!r}")
    return match.group(2)


# ----------------------------------------------------------------- download check


def cmd_validate_download(args: argparse.Namespace) -> int:
    sources = {row["month"]: row for row in load_sources()}
    members = load_members()
    source = sources[args.month]
    path = Path(args.archive)
    sha256 = check_archive_identity(path, source)
    archive = open_checked_archive(path, args.month, members)
    if args.quick:
        print(
            f"archive_validation=ok(quick) month={args.month} bytes={source['size_bytes']} "
            f"content_md5={source['content_md5_b64']} sha256={sha256} members={len(archive.entries)}"
        )
        return 0
    count = 0
    decoded = 0
    for entry, payload in archive.iter_members():
        if not payload.startswith(HEADER_LINE):
            raise RecipeError(f"{entry.name}: does not start with {HEADER_LINE!r}")
        count += 1
        decoded += len(payload)
    if count != len(members[args.month]):
        raise RecipeError(f"{path.name}: decoded {count} members, expected {len(members[args.month])}")
    print(
        f"archive_validation=ok month={args.month} bytes={source['size_bytes']} "
        f"content_md5={source['content_md5_b64']} sha256={sha256} coder={archive.coder_name} "
        f"members={count} decoded_bytes={decoded} crc32=all_match"
    )
    return 0


# ------------------------------------------------------------- dataset page check


def load_page_data(page: Path) -> dict:
    text = page.read_text(encoding="utf-8")
    match = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', text, re.S)
    if not match:
        raise RecipeError("dataset page has no __NEXT_DATA__ block; the page layout changed")
    props = json.loads(match.group(1))["props"]["pageProps"]
    info = props["datasetInfo"]["data"]
    if int(info.get("id", -1)) != DATASET_PAGE_ID:
        raise RecipeError(f"dataset page id {info.get('id')!r} != {DATASET_PAGE_ID}")
    if "10 Hz" not in str(info.get("descriptionEn", "")) or info.get("unitEn") != "Hz":
        raise RecipeError("dataset page no longer describes the 10 Hz frequency archive")
    license_info = info.get("license") or {}
    if license_info.get("name") != LICENSE_NAME or license_info.get("termsLink") != LICENSE_TERMS:
        raise RecipeError(f"dataset license changed: {license_info!r}")
    files = props["datasetFile"]["data"]
    return {"info": info, "files": files}


def cmd_check_page(args: argparse.Namespace) -> int:
    page = load_page_data(Path(args.page))
    listing = {item["link"]: item for item in page["files"]}
    for source in load_sources():
        link = source["url"].removeprefix(FILES_BASE)
        item = listing.get(link)
        if item is None:
            raise RecipeError(f"{link} is no longer listed on the dataset page")
        if int(item["size"]) != source["size_bytes"]:
            raise RecipeError(f"{link}: listed size {item['size']} != pinned {source['size_bytes']}")
        if not str(item.get("filenameEn", "")).endswith(source["month"]):
            raise RecipeError(f"{link}: listed name {item.get('filenameEn')!r} does not match {source['month']}")
    print(
        f"page_validation=ok dataset={DATASET_PAGE_ID} license={page['info']['license']['name']!r} "
        f"terms={page['info']['license']['termsLink']} listed_files={len(listing)} pinned_months={len(load_sources())}"
    )
    return 0


def cmd_page_listing(args: argparse.Namespace) -> int:
    page = load_page_data(Path(args.page))
    wanted = set(args.months)
    for item in sorted(page["files"], key=lambda x: x["link"]):
        match = re.search(r"/(\d{4}-\d{2})\.7z$", item["link"])
        if match and match.group(1) in wanted:
            print(f"{match.group(1)}\t{FILES_BASE}{item['link']}\t{item['size']}")
    return 0


# --------------------------------------------------------------- discovery helper


def cmd_discover_members(args: argparse.Namespace) -> int:
    """Decode the 7z header from three range-fetched pieces.

    --start: bytes 0-31; --next: the next header; --packed: the packed
    (encoded) header bytes, if the next header is kEncodedHeader.  With
    --print-ranges, print the byte ranges still needed instead.
    """
    start = Path(args.start).read_bytes()
    next_offset, next_size, _ = struct.unpack("<QQI", start[12:32])
    if args.print_ranges == "next":
        print(f"{32 + next_offset}-{32 + next_offset + next_size - 1}")
        return 0
    reader = sevenzip._Reader(Path(args.next).read_bytes())
    if reader.byte() != sevenzip.K_ENCODED_HEADER:
        raise RecipeError("next header is not encoded; extend discovery if this changes")
    info = sevenzip._read_streams_info(reader)
    if args.print_ranges == "packed":
        print(f"{32 + info.pack_pos}-{32 + info.pack_pos + info.pack_sizes[0] - 1}")
        return 0
    packed = Path(args.packed).read_bytes()
    fake = io.BytesIO(b"\x00" * (32 + info.pack_pos) + packed)
    header = sevenzip._decode_encoded_header(fake, info)
    reader = sevenzip._Reader(header)
    if reader.byte() != sevenzip.K_HEADER or reader.byte() != sevenzip.K_MAIN_STREAMS_INFO:
        raise RecipeError("unexpected decoded header layout")
    main = sevenzip._read_streams_info(reader)
    if reader.byte() != sevenzip.K_FILES_INFO:
        raise RecipeError("decoded header lacks FilesInfo")
    names, empty_stream, _ = sevenzip._read_files_info(reader)
    stream_names = [name for name, empty in zip(names, empty_stream) if not empty]
    coder = main.folders[0].coders[0]
    print(
        f"# {args.month} coder={coder.codec_id.hex()} props={coder.properties.hex()} "
        f"pack_size={main.pack_sizes[0]} unpack={main.folders[0].unpack_sizes[-1]} "
        f"dirs={[n for n, e in zip(names, empty_stream) if e]}",
        file=sys.stderr,
    )
    for name, size, crc in zip(stream_names, main.substream_sizes, main.substream_crcs):
        print(f"{args.month}\t{name}\t{size}\t{crc:08x}")
    return 0


# ------------------------------------------------------------------- build parse


def _token_to_f32(token: bytes) -> tuple[bytes, float, int]:
    match = TOKEN_RE.match(token)
    if not match:
        raise RecipeError(f"malformed Value token {token!r}")
    decimals = len(match.group(1) or b"")
    value = float(token)
    if not (VALUE_MIN_HZ <= value <= VALUE_MAX_HZ):
        raise RecipeError(f"Value {token!r} outside the physical range {VALUE_MIN_HZ}-{VALUE_MAX_HZ} Hz")
    packed = struct.pack("<f", value)
    stored = struct.unpack("<f", packed)[0]
    quantum = Decimal(1).scaleb(-decimals)
    if Decimal(stored).quantize(quantum) != Decimal(token.decode("ascii")):
        raise RecipeError(f"Value {token!r} does not round-trip through float32")
    return packed, stored, decimals


def apply_day_rules(stats: dict) -> dict:
    """Pinned per-day inclusion rules shared by build and verify."""
    hist = stats["decimals_histogram"]
    count = stats["value_count"]
    share = sum(hist[:4]) / count if count else 1.0
    reasons = []
    if stats["covered_ticks"] < MIN_COVERED_TICKS:
        reasons.append(f"coverage {stats['covered_ticks']} < {MIN_COVERED_TICKS} ticks")
    if share > MAX_COARSE_TOKEN_SHARE:
        reasons.append(f"coarse_token_share {share:.4f} > {MAX_COARSE_TOKEN_SHARE} (1 mHz backup-chain hours)")
    stats["coarse_token_share"] = share
    stats["exclusion_reasons"] = reasons
    stats["kept"] = not reasons
    return stats


def gap_runs(seen: bytearray) -> list[tuple[int, int]]:
    return [(m.start(), m.end() - m.start()) for m in re.finditer(rb"\x00+", bytes(seen))]


def parse_day_build(payload: bytes, date: str) -> tuple[bytes, dict]:
    """Fast path: fixed-width slicing with per-token and per-second caches."""
    if not payload.startswith(HEADER_LINE):
        raise RecipeError(f"{date}: CSV header is not {HEADER_LINE!r}")
    lines = payload.split(b"\n")
    if lines[0].rstrip(b"\r") != HEADER_LINE:
        raise RecipeError(f"{date}: CSV header is not {HEADER_LINE!r}")
    if lines[-1] == b"":
        lines.pop()
    date_b = date.encode("ascii")
    hms_cache: dict[bytes, int] = {}
    ms_ticks = {f"{n}00".encode(): n for n in range(10)}
    token_cache: dict[bytes, tuple[bytes, float, int]] = {}
    decimals_hist = [0] * (MAX_DECIMALS + 1)
    seen = bytearray(TICKS_PER_DAY)
    out: list[bytes] = []
    blank = duplicates = backward = 0
    prev = -1
    vmin = math.inf
    vmax = -math.inf
    for number, line in enumerate(lines[1:], 2):
        if line.endswith(b"\r"):
            line = line[:-1]
        if line[:10] != date_b or line[10:11] != b" " or line[19:20] != b"." or line[23:24] != b",":
            raise RecipeError(f"{date}: malformed row {number}: {line[:60]!r}")
        hms = line[11:19]
        base = hms_cache.get(hms)
        if base is None:
            match = HMS_RE.match(hms)
            if not match:
                raise RecipeError(f"{date}: bad time in row {number}: {line[:60]!r}")
            hh, mm, ss = (int(x) for x in match.groups())
            base = hms_cache[hms] = ((hh * 60 + mm) * 60 + ss) * 10
        tenth = ms_ticks.get(line[20:23])
        if tenth is None:
            raise RecipeError(f"{date}: timestamp off the 100 ms lattice in row {number}: {line[:60]!r}")
        tick = base + tenth
        token = line[24:]
        if not token:
            blank += 1
            continue
        cached = token_cache.get(token)
        if cached is None:
            cached = token_cache[token] = _token_to_f32(token)
            if cached[1] < vmin:
                vmin = cached[1]
            if cached[1] > vmax:
                vmax = cached[1]
        out.append(cached[0])
        decimals_hist[cached[2]] += 1
        if seen[tick]:
            duplicates += 1
        else:
            seen[tick] = 1
        if tick < prev:
            backward += 1
        prev = tick
    raw = b"".join(out)
    runs = gap_runs(seen)
    covered = TICKS_PER_DAY - sum(length for _, length in runs)
    stats = {
        "date": date,
        "csv_data_rows": len(lines) - 1,
        "value_count": len(out),
        "blank_value_rows": blank,
        "covered_ticks": covered,
        "missing_ticks": TICKS_PER_DAY - covered,
        "duplicate_timestamp_rows": duplicates,
        "backward_timestamp_steps": backward,
        "gap_count": len(runs),
        "max_gap_ticks": max((length for _, length in runs), default=0),
        "decimals_histogram": decimals_hist,
        "distinct_values": len({c[0] for c in token_cache.values()}),
        "min": vmin,
        "max": vmax,
        "gaps": [list(run) for run in runs[:MAX_LISTED_GAPS]],
    }
    return raw, apply_day_rules(stats)


# ------------------------------------------------------------------ verify parse


def parse_day_verify(payload: bytes, date: str) -> tuple[bytes, dict]:
    """Independent path: csv module, datetime.fromisoformat, Decimal, array('f')."""
    text = payload.decode("ascii")
    reader = csv.reader(io.StringIO(text, newline=""))
    if next(reader) != ["Time", "Value"]:
        raise RecipeError(f"{date}: CSV header changed")
    day = dt.date.fromisoformat(date)
    ticks: list[int] = []
    values: list[float] = []
    token_info: dict[str, int] = {}
    decimals_hist = [0] * (MAX_DECIMALS + 1)
    rows = blank = 0
    for record in reader:
        rows += 1
        if len(record) != 2:
            raise RecipeError(f"{date}: row {rows + 1} has {len(record)} fields")
        stamp, token = record
        if len(stamp) != 23:
            raise RecipeError(f"{date}: unexpected timestamp {stamp!r}")
        try:
            moment = dt.datetime.fromisoformat(stamp)
        except ValueError as exc:
            raise RecipeError(f"{date}: invalid timestamp {stamp!r}") from exc
        if moment.tzinfo is not None or moment.date() != day or moment.microsecond % 100_000:
            raise RecipeError(f"{date}: timestamp {stamp!r} off-day or off-lattice")
        if token == "":
            blank += 1
            continue
        decimals = token_info.get(token)
        if decimals is None:
            try:
                number = Decimal(token)
            except ArithmeticError as exc:
                raise RecipeError(f"{date}: invalid Value {token!r}") from exc
            if not number.is_finite() or number.is_signed() or token.strip() != token or "e" in token.lower():
                raise RecipeError(f"{date}: invalid Value {token!r}")
            decimals = max(0, -number.as_tuple().exponent)
            if decimals > MAX_DECIMALS or ("." in token) != (decimals > 0):
                raise RecipeError(f"{date}: Value {token!r} has unsupported precision")
            stored = array("f", [float(token)])[0]
            if f"{stored:.{decimals}f}" != token:
                raise RecipeError(f"{date}: Value {token!r} does not round-trip through float32")
            if not (VALUE_MIN_HZ <= stored <= VALUE_MAX_HZ):
                raise RecipeError(f"{date}: Value {token!r} outside physical range")
            token_info[token] = decimals
        decimals_hist[decimals] += 1
        ticks.append(((moment.hour * 60 + moment.minute) * 60 + moment.second) * 10 + moment.microsecond // 100_000)
        values.append(float(token))
    samples = array("f", values)
    if sys.byteorder != "little":
        samples.byteswap()
    distinct_ticks = sorted(set(ticks))
    gaps: list[tuple[int, int]] = []
    previous = -1
    for tick in distinct_ticks + [TICKS_PER_DAY]:
        if tick > previous + 1:
            gaps.append((previous + 1, tick - previous - 1))
        previous = tick
    stored_values = samples.tolist() if sys.byteorder == "little" else array("f", values).tolist()
    stats = {
        "date": date,
        "csv_data_rows": rows,
        "value_count": len(values),
        "blank_value_rows": blank,
        "covered_ticks": len(distinct_ticks),
        "missing_ticks": TICKS_PER_DAY - len(distinct_ticks),
        "duplicate_timestamp_rows": len(ticks) - len(distinct_ticks),
        "backward_timestamp_steps": sum(1 for a, b in zip(ticks, ticks[1:]) if b < a),
        "gap_count": len(gaps),
        "max_gap_ticks": max((length for _, length in gaps), default=0),
        "decimals_histogram": decimals_hist,
        "distinct_values": len(set(stored_values)),
        "min": min(stored_values) if stored_values else math.inf,
        "max": max(stored_values) if stored_values else -math.inf,
        "gaps": [list(gap) for gap in gaps[:MAX_LISTED_GAPS]],
    }
    return samples.tobytes(), apply_day_rules(stats)


# ------------------------------------------------------------------------- build


def relative(path: Path, data_root: Path) -> str:
    return path.relative_to(data_root).as_posix()


def cmd_build(args: argparse.Namespace) -> int:
    data_root = (Path(args.repo_root) / args.data_dir).resolve()
    sources = load_sources()
    members = load_members()
    series_dir = data_root / "samples" / DATASET_ID / SERIES_ID
    index_path = data_root / "index" / DATASET_ID / "samples.jsonl"
    filtered_dir = data_root / "filtered" / DATASET_ID
    if series_dir.exists():
        shutil.rmtree(series_dir)
    series_dir.mkdir(parents=True)
    index_path.parent.mkdir(parents=True, exist_ok=True)
    filtered_dir.mkdir(parents=True, exist_ok=True)

    rows: list[dict] = []
    day_stats: list[dict] = []
    archive_summaries = []
    for source in sources:
        path = archive_path(data_root, source)
        sha256 = check_archive_identity(path, source)
        archive = open_checked_archive(path, source["month"], members)
        kept = dropped = 0
        for entry, payload in archive.iter_members():
            date = member_date(entry.name)
            raw, stats = parse_day_build(payload, date)
            stats.update({"source_archive": source["filename"], "source_member": entry.name, "source_member_crc32": f"{entry.crc32:08x}"})
            day_stats.append(stats)
            if not stats["kept"]:
                dropped += 1
                print(f"exclude {date}: {'; '.join(stats['exclusion_reasons'])}")
                continue
            if stats["distinct_values"] < 100 or stats["max"] - stats["min"] < 0.01:
                raise RecipeError(f"{date}: degenerate day (distinct={stats['distinct_values']})")
            kept += 1
            sample_path = series_dir / f"{date}.bin"
            tmp = sample_path.with_suffix(".bin.part")
            tmp.write_bytes(raw)
            tmp.rename(sample_path)
            row = {
                "dataset_id": DATASET_ID,
                "series_id": SERIES_ID,
                "role": "primary",
                "natural_record_kind": NATURAL_RECORD_KIND,
                "sample_path": relative(sample_path, data_root),
                "numeric_kind": "float",
                "bit_width": 32,
                "endianness": "little",
                "element_size_bytes": 4,
                "sample_size_bytes": len(raw),
                "value_count": stats["value_count"],
                "date_local": date,
                "source_archive": source["filename"],
                "source_member": entry.name,
                "source_member_crc32": f"{entry.crc32:08x}",
                "csv_data_rows": stats["csv_data_rows"],
                "blank_value_rows": stats["blank_value_rows"],
                "covered_ticks": stats["covered_ticks"],
                "missing_ticks": stats["missing_ticks"],
                "duplicate_timestamp_rows": stats["duplicate_timestamp_rows"],
                "backward_timestamp_steps": stats["backward_timestamp_steps"],
                "gap_count": stats["gap_count"],
                "max_gap_ticks": stats["max_gap_ticks"],
                "decimals_histogram": stats["decimals_histogram"],
                "coarse_token_share": stats["coarse_token_share"],
                "distinct_values": stats["distinct_values"],
                "min": stats["min"],
                "max": stats["max"],
                "sample_sha256": hashlib.sha256(raw).hexdigest(),
            }
            rows.append(row)
            print(
                f"sample {date}: values={row['value_count']} covered={row['covered_ticks']} "
                f"gaps={row['gap_count']} dup={row['duplicate_timestamp_rows']} "
                f"coarse={row['coarse_token_share']:.4f} "
                f"range={row['min']:.5f}..{row['max']:.5f} distinct={row['distinct_values']}"
            )
        archive_summaries.append({"month": source["month"], "filename": source["filename"], "sha256": sha256, "coder": archive.coder_name, "members": len(archive.entries), "kept_days": kept, "excluded_days": dropped})

    rows.sort(key=lambda row: row["date_local"])
    # Aggregate digest over samples in index (date) order; archive member
    # order is not chronological in every month (e.g. 2025-07).
    aggregate = hashlib.sha256()
    for row in rows:
        aggregate.update((data_root / row["sample_path"]).read_bytes())
    tmp_index = index_path.with_suffix(".jsonl.part")
    with tmp_index.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n")
    tmp_index.rename(index_path)
    with (filtered_dir / "day_stats.jsonl").open("w", encoding="utf-8") as handle:
        for stats in sorted(day_stats, key=lambda s: s["date"]):
            handle.write(json.dumps(stats, sort_keys=True, separators=(",", ":")) + "\n")
    hist = [sum(row["decimals_histogram"][i] for row in rows) for i in range(MAX_DECIMALS + 1)]
    summary = {
        "dataset_id": DATASET_ID,
        "series_id": SERIES_ID,
        "archives": archive_summaries,
        "sample_count": len(rows),
        "excluded_days": {s["date"]: s["exclusion_reasons"] for s in day_stats if not s["kept"]},
        "rules": {"min_covered_ticks": MIN_COVERED_TICKS, "max_coarse_token_share": MAX_COARSE_TOKEN_SHARE},
        "max_coarse_token_share_kept": max((row["coarse_token_share"] for row in rows), default=None),
        "min_coarse_token_share_kept": min((row["coarse_token_share"] for row in rows), default=None),
        "total_values": sum(row["value_count"] for row in rows),
        "total_size_bytes": sum(row["sample_size_bytes"] for row in rows),
        "min_values_per_sample": min((row["value_count"] for row in rows), default=0),
        "max_values_per_sample": max((row["value_count"] for row in rows), default=0),
        "total_missing_ticks": sum(row["missing_ticks"] for row in rows),
        "total_duplicate_timestamp_rows": sum(row["duplicate_timestamp_rows"] for row in rows),
        "total_backward_timestamp_steps": sum(row["backward_timestamp_steps"] for row in rows),
        "decimals_histogram": hist,
        "global_min": min((row["min"] for row in rows), default=None),
        "global_max": max((row["max"] for row in rows), default=None),
        "aggregate_sample_sha256": aggregate.hexdigest(),
    }
    (filtered_dir / "build_summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))
    if not rows:
        raise RecipeError("no samples emitted")
    return 0


# ------------------------------------------------------------------------ verify


def cmd_verify(args: argparse.Namespace) -> int:
    data_root = (Path(args.repo_root) / args.data_dir).resolve()
    manifest = tomllib.loads((RECIPE_DIR / "manifest.toml").read_text(encoding="utf-8"))
    series = [s for s in manifest["series"] if s.get("id") == SERIES_ID]
    if len(series) != 1 or len(manifest["series"]) != 1:
        raise RecipeError("manifest must declare exactly the one primary series")
    series = series[0]
    sources = load_sources()
    members = load_members()
    manifest_resources = {r["id"]: r for r in manifest["resources"]}
    for source in sources:
        resource = manifest_resources.get(f"archive_{source['month'].replace('-', '_')}")
        if not resource or resource["url"] != source["url"] or int(resource["size_bytes"]) != source["size_bytes"]:
            raise RecipeError(f"manifest resource for {source['month']} disagrees with sources.tsv")
        if source.get("sha256") and resource.get("sha256") != source["sha256"]:
            raise RecipeError(f"manifest sha256 for {source['month']} disagrees with sources.tsv")

    index_path = data_root / "index" / DATASET_ID / "samples.jsonl"
    index_rows = [json.loads(line) for line in index_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    by_date = {row["date_local"]: row for row in index_rows}
    if len(by_date) != len(index_rows):
        raise RecipeError("duplicate dates in the index")
    series_dir = data_root / "samples" / DATASET_ID / SERIES_ID
    on_disk = sorted(p.name for p in series_dir.iterdir())
    if on_disk != sorted(f"{d}.bin" for d in by_date):
        raise RecipeError("sample directory contents differ from the index")

    seen_dates: set[str] = set()
    dropped: list[str] = []
    total_bytes = total_values = 0
    compare_keys = [
        "value_count", "csv_data_rows", "blank_value_rows", "covered_ticks", "missing_ticks",
        "duplicate_timestamp_rows", "backward_timestamp_steps", "gap_count", "max_gap_ticks",
        "decimals_histogram", "coarse_token_share", "distinct_values", "min", "max",
    ]
    for source in sources:
        path = archive_path(data_root, source)
        check_archive_identity(path, source)
        archive = open_checked_archive(path, source["month"], members)
        for entry, payload in archive.iter_members():
            date = member_date(entry.name)
            raw, stats = parse_day_verify(payload, date)
            if not stats["kept"]:
                if date in by_date:
                    raise RecipeError(f"{date}: fails a day rule ({'; '.join(stats['exclusion_reasons'])}) but is present in the index")
                dropped.append(date)
                print(f"excluded {date}: {'; '.join(stats['exclusion_reasons'])}")
                continue
            row = by_date.get(date)
            if row is None:
                raise RecipeError(f"{date}: passes the coverage and resolution rules but is missing from the index")
            seen_dates.add(date)
            for key in compare_keys:
                if row.get(key) != stats[key]:
                    raise RecipeError(f"{date}: index {key}={row.get(key)!r} but re-derived {stats[key]!r}")
            if stats["distinct_values"] < 100 or stats["max"] - stats["min"] < 0.01:
                raise RecipeError(f"{date}: degenerate day (distinct={stats['distinct_values']}, range={stats['max'] - stats['min']})")
            sample_path = data_root / row["sample_path"]
            actual = sample_path.read_bytes()
            if actual != raw:
                raise RecipeError(f"{date}: sample bytes differ from the independent re-derivation")
            digest = hashlib.sha256(actual).hexdigest()
            if digest != row["sample_sha256"]:
                raise RecipeError(f"{date}: sample SHA-256 differs from the index")
            expected_fields = {
                "dataset_id": DATASET_ID, "series_id": SERIES_ID, "numeric_kind": "float", "bit_width": 32,
                "endianness": "little", "element_size_bytes": 4, "sample_size_bytes": len(actual),
                "source_member": entry.name, "source_archive": source["filename"],
            }
            for key, value in expected_fields.items():
                if row.get(key) != value:
                    raise RecipeError(f"{date}: index {key}={row.get(key)!r}, expected {value!r}")
            if len(actual) != 4 * row["value_count"]:
                raise RecipeError(f"{date}: size/value_count mismatch")
            total_bytes += len(actual)
            total_values += row["value_count"]
            print(f"ok {date}: values={row['value_count']} sha256={digest[:16]}")
    if seen_dates != set(by_date):
        raise RecipeError(f"index has dates not found in the archives: {sorted(set(by_date) - seen_dates)}")
    if series["sample_count"] != len(index_rows) or series["total_size_bytes"] != total_bytes:
        raise RecipeError(
            f"manifest scope sample_count={series['sample_count']} total_size_bytes={series['total_size_bytes']} "
            f"but realized {len(index_rows)} samples / {total_bytes} bytes"
        )
    if total_bytes > 1_000_000_000:
        raise RecipeError("primary output exceeds the 1 GB cap")
    print(
        f"verify=ok samples={len(index_rows)} values={total_values} bytes={total_bytes} "
        f"excluded_days={dropped or 'none'}"
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("validate-download")
    p.add_argument("--month", required=True)
    p.add_argument("--archive", required=True)
    p.add_argument("--quick", action="store_true", help="identity + header only (cache hits)")
    p.set_defaults(func=cmd_validate_download)
    p = sub.add_parser("check-page")
    p.add_argument("--page", required=True)
    p.set_defaults(func=cmd_check_page)
    p = sub.add_parser("page-listing")
    p.add_argument("--page", required=True)
    p.add_argument("months", nargs="+")
    p.set_defaults(func=cmd_page_listing)
    p = sub.add_parser("discover-members")
    p.add_argument("--month", required=True)
    p.add_argument("--start", required=True)
    p.add_argument("--next")
    p.add_argument("--packed")
    p.add_argument("--print-ranges", choices=["next", "packed"])
    p.set_defaults(func=cmd_discover_members)
    for name, func in (("build", cmd_build), ("verify", cmd_verify)):
        p = sub.add_parser(name)
        p.add_argument("--repo-root", required=True)
        p.add_argument("--data-dir", default=".data")
        p.set_defaults(func=func)
    args = parser.parse_args()
    try:
        return args.func(args)
    except (RecipeError, sevenzip.SevenZipError) as exc:
        print(f"FATAL: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
