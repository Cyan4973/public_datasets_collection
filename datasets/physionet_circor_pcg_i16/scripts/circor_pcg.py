#!/usr/bin/env python3
"""CirCor DigiScope phonocardiogram (PhysioNet circor-heart-sound 1.0.3) helper.

Subcommands:
  selftest         validate both WAV decoders and the WFDB header parser on
                   synthetic inputs (run by build.sh and verify.sh)
  plan             download helper: promote verified .part files, drop bad
                   files, and write a curl config for what is still missing
  check-downloads  download helper: semantic validation of every fetched
                   WAV/.hea pair and an inventory JSON
  build            emit one little-endian int16 sample per auscultation
                   recording plus the sample index and ingest stats
  verify           independently re-decode every source recording (stdlib
                   `wave` module) and check samples, index, stats and manifest

Pure standard library; no network access (download.sh does all transfers).
"""
from __future__ import annotations

import argparse
import array
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import statistics
import struct
import sys
import tomllib
import wave

DATASET_ID = "physionet_circor_pcg_i16"
SERIES_ID = "circor_pcg_pcm_i16"
VERSION = "1.0.3"
EXPECTED_RECORDS = 3163
EXPECTED_PATIENTS = 942
EXPECTED_WAV_BYTES = 578_849_274
EXPECTED_HEA_BYTES = 187_976
SAMPLE_RATE = 4000
BITS = 16
SITE_ORDER = {"AV": 0, "PV": 1, "TV": 2, "MV": 3, "Phc": 4}
RECORD_RE = re.compile(r"^training_data/((\d+)_(AV|PV|TV|MV|Phc)(?:_(\d+))?)$")
MIN_DISTINCT_VALUES = 16          # fewer distinct codes than this = degenerate
MAX_EXCLUDED_FRACTION = 0.01      # more exclusions than this = recipe failure
FULL_SCALE = (-32768, 32767)


# --------------------------------------------------------------------------
# shared inventory helpers
# --------------------------------------------------------------------------

def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_checksums(download_dir: Path) -> dict[str, str]:
    sums: dict[str, str] = {}
    text = (download_dir / "SHA256SUMS.txt").read_text(encoding="utf-8")
    for line in text.splitlines():
        if not line.strip():
            continue
        match = re.fullmatch(r"([0-9a-fA-F]{64})\s+\*?(?:\./)?(\S.*)", line.strip())
        if not match:
            raise SystemExit(f"malformed SHA256SUMS line: {line!r}")
        sums[match.group(2)] = match.group(1).lower()
    return sums


def sort_key(record: dict) -> tuple[int, int, int]:
    return (record["patient"], SITE_ORDER[record["site"]], record["repeat"])


def load_records(download_dir: Path) -> list[dict]:
    """Parse the official RECORDS list and return records in canonical order."""
    lines = [line.strip() for line in (download_dir / "RECORDS").read_text(encoding="utf-8").splitlines() if line.strip()]
    records = []
    seen = set()
    for line in lines:
        match = RECORD_RE.fullmatch(line)
        if not match:
            raise SystemExit(f"unexpected RECORDS entry: {line!r}")
        name = match.group(1)
        if name in seen:
            raise SystemExit(f"duplicate RECORDS entry: {name}")
        seen.add(name)
        records.append(
            {
                "recording_id": name,
                "patient": int(match.group(2)),
                "site": match.group(3),
                "repeat": int(match.group(4) or 0),
                "wav": f"training_data/{name}.wav",
                "hea": f"training_data/{name}.hea",
            }
        )
    if len(records) != EXPECTED_RECORDS:
        raise SystemExit(f"RECORDS count changed: {len(records)} != {EXPECTED_RECORDS}")
    patients = {record["patient"] for record in records}
    if len(patients) != EXPECTED_PATIENTS:
        raise SystemExit(f"patient count changed: {len(patients)} != {EXPECTED_PATIENTS}")
    records.sort(key=sort_key)
    return records


