# Evaluation-only recipes

This directory contains reproducible numeric benchmarks that are deliberately
excluded from the training corpus. A recipe here does not count as an accepted
dataset and must never be used to populate training indexes.

Isolation requirements:

- all payloads, indexes, samples, statistics, and logs live under
  `.data/evaluation/<dataset_id>/`;
- evaluation recipes never write to `.data/samples/`, `.data/index/`, or
  `.data/filtered/`;
- every manifest and index row declares `intended_use = "evaluation_only"`
  and `training_eligible = false`;
- recipes are absent from `attempts/dataset_status.tsv` and
  `reports/accepted_recipe_audit.tsv`;
- unclear rights must be stated plainly and must not be represented as a
  permissive training license; and
- model weights, codec logic, and hyperparameters should be frozen before the
  material is evaluated. Repeated tuning converts a holdout into development
  data and invalidates the intended use.

The repository stores recipes and hashes only. It does not redistribute
evaluation payloads or grant rights to use them.
