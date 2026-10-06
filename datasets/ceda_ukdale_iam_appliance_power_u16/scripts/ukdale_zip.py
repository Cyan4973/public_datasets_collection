#!/usr/bin/env python3
"""Range-only ZIP helpers for the UK-DALE IAM recipe (pure standard library).

Subcommands
-----------
resolve   Parse the ZIP (ZIP64-aware) end records and central directory from a
          tail byte range of ukdale.zip, inflate the in-archive metadata YAML
          members that live inside that tail, select every EcoManagerTxPlug
          (individual appliance monitor) channel of houses 2-5, and write the
          member table. With --pinned, the live selection must equal the pinned
          table byte for byte.
member    Validate one fetched member byte range: HTTP 206 + exact
          Content-Range + pinned ETag/Last-Modified, ZIP local header, exact
          DEFLATE boundary, CRC32, uncompressed size, and a cheap text screen
          (only ASCII digits, spaces and newlines; one space per line on
          average; newline-terminated).

No network access happens here; download.sh fetches with curl.
"""
from __future__ import annotations

import argparse
import csv
import re
import struct
import sys
import zlib
from pathlib import Path

HOUSES = (2, 3, 4, 5)
IAM_MODEL = "EcoManagerTxPlug"
METADATA_MEMBERS = [f"metadata/building{house}.yaml" for house in HOUSES] + [
    "metadata/meter_devices.yaml",
    "metadata/dataset.yaml",
]
LICENSE_TEXT = "Creative Commons Attribution 4.0 International (CC BY 4.0)"
MEMBER_FIELDS = [
    "house",
    "channel",
    "member",
    "appliance",
    "range_start",
    "range_end",
    "range_bytes",
    "compressed_size",
    "uncompressed_size",
    "crc32",
]
U32 = 0xFFFFFFFF
U16 = 0xFFFF


def fail(message: str) -> None:
    raise SystemExit(f"FATAL: {message}")


# --------------------------------------------------------------------------
# HTTP header checks
# --------------------------------------------------------------------------
def final_response(headers_path: Path) -> tuple[int, dict[str, str]]:
    text = headers_path.read_text(encoding="iso-8859-1")
    parts = [part for part in re.split(r"(?=^HTTP/)", text, flags=re.MULTILINE) if part.strip()]
    if not parts:
        fail(f"no HTTP response in {headers_path}")
    final = parts[-1]
    lines = final.splitlines()
    match = re.match(r"^HTTP/\S+\s+(\d+)", lines[0])
    status = int(match.group(1)) if match else 0
    headers: dict[str, str] = {}
    for line in lines[1:]:
        if ":" in line:
            key, value = line.split(":", 1)
            headers[key.strip().lower()] = value.strip()
    return status, headers


def check_range_headers(
    headers_path: Path, start: int, end: int, total: int, etag: str, last_modified: str
) -> None:
    status, headers = final_response(headers_path)
    if status != 206:
        fail(f"expected HTTP 206 for bytes {start}-{end}, got {status} ({headers_path.name})")
    match = re.fullmatch(r"bytes\s+(\d+)-(\d+)/(\d+)", headers.get("content-range", ""))
    if not match or tuple(map(int, match.groups())) != (start, end, total):
        fail(f"unexpected Content-Range {headers.get('content-range')!r}; want bytes {start}-{end}/{total}")
    if headers.get("etag") != etag:
        fail(f"ETag changed: got {headers.get('etag')!r}, pinned {etag!r}")
    if last_modified and headers.get("last-modified") != last_modified:
        fail(f"Last-Modified changed: got {headers.get('last-modified')!r}, pinned {last_modified!r}")


