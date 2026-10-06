#!/usr/bin/env python3
"""Zenodo record checks and source selection for the Grape V1 WWV10 recipe.

Pure standard library; reads only local files (curl fetches the record JSON).

Subcommands:
  select   <record.json> <out.tsv>             write the selection table
  check    <record.json> <pinned sources.tsv>  validate identity, license and
                                               that every pinned file is
                                               listed with the same size/md5
  payloads <pinned sources.tsv> <download dir> <summary.tsv>
                                               semantic check of downloaded
                                               files (gzip, identity line,
                                               WWV10 header, column header)
"""
from __future__ import annotations

import csv
import gzip
import hashlib
import html
import json
import re
import sys
from pathlib import Path

RECORD_ID = 6590283
CONCEPT_RECID = "6584416"
EXPECTED_TITLE = "Grape V1 Data: Frequency Estimation and Amplitudes of North American Time Standard Stations"
EXPECTED_LICENSE = "cc-by-4.0"
EXPECTED_FILE_COUNT = 3017
EXPECTED_SELECTED = 920
EXPECTED_SELECTED_BYTES = 614396212
URL_TEMPLATE = "https://zenodo.org/api/records/6590283/files/{key}/content"

# <YYYY-MM-DD>T<HHMMSS>Z_<node>_G1_<grid>_FRQ_WWV10.csv.gz ; S1 receivers,
# other beacons (WWV5, WWV2p5, CHU7) and 'Unknown' files do not match.
KEY_RE = re.compile(
    r"^(\d{4}-\d\d-\d\d)T(\d\d)(\d\d)(\d\d)Z_(N\d+)_(G1)_([A-R]{2}\d\d[a-x]{2})_FRQ_(WWV10)\.csv\.gz$"
)
FIELDS = [
    "sample_order",
    "key",
    "node",
    "receiver",
    "grid",
    "beacon",
    "file_start_utc",
    "size_bytes",
    "md5",
    "url",
    "expected_status",
]


def load_record(path: Path) -> dict:
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        raise SystemExit(f"invalid Zenodo record JSON {path}: {exc}") from exc
    if not isinstance(record, dict):
        raise SystemExit("Zenodo response is not a JSON object")
    if int(record.get("id") or 0) != RECORD_ID:
        raise SystemExit(f"unexpected Zenodo record id {record.get('id')!r}")
    if str(record.get("conceptrecid") or "") != CONCEPT_RECID:
        raise SystemExit(f"unexpected concept record id {record.get('conceptrecid')!r}")
    metadata = record.get("metadata")
    if not isinstance(metadata, dict):
        raise SystemExit("record has no metadata object")
    title = html.unescape(re.sub(r"<[^>]+>", " ", str(metadata.get("title") or ""))).strip()
    if title != EXPECTED_TITLE:
        raise SystemExit(f"record title changed: {title!r}")
    license_value = metadata.get("license")
    license_id = (
        str(license_value.get("id") or "") if isinstance(license_value, dict) else str(license_value or "")
    )
    if license_id.lower() != EXPECTED_LICENSE:
        raise SystemExit(f"record license changed: {license_id!r}")
    if str(metadata.get("access_right") or "") != "open":
        raise SystemExit(f"record is not open access: {metadata.get('access_right')!r}")
    files = record.get("files")
    if not isinstance(files, list) or len(files) != EXPECTED_FILE_COUNT:
        raise SystemExit(f"record file count changed: {len(files) if isinstance(files, list) else files!r}")
    return record


def select(record: dict) -> list[dict]:
    rows = []
    for item in record["files"]:
        key = str(item.get("key") or "")
        match = KEY_RE.match(key)
        if not match:
            continue
        date, hh, mm, ss, node, receiver, grid, beacon = match.groups()
        checksum = str(item.get("checksum") or "")
        if not re.fullmatch(r"md5:[0-9a-f]{32}", checksum):
            raise SystemExit(f"unexpected checksum form for {key}: {checksum!r}")
        rows.append(
            {
                "key": key,
                "node": node,
                "receiver": receiver,
                "grid": grid,
                "beacon": beacon,
                "file_start_utc": f"{date}T{hh}:{mm}:{ss}Z",
                "size_bytes": int(item.get("size") or 0),
                "md5": checksum[4:],
                "url": URL_TEMPLATE.format(key=key),
                "expected_status": "unpinned",
            }
        )
    rows.sort(key=lambda row: (row["node"], row["file_start_utc"], row["key"]))
    for order, row in enumerate(rows):
        row["sample_order"] = order
    if len(rows) != EXPECTED_SELECTED:
        raise SystemExit(f"selected {len(rows)} G1 WWV10 files, expected {EXPECTED_SELECTED}")
    total = sum(row["size_bytes"] for row in rows)
    if total != EXPECTED_SELECTED_BYTES:
        raise SystemExit(f"selected bytes {total}, expected {EXPECTED_SELECTED_BYTES}")
    days = {(row["node"], row["file_start_utc"][:10]) for row in rows}
    if len(days) != len(rows):
        raise SystemExit("more than one file for some node-day")
    return rows