# --------------------------------------------------------------------------
# build-side decoders: explicit RIFF chunk walk + WFDB header parser
# --------------------------------------------------------------------------

def parse_wav(blob: bytes) -> dict:
    """Walk RIFF chunks; require PCM mono 4000 Hz 16-bit; return data span."""
    if len(blob) < 12 or blob[0:4] != b"RIFF" or blob[8:12] != b"WAVE":
        raise ValueError("not a RIFF/WAVE file")
    riff_size = struct.unpack_from("<I", blob, 4)[0]
    if riff_size + 8 != len(blob):
        raise ValueError(f"RIFF size {riff_size} + 8 != file size {len(blob)}")
    offset = 12
    fmt = None
    data_offset = data_size = None
    chunks = []
    while offset + 8 <= len(blob):
        chunk_id = blob[offset:offset + 4]
        chunk_size = struct.unpack_from("<I", blob, offset + 4)[0]
        body = offset + 8
        if body + chunk_size > len(blob):
            raise ValueError(f"chunk {chunk_id!r} at {offset} overruns file")
        chunks.append(chunk_id.decode("latin-1"))
        if chunk_id == b"fmt ":
            if fmt is not None:
                raise ValueError("duplicate fmt chunk")
            if chunk_size < 16:
                raise ValueError("fmt chunk too short")
            fmt = struct.unpack_from("<HHIIHH", blob, body)
        elif chunk_id == b"data":
            if data_offset is not None:
                raise ValueError("duplicate data chunk")
            data_offset, data_size = body, chunk_size
        offset = body + chunk_size + (chunk_size & 1)
    if offset != len(blob):
        raise ValueError(f"trailing {len(blob) - offset} bytes after last chunk")
    if fmt is None or data_offset is None:
        raise ValueError("missing fmt or data chunk")
    tag, channels, rate, byte_rate, block_align, bits = fmt
    if (tag, channels, rate, bits) != (1, 1, SAMPLE_RATE, BITS):
        raise ValueError(f"unexpected fmt tag={tag} channels={channels} rate={rate} bits={bits}")
    if byte_rate != SAMPLE_RATE * 2 or block_align != 2:
        raise ValueError(f"inconsistent byte_rate={byte_rate} block_align={block_align}")
    if data_size == 0 or data_size % 2:
        raise ValueError(f"data chunk size {data_size} is empty or odd")
    return {"data_offset": data_offset, "data_size": data_size, "chunks": chunks}


def parse_hea(text: str, recording_id: str) -> dict:
    """Parse the single-signal WFDB header shipped next to each WAV."""
    lines = [line.strip() for line in text.splitlines() if line.strip() and not line.lstrip().startswith("#")]
    if len(lines) != 2:
        raise ValueError(f"expected record line + 1 signal line, got {len(lines)} lines")
    rec = lines[0].split()
    if len(rec) < 4 or rec[0] != recording_id or rec[1] != "1":
        raise ValueError(f"bad record line {lines[0]!r}")
    if float(rec[2].split("/")[0]) != SAMPLE_RATE:
        raise ValueError(f"bad sampling frequency {rec[2]!r}")
    nsamp = int(rec[3])
    sig = lines[1].split()
    if len(sig) < 9 or sig[0] != f"{recording_id}.wav":
        raise ValueError(f"bad signal line {lines[1]!r}")
    fmt_match = re.fullmatch(r"16\+(\d+)", sig[1])
    if not fmt_match:
        raise ValueError(f"signal format is not 16+offset: {sig[1]!r}")
    if sig[3] != "16":
        raise ValueError(f"ADC resolution is not 16: {sig[3]!r}")
    return {"nsamp": nsamp, "byte_offset": int(fmt_match.group(1)), "description": " ".join(sig[8:])}


