#!/usr/bin/env python3
from __future__ import annotations

import argparse
import gzip
import json
import math
import os
import re
import shutil
import statistics
import subprocess
import sys
from array import array
from pathlib import Path
from urllib.parse import urlparse


MIN_PRIMARY_VALUES = 10_000
MIN_PRIMARY_BYTES = 100 * 1024
MIN_MEDIAN_VALUES = 1_000
MAX_PRIMARY_BYTES = 1_000_000_000
MAX_SOURCE_BYTES = 250_000_000
SERIES_ID = "detector_strain_f32"


def load_config(path: Path) -> dict:
    cfg = json.loads(path.read_text(encoding="utf-8"))
    if cfg.get("dataset_id") != "gwosc_event_strain_f32":
        raise SystemExit(f"unexpected dataset_id in {path}")
    return cfg


def repo_paths(dataset_id: str) -> dict[str, Path]:
    repo_root = Path(os.environ.get("REPO_ROOT", Path.cwd())).resolve()
    data_dir = os.environ.get("DATA_DIR", ".data")
    data_root = repo_root / data_dir
    return {
        "repo_root": repo_root,
        "data_root": data_root,
        "download_dir": data_root / "downloads" / dataset_id,
        "filtered_dir": data_root / "filtered" / dataset_id,
        "index_dir": data_root / "index" / dataset_id,
        "samples_dir": data_root / "samples" / dataset_id,
    }


def strip_gz_txt(name: str) -> str:
    if name.endswith(".txt.gz"):
        return name[: -len(".txt.gz")]
    if name.endswith(".gz"):
        return name[: -len(".gz")]
    if name.endswith(".txt"):
        return name[: -len(".txt")]
    return name


def safe_filename_from_url(url: str) -> str:
    name = Path(urlparse(url).path).name
    if not name:
        raise ValueError(f"URL has no basename: {url}")
    if not name.endswith(".txt.gz"):
        raise ValueError(f"expected .txt.gz URL, got: {url}")
    return re.sub(r"[^A-Za-z0-9._+-]", "_", name)


def parse_metadata_from_name(name: str) -> dict:
    stem = strip_gz_txt(name)
    parts = stem.split("-")
    meta: dict[str, object] = {"sample_id": re.sub(r"[^A-Za-z0-9._+-]", "_", stem)}
    if len(parts) >= 4:
        meta["detector"] = parts[1].split("_", 1)[0]
        try:
            meta["gps_start"] = int(parts[-2])
        except ValueError:
            pass
        try:
            meta["duration_seconds"] = int(parts[-1])
        except ValueError:
            pass
    upper = stem.upper()
    if "16KHZ" in upper or "_16_" in upper:
        meta["sample_rate_hz"] = 16384
    elif "4KHZ" in upper or "_4_" in upper:
        meta["sample_rate_hz"] = 4096
    return meta


def resource_id(event: str, detector: str, local_name: str) -> str:
    base = strip_gz_txt(local_name)
    return re.sub(r"[^A-Za-z0-9._+-]", "_", f"{event}_{detector}_{base}")


def load_resources(cfg: dict) -> list[dict]:
    resources = []
    for item in cfg.get("default_resources", []):
        local_name = item.get("local_name") or safe_filename_from_url(item["url"])
        urls = item.get("urls") or [item["url"]]
        meta = parse_metadata_from_name(local_name)
        event = item.get("event") or meta.get("event") or "unknown_event"
        detector = item.get("detector") or meta.get("detector") or "unknown_detector"
        resources.append(
            {
                **meta,
                **item,
                "event": event,
                "detector": detector,
                "local_name": local_name,
                "urls": urls,
                "resource_id": item.get("id") or resource_id(str(event), str(detector), local_name),
            }
        )

    url_file = os.environ.get("GWOSC_URLS_FILE")
    if url_file:
        for line_no, raw in enumerate(Path(url_file).read_text(encoding="utf-8").splitlines(), 1):
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            fields = re.split(r"\s+", line)
            if len(fields) == 1:
                event = "external"
                detector = ""
                url = fields[0]
            elif len(fields) >= 3:
                event, detector, url = fields[0], fields[1], fields[2]
            else:
                raise SystemExit(f"bad GWOSC_URLS_FILE line {line_no}: expected URL or event detector URL")
            local_name = safe_filename_from_url(url)
            meta = parse_metadata_from_name(local_name)
            detector = detector or str(meta.get("detector") or "unknown_detector")
            resources.append(
                {
                    **meta,
                    "event": event,
                    "detector": detector,
                    "local_name": local_name,
                    "urls": [url],
                    "resource_id": resource_id(event, detector, local_name),
                    "source": "GWOSC_URLS_FILE",
                }
            )

    seen = set()
    deduped = []
    for item in resources:
        key = (item["resource_id"], item["local_name"])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def iter_strain_values(path: Path):
    with gzip.open(path, "rt", encoding="utf-8", errors="strict") as fh:
        for line_no, raw in enumerate(fh, 1):
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            fields = line.split()
            if len(fields) != 1:
                raise ValueError(f"{path.name}: line {line_no} has {len(fields)} fields; expected one strain value")
            value = float(fields[0])
            if not math.isfinite(value):
                raise ValueError(f"{path.name}: line {line_no} has non-finite strain value")
            yield value


