#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import math
import shutil
import statistics
import sys
import zipfile
from array import array
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

MIN_PRIMARY_VALUES = 10_000
MIN_PRIMARY_BYTES = 100 * 1024
MIN_MEDIAN_VALUES = 1_000
MAX_PRIMARY_BYTES = 1_000_000_000
CITIBIKE_FULL_YEAR_SOFT_PRIMARY_BYTES = 1_000_000_000
CITIBIKE_FULL_YEAR_MAX_PRIMARY_BYTES = 2_000_000_000

SEC_FSD_10Y_QUARTERS = [
    f"{year}q{quarter}"
    for year in range(2015, 2025)
    for quarter in range(1, 5)
]

SEC_FSD_TAGS = {
    "USD": [
        "StockholdersEquity",
        "InvestmentOwnedAtFairValue",
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "InvestmentOwnedAtCost",
        "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
        "InvestmentOwnedBalancePrincipalAmount",
        "NetIncomeLoss",
        "Revenues",
        "OperatingIncomeLoss",
        "Assets",
    ],
    "SHARES": [
        "CommonStockSharesOutstanding",
        "SharesOutstanding",
        "WeightedAverageNumberOfSharesOutstandingBasic",
        "CommonStockSharesIssued",
        "WeightedAverageNumberOfDilutedSharesOutstanding",
        "CommonStockSharesAuthorized",
        "StockIssuedDuringPeriodSharesNewIssues",
        "PreferredStockSharesAuthorized",
        "InvestmentOwnedBalanceShares",
        "PreferredStockSharesOutstanding",
    ],
}

CITIBIKE_2024_ARCHIVES = [
    f"2024{month:02d}-citibike-tripdata.zip"
    for month in range(1, 13)
]


def snake_tag(text: str) -> str:
    out = []
    prev_is_lower_or_digit = False
    for ch in text:
        if ch.isupper() and prev_is_lower_or_digit:
            out.append("_")
        if ch.isalnum():
            out.append(ch.lower())
            prev_is_lower_or_digit = ch.islower() or ch.isdigit()
        else:
            if out and out[-1] != "_":
                out.append("_")
            prev_is_lower_or_digit = False
    return "".join(out).strip("_")


def sec_fsd_series_id(unit: str, tag: str) -> str:
    return f"sec_fsd_{unit.lower()}_{snake_tag(tag)}_i64"


def sec_fsd_series_map() -> dict[str, tuple[str, int, str, int]]:
    return {
        sec_fsd_series_id(unit, tag): ("int", 64, "q", 8)
        for unit, tags in SEC_FSD_TAGS.items()
        for tag in tags
    }


DATASETS = {
    "citibike_2024_trip_geocoords_f64": {
        "kind": "citibike",
        "geometry": "trip_month_table_column",
        "expected_archives": CITIBIKE_2024_ARCHIVES,
        "soft_primary_bytes": CITIBIKE_FULL_YEAR_SOFT_PRIMARY_BYTES,
        "max_primary_bytes": CITIBIKE_FULL_YEAR_MAX_PRIMARY_BYTES,
        "series": {
            "start_latitude_f64": ("float", 64, "d", 8),
            "start_longitude_f64": ("float", 64, "d", 8),
            "end_latitude_f64": ("float", 64, "d", 8),
            "end_longitude_f64": ("float", 64, "d", 8),
        },
    },
    "usdot_bts_ontime_2024_q1_f64": {
        "kind": "bts",
        "geometry": "flight_month_table_column",
        "series": {
            "departure_delay_minutes_f64": ("float", 64, "d", 8),
            "arrival_delay_minutes_f64": ("float", 64, "d", 8),
            "air_time_minutes_f64": ("float", 64, "d", 8),
            "taxi_out_minutes_f64": ("float", 64, "d", 8),
            "taxi_in_minutes_f64": ("float", 64, "d", 8),
            "distance_miles_f64": ("float", 64, "d", 8),
        },
    },
    "census_acs_pums_ca_person_2023_i64": {
        "kind": "pums",
        "geometry": "person_microdata_table_column",
        "series": {
            "person_weight_i64": ("int", 64, "q", 8),
            "personal_income_i64": ("int", 64, "q", 8),
            "wage_income_i64": ("int", 64, "q", 8),
            "weeks_worked_i64": ("int", 64, "q", 8),
        },
    },
    "sec_fsd_2015q1_2024q4_numeric_values_i64": {
        "kind": "sec_fsd",
        "geometry": "quarterly_sec_num_table_tag_unit_column",
        "series": sec_fsd_series_map(),
        "sec_fsd_quarters": SEC_FSD_10Y_QUARTERS,
        "sec_fsd_tags": SEC_FSD_TAGS,
    },
}


