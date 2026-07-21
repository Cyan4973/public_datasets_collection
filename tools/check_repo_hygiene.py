#!/usr/bin/env python3
"""Repository guardrails for tracked recipe hygiene."""

from __future__ import annotations

import csv
from pathlib import Path
import subprocess
import sys
import tomllib


ALLOWED_STAGING_PATHS = {"staging/README.md"}

STATUS_REGISTRY_PATH = Path("attempts/dataset_status.tsv")
STATUS_REGISTRY_COLUMNS = [
    "dataset_id",
    "status",
    "active_path",
    "evidence_path",
    "replacement_id",
    "reason",
    "retry_condition",
]
ALLOWED_DATASET_STATUSES = {
    "accepted",
    "blocked",
    "deferred",
    "needs_tooling",
    "rejected",
    "superseded",
    "transient_failure",
}
NON_ACTIVE_DATASET_STATUSES = ALLOWED_DATASET_STATUSES - {"accepted"}

LEGACY_NATURAL_BOUNDARY_VIOLATIONS = {
    # Historical accepted recipes that grouped independent small images/drawings
    # into class-level samples to clear sample-size floors. Keep these explicit
    # until the recipes are repaired or retired; do not add new entries lightly.
}

BLIND_CONCAT_PATTERNS = [
    (
        "grouped_by_floor",
        ["grouped by", "floor"],
    ),
    (
        "concatenated_pixel_class_sample",
        ["one sample per (split", "concatenated"],
    ),
    (
        "bitmap_stack_per_class",
        ["bitmap-stack sample per class"],
    ),
    (
        "class_level_bitmap_stack",
        ["bitmap stacks by prompt class"],
    ),
]

AMBIGUOUS_NATURAL_RECORD_KINDS = {
    "",
    "bitmap_class",
    "class_stack",
    "contiguous_stream",
    "image_class_pixels",
    "payload_stream",
    "row_stream",
    "shard_payload",
}

OPAQUE_PRIMARY_REPRESENTATION_CLASSES = {
    "container_bytes",
    "container_payload_bytes",
    "file_bytes",
    "opaque_bytes",
    "serialized_bytes",
}

OPAQUE_PRIMARY_TEXT_PATTERNS = [
    ("complete_file_bytes", ["complete", "file bytes"]),
    ("complete_container_bytes", ["complete", "container", "bytes"]),
    ("complete_product_bytes", ["complete", "product", "bytes"]),
    ("container_bytes", ["container bytes"]),
    ("file_container_bytes", ["file-container bytes"]),
    ("hdf5_product_bytes", ["hdf5", "product", "bytes"]),
    ("netcdf_product_bytes", ["netcdf", "product", "bytes"]),
    ("opaque_bytes", ["opaque", "bytes"]),
    ("serialized_payload", ["serialized", "payload"]),
    ("copy_complete_source", ["copy", "complete", "source", "unchanged"]),
    ("preserve_complete_product", ["preserve", "complete", "product", "bytes"]),
]


