#!/usr/bin/env python3
from __future__ import annotations

import argparse
import gzip
import html.parser
import json
import os
import re
import shutil
import statistics
import sys
import urllib.parse
import urllib.request
from array import array
from pathlib import Path


MIN_PRIMARY_VALUES = 10_000
MIN_PRIMARY_BYTES = 100 * 1024
MIN_MEDIAN_VALUES = 1_000
MAX_PRIMARY_BYTES = 1_000_000_000
MAX_SOURCE_BYTES = 1_000_000_000


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


def load_config(path: Path) -> dict:
    cfg = json.loads(path.read_text(encoding="utf-8"))
    required = {"dataset_id", "seed_urls"}
    missing = sorted(required - set(cfg))
    if missing:
        raise SystemExit(f"missing config keys: {missing}")
    return cfg


def repo_paths(cfg: dict) -> dict[str, Path]:
    repo_root = Path(os.environ.get("REPO_ROOT", Path.cwd())).resolve()
    data_dir = os.environ.get("DATA_DIR", ".data")
    dataset_id = cfg["dataset_id"]
    data_root = repo_root / data_dir
    return {
        "repo_root": repo_root,
        "data_root": data_root,
        "download_dir": data_root / "downloads" / dataset_id,
        "filter_dir": data_root / "filtered" / dataset_id,
        "index_dir": data_root / "index" / dataset_id,
        "samples_dir": data_root / "samples" / dataset_id,
    }


def fetch_text(url: str, timeout: int) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "openzl-public-datasets/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return response.read().decode("utf-8", "replace")


def discover_matrix_urls(seed_url: str, timeout: int) -> list[str]:
    html = fetch_text(seed_url, timeout)
    parser = LinkParser()
    parser.feed(html)
    candidates = list(parser.links)
    candidates.extend(re.findall(r"https?://[^\s\"'<>]+", html))
    urls: list[str] = []
    for href in candidates:
        full = urllib.parse.urljoin(seed_url, href)
        parsed = urllib.parse.urlparse(full)
        if parsed.scheme not in {"http", "https"}:
            continue
        path = parsed.path.lower()
        if path.endswith((".mtx.gz", ".mtx")):
            urls.append(urllib.parse.urlunparse(parsed._replace(fragment="")))
    return urls


def read_url_list(path: Path) -> list[str]:
    urls: list[str] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line and not line.startswith("#"):
            urls.append(line)
    return urls


def local_name_for_url(url: str) -> str:
    name = Path(urllib.parse.unquote(urllib.parse.urlparse(url).path)).name
    if not name:
        name = re.sub(r"[^A-Za-z0-9._-]+", "_", url).strip("_") or "matrix.mtx.gz"
    return name


def open_matrix_text(path: Path):
    if path.name.lower().endswith(".gz"):
        return gzip.open(path, "rt", encoding="utf-8", errors="replace")
    return path.open("rt", encoding="utf-8", errors="replace")


def matrix_payload_hash(path: Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    if path.name.lower().endswith(".gz"):
        with gzip.open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(1024 * 1024), b""):
                digest.update(chunk)
    else:
        with path.open("rb") as fh:
            for chunk in iter(lambda: fh.read(1024 * 1024), b""):
                digest.update(chunk)
    return digest.hexdigest()


def parse_header(path: Path) -> dict:
    with open_matrix_text(path) as fh:
        header = ""
        for raw in fh:
            line = raw.strip()
            if line:
                header = line
                break
        parts = header.split()
        if len(parts) != 5 or parts[0] != "%%MatrixMarket" or parts[1].lower() != "matrix":
            raise ValueError(f"{path}: not a Matrix Market matrix")
        storage, field, symmetry = (part.lower() for part in parts[2:])
        if storage != "coordinate":
            raise ValueError(f"{path}: only coordinate sparse matrices are accepted")
        if field not in {"real", "integer", "pattern"}:
            raise ValueError(f"{path}: unsupported Matrix Market field {field}")
        if symmetry not in {"general", "symmetric", "skew-symmetric", "hermitian"}:
            raise ValueError(f"{path}: unsupported Matrix Market symmetry {symmetry}")
        for raw in fh:
            line = raw.strip()
            if not line or line.startswith("%"):
                continue
            dims = line.split()
            if len(dims) != 3:
                raise ValueError(f"{path}: malformed dimension line")
            rows, cols, entries = (int(token) for token in dims)
            if rows <= 0 or cols <= 0 or entries <= 0:
                raise ValueError(f"{path}: invalid matrix dimensions")
            return {
                "field": field,
                "symmetry": symmetry,
                "rows": rows,
                "cols": cols,
                "entries": entries,
            }
    raise ValueError(f"{path}: missing Matrix Market dimensions")


