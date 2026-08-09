#!/usr/bin/env python3
"""Bounded range-first discovery for native-16-bit Cassini VIMS QUBEs."""
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


CANDIDATE_ID = "nasa_pds_cassini_vims_qube_i16"
POLICY_URL = "https://science.nasa.gov/researchers/science-data/science-information-policy/"
OFFICIAL_HOST = "pds-imaging.jpl.nasa.gov"
USER_AGENT = "openzl-public-datasets-cassini-vims-label-discovery/1.0"
MAX_POLICY_BYTES = 5_000_000
MAX_LISTING_BYTES = 20_000_000
MAX_INDEX_BYTES = 100_000_000
MAX_LABEL_PREFIX_BYTES = 32_768
MAX_DETACHED_LABEL_BYTES = 2_000_000
MAX_FILE_BYTES = 250_000_000
MAX_TOTAL_CORE_BYTES = 2_000_000_000
HREF_RE = re.compile(r"(?i)href\s*=\s*['\"]([^'\"]+)['\"]")
PRODUCT_PATH_RE = re.compile(
    r"(?i)([A-Za-z0-9_.+\\/-]+\.(?:qub|lbl))(?=[\s,\"']|$)"
)
INTEGER_TYPES = {
    "MSB_INTEGER": ("int", "big"),
    "MSB_UNSIGNED_INTEGER": ("uint", "big"),
    "SUN_INTEGER": ("int", "big"),
    "SUN_UNSIGNED_INTEGER": ("uint", "big"),
    "LSB_INTEGER": ("int", "little"),
    "LSB_UNSIGNED_INTEGER": ("uint", "little"),
    "PC_INTEGER": ("int", "little"),
    "PC_UNSIGNED_INTEGER": ("uint", "little"),
}


def curl_bytes(url: str, maximum: int, byte_range: tuple[int, int] | None = None) -> bytes:
    command = [
        "curl", "--fail", "--silent", "--show-error", "--location",
        "--retry", "4", "--retry-delay", "2", "--max-time", "300",
        "--max-filesize", str(maximum), "--user-agent", USER_AGENT,
    ]
    if byte_range is not None:
        command.extend(["--range", f"{byte_range[0]}-{byte_range[1]}"])
    command.append(url)
    result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if result.returncode or not result.stdout or len(result.stdout) > maximum:
        detail = result.stderr.decode("utf-8", "replace").strip()
        raise RuntimeError(f"{url}: {detail or 'bounded fetch failed'}")
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


def clean_url(base: str, reference: str) -> str:
    absolute = urljoin(base, html.unescape(reference).replace("\\", "/"))
    parts = urlsplit(absolute)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))


def official_url(url: str, archive_root: str) -> bool:
    parsed = urlsplit(url)
    return (
        parsed.scheme == "https"
        and parsed.hostname == OFFICIAL_HOST
        and url.startswith(archive_root)
    )


def directory_links(url: str, archive_root: str) -> tuple[list[str], bytes]:
    raw = curl_bytes(url, MAX_LISTING_BYTES)
    text = raw.decode("utf-8", "replace")
    links = {
        clean_url(url, reference)
        for reference in HREF_RE.findall(text)
    }
    return sorted(link for link in links if official_url(link, archive_root)), raw


def pds_value(text: str, key: str) -> str:
    pattern = re.compile(
        rf"(?im)^\s*{re.escape(key)}\s*=\s*(\([^)]*\)|[^\r\n]*)"
    )
    match = pattern.search(text)
    return match.group(1).strip().strip('"') if match else ""


def tuple_tokens(value: str) -> list[str]:
    if not value:
        return []
    inner = value.strip().strip("()")
    return [token.strip().strip('"') for token in inner.split(",") if token.strip()]


def tuple_ints(value: str) -> list[int]:
    result = []
    for token in tuple_tokens(value):
        match = re.fullmatch(r"([-+]?\d+)(?:\s*<[^>]+>)?", token)
        if not match:
            raise ValueError(f"non-integer PDS tuple token: {token}")
        result.append(int(match.group(1)))
    return result


