#!/usr/bin/env python3
"""Build-side decoder for the NIH ChestX-ray14 8-bit radiograph recipe.

Pure standard library. For each pinned tarball prefix: inflate the gzip stream
as far as the prefix reaches (zlib.decompressobj(31)), walk the POSIX ustar
headers (checksum-verified), keep only tar members whose data lies wholly
inside the inflated prefix, and decode each PNG with a strict decoder
(chunk CRCs, IDAT inflate, scanline unfilter for filter types 0-4). Images
whose IHDR is not 1024x1024, bit depth 8, colour type 0, non-interlaced are
skipped and logged, never converted. One raw uint8 sample per kept image.

Usage:
  nih_decode.py check-prefix <prefix.tar.gz>   (download-time validation)
  nih_decode.py build <data_root>
"""
from __future__ import annotations

import collections
import hashlib
import json
import re
import shutil
import struct
import sys
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import nih_pins as pins  # noqa: E402

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


class DecodeError(ValueError):
    pass


# --------------------------------------------------------------------- tar


def inflate_prefix(data: bytes) -> tuple[bytes, bool]:
    """Inflate a gzip prefix as far as it goes; returns (bytes, stream_ended)."""
    if len(data) < 18 or data[:3] != b"\x1f\x8b\x08":
        raise DecodeError("not a gzip (deflate) stream: bad magic")
    inflater = zlib.decompressobj(31)
    out = inflater.decompress(data)
    if inflater.eof and inflater.unused_data.strip(b"\x00"):
        raise DecodeError("multi-member gzip or trailing data inside the prefix")
    return out, inflater.eof


def _octal(field: bytes) -> int:
    text = field.replace(b"\x00", b" ").strip()
    if not text:
        return 0
    if not re.fullmatch(rb"[0-7]+", text):
        raise DecodeError(f"non-octal tar header field {field!r}")
    return int(text, 8)


