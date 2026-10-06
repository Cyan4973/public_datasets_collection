#!/usr/bin/env python3
"""CTF res4/meg4 helpers for the THINGS-MEG axial-gradiometer int32 recipe.

Pure standard library. Network I/O is done by download.sh with curl; this
module only parses what curl fetched, plans byte ranges, validates streams,
and builds canonical little-endian samples.

res4 layout follows MNE-Python mne/io/ctf/res4.py (_read_res4) and
constants.py (FUNNY_POS = 1844): big-endian header with no_samples int32 @1288,
no_channels int16 @1292, sample_rate float64 @1296, no_trials int16 @1312,
run-description length int32 @1836; the run description (rdlen bytes) starts
at 1844 and is followed by nfilt int16 and nfilt variable-length filter
records (float64 freq, int32 class, int32 type, int16 npar, npar float64),
then nchan 32-byte channel names, then nchan 1328-byte channel records
(sensor_type_index int16, original_run_no int16, coil_type int32,
proper_gain/qgain/io_gain/io_offset float64, num_coils int16,
grad_order_no int16, pad int32, 2 x 8 coil records of 80 bytes), then ncomp
int16 and ncomp 1992-byte compensation records.

meg4 layout follows MNE-Python mne/io/ctf/ctf.py: 8-byte magic 'MEG41CP\\0'
then, per trial, channel-major big-endian int32 blocks of no_samples values.
"""
from __future__ import annotations

from array import array
import argparse
import collections
import csv
import hashlib
import json
import os
from pathlib import Path
import shutil
import struct
import sys

DATASET_ID = "openneuro_ds004212_things_meg_ctf_i32"
SERIES_ID = "ctf275_axial_gradiometer_counts_i32"
BUCKET_URL = "https://s3.amazonaws.com/openneuro.org"
RES4_MAGIC = b"MEG42RS\x00"
MEG4_MAGIC = b"MEG41CP\x00"
MEG4_HEADER_BYTES = 8
FUNNY_POS = 1844
RDLEN_POS = 1836
CHANNEL_NAME_BYTES = 32
CHANNEL_RECORD_BYTES = 1328  # 48-byte header + 2 * 8 coils * 80 bytes
COMP_RECORD_BYTES = 32 + 4 + 4 + 2 + 50 * 31 + 50 * 8  # 1992
MEG_AXIAL_GRADIOMETER_TYPE = 5

# Pinned acquisition geometry of every THINGS-MEG main-task run.
EXPECTED_NSAMP = 417_600
EXPECTED_NCHAN = 310
EXPECTED_SFREQ = 1200.0
EXPECTED_TRIALS = 1
EXPECTED_RES4_BYTES = 3_188_345
EXPECTED_MEG4_BYTES = MEG4_HEADER_BYTES + EXPECTED_NCHAN * EXPECTED_NSAMP * 4
EXPECTED_TYPE_COUNTS = {5: 272, 1: 19, 0: 9, 18: 8, 17: 1, 20: 1}
EXPECTED_GRAD_ORDER = 3
EXPECTED_QGAIN = 1_048_576.0
EXPECTED_RUNS = 24
STREAM_BYTES = EXPECTED_NSAMP * 4

# Fixed gradiometer subset: one mirrored left/right pair per CTF sensor
# region (frontal, central, temporal, occipital). Names are matched on the
# prefix before the '-<serial>' suffix and re-located in every run's res4.
CHANNELS = ("MLF32", "MRF32", "MLC32", "MRC32", "MLT33", "MRT33", "MLO32", "MRO32")
EXPECTED_SAMPLES = EXPECTED_RUNS * len(CHANNELS)
EXPECTED_TOTAL_BYTES = EXPECTED_SAMPLES * STREAM_BYTES

