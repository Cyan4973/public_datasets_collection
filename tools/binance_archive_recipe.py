#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import os
import shutil
import statistics
import subprocess
import sys
import zipfile
from array import array
from datetime import date, timedelta
from pathlib import Path


MIN_PRIMARY_VALUES = 10_000
MIN_PRIMARY_BYTES = 100 * 1024
MIN_MEDIAN_VALUES = 1_000
MAX_PRIMARY_BYTES = 1_000_000_000
MAX_SOURCE_BYTES = 900_000_000
BASE_URL = "https://data.binance.vision"

KLINE_FIELDS = {
    "open_time_ms": ("auxiliary", "uint", 64, "Q", 0),
    "open_price": ("primary", "float", 64, "d", 1),
    "high_price": ("primary", "float", 64, "d", 2),
    "low_price": ("primary", "float", 64, "d", 3),
    "close_price": ("primary", "float", 64, "d", 4),
    "base_volume": ("primary", "float", 64, "d", 5),
    "close_time_ms": ("auxiliary", "uint", 64, "Q", 6),
    "quote_volume": ("primary", "float", 64, "d", 7),
    "trade_count": ("primary", "uint", 32, "I", 8),
    "taker_buy_base_volume": ("primary", "float", 64, "d", 9),
    "taker_buy_quote_volume": ("primary", "float", 64, "d", 10),
}

AGGTRADE_FIELDS = {
    "agg_trade_id": ("auxiliary", "uint", 64, "Q", 0),
    "price": ("primary", "float", 64, "d", 1),
    "quantity": ("primary", "float", 64, "d", 2),
    "first_trade_id": ("auxiliary", "uint", 64, "Q", 3),
    "last_trade_id": ("auxiliary", "uint", 64, "Q", 4),
    "transact_time_ms": ("auxiliary", "uint", 64, "Q", 5),
    "buyer_maker": ("auxiliary", "uint", 8, "B", 6),
}


def load_config(path: Path) -> dict:
    cfg = json.loads(path.read_text(encoding="utf-8"))
    required = {"dataset_id", "kind", "market_path", "symbols"}
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


def iter_dates(start: str, end: str) -> list[str]:
    current = date.fromisoformat(start)
    last = date.fromisoformat(end)
    values = []
    while current <= last:
        values.append(current.isoformat())
        current += timedelta(days=1)
    return values


def resources(cfg: dict) -> list[dict]:
    out = []
    kind = cfg["kind"]
    market_path = cfg["market_path"].strip("/")
    if kind == "klines":
        interval = cfg["interval"]
        for symbol in cfg["symbols"]:
            for month in cfg["months"]:
                name = f"{symbol}-{interval}-{month}.zip"
                rel = f"data/{market_path}/monthly/klines/{symbol}/{interval}/{name}"
                out.append(
                    {
                        "symbol": symbol,
                        "period": month,
                        "local_name": name,
                        "url": f"{BASE_URL}/{rel}",
                    }
                )
    elif kind == "aggTrades":
        for symbol in cfg["symbols"]:
            for day in iter_dates(cfg["start_date"], cfg["end_date"]):
                name = f"{symbol}-aggTrades-{day}.zip"
                rel = f"data/{market_path}/daily/aggTrades/{symbol}/{name}"
                out.append(
                    {
                        "symbol": symbol,
                        "period": day,
                        "local_name": name,
                        "url": f"{BASE_URL}/{rel}",
                    }
                )
    else:
        raise SystemExit(f"unsupported kind: {kind}")
    return out


