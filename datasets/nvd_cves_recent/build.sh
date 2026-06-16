#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
DATASET_ID="nvd_cves_recent"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$DATASET_ID"
DOWNLOAD_DIR="$REPO_ROOT/$DATA_DIR/downloads/$DATASET_ID"
FILTER_DIR="$REPO_ROOT/$DATA_DIR/filtered/$DATASET_ID"
INDEX_DIR="$REPO_ROOT/$DATA_DIR/index/$DATASET_ID"
SAMPLES_DIR="$REPO_ROOT/$DATA_DIR/samples/$DATASET_ID"
mkdir -p "$LOG_DIR" "$DOWNLOAD_DIR" "$FILTER_DIR" "$INDEX_DIR" "$SAMPLES_DIR"

RUN_TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="$LOG_DIR/build.$RUN_TS.log"
LATEST_LOG="$LOG_DIR/build.latest.log"
exec > >(tee "$LOG_FILE" "$LATEST_LOG") 2>&1

echo "[$(date -Is)] build start dataset=$DATASET_ID"
export REPO_ROOT DATA_DIR DOWNLOAD_DIR FILTER_DIR INDEX_DIR SAMPLES_DIR
python3 - <<'PY'
from __future__ import annotations

import calendar
import json
import os
import re
import shutil
import statistics
import struct
from datetime import datetime
from pathlib import Path

DATASET_ID = "nvd_cves_recent"
MIN_CVE_RECORDS = 10_000
MIN_PRIMARY_VALUES = 10_000
MIN_PRIMARY_BYTES = 100 * 1024
MIN_MEDIAN_VALUES = 1_000
MAX_PRIMARY_BYTES = 1_000_000_000

SERIES = {
    "nvd_published_at": ("uint", 32, "I", "Publication timestamp seconds since Unix epoch."),
    "nvd_last_modified_at": ("uint", 32, "I", "Last-modified timestamp seconds since Unix epoch."),
    "nvd_reference_count": ("uint", 16, "H", "Number of NVD reference URLs attached to the CVE."),
    "nvd_cvss_base_score_x10": ("uint", 16, "H", "Primary CVSS base score scaled by 10; 0 is used only when no metric is present."),
    "nvd_primary_cwe_id": ("uint", 16, "H", "First numeric CWE identifier, or 0 for noinfo/other/missing."),
    "nvd_cpe_match_count": ("uint", 16, "H", "Number of CPE match entries in the NVD configuration tree."),
}

repo_root = Path(os.environ["REPO_ROOT"])
data_root = repo_root / os.environ["DATA_DIR"]
download_dir = Path(os.environ["DOWNLOAD_DIR"])
filter_dir = Path(os.environ["FILTER_DIR"])
index_dir = Path(os.environ["INDEX_DIR"])
samples_dir = Path(os.environ["SAMPLES_DIR"])
inventory_path = download_dir / "download_inventory.json"
if not inventory_path.exists():
    raise SystemExit(f"missing download inventory: {inventory_path}")


def rel(path: Path) -> str:
    return path.relative_to(data_root).as_posix()


def parse_ts(raw: str) -> int:
    text = raw.strip().replace("Z", "")
    return calendar.timegm(datetime.strptime(text[:19], "%Y-%m-%dT%H:%M:%S").utctimetuple())


def reference_count(cve: dict) -> int:
    refs = cve.get("references", [])
    if isinstance(refs, list):
        return len(refs)
    if isinstance(refs, dict):
        data = refs.get("referenceData", [])
        return len(data) if isinstance(data, list) else 0
    return 0


def cvss_base_score_x10(cve: dict) -> int:
    metrics = cve.get("metrics", {}) or {}
    for key in ("cvssMetricV40", "cvssMetricV31", "cvssMetricV30", "cvssMetricV2"):
        entries = metrics.get(key)
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            data = entry.get("cvssData", {})
            score = data.get("baseScore")
            if isinstance(score, (int, float)):
                return max(0, min(100, int(round(float(score) * 10))))
    return 0


def primary_cwe_id(cve: dict) -> int:
    for weakness in cve.get("weaknesses", []) or []:
        for description in weakness.get("description", []) or []:
            value = str(description.get("value", ""))
            match = re.search(r"CWE-(\d+)", value)
            if match:
                return min(65535, int(match.group(1)))
    return 0


def cpe_match_count_node(node) -> int:
    if isinstance(node, dict):
        count = 0
        matches = node.get("cpeMatch")
        if isinstance(matches, list):
            count += len(matches)
        for child in node.get("nodes", []) or []:
            count += cpe_match_count_node(child)
        return count
    if isinstance(node, list):
        return sum(cpe_match_count_node(item) for item in node)
    return 0


def cpe_match_count(cve: dict) -> int:
    return cpe_match_count_node(cve.get("configurations", []))


def bounded_u16(value: int, field: str, cve_id: str) -> int:
    if value < 0 or value > 65535:
        raise ValueError(f"{cve_id}: {field} outside uint16 range: {value}")
    return value


inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
records = inventory.get("records", [])
if not records:
    raise SystemExit("download inventory has no records")