# --------------------------------------------------------------------------
# ZIP structures
# --------------------------------------------------------------------------
def zip64_extra(extra: bytes, want: list[str], values: dict[str, int]) -> None:
    """Fill sentinel fields from a ZIP64 extended-information extra field."""
    cursor = 0
    while cursor + 4 <= len(extra):
        header_id, size = struct.unpack_from("<HH", extra, cursor)
        body = extra[cursor + 4 : cursor + 4 + size]
        cursor += 4 + size
        if header_id != 0x0001:
            continue
        offset = 0
        for key in want:
            if offset + 8 > len(body):
                fail(f"truncated ZIP64 extra field for {key}")
            values[key] = struct.unpack_from("<Q", body, offset)[0]
            offset += 8
        return
    if want:
        fail(f"ZIP64 sentinel present but no ZIP64 extra field for {want}")


def parse_central_directory(tail: bytes, tail_start: int, archive_size: int) -> tuple[list[dict], int]:
    if tail_start + len(tail) != archive_size:
        fail("tail bytes do not end at the archive end")
    eocd = tail.rfind(b"PK\x05\x06")
    if eocd < 0 or eocd + 22 > len(tail):
        fail("end-of-central-directory record not found")
    (_, disk, cd_disk, disk_entries, entries, cd_size, cd_offset, comment_length) = struct.unpack_from(
        "<4s4H2IH", tail, eocd
    )
    if eocd + 22 + comment_length != len(tail):
        fail("EOCD comment does not end at the archive end")
    if disk != 0 or cd_disk != 0 or disk_entries != entries:
        fail("multi-disk ZIP archives are unsupported")
    cd_end_abs = tail_start + eocd
    locator = eocd - 20
    if locator >= 0 and tail[locator : locator + 4] == b"PK\x06\x07":
        _, z64_disk, z64_offset, total_disks = struct.unpack_from("<4sIQI", tail, locator)
        if z64_disk != 0 or total_disks != 1:
            fail("unexpected ZIP64 locator disk fields")
        rel = z64_offset - tail_start
        if rel < 0 or tail[rel : rel + 4] != b"PK\x06\x06":
            fail("ZIP64 end-of-central-directory record not inside the tail")
        fields = struct.unpack_from("<4sQHHIIQQQQ", tail, rel)
        z64_entries, z64_cd_size, z64_cd_offset = fields[7], fields[8], fields[9]
        if fields[4] != 0 or fields[5] != 0 or fields[6] != z64_entries:
            fail("multi-disk ZIP64 archives are unsupported")
        for classic, wide, sentinel in ((entries, z64_entries, U16), (cd_size, z64_cd_size, U32), (cd_offset, z64_cd_offset, U32)):
            if classic != sentinel and classic != wide:
                fail("classic and ZIP64 end records disagree")
        entries, cd_size, cd_offset = z64_entries, z64_cd_size, z64_cd_offset
        cd_end_abs = z64_offset
    elif U32 in (cd_size, cd_offset) or entries == U16:
        fail("ZIP64 sentinels present without a ZIP64 locator")
    if cd_offset + cd_size != cd_end_abs:
        fail("central directory is not contiguous with the end records")
    cursor = cd_offset - tail_start
    if cursor < 0:
        fail(f"central directory starts before the tail; fetch at least {archive_size - cd_offset} tail bytes")
    end = cursor + cd_size
    members: list[dict] = []
    while cursor < end:
        if tail[cursor : cursor + 4] != b"PK\x01\x02":
            fail(f"bad central-directory signature at archive offset {tail_start + cursor}")
        (_, _, _, flags, method, _, _, crc, csz, usz, name_len, extra_len, comment_len, disk_start, _, _, lho) = (
            struct.unpack_from("<4s6H3I5H2I", tail, cursor)
        )
        name_raw = tail[cursor + 46 : cursor + 46 + name_len]
        extra = tail[cursor + 46 + name_len : cursor + 46 + name_len + extra_len]
        name = name_raw.decode("utf-8" if flags & 0x800 else "cp437")
        values = {"usz": usz, "csz": csz, "lho": lho}
        want = [key for key, value in (("usz", usz), ("csz", csz), ("lho", lho)) if value == U32]
        zip64_extra(extra, want, values)
        if disk_start not in (0, U16):
            fail(f"member {name} starts on another disk")
        members.append(
            {
                "name": name,
                "flags": flags,
                "method": method,
                "crc32": crc,
                "compressed_size": values["csz"],
                "uncompressed_size": values["usz"],
                "local_header_offset": values["lho"],
            }
        )
        cursor += 46 + name_len + extra_len + comment_len
    if cursor != end or len(members) != entries:
        fail(f"central directory count mismatch: parsed {len(members)}, declared {entries}")
    ordered = sorted(members, key=lambda item: item["local_header_offset"])
    for item, following in zip(ordered, ordered[1:] + [None]):
        item["next_offset"] = following["local_header_offset"] if following else cd_offset
        if item["next_offset"] <= item["local_header_offset"]:
            fail("overlapping ZIP members")
    return members, cd_offset


