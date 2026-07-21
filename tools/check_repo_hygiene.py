#!/usr/bin/env python3
"""Repository guardrails for tracked recipe hygiene."""

from __future__ import annotations

from pathlib import Path
import subprocess
import sys
import tomllib


ALLOWED_STAGING_PATHS = {"staging/README.md"}

REJECTED_DATASET_IDS = {
    "fmnist_px_u8": (
        "Rejected on 2026-07-21: natural records are individual 28x28 images "
        "with 784 uint8 values; class-level concatenation is forbidden."
    ),
    "google_quickdraw_bitmap_classes_u8": (
        "Rejected on 2026-07-21: natural records are individual 28x28 drawings "
        "with 784 uint8 values; prompt-class concatenation is forbidden."
    ),
    "mnist_px_u8": (
        "Rejected on 2026-07-21: natural records are individual 28x28 images "
        "with 784 uint8 values; class-level concatenation is forbidden."
    ),
}

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


def check_natural_boundaries(errors: list[str]) -> None:
    changed_manifests = changed_dataset_manifests()

    for dataset_id, reason in sorted(REJECTED_DATASET_IDS.items()):
        dataset_path = Path("datasets") / dataset_id
        if dataset_path.exists():
            errors.append(f"Rejected dataset is present under datasets/: {dataset_id}")
            errors.append(f"  {reason}")

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

    check_natural_boundaries(errors)

    if errors:
        print("repository hygiene check failed:", file=sys.stderr)
        print("\n".join(errors), file=sys.stderr)
        return 1

    print("repository hygiene check passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
