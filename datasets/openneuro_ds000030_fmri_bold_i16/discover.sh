#!/usr/bin/env bash
# Inventory BOLD objects and inspect only bounded compressed NIfTI prefixes.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
CANDIDATE_ID="openneuro_ds000030_fmri_bold_i16"
OUT_DIR="$REPO_ROOT/$DATA_DIR/discovery/$CANDIDATE_ID"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$CANDIDATE_ID"
PROBE_LIMIT="${PROBE_LIMIT:-80}"
FILE_LIMIT="${FILE_LIMIT:-10}"
MAX_DECODED_BYTES="${MAX_DECODED_BYTES:-900000000}"
PREFIX_BYTES="${PREFIX_BYTES:-262144}"

mkdir -p "$OUT_DIR" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/discover.$RUN_TS.log" "$LOG_DIR/discover.latest.log") 2>&1
echo "[$(date -Is)] discovery start candidate=$CANDIDATE_ID"

export OUT_DIR PROBE_LIMIT FILE_LIMIT MAX_DECODED_BYTES PREFIX_BYTES
python3 - <<'PY'
from __future__ import annotations

from collections import defaultdict, deque
import json
import math
import os
from pathlib import Path
import re
import struct
import subprocess
import urllib.parse
import xml.etree.ElementTree as ET
import zlib


DATASET = "ds000030"
BUCKET_BASE = "https://s3.amazonaws.com/openneuro.org"
BUCKET_PREFIX = f"{DATASET}/"
OUT_DIR = Path(os.environ["OUT_DIR"])
PROBE_LIMIT = int(os.environ["PROBE_LIMIT"])
FILE_LIMIT = int(os.environ["FILE_LIMIT"])
MAX_DECODED_BYTES = int(os.environ["MAX_DECODED_BYTES"])
PREFIX_BYTES = int(os.environ["PREFIX_BYTES"])
USER_AGENT = "openzl-public-datasets-openneuro-bold-metadata/1.0"
BOLD_PATTERN = re.compile(
    r"(?:^|/)(sub-[^/]+)/(?:ses-[^/]+/)?func/([^/]*_bold\.nii\.gz)$"
)
TASK_PATTERN = re.compile(r"(?:^|_)task-([^_]+)")
RUN_PATTERN = re.compile(r"(?:^|_)run-([^_]+)")


def curl(url: str, *, byte_range: tuple[int, int] | None = None) -> bytes:
    command = [
        "curl", "--fail", "--silent", "--show-error", "--location",
        "--retry", "3", "--retry-all-errors", "--max-time", "180",
        "--user-agent", USER_AGENT,
    ]
    if byte_range is None:
        command.extend(["--max-filesize", "5000000"])
    else:
        start, end = byte_range
        expected = end - start + 1
        command.extend(["--range", f"{start}-{end}", "--max-filesize", str(expected + 1)])
    command.append(url)
    result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if result.returncode:
        raise RuntimeError(result.stderr.decode("utf-8", errors="replace").strip())
    if byte_range is not None and len(result.stdout) > byte_range[1] - byte_range[0] + 1:
        raise ValueError("server ignored bounded range request")
    return result.stdout


def object_url(key: str) -> str:
    return f"{BUCKET_BASE}/{urllib.parse.quote(key, safe='/')}"


def list_objects() -> list[dict[str, object]]:
    objects: list[dict[str, object]] = []
    token: str | None = None
    while True:
        query = {"list-type": "2", "prefix": BUCKET_PREFIX, "max-keys": "1000"}
        if token:
            query["continuation-token"] = token
        root = ET.fromstring(curl(f"{BUCKET_BASE}?{urllib.parse.urlencode(query)}"))
        namespace = root.tag.split("}", 1)[0] + "}" if root.tag.startswith("{") else ""
        for content in root.findall(f"{namespace}Contents"):
            key = content.findtext(f"{namespace}Key") or ""
            size = int(content.findtext(f"{namespace}Size") or 0)
            etag = (content.findtext(f"{namespace}ETag") or "").strip('"')
            objects.append({"key": key, "size": size, "etag": etag})
        if (root.findtext(f"{namespace}IsTruncated") or "false").lower() != "true":
            break
        token = root.findtext(f"{namespace}NextContinuationToken")
        if not token:
            raise ValueError("truncated S3 listing lacks a continuation token")
    return objects


