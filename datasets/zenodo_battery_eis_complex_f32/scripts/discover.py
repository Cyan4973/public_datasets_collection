#!/usr/bin/env python3
"""Rank permissively licensed Zenodo battery EIS measurement payloads."""
from __future__ import annotations

import argparse
import csv
import html
import json
from pathlib import Path
import re
import subprocess
from urllib.parse import urlencode


API = "https://zenodo.org/api/records"
USER_AGENT = "openzl-public-datasets-battery-eis-f32-discovery/1.0"
QUERIES = (
    "battery electrochemical impedance spectroscopy dataset",
    "lithium ion battery impedance spectroscopy data",
    "battery EIS aging measurements",
    "battery impedance spectra dataset",
    "electrochemical impedance battery cycling",
    "battery Nyquist impedance data",
)
PAGE_SIZE = 25
PAGES_PER_QUERY = 4
MAX_RESPONSE_BYTES = 20_000_000
MIN_FILE_BYTES = 20_000
MAX_FILE_BYTES = 1_000_000_000
PERMISSIVE_LICENSES = {
    "cc-zero",
    "cc0-1.0",
    "cc-by-1.0",
    "cc-by-2.0",
    "cc-by-2.5",
    "cc-by-3.0",
    "cc-by-4.0",
}
PAYLOAD_SUFFIXES = (
    ".csv", ".tsv", ".txt", ".dat", ".mpt", ".dta", ".xlsx",
    ".npy", ".npz", ".h5", ".hdf5", ".mat", ".zip", ".tar.gz", ".tgz",
)
EIS_TERMS = (
    "electrochemical impedance spectroscopy",
    "impedance spectroscopy",
    "impedance spectra",
    "impedance spectrum",
    "eis measurement",
    "eis data",
    "nyquist",
)
BATTERY_TERMS = (
    "battery", "batteries", "lithium-ion", "lithium ion", "li-ion", "cell cycling",
    "state of charge", "state-of-health", "state of health",
)
COMPLEX_TERMS = (
    "real impedance", "imaginary impedance", "zreal", "zimag", "z_real", "z_imag",
    "real(z)", "imag(z)", "nyquist",
)
DATA_TERMS = (
    "dataset", "raw data", "measurements", "cycling data", "spectra", "sweeps",
    "experimental data",
)
NEGATIVE_TERMS = (
    "simulation only", "synthetic only", "code only", "source code only",
    "trained model", "poster", "presentation", "review article",
)


