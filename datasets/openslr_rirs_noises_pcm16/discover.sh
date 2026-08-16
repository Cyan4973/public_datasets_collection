#!/usr/bin/env bash
# Inspect the official OpenSLR page, ZIP directory, and bounded WAV prefixes.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
CANDIDATE_ID="openslr_rirs_noises_pcm16"
OUT_DIR="$REPO_ROOT/$DATA_DIR/discovery/$CANDIDATE_ID"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$CANDIDATE_ID"
PROBE_LIMIT="${PROBE_LIMIT:-32}"

mkdir -p "$OUT_DIR/member_headers" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/discover.$RUN_TS.log" "$LOG_DIR/discover.latest.log") 2>&1
echo "[$(date -Is)] discovery start candidate=$CANDIDATE_ID"

export OUT_DIR PROBE_LIMIT
python3 - <<'PY'
from __future__ import annotations

from collections import defaultdict
from html.parser import HTMLParser
import json
import os
from pathlib import Path, PurePosixPath
import re
import struct
import subprocess
import urllib.parse
import zlib


OUT_DIR = Path(os.environ["OUT_DIR"])
PROBE_LIMIT = int(os.environ["PROBE_LIMIT"])
USER_AGENT = "openzl-public-datasets-openslr-rirs-metadata/1.0"
PAGE_URL = "https://www.openslr.org/28/"
ARCHIVE_URL = "https://www.openslr.org/resources/28/rirs_noises.zip"
MAX_CENTRAL_DIRECTORY = 32 * 1024 * 1024
MEMBER_PREFIX_BYTES = 128 * 1024


