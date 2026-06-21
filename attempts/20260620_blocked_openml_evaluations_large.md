# openml_evaluations_large

- Date: 2026-06-20
- Status: blocked (recipe parked in staging/; API requires scoping)
- Candidate dataset: OpenML run evaluations, per-metric families
- Source:
  - `https://www.openml.org/api/v1/json/evaluation/list/function/<metric>/limit/10000/offset/0`
- Why it looked promising:
  - millions of run evaluations; per-metric families (predictive_accuracy, AUC,
    f_measure, kappa, RMSE, MAE, runtime) are homogeneous and varied
  - far better material than `openml_runs_large`, which only exposes sequential IDs
- Failure class:
  - upstream API requires a scope; function-only listing not allowed
- What happened:
  - Every metric returned HTTP 412 (OpenML "no results") at offset 0. OpenML's
    `evaluation/list` does not support an unbounded function-only dump; it requires
    a scope (task / flow / study / run / uploader).
  - The >1M single-column model is therefore not reachable directly. A viable
    redesign would be per-(metric, task-or-study) samples scoped to large benchmark
    suites, where family=metric and samples=tasks/studies with enough runs — more
    involved and uncertain (most tasks have few runs).
- Decision:
  - Park. `openml_runs_large` (sequential IDs only) is weak material and not worth
    repairing as-is. Revisit OpenML later via task/study-scoped evaluation queries
    if a clean set of high-run benchmark suites is identified.
  - Recipe preserved at `staging/openml_evaluations_large/` (structure/guards correct;
    only the scoping is missing).