def decode_record(blob: bytes, hea_text: str, record: dict) -> bytes:
    """Return the validated little-endian int16 PCM payload of one recording."""
    info = parse_wav(blob)
    hea = parse_hea(hea_text, record["recording_id"])
    if hea["byte_offset"] != info["data_offset"]:
        raise ValueError(f"header byte offset {hea['byte_offset']} != data chunk offset {info['data_offset']}")
    if hea["nsamp"] * 2 != info["data_size"]:
        raise ValueError(f"header sample count {hea['nsamp']} != data bytes {info['data_size']} / 2")
    if hea["description"] != record["site"]:
        raise ValueError(f"header site {hea['description']!r} != filename site {record['site']!r}")
    return blob[info["data_offset"]:info["data_offset"] + info["data_size"]]


def as_int16(payload: bytes) -> array.array:
    values = array.array("h")
    values.frombytes(payload)
    if sys.byteorder != "little":
        values.byteswap()
    return values


def degeneracy(values: array.array) -> dict:
    distinct = len(set(values))
    lo, hi = min(values), max(values)
    return {
        "distinct_values": distinct,
        "min": lo,
        "max": hi,
        "zero_fraction": values.count(0) / len(values),
        "rail_count": values.count(FULL_SCALE[0]) + values.count(FULL_SCALE[1]),
        "degenerate": distinct < MIN_DISTINCT_VALUES,
    }


# --------------------------------------------------------------------------
# verify-side decoders (independent: stdlib wave module + token parsing)
# --------------------------------------------------------------------------

def wave_decode(blob: bytes) -> tuple[bytes, int]:
    with wave.open(io.BytesIO(blob), "rb") as handle:
        if handle.getcomptype() != "NONE":
            raise ValueError("compressed WAV")
        if (handle.getnchannels(), handle.getsampwidth(), handle.getframerate()) != (1, 2, SAMPLE_RATE):
            raise ValueError(
                f"wave params channels={handle.getnchannels()} width={handle.getsampwidth()} rate={handle.getframerate()}"
            )
        frames = handle.getnframes()
        payload = handle.readframes(frames)
    if len(payload) != frames * 2:
        raise ValueError("wave readframes returned a short payload")
    return payload, frames


def verify_hea(text: str, recording_id: str, site: str) -> tuple[int, int]:
    tokens = [line.split() for line in text.splitlines() if line.split() and not line.startswith("#")]
    head, signal = tokens[0], tokens[1]
    assert len(tokens) == 2, f"{recording_id}: header line count"
    assert head[0] == recording_id and int(head[1]) == 1 and int(float(head[2])) == SAMPLE_RATE, f"{recording_id}: record line"
    fmt, _, offset = signal[1].partition("+")
    assert signal[0] == recording_id + ".wav" and fmt == "16" and signal[3] == "16", f"{recording_id}: signal line"
    assert signal[-1] == site, f"{recording_id}: header site {signal[-1]} != {site}"
    return int(head[3]), int(offset)


# --------------------------------------------------------------------------
# selftest
# --------------------------------------------------------------------------

def synth_wav(values: list[int], *, tag=1, channels=1, rate=SAMPLE_RATE, bits=16, extra_chunk=False, drop_data=False) -> bytes:
    payload = struct.pack(f"<{len(values)}h", *values)
    block = channels * bits // 8
    fmt = struct.pack("<HHIIHH", tag, channels, rate, rate * block, block, bits)
    body = b"WAVE" + b"fmt " + struct.pack("<I", len(fmt)) + fmt
    if extra_chunk:
        info = b"INFOabc"  # odd length exercises the RIFF pad byte
        body += b"LIST" + struct.pack("<I", len(info)) + info + b"\x00"
    if not drop_data:
        body += b"data" + struct.pack("<I", len(payload)) + payload
    return b"RIFF" + struct.pack("<I", len(body)) + body