def local_member_data(blob: bytes, name: str, method: int, crc: int, csz: int, usz: int) -> memoryview:
    """Validate a local header + data range and return the compressed data view."""
    if len(blob) < 30 or blob[:4] != b"PK\x03\x04":
        fail(f"{name}: missing local file header signature")
    (_, _, flags, local_method, _, _, local_crc, local_csz, local_usz, name_len, extra_len) = struct.unpack_from(
        "<4s5H3I2H", blob, 0
    )
    local_name = blob[30 : 30 + name_len].decode("utf-8" if flags & 0x800 else "cp437")
    if local_name != name:
        fail(f"local header name {local_name!r} != {name!r}")
    if flags & 0x1 or flags & 0x8:
        fail(f"{name}: encrypted or data-descriptor members are unsupported (flags={flags:#x})")
    values = {"usz": local_usz, "csz": local_csz}
    want = [key for key, value in (("usz", local_usz), ("csz", local_csz)) if value == U32]
    zip64_extra(blob[30 + name_len : 30 + name_len + extra_len], want, values)
    if (local_method, local_crc, values["csz"], values["usz"]) != (method, crc, csz, usz):
        fail(f"{name}: local header disagrees with the central directory")
    data_offset = 30 + name_len + extra_len
    if data_offset + csz != len(blob):
        fail(f"{name}: member data does not end exactly at the next member ({data_offset}+{csz} != {len(blob)})")
    return memoryview(blob)[data_offset:]


def inflate_checked(data: memoryview, name: str, method: int, crc: int, usz: int) -> bytes:
    if method == 0:
        out = bytes(data)
    elif method == 8:
        decompressor = zlib.decompressobj(-zlib.MAX_WBITS)
        out = decompressor.decompress(data) + decompressor.flush()
        if not decompressor.eof or decompressor.unused_data:
            fail(f"{name}: DEFLATE stream does not end at the member boundary")
    else:
        fail(f"{name}: unsupported compression method {method}")
    if len(out) != usz:
        fail(f"{name}: inflated {len(out)} bytes, central directory says {usz}")
    if zlib.crc32(out) & U32 != crc:
        fail(f"{name}: CRC32 mismatch")
    return out


# --------------------------------------------------------------------------
# Minimal parsers for the fixed nilm_metadata YAML layout
# --------------------------------------------------------------------------
def top_level_block(text: str, key: str) -> list[str]:
    lines = text.split("\n")
    out: list[str] = []
    inside = False
    for line in lines:
        if line.startswith(f"{key}:"):
            inside = True
            continue
        if inside and line and not line.startswith((" ", "-")):
            break
        if inside:
            out.append(line)
    return out