# Degeneracy thresholds shared by download checks and build.
BLOCK_SAMPLES = 1200  # one second
MIN_DISTINCT_VALUES = 1000
MAX_IDENTICAL_RUN = 120  # 0.1 s; real streams show runs of <= 3
MIN_PEAK_TO_PEAK = 1000
INT32_MIN, INT32_MAX = -(2**31), 2**31 - 1


class FormatError(ValueError):
    pass


def cstring(raw: bytes) -> str:
    return raw.split(b"\x00", 1)[0].decode("latin-1")


def parse_res4(raw: bytes, *, require_complete: bool = True) -> dict:
    """Parse a CTF res4 header per the MNE-Python layout."""
    if len(raw) < FUNNY_POS + 2:
        raise FormatError(f"res4 too short: {len(raw)} bytes")
    if raw[:8] != RES4_MAGIC:
        raise FormatError(f"bad res4 magic {raw[:8]!r}")
    nsamp, nchan = struct.unpack_from(">ih", raw, 1288)
    sfreq, epoch_time = struct.unpack_from(">dd", raw, 1296)
    (no_trials,) = struct.unpack_from(">h", raw, 1312)
    (pre_trig_pts,) = struct.unpack_from(">i", raw, 1316)
    (rdlen,) = struct.unpack_from(">i", raw, RDLEN_POS)
    if nsamp <= 0 or nchan <= 0 or no_trials <= 0 or not 0 <= rdlen < 1_000_000:
        raise FormatError(f"implausible res4 geometry nsamp={nsamp} nchan={nchan} trials={no_trials} rdlen={rdlen}")
    position = FUNNY_POS + rdlen
    (nfilt,) = struct.unpack_from(">h", raw, position)
    position += 2
    if not 0 <= nfilt < 100:
        raise FormatError(f"implausible filter count {nfilt}")
    filters = []
    for _ in range(nfilt):
        freq, klass, kind, npar = struct.unpack_from(">diih", raw, position)
        position += 18
        if not 0 <= npar < 100:
            raise FormatError(f"implausible filter parameter count {npar}")
        params = struct.unpack_from(f">{npar}d", raw, position)
        position += 8 * npar
        filters.append({"freq": freq, "class": klass, "type": kind, "params": list(params)})
    names_offset = position
    channels_offset = names_offset + CHANNEL_NAME_BYTES * nchan
    comp_offset = channels_offset + CHANNEL_RECORD_BYTES * nchan
    if comp_offset + 2 > len(raw):
        raise FormatError("res4 truncated inside the channel table")
    channels = []
    for index in range(nchan):
        name = cstring(raw[names_offset + CHANNEL_NAME_BYTES * index:names_offset + CHANNEL_NAME_BYTES * (index + 1)])
        record = channels_offset + CHANNEL_RECORD_BYTES * index
        (sensor_type, original_run, coil_type, proper_gain, qgain, io_gain, io_offset,
         num_coils, grad_order) = struct.unpack_from(">hhiddddhh", raw, record)
        channels.append({
            "index": index, "name": name, "label": name.split("-", 1)[0],
            "sensor_type_index": sensor_type, "original_run_no": original_run,
            "coil_type": coil_type, "proper_gain": proper_gain, "qgain": qgain,
            "io_gain": io_gain, "io_offset": io_offset, "num_coils": num_coils,
            "grad_order_no": grad_order,
        })
    (ncomp,) = struct.unpack_from(">h", raw, comp_offset)
    comp_end = comp_offset + 2 + COMP_RECORD_BYTES * ncomp
    if require_complete and comp_end != len(raw):
        raise FormatError(f"res4 compensation table ends at {comp_end}, file has {len(raw)} bytes")
    return {
        "nsamp": nsamp, "nchan": nchan, "sfreq": sfreq, "epoch_time": epoch_time,
        "no_trials": no_trials, "pre_trig_pts": pre_trig_pts, "rdlen": rdlen,
        "nfilt": nfilt, "filters": filters, "names_offset": names_offset,
        "channels_offset": channels_offset, "comp_offset": comp_offset,
        "ncomp": ncomp, "channels": channels,
    }


