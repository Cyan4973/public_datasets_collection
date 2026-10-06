#!/usr/bin/env python3
"""Elekta Neuromag FIFF helpers for openneuro_ds003483_vectorview_meg_mag_i16.

Pure standard library. Network I/O is done by download.sh with curl; this
module only parses what curl fetched, validates it, and builds canonical
little-endian int16 samples.

FIFF layout (MNE-Python mne/_fiff/tag.py, open.py, constants.py; Elekta
"FIF file format" manual): a file is a chain of tags, each with a 16-byte
big-endian header (int32 kind, int32 type, int32 size, int32 next) followed
by `size` payload bytes. next == 0 means the following tag is adjacent,
next > 0 is an absolute file offset, next == -1 ends the chain (in these
files on a final FIFF_NOP, kind 108, just before FIFF_DIR). Blocks are
delimited by FIFF_BLOCK_START (104) / FIFF_BLOCK_END (105) tags whose int32
payload is the block kind. The second tag, FIFF_DIR_POINTER (101), points to
a trailing FIFF_DIR (102) tag, outside the chain, whose payload lists
(kind, type, size, pos) of every chained tag plus a (-1, -1, -1, -1)
terminator.

Inside FIFFB_MEAS_INFO (101): FIFF_NCHAN (200), FIFF_SFREQ (201),
FIFF_DATA_PACK (202), FIFF_LOWPASS (219), FIFF_HIGHPASS (223),
FIFF_LINE_FREQ (235) and NCHAN FIFF_CH_INFO (203, type 30) records of 96
bytes: scanNo, logNo, kind (int32), range, cal (float32), coil_type (int32),
r0/ex/ey/ez (12 float32), unit, unit_mul (int32), ch_name (char[16]).
Inside FIFFB_RAW_DATA (102): FIFF_DATA_SKIP (301) and FIFF_DATA_BUFFER (300)
tags. Buffers of type FIFFT_DAU_PACK16 (16) hold time-major big-endian int16
codes [nsamp][nchan]. As in MNE _read_raw_file, a DATA_SKIP that precedes
the first buffer is a start offset (first_samp += skip * buffer_samples),
not a gap; a DATA_SKIP between buffers is a real gap and is rejected here.

The measurement-info HPI block (108) carries its own NCHAN=306 and 1.2 MB
FIFF_EPOCH tags; only scalars whose parent block is 101 are used. The
subject block (106) and the measurement date are never decoded or emitted.
"""
from __future__ import annotations

from array import array
import argparse
import csv
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import struct
import sys
import tempfile

DATASET_ID = "openneuro_ds003483_vectorview_meg_mag_i16"
SERIES_ID = "vectorview_magnetometer_tsss_i16"
BUCKET_URL = "https://s3.amazonaws.com/openneuro.org"

TAG = struct.Struct(">iiii")
CH_INFO = struct.Struct(">iiiffi12fii16s")  # 96 bytes
NEXT_SEQUENTIAL, NEXT_NONE = 0, -1

# Tag kinds.
FIFF_FILE_ID = 100
FIFF_DIR_POINTER = 101
FIFF_DIR = 102
FIFF_BLOCK_START = 104
FIFF_BLOCK_END = 105
FIFF_CREATOR = 113
FIFF_NCHAN = 200
FIFF_SFREQ = 201
FIFF_DATA_PACK = 202
FIFF_CH_INFO = 203
FIFF_FIRST_SAMPLE = 208
FIFF_LOWPASS = 219
FIFF_HIGHPASS = 223
FIFF_LINE_FREQ = 235
FIFF_DATA_BUFFER = 300
FIFF_DATA_SKIP = 301
FIFF_SSS_FRAME = 263
FIFF_SSS_JOB = 264
FIFF_SSS_ORD_IN = 266
FIFF_SSS_ORD_OUT = 267
FIFF_SSS_NMAG = 268
FIFF_SSS_ST_CORR = 272
FIFF_SSS_NFREE = 278
FIFF_SSS_ST_LENGTH = 279

# Block kinds.
FIFFB_MEAS = 100
FIFFB_MEAS_INFO = 101
FIFFB_RAW_DATA = 102
FIFFB_SUBJECT = 106
FIFFB_CHANNEL_DECOUPLER = 501
FIFFB_SSS_INFO = 502
FIFFB_SSS_CAL = 503
FIFFB_SSS_ST_INFO = 504
FIFFB_PROCESSING_HISTORY = 900
FIFFB_PROCESSING_RECORD = 901

# Types.
FIFFT_INT = 3
FIFFT_FLOAT = 4
FIFFT_STRING = 10
FIFFT_DAU_PACK16 = 16
FIFFT_CH_INFO_STRUCT = 30
FIFFT_ID_STRUCT = 31
FIFFT_DIR_ENTRY_STRUCT = 32

MEAS_INFO_SCALARS = {
    FIFF_NCHAN: ">i", FIFF_SFREQ: ">f", FIFF_DATA_PACK: ">i",
    FIFF_LOWPASS: ">f", FIFF_HIGHPASS: ">f", FIFF_LINE_FREQ: ">f",
}


def f32(value: float) -> float:
    return struct.unpack(">f", struct.pack(">f", value))[0]