def scalar_int(value: str) -> int:
    match = re.fullmatch(r"([-+]?\d+)(?:\s*<[^>]+>)?", value.strip())
    if not match:
        raise ValueError(f"not a scalar PDS integer: {value}")
    return int(match.group(1))


def label_text(raw: bytes) -> str:
    text = raw.decode("latin-1", "replace")
    match = re.search(r"(?m)^END\s*\r?$", text)
    if not match:
        raise ValueError("PDS3 END marker absent from bounded label prefix")
    return text[:match.end()] + "\n"


def pointer_parts(value: str, current_name: str) -> tuple[str, int]:
    if value.strip().startswith("("):
        tokens = tuple_tokens(value)
        if len(tokens) != 2:
            raise ValueError(f"unsupported QUBE pointer tuple: {value}")
        filename = tokens[0]
        record = scalar_int(tokens[1])
        return filename, record
    return current_name, scalar_int(value)


def parse_product(
    *, raw: bytes, metadata_url: str, payload_url: str, file_bytes: int,
) -> dict[str, object]:
    text = label_text(raw)
    data_set_id = pds_value(text, "DATA_SET_ID").upper()
    instrument_id = pds_value(text, "INSTRUMENT_ID").upper()
    host_id = pds_value(text, "INSTRUMENT_HOST_ID").upper()
    host_name = pds_value(text, "INSTRUMENT_HOST_NAME").upper()
    if not (
        data_set_id.startswith("CO-")
        and "VIMS" in data_set_id
        and instrument_id == "VIMS"
        and (host_id == "CO" or "CASSINI" in host_name)
    ):
        raise ValueError(
            "label does not establish Cassini VIMS provenance: "
            f"dataset={data_set_id!r} instrument={instrument_id!r} "
            f"host_id={host_id!r} host_name={host_name!r}"
        )
    if not re.search(r"(?im)^\s*OBJECT\s*=\s*QUBE\s*$", text):
        raise ValueError("label has no QUBE object")

    item_bytes = scalar_int(pds_value(text, "CORE_ITEM_BYTES"))
    item_type = pds_value(text, "CORE_ITEM_TYPE").upper()
    if item_bytes != 2 or item_type not in INTEGER_TYPES:
        raise ValueError(f"not a supported 16-bit integer core: {item_bytes}/{item_type}")
    numeric_kind, endianness = INTEGER_TYPES[item_type]

    axes = [token.upper() for token in tuple_tokens(pds_value(text, "AXIS_NAME"))]
    items = tuple_ints(pds_value(text, "CORE_ITEMS"))
    if len(axes) != 3 or len(items) != 3 or set(axes) != {"SAMPLE", "BAND", "LINE"}:
        raise ValueError(f"unsupported QUBE axes: axes={axes} items={items}")
    geometry = dict(zip(axes, items))
    if any(value <= 0 for value in geometry.values()):
        raise ValueError(f"nonpositive QUBE geometry: {geometry}")

    suffix_items = tuple_ints(pds_value(text, "SUFFIX_ITEMS") or "(0,0,0)")
    if len(suffix_items) != 3 or any(value < 0 for value in suffix_items):
        raise ValueError(f"invalid QUBE suffix geometry: {suffix_items}")
    suffix_bytes = scalar_int(pds_value(text, "SUFFIX_BYTES")) if any(suffix_items) else 0
    if any(suffix_items) and not 0 < suffix_bytes <= 16:
        raise ValueError(f"invalid QUBE suffix width: {suffix_bytes}")
    record_bytes = scalar_int(pds_value(text, "RECORD_BYTES"))
    pointer_name, pointer_record = pointer_parts(
        pds_value(text, "^QUBE"), Path(urlsplit(payload_url).path).name
    )
    resolved_payload = clean_url(metadata_url, pointer_name)
    if resolved_payload != payload_url:
        raise ValueError(
            f"QUBE pointer target differs from candidate payload: {resolved_payload} != {payload_url}"
        )
    if record_bytes <= 0 or pointer_record <= 0:
        raise ValueError("invalid record geometry or QUBE pointer")
    core_offset = (pointer_record - 1) * record_bytes
    value_count = geometry["SAMPLE"] * geometry["BAND"] * geometry["LINE"]
    core_bytes = value_count * item_bytes
    if not 0 < core_bytes <= MAX_FILE_BYTES:
        raise ValueError(f"QUBE core outside file cap: {core_bytes}")
    expanded_items = [core + suffix for core, suffix in zip(items, suffix_items)]
    expanded_values = expanded_items[0] * expanded_items[1] * expanded_items[2]
    suffix_value_count = expanded_values - value_count
    qube_bytes = core_bytes + suffix_value_count * suffix_bytes
    if not 0 <= core_offset < file_bytes or core_offset + qube_bytes > file_bytes:
        raise ValueError(
            f"QUBE extent exceeds file: offset={core_offset} qube={qube_bytes} file={file_bytes}"
        )

    return {
        "axis_names": axes,
        "bands": geometry["BAND"],
        "core_bytes": core_bytes,
        "core_item_bytes": item_bytes,
        "core_item_type": item_type,
        "core_offset": core_offset,
        "endianness": endianness,
        "file_bytes": file_bytes,
        "instrument_id": pds_value(text, "INSTRUMENT_ID"),
        "label_prefix_bytes": len(raw),
        "label_prefix_sha256": hashlib.sha256(raw).hexdigest(),
        "lines": geometry["LINE"],
        "metadata_url": metadata_url,
        "numeric_kind": numeric_kind,
        "payload_url": payload_url,
        "product_id": pds_value(text, "PRODUCT_ID") or Path(urlsplit(payload_url).path).stem,
        "qube_bytes": qube_bytes,
        "record_bytes": record_bytes,
        "samples": geometry["SAMPLE"],
        "start_time": pds_value(text, "START_TIME"),
        "suffix_items": suffix_items,
        "suffix_bytes": suffix_bytes,
        "suffix_value_count": suffix_value_count,
        "target_name": pds_value(text, "TARGET_NAME"),
        "value_count": value_count,
    }


