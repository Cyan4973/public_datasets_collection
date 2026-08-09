#!/usr/bin/env python3
"""Bounded label-only discovery of native-int16 Mars 2020 Mastcam-Z frames."""
from __future__ import annotations

import argparse
from collections import deque
import csv
import hashlib
import html
import json
from pathlib import Path
import re
import subprocess
from urllib.parse import urljoin, urlsplit, urlunsplit
import xml.etree.ElementTree as ET


CANDIDATE_ID = "nasa_pds_mastcamz_raw_i16"
POLICY_URL = "https://science.nasa.gov/researchers/science-data/science-information-policy/"
ROOT_CANDIDATES = (
    "https://pds-imaging.jpl.nasa.gov/data/mars2020/mars2020_mastcamz_ops_raw/",
    "https://pds-imaging.jpl.nasa.gov/data/mars2020/mars2020_mastcamz/",
)
USER_AGENT = "openzl-public-datasets-mastcamz-label-discovery/1.0"
MAX_PAGE_BYTES = 20_000_000
MAX_POLICY_BYTES = 5_000_000
MAX_LABEL_BYTES = 2_000_000
MAX_DIRECTORIES = 180
MAX_DEPTH = 6
MAX_LABELS = 400
MAX_PARSED_LABELS = 240
MAX_QUALIFIED = 80
MAX_PAYLOAD_BYTES = 250_000_000
MAX_TOTAL_QUALIFIED_BYTES = 2_000_000_000
HREF_RE = re.compile(r"(?i)href\s*=\s*['\"]([^'\"]+)['\"]")
EXCLUDED_PATH_PARTS = (
    "/browse", "/document", "/calibration", "/context", "/miscellaneous",
    "/readme", "/schema", "/xml_schema",
)