def validate_source(path: Path, expected_values: int | None = None) -> dict:
    if not path.is_file() or path.stat().st_size <= 0:
        raise ValueError(f"missing or empty file: {path}")
    with path.open("rb") as fh:
        prefix = fh.read(64)
    if prefix.lstrip().startswith(b"<"):
        raise ValueError(f"looks like HTML, not gzip strain text: {path}")

    count = 0
    first = None
    min_value = math.inf
    max_value = -math.inf
    prefix_values = []
    for value in iter_strain_values(path):
        if first is None:
            first = value
        if len(prefix_values) < 4096:
            prefix_values.append(value)
        min_value = min(min_value, value)
        max_value = max(max_value, value)
        count += 1

    if count < MIN_MEDIAN_VALUES:
        raise ValueError(f"too few numeric strain values in {path}: {count}")
    if expected_values is not None and count != expected_values:
        raise ValueError(f"unexpected strain value count in {path}: got {count}, expected {expected_values}")
    if len(set(prefix_values)) <= 1:
        raise ValueError(f"constant prefix in {path}")
    return {
        "value_count": count,
        "source_bytes": path.stat().st_size,
        "min_value": min_value,
        "max_value": max_value,
        "first_value": first,
    }


def fetch_url(url: str, out: Path) -> None:
    if shutil.which("curl"):
        subprocess.run(
            [
                "curl",
                "--globoff",
                "-fL",
                "--show-error",
                "--retry",
                "3",
                "--retry-delay",
                "3",
                "-A",
                "openzl-public-datasets/1.0",
                "-o",
                str(out),
                url,
            ],
            check=True,
        )
    elif shutil.which("wget"):
        subprocess.run(["wget", "-O", str(out), url], check=True)
    else:
        raise SystemExit("neither curl nor wget is available")