def synth_hea(name: str, nsamp: int, offset: int, site: str) -> str:
    return f"{name} 1 4000 {nsamp}\n{name}.wav 16+{offset} 1 16 0 0 0 0 {site}\n"


def selftest() -> None:
    values = [0, 1, -1, 32767, -32768, 1234, -4321] + [((i * 7919) % 65536) - 32768 for i in range(993)]
    record = {"recording_id": "12345_MV_2", "site": "MV"}
    for extra in (False, True):
        blob = synth_wav(values, extra_chunk=extra)
        offset = parse_wav(blob)["data_offset"]
        assert offset == (44 if not extra else 60), offset
        payload = decode_record(blob, synth_hea("12345_MV_2", len(values), offset, "MV"), record)
        assert list(as_int16(payload)) == values
        wave_payload, frames = wave_decode(blob)
        assert wave_payload == payload and frames == len(values)
        assert verify_hea(synth_hea("12345_MV_2", len(values), offset, "MV"), "12345_MV_2", "MV") == (len(values), offset)
    good = synth_wav(values)
    bad_cases = {
        "stereo": (synth_wav(values + [0], channels=2), synth_hea("12345_MV_2", len(values), 44, "MV")),
        "8 kHz": (synth_wav(values, rate=8000), synth_hea("12345_MV_2", len(values), 44, "MV")),
        "float tag": (synth_wav(values, tag=3), synth_hea("12345_MV_2", len(values), 44, "MV")),
        "no data": (synth_wav(values, drop_data=True), synth_hea("12345_MV_2", len(values), 44, "MV")),
        "truncated": (good[:-2], synth_hea("12345_MV_2", len(values), 44, "MV")),
        "count mismatch": (good, synth_hea("12345_MV_2", len(values) - 1, 44, "MV")),
        "offset mismatch": (good, synth_hea("12345_MV_2", len(values), 46, "MV")),
        "site mismatch": (good, synth_hea("12345_MV_2", len(values), 44, "AV")),
        "name mismatch": (good, synth_hea("12345_AV_2", len(values), 44, "MV")),
    }
    for label, (blob, hea) in bad_cases.items():
        try:
            decode_record(blob, hea, record)
        except (ValueError, struct.error):
            continue
        raise AssertionError(f"selftest: decoder accepted invalid input ({label})")
    assert degeneracy(as_int16(struct.pack("<4h", 5, 5, 5, 5)))["degenerate"]
    assert not degeneracy(as_int16(struct.pack(f"<{len(values)}h", *values)))["degenerate"]
    print("selftest=ok decoders=riff_walk,stdlib_wave cases=2_valid,9_invalid")


# --------------------------------------------------------------------------
# download helpers
# --------------------------------------------------------------------------

def cfg_quote(text: str) -> str:
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def cmd_plan(args: argparse.Namespace) -> None:
    download_dir = Path(args.download_dir)
    sums = load_checksums(download_dir)
    records = load_records(download_dir)
    (download_dir / "training_data").mkdir(parents=True, exist_ok=True)
    pending = []
    promoted = verified = removed = 0
    for record in records:
        for key in ("hea", "wav"):
            relative = record[key]
            expected = sums.get(relative)
            if expected is None:
                raise SystemExit(f"SHA256SUMS lacks {relative}")
            final = download_dir / relative
            part = final.with_name(final.name + ".part")
            if final.is_file():
                if sha256_file(final) == expected:
                    verified += 1
                    part.unlink(missing_ok=True)
                    continue
                print(f"checksum_mismatch_removed file={relative}")
                final.unlink()
                removed += 1
            if part.is_file():
                if sha256_file(part) == expected:
                    part.rename(final)
                    promoted += 1
                    continue
                part.unlink()
                removed += 1
            pending.append((relative, part))
    with open(args.config, "w", encoding="utf-8") as handle:
        for relative, part in pending:
            handle.write(f"url = {cfg_quote(args.base_url + '/' + relative)}\n")
            handle.write(f"output = {cfg_quote(str(part))}\n")
    print(f"plan verified={verified} promoted={promoted} removed={removed} pending={len(pending)}")
    with open(args.pending_out, "w", encoding="utf-8") as handle:
        handle.write(f"{len(pending)}\n")