def validate_zip(path: Path, kind: str) -> int:
    if not path.is_file() or path.stat().st_size == 0:
        raise SystemExit(f"missing or empty ZIP: {path}")
    fields = KLINE_FIELDS if kind == "klines" else AGGTRADE_FIELDS
    expected_cols = 12 if kind == "klines" else 7
    rows = 0
    valid_rows = 0
    with zipfile.ZipFile(path) as zf:
        names = [name for name in zf.namelist() if not name.endswith("/")]
        if not names:
            raise SystemExit(f"empty ZIP archive: {path}")
        for name in names:
            with zf.open(name) as fh:
                text = (line.decode("utf-8").strip() for line in fh)
                for row in csv.reader(line for line in text if line):
                    if not row or row[0] in {"open_time", "agg_trade_id", "a"}:
                        continue
                    rows += 1
                    if len(row) < expected_cols:
                        continue
                    try:
                        for _sid, (_role, field_kind, _bits, code, idx) in fields.items():
                            tmp = new_array(code)
                            append_value(tmp, field_kind, code, row[idx])
                    except Exception:
                        continue
                    valid_rows += 1
    if rows <= 1 or valid_rows <= 1:
        raise SystemExit(f"ZIP has too few parseable CSV rows: {path} rows={rows} valid_rows={valid_rows}")
    return rows


