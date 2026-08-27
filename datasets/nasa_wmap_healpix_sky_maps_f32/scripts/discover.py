#!/usr/bin/env python3
"""Discover official NASA WMAP pages and bounded FITS headers."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
import re
import subprocess
from typing import Any
from urllib.parse import urljoin


BLOCK = 2880
CARD = 80
MAX_PAGE_BYTES = 5_000_000
MAX_PROBE_BYTES = 65_536
USER_AGENT = "openzl-public-datasets-wmap-healpix-f32-discovery/1.0"
BANDS = ("K", "Ka", "Q", "V", "W")
EXPECTED_URLS = {
    band: (
        "https://lambda.gsfc.nasa.gov/data/map/dr5/skymaps/9yr/raw/"
        f"wmap_band_iqumap_r9_9yr_{band}_v5.fits"
    )
    for band in BANDS
}
PAGE_URLS = {
    "wmap_current_products.html":
        "https://lambda.gsfc.nasa.gov/product/wmap/current/m_products.html",
    "wmap_dr5_products.html":
        "https://lambda.gsfc.nasa.gov/product/wmap/dr5/m_products.html",
    "wmap_current_home.html":
        "https://lambda.gsfc.nasa.gov/product/wmap/current/",
    "nasa_media_usage.html":
        "https://www.nasa.gov/nasa-brand-center/images-and-media/",
}


def run_curl(arguments: list[str]) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        [
            "curl", "--globoff", "--fail-with-body", "--silent", "--show-error",
            "--location", "--retry", "3", "--retry-all-errors",
            "--retry-delay", "2", "--connect-timeout", "30", "--max-time", "180",
            "--user-agent", USER_AGENT, *arguments,
        ],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def fetch_page(url: str, target: Path) -> dict[str, object]:
    result = run_curl(["--max-filesize", str(MAX_PAGE_BYTES), url])
    if result.returncode != 0:
        return {
            "url": url,
            "ok": False,
            "error": result.stderr.decode(errors="replace").strip(),
        }
    target.write_bytes(result.stdout)
    return {
        "url": url,
        "ok": True,
        "size_bytes": len(result.stdout),
        "sha256": hashlib.sha256(result.stdout).hexdigest(),
        "file": target.name,
    }


def html_fits_links(page: bytes, base_url: str) -> set[str]:
    text = page.decode("utf-8", errors="replace")
    links: set[str] = set()
    for match in re.finditer(r"(?i)href\s*=\s*['\"]([^'\"]+)", text):
        link = urljoin(base_url, match.group(1))
        if re.search(r"(?i)\.fits(?:\.gz)?(?:$|[?#])", link):
            links.add(link)
    return links


def probe_range(url: str, body_path: Path, headers_path: Path) -> dict[str, object]:
    result = run_curl([
        "--range", f"0-{MAX_PROBE_BYTES - 1}",
        "--max-filesize", str(MAX_PROBE_BYTES + 1),
        "--dump-header", str(headers_path),
        "--output", str(body_path),
        "--write-out", "%{http_code}\t%{url_effective}\t%{size_download}\n",
        url,
    ])
    status = result.stdout.decode(errors="replace").strip().split("\t")
    if result.returncode != 0 or len(status) != 3:
        body_path.unlink(missing_ok=True)
        return {
            "url": url,
            "ok": False,
            "error": result.stderr.decode(errors="replace").strip(),
        }
    body = body_path.read_bytes()
    response_headers = headers_path.read_text(encoding="latin-1", errors="replace")
    total_size = None
    content_range = re.findall(r"(?im)^content-range:\s*bytes\s+\d+-\d+/(\d+)\s*$", response_headers)
    if content_range:
        total_size = int(content_range[-1])
    else:
        content_length = re.findall(r"(?im)^content-length:\s*(\d+)\s*$", response_headers)
        if content_length:
            total_size = int(content_length[-1])
    return {
        "url": url,
        "ok": True,
        "http_status": int(status[0]),
        "final_url": status[1],
        "probe_size_bytes": len(body),
        "remote_size_bytes": total_size,
        "probe_sha256": hashlib.sha256(body).hexdigest(),
        "response_headers_file": headers_path.name,
    }


def parse_value(card: bytes) -> object:
    raw = card[10:80].decode("ascii", errors="strict").rstrip()
    if raw.startswith("'"):
        chars: list[str] = []
        index = 1
        while index < len(raw):
            if raw[index] == "'":
                if index + 1 < len(raw) and raw[index + 1] == "'":
                    chars.append("'")
                    index += 2
                    continue
                break
            chars.append(raw[index])
            index += 1
        return "".join(chars).strip()
    token = raw.split("/", 1)[0].strip()
    if token in {"T", "F"}:
        return token == "T"
    try:
        return int(token)
    except ValueError:
        try:
            return float(token.replace("D", "E"))
        except ValueError:
            return token


def read_header(data: bytes, offset: int) -> tuple[dict[str, object], int]:
    header: dict[str, object] = {}
    cursor = offset
    while cursor + CARD <= len(data):
        card = data[cursor : cursor + CARD]
        cursor += CARD
        keyword = card[:8].decode("ascii", errors="strict").strip()
        if keyword == "END":
            return header, ((cursor + BLOCK - 1) // BLOCK) * BLOCK
        if card[8:10] == b"= ":
            header[keyword] = parse_value(card)
    raise ValueError("FITS END card was not present in the bounded probe")


def tform_width(tform: str) -> tuple[int, str] | None:
    match = re.fullmatch(r"(\d*)([A-Z])", tform.strip().upper())
    if not match:
        return None
    return int(match.group(1) or "1"), match.group(2)


def inspect_probe(path: Path) -> dict[str, Any]:
    data = path.read_bytes()
    primary, extension_offset = read_header(data, 0)
    if primary.get("SIMPLE") is not True or int(primary.get("NAXIS", -1)) != 0:
        raise ValueError("unexpected WMAP primary HDU")
    table, _ = read_header(data, extension_offset)
    if str(table.get("XTENSION", "")).upper() != "BINTABLE":
        raise ValueError("first extension is not a FITS binary table")
    fields = int(table.get("TFIELDS", 0))
    columns = []
    for index in range(1, fields + 1):
        tform = str(table.get(f"TFORM{index}", "")).upper()
        parsed = tform_width(tform)
        columns.append({
            "index": index,
            "name": str(table.get(f"TTYPE{index}", "")),
            "tform": tform,
            "unit": str(table.get(f"TUNIT{index}", "")),
            "repeat": parsed[0] if parsed else None,
            "type_code": parsed[1] if parsed else None,
        })
    nside = int(table.get("NSIDE", 0))
    row_count = int(table.get("NAXIS2", 0))
    float_columns = [column for column in columns if column["type_code"] == "E"]
    for column in float_columns:
        column["value_count"] = row_count * int(column["repeat"])
    return {
        "primary": {
            "bitpix": primary.get("BITPIX"),
            "naxis": primary.get("NAXIS"),
            "extend": primary.get("EXTEND"),
        },
        "table": {
            "extname": table.get("EXTNAME", ""),
            "row_size_bytes": int(table.get("NAXIS1", 0)),
            "row_count": row_count,
            "field_count": fields,
            "pixtype": table.get("PIXTYPE", ""),
            "ordering": table.get("ORDERING", ""),
            "nside": nside,
            "firstpix": table.get("FIRSTPIX"),
            "lastpix": table.get("LASTPIX"),
            "coordsys": table.get("COORDSYS", ""),
            "expected_healpix_value_count": 12 * nside * nside if nside else None,
            "columns": columns,
            "native_float32_columns": float_columns,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    pages_dir = args.output_dir / "pages"
    headers_dir = args.output_dir / "headers"
    pages_dir.mkdir(parents=True, exist_ok=True)
    headers_dir.mkdir(parents=True, exist_ok=True)

    page_results: dict[str, dict[str, object]] = {}
    discovered_links: set[str] = set()
    for filename, url in PAGE_URLS.items():
        target = pages_dir / filename
        result = fetch_page(url, target)
        page_results[filename] = result
        print(f"page={filename} ok={result['ok']} url={url}")
        if result["ok"]:
            discovered_links.update(html_fits_links(target.read_bytes(), url))
    if not any(result["ok"] for name, result in page_results.items() if name.startswith("wmap_")):
        raise SystemExit("no official WMAP product page was reachable")
    rights = page_results["nasa_media_usage.html"]
    if not rights["ok"]:
        raise SystemExit("official NASA reuse-guidance page was not reachable")
    rights_text = " ".join((pages_dir / "nasa_media_usage.html").read_text(
        encoding="utf-8", errors="replace"
    ).lower().split())
    if "generally are not subject to copyright in the united states" not in rights_text:
        raise SystemExit("expected NASA public-content statement was not found")

    probes = []
    for band in BANDS:
        expected_url = EXPECTED_URLS[band]
        scraped = sorted(
            link for link in discovered_links
            if re.search(rf"(?i)9yr.*(?:_|/){re.escape(band)}(?:_|\.|-)", link)
            and "iqumap" in link.lower()
        )
        urls = [expected_url, *[url for url in scraped if url != expected_url]]
        result: dict[str, object] | None = None
        errors = []
        for candidate_index, url in enumerate(urls):
            body = headers_dir / f"{band}_{candidate_index}.fits.head"
            response = headers_dir / f"{band}_{candidate_index}.http_headers.txt"
            attempt = probe_range(url, body, response)
            if not attempt["ok"]:
                errors.append({"url": url, "error": attempt.get("error", "")})
                continue
            try:
                attempt["fits"] = inspect_probe(body)
            except (UnicodeDecodeError, ValueError) as error:
                errors.append({"url": url, "error": str(error)})
                continue
            attempt["band"] = band
            attempt["probe_file"] = body.name
            attempt["errors_before_success"] = errors
            result = attempt
            break
        if result is None:
            probes.append({"band": band, "ok": False, "attempts": errors})
        else:
            probes.append(result)
        print(
            f"band={band} ok={result is not None} "
            f"url={result.get('final_url', '') if result else ''}"
        )

    summary = {
        "candidate_id": "nasa_wmap_healpix_sky_maps_f32",
        "page_results": page_results,
        "scraped_fits_link_count": len(discovered_links),
        "expected_urls": EXPECTED_URLS,
        "probes": probes,
    }
    (args.output_dir / "discovery_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    with (args.output_dir / "candidates.tsv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, delimiter="\t", lineterminator="\n")
        writer.writerow([
            "band", "ok", "remote_size_bytes", "nside", "ordering", "coordsys",
            "float32_columns", "url",
        ])
        for probe in probes:
            table = probe.get("fits", {}).get("table", {}) if probe.get("ok") else {}
            columns = table.get("native_float32_columns", [])
            writer.writerow([
                probe["band"],
                str(bool(probe.get("ok"))).lower(),
                probe.get("remote_size_bytes", ""),
                table.get("nside", ""),
                table.get("ordering", ""),
                table.get("coordsys", ""),
                ",".join(f"{column['name']}:{column['tform']}" for column in columns),
                probe.get("final_url", probe.get("url", "")),
            ])
    qualified = [probe for probe in probes if probe.get("ok")]
    print(json.dumps({
        "reachable_band_count": len(qualified),
        "bands": [probe["band"] for probe in qualified],
        "output": str(args.output_dir / "candidates.tsv"),
    }, indent=2, sort_keys=True))
    if len(qualified) != len(BANDS):
        raise SystemExit("not all five expected WMAP band maps qualified")


if __name__ == "__main__":
    main()