def cmd_check_downloads(args: argparse.Namespace) -> None:
    download_dir = Path(args.download_dir)
    sums = load_checksums(download_dir)
    records = load_records(download_dir)
    wav_bytes = hea_bytes = 0
    inventory = []
    for record in records:
        wav_path = download_dir / record["wav"]
        hea_path = download_dir / record["hea"]
        blob = wav_path.read_bytes()
        hea_raw = hea_path.read_bytes()
        if sha256_bytes(blob) != sums[record["wav"]]:
            raise SystemExit(f"checksum mismatch {record['wav']}")
        if sha256_bytes(hea_raw) != sums[record["hea"]]:
            raise SystemExit(f"checksum mismatch {record['hea']}")
        hea_text = hea_raw.decode("ascii")
        try:
            payload = decode_record(blob, hea_text, record)
        except (ValueError, struct.error) as exc:
            raise SystemExit(f"semantic check failed for {record['recording_id']}: {exc}")
        wav_bytes += len(blob)
        hea_bytes += len(hea_raw)
        inventory.append(
            {
                "recording_id": record["recording_id"],
                "wav_bytes": len(blob),
                "wav_sha256": sums[record["wav"]],
                "pcm_values": len(payload) // 2,
            }
        )
    if wav_bytes != EXPECTED_WAV_BYTES or hea_bytes != EXPECTED_HEA_BYTES:
        raise SystemExit(f"aggregate size changed: wav={wav_bytes} hea={hea_bytes}")
    payload = {
        "dataset_id": DATASET_ID,
        "version": VERSION,
        "records": len(inventory),
        "wav_bytes": wav_bytes,
        "hea_bytes": hea_bytes,
        "inventory": inventory,
    }
    (download_dir / "download_inventory.json").write_text(json.dumps(payload, indent=1) + "\n", encoding="utf-8")
    print(f"download_check=ok records={len(inventory)} wav_bytes={wav_bytes} hea_bytes={hea_bytes}")


# --------------------------------------------------------------------------
# build
# --------------------------------------------------------------------------

