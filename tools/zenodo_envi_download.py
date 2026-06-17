#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.request
from pathlib import Path


ENVI_SUFFIXES = (".zip", ".tar", ".tar.gz", ".tgz", ".hdr", ".img", ".raw", ".bil", ".bip", ".bsq", ".dat")


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


def fetch_json(url: str, timeout: int) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "openzl-public-datasets/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def load_config(path: Path) -> dict:
    cfg = json.loads(path.read_text(encoding="utf-8"))
    required = {"dataset_id", "record_ids", "allowed_license_ids"}
    missing = sorted(required - set(cfg))
    if missing:
        raise SystemExit(f"missing config keys: {missing}")
    return cfg


def repo_paths(cfg: dict) -> dict[str, Path]:
    repo_root = Path(os.environ.get("REPO_ROOT", Path.cwd())).resolve()
    data_dir = os.environ.get("DATA_DIR", ".data")
    dataset_id = cfg["dataset_id"]
    return {"repo_root": repo_root, "download_dir": repo_root / data_dir / "downloads" / dataset_id}


def suffix_ok(name: str) -> bool:
    lower = name.lower()
    return lower.endswith(ENVI_SUFFIXES)


def safe_name(record_id: str, file_name: str) -> str:
    clean = re.sub(r"[^A-Za-z0-9._-]+", "_", file_name).strip("._") or "download.bin"
    return f"{record_id}_{clean}"


def download_file(url: str, target: Path, timeout: int, max_file_bytes: int, force: bool) -> int:
    if target.exists() and target.stat().st_size > 0 and not force:
        return target.stat().st_size
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.unlink(missing_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": "openzl-public-datasets/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as response, tmp.open("wb") as fh:
        total = 0
        while True:
            chunk = response.read(1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > max_file_bytes:
                raise RuntimeError(f"file exceeds max_file_bytes={max_file_bytes}")
            fh.write(chunk)
    if tmp.stat().st_size <= 0:
        raise RuntimeError("empty download")
    tmp.replace(target)
    return target.stat().st_size


def main() -> int:
    apply_curlrc_proxy_fallback()
    parser = argparse.ArgumentParser(description="Download bounded Zenodo ENVI hyperspectral records.")
    parser.add_argument("config", type=Path)
    args = parser.parse_args()
    cfg = load_config(args.config)
    paths = repo_paths(cfg)
    download_dir = paths["download_dir"]
    download_dir.mkdir(parents=True, exist_ok=True)
    timeout = int(os.environ.get("DOWNLOAD_TIMEOUT", cfg.get("timeout", 120)))
    max_files = int(os.environ.get("MAX_FILES", cfg.get("max_files", 12)))
    max_file_bytes = int(os.environ.get("MAX_FILE_BYTES", cfg.get("max_file_bytes", 500_000_000)))
    max_total_bytes = int(os.environ.get("MAX_DOWNLOAD_BYTES", cfg.get("max_source_bytes", 1_000_000_000)))
    force = os.environ.get("FORCE_DOWNLOAD") == "1"
    allowed = {str(item).lower() for item in cfg["allowed_license_ids"]}
    records = []
    failures = []
    inspected_records = []
    total = 0
    for record_id in [str(value) for value in cfg["record_ids"]]:
        try:
            meta = fetch_json(f"https://zenodo.org/api/records/{record_id}", timeout)
        except Exception as exc:
            failures.append({"record_id": record_id, "reason": f"metadata_fetch_failed: {exc}"})
            continue
        license_id = str(meta.get("metadata", {}).get("license", {}).get("id", "")).lower()
        title = str(meta.get("metadata", {}).get("title", ""))
        files = meta.get("files", [])
        inspected_records.append(
            {
                "record_id": record_id,
                "title": title,
                "license_id": license_id,
                "file_count": len(files),
                "candidate_file_count": sum(1 for item in files if suffix_ok(str(item.get("key") or item.get("filename") or ""))),
                "files": [
                    {
                        "name": str(item.get("key") or item.get("filename") or ""),
                        "size": int(item.get("size") or 0),
                    }
                    for item in files
                ],
            }
        )
        if license_id not in allowed:
            failures.append({"record_id": record_id, "reason": f"license_not_allowed: {license_id}"})
            continue
        matched_candidate = False
        for item in files:
            file_name = str(item.get("key") or item.get("filename") or "")
            if not suffix_ok(file_name):
                continue
            matched_candidate = True
            size = int(item.get("size") or 0)
            if size > max_file_bytes:
                failures.append({"record_id": record_id, "file": file_name, "reason": f"file_too_large: {size}"})
                continue
            if total + size > max_total_bytes:
                print(f"stop before exceeding total cap file={file_name} declared_bytes={size}")
                break
            links = item.get("links", {})
            url = links.get("download") or links.get("self")
            if not url:
                failures.append({"record_id": record_id, "file": file_name, "reason": "missing_download_link"})
                continue
            target = download_dir / safe_name(record_id, file_name)
            try:
                actual = download_file(str(url), target, timeout, max_file_bytes, force)
            except Exception as exc:
                failures.append({"record_id": record_id, "file": file_name, "reason": f"download_failed: {exc}"})
                continue
            total += actual
            records.append(
                {
                    "record_id": record_id,
                    "title": title,
                    "license_id": license_id,
                    "file_name": file_name,
                    "local_name": target.name,
                    "declared_bytes": size,
                    "source_bytes": actual,
                    "url": str(url),
                }
            )
            print(f"downloaded record={record_id} license={license_id} bytes={actual} file={target.name}")
            if len(records) >= max_files:
                break
        if not matched_candidate:
            failures.append({"record_id": record_id, "reason": "no_envi_like_file_suffixes"})
        if len(records) >= max_files or total >= max_total_bytes:
            break
    inventory = {
        "dataset_id": cfg["dataset_id"],
        "record_count": len({row["record_id"] for row in records}),
        "resource_count": len(records),
        "failure_count": len(failures),
        "source_bytes": total,
        "records": records,
        "failures": failures,
        "inspected_records": inspected_records,
    }
    (download_dir / "download_inventory.json").write_text(json.dumps(inventory, indent=2, sort_keys=True) + "\n")
    with (download_dir / "download_inventory.tsv").open("w", encoding="utf-8") as fh:
        fh.write("record_id\tlicense_id\tlocal_name\tsource_bytes\tfile_name\ttitle\n")
        for row in records:
            fh.write(
                f"{row['record_id']}\t{row['license_id']}\t{row['local_name']}\t"
                f"{row['source_bytes']}\t{row['file_name']}\t{row['title']}\n"
            )
    if not records:
        print(f"inspected_records={len(inspected_records)} failures={len(failures)}")
        for failure in failures:
            print(f"failure record={failure.get('record_id')} reason={failure.get('reason')}")
        raise SystemExit("no Zenodo ENVI candidate files downloaded; wrote download_inventory.json")
    print(f"downloaded_files={len(records)} source_bytes={total} failures={len(failures)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
