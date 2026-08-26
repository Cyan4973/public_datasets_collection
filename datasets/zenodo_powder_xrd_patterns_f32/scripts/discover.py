#!/usr/bin/env python3
# Broad license-first source discovery.
from __future__ import annotations

import argparse
import binascii
import csv
import html
import json
import math
from pathlib import Path, PurePosixPath
import re
import struct
import subprocess
from urllib.parse import urlencode
import zlib


DATASET_ID = "zenodo_powder_xrd_patterns_f32"
API = "https://zenodo.org/api/records"
USER_AGENT = "openzl-public-datasets-powder-xrd-f32-discovery/1.0"
QUERIES = (
    '"powder X-ray diffraction" data',
    '"powder XRD" dataset',
    'PXRD experimental data',
    '"XRD patterns" experimental',
    '"in situ XRD" data',
    'diffractogram powder',
)
PAGE_SIZE = 25
PAGES_PER_QUERY = 4
MAX_RECORDS = 400
MAX_PROBES = 120
MAX_ARCHIVE_PROBES = 40
MAX_ARCHIVE_BYTES = 1_000_000_000
MAX_CENTRAL_BYTES = 20 * 1024 * 1024
MAX_TEXT_BYTES = 5 * 1024 * 1024
MAX_COMPRESSED_TEXT_BYTES = 2 * 1024 * 1024
PREFIX_BYTES = 512 * 1024
MIN_ROWS = 1_000
MAX_ROWS = 10_000_000
PERMISSIVE_LICENSES = {
    "cc-zero",
    "cc0-1.0",
    "cc-by-1.0",
    "cc-by-2.0",
    "cc-by-2.5",
    "cc-by-3.0",
    "cc-by-4.0",
}
TEXT_SUFFIXES = {".xy", ".xye", ".chi", ".uxd", ".dat", ".csv", ".tsv", ".txt"}
ARCHIVE_SUFFIXES = {".zip"}
DOMAIN_TERMS = (
    "powder x-ray diffraction",
    "powder x ray diffraction",
    "powder xrd",
    "pxrd",
    "x-ray diffraction pattern",
    "xrd pattern",
    "diffractogram",
    "in situ xrd",
    "operando xrd",
)
MEASURED_TERMS = (
    "experimental",
    "experiment",
    "measured",
    "measurement",
    "characterization",
    "characterisation",
    "synchrotron",
    "laboratory",
    "in situ",
    "operando",
    "ex situ",
    "raw data",
)
SIMULATION_TERMS = (
    "simulated pattern",
    "calculated pattern",
    "synthetic xrd",
    "generated xrd",
    "machine-learning generated",
)