def git_lines(*args: str) -> list[str]:
    result = subprocess.run(
        ["git", *args],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return [line for line in result.stdout.splitlines() if line]


def changed_dataset_manifests() -> set[Path]:
    paths: set[Path] = set()
    for args in [
        ("diff", "--name-only", "--", "datasets"),
        ("diff", "--cached", "--name-only", "--", "datasets"),
        ("ls-files", "--others", "--exclude-standard", "datasets"),
    ]:
        for path in git_lines(*args):
            candidate = Path(path)
            if candidate.parts[:1] == ("datasets",) and candidate.name == "manifest.toml":
                paths.add(candidate)
    return paths


def role_of(series: dict[str, object]) -> str:
    return str(series.get("role", "primary"))


def joined_series_text(series: dict[str, object]) -> str:
    values: list[str] = []
    for key in [
        "description",
        "semantic_meaning",
        "representation_class",
        "representation_notes",
        "conversion",
        "sample_format",
        "sample_geometry",
        "natural_record_kind",
    ]:
        value = series.get(key)
        if isinstance(value, str):
            values.append(value)
    return " ".join(values).lower()


def load_status_registry(errors: list[str]) -> dict[str, dict[str, str]]:
    if not STATUS_REGISTRY_PATH.exists():
        errors.append(f"Missing dataset status registry: {STATUS_REGISTRY_PATH}")
        return {}

    with STATUS_REGISTRY_PATH.open("r", encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh, delimiter="\t")
        if reader.fieldnames != STATUS_REGISTRY_COLUMNS:
            errors.append(
                f"{STATUS_REGISTRY_PATH}: expected TSV columns {STATUS_REGISTRY_COLUMNS}, "
                f"got {reader.fieldnames}"
            )
            return {}

        registry: dict[str, dict[str, str]] = {}
        for line_number, row in enumerate(reader, 2):
            dataset_id = (row.get("dataset_id") or "").strip()
            status = (row.get("status") or "").strip()
            if not dataset_id:
                errors.append(f"{STATUS_REGISTRY_PATH}:{line_number}: missing dataset_id")
                continue
            if dataset_id in registry:
                errors.append(
                    f"{STATUS_REGISTRY_PATH}:{line_number}: duplicate dataset_id "
                    f"{dataset_id}"
                )
                continue
            if status not in ALLOWED_DATASET_STATUSES:
                errors.append(
                    f"{STATUS_REGISTRY_PATH}:{line_number}: invalid status {status!r} "
                    f"for {dataset_id}"
                )
            registry[dataset_id] = {
                key: (value or "").strip() for key, value in row.items()
            }

    return registry


def check_status_registry(
    errors: list[str], registry: dict[str, dict[str, str]]
) -> None:
    for dataset_id, row in sorted(registry.items()):
        status = row["status"]
        active_path = row["active_path"]
        evidence_path = row["evidence_path"]
        replacement_id = row["replacement_id"]

        if evidence_path and not Path(evidence_path).exists():
            errors.append(
                f"{STATUS_REGISTRY_PATH}: evidence_path for {dataset_id} does not exist: "
                f"{evidence_path}"
            )
        replacement_path = Path("datasets") / replacement_id
        if (
            replacement_id
            and replacement_id not in registry
            and not replacement_path.exists()
        ):
            errors.append(
                f"{STATUS_REGISTRY_PATH}: replacement_id for {dataset_id} is not registered "
                f"or active: {replacement_id}"
            )

        dataset_path = Path("datasets") / dataset_id
        if status in NON_ACTIVE_DATASET_STATUSES:
            if active_path:
                errors.append(
                    f"{STATUS_REGISTRY_PATH}: non-active dataset {dataset_id} "
                    f"must not set active_path."
                )
            if dataset_path.exists():
                errors.append(
                    f"Non-active dataset is present under datasets/: {dataset_id} "
                    f"status={status}"
                )
                errors.append(f"  reason: {row['reason']}")
        elif status == "accepted":
            if not active_path:
                errors.append(
                    f"{STATUS_REGISTRY_PATH}: accepted dataset {dataset_id} needs active_path."
                )
            elif not Path(active_path).exists():
                errors.append(
                    f"{STATUS_REGISTRY_PATH}: active_path for accepted dataset {dataset_id} "
                    f"does not exist: {active_path}"
                )
            if not dataset_path.exists():
                errors.append(
                    f"{STATUS_REGISTRY_PATH}: accepted dataset {dataset_id} is not present "
                    f"under datasets/."
                )


def check_natural_boundaries(errors: list[str]) -> None:
    changed_manifests = changed_dataset_manifests()

    for manifest_path in sorted(Path("datasets").glob("*/manifest.toml")):
        dataset_id = manifest_path.parent.name
        text = manifest_path.read_text(encoding="utf-8")
        lower = text.lower()

        if dataset_id not in LEGACY_NATURAL_BOUNDARY_VIOLATIONS:
            for pattern_name, needles in BLIND_CONCAT_PATTERNS:
                if all(needle in lower for needle in needles):
                    errors.append(
                        "Possible blind concatenation of natural records in accepted manifest."
                    )
                    errors.append(
                        f"  dataset: {dataset_id} pattern={pattern_name} path={manifest_path}"
                    )

        if manifest_path not in changed_manifests:
            continue

        try:
            manifest = tomllib.loads(text)
        except tomllib.TOMLDecodeError as exc:
            errors.append(f"Invalid TOML manifest: {manifest_path}: {exc}")
            continue

        for index, series in enumerate(manifest.get("series", []), 1):
            if not isinstance(series, dict):
                continue
            series_id = str(series.get("id", f"series_{index}"))
            role = role_of(series)
            if role not in {"primary", "auxiliary"}:
                errors.append(
                    f"{manifest_path}: series {series_id} must declare role='primary' or role='auxiliary'."
                )
                continue
            if role != "primary":
                continue
            natural_record_kind = str(series.get("natural_record_kind", "")).strip()
            if natural_record_kind in AMBIGUOUS_NATURAL_RECORD_KINDS:
                errors.append(
                    f"{manifest_path}: primary series {series_id} needs a specific natural_record_kind; "
                    f"got {natural_record_kind!r}."
                )
            representation_class = str(series.get("representation_class", "")).strip()
            if representation_class in OPAQUE_PRIMARY_REPRESENTATION_CLASSES:
                errors.append(
                    f"{manifest_path}: primary series {series_id} uses opaque "
                    f"representation_class={representation_class!r}; decode the "
                    "source variable/field or reject/defer the dataset."
                )
            series_text = joined_series_text(series)
            for pattern_name, needles in OPAQUE_PRIMARY_TEXT_PATTERNS:
                if all(needle in series_text for needle in needles):
                    errors.append(
                        f"{manifest_path}: primary series {series_id} appears to use "
                        f"opaque container/file bytes pattern={pattern_name}; decode "
                        "the source variable/field or reject/defer the dataset."
                    )


def main() -> int:
    errors: list[str] = []

    tracked_staging = [
        path
        for path in git_lines("ls-files", "staging")
        if path not in ALLOWED_STAGING_PATHS
    ]
    if tracked_staging:
        errors.append(
            "Tracked staging material is forbidden; only staging/README.md may be tracked."
        )
        errors.extend(f"  tracked: {path}" for path in tracked_staging)

    staged_staging = [
        path
        for path in git_lines(
            "diff",
            "--cached",
            "--name-only",
            "--diff-filter=ACMR",
            "--",
            "staging",
        )
        if path not in ALLOWED_STAGING_PATHS
    ]
    if staged_staging:
        errors.append(
            "Staged additions/modifications under staging/ are forbidden; keep drafts ignored."
        )
        errors.extend(f"  staged: {path}" for path in staged_staging)

    tracked_data = git_lines("ls-files", ".data")
    if tracked_data:
        errors.append("Tracked .data payload material is forbidden.")
        errors.extend(f"  tracked: {path}" for path in tracked_data)

    staged_data = git_lines(
        "diff",
        "--cached",
        "--name-only",
        "--diff-filter=ACMR",
        "--",
        ".data",
    )
    if staged_data:
        errors.append("Staged additions/modifications under .data/ are forbidden.")
        errors.extend(f"  staged: {path}" for path in staged_data)

    registry = load_status_registry(errors)
    check_status_registry(errors, registry)
    check_natural_boundaries(errors)

    if errors:
        print("repository hygiene check failed:", file=sys.stderr)
        print("\n".join(errors), file=sys.stderr)
        return 1

    print("repository hygiene check passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
