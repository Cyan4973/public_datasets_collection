#!/usr/bin/env python3
"""ZIP / Zenodo helpers for zenodo_offaxis_dhm_holograms_u8 (standard library only).

Subcommands (all purely local; curl does the network I/O in the shell scripts):

  check-record  RECORD_JSON VIDEOS_TSV
      Validate Zenodo record identity, CC0 license and every pinned zip
      (size + MD5) listed in VIDEOS_TSV; also check the excluded 520 nm zip
      is still listed (so the exclusion stays meaningful).
  check-readme  README_MD
      Check the record README states the 405 nm default and the 520 nm exception.
  parse-cd      TAIL HEADERS ARCHIVE_SIZE TAIL_START KEY OUT_TSV
      Parse the classic ZIP central directory from a ranged tail, rejecting
      ZIP64, multi-disk archives and non deflate/stored hologram members, and
      write one row per Holograms/NNNNN_holo.tif member (AppleDouble __MACOSX
      entries are ignored). Frame numbers must be contiguous from 0.
  select        MEMBERS_TSV FRAMES_PER_VIDEO
      Print the evenly spaced selection floor((2k+1)*N/(2K)), k=0..K-1.
  check-pins    MEMBERS_TSV SELECTED_TSV KEY
      Check every pinned selected frame of KEY matches the live central directory.
  extract       RANGE HEADERS ARCHIVE_SIZE RANGE_START NAME METHOD CSIZE USIZE CRC32 OUT
      Validate a ranged local-file-header + member payload, inflate it, check
      CRC32 and size, check the TIFF layout and write OUT.
"""

from __future__ import annotations

import csv
import hashlib
import html
import json
from pathlib import Path
import re
import struct
import sys
import zlib

sys.path.insert(0, str(Path(__file__).resolve().parent))
import dhm_tiff  # noqa: E402

RECORD_ID = 10632465
EXCLUDED_KEY = "2022.08.02_14-37_AuFlat520.zip"
MEMBER_RE = re.compile(r"([^/]+)/Holograms/(\d{5})_holo\.tif")
MEMBER_FIELDS = (
    "key",
    "frame",
    "name",
    "flags",
    "method",
    "crc32_hex",
    "compressed_size",
    "uncompressed_size",
    "local_header_offset",
    "name_length",
    "next_offset",
)


