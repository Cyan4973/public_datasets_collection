#!/usr/bin/env python3
"""Egyptian fruit bat (Rousettus aegyptiacus) vocalization recordings, PCM16.

Source: Prat, Taub, Pratt & Yovel (2017), "An annotated dataset of Egyptian
fruit bat vocalizations across varying contexts and during vocal ontogeny",
figshare collection 3666502 v2 (CC0). The 293,238 triggered 250 kHz mono
16-bit WAV recordings are stored as LZMA (ZIP method 14) members of 30 large
ZIP archives (files101-106, files201-224). This recipe collects a pinned,
evenly spaced subset of whole recordings by HTTP range requests, without
fetching the 98 GB of archives.

Subcommands (all network I/O is done by curl in the shell scripts; this
module only parses local files):

  discover        derive archives.tsv / members.tsv from a scratch directory
                  filled by discover.sh (documents how the pins were made)
  check-metadata  validate API article JSON, ZIP tails, central directories
                  and FileInfo.csv against archives.tsv, and re-derive the
                  member selection, which must equal members.tsv
  plan-members    list member byte spans still missing
  check-members   validate fetched .part spans and promote the good ones
  check-downloads require every pinned member to be present and valid
  build           decode every member and emit one int16 sample each
  verify          independent re-decode (zipfile + wave) and full checks
  selftest        synthetic-input test of both decoders and the ZIP parsers
"""
from __future__ import annotations

import argparse
import array
import csv
import datetime as dt
import hashlib
import io
import json
import lzma
import os
import re
import struct
import sys
import wave
import zipfile
import zlib
from pathlib import Path

DATASET_ID = "figshare_rousettus_vocalizations_i16"
SERIES_ID = "rousettus_vocalization_pcm_i16"
RECIPE_DIR = Path(__file__).resolve().parents[1]
ARCHIVES_TSV = RECIPE_DIR / "archives.tsv"
MEMBERS_TSV = RECIPE_DIR / "members.tsv"

COLLECTION_ID = 3666502
ARCHIVE_TITLE_RE = re.compile(r"^Egyptian fruit bat vocalizations files (\d{3})$")
FILEINFO = {
    "article_id": 4555897,
    "file_id": 8900695,
    "name": "FileInfo.csv",
    "size": 31574701,
    "md5": "b27252490ac5618bd55a9038110809d5",
    "sha256": "753529d166f8cbb6f900fa54d3d5122d1e47bae5d6be59669e37f33e4cc1ed34",
}
FILEINFO_HEADER = ["FileID", "Treatment ID", "File name", "File folder", "Recording channel", "Recording time"]
LICENSE_NAME = "CC0"
LICENSE_URL = "https://creativecommons.org/publicdomain/zero/1.0/"

# Selection rule (see README): TARGET_SAMPLES evenly spaced target positions
# over all members of the 30 archives in archive order and central-directory
# order; each target takes the first eligible member at or after it whose
# FileInfo recording time is more than MIN_SEPARATION_S seconds away from
# every member already taken (one microphone channel per vocal event).
TARGET_SAMPLES = 400
MIN_SEPARATION_S = 10
VALID_TREATMENTS = set(range(1, 21))
MEMBER_NAME_RE = re.compile(r"^\d{18}\.WAV$")

EXPECTED_FMT = (1, 1, 250000, 500000, 2, 16)  # PCM, mono, Hz, byte rate, block align, bits
TAIL_BYTES = 1024
MIN_DISTINCT_CODES = 64
MAX_EXCLUDED_FRACTION = 0.01
MAX_FLUSH_OVERRUN = 1024  # bytes a no-end-marker LZMA1 stream may decode past its declared size
FULL_SCALE = (-32768, 32767)

ARCHIVE_COLUMNS = ["archive", "article_id", "file_id", "size_bytes", "md5", "entries", "cd_offset", "cd_size", "cd_sha256", "zip64_eocd"]
MEMBER_COLUMNS = [
    "sample_id", "archive", "member", "cd_index", "global_index", "fileinfo_file_id", "treatment_id",
    "recording_channel", "recording_time", "local_header_offset", "span_bytes", "compressed_size",
    "uncompressed_size", "crc32",
]


class RecipeError(Exception):
    pass


def fail(message: str) -> None:
    raise RecipeError(message)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def md5_file(path: Path) -> str:
    digest = hashlib.md5()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


# --------------------------------------------------------------------------
# pinned tables


def read_tsv(path: Path, columns: list[str]) -> list[dict]:
    with path.open(encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh, delimiter="\t")
        if reader.fieldnames != columns:
            fail(f"{path.name}: unexpected columns {reader.fieldnames}")
        return list(reader)


def write_tsv(path: Path, columns: list[str], rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=columns, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row[key] for key in columns})


def load_archives(path: Path = ARCHIVES_TSV) -> list[dict]:
    rows = read_tsv(path, ARCHIVE_COLUMNS)
    for row in rows:
        for key in ("article_id", "file_id", "size_bytes", "entries", "cd_offset", "cd_size"):
            row[key] = int(row[key])
        row["zip64_eocd"] = row["zip64_eocd"] == "1"
    names = [row["archive"] for row in rows]
    if names != sorted(names) or len(set(names)) != len(names):
        fail("archives.tsv must list unique archives in sorted order")
    return rows


def load_members(path: Path = MEMBERS_TSV) -> list[dict]:
    rows = read_tsv(path, MEMBER_COLUMNS)
    for row in rows:
        for key in ("cd_index", "global_index", "fileinfo_file_id", "treatment_id", "recording_channel",
                    "local_header_offset", "span_bytes", "compressed_size", "uncompressed_size", "crc32"):
            row[key] = int(row[key])
    return rows


def member_relpath(row: dict) -> str:
    return f"members/{row['archive'][:-4]}/{row['member']}.zipentry"


# --------------------------------------------------------------------------
# ZIP structures