# Pinned acquisition/processing signature shared by all six runs.
EXPECTED_NCHAN = 320
EXPECTED_MEAS = {
    FIFF_NCHAN: EXPECTED_NCHAN, FIFF_SFREQ: 1000.0, FIFF_DATA_PACK: FIFFT_DAU_PACK16,
    FIFF_LOWPASS: 330.0, FIFF_HIGHPASS: f32(0.1), FIFF_LINE_FREQ: 50.0,
}
BUFFER_SAMPLES = 1000
FULL_BUFFER_BYTES = EXPECTED_NCHAN * BUFFER_SAMPLES * 2
MEG_CH_KIND = 1
MAG_COIL = 3024  # FIFFV_COIL_VV_MAG_T3, Vectorview SQ20950N magnetometer
GRAD_COIL = 3012  # FIFFV_COIL_VV_PLANAR_T1
EXPECTED_MAGS = 102
EXPECTED_GRADS = 204
MAG_RANGE = f32(1.9073486328125e-05)
MAG_CAL = f32(4.14e-11)
MAG_UNIT = 112  # FIFF_UNIT_T
MAG_NAME = re.compile(r"^MEG\d{3}1$")
EXPECTED_RECORDS = 2
EXPECTED_CREATOR = "maxfilter 2.2.10"
EXPECTED_CT_CREATOR = "create_ct_matrix 1.0"
EXPECTED_RECORD_BLOCKS = {FIFFB_CHANNEL_DECOUPLER: 1, FIFFB_SSS_INFO: 1, FIFFB_SSS_CAL: 1, FIFFB_SSS_ST_INFO: 1}
# SSS job 5 = FIFFV_SSS_JOB_MOVEC_FIT (head-movement compensation), frame 4 =
# head coordinates, internal/external expansion orders 8/3, 306 MEG channels;
# temporal block job 10 = FIFFV_SSS_JOB_ST (tSSS) with a 0.9 correlation limit
# and a 10 s window. FIFF_SSS_NFREE (fitted degrees of freedom) is
# data-dependent (67-71 in the six runs) and only reported.
EXPECTED_SSS = {FIFF_SSS_FRAME: 4, FIFF_SSS_JOB: 5, FIFF_SSS_ORD_IN: 8, FIFF_SSS_ORD_OUT: 3,
                FIFF_SSS_NMAG: 306}
REPORTED_SSS = (FIFF_SSS_NFREE,)
EXPECTED_ST = {FIFF_SSS_JOB: 10, FIFF_SSS_ST_CORR: f32(0.9), FIFF_SSS_ST_LENGTH: 10.0}
EXPECTED_RUNS = 6

# Degeneracy thresholds shared by download checks and build (verify re-states them).
BLOCK_SAMPLES = 1000  # one second
MIN_DISTINCT_VALUES = 1000
MIN_PEAK_TO_PEAK = 1000
MAX_IDENTICAL_RUN = 100  # 0.1 s
INT16_MIN, INT16_MAX = -32768, 32767


class FifError(ValueError):
    pass


def read_selection(path: Path) -> list[dict]:
    with path.open(newline="") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    for row in rows:
        for key in ("size_bytes", "dir_pointer", "n_buffers", "leading_skip_buffers"):
            row[key] = int(row[key])
    return rows


def parse_ch_info(raw: bytes) -> dict:
    fields = CH_INFO.unpack(raw)
    return {
        "scan_no": fields[0], "log_no": fields[1], "kind": fields[2],
        "range": fields[3], "cal": fields[4], "coil_type": fields[5],
        "unit": fields[18], "unit_mul": fields[19],
        "name": fields[20].split(b"\x00", 1)[0].decode("latin-1"),
    }