def cmd_download(cfg: dict) -> None:
    dataset_id = cfg["dataset_id"]
    paths = repo_paths(dataset_id)
    download_dir = paths["download_dir"]
    download_dir.mkdir(parents=True, exist_ok=True)
    resources = load_resources(cfg)
    if not resources:
        raise SystemExit("no GWOSC resources configured")

    force = os.environ.get("FORCE_DOWNLOAD") == "1"
    offline = os.environ.get("OFFLINE") == "1"
    allow_partial = os.environ.get("ALLOW_PARTIAL") == "1"
    max_source_bytes = int(os.environ.get("MAX_SOURCE_BYTES", MAX_SOURCE_BYTES))
    failures = []
    accepted = []
    source_bytes = 0

    with (download_dir / "download_plan.tsv").open("w", encoding="utf-8") as fh:
        fh.write("resource_id\tevent\tdetector\tlocal_name\turl_count\turls\n")
        for item in resources:
            fh.write(
                f"{item['resource_id']}\t{item['event']}\t{item['detector']}\t"
                f"{item['local_name']}\t{len(item['urls'])}\t{';'.join(item['urls'])}\n"
            )

    for item in resources:
        target = download_dir / item["local_name"]
        expected_values = item.get("expected_values")
        if target.exists() and target.stat().st_size > 0 and not force:
            print(f"cache_check resource={item['resource_id']} file={target.name}")
            try:
                validation = validate_source(target, expected_values)
                accepted.append({**item, **validation, "selected_url": item["urls"][0], "cached": True})
                source_bytes += validation["source_bytes"]
                print(f"validated_cached resource={item['resource_id']} values={validation['value_count']}")
                continue
            except Exception as exc:  # noqa: BLE001
                print(f"cached_invalid resource={item['resource_id']} reason={exc}")
                target.unlink(missing_ok=True)

        if offline:
            reason = "offline_cache_missing_or_invalid"
            failures.append(
                {
                    "resource_id": item["resource_id"],
                    "event": item["event"],
                    "detector": item["detector"],
                    "url": ";".join(item["urls"]),
                    "reason": reason,
                }
            )
            print(f"failed resource={item['resource_id']} reason={reason}")
            continue

        selected = None
        last_error = None
        for url in item["urls"]:
            tmp = target.with_suffix(target.suffix + ".tmp")
            tmp.unlink(missing_ok=True)
            print(f"fetch resource={item['resource_id']} url={url}")
            try:
                fetch_url(url, tmp)
                validation = validate_source(tmp, expected_values)
                tmp.replace(target)
                selected = {**item, **validation, "selected_url": url, "cached": False}
                print(f"validated resource={item['resource_id']} values={validation['value_count']}")
                break
            except Exception as exc:  # noqa: BLE001
                last_error = str(exc)
                failures.append(
                    {
                        "resource_id": item["resource_id"],
                        "event": item["event"],
                        "detector": item["detector"],
                        "url": url,
                        "reason": last_error,
                    }
                )
                tmp.unlink(missing_ok=True)
                print(f"failed resource={item['resource_id']} reason={last_error}")
        if selected is None:
            if not allow_partial:
                print(f"required_resource_failed resource={item['resource_id']}")
            continue
        accepted.append(selected)
        source_bytes += int(selected["source_bytes"])
        if source_bytes > max_source_bytes:
            raise SystemExit(f"downloaded source bytes exceed cap: {source_bytes} > {max_source_bytes}")

    with (download_dir / "download_failures.tsv").open("w", encoding="utf-8") as fh:
        fh.write("resource_id\tevent\tdetector\turl\treason\n")
        for row in failures:
            fh.write(f"{row['resource_id']}\t{row['event']}\t{row['detector']}\t{row['url']}\t{row['reason']}\n")

    inventory = {
        "dataset_id": dataset_id,
        "resource_count": len(accepted),
        "source_bytes": source_bytes,
        "failed_fetch_attempts": len(failures),
        "records": accepted,
    }
    (download_dir / "download_inventory.json").write_text(json.dumps(inventory, indent=2, sort_keys=True) + "\n")
    with (download_dir / "download_inventory.tsv").open("w", encoding="utf-8") as fh:
        fh.write("resource_id\tevent\tdetector\tlocal_name\tvalue_count\tsource_bytes\tselected_url\n")
        for row in accepted:
            fh.write(
                f"{row['resource_id']}\t{row['event']}\t{row['detector']}\t{row['local_name']}\t"
                f"{row['value_count']}\t{row['source_bytes']}\t{row['selected_url']}\n"
            )

    if not accepted:
        raise SystemExit("no GWOSC strain resources downloaded and validated")
    if not allow_partial and len(accepted) != len(resources):
        raise SystemExit(f"only {len(accepted)}/{len(resources)} configured resources validated")
    print(f"semantic_validation=ok resources={len(accepted)} source_bytes={source_bytes}")


def write_f32(path: Path, values: array) -> None:
    out = array("f", values)
    if sys.byteorder != "little":
        out.byteswap()
    path.write_bytes(out.tobytes())


def sample_file_nonconstant_f32(path: Path, value_count: int) -> bool:
    if value_count <= 1:
        return False
    with path.open("rb") as fh:
        raw = fh.read(min(value_count, 8192) * 4)
    vals = array("f")
    vals.frombytes(raw)
    if sys.byteorder != "little":
        vals.byteswap()
    return len(set(vals)) > 1