def parse_eocd(tail: bytes, archive_size: int) -> dict:
    """Parse the end of central directory (with ZIP64 when flagged) from the
    last bytes of an archive. Returns entries, cd_offset, cd_size, zip64."""
    base = archive_size - len(tail)
    pos = tail.rfind(b"PK\x05\x06")
    if pos < 0 or pos + 22 > len(tail):
        fail("EOCD signature not found in archive tail")
    _, disk, cd_disk, n_disk, n_total, cd_size, cd_offset, comment_len = struct.unpack("<IHHHHIIH", tail[pos:pos + 22])
    if pos + 22 + comment_len != len(tail):
        fail("EOCD comment length does not reach the end of the archive")
    if disk != 0 or cd_disk != 0 or n_disk != n_total:
        fail("multi-disk archives are not supported")
    zip64 = False
    cd_end = base + pos
    if cd_offset == 0xFFFFFFFF or cd_size == 0xFFFFFFFF or n_total == 0xFFFF:
        loc = pos - 20
        if loc < 0 or tail[loc:loc + 4] != b"PK\x06\x07":
            fail("ZIP64 EOCD locator missing")
        _, loc_disk, eocd64_offset, total_disks = struct.unpack("<IIQI", tail[loc:loc + 20])
        if loc_disk != 0 or total_disks != 1:
            fail("multi-disk ZIP64 archives are not supported")
        rel = eocd64_offset - base
        if rel < 0 or rel + 56 > loc:
            fail("ZIP64 EOCD record outside the fetched tail")
        rec = struct.unpack("<IQHHIIQQQQ", tail[rel:rel + 56])
        if rec[0] != 0x06064B50:
            fail("ZIP64 EOCD record signature mismatch")
        if rec[1] + 12 != loc - rel:
            fail("ZIP64 EOCD record size does not abut the locator")
        n_total, cd_size, cd_offset = rec[7], rec[8], rec[9]
        if rec[6] != rec[7]:
            fail("ZIP64 multi-disk entry counts")
        zip64 = True
        cd_end = eocd64_offset
    if cd_offset + cd_size != cd_end:
        fail(f"central directory [{cd_offset}, +{cd_size}) does not end at the EOCD ({cd_end})")
    return {"entries": n_total, "cd_offset": cd_offset, "cd_size": cd_size, "zip64": zip64}


def parse_zip64_extra(extra: bytes, usize: int, csize: int, offset: int) -> tuple[int, int, int]:
    pos = 0
    while pos + 4 <= len(extra):
        header_id, size = struct.unpack("<HH", extra[pos:pos + 4])
        body = extra[pos + 4:pos + 4 + size]
        if len(body) != size:
            fail("truncated extra field")
        if header_id == 0x0001:
            k = 0
            for name in ("usize", "csize", "offset"):
                value = {"usize": usize, "csize": csize, "offset": offset}[name]
                if value == 0xFFFFFFFF:
                    if k + 8 > len(body):
                        fail("ZIP64 extra field too short")
                    (wide,) = struct.unpack("<Q", body[k:k + 8])
                    k += 8
                    if name == "usize":
                        usize = wide
                    elif name == "csize":
                        csize = wide
                    else:
                        offset = wide
        pos += 4 + size
    if pos != len(extra):
        fail("malformed extra field")
    if 0xFFFFFFFF in (usize, csize, offset):
        fail("ZIP64 sentinel without matching ZIP64 extra field")
    return usize, csize, offset


def parse_central_directory(data: bytes, expected_entries: int) -> list[dict]:
    entries = []
    pos = 0
    while pos < len(data):
        if pos + 46 > len(data):
            fail("truncated central directory entry")
        (sig, made_by, needed, flags, method, mtime, mdate, crc, csize, usize, name_len, extra_len,
         comment_len, disk, internal, external, offset) = struct.unpack("<IHHHHHHIIIHHHHHII", data[pos:pos + 46])
        if sig != 0x02014B50:
            fail(f"central directory signature mismatch at {pos}")
        name_raw = data[pos + 46:pos + 46 + name_len]
        extra = data[pos + 46 + name_len:pos + 46 + name_len + extra_len]
        usize, csize, offset = parse_zip64_extra(extra, usize, csize, offset)
        if disk not in (0, 0xFFFF):
            fail("multi-disk member")
        entries.append({
            "name": name_raw.decode("cp437"), "flags": flags, "method": method, "crc32": crc,
            "compressed_size": csize, "uncompressed_size": usize, "local_header_offset": offset,
            "version_needed": needed, "mtime": mtime, "mdate": mdate,
        })
        pos += 46 + name_len + extra_len + comment_len
    if len(entries) != expected_entries:
        fail(f"central directory has {len(entries)} entries, EOCD says {expected_entries}")
    offsets = [entry["local_header_offset"] for entry in entries]
    if offsets != sorted(offsets) or len(set(offsets)) != len(offsets):
        fail("central directory local-header offsets are not strictly increasing")
    return entries


def attach_spans(entries: list[dict], cd_offset: int) -> None:
    """Each member occupies [own offset, next member offset) because the
    archives store members back to back without data descriptors."""
    for index, entry in enumerate(entries):
        end = entries[index + 1]["local_header_offset"] if index + 1 < len(entries) else cd_offset
        entry["span_bytes"] = end - entry["local_header_offset"]


def parse_local_header(span: bytes, cd: dict) -> int:
    """Validate the local file header of one fetched member span against its
    central-directory entry. Returns the offset of the compressed data."""
    if len(span) < 30:
        fail("member span shorter than a local header")
    (sig, needed, flags, method, mtime, mdate, crc, csize, usize, name_len, extra_len) = struct.unpack("<IHHHHHIIIHH", span[:30])
    if sig != 0x04034B50:
        fail("local header signature mismatch")
    name = span[30:30 + name_len].decode("cp437")
    if name != cd["name"]:
        fail(f"local header name {name!r} != central directory name {cd['name']!r}")
    if flags != cd["flags"] or method != cd["method"]:
        fail("local header flags/method disagree with the central directory")
    if flags & 0x0001:
        fail("encrypted member")
    if flags & 0x0008:
        fail("member uses a data descriptor; spans would not be exact")
    extra = span[30 + name_len:30 + name_len + extra_len]
    usize, csize, _ = parse_zip64_extra(extra, usize, csize, 0)
    if (crc, csize, usize) != (cd["crc32"], cd["compressed_size"], cd["uncompressed_size"]):
        fail("local header crc/sizes disagree with the central directory")
    data_offset = 30 + name_len + extra_len
    if data_offset + csize != len(span):
        fail(f"span length {len(span)} != header {data_offset} + compressed {csize}")
    return data_offset


def lzma_decode(data: bytes, uncompressed_size: int, flags: int) -> tuple[bytes, int]:
    """Decode ZIP method 14: u8 major, u8 minor, u16 props size (5), the
    5-byte LZMA1 properties (lc/lp/pb byte + u32 dictionary size), then a raw
    LZMA1 stream, terminated by an end marker only when flag bit 1 is set.

    Returns (exactly uncompressed_size bytes, flush overrun). Without an end
    marker the raw decoder cannot know where the stream stops, so the range
    coder's final flush bytes can decode into a few spurious symbols past the
    declared size (observed: one 0x00 byte in 1 of the 400 pinned members).
    As in 7-Zip and the stdlib zipfile module, the declared size bounds the
    output; the overrun must stay within MAX_FLUSH_OVERRUN bytes and consume
    all input, and the caller checks the CRC32 of the declared-size prefix."""
    if len(data) < 9:
        fail("LZMA member too short")
    _major, _minor, props_size = struct.unpack("<BBH", data[:4])
    if props_size != 5:
        fail(f"LZMA properties size {props_size} != 5")
    props = data[4:9]
    lclppb = props[0]
    if lclppb >= 9 * 5 * 5:
        fail("invalid LZMA lc/lp/pb byte")
    pb, rem = divmod(lclppb, 45)
    lp, lc = divmod(rem, 9)
    (dict_size,) = struct.unpack("<I", props[1:5])
    decoder = lzma.LZMADecompressor(
        format=lzma.FORMAT_RAW,
        filters=[{"id": lzma.FILTER_LZMA1, "dict_size": dict_size, "lc": lc, "lp": lp, "pb": pb}],
    )
    out = decoder.decompress(data[9:], max_length=uncompressed_size)
    if len(out) != uncompressed_size:
        fail(f"LZMA produced {len(out)} bytes, expected {uncompressed_size}")
    if flags & 0x0002:
        more = b"" if decoder.eof else decoder.decompress(b"", max_length=1)
        if more or not decoder.eof or decoder.unused_data:
            fail("LZMA end-of-stream marker missing, misplaced, or followed by trailing data")
        return out, 0
    more = b"" if decoder.eof else decoder.decompress(b"", max_length=MAX_FLUSH_OVERRUN + 1)
    if len(more) > MAX_FLUSH_OVERRUN:
        fail(f"LZMA stream decodes more than {MAX_FLUSH_OVERRUN} bytes past the declared uncompressed size")
    if decoder.unused_data or not (decoder.eof or decoder.needs_input):
        fail("LZMA input not fully consumed at the end of the member")
    return out, len(more)


