#!/usr/bin/env python3
"""Download, decode, build, inspect, and verify pinned MetaClean uint32 FCS data."""
from __future__ import annotations

from array import array
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import statistics
import subprocess
import sys
import zlib


DATASET_ID = "zenodo_metaclean_fcs_u32"
SERIES_ID = "metaclean_event_measurements_u32"
RECORD_ID = 10_639_508
RECORD_TITLE = "MetaClean3.0: Robust and accurate removal of low-quality event measurements in cytometry."
RECORD_API = f"https://zenodo.org/api/records/{RECORD_ID}"
USER_AGENT = "openzl-public-datasets-metaclean/1.0"
PARAMETER_COUNT = 67
HOUSEKEEPING_NAMES = ("TLSW", "TMSW", "Event Info")
SELECTED_PARAMETER_NAMES = (
    "FSC 488/10-H", "FSC 488/10-A", "FSC 488/10-W",
    "FSC 405/10 (spd)-H", "FSC 405/10 (spd)-A", "FSC 405/10 (spd)-W",
    "SSC 488/10-H", "SSC 488/10-A", "SSC 488/10-W",
    "525/35-488 nm-H", "525/35-488 nm-A", "525/35-488 nm-W",
    "593/52-488 nm-H", "593/52-488 nm-A", "593/52-488 nm-W",
    "750LP-488 nm-H", "750LP-488 nm-A", "750LP-488 nm-W",
    "692/80-488 nm-H", "692/80-488 nm-A", "692/80-488 nm-W",
    "750LP-561 nm-H", "750LP-561 nm-A", "750LP-561 nm-W",
    "692/80-561 nm-H", "692/80-561 nm-A", "692/80-561 nm-W",
    "583/30-561 nm-H", "583/30-561 nm-A", "583/30-561 nm-W",
    "615/24-561 nm-H", "615/24-561 nm-A", "615/24-561 nm-W",
    "670/30-405 nm-H", "670/30-405 nm-A", "670/30-405 nm-W",
    "720/60-405 nm-H", "720/60-405 nm-A", "720/60-405 nm-W",
    "750LP-405 nm-H", "750LP-405 nm-A", "750LP-405 nm-W",
    "460/22-405 nm-H", "460/22-405 nm-A", "460/22-405 nm-W",
    "420/10-405 nm-H", "420/10-405 nm-A", "420/10-405 nm-W",
    "615/24-405 nm-H", "615/24-405 nm-A", "615/24-405 nm-W",
    "525/50-405 nm-H", "525/50-405 nm-A", "525/50-405 nm-W",
    "720/60-640 nm-H", "720/60-640 nm-A", "720/60-640 nm-W",
    "750LP-640 nm-H", "750LP-640 nm-A", "750LP-640 nm-W",
    "670/30-640 nm-H", "670/30-640 nm-A", "670/30-640 nm-W",
    "TIME",
)
EXPECTED_FILES = {
    "CleanPositiveControl_bubbles_Panel_step3a_fcs_folder_Step3-A.fcs": {
        "size": 5_495_522, "md5": "a5f6c6f42d6752562d4be767215890a4", "events": 20_468,
        "output": "step3a_u32le.bin", "sha256": "d6ec13e33535615fd77f4566f96cfe91a43729df63bd069156cdb7752d186bcc",
    },
    "CleanPositiveControl_bubbles_Panel_step3e_fcs_folder_Step3-E.fcs": {
        "size": 3_956_130, "md5": "19f81378fbc604efc7cc67dc53190f68", "events": 14_724,
        "output": "step3e_u32le.bin", "sha256": "f47dd92446399604800849b39a1b02b584ac10f4780a7ec1f899cabcf0b04a5d",
    },
    "CleanPositiveControl_bubbles_Panel_step3g_fcs_folder_Step3-G.fcs": {
        "size": 2_803_194, "md5": "fed38b19dfa2f21a1a7b719167a2f060", "events": 10_422,
        "output": "step3g_u32le.bin", "sha256": "98acde4d71ffda5688e49ffe31a3af8893eb21f20b0fcac9204edfd7a9a26545",
    },
    "CleanPositiveControl_lowmedhigh_Panel_step2a_fcs_folder_Step2-A.fcs": {
        "size": 7_738_682, "md5": "260f1957d9481ed5297aff9035e97bbb", "events": 28_838,
        "output": "step2a_u32le.bin", "sha256": "27ed262cf878df9777433ce3ada074524fde90f80a3b563fb9d00b9fc9887d8e",
    },
    "CleanPositiveControl_lowmedhigh_Panel_step2b_fcs_folder_Step2-B.fcs": {
        "size": 8_072_342, "md5": "83cfca450305f5158b0d7f452996af45", "events": 30_083,
        "output": "step2b_u32le.bin", "sha256": "8aaf95578634ea363c599783c8c85a789a3009b3ad38bb4eccad12e490f02666",
    },
    "CleanPositiveControl_lowmedhigh_Panel_step2c_fcs_folder_Step2-C.fcs": {
        "size": 7_238_058, "md5": "0c847b068bc7e383b2a2bfa8658723f4", "events": 26_970,
        "output": "step2c_u32le.bin", "sha256": "26e8dab2b7d582cc3931b3ca9d68f0cb020c7a5cb9d8a24c1e04a421c498fd9d",
    },
    "CleanPositiveControl_lowtohigh_Panel_step1a_fcs_folder_Step1-A.fcs": {
        "size": 6_665_074, "md5": "f1e8af92bd08ac7c14e94c3675a5b358", "events": 24_832,
        "output": "step1a_u32le.bin", "sha256": "a3448b5ec2514b20a1c2bde3f9e7482ac7cdad3e787d78ca8afc2e5ba470a471",
    },
    "CleanPositiveControl_lowtohigh_Panel_step1b_fcs_folder_Step1-B.fcs": {
        "size": 6_421_998, "md5": "d3005042bbe9e9d10503aa415b972d70", "events": 23_925,
        "output": "step1b_u32le.bin", "sha256": "43aa1d3cac7ece4803827cce714683c626be326e6b4c825e4be6105faa364d67",
    },
    "CleanPositiveControl_lowtohigh_Panel_step1c_fcs_folder_Step1-C.fcs": {
        "size": 7_129_786, "md5": "9806929b5dbfd691abc9922a889a6dd5", "events": 26_566,
        "output": "step1c_u32le.bin", "sha256": "7827b76bed707232f9a6d4d70bd1976496d7c5d7c55c9278ec9a9d838123f67a",
    },
}


