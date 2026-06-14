#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import statistics
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATA_DIR = ".data"
MIN_NATURAL_RECORD_VALUES = 1_000


def fmt(value: float | int) -> str:
    if isinstance(value, float) and not value.is_integer():
        return f"{value:.1f}"
    return str(int(value))


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def image_record_from_stats(dataset_id: str, stats: dict) -> list[dict]:
    rows = []
    for split in stats.get("splits", []):
        image = split.get("images")
        if not isinstance(image, dict):
            continue
        shape = image.get("shape")
        if shape:
            record_count = int(shape[0])
            record_values = 1
            for dim in shape[1:]:
                record_values *= int(dim)
        else:
            record_count = int(image.get("images", 0))
            record_values = int(image.get("values", 0)) // record_count if record_count else 0
        rows.append(
            {
                "dataset_id": dataset_id,
                "series_id": infer_primary_series_id(dataset_id),
                "sample_path": image.get("file") or image.get("sample_dir", ""),
                "split": split.get("split", ""),
                "natural_record_kind": "image",
                "natural_record_count": record_count,
                "natural_record_values": record_values,
                "sample_values": int(image.get("values", 0)),
            }
        )
    return rows


def table_records_from_stats(dataset_id: str, stats: dict) -> list[dict]:
    if dataset_id == "uci_letter_recognition_u8":
        return [
            {
                "dataset_id": dataset_id,
                "series_id": "letter_ocr_features",
                "sample_path": stats.get("feature_file", ""),
                "split": "full",
                "natural_record_kind": "table_row",
                "natural_record_count": int(stats.get("rows", 0)),
                "natural_record_values": int(stats.get("features_per_row", 0)),
                "sample_values": int(stats.get("feature_values", 0)),
            }
        ]
    if dataset_id == "uci_skin_segmentation_bgr_u8":
        return [
            {
                "dataset_id": dataset_id,
                "series_id": "skin_bgr_channels",
                "sample_path": stats.get("bgr_file", ""),
                "split": "full",
                "natural_record_kind": "table_row",
                "natural_record_count": int(stats.get("rows", 0)),
                "natural_record_values": int(stats.get("channels_per_row", 0)),
                "sample_values": int(stats.get("bgr_values", 0)),
            }
        ]

    series_by_dataset = {
        "uci_optdigits_u8": "optdigits_features",
        "uci_statlog_landsat_satellite_u8": "landsat_spectral_features",
    }
    feature_key_by_dataset = {
        "uci_optdigits_u8": "feature_file",
        "uci_statlog_landsat_satellite_u8": "feature_file",
    }
    values_key_by_dataset = {
        "uci_optdigits_u8": "feature_values",
        "uci_statlog_landsat_satellite_u8": "feature_values",
    }
    known_width_by_dataset = {
        "uci_optdigits_u8": 64,
        "uci_statlog_landsat_satellite_u8": 36,
    }
    if dataset_id not in series_by_dataset:
        return []
    rows = []
    for split in stats.get("splits", []):
        record_count = int(split.get("rows", 0))
        sample_values = int(split.get(values_key_by_dataset[dataset_id], 0))
        rows.append(
            {
                "dataset_id": dataset_id,
                "series_id": series_by_dataset[dataset_id],
                "sample_path": split.get(feature_key_by_dataset[dataset_id], ""),
                "split": split.get("split", ""),
                "natural_record_kind": "table_row",
                "natural_record_count": record_count,
                "natural_record_values": known_width_by_dataset[dataset_id],
                "sample_values": sample_values,
            }
        )
    return rows


def infer_primary_series_id(dataset_id: str) -> str:
    return {
        "fashion_mnist_images_u8": "fashion_mnist_images",
        "emnist_byclass_images_u8": "emnist_byclass_images",
        "medmnist_pathmnist_images_u8": "pathmnist_images",
    }.get(dataset_id, "")


def audit_dataset(data_root: Path, dataset_id: str) -> list[dict]:
    stats_path = data_root / "filtered" / dataset_id / "ingest_stats.json"
    if not stats_path.exists():
        return []
    stats = load_json(stats_path)
    if dataset_id in {"fashion_mnist_images_u8", "emnist_byclass_images_u8", "medmnist_pathmnist_images_u8"}:
        return image_record_from_stats(dataset_id, stats)
    return table_records_from_stats(dataset_id, stats)