def read_pinned(path: Path) -> list[dict]:
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        if reader.fieldnames != FIELDS:
            raise SystemExit(f"unexpected sources.tsv columns: {reader.fieldnames}")
        return list(reader)


def validate_payloads(sources_path: Path, download_dir: Path, summary_path: Path) -> None:
    """Semantic check of every downloaded file (after curl and md5sum)."""
    pinned = read_pinned(sources_path)
    lines_out = ["key\tsize_bytes\tmd5\tsha256\tdecoded_bytes\tdata_lines"]
    total = 0
    for row in pinned:
        path = download_dir / row["key"]
        raw = path.read_bytes()
        if len(raw) != int(row["size_bytes"]) or hashlib.md5(raw).hexdigest() != row["md5"]:
            raise SystemExit(f"{row['key']}: size/md5 mismatch")
        try:
            text = gzip.decompress(raw).decode("ascii")
        except Exception as exc:  # noqa: BLE001
            raise SystemExit(f"{row['key']}: not a decodable ASCII gzip payload: {exc}") from exc
        first = text.split("\n", 1)[0].rstrip("\r").split(",")
        if (
            len(first) < 6
            or first[0] != "#"
            or first[1] != row["file_start_utc"]
            or first[2] != row["node"]
            or first[3] != row["grid"]
            or first[-2:] != ["G1", "WWV10"]
        ):
            raise SystemExit(f"{row['key']}: identity line does not match the pinned station/beacon: {first[:4]}")
        if not re.search(r"^# Beacon Now Decoded +WWV10\r?$", text, flags=re.MULTILINE):
            raise SystemExit(f"{row['key']}: header does not declare beacon WWV10")
        head, separator, body = text.partition("\nUTC,Freq,Vpk")
        if not separator:
            raise SystemExit(f"{row['key']}: missing 'UTC,Freq,Vpk' column header")
        data_lines = body.count("\n") - 1
        if data_lines < 1:
            raise SystemExit(f"{row['key']}: no data rows")
        lines_out.append(
            f"{row['key']}\t{len(raw)}\t{row['md5']}\t{hashlib.sha256(raw).hexdigest()}\t{len(text)}\t{data_lines}"
        )
        total += len(raw)
    summary_path.write_text("\n".join(lines_out) + "\n", encoding="utf-8")
    print(f"payload_validation=ok files={len(pinned)} bytes={total}")


def main() -> None:
    if len(sys.argv) == 5 and sys.argv[1] == "payloads":
        validate_payloads(Path(sys.argv[2]), Path(sys.argv[3]), Path(sys.argv[4]))
        return
    if len(sys.argv) != 4 or sys.argv[1] not in {"select", "check"}:
        raise SystemExit(__doc__)
    record = load_record(Path(sys.argv[2]))
    rows = select(record)
    if sys.argv[1] == "select":
        with Path(sys.argv[3]).open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=FIELDS, delimiter="\t", lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)
        print(f"selected={len(rows)} bytes={sum(r['size_bytes'] for r in rows)}")
        return
    pinned = read_pinned(Path(sys.argv[3]))
    live = {row["key"]: row for row in rows}
    if len(pinned) != len(live):
        raise SystemExit(f"pinned {len(pinned)} files but record selection has {len(live)}")
    for order, row in enumerate(pinned):
        other = live.get(row["key"])
        if other is None:
            raise SystemExit(f"pinned file missing from record: {row['key']}")
        for field in ("node", "receiver", "grid", "beacon", "file_start_utc", "url"):
            if str(other[field]) != row[field]:
                raise SystemExit(f"{row['key']}: {field} drift {row[field]!r} -> {other[field]!r}")
        if int(row["size_bytes"]) != other["size_bytes"] or row["md5"] != other["md5"]:
            raise SystemExit(f"{row['key']}: size/md5 drift")
        if int(row["sample_order"]) != order or other["sample_order"] != order:
            raise SystemExit(f"{row['key']}: sample_order drift")
    print(
        f"record_check=ok record={RECORD_ID} license={EXPECTED_LICENSE} "
        f"pinned_files={len(pinned)} pinned_bytes={sum(int(r['size_bytes']) for r in pinned)}"
    )


if __name__ == "__main__":
    main()