def parse_elec_meters(text: str) -> dict[int, dict[str, str]]:
    meters: dict[int, dict[str, str]] = {}
    current = None
    for line in top_level_block(text, "elec_meters"):
        match = re.match(r"^  (\d+):\s*$", line)
        if match:
            current = int(match.group(1))
            meters[current] = {}
            continue
        match = re.match(r"^    (\w+):\s*(.*)$", line)
        if match and current is not None:
            meters[current][match.group(1)] = match.group(2).strip()
    if not meters:
        fail("no elec_meters parsed")
    return meters


def parse_appliances(text: str) -> dict[int, list[str]]:
    names: dict[int, list[str]] = {}
    items: list[dict[str, str]] = []
    for line in top_level_block(text, "appliances"):
        if line.startswith("- "):
            items.append({})
            line = "  " + line[2:]
        match = re.match(r"^  (\w+):\s*(.*)$", line)
        if match and items:
            items[-1][match.group(1)] = match.group(2).strip()
    for item in items:
        meters = re.fullmatch(r"\[([0-9, ]+)\]", item.get("meters", ""))
        if not meters:
            continue
        for meter in (int(value) for value in meters.group(1).split(",")):
            label = item.get("original_name", "")
            if label and label not in names.setdefault(meter, []):
                names[meter].append(label)
    return names


def device_block(text: str, model: str) -> str:
    match = re.search(rf"^{re.escape(model)}:\n((?:[ \t].*\n|\n)*)", text, flags=re.MULTILINE)
    if not match:
        fail(f"meter_devices.yaml has no {model} block")
    return match.group(1)


# --------------------------------------------------------------------------
# Subcommands
# --------------------------------------------------------------------------
def resolve(args: argparse.Namespace) -> int:
    tail = args.tail.read_bytes()
    tail_start = args.archive_bytes - len(tail)
    check_range_headers(args.headers, tail_start, args.archive_bytes - 1, args.archive_bytes, args.etag, args.last_modified)
    members, cd_offset = parse_central_directory(tail, tail_start, args.archive_bytes)
    by_name = {item["name"]: item for item in members}
    print(f"central_directory=ok entries={len(members)} cd_offset={cd_offset}")

    args.metadata_out.mkdir(parents=True, exist_ok=True)
    texts: dict[str, str] = {}
    for name in METADATA_MEMBERS:
        item = by_name.get(name)
        if item is None:
            fail(f"archive lacks {name}")
        start = item["local_header_offset"] - tail_start
        stop = item["next_offset"] - tail_start
        if start < 0:
            fail(f"{name} is outside the fetched tail")
        data = local_member_data(
            tail[start:stop], name, item["method"], item["crc32"], item["compressed_size"], item["uncompressed_size"]
        )
        raw = inflate_checked(data, name, item["method"], item["crc32"], item["uncompressed_size"])
        texts[name] = raw.decode("utf-8")
        (args.metadata_out / Path(name).name).write_bytes(raw)

    if LICENSE_TEXT not in texts["metadata/dataset.yaml"]:
        fail("in-archive dataset.yaml no longer declares CC BY 4.0")
    block = device_block(texts["metadata/meter_devices.yaml"], IAM_MODEL)
    if "physical_quantity: power, type: active" not in block or "upper_limit: 3300" not in block:
        fail("meter_devices.yaml EcoManagerTxPlug is no longer active power 0-3300 W")
    if "sample_period: 6" not in block:
        fail("meter_devices.yaml EcoManagerTxPlug sample_period changed")

    rows: list[dict[str, str]] = []
    for house in HOUSES:
        text = texts[f"metadata/building{house}.yaml"]
        meters = parse_elec_meters(text)
        labels = parse_appliances(text)
        for channel in sorted(meters):
            meter = meters[channel]
            if meter.get("device_model") != IAM_MODEL:
                continue
            member = f"house_{house}/channel_{channel}.dat"
            if meter.get("data_location") != member:
                fail(f"house {house} meter {channel}: unexpected data_location {meter.get('data_location')!r}")
            item = by_name.get(member)
            if item is None:
                fail(f"archive lacks {member}")
            if item["method"] != 8:
                fail(f"{member}: expected DEFLATE (method 8), got {item['method']}")
            rows.append(
                {
                    "house": str(house),
                    "channel": str(channel),
                    "member": member,
                    "appliance": "+".join(labels.get(channel, [])) or "unlabelled",
                    "range_start": str(item["local_header_offset"]),
                    "range_end": str(item["next_offset"] - 1),
                    "range_bytes": str(item["next_offset"] - item["local_header_offset"]),
                    "compressed_size": str(item["compressed_size"]),
                    "uncompressed_size": str(item["uncompressed_size"]),
                    "crc32": f"{item['crc32']:08x}",
                }
            )
    if not rows:
        fail("no EcoManagerTxPlug channels selected")

    args.members_out.parent.mkdir(parents=True, exist_ok=True)
    with args.members_out.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=MEMBER_FIELDS, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    total_range = sum(int(row["range_bytes"]) for row in rows)
    total_text = sum(int(row["uncompressed_size"]) for row in rows)
    print(f"selection=ok members={len(rows)} range_bytes={total_range} inflated_text_bytes={total_text}")

    if args.pinned:
        if args.pinned.read_bytes() != args.members_out.read_bytes():
            fail(f"live selection differs from pinned {args.pinned}; rerun discover.sh and review")
        print(f"pinned_selection=match file={args.pinned}")
    return 0


