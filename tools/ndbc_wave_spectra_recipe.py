#!/usr/bin/env python3
from __future__ import annotations

import argparse
import gzip
import json
import os
import shutil
import statistics
import subprocess
import sys
from array import array
from pathlib import Path


MIN_PRIMARY_VALUES = 10_000
MIN_PRIMARY_BYTES = 100 * 1024
MIN_MEDIAN_VALUES = 1_000
MAX_PRIMARY_BYTES = 1_000_000_000
MAX_SOURCE_BYTES = 900_000_000
BASE_URL = "https://www.ndbc.noaa.gov/data/historical"


def load_config(path: Path) -> dict:
    cfg = json.loads(path.read_text(encoding="utf-8"))
    required = {"dataset_id", "stations", "years", "product_dir", "file_suffix"}
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


def resources(cfg: dict) -> list[dict]:
    out = []
    base_url = cfg.get("base_url", BASE_URL).rstrip("/")
    product_dir = cfg["product_dir"].strip("/")
    suffix = cfg["file_suffix"]
    for station in cfg["stations"]:
        for year in cfg["years"]:
            name = f"{station}{suffix}{year}.txt.gz"
            url = f"{base_url}/{product_dir}/{name}"
            out.append({"station": station, "year": int(year), "local_name": name, "url": url})
    return out


def parse_header(tokens: list[str]) -> tuple[int, list[float]] | None:
    if not tokens:
        return None
    first = tokens[0].lstrip("#").upper()
    if first not in {"YY", "YYYY"}:
        return None
    date_cols = 5 if len(tokens) > 4 and tokens[4].upper() == "MM" else 4
    freqs = []
    for token in tokens[date_cols:]:
        try:
            freqs.append(float(token))
        except ValueError:
            return None
    return (date_cols, freqs) if freqs else None


def iter_spectra(path: Path, stats: dict | None = None):
    header = None
    with gzip.open(path, "rt", encoding="utf-8", errors="replace") as fh:
        for raw in fh:
            line = raw.strip()
            if not line:
                continue
            tokens = line.split()
            parsed_header = parse_header(tokens)
            if parsed_header:
                header = parsed_header
                continue
            if header is None:
                continue
            date_cols, freqs = header
            if len(tokens) < date_cols + len(freqs):
                if stats is not None:
                    stats["skipped_short_rows"] = stats.get("skipped_short_rows", 0) + 1
                continue
            first = tokens[0].lstrip("#").upper()
            if first in {"YY", "YYYY", "YR"}:
                continue
            if stats is not None:
                stats["source_data_rows"] = stats.get("source_data_rows", 0) + 1
            values = []
            bad = False
            bad_reason = None
            for token in tokens[date_cols : date_cols + len(freqs)]:
                try:
                    value = float(token)
                except ValueError:
                    bad = True
                    bad_reason = "malformed"
                    break
                if abs(value) >= 900:
                    bad = True
                    bad_reason = "missing_sentinel"
                    break
                values.append(value)
            if bad:
                if stats is not None:
                    key = f"skipped_{bad_reason}_rows"
                    stats[key] = stats.get(key, 0) + 1
                continue
            if stats is not None:
                stats["kept_rows"] = stats.get("kept_rows", 0) + 1
            yield freqs, values


def validate_gzip(path: Path) -> dict:
    if not path.is_file() or path.stat().st_size <= 0:
        raise SystemExit(f"missing or empty gzip: {path}")
    rows = 0
    freq_count = 0
    first_freqs = None
    for freqs, values in iter_spectra(path):
        if first_freqs is None:
            first_freqs = freqs
            freq_count = len(freqs)
        elif freqs != first_freqs:
            raise SystemExit(f"frequency grid changed inside {path}")
        if len(values) != freq_count:
            raise SystemExit(f"bad spectrum width in {path}")
        rows += 1
        if rows >= 16:
            break
    if rows < 8 or freq_count < 8:
        raise SystemExit(f"too few parseable spectra in {path}: rows={rows} freq_count={freq_count}")
    return {"validated_rows": rows, "frequency_count": freq_count}