def data_root(repo_root: Path, data_dir: str) -> Path:
    root = Path(data_dir)
    if not root.is_absolute():
        root = repo_root / root
    return root


def paths(repo_root: Path, data_dir: str, dataset_id: str) -> dict[str, Path]:
    root = data_root(repo_root, data_dir)
    return {
        "data": root,
        "downloads": root / "downloads" / dataset_id,
        "filtered": root / "filtered" / dataset_id,
        "index": root / "index" / dataset_id,
        "samples": root / "samples" / dataset_id,
    }


def reset_output(ps: dict[str, Path]) -> None:
    for key in ("filtered", "index", "samples"):
        if ps[key].exists():
            shutil.rmtree(ps[key])
        ps[key].mkdir(parents=True, exist_ok=True)


def ensure_output(ps: dict[str, Path]) -> None:
    for key in ("filtered", "index", "samples"):
        ps[key].mkdir(parents=True, exist_ok=True)


def rel(ps: dict[str, Path], path: Path) -> str:
    return path.relative_to(ps["data"]).as_posix()


def write_array(path: Path, values: array) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    out = array(values.typecode, values)
    if sys.byteorder != "little":
        out.byteswap()
    with path.open("wb") as fh:
        out.tofile(fh)


def sample_stem(name: str) -> str:
    stem = Path(name).name
    for suffix in (".csv", ".tsv", ".txt", ".zip"):
        stem = stem.removesuffix(suffix)
    return "".join(ch.lower() if ch.isalnum() else "_" for ch in stem).strip("_")


def parse_float(text: str) -> float | None:
    s = (text or "").strip()
    if not s:
        return None
    try:
        value = float(s)
    except ValueError:
        return None
    if not math.isfinite(value):
        return None
    return value


def parse_int(text: str) -> int | None:
    s = (text or "").strip()
    if not s:
        return None
    try:
        dec = Decimal(s)
    except InvalidOperation:
        return None
    if dec != dec.to_integral_value():
        return None
    value = int(dec)
    if value < -(2**63) or value >= 2**63:
        return None
    return value


def add_sample(
    ps: dict[str, Path],
    dataset_id: str,
    rows: list[dict],
    series_id: str,
    numeric_kind: str,
    bit_width: int,
    element_size: int,
    values: array,
    source_name: str,
    geometry: str,
    extras: dict | None = None,
) -> None:
    if not values:
        return
    stem = sample_stem(source_name)
    path = ps["samples"] / series_id / f"{stem}_{series_id}_n{len(values):08d}.bin"
    write_array(path, values)
    row = {
        "dataset_id": dataset_id,
        "series_id": series_id,
        "role": "primary",
        "sample_path": rel(ps, path),
        "numeric_kind": numeric_kind,
        "bit_width": bit_width,
        "endianness": "little",
        "element_size_bytes": element_size,
        "sample_size_bytes": path.stat().st_size,
        "value_count": len(values),
        "sample_geometry": geometry,
        "sample_rank": 1,
        "sample_shape": [len(values)],
        "sample_axes": ["row"],
        "source_name": source_name,
    }
    if extras:
        row.update(extras)
    rows.append(row)


def iter_zip_csv(zip_path: Path):
    with zipfile.ZipFile(zip_path) as zf:
        names = [n for n in zf.namelist() if not n.endswith("/") and n.lower().endswith(".csv")]
        if not names:
            raise SystemExit(f"{zip_path}: no CSV member")
        for name in sorted(names):
            with zf.open(name) as fh:
                text = (line.decode("utf-8-sig", errors="replace") for line in fh)
                yield name, csv.DictReader(text)