class Links(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.hrefs: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "a":
            return
        for key, value in attrs:
            if key.lower() == "href" and value:
                self.hrefs.append(value)


def curl(url: str, *, head: bool = False, byte_range: tuple[int, int] | None = None) -> bytes:
    command = [
        "curl", "--fail", "--silent", "--show-error", "--location",
        "--retry", "3", "--retry-all-errors", "--max-time", "180",
        "--user-agent", USER_AGENT,
    ]
    if head:
        command.append("--head")
    elif byte_range is not None:
        start, end = byte_range
        expected = end - start + 1
        command.extend(["--range", f"{start}-{end}", "--max-filesize", str(expected + 1)])
    else:
        command.extend(["--max-filesize", "5000000"])
    command.append(url)
    result = subprocess.run(command, check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if result.returncode:
        raise RuntimeError(result.stderr.decode("utf-8", errors="replace").strip())
    if byte_range is not None and len(result.stdout) > byte_range[1] - byte_range[0] + 1:
        raise ValueError("server ignored bounded range request")
    return result.stdout


def final_headers(raw: bytes) -> dict[str, str]:
    text = raw.decode("latin-1", errors="replace").replace("\r\n", "\n")
    blocks = re.split(r"(?=^HTTP/)", text, flags=re.MULTILINE)
    block = next((value for value in reversed(blocks) if value.startswith("HTTP/")), "")
    headers: dict[str, str] = {}
    line0 = block.splitlines()[0] if block else ""
    match = re.search(r"\s(\d{3})(?:\s|$)", line0)
    headers["http_status"] = match.group(1) if match else ""
    for line in block.splitlines()[1:]:
        if ":" in line:
            key, value = line.split(":", 1)
            headers[key.strip().lower()] = value.strip()
    return headers


def strip_html(body: bytes) -> str:
    text = body.decode("utf-8", errors="replace")
    text = re.sub(r"<script\b[^>]*>.*?</script>|<style\b[^>]*>.*?</style>", " ", text, flags=re.I | re.S)
    return " ".join(re.sub(r"<[^>]+>", " ", text).split())


def zip64_values(extra: bytes, needs: tuple[bool, bool, bool, bool]) -> list[int | None]:
    payload = None
    offset = 0
    while offset + 4 <= len(extra):
        field_id, size = struct.unpack_from("<HH", extra, offset)
        value = extra[offset + 4 : offset + 4 + size]
        if field_id == 0x0001:
            payload = value
            break
        offset += 4 + size
    values: list[int | None] = []
    cursor = 0
    for needed in needs:
        if needed:
            if payload is None or cursor + 8 > len(payload):
                raise ValueError("missing ZIP64 extended information")
            values.append(struct.unpack_from("<Q", payload, cursor)[0])
            cursor += 8
        else:
            values.append(None)
    return values


def parse_central_directory(data: bytes, expected_entries: int) -> list[dict[str, object]]:
    entries = []
    offset = 0
    while offset < len(data):
        if offset + 46 > len(data) or data[offset : offset + 4] != b"PK\x01\x02":
            raise ValueError(f"invalid central-directory record at offset {offset}")
        fields = struct.unpack_from("<4s6H3I5H2I", data, offset)
        (
            _signature, _made, _needed, flags, method, _mtime, _mdate,
            crc32, compressed, uncompressed, name_len, extra_len, comment_len,
            disk_start, _internal, _external, local_offset,
        ) = fields
        record_end = offset + 46 + name_len + extra_len + comment_len
        if record_end > len(data):
            raise ValueError("truncated central-directory entry")
        name_raw = data[offset + 46 : offset + 46 + name_len]
        encoding = "utf-8" if flags & 0x0800 else "cp437"
        name = name_raw.decode(encoding, errors="strict")
        extra = data[offset + 46 + name_len : offset + 46 + name_len + extra_len]
        z_uncompressed, z_compressed, z_offset, z_disk = zip64_values(
            extra,
            (uncompressed == 0xFFFFFFFF, compressed == 0xFFFFFFFF, local_offset == 0xFFFFFFFF, disk_start == 0xFFFF),
        )
        if z_uncompressed is not None:
            uncompressed = z_uncompressed
        if z_compressed is not None:
            compressed = z_compressed
        if z_offset is not None:
            local_offset = z_offset
        if z_disk not in {None, 0} or disk_start not in {0, 0xFFFF}:
            raise ValueError("multi-disk ZIP is unsupported")
        entries.append(
            {
                "path": name,
                "flags": flags,
                "method": method,
                "crc32": f"{crc32:08x}",
                "compressed_size": compressed,
                "uncompressed_size": uncompressed,
                "local_offset": local_offset,
            }
        )
        offset = record_end
    if len(entries) != expected_entries:
        raise ValueError(f"central-directory count mismatch: {len(entries)} != {expected_entries}")
    return entries


def parse_wav_prefix(data: bytes) -> dict[str, object]:
    if len(data) < 12 or data[:4] not in {b"RIFF", b"RF64"} or data[8:12] != b"WAVE":
        raise ValueError("member is not RIFF/RF64 WAVE")
    offset = 12
    while offset + 8 <= len(data):
        chunk_id = data[offset : offset + 4]
        chunk_size = struct.unpack_from("<I", data, offset + 4)[0]
        payload = offset + 8
        available = min(chunk_size, len(data) - payload)
        if chunk_id == b"fmt ":
            if available < 16:
                raise ValueError("truncated fmt chunk")
            tag, channels, rate, byte_rate, align, bits = struct.unpack_from("<HHIIHH", data, payload)
            valid_bits = bits
            subformat = tag
            if tag == 0xFFFE:
                if available < 40:
                    raise ValueError("truncated extensible fmt chunk")
                valid_bits = struct.unpack_from("<H", data, payload + 18)[0]
                subformat = struct.unpack_from("<H", data, payload + 24)[0]
            return {
                "riff_kind": data[:4].decode("ascii"),
                "format_tag": tag,
                "subformat_tag": subformat,
                "channels": channels,
                "sample_rate": rate,
                "byte_rate": byte_rate,
                "block_align": align,
                "bits_per_sample": bits,
                "valid_bits_per_sample": valid_bits,
                "qualifies_pcm16": subformat == 1 and bits == 16 and valid_bits == 16,
            }
        next_offset = payload + chunk_size + (chunk_size & 1)
        if next_offset <= offset or next_offset > len(data):
            break
        offset = next_offset
    raise ValueError("fmt chunk absent from bounded member prefix")


def member_prefix(entry: dict[str, object]) -> bytes:
    local_offset = int(entry["local_offset"])
    end = local_offset + MEMBER_PREFIX_BYTES - 1
    block = curl(ARCHIVE_URL, byte_range=(local_offset, end))
    if len(block) < 30 or block[:4] != b"PK\x03\x04":
        raise ValueError("invalid local ZIP header")
    fields = struct.unpack_from("<4s5H3I2H", block, 0)
    _sig, _needed, flags, method, _mtime, _mdate, _crc, _csize, _usize, name_len, extra_len = fields
    if flags & 1:
        raise ValueError("encrypted ZIP member")
    if method != int(entry["method"]):
        raise ValueError("local/central compression mismatch")
    data_start = 30 + name_len + extra_len
    compressed = block[data_start:]
    if method == 0:
        return compressed[:8192]
    if method == 8:
        return zlib.decompressobj(-15).decompress(compressed, 8192)
    raise ValueError(f"unsupported ZIP compression method {method}")


# Official resource page and live license evidence.
page = curl(PAGE_URL)
(OUT_DIR / "resource_page.html").write_bytes(page)
page_text = strip_html(page)
parser = Links()
parser.feed(page.decode("utf-8", errors="replace"))
page_links = sorted({urllib.parse.urljoin(PAGE_URL, href) for href in parser.hrefs})
(OUT_DIR / "resource_page_links.txt").write_text("".join(f"{url}\n" for url in page_links))
license_snippets = []
for match in re.finditer(r"license|licence|apache|creative commons|cc\s*by|attribution", page_text, re.I):
    license_snippets.append(page_text[max(0, match.start() - 180) : min(len(page_text), match.end() + 350)])
(OUT_DIR / "license_evidence.json").write_text(
    json.dumps({"url": PAGE_URL, "snippets": license_snippets[:40]}, indent=2, sort_keys=True) + "\n"
)

headers = final_headers(curl(ARCHIVE_URL, head=True))
if not headers.get("content-length", "").isdigit():
    raise SystemExit(f"archive HEAD has no numeric Content-Length: {headers}")
archive_size = int(headers["content-length"])
if archive_size <= 0:
    raise SystemExit("archive size is invalid")

# EOCD is always within the final 65,557 bytes; use a wider bounded tail.
tail_start = max(0, archive_size - 131_072)
tail = curl(ARCHIVE_URL, byte_range=(tail_start, archive_size - 1))
eocd_pos = tail.rfind(b"PK\x05\x06")
if eocd_pos < 0 or eocd_pos + 22 > len(tail):
    raise SystemExit("ZIP end-of-central-directory record not found")
(
    _sig, disk_no, cd_disk, disk_entries, total_entries,
    cd_size, cd_offset, comment_len,
) = struct.unpack_from("<4s4H2IH", tail, eocd_pos)
if disk_no != 0 or cd_disk != 0:
    raise SystemExit("multi-disk ZIP is unsupported")

if total_entries == 0xFFFF or cd_size == 0xFFFFFFFF or cd_offset == 0xFFFFFFFF:
    locator_pos = tail.rfind(b"PK\x06\x07", 0, eocd_pos)
    if locator_pos < 0 or locator_pos + 20 > len(tail):
        raise SystemExit("ZIP64 locator not found")
    _locator_sig, zip64_disk, zip64_offset, total_disks = struct.unpack_from("<4sIQI", tail, locator_pos)
    if zip64_disk != 0 or total_disks != 1:
        raise SystemExit("multi-disk ZIP64 is unsupported")
    fixed = curl(ARCHIVE_URL, byte_range=(zip64_offset, zip64_offset + 55))
    if len(fixed) < 56 or fixed[:4] != b"PK\x06\x06":
        raise SystemExit("ZIP64 EOCD is invalid")
    (
        _zsig, _zsize, _made, _needed, zdisk, zcd_disk,
        _disk_entries64, total_entries64, cd_size64, cd_offset64,
    ) = struct.unpack_from("<4sQ2H2I4Q", fixed, 0)
    if zdisk != 0 or zcd_disk != 0:
        raise SystemExit("multi-disk ZIP64 is unsupported")
    total_entries, cd_size, cd_offset = total_entries64, cd_size64, cd_offset64

if cd_size <= 0 or cd_size > MAX_CENTRAL_DIRECTORY:
    raise SystemExit(f"central directory exceeds metadata cap: {cd_size}")
central = curl(ARCHIVE_URL, byte_range=(cd_offset, cd_offset + cd_size - 1))
entries = parse_central_directory(central, total_entries)

def coherent_group(path: str) -> str:
    parts = [part for part in PurePosixPath(path).parts if part not in {".", ".."}]
    if parts and parts[0].lower() == "rirs_noises":
        parts = parts[1:]
    return "/".join(parts[:3]) if len(parts) >= 3 else "/".join(parts[:-1]) or "root"

wav_entries = []
for entry in entries:
    path = str(entry["path"])
    entry["group"] = coherent_group(path)
    entry["is_wav"] = path.lower().endswith((".wav", ".wave")) and not path.endswith("/")
    if entry["is_wav"]:
        wav_entries.append(entry)

columns = ("path", "group", "method", "flags", "crc32", "compressed_size", "uncompressed_size", "local_offset", "is_wav")
with (OUT_DIR / "archive_inventory.tsv").open("w", encoding="utf-8") as handle:
    handle.write("\t".join(columns) + "\n")
    for entry in entries:
        handle.write("\t".join(str(entry[column]) for column in columns) + "\n")
if not wav_entries:
    raise SystemExit("archive central directory contains no WAV members")

groups: dict[str, list[dict[str, object]]] = defaultdict(list)
for entry in wav_entries:
    groups[str(entry["group"])].append(entry)
with (OUT_DIR / "group_summary.tsv").open("w", encoding="utf-8") as handle:
    handle.write("group\twav_members\tcompressed_member_bytes\tuncompressed_wav_bytes\n")
    for group, members in sorted(groups.items()):
        handle.write(
            f"{group}\t{len(members)}\t{sum(int(x['compressed_size']) for x in members)}\t"
            f"{sum(int(x['uncompressed_size']) for x in members)}\n"
        )

# Probe up to two deterministic members per coherent group, then fill any
# remaining budget round-robin from the archive inventory.
selected: list[dict[str, object]] = []
for group in sorted(groups):
    selected.extend(sorted(groups[group], key=lambda value: str(value["path"]))[:2])
    if len(selected) >= PROBE_LIMIT:
        selected = selected[:PROBE_LIMIT]
        break
if len(selected) < PROBE_LIMIT:
    selected_paths = {str(value["path"]) for value in selected}
    for entry in sorted(wav_entries, key=lambda value: str(value["path"])):
        if str(entry["path"]) not in selected_paths:
            selected.append(entry)
            selected_paths.add(str(entry["path"]))
        if len(selected) >= PROBE_LIMIT:
            break

probe_rows = []
for entry in selected:
    row: dict[str, object] = {"path": entry["path"], "group": entry["group"], "status": "ok"}
    try:
        prefix = member_prefix(entry)
        info = parse_wav_prefix(prefix)
        row.update(info)
        (OUT_DIR / "member_headers" / f"{len(probe_rows):03d}.bin").write_bytes(prefix)
    except Exception as exc:
        row.update({"status": "failed", "qualifies_pcm16": False, "reason": str(exc)})
    probe_rows.append(row)
    print(json.dumps(row, sort_keys=True))

probe_columns = (
    "path", "group", "status", "riff_kind", "format_tag", "subformat_tag", "channels",
    "sample_rate", "byte_rate", "block_align", "bits_per_sample", "valid_bits_per_sample",
    "qualifies_pcm16", "reason",
)
with (OUT_DIR / "wav_probes.tsv").open("w", encoding="utf-8") as handle:
    handle.write("\t".join(probe_columns) + "\n")
    for row in probe_rows:
        handle.write("\t".join(str(row.get(key, "")) for key in probe_columns) + "\n")

summary = {
    "candidate_id": "openslr_rirs_noises_pcm16",
    "resource_page": PAGE_URL,
    "archive_url": ARCHIVE_URL,
    "archive_size_bytes": archive_size,
    "archive_etag": headers.get("etag", ""),
    "archive_last_modified": headers.get("last-modified", ""),
    "license_snippet_count": len(license_snippets),
    "zip_entries": len(entries),
    "wav_members": len(wav_entries),
    "coherent_groups": len(groups),
    "uncompressed_wav_bytes": sum(int(entry["uncompressed_size"]) for entry in wav_entries),
    "wav_headers_probed": len(probe_rows),
    "pcm16_headers": sum(row.get("qualifies_pcm16") is True for row in probe_rows),
}
(OUT_DIR / "summary.json").write_text(
    json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
)
print(json.dumps(summary, indent=2, sort_keys=True))
if not any(row.get("qualifies_pcm16") is True for row in probe_rows):
    raise SystemExit("no representative archive WAV member qualifies as PCM16")
PY

echo "[$(date -Is)] discovery done candidate=$CANDIDATE_ID"