def file_hash(path: Path, algorithm: str) -> str:
    digest = hashlib.new(algorithm)
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def curl(url: str, output: Path, *, max_bytes: int, timeout: int) -> None:
    command = [
        "curl", "--fail", "--silent", "--show-error", "--location",
        "--retry", "5", "--retry-delay", "2", "--max-time", str(timeout),
        "--max-filesize", str(max_bytes), "--user-agent", USER_AGENT,
        "--output", str(output), url,
    ]
    result = subprocess.run(command, check=False)
    if result.returncode != 0:
        raise SystemExit(f"curl failed with exit status {result.returncode}: {url}")


def metadata_record(download_dir: Path) -> dict[str, object]:
    path = download_dir / f"record_{RECORD_ID}.json"
    if not path.is_file():
        raise SystemExit("missing Zenodo metadata; run download.sh first")
    record = json.loads(path.read_text(encoding="utf-8"))
    metadata = record.get("metadata", {})
    if not isinstance(metadata, dict):
        raise SystemExit("Zenodo metadata is not an object")
    if int(record.get("id", 0)) != RECORD_ID or metadata.get("title") != RECORD_TITLE:
        raise SystemExit("unexpected Zenodo record identity")
    if metadata.get("license", {}).get("id") != "cc-by-4.0":
        raise SystemExit("Zenodo record no longer declares CC BY 4.0")
    description = re.sub(r"<[^>]+>", " ", str(metadata.get("description", ""))).lower()
    if "positive control fcs files" not in description or "metaclean3.0" not in description:
        raise SystemExit("Zenodo record no longer documents the positive-control FCS material")
    return record


