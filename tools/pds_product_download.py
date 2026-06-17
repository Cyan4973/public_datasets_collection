#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import html.parser
import json
import os
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path


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


def apply_curlrc_proxy_fallback() -> None:
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


def fetch_bytes(url: str, timeout: int, max_bytes: int) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "openzl-public-datasets/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        chunks = []
        total = 0
        while True:
            chunk = response.read(1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > max_bytes:
                raise RuntimeError(f"response exceeds byte cap {max_bytes}")
            chunks.append(chunk)
    return b"".join(chunks)


def fetch_text(url: str, timeout: int, max_bytes: int = 4_000_000) -> str:
    return fetch_bytes(url, timeout, max_bytes).decode("utf-8", "replace")


def read_url_list(path: Path) -> list[str]:
    urls: list[str] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line and not line.startswith("#"):
            urls.append(line)
    return urls


def pds_value(text: str, key: str) -> str | None:
    match = re.search(rf"(?im)^\s*{re.escape(key)}\s*=\s*(.+?)\s*$", text)
    if not match:
        return None
    return match.group(1).strip().strip('"')


def pds_tuple_ints(value: str | None) -> list[int]:
    if not value:
        return []
    return [int(token) for token in re.findall(r"[-+]?\d+", value)]


def pointer_file(value: str | None) -> str:
    if not value:
        return ""
    value = value.strip()
    if value.startswith("("):
        inner = value.strip("()")
        return inner.split(",", 1)[0].strip().strip('"')
    if value.startswith('"'):
        return value.strip('"')
    return ""


def label_semantics(text: str) -> dict | None:
    sample_bits = pds_value(text, "SAMPLE_BITS")
    sample_type = pds_value(text, "SAMPLE_TYPE") or ""
    if sample_bits == "16":
        try:
            lines = int((pds_value(text, "LINES") or "0").split()[0])
            line_samples = int((pds_value(text, "LINE_SAMPLES") or "0").split()[0])
            bands = int((pds_value(text, "BANDS") or "1").split()[0])
        except Exception:
            lines = line_samples = bands = 0
        if lines > 0 and line_samples > 0:
            return {
                "object": "IMAGE",
                "payload_name": pointer_file(pds_value(text, "^IMAGE")),
                "lines": lines,
                "samples": line_samples,
                "bands": bands,
                "sample_type": sample_type,
            }
    core_items = pds_tuple_ints(pds_value(text, "CORE_ITEMS"))
    core_item_bytes = pds_value(text, "CORE_ITEM_BYTES")
    core_item_type = pds_value(text, "CORE_ITEM_TYPE") or ""
    if len(core_items) >= 3 and core_item_bytes == "2":
        return {
            "object": "QUBE",
            "payload_name": pointer_file(pds_value(text, "^QUBE")),
            "samples": core_items[0],
            "bands": core_items[1],
            "lines": core_items[2],
            "sample_type": core_item_type,
        }
    return None


def is_directory_url(url: str) -> bool:
    return urllib.parse.urlparse(url).path.endswith("/")


def discover_labels(seed_urls: list[str], args: argparse.Namespace) -> list[str]:
    queue = list(seed_urls)
    seen_pages: set[str] = set()
    labels: list[str] = []
    label_re = re.compile(args.label_regex, re.I) if args.label_regex else None
    while queue and len(seen_pages) < args.max_pages and len(labels) < args.max_labels:
        page = queue.pop(0)
        if page in seen_pages:
            continue
        seen_pages.add(page)
        try:
            html = fetch_text(page, args.timeout)
        except Exception as exc:
            print(f"skip_page url={page} error={exc}", file=sys.stderr)
            continue
        parser = LinkParser()
        parser.feed(html)
        for href in parser.links:
            full = urllib.parse.urljoin(page, href)
            parsed = urllib.parse.urlparse(full)
            if parsed.scheme not in {"http", "https"}:
                continue
            if not full.startswith(tuple(seed_urls)):
                continue
            path = parsed.path
            name = Path(path).name
            if path.lower().endswith(".lbl"):
                if label_re is None or label_re.search(name):
                    labels.append(urllib.parse.urlunparse(parsed._replace(fragment="")))
                    if len(labels) >= args.max_labels:
                        break
            elif is_directory_url(full) and name not in {"", ".", ".."}:
                if full not in seen_pages and len(queue) < args.max_pages * 8:
                    queue.append(urllib.parse.urlunparse(parsed._replace(fragment="")))
    deduped = []
    seen: set[str] = set()
    for url in labels:
        if url not in seen:
            seen.add(url)
            deduped.append(url)
    return deduped


def discover_labels_from_indexes(index_urls: list[str], args: argparse.Namespace) -> list[str]:
    label_re = re.compile(args.label_regex, re.I) if args.label_regex else None
    labels: list[str] = []
    skipped = 0
    for index_url in index_urls:
        try:
            text = fetch_text(index_url, args.timeout, max_bytes=100_000_000)
        except Exception as exc:
            skipped += 1
            if args.verbose:
                print(f"skip_index url={index_url} error={exc}", file=sys.stderr)
            continue
        base = index_url.rsplit("/", 2)[0] + "/"
        for row in csv.reader(text.splitlines()):
            for field in row:
                value = field.strip().strip('"')
                if not value.lower().endswith(".lbl"):
                    continue
                name = Path(value).name
                if label_re is not None and not label_re.search(name):
                    continue
                labels.append(urllib.parse.urljoin(base, value.replace("\\", "/")))
                if len(labels) >= args.max_labels:
                    if skipped:
                        print(f"skipped_index_count={skipped}", file=sys.stderr)
                    return labels
    if skipped:
        print(f"skipped_index_count={skipped}", file=sys.stderr)
    deduped = []
    seen: set[str] = set()
    for url in labels:
        if url not in seen:
            seen.add(url)
            deduped.append(url)
    return deduped


def safe_product_dir(download_dir: Path, label_url: str) -> Path:
    parsed = urllib.parse.urlparse(label_url)
    parts = [part for part in parsed.path.split("/") if part]
    stem = Path(parts[-1]).stem if parts else "product"
    parent = parts[-2] if len(parts) >= 2 else ""
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", f"{parent}_{stem}").strip("._") or "product"
    return download_dir / name


def download_file(url: str, target: Path, args: argparse.Namespace) -> int:
    if target.exists() and target.stat().st_size > 0 and not args.force:
        return target.stat().st_size
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.unlink(missing_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": "openzl-public-datasets/1.0"})
    with urllib.request.urlopen(req, timeout=args.timeout) as response, tmp.open("wb") as fh:
        total = 0
        while True:
            chunk = response.read(1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > args.max_file_bytes:
                raise RuntimeError(f"{url}: file exceeds max-file-bytes={args.max_file_bytes}")
            fh.write(chunk)
    if tmp.stat().st_size <= 0:
        raise RuntimeError(f"{url}: empty download")
    tmp.replace(target)
    return target.stat().st_size


def main() -> int:
    apply_curlrc_proxy_fallback()
    parser = argparse.ArgumentParser(description="Bounded PDS label/payload downloader.")
    parser.add_argument("--dataset-id", required=True)
    parser.add_argument("--download-dir", required=True)
    parser.add_argument("--url-list")
    parser.add_argument("--seed-url", action="append", default=[])
    parser.add_argument("--index-url", action="append", default=[])
    parser.add_argument("--label-regex", default="")
    parser.add_argument("--max-products", type=int, default=int(os.environ.get("MAX_PRODUCTS", "6")))
    parser.add_argument("--max-labels", type=int, default=int(os.environ.get("MAX_LABELS", "200")))
    parser.add_argument("--max-pages", type=int, default=int(os.environ.get("MAX_PAGES", "500")))
    parser.add_argument("--max-total-bytes", type=int, default=int(os.environ.get("MAX_DOWNLOAD_BYTES", "1000000000")))
    parser.add_argument("--max-file-bytes", type=int, default=int(os.environ.get("MAX_FILE_BYTES", "500000000")))
    parser.add_argument("--timeout", type=int, default=int(os.environ.get("DOWNLOAD_TIMEOUT", "120")))
    parser.add_argument("--force", action="store_true", default=os.environ.get("FORCE_DOWNLOAD") == "1")
    parser.add_argument("--verbose", action="store_true", default=os.environ.get("VERBOSE") == "1")
    args = parser.parse_args()

    download_dir = Path(args.download_dir)
    download_dir.mkdir(parents=True, exist_ok=True)
    if args.url_list and Path(args.url_list).exists():
        label_urls = [url for url in read_url_list(Path(args.url_list)) if url.lower().endswith(".lbl")]
    elif args.index_url:
        label_urls = discover_labels_from_indexes(args.index_url, args)
    else:
        label_urls = discover_labels(args.seed_url, args)
    if not label_urls:
        raise SystemExit("no PDS labels discovered; provide exact label URLs with URL list")

    records = []
    failures = []
    total_bytes = 0
    for label_url in label_urls:
        if len(records) >= args.max_products:
            break
        product_dir = safe_product_dir(download_dir, label_url)
        label_target = product_dir / Path(urllib.parse.urlparse(label_url).path).name
        try:
            label_bytes = fetch_bytes(label_url, args.timeout, 8_000_000)
            label_text = label_bytes.decode("utf-8", "replace")
            semantics = label_semantics(label_text)
            if not semantics:
                failures.append({"url": label_url, "reason": "not_supported_16bit_pds_image_or_qube"})
                continue
            payload_name = semantics.get("payload_name") or ""
            if not payload_name:
                failures.append({"url": label_url, "reason": "missing_payload_pointer"})
                continue
            payload_url = urllib.parse.urljoin(label_url, payload_name)
            product_dir.mkdir(parents=True, exist_ok=True)
            label_target.write_bytes(label_bytes)
            payload_target = product_dir / Path(payload_name).name
            payload_size = download_file(payload_url, payload_target, args)
            label_size = label_target.stat().st_size
            total_bytes += label_size + payload_size
            if total_bytes > args.max_total_bytes:
                raise SystemExit(f"downloaded bytes exceed cap: {total_bytes}")
            record = {
                "label_url": label_url,
                "payload_url": payload_url,
                "label_path": label_target.relative_to(download_dir).as_posix(),
                "payload_path": payload_target.relative_to(download_dir).as_posix(),
                "label_bytes": label_size,
                "payload_bytes": payload_size,
                **semantics,
            }
            records.append(record)
            print(
                f"downloaded_product object={semantics['object']} lines={semantics['lines']} "
                f"samples={semantics['samples']} bands={semantics['bands']} bytes={payload_size} "
                f"label={label_target.name}"
            )
        except Exception as exc:
            failures.append({"url": label_url, "reason": str(exc)})
            print(f"skip_label url={label_url} error={exc}", file=sys.stderr)

    if not records:
        raise SystemExit("no supported PDS products downloaded")
    inventory = {
        "dataset_id": args.dataset_id,
        "resource_count": len(records),
        "failure_count": len(failures),
        "source_bytes": total_bytes,
        "records": records,
        "failures": failures,
    }
    (download_dir / "download_inventory.json").write_text(json.dumps(inventory, indent=2, sort_keys=True) + "\n")
    with (download_dir / "download_inventory.tsv").open("w", encoding="utf-8") as fh:
        fh.write("object\tlines\tsamples\tbands\tpayload_bytes\tlabel_path\tpayload_path\tlabel_url\n")
        for row in records:
            fh.write(
                f"{row['object']}\t{row['lines']}\t{row['samples']}\t{row['bands']}\t"
                f"{row['payload_bytes']}\t{row['label_path']}\t{row['payload_path']}\t{row['label_url']}\n"
            )
    print(f"downloaded_products={len(records)} source_bytes={total_bytes} failures={len(failures)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