def read_tsv(path: str | Path) -> list[dict[str, str]]:
    with open(path, encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def final_response(headers_path: str | Path) -> tuple[int, tuple[int, int, int] | None]:
    text = Path(headers_path).read_text(encoding="iso-8859-1")
    parts = [p for p in re.split(r"(?=^HTTP/)", text, flags=re.MULTILINE) if p.strip()]
    # Skip proxy CONNECT preambles ("200 Connection established").
    parts = [p for p in parts if "connection established" not in p.lower().split("\n", 1)[0]]
    if not parts:
        return 0, None
    final = parts[-1]
    status = re.search(r"^HTTP/\S+\s+(\d+)", final, flags=re.MULTILINE)
    cr = re.search(
        r"^Content-Range:\s*bytes\s+(\d+)-(\d+)/(\d+)\s*$", final, flags=re.IGNORECASE | re.MULTILINE
    )
    return (int(status.group(1)) if status else 0), (tuple(map(int, cr.groups())) if cr else None)


def require_range(headers: str, start: int, end: int, total: int) -> None:
    status, cr = final_response(headers)
    if status != 206 or cr != (start, end, total):
        raise SystemExit(f"server did not honor range {start}-{end}/{total}: status={status} content_range={cr}")


def cmd_check_record(record_json: str, videos_tsv: str) -> None:
    record = json.loads(Path(record_json).read_text(encoding="utf-8"))
    if int(record.get("id") or 0) != RECORD_ID:
        raise SystemExit(f"unexpected record id {record.get('id')!r}")
    meta = record.get("metadata") or {}
    title = html.unescape(str(meta.get("title", "")))
    if "unresolved particles" not in title.lower() or "holographic" not in title.lower():
        raise SystemExit(f"record title changed: {title!r}")
    lic = meta.get("license")
    lic_id = str(lic.get("id") if isinstance(lic, dict) else lic or "").lower()
    if lic_id not in {"cc-zero", "cc0-1.0"}:
        raise SystemExit(f"record license changed: {lic!r}")
    access = meta.get("access_right")
    if access not in (None, "open"):
        raise SystemExit(f"record access changed: {access!r}")
    files = {f.get("key"): f for f in record.get("files") or [] if isinstance(f, dict)}
    if EXCLUDED_KEY not in files:
        raise SystemExit("excluded 520 nm zip no longer listed; record layout changed")
    for row in read_tsv(videos_tsv):
        item = files.get(row["key"])
        if item is None:
            raise SystemExit(f"pinned zip missing from record: {row['key']}")
        if int(item.get("size") or 0) != int(row["archive_size"]):
            raise SystemExit(f"zip size changed: {row['key']} {item.get('size')}")
        if str(item.get("checksum") or "").lower() != f"md5:{row['archive_md5']}":
            raise SystemExit(f"zip checksum changed: {row['key']} {item.get('checksum')}")
        if row["key"] == EXCLUDED_KEY or "520" in row["key"]:
            raise SystemExit(f"520 nm video must not be selected: {row['key']}")
    print(f"record_validation=ok record={RECORD_ID} license={lic_id} zips={len(read_tsv(videos_tsv))}")


def cmd_check_readme(readme: str) -> None:
    text = Path(readme).read_text(encoding="utf-8")
    flat = re.sub(r"\s+", " ", text)
    for needle in (
        "Illumination wavelength was 405 nm unless specified to be 520 nm",
        "2048x2048 pixel tiff files",
        "raw holograms",
        "Flat slide 520 nm",
        "2022.08.02 14-37",
    ):
        if needle not in flat:
            raise SystemExit(f"README no longer states: {needle!r}")
    print("readme_validation=ok wavelength_default=405nm exception=2022.08.02_14-37 (520 nm)")


def cmd_parse_cd(tail_path: str, headers: str, archive_size: str, tail_start: str, key: str, out: str) -> None:
    size = int(archive_size)
    start = int(tail_start)
    require_range(headers, start, size - 1, size)
    tail = Path(tail_path).read_bytes()
    if len(tail) != size - start:
        raise SystemExit(f"tail length mismatch {len(tail)} != {size - start}")
    if tail.find(b"PK\x06\x06") >= 0 or tail.find(b"PK\x06\x07") >= 0:
        raise SystemExit(f"{key}: ZIP64 end-of-central-directory records present; refusing")
    eocd = tail.rfind(b"PK\x05\x06")
    if eocd < 0:
        raise SystemExit(f"{key}: EOCD not found in tail")
    _, disk, cd_disk, disk_entries, total, cd_size, cd_offset, comment = struct.unpack_from("<4s4H2IH", tail, eocd)
    if disk or cd_disk or disk_entries != total:
        raise SystemExit(f"{key}: multi-disk ZIP unsupported")
    if 0xFFFF in (disk_entries, total) or 0xFFFFFFFF in (cd_size, cd_offset):
        raise SystemExit(f"{key}: ZIP64 required; refusing")
    if eocd + 22 + comment != len(tail):
        raise SystemExit(f"{key}: EOCD does not end the archive")
    if cd_offset != start or cd_offset + cd_size != start + eocd:
        raise SystemExit(f"{key}: central directory not where pinned (offset {cd_offset}, size {cd_size})")
    entries = []
    p = 0
    for _ in range(total):
        if tail[p : p + 4] != b"PK\x01\x02":
            raise SystemExit(f"{key}: bad central directory entry at {start + p}")
        f = struct.unpack_from("<4s6H3I5H2I", tail, p)
        flags, method, crc, csz, usz = f[3], f[4], f[7], f[8], f[9]
        nl, el, cl, disk_start, lho = f[10], f[11], f[12], f[13], f[16]
        name = tail[p + 46 : p + 46 + nl].decode("utf-8" if flags & 0x800 else "cp437")
        if disk_start != 0 or 0xFFFFFFFF in (csz, usz, lho):
            raise SystemExit(f"{key}: member {name!r} needs ZIP64/multi-disk; refusing")
        entries.append((lho, name, flags, method, crc, csz, usz, nl))
        p += 46 + nl + el + cl
    if p != cd_size:
        raise SystemExit(f"{key}: central directory size mismatch")
    offsets = sorted(e[0] for e in entries) + [cd_offset]
    next_of = {offsets[i]: offsets[i + 1] for i in range(len(offsets) - 1)}
    rows = []
    for lho, name, flags, method, crc, csz, usz, nl in entries:
        if name.startswith("__MACOSX/"):
            continue
        m = MEMBER_RE.fullmatch(name)
        if not m:
            continue
        if method not in (0, 8):
            raise SystemExit(f"{key}: member {name!r} uses compression method {method}; refusing")
        if flags & 0x1:
            raise SystemExit(f"{key}: member {name!r} is encrypted")
        rows.append(
            {
                "key": key,
                "frame": int(m.group(2)),
                "name": name,
                "flags": flags,
                "method": method,
                "crc32_hex": f"{crc:08x}",
                "compressed_size": csz,
                "uncompressed_size": usz,
                "local_header_offset": lho,
                "name_length": nl,
                "next_offset": next_of[lho],
            }
        )
    rows.sort(key=lambda r: r["frame"])
    if not rows or [r["frame"] for r in rows] != list(range(len(rows))):
        raise SystemExit(f"{key}: hologram frames are not contiguous from 00000")
    if len({r["name"].split("/")[0] for r in rows}) != 1:
        raise SystemExit(f"{key}: holograms span multiple top-level folders")
    with open(out, "w", encoding="utf-8", newline="") as handle:
        w = csv.DictWriter(handle, fieldnames=MEMBER_FIELDS, delimiter="\t", lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    print(f"cd_validation=ok key={key} entries={total} holograms={len(rows)} cd_bytes={cd_size}")


def selection(n: int, k: int) -> list[int]:
    if n < k:
        raise SystemExit(f"video has {n} frames < {k}")
    picks = [((2 * i + 1) * n) // (2 * k) for i in range(k)]
    if len(set(picks)) != k:
        raise SystemExit("selection collision")
    return picks


def cmd_select(members_tsv: str, k: str) -> None:
    rows = read_tsv(members_tsv)
    for i in selection(len(rows), int(k)):
        print(rows[i]["frame"])


def cmd_check_pins(members_tsv: str, selected_tsv: str, key: str) -> None:
    live = {int(r["frame"]): r for r in read_tsv(members_tsv)}
    pinned = [r for r in read_tsv(selected_tsv) if r["key"] == key]
    expected = selection(len(live), len(pinned)) if pinned else []
    if [int(r["frame"]) for r in pinned] != expected:
        raise SystemExit(f"{key}: pinned frames {[r['frame'] for r in pinned]} != even selection {expected}")
    for r in pinned:
        l = live[int(r["frame"])]
        for field in ("name", "method", "crc32_hex", "compressed_size", "uncompressed_size", "local_header_offset", "next_offset"):
            if str(l[field]) != str(r[field]):
                raise SystemExit(f"{key} frame {r['frame']}: {field} live={l[field]!r} pinned={r[field]!r}")
    print(f"pin_validation=ok key={key} frames={len(pinned)} of {len(live)}")


def cmd_extract(range_path, headers, archive_size, range_start, name, method, csize, usize, crc_hex, out) -> None:
    payload = Path(range_path).read_bytes()
    start = int(range_start)
    require_range(headers, start, start + len(payload) - 1, int(archive_size))
    method, csize, usize = int(method), int(csize), int(usize)
    crc_expected = int(crc_hex, 16)
    if payload[:4] != b"PK\x03\x04":
        raise SystemExit(f"{name}: range does not start with a local file header")
    _, _, flags, lmethod, _, _, _, _, _, nl, el = struct.unpack_from("<4s5H3I2H", payload, 0)
    lname = payload[30 : 30 + nl].decode("utf-8" if flags & 0x800 else "cp437")
    if lname != name or lmethod != method:
        raise SystemExit(f"{name}: local header mismatch name={lname!r} method={lmethod}")
    data_start = 30 + nl + el
    if data_start + csize > len(payload):
        raise SystemExit(f"{name}: range too short for member data")
    data = payload[data_start : data_start + csize]
    if method == 8:
        d = zlib.decompressobj(-zlib.MAX_WBITS)
        tif = d.decompress(data) + d.flush()
        if not d.eof or d.unused_data:
            raise SystemExit(f"{name}: deflate stream does not end at the member boundary")
    elif method == 0:
        tif = data
    else:
        raise SystemExit(f"{name}: unsupported method {method}")
    if len(tif) != usize or zlib.crc32(tif) & 0xFFFFFFFF != crc_expected:
        raise SystemExit(f"{name}: inflated size/CRC32 mismatch ({len(tif)}, {zlib.crc32(tif):08x})")
    try:
        dhm_tiff.check_layout(dhm_tiff.parse_ifd(tif))
    except dhm_tiff.TiffFormatError as exc:
        raise SystemExit(f"{name}: TIFF layout rejected: {exc}")
    Path(out).write_bytes(tif)
    print(f"member_validation=ok name={name} bytes={usize} crc32={crc_hex} sha256={hashlib.sha256(tif).hexdigest()}")


def main(argv: list[str]) -> None:
    if not argv:
        raise SystemExit(__doc__)
    cmd, args = argv[0], argv[1:]
    table = {
        "check-record": cmd_check_record,
        "check-readme": cmd_check_readme,
        "parse-cd": cmd_parse_cd,
        "select": cmd_select,
        "check-pins": cmd_check_pins,
        "extract": cmd_extract,
    }
    if cmd not in table:
        raise SystemExit(f"unknown subcommand {cmd}")
    table[cmd](*args)


if __name__ == "__main__":
    main(sys.argv[1:])
