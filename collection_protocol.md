The goal of this repository is to gather public datasets to train a Data Compression Transformer.

This repository stores reproducible recipes, not dataset payloads. Accepted recipes must satisfy the hard rules below. Explanatory examples and past failure modes live in `reports/protocol_case_law.md`, `reports/family_homogeneity_policy.md`, and `reports/below_floor_triage.md`.

## Hard Rules

1. One recipe must collect one coherent material.
   Same API, portal, vendor, or cadence is not enough. Material type, generation process, and unit semantics must cohere.

2. The payload must be real source material, not a synthetic local numericization.
   Native numeric content is allowed. Pinned derived operational numeric representations are allowed only when they are stable machine-facing artifacts. Arbitrary remaps, gratuitous width mirrors, selector-gap streams, helper overlays, and similar local inventions are out.

3. Primary numeric series must be decoded typed values, not opaque file-container bytes.
   Treating arbitrary serialized bytes as `uint8` is not acceptable. NetCDF/HDF5, ZIP, NPY, FITS, PNG, TFRecord, database, checkpoint, and other container formats must be decoded to the intended source variable, tensor, raster, record field, or other typed payload before they can be primary series. If the recipe cannot decode the format without an acceptable dependency/tooling path, reject or defer the dataset instead of preserving complete file bytes as a shortcut.

4. Intrinsically thin scopes are not acceptable.
   Single entities, single snapshots, single pages, single arbitrary queries, ranked feeds, or other bounded slices that remain tiny even after exhausting the documented scope do not belong in `datasets/`.

5. Acceptance floors apply to primary payload only.
   Coordinate helpers, calendar decompositions, alignment arrays, IDs, masks, flags, and similar auxiliary metadata may be emitted if justified, but they must not help a recipe pass acceptance.

6. Aggregate-only salvage is not acceptable.
   A recipe must reach the floor through materially sized primary samples, not by multiplying trivial ones. Current floor: at least `10,000` primary values total or at least `100 KB` primary sample bytes, plus median primary sample size at least `1,000` values.

7. Dataset size must stay operationally bounded.
   Accepted primary output must not exceed `1,000,000,000` bytes total. When the full upstream source is too large, the recipe must define a coherent bounded subset that can be downloaded, built, and validated directly without first fetching the oversized full source.

8. Sample boundaries must respect the natural record boundary.
   A recipe must not concatenate many smaller natural records into large physical sample files to pass the median-sample floor. If the actual primary natural records are below the median floor, the recipe is below floor even when split-level, table-level, or archive-level concatenations are large.
   Grouping by class, label, prompt, split, shard, source file, or archive is not a valid escape hatch when the upstream material has smaller independent records such as images, drawings, utterances, TFRecord payloads, FASTA records, or match/event files. The correct response is to emit natural records as samples, explicitly lower or waive a floor in a reviewed policy note, or reject the dataset.

9. Claimed scope must match realized output.
   If a recipe claims `50` sites, `20` years, or some other coverage, the accepted output must actually realize that scope or be explicitly narrowed before acceptance.

10. Accepted recipes must be public, permissively licensed, safe, and locally reproducible.
   The user must have run the current `download.sh`, and the current `build.sh` and `verify.sh` must succeed against local files.

## Minimal Mechanics

- Start experimental work in `staging/<dataset_id>/`. Promote to `datasets/<dataset_id>/` only after the current acceptance path has been run successfully.
- Each recipe should contain `manifest.toml`, `README.md`, `download.sh`, `build.sh`, and `verify.sh`.
- Payloads must stay under the gitignored local data directory, `.data/` by default. Do not commit downloads, extracted data, filtered data, or generated samples.
- `download.sh` must reject semantically invalid upstream payloads, not just transport failures.
- `build.sh` must work only from local files already present under `.data/`.
- `verify.sh` must independently check the same missing-value policy as `build.sh` and reject degenerate outputs.
- All scripts should write durable logs under `.data/logs/<dataset_id>/`.

## Manifest Requirements

- Paths in `manifest.toml` are relative to `${DATA_DIR:-.data}`.
- Each `[[series]]` entry must document semantic meaning, missing-value policy, conversion, numeric kind, bit width, endianness, sample count, total size, output path, and whether the series is `native_numeric` or `derived_operational_numeric`.
- New or touched `[[series]]` entries must declare `role = "primary"` or `role = "auxiliary"`.
- `role = "primary"` means the series is part of the actual compression target and counts toward acceptance.
- `role = "auxiliary"` means the series exists only to preserve alignment, coordinates, timestamps, bookkeeping, or similar metadata and must not count toward acceptance.
- Legacy manifests that omit `role` are audited with a narrow helper-series inference until they are migrated.
- New or touched primary `[[series]]` entries must declare a specific `natural_record_kind`. Values that describe an aggregation artifact rather than a source boundary, such as class stacks, row streams, contiguous streams, shard payloads, or generic payload streams, are not acceptable.
- New or touched primary `[[series]]` entries must declare the decoded upstream `source_format` and `source_field`. The field must be the typed measurement, tensor, raster band, geometry member, table column, or documented symbol stream being emitted. It must not be generic file bytes, complete product bytes, container payload bytes, archive members, serialized records, or other wrapper material.
- New or touched primary `[[series]]` entries must not use opaque container/file bytes as the compression target. Disallowed primary representations include generic file bytes, complete product/container bytes, serialized container payloads, compressed archive bytes, and dependency-avoidance copies of wrappers instead of decoded source variables.
- Each accepted recipe must generate a machine-readable sample index under `.data/index/<dataset_id>/samples.jsonl` containing one row per sample file with `dataset_id`, `series_id`, `sample_path`, `numeric_kind`, `bit_width`, `endianness`, `element_size_bytes`, `sample_size_bytes`, and `value_count`.

## Batch Execution

- Temporary batch launchers are allowed for user convenience.
- Keep them outside the repository, typically under `/tmp/`.
- They must call the per-dataset `download.sh` scripts and must not replace per-dataset acceptance decisions.
- Batch runs should emit a local summary under `.data/batches/<batch_id>/`.