def riff_pcm(wav: bytes) -> tuple[tuple, bytes, list[str]]:
    """Walk the RIFF chunk list; return (fmt tuple, data chunk, chunk ids)."""
    if len(wav) < 12 or wav[:4] != b"RIFF" or wav[8:12] != b"WAVE":
        fail("not a RIFF/WAVE file")
    (riff_size,) = struct.unpack("<I", wav[4:8])
    if riff_size + 8 != len(wav):
        fail(f"RIFF size {riff_size} + 8 != file size {len(wav)}")
    pos = 12
    fmt = None
    data = None
    chunk_ids = []
    while pos < len(wav):
        if pos + 8 > len(wav):
            fail("truncated RIFF chunk header")
        cid = wav[pos:pos + 4]
        (size,) = struct.unpack("<I", wav[pos + 4:pos + 8])
        body = wav[pos + 8:pos + 8 + size]
        if len(body) != size:
            fail(f"truncated RIFF chunk {cid!r}")
        chunk_ids.append(cid.decode("latin-1"))
        if cid == b"fmt ":
            if fmt is not None or size < 16:
                fail("duplicate or short fmt chunk")
            fmt = struct.unpack("<HHIIHH", body[:16])
        elif cid == b"data":
            if data is not None:
                fail("duplicate data chunk")
            data = body
        pos += 8 + size + (size & 1)
    if pos != len(wav):
        fail("RIFF chunks overrun the file")
    if fmt is None or data is None:
        fail("missing fmt or data chunk")
    if fmt != EXPECTED_FMT:
        fail(f"fmt {fmt} != expected {EXPECTED_FMT} (PCM, mono, 250 kHz, 16-bit)")
    if len(data) % 2 or not data:
        fail("data chunk empty or not a whole number of int16 samples")
    return fmt, data, chunk_ids


def decode_member_span(span: bytes, cd: dict) -> tuple[bytes, list[str], int]:
    """Build path: local header -> raw LZMA1 -> CRC32 -> RIFF -> PCM bytes.
    Returns (PCM data chunk, RIFF chunk ids, LZMA flush overrun bytes)."""
    if cd["method"] != 14:
        fail(f"member {cd['name']} uses method {cd['method']}, expected 14 (LZMA)")
    offset = parse_local_header(span, cd)
    wav, overrun = lzma_decode(span[offset:], cd["uncompressed_size"], cd["flags"])
    if zlib.crc32(wav) & 0xFFFFFFFF != cd["crc32"]:
        fail(f"CRC32 mismatch for {cd['name']}")
    _fmt, data, chunk_ids = riff_pcm(wav)
    return data, chunk_ids, overrun


def decode_member_independent(span: bytes, cd: dict) -> bytes:
    """Verify path: wrap the fetched local entry in a one-entry central
    directory carrying the real central-directory CRC and sizes, let the
    stdlib zipfile module (its own method-14 handling and CRC check) extract
    it, then read the frames with the stdlib wave module."""
    (_sig, needed, flags, method, mtime, mdate, _crc, _csize, _usize, name_len, _extra_len) = struct.unpack("<IHHHHHIIIHH", span[:30])
    name = span[30:30 + name_len]
    central = struct.pack("<IHHHHHHIIIHHHHHII", 0x02014B50, needed, needed, flags, method, mtime, mdate, cd["crc32"],
                          cd["compressed_size"], cd["uncompressed_size"], name_len, 0, 0, 0, 0, 0, 0) + name
    eocd = struct.pack("<IHHHHIIH", 0x06054B50, 0, 0, 1, 1, len(central), len(span), 0)
    with zipfile.ZipFile(io.BytesIO(span + central + eocd)) as archive:
        info = archive.getinfo(name.decode("cp437"))
        if info.compress_type != zipfile.ZIP_LZMA:
            fail("zipfile reports a non-LZMA member")
        wav = archive.read(info)
    with wave.open(io.BytesIO(wav)) as reader:
        params = (reader.getnchannels(), reader.getsampwidth(), reader.getframerate(), reader.getcomptype())
        if params != (1, 2, 250000, "NONE"):
            fail(f"wave module reports {params}")
        frames = reader.readframes(reader.getnframes())
        if len(frames) != 2 * reader.getnframes():
            fail("wave module returned a short frame buffer")
    return frames


# --------------------------------------------------------------------------
# FileInfo and selection


def load_fileinfo(path: Path) -> dict[tuple[str, str], dict]:
    with path.open(encoding="utf-8", newline="") as fh:
        reader = csv.reader(fh)
        header = next(reader)
        if header[:6] != FILEINFO_HEADER:
            fail(f"FileInfo.csv header {header[:6]} unexpected")
        table = {}
        for line_number, row in enumerate(reader, 2):
            if len(row) < 6:
                fail(f"FileInfo.csv line {line_number}: too few columns")
            key = (row[3], row[2])
            if key in table:
                fail(f"FileInfo.csv duplicate entry {key}")
            table[key] = {
                "file_id": int(row[0]),
                "treatment_id": int(row[1]),
                "channel": int(row[4]),
                "recording_time": row[5],
                "epoch": dt.datetime.strptime(row[5], "%Y-%m-%d %H:%M:%S").replace(tzinfo=dt.timezone.utc).timestamp(),
            }
    return table


def load_central_directories(cd_dir: Path, archives: list[dict], check_sha: bool = True) -> dict[str, list[dict]]:
    cds = {}
    for arch in archives:
        path = cd_dir / f"{arch['archive']}.cd"
        if not path.is_file():
            fail(f"missing central directory {path}")
        data = path.read_bytes()
        if len(data) != arch["cd_size"]:
            fail(f"{path.name}: {len(data)} bytes, expected {arch['cd_size']}")
        if check_sha and sha256_bytes(data) != arch["cd_sha256"]:
            fail(f"{path.name}: sha256 mismatch (archive listing changed?)")
        entries = parse_central_directory(data, arch["entries"])
        attach_spans(entries, arch["cd_offset"])
        cds[arch["archive"]] = entries
    return cds