def build_citibike(dataset_id: str, ps: dict[str, Path], cfg: dict) -> dict:
    archives_by_name = {path.name: path for path in ps["downloads"].glob("*.zip")}
    expected_archives = cfg.get("expected_archives")
    if expected_archives:
        missing = [name for name in expected_archives if name not in archives_by_name]
        unexpected = sorted(set(archives_by_name) - set(expected_archives))
        if missing:
            raise SystemExit(f"missing Citi Bike zip files under {ps['downloads']}: {missing}")
        if unexpected:
            raise SystemExit(f"unexpected Citi Bike zip files under {ps['downloads']}: {unexpected}")
        archives = [archives_by_name[name] for name in expected_archives]
    else:
        archives = sorted(archives_by_name.values())
    if not archives:
        raise SystemExit(f"missing Citi Bike zip under {ps['downloads']}")
    series_map = {
        "start_latitude_f64": "start_lat",
        "start_longitude_f64": "start_lng",
        "end_latitude_f64": "end_lat",
        "end_longitude_f64": "end_lng",
    }
    rows: list[dict] = []
    resource_stats = []
    total_rows = kept_rows = skipped_rows = 0
    for archive in archives:
        for member, reader in iter_zip_csv(archive):
            arrays = {sid: array("d") for sid in series_map}
            member_total_rows = member_kept_rows = member_skipped_rows = 0
            header = reader.fieldnames or []
            absent = [col for col in series_map.values() if col not in header]
            if absent:
                raise SystemExit(f"{archive}:{member}: missing Citi Bike columns {absent}")
            for record in reader:
                total_rows += 1
                member_total_rows += 1
                parsed = {sid: parse_float(record.get(col, "")) for sid, col in series_map.items()}
                if any(value is None for value in parsed.values()):
                    skipped_rows += 1
                    member_skipped_rows += 1
                    continue
                if not (
                    -90.0 <= parsed["start_latitude_f64"] <= 90.0
                    and -90.0 <= parsed["end_latitude_f64"] <= 90.0
                    and -180.0 <= parsed["start_longitude_f64"] <= 180.0
                    and -180.0 <= parsed["end_longitude_f64"] <= 180.0
                ):
                    skipped_rows += 1
                    member_skipped_rows += 1
                    continue
                for sid, value in parsed.items():
                    arrays[sid].append(float(value))
                kept_rows += 1
                member_kept_rows += 1
            for sid, values in arrays.items():
                kind, width, _code, elem = cfg["series"][sid]
                add_sample(
                    ps,
                    dataset_id,
                    rows,
                    sid,
                    kind,
                    width,
                    elem,
                    values,
                    member,
                    cfg["geometry"],
                    {"source_archive": archive.name},
                )
            resource_stats.append(
                {
                    "archive": archive.name,
                    "member": member,
                    "kept_rows": member_kept_rows,
                    "skipped_rows": member_skipped_rows,
                    "total_rows": member_total_rows,
                }
            )
    return {
        "dataset_id": dataset_id,
        "source_bytes": sum(p.stat().st_size for p in archives),
        "total_rows": total_rows,
        "kept_rows": kept_rows,
        "skipped_rows": skipped_rows,
        "resources": resource_stats,
        "sample_rows": rows,
    }


def build_bts(dataset_id: str, ps: dict[str, Path], cfg: dict) -> dict:
    archives = sorted(ps["downloads"].glob("*.zip"))
    if not archives:
        raise SystemExit(f"missing BTS zip files under {ps['downloads']}")
    series_map = {
        "departure_delay_minutes_f64": "DepDelayMinutes",
        "arrival_delay_minutes_f64": "ArrDelayMinutes",
        "air_time_minutes_f64": "AirTime",
        "taxi_out_minutes_f64": "TaxiOut",
        "taxi_in_minutes_f64": "TaxiIn",
        "distance_miles_f64": "Distance",
    }
    rows: list[dict] = []
    resource_stats = []
    for archive in archives:
        for member, reader in iter_zip_csv(archive):
            arrays = {sid: array("d") for sid in series_map}
            total_rows = kept_by_series = {sid: 0 for sid in series_map}
            missing = {sid: 0 for sid in series_map}
            header = reader.fieldnames or []
            absent = [col for col in series_map.values() if col not in header]
            if absent:
                raise SystemExit(f"{archive}:{member}: missing BTS columns {absent}")
            for record in reader:
                total_rows += 1
                for sid, col in series_map.items():
                    value = parse_float(record.get(col, ""))
                    if value is None:
                        missing[sid] += 1
                    else:
                        arrays[sid].append(value)
                        kept_by_series[sid] += 1
            for sid, values in arrays.items():
                kind, width, _code, elem = cfg["series"][sid]
                add_sample(ps, dataset_id, rows, sid, kind, width, elem, values, member, cfg["geometry"])
            resource_stats.append(
                {"archive": archive.name, "member": member, "total_rows": total_rows, "kept_by_series": kept_by_series, "missing_by_series": missing}
            )
    return {
        "dataset_id": dataset_id,
        "source_bytes": sum(p.stat().st_size for p in archives),
        "resources": resource_stats,
        "sample_rows": rows,
    }