def volume_urls(archive_root: str, limit: int, output_dir: Path) -> list[str]:
    links, raw = directory_links(archive_root, archive_root)
    (output_dir / "archive_root.html").write_bytes(raw)
    volumes = sorted(
        link for link in links
        if re.search(r"(?i)/covims_\d{4}/$", urlsplit(link).path)
    )
    if not volumes:
        raise SystemExit("official Cassini archive listing exposed no COVIMS volume directories")
    if len(volumes) <= limit:
        return volumes
    if limit == 1:
        return [volumes[0]]
    # Span the mission archive instead of biasing discovery toward cruise and
    # Jupiter-era volumes at the beginning of the lexicographic listing.
    indices = [round(index * (len(volumes) - 1) / (limit - 1)) for index in range(limit)]
    return [volumes[index] for index in indices]


def indexed_product_urls(
    volume_url: str, archive_root: str,
) -> tuple[list[str], list[dict[str, str]]]:
    attempts = []
    candidates = set()
    for relative in ("index/index.tab", "INDEX/INDEX.TAB"):
        index_url = clean_url(volume_url, relative)
        try:
            raw = curl_bytes(index_url, MAX_INDEX_BYTES)
            attempts.append({"url": index_url, "status": "ok", "bytes": str(len(raw))})
        except Exception as error:
            attempts.append({"url": index_url, "status": "failed", "error": str(error)})
            continue
        text = raw.decode("latin-1", "replace")
        for match in PRODUCT_PATH_RE.finditer(text):
            url = clean_url(volume_url, match.group(1))
            if official_url(url, archive_root):
                candidates.add(url)
        if candidates:
            break
    return sorted(candidates), attempts