def select_members(archives: list[dict], cds: dict[str, list[dict]], fileinfo: dict) -> tuple[list[dict], dict]:
    universe = []
    for arch in archives:
        for index, entry in enumerate(cds[arch["archive"]]):
            universe.append((arch, index, entry))
    total = len(universe)
    if total != len(fileinfo):
        fail(f"archives list {total} members but FileInfo.csv has {len(fileinfo)} rows")
    targets = [((2 * k + 1) * total) // (2 * TARGET_SAMPLES) for k in range(TARGET_SAMPLES)]
    selected: list[dict] = []
    taken_epochs: list[float] = []
    skipped = {"ineligible": 0, "too_close_in_time": 0}
    for k, start in enumerate(targets):
        stop = targets[k + 1] if k + 1 < len(targets) else total
        chosen = None
        for global_index in range(start, stop):
            arch, cd_index, entry = universe[global_index]
            info = fileinfo.get((arch["archive"][:-4], entry["name"]))
            eligible = (
                info is not None
                and MEMBER_NAME_RE.match(entry["name"]) is not None
                and entry["method"] == 14
                and entry["flags"] in (0, 2)
                and info["treatment_id"] in VALID_TREATMENTS
                and entry["span_bytes"] == 30 + len(entry["name"]) + entry["compressed_size"]
            )
            if not eligible:
                skipped["ineligible"] += 1
                continue
            if any(abs(info["epoch"] - epoch) <= MIN_SEPARATION_S for epoch in taken_epochs):
                skipped["too_close_in_time"] += 1
                continue
            chosen = (global_index, arch, cd_index, entry, info)
            break
        if chosen is None:
            fail(f"no eligible member between global positions {start} and {stop}")
        global_index, arch, cd_index, entry, info = chosen
        taken_epochs.append(info["epoch"])
        selected.append({
            "sample_id": f"{arch['archive'][:-4]}_{entry['name'][:-4]}",
            "archive": arch["archive"],
            "member": entry["name"],
            "cd_index": cd_index,
            "global_index": global_index,
            "fileinfo_file_id": info["file_id"],
            "treatment_id": info["treatment_id"],
            "recording_channel": info["channel"],
            "recording_time": info["recording_time"],
            "local_header_offset": entry["local_header_offset"],
            "span_bytes": entry["span_bytes"],
            "compressed_size": entry["compressed_size"],
            "uncompressed_size": entry["uncompressed_size"],
            "crc32": entry["crc32"],
        })
    return selected, {"universe_members": total, "targets": len(targets), **skipped}


def normalize_members(rows: list[dict]) -> list[tuple]:
    return [tuple(str(row[key]) for key in MEMBER_COLUMNS) for row in rows]


# --------------------------------------------------------------------------
# download-time checks


def check_article_json(path: Path, article_id: int, file_id: int, name: str, size: int, md5: str) -> None:
    try:
        meta = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        fail(f"{path.name}: unreadable article JSON ({exc})")
    if meta.get("id") != article_id:
        fail(f"{path.name}: article id {meta.get('id')} != {article_id}")
    lic = meta.get("license") or {}
    if lic.get("name") != LICENSE_NAME or lic.get("url") != LICENSE_URL:
        fail(f"{path.name}: license {lic} is not CC0")
    files = [f for f in meta.get("files", []) if f.get("id") == file_id]
    if len(files) != 1:
        fail(f"{path.name}: file {file_id} not listed")
    entry = files[0]
    if entry.get("name") != name or int(entry.get("size", -1)) != size or entry.get("computed_md5") != md5:
        fail(f"{path.name}: file {file_id} metadata changed: {entry.get('name')} {entry.get('size')} {entry.get('computed_md5')}")


def check_metadata(download_dir: Path) -> dict:
    archives = load_archives()
    api_dir = download_dir / "api"
    for arch in archives:
        check_article_json(api_dir / f"article_{arch['article_id']}.json", arch["article_id"], arch["file_id"],
                           arch["archive"], arch["size_bytes"], arch["md5"])
    check_article_json(api_dir / f"article_{FILEINFO['article_id']}.json", FILEINFO["article_id"], FILEINFO["file_id"],
                       FILEINFO["name"], FILEINFO["size"], FILEINFO["md5"])
    for arch in archives:
        tail_path = download_dir / "zip_tails" / f"{arch['archive']}.tail"
        tail = tail_path.read_bytes()
        if len(tail) != TAIL_BYTES:
            fail(f"{tail_path.name}: {len(tail)} bytes, expected {TAIL_BYTES}")
        eocd = parse_eocd(tail, arch["size_bytes"])
        if (eocd["entries"], eocd["cd_offset"], eocd["cd_size"], eocd["zip64"]) != (arch["entries"], arch["cd_offset"], arch["cd_size"], arch["zip64_eocd"]):
            fail(f"{arch['archive']}: EOCD {eocd} disagrees with archives.tsv")
    cds = load_central_directories(download_dir / "central_directories", archives)
    fileinfo_path = download_dir / FILEINFO["name"]
    if fileinfo_path.stat().st_size != FILEINFO["size"] or md5_file(fileinfo_path) != FILEINFO["md5"]:
        fail("FileInfo.csv size/md5 mismatch")
    if sha256_file(fileinfo_path) != FILEINFO["sha256"]:
        fail("FileInfo.csv sha256 mismatch")
    fileinfo = load_fileinfo(fileinfo_path)
    selected, stats = select_members(archives, cds, fileinfo)
    pinned = load_members()
    if normalize_members(selected) != normalize_members(pinned):
        fail("re-derived member selection differs from the pinned members.tsv")
    return {"archives": len(archives), "selected": len(selected), **stats}


def parse_content_range(header_path: Path) -> tuple[int, int, int]:
    found = None
    for line in header_path.read_text(encoding="latin-1").splitlines():
        match = re.match(r"(?i)^content-range:\s*bytes\s+(\d+)-(\d+)/(\d+)\s*$", line.strip())
        if match:
            found = tuple(int(group) for group in match.groups())
    if found is None:
        fail(f"{header_path.name}: no Content-Range header (range request not honoured)")
    return found


def member_cd(row: dict, cds: dict[str, list[dict]]) -> dict:
    """The central-directory entry of a pinned member, cross-checked against
    the pinned CRC and sizes."""
    cd = cds[row["archive"]][row["cd_index"]]
    pinned = (row["member"], row["local_header_offset"], row["span_bytes"], row["compressed_size"], row["uncompressed_size"], row["crc32"])
    actual = (cd["name"], cd["local_header_offset"], cd["span_bytes"], cd["compressed_size"], cd["uncompressed_size"], cd["crc32"])
    if pinned != actual:
        fail(f"members.tsv row {row['sample_id']} disagrees with the central directory: {pinned} != {actual}")
    return cd


def plan_members(download_dir: Path, plan_path: Path) -> int:
    archives = {arch["archive"]: arch for arch in load_archives()}
    pending = 0
    with plan_path.open("w", encoding="utf-8") as out:
        for row in load_members():
            final = download_dir / member_relpath(row)
            if final.is_file() and final.stat().st_size == row["span_bytes"]:
                continue
            start = row["local_header_offset"]
            end = start + row["span_bytes"] - 1
            out.write(f"{archives[row['archive']]['file_id']} {start} {end} {member_relpath(row)}\n")
            pending += 1
    return pending


def check_members(download_dir: Path) -> dict:
    archive_list = load_archives()
    archives = {arch["archive"]: arch for arch in archive_list}
    cds = load_central_directories(download_dir / "central_directories", archive_list)
    promoted = rejected = 0
    for row in load_members():
        final = download_dir / member_relpath(row)
        part = final.with_name(final.name + ".part")
        header = final.with_name(final.name + ".hdr")
        if not part.exists():
            header.unlink(missing_ok=True)
            continue
        try:
            if not header.exists():
                fail(f"{header.name} missing")
            first, last, total = parse_content_range(header)
            start = row["local_header_offset"]
            if (first, last) != (start, start + row["span_bytes"] - 1):
                fail(f"Content-Range {first}-{last} != requested span")
            if total != archives[row["archive"]]["size_bytes"]:
                fail(f"Content-Range total {total} != pinned archive size {archives[row['archive']]['size_bytes']}")
            span = part.read_bytes()
            if len(span) != row["span_bytes"]:
                fail(f"{len(span)} bytes, expected {row['span_bytes']}")
            decode_member_span(span, member_cd(row, cds))
        except (RecipeError, lzma.LZMAError) as exc:
            print(f"reject member={row['archive']}/{row['member']} reason={exc}", flush=True)
            part.unlink(missing_ok=True)
            header.unlink(missing_ok=True)
            rejected += 1
            continue
        os.replace(part, final)
        header.unlink(missing_ok=True)
        promoted += 1
    return {"promoted": promoted, "rejected": rejected}


def check_downloads(download_dir: Path) -> dict:
    cds = load_central_directories(download_dir / "central_directories", load_archives())
    total_bytes = 0
    rows = load_members()
    for row in rows:
        path = download_dir / member_relpath(row)
        if not path.is_file():
            fail(f"missing member span {member_relpath(row)}")
        span = path.read_bytes()
        if len(span) != row["span_bytes"]:
            fail(f"{member_relpath(row)}: wrong size")
        try:
            decode_member_span(span, member_cd(row, cds))
        except lzma.LZMAError as exc:
            fail(f"{member_relpath(row)}: LZMA error {exc}")
        total_bytes += len(span)
    return {"members": len(rows), "member_span_bytes": total_bytes}


# --------------------------------------------------------------------------
# build / verify


def pcm_stats(pcm: bytes) -> dict:
    values = array.array("h")
    values.frombytes(pcm)
    if sys.byteorder != "little":
        values.byteswap()
    distinct = len(set(values))
    return {
        "value_count": len(values),
        "min": min(values),
        "max": max(values),
        "distinct_codes": distinct,
        "full_scale_count": values.count(FULL_SCALE[0]) + values.count(FULL_SCALE[1]),
    }


def exclusion_reason(stats: dict, digest: str, seen: set[str]) -> str | None:
    if stats["distinct_codes"] < MIN_DISTINCT_CODES:
        return f"fewer than {MIN_DISTINCT_CODES} distinct PCM codes ({stats['distinct_codes']})"
    if digest in seen:
        return "PCM payload byte-identical to an earlier selected recording"
    return None


def sample_relpath(row: dict) -> str:
    return f"samples/{DATASET_ID}/{SERIES_ID}/{row['sample_id']}.bin"


def build(download_dir: Path, data_root: Path, index_path: Path, stats_path: Path) -> dict:
    archives = load_archives()
    cds = load_central_directories(download_dir / "central_directories", archives)
    fileinfo = load_fileinfo(download_dir / FILEINFO["name"])
    selected, selection_stats = select_members(archives, cds, fileinfo)
    pinned = load_members()
    if normalize_members(selected) != normalize_members(pinned):
        fail("re-derived member selection differs from the pinned members.tsv")
    samples_dir = data_root / "samples" / DATASET_ID / SERIES_ID
    samples_dir.mkdir(parents=True, exist_ok=True)
    for stale in samples_dir.glob("*.bin"):
        stale.unlink()
    index_path.parent.mkdir(parents=True, exist_ok=True)
    stats_path.parent.mkdir(parents=True, exist_ok=True)
    aggregate = hashlib.sha256()
    seen: set[str] = set()
    rows_out = []
    excluded = []
    chunk_layouts: dict[str, int] = {}
    flush_overruns: dict[str, int] = {}
    totals = {"values": 0, "bytes": 0, "full_scale": 0}
    for row in pinned:
        cd = member_cd(row, cds)
        span = (download_dir / member_relpath(row)).read_bytes()
        pcm, chunk_ids, overrun = decode_member_span(span, cd)
        if overrun:
            flush_overruns[row["sample_id"]] = overrun
        layout = ",".join(chunk_ids)
        chunk_layouts[layout] = chunk_layouts.get(layout, 0) + 1
        digest = sha256_bytes(pcm)
        stats = pcm_stats(pcm)
        reason = exclusion_reason(stats, digest, seen)
        seen.add(digest)
        if reason:
            excluded.append({"sample_id": row["sample_id"], "reason": reason})
            continue
        rel = sample_relpath(row)
        (data_root / rel).write_bytes(pcm)
        aggregate.update(pcm)
        totals["values"] += stats["value_count"]
        totals["bytes"] += len(pcm)
        totals["full_scale"] += stats["full_scale_count"]
        rows_out.append({
            "dataset_id": DATASET_ID,
            "series_id": SERIES_ID,
            "sample_path": rel,
            "numeric_kind": "int",
            "bit_width": 16,
            "endianness": "little",
            "element_size_bytes": 2,
            "sample_size_bytes": len(pcm),
            "value_count": stats["value_count"],
            "sample_rate_hz": 250000,
            "duration_s": round(stats["value_count"] / 250000, 6),
            "archive": row["archive"],
            "member": row["member"],
            "fileinfo_file_id": row["fileinfo_file_id"],
            "treatment_id": row["treatment_id"],
            "recording_channel": row["recording_channel"],
            "recording_time": row["recording_time"],
            "member_crc32": f"{row['crc32']:08x}",
            "sha256": digest,
            "min": stats["min"],
            "max": stats["max"],
            "distinct_codes": stats["distinct_codes"],
            "full_scale_count": stats["full_scale_count"],
        })
    if len(excluded) > MAX_EXCLUDED_FRACTION * len(pinned):
        fail(f"{len(excluded)} of {len(pinned)} recordings excluded; more than {MAX_EXCLUDED_FRACTION:.0%}")
    with index_path.open("w", encoding="utf-8") as fh:
        for row in rows_out:
            fh.write(json.dumps(row, sort_keys=True) + "\n")
    counts = sorted(row["value_count"] for row in rows_out)
    mid = len(counts) // 2
    median = counts[mid] if len(counts) % 2 else (counts[mid - 1] + counts[mid]) / 2
    treatments: dict[str, int] = {}
    for row in rows_out:
        treatments[str(row["treatment_id"])] = treatments.get(str(row["treatment_id"]), 0) + 1
    summary = {
        "dataset_id": DATASET_ID,
        "series_id": SERIES_ID,
        "selection": selection_stats,
        "pinned_members": len(pinned),
        "samples": len(rows_out),
        "excluded": excluded,
        "total_values": totals["values"],
        "total_bytes": totals["bytes"],
        "median_values": median,
        "min_values": counts[0],
        "max_values": counts[-1],
        "full_scale_values": totals["full_scale"],
        "full_scale_fraction": round(totals["full_scale"] / totals["values"], 8),
        "treatment_counts": dict(sorted(treatments.items(), key=lambda kv: int(kv[0]))),
        "archives_used": len({row["archive"] for row in rows_out}),
        "riff_chunk_layouts": chunk_layouts,
        "lzma_flush_overrun_bytes": flush_overruns,
        "aggregate_sha256": aggregate.hexdigest(),
    }
    stats_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return summary


def verify(download_dir: Path, data_root: Path, index_path: Path, stats_path: Path, manifest_path: Path) -> dict:
    import tomllib

    archives = load_archives()
    cds = load_central_directories(download_dir / "central_directories", archives)
    fileinfo = load_fileinfo(download_dir / FILEINFO["name"])
    selected, _ = select_members(archives, cds, fileinfo)
    pinned = load_members()
    if normalize_members(selected) != normalize_members(pinned):
        fail("re-derived member selection differs from the pinned members.tsv")
    for row in pinned:
        info = fileinfo[(row["archive"][:-4], row["member"])]
        if (info["file_id"], info["treatment_id"], info["channel"], info["recording_time"]) != (
            row["fileinfo_file_id"], row["treatment_id"], row["recording_channel"], row["recording_time"]):
            fail(f"members.tsv metadata for {row['sample_id']} disagrees with FileInfo.csv")
    epochs = sorted(fileinfo[(row["archive"][:-4], row["member"])]["epoch"] for row in pinned)
    if any(b - a <= MIN_SEPARATION_S for a, b in zip(epochs, epochs[1:])):
        fail("two selected recordings are within the minimum time separation")

    index_rows = [json.loads(line) for line in index_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    stats = json.loads(stats_path.read_text(encoding="utf-8"))
    by_path = {row["sample_path"]: row for row in index_rows}
    if len(by_path) != len(index_rows):
        fail("duplicate sample paths in index")
    aggregate = hashlib.sha256()
    seen: set[str] = set()
    excluded = []
    expected_paths = []
    values_total = bytes_total = full_scale_total = 0
    for row in pinned:
        span = (download_dir / member_relpath(row)).read_bytes()
        frames = decode_member_independent(span, member_cd(row, cds))
        digest = sha256_bytes(frames)
        pstats = pcm_stats(frames)
        reason = exclusion_reason(pstats, digest, seen)
        seen.add(digest)
        if reason:
            excluded.append({"sample_id": row["sample_id"], "reason": reason})
            continue
        rel = sample_relpath(row)
        expected_paths.append(rel)
        index_row = by_path.get(rel)
        if index_row is None:
            fail(f"index lacks {rel}")
        sample = (data_root / rel).read_bytes()
        if sample != frames:
            fail(f"{rel}: sample bytes differ from the independent zipfile+wave decode")
        expect = {
            "dataset_id": DATASET_ID, "series_id": SERIES_ID, "numeric_kind": "int", "bit_width": 16,
            "endianness": "little", "element_size_bytes": 2, "sample_size_bytes": len(frames),
            "value_count": pstats["value_count"], "archive": row["archive"], "member": row["member"],
            "fileinfo_file_id": row["fileinfo_file_id"], "treatment_id": row["treatment_id"],
            "recording_channel": row["recording_channel"], "recording_time": row["recording_time"],
            "sha256": digest, "min": pstats["min"], "max": pstats["max"],
            "distinct_codes": pstats["distinct_codes"], "full_scale_count": pstats["full_scale_count"],
            "sample_rate_hz": 250000, "member_crc32": f"{row['crc32']:08x}",
        }
        for key, value in expect.items():
            if index_row.get(key) != value:
                fail(f"{rel}: index field {key}={index_row.get(key)!r}, expected {value!r}")
        if pstats["min"] == pstats["max"]:
            fail(f"{rel}: constant sample")
        aggregate.update(frames)
        values_total += pstats["value_count"]
        bytes_total += len(frames)
        full_scale_total += pstats["full_scale_count"]
    if [row["sample_path"] for row in index_rows] != expected_paths:
        fail("index rows are not exactly the expected samples in canonical order")
    on_disk = sorted(str(p.relative_to(data_root)) for p in (data_root / "samples" / DATASET_ID / SERIES_ID).glob("*"))
    if on_disk != sorted(expected_paths):
        fail("sample directory contains unexpected or missing files")
    if excluded != stats.get("excluded"):
        fail(f"exclusions {excluded} disagree with build stats {stats.get('excluded')}")
    if len(excluded) > MAX_EXCLUDED_FRACTION * len(pinned):
        fail("too many exclusions")
    if aggregate.hexdigest() != stats.get("aggregate_sha256"):
        fail("aggregate sha256 disagrees with build stats")
    if values_total != stats.get("total_values") or bytes_total != stats.get("total_bytes"):
        fail("totals disagree with build stats")
    counts = sorted(row["value_count"] for row in index_rows)
    mid = len(counts) // 2
    median = counts[mid] if len(counts) % 2 else (counts[mid - 1] + counts[mid]) / 2
    if not (values_total >= 10_000 or bytes_total >= 100_000) or median < 1_000:
        fail("primary floors not met")
    if bytes_total > 1_000_000_000:
        fail("primary output exceeds 1 GB")
    manifest = tomllib.loads(manifest_path.read_text(encoding="utf-8"))
    series = [s for s in manifest.get("series", []) if s.get("id") == SERIES_ID]
    if len(series) != 1:
        fail("manifest must declare the series exactly once")
    if series[0].get("sample_count") != len(index_rows) or series[0].get("total_size_bytes") != bytes_total:
        fail(f"manifest totals ({series[0].get('sample_count')}, {series[0].get('total_size_bytes')}) != realized ({len(index_rows)}, {bytes_total})")
    return {
        "samples": len(index_rows), "excluded": len(excluded), "total_values": values_total,
        "total_bytes": bytes_total, "median_values": median, "full_scale_values": full_scale_total,
        "aggregate_sha256": aggregate.hexdigest(),
    }


# --------------------------------------------------------------------------
# self-test on synthetic inputs


def synthetic_wav(n: int, seed: int, trailer: bool) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(250000)
        values = array.array("h", [((i * 7919 + seed * 104729) % 65536) - 32768 for i in range(n)])
        if sys.byteorder != "little":
            values.byteswap()
        writer.writeframes(values.tobytes())
    wav = buf.getvalue()
    if trailer:  # mimic the Avisoft TIME/bext trailer chunks
        extra = b"TIME" + struct.pack("<I", 5) + b"12:00" + b"\x00" + b"bext" + struct.pack("<I", 4) + b"\x00" * 4
        wav = wav[:4] + struct.pack("<I", len(wav) - 8 + len(extra)) + wav[8:] + extra
    return wav


def selftest() -> None:
    # 1. method-14 members written by zipfile (EOS marker, flag bit 1), and a
    #    forced-ZIP64 local header, decoded by both paths.
    buf = io.BytesIO()
    wavs = {"000000000000000001.WAV": synthetic_wav(4001, 1, True), "000000000000000002.WAV": synthetic_wav(2500, 2, False)}
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_LZMA) as archive:
        for name, payload in wavs.items():
            archive.writestr(name, payload)
        with archive.open("000000000000000003.WAV", "w", force_zip64=True) as fh:
            fh.write(synthetic_wav(3000, 3, True))
        wavs["000000000000000003.WAV"] = synthetic_wav(3000, 3, True)
    blob = buf.getvalue()
    eocd = parse_eocd(blob[-TAIL_BYTES:] if len(blob) > TAIL_BYTES else blob, len(blob))
    entries = parse_central_directory(blob[eocd["cd_offset"]:eocd["cd_offset"] + eocd["cd_size"]], eocd["entries"])
    attach_spans(entries, eocd["cd_offset"])
    assert len(entries) == 3 and all(e["method"] == 14 and e["flags"] & 0x0002 for e in entries), entries
    for entry in entries:
        span = blob[entry["local_header_offset"]:entry["local_header_offset"] + entry["span_bytes"]]
        pcm, chunk_ids, overrun = decode_member_span(span, entry)
        assert overrun == 0
        expected = riff_pcm(wavs[entry["name"]])[1]
        assert pcm == expected, entry["name"]
        assert decode_member_independent(span, entry) == expected, entry["name"]
        assert chunk_ids[:2] == ["fmt ", "data"]
    # the forced-ZIP64 member carries a ZIP64 extra in its local header
    zip64_span = blob[entries[2]["local_header_offset"]:]
    assert struct.unpack("<I", zip64_span[18:22])[0] == 0xFFFFFFFF
    # 2. corruption must be caught (flip one compressed byte, then the CRC).
    entry = entries[0]
    span = bytearray(blob[entry["local_header_offset"]:entry["local_header_offset"] + entry["span_bytes"]])
    span[-40] ^= 0x55
    try:
        decode_member_span(bytes(span), entry)
    except (RecipeError, lzma.LZMAError):
        pass
    else:
        raise AssertionError("corrupted LZMA payload was not rejected")
    bad = dict(entry, crc32=(entry["crc32"] ^ 1))
    good_span = blob[entry["local_header_offset"]:entry["local_header_offset"] + entry["span_bytes"]]
    try:
        decode_member_span(good_span, bad)
    except RecipeError:
        pass
    else:
        raise AssertionError("CRC mismatch was not rejected")
    # 3. hand-built method-14 header around a stdlib raw LZMA1 stream (the
    #    archives omit the end marker; real members exercise that path).
    wav = synthetic_wav(5000, 4, True)
    props = {"id": lzma.FILTER_LZMA1, "dict_size": 1 << 20, "lc": 3, "lp": 0, "pb": 2}
    raw = lzma.compress(wav, format=lzma.FORMAT_RAW, filters=[props])
    header = struct.pack("<BBH", 9, 20, 5) + bytes([2 * 45 + 0 * 9 + 3]) + struct.pack("<I", 1 << 20)
    assert lzma_decode(header + raw, len(wav), 0x0002) == (wav, 0)
    # No end marker declared (flag bit 1 clear): output stops at the declared
    # size; a small decodable tail past it is tolerated (the flush artifact of
    # real no-end-marker streams), a large one is rejected, and an end marker
    # declared but absent at the declared size is rejected.
    assert lzma_decode(header + raw, len(wav), 0) == (wav, 0)
    assert lzma_decode(header + raw, len(wav) - 1, 0) == (wav[:-1], 1)
    for size, flags in ((len(wav) - MAX_FLUSH_OVERRUN - 1, 0), (len(wav) - 1, 0x0002)):
        try:
            lzma_decode(header + raw, size, flags)
        except RecipeError:
            pass
        else:
            raise AssertionError(f"LZMA overrun not rejected (size={size}, flags={flags})")
    # 4. hand-built ZIP64 central-directory entry (offset > 4 GiB).
    name = b"000000000000000009.WAV"
    extra = struct.pack("<HHQ", 0x0001, 8, 5_000_000_000)
    cd = struct.pack("<IHHHHHHIIIHHHHHII", 0x02014B50, 63, 63, 0, 14, 0, 0, 0x1234, 100, 200, len(name), len(extra), 0, 0, 0, 0, 0xFFFFFFFF) + name + extra
    parsed = parse_central_directory(cd, 1)[0]
    assert parsed["local_header_offset"] == 5_000_000_000 and parsed["compressed_size"] == 100
    # 5. ZIP64 EOCD parse: [... cd][eocd64 56 B][locator 20 B][eocd 22 B].
    n, cd_size, archive_size = 10000, 1_045_580, 4_600_000_000
    eocd64_pos = archive_size - 22 - 20 - 56
    cd_offset = eocd64_pos - cd_size
    tail = (b"\x00" * (TAIL_BYTES - 98)
            + struct.pack("<IQHHIIQQQQ", 0x06064B50, 44, 45, 45, 0, 0, n, n, cd_size, cd_offset)
            + struct.pack("<IIQI", 0x07064B50, 0, eocd64_pos, 1)
            + struct.pack("<IHHHHIIH", 0x06054B50, 0, 0, n, n, 0xFFFFFFFF, 0xFFFFFFFF, 0))
    parsed_eocd = parse_eocd(tail, archive_size)
    assert parsed_eocd == {"entries": n, "cd_offset": cd_offset, "cd_size": cd_size, "zip64": True}, parsed_eocd
    # and a plain EOCD whose central directory does not abut it is rejected
    try:
        parse_eocd(b"\x00" * 10 + struct.pack("<IHHHHIIH", 0x06054B50, 0, 0, 1, 1, 46, 0, 0), 1000)
    except RecipeError:
        pass
    else:
        raise AssertionError("inconsistent EOCD was not rejected")
    # 6. fmt validation rejects stereo / other rates.
    buf = io.BytesIO()
    with wave.open(buf, "wb") as writer:
        writer.setnchannels(2)
        writer.setsampwidth(2)
        writer.setframerate(250000)
        writer.writeframes(b"\x01\x00" * 200)
    try:
        riff_pcm(buf.getvalue())
    except RecipeError:
        pass
    else:
        raise AssertionError("stereo WAV was not rejected")
    print("selftest ok: zipfile ZIP_LZMA members incl. forced-ZIP64 local header, hand-built method-14 header, end-marker and no-end-marker overrun bounds, ZIP64 CD extra and EOCD, corruption and CRC rejection, fmt rejection")


# --------------------------------------------------------------------------
# discovery (documents how archives.tsv and members.tsv were produced)


def discover(scratch: Path, archives_out: Path, members_out: Path) -> dict:
    listing = json.loads((scratch / "api" / "collection_articles.json").read_text(encoding="utf-8"))
    rows = []
    for item in listing:
        if not ARCHIVE_TITLE_RE.match(item.get("title", "")):
            continue
        meta = json.loads((scratch / "api" / f"article_{item['id']}.json").read_text(encoding="utf-8"))
        if len(meta["files"]) != 1:
            fail(f"article {item['id']} has {len(meta['files'])} files")
        entry = meta["files"][0]
        number = ARCHIVE_TITLE_RE.match(item["title"]).group(1)
        if entry["name"] != f"files{number}.zip":
            fail(f"article {item['id']}: unexpected file {entry['name']}")
        lic = meta.get("license") or {}
        if lic.get("name") != LICENSE_NAME:
            fail(f"article {item['id']}: license {lic}")
        tail = (scratch / "zip_tails" / f"{entry['name']}.tail").read_bytes()
        eocd = parse_eocd(tail, int(entry["size"]))
        cd = (scratch / "central_directories" / f"{entry['name']}.cd").read_bytes()
        if len(cd) != eocd["cd_size"]:
            fail(f"{entry['name']}: central directory size mismatch")
        rows.append({
            "archive": entry["name"], "article_id": item["id"], "file_id": entry["id"], "size_bytes": entry["size"],
            "md5": entry["computed_md5"], "entries": eocd["entries"], "cd_offset": eocd["cd_offset"],
            "cd_size": eocd["cd_size"], "cd_sha256": sha256_bytes(cd), "zip64_eocd": int(eocd["zip64"]),
        })
    rows.sort(key=lambda row: row["archive"])
    write_tsv(archives_out, ARCHIVE_COLUMNS, rows)
    archives = load_archives(archives_out)
    cds = load_central_directories(scratch / "central_directories", archives)
    fileinfo = load_fileinfo(scratch / FILEINFO["name"])
    selected, stats = select_members(archives, cds, fileinfo)
    write_tsv(members_out, MEMBER_COLUMNS, selected)
    return {
        "archives": len(archives), "selected": len(selected), **stats,
        "member_span_bytes": sum(row["span_bytes"] for row in selected),
        "uncompressed_bytes": sum(row["uncompressed_size"] for row in selected),
        "fileinfo_sha256": sha256_file(scratch / FILEINFO["name"]),
        "cd_bytes": sum(row["cd_size"] for row in archives),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("discover")
    p.add_argument("--scratch", type=Path, required=True)
    p.add_argument("--archives-out", type=Path, required=True)
    p.add_argument("--members-out", type=Path, required=True)
    for name in ("check-metadata", "check-members", "check-downloads"):
        p = sub.add_parser(name)
        p.add_argument("--download-dir", type=Path, required=True)
    p = sub.add_parser("plan-members")
    p.add_argument("--download-dir", type=Path, required=True)
    p.add_argument("--plan", type=Path, required=True)
    p.add_argument("--pending-out", type=Path, required=True)
    p = sub.add_parser("archive-list")
    p.add_argument("--fields", default="archive,article_id,file_id,size_bytes,cd_offset,cd_size")
    p = sub.add_parser("discover-articles", help="print the article ids of the 30 archive articles plus FileInfo.csv")
    p.add_argument("--scratch", type=Path, required=True)
    p = sub.add_parser("discover-files", help="print '<archive> <file id> <size>' from the fetched archive article JSON")
    p.add_argument("--scratch", type=Path, required=True)
    p = sub.add_parser("discover-eocd", help="print '<cd offset> <cd size>' parsed from a fetched archive tail")
    p.add_argument("--tail", type=Path, required=True)
    p.add_argument("--archive-size", type=int, required=True)
    for name in ("build", "verify"):
        p = sub.add_parser(name)
        p.add_argument("--download-dir", type=Path, required=True)
        p.add_argument("--data-root", type=Path, required=True)
        p.add_argument("--index", type=Path, required=True)
        p.add_argument("--stats", type=Path, required=True)
        if name == "verify":
            p.add_argument("--manifest", type=Path, required=True)
    sub.add_parser("selftest")
    args = parser.parse_args()
    try:
        if args.command == "discover":
            result = discover(args.scratch, args.archives_out, args.members_out)
        elif args.command == "check-metadata":
            result = check_metadata(args.download_dir)
        elif args.command == "check-members":
            result = check_members(args.download_dir)
        elif args.command == "check-downloads":
            result = check_downloads(args.download_dir)
        elif args.command == "plan-members":
            pending = plan_members(args.download_dir, args.plan)
            args.pending_out.write_text(f"{pending}\n", encoding="utf-8")
            result = {"pending": pending}
        elif args.command == "archive-list":
            fields = args.fields.split(",")
            for arch in load_archives():
                print(" ".join(str(int(arch[f]) if isinstance(arch[f], bool) else arch[f]) for f in fields))
            return 0
        elif args.command == "discover-articles":
            listing = json.loads((args.scratch / "api" / "collection_articles.json").read_text(encoding="utf-8"))
            ids = [item["id"] for item in listing if ARCHIVE_TITLE_RE.match(item.get("title", ""))]
            if len(ids) != 30:
                fail(f"collection lists {len(ids)} archive articles, expected 30")
            for article_id in sorted(ids) + [FILEINFO["article_id"]]:
                print(article_id)
            return 0
        elif args.command == "discover-files":
            listing = json.loads((args.scratch / "api" / "collection_articles.json").read_text(encoding="utf-8"))
            for item in sorted(listing, key=lambda item: item["title"]):
                if ARCHIVE_TITLE_RE.match(item.get("title", "")):
                    meta = json.loads((args.scratch / "api" / f"article_{item['id']}.json").read_text(encoding="utf-8"))
                    for entry in meta["files"]:
                        print(entry["name"], entry["id"], entry["size"])
            return 0
        elif args.command == "discover-eocd":
            eocd = parse_eocd(args.tail.read_bytes(), args.archive_size)
            print(eocd["cd_offset"], eocd["cd_size"])
            return 0
        elif args.command == "build":
            selftest()
            result = build(args.download_dir, args.data_root, args.index, args.stats)
            result = {k: v for k, v in result.items() if k not in ("excluded",)} | {"excluded": len(result["excluded"])}
        elif args.command == "verify":
            selftest()
            result = verify(args.download_dir, args.data_root, args.index, args.stats, args.manifest)
        else:
            selftest()
            return 0
    except RecipeError as exc:
        print(f"FATAL: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