def build_pums(dataset_id: str, ps: dict[str, Path], cfg: dict) -> dict:
    archives = sorted(ps["downloads"].glob("*.zip"))
    if not archives:
        raise SystemExit(f"missing ACS PUMS zip under {ps['downloads']}")
    series_map = {
        "person_weight_i64": "PWGTP",
        "personal_income_i64": "PINCP",
        "wage_income_i64": "WAGP",
        "weeks_worked_i64": "WKWN",
    }
    rows: list[dict] = []
    resource_stats = []
    for archive in archives:
        with zipfile.ZipFile(archive) as zf:
            members = [n for n in zf.namelist() if Path(n).name.lower().startswith("psam_p") and n.lower().endswith(".csv")]
            if not members:
                raise SystemExit(f"{archive}: no ACS person CSV member")
            for member in sorted(members):
                arrays = {sid: array("q") for sid in series_map}
                total_rows = 0
                missing = {sid: 0 for sid in series_map}
                with zf.open(member) as fh:
                    text = (line.decode("utf-8-sig", errors="replace") for line in fh)
                    reader = csv.DictReader(text)
                    header = reader.fieldnames or []
                    absent = [col for col in series_map.values() if col not in header]
                    if absent:
                        raise SystemExit(f"{archive}:{member}: missing ACS columns {absent}")
                    for record in reader:
                        total_rows += 1
                        for sid, col in series_map.items():
                            value = parse_int(record.get(col, ""))
                            if value is None:
                                missing[sid] += 1
                            else:
                                arrays[sid].append(value)
                for sid, values in arrays.items():
                    kind, width, _code, elem = cfg["series"][sid]
                    add_sample(ps, dataset_id, rows, sid, kind, width, elem, values, member, cfg["geometry"])
                resource_stats.append({"archive": archive.name, "member": member, "total_rows": total_rows, "missing_by_series": missing})
    return {
        "dataset_id": dataset_id,
        "source_bytes": sum(p.stat().st_size for p in archives),
        "resources": resource_stats,
        "sample_rows": rows,
    }


