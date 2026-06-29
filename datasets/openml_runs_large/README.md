# OpenML Runs Large

Bounded OpenML run listing. The default download target is 20,000 run records,
not a single API page.

Selected series:
- `openml_run_id_u32`
- `openml_task_id_u32`
- `openml_setup_id_u32`
- `openml_flow_id_u32`
- `openml_uploader_u32`
- `openml_upload_timestamp_u64`

Missing-value policy: filters rows with invalid upload timestamps or required identifiers.

Download knobs:
- `OPENML_RUNS_LARGE_TARGET_RECORDS` defaults to `20000`.
- `OPENML_RUNS_LARGE_MIN_RECORDS` defaults to `10000`.
- `OPENML_RUNS_LARGE_PAGE_SIZE` defaults to `1000`.
- `OPENML_RUNS_LARGE_REQUEST_DELAY_SECONDS` defaults to `1`.