def summarize(rows: list[dict]) -> dict[str, dict]:
    by_dataset: dict[str, list[dict]] = {}
    for row in rows:
        by_dataset.setdefault(row["dataset_id"], []).append(row)

    summaries = {}
    for dataset_id, ds_rows in by_dataset.items():
        natural_sizes = [int(row["natural_record_values"]) for row in ds_rows if int(row["natural_record_values"]) > 0]
        record_counts = [int(row["natural_record_count"]) for row in ds_rows]
        sample_values = [int(row["sample_values"]) for row in ds_rows]
        below = [size for size in natural_sizes if size < MIN_NATURAL_RECORD_VALUES]
        summaries[dataset_id] = {
            "natural_record_samples": len(ds_rows),
            "natural_record_count": sum(record_counts),
            "sample_values_total": sum(sample_values),
            "natural_record_values_min": min(natural_sizes) if natural_sizes else 0,
            "natural_record_values_median": statistics.median(natural_sizes) if natural_sizes else 0,
            "natural_record_values_max": max(natural_sizes) if natural_sizes else 0,
            "status": "natural_record_below_floor" if below else "ok",
        }
    return summaries


def write_reports(rows: list[dict], output_md: Path, output_tsv: Path) -> None:
    output_md.parent.mkdir(parents=True, exist_ok=True)
    output_tsv.parent.mkdir(parents=True, exist_ok=True)
    summaries = summarize(rows)

    with output_tsv.open("w", encoding="utf-8") as fh:
        fh.write(
            "dataset_id\tstatus\tseries_id\tsplit\tnatural_record_kind\tnatural_record_count\tnatural_record_values\tsample_values\tsample_path\n"
        )
        for row in rows:
            status = summaries[row["dataset_id"]]["status"]
            fh.write(
                f"{row['dataset_id']}\t{status}\t{row['series_id']}\t{row['split']}\t{row['natural_record_kind']}\t{row['natural_record_count']}\t{row['natural_record_values']}\t{row['sample_values']}\t{row['sample_path']}\n"
            )

    with output_md.open("w", encoding="utf-8") as fh:
        fh.write("# Natural Boundary Audit\n\n")
        fh.write(
            "This report distinguishes physical sample files from natural records inside those files. "
            "A `natural_record_below_floor` status means the recipe currently uses block samples whose natural record size is below the 1,000-value median-sample floor.\n\n"
        )
        fh.write("| dataset_id | status | natural records | natural record values min/median/max | physical sample values |\n")
        fh.write("|---|---|---:|---:|---:|\n")
        for dataset_id in sorted(summaries):
            summary = summaries[dataset_id]
            fh.write(
                f"| `{dataset_id}` | `{summary['status']}` | {summary['natural_record_count']} | {summary['natural_record_values_min']} / {fmt(summary['natural_record_values_median'])} / {summary['natural_record_values_max']} | {summary['sample_values_total']} |\n"
            )
        fh.write("\n")
        fh.write("## Samples\n\n")
        fh.write("| dataset_id | series_id | split | natural record kind | natural records | values per natural record | physical sample values |\n")
        fh.write("|---|---|---|---|---:|---:|---:|\n")
        for row in rows:
            fh.write(
                f"| `{row['dataset_id']}` | `{row['series_id']}` | {row['split']} | {row['natural_record_kind']} | {row['natural_record_count']} | {row['natural_record_values']} | {row['sample_values']} |\n"
            )


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit natural-record boundaries hidden inside sample files.")
    parser.add_argument("dataset_ids", nargs="+")
    parser.add_argument("--data-dir", default=DEFAULT_DATA_DIR)
    parser.add_argument("--output-md", default="reports/natural_boundary_audit.md")
    parser.add_argument("--output-tsv", default="reports/natural_boundary_audit.tsv")
    args = parser.parse_args()

    data_root = REPO_ROOT / args.data_dir
    rows = []
    for dataset_id in args.dataset_ids:
        rows.extend(audit_dataset(data_root, dataset_id))
    write_reports(rows, REPO_ROOT / args.output_md, REPO_ROOT / args.output_tsv)
    print(f"wrote {args.output_md}")
    print(f"wrote {args.output_tsv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