def curl_bytes(url: str, *, cap: int, byte_range: str | None = None) -> bytes:
    command = [
        "curl",
        "--fail-with-body",
        "--silent",
        "--show-error",
        "--location",
        "--retry",
        "3",
        "--retry-delay",
        "2",
        "--max-time",
        "180",
        "--max-filesize",
        str(cap),
        "--user-agent",
        USER_AGENT,
    ]
    if byte_range is not None:
        command.extend(("--range", byte_range))
    command.append(url)
    result = subprocess.run(command, check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if result.returncode:
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        body = result.stdout.decode("utf-8", errors="replace").strip()[:600]
        suffix = f" response={body}" if body else ""
        raise RuntimeError(f"curl failed rc={result.returncode}: {detail}{suffix}")
    if len(result.stdout) > cap:
        raise RuntimeError(f"response exceeds cap: {len(result.stdout)} > {cap}")
    return result.stdout


def curl_json(url: str) -> dict[str, object]:
    value = json.loads(curl_bytes(url, cap=20_000_000))
    if not isinstance(value, dict):
        raise ValueError("Zenodo response is not a JSON object")
    return value


def archive_range(url: str, start: int, size: int, maximum: int) -> bytes:
    if start < 0 or not 0 < size <= maximum:
        raise ValueError(f"invalid range start={start} size={size}")
    raw = curl_bytes(url, cap=size, byte_range=f"{start}-{start + size - 1}")
    if len(raw) != size:
        raise ValueError(f"range response length {len(raw)} != {size}")
    return raw


def normalize_text(value: object) -> str:
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
    normalized = re.sub(r"-+", "-", raw.lower().strip().replace("_", "-").replace(" ", "-"))
    aliases = {
        "creative-commons-attribution-4.0-international": "cc-by-4.0",
        "creative-commons-zero-v1.0-universal": "cc0-1.0",
        "cc-zero-1.0": "cc0-1.0",
    }
    return aliases.get(normalized, normalized)


def record_semantics(record: dict[str, object]) -> tuple[bool, list[str]]:
    meta = metadata(record)
    fields = [meta.get("title", ""), meta.get("description", ""), meta.get("notes", "")]
    keywords = meta.get("keywords", [])
    if isinstance(keywords, list):
        fields.extend(keywords)
    text = normalize_text(" ".join(str(item) for item in fields))
    reasons = []
    if not any(term in text for term in DOMAIN_TERMS):
        reasons.append("no_powder_xrd_semantics")
    measured = any(term in text for term in MEASURED_TERMS)
    simulated = any(term in text for term in SIMULATION_TERMS)
    if not measured:
        reasons.append("no_measurement_evidence")
    if simulated and not measured:
        reasons.append("simulation_only")
    return not reasons, reasons


def file_url(file_obj: dict[str, object]) -> str:
    links = file_obj.get("links", {})
    if not isinstance(links, dict):
        return ""
    return str(links.get("content") or links.get("self") or "")


def decode_text(raw: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-16", "ascii", "latin-1"):
        try:
            text = raw.decode(encoding)
        except UnicodeDecodeError:
            continue
        if "\x00" not in text:
            return text
    raise ValueError("unsupported text encoding or binary content")


def numeric_tokens(line: str) -> list[float] | None:
    stripped = line.strip()
    if not stripped or stripped.startswith(("#", "%", ";", "//", "'", '"')):
        return None
    tokens = [token for token in re.split(r"[\s,;]+", stripped) if token]
    if not 2 <= len(tokens) <= 5:
        return None
    values = []
    for token in tokens:
        token = token.replace("D", "E").replace("d", "e")
        try:
            value = float(token)
        except ValueError:
            return None
        if not math.isfinite(value):
            return None
        values.append(value)
    return values


def inspect_table(raw: bytes, complete: bool) -> dict[str, object]:
    text = decode_text(raw)
    lines = text.splitlines()
    if not complete and text and not text.endswith(("\n", "\r")):
        lines = lines[:-1]
    rows = []
    widths: dict[int, int] = {}
    for line in lines:
        values = numeric_tokens(line)
        if values is None:
            continue
        widths[len(values)] = widths.get(len(values), 0) + 1
        rows.append(values)
        if len(rows) >= MAX_ROWS:
            break
    if not rows:
        raise ValueError("no numeric table rows")
    width = max(widths, key=widths.get)
    rows = [row for row in rows if len(row) == width]
    if len(rows) < MIN_ROWS:
        raise ValueError(f"too few numeric rows in bounded probe: {len(rows)}")
    coordinates = [row[0] for row in rows]
    intensities = [row[1] for row in rows]
    increasing = sum(right > left for left, right in zip(coordinates, coordinates[1:]))
    monotonic_fraction = increasing / max(1, len(coordinates) - 1)
    if monotonic_fraction < 0.98:
        raise ValueError(f"first numeric column is not a monotonic scan axis: {monotonic_fraction:.4f}")
    if len(set(intensities)) < 32 or min(intensities) == max(intensities):
        raise ValueError("intensity column is degenerate")
    steps = [right - left for left, right in zip(coordinates, coordinates[1:]) if right > left]
    return {
        "rows_in_probe": len(rows),
        "column_count": width,
        "complete_file": complete,
        "coordinate_min": min(coordinates),
        "coordinate_max": max(coordinates),
        "coordinate_monotonic_fraction": monotonic_fraction,
        "median_positive_step": sorted(steps)[len(steps) // 2] if steps else 0,
        "intensity_min": min(intensities),
        "intensity_max": max(intensities),
        "intensity_distinct_in_probe": len(set(intensities)),
    }


def zip64_values(extra: bytes, need_u: bool, need_c: bool, need_o: bool) -> tuple[int | None, int | None, int | None]:
    position = 0
    while position + 4 <= len(extra):
        field_id, field_size = struct.unpack_from("<HH", extra, position)
        position += 4
        field = extra[position:position + field_size]
        position += field_size
        if field_id != 1:
            continue
        cursor = 0
        values = []
        for needed in (need_u, need_c, need_o):
            if needed:
                if cursor + 8 > len(field):
                    raise ValueError("truncated ZIP64 extra field")
                values.append(struct.unpack_from("<Q", field, cursor)[0])
                cursor += 8
            else:
                values.append(None)
        return values[0], values[1], values[2]
    raise ValueError("ZIP64 sentinel without ZIP64 extra field")


def remote_zip_members(url: str, archive_size: int) -> list[dict[str, object]]:
    tail_size = min(archive_size, 65_557)
    tail = archive_range(url, archive_size - tail_size, tail_size, 65_557)
    position = tail.rfind(b"PK\x05\x06")
    if position < 0 or position + 22 > len(tail):
        raise ValueError("ZIP end record not found")
    fields = struct.unpack_from("<4s4H2LH", tail, position)
    _, disk, central_disk, disk_entries, total, central_size, central_offset, comment_size = fields
    if disk or central_disk or position + 22 + comment_size > len(tail):
        raise ValueError("spanned or malformed ZIP")
    if total == 0xFFFF or central_size == 0xFFFFFFFF or central_offset == 0xFFFFFFFF:
        locator_position = tail.rfind(b"PK\x06\x07", 0, position)
        if locator_position < 0 or locator_position + 20 > len(tail):
            raise ValueError("ZIP64 locator not found")
        _, locator_disk, zip64_offset, disks = struct.unpack_from("<4sLQL", tail, locator_position)
        if locator_disk or disks != 1:
            raise ValueError("spanned ZIP64")
        record = archive_range(url, zip64_offset, 56, 56)
        values = struct.unpack_from("<4sQ2H2L4Q", record)
        if values[0] != b"PK\x06\x06" or values[4] or values[5]:
            raise ValueError("invalid ZIP64 end record")
        total, central_size, central_offset = values[7], values[8], values[9]
    elif disk_entries != total:
        raise ValueError("ZIP entry counts disagree")
    if not 0 < central_size <= MAX_CENTRAL_BYTES or central_offset + central_size > archive_size:
        raise ValueError("invalid or oversized central directory")
    central = archive_range(url, int(central_offset), int(central_size), MAX_CENTRAL_BYTES)
    members = []
    cursor = 0
    while cursor < len(central):
        if cursor + 46 > len(central):
            raise ValueError("truncated central directory")
        fields = struct.unpack_from("<4s6H3L5H2L", central, cursor)
        if fields[0] != b"PK\x01\x02":
            raise ValueError("invalid central member signature")
        flags, method, crc = fields[3], fields[4], fields[7]
        compressed, uncompressed = fields[8], fields[9]
        name_length, extra_length, comment_length, local_offset = fields[10], fields[11], fields[12], fields[16]
        end = cursor + 46 + name_length + extra_length + comment_length
        if end > len(central):
            raise ValueError("central member extends past directory")
        name_raw = central[cursor + 46:cursor + 46 + name_length]
        extra = central[cursor + 46 + name_length:cursor + 46 + name_length + extra_length]
        if uncompressed == 0xFFFFFFFF or compressed == 0xFFFFFFFF or local_offset == 0xFFFFFFFF:
            u64, c64, o64 = zip64_values(
                extra,
                uncompressed == 0xFFFFFFFF,
                compressed == 0xFFFFFFFF,
                local_offset == 0xFFFFFFFF,
            )
            uncompressed = u64 if u64 is not None else uncompressed
            compressed = c64 if c64 is not None else compressed
            local_offset = o64 if o64 is not None else local_offset
        encoding = "utf-8" if flags & 0x800 else "cp437"
        members.append(
            {
                "name": name_raw.decode(encoding, errors="replace"),
                "flags": flags,
                "method": method,
                "crc32": crc,
                "compressed_size": compressed,
                "uncompressed_size": uncompressed,
                "local_offset": local_offset,
            }
        )
        cursor = end
    if cursor != len(central) or len(members) != total:
        raise ValueError(f"ZIP member count mismatch parsed={len(members)} expected={total}")
    return members


def extract_small_member(url: str, member: dict[str, object]) -> bytes:
    offset = int(member["local_offset"])
    fixed = archive_range(url, offset, 30, 30)
    fields = struct.unpack("<4s5H3L2H", fixed)
    if fields[0] != b"PK\x03\x04" or fields[2] != member["flags"] or fields[3] != member["method"]:
        raise ValueError("local and central ZIP headers disagree")
    flags, method, name_length, extra_length = fields[2], fields[3], fields[9], fields[10]
    if flags & 1:
        raise ValueError("encrypted ZIP member")
    variable = archive_range(url, offset + 30, name_length + extra_length, 2 * 1024 * 1024)
    encoding = "utf-8" if flags & 0x800 else "cp437"
    if variable[:name_length].decode(encoding, errors="replace") != member["name"]:
        raise ValueError("local and central ZIP names disagree")
    compressed_size = int(member["compressed_size"])
    if not 0 < compressed_size <= MAX_COMPRESSED_TEXT_BYTES:
        raise ValueError("compressed text member exceeds bounded probe cap")
    compressed = archive_range(
        url,
        offset + 30 + name_length + extra_length,
        compressed_size,
        MAX_COMPRESSED_TEXT_BYTES,
    )
    if method == 0:
        raw = compressed
    elif method == 8:
        raw = zlib.decompress(compressed, -15)
    else:
        raise ValueError(f"unsupported ZIP compression method {method}")
    if len(raw) != int(member["uncompressed_size"]) or len(raw) > MAX_TEXT_BYTES:
        raise ValueError("ZIP text member size mismatch or cap exceeded")
    if binascii.crc32(raw) & 0xFFFFFFFF != int(member["crc32"]):
        raise ValueError("ZIP text member CRC mismatch")
    return raw


def probe_direct(file_obj: dict[str, object]) -> dict[str, object]:
    name = str(file_obj.get("key", ""))
    size = int(file_obj.get("size", 0) or 0)
    url = file_url(file_obj)
    if not url or size <= 0:
        raise ValueError("missing direct-file URL or size")
    amount = min(size, PREFIX_BYTES)
    raw = archive_range(url, 0, amount, PREFIX_BYTES)
    return inspect_table(raw, complete=size <= PREFIX_BYTES)


def write_tsv(path: Path, rows: list[dict[str, object]], fields: list[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n", extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "records").mkdir(exist_ok=True)
    (args.output_dir / "probes").mkdir(exist_ok=True)

    records: dict[int, dict[str, object]] = {}
    query_errors = []
    for query in QUERIES:
        for page in range(1, PAGES_PER_QUERY + 1):
            url = API + "?" + urlencode({"q": query, "size": PAGE_SIZE, "page": page})
            try:
                response = curl_json(url)
            except Exception as exc:
                query_errors.append({"query": query, "page": page, "error": str(exc)})
                continue
            hits_obj = response.get("hits", {})
            hits = hits_obj.get("hits", []) if isinstance(hits_obj, dict) else []
            if not isinstance(hits, list):
                continue
            for record in hits:
                if isinstance(record, dict) and record.get("id") is not None:
                    records[int(record["id"])] = record
                    if len(records) >= MAX_RECORDS:
                        break
            if len(records) >= MAX_RECORDS or len(hits) < PAGE_SIZE:
                break
        if len(records) >= MAX_RECORDS:
            break

    record_rows = []
    candidates = []
    probes = 0
    archive_probes = 0
    for record_id, record in sorted(records.items()):
        meta = metadata(record)
        semantic, semantic_reasons = record_semantics(record)
        license_value = license_id(record)
        licensed = license_value in PERMISSIVE_LICENSES
        files = record.get("files", [])
        files = files if isinstance(files, list) else []
        record_rows.append(
            {
                "record_id": record_id,
                "title": normalize_text(meta.get("title", "")),
                "license": license_value,
                "licensed": int(licensed),
                "semantic": int(semantic),
                "semantic_reasons": ",".join(semantic_reasons),
                "file_count": len(files),
                "record_url": f"https://zenodo.org/records/{record_id}",
            }
        )
        if not licensed or not semantic:
            continue
        for file_obj in files:
            if not isinstance(file_obj, dict):
                continue
            name = str(file_obj.get("key", ""))
            suffix = PurePosixPath(name.lower()).suffix
            size = int(file_obj.get("size", 0) or 0)
            url = file_url(file_obj)
            if suffix in TEXT_SUFFIXES and 1_000 <= size <= 100_000_000 and probes < MAX_PROBES:
                probes += 1
                row = {
                    "record_id": record_id,
                    "title": normalize_text(meta.get("title", "")),
                    "license": license_value,
                    "container": "direct",
                    "archive_name": "",
                    "member_name": name,
                    "source_bytes": size,
                    "url": url,
                    "record_url": f"https://zenodo.org/records/{record_id}",
                    "status": "rejected",
                }
                try:
                    row.update(probe_direct(file_obj))
                    row["status"] = "qualified_probe"
                except Exception as exc:
                    row["reason"] = str(exc)
                candidates.append(row)
            elif suffix in ARCHIVE_SUFFIXES and 1_000 <= size <= MAX_ARCHIVE_BYTES and archive_probes < MAX_ARCHIVE_PROBES:
                archive_probes += 1
                try:
                    members = remote_zip_members(url, size)
                except Exception as exc:
                    candidates.append(
                        {
                            "record_id": record_id,
                            "title": normalize_text(meta.get("title", "")),
                            "license": license_value,
                            "container": "zip",
                            "archive_name": name,
                            "member_name": "",
                            "source_bytes": size,
                            "url": url,
                            "record_url": f"https://zenodo.org/records/{record_id}",
                            "status": "archive_rejected",
                            "reason": str(exc),
                        }
                    )
                    continue
                eligible = [
                    member for member in members
                    if PurePosixPath(str(member["name"]).lower()).suffix in TEXT_SUFFIXES
                    and MIN_ROWS * 8 <= int(member["uncompressed_size"]) <= MAX_TEXT_BYTES
                ]
                for member in eligible[:100]:
                    row = {
                        "record_id": record_id,
                        "title": normalize_text(meta.get("title", "")),
                        "license": license_value,
                        "container": "zip",
                        "archive_name": name,
                        "member_name": member["name"],
                        "source_bytes": member["uncompressed_size"],
                        "url": url,
                        "record_url": f"https://zenodo.org/records/{record_id}",
                        "status": "member_unprobed",
                    }
                    try:
                        raw = extract_small_member(url, member)
                        row.update(inspect_table(raw, complete=True))
                        row["status"] = "qualified_probe"
                    except Exception as exc:
                        row["reason"] = str(exc)
                    candidates.append(row)

    qualified = [row for row in candidates if row["status"] == "qualified_probe"]
    qualified_records = sorted({int(row["record_id"]) for row in qualified})
    write_tsv(
        args.output_dir / "records.tsv",
        record_rows,
        ["record_id", "title", "license", "licensed", "semantic", "semantic_reasons", "file_count", "record_url"],
    )
    write_tsv(
        args.output_dir / "candidates.tsv",
        candidates,
        [
            "record_id", "title", "license", "container", "archive_name", "member_name",
            "source_bytes", "status", "rows_in_probe", "column_count", "complete_file",
            "coordinate_min", "coordinate_max", "coordinate_monotonic_fraction",
            "median_positive_step", "intensity_min", "intensity_max",
            "intensity_distinct_in_probe", "reason", "record_url", "url",
        ],
    )
    summary = {
        "candidate_id": DATASET_ID,
        "queries": list(QUERIES),
        "unique_records": len(records),
        "licensed_semantic_records": sum(bool(row["licensed"] and row["semantic"]) for row in record_rows),
        "direct_and_member_candidates": len(candidates),
        "qualified_scan_probes": len(qualified),
        "qualified_records": qualified_records,
        "archive_probes": archive_probes,
        "file_probes": probes,
        "query_errors": query_errors,
        "qualified": qualified,
    }
    (args.output_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        f"summary unique_records={len(records)} "
        f"licensed_semantic_records={summary['licensed_semantic_records']} "
        f"candidates={len(candidates)} qualified_scan_probes={len(qualified)} "
        f"qualified_records={','.join(map(str, qualified_records)) or 'none'}"
    )
    print(f"summary_path={args.output_dir / 'summary.json'}")
    if not qualified:
        raise SystemExit("no permissively licensed experimental powder-XRD numeric scan passed bounded probing")


if __name__ == "__main__":
    main()