def cmd_download(cfg: dict) -> None:
    paths = repo_paths(cfg)
    download_dir = paths["download_dir"]
    download_dir.mkdir(parents=True, exist_ok=True)
    plan_path = download_dir / "download_plan.tsv"
    inventory_path = download_dir / "download_inventory.json"
    inventory_tsv = download_dir / "download_inventory.tsv"
    force = os.environ.get("FORCE_DOWNLOAD") == "1"
    selected = resources(cfg)

    with plan_path.open("w", encoding="utf-8") as fh:
        fh.write("symbol\tperiod\tlocal_name\turl\n")
        for item in selected:
            fh.write(f"{item['symbol']}\t{item['period']}\t{item['local_name']}\t{item['url']}\n")

    records = []
    source_bytes = 0
    for item in selected:
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
        row_count = validate_zip(target, cfg["kind"])
        size = target.stat().st_size
        source_bytes += size
        if source_bytes > int(os.environ.get("MAX_SOURCE_BYTES", MAX_SOURCE_BYTES)):
            raise SystemExit(f"source bytes exceed cap: {source_bytes}")
        records.append({**item, "source_bytes": size, "csv_rows": row_count})

    inventory = {
        "dataset_id": cfg["dataset_id"],
        "kind": cfg["kind"],
        "market_path": cfg["market_path"],
        "resource_count": len(records),
        "source_bytes": source_bytes,
        "records": records,
    }
    inventory_path.write_text(json.dumps(inventory, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    with inventory_tsv.open("w", encoding="utf-8") as fh:
        fh.write("symbol\tperiod\tlocal_name\tsource_bytes\tcsv_rows\n")
        for row in records:
            fh.write(f"{row['symbol']}\t{row['period']}\t{row['local_name']}\t{row['source_bytes']}\t{row['csv_rows']}\n")
    print(f"semantic_validation=ok resources={len(records)} source_bytes={source_bytes}")


def new_array(code: str) -> array:
    return array(code)


def append_value(values: array, kind: str, code: str, raw: str) -> None:
    if kind == "float":
        values.append(float(raw))
    elif code == "B":
        text = raw.strip().lower()
        values.append(1 if text == "true" else 0 if text == "false" else int(raw))
    else:
        values.append(int(raw))


def write_array(path: Path, values: array) -> None:
    data = array(values.typecode, values)
    if sys.byteorder != "little" and data.itemsize > 1:
        data.byteswap()
    path.write_bytes(data.tobytes())


def read_csv_rows(zip_path: Path):
    with zipfile.ZipFile(zip_path) as zf:
        names = [name for name in zf.namelist() if not name.endswith("/")]
        if len(names) != 1:
            raise SystemExit(f"expected one CSV per ZIP, got {len(names)} in {zip_path}")
        with zf.open(names[0]) as raw_fh:
            text = (line.decode("utf-8").strip() for line in raw_fh)
            yield from csv.reader(line for line in text if line)


def build_one_resource(cfg: dict, zip_path: Path, record: dict, fields: dict) -> tuple[list[dict], int]:
    paths = repo_paths(cfg)
    data_root = paths["data_root"]
    samples_dir = paths["samples_dir"]
    dataset_id = cfg["dataset_id"]
    values = {sid: new_array(code) for sid, (_role, _kind, _bits, code, _idx) in fields.items()}
    skipped = 0
    expected_cols = 12 if cfg["kind"] == "klines" else 7

    for row in read_csv_rows(zip_path):
        if not row:
            continue
        if row[0] in {"open_time", "agg_trade_id", "a"}:
            continue
        if len(row) < expected_cols:
            skipped += 1
            continue
        parsed = {}
        try:
            for sid, (_role, kind, _bits, code, idx) in fields.items():
                tmp = new_array(code)
                append_value(tmp, kind, code, row[idx])
                parsed[sid] = tmp[0]
        except Exception:
            skipped += 1
            continue
        for sid, value in parsed.items():
            values[sid].append(value)

    sample_rows = []
    sample_tag = f"{record['symbol']}_{record['period']}".replace("-", "")
    for sid, vals in values.items():
        role, kind, bits, code, _idx = fields[sid]
        out_dir = samples_dir / sid
        out_dir.mkdir(parents=True, exist_ok=True)
        out = out_dir / f"{sample_tag}_{sid}_{kind}{bits}_n{len(vals):08d}.bin"
        write_array(out, vals)
        sample_rows.append(
            {
                "dataset_id": dataset_id,
                "series_id": sid,
                "role": role,
                "sample_path": out.relative_to(data_root).as_posix(),
                "numeric_kind": kind,
                "bit_width": bits,
                "endianness": "little",
                "element_size_bytes": bits // 8,
                "sample_size_bytes": out.stat().st_size,
                "value_count": len(vals),
                "symbol": record["symbol"],
                "period": record["period"],
                "sample_geometry": "sequence",
                "sample_rank": 1,
                "sample_shape": [len(vals)],
                "sample_axes": [cfg["sample_axis"]],
            }
        )
    return sample_rows, skipped


def cmd_build(cfg: dict) -> None:
    paths = repo_paths(cfg)
    download_dir = paths["download_dir"]
    filter_dir = paths["filter_dir"]
    index_dir = paths["index_dir"]
    samples_dir = paths["samples_dir"]
    inventory_path = download_dir / "download_inventory.json"
    if not inventory_path.exists():
        raise SystemExit(f"missing download inventory: {inventory_path}; run download.sh first")
    inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
    records = inventory.get("records", [])
    if not records:
        raise SystemExit("download inventory has no records")

    if samples_dir.exists():
        shutil.rmtree(samples_dir)
    samples_dir.mkdir(parents=True, exist_ok=True)
    filter_dir.mkdir(parents=True, exist_ok=True)
    index_dir.mkdir(parents=True, exist_ok=True)

    fields = KLINE_FIELDS if cfg["kind"] == "klines" else AGGTRADE_FIELDS
    all_rows = []
    skipped = 0
    source_bytes = 0
    for record in records:
        zip_path = download_dir / record["local_name"]
        source_bytes += zip_path.stat().st_size
        rows, skipped_rows = build_one_resource(cfg, zip_path, record, fields)
        all_rows.extend(rows)
        skipped += skipped_rows

    primary_rows = [row for row in all_rows if row["role"] == "primary"]
    primary_values = sum(int(row["value_count"]) for row in primary_rows)
    primary_bytes = sum(int(row["sample_size_bytes"]) for row in primary_rows)
    median_values = statistics.median(int(row["value_count"]) for row in primary_rows)
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
        "kind": cfg["kind"],
        "market_path": cfg["market_path"],
        "resource_count": len(records),
        "source_bytes": source_bytes,
        "rows_skipped": skipped,
        "sample_count": len(all_rows),
        "primary_samples": len(primary_rows),
        "primary_values": primary_values,
        "primary_bytes": primary_bytes,
        "median_primary_values": int(median_values),
    }
    (filter_dir / "ingest_stats.json").write_text(json.dumps(stats, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    with (index_dir / "samples.jsonl").open("w", encoding="utf-8") as fh:
        for row in all_rows:
            fh.write(json.dumps(row, sort_keys=True) + "\n")
    print(
        f"built_samples={len(all_rows)} primary_samples={len(primary_rows)} "
        f"primary_values={primary_values} primary_bytes={primary_bytes} "
        f"median_values={int(median_values)} source_bytes={source_bytes}"
    )


def nonconstant_prefix(path: Path, code: str, count: int) -> bool:
    if count <= 1:
        return False
    itemsize = array(code).itemsize
    limit = min(count, 200_000)
    data = path.read_bytes()[: limit * itemsize]
    vals = array(code)
    vals.frombytes(data)
    if sys.byteorder != "little" and vals.itemsize > 1:
        vals.byteswap()
    return len(set(vals)) > 1


def cmd_verify(cfg: dict) -> None:
    paths = repo_paths(cfg)
    data_root = paths["data_root"]
    filter_dir = paths["filter_dir"]
    index_dir = paths["index_dir"]
    index_path = index_dir / "samples.jsonl"
    stats_path = filter_dir / "ingest_stats.json"
    if not index_path.exists():
        raise SystemExit(f"missing sample index: {index_path}")
    if not stats_path.exists():
        raise SystemExit(f"missing ingest stats: {stats_path}")
    rows = [json.loads(line) for line in index_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    stats = json.loads(stats_path.read_text(encoding="utf-8"))
    fields = KLINE_FIELDS if cfg["kind"] == "klines" else AGGTRADE_FIELDS
    expected_series = set(fields)
    if {row["series_id"] for row in rows} != expected_series:
        raise SystemExit(f"unexpected series set: {sorted({row['series_id'] for row in rows})}")

    primary_sizes = []
    primary_counts = []
    for row in rows:
        sid = row["series_id"]
        role, kind, bits, code, _idx = fields[sid]
        if row["dataset_id"] != cfg["dataset_id"] or row.get("role") != role:
            raise SystemExit(f"unexpected row identity: {row}")
        if row["numeric_kind"] != kind or int(row["bit_width"]) != bits:
            raise SystemExit(f"unexpected numeric representation: {row}")
        path = data_root / row["sample_path"]
        if not path.is_file():
            raise SystemExit(f"missing sample: {row['sample_path']}")
        expected_size = int(row["value_count"]) * int(row["element_size_bytes"])
        if path.stat().st_size != int(row["sample_size_bytes"]) or path.stat().st_size != expected_size:
            raise SystemExit(f"size mismatch: {row['sample_path']}")
        if row.get("sample_geometry") != "sequence" or int(row.get("sample_rank", 0)) != 1:
            raise SystemExit(f"unexpected sample geometry: {row}")
        if role == "primary":
            if not nonconstant_prefix(path, code, int(row["value_count"])):
                raise SystemExit(f"constant primary prefix rejected: {row['sample_path']}")
            primary_sizes.append(int(row["sample_size_bytes"]))
            primary_counts.append(int(row["value_count"]))

    primary_values = sum(primary_counts)
    primary_bytes = sum(primary_sizes)
    median_values = statistics.median(primary_counts)
    if primary_values != int(stats["primary_values"]) or primary_bytes != int(stats["primary_bytes"]):
        raise SystemExit("stats/index primary total mismatch")
    if primary_values < MIN_PRIMARY_VALUES:
        raise SystemExit(f"primary values below floor: {primary_values}")
    if primary_bytes < MIN_PRIMARY_BYTES:
        raise SystemExit(f"primary bytes below floor: {primary_bytes}")
    if median_values < MIN_MEDIAN_VALUES:
        raise SystemExit(f"median primary sample values below floor: {median_values}")
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
