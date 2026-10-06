#!/usr/bin/env python3
"""Decode complete Kongsberg EM302 water-column pings from pinned EX1711 .wcd files.

Subcommands:
  files    print the pinned "name size etag" table (used by download.sh)
  etag     compute the S3 ETag (8 MiB multipart MD5 or plain MD5) of a file
  listing  check an S3 ListObjectsV2 XML page against the pinned file table
  check    validate the complete datagram framing of one downloaded .wcd file
  build    emit one int8 sample per complete ping plus auxiliary beam layout

Only the standard library is used.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import struct
import sys
from pathlib import Path

DATASET_ID = "noaa_wcsd_em302_water_column_i8"
BUCKET_URL = "https://noaa-wcsd-pds.s3.amazonaws.com"
PREFIX = "data/raw/Okeanos_Explorer/EX1711/EM302/"
PART_SIZE = 8 * 1024 * 1024

# (object name, size in bytes, S3 ETag). ETags with a "-N" suffix are S3
# multipart ETags over 8 MiB parts; the other one is a plain MD5.
# 0062_20171203_000100 was dropped: the archived object (10977280 bytes, an
# exact multiple of 4096) ends inside a truncated water-column datagram.
FILES = [
    ("0016_20171130_045718_EX1711b_MB.wcd", 14150152, "8e6012043a131aa82c53dba5767585bd-2"),
    ("0032_20171201_050548_EX1711b_MB.wcd", 31598272, "6b89ba77bf89db3674a34938f661b4ab-4"),
    ("0043_20171202_004144_EX1711b_MB.wcd", 13051662, "9cda0c9b3dfdc8d4a66a7000ec4ba719-2"),
    ("0058_20171202_104145_EX1711b_MB.wcd", 7895394, "dc11be3d569f27cb5ae6e9638188d537"),
    ("0064_20171203_004816_EX1711b_MB.wcd", 18810152, "239221955fcaea55a8e31c2c2ac74636-3"),
    ("0102_20171204_091713_EX1711b_MB.wcd", 29846374, "cb517ffce55fe9ea02794a5237ef4bda-4"),
    ("0124_20171206_044514_EX1711b_MB.wcd", 30591162, "cb279c9f426a9f9583842132b0d58765-4"),
    ("0148_20171207_035932_EX1711b_MB.wcd", 41740046, "950ba31aab79842e6d220cc3c4d672af-5"),
    ("0208_20171210_091038_EX1711b_MB.wcd", 41348090, "7665e625527666fcd38d79611e9090cc-5"),
    ("0270_20171213_110507_EX1711b_MB.wcd", 8893816, "3202af66f4d1223398a09d8ea3eabaea-2"),
    ("0321_20171215_232631_EX1711b_MB.wcd", 30687674, "412d31557f9afb87d3852b6822c9f8a9-4"),
    ("0346_20171217_051227_EX1711b_MB.wcd", 24398754, "017256f62d6a12524b258e1fbfde3f87-3"),
    ("0369_20171218_100453_EX1711b_MB.wcd", 22763266, "79bd7d066ad379b5a62074bdbbb5a02b-3"),
    ("0390_20171219_114303_EX1711b_MB.wcd", 22081168, "2ef192e40ed8008fa43fcf4a949e1396-3"),
    ("0403_20171220_104446_EX1711b_MB.wcd", 19601624, "d3f80aed0f36fc6e4ad0ab50e5d4db20-3"),
]

PRIMARY = "em302_ping_water_column_amplitude_i8"
AUX_SAMPLE_COUNT = "em302_ping_beam_sample_count_u16"
AUX_POINTING = "em302_ping_beam_pointing_angle_i16"
SERIES = (PRIMARY, AUX_SAMPLE_COUNT, AUX_POINTING)

EXPECTED_MODEL = 302
EXPECTED_SERIAL = 101
EXPECTED_TVG_FUNCTION = 30
EXPECTED_TVG_OFFSET_DB = 20
EXPECTED_BEAMS = 288
WATER_COLUMN_TYPE = 0x6B  # 'k'
STX = 0x02
ETX = 0x03
MIN_DATAGRAM_LENGTH = 19  # STX..serial (16) + ETX + checksum

K_HEADER = struct.Struct("<HIIHHHHHHHHIhBbB3s")  # starts 6 bytes after the length field
TX_ENTRY = struct.Struct("<hHBB")
RX_BEAM = struct.Struct("<hHHHBB")
# Maps the stored int8 bit pattern (as a byte) to an order-preserving u8 so that
# bytes.min()/max() give the int8 extremes: 0x80 (-128) -> 0, 0x7F (+127) -> 255.
INT8_ORDER = bytes(((b ^ 0x80) & 0xFF) for b in range(256))


class DecodeError(ValueError):
    pass


def s3_etag(path: Path) -> str:
    size = path.stat().st_size
    digests = []
    with path.open("rb") as handle:
        while True:
            block = handle.read(PART_SIZE)
            if not block:
                break
            digests.append(hashlib.md5(block).digest())
    if size <= PART_SIZE and len(digests) <= 1:
        return digests[0].hex() if digests else hashlib.md5(b"").hexdigest()
    return f"{hashlib.md5(b''.join(digests)).hexdigest()}-{len(digests)}"


def multipart_etag(path: Path) -> str:
    """Return the multipart form even for single-part files (for ETags with -1)."""
    with path.open("rb") as handle:
        digests = [hashlib.md5(block).digest() for block in iter(lambda: handle.read(PART_SIZE), b"")]
    return f"{hashlib.md5(b''.join(digests)).hexdigest()}-{len(digests)}"


def etag_matches(path: Path, expected: str) -> bool:
    if "-" in expected:
        parts = int(expected.split("-", 1)[1])
        size = path.stat().st_size
        if parts != max(1, -(-size // PART_SIZE)):
            return False
        return multipart_etag(path) == expected
    with path.open("rb") as handle:
        digest = hashlib.md5()
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest() == expected


def iter_datagrams(raw: bytes):
    """Yield (offset, length, type) for every datagram; fail on any framing error."""
    position = 0
    total = len(raw)
    while position < total:
        if position + 4 > total:
            raise DecodeError(f"truncated length field at byte {position}")
        (length,) = struct.unpack_from("<I", raw, position)
        end = position + 4 + length
        if length < MIN_DATAGRAM_LENGTH or end > total:
            raise DecodeError(f"invalid datagram length {length} at byte {position}")
        if raw[position + 4] != STX:
            raise DecodeError(f"missing STX at byte {position}")
        if raw[end - 3] != ETX:
            raise DecodeError(f"missing ETX at byte {position}")
        (checksum,) = struct.unpack_from("<H", raw, end - 2)
        if sum(raw[position + 5 : end - 3]) & 0xFFFF != checksum:
            raise DecodeError(f"checksum mismatch at byte {position}")
        (model,) = struct.unpack_from("<H", raw, position + 6)
        if model != EXPECTED_MODEL:
            raise DecodeError(f"datagram model {model} != {EXPECTED_MODEL} at byte {position}")
        yield position, length, raw[position + 5]
        position = end


def parse_water_column(raw: bytes, position: int, length: int) -> dict:
    end = position + 4 + length
    if position + 44 > end - 3:
        raise DecodeError(f"truncated water-column header at byte {position}")
    (
        _model,
        date,
        time_ms,
        ping_counter,
        serial,
        datagram_count,
        datagram_number,
        tx_count,
        rx_total,
        rx_count,
        sound_speed_dm_s,
        sample_frequency_centihz,
        tx_heave_cm,
        tvg_function,
        tvg_offset_db,
        scan_info,
        _spare,
    ) = K_HEADER.unpack_from(raw, position + 6)
    if serial != EXPECTED_SERIAL:
        raise DecodeError(f"system serial {serial} != {EXPECTED_SERIAL} at byte {position}")
    if tvg_function != EXPECTED_TVG_FUNCTION or tvg_offset_db != EXPECTED_TVG_OFFSET_DB:
        raise DecodeError(f"TVG function/offset {tvg_function}/{tvg_offset_db} at byte {position}")
    if rx_total != EXPECTED_BEAMS:
        raise DecodeError(f"total receive beams {rx_total} != {EXPECTED_BEAMS} at byte {position}")
    if not 1 <= datagram_number <= datagram_count or not 1 <= tx_count <= 20 or not 1 <= rx_count <= rx_total:
        raise DecodeError(f"invalid datagram/sector/beam counts at byte {position}")
    if sample_frequency_centihz == 0 or not 14000 <= sound_speed_dm_s <= 16000:
        raise DecodeError(f"implausible sample frequency or sound speed at byte {position}")
    cursor = position + 44
    tx_entries = []
    for _ in range(tx_count):
        tilt, frequency, sector, _tx_spare = TX_ENTRY.unpack_from(raw, cursor)
        if sector >= tx_count:
            raise DecodeError(f"transmit sector {sector} out of range at byte {position}")
        tx_entries.append((tilt, frequency, sector))
        cursor += TX_ENTRY.size
    beams = []
    amplitudes = []
    limit = end - 3
    for _ in range(rx_count):
        if cursor + RX_BEAM.size > limit:
            raise DecodeError(f"truncated beam header at byte {position}")
        angle, start_sample, sample_count, detected_range, sector, _beam_number = RX_BEAM.unpack_from(raw, cursor)
        cursor += RX_BEAM.size
        if start_sample != 0:
            raise DecodeError(f"non-zero start range sample {start_sample} at byte {position}")
        if sector >= tx_count:
            raise DecodeError(f"beam transmit sector {sector} out of range at byte {position}")
        if cursor + sample_count > limit:
            raise DecodeError(f"truncated beam amplitudes at byte {position}")
        amplitudes.append(raw[cursor : cursor + sample_count])
        beams.append((angle, sample_count, detected_range))
        cursor += sample_count
    padding = limit - cursor
    if padding not in (0, 1) or (padding == 1 and raw[cursor] != 0):
        raise DecodeError(f"unexpected trailing bytes ({padding}) in water-column datagram at byte {position}")
    return {
        "offset": position,
        "date": date,
        "time_ms": time_ms,
        "ping_counter": ping_counter,
        "datagram_count": datagram_count,
        "datagram_number": datagram_number,
        "header": (
            datagram_count,
            tx_count,
            rx_total,
            sound_speed_dm_s,
            sample_frequency_centihz,
            tx_heave_cm,
            tvg_function,
            tvg_offset_db,
            scan_info,
            tuple(tx_entries),
        ),
        "beams": beams,
        "amplitudes": amplitudes,
    }


def decode_stream(raw: bytes) -> dict:
    """Group water-column datagrams into pings and keep only complete, non-blank pings."""
    type_counts: dict[str, int] = {}
    groups: dict[tuple[int, int, int], list[dict]] = {}
    order: list[tuple[int, int, int]] = []
    for position, length, kind in iter_datagrams(raw):
        name = chr(kind) if 32 <= kind < 127 else f"0x{kind:02x}"
        type_counts[name] = type_counts.get(name, 0) + 1
        if kind != WATER_COLUMN_TYPE:
            continue
        datagram = parse_water_column(raw, position, length)
        key = (datagram["date"], datagram["time_ms"], datagram["ping_counter"])
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(datagram)
    pings = []
    partial_keys = []
    blank_keys = []
    for index, key in enumerate(order):
        datagrams = sorted(groups[key], key=lambda item: item["datagram_number"])
        count = datagrams[0]["datagram_count"]
        numbers = [item["datagram_number"] for item in datagrams]
        if any(item["datagram_count"] != count for item in datagrams):
            raise DecodeError(f"inconsistent datagram count within ping {key}")
        if len(numbers) != len(set(numbers)):
            raise DecodeError(f"duplicate water-column datagram within ping {key}")
        if numbers != list(range(1, count + 1)):
            if index in (0, len(order) - 1):
                partial_keys.append(list(key))
                continue
            raise DecodeError(f"interior ping {key} is missing datagrams: {numbers} of {count}")
        header = datagrams[0]["header"]
        if any(item["header"] != header for item in datagrams):
            raise DecodeError(f"ping {key} has inconsistent per-datagram headers")
        beams = [beam for item in datagrams for beam in item["beams"]]
        if len(beams) != EXPECTED_BEAMS:
            raise DecodeError(f"ping {key} has {len(beams)} beams")
        angles = [beam[0] for beam in beams]
        if any(left <= right for left, right in zip(angles, angles[1:])):
            raise DecodeError(f"ping {key} beam pointing angles are not strictly decreasing")
        payload = b"".join(chunk for item in datagrams for chunk in item["amplitudes"])
        if not payload or payload.count(payload[:1]) == len(payload):
            blank_keys.append(list(key))
            continue
        pings.append(
            {
                "key": key,
                "offsets": [item["offset"] for item in datagrams],
                "header": header,
                "beams": beams,
                "payload": payload,
            }
        )
    previous = None
    for ping in pings:
        stamp = (ping["key"][0], ping["key"][1])
        if previous is not None and stamp < previous:
            raise DecodeError(f"ping timestamps decrease at {ping['key']}")
        previous = stamp
    return {
        "type_counts": dict(sorted(type_counts.items())),
        "water_column_groups": len(order),
        "pings": pings,
        "dropped_edge_partial_pings": partial_keys,
        "dropped_blank_pings": blank_keys,
    }


def amplitude_stats(payload: bytes) -> dict:
    ordered = payload.translate(INT8_ORDER)
    return {
        "minimum": min(ordered) - 128,
        "maximum": max(ordered) - 128,
        "floor_count": payload.count(b"\x80"),
        "distinct_values": len(set(payload)),
    }


def validate_source(download_dir: Path, name: str, size: int, etag: str) -> bytes:
    path = download_dir / name
    if not path.is_file() or path.stat().st_size != size:
        raise SystemExit(f"missing or wrong-size source {path}; run download.sh first")
    if not etag_matches(path, etag):
        raise SystemExit(f"S3 ETag mismatch for {path}")
    return path.read_bytes()


def check_listing(listing: Path) -> None:
    text = listing.read_text(encoding="utf-8")
    entries = {}
    for block in re.findall(r"<Contents>(.*?)</Contents>", text, re.S):
        key = re.search(r"<Key>(.*?)</Key>", block)
        size = re.search(r"<Size>(\d+)</Size>", block)
        etag = re.search(r"<ETag>(.*?)</ETag>", block)
        if key and size and etag:
            entries[key.group(1)] = (int(size.group(1)), etag.group(1).replace("&quot;", "").strip('"'))
    if not entries:
        raise SystemExit("S3 listing has no objects")
    for name, size, etag in FILES:
        found = entries.get(PREFIX + name)
        if found is None:
            raise SystemExit(f"pinned object {name} absent from S3 listing")
        if found != (size, etag):
            raise SystemExit(f"pinned object {name} changed upstream: {found} != {(size, etag)}")
    print(f"listing ok: {len(entries)} objects, {len(FILES)} pinned objects match size and ETag")


def command_check(args: argparse.Namespace) -> None:
    raw = args.path.read_bytes()
    try:
        result = decode_stream(raw)
    except DecodeError as error:
        raise SystemExit(f"{args.path.name}: {error}") from error
    if not result["pings"]:
        raise SystemExit(f"{args.path.name}: no complete water-column pings")
    print(
        f"{args.path.name}: datagrams ok {result['type_counts']} complete_pings={len(result['pings'])} "
        f"edge_partial={len(result['dropped_edge_partial_pings'])} blank={len(result['dropped_blank_pings'])}"
    )


def command_build(args: argparse.Namespace) -> None:
    samples_root = args.samples_dir
    if samples_root.exists():
        shutil.rmtree(samples_root)
    for series in SERIES:
        (samples_root / series).mkdir(parents=True)
    rows = []
    file_reports = []
    seen_hashes: set[str] = set()
    totals = {series: [0, 0] for series in SERIES}
    global_min = 127
    global_max = -128
    floor_total = 0
    modes: dict[str, int] = {}
    for name, size, etag in FILES:
        raw = validate_source(args.download_dir, name, size, etag)
        try:
            result = decode_stream(raw)
        except DecodeError as error:
            raise SystemExit(f"{name}: {error}") from error
        if not result["pings"]:
            raise SystemExit(f"{name}: no complete water-column pings")
        stem = name[:20]
        values_in_file = 0
        for ordinal, ping in enumerate(result["pings"], 1):
            date, time_ms, ping_counter = ping["key"]
            (count, tx_count, rx_total, sound_speed, frequency, heave, tvg_function, tvg_offset, scan_info, tx_entries) = ping["header"]
            payload = ping["payload"]
            digest = hashlib.sha256(payload).hexdigest()
            if digest in seen_hashes:
                raise SystemExit(f"{name}: duplicate ping payload at {ping['key']}")
            seen_hashes.add(digest)
            stats = amplitude_stats(payload)
            global_min = min(global_min, stats["minimum"])
            global_max = max(global_max, stats["maximum"])
            floor_total += stats["floor_count"]
            mode = f"sf={frequency / 100:.2f}Hz ntx={tx_count}"
            modes[mode] = modes.get(mode, 0) + 1
            sample_counts = [beam[1] for beam in ping["beams"]]
            angles = [beam[0] for beam in ping["beams"]]
            base = f"{stem}_ping{ordinal:04d}_pc{ping_counter:05d}"
            common = {
                "dataset_id": DATASET_ID,
                "source_file": name,
                "source_datagram_offsets": ping["offsets"],
                "ping_ordinal_in_file": ordinal,
                "ping_counter": ping_counter,
                "ping_date": date,
                "ping_time_ms": time_ms,
                "water_column_datagram_count": count,
                "tx_sector_count": tx_count,
                "beam_count": rx_total,
                "sample_frequency_hz": frequency / 100,
                "sound_speed_m_s": sound_speed / 10,
                "tvg_function": tvg_function,
                "tvg_offset_db": tvg_offset,
                "endianness": "little",
            }
            outputs = (
                (PRIMARY, payload, "int", 8, ["beam_ragged_range_sample"], "complete_em302_water_column_ping",
                 {"amplitude_unit": "0.5 dB", **stats, "beam_sample_count_min": min(sample_counts),
                  "beam_sample_count_max": max(sample_counts), "sha256": digest, "role": "primary"}),
                (AUX_SAMPLE_COUNT, struct.pack(f"<{len(sample_counts)}H", *sample_counts), "uint", 16, ["beam"],
                 "complete_em302_water_column_ping_beam_layout", {"role": "auxiliary"}),
                (AUX_POINTING, struct.pack(f"<{len(angles)}h", *angles), "int", 16, ["beam"],
                 "complete_em302_water_column_ping_beam_layout", {"role": "auxiliary", "angle_unit": "0.01 degree"}),
            )
            for series, data, kind, width, axes, record_kind, extra in outputs:
                path = samples_root / series / f"{base}.bin"
                path.write_bytes(data)
                element = width // 8
                rows.append(
                    {
                        **common,
                        "series_id": series,
                        "sample_path": path.relative_to(args.data_root).as_posix(),
                        "numeric_kind": kind,
                        "bit_width": width,
                        "element_size_bytes": element,
                        "sample_size_bytes": len(data),
                        "value_count": len(data) // element,
                        "sample_shape": [len(data) // element],
                        "sample_axes": axes,
                        "natural_record_kind": record_kind,
                        **extra,
                    }
                )
                totals[series][0] += 1
                totals[series][1] += len(data)
            values_in_file += len(payload)
        file_reports.append(
            {
                "source_file": name,
                "size_bytes": size,
                "s3_etag": etag,
                "datagram_type_counts": result["type_counts"],
                "water_column_ping_groups": result["water_column_groups"],
                "emitted_pings": len(result["pings"]),
                "emitted_values": values_in_file,
                "dropped_edge_partial_pings": result["dropped_edge_partial_pings"],
                "dropped_blank_pings": result["dropped_blank_pings"],
            }
        )
        print(
            f"{name}: pings={len(result['pings'])} values={values_in_file} "
            f"edge_partial={len(result['dropped_edge_partial_pings'])} blank={len(result['dropped_blank_pings'])}",
            flush=True,
        )
    args.index.parent.mkdir(parents=True, exist_ok=True)
    with args.index.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")
    summary = {
        "dataset_id": DATASET_ID,
        "source_files": len(FILES),
        "series": {series: {"sample_count": count, "total_size_bytes": size} for series, (count, size) in totals.items()},
        "primary_global_minimum": global_min,
        "primary_global_maximum": global_max,
        "primary_floor_value_count": floor_total,
        "modes": dict(sorted(modes.items())),
        "files": file_reports,
    }
    args.stats.parent.mkdir(parents=True, exist_ok=True)
    args.stats.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in summary.items() if key != "files"}, indent=2, sort_keys=True))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("files")
    etag = sub.add_parser("etag")
    etag.add_argument("path", type=Path)
    etag.add_argument("--expect")
    listing = sub.add_parser("listing")
    listing.add_argument("path", type=Path)
    check = sub.add_parser("check")
    check.add_argument("path", type=Path)
    build = sub.add_parser("build")
    build.add_argument("--download-dir", type=Path, required=True)
    build.add_argument("--samples-dir", type=Path, required=True)
    build.add_argument("--index", type=Path, required=True)
    build.add_argument("--stats", type=Path, required=True)
    build.add_argument("--data-root", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "files":
        for name, size, etag_value in FILES:
            print(f"{name} {size} {etag_value}")
    elif args.command == "etag":
        if args.expect:
            if not etag_matches(args.path, args.expect):
                raise SystemExit(f"ETag mismatch for {args.path}")
            print(f"etag ok {args.path.name} {args.expect}")
        else:
            print(s3_etag(args.path))
    elif args.command == "listing":
        check_listing(args.path)
    elif args.command == "check":
        command_check(args)
    else:
        command_build(args)


if __name__ == "__main__":
    sys.exit(main())