def cmd_build(cfg: dict) -> None:
    dataset_id = cfg["dataset_id"]
    paths = repo_paths(dataset_id)
    data_root = paths["data_root"]
    download_dir = paths["download_dir"]
    filtered_dir = paths["filtered_dir"]
    index_dir = paths["index_dir"]
    samples_dir = paths["samples_dir"]
    inventory_path = download_dir / "download_inventory.json"
    if not inventory_path.exists():
        raise SystemExit(f"missing download inventory: {inventory_path}; run download.sh first")
    inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
    records = inventory.get("records") or []
    if not records:
        raise SystemExit("download inventory has no records")

    if samples_dir.exists():
        shutil.rmtree(samples_dir)
    series_dir = samples_dir / SERIES_ID
    series_dir.mkdir(parents=True, exist_ok=True)
    filtered_dir.mkdir(parents=True, exist_ok=True)
    index_dir.mkdir(parents=True, exist_ok=True)

    index_rows = []
    sample_values = []
    sample_bytes = []
    by_event: dict[str, int] = {}
    by_detector: dict[str, int] = {}

    for record in records:
        source = download_dir / record["local_name"]
        validation = validate_source(source, record.get("expected_values"))
        values = array("f")
        for value in iter_strain_values(source):
            values.append(float(value))
        if len(values) != validation["value_count"]:
            raise SystemExit(f"internal count mismatch for {source}")
        sample_id = str(record["resource_id"])
        sample_path = series_dir / f"{sample_id}.f32le"
        write_f32(sample_path, values)
        value_count = len(values)
        size_bytes = sample_path.stat().st_size
        if size_bytes != value_count * 4:
            raise SystemExit(f"bad output size for {sample_path}")
        if not sample_file_nonconstant_f32(sample_path, value_count):
            raise SystemExit(f"constant output prefix for {sample_path}")

        event = str(record.get("event") or "unknown_event")
        detector = str(record.get("detector") or "unknown_detector")
        by_event[event] = by_event.get(event, 0) + 1
        by_detector[detector] = by_detector.get(detector, 0) + 1
        sample_values.append(value_count)
        sample_bytes.append(size_bytes)

        index_rows.append(
            {
                "dataset_id": dataset_id,
                "series_id": SERIES_ID,
                "role": "primary",
                "sample_id": sample_id,
                "sample_path": str(sample_path.relative_to(data_root)),
                "source_path": str(source.relative_to(data_root)),
                "source_url": record.get("selected_url"),
                "numeric_kind": "float",
                "bit_width": 32,
                "endianness": "little",
                "element_size_bytes": 4,
                "sample_size_bytes": size_bytes,
                "value_count": value_count,
                "sample_geometry": "1d_detector_strain_timeseries",
                "sample_rank": 1,
                "sample_shape": [value_count],
                "sample_axes": ["time"],
                "event": event,
                "detector": detector,
                "gps_start": record.get("gps_start"),
                "duration_seconds": record.get("duration_seconds"),
                "sample_rate_hz": record.get("sample_rate_hz"),
            }
        )

    total_values = sum(sample_values)
    total_bytes = sum(sample_bytes)
    median_values = int(statistics.median(sample_values))
    if total_values < MIN_PRIMARY_VALUES:
        raise SystemExit(f"below total primary value floor: {total_values} < {MIN_PRIMARY_VALUES}")
    if total_bytes < MIN_PRIMARY_BYTES:
        raise SystemExit(f"below total primary byte floor: {total_bytes} < {MIN_PRIMARY_BYTES}")
    if median_values < MIN_MEDIAN_VALUES:
        raise SystemExit(f"below median primary value floor: {median_values} < {MIN_MEDIAN_VALUES}")
    if total_bytes > MAX_PRIMARY_BYTES:
        raise SystemExit(f"primary output exceeds cap: {total_bytes} > {MAX_PRIMARY_BYTES}")

    with (index_dir / "samples.jsonl").open("w", encoding="utf-8") as fh:
        for row in index_rows:
            fh.write(json.dumps(row, sort_keys=True) + "\n")

    stats = {
        "dataset_id": dataset_id,
        "series_id": SERIES_ID,
        "sample_count": len(index_rows),
        "total_primary_values": total_values,
        "total_primary_bytes": total_bytes,
        "min_sample_values": min(sample_values),
        "median_sample_values": median_values,
        "max_sample_values": max(sample_values),
        "min_sample_bytes": min(sample_bytes),
        "median_sample_bytes": int(statistics.median(sample_bytes)),
        "max_sample_bytes": max(sample_bytes),
        "by_event": by_event,
        "by_detector": by_detector,
    }
    (filtered_dir / "ingest_stats.json").write_text(json.dumps(stats, indent=2, sort_keys=True) + "\n")
    print(json.dumps(stats, indent=2, sort_keys=True))