def curl_json(url: str) -> dict[str, object]:
    command = [
        "curl", "--fail-with-body", "--silent", "--show-error", "--location",
        "--retry", "5", "--retry-all-errors", "--retry-delay", "3",
        "--connect-timeout", "30", "--max-time", "180",
        "--max-filesize", str(MAX_RESPONSE_BYTES), "--user-agent", USER_AGENT, url,
    ]
    result = subprocess.run(
        command, check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    if result.returncode:
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        body = result.stdout.decode("utf-8", errors="replace").strip()[:1_000]
        suffix = f" response={body}" if body else ""
        raise RuntimeError(f"curl failed rc={result.returncode}: {detail}{suffix}")
    if len(result.stdout) > MAX_RESPONSE_BYTES:
        raise RuntimeError("Zenodo response exceeded metadata cap")
    value = json.loads(result.stdout)
    if not isinstance(value, dict):
        raise RuntimeError("Zenodo response is not a JSON object")
    return value


def normalized_text(value: object) -> str:
    text = html.unescape(re.sub(r"<[^>]+>", " ", str(value or ""))).lower()
    return re.sub(r"\s+", " ", text).strip()


def metadata(record: dict[str, object]) -> dict[str, object]:
    value = record.get("metadata", {})
    return value if isinstance(value, dict) else {}


def license_id(record: dict[str, object]) -> str:
    value = metadata(record).get("license", {})
    if isinstance(value, dict):
        raw = str(value.get("id") or value.get("title") or value.get("name") or "")
    else:
        raw = str(value or "")
    normalized = re.sub(
        r"-+", "-", raw.lower().strip().replace("_", "-").replace(" ", "-")
    )
    aliases = {
        "creative-commons-attribution-4.0-international": "cc-by-4.0",
        "creative-commons-zero-v1.0-universal": "cc0-1.0",
        "cc-zero-1.0": "cc0-1.0",
    }
    return aliases.get(normalized, normalized)


def record_text(record: dict[str, object]) -> str:
    meta = metadata(record)
    values = [meta.get("title", ""), meta.get("description", ""), meta.get("notes", "")]
    keywords = meta.get("keywords", [])
    if isinstance(keywords, list):
        values.extend(keywords)
    return normalized_text(" ".join(str(value) for value in values))


def file_url(file_object: dict[str, object]) -> str:
    links = file_object.get("links", {})
    if not isinstance(links, dict):
        return ""
    return str(links.get("content") or links.get("self") or "")


def relevant_suffix(name: str) -> str:
    lowered = name.lower()
    return next((suffix for suffix in PAYLOAD_SUFFIXES if lowered.endswith(suffix)), "")


def score(text: str, filename: str, suffix: str, size: int) -> tuple[int, list[str]]:
    lowered_name = filename.lower()
    notes: list[str] = []
    value = 0
    value += min(sum(term in text for term in EIS_TERMS), 3) * 9
    value += min(sum(term in text for term in BATTERY_TERMS), 3) * 7
    value += min(sum(term in text or term in lowered_name for term in COMPLEX_TERMS), 2) * 5
    value += min(sum(term in text for term in DATA_TERMS), 2) * 3
    if any(term in lowered_name for term in ("eis", "impedance", "nyquist")):
        value += 8
        notes.append("eis_filename")
    if suffix in {".csv", ".tsv", ".txt", ".dat", ".mpt", ".dta"}:
        value += 8
        notes.append("direct_table")
    elif suffix in {".npy", ".npz", ".h5", ".hdf5", ".mat"}:
        value += 7
        notes.append("typed_container")
    elif suffix == ".xlsx":
        value += 4
        notes.append("xlsx_requires_schema_inspection")
    else:
        value += 2
        notes.append("archive_requires_member_inspection")
    if 100_000 <= size <= 500_000_000:
        value += 5
        notes.append("useful_bounded_size")
    if any(term in text for term in NEGATIVE_TERMS):
        value -= 25
        notes.append("possible_nonmeasurement_record")
    return value, notes


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    records_dir = args.output_dir / "records"
    records_dir.mkdir(parents=True, exist_ok=True)

    records: dict[int, dict[str, object]] = {}
    query_stats: list[dict[str, object]] = []
    for query in QUERIES:
        returned = 0
        errors: list[str] = []
        for page in range(1, PAGES_PER_QUERY + 1):
            url = API + "?" + urlencode({"q": query, "size": PAGE_SIZE, "page": page})
            try:
                response = curl_json(url)
            except Exception as error:
                errors.append(f"page {page}: {error}")
                break
            hits_object = response.get("hits", {})
            hits = hits_object.get("hits", []) if isinstance(hits_object, dict) else []
            if not isinstance(hits, list):
                errors.append(f"page {page}: hits payload is not a list")
                break
            if not hits:
                break
            returned += len(hits)
            for record in hits:
                if not isinstance(record, dict):
                    continue
                try:
                    record_id = int(record.get("id"))
                except (TypeError, ValueError):
                    continue
                records[record_id] = record
            if len(hits) < PAGE_SIZE:
                break
        query_stats.append({"query": query, "returned_hits": returned, "errors": errors})

    rows: list[dict[str, object]] = []
    licensed_records = 0
    semantic_records = 0
    for record_id, record in sorted(records.items()):
        license_name = license_id(record)
        if license_name not in PERMISSIVE_LICENSES:
            continue
        licensed_records += 1
        text = record_text(record)
        if not any(term in text for term in EIS_TERMS) or not any(
            term in text for term in BATTERY_TERMS
        ):
            continue
        semantic_records += 1
        meta = metadata(record)
        title = str(meta.get("title", ""))
        doi = str(meta.get("doi", ""))
        files = record.get("files", [])
        if not isinstance(files, list):
            continue
        record_rows = []
        for file_object in files:
            if not isinstance(file_object, dict):
                continue
            filename = str(file_object.get("key") or file_object.get("filename") or "")
            suffix = relevant_suffix(filename)
            if not suffix:
                continue
            try:
                size = int(file_object.get("size", 0))
            except (TypeError, ValueError):
                continue
            url = file_url(file_object)
            if not MIN_FILE_BYTES <= size <= MAX_FILE_BYTES or not url:
                continue
            ranking, notes = score(text, filename, suffix, size)
            row = {
                "score": ranking,
                "record_id": record_id,
                "license": license_name,
                "doi": doi,
                "title": title,
                "filename": filename,
                "suffix": suffix,
                "size_bytes": size,
                "checksum": str(file_object.get("checksum", "")),
                "url": url,
                "ranking_notes": ",".join(notes),
            }
            rows.append(row)
            record_rows.append(row)
        if record_rows:
            (records_dir / f"{record_id}.json").write_text(
                json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )

    rows.sort(
        key=lambda row: (
            -int(row["score"]), int(row["size_bytes"]),
            int(row["record_id"]), str(row["filename"]),
        )
    )
    fields = (
        "score", "record_id", "license", "doi", "title", "filename",
        "suffix", "size_bytes", "checksum", "url", "ranking_notes",
    )
    with (args.output_dir / "candidates.tsv").open(
        "w", encoding="utf-8", newline=""
    ) as handle:
        writer = csv.DictWriter(
            handle, fieldnames=fields, delimiter="\t", lineterminator="\n"
        )
        writer.writeheader()
        writer.writerows(rows)
    summary = {
        "queries": query_stats,
        "unique_records": len(records),
        "permissively_licensed_records": licensed_records,
        "battery_eis_records": semantic_records,
        "candidate_files": len(rows),
        "top_candidate_files": rows[:20],
    }
    (args.output_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(
        {key: value for key, value in summary.items() if key != "top_candidate_files"},
        indent=2, sort_keys=True,
    ))
    print(f"candidate_table={args.output_dir / 'candidates.tsv'}")
    if not records and any(item["errors"] for item in query_stats):
        raise SystemExit("all Zenodo metadata queries failed; see summary.json")


if __name__ == "__main__":
    main()
