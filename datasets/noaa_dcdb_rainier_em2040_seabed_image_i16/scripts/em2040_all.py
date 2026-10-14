#!/usr/bin/env python3
"""Extract Kongsberg EM2040 seabed-image ('Y', 0x59) backscatter samples from
pinned NOAA Ship Rainier RICHARD2023L4 raw .all files (MB-System id 58).

Subcommands:
  files    print the pinned "name size etag" table (used by download.sh)
  etag     check the S3 ETag (5 MiB multipart MD5 or plain MD5) of a file
  listing  check an S3 ListObjectsV2 XML page against the pinned file table
  check    validate the complete datagram stream of one downloaded file
  build    emit one int16 sample per file (all Y samples in ping order) plus
           an auxiliary per-beam sample-count series

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

DATASET_ID = "noaa_dcdb_rainier_em2040_seabed_image_i16"
BUCKET_URL = "https://noaa-dcdb-bathymetry-pds.s3.amazonaws.com"
PREFIX = "mb/ships/rainier/RICHARD2023L4/multibeam/data/version1/MB/em2040/"
PART_SIZE = 5 * 1024 * 1024  # S3 multipart part size (HEAD ?partNumber=1 -> 5242880)

# The 20 smallest of the 36 raw EM2040 .all files of the cruise (2026-10-14
# listing, objects last modified 2026-05-22). (object name, bytes, S3 ETag).
FILES = [
    ("0030_20230430_225138_2802.all.mb58", 2828052, "c649658fbfc0ba37903be24c59d26485"),
    ("0032_20230430_225357_2802.all.mb58", 17605666, "8d4abb361cf5026d917ef00dd0de2f9c-4"),
    ("0035_20230430_230039_2802.all.mb58", 20342534, "918298f54371a138254350086a2142f8-4"),
    ("0031_20230430_225153_2802.all.mb58", 21814280, "6efb39dca049942a6d70b376f7bc21df-5"),
    ("0033_20230430_225613_2802.all.mb58", 45515860, "b23199d10017751879965b99682f5e38-9"),
    ("0020_20230430_214727_2802.all.mb58", 49513740, "186c0e0f65fb14b66d362516d3679790-10"),
    ("0036_20230430_230503_2802.all.mb58", 50695988, "cd73b079d0613868b283811d2055be5a-10"),
    ("0004_20230430_200930_2802.all.mb58", 60743932, "25bcb37cb92b3fcc04b8204ea634cd3d-12"),
    ("0034_20230430_225805_2802.all.mb58", 67538438, "f0d6cc2a368fed268ff8b6ca7e004d09-13"),
    ("0028_20230430_224132_2802.all.mb58", 68305784, "7897c78234a59f756d727d43168b2494-14"),
    ("0005_20230430_201027_2802.all.mb58", 89106478, "50ce67a504ebf2949ae7630e473115c2-17"),
    ("0024_20230430_220250_2802.all.mb58", 109469244, "1d79133536dbd9457c8c91b04a93a8f1-21"),
    ("0011_20230430_210357_2802.all.mb58", 206406912, "8351dde7fc8bb0e7c3d18bde215f2e04-40"),
    ("0016_20230430_212900_2802.all.mb58", 213934446, "c8a49bd50c57fffd494a8149a2ca161a-41"),
    ("0012_20230430_210806_2802.all.mb58", 214731102, "b4ea2bbe86c8d4e828b4b9755cd3263b-41"),
    ("0026_20230430_220931_2802.all.mb58", 231506710, "1d51eed3822d27ee36a93bd2e9468f09-45"),
    ("0019_20230430_214303_2802.all.mb58", 238052504, "2b4138313666d6ef65ed1d242a21a50c-46"),
    ("0014_20230430_211906_2802.all.mb58", 238779622, "e9e1f4c72222af9445743c2aff91c2c3-46"),
    ("0018_20230430_213824_2802.all.mb58", 246675772, "c6780f4ba94cfa329d495f778fca67dd-48"),
    ("0022_20230430_215405_2802.all.mb58", 248501136, "57fca71e444d3a7c84e12ef40ee8527b-48"),
]
# Processing order: chronological (file names start with the line number and
# start time), so the corpus reads in acquisition order.
FILES.sort(key=lambda item: item[0][5:20])

PRIMARY = "em2040_seabed_image_backscatter_i16"
AUX_NSAMPLES = "em2040_beam_sample_count_u16"
SERIES = (PRIMARY, AUX_NSAMPLES)

EXPECTED_MODEL = 2040
EXPECTED_SERIAL = 40129  # EM2040 system serial in every Y header ("2802" is the launch hull number)
EXPECTED_BEAMS = 400
SEABED_IMAGE_TYPE = 0x59  # 'Y'
STX = 0x02
ETX = 0x03
MIN_LENGTH = 19  # STX..serial (16 bytes) + ETX + checksum
MAX_LENGTH = 1 << 24
MAX_PRIMARY_BYTES = 1_000_000_000
# Resync tolerance: a framing error is skipped by scanning to the next valid
# datagram, but a file may lose at most max(0.1 %, 64 KiB) of its bytes and
# at most MAX_RESYNC_EVENTS events.
MAX_SKIPPED_FRACTION = 0.001
MIN_SKIPPED_ALLOWANCE = 65536
MAX_RESYNC_EVENTS = 16

HEADER = struct.Struct("<HIIHH")  # model, date, time_ms, ping counter, serial (at +6)
Y_BODY = struct.Struct("<fHhhHHH")  # at +20: sf, R0, BSn, BSo, Tx bw, TVG crossover, Nbeams
Y_BEAM = struct.Struct("<bBHH")  # sorting direction, detection info, Nsamples, centre sample


class DecodeError(ValueError):
    pass


def etag_matches(path: Path, expected: str) -> bool:
    with path.open("rb") as handle:
        if "-" in expected:
            parts = int(expected.split("-", 1)[1])
            if parts != max(1, -(-path.stat().st_size // PART_SIZE)):
                return False
            digests = [hashlib.md5(block).digest() for block in iter(lambda: handle.read(PART_SIZE), b"")]
            return f"{hashlib.md5(b''.join(digests)).hexdigest()}-{len(digests)}" == expected
        digest = hashlib.md5()
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
        return digest.hexdigest() == expected


def framed_at(raw: bytes, position: int) -> int:
    """Return the end offset of a correctly framed datagram at position, else -1."""
    total = len(raw)
    if position + 4 > total:
        return -1
    (length,) = struct.unpack_from("<I", raw, position)
    end = position + 4 + length
    if length < MIN_LENGTH or length > MAX_LENGTH or end > total:
        return -1
    if raw[position + 4] != STX or raw[end - 3] != ETX:
        return -1
    (checksum,) = struct.unpack_from("<H", raw, end - 2)
    if sum(raw[position + 5 : end - 3]) & 0xFFFF != checksum:
        return -1
    return end


def resync(raw: bytes, start: int) -> int:
    """Next offset >= start holding a correctly framed datagram, or -1."""
    probe = start + 4
    while True:
        probe = raw.find(b"\x02", probe)
        if probe < 0:
            return -1
        if framed_at(raw, probe - 4) > 0:
            return probe - 4
        probe += 1


def walk(raw: bytes):
    """Yield (offset, end, type) for every valid datagram; record skipped spans."""
    events = []
    position = 0
    total = len(raw)
    while position < total:
        end = framed_at(raw, position)
        if end < 0:
            nxt = resync(raw, position + 1)
            if nxt < 0:
                events.append({"kind": "unframed_tail", "offset": position, "bytes": total - position})
                break
            events.append({"kind": "resync", "offset": position, "bytes": nxt - position})
            position = nxt
            continue
        yield position, end, raw[position + 5], events
        position = end
    yield -1, -1, -1, events


def parse_seabed_image(raw: bytes, position: int, end: int) -> dict:
    model, date, time_ms, ping_counter, serial = HEADER.unpack_from(raw, position + 6)
    if serial != EXPECTED_SERIAL:
        raise DecodeError(f"Y datagram system serial {serial} != {EXPECTED_SERIAL} at byte {position}")
    if position + 36 > end - 3:
        raise DecodeError(f"truncated Y header at byte {position}")
    frequency, r0, bsn, bso, tx_beamwidth, tvg_crossover, beams = Y_BODY.unpack_from(raw, position + 20)
    if beams != EXPECTED_BEAMS:
        raise DecodeError(f"Y datagram has {beams} beams != {EXPECTED_BEAMS} at byte {position}")
    if not 1000.0 <= frequency <= 200000.0:
        raise DecodeError(f"implausible sampling frequency {frequency} at byte {position}")
    cursor = position + 36
    counts = []
    for _ in range(beams):
        _direction, _detection, nsamples, _centre = Y_BEAM.unpack_from(raw, cursor)
        counts.append(nsamples)
        cursor += Y_BEAM.size
    total_samples = sum(counts)
    stop = cursor + 2 * total_samples
    padding = (end - 3) - stop
    if padding not in (0, 1) or (padding == 1 and raw[stop] != 0):
        raise DecodeError(f"Y datagram length/sample-count mismatch (padding {padding}) at byte {position}")
    return {
        "offset": position,
        "date": date,
        "time_ms": time_ms,
        "ping_counter": ping_counter,
        "frequency": frequency,
        "bsn": bsn,
        "bso": bso,
        "tvg_crossover": tvg_crossover,
        "tx_beamwidth": tx_beamwidth,
        "r0": r0,
        "counts": counts,
        "samples": raw[cursor:stop],
    }


def decode_file(raw: bytes) -> dict:
    type_counts: dict[str, int] = {}
    pings = []
    events: list = []
    for position, end, kind, events in walk(raw):
        if position < 0:
            break
        (model,) = struct.unpack_from("<H", raw, position + 6)
        if model != EXPECTED_MODEL:
            raise DecodeError(f"datagram model {model} != {EXPECTED_MODEL} at byte {position}")
        name = chr(kind) if 32 <= kind < 127 else f"0x{kind:02x}"
        type_counts[name] = type_counts.get(name, 0) + 1
        if kind == SEABED_IMAGE_TYPE:
            pings.append(parse_seabed_image(raw, position, end))
    skipped = sum(event["bytes"] for event in events)
    if len(events) > MAX_RESYNC_EVENTS or skipped > max(MAX_SKIPPED_FRACTION * len(raw), MIN_SKIPPED_ALLOWANCE):
        raise DecodeError(f"too much unframed data: {len(events)} events, {skipped} bytes")
    if not pings:
        raise DecodeError("no seabed-image datagrams")
    previous = None
    seen = set()
    for ping in pings:
        stamp = (ping["date"], ping["time_ms"])
        if previous is not None and stamp < previous:
            raise DecodeError(f"Y timestamps decrease at byte {ping['offset']}")
        key = (ping["date"], ping["time_ms"], ping["ping_counter"])
        if key in seen:
            raise DecodeError(f"duplicate Y datagram for ping {key}")
        seen.add(key)
        previous = stamp
    return {"type_counts": dict(sorted(type_counts.items())), "events": events, "pings": pings}


def int16_stats(payload: bytes) -> dict:
    values = struct.unpack(f"<{len(payload) // 2}h", payload)
    distinct = set(values)
    return {
        "minimum": min(values),
        "maximum": max(values),
        "distinct_values": len(distinct),
        "zero_count": values.count(0),
        "minus32768_count": values.count(-32768),
    }


def load_source(download_dir: Path, name: str, size: int, etag: str) -> bytes:
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
    raw_all = [key for key in entries if key.startswith(PREFIX) and key.endswith(".all.mb58") and "/generated/" not in key]
    if len(raw_all) < len(FILES):
        raise SystemExit(f"S3 listing shows only {len(raw_all)} raw .all.mb58 objects")
    for name, size, etag in FILES:
        found = entries.get(PREFIX + name)
        if found is None:
            raise SystemExit(f"pinned object {name} absent from S3 listing")
        if found != (size, etag):
            raise SystemExit(f"pinned object {name} changed upstream: {found} != {(size, etag)}")
    print(f"listing ok: {len(entries)} objects, {len(raw_all)} raw .all.mb58, {len(FILES)} pinned objects match size and ETag")


def command_check(args: argparse.Namespace) -> None:
    raw = args.path.read_bytes()
    try:
        result = decode_file(raw)
    except DecodeError as error:
        raise SystemExit(f"{args.path.name}: {error}") from error
    y_bytes = sum(2 * sum(p["counts"]) for p in result["pings"])
    print(
        f"{args.path.name}: datagrams ok {result['type_counts']} y_pings={len(result['pings'])} "
        f"y_sample_bytes={y_bytes} ({y_bytes / len(raw):.3f} of file) unframed_events={result['events']}"
    )


def command_build(args: argparse.Namespace) -> None:
    samples_root = args.samples_dir
    if samples_root.exists():
        shutil.rmtree(samples_root)
    for series in SERIES:
        (samples_root / series).mkdir(parents=True)
    rows = []
    reports = []
    totals = {series: [0, 0] for series in SERIES}
    seen_hashes: set[str] = set()
    global_min, global_max = 32767, -32768
    for name, size, etag in FILES:
        raw = load_source(args.download_dir, name, size, etag)
        try:
            result = decode_file(raw)
        except DecodeError as error:
            raise SystemExit(f"{name}: {error}") from error
        pings = result["pings"]
        payload = b"".join(ping["samples"] for ping in pings)
        counts = [count for ping in pings for count in ping["counts"]]
        aux = struct.pack(f"<{len(counts)}H", *counts)
        if 2 * sum(counts) != len(payload):
            raise SystemExit(f"{name}: sample count bookkeeping mismatch")
        digest = hashlib.sha256(payload).hexdigest()
        if digest in seen_hashes:
            raise SystemExit(f"{name}: duplicate payload")
        seen_hashes.add(digest)
        stats = int16_stats(payload)
        if stats["distinct_values"] < 2:
            raise SystemExit(f"{name}: constant seabed-image payload")
        global_min = min(global_min, stats["minimum"])
        global_max = max(global_max, stats["maximum"])
        modes: dict[str, int] = {}
        for ping in pings:
            mode = f"{ping['frequency']:.1f}"
            modes[mode] = modes.get(mode, 0) + 1
        stem = name.split(".", 1)[0]
        common = {
            "dataset_id": DATASET_ID,
            "source_file": name,
            "source_size_bytes": size,
            "source_s3_etag": etag,
            "ping_count": len(pings),
            "beams_per_ping": EXPECTED_BEAMS,
            "first_ping": [pings[0]["date"], pings[0]["time_ms"], pings[0]["ping_counter"]],
            "last_ping": [pings[-1]["date"], pings[-1]["time_ms"], pings[-1]["ping_counter"]],
            "sampling_frequency_hz_ping_counts": dict(sorted(modes.items())),
            "endianness": "little",
        }
        outputs = (
            (PRIMARY, payload, "int", 16, "raw_all_file_seabed_image_samples",
             {"role": "primary", "unit": "0.1 dB", "sha256": digest, **stats}),
            (AUX_NSAMPLES, aux, "uint", 16, "raw_all_file_seabed_image_beam_layout",
             {"role": "auxiliary", "sha256": hashlib.sha256(aux).hexdigest()}),
        )
        for series, data, kind, width, record_kind, extra in outputs:
            path = samples_root / series / f"{stem}.bin"
            path.write_bytes(data)
            rows.append(
                {
                    **common,
                    "series_id": series,
                    "sample_path": path.relative_to(args.data_root).as_posix(),
                    "numeric_kind": kind,
                    "bit_width": width,
                    "element_size_bytes": 2,
                    "sample_size_bytes": len(data),
                    "value_count": len(data) // 2,
                    "sample_shape": [len(data) // 2],
                    "sample_axes": ["ping_beam_sample" if series == PRIMARY else "ping_beam"],
                    "natural_record_kind": record_kind,
                    **extra,
                }
            )
            totals[series][0] += 1
            totals[series][1] += len(data)
        reports.append(
            {
                "source_file": name,
                "size_bytes": size,
                "datagram_type_counts": result["type_counts"],
                "unframed_events": result["events"],
                "y_pings": len(pings),
                "y_sample_values": len(payload) // 2,
                "y_sample_fraction_of_file": round(len(payload) / size, 4),
                "sampling_frequency_hz_ping_counts": dict(sorted(modes.items())),
                **stats,
            }
        )
        print(
            f"{name}: pings={len(pings)} values={len(payload) // 2} frac={len(payload) / size:.3f} "
            f"min={stats['minimum']} max={stats['maximum']} distinct={stats['distinct_values']} "
            f"zeros={stats['zero_count']} modes={modes} unframed={len(result['events'])}",
            flush=True,
        )
        del raw, result, pings, payload
    if totals[PRIMARY][1] > MAX_PRIMARY_BYTES:
        raise SystemExit(f"primary bytes {totals[PRIMARY][1]} exceed {MAX_PRIMARY_BYTES}")
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
        "files": reports,
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
    etag.add_argument("--expect", required=True)
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
        if not etag_matches(args.path, args.expect):
            raise SystemExit(f"ETag mismatch for {args.path}")
        print(f"etag ok {args.path.name} {args.expect}")
    elif args.command == "listing":
        check_listing(args.path)
    elif args.command == "check":
        command_check(args)
    else:
        command_build(args)


if __name__ == "__main__":
    sys.exit(main())
