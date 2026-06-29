# OpenML Tasks Large

Bounded OpenML task listing. The default download target is 20,000 task
records, not a single API page.

Selected series:
- `openml_task_id_u32`
- `openml_dataset_id_u32`
- `openml_task_type_id_u16`
- `openml_number_of_instances_f32`
- `openml_number_of_features_f32`
- `openml_number_of_classes_f32`
- `openml_number_of_missing_values_f32`
- `openml_number_of_instances_with_missing_values_f32`
- `openml_number_of_numeric_features_f32`
- `openml_number_of_symbolic_features_f32`

Missing-value policy: filters task rows missing required quality metrics.

Download knobs:
- `OPENML_TASKS_LARGE_TARGET_RECORDS` defaults to `20000`.
- `OPENML_TASKS_LARGE_MIN_RECORDS` defaults to `10000`.
- `OPENML_TASKS_LARGE_PAGE_SIZE` defaults to `1000`.
- `OPENML_TASKS_LARGE_REQUEST_DELAY_SECONDS` defaults to `1`.
