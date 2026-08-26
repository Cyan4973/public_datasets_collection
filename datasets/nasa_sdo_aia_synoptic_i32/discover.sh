#!/usr/bin/env bash
# Metadata-only discovery for a fixed historical SDO/AIA synoptic observation.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_DIR="${DATA_DIR:-.data}"
CANDIDATE_ID="nasa_sdo_aia_synoptic_i32"
OUT_DIR="$REPO_ROOT/$DATA_DIR/discovery/$CANDIDATE_ID"
LOG_DIR="$REPO_ROOT/$DATA_DIR/logs/$CANDIDATE_ID"
MONTH_URL="${SDO_SYNOPTIC_MONTH_URL:-https://jsoc1.stanford.edu/data/aia/synoptic/2025/01/}"
MAX_PAGES="${SDO_DISCOVERY_MAX_PAGES:-120}"
MAX_CANDIDATES="${SDO_DISCOVERY_MAX_CANDIDATES:-120}"

mkdir -p "$OUT_DIR/pages" "$LOG_DIR"
RUN_TS="$(date +%Y%m%d_%H%M%S)"
exec > >(tee "$LOG_DIR/discover.$RUN_TS.log" "$LOG_DIR/discover.latest.log") 2>&1
echo "[$(date -Is)] discovery start candidate=$CANDIDATE_ID month=$MONTH_URL"

fetch_policy() {
  local target="$1" url="$2"
  echo "fetch_policy url=$url"
  curl --globoff --fail-with-body --silent --show-error --location \
    --retry 3 --retry-all-errors --connect-timeout 30 --max-time 120 \
    --max-filesize 5000000 --user-agent "openzl-public-datasets/1.0" \
    --output "$target.part" "$url"
  [[ -s "$target.part" ]] || { echo "empty policy response: $url" >&2; exit 1; }
  mv "$target.part" "$target"
}

fetch_policy "$OUT_DIR/sdo_data_access.html" \
  "https://sdo.gsfc.nasa.gov/data/dataaccess.php"
fetch_policy "$OUT_DIR/sdo_copyright.html" \
  "https://sdo.gsfc.nasa.gov/gallery/copyright/"
fetch_policy "$OUT_DIR/nasa_media_usage_guidelines.html" \
  "https://www.nasa.gov/nasa-brand-center/images-and-media/"

export OUT_DIR MONTH_URL MAX_PAGES MAX_CANDIDATES
python3 - <<'PY'
from __future__ import annotations

from collections import defaultdict
from html.parser import HTMLParser
import csv
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import urllib.parse


OUT_DIR = Path(os.environ["OUT_DIR"])
MONTH_URL = os.environ["MONTH_URL"]
MAX_PAGES = int(os.environ["MAX_PAGES"])
MAX_CANDIDATES = int(os.environ["MAX_CANDIDATES"])
USER_AGENT = "openzl-public-datasets-sdo-aia-i32-discovery/1.0"
WAVELENGTHS = (94, 131, 171, 193, 211, 304, 335, 1600, 1700, 4500)


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


def curl_bytes(url: str, *, range_probe: bool = False) -> bytes:
    command = [
        "curl", "--globoff", "--fail", "--silent", "--show-error", "--location",
        "--retry", "3", "--retry-all-errors", "--connect-timeout", "30",
        "--max-time", "120", "--user-agent", USER_AGENT,
    ]
    if range_probe:
        command.extend(["--range", "0-65535", "--max-filesize", "100000"])
    else:
        command.extend(["--max-filesize", "5000000"])
    command.append(url)
    result = subprocess.run(command, check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if result.returncode != 0:
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"curl failed rc={result.returncode}: {detail}")
    if range_probe and len(result.stdout) > 100_000:
        raise RuntimeError("server ignored bounded range request")
    return result.stdout


def within_month(url: str) -> bool:
    parsed = urllib.parse.urlsplit(url)
    root = urllib.parse.urlsplit(MONTH_URL)
    return (
        parsed.scheme in {"http", "https"}
        and parsed.netloc == root.netloc
        and parsed.path.startswith(root.path)
        and not parsed.query
        and not parsed.fragment
    )


