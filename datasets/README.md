# Dataset Recipes

Each subdirectory under `datasets/` is an accepted recipe only.

Use `staging/` for drafts. Move a recipe into `datasets/` only after the user has run the current `download.sh` and the recipe has then passed local `build.sh` and `verify.sh`.

Core acceptance rules:
- one recipe, one coherent material
- no synthetic local numericizations
- no intrinsically thin scopes such as single entities, single snapshots, or arbitrary one-query slices
- acceptance floors count only `role = "primary"` series
- aggregate floor and median-sample floor must be met by primary payload, not helper metadata
- claimed scope must match realized output

Expected files:
- `manifest.toml`
- `README.md`
- `download.sh`
- `build.sh`
- `verify.sh`
- optional `scripts/`

Payloads do not belong in this directory. Downloads, extracted data, filtered data, generated indexes, and generated samples should live under `${DATA_DIR:-.data}`.

Manifest rules:
- new or touched `[[series]]` entries must declare `role = "primary"` or `role = "auxiliary"`
- auxiliary series may preserve timestamps, coordinates, masks, IDs, or bookkeeping
- auxiliary series must not count toward acceptance floors
- start new manifests from `datasets/manifest.template.toml`

Script contract:
- `download.sh` acquires only documented upstream resources and rejects semantically invalid payloads
- `build.sh` uses only local files already present under `${DATA_DIR:-.data}`
- `build.sh` and `verify.sh` must agree on missing-value handling
- `verify.sh` must reject constant and structurally degenerate outputs
- all scripts should support `DATA_DIR` and write durable logs under `${DATA_DIR:-.data}/logs/<dataset_id>/`

Current acceptance floor:
- at least `10,000` primary values total or at least `100 KB` primary sample bytes
- plus median primary sample size at least `1,000` values

For examples and edge cases, use:
- `collection_protocol.md`
- `reports/protocol_case_law.md`
- `reports/family_homogeneity_policy.md`