def crawl_volume_products(
    volume_url: str, archive_root: str, product_limit: int,
) -> tuple[list[str], list[dict[str, object]]]:
    data_root = clean_url(volume_url, "data/")
    queue = deque([(data_root, 0)])
    seen = set()
    products = set()
    reports = []
    while queue and len(seen) < 120 and len(products) < product_limit:
        url, depth = queue.popleft()
        if url in seen:
            continue
        seen.add(url)
        try:
            links, raw = directory_links(url, archive_root)
        except Exception as error:
            reports.append({"url": url, "depth": depth, "error": str(error)})
            continue
        child_directories = []
        child_products = []
        for link in links:
            if not link.startswith(data_root) or link == url:
                continue
            lower_path = urlsplit(link).path.lower()
            if lower_path.endswith((".qub", ".lbl")):
                child_products.append(link)
                products.add(link)
            elif lower_path.endswith("/") and depth < 4:
                child_directories.append(link)
        reports.append({
            "url": url,
            "depth": depth,
            "listing_bytes": len(raw),
            "child_directories": len(child_directories),
            "products": len(child_products),
        })
        # Descend immediately: breadth-first traversal can exhaust the bound
        # enumerating siblings before reaching product-bearing directories.
        for child in reversed(sorted(set(child_directories))):
            if child not in seen:
                queue.appendleft((child, depth + 1))
    return sorted(products)[:product_limit], reports


