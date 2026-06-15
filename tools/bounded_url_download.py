#!/usr/bin/env python3
from __future__ import annotations

import argparse
import html.parser
import json
import os
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path


def apply_curlrc_proxy_fallback() -> None:
    """urllib ignores ~/.curlrc; use its proxy when no proxy env is set."""
    if any(os.environ.get(name) for name in ("https_proxy", "HTTPS_PROXY", "http_proxy", "HTTP_PROXY")):
        return
    curlrc = Path.home() / ".curlrc"
    if not curlrc.exists():
        return
    for raw in curlrc.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("proxy="):
            proxy = line.split("=", 1)[1].strip().strip('"')
            if proxy:
                os.environ["http_proxy"] = proxy
                os.environ["https_proxy"] = proxy
        elif line.startswith("noproxy="):
            no_proxy = line.split("=", 1)[1].strip().strip('"')
            if no_proxy:
                os.environ.setdefault("no_proxy", no_proxy)


class LinkParser(html.parser.HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() not in {"a", "link"}:
            return
        for name, value in attrs:
            if name and name.lower() == "href" and value:
                self.links.append(value)


def read_url_list(path: Path) -> list[str]:
    urls: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        urls.append(line)
    return urls


def fetch_text(url: str, timeout: int) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "openzl-public-datasets/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return response.read().decode("utf-8", "replace")


def discover_from_seed(seed_url: str, suffixes: tuple[str, ...], timeout: int) -> list[str]:
    html = fetch_text(seed_url, timeout)
    parser = LinkParser()
    parser.feed(html)
    urls: list[str] = []
    for href in parser.links:
        full = urllib.parse.urljoin(seed_url, href)
        if urllib.parse.urlparse(full).scheme not in {"http", "https"}:
            continue
        path = urllib.parse.urlparse(full).path.lower()
        if path.endswith(suffixes):
            urls.append(full)
    return urls


def discover_polyhaven(asset_limit: int, timeout: int) -> list[str]:
    assets = json.loads(fetch_text("https://api.polyhaven.com/assets?t=hdris", timeout))
    urls: list[str] = []
    for asset_id in sorted(assets)[: asset_limit * 4]:
        files = json.loads(fetch_text(f"https://api.polyhaven.com/files/{asset_id}", timeout))
        hdri = files.get("hdri", {})
        # Prefer small EXR files; build will independently reject non-HALF or unsupported compression.
        for res in ("1k", "2k", "4k"):
            item = hdri.get(res, {}).get("exr")
            if isinstance(item, dict) and item.get("url"):
                urls.append(str(item["url"]))
                break
        if len(urls) >= asset_limit:
            break
    return urls


def discover_github_gltf(asset_limit: int, timeout: int) -> list[str]:
    index_url = "https://raw.githubusercontent.com/KhronosGroup/glTF-Sample-Assets/main/Models/model-index.json"
    models = json.loads(fetch_text(index_url, timeout))
    urls: list[str] = []
    accepted_licenses = {"CC0", "CC-BY-4.0", "CC-BY", "Public Domain", "Apache-2.0"}
    for model in models:
        license_name = str(model.get("license", "")).strip()
        if license_name and license_name not in accepted_licenses:
            continue
        name = model.get("name")
        variants = model.get("variants", {})
        if not name or "glTF-Binary" not in variants:
            continue
        encoded = urllib.parse.quote(str(name))
        urls.append(
            f"https://raw.githubusercontent.com/KhronosGroup/glTF-Sample-Assets/main/Models/{encoded}/glTF-Binary/{encoded}.glb"
        )
        if len(urls) >= asset_limit:
            break
    return urls


def discover_tcia_series(collection: str, series_limit: int, timeout: int) -> list[str]:
    base = "https://services.cancerimagingarchive.net/nbia-api/services/v1"
    url = f"{base}/getSeries?Collection={urllib.parse.quote(collection)}"
    series = json.loads(fetch_text(url, timeout))
    urls: list[str] = []
    for row in series[:series_limit]:
        uid = row.get("SeriesInstanceUID")
        if not uid:
            continue
        urls.append(f"{base}/getImage?SeriesInstanceUID={urllib.parse.quote(str(uid))}")
    return urls


def content_length(url: str, timeout: int) -> int | None:
    req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": "openzl-public-datasets/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            value = response.headers.get("Content-Length")
            return int(value) if value else None
    except Exception:
        return None


def download_one(url: str, out_dir: Path, timeout: int, max_file_bytes: int) -> Path:
    parsed = urllib.parse.urlparse(url)
    name = Path(urllib.parse.unquote(parsed.path)).name
    if not name or name.endswith("/"):
        name = re.sub(r"[^A-Za-z0-9._-]+", "_", parsed.query) or "download.bin"
    if "getImage" in parsed.path and not name.lower().endswith(".zip"):
        query_id = urllib.parse.parse_qs(parsed.query).get("SeriesInstanceUID", ["series"])[0]
        name = f"tcia_{re.sub(r'[^A-Za-z0-9._-]+', '_', query_id)}.zip"
    out = out_dir / name
    req = urllib.request.Request(url, headers={"User-Agent": "openzl-public-datasets/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response, out.open("wb") as fh:
            total = 0
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > max_file_bytes:
                    raise SystemExit(f"{url}: file exceeds MAX_FILE_BYTES={max_file_bytes}")
                fh.write(chunk)
    except Exception as exc:
        raise SystemExit(f"{url}: download failed: {exc}") from exc
    if out.stat().st_size == 0:
        raise SystemExit(f"{url}: empty download")
    return out


def main() -> int:
    apply_curlrc_proxy_fallback()

    parser = argparse.ArgumentParser(description="Bounded public URL downloader for staged recipes.")
    parser.add_argument("--dataset-id", required=True)
    parser.add_argument("--download-dir", required=True)
    parser.add_argument("--url-list")
    parser.add_argument("--seed-url", action="append", default=[])
    parser.add_argument("--suffix", action="append", default=[])
    parser.add_argument("--mode", choices=["url_list_or_seed", "polyhaven", "gltf_sample_assets", "tcia_series"], default="url_list_or_seed")
    parser.add_argument("--tcia-collection", default="")
    parser.add_argument("--max-files", type=int, default=int(os.environ.get("MAX_FILES", "24")))
    parser.add_argument("--max-total-bytes", type=int, default=int(os.environ.get("MAX_DOWNLOAD_BYTES", "1000000000")))
    parser.add_argument("--max-file-bytes", type=int, default=int(os.environ.get("MAX_FILE_BYTES", "600000000")))
    parser.add_argument("--timeout", type=int, default=120)
    args = parser.parse_args()

    out_dir = Path(args.download_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    urls: list[str] = []
    if args.mode == "polyhaven":
        urls = discover_polyhaven(args.max_files, args.timeout)
    elif args.mode == "gltf_sample_assets":
        urls = discover_github_gltf(args.max_files, args.timeout)
    elif args.mode == "tcia_series":
        if not args.tcia_collection:
            raise SystemExit("--tcia-collection is required for tcia_series mode")
        urls = discover_tcia_series(args.tcia_collection, args.max_files, args.timeout)
    else:
        if args.url_list and Path(args.url_list).exists():
            urls.extend(read_url_list(Path(args.url_list)))
        suffixes = tuple(s.lower() for s in args.suffix) or (".bin",)
        for seed in args.seed_url:
            urls.extend(discover_from_seed(seed, suffixes, args.timeout))

    deduped: list[str] = []
    seen: set[str] = set()
    for url in urls:
        if url not in seen:
            deduped.append(url)
            seen.add(url)
    urls = deduped[: args.max_files]
    if not urls:
        raise SystemExit("no candidate URLs discovered; provide URL list or adjust seed selectors")

    selected: list[tuple[str, int | None]] = []
    running = 0
    for url in urls:
        length = content_length(url, args.timeout)
        if length is not None and length > args.max_file_bytes:
            print(f"skip oversized file length={length} url={url}", file=sys.stderr)
            continue
        if length is not None and running + length > args.max_total_bytes:
            print(f"stop before exceeding max total bytes: {url}", file=sys.stderr)
            break
        selected.append((url, length))
        if length is not None:
            running += length
    if not selected:
        raise SystemExit("all discovered URLs were oversized or invalid")

    manifest_rows = []
    total = 0
    for url, declared_length in selected:
        path = download_one(url, out_dir, args.timeout, args.max_file_bytes)
        size = path.stat().st_size
        total += size
        if total > args.max_total_bytes:
            raise SystemExit(f"downloaded bytes exceed cap: {total}")
        manifest_rows.append({"url": url, "local_name": path.name, "bytes": size, "declared_bytes": declared_length})
        print(f"downloaded bytes={size} file={path.name}")

    (out_dir / "download_manifest.json").write_text(json.dumps(manifest_rows, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"downloaded_files={len(manifest_rows)} downloaded_bytes={total}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