def cmd_build(args: argparse.Namespace) -> None:
    selftest()
    download_dir = Path(args.download_dir)
    data_root = Path(args.data_root)
    series_dir = Path(args.samples_root) / SERIES_ID
    sums = load_checksums(download_dir)
    records = load_records(download_dir)
    if series_dir.exists():
        shutil.rmtree(series_dir)
    series_dir.mkdir(parents=True)
    index_path = Path(args.index)
    stats_path = Path(args.stats)
    index_path.parent.mkdir(parents=True, exist_ok=True)
    stats_path.parent.mkdir(parents=True, exist_ok=True)

    rows = []
    excluded = []
    seen_payloads: dict[str, str] = {}
    aggregate = hashlib.sha256()
    total_values = rail_values = 0
    site_counts: dict[str, int] = {}
    for number, record in enumerate(records, 1):
        blob = (download_dir / record["wav"]).read_bytes()
        if sha256_bytes(blob) != sums[record["wav"]]:
            raise SystemExit(f"checksum mismatch {record['wav']}")
        hea_raw = (download_dir / record["hea"]).read_bytes()
        if sha256_bytes(hea_raw) != sums[record["hea"]]:
            raise SystemExit(f"checksum mismatch {record['hea']}")
        try:
            payload = decode_record(blob, hea_raw.decode("ascii"), record)
        except (ValueError, struct.error) as exc:
            raise SystemExit(f"decode failed for {record['recording_id']}: {exc}")
        values = as_int16(payload)
        quality = degeneracy(values)
        digest = sha256_bytes(payload)
        if quality["degenerate"]:
            excluded.append({"recording_id": record["recording_id"], "reason": f"fewer than {MIN_DISTINCT_VALUES} distinct values", **quality})
            continue
        if digest in seen_payloads:
            excluded.append({"recording_id": record["recording_id"], "reason": f"payload identical to {seen_payloads[digest]}"})
            continue
        seen_payloads[digest] = record["recording_id"]
        out_bytes = values.tobytes() if sys.byteorder == "little" else _swapped(values)
        sample_path = series_dir / f"{record['recording_id']}.bin"
        tmp_path = sample_path.with_suffix(".bin.tmp")
        tmp_path.write_bytes(out_bytes)
        tmp_path.rename(sample_path)
        aggregate.update(out_bytes)
        total_values += len(values)
        rail_values += quality["rail_count"]
        site_counts[record["site"]] = site_counts.get(record["site"], 0) + 1
        rows.append(
            {
                "dataset_id": DATASET_ID,
                "series_id": SERIES_ID,
                "sample_path": os.path.relpath(sample_path, data_root),
                "numeric_kind": "int",
                "bit_width": 16,
                "endianness": "little",
                "element_size_bytes": 2,
                "sample_size_bytes": len(out_bytes),
                "value_count": len(values),
                "recording_id": record["recording_id"],
                "auscultation_site": record["site"],
                "sample_rate_hz": SAMPLE_RATE,
                "min": quality["min"],
                "max": quality["max"],
                "distinct_values": quality["distinct_values"],
                "full_scale_count": quality["rail_count"],
                "source_wav_sha256": sums[record["wav"]],
                "sample_sha256": digest,
            }
        )
        if number % 500 == 0:
            print(f"progress records={number}/{len(records)} emitted={len(rows)}")
    if len(excluded) > MAX_EXCLUDED_FRACTION * len(records):
        raise SystemExit(f"too many excluded recordings: {len(excluded)}")
    tmp_index = index_path.with_suffix(".jsonl.tmp")
    with tmp_index.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")
    tmp_index.rename(index_path)
    counts = sorted(row["value_count"] for row in rows)
    distinct = sorted(row["distinct_values"] for row in rows)
    stats = {
        "dataset_id": DATASET_ID,
        "series_id": SERIES_ID,
        "version": VERSION,
        "source_records": len(records),
        "sample_count": len(rows),
        "excluded": excluded,
        "total_values": total_values,
        "total_size_bytes": total_values * 2,
        "median_values": statistics.median(counts),
        "min_values": counts[0],
        "max_values": counts[-1],
        "site_counts": site_counts,
        "patients": len({row["recording_id"].split("_")[0] for row in rows}),
        "global_min": min(row["min"] for row in rows),
        "global_max": max(row["max"] for row in rows),
        "distinct_values_min": distinct[0],
        "distinct_values_median": statistics.median(distinct),
        "full_scale_values": rail_values,
        "full_scale_fraction": rail_values / total_values,
        "recordings_touching_full_scale": sum(1 for row in rows if row["full_scale_count"]),
        "aggregate_sha256": aggregate.hexdigest(),
    }
    stats_path.write_text(json.dumps(stats, indent=1) + "\n", encoding="utf-8")
    print(
        f"build=ok samples={len(rows)} excluded={len(excluded)} values={total_values} bytes={total_values * 2} "
        f"median_values={stats['median_values']} full_scale_fraction={stats['full_scale_fraction']:.6g} "
        f"aggregate_sha256={stats['aggregate_sha256']}"
    )


def _swapped(values: array.array) -> bytes:
    copy = array.array("h", values)
    copy.byteswap()
    return copy.tobytes()


# --------------------------------------------------------------------------
# verify (independent re-derivation)
# --------------------------------------------------------------------------

