#!/usr/bin/env python3
"""Bounded label-only discovery of native-int16 MOLA MEGDR grids."""
from __future__ import annotations

import argparse
from collections import deque
import csv
import html
import json
from pathlib import Path
import re
import subprocess
from urllib.parse import urljoin, urlsplit, urlunsplit


CANDIDATE_ID = "nasa_pds_mola_megdr_i16"
MISSION_URL = "https://pds-geosciences.wustl.edu/missions/mgs/mola.html"
DATASET_ROOT = "https://pds-geosciences.wustl.edu/mgs/mgs-m-mola-5-megdr-l3-v1/"
VOLUME_ROOT = DATASET_ROOT + "mgol_1201/"
SEED_DIRECTORIES = (
    DATASET_ROOT,
    VOLUME_ROOT,
    VOLUME_ROOT + "data/",
    VOLUME_ROOT + "index/",
)
USER_AGENT = "openzl-public-datasets-mola-megdr-i16-preflight/1.0"
MAX_PAGE_BYTES = 20 * 1024 * 1024
MAX_LABEL_BYTES = 2 * 1024 * 1024
MAX_DIRECTORIES = 100
MAX_DEPTH = 8
MAX_LABELS = 200
MAX_PAYLOAD_BYTES = 500 * 1024 * 1024
MAX_TOTAL_CANDIDATE_BYTES = 4 * 1024 * 1024 * 1024
HREF_RE = re.compile(r"(?i)href\s*=\s*['\"]([^'\"]+)['\"]")


def curl_bytes(url: str, maximum: int) -> bytes:
    result = subprocess.run(
        [
            "curl", "--fail", "--silent", "--show-error", "--location", "--retry", "4",
            "--retry-delay", "2", "--max-time", "300", "--max-filesize", str(maximum),
            "--user-agent", USER_AGENT, url,
        ],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
    )
    if result.returncode or len(result.stdout) > maximum:
        message = result.stderr.decode("utf-8", "replace").strip()
        raise RuntimeError(f"{url}: {message or 'fetch failed'}")
    return result.stdout


def content_length(url: str) -> int:
    result = subprocess.run(
        [
            "curl", "--fail", "--silent", "--show-error", "--location", "--head",
            "--retry", "4", "--retry-delay", "2", "--max-time", "180",
            "--user-agent", USER_AGENT, url,
        ],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
    )
    if result.returncode:
        message = result.stderr.decode("utf-8", "replace").strip()
        raise RuntimeError(f"{url}: {message or 'HEAD failed'}")
    matches = re.findall(rb"(?im)^content-length:\s*(\d+)\s*$", result.stdout)
    if not matches:
        raise RuntimeError(f"{url}: HEAD lacks Content-Length")
    return int(matches[-1])


def clean_url(base: str, href: str) -> str:
    absolute = urljoin(base, html.unescape(href))
    parts = urlsplit(absolute)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))


def directory_links(url: str) -> tuple[list[str], list[str]]:
    raw = curl_bytes(url, MAX_PAGE_BYTES)
    text = raw.decode("utf-8", "replace")
    directories = []
    labels = []
    for href in HREF_RE.findall(text):
        linked = clean_url(url, href)
        if not linked.startswith(DATASET_ROOT) or linked == url:
            continue
        path = urlsplit(linked).path.lower()
        if path.endswith("/"):
            directories.append(linked)
        elif path.endswith(".lbl"):
            labels.append(linked)
    return sorted(set(directories)), sorted(set(labels))


def strip_pds_comments(text: str) -> str:
    return re.sub(r"/\*.*?\*/", " ", text, flags=re.S)


def pds_scalar(text: str, key: str) -> str:
    match = re.search(rf"(?im)^\s*{re.escape(key)}\s*=\s*([^\r\n]+)", text)
    if not match:
        return ""
    value = match.group(1).strip()
    if value.startswith('"') and value.endswith('"'):
        value = value[1:-1]
    return value.strip()


