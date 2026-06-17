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
from datetime import date, datetime, timezone, timedelta
from pathlib import Path


MIN_PRIMARY_VALUES = 10_000
MIN_PRIMARY_BYTES = 100 * 1024
MIN_MEDIAN_VALUES = 1_000
MAX_PRIMARY_BYTES = 1_000_000_000
MAX_SOURCE_BYTES = 900_000_000
MAX_DOWNLOAD_VALIDATION_ROWS = 20_000
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

BOOKTICKER_FIELDS = {
    "best_bid_price": ("primary", "float", 64, "d", 1),
    "best_bid_qty": ("primary", "float", 64, "d", 2),
    "best_ask_price": ("primary", "float", 64, "d", 3),
    "best_ask_qty": ("primary", "float", 64, "d", 4),
}

BOOKDEPTH_FIELDS = {
    "timestamp_ms": ("auxiliary", "uint", 64, "Q", 0),
    "percentage": ("auxiliary", "float", 64, "d", 1),
    "depth": ("primary", "float", 64, "d", 2),
    "notional": ("primary", "float", 64, "d", 3),
}

FIELD_ALIASES = {
    "update_id": ["update_id", "updateid", "last_update_id", "u"],
    "best_bid_price": ["best_bid_price", "bid_price", "bidprice", "b"],
    "best_bid_qty": ["best_bid_qty", "bid_qty", "bidqty", "bid_quantity", "B"],
    "best_ask_price": ["best_ask_price", "ask_price", "askprice", "a"],
    "best_ask_qty": ["best_ask_qty", "ask_qty", "askqty", "ask_quantity", "A"],
    "transaction_time_ms": ["transaction_time", "transaction_time_ms", "transact_time", "transact_time_ms", "T"],
    "event_time_ms": ["event_time", "event_time_ms", "E"],
    "timestamp_ms": ["timestamp", "timestamp_ms", "time", "T"],
    "percentage": ["percentage", "percent", "level"],
    "depth": ["depth"],
    "notional": ["notional"],
    "buyer_maker": ["buyer_maker", "is_buyer_maker"],
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
    elif kind in {"bookTicker", "bookDepth"}:
        for symbol in cfg["symbols"]:
            for day in iter_dates(cfg["start_date"], cfg["end_date"]):
                name = f"{symbol}-{kind}-{day}.zip"
                rel = f"data/{market_path}/daily/{kind}/{symbol}/{name}"
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


def fields_for_kind(kind: str) -> dict:
    if kind == "klines":
        return KLINE_FIELDS
    if kind == "aggTrades":
        return AGGTRADE_FIELDS
    if kind == "bookTicker":
        return BOOKTICKER_FIELDS
    if kind == "bookDepth":
        return BOOKDEPTH_FIELDS
    raise SystemExit(f"unsupported kind: {kind}")


def field_text(value: str | bytes) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def normalize_header(value: str | bytes) -> str:
    text = field_text(value)
    return "".join(ch for ch in text.strip().lower() if ch.isalnum())


def header_index(row: list[str], fields: dict) -> dict[str, int] | None:
    exact = {field_text(value).strip(): idx for idx, value in enumerate(row)}
    normalized = {normalize_header(value): idx for idx, value in enumerate(row)}
    resolved = {}
    for sid in fields:
        aliases = FIELD_ALIASES.get(sid, [sid])
        for alias in aliases:
            if alias in exact:
                resolved[sid] = exact[alias]
                break
            if len(alias) == 1:
                continue
            key = normalize_header(alias)
            if key in normalized:
                resolved[sid] = normalized[key]
                break
    return resolved if len(resolved) == len(fields) else None


def parse_scalar(kind: str, code: str, raw: str | bytes):
    if kind == "float":
        return float(raw)
    if code == "B":
        text = field_text(raw).strip().lower()
        return 1 if text == "true" else 0 if text == "false" else int(raw)
    try:
        return int(raw)
    except ValueError:
        text = field_text(raw).strip()
        dt = datetime.strptime(text, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        return int(dt.timestamp() * 1000)


def validate_zip(path: Path, kind: str) -> int:
    if not path.is_file() or path.stat().st_size == 0:
        raise SystemExit(f"missing or empty ZIP: {path}")
    fields = fields_for_kind(kind)
    expected_cols = max(int(spec[4]) for spec in fields.values()) + 1
    max_validation_rows = int(os.environ.get("MAX_DOWNLOAD_VALIDATION_ROWS", MAX_DOWNLOAD_VALIDATION_ROWS))
    rows = 0
    valid_rows = 0
    stop = False
    with zipfile.ZipFile(path) as zf:
        names = [name for name in zf.namelist() if not name.endswith("/")]
        if not names:
            raise SystemExit(f"empty ZIP archive: {path}")
        for name in names:
            with zf.open(name) as fh:
                text = (line.decode("utf-8").strip() for line in fh)
                index_map = None
                for row in csv.reader(line for line in text if line):
                    if not row:
                        continue
                    maybe_header = header_index(row, fields)
                    if maybe_header:
                        index_map = maybe_header
                        continue
                    rows += 1
                    if len(row) < (max(index_map.values()) + 1 if index_map else expected_cols):
                        continue
                    try:
                        parse_field_row(row, fields, index_map)
                    except Exception:
                        continue
                    valid_rows += 1
                    if valid_rows >= max_validation_rows:
                        stop = True
                        break
            if stop:
                break
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
        print(f"validated {item['local_name']} checked_rows={row_count}")
        size = target.stat().st_size
        source_bytes += size
        if source_bytes > int(os.environ.get("MAX_SOURCE_BYTES", MAX_SOURCE_BYTES)):
            raise SystemExit(f"source bytes exceed cap: {source_bytes}")
        records.append({**item, "source_bytes": size, "validated_rows": row_count})

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
        fh.write("symbol\tperiod\tlocal_name\tsource_bytes\tvalidated_rows\n")
        for row in records:
            fh.write(f"{row['symbol']}\t{row['period']}\t{row['local_name']}\t{row['source_bytes']}\t{row['validated_rows']}\n")
    print(f"semantic_validation=ok resources={len(records)} source_bytes={source_bytes}")


def new_array(code: str) -> array:
    return array(code)


def append_value(values: array, kind: str, code: str, raw: str) -> None:
    values.append(parse_scalar(kind, code, raw))


def parse_field_row(row: list[str], fields: dict, index_map: dict[str, int] | None) -> dict:
    parsed = {}
    for sid, (_role, kind, _bits, code, fallback_idx) in fields.items():
        idx = index_map[sid] if index_map else fallback_idx
        parsed[sid] = parse_scalar(kind, code, row[idx])
    return parsed


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
            for raw in raw_fh:
                line = raw.strip()
                if line:
                    yield line.split(b",")


def build_one_resource(cfg: dict, zip_path: Path, record: dict, fields: dict) -> tuple[list[dict], int]:
    paths = repo_paths(cfg)
    data_root = paths["data_root"]
    samples_dir = paths["samples_dir"]
    dataset_id = cfg["dataset_id"]
    values = {sid: new_array(code) for sid, (_role, _kind, _bits, code, _idx) in fields.items()}
    skipped = 0
    accepted = 0
    max_rows = int(cfg.get("max_rows_per_resource_by_symbol", {}).get(record["symbol"], cfg.get("max_rows_per_resource", 0)) or 0)
    max_time_span_ms = int(float(cfg.get("max_time_span_seconds", 0) or 0) * 1000)
    time_filter_index = int(cfg.get("time_filter_index", 6))
    first_time_ms = None
    expected_cols = max(int(spec[4]) for spec in fields.values()) + 1
    index_map = None

    for row in read_csv_rows(zip_path):
        if not row:
            continue
        maybe_header = header_index(row, fields)
        if maybe_header:
            index_map = maybe_header
            continue
        if len(row) < (max(index_map.values()) + 1 if index_map else expected_cols):
            skipped += 1
            continue
        if max_time_span_ms:
            try:
                time_ms = int(row[time_filter_index])
            except Exception:
                skipped += 1
                continue
            if first_time_ms is None:
                first_time_ms = time_ms
            if time_ms >= first_time_ms + max_time_span_ms:
                break
        try:
            parsed = parse_field_row(row, fields, index_map)
        except Exception:
            skipped += 1
            continue
        for sid, value in parsed.items():
            values[sid].append(value)
        accepted += 1
        if max_rows and accepted >= max_rows:
            break

    sample_rows = []
    sample_tag = f"{record['symbol']}_{record['period']}".replace("-", "")
    geometry = "sequence"
    rank = 1
    shape = None
    axes = [cfg["sample_axis"]]
    if cfg["kind"] == "bookDepth" and values["timestamp_ms"] and values["percentage"]:
        timestamps = len(set(values["timestamp_ms"]))
        levels = len(set(values["percentage"]))
        if timestamps > 1 and levels > 1 and len(values["depth"]) == timestamps * levels:
            geometry = "grid"
            rank = 2
            shape = [timestamps, levels]
            axes = ["timestamp_ms", "percentage_level"]
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
                "sample_geometry": geometry,
                "sample_rank": rank,
                "sample_shape": shape if shape else [len(vals)],
                "sample_axes": axes,
                "source_rows_used": accepted,
                "source_rows_limit": max_rows,
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

    fields = fields_for_kind(cfg["kind"])
    all_rows = []
    skipped = 0
    source_bytes = 0
    for record in records:
        zip_path = download_dir / record["local_name"]
        source_bytes += zip_path.stat().st_size
        rows, skipped_rows = build_one_resource(cfg, zip_path, record, fields)
        all_rows.extend(rows)
        skipped += skipped_rows
        print(f"built_resource {record['local_name']} samples={len(rows)} skipped_rows={skipped_rows}", flush=True)

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
    fields = fields_for_kind(cfg["kind"])
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
        if row.get("sample_geometry") not in {"sequence", "grid"} or int(row.get("sample_rank", 0)) not in {1, 2}:
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