by_id: dict[str, dict] = {}
raw_count = 0
malformed = 0
for record in records:
    path = download_dir / record["local_name"]
    obj = json.load(open(path, encoding="utf-8"))
    for wrapper in obj.get("vulnerabilities", []) or []:
        raw_count += 1
        cve = wrapper.get("cve", {})
        cve_id = str(cve.get("id", "")).strip()
        if not cve_id:
            malformed += 1
            continue
        by_id[cve_id] = cve

items = []
for cve_id, cve in by_id.items():
    try:
        published = parse_ts(str(cve["published"]))
        modified = parse_ts(str(cve["lastModified"]))
        row = {
            "cve_id": cve_id,
            "published": published,
            "last_modified": modified,
            "reference_count": bounded_u16(reference_count(cve), "reference_count", cve_id),
            "cvss_base_score_x10": bounded_u16(cvss_base_score_x10(cve), "cvss_base_score_x10", cve_id),
            "primary_cwe_id": bounded_u16(primary_cwe_id(cve), "primary_cwe_id", cve_id),
            "cpe_match_count": bounded_u16(cpe_match_count(cve), "cpe_match_count", cve_id),
        }
    except Exception:
        malformed += 1
        continue
    items.append(row)

items.sort(key=lambda item: (item["published"], item["cve_id"]))
if len(items) < MIN_CVE_RECORDS:
    raise SystemExit(f"kept CVE count below repair floor: {len(items)} < {MIN_CVE_RECORDS}")

values_by_series = {
    "nvd_published_at": [item["published"] for item in items],
    "nvd_last_modified_at": [item["last_modified"] for item in items],
    "nvd_reference_count": [item["reference_count"] for item in items],
    "nvd_cvss_base_score_x10": [item["cvss_base_score_x10"] for item in items],
    "nvd_primary_cwe_id": [item["primary_cwe_id"] for item in items],
    "nvd_cpe_match_count": [item["cpe_match_count"] for item in items],
}

for sid, values in values_by_series.items():
    if len(set(values)) <= 1:
        raise SystemExit(f"constant primary series rejected: {sid}")

if samples_dir.exists():
    shutil.rmtree(samples_dir)
samples_dir.mkdir(parents=True, exist_ok=True)
filter_dir.mkdir(parents=True, exist_ok=True)
index_dir.mkdir(parents=True, exist_ok=True)

rows = []
for sid, values in values_by_series.items():
    kind, bits, code, _description = SERIES[sid]
    out_dir = samples_dir / sid
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{sid}_{kind}{bits}_n{len(values):06d}.bin"
    with out.open("wb") as fh:
        fh.write(struct.pack("<" + code * len(values), *values))
    rows.append(
        {
            "dataset_id": DATASET_ID,
            "series_id": sid,
            "role": "primary",
            "sample_path": rel(out),
            "numeric_kind": kind,
            "bit_width": bits,
            "endianness": "little",
            "element_size_bytes": bits // 8,
            "sample_size_bytes": out.stat().st_size,
            "value_count": len(values),
            "sample_geometry": "sequence",
            "sample_rank": 1,
            "sample_shape": [len(values)],
            "sample_axes": ["cve_sorted_by_published"],
        }
    )

sizes = [row["sample_size_bytes"] for row in rows]
counts = [row["value_count"] for row in rows]
primary_bytes = sum(sizes)
primary_values = sum(counts)
median_values = statistics.median(counts)
if primary_values < MIN_PRIMARY_VALUES:
    raise SystemExit(f"primary values below floor: {primary_values}")
if primary_bytes < MIN_PRIMARY_BYTES:
    raise SystemExit(f"primary bytes below floor: {primary_bytes}")
if median_values < MIN_MEDIAN_VALUES:
    raise SystemExit(f"median sample values below floor: {median_values}")
if primary_bytes > MAX_PRIMARY_BYTES:
    raise SystemExit(f"primary bytes exceed cap: {primary_bytes}")

stats = {
    "dataset_id": DATASET_ID,
    "raw_cve_records": raw_count,
    "unique_cve_records": len(by_id),
    "kept_cve_records": len(items),
    "malformed_or_skipped_records": malformed,
    "download_page_count": len(records),
    "source_bytes": inventory.get("source_bytes", 0),
    "primary_values": primary_values,
    "primary_bytes": primary_bytes,
    "series": {
        sid: {
            "count": len(values),
            "min": min(values),
            "max": max(values),
            "distinct_prefix_200k": len(set(values[:200_000])),
        }
        for sid, values in values_by_series.items()
    },
}
(filter_dir / "ingest_stats.json").write_text(json.dumps(stats, indent=2, sort_keys=True) + "\n", encoding="utf-8")
with (index_dir / "samples.jsonl").open("w", encoding="utf-8") as fh:
    for row in rows:
        fh.write(json.dumps(row, sort_keys=True) + "\n")

print(
    f"built_samples={len(rows)} kept_cves={len(items)} primary_values={primary_values} "
    f"primary_bytes={primary_bytes} median_values={int(median_values)}"
)
PY

echo "[$(date -Is)] build done dataset=$DATASET_ID"