def parse_header(data: bytes, start: int) -> tuple[dict[str, str], int]:
    cards: dict[str, str] = {}
    end_offset = None
    for offset in range(start, len(data) - 79, 80):
        card = data[offset : offset + 80].decode("ascii", errors="strict")
        key = card[:8].strip()
        if key == "END":
            end_offset = offset + 80
            break
        if card[8:10] == "= ":
            token = card[10:80].split("/", 1)[0].strip()
            cards[key] = token.strip("'").strip()
    if end_offset is None:
        raise ValueError("FITS END card not found in bounded probe")
    return cards, ((end_offset + 2879) // 2880) * 2880


def parse_image_headers(data: bytes) -> tuple[dict[str, str], dict[str, str]]:
    primary, primary_data_start = parse_header(data, 0)
    if primary.get("SIMPLE", "").upper() != "T":
        raise ValueError("primary HDU does not declare SIMPLE=T")
    primary_bitpix = abs(int(primary.get("BITPIX", "0")))
    primary_naxis = int(primary.get("NAXIS", "0"))
    elements = 0 if primary_naxis == 0 else 1
    for axis in range(1, primary_naxis + 1):
        elements *= int(primary.get(f"NAXIS{axis}", "0"))
    data_bytes = ((primary_bitpix * elements + 7) // 8) + int(primary.get("PCOUNT", "0"))
    extension_start = ((primary_data_start + data_bytes + 2879) // 2880) * 2880
    extension, _ = parse_header(data, extension_start)
    if extension.get("XTENSION", "").upper() != "BINTABLE" or extension.get("ZIMAGE", "").upper() != "T":
        raise ValueError("first extension is not a tiled-compressed FITS image")
    return primary, extension


def integer_token(value: str) -> int:
    return int(value.strip().strip("'"))


def float_token(value: str) -> float:
    return float(value.strip().strip("'").replace("D", "E").replace("d", "e"))


def filename_group(url: str, wavelength: int) -> str:
    parsed = urllib.parse.urlsplit(url)
    name = Path(parsed.path).stem
    suffixes = (f"_{wavelength:04d}", f"{wavelength:04d}")
    for suffix in suffixes:
        if name.endswith(suffix):
            return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, str(Path(parsed.path).parent / name[:-len(suffix)]), "", ""))
    return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, str(Path(parsed.path).parent), "", ""))


root = urllib.parse.urlsplit(MONTH_URL)
if root.scheme != "https" or not root.path.endswith("/"):
    raise SystemExit("SDO_SYNOPTIC_MONTH_URL must be an HTTPS directory URL ending in /")
if "/mostrecent/" in root.path or "/nrt/" in root.path:
    raise SystemExit("mutable mostrecent/nrt paths are forbidden")

stack = [MONTH_URL]
visited: set[str] = set()
pages: list[dict[str, object]] = []
candidates: set[str] = set()
while stack and len(visited) < MAX_PAGES and len(candidates) < MAX_CANDIDATES:
    page_url = stack.pop()
    if page_url in visited:
        continue
    visited.add(page_url)
    try:
        body = curl_bytes(page_url)
    except Exception as exc:
        pages.append({"url": page_url, "status": "failed", "reason": str(exc)})
        continue
    pages.append({"url": page_url, "status": "ok", "bytes": len(body)})
    parser = Links()
    parser.feed(body.decode("utf-8", errors="replace"))
    child_dirs: set[str] = set()
    for href in parser.hrefs:
        if href.startswith(("?", "#")) or href in {"../", "./"}:
            continue
        absolute = urllib.parse.urljoin(page_url, href)
        if not within_month(absolute):
            continue
        path = urllib.parse.urlsplit(absolute).path
        if re.search(r"\.(?:fits|fit|fts)$", path, re.IGNORECASE):
            candidates.add(absolute)
        elif path.endswith("/") and absolute not in visited:
            child_dirs.add(absolute)
    for child in sorted(child_dirs, reverse=True):
        stack.append(child)

(OUT_DIR / "pages.json").write_text(json.dumps(pages, indent=2, sort_keys=True) + "\n")
(OUT_DIR / "candidate_urls.txt").write_text("".join(f"{url}\n" for url in sorted(candidates)))
if not candidates:
    raise SystemExit(f"no dated FITS candidates found under {MONTH_URL}")

