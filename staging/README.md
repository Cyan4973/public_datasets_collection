# Staged Recipes

`staging/` is the draft area for dataset recipes that are not accepted yet.

Use it for:
- first-pass recipe authoring
- source-path experiments
- schema or parser fixes
- recipes waiting on the user-run download step
- recipes that have downloaded but not yet passed `build.sh` and `verify.sh`

Do not move a recipe from `staging/` into `datasets/` until all of the following are true:
- the user has run the current `download.sh`
- `build.sh` succeeds from local files only
- `verify.sh` succeeds

If a staged recipe proves ineligible, unreachable, or otherwise non-acceptable:
- keep revising it in `staging/`, or
- remove it and record the outcome under `attempts/`

Recommended layout:

```text
staging/
  <dataset_id>/
    manifest.toml
    README.md
    download.sh
    build.sh
    verify.sh
    scripts/
```