def channel_byte_range(nsamp: int, nchan: int, channel_index: int, trial: int = 0) -> tuple[int, int]:
    """Inclusive byte range of one channel block in a meg4 file (MNE ctf.py)."""
    if not 0 <= channel_index < nchan:
        raise FormatError(f"channel index {channel_index} outside 0..{nchan - 1}")
    start = MEG4_HEADER_BYTES + (trial * nsamp * nchan + channel_index * nsamp) * 4
    return start, start + nsamp * 4 - 1


def validate_run_header(res4: dict) -> None:
    """Pinned per-run checks: geometry, type-count self-check, compensation grade."""
    geometry = (res4["nsamp"], res4["nchan"], res4["sfreq"], res4["no_trials"])
    if geometry != (EXPECTED_NSAMP, EXPECTED_NCHAN, EXPECTED_SFREQ, EXPECTED_TRIALS):
        raise FormatError(f"unexpected run geometry {geometry}")
    counts = dict(collections.Counter(ch["sensor_type_index"] for ch in res4["channels"]))
    if counts != EXPECTED_TYPE_COUNTS:
        raise FormatError(f"sensor type self-check failed: {counts}")
    grads = [ch for ch in res4["channels"] if ch["sensor_type_index"] == MEG_AXIAL_GRADIOMETER_TYPE]
    orders = {ch["grad_order_no"] for ch in grads}
    if orders != {EXPECTED_GRAD_ORDER}:
        raise FormatError(f"mixed or unexpected gradient compensation grades {sorted(orders)}")
    if {ch["qgain"] for ch in grads} != {EXPECTED_QGAIN}:
        raise FormatError("unexpected gradiometer qgain")
    labels = [ch["label"] for ch in res4["channels"]]
    if len(set(labels)) != len(labels):
        raise FormatError("duplicate channel labels in res4")


def select_channels(res4: dict) -> list[dict]:
    by_label = {ch["label"]: ch for ch in res4["channels"]}
    chosen = []
    for label in CHANNELS:
        channel = by_label.get(label)
        if channel is None:
            raise FormatError(f"channel {label} missing from res4")
        if channel["sensor_type_index"] != MEG_AXIAL_GRADIOMETER_TYPE or channel["grad_order_no"] != EXPECTED_GRAD_ORDER:
            raise FormatError(f"channel {label} is not a grade-{EXPECTED_GRAD_ORDER} axial gradiometer")
        chosen.append(channel)
    return chosen