def classify_object(item: dict[str, object]) -> dict[str, object] | None:
    key = str(item["key"])
    if "/derivatives/" in key or "/sourcedata/" in key:
        return None
    match = BOLD_PATTERN.search(key)
    if not match:
        return None
    filename = match.group(2)
    task_match = TASK_PATTERN.search(filename)
    run_match = RUN_PATTERN.search(filename)
    return {
        **item,
        "subject": match.group(1),
        "task": task_match.group(1) if task_match else "unspecified",
        "run": run_match.group(1) if run_match else "",
        "release_root": key[: match.start(1)].rstrip("/"),
        "url": object_url(key),
    }


def balanced_probe_order(items: list[dict[str, object]]) -> list[dict[str, object]]:
    # Within each task, rotate across subjects; then rotate across tasks. This
    # avoids probing many runs from one subject or task before seeing others.
    by_task_subject: dict[str, dict[str, deque[dict[str, object]]]] = defaultdict(
        lambda: defaultdict(deque)
    )
    for item in sorted(items, key=lambda row: str(row["key"])):
        by_task_subject[str(item["task"])][str(item["subject"])].append(item)
    task_queues: dict[str, deque[dict[str, object]]] = {}
    for task, subjects in sorted(by_task_subject.items()):
        queue: deque[dict[str, object]] = deque()
        while any(subjects.values()):
            for subject in sorted(subjects):
                if subjects[subject]:
                    queue.append(subjects[subject].popleft())
        task_queues[task] = queue
    ordered: list[dict[str, object]] = []
    while any(task_queues.values()):
        for task in sorted(task_queues):
            if task_queues[task]:
                ordered.append(task_queues[task].popleft())
    return ordered


def parse_nifti_prefix(compressed: bytes) -> dict[str, object]:
    inflater = zlib.decompressobj(16 + zlib.MAX_WBITS)
    try:
        header = inflater.decompress(compressed, 4096)
    except zlib.error as error:
        raise ValueError(f"invalid gzip prefix: {error}") from error
    if len(header) < 352:
        raise ValueError(f"bounded prefix yielded only {len(header)} decompressed bytes")
    if struct.unpack_from("<I", header, 0)[0] == 348:
        endian, endianness = "<", "little"
    elif struct.unpack_from(">I", header, 0)[0] == 348:
        endian, endianness = ">", "big"
    else:
        raise ValueError("invalid NIfTI-1 sizeof_hdr")
    if header[344:348] != b"n+1\0":
        raise ValueError("not a NIfTI-1 single-file image")
    dims = struct.unpack_from(endian + "8h", header, 40)
    rank = int(dims[0])
    shape = [int(value) for value in dims[1 : rank + 1]] if 0 < rank <= 7 else []
    if not shape or any(value <= 0 for value in shape):
        raise ValueError(f"invalid NIfTI dimensions: {dims!r}")
    datatype = int(struct.unpack_from(endian + "h", header, 70)[0])
    bitpix = int(struct.unpack_from(endian + "h", header, 72)[0])
    vox_offset = float(struct.unpack_from(endian + "f", header, 108)[0])
    slope = float(struct.unpack_from(endian + "f", header, 112)[0])
    intercept = float(struct.unpack_from(endian + "f", header, 116)[0])
    pixdim = list(struct.unpack_from(endian + "8f", header, 76))
    if not math.isfinite(vox_offset) or not vox_offset.is_integer() or vox_offset < 352:
        raise ValueError(f"invalid vox_offset: {vox_offset}")
    value_count = math.prod(shape)
    decoded_bytes = value_count * bitpix // 8 if bitpix > 0 and bitpix % 8 == 0 else 0
    identity_scaling = slope in {0.0, 1.0} and intercept == 0.0
    qualifies = rank == 4 and datatype == 4 and bitpix == 16 and identity_scaling
    return {
        "source_endianness": endianness,
        "rank": rank,
        "shape": shape,
        "datatype": datatype,
        "bitpix": bitpix,
        "vox_offset": int(vox_offset),
        "scl_slope": slope,
        "scl_inter": intercept,
        "pixdim": pixdim[1 : rank + 1],
        "value_count": value_count,
        "decoded_bytes": decoded_bytes,
        "qualifies_i16_bold": qualifies,
    }