def iter_entries(path: Path, meta: dict):
    seen_dims = False
    with open_matrix_text(path) as fh:
        for raw in fh:
            line = raw.strip()
            if not line or line.startswith("%"):
                continue
            if line.startswith("%%MatrixMarket"):
                continue
            if not seen_dims:
                seen_dims = True
                continue
            parts = line.split()
            if meta["field"] == "pattern":
                if len(parts) < 2:
                    raise ValueError(f"{path}: malformed pattern entry")
                row, col = int(parts[0]), int(parts[1])
                value = None
            else:
                if len(parts) < 3:
                    raise ValueError(f"{path}: malformed numeric entry")
                row, col = int(parts[0]), int(parts[1])
                value = int(parts[2]) if meta["field"] == "integer" else float(parts[2])
            if row < 1 or row > meta["rows"] or col < 1 or col > meta["cols"]:
                raise ValueError(f"{path}: coordinate out of matrix bounds")
            yield row, col, value


def download_one(url: str, target: Path, timeout: int, max_file_bytes: int) -> None:
    req = urllib.request.Request(url, headers={"User-Agent": "openzl-public-datasets/1.0"})
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.unlink(missing_ok=True)
    with urllib.request.urlopen(req, timeout=timeout) as response, tmp.open("wb") as fh:
        total = 0
        while True:
            chunk = response.read(1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > max_file_bytes:
                raise SystemExit(f"{url}: file exceeds max_file_bytes={max_file_bytes}")
            fh.write(chunk)
    if tmp.stat().st_size <= 0:
        raise SystemExit(f"{url}: empty download")
    tmp.replace(target)


def collect_urls(cfg: dict, config_path: Path, timeout: int) -> list[str]:
    override = os.environ.get("MATRIX_MARKET_URLS_FILE")
    default_list = config_path.parent / "urls.txt"
    if override:
        urls = read_url_list(Path(override))
    elif default_list.exists():
        urls = read_url_list(default_list)
    else:
        urls = list(cfg.get("exact_urls", []))
    if not urls:
        for seed in cfg["seed_urls"]:
            urls.extend(discover_matrix_urls(str(seed), timeout))
    seen: set[str] = set()
    deduped = []
    for url in urls:
        if url not in seen:
            seen.add(url)
            deduped.append(url)
    return deduped


def cmd_download(cfg: dict, config_path: Path) -> None:
    apply_curlrc_proxy_fallback()
    paths = repo_paths(cfg)
    download_dir = paths["download_dir"]
    download_dir.mkdir(parents=True, exist_ok=True)
    timeout = int(os.environ.get("DOWNLOAD_TIMEOUT", "120"))
    max_files = int(os.environ.get("MAX_FILES", cfg.get("max_files", 24)))
    max_file_bytes = int(os.environ.get("MAX_FILE_BYTES", cfg.get("max_file_bytes", 250_000_000)))
    max_total_bytes = int(os.environ.get("MAX_DOWNLOAD_BYTES", cfg.get("max_source_bytes", MAX_SOURCE_BYTES)))
    force = os.environ.get("FORCE_DOWNLOAD") == "1"
    urls = collect_urls(cfg, config_path, timeout)[:max_files]
    if not urls:
        raise SystemExit("no Matrix Market URLs discovered; provide MATRIX_MARKET_URLS_FILE or adjust seed URLs")
    total = 0
    records = []
    failures = []
    for url in urls:
        target = download_dir / local_name_for_url(url)
        if target.exists() and target.stat().st_size > 0 and not force:
            print(f"cache_hit {target.name}")
        else:
            print(f"fetch {url}")
            try:
                download_one(url, target, timeout, max_file_bytes)
            except Exception as exc:
                failures.append({"url": url, "reason": f"download_failed: {exc}"})
                print(f"skip_url reason=download_failed url={url} error={exc}", file=sys.stderr)
                continue
        size = target.stat().st_size
        total += size
        if total > max_total_bytes:
            raise SystemExit(f"source bytes exceed cap: {total}")
        try:
            meta = parse_header(target)
        except Exception as exc:
            target.unlink(missing_ok=True)
            failures.append({"url": url, "reason": f"semantic_validation_failed: {exc}"})
            print(f"skip_url reason=semantic_validation_failed url={url} error={exc}", file=sys.stderr)
            total -= size
            continue
        if meta["entries"] < int(cfg.get("min_stored_entries_per_matrix", 1_000)):
            print(f"skip below matrix entry floor entries={meta['entries']} file={target.name}")
            target.unlink(missing_ok=True)
            failures.append({"url": url, "reason": f"below_entry_floor: {meta['entries']}"})
            total -= size
            continue
        records.append({"url": url, "local_name": target.name, "source_bytes": size, **meta})
        print(
            f"validated {target.name} rows={meta['rows']} cols={meta['cols']} "
            f"entries={meta['entries']} field={meta['field']} symmetry={meta['symmetry']}"
        )
    if not records:
        raise SystemExit("no Matrix Market files survived semantic validation")
    inventory = {
        "dataset_id": cfg["dataset_id"],
        "source_bytes": total,
        "resource_count": len(records),
        "failure_count": len(failures),
        "records": records,
        "failures": failures,
    }
    (download_dir / "download_inventory.json").write_text(json.dumps(inventory, indent=2, sort_keys=True) + "\n")
    with (download_dir / "download_inventory.tsv").open("w", encoding="utf-8") as fh:
        fh.write("local_name\tsource_bytes\trows\tcols\tentries\tfield\tsymmetry\turl\n")
        for row in records:
            fh.write(
                f"{row['local_name']}\t{row['source_bytes']}\t{row['rows']}\t{row['cols']}\t"
                f"{row['entries']}\t{row['field']}\t{row['symmetry']}\t{row['url']}\n"
            )
    print(f"semantic_validation=ok resources={len(records)} source_bytes={total}")


def write_array(path: Path, values: array) -> None:
    data = array(values.typecode, values)
    if sys.byteorder != "little" and data.itemsize > 1:
        data.byteswap()
    path.write_bytes(data.tobytes())


def nonconstant_prefix(path: Path, typecode: str, count: int) -> bool:
    if count <= 1:
        return False
    vals = array(typecode)
    vals.frombytes(path.read_bytes()[: min(count, 200_000) * vals.itemsize])
    if sys.byteorder != "little" and vals.itemsize > 1:
        vals.byteswap()
    return len(set(vals)) > 1


def add_index_row(
    rows: list[dict],
    *,
    cfg: dict,
    data_root: Path,
    sample_path: Path,
    series_id: str,
    numeric_kind: str,
    bit_width: int,
    element_size_bytes: int,
    value_count: int,
    source_file: str,
    meta: dict,
) -> None:
    rows.append(
        {
            "dataset_id": cfg["dataset_id"],
            "series_id": series_id,
            "role": "primary",
            "sample_path": sample_path.relative_to(data_root).as_posix(),
            "numeric_kind": numeric_kind,
            "bit_width": bit_width,
            "endianness": "little",
            "element_size_bytes": element_size_bytes,
            "sample_size_bytes": sample_path.stat().st_size,
            "value_count": value_count,
            "sample_geometry": "sparse_coordinate_matrix_attribute",
            "sample_rank": 1,
            "sample_shape": [value_count],
            "sample_axes": ["stored_entry"],
            "matrix_shape": [meta["rows"], meta["cols"]],
            "stored_entry_count": meta["entries"],
            "matrix_market_field": meta["field"],
            "matrix_market_symmetry": meta["symmetry"],
            "source_file": source_file,
        }
    )


def summarize(rows: list[dict]) -> dict:
    if not rows:
        raise SystemExit("no sparse matrix samples accepted")
    counts = [int(row["value_count"]) for row in rows if row.get("role") == "primary"]
    sizes = [int(row["sample_size_bytes"]) for row in rows if row.get("role") == "primary"]
    total_values = sum(counts)
    total_bytes = sum(sizes)
    median_values = statistics.median(counts)
    if total_values < MIN_PRIMARY_VALUES:
        raise SystemExit(f"primary values below floor: {total_values}")
    if total_bytes < MIN_PRIMARY_BYTES:
        raise SystemExit(f"primary bytes below floor: {total_bytes}")
    if median_values < MIN_MEDIAN_VALUES:
        raise SystemExit(f"median primary sample values below floor: {median_values}")
    if total_bytes > MAX_PRIMARY_BYTES:
        raise SystemExit(f"primary bytes exceed cap: {total_bytes}")
    return {
        "sample_count": len(rows),
        "primary_samples": len(rows),
        "primary_values": total_values,
        "primary_bytes": total_bytes,
        "median_primary_values": median_values,
        "min_sample_values": min(counts),
        "max_sample_values": max(counts),
        "min_sample_bytes": min(sizes),
        "max_sample_bytes": max(sizes),
        "same_size_fraction": max(counts.count(value) for value in set(counts)) / len(counts),
    }


def cmd_build(cfg: dict) -> None:
    paths = repo_paths(cfg)
    data_root = paths["data_root"]
    download_dir = paths["download_dir"]
    samples_dir = paths["samples_dir"]
    filter_dir = paths["filter_dir"]
    index_dir = paths["index_dir"]
    inventory_path = download_dir / "download_inventory.json"
    if not inventory_path.exists():
        raise SystemExit(f"missing download inventory: {inventory_path}; run download.sh first")
    inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
    records = inventory.get("records", [])
    if not records:
        raise SystemExit("download inventory has no records")
    if samples_dir.exists():
        shutil.rmtree(samples_dir)
    for series_id in ("row_index_u32", "col_index_u32", "entry_value_f64", "entry_value_i64"):
        (samples_dir / series_id).mkdir(parents=True, exist_ok=True)
    filter_dir.mkdir(parents=True, exist_ok=True)
    index_dir.mkdir(parents=True, exist_ok=True)

    rows_out: list[dict] = []
    matrix_stats = []
    skipped_duplicates = []
    seen_payload_hashes: dict[str, str] = {}
    for record in records:
        source = download_dir / record["local_name"]
        payload_hash = matrix_payload_hash(source)
        if payload_hash in seen_payload_hashes:
            skipped_duplicates.append(
                {
                    "local_name": record["local_name"],
                    "duplicate_of": seen_payload_hashes[payload_hash],
                    "matrix_sha256": payload_hash,
                }
            )
            print(
                f"skip_duplicate_matrix {record['local_name']} "
                f"duplicate_of={seen_payload_hashes[payload_hash]}"
            )
            continue
        seen_payload_hashes[payload_hash] = record["local_name"]
        meta = parse_header(source)
        row_index = array("I")
        col_index = array("I")
        values_real = array("d")
        values_int = array("q")
        for row, col, value in iter_entries(source, meta):
            row_index.append(row)
            col_index.append(col)
            if meta["field"] == "real":
                values_real.append(float(value))
            elif meta["field"] == "integer":
                values_int.append(int(value))
        if len(row_index) != meta["entries"] or len(col_index) != meta["entries"]:
            raise SystemExit(f"{source}: parsed entry count mismatch")
        stem = re.sub(r"\.mtx(?:\.gz)?$", "", source.name, flags=re.I)
        outputs = [
            ("row_index_u32", "uint", 32, 4, row_index, "I"),
            ("col_index_u32", "uint", 32, 4, col_index, "I"),
        ]
        if meta["field"] == "real":
            outputs.append(("entry_value_f64", "float", 64, 8, values_real, "d"))
        elif meta["field"] == "integer":
            outputs.append(("entry_value_i64", "int", 64, 8, values_int, "q"))
        for series_id, numeric_kind, bit_width, element_size_bytes, values, _typecode in outputs:
            out = samples_dir / series_id / f"{stem}_{series_id}_n{len(values):08d}.bin"
            write_array(out, values)
            add_index_row(
                rows_out,
                cfg=cfg,
                data_root=data_root,
                sample_path=out,
                series_id=series_id,
                numeric_kind=numeric_kind,
                bit_width=bit_width,
                element_size_bytes=element_size_bytes,
                value_count=len(values),
                source_file=record["local_name"],
                meta=meta,
            )
        matrix_stats.append(
            {
                "local_name": record["local_name"],
                "matrix_sha256": payload_hash,
                **meta,
                "emitted_series": len(outputs),
            }
        )
        print(
            f"built_matrix {record['local_name']} rows={meta['rows']} cols={meta['cols']} "
            f"entries={meta['entries']} field={meta['field']} emitted_series={len(outputs)}"
        )
    stats = summarize(rows_out)
    stats.update(
        {
            "dataset_id": cfg["dataset_id"],
            "resource_count": len(records),
            "source_bytes": int(inventory.get("source_bytes", 0)),
            "matrices": matrix_stats,
            "skipped_duplicate_matrices": skipped_duplicates,
        }
    )
    (filter_dir / "ingest_stats.json").write_text(json.dumps(stats, indent=2, sort_keys=True) + "\n")
    with (index_dir / "samples.jsonl").open("w", encoding="utf-8") as fh:
        for row in rows_out:
            fh.write(json.dumps(row, sort_keys=True) + "\n")
    print(
        f"built_samples={stats['sample_count']} primary_values={stats['primary_values']} "
        f"primary_bytes={stats['primary_bytes']} median_values={stats['median_primary_values']}"
    )


def cmd_verify(cfg: dict) -> None:
    paths = repo_paths(cfg)
    data_root = paths["data_root"]
    index_path = paths["index_dir"] / "samples.jsonl"
    stats_path = paths["filter_dir"] / "ingest_stats.json"
    if not index_path.exists() or not stats_path.exists():
        raise SystemExit("missing build outputs; run build.sh first")
    rows = [json.loads(line) for line in index_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    typecodes = {("uint", 32): "I", ("float", 64): "d", ("int", 64): "q"}
    for row in rows:
        if row["dataset_id"] != cfg["dataset_id"]:
            raise SystemExit(f"unexpected dataset id: {row}")
        if row.get("role") != "primary":
            raise SystemExit(f"unexpected non-primary row: {row}")
        if row.get("sample_geometry") != "sparse_coordinate_matrix_attribute":
            raise SystemExit(f"unexpected geometry: {row}")
        key = (row["numeric_kind"], int(row["bit_width"]))
        if key not in typecodes:
            raise SystemExit(f"unexpected numeric representation: {row}")
        path = data_root / row["sample_path"]
        if not path.is_file():
            raise SystemExit(f"missing sample: {row['sample_path']}")
        expected_size = int(row["value_count"]) * int(row["element_size_bytes"])
        if path.stat().st_size != expected_size or int(row["sample_size_bytes"]) != expected_size:
            raise SystemExit(f"size mismatch: {row['sample_path']}")
        if not nonconstant_prefix(path, typecodes[key], int(row["value_count"])):
            raise SystemExit(f"constant primary prefix rejected: {row['sample_path']}")
    stats = summarize(rows)
    recorded = json.loads(stats_path.read_text(encoding="utf-8"))
    if stats["primary_values"] != int(recorded["primary_values"]) or stats["primary_bytes"] != int(recorded["primary_bytes"]):
        raise SystemExit("stats/index primary total mismatch")
    print(
        f"verified_samples={len(rows)} primary_values={stats['primary_values']} "
        f"primary_bytes={stats['primary_bytes']} median_values={stats['median_primary_values']} "
        f"source_bytes={recorded.get('source_bytes', 0)}"
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["download", "build", "verify"])
    parser.add_argument("config", type=Path)
    args = parser.parse_args()
    cfg = load_config(args.config)
    if args.command == "download":
        cmd_download(cfg, args.config)
    elif args.command == "build":
        cmd_build(cfg)
    elif args.command == "verify":
        cmd_verify(cfg)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