rows: list[dict[str, object]] = []
groups: dict[str, dict[int, dict[str, object]]] = defaultdict(dict)
directories: dict[str, dict[int, list[dict[str, object]]]] = defaultdict(
    lambda: defaultdict(list)
)
for url in sorted(candidates):
    row: dict[str, object] = {"url": url}
    try:
        probe = curl_bytes(url, range_probe=True)
        primary, image = parse_image_headers(probe)
        bitpix = integer_token(image.get("ZBITPIX", "0"))
        naxis = integer_token(image.get("ZNAXIS", "0"))
        width = integer_token(image.get("ZNAXIS1", "0"))
        height = integer_token(image.get("ZNAXIS2", "0"))
        bscale = float_token(image.get("BSCALE", primary.get("BSCALE", "1")))
        bzero = float_token(image.get("BZERO", primary.get("BZERO", "0")))
        compression = image.get("ZCMPTYPE", "")
        wavelength_raw = image.get("WAVELNTH", primary.get("WAVELNTH", "0"))
        wavelength = integer_token(wavelength_raw)
        qualifies = (
            bitpix == 32
            and naxis == 2
            and width == 1024
            and height == 1024
            and bscale == 0.0625
            and bzero == 0.0
            and wavelength in WAVELENGTHS
        )
        group = filename_group(url, wavelength)
        directory = url.rsplit("/", 1)[0] + "/"
        row.update({
            "status": "ok",
            "probe_bytes": len(probe),
            "wavelength": wavelength,
            "bitpix": bitpix,
            "naxis": naxis,
            "width": width,
            "height": height,
            "bscale": bscale,
            "bzero": bzero,
            "compression": compression,
            "group": group,
            "directory": directory,
            "qualifies": qualifies,
        })
        if qualifies:
            if wavelength in groups[group]:
                raise ValueError(f"duplicate wavelength {wavelength} in group")
            groups[group][wavelength] = row
            directories[directory][wavelength].append(row)
    except Exception as exc:
        row.update({"status": "failed", "qualifies": False, "reason": str(exc)})
    rows.append(row)
    print(json.dumps(row, sort_keys=True))

complete_directories = [
    directory
    for directory, items in directories.items()
    if set(items) == set(WAVELENGTHS)
]
if not complete_directories:
    coverage = {
        directory: sorted(items) for directory, items in sorted(directories.items())
    }
    raise SystemExit(
        f"no single archive directory covers all ten wavelengths; coverage={coverage}"
    )
selected_directory = sorted(complete_directories)[0]
selected = [
    sorted(directories[selected_directory][wavelength], key=lambda row: str(row["url"]))[0]
    for wavelength in WAVELENGTHS
]

columns = (
    "wavelength", "url", "probe_bytes", "bitpix", "naxis", "width", "height",
    "bscale", "bzero", "compression", "group", "directory",
)
with (OUT_DIR / "header_preflight.tsv").open("w", encoding="utf-8", newline="") as handle:
    writer = csv.DictWriter(handle, fieldnames=columns, delimiter="\t", extrasaction="ignore", lineterminator="\n")
    writer.writeheader()
    writer.writerows(selected)
(OUT_DIR / "selected_urls.txt").write_text(
    "".join(f"{row['url']}\n" for row in selected), encoding="utf-8"
)

policy = {}
for name in (
    "sdo_data_access.html",
    "sdo_copyright.html",
    "nasa_media_usage_guidelines.html",
):
    path = OUT_DIR / name
    raw = path.read_bytes()
    policy[name] = {"size_bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
summary = {
    "candidate_id": "nasa_sdo_aia_synoptic_i32",
    "month_url": MONTH_URL,
    "pages_visited": len(visited),
    "fits_candidates": len(candidates),
    "complete_timestamp_group_count": len(
        [group for group, items in groups.items() if set(items) == set(WAVELENGTHS)]
    ),
    "complete_directory_count": len(complete_directories),
    "selected_directory": selected_directory,
    "selection_rule": "earliest qualifying exposure per wavelength in selected fixed hour",
    "selected_images": len(selected),
    "wavelengths": list(WAVELENGTHS),
    "logical_bitpix": 32,
    "shape": [1024, 1024],
    "bscale": 0.0625,
    "bzero": 0.0,
    "expected_output_bytes": len(selected) * 1024 * 1024 * 4,
    "policy_files": policy,
}
(OUT_DIR / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
print(json.dumps(summary, indent=2, sort_keys=True))
PY

echo "[$(date -Is)] discovery done candidate=$CANDIDATE_ID"