def walk_tar(buf: bytes) -> tuple[list[dict], dict]:
    """Walk ustar headers; return whole regular-file members plus a summary."""
    members: list[dict] = []
    pos = 0
    partial = None
    directories = 0
    end_marker = False
    while pos + 512 <= len(buf):
        header = buf[pos : pos + 512]
        if header == b"\x00" * 512:
            end_marker = True
            break
        stored_sum = _octal(header[148:156])
        computed = sum(header[:148]) + 8 * 32 + sum(header[156:])
        if stored_sum != computed:
            raise DecodeError(f"tar header checksum mismatch at offset {pos}")
        if header[257:262] != b"ustar":
            raise DecodeError(f"tar header at {pos} is not ustar")
        name = header[:100].split(b"\x00", 1)[0].decode("utf-8")
        prefix = header[345:500].split(b"\x00", 1)[0].decode("utf-8")
        if prefix:
            name = f"{prefix}/{name}"
        size = _octal(header[124:136])
        typeflag = header[156:157]
        data_start = pos + 512
        data_end = data_start + size
        if typeflag == b"5":
            directories += 1
        elif typeflag in (b"0", b"\x00"):
            if data_end <= len(buf):
                members.append({"name": name, "size": size, "data_offset": data_start, "data": buf[data_start:data_end]})
            else:
                partial = {"name": name, "size": size, "have": len(buf) - data_start}
                break
        else:
            raise DecodeError(f"unsupported tar typeflag {typeflag!r} for {name!r}")
        pos = data_start + ((size + 511) // 512) * 512
    return members, {"directories": directories, "partial_member": partial, "end_marker": end_marker}


def read_prefix_members(path: Path) -> tuple[list[dict], dict]:
    data = path.read_bytes()
    inflated, ended = inflate_prefix(data)
    if ended:
        raise DecodeError(f"{path.name}: gzip stream ended inside the prefix (unexpected for a multi-GB tarball)")
    members, summary = walk_tar(inflated)
    summary.update({"prefix_bytes": len(data), "inflated_bytes": len(inflated)})
    for member in members:
        if not re.fullmatch(pins.MEMBER_NAME_PATTERN, member["name"]):
            raise DecodeError(f"{path.name}: unexpected member name {member['name']!r}")
    return members, summary


# --------------------------------------------------------------------- PNG


def png_ihdr(png: bytes) -> tuple[int, int, int, int, int, int, int]:
    if png[:8] != PNG_SIGNATURE:
        raise DecodeError("missing PNG signature")
    if len(png) < 33:
        raise DecodeError("truncated PNG")
    (length,) = struct.unpack_from(">I", png, 8)
    if png[12:16] != b"IHDR" or length != 13:
        raise DecodeError("first chunk is not a 13-byte IHDR")
    body = png[16:29]
    (crc,) = struct.unpack_from(">I", png, 29)
    if zlib.crc32(b"IHDR" + body) & 0xFFFFFFFF != crc:
        raise DecodeError("IHDR CRC mismatch")
    return struct.unpack(">IIBBBBB", body)


def qualifies(ihdr: tuple) -> bool:
    return tuple(ihdr) == (pins.WIDTH, pins.HEIGHT, 8, 0, 0, 0, 0)


def unfilter(raw: bytes, width: int, height: int) -> tuple[bytes, list[int]]:
    """Undo PNG scanline filters for 1 byte per pixel."""
    stride = width + 1
    if len(raw) != stride * height:
        raise DecodeError(f"inflated image data has {len(raw)} bytes, expected {stride * height}")
    out = bytearray(width * height)
    prev = bytearray(width)
    filter_counts = [0, 0, 0, 0, 0]
    for y in range(height):
        start = y * stride
        ftype = raw[start]
        row = bytearray(raw[start + 1 : start + stride])
        if ftype == 0:
            pass
        elif ftype == 1:
            for i in range(1, width):
                row[i] = (row[i] + row[i - 1]) & 255
        elif ftype == 2:
            for i in range(width):
                row[i] = (row[i] + prev[i]) & 255
        elif ftype == 3:
            row[0] = (row[0] + (prev[0] >> 1)) & 255
            for i in range(1, width):
                row[i] = (row[i] + ((row[i - 1] + prev[i]) >> 1)) & 255
        elif ftype == 4:
            a = (row[0] + prev[0]) & 255
            row[0] = a
            for i in range(1, width):
                b = prev[i]
                c = prev[i - 1]
                p = a + b - c
                pa = abs(p - a)
                pb = abs(p - b)
                pc = abs(p - c)
                if pa <= pb and pa <= pc:
                    predictor = a
                elif pb <= pc:
                    predictor = b
                else:
                    predictor = c
                a = (row[i] + predictor) & 255
                row[i] = a
        else:
            raise DecodeError(f"row {y}: invalid PNG filter type {ftype}")
        filter_counts[ftype] += 1
        out[y * width : (y + 1) * width] = row
        prev = row
    return bytes(out), filter_counts


def decode_png(png: bytes, width: int, height: int) -> tuple[bytes, dict]:
    """Strict decoder: 8-bit grayscale, non-interlaced, exact dimensions."""
    ihdr = png_ihdr(png)
    if tuple(ihdr) != (width, height, 8, 0, 0, 0, 0):
        raise DecodeError(f"IHDR {ihdr} is not {width}x{height} 8-bit grayscale non-interlaced")
    pos = 33
    idat = bytearray()
    idat_chunks = 0
    idat_closed = False
    ancillary: collections.Counter = collections.Counter()
    while True:
        if pos + 12 > len(png):
            raise DecodeError("truncated PNG chunk stream (no IEND)")
        (length,) = struct.unpack_from(">I", png, pos)
        ctype = png[pos + 4 : pos + 8]
        if pos + 12 + length > len(png):
            raise DecodeError(f"chunk {ctype!r} overruns the PNG")
        body = png[pos + 8 : pos + 8 + length]
        (crc,) = struct.unpack_from(">I", png, pos + 8 + length)
        if zlib.crc32(ctype + body) & 0xFFFFFFFF != crc:
            raise DecodeError(f"chunk {ctype!r} CRC mismatch")
        pos += 12 + length
        if ctype == b"IDAT":
            if idat_closed:
                raise DecodeError("IDAT chunks are not consecutive")
            idat += body
            idat_chunks += 1
        elif ctype == b"IEND":
            if length != 0:
                raise DecodeError("IEND has a body")
            break
        elif ctype in (b"tRNS", b"PLTE", b"IHDR"):
            raise DecodeError(f"{ctype!r} chunk not allowed here")
        elif ctype[0:1].isupper():
            raise DecodeError(f"unexpected critical chunk {ctype!r}")
        else:
            ancillary[ctype.decode("latin-1")] += 1
            if idat_chunks:
                idat_closed = True
    if pos != len(png):
        raise DecodeError(f"{len(png) - pos} bytes after IEND")
    if not idat_chunks:
        raise DecodeError("no IDAT chunk")
    inflater = zlib.decompressobj()
    raw = inflater.decompress(bytes(idat)) + inflater.flush()
    if not inflater.eof or inflater.unused_data:
        raise DecodeError("IDAT zlib stream is incomplete or has trailing data")
    pixels, filter_counts = unfilter(raw, width, height)
    return pixels, {"idat_chunks": idat_chunks, "ancillary": dict(ancillary), "filter_rows": filter_counts}


# ------------------------------------------------------------------- build


def image_stats(pixels: bytes) -> dict:
    histogram = [0] * 256
    for value, count in collections.Counter(pixels).items():
        histogram[value] = count
    present = [value for value in range(256) if histogram[value]]
    return {
        "min_value": present[0],
        "max_value": present[-1],
        "distinct_values": len(present),
        "modal_fraction": round(max(histogram) / len(pixels), 6),
        "zero_fraction": round(histogram[0] / len(pixels), 6),
        "mean_value": round(sum(value * histogram[value] for value in present) / len(pixels), 6),
    }


def check_degenerate(name: str, stats: dict) -> None:
    if stats["min_value"] == stats["max_value"]:
        raise DecodeError(f"{name}: constant image")
    if stats["distinct_values"] < pins.MIN_DISTINCT_VALUES:
        raise DecodeError(f"{name}: only {stats['distinct_values']} distinct values")
    if stats["modal_fraction"] > pins.MAX_MODAL_FRACTION:
        raise DecodeError(f"{name}: modal value covers {stats['modal_fraction']:.3f} of the image")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        while block := fh.read(8 << 20):
            digest.update(block)
    return digest.hexdigest()


def check_prefix(path: Path) -> None:
    tarball = next((t for t in pins.TARBALLS if pins.prefix_name(t[0]) == path.name), None)
    if tarball is None:
        raise DecodeError(f"{path.name}: not a pinned prefix name")
    if path.stat().st_size != pins.PREFIX_BYTES:
        raise DecodeError(f"{path.name}: {path.stat().st_size} bytes, expected {pins.PREFIX_BYTES}")
    members, summary = read_prefix_members(path)
    if len(members) < pins.MIN_MEMBERS_PER_PREFIX:
        raise DecodeError(f"{path.name}: only {len(members)} whole tar members")
    kinds: collections.Counter = collections.Counter()
    for member in members:
        ihdr = png_ihdr(member["data"])
        kinds["gray8_1024" if qualifies(ihdr) else f"skip_{ihdr[0]}x{ihdr[1]}_d{ihdr[2]}_c{ihdr[3]}"] += 1
    if kinds["gray8_1024"] < pins.MIN_MEMBERS_PER_PREFIX:
        raise DecodeError(f"{path.name}: only {kinds['gray8_1024']} 8-bit grayscale 1024x1024 PNG members")
    print(
        f"prefix_validation=ok file={path.name} inflated={summary['inflated_bytes']} "
        f"whole_members={len(members)} kinds={dict(kinds)} "
        f"partial={summary['partial_member']['name'] if summary['partial_member'] else None}"
    )


def build(data_root: Path) -> None:
    dataset_id = pins.DATASET_ID
    download_dir = data_root / "downloads" / dataset_id
    out_dir = data_root / "samples" / dataset_id / pins.SERIES_ID
    index_dir = data_root / "index" / dataset_id
    filtered_dir = data_root / "filtered" / dataset_id
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)
    index_dir.mkdir(parents=True, exist_ok=True)
    filtered_dir.mkdir(parents=True, exist_ok=True)

    rows: list[dict] = []
    skipped: list[dict] = []
    seen: dict[str, str] = {}
    filter_totals = [0, 0, 0, 0, 0]
    ancillary_totals: collections.Counter = collections.Counter()
    per_tarball: dict[str, dict] = {}
    patients: set[str] = set()
    for tarball, _hash, full_size, _md5 in pins.TARBALLS:
        path = download_dir / pins.prefix_name(tarball)
        if path.stat().st_size != pins.PREFIX_BYTES:
            raise DecodeError(f"{path.name}: size {path.stat().st_size} != {pins.PREFIX_BYTES}")
        pinned = pins.PREFIX_SHA256.get(tarball)
        prefix_sha = sha256_file(path)
        if pinned and prefix_sha != pinned:
            raise DecodeError(f"{path.name}: sha256 {prefix_sha} != pinned {pinned}")
        members, summary = read_prefix_members(path)
        kept = 0
        for member in members:
            name = member["name"]
            png = member["data"]
            ihdr = png_ihdr(png)
            if not qualifies(ihdr):
                skipped.append({"tarball": tarball, "member": name, "ihdr": list(ihdr)})
                print(f"skip tarball={tarball} member={name} ihdr={list(ihdr)}")
                continue
            pixels, info = decode_png(png, pins.WIDTH, pins.HEIGHT)
            stats = image_stats(pixels)
            check_degenerate(name, stats)
            digest = hashlib.sha256(pixels).hexdigest()
            if digest in seen:
                raise DecodeError(f"{tarball}:{name}: pixel payload duplicates {seen[digest]}")
            seen[digest] = f"{tarball}:{name}"
            for ftype, count in enumerate(info["filter_rows"]):
                filter_totals[ftype] += count
            ancillary_totals.update(info["ancillary"])
            out_path = out_dir / pins.sample_name(tarball, name)
            if out_path.exists():
                raise DecodeError(f"{out_path.name}: sample name collision")
            out_path.write_bytes(pixels)
            patients.add(name.rsplit("/", 1)[-1].split("_")[0])
            kept += 1
            rows.append(
                {
                    "dataset_id": dataset_id,
                    "series_id": pins.SERIES_ID,
                    "role": "primary",
                    "sample_path": out_path.relative_to(data_root).as_posix(),
                    "numeric_kind": "uint",
                    "bit_width": 8,
                    "endianness": "little",
                    "element_size_bytes": 1,
                    "sample_size_bytes": len(pixels),
                    "value_count": len(pixels),
                    "sample_format": "raw homogeneous uint8 chest radiograph image",
                    "sample_rank": 2,
                    "sample_shape": [pins.HEIGHT, pins.WIDTH],
                    "sample_axes": ["image_row_y", "image_column_x"],
                    "natural_record_kind": "chestxray14_frontal_radiograph_png_image",
                    "source_tarball": tarball,
                    "source_member": name,
                    "source_member_bytes": member["size"],
                    "source_member_tar_offset": member["data_offset"],
                    "sha256": digest,
                    **stats,
                }
            )
        per_tarball[tarball] = {
            "prefix_sha256": prefix_sha,
            "full_tarball_bytes": full_size,
            "inflated_bytes": summary["inflated_bytes"],
            "whole_members": len(members),
            "kept": kept,
            "partial_member_dropped": summary["partial_member"],
        }
        print(f"tarball={tarball} whole_members={len(members)} kept={kept} prefix_sha256={prefix_sha}")
    if pins.TOTAL_SAMPLES and len(rows) != pins.TOTAL_SAMPLES:
        raise DecodeError(f"built {len(rows)} samples, expected {pins.TOTAL_SAMPLES}")
    aggregate = hashlib.sha256(
        "".join(f"{Path(row['sample_path']).name}\t{row['sha256']}\n" for row in rows).encode("ascii")
    ).hexdigest()
    if pins.AGGREGATE_SHA256 and aggregate != pins.AGGREGATE_SHA256:
        raise DecodeError(f"aggregate SHA-256 {aggregate} != pinned {pins.AGGREGATE_SHA256}")
    with (index_dir / "samples.jsonl").open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, sort_keys=True) + "\n")
    total_bytes = sum(row["sample_size_bytes"] for row in rows)
    stats = {
        "dataset_id": dataset_id,
        "series_id": pins.SERIES_ID,
        "samples": len(rows),
        "total_values": total_bytes,
        "total_bytes": total_bytes,
        "distinct_patients": len(patients),
        "tarballs": per_tarball,
        "skipped_non_gray8": skipped,
        "png_filter_rows": dict(zip(["none", "sub", "up", "average", "paeth"], filter_totals)),
        "png_ancillary_chunks": dict(sorted(ancillary_totals.items())),
        "min_distinct_values": min(row["distinct_values"] for row in rows),
        "max_modal_fraction": max(row["modal_fraction"] for row in rows),
        "mean_zero_fraction": round(sum(row["zero_fraction"] for row in rows) / len(rows), 6),
        "global_min_value": min(row["min_value"] for row in rows),
        "global_max_value": max(row["max_value"] for row in rows),
        "aggregate_sha256": aggregate,
    }
    (filtered_dir / "ingest_stats.json").write_text(json.dumps(stats, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in stats.items() if key != "tarballs"}, sort_keys=True))
    print(f"built samples={len(rows)} total_bytes={total_bytes} aggregate_sha256={aggregate}")


def main(argv: list[str]) -> int:
    if len(argv) == 3 and argv[1] == "check-prefix":
        check_prefix(Path(argv[2]))
        return 0
    if len(argv) == 3 and argv[1] == "build":
        build(Path(argv[2]).resolve())
        return 0
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv))
    except DecodeError as exc:
        raise SystemExit(f"FATAL: {exc}")