def cmd_verify(cfg: dict) -> None:
    dataset_id = cfg["dataset_id"]
    paths = repo_paths(dataset_id)
    data_root = paths["data_root"]
    index_path = paths["index_dir"] / "samples.jsonl"
    if not index_path.exists():
        raise SystemExit(f"missing sample index: {index_path}; run build.sh first")
    rows = [json.loads(line) for line in index_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not rows:
        raise SystemExit("sample index is empty")

    sample_values = []
    sample_bytes = []
    by_event: dict[str, int] = {}
    by_detector: dict[str, int] = {}
    for row in rows:
        required = {
            "dataset_id",
            "series_id",
            "role",
            "sample_path",
            "numeric_kind",
            "bit_width",
            "endianness",
            "element_size_bytes",
            "sample_size_bytes",
            "value_count",
            "sample_geometry",
            "sample_rank",
            "sample_shape",
            "sample_axes",
            "source_path",
        }
        missing = sorted(required - set(row))
        if missing:
            raise SystemExit(f"index row missing keys {missing}: {row.get('sample_id')}")
        if row["dataset_id"] != dataset_id or row["series_id"] != SERIES_ID or row["role"] != "primary":
            raise SystemExit(f"bad identity/role in index row: {row}")
        if row["numeric_kind"] != "float" or row["bit_width"] != 32 or row["endianness"] != "little":
            raise SystemExit(f"bad numeric metadata in row: {row.get('sample_id')}")
        sample_path = data_root / row["sample_path"]
        source_path = data_root / row["source_path"]
        if not sample_path.exists():
            raise SystemExit(f"missing sample file: {sample_path}")
        if not source_path.exists():
            raise SystemExit(f"missing source file: {source_path}")
        source_validation = validate_source(source_path)
        if int(row["value_count"]) != int(source_validation["value_count"]):
            raise SystemExit(f"source/sample count mismatch for {row.get('sample_id')}")
        expected_size = int(row["value_count"]) * int(row["element_size_bytes"])
        actual_size = sample_path.stat().st_size
        if actual_size != expected_size or actual_size != int(row["sample_size_bytes"]):
            raise SystemExit(f"bad sample byte size for {sample_path}")
        if row["sample_shape"] != [row["value_count"]] or row["sample_axes"] != ["time"]:
            raise SystemExit(f"bad sample geometry in row: {row.get('sample_id')}")
        if not sample_file_nonconstant_f32(sample_path, int(row["value_count"])):
            raise SystemExit(f"constant sample prefix: {sample_path}")
        sample_values.append(int(row["value_count"]))
        sample_bytes.append(actual_size)
        event = str(row.get("event") or "unknown_event")
        detector = str(row.get("detector") or "unknown_detector")
        by_event[event] = by_event.get(event, 0) + 1
        by_detector[detector] = by_detector.get(detector, 0) + 1

    total_values = sum(sample_values)
    total_bytes = sum(sample_bytes)
    median_values = int(statistics.median(sample_values))
    if total_values < MIN_PRIMARY_VALUES:
        raise SystemExit(f"below total primary value floor: {total_values} < {MIN_PRIMARY_VALUES}")
    if total_bytes < MIN_PRIMARY_BYTES:
        raise SystemExit(f"below total primary byte floor: {total_bytes} < {MIN_PRIMARY_BYTES}")
    if median_values < MIN_MEDIAN_VALUES:
        raise SystemExit(f"below median primary value floor: {median_values} < {MIN_MEDIAN_VALUES}")
    if total_bytes > MAX_PRIMARY_BYTES:
        raise SystemExit(f"primary output exceeds cap: {total_bytes} > {MAX_PRIMARY_BYTES}")

    report = {
        "dataset_id": dataset_id,
        "series_id": SERIES_ID,
        "verification": "ok",
        "sample_count": len(rows),
        "total_primary_values": total_values,
        "total_primary_bytes": total_bytes,
        "min_sample_values": min(sample_values),
        "median_sample_values": median_values,
        "max_sample_values": max(sample_values),
        "min_sample_bytes": min(sample_bytes),
        "median_sample_bytes": int(statistics.median(sample_bytes)),
        "max_sample_bytes": max(sample_bytes),
        "by_event": by_event,
        "by_detector": by_detector,
    }
    report_path = paths["filtered_dir"] / "verification_report.json"
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps(report, indent=2, sort_keys=True))


def main() -> None:
    parser = argparse.ArgumentParser(description="GWOSC event strain f32 recipe")
    parser.add_argument("command", choices=["download", "build", "verify"])
    parser.add_argument("--config", required=True, type=Path)
    args = parser.parse_args()
    cfg = load_config(args.config)
    if args.command == "download":
        cmd_download(cfg)
    elif args.command == "build":
        cmd_build(cfg)
    elif args.command == "verify":
        cmd_verify(cfg)


if __name__ == "__main__":
    main()