def parse_fif(path: Path) -> dict:
    """Walk the tag chain from offset 0 following next pointers."""
    size = path.stat().st_size
    tags: list[tuple[int, int, int, int]] = []
    stack: list[int] = []
    meas: dict[int, object] = {}
    channels: list[dict] = []
    records: list[dict] = []
    record = None
    raw = {"blocks": 0, "leading_skip": None, "buffers": [], "inner_skips": [],
           "first_sample_tags": 0, "other_kinds": []}
    dir_pointer = None
    directory = None
    dir_tag = None
    with path.open("rb") as fh:
        def payload(position: int, length: int) -> bytes:
            fh.seek(position + 16)
            data = fh.read(length)
            if len(data) != length:
                raise FifError(f"short payload read at {position}")
            return data

        pos = 0
        while True:
            if pos < 0 or pos + 16 > size:
                raise FifError(f"tag header at {pos} lies outside the {size}-byte file")
            fh.seek(pos)
            kind, typ, length, nxt = TAG.unpack(fh.read(16))
            if length < 0 or pos + 16 + length > size:
                raise FifError(f"tag kind={kind} at {pos} overruns the file (size field {length})")
            parent = stack[-1] if stack else None
            if kind == FIFF_DIR:
                raise FifError(f"FIFF_DIR found inside the tag chain at {pos}")
            tags.append((kind, typ, length, pos))
            if FIFFB_SUBJECT in stack and kind not in (FIFF_BLOCK_START, FIFF_BLOCK_END):
                pass  # never decode subject identifiers
            elif kind == FIFF_BLOCK_START:
                (block,) = struct.unpack(">i", payload(pos, 4))
                stack.append(block)
                if block == FIFFB_RAW_DATA:
                    raw["blocks"] += 1
                elif block == FIFFB_PROCESSING_RECORD:
                    record = {"creators": [], "blocks": {}, "ct_creators": [], "sss": {}, "st": {}, "reported": {}}
                    records.append(record)
                elif record is not None and parent == FIFFB_PROCESSING_RECORD:
                    record["blocks"][block] = record["blocks"].get(block, 0) + 1
            elif kind == FIFF_BLOCK_END:
                (block,) = struct.unpack(">i", payload(pos, 4))
                if not stack or stack[-1] != block:
                    raise FifError(f"unbalanced block end {block} at {pos}")
                stack.pop()
                if block == FIFFB_PROCESSING_RECORD:
                    record = None
            elif kind == FIFF_DIR_POINTER and parent is None:
                (dir_pointer,) = struct.unpack(">i", payload(pos, 4))
            elif parent == FIFFB_MEAS_INFO and kind in MEAS_INFO_SCALARS:
                if length != 4 or kind in meas:
                    raise FifError(f"unexpected measurement-info scalar kind={kind}")
                (meas[kind],) = struct.unpack(MEAS_INFO_SCALARS[kind], payload(pos, 4))
            elif parent == FIFFB_MEAS_INFO and kind == FIFF_CH_INFO:
                if typ != FIFFT_CH_INFO_STRUCT or length != CH_INFO.size:
                    raise FifError(f"malformed FIFF_CH_INFO at {pos}")
                channels.append(parse_ch_info(payload(pos, length)))
            elif kind == FIFF_CREATOR and record is not None and typ == FIFFT_STRING:
                text = payload(pos, length).decode("latin-1")
                if parent == FIFFB_PROCESSING_RECORD:
                    record["creators"].append(text)
                elif parent == FIFFB_CHANNEL_DECOUPLER:
                    record["ct_creators"].append(text)
            elif record is not None and parent == FIFFB_SSS_INFO and kind in EXPECTED_SSS:
                (record["sss"][kind],) = struct.unpack(">i", payload(pos, 4))
            elif record is not None and parent == FIFFB_SSS_INFO and kind in REPORTED_SSS:
                (record["reported"][kind],) = struct.unpack(">i", payload(pos, 4))
            elif record is not None and parent == FIFFB_SSS_ST_INFO and kind in EXPECTED_ST:
                fmt = ">i" if kind == FIFF_SSS_JOB else ">f"
                (record["st"][kind],) = struct.unpack(fmt, payload(pos, 4))
            elif parent == FIFFB_RAW_DATA:
                if kind == FIFF_DATA_SKIP:
                    (skip,) = struct.unpack(">i", payload(pos, 4))
                    if raw["buffers"]:
                        raw["inner_skips"].append((pos, skip))
                    elif raw["leading_skip"] is None:
                        raw["leading_skip"] = skip
                    else:
                        raise FifError("more than one leading FIFF_DATA_SKIP")
                elif kind == FIFF_DATA_BUFFER:
                    raw["buffers"].append((pos, typ, length))
                elif kind == FIFF_FIRST_SAMPLE:
                    raw["first_sample_tags"] += 1
                else:
                    raw["other_kinds"].append(kind)
            if nxt == NEXT_NONE:
                break
            if nxt == NEXT_SEQUENTIAL:
                pos += 16 + length
            elif nxt > pos:
                pos = nxt
            else:
                raise FifError(f"backward or invalid next pointer {nxt} at {pos}")
        chain_end = pos + 16 + length
        # The chain ends (next == -1) on a FIFF_NOP; the FIFF_DIR directory that
        # follows it is reachable only through FIFF_DIR_POINTER.
        if dir_pointer is not None and 0 < dir_pointer and dir_pointer + 16 <= size:
            fh.seek(dir_pointer)
            kind, typ, length, nxt = TAG.unpack(fh.read(16))
            if kind != FIFF_DIR or typ != FIFFT_DIR_ENTRY_STRUCT or length % 16 or dir_pointer + 16 + length > size:
                raise FifError(f"FIFF_DIR_POINTER {dir_pointer} does not point at a FIFF_DIR tag")
            body = payload(dir_pointer, length)
            directory = [struct.unpack_from(">iiii", body, 16 * k) for k in range(length // 16)]
            dir_tag = (dir_pointer, nxt, dir_pointer + 16 + length)
    return {
        "size": size, "tags": tags, "open_blocks": stack, "meas": meas, "channels": channels,
        "records": records, "raw": raw, "dir_pointer": dir_pointer, "directory": directory,
        "dir_tag": dir_tag, "chain_end": chain_end,
    }


def validate_structure(info: dict) -> dict:
    """Check container integrity and the pinned acquisition/processing signature.

    Returns a summary with magnetometer indices and sample counts.
    """
    tags = info["tags"]
    if not tags or tags[0] != (FIFF_FILE_ID, FIFFT_ID_STRUCT, 20, 0):
        raise FifError("file does not start with a FIFF_FILE_ID tag")
    if info["open_blocks"]:
        raise FifError(f"unclosed blocks at end of chain: {info['open_blocks']}")
    if info["dir_tag"] is None or info["dir_pointer"] is None:
        raise FifError("missing FIFF_DIR_POINTER or FIFF_DIR")
    dir_pos, dir_next, dir_end = info["dir_tag"]
    if dir_pos != info["dir_pointer"] or dir_next != NEXT_NONE or dir_end != info["size"]:
        raise FifError("FIFF_DIR is not the pointed-to final tag ending at EOF")
    if info["chain_end"] != dir_pos:
        raise FifError(f"tag chain ends at {info['chain_end']}, not at FIFF_DIR {dir_pos}")
    if [tuple(e) for e in info["directory"]] != tags + [(-1, -1, -1, -1)]:
        raise FifError("tag chain and FIFF_DIR directory disagree")

    meas = info["meas"]
    for kind, expected in EXPECTED_MEAS.items():
        if meas.get(kind) != expected:
            raise FifError(f"measurement info kind={kind}: {meas.get(kind)!r} != {expected!r}")
    channels = info["channels"]
    if len(channels) != meas[FIFF_NCHAN]:
        raise FifError(f"{len(channels)} FIFF_CH_INFO records for NCHAN={meas[FIFF_NCHAN]}")
    names = [ch["name"] for ch in channels]
    if len(set(names)) != len(names):
        raise FifError("duplicate channel names")
    mags = [k for k, ch in enumerate(channels) if ch["kind"] == MEG_CH_KIND and ch["coil_type"] == MAG_COIL]
    grads = [k for k, ch in enumerate(channels) if ch["kind"] == MEG_CH_KIND and ch["coil_type"] == GRAD_COIL]
    if len(mags) != EXPECTED_MAGS or len(grads) != EXPECTED_GRADS:
        raise FifError(f"{len(mags)} magnetometers / {len(grads)} gradiometers")
    for k in mags:
        ch = channels[k]
        if (ch["range"], ch["cal"], ch["unit"], ch["unit_mul"]) != (MAG_RANGE, MAG_CAL, MAG_UNIT, 0) \
                or not MAG_NAME.match(ch["name"]):
            raise FifError(f"magnetometer {ch['name']} has unexpected range/cal/unit/name")

    records = info["records"]
    if len(records) != EXPECTED_RECORDS:
        raise FifError(f"{len(records)} processing records (expected {EXPECTED_RECORDS})")
    for record in records:
        if record["creators"] != [EXPECTED_CREATOR] or record["ct_creators"] != [EXPECTED_CT_CREATOR]:
            raise FifError(f"processing record creators {record['creators']} / {record['ct_creators']}")
        if record["blocks"] != EXPECTED_RECORD_BLOCKS:
            raise FifError(f"processing record blocks {record['blocks']}")
        if record["sss"] != EXPECTED_SSS or record["st"] != EXPECTED_ST:
            raise FifError(f"processing record SSS parameters {record['sss']} / {record['st']}")

    raw = info["raw"]
    if raw["blocks"] != 1:
        raise FifError(f"{raw['blocks']} FIFFB_RAW_DATA blocks")
    if raw["inner_skips"]:
        raise FifError(f"FIFF_DATA_SKIP between buffers (data gap): {raw['inner_skips'][:3]}")
    if raw["first_sample_tags"] or raw["other_kinds"]:
        raise FifError(f"unexpected raw-block tags: first_sample={raw['first_sample_tags']} other={raw['other_kinds'][:5]}")
    if raw["leading_skip"] is None or raw["leading_skip"] < 0:
        raise FifError("raw block does not open with a FIFF_DATA_SKIP")
    buffers = raw["buffers"]
    if not buffers:
        raise FifError("no data buffers")
    row_bytes = meas[FIFF_NCHAN] * 2
    for k, (pos, typ, length) in enumerate(buffers):
        if typ != FIFFT_DAU_PACK16:
            raise FifError(f"buffer at {pos} has type {typ}, not FIFFT_DAU_PACK16")
        if length % row_bytes:
            raise FifError(f"buffer at {pos} is not a whole number of {meas[FIFF_NCHAN]}-channel rows")
        last = k == len(buffers) - 1
        if not (length == FULL_BUFFER_BYTES or (last and 0 < length < FULL_BUFFER_BYTES)):
            raise FifError(f"buffer at {pos} has {length} bytes")
    nsamp = sum(length for _p, _t, length in buffers) // row_bytes
    return {
        "nchan": meas[FIFF_NCHAN], "mags": mags, "names": names, "nsamp": nsamp,
        "n_buffers": len(buffers), "leading_skip": raw["leading_skip"],
        "first_sample": raw["leading_skip"] * (buffers[0][2] // row_bytes),
        "sss_nfree": [record["reported"].get(FIFF_SSS_NFREE) for record in records],
    }


def check_pins(info: dict, summary: dict, row: dict) -> None:
    got = (info["size"], info["dir_pointer"], summary["n_buffers"], summary["leading_skip"])
    want = (row["size_bytes"], row["dir_pointer"], row["n_buffers"], row["leading_skip_buffers"])
    if got != want:
        raise FifError(f"{row['subject']}: (size, dir_pointer, n_buffers, leading_skip) {got} != pinned {want}")


def decode_buffer(raw: bytes) -> array:
    """Big-endian int16 buffer -> native-order array of values."""
    values = array("h")
    values.frombytes(raw)
    if sys.byteorder == "little":
        values.byteswap()
    return values


def le_bytes(values: array) -> bytes:
    if sys.byteorder == "little":
        return values.tobytes()
    swapped = array("h", values)
    swapped.byteswap()
    return swapped.tobytes()


def stream_stats(sample: bytes) -> dict:
    values = array("h")
    values.frombytes(sample)
    if sys.byteorder != "little":
        values.byteswap()
    best = run = 1
    previous = values[0]
    for value in values[1:]:
        if value == previous:
            run += 1
            if run > best:
                best = run
        else:
            run = 1
            previous = value
    return {"minimum": min(values), "maximum": max(values), "distinct_values": len(set(values)),
            "longest_identical_run": best, "value_count": len(values)}


def check_degenerate(sample: bytes, stats: dict, label: str, block_digests: set | None) -> None:
    if stats["distinct_values"] < MIN_DISTINCT_VALUES:
        raise FifError(f"{label}: only {stats['distinct_values']} distinct values")
    if stats["maximum"] - stats["minimum"] < MIN_PEAK_TO_PEAK:
        raise FifError(f"{label}: peak-to-peak {stats['maximum'] - stats['minimum']} codes")
    if stats["longest_identical_run"] > MAX_IDENTICAL_RUN:
        raise FifError(f"{label}: flat run of {stats['longest_identical_run']} samples")
    if stats["minimum"] == INT16_MIN or stats["maximum"] == INT16_MAX:
        raise FifError(f"{label}: int16 saturation")
    step = BLOCK_SAMPLES * 2
    for start in range(0, len(sample) - step + 1, step):
        block = sample[start:start + step]
        if block == block[:2] * BLOCK_SAMPLES:
            raise FifError(f"{label}: constant 1-s block at sample {start // 2}")
        if block_digests is not None:
            digest = hashlib.blake2b(block, digest_size=16).digest()
            if digest in block_digests:
                raise FifError(f"{label}: duplicate 1-s block at sample {start // 2}")
            block_digests.add(digest)


def md5_file(path: Path) -> str:
    digest = hashlib.md5()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 22), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sample_stem(row: dict) -> str:
    return f"{row['subject']}_{row['session']}_task-{row['task']}_{row['run']}"


# ---------------------------------------------------------------- commands

def cmd_check_description(args: argparse.Namespace) -> None:
    meta = json.loads(Path(args.path).read_text(encoding="utf-8"))
    expected = {"Name": "Logical reasoning study", "License": "CC0",
                "DatasetDOI": "10.18112/openneuro.ds003483.v1.0.2"}
    for key, value in expected.items():
        if meta.get(key) != value:
            raise SystemExit(f"dataset_description.json {key}={meta.get(key)!r}, expected {value!r}")
    print("dataset_description ok: License=CC0 DOI=10.18112/openneuro.ds003483.v1.0.2")


def cmd_check_fif(args: argparse.Namespace) -> None:
    rows = {r["subject"]: r for r in read_selection(Path(args.selection))}
    row = rows[args.subject]
    path = Path(args.path)
    info = parse_fif(path)
    summary = validate_structure(info)
    check_pins(info, summary, row)
    # Content sanity on the first, middle and last buffer: every magnetometer
    # column must vary within the buffer.
    buffers = info["raw"]["buffers"]
    with path.open("rb") as fh:
        for pos, _typ, length in {buffers[0], buffers[len(buffers) // 2], buffers[-1]}:
            fh.seek(pos + 16)
            values = decode_buffer(fh.read(length))
            for k in summary["mags"]:
                column = values[k::summary["nchan"]]
                if min(column) == max(column):
                    raise FifError(f"{args.subject}: constant magnetometer column {summary['names'][k]} in buffer at {pos}")
    print(f"fif ok {args.subject}: {summary['n_buffers']} buffers, {summary['nsamp']} samples x "
          f"{len(summary['mags'])} magnetometers, leading skip {summary['leading_skip']}, "
          f"2 x {EXPECTED_CREATOR} tSSS records")


def cmd_build(args: argparse.Namespace) -> None:
    rows = read_selection(Path(args.selection))
    if len(rows) != EXPECTED_RUNS or len({r["subject"] for r in rows}) != EXPECTED_RUNS:
        raise SystemExit("selection.tsv must list six distinct subjects")
    data_root = Path(args.data_root)
    downloads = data_root / "downloads" / DATASET_ID / "fif"
    samples_root = data_root / "samples" / DATASET_ID
    series_dir = samples_root / SERIES_ID
    index_path = data_root / "index" / DATASET_ID / "samples.jsonl"
    stats_path = data_root / "filtered" / DATASET_ID / "ingest_stats.json"
    if samples_root.exists():
        shutil.rmtree(samples_root)
    series_dir.mkdir(parents=True)
    index_rows: list[dict] = []
    block_digests: set = set()
    payload_digests: set = set()
    reference_names = None
    run_summaries = []
    global_min, global_max = INT16_MAX, INT16_MIN
    total_bytes = total_values = 0
    for row in rows:
        path = downloads / Path(row["key"]).name
        if not path.is_file() or path.stat().st_size != row["size_bytes"]:
            raise SystemExit(f"missing or wrong-size download {path}")
        if md5_file(path) != row["md5"]:
            raise SystemExit(f"MD5 mismatch for {path}")
        info = parse_fif(path)
        summary = validate_structure(info)
        check_pins(info, summary, row)
        if reference_names is None:
            reference_names = summary["names"]
        elif summary["names"] != reference_names:
            raise SystemExit(f"{row['subject']}: channel order differs from the first run")
        nchan, mags = summary["nchan"], summary["mags"]
        channels = info["channels"]
        stem = sample_stem(row)
        parts = [series_dir / f"{stem}_{channels[k]['name']}.bin.part" for k in mags]
        outs = [p.open("wb") for p in parts]
        try:
            with path.open("rb") as fh:
                for pos, _typ, length in info["raw"]["buffers"]:
                    fh.seek(pos + 16)
                    raw = fh.read(length)
                    if len(raw) != length:
                        raise SystemExit(f"short buffer read in {path}")
                    values = decode_buffer(raw)
                    for out, k in zip(outs, mags):
                        out.write(le_bytes(values[k::nchan]))
        finally:
            for out in outs:
                out.close()
        for part, k in zip(parts, mags):
            ch = channels[k]
            sample = part.read_bytes()
            label = f"{stem}_{ch['name']}"
            if len(sample) != summary["nsamp"] * 2:
                raise SystemExit(f"{label}: wrote {len(sample)} bytes")
            stats = stream_stats(sample)
            check_degenerate(sample, stats, label, block_digests)
            digest = hashlib.sha256(sample).hexdigest()
            if digest in payload_digests:
                raise SystemExit(f"{label}: duplicate payload")
            payload_digests.add(digest)
            final = part.with_suffix("")
            part.rename(final)
            index_rows.append({
                "dataset_id": DATASET_ID, "series_id": SERIES_ID,
                "sample_path": final.relative_to(data_root).as_posix(),
                "numeric_kind": "int", "bit_width": 16, "endianness": "little",
                "element_size_bytes": 2, "sample_size_bytes": len(sample),
                "value_count": stats["value_count"], "role": "primary",
                "subject": row["subject"], "session": row["session"], "task": row["task"], "run": row["run"],
                "source_key": row["key"], "source_version_id": row["version_id"],
                "channel_name": ch["name"], "ch_info_index": k, "scan_no": ch["scan_no"],
                "log_no": ch["log_no"], "coil_type": ch["coil_type"],
                "range": ch["range"], "cal": ch["cal"], "tesla_per_code": ch["range"] * ch["cal"],
                "sample_rate_hz": 1000.0,
                "fiff_leading_skip_buffers": summary["leading_skip"],
                "fiff_first_sample": summary["first_sample"],
                "minimum": stats["minimum"], "maximum": stats["maximum"],
                "distinct_values": stats["distinct_values"],
                "longest_identical_run": stats["longest_identical_run"],
                "sha256": digest,
            })
            total_bytes += len(sample)
            total_values += stats["value_count"]
            global_min = min(global_min, stats["minimum"])
            global_max = max(global_max, stats["maximum"])
        run_summaries.append({
            "subject": row["subject"], "n_buffers": summary["n_buffers"], "n_samples": summary["nsamp"],
            "duration_s": summary["nsamp"] / 1000.0, "leading_skip_buffers": summary["leading_skip"],
            "fiff_first_sample": summary["first_sample"], "magnetometers": len(mags),
            "sss_nfree": summary["sss_nfree"],
        })
        print(f"built {row['subject']}: {len(mags)} streams x {summary['nsamp']} samples")
    index_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = index_path.with_suffix(".jsonl.tmp")
    with tmp.open("w", encoding="utf-8") as handle:
        for item in index_rows:
            handle.write(json.dumps(item, sort_keys=True) + "\n")
    tmp.replace(index_path)
    stats_path.parent.mkdir(parents=True, exist_ok=True)
    stats_path.write_text(json.dumps({
        "dataset_id": DATASET_ID, "series_id": SERIES_ID, "sample_count": len(index_rows),
        "total_size_bytes": total_bytes, "value_count": total_values,
        "global_minimum": global_min, "global_maximum": global_max,
        "unique_1s_blocks": len(block_digests), "runs": run_summaries,
    }, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"samples": len(index_rows), "bytes": total_bytes, "values": total_values,
                      "min": global_min, "max": global_max}))


def cmd_dir_summary(args: argparse.Namespace) -> None:
    """Summarise a fetched tail (bytes from the dir pointer to EOF) for discover.sh."""
    tail = Path(args.tail).read_bytes()
    kind, typ, length, nxt = TAG.unpack_from(tail, 0)
    if kind != FIFF_DIR or typ != FIFFT_DIR_ENTRY_STRUCT or 16 + length != len(tail) or nxt != NEXT_NONE:
        raise SystemExit("tail is not a final FIFF_DIR tag")
    entries = [struct.unpack_from(">iiii", tail, 16 + 16 * k) for k in range(length // 16)]
    raw_kinds = [e for e in entries if e[0] in (FIFF_DATA_SKIP, FIFF_DATA_BUFFER)]
    first_buffer = next(k for k, e in enumerate(raw_kinds) if e[0] == FIFF_DATA_BUFFER)
    buffers = [e for e in raw_kinds if e[0] == FIFF_DATA_BUFFER]
    print(json.dumps({
        "n_buffers": len(buffers),
        "buffer_types": sorted({(e[1], e[2]) for e in buffers}),
        "leading_skip_positions": [e[3] for e in raw_kinds[:first_buffer]],
        "inner_skips": sum(1 for e in raw_kinds[first_buffer:] if e[0] == FIFF_DATA_SKIP),
    }))


# ---------------------------------------------------------------- self-test

def _synthetic_fif(path: Path, *, buffers: list[list[list[int]]], leading_skip: int = 3,
                   inner_skip: bool = False, records: int = 2, buffer_type: int = FIFFT_DAU_PACK16,
                   corrupt_directory: bool = False) -> dict:
    """Write a small but structurally faithful Vectorview-like FIF file."""
    def i32(value: int) -> bytes:
        return struct.pack(">i", value)

    def fl(value: float) -> bytes:
        return struct.pack(">f", value)

    channels = []
    for triplet in range(102):
        base = 111 + 10 * triplet
        channels.append((MEG_CH_KIND, MAG_RANGE, 3.25e-9, GRAD_COIL, 201, f"MEG{base + 2:04d}"))
        channels.append((MEG_CH_KIND, MAG_RANGE, -3.25e-9, GRAD_COIL, 201, f"MEG{base + 1:04d}"))
        channels.append((MEG_CH_KIND, MAG_RANGE, MAG_CAL, MAG_COIL, MAG_UNIT, f"MEG{base:04d}"))
    for k in range(EXPECTED_NCHAN - 306):
        channels.append((3, 1.0, 1.0, 0, 107, f"STI{k:03d}"))
    tags: list[tuple[int, int, bytes]] = [
        (FIFF_FILE_ID, FIFFT_ID_STRUCT, bytes(20)),
        (FIFF_DIR_POINTER, FIFFT_INT, i32(0)),
        (FIFF_BLOCK_START, FIFFT_INT, i32(FIFFB_MEAS)),
        (FIFF_BLOCK_START, FIFFT_INT, i32(FIFFB_MEAS_INFO)),
        (FIFF_BLOCK_START, FIFFT_INT, i32(108)),
        (FIFF_NCHAN, FIFFT_INT, i32(306)),  # HPI-block decoy, must be ignored
        (FIFF_BLOCK_END, FIFFT_INT, i32(108)),
        (FIFF_BLOCK_START, FIFFT_INT, i32(FIFFB_SUBJECT)),
        (401, FIFFT_STRING, b"secret"),
        (FIFF_BLOCK_END, FIFFT_INT, i32(FIFFB_SUBJECT)),
        (FIFF_SFREQ, FIFFT_FLOAT, fl(1000.0)), (FIFF_LOWPASS, FIFFT_FLOAT, fl(330.0)),
        (FIFF_HIGHPASS, FIFFT_FLOAT, fl(0.1)), (FIFF_LINE_FREQ, FIFFT_FLOAT, fl(50.0)),
        (FIFF_DATA_PACK, FIFFT_INT, i32(FIFFT_DAU_PACK16)), (FIFF_NCHAN, FIFFT_INT, i32(EXPECTED_NCHAN)),
    ]
    for k, (kind, rng, cal, coil, unit, name) in enumerate(channels):
        tags.append((FIFF_CH_INFO, FIFFT_CH_INFO_STRUCT,
                     CH_INFO.pack(k + 1, k + 1, kind, rng, cal, coil, *([0.0] * 12), unit, 0, name.encode())))
    tags.append((FIFF_BLOCK_END, FIFFT_INT, i32(FIFFB_MEAS_INFO)))
    for _ in range(records):
        tags += [
            (FIFF_BLOCK_START, FIFFT_INT, i32(FIFFB_PROCESSING_HISTORY)),
            (FIFF_BLOCK_START, FIFFT_INT, i32(FIFFB_PROCESSING_RECORD)),
            (FIFF_CREATOR, FIFFT_STRING, EXPECTED_CREATOR.encode()),
            (FIFF_BLOCK_START, FIFFT_INT, i32(FIFFB_SSS_INFO)),
            *[(kind, FIFFT_INT, i32(value)) for kind, value in EXPECTED_SSS.items()],
            (FIFF_BLOCK_END, FIFFT_INT, i32(FIFFB_SSS_INFO)),
            (FIFF_BLOCK_START, FIFFT_INT, i32(FIFFB_SSS_ST_INFO)),
            (FIFF_SSS_JOB, FIFFT_INT, i32(10)), (FIFF_SSS_ST_CORR, FIFFT_FLOAT, fl(0.9)),
            (FIFF_SSS_ST_LENGTH, FIFFT_FLOAT, fl(10.0)),
            (FIFF_BLOCK_END, FIFFT_INT, i32(FIFFB_SSS_ST_INFO)),
            (FIFF_BLOCK_START, FIFFT_INT, i32(FIFFB_CHANNEL_DECOUPLER)),
            (FIFF_CREATOR, FIFFT_STRING, EXPECTED_CT_CREATOR.encode()),
            (FIFF_BLOCK_END, FIFFT_INT, i32(FIFFB_CHANNEL_DECOUPLER)),
            (FIFF_BLOCK_START, FIFFT_INT, i32(FIFFB_SSS_CAL)),
            (FIFF_BLOCK_END, FIFFT_INT, i32(FIFFB_SSS_CAL)),
            (FIFF_BLOCK_END, FIFFT_INT, i32(FIFFB_PROCESSING_RECORD)),
            (FIFF_BLOCK_END, FIFFT_INT, i32(FIFFB_PROCESSING_HISTORY)),
        ]
    tags += [(FIFF_BLOCK_START, FIFFT_INT, i32(FIFFB_RAW_DATA)), (FIFF_DATA_SKIP, FIFFT_INT, i32(leading_skip))]
    for k, rows in enumerate(buffers):
        if inner_skip and k == 1:
            tags.append((FIFF_DATA_SKIP, FIFFT_INT, i32(2)))
        flat = [value for row in rows for value in row]
        tags.append((FIFF_DATA_BUFFER, buffer_type, struct.pack(f">{len(flat)}h", *flat)))
    tags += [(FIFF_BLOCK_END, FIFFT_INT, i32(FIFFB_RAW_DATA)), (FIFF_BLOCK_END, FIFFT_INT, i32(FIFFB_MEAS)),
             (108, 0, b"")]
    blob = bytearray()
    entries = []
    for k, (kind, typ, body) in enumerate(tags):
        entries.append((kind, typ, len(body), len(blob)))
        last = k == len(tags) - 1  # the real files end the chain on a FIFF_NOP with next = -1
        blob += TAG.pack(kind, typ, len(body), NEXT_NONE if last else 0) + body
    dir_pos = len(blob)
    struct.pack_into(">i", blob, 36 + 16, dir_pos)
    entries.append((-1, -1, -1, -1))
    if corrupt_directory:
        entries[5] = (entries[5][0], entries[5][1], entries[5][2], entries[5][3] + 1)
    body = b"".join(struct.pack(">iiii", *e) for e in entries)
    blob += TAG.pack(FIFF_DIR, FIFFT_DIR_ENTRY_STRUCT, len(body), NEXT_NONE) + body
    path.write_bytes(bytes(blob))
    return {"size": len(blob), "dir_pointer": dir_pos}


def cmd_selftest(_args: argparse.Namespace) -> None:
    def value(t: int, ch: int) -> int:
        # Exercise sign, byte asymmetry (0x0102) and large magnitudes.
        special = {(0, 2): 258, (1, 2): -2, (2, 5): -30000, (3, 5): 30000}
        return special.get((t, ch), ((t * 7919 + ch * 104729) % 9001) - 4500)

    nsamp_full, nsamp_last = 1000, 250
    buffers = []
    t = 0
    for count in (nsamp_full, nsamp_full, nsamp_last):
        buffers.append([[value(t + i, ch) for ch in range(EXPECTED_NCHAN)] for i in range(count)])
        t += count
    with tempfile.TemporaryDirectory(prefix="fif_selftest_") as tmp:
        tmpdir = Path(tmp)
        good = tmpdir / "good.fif"
        meta = _synthetic_fif(good, buffers=buffers, leading_skip=3)
        info = parse_fif(good)
        summary = validate_structure(info)
        row = {"subject": "sub-test", "size_bytes": meta["size"], "dir_pointer": meta["dir_pointer"],
               "n_buffers": 3, "leading_skip_buffers": 3}
        check_pins(info, summary, row)
        assert summary["mags"] == list(range(2, 306, 3)), summary["mags"][:5]
        assert summary["nsamp"] == 2250 and summary["first_sample"] == 3000, summary
        assert "secret" not in json.dumps(info["channels"])
        streams = {k: bytearray() for k in summary["mags"]}
        with good.open("rb") as fh:
            for pos, _typ, length in info["raw"]["buffers"]:
                fh.seek(pos + 16)
                values = decode_buffer(fh.read(length))
                for k in summary["mags"]:
                    streams[k] += le_bytes(values[k::EXPECTED_NCHAN])
        for k, got in streams.items():
            want = struct.pack(f"<{t}h", *[value(i, k) for i in range(t)])
            assert bytes(got) == want, f"de-interleave mismatch for channel {k}"
        assert streams[2][:4] == b"\x02\x01\xfe\xff", streams[2][:4]
        assert stream_stats(bytes(streams[5]))["minimum"] == -30000
        bad_cases = {
            "inner_skip": {"inner_skip": True},
            "one_record": {"records": 1},
            "int32_buffers": {"buffer_type": 3},
            "directory": {"corrupt_directory": True},
        }
        for name, kwargs in bad_cases.items():
            bad = tmpdir / f"{name}.fif"
            _synthetic_fif(bad, buffers=buffers, **kwargs)
            try:
                validate_structure(parse_fif(bad))
            except FifError:
                continue
            raise AssertionError(f"selftest: {name} corruption was not rejected")
        flat = struct.pack("<1000h", *([7] * 1000)) + bytes(streams[2][:4000])
        try:
            check_degenerate(flat, stream_stats(flat), "flat", None)
        except FifError:
            pass
        else:
            raise AssertionError("selftest: flat stream was not rejected")
    print("selftest ok: tag chain, directory cross-check, meas-info scoping, tSSS history, "
          "leading/inner skips, DAU_PACK16 decode and de-interleave")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("selftest")
    p = sub.add_parser("check-description")
    p.add_argument("--path", required=True)
    p = sub.add_parser("check-fif")
    p.add_argument("--selection", required=True)
    p.add_argument("--subject", required=True)
    p.add_argument("--path", required=True)
    p = sub.add_parser("build")
    p.add_argument("--selection", required=True)
    p.add_argument("--data-root", required=True)
    p = sub.add_parser("dir-summary")
    p.add_argument("--tail", required=True)
    args = parser.parse_args()
    handlers = {"selftest": cmd_selftest, "check-description": cmd_check_description,
                "check-fif": cmd_check_fif, "build": cmd_build, "dir-summary": cmd_dir_summary}
    try:
        handlers[args.command](args)
    except FifError as exc:
        raise SystemExit(f"FIF validation failed: {exc}")


if __name__ == "__main__":
    main()