def cmd_download(cfg: dict) -> None:
    paths = repo_paths(cfg)
    download_dir = paths["download_dir"]
    download_dir.mkdir(parents=True, exist_ok=True)
    force = os.environ.get("FORCE_DOWNLOAD") == "1"
    plan = resources(cfg)
    source_bytes = 0
    records = []
    (download_dir / "download_plan.tsv").write_text(
        "station\tyear\tlocal_name\turl\n"
        + "".join(f"{r['station']}\t{r['year']}\t{r['local_name']}\t{r['url']}\n" for r in plan),
        encoding="utf-8",
    )
    for item in plan:
        target = download_dir / item["local_name"]
        if target.exists() and target.stat().st_size > 0 and not force:
            print(f"cache_hit {item['local_name']}")
        else:
            tmp = target.with_suffix(target.suffix + ".tmp")
            tmp.unlink(missing_ok=True)
            print(f"fetch {item['url']}")
            subprocess.run(
                [
                    "curl",
                    "--globoff",
                    "-fL",
                    "--retry",
                    "3",
                    "--retry-delay",
                    "5",
                    "-A",
                    "openzl-public-datasets/1.0",
                    "-o",
                    str(tmp),
                    item["url"],
                ],
                check=True,
            )
            tmp.replace(target)
        validation = validate_gzip(target)
        size = target.stat().st_size
        source_bytes += size
        if source_bytes > int(os.environ.get("MAX_SOURCE_BYTES", MAX_SOURCE_BYTES)):
            raise SystemExit(f"source bytes exceed cap: {source_bytes}")
        records.append({**item, "source_bytes": size, **validation})
        print(
            f"validated {item['local_name']} rows>={validation['validated_rows']} "
            f"freq_count={validation['frequency_count']}"
        )
    inventory = {
        "dataset_id": cfg["dataset_id"],
        "product_dir": cfg["product_dir"],
        "resource_count": len(records),
        "source_bytes": source_bytes,
        "records": records,
    }
    (download_dir / "download_inventory.json").write_text(json.dumps(inventory, indent=2, sort_keys=True) + "\n")
    with (download_dir / "download_inventory.tsv").open("w", encoding="utf-8") as fh:
        fh.write("station\tyear\tlocal_name\tsource_bytes\tfrequency_count\n")
        for row in records:
            fh.write(f"{row['station']}\t{row['year']}\t{row['local_name']}\t{row['source_bytes']}\t{row['frequency_count']}\n")
    print(f"semantic_validation=ok resources={len(records)} source_bytes={source_bytes}")


def write_array(path: Path, values: array) -> None:
    data = array(values.typecode, values)
    if sys.byteorder != "little" and data.itemsize > 1:
        data.byteswap()
    path.write_bytes(data.tobytes())


def nonconstant_prefix(path: Path, count: int) -> bool:
    if count <= 1:
        return False
    limit = min(count, 200_000)
    vals = array("d")
    vals.frombytes(path.read_bytes()[: limit * vals.itemsize])
    if sys.byteorder != "little":
        vals.byteswap()
    return len(set(vals)) > 1


def cmd_build(cfg: dict) -> None:
    paths = repo_paths(cfg)
    download_dir = paths["download_dir"]
    filter_dir = paths["filter_dir"]
    index_dir = paths["index_dir"]
    samples_dir = paths["samples_dir"]
    data_root = paths["data_root"]
    inventory_path = download_dir / "download_inventory.json"
    if not inventory_path.exists():
        raise SystemExit(f"missing download inventory: {inventory_path}; run download.sh first")
    inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
    records = inventory.get("records", [])
    if not records:
        raise SystemExit("download inventory has no records")
    if samples_dir.exists():
        shutil.rmtree(samples_dir)
    (samples_dir / "wave_spectral_density").mkdir(parents=True, exist_ok=True)
    filter_dir.mkdir(parents=True, exist_ok=True)
    index_dir.mkdir(parents=True, exist_ok=True)

    rows_out = []
    stats_rows = []
    primary_values = 0
    primary_bytes = 0
    for record in records:
        path = download_dir / record["local_name"]
        values = array("d")
        freq_count = 0
        row_count = 0
        row_stats: dict[str, int] = {}
        for freqs, spectrum in iter_spectra(path, row_stats):
            if freq_count == 0:
                freq_count = len(freqs)
            if len(freqs) != freq_count or len(spectrum) != freq_count:
                raise SystemExit(f"inconsistent frequency grid in {path}")
            values.extend(spectrum)
            row_count += 1
        if row_count < 1 or freq_count < 1:
            raise SystemExit(f"no spectra parsed from {path}")
        out = (
            samples_dir
            / "wave_spectral_density"
            / f"{record['station']}_{record['year']}_wave_spectral_density_float64_n{len(values):08d}.bin"
        )
        write_array(out, values)
        size = out.stat().st_size
        primary_values += len(values)
        primary_bytes += size
        rows_out.append(
            {
                "dataset_id": cfg["dataset_id"],
                "series_id": "wave_spectral_density",
                "role": "primary",
                "sample_path": out.relative_to(data_root).as_posix(),
                "numeric_kind": "float",
                "bit_width": 64,
                "endianness": "little",
                "element_size_bytes": 8,
                "sample_size_bytes": size,
                "value_count": len(values),
                "station": record["station"],
                "year": int(record["year"]),
                "sample_geometry": "grid",
                "sample_rank": 2,
                "sample_shape": [row_count, freq_count],
                "sample_axes": ["time", "frequency_hz"],
            }
        )
        stats_rows.append(
            {
                "station": record["station"],
                "year": int(record["year"]),
                "source_data_rows": int(row_stats.get("source_data_rows", row_count)),
                "kept_rows": int(row_stats.get("kept_rows", row_count)),
                "skipped_rows": int(row_stats.get("source_data_rows", row_count)) - row_count,
                "skipped_malformed_rows": int(row_stats.get("skipped_malformed_rows", 0)),
                "skipped_missing_sentinel_rows": int(row_stats.get("skipped_missing_sentinel_rows", 0)),
                "skipped_short_rows": int(row_stats.get("skipped_short_rows", 0)),
                "rows": row_count,
                "frequency_count": freq_count,
                "values": len(values),
                "bytes": size,
            }
        )
        print(f"built_resource {record['local_name']} rows={row_count} freq_count={freq_count} values={len(values)}", flush=True)

    counts = [int(row["value_count"]) for row in rows_out]
    median_values = statistics.median(counts)
    if primary_values < MIN_PRIMARY_VALUES:
        raise SystemExit(f"primary values below floor: {primary_values}")
    if primary_bytes < MIN_PRIMARY_BYTES:
        raise SystemExit(f"primary bytes below floor: {primary_bytes}")
    if median_values < MIN_MEDIAN_VALUES:
        raise SystemExit(f"median primary sample values below floor: {median_values}")
    if primary_bytes > MAX_PRIMARY_BYTES:
        raise SystemExit(f"primary bytes exceed cap: {primary_bytes}")

    stats = {
        "dataset_id": cfg["dataset_id"],
        "resource_count": len(records),
        "source_bytes": int(inventory.get("source_bytes", 0)),
        "sample_count": len(rows_out),
        "primary_samples": len(rows_out),
        "primary_values": primary_values,
        "primary_bytes": primary_bytes,
        "median_primary_values": int(median_values),
        "records": stats_rows,
    }
    (filter_dir / "ingest_stats.json").write_text(json.dumps(stats, indent=2, sort_keys=True) + "\n")
    with (index_dir / "samples.jsonl").open("w", encoding="utf-8") as fh:
        for row in rows_out:
            fh.write(json.dumps(row, sort_keys=True) + "\n")
    print(
        f"built_samples={len(rows_out)} primary_values={primary_values} "
        f"primary_bytes={primary_bytes} median_values={int(median_values)}"
    )