def build_sec_fsd(dataset_id: str, ps: dict[str, Path], cfg: dict) -> dict:
    expected_archives = [f"{quarter}.zip" for quarter in cfg["sec_fsd_quarters"]]
    archives_by_name = {path.name: path for path in ps["downloads"].glob("*.zip")}
    missing = [name for name in expected_archives if name not in archives_by_name]
    unexpected = sorted(set(archives_by_name) - set(expected_archives))
    if missing:
        raise SystemExit(f"missing SEC FSD zip files under {ps['downloads']}: {missing}")
    if unexpected:
        raise SystemExit(f"unexpected SEC FSD zip files under {ps['downloads']}: {unexpected}")
    archives = [archives_by_name[name] for name in expected_archives]
    selected = {
        (unit, tag): sec_fsd_series_id(unit, tag)
        for unit, tags in cfg["sec_fsd_tags"].items()
        for tag in tags
    }
    rows: list[dict] = []
    resource_stats = []
    for archive in archives:
        with zipfile.ZipFile(archive) as zf:
            members = [n for n in zf.namelist() if Path(n).name.lower() in {"num.txt", "num.tsv"}]
            if not members:
                raise SystemExit(f"{archive}: no SEC num member")
            for member in members:
                arrays = {series_id: array("q") for series_id in selected.values()}
                total_rows = skipped_non_integral = skipped_unselected = 0
                with zf.open(member) as fh:
                    text = (line.decode("utf-8", errors="replace") for line in fh)
                    reader = csv.DictReader(text, delimiter="\t")
                    header = reader.fieldnames or []
                    for col in ("tag", "uom", "value"):
                        if col not in header:
                            raise SystemExit(f"{archive}:{member}: missing SEC column {col}")
                    for record in reader:
                        total_rows += 1
                        value = parse_int(record.get("value", ""))
                        if value is None:
                            skipped_non_integral += 1
                            continue
                        uom = (record.get("uom") or "").strip().upper()
                        tag = (record.get("tag") or "").strip()
                        series_id = selected.get((uom, tag))
                        if series_id is None:
                            skipped_unselected += 1
                            continue
                        arrays[series_id].append(value)
                quarter = archive.stem.lower()
                kept_by_series = {}
                for (unit, tag), sid in selected.items():
                    values = arrays[sid]
                    kind, width, _code, elem = cfg["series"][sid]
                    add_sample(
                        ps,
                        dataset_id,
                        rows,
                        sid,
                        kind,
                        width,
                        elem,
                        values,
                        f"{quarter}_{member}",
                        cfg["geometry"],
                        {"quarter": quarter, "sec_tag": tag, "uom": unit},
                    )
                    kept_by_series[sid] = len(values)
                resource_stats.append(
                    {
                        "archive": archive.name,
                        "member": member,
                        "total_rows": total_rows,
                        "skipped_non_integral_or_missing": skipped_non_integral,
                        "skipped_unselected_tag_or_unit": skipped_unselected,
                        "kept_by_series": kept_by_series,
                    }
                )
    return {
        "dataset_id": dataset_id,
        "source_bytes": sum(p.stat().st_size for p in archives),
        "resources": resource_stats,
        "sample_rows": rows,
    }


BUILDERS = {
    "citibike": build_citibike,
    "bts": build_bts,
    "pums": build_pums,
    "sec_fsd": build_sec_fsd,
}


