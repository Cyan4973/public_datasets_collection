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

Batch downloads:
- It is acceptable to prepare temporary batch launcher scripts for user convenience when multiple dataset downloads should be run together.
- Batch launchers should live outside the repository, typically under `/tmp/`.
- Do not commit batch launchers under `datasets/` or elsewhere in the repository.
- Batch launchers should call the durable per-dataset `download.sh` entry points rather than reimplementing download logic.

Recommended layout:

```text
datasets/
  <dataset_id>/
    manifest.toml
    README.md
    download.sh
    build.sh
    verify.sh
    scripts/
```

Recommended local data layout under `${DATA_DIR:-.data}`:

```text
.data/
  batches/<batch_id>/
  downloads/<dataset_id>/
  extracted/<dataset_id>/
  filtered/<dataset_id>/
  index/<dataset_id>/
  samples/<dataset_id>/<series_id>/
```

Script contract:
- `download.sh` acquires only the documented upstream resources and writes them under `${DATA_DIR:-.data}/downloads/<dataset_id>/`.
- `download.sh` must validate payload semantics, not only HTTP success or file existence. API error JSON, empty structured responses, wrong-format files, or otherwise semantically invalid inputs must not be accepted into cache as successful downloads.
- `build.sh` works only from local files already present under `${DATA_DIR:-.data}`. It should not fetch from the network.
- `build.sh` may populate `${DATA_DIR:-.data}/extracted/<dataset_id>/` and `${DATA_DIR:-.data}/filtered/<dataset_id>/` when intermediate stages are useful for reproducibility or verification.
- `build.sh` emits final raw numeric samples under `${DATA_DIR:-.data}/samples/<dataset_id>/<series_id>/`.
- `build.sh` also emits a machine-readable sample index under `${DATA_DIR:-.data}/index/<dataset_id>/`.
- `build.sh` must implement an explicit missing-value policy. Upstream blanks, sentinels, flagged rows, NaNs, malformed rows, or unavailable observations must be either filtered, preserved as documented sentinel values, or treated as fatal. This policy should be stated in the dataset `README.md` and manifest.
- `verify.sh` validates pinned resource properties where stable and checks generated sample counts, sizes, encoding assumptions, and the same missing-value policy applied by `build.sh`.
- All scripts should support `DATA_DIR` overrides and be safe to rerun.
- All scripts should write durable logs under `${DATA_DIR:-.data}/logs/<dataset_id>/`.

Scaling guidance:
- Keep one dataset per recipe directory. If one upstream source yields multiple distinct numeric outputs, model them as separate `series` entries in one manifest.
- Prefer stable upstream releases, snapshots, or explicitly versioned API parameters over unpinned "latest" endpoints.
- Use deterministic file naming, sort order, and shard boundaries so two users can regenerate the same local outputs.
- Keep committed metadata concise; put bulky inventories, row counts, or derived statistics in `verify.sh` output or generated local reports instead of expanding the manifest unnecessarily.
- When the same upstream dataset can be represented at multiple numeric widths or meanings, define one series per distinct semantic output.
- If `download.sh` changes materially, rerun the updated downloader before accepting or committing the recipe. Material changes include different URLs, query parameters, selected subsets, payload-validation rules, or cache-acceptance behavior.
- If a curated subset turns out to be only partially supported upstream, narrow the subset explicitly and update the manifest, README, build logic, verify logic, and sample counts before accepting the recipe.

Batch outcomes:
- When running multiple datasets as a batch, keep the launcher ephemeral and outside the repo, but generate a machine-readable local summary under `${DATA_DIR:-.data}/batches/<batch_id>/`.
- The batch summary should record at least:
  - `dataset_id`
  - `download_status`
  - `build_status`
  - `verify_status`
  - `needs_redownload`
  - `notes`
- A batch summary is a convenience artifact for triage. It does not replace per-dataset logs or per-dataset acceptance decisions.

Review checklist for a dataset recipe:
- Dataset recipe lives under `datasets/<dataset_id>/`.
- No dataset payloads, downloads, extracted data, filtered data, or generated samples are committed.
- `manifest.toml` is present and uses the current `manifest_version`.
- Origin URL, resource URLs or access descriptions, and resource versions are documented.
- License name, SPDX identifier when available, license URL/text, and citation/attribution requirements are documented.
- License is permissive; non-commercial, no-derivatives, missing, ambiguous, or otherwise restrictive licenses are rejected unless explicitly approved.
- Safety/provenance notes confirm the data is not sensitive, private, leaked, scraped personal content, or legally ambiguous.
- `download.sh` downloads only selected resources and writes under `${DATA_DIR:-.data}`.
- `download.sh` rejects semantically invalid payloads instead of caching them as successful downloads.
- `build.sh` rebuilds generated samples from local downloads without fabricating, synthesizing, or augmenting data.
- Missing-value handling is explicit, documented, and enforced consistently in both `build.sh` and `verify.sh`.
- `download.sh`, `build.sh`, and `verify.sh` are deterministic where possible and document any unavoidable upstream mutability.
- Any multi-dataset batch launcher used during collection is ephemeral, lives outside the repository, and delegates to the committed per-dataset `download.sh` scripts.
- If `download.sh` changed materially during recipe development, the updated downloader was rerun before acceptance.
- `verify.sh` checks expected resource checksums/sizes where stable and validates generated sample counts, series byte sizes, and output format.
- A generated sample index exists under `${DATA_DIR:-.data}/index/<dataset_id>/` and includes one row per sample with numeric kind, bit width, endianness, element size, sample size, and value count.
- Each generated series has documented semantic meaning, filtering/conversion summary, numeric kind, bit width, byte order, sample count, total size, and output path.
- Samples are raw homogeneous numeric arrays with no headers, delimiters, metadata blocks, compression wrappers, or bundled side data.
- Multi-byte samples are little-endian, or retained byte order is explicitly documented.
- Total generated size per series is about 1 GB or less unless explicitly approved.