def read_selection(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    if len(rows) != EXPECTED_RUNS:
        raise SystemExit(f"selection has {len(rows)} runs, expected {EXPECTED_RUNS}")
    seen = set()
    for row in rows:
        key = (row["subject"], row["session"], row["run"])
        if key in seen:
            raise SystemExit(f"duplicate run in selection: {key}")
        seen.add(key)
        if int(row["res4_size"]) != EXPECTED_RES4_BYTES or int(row["meg4_size"]) != EXPECTED_MEG4_BYTES:
            raise SystemExit(f"selection size pin changed for {key}")
    return rows


def read_streams(path: Path) -> dict[str, dict]:
    if not path.is_file():
        return {}
    with path.open(newline="", encoding="utf-8") as handle:
        return {row["stream_id"]: row for row in csv.DictReader(handle, delimiter="\t")}


def run_tag(row: dict) -> str:
    return f"{row['subject']}_{row['session']}_{row['run']}"


def res4_path(download_dir: Path, row: dict) -> Path:
    return download_dir / "res4" / Path(row["res4_key"]).name


def stream_path(download_dir: Path, stream_id: str) -> Path:
    return download_dir / "streams" / f"{stream_id}.i32be"


def versioned_url(key: str, version_id: str) -> str:
    return f"{BUCKET_URL}/{key}?versionId={version_id}"


def plan_rows(selection: list[dict], download_dir: Path, pinned: dict[str, dict]) -> list[dict]:
    reference_labels = None
    plan = []
    for row in selection:
        raw = res4_path(download_dir, row).read_bytes()
        if len(raw) != EXPECTED_RES4_BYTES or hashlib.md5(raw).hexdigest() != row["res4_md5"]:
            raise SystemExit(f"res4 identity mismatch for {run_tag(row)}")
        res4 = parse_res4(raw)
        validate_run_header(res4)
        labels = [ch["label"] for ch in res4["channels"]]
        if reference_labels is None:
            reference_labels = labels
        elif labels != reference_labels:
            raise SystemExit(f"channel set/order differs in {run_tag(row)}")
        expected_size = MEG4_HEADER_BYTES + res4["nchan"] * res4["nsamp"] * 4 * res4["no_trials"]
        if expected_size != int(row["meg4_size"]):
            raise SystemExit(f"meg4 size pin disagrees with res4 geometry for {run_tag(row)}")
        for channel in select_channels(res4):
            start, end = channel_byte_range(res4["nsamp"], res4["nchan"], channel["index"])
            stream_id = f"{run_tag(row)}_{channel['label']}"
            pin = pinned.get(stream_id)
            if pin is not None and (int(pin["channel_index"]), int(pin["byte_start"]), int(pin["byte_end"])) != (channel["index"], start, end):
                raise SystemExit(f"pinned layout differs from res4 for {stream_id}")
            plan.append({
                "stream_id": stream_id, "subject": row["subject"], "session": row["session"],
                "run": row["run"], "channel_label": channel["label"], "channel_name": channel["name"],
                "channel_index": channel["index"], "byte_start": start, "byte_end": end,
                "byte_length": end - start + 1,
                "url": versioned_url(row["meg4_key"], row["meg4_version_id"]),
                "sha256_be": (pin or {}).get("sha256_be", ""),
                "proper_gain": channel["proper_gain"], "qgain": channel["qgain"],
                "grad_order_no": channel["grad_order_no"],
            })
    if len(plan) != EXPECTED_SAMPLES:
        raise SystemExit(f"plan has {len(plan)} streams, expected {EXPECTED_SAMPLES}")
    return plan


def decode_be(raw: bytes) -> array:
    values = array("i")
    if values.itemsize != 4:
        raise SystemExit("platform int is not 32-bit")
    values.frombytes(raw)
    if sys.byteorder == "little":
        values.byteswap()
    return values


def encode_le(values: array) -> bytes:
    out = array("i", values)
    if sys.byteorder == "big":
        out.byteswap()
    return out.tobytes()


def stream_profile(values: array) -> dict:
    longest = current = 1
    for left, right in zip(values, values[1:]):
        if left == right:
            current += 1
            if current > longest:
                longest = current
        else:
            current = 1
    minimum, maximum = min(values), max(values)
    blocks = len(values) // BLOCK_SAMPLES
    constant_blocks = sum(
        1 for b in range(blocks)
        if min(values[b * BLOCK_SAMPLES:(b + 1) * BLOCK_SAMPLES]) == max(values[b * BLOCK_SAMPLES:(b + 1) * BLOCK_SAMPLES])
    )
    return {
        "value_count": len(values), "minimum": minimum, "maximum": maximum,
        "peak_to_peak": maximum - minimum, "distinct_values": len(set(values)),
        "longest_identical_run": longest, "constant_blocks": constant_blocks,
        "saturated_values": values.count(INT32_MIN) + values.count(INT32_MAX),
        "beyond_int16_values": sum(1 for v in values if v < -32768 or v > 32767),
    }


def check_profile(stream_id: str, profile: dict) -> None:
    problems = []
    if profile["value_count"] != EXPECTED_NSAMP:
        problems.append(f"value_count {profile['value_count']}")
    if profile["distinct_values"] < MIN_DISTINCT_VALUES:
        problems.append(f"only {profile['distinct_values']} distinct values")
    if profile["longest_identical_run"] > MAX_IDENTICAL_RUN:
        problems.append(f"flat run of {profile['longest_identical_run']} samples")
    if profile["peak_to_peak"] < MIN_PEAK_TO_PEAK:
        problems.append(f"peak-to-peak {profile['peak_to_peak']}")
    if profile["constant_blocks"]:
        problems.append(f"{profile['constant_blocks']} constant 1-s blocks")
    if profile["saturated_values"]:
        problems.append(f"{profile['saturated_values']} int32-saturated values")
    if problems:
        raise SystemExit(f"degenerate stream {stream_id}: {'; '.join(problems)}")


def sha256_hex(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def write_tsv(path: Path, rows: list[dict], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as handle:
        handle.write("\t".join(fields) + "\n")
        for row in rows:
            handle.write("\t".join(str(row[f]) for f in fields) + "\n")
    os.replace(tmp, path)


# The shell loop reads this with IFS=$'\t'; tab is IFS whitespace, so empty
# fields would collapse. Every column is therefore non-empty ("-" = unpinned).
PLAN_FIELDS = ["stream_id", "byte_start", "byte_end", "byte_length", "url", "expected_sha256"]


# ---------------------------------------------------------------- commands

def cmd_check_description(args: argparse.Namespace) -> None:
    raw = args.path.read_bytes()
    description = json.loads(raw)
    if description.get("Name") != "THINGS-MEG":
        raise SystemExit(f"unexpected dataset name {description.get('Name')!r}")
    if description.get("License") != "CC0":
        raise SystemExit(f"expected License=CC0, found {description.get('License')!r}")
    if description.get("DatasetDOI") != "doi:10.18112/openneuro.ds004212.v3.0.0":
        raise SystemExit(f"unexpected DatasetDOI {description.get('DatasetDOI')!r}")
    print(f"license={description['License']} doi={description['DatasetDOI']} sha256={sha256_hex(raw)}")


def cmd_plan(args: argparse.Namespace) -> None:
    selection = read_selection(args.selection)
    plan = plan_rows(selection, args.download_dir, read_streams(args.streams))
    for row in plan:
        row["expected_sha256"] = row["sha256_be"] or "-"
        if any(str(row[field]) == "" for field in PLAN_FIELDS):
            raise SystemExit(f"empty plan field for {row['stream_id']}")
    write_tsv(args.out, plan, PLAN_FIELDS)
    pinned = sum(1 for row in plan if row["sha256_be"])
    print(f"planned {len(plan)} streams from {len(selection)} res4 headers; {pinned} with pinned sha256")


def cmd_check_stream(args: argparse.Namespace) -> None:
    raw = args.path.read_bytes()
    if len(raw) != STREAM_BYTES:
        raise SystemExit(f"{args.stream_id}: {len(raw)} bytes, expected {STREAM_BYTES}")
    digest = sha256_hex(raw)
    if args.expected_sha256 and digest != args.expected_sha256:
        raise SystemExit(f"{args.stream_id}: sha256 {digest} != pinned {args.expected_sha256}")
    check_profile(args.stream_id, stream_profile(decode_be(raw)))


def cmd_audit(args: argparse.Namespace) -> None:
    """Re-check every downloaded stream and record the acquisition inventory."""
    selection = read_selection(args.selection)
    pinned = read_streams(args.streams)
    plan = plan_rows(selection, args.download_dir, pinned)
    inventory, digests, unpinned = [], set(), 0
    for row in plan:
        raw = stream_path(args.download_dir, row["stream_id"]).read_bytes()
        if len(raw) != row["byte_length"]:
            raise SystemExit(f"missing or truncated stream {row['stream_id']}")
        digest = sha256_hex(raw)
        if row["sha256_be"]:
            if digest != row["sha256_be"]:
                raise SystemExit(f"sha256 mismatch for {row['stream_id']}")
        else:
            unpinned += 1
        if digest in digests:
            raise SystemExit(f"duplicate stream payload {row['stream_id']}")
        digests.add(digest)
        profile = stream_profile(decode_be(raw))
        check_profile(row["stream_id"], profile)
        inventory.append({**row, "sha256_be": digest, **profile})
    (args.download_dir / "acquisition.json").write_text(json.dumps(inventory, indent=1, sort_keys=True) + "\n")
    if args.write_streams:
        write_tsv(args.write_streams, inventory, STREAM_FIELDS)
    print(f"audited {len(inventory)} streams ({unpinned} without pinned sha256), {len(inventory) * STREAM_BYTES} bytes")
    if args.require_pinned and unpinned:
        raise SystemExit("streams.tsv lacks pinned sha256 values")


STREAM_FIELDS = [
    "stream_id", "subject", "session", "run", "channel_label", "channel_name",
    "channel_index", "byte_start", "byte_end", "sha256_be",
]


def cmd_build(args: argparse.Namespace) -> None:
    selection = read_selection(args.selection)
    pinned = read_streams(args.streams)
    if len(pinned) != EXPECTED_SAMPLES or any(not row["sha256_be"] for row in pinned.values()):
        raise SystemExit("streams.tsv must pin sha256_be for every stream before build")
    plan = plan_rows(selection, args.download_dir, pinned)
    if args.samples_dir.exists():
        shutil.rmtree(args.samples_dir)
    series_dir = args.samples_dir / SERIES_ID
    series_dir.mkdir(parents=True)
    rows, profiles, block_hashes = [], [], set()
    duplicate_blocks = 0
    for item in plan:
        source = stream_path(args.download_dir, item["stream_id"])
        raw = source.read_bytes()
        if len(raw) != item["byte_length"] or sha256_hex(raw) != item["sha256_be"]:
            raise SystemExit(f"downloaded stream changed: {item['stream_id']}")
        values = decode_be(raw)
        profile = stream_profile(values)
        check_profile(item["stream_id"], profile)
        for b in range(len(values) // BLOCK_SAMPLES):
            digest = hashlib.sha256(raw[b * BLOCK_SAMPLES * 4:(b + 1) * BLOCK_SAMPLES * 4]).digest()
            duplicate_blocks += digest in block_hashes
            block_hashes.add(digest)
        canonical = encode_le(values)
        output = series_dir / f"{item['stream_id']}.bin"
        output.write_bytes(canonical)
        out_sha = sha256_hex(canonical)
        profiles.append(profile)
        rows.append({
            "dataset_id": DATASET_ID, "series_id": SERIES_ID, "role": "primary",
            "sample_path": output.relative_to(args.data_root).as_posix(),
            "source_sample": source.relative_to(args.data_root).as_posix(),
            "source_url": item["url"], "source_byte_start": item["byte_start"],
            "source_byte_end": item["byte_end"],
            "subject": item["subject"], "session": item["session"], "run": item["run"],
            "channel_label": item["channel_label"], "channel_name": item["channel_name"],
            "channel_index": item["channel_index"],
            "sensor_type_index": MEG_AXIAL_GRADIOMETER_TYPE,
            "grad_order_no": item["grad_order_no"], "proper_gain": item["proper_gain"],
            "qgain": item["qgain"], "sample_rate_hz": EXPECTED_SFREQ,
            "numeric_kind": "int", "bit_width": 32, "endianness": "little",
            "element_size_bytes": 4, "value_count": len(values),
            "sample_size_bytes": len(canonical),
            "sample_format": "raw homogeneous little-endian signed-int32 CTF SQUID gradiometer ADC counts",
            "sample_rank": 1, "sample_shape": [len(values)], "sample_axes": ["time_sample"],
            "natural_record_kind": "complete_ctf_meg4_channel_run_stream",
            "minimum": profile["minimum"], "maximum": profile["maximum"],
            "distinct_values": profile["distinct_values"],
            "sha256_be_source": item["sha256_be"], "sha256": out_sha,
        })
    if duplicate_blocks:
        raise SystemExit(f"{duplicate_blocks} duplicate 1-s blocks across streams")
    total_values = sum(p["value_count"] for p in profiles)
    summary = {
        "dataset_id": DATASET_ID, "series_id": SERIES_ID, "sample_count": len(rows),
        "runs": len(selection), "channels": list(CHANNELS),
        "subjects": sorted({r["subject"] for r in rows}),
        "sessions": sorted({r["session"] for r in rows}),
        "values_per_sample": EXPECTED_NSAMP, "sample_rate_hz": EXPECTED_SFREQ,
        "value_count": total_values, "total_size_bytes": sum(r["sample_size_bytes"] for r in rows),
        "global_minimum": min(p["minimum"] for p in profiles),
        "global_maximum": max(p["maximum"] for p in profiles),
        "minimum_distinct_values": min(p["distinct_values"] for p in profiles),
        "maximum_identical_run": max(p["longest_identical_run"] for p in profiles),
        "minimum_peak_to_peak": min(p["peak_to_peak"] for p in profiles),
        "beyond_int16_fraction": round(sum(p["beyond_int16_values"] for p in profiles) / total_values, 6),
        "unique_block_payloads": len(block_hashes),
        "output_sha256": sorted(r["sha256"] for r in rows),
    }
    if (summary["sample_count"], summary["total_size_bytes"]) != (EXPECTED_SAMPLES, EXPECTED_TOTAL_BYTES):
        raise SystemExit("realized sample count/size disagree with the pinned scope")
    args.index.parent.mkdir(parents=True, exist_ok=True)
    args.index.write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in rows), encoding="utf-8")
    args.stats.parent.mkdir(parents=True, exist_ok=True)
    args.stats.write_text(json.dumps(summary, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in summary.items() if k != "output_sha256"}, indent=1, sort_keys=True))


# ---------------------------------------------------------------- self-test

def synthetic_res4(nsamp: int, labels_types: list[tuple[str, int, int]], run_desc: bytes,
                   filters: list[tuple[float, int, int, list[float]]], ncomp: int) -> bytes:
    head = bytearray(FUNNY_POS)
    head[0:8] = RES4_MAGIC
    struct.pack_into(">ih", head, 1288, nsamp, len(labels_types))
    struct.pack_into(">dd", head, 1296, 1200.0, nsamp / 1200.0)
    struct.pack_into(">h", head, 1312, 1)
    struct.pack_into(">i", head, RDLEN_POS, len(run_desc))
    body = bytearray(run_desc)
    body += struct.pack(">h", len(filters))
    for freq, klass, kind, params in filters:
        body += struct.pack(">diih", freq, klass, kind, len(params)) + struct.pack(f">{len(params)}d", *params)
    for label, _type, _grade in labels_types:
        body += label.encode().ljust(CHANNEL_NAME_BYTES, b"\x00")
    for index, (_label, sensor_type, grade) in enumerate(labels_types):
        record = bytearray(CHANNEL_RECORD_BYTES)
        struct.pack_into(">hhiddddhh", record, 0, sensor_type, 0, 0, 1e9 + index, EXPECTED_QGAIN, 1.0, 0.0, 2, grade)
        record[100:108] = b"\xa5" * 8  # coil filler must not leak into fields
        body += record
    body += struct.pack(">h", ncomp) + b"\x00" * (COMP_RECORD_BYTES * ncomp)
    return bytes(head + body)


def cmd_selftest(_args: argparse.Namespace) -> None:
    nsamp = 50
    layout = [("SCLK01-177", 17, 0), ("BG1-1609", 0, 0), ("G11-1609", 1, 0),
              ("MLC11-1609", 5, 3), ("MRO22-1609", 5, 3), ("UPPT001", 20, 0)]
    for run_desc, filters in ((b"\x00", []), (b"synthetic run desc\x00", [(0.5, 2, 1, [3.0]), (300.0, 1, 2, [1.0, 2.0, 3.0])])):
        raw = synthetic_res4(nsamp, layout, run_desc, filters, ncomp=3)
        res4 = parse_res4(raw)
        assert res4["nsamp"] == nsamp and res4["nchan"] == len(layout) and res4["no_trials"] == 1
        assert res4["rdlen"] == len(run_desc) and res4["nfilt"] == len(filters)
        assert res4["names_offset"] == FUNNY_POS + len(run_desc) + 2 + sum(18 + 8 * len(f[3]) for f in filters)
        assert [ch["name"] for ch in res4["channels"]] == [name for name, _t, _g in layout]
        assert [ch["sensor_type_index"] for ch in res4["channels"]] == [t for _n, t, _g in layout]
        assert [ch["grad_order_no"] for ch in res4["channels"]] == [g for _n, _t, g in layout]
        assert [ch["label"] for ch in res4["channels"]][3] == "MLC11"
        assert res4["channels"][4]["proper_gain"] == 1e9 + 4 and res4["ncomp"] == 3
        # meg4: channel c holds values c*1000 + sample - 600000 (exercise sign).
        meg4 = bytearray(MEG4_MAGIC)
        expected = {}
        for c in range(len(layout)):
            vals = [c * 1000 + s - 600_000 + (s % 7) * 70_001 for s in range(nsamp)]
            expected[c] = vals
            meg4 += struct.pack(f">{nsamp}i", *vals)
        assert len(meg4) == MEG4_HEADER_BYTES + len(layout) * nsamp * 4
        for c in range(len(layout)):
            start, end = channel_byte_range(nsamp, len(layout), c)
            chunk = bytes(meg4[start:end + 1])
            values = decode_be(chunk)
            assert list(values) == expected[c]
            assert list(struct.unpack(f"<{nsamp}i", encode_le(values))) == expected[c]
        # Truncation and wrong magic must fail.
        for broken in (raw[:-1], b"XXXXXXXX" + raw[8:]):
            try:
                parse_res4(broken)
            except FormatError:
                pass
            else:
                raise AssertionError("broken res4 accepted")
    # Second trial offset follows MNE trial-major layout.
    assert channel_byte_range(10, 3, 1, trial=1) == (8 + (30 + 10) * 4, 8 + (30 + 10) * 4 + 39)
    print("selftest ok: res4 variable-offset parse, meg4 channel ranges, BE->LE int32 round trip")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("selftest")
    p = sub.add_parser("check-description")
    p.add_argument("--path", type=Path, required=True)
    for name in ("plan", "audit", "build"):
        p = sub.add_parser(name)
        p.add_argument("--selection", type=Path, required=True)
        p.add_argument("--streams", type=Path, required=True)
        p.add_argument("--download-dir", type=Path, required=True)
        if name == "plan":
            p.add_argument("--out", type=Path, required=True)
        if name == "audit":
            p.add_argument("--write-streams", type=Path)
            p.add_argument("--require-pinned", action="store_true")
        if name == "build":
            p.add_argument("--samples-dir", type=Path, required=True)
            p.add_argument("--index", type=Path, required=True)
            p.add_argument("--stats", type=Path, required=True)
            p.add_argument("--data-root", type=Path, required=True)
    p = sub.add_parser("check-stream")
    p.add_argument("--stream-id", required=True)
    p.add_argument("--path", type=Path, required=True)
    p.add_argument("--expected-sha256", default="")
    args = parser.parse_args()
    {
        "selftest": cmd_selftest, "check-description": cmd_check_description,
        "plan": cmd_plan, "audit": cmd_audit, "build": cmd_build,
        "check-stream": cmd_check_stream,
    }[args.command](args)


if __name__ == "__main__":
    main()