def summarize_and_write(dataset_id: str, ps: dict[str, Path], cfg: dict, stats: dict) -> None:
    rows = stats.pop("sample_rows")
    if not rows:
        raise SystemExit("no samples built")
    counts = [int(row["value_count"]) for row in rows if row.get("role") == "primary"]
    sizes = [int(row["sample_size_bytes"]) for row in rows if row.get("role") == "primary"]
    primary_values = sum(counts)
    primary_bytes = sum(sizes)
    median_values = statistics.median(counts) if counts else 0
    if primary_values < MIN_PRIMARY_VALUES:
        raise SystemExit(f"primary values below floor: {primary_values}")
    if primary_bytes < MIN_PRIMARY_BYTES:
        raise SystemExit(f"primary bytes below floor: {primary_bytes}")
    if median_values < MIN_MEDIAN_VALUES:
        raise SystemExit(f"median primary sample values below floor: {median_values}")
    soft_primary_bytes = int(cfg.get("soft_primary_bytes", MAX_PRIMARY_BYTES))
    max_primary_bytes = int(cfg.get("max_primary_bytes", MAX_PRIMARY_BYTES))
    if primary_bytes > max_primary_bytes:
        raise SystemExit(f"primary bytes exceed hard cap: {primary_bytes} > {max_primary_bytes}")

    stats.update(
        {
            "primary_samples": len(counts),
            "primary_values": primary_values,
            "primary_bytes": primary_bytes,
            "median_primary_values": median_values,
            "min_primary_values": min(counts),
            "max_primary_values": max(counts),
            "soft_primary_bytes": soft_primary_bytes,
            "max_primary_bytes": max_primary_bytes,
            "exceeds_soft_primary_bytes": primary_bytes > soft_primary_bytes,
        }
    )
    (ps["index"] / "samples.jsonl").write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )
    (ps["filtered"] / "ingest_stats.json").write_text(json.dumps(stats, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        f"built_samples={len(rows)} primary_values={primary_values} "
        f"primary_bytes={primary_bytes} median_values={median_values}"
    )
    if primary_bytes > soft_primary_bytes:
        print(f"warning_primary_bytes_exceed_soft_limit={primary_bytes}>{soft_primary_bytes}")


def build(dataset_id: str, repo_root: Path, data_dir: str) -> None:
    if dataset_id not in DATASETS:
        raise SystemExit(f"unknown dataset_id: {dataset_id}")
    cfg = DATASETS[dataset_id]
    ps = paths(repo_root, data_dir, dataset_id)
    reset_output(ps)
    stats = BUILDERS[cfg["kind"]](dataset_id, ps, cfg)
    summarize_and_write(dataset_id, ps, cfg, stats)


def decode_prefix(path: Path, code: str, count: int):
    n = min(count, 4096)
    size = array(code).itemsize
    vals = array(code)
    with path.open("rb") as fh:
        vals.frombytes(fh.read(n * size))
    if sys.byteorder != "little":
        vals.byteswap()
    return vals


def verify(dataset_id: str, repo_root: Path, data_dir: str) -> None:
    if dataset_id not in DATASETS:
        raise SystemExit(f"unknown dataset_id: {dataset_id}")
    cfg = DATASETS[dataset_id]
    ps = paths(repo_root, data_dir, dataset_id)
    ensure_output(ps)
    index_path = ps["index"] / "samples.jsonl"
    stats_path = ps["filtered"] / "ingest_stats.json"
    if not index_path.exists():
        raise SystemExit(f"missing index: {index_path}")
    if not stats_path.exists():
        raise SystemExit(f"missing stats: {stats_path}")
    rows = [json.loads(line) for line in index_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    stats = json.loads(stats_path.read_text(encoding="utf-8"))
    if stats.get("dataset_id") != dataset_id:
        raise SystemExit(f"stats dataset mismatch: {stats.get('dataset_id')}")

    counts = []
    sizes = []
    allowed = cfg["series"]
    for row in rows:
        sid = row["series_id"]
        if sid not in allowed:
            raise SystemExit(f"unexpected series: {sid}")
        kind, width, code, elem = allowed[sid]
        if row.get("role") != "primary" or row["numeric_kind"] != kind or int(row["bit_width"]) != width:
            raise SystemExit(f"unexpected index row: {row}")
        if int(row["element_size_bytes"]) != elem:
            raise SystemExit(f"element size mismatch: {row}")
        path = ps["data"] / row["sample_path"]
        if not path.is_file():
            raise SystemExit(f"missing sample: {row['sample_path']}")
        count = int(row["value_count"])
        size = int(row["sample_size_bytes"])
        if path.stat().st_size != size or size != count * elem:
            raise SystemExit(f"size/count mismatch: {row['sample_path']}")
        prefix = decode_prefix(path, code, count)
        if len(prefix) > 1 and len(set(prefix)) <= 1:
            raise SystemExit(f"constant primary prefix rejected: {row['sample_path']}")
        counts.append(count)
        sizes.append(size)

    primary_values = sum(counts)
    primary_bytes = sum(sizes)
    median_values = statistics.median(counts) if counts else 0
    if primary_values != int(stats["primary_values"]) or primary_bytes != int(stats["primary_bytes"]):
        raise SystemExit("stats/index primary total mismatch")
    if primary_values < MIN_PRIMARY_VALUES:
        raise SystemExit(f"primary values below floor: {primary_values}")
    if primary_bytes < MIN_PRIMARY_BYTES:
        raise SystemExit(f"primary bytes below floor: {primary_bytes}")
    if median_values < MIN_MEDIAN_VALUES:
        raise SystemExit(f"median primary sample values below floor: {median_values}")
    soft_primary_bytes = int(cfg.get("soft_primary_bytes", MAX_PRIMARY_BYTES))
    max_primary_bytes = int(cfg.get("max_primary_bytes", MAX_PRIMARY_BYTES))
    if primary_bytes > max_primary_bytes:
        raise SystemExit(f"primary bytes exceed hard cap: {primary_bytes} > {max_primary_bytes}")
    print(
        f"verified_samples={len(rows)} primary_values={primary_values} "
        f"primary_bytes={primary_bytes} median_values={median_values} "
        f"source_bytes={stats.get('source_bytes', 0)}"
    )
    if primary_bytes > soft_primary_bytes:
        print(f"warning_primary_bytes_exceed_soft_limit={primary_bytes}>{soft_primary_bytes}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["build", "verify"])
    parser.add_argument("dataset_id", choices=sorted(DATASETS))
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--data-dir", default=".data")
    args = parser.parse_args()
    repo_root = Path(args.repo_root).resolve()
    if args.action == "build":
        build(args.dataset_id, repo_root, args.data_dir)
    else:
        verify(args.dataset_id, repo_root, args.data_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