def cmd_verify(cfg: dict) -> None:
    paths = repo_paths(cfg)
    data_root = paths["data_root"]
    index_path = paths["index_dir"] / "samples.jsonl"
    stats_path = paths["filter_dir"] / "ingest_stats.json"
    if not index_path.exists() or not stats_path.exists():
        raise SystemExit("missing build outputs; run build.sh first")
    rows = [json.loads(line) for line in index_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    stats = json.loads(stats_path.read_text(encoding="utf-8"))
    if not rows:
        raise SystemExit("empty sample index")
    counts = []
    sizes = []
    for row in rows:
        if row["dataset_id"] != cfg["dataset_id"] or row["series_id"] != "wave_spectral_density":
            raise SystemExit(f"unexpected index row identity: {row}")
        if row.get("role") != "primary" or row["numeric_kind"] != "float" or int(row["bit_width"]) != 64:
            raise SystemExit(f"unexpected numeric representation: {row}")
        if row.get("sample_geometry") != "grid" or int(row.get("sample_rank", 0)) != 2:
            raise SystemExit(f"unexpected sample geometry: {row}")
        shape = row.get("sample_shape")
        if not isinstance(shape, list) or len(shape) != 2 or int(shape[0]) * int(shape[1]) != int(row["value_count"]):
            raise SystemExit(f"bad sample shape: {row}")
        path = data_root / row["sample_path"]
        if not path.is_file():
            raise SystemExit(f"missing sample: {row['sample_path']}")
        expected_size = int(row["value_count"]) * int(row["element_size_bytes"])
        if path.stat().st_size != expected_size or int(row["sample_size_bytes"]) != expected_size:
            raise SystemExit(f"size mismatch: {row['sample_path']}")
        if not nonconstant_prefix(path, int(row["value_count"])):
            raise SystemExit(f"constant primary prefix rejected: {row['sample_path']}")
        counts.append(int(row["value_count"]))
        sizes.append(expected_size)
    primary_values = sum(counts)
    primary_bytes = sum(sizes)
    median_values = statistics.median(counts)
    if primary_values != int(stats["primary_values"]) or primary_bytes != int(stats["primary_bytes"]):
        raise SystemExit("stats/index primary total mismatch")
    if primary_values < MIN_PRIMARY_VALUES or primary_bytes < MIN_PRIMARY_BYTES or median_values < MIN_MEDIAN_VALUES:
        raise SystemExit("acceptance floor failed")
    if primary_bytes > MAX_PRIMARY_BYTES:
        raise SystemExit(f"primary bytes exceed cap: {primary_bytes}")
    print(
        f"verified_samples={len(rows)} primary_values={primary_values} "
        f"primary_bytes={primary_bytes} median_values={int(median_values)} "
        f"source_bytes={stats.get('source_bytes', 0)}"
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["download", "build", "verify"])
    parser.add_argument("config", type=Path)
    args = parser.parse_args()
    cfg = load_config(args.config)
    if args.command == "download":
        cmd_download(cfg)
    elif args.command == "build":
        cmd_build(cfg)
    elif args.command == "verify":
        cmd_verify(cfg)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