def pds_int(text: str, key: str, default: int | None = None) -> int:
    value = pds_scalar(text, key)
    match = re.match(r"^[+-]?\d+", value)
    if not match:
        if default is not None:
            return default
        raise ValueError(f"PDS label lacks integer {key}")
    return int(match.group(0))


def image_object(text: str) -> str:
    match = re.search(r"(?is)OBJECT\s*=\s*IMAGE\b(.*?)END_OBJECT\s*=\s*IMAGE", text)
    return match.group(1) if match else ""


def image_pointer(text: str, label_url: str) -> tuple[str, int]:
    value = pds_scalar(text, "^IMAGE")
    if not value:
        raise ValueError("PDS label lacks ^IMAGE")
    filename = re.match(r'^\s*(?:"([^"]+\.img)"|([^,\s()]+\.img))', value, re.I)
    if not filename:
        raise ValueError(f"PDS IMAGE pointer is not detached IMG: {value}")
    payload_url = clean_url(label_url, filename.group(1) or filename.group(2))
    tail = value[filename.end():]
    record_match = re.search(r",\s*(\d+)", tail)
    start_record = int(record_match.group(1)) if record_match else 1
    return payload_url, start_record


def parse_label(raw: bytes, label_url: str) -> dict[str, object]:
    text = strip_pds_comments(raw.decode("ascii", "replace"))
    upper = text.upper()
    data_set_id = pds_scalar(text, "DATA_SET_ID")
    product_id = pds_scalar(text, "PRODUCT_ID")
    if "MOLA" not in upper or "MEGDR" not in upper:
        raise ValueError("label does not establish MOLA MEGDR semantics")
    image = image_object(text)
    if not image:
        raise ValueError("label lacks IMAGE object")
    lines = pds_int(image, "LINES")
    line_samples = pds_int(image, "LINE_SAMPLES")
    sample_bits = pds_int(image, "SAMPLE_BITS")
    sample_type = pds_scalar(image, "SAMPLE_TYPE").upper()
    prefix_bytes = pds_int(image, "LINE_PREFIX_BYTES", 0)
    suffix_bytes = pds_int(image, "LINE_SUFFIX_BYTES", 0)
    bands = pds_int(image, "BANDS", 1)
    if lines <= 0 or line_samples <= 0 or bands != 1:
        raise ValueError("unsupported MOLA image geometry")
    if sample_bits != 16 or sample_type not in {"MSB_INTEGER", "SIGNED_INTEGER", "INTEGER"}:
        raise ValueError(f"not native signed int16: bits={sample_bits} type={sample_type!r}")
    if prefix_bytes or suffix_bytes:
        raise ValueError("image has line prefix/suffix bytes")
    payload_url, start_record = image_pointer(text, label_url)
    record_bytes = pds_int(text, "RECORD_BYTES", 0)
    if start_record != 1:
        raise ValueError(f"detached image does not begin at record 1: {start_record}")
    expected_bytes = lines * line_samples * 2
    if not 0 < expected_bytes <= MAX_PAYLOAD_BYTES:
        raise ValueError(f"payload size outside cap: {expected_bytes}")
    actual_bytes = content_length(payload_url)
    if actual_bytes != expected_bytes:
        raise ValueError(f"payload size {actual_bytes} != label geometry {expected_bytes}")
    product_text = f"{product_id} {pds_scalar(text, 'PRODUCT_TYPE')} {pds_scalar(text, 'DESCRIPTION')}".upper()
    topography = "TOPO" in product_text or (len(product_id) >= 4 and product_id[3:4].upper() == "T")
    return {
        "label_url": label_url, "payload_url": payload_url,
        "data_set_id": data_set_id, "product_id": product_id,
        "sample_type": sample_type, "sample_bits": sample_bits,
        "endianness": "big" if sample_type == "MSB_INTEGER" else "source_declared",
        "lines": lines, "line_samples": line_samples, "shape": [lines, line_samples],
        "value_count": lines * line_samples, "payload_bytes": expected_bytes,
        "record_bytes": record_bytes, "topography_semantics": topography,
        "missing_constant": pds_scalar(image, "MISSING_CONSTANT"),
        "invalid_constant": pds_scalar(image, "INVALID_CONSTANT"),
        "minimum": pds_scalar(image, "MINIMUM"), "maximum": pds_scalar(image, "MAXIMUM"),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    mission = curl_bytes(MISSION_URL, MAX_PAGE_BYTES)
    mission_text = re.sub(r"<[^>]+>", " ", mission.decode("utf-8", "replace")).lower()
    if "mola" not in mission_text or "mars" not in mission_text or "laser altimeter" not in mission_text:
        raise SystemExit("official mission page no longer establishes MOLA semantics")
    (args.output_dir / "mola_mission_page.html").write_bytes(mission)

    queue = deque((url, 0) for url in SEED_DIRECTORIES)
    seen = set(SEED_DIRECTORIES)
    labels = set()
    directory_reports = []
    while queue and len(directory_reports) < MAX_DIRECTORIES and len(labels) < MAX_LABELS:
        url, depth = queue.popleft()
        try:
            child_dirs, child_labels = directory_links(url)
        except RuntimeError as error:
            directory_reports.append({"url": url, "depth": depth, "error": str(error)})
            continue
        labels.update(child_labels)
        directory_reports.append({
            "url": url, "depth": depth, "child_directories": len(child_dirs),
            "labels": len(child_labels),
        })
        if depth < MAX_DEPTH:
            for child in child_dirs:
                if child not in seen:
                    seen.add(child)
                    queue.append((child, depth + 1))
    (args.output_dir / "directory_reports.json").write_text(
        json.dumps(directory_reports, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    label_urls = sorted(labels)[:MAX_LABELS]
    if not label_urls:
        raise SystemExit("official PDS hierarchy exposed no detached labels within traversal bounds")

    candidates = []
    failures = []
    total_candidate_bytes = 0
    for label_url in label_urls:
        try:
            raw = curl_bytes(label_url, MAX_LABEL_BYTES)
            report = parse_label(raw, label_url)
        except (RuntimeError, ValueError) as error:
            failures.append({"label_url": label_url, "reason": str(error)})
            continue
        if total_candidate_bytes + int(report["payload_bytes"]) > MAX_TOTAL_CANDIDATE_BYTES:
            failures.append({"label_url": label_url, "reason": "global candidate-byte reporting cap"})
            continue
        total_candidate_bytes += int(report["payload_bytes"])
        candidates.append(report)

    (args.output_dir / "label_failures.json").write_text(
        json.dumps(failures, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (args.output_dir / "int16_candidates.json").write_text(
        json.dumps(candidates, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    columns = (
        "product_id", "topography_semantics", "lines", "line_samples", "value_count",
        "payload_bytes", "sample_type", "sample_bits", "endianness", "missing_constant",
        "minimum", "maximum", "label_url", "payload_url",
    )
    with (args.output_dir / "int16_candidates.tsv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, delimiter="\t", extrasaction="ignore")
        writer.writeheader()
        writer.writerows(candidates)
    summary = {
        "candidate_id": CANDIDATE_ID, "mission_url": MISSION_URL,
        "dataset_root": DATASET_ROOT, "directories_attempted": len(directory_reports),
        "directories_seen": len(seen), "labels_discovered": len(labels),
        "labels_probed": len(label_urls), "native_int16_candidates": len(candidates),
        "topography_candidates": sum(bool(row["topography_semantics"]) for row in candidates),
        "label_failures": len(failures), "candidate_payload_bytes": total_candidate_bytes,
    }
    (args.output_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    if not candidates:
        raise SystemExit("bounded official-PDS traversal found no native-int16 MEGDR product")


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, ValueError) as error:
        raise SystemExit(str(error)) from error
