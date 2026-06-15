#!/usr/bin/env python3
from __future__ import annotations

import argparse
import html.parser
import json
import os
import re
import subprocess
from pathlib import Path
from urllib.parse import urljoin, urlparse


def run_curl(url: str, target: Path, max_file_bytes: int | None = None, *, check: bool = True) -> bool:
    cmd = ["curl", "-fL", "--retry", "3", "--retry-delay", "5"]
    if max_file_bytes is not None:
        cmd.extend(["--max-filesize", str(max_file_bytes)])
    cmd.extend(["-o", str(target), url])
    result = subprocess.run(cmd, check=False)
    if check and result.returncode != 0:
        result.check_returncode()
    return result.returncode == 0


class LinkParser(html.parser.HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.hrefs: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "a":
            return
        for key, value in attrs:
            if key.lower() == "href" and value:
                self.hrefs.append(value)


def safe_name(value: str, fallback: str) -> str:
    parsed = urlparse(value)
    name = Path(parsed.path).name or fallback
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("._")
    return name or fallback


def looks_like_data_file_url(url: str) -> bool:
    path = urlparse(url).path.lower()
    data_suffixes = (
        ".bin",
        ".bz2",
        ".cub",
        ".dat",
        ".fit",
        ".fit.gz",
        ".fits",
        ".fits.gz",
        ".gz",
        ".img",
        ".jp2",
        ".lbl",
        ".tar",
        ".tar.gz",
        ".tgz",
        ".tif",
        ".tiff",
        ".zip",
    )
    return path.endswith(data_suffixes)


def candidate_url(resource: dict) -> str:
    for key in ["url", "download_url", "accessURL"]:
        value = resource.get(key)
        if isinstance(value, str) and value.startswith(("http://", "https://")):
            return value
    return ""


def resource_text(resource: dict) -> str:
    fields = [
        str(resource.get("name", "")),
        str(resource.get("description", "")),
        str(resource.get("format", "")),
        str(resource.get("mimetype", "")),
        candidate_url(resource),
    ]
    return " ".join(fields)


def download_records(plan: list[dict], download_dir: Path, max_file_bytes: int, min_file_bytes: int) -> list[dict]:
    records = []
    with (download_dir / "download_plan.tsv").open("w", encoding="utf-8") as fh:
        for item in plan:
            fh.write(f"{item['name']}\t{item['url']}\n")
            target = download_dir / item["name"]
            if target.exists():
                print(f"using existing file: {target}")
            else:
                run_curl(item["url"], target, max_file_bytes)
            size = target.stat().st_size
            if size < min_file_bytes:
                raise SystemExit(f"{target.name}: too small: {size}")
            if size > max_file_bytes:
                raise SystemExit(f"{target.name}: exceeds cap: {size}")
            records.append(
                {
                    "file": target.name,
                    "url": item["url"],
                    "source_bytes": size,
                    "resource_name": item.get("resource_name"),
                    "resource_format": item.get("resource_format"),
                }
            )
    return records


def main() -> int:
    parser = argparse.ArgumentParser(description="Download direct file resources from a data.gov CKAN package.")
    parser.add_argument("--dataset-id", required=True)
    parser.add_argument("--package-id", required=True)
    parser.add_argument("--download-dir", required=True)
    parser.add_argument("--api-base", default="https://catalog.data.gov/api/3/action/package_show")
    parser.add_argument("--pattern", required=True, help="Case-insensitive regex matched against resource name/format/url.")
    parser.add_argument("--file-limit", type=int, default=8)
    parser.add_argument("--min-files", type=int, default=1)
    parser.add_argument("--max-file-bytes", type=int, default=750_000_000)
    parser.add_argument("--min-file-bytes", type=int, default=1024)
    args = parser.parse_args()

    download_dir = Path(args.download_dir)
    download_dir.mkdir(parents=True, exist_ok=True)
    metadata_path = download_dir / "package_show.json"
    api_url = f"{args.api_base}?id={args.package_id}"
    pattern = re.compile(args.pattern, re.IGNORECASE)
    api_ok = run_curl(api_url, metadata_path, None, check=False)

    if not api_ok:
        page_url = f"https://catalog.data.gov/dataset/{args.package_id}"
        page_path = download_dir / "catalog_page.html"
        if not run_curl(page_url, page_path, None, check=False):
            raise SystemExit(f"catalog API and page lookup failed for {args.package_id}")
        parser = LinkParser()
        parser.feed(page_path.read_text(encoding="utf-8", errors="replace"))
        urls = []
        for href in parser.hrefs:
            href = urljoin(page_url, href)
            if href.startswith(("http://", "https://")) and pattern.search(href) and looks_like_data_file_url(href):
                urls.append(href)
        urls = sorted(set(urls))[: args.file_limit]
        if len(urls) < args.min_files:
            (download_dir / "page_links_all.json").write_text(json.dumps(parser.hrefs, indent=2) + "\n", encoding="utf-8")
            raise SystemExit(f"too few direct matching page links: {len(urls)} < {args.min_files}")
        plan = []
        for index, url in enumerate(urls, start=1):
            plan.append({"name": safe_name(url, f"resource_{index:03d}"), "url": url, "resource_name": "catalog_page_link", "resource_format": ""})
        records = download_records(plan, download_dir, args.max_file_bytes, args.min_file_bytes)
        inventory = {
            "dataset_id": args.dataset_id,
            "package_id": args.package_id,
            "api_url": api_url,
            "page_url": page_url,
            "record_count": len(records),
            "source_bytes": sum(row["source_bytes"] for row in records),
            "records": records,
        }
        (download_dir / "download_inventory.json").write_text(json.dumps(inventory, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"semantic_validation=ok files={len(records)} source_bytes={inventory['source_bytes']}")
        return 0

    package = json.loads(metadata_path.read_text(encoding="utf-8"))
    if not package.get("success"):
        raise SystemExit(f"catalog package lookup failed for {args.package_id}")
    resources = package.get("result", {}).get("resources", [])
    selected = []
    for resource in resources:
        url = candidate_url(resource)
        if not url:
            continue
        if pattern.search(resource_text(resource)):
            selected.append(resource)
    selected = selected[: args.file_limit]
    if len(selected) < args.min_files:
        all_resources = [
            {
                "name": resource.get("name"),
                "format": resource.get("format"),
                "url": candidate_url(resource),
            }
            for resource in resources
        ]
        (download_dir / "resource_inventory_all.json").write_text(
            json.dumps(all_resources, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        raise SystemExit(f"too few direct matching resources: {len(selected)} < {args.min_files}")

    plan = []
    used_names: set[str] = set()
    for index, resource in enumerate(selected, start=1):
        url = candidate_url(resource)
        name = safe_name(str(resource.get("name") or url), f"resource_{index:03d}")
        if "." not in name:
            url_name = safe_name(url, f"resource_{index:03d}")
            if "." in url_name:
                name = url_name
        if name in used_names:
            stem = Path(name).stem
            suffix = Path(name).suffix
            name = f"{stem}_{index:03d}{suffix}"
        used_names.add(name)
        plan.append({"name": name, "url": url, "resource": resource})

    for item in plan:
        item["resource_name"] = item["resource"].get("name")
        item["resource_format"] = item["resource"].get("format")
    records = download_records(plan, download_dir, args.max_file_bytes, args.min_file_bytes)

    inventory = {
        "dataset_id": args.dataset_id,
        "package_id": args.package_id,
        "api_url": api_url,
        "record_count": len(records),
        "source_bytes": sum(row["source_bytes"] for row in records),
        "records": records,
    }
    (download_dir / "download_inventory.json").write_text(json.dumps(inventory, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"semantic_validation=ok files={len(records)} source_bytes={inventory['source_bytes']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