def cmd_verify(args: argparse.Namespace) -> None:
    selftest()
    download_dir = Path(args.download_dir)
    data_root = Path(args.data_root)
    series_dir = Path(args.samples_root) / SERIES_ID
    manifest = tomllib.loads(Path(args.manifest).read_text(encoding="utf-8"))
    series = [s for s in manifest["series"] if s["id"] == SERIES_ID]
    assert len(series) == 1, "manifest must declare the series exactly once"
    series = series[0]
    assert manifest["dataset_id"] == DATASET_ID
    assert (series["role"], series["numeric_kind"], series["bit_width"], series["endianness"]) == ("primary", "int", 16, "little")
    assert [s for s in manifest["series"] if s["role"] == "primary"] == [series], "unexpected extra primary series"

    sums = {}
    for line in (download_dir / "SHA256SUMS.txt").read_text(encoding="utf-8").splitlines():
        parts = line.split()
        if len(parts) == 2:
            sums[parts[1]] = parts[0]
    names = sorted(
        (line.strip().split("/", 1)[1] for line in (download_dir / "RECORDS").read_text(encoding="utf-8").splitlines() if line.strip()),
        key=lambda n: (int(n.split("_")[0]), SITE_ORDER[n.split("_")[1]], int(n.split("_")[2]) if n.count("_") == 2 else 0),
    )
    assert len(names) == EXPECTED_RECORDS == len(set(names)), "RECORDS inventory changed"

    rows = [json.loads(line) for line in Path(args.index).read_text(encoding="utf-8").splitlines() if line.strip()]
    stats = json.loads(Path(args.stats).read_text(encoding="utf-8"))
    by_id = {row["recording_id"]: row for row in rows}
    assert len(by_id) == len(rows), "duplicate recording ids in index"

    expected_excluded = []
    emitted_order = []
    seen_payload: dict[str, str] = {}
    total_values = rail_values = 0
    aggregate = hashlib.sha256()
    for name in names:
        site = name.split("_")[1]
        blob = (download_dir / "training_data" / f"{name}.wav").read_bytes()
        assert hashlib.sha256(blob).hexdigest() == sums[f"training_data/{name}.wav"], f"{name}: source checksum"
        hea_raw = (download_dir / "training_data" / f"{name}.hea").read_bytes()
        assert hashlib.sha256(hea_raw).hexdigest() == sums[f"training_data/{name}.hea"], f"{name}: header checksum"
        nsamp, offset = verify_hea(hea_raw.decode("ascii"), name, site)
        payload, frames = wave_decode(blob)
        assert frames == nsamp, f"{name}: wave frames {frames} != header samples {nsamp}"
        assert blob[offset:offset + 2 * nsamp] == payload and len(blob) == offset + 2 * nsamp, f"{name}: header offset/length disagree with wave payload"
        decoded = struct.unpack(f"<{nsamp}h", payload)
        distinct = len(set(decoded))
        digest = hashlib.sha256(payload).hexdigest()
        if distinct < MIN_DISTINCT_VALUES:
            expected_excluded.append(name)
            assert name not in by_id, f"{name}: degenerate recording was emitted"
            continue
        if digest in seen_payload:
            expected_excluded.append(name)
            assert name not in by_id, f"{name}: duplicate of {seen_payload[digest]} was emitted"
            continue
        seen_payload[digest] = name
        row = by_id.get(name)
        assert row is not None, f"{name}: valid recording missing from index"
        sample_path = data_root / row["sample_path"]
        assert sample_path.parent == series_dir and sample_path.name == f"{name}.bin", f"{name}: unexpected sample path"
        sample = sample_path.read_bytes()
        assert sample == payload, f"{name}: sample bytes differ from the independently decoded PCM payload"
        lo, hi = min(decoded), max(decoded)
        rails = decoded.count(FULL_SCALE[0]) + decoded.count(FULL_SCALE[1])
        assert lo < hi and distinct >= MIN_DISTINCT_VALUES, f"{name}: constant or degenerate sample"
        expected_row = {
            "dataset_id": DATASET_ID, "series_id": SERIES_ID, "numeric_kind": "int", "bit_width": 16,
            "endianness": "little", "element_size_bytes": 2, "sample_size_bytes": len(sample), "value_count": nsamp,
            "auscultation_site": site, "sample_rate_hz": SAMPLE_RATE, "min": lo, "max": hi,
            "distinct_values": distinct, "full_scale_count": rails, "sample_sha256": digest,
            "source_wav_sha256": sums[f"training_data/{name}.wav"],
        }
        for key, value in expected_row.items():
            assert row[key] == value, f"{name}: index field {key}={row[key]!r} != {value!r}"
        emitted_order.append(name)
        total_values += nsamp
        rail_values += rails
        aggregate.update(sample)

    assert [row["recording_id"] for row in rows] == emitted_order, "index order or membership differs from re-derivation"
    assert sorted(item["recording_id"] for item in stats["excluded"]) == sorted(expected_excluded), "exclusion list differs"
    assert len(expected_excluded) <= MAX_EXCLUDED_FRACTION * len(names), "too many exclusions"
    on_disk = sorted(path.name for path in series_dir.iterdir())
    assert on_disk == sorted(f"{name}.bin" for name in emitted_order), "stray or missing files in the sample directory"
    assert series["sample_count"] == len(rows) == stats["sample_count"], (
        f"sample_count manifest={series['sample_count']} index={len(rows)} stats={stats['sample_count']}"
    )
    assert series["total_size_bytes"] == 2 * total_values == stats["total_size_bytes"], (
        f"total_size_bytes manifest={series['total_size_bytes']} derived={2 * total_values} stats={stats['total_size_bytes']}"
    )
    assert aggregate.hexdigest() == stats["aggregate_sha256"], "aggregate output hash differs from build stats"
    counts = sorted(row["value_count"] for row in rows)
    median = statistics.median(counts)
    assert median >= 1000 and total_values >= 10_000, "below acceptance floor"
    assert 2 * total_values <= 1_000_000_000, "primary output exceeds 1 GB cap"
    sites = sorted({row["auscultation_site"] for row in rows})
    print(
        f"verify=ok samples={len(rows)} excluded={len(expected_excluded)} values={total_values} bytes={2 * total_values} "
        f"median_values={median} min_values={counts[0]} max_values={counts[-1]} sites={','.join(sites)} "
        f"full_scale_values={rail_values} full_scale_fraction={rail_values / total_values:.6g} "
        f"recordings_touching_full_scale={sum(1 for row in rows if row['full_scale_count'])} "
        f"aggregate_sha256={aggregate.hexdigest()}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("selftest")
    plan = sub.add_parser("plan")
    plan.add_argument("--download-dir", required=True)
    plan.add_argument("--base-url", required=True)
    plan.add_argument("--config", required=True)
    plan.add_argument("--pending-out", required=True)
    check = sub.add_parser("check-downloads")
    check.add_argument("--download-dir", required=True)
    for name in ("build", "verify"):
        cmd = sub.add_parser(name)
        cmd.add_argument("--download-dir", required=True)
        cmd.add_argument("--samples-root", required=True)
        cmd.add_argument("--index", required=True)
        cmd.add_argument("--stats", required=True)
        cmd.add_argument("--data-root", required=True)
        if name == "verify":
            cmd.add_argument("--manifest", required=True)
    args = parser.parse_args()
    if args.command == "selftest":
        selftest()
    elif args.command == "plan":
        cmd_plan(args)
    elif args.command == "check-downloads":
        cmd_check_downloads(args)
    elif args.command == "build":
        cmd_build(args)
    else:
        try:
            cmd_verify(args)
        except AssertionError as exc:
            raise SystemExit(f"verify FAILED: {exc}")


if __name__ == "__main__":
    main()