objects = list_objects()
bold = [row for item in objects if (row := classify_object(item)) is not None]
if not bold:
    raise SystemExit("no public non-derivative BOLD NIfTI objects found")

root_counts: dict[str, int] = defaultdict(int)
for item in bold:
    root_counts[str(item["release_root"])] += 1
release_root = sorted(root_counts, key=lambda root: (-root_counts[root], root))[0]
bold = [item for item in bold if item["release_root"] == release_root]

description_keys = [f"{release_root}/dataset_description.json", f"{DATASET}/dataset_description.json"]
description_item = next(
    (item for key in description_keys for item in objects if item["key"] == key),
    None,
)
if description_item is None:
    raise SystemExit("dataset_description.json absent from selected release root")
description_raw = curl(object_url(str(description_item["key"])))
description = json.loads(description_raw)
if str(description.get("License", "")).strip().upper() != "CC0":
    raise SystemExit(f"expected explicit CC0 license, found {description.get('License')!r}")
if description.get("DatasetDOI") != "10.18112/openneuro.ds000030.v1.0.0":
    raise SystemExit(f"unexpected dataset DOI: {description.get('DatasetDOI')!r}")
(OUT_DIR / "dataset_description.json").write_bytes(description_raw)

ordered = balanced_probe_order(bold)
probes: list[dict[str, object]] = []
successful_headers = 0
for item in ordered[:PROBE_LIMIT]:
    result = dict(item)
    try:
        prefix = curl(str(item["url"]), byte_range=(0, PREFIX_BYTES - 1))
        result.update(parse_nifti_prefix(prefix))
        result["probe_status"] = "ok"
        result["probe_bytes"] = len(prefix)
        successful_headers += 1
    except (RuntimeError, ValueError, struct.error) as error:
        result["probe_status"] = "error"
        result["error"] = str(error).replace("\t", " ").replace("\n", " ")
        result["qualifies_i16_bold"] = False
    probes.append(result)

selected: list[dict[str, object]] = []
selected_bytes = 0
selected_tasks: set[str] = set()
selected_subjects: set[str] = set()
while len(selected) < FILE_LIMIT:
    feasible = [
        item
        for item in probes
        if item not in selected
        and item.get("qualifies_i16_bold")
        and 0 < int(item["decoded_bytes"]) <= MAX_DECODED_BYTES
        and selected_bytes + int(item["decoded_bytes"]) <= MAX_DECODED_BYTES
    ]
    if not feasible:
        break
    feasible.sort(
        key=lambda item: (
            -(str(item["task"]) not in selected_tasks),
            -(str(item["subject"]) not in selected_subjects),
            int(item["decoded_bytes"]),
            str(item["key"]),
        )
    )
    chosen = feasible[0]
    selected.append(chosen)
    selected_bytes += int(chosen["decoded_bytes"])
    selected_tasks.add(str(chosen["task"]))
    selected_subjects.add(str(chosen["subject"]))