def member(args: argparse.Namespace) -> int:
    with args.pinned.open(encoding="utf-8", newline="") as handle:
        rows = {row["member"]: row for row in csv.DictReader(handle, delimiter="\t")}
    row = rows.get(args.member)
    if row is None:
        fail(f"{args.member} is not in {args.pinned}")
    start, end = int(row["range_start"]), int(row["range_end"])
    check_range_headers(args.headers, start, end, args.archive_bytes, args.etag, args.last_modified)
    blob = args.range_file.read_bytes()
    if len(blob) != int(row["range_bytes"]) or len(blob) != end - start + 1:
        fail(f"{args.member}: fetched {len(blob)} bytes, want {row['range_bytes']}")
    method = 8
    crc = int(row["crc32"], 16)
    usz = int(row["uncompressed_size"])
    data = local_member_data(blob, args.member, method, crc, int(row["compressed_size"]), usz)
    text = inflate_checked(data, args.member, method, crc, usz)
    if not text.endswith(b"\n") or text.startswith((b"\n", b" ")):
        fail(f"{args.member}: text is not newline-terminated '<ts> <watts>' lines")
    if text.translate(None, b"0123456789 \n"):
        fail(f"{args.member}: text contains bytes other than ASCII digits, space and newline")
    lines = text.count(b"\n")
    if text.count(b" ") != lines or b"\n\n" in text or b" \n" in text or b"\n " in text or b"  " in text:
        fail(f"{args.member}: text is not one '<ts> <watts>' pair per line")
    print(f"member=ok name={args.member} range_bytes={len(blob)} text_bytes={usz} lines={lines} crc32={row['crc32']}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--headers", type=Path, required=True)
    common.add_argument("--archive-bytes", type=int, required=True)
    common.add_argument("--etag", required=True)
    common.add_argument("--last-modified", default="")
    p_resolve = sub.add_parser("resolve", parents=[common])
    p_resolve.add_argument("--tail", type=Path, required=True)
    p_resolve.add_argument("--members-out", type=Path, required=True)
    p_resolve.add_argument("--metadata-out", type=Path, required=True)
    p_resolve.add_argument("--pinned", type=Path)
    p_member = sub.add_parser("member", parents=[common])
    p_member.add_argument("--range-file", type=Path, required=True)
    p_member.add_argument("--member", required=True)
    p_member.add_argument("--pinned", type=Path, required=True)
    args = parser.parse_args()
    return resolve(args) if args.command == "resolve" else member(args)


if __name__ == "__main__":
    sys.exit(main())