def download(args: argparse.Namespace) -> None:
    args.download_dir.mkdir(parents=True, exist_ok=True)
    metadata_path = args.download_dir / f"record_{RECORD_ID}.json"
    part = metadata_path.with_suffix(".json.part")
    curl(RECORD_API, part, max_bytes=20_000_000, timeout=180)
    record = json.loads(part.read_text(encoding="utf-8"))
    metadata = record.get("metadata", {})
    if int(record.get("id", 0)) != RECORD_ID or metadata.get("title") != RECORD_TITLE:
        raise SystemExit("unexpected Zenodo record identity")
    if metadata.get("license", {}).get("id") != "cc-by-4.0":
        raise SystemExit("Zenodo record no longer declares CC BY 4.0")
    files = record.get("files", [])
    if not isinstance(files, list):
        raise SystemExit("Zenodo files field is not a list")
    fcs_items = {
        str(item.get("key", "")): item for item in files
        if isinstance(item, dict) and str(item.get("key", "")).lower().endswith(".fcs")
    }
    if set(fcs_items) != set(EXPECTED_FILES):
        raise SystemExit("exact Zenodo FCS inventory changed")
    os.replace(part, metadata_path)
    inventory = []
    for index, (name, expected) in enumerate(EXPECTED_FILES.items(), start=1):
        item = fcs_items[name]
        size = int(expected["size"])
        md5 = str(expected["md5"])
        if int(item.get("size", 0)) != size or item.get("checksum") != f"md5:{md5}":
            raise SystemExit(f"Zenodo identity changed for {name}")
        links = item.get("links", {})
        url = str(links.get("self") or links.get("download") or "") if isinstance(links, dict) else ""
        if not url:
            raise SystemExit(f"missing URL for {name}")
        target = args.download_dir / name
        if target.is_file() and target.stat().st_size == size and file_hash(target, "md5") == md5:
            print(f"[{index}/{len(EXPECTED_FILES)}] verified cached {name}")
        else:
            target_part = target.with_suffix(target.suffix + ".part")
            target_part.unlink(missing_ok=True)
            print(f"[{index}/{len(EXPECTED_FILES)}] downloading {name} ({size} bytes)")
            curl(url, target_part, max_bytes=size + 1, timeout=1800)
            if target_part.stat().st_size != size or file_hash(target_part, "md5") != md5:
                raise SystemExit(f"download identity mismatch for {name}")
            os.replace(target_part, target)
        inventory.append({"name": name, "size": size, "md5": md5, "url": url})
    (args.download_dir / "source_inventory.json").write_text(
        json.dumps(inventory, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"validated {len(EXPECTED_FILES)} FCS files totaling {sum(int(v['size']) for v in EXPECTED_FILES.values())} bytes")


def ascii_offset(field: bytes) -> int:
    text = field.decode("ascii", "strict").strip()
    return int(text) if text else 0


def parse_text_segment(raw: bytes) -> dict[str, str]:
    if len(raw) < 3:
        raise ValueError("FCS TEXT segment is too short")
    delimiter = raw[0]
    if delimiter == 0 or delimiter > 0x7F:
        raise ValueError(f"invalid FCS TEXT delimiter 0x{delimiter:02x}")
    delimiter_bytes = bytes((delimiter,))
    while len(raw) > 1 and raw[-1] in b"\x00 \t\r\n" and raw[-1] != delimiter:
        raw = raw[:-1]
    body = raw[1:]
    if body.endswith(delimiter_bytes):
        body = body[:-1]
    split_tokens = body.split(delimiter_bytes)
    escaped_tokens = []
    token = bytearray()
    position = 1
    while position < len(raw):
        value = raw[position]
        if value != delimiter:
            token.append(value)
            position += 1
        elif position + 1 < len(raw) and raw[position + 1] == delimiter:
            token.append(delimiter)
            position += 2
        else:
            escaped_tokens.append(bytes(token))
            token.clear()
            position += 1
    if token:
        escaped_tokens.append(bytes(token))
    candidates = []
    for tokens in (split_tokens, escaped_tokens):
        variants = [tokens]
        if len(tokens) % 2:
            variants.extend((tokens[:-1], tokens[1:]))
        for variant in variants:
            if len(variant) % 2:
                continue
            result = {}
            valid = True
            for index in range(0, len(variant), 2):
                key = variant[index].decode("latin-1").strip().upper()
                value = variant[index + 1].decode("latin-1").strip()
                if not key or key in result:
                    valid = False
                    break
                result[key] = value
            required = {"$MODE", "$DATATYPE", "$TOT", "$PAR", "$BYTEORD"}
            if valid and required.issubset(result):
                score = sum(bool(re.fullmatch(r"\$[A-Z0-9]+", key)) for key in result)
                candidates.append((score * 10_000 + len(result), result))
    if not candidates:
        raise ValueError("cannot parse FCS TEXT metadata")
    return max(candidates, key=lambda item: item[0])[1]


def required_int(text: dict[str, str], key: str) -> int:
    try:
        return int(text[key])
    except (KeyError, ValueError) as error:
        raise ValueError(f"missing or invalid {key}") from error


def transition_count(values: array) -> int:
    return sum(left != right for left, right in zip(values, values[1:]))


def parse_source(download_dir: Path, name: str, expected: dict[str, object]) -> tuple[dict[str, object], bytes, set[bytes]]:
    path = download_dir / name
    if not path.is_file() or path.stat().st_size != expected["size"] or file_hash(path, "md5") != expected["md5"]:
        raise SystemExit(f"missing or mismatched pinned source {name}")
    raw = path.read_bytes()
    if len(raw) < 58 or raw[:6] != b"FCS3.1":
        raise SystemExit(f"unexpected FCS version/header in {name}")
    text_start = ascii_offset(raw[10:18])
    text_end = ascii_offset(raw[18:26])
    header_data_start = ascii_offset(raw[26:34])
    header_data_end = ascii_offset(raw[34:42])
    if text_start < 58 or text_end < text_start or text_end >= len(raw):
        raise SystemExit(f"invalid FCS TEXT offsets in {name}")
    try:
        text = parse_text_segment(raw[text_start : text_end + 1])
    except ValueError as error:
        raise SystemExit(f"cannot parse FCS TEXT in {name}: {error}") from error
    if text.get("$MODE", "").upper() != "L" or text.get("$DATATYPE", "").upper() != "I":
        raise SystemExit(f"unexpected FCS mode/datatype in {name}")
    events = required_int(text, "$TOT")
    parameters = required_int(text, "$PAR")
    if events != expected["events"] or parameters != PARAMETER_COUNT:
        raise SystemExit(f"unexpected event/parameter count in {name}")
    if text.get("$BYTEORD", "").replace(" ", "") != "1,2,3,4":
        raise SystemExit(f"unexpected FCS byte order in {name}")
    if required_int(text, "$NEXTDATA") != 0:
        raise SystemExit(f"chained FCS datasets are unsupported in {name}")
    bits = [required_int(text, f"$P{index}B") for index in range(1, parameters + 1)]
    ranges = [required_int(text, f"$P{index}R") for index in range(1, parameters + 1)]
    names = [
        text.get(f"$P{index}S") or text.get(f"$P{index}N") or f"P{index}"
        for index in range(1, parameters + 1)
    ]
    if set(bits) != {32} or set(ranges) != {2_147_483_647}:
        raise SystemExit(f"unexpected FCS parameter width/range in {name}")
    if tuple(names[:3]) != HOUSEKEEPING_NAMES or tuple(names[3:]) != SELECTED_PARAMETER_NAMES:
        raise SystemExit(f"unexpected FCS parameter schema in {name}")
    data_start = required_int(text, "$BEGINDATA")
    data_end = required_int(text, "$ENDDATA")
    if header_data_start != data_start or header_data_end != data_end:
        raise SystemExit(f"FCS HEADER/TEXT DATA offsets disagree in {name}")
    expected_data_bytes = events * parameters * 4
    if data_start <= text_end or data_end != len(raw) or data_end - data_start != expected_data_bytes:
        raise SystemExit(f"unexpected FCS exclusive DATA geometry in {name}")
    data = raw[data_start:data_end]
    values = array("I")
    values.frombytes(data)
    if sys.byteorder != "little":
        values.byteswap()
    parameter_stats = []
    for index, parameter_name in enumerate(names):
        channel = values[index::parameters]
        parameter_stats.append({
            "index": index,
            "name": parameter_name,
            "minimum": min(channel),
            "maximum": max(channel),
            "distinct_values": len(set(channel)),
            "zero_values": channel.count(0),
            "transitions": transition_count(channel),
        })
    selected_stats = parameter_stats[3:]
    if any(item["distinct_values"] < 4 or item["transitions"] < 3 for item in selected_stats):
        raise SystemExit(f"degenerate selected FCS channel in {name}")
    if any(item["maximum"] > 2_147_483_647 for item in selected_stats):
        raise SystemExit(f"selected FCS value exceeds declared range in {name}")
    row_bytes = parameters * 4
    payload = bytearray(events * len(SELECTED_PARAMETER_NAMES) * 4)
    event_hashes = set()
    output_position = 0
    for event in range(events):
        row_start = event * row_bytes
        selected_row = data[row_start + 12 : row_start + row_bytes]
        payload[output_position : output_position + len(selected_row)] = selected_row
        output_position += len(selected_row)
        event_hashes.add(hashlib.sha256(selected_row).digest())
    payload = bytes(payload)
    sha256 = hashlib.sha256(payload).hexdigest()
    if sha256 != expected["sha256"]:
        raise SystemExit(f"selected FCS payload hash changed in {name}")
    report = {
        "file_name": name,
        "source_size_bytes": expected["size"],
        "source_md5": expected["md5"],
        "output_name": expected["output"],
        "events": events,
        "source_parameters": parameters,
        "selected_parameters": len(SELECTED_PARAMETER_NAMES),
        "source_numeric_values": len(values),
        "source_numeric_bytes": len(data),
        "selected_numeric_values": events * len(SELECTED_PARAMETER_NAMES),
        "selected_numeric_bytes": len(payload),
        "selected_minimum": min(item["minimum"] for item in selected_stats),
        "selected_maximum": max(item["maximum"] for item in selected_stats),
        "minimum_selected_distinct_values": min(item["distinct_values"] for item in selected_stats),
        "minimum_selected_transitions": min(item["transitions"] for item in selected_stats),
        "housekeeping_parameter_stats": parameter_stats[:3],
        "selected_parameter_stats": selected_stats,
        "selected_sha256": sha256,
        "selected_zlib_ratio": round(len(zlib.compress(payload, 9)) / len(payload), 9),
        "unique_event_rows": len(event_hashes),
        "within_file_duplicate_event_rows": events - len(event_hashes),
        "data_start": data_start,
        "declared_exclusive_data_end": data_end,
    }
    return report, payload, event_hashes


def scan(download_dir: Path) -> tuple[list[dict[str, object]], list[bytes], dict[str, object]]:
    metadata_record(download_dir)
    reports = []
    payloads = []
    sample_hashes = set()
    prior_event_hashes = set()
    cross_file_duplicates = 0
    for name, expected in EXPECTED_FILES.items():
        report, payload, event_hashes = parse_source(download_dir, name, expected)
        digest = str(report["selected_sha256"])
        if digest in sample_hashes:
            raise SystemExit(f"duplicate selected matrix payload: {name}")
        sample_hashes.add(digest)
        duplicates = len(event_hashes & prior_event_hashes)
        report["rows_duplicated_from_prior_files"] = duplicates
        cross_file_duplicates += duplicates
        prior_event_hashes.update(event_hashes)
        reports.append(report)
        payloads.append(payload)
    ratios = [float(report["selected_zlib_ratio"]) for report in reports]
    summary = {
        "dataset_id": DATASET_ID,
        "series_id": SERIES_ID,
        "record_id": RECORD_ID,
        "license": "cc-by-4.0",
        "sample_count": len(reports),
        "total_events": sum(int(report["events"]) for report in reports),
        "selected_parameter_count": len(SELECTED_PARAMETER_NAMES),
        "selected_parameter_names": list(SELECTED_PARAMETER_NAMES),
        "source_numeric_values": sum(int(report["source_numeric_values"]) for report in reports),
        "source_numeric_bytes": sum(int(report["source_numeric_bytes"]) for report in reports),
        "value_count": sum(int(report["selected_numeric_values"]) for report in reports),
        "total_size_bytes": sum(int(report["selected_numeric_bytes"]) for report in reports),
        "global_minimum": min(int(report["selected_minimum"]) for report in reports),
        "global_maximum": max(int(report["selected_maximum"]) for report in reports),
        "minimum_selected_distinct_values": min(
            int(report["minimum_selected_distinct_values"]) for report in reports
        ),
        "minimum_selected_transitions": min(int(report["minimum_selected_transitions"]) for report in reports),
        "unique_sample_payloads": len(sample_hashes),
        "within_file_duplicate_event_rows": sum(
            int(report["within_file_duplicate_event_rows"]) for report in reports
        ),
        "rows_duplicated_from_prior_files": cross_file_duplicates,
        "minimum_zlib_ratio": min(ratios),
        "median_zlib_ratio": statistics.median(ratios),
        "maximum_zlib_ratio": max(ratios),
        "profiles": reports,
    }
    expected_summary = {
        "sample_count": 9,
        "total_events": 206_828,
        "source_numeric_values": 13_857_476,
        "source_numeric_bytes": 55_429_904,
        "value_count": 13_236_992,
        "total_size_bytes": 52_947_968,
        "global_minimum": 225,
        "global_maximum": 2_147_483_392,
        "minimum_selected_distinct_values": 1_006,
        "minimum_selected_transitions": 10_381,
        "unique_sample_payloads": 9,
        "within_file_duplicate_event_rows": 0,
        "rows_duplicated_from_prior_files": 0,
        "minimum_zlib_ratio": 0.759143766,
        "median_zlib_ratio": 0.760733975,
        "maximum_zlib_ratio": 0.761419801,
    }
    for key, value in expected_summary.items():
        if summary[key] != value:
            raise SystemExit(f"aggregate source statistic changed for {key}: {summary[key]} != {value}")
    return reports, payloads, summary


def public_summary(summary: dict[str, object]) -> dict[str, object]:
    return {key: value for key, value in summary.items() if key not in {"profiles", "selected_parameter_names"}}


def inspect(args: argparse.Namespace) -> None:
    _reports, _payloads, summary = scan(args.download_dir)
    print(json.dumps(public_summary(summary), indent=2, sort_keys=True))


def build(args: argparse.Namespace) -> None:
    reports, payloads, summary = scan(args.download_dir)
    series_dir = args.samples_dir / SERIES_ID
    if series_dir.exists():
        shutil.rmtree(series_dir)
    series_dir.mkdir(parents=True)
    rows = []
    for report, payload in zip(reports, payloads, strict=True):
        output = series_dir / str(report["output_name"])
        output.write_bytes(payload)
        rows.append({
            "dataset_id": DATASET_ID,
            "series_id": SERIES_ID,
            "role": "primary",
            "sample_path": output.relative_to(args.data_root).as_posix(),
            "source_sample": f"downloads/{DATASET_ID}/{report['file_name']}",
            "source_data_start": report["data_start"],
            "source_declared_exclusive_data_end": report["declared_exclusive_data_end"],
            "event_count": report["events"],
            "measurement_channel_count": len(SELECTED_PARAMETER_NAMES),
            "measurement_channel_names": list(SELECTED_PARAMETER_NAMES),
            "excluded_parameter_names": list(HOUSEKEEPING_NAMES),
            "numeric_kind": "uint",
            "bit_width": 32,
            "endianness": "little",
            "element_size_bytes": 4,
            "value_count": report["selected_numeric_values"],
            "sample_size_bytes": report["selected_numeric_bytes"],
            "sample_format": "raw homogeneous uint32 FCS event-by-measurement matrix",
            "sample_geometry": "2d_flow_cytometry_event_channel_matrix",
            "sample_rank": 2,
            "sample_shape": [report["events"], len(SELECTED_PARAMETER_NAMES)],
            "sample_axes": ["event", "measurement_channel"],
            "natural_record_kind": "complete_fcs_positive_control",
            "minimum": report["selected_minimum"],
            "maximum": report["selected_maximum"],
            "minimum_channel_distinct_values": report["minimum_selected_distinct_values"],
            "sha256": report["selected_sha256"],
        })
    args.index.parent.mkdir(parents=True, exist_ok=True)
    with args.index.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")
    args.stats.parent.mkdir(parents=True, exist_ok=True)
    args.stats.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(public_summary(summary), indent=2, sort_keys=True))


