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

Review checklist for a dataset recipe:
- Dataset recipe lives under `datasets/<dataset_id>/`.
- No dataset payloads, downloads, extracted data, filtered data, or generated samples are committed.
- `manifest.toml` is present and uses the current `manifest_version`.
- Origin URL, resource URLs or access descriptions, and resource versions are documented.
- License name, SPDX identifier when available, license URL/text, and citation/attribution requirements are documented.
- License is permissive; non-commercial, no-derivatives, missing, ambiguous, or otherwise restrictive licenses are rejected unless explicitly approved.
- Safety/provenance notes confirm the data is not sensitive, private, leaked, scraped personal content, or legally ambiguous.
- `download.sh` downloads only selected resources and writes under `${DATA_DIR:-.data}`.
- `build.sh` rebuilds generated samples from local downloads without fabricating, synthesizing, or augmenting data.
- `verify.sh` checks expected resource checksums/sizes where stable and validates generated sample counts, series byte sizes, and output format.
- Each generated series has documented semantic meaning, filtering/conversion summary, numeric kind, bit width, byte order, sample count, total size, and output path.
- Samples are raw homogeneous numeric arrays with no headers, delimiters, metadata blocks, compression wrappers, or bundled side data.
- Multi-byte samples are little-endian, or retained byte order is explicitly documented.
- Total generated size per series is about 1 GB or less unless explicitly approved.