def curl_bytes(url: str, maximum: int) -> bytes:
    result = subprocess.run(
        [
            "curl", "--fail", "--silent", "--show-error", "--location", "--retry", "4",
            "--retry-delay", "2", "--max-time", "300", "--max-filesize", str(maximum),
            "--user-agent", USER_AGENT, url,
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if result.returncode or len(result.stdout) > maximum:
        detail = result.stderr.decode("utf-8", "replace").strip()
        raise RuntimeError(f"{url}: {detail or 'fetch failed'}")
    return result.stdout


def content_length(url: str) -> int:
    result = subprocess.run(
        [
            "curl", "--fail", "--silent", "--show-error", "--location", "--head",
            "--retry", "4", "--retry-delay", "2", "--max-time", "180",
            "--user-agent", USER_AGENT, url,
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if result.returncode:
        detail = result.stderr.decode("utf-8", "replace").strip()
        raise RuntimeError(f"{url}: {detail or 'HEAD failed'}")
    matches = re.findall(rb"(?im)^content-length:\s*(\d+)\s*$", result.stdout)
    if not matches:
        raise RuntimeError(f"{url}: HEAD lacks Content-Length")
    return int(matches[-1])


def clean_url(base: str, href: str) -> str:
    absolute = urljoin(base, html.unescape(href))
    parts = urlsplit(absolute)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))


def local_name(element: ET.Element) -> str:
    return element.tag.rsplit("}", 1)[-1]


def child_text(parent: ET.Element, name: str) -> str:
    for element in parent.iter():
        if local_name(element) == name and element.text:
            return element.text.strip()
    return ""


def direct_children(parent: ET.Element, name: str) -> list[ET.Element]:
    return [element for element in list(parent) if local_name(element) == name]


def directory_links(url: str, root: str) -> tuple[list[str], list[str], bytes]:
    raw = curl_bytes(url, MAX_PAGE_BYTES)
    text = raw.decode("utf-8", "replace")
    directories = []
    labels = []
    for href in HREF_RE.findall(text):
        linked = clean_url(url, href)
        if not linked.startswith(root) or linked == url:
            continue
        lower_path = urlsplit(linked).path.lower()
        if any(part in lower_path for part in EXCLUDED_PATH_PARTS):
            continue
        if lower_path.endswith("/"):
            directories.append(linked)
        elif lower_path.endswith(".xml"):
            labels.append(linked)
    return sorted(set(directories)), sorted(set(labels)), raw


def image_array(area: ET.Element) -> tuple[ET.Element, str] | None:
    for element in area.iter():
        name = local_name(element)
        if name in {"Array_2D_Image", "Array_3D_Image"}:
            return element, name
    return None


def axis_geometry(array: ET.Element) -> dict[str, int]:
    result: dict[str, int] = {}
    for axis in array.iter():
        if local_name(axis) != "Axis_Array":
            continue
        axis_name = child_text(axis, "axis_name")
        elements = child_text(axis, "elements")
        if axis_name and re.fullmatch(r"\d+", elements):
            result[axis_name.lower()] = int(elements)
    return result


def parse_label(raw: bytes, label_url: str) -> list[dict[str, object]]:
    root = ET.fromstring(raw)
    text_lower = raw.decode("utf-8", "replace").lower()
    logical_identifier = child_text(root, "logical_identifier")
    title = child_text(root, "title")
    product_class = local_name(root)
    if product_class != "Product_Observational":
        raise ValueError(f"not Product_Observational: {product_class}")
    identity = f"{logical_identifier} {title} {text_lower[:20000]}".lower()
    if "mars2020" not in identity or not any(token in identity for token in ("mastcamz", "mastcam-z")):
        raise ValueError("label does not establish Mars 2020 Mastcam-Z provenance")
    if " edr " not in f" {title.lower()} ":
        raise ValueError("not a Mastcam-Z EDR observational product")

    results = []
    for area in root.iter():
        if local_name(area) != "File_Area_Observational":
            continue
        filename = child_text(area, "file_name")
        found = image_array(area)
        if not filename or found is None:
            continue
        array, array_kind = found
        data_type = child_text(array, "data_type")
        if data_type != "SignedMSB2":
            continue
        geometry = axis_geometry(array)
        lines = geometry.get("line", geometry.get("lines", 0))
        samples = geometry.get("sample", geometry.get("samples", 0))
        bands = geometry.get("band", geometry.get("bands", 1))
        if lines <= 0 or samples <= 0 or bands != 1:
            raise ValueError(f"unsupported image axes: {geometry}")
        offset_text = child_text(array, "offset")
        if not re.fullmatch(r"\d+", offset_text):
            raise ValueError("image array lacks byte offset")
        offset = int(offset_text)
        parsing_standard = child_text(area, "parsing_standard_id")
        if parsing_standard and parsing_standard.upper() not in {"PDS4", "VICAR2", "PDS ODL 2"}:
            raise ValueError(f"unexpected parsing standard: {parsing_standard}")
        payload_url = clean_url(label_url, filename)
        parsed = urlsplit(payload_url)
        if parsed.scheme != "https" or parsed.hostname != "pds-imaging.jpl.nasa.gov":
            raise ValueError("label points outside official PDS Imaging host")
        value_count = lines * samples
        array_bytes = value_count * 2
        if not 0 < array_bytes <= MAX_PAYLOAD_BYTES:
            raise ValueError(f"image array outside payload cap: {array_bytes}")
        file_bytes = content_length(payload_url)
        if offset < 0 or offset + array_bytes > file_bytes:
            raise ValueError(
                f"array extent exceeds file: offset={offset} array={array_bytes} file={file_bytes}"
            )
        results.append({
            "array_bytes": array_bytes,
            "array_kind": array_kind,
            "array_offset": offset,
            "bands": bands,
            "data_type": data_type,
            "endianness": "big",
            "file_bytes": file_bytes,
            "label_bytes": len(raw),
            "label_sha256": hashlib.sha256(raw).hexdigest(),
            "label_url": label_url,
            "lines": lines,
            "logical_identifier": logical_identifier,
            "parsing_standard_id": parsing_standard,
            "payload_url": payload_url,
            "product_title": title,
            "samples": samples,
            "value_count": value_count,
        })
    if not results:
        raise ValueError("no qualifying native-int16 image array in label")
    return results


def observed_array_schemas(raw: bytes) -> list[dict[str, str]]:
    root = ET.fromstring(raw)
    schemas = set()
    for element in root.iter():
        name = local_name(element)
        if not name.startswith("Array_"):
            continue
        schemas.add((name, child_text(element, "data_type")))
    return [
        {"array_class": name, "data_type": data_type}
        for name, data_type in sorted(schemas)
    ]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    policy = curl_bytes(POLICY_URL, MAX_POLICY_BYTES)
    policy_text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", policy.decode("utf-8", "replace"))).lower()
    (args.output_dir / "nasa_science_information_policy.html").write_bytes(policy)
    policy_phrases = {
        "public_trust": "public trust" in policy_text,
        "publicly_available": "publicly available" in policy_text,
        "open_sharing": any(
            phrase in policy_text
            for phrase in (
                "openly shared",
                "shared openly",
                "full and open sharing",
                "open sharing of",
                "open data",
            )
        ),
    }
    if not all(policy_phrases.values()):
        raise SystemExit(f"official NASA information-policy evidence changed: {policy_phrases}")

    root_reports = []
    active_root = None
    initial_listing = None
    for root in ROOT_CANDIDATES:
        try:
            child_dirs, labels, raw = directory_links(root, root)
            root_reports.append({
                "root": root,
                "child_directories": len(child_dirs),
                "labels": len(labels),
                "success": True,
            })
            if child_dirs or labels:
                active_root = root
                initial_listing = (child_dirs, labels, raw)
                break
        except Exception as error:
            root_reports.append({"root": root, "success": False, "error": str(error)})
    if active_root is None or initial_listing is None:
        (args.output_dir / "root_reports.json").write_text(
            json.dumps(root_reports, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        raise SystemExit("no official Mastcam-Z archive root could be traversed")
    (args.output_dir / "root_reports.json").write_text(
        json.dumps(root_reports, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (args.output_dir / "archive_root.html").write_bytes(initial_listing[2])

    queue = deque([(active_root, 0, initial_listing[0], initial_listing[1])])
    seen = {active_root}
    labels = set(initial_listing[1])
    directory_reports = []
    while queue and len(directory_reports) < MAX_DIRECTORIES and len(labels) < MAX_LABELS:
        url, depth, prefetched_dirs, prefetched_labels = queue.popleft()
        if url == active_root:
            child_dirs, child_labels = prefetched_dirs, prefetched_labels
        else:
            try:
                child_dirs, child_labels, _ = directory_links(url, active_root)
            except Exception as error:
                directory_reports.append({"url": url, "depth": depth, "error": str(error)})
                continue
        labels.update(child_labels)
        directory_reports.append({
            "url": url,
            "depth": depth,
            "child_directories": len(child_dirs),
            "labels": len(child_labels),
        })
        if depth < MAX_DEPTH:
            # Prefer descending into a sol's product directories immediately;
            # breadth-first traversal would spend the entire bound enumerating
            # hundreds of sibling sol directories before reaching any labels.
            for child in reversed(child_dirs):
                if child not in seen:
                    seen.add(child)
                    queue.appendleft((child, depth + 1, [], []))
    (args.output_dir / "directory_reports.json").write_text(
        json.dumps(directory_reports, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    qualified = []
    failures = []
    label_dir = args.output_dir / "labels"
    label_dir.mkdir(exist_ok=True)
    failed_label_dir = args.output_dir / "failed_label_examples"
    failed_label_dir.mkdir(exist_ok=True)
    for label_url in sorted(labels)[:MAX_PARSED_LABELS]:
        if len(qualified) >= MAX_QUALIFIED:
            break
        raw = b""
        try:
            raw = curl_bytes(label_url, MAX_LABEL_BYTES)
            products = parse_label(raw, label_url)
            for product in products:
                qualified.append(product)
            snapshot = label_dir / f"label_{len(qualified):04d}_{Path(urlsplit(label_url).path).name}"
            snapshot.write_bytes(raw)
            print(
                f"qualified label={Path(urlsplit(label_url).path).name} "
                f"arrays={len(products)} bytes={sum(int(item['array_bytes']) for item in products)}"
            )
        except Exception as error:
            try:
                schemas = observed_array_schemas(raw)
            except Exception:
                schemas = []
            failures.append({"label_url": label_url, "error": str(error), "array_schemas": schemas})
            if len(list(failed_label_dir.glob("*.xml"))) < 12:
                (failed_label_dir / Path(urlsplit(label_url).path).name).write_bytes(raw)

    qualified.sort(key=lambda item: (str(item["logical_identifier"]), str(item["payload_url"])))
    columns = (
        "logical_identifier", "product_title", "label_url", "payload_url", "label_bytes",
        "label_sha256", "file_bytes", "array_offset", "array_bytes", "value_count",
        "lines", "samples", "bands", "array_kind", "data_type", "endianness",
        "parsing_standard_id",
    )
    with (args.output_dir / "qualified.tsv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(qualified)
    (args.output_dir / "label_failures.json").write_text(
        json.dumps(failures, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    total_bytes = sum(int(item["array_bytes"]) for item in qualified)
    summary = {
        "active_root": active_root,
        "candidate_id": CANDIDATE_ID,
        "directories_visited": len(directory_reports),
        "labels_discovered": len(labels),
        "labels_attempted": min(len(labels), MAX_PARSED_LABELS),
        "label_failures": len(failures),
        "qualified_arrays": len(qualified),
        "qualified_array_bytes": total_bytes,
        "qualified_values": total_bytes // 2,
        "data_types": sorted({str(item["data_type"]) for item in qualified}),
        "endiannesses": sorted({str(item["endianness"]) for item in qualified}),
        "nasa_policy_evidence": policy_phrases,
        "image_payload_bytes_downloaded": 0,
    }
    (args.output_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    if len(qualified) < 4:
        raise SystemExit("fewer than four native-int16 Mastcam-Z arrays qualified")
    if total_bytes < 10_000_000:
        raise SystemExit("qualified native-int16 Mastcam-Z material is too small")
    if total_bytes > MAX_TOTAL_QUALIFIED_BYTES:
        raise SystemExit("qualified discovery material exceeds aggregate reporting bound")


if __name__ == "__main__":
    main()