def verify(args: argparse.Namespace) -> None:
    reports, payloads, summary = scan(args.download_dir)
    if not args.index.is_file() or not args.stats.is_file():
        raise SystemExit("missing index or ingest stats; run build.sh first")
    rows = [json.loads(line) for line in args.index.read_text(encoding="utf-8").splitlines() if line.strip()]
    if len(rows) != len(reports):
        raise SystemExit(f"unexpected index row count: {len(rows)}")
    expected_outputs = set()
    for row, report, payload in zip(rows, reports, payloads, strict=True):
        if row.get("dataset_id") != DATASET_ID or row.get("series_id") != SERIES_ID or row.get("role") != "primary":
            raise SystemExit(f"unexpected dataset/series/role for {report['file_name']}")
        if row.get("sample_shape") != [report["events"], len(SELECTED_PARAMETER_NAMES)]:
            raise SystemExit(f"sample shape mismatch for {report['file_name']}")
        if row.get("numeric_kind") != "uint" or row.get("bit_width") != 32 or row.get("endianness") != "little":
            raise SystemExit(f"numeric representation mismatch for {report['file_name']}")
        if row.get("measurement_channel_names") != list(SELECTED_PARAMETER_NAMES):
            raise SystemExit(f"measurement channel schema mismatch for {report['file_name']}")
        output = args.data_root / str(row["sample_path"])
        expected_outputs.add(output.resolve())
        if not output.is_file() or output.read_bytes() != payload:
            raise SystemExit(f"output is not byte-identical to selected FCS words for {report['file_name']}")
        if row.get("sha256") != report["selected_sha256"]:
            raise SystemExit(f"indexed hash mismatch for {report['file_name']}")
    actual_outputs = {path.resolve() for path in (args.data_root / "samples" / DATASET_ID).glob("*/*.bin")}
    if actual_outputs != expected_outputs:
        raise SystemExit("sample directory contents do not exactly match the index")
    stored = json.loads(args.stats.read_text(encoding="utf-8"))
    if stored != summary:
        raise SystemExit("stored ingest statistics differ from independently recomputed source statistics")
    print(json.dumps({
        "dataset_id": DATASET_ID,
        "verified_samples": len(reports),
        "verified_events": summary["total_events"],
        "verified_values": summary["value_count"],
        "verified_bytes": summary["total_size_bytes"],
    }, indent=2, sort_keys=True))


def main() -> None:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    download_parser = subparsers.add_parser("download")
    download_parser.add_argument("--download-dir", type=Path, required=True)
    inspect_parser = subparsers.add_parser("inspect")
    inspect_parser.add_argument("--download-dir", type=Path, required=True)
    for command in ("build", "verify"):
        sub = subparsers.add_parser(command)
        sub.add_argument("--download-dir", type=Path, required=True)
        sub.add_argument("--index", type=Path, required=True)
        sub.add_argument("--stats", type=Path, required=True)
        sub.add_argument("--data-root", type=Path, required=True)
        if command == "build":
            sub.add_argument("--samples-dir", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "download":
        download(args)
    elif args.command == "inspect":
        inspect(args)
    elif args.command == "build":
        build(args)
    else:
        verify(args)


if __name__ == "__main__":
    main()
