# Dataset Recipes

Each subdirectory under `datasets/` describes how to collect one public dataset.

Expected per-dataset files:
- `manifest.toml`: origin, resources, license metadata, generated series, and validation metadata. Start from `datasets/manifest.template.toml`.
- `README.md`: human-readable notes about the dataset and processing choices.
- `download.sh`: download selected resources into `${DATA_DIR:-.data}`.
- `build.sh`: extract, filter, convert, and generate samples from local resources.
- `verify.sh`: validate expected checksums, sizes, counts, and output format.
- `scripts/`: optional helper scripts used by the main shell entry points.

Dataset payloads do not belong in this directory. Downloads, extracted data, filtered data, and generated samples should live under the gitignored local data directory, `.data/` by default.
