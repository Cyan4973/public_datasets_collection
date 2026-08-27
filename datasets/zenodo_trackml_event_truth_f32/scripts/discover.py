#!/usr/bin/env python3
"""Find a permissively licensed TrackML release and inventory its archives."""
from __future__ import annotations

import argparse
import csv
import html
import json
from pathlib import Path
import re
from typing import Any


MAX_METADATA_BYTES = 20_000_000
MAX_CANDIDATE_BYTES = 1_000_000_000
PERMISSIVE_LICENSES = {
    "cc-by-4.0",
    "cc-by-3.0",
    "cc0-1.0",
    "cc-zero",
}


def clean_text(value: Any) -> str:
    rendered = html.unescape(re.sub(r"<[^>]+>", " ", str(value or "")))
    return re.sub(r"\s+", " ", rendered).strip()


def metadata(record: dict[str, Any]) -> dict[str, Any]:
    value = record.get("metadata", {})
    return value if isinstance(value, dict) else {}


def license_id(record: dict[str, Any]) -> str:
    value = metadata(record).get("license", {})
    if isinstance(value, dict):
        raw = str(value.get("id") or value.get("title") or value.get("name") or "")
    else:
        raw = str(value or "")
    normalized = re.sub(r"-+", "-", raw.lower().strip().replace("_", "-").replace(" ", "-"))
    aliases = {
        "creative-commons-attribution-4.0-international": "cc-by-4.0",
        "creative-commons-attribution-3.0-unported": "cc-by-3.0",
        "creative-commons-zero-v1.0-universal": "cc0-1.0",
    }
    return aliases.get(normalized, normalized)


def record_text(record: dict[str, Any]) -> str:
    meta = metadata(record)
    parts: list[str] = [
        str(meta.get("title", "")),
        str(meta.get("description", "")),
        str(meta.get("notes", "")),
        str(meta.get("doi", "")),
    ]
    keywords = meta.get("keywords", [])
    if isinstance(keywords, list):
        parts.extend(str(value) for value in keywords)
    return clean_text(" ".join(parts)).lower()


def file_url(file_object: dict[str, Any]) -> str:
    links = file_object.get("links", {})
    if not isinstance(links, dict):
        return ""
    return str(links.get("content") or links.get("self") or "")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--record", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()

    raw = args.record.read_bytes()
    if len(raw) > MAX_METADATA_BYTES:
        raise SystemExit("Zenodo record response exceeds metadata cap")
    response = json.loads(raw)
    if not isinstance(response, dict):
        raise SystemExit("Zenodo record response is not a JSON object")
    hits = [response]

    records: list[dict[str, Any]] = []
    for record in hits:
        if not isinstance(record, dict):
            continue
        text = record_text(record)
        if "trackml" not in text or "particle tracking" not in text:
            continue
        meta = metadata(record)
        identifier = str(record.get("id") or "")
        title = clean_text(meta.get("title"))
        license_name = license_id(record)
        files = record.get("files", [])
        files = files if isinstance(files, list) else []
        score = 0
        if "trackml particle tracking challenge" in title.lower():
            score += 100
        if str(meta.get("resource_type", {})).lower().find("dataset") >= 0:
            score += 30
        if license_name in PERMISSIVE_LICENSES:
            score += 50
        if any(
            isinstance(value, dict)
            and str(value.get("key", "")).lower() == "train_sample.zip"
            for value in files
        ):
            score += 40
        records.append({
            "score": score,
            "record_id": identifier,
            "title": title,
            "doi": str(meta.get("doi") or ""),
            "license": license_name,
            "record": record,
        })

    records.sort(key=lambda row: (-row["score"], row["record_id"]))
    args.output_dir.mkdir(parents=True, exist_ok=True)
    records_path = args.output_dir / "records.tsv"
    with records_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=("score", "record_id", "title", "doi", "license"),
            delimiter="\t",
            lineterminator="\n",
        )
        writer.writeheader()
        for row in records:
            writer.writerow({key: row[key] for key in writer.fieldnames})

    licensed = [row for row in records if row["license"] in PERMISSIVE_LICENSES]
    if not licensed:
        raise SystemExit("no explicit CC BY/CC0 TrackML dataset record was found")
    selected_record = licensed[0]
    record = selected_record["record"]
    files = record.get("files", [])
    files = files if isinstance(files, list) else []

    archive_rows: list[dict[str, Any]] = []
    for file_object in files:
        if not isinstance(file_object, dict):
            continue
        filename = str(file_object.get("key") or "")
        if not filename.lower().endswith((".zip", ".tar.gz", ".tgz")):
            continue
        try:
            size = int(file_object.get("size", 0))
        except (TypeError, ValueError):
            size = 0
        archive_rows.append({
            "filename": filename,
            "size_bytes": size,
            "checksum": str(file_object.get("checksum") or ""),
            "url": file_url(file_object),
        })
    archive_rows.sort(key=lambda row: (row["size_bytes"] or 2**63, row["filename"]))

    files_path = args.output_dir / "files.tsv"
    with files_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=("filename", "size_bytes", "checksum", "url"),
            delimiter="\t",
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(archive_rows)

    exact_samples = [
        row for row in archive_rows
        if row["filename"].lower() == "trackml_40k-events-10-to-50-tracks.tar.gz"
    ]
    bounded_training = [
        row for row in archive_rows
        if row["filename"].lower().startswith("trackml_")
        and row["size_bytes"]
        and row["size_bytes"] <= MAX_CANDIDATE_BYTES
        and row["url"]
    ]
    selected_archive = exact_samples[0] if exact_samples else (
        bounded_training[0] if bounded_training else None
    )

    selected_json = args.output_dir / f"record_{selected_record['record_id']}.json"
    selected_json.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    summary = {
        "candidate_id": "zenodo_trackml_event_truth_f32",
        "matching_record_count": len(records),
        "record_id": selected_record["record_id"],
        "title": selected_record["title"],
        "doi": selected_record["doi"],
        "license": selected_record["license"],
        "archive_count": len(archive_rows),
        "bounded_training_archive_count": len(bounded_training),
        "selected_archive": selected_archive,
        "next_check": "inspect archive members and truth.csv schemas; no payload was downloaded",
    }
    (args.output_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    print(f"records={records_path}")
    print(f"files={files_path}")
    if selected_archive is None:
        raise SystemExit("no bounded TrackML training archive was found")


if __name__ == "__main__":
    main()