with (OUT_DIR / "all_bold_objects.tsv").open("w", encoding="utf-8") as handle:
    handle.write("key\tsize_bytes\tetag\tsubject\ttask\trun\turl\n")
    for item in sorted(bold, key=lambda row: str(row["key"])):
        handle.write(
            f"{item['key']}\t{item['size']}\t{item['etag']}\t{item['subject']}\t"
            f"{item['task']}\t{item['run']}\t{item['url']}\n"
        )

probe_fields = [
    "key", "size", "etag", "subject", "task", "run", "probe_status",
    "probe_bytes", "source_endianness", "rank", "shape", "datatype", "bitpix",
    "vox_offset", "scl_slope", "scl_inter", "pixdim", "value_count",
    "decoded_bytes", "qualifies_i16_bold", "error", "url",
]
with (OUT_DIR / "bold_header_probes.tsv").open("w", encoding="utf-8") as handle:
    handle.write("\t".join(probe_fields) + "\n")
    for item in probes:
        values = []
        for field in probe_fields:
            value = item.get(field, "")
            if isinstance(value, list):
                value = "x".join(str(part) for part in value)
            values.append(str(value).replace("\t", " ").replace("\n", " "))
        handle.write("\t".join(values) + "\n")

selection_fields = [
    "key", "size", "etag", "subject", "task", "run", "source_endianness",
    "shape", "datatype", "bitpix", "vox_offset", "scl_slope", "scl_inter",
    "value_count", "decoded_bytes", "url",
]
with (OUT_DIR / "selected_bold_plan.tsv").open("w", encoding="utf-8") as handle:
    handle.write("\t".join(selection_fields) + "\n")
    for item in selected:
        values = []
        for field in selection_fields:
            value = item.get(field, "")
            if isinstance(value, list):
                value = "x".join(str(part) for part in value)
            values.append(str(value))
        handle.write("\t".join(values) + "\n")

datatype_counts: dict[str, int] = defaultdict(int)
for item in probes:
    if item.get("probe_status") == "ok":
        key = f"datatype={item['datatype']}/bitpix={item['bitpix']}/rank={item['rank']}"
        datatype_counts[key] += 1
summary = {
    "candidate_id": "openneuro_ds000030_fmri_bold_i16",
    "dataset_id": DATASET,
    "dataset_name": description.get("Name"),
    "dataset_doi": description.get("DatasetDOI"),
    "license": description.get("License"),
    "release_root": release_root,
    "listed_objects": len(objects),
    "bold_objects": len(bold),
    "bold_subjects": len({str(item['subject']) for item in bold}),
    "bold_tasks": sorted({str(item['task']) for item in bold}),
    "probed_objects": len(probes),
    "successful_headers": successful_headers,
    "probe_format_counts": dict(sorted(datatype_counts.items())),
    "qualifying_probes": sum(bool(item.get("qualifies_i16_bold")) for item in probes),
    "selected_objects": len(selected),
    "selected_subjects": len({str(item['subject']) for item in selected}),
    "selected_tasks": sorted({str(item['task']) for item in selected}),
    "selected_compressed_bytes": sum(int(item["size"]) for item in selected),
    "selected_decoded_bytes": selected_bytes,
    "probe_limit": PROBE_LIMIT,
    "file_limit": FILE_LIMIT,
    "max_decoded_bytes": MAX_DECODED_BYTES,
    "prefix_bytes_per_object": PREFIX_BYTES,
    "outcome": "qualifying_plan" if selected else "no_native_int16_plan",
}
(OUT_DIR / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
print(json.dumps(summary, indent=2, sort_keys=True))
print(f"probes={OUT_DIR / 'bold_header_probes.tsv'}")
print(f"plan={OUT_DIR / 'selected_bold_plan.tsv'}")
if successful_headers == 0:
    raise SystemExit("all bounded BOLD header probes failed")
PY

echo "[$(date -Is)] discovery done candidate=$CANDIDATE_ID"