def inspect_candidate(candidate_url: str) -> dict[str, object]:
    lower = urlsplit(candidate_url).path.lower()
    if lower.endswith(".lbl"):
        raw = curl_bytes(candidate_url, MAX_DETACHED_LABEL_BYTES)
        text = label_text(raw)
        pointer_name, _ = pointer_parts(pds_value(text, "^QUBE"), "")
        payload_url = clean_url(candidate_url, pointer_name)
        metadata_url = candidate_url
    elif lower.endswith(".qub"):
        raw = curl_bytes(
            candidate_url,
            MAX_LABEL_PREFIX_BYTES,
            byte_range=(0, MAX_LABEL_PREFIX_BYTES - 1),
        )
        payload_url = candidate_url
        metadata_url = candidate_url
    else:
        raise ValueError("candidate is neither PDS label nor QUBE")
    if urlsplit(payload_url).hostname != OFFICIAL_HOST:
        raise ValueError("QUBE pointer leaves the official PDS Imaging host")
    size = content_length(payload_url)
    if not 0 < size <= MAX_FILE_BYTES:
        raise ValueError(f"payload size outside bound: {size}")
    return parse_product(
        raw=raw, metadata_url=metadata_url, payload_url=payload_url, file_bytes=size
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--archive-root", required=True)
    parser.add_argument("--volume-limit", type=int, required=True)
    parser.add_argument("--candidate-limit", type=int, required=True)
    parser.add_argument("--qualified-limit", type=int, required=True)
    args = parser.parse_args()
    if not (1 <= args.volume_limit <= 20):
        raise SystemExit("volume limit must be 1..20")
    if not (1 <= args.candidate_limit <= 2000):
        raise SystemExit("candidate limit must be 1..2000")
    if not (1 <= args.qualified_limit <= 200):
        raise SystemExit("qualified limit must be 1..200")
    archive_root = clean_url(args.archive_root, "./")
    if not archive_root.endswith("/"):
        archive_root += "/"
    if urlsplit(archive_root).hostname != OFFICIAL_HOST:
        raise SystemExit("archive root must use the official PDS Imaging host")
    args.output_dir.mkdir(parents=True, exist_ok=True)

    policy = curl_bytes(POLICY_URL, MAX_POLICY_BYTES)
    policy_text = re.sub(
        r"\s+", " ", re.sub(r"<[^>]+>", " ", policy.decode("utf-8", "replace"))
    ).lower()
    (args.output_dir / "nasa_science_information_policy.html").write_bytes(policy)
    policy_evidence = {
        "public_trust": "public trust" in policy_text,
        "publicly_available": "publicly available" in policy_text,
        "open_sharing": any(
            phrase in policy_text
            for phrase in ("openly shared", "shared openly", "full and open sharing", "open data")
        ),
    }
    if not all(policy_evidence.values()):
        raise SystemExit(f"official NASA information-policy evidence changed: {policy_evidence}")

    volumes = volume_urls(archive_root, args.volume_limit, args.output_dir)
    all_candidates = []
    index_attempts = []
    crawl_reports = []
    per_volume_limit = max(8, (args.candidate_limit + len(volumes) - 1) // len(volumes))
    for volume in volumes:
        indexed_urls, attempts = indexed_product_urls(volume, archive_root)
        crawled_urls, reports = crawl_volume_products(
            volume, archive_root, per_volume_limit
        )
        # Directory-derived URLs carry the actual nested archive path. Index
        # rows in this archive can expose only a basename, which is not enough
        # to construct a valid URL by itself.
        urls = crawled_urls or indexed_urls
        all_candidates.extend(urls)
        index_attempts.extend({"volume": volume, **attempt} for attempt in attempts)
        crawl_reports.extend({"volume": volume, **report} for report in reports)
    candidates = list(dict.fromkeys(all_candidates))[:args.candidate_limit]
    (args.output_dir / "index_attempts.json").write_text(
        json.dumps(index_attempts, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (args.output_dir / "crawl_reports.json").write_text(
        json.dumps(crawl_reports, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    if not candidates:
        raise SystemExit("COVIMS index metadata exposed no .QUB or .LBL product paths")

    qualified = []
    failures = []
    for url in candidates:
        if len(qualified) >= args.qualified_limit:
            break
        try:
            item = inspect_candidate(url)
            if item["payload_url"] in {entry["payload_url"] for entry in qualified}:
                continue
            qualified.append(item)
            print(
                f"qualified product={item['product_id']} target={item['target_name']} "
                f"shape={item['lines']}x{item['bands']}x{item['samples']} "
                f"type={item['core_item_type']} bytes={item['core_bytes']}"
            )
        except Exception as error:
            failures.append({"candidate_url": url, "error": str(error)})

    columns = (
        "product_id", "target_name", "start_time", "metadata_url", "payload_url",
        "file_bytes", "core_offset", "core_bytes", "value_count", "lines", "bands",
        "samples", "axis_names", "core_item_type", "core_item_bytes", "numeric_kind",
        "endianness", "suffix_items", "suffix_bytes", "suffix_value_count", "qube_bytes",
        "record_bytes", "instrument_id",
        "label_prefix_bytes", "label_prefix_sha256",
    )
    with (args.output_dir / "qualified.tsv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        for item in qualified:
            writer.writerow({
                key: json.dumps(item[key]) if isinstance(item[key], list) else item[key]
                for key in columns
            })
    (args.output_dir / "failures.json").write_text(
        json.dumps(failures, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    total_bytes = sum(int(item["core_bytes"]) for item in qualified)
    range_probe_bytes = sum(int(item["label_prefix_bytes"]) for item in qualified)
    numeric_prefix_bytes = sum(
        max(0, int(item["label_prefix_bytes"]) - int(item["core_offset"]))
        for item in qualified
    )
    summary = {
        "archive_root": archive_root,
        "candidate_id": CANDIDATE_ID,
        "candidate_urls": len(candidates),
        "failures": len(failures),
        "nasa_policy_evidence": policy_evidence,
        "qualified_numeric_prefix_probe_bytes": numeric_prefix_bytes,
        "qualified_range_probe_bytes": range_probe_bytes,
        "qualified_core_bytes": total_bytes,
        "qualified_products": len(qualified),
        "qualified_values": total_bytes // 2,
        "targets": sorted({str(item["target_name"]) for item in qualified}),
        "types": sorted({str(item["core_item_type"]) for item in qualified}),
        "volumes": volumes,
    }
    (args.output_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    if len(qualified) < 8:
        raise SystemExit("fewer than eight simple native-16-bit Cassini VIMS QUBEs qualified")
    if total_bytes < 10_000_000:
        raise SystemExit("qualified Cassini VIMS material is below the useful-size floor")
    if total_bytes > MAX_TOTAL_CORE_BYTES:
        raise SystemExit("qualified Cassini VIMS material exceeds the reporting bound")


if __name__ == "__main__":
    main()
