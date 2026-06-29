# openFDA Device Event

openFDA device adverse event records from the openFDA bulk download index. The
recipe keeps one date column and separate homogeneous count columns for event
substructures; it does not emit text bytes.

Selected series:
- `openfda_device_event_date_received_ymd_u32`
- `openfda_device_event_date_changed_ymd_u32`
- `openfda_device_event_mdr_text_count_u16`
- `openfda_device_event_patient_problem_count_u16`
- `openfda_device_event_product_problem_count_u16`

Download knobs:
- `OPENFDA_DEVICE_EVENT_DOWNLOAD_INDEX_URL` defaults to
  `https://api.fda.gov/download.json`.
- `OPENFDA_DEVICE_EVENT_MAX_RECORDS` defaults to `10000`.
- `OPENFDA_DEVICE_EVENT_MIN_RECORDS` defaults to `5000`.
- `OPENFDA_DEVICE_EVENT_MAX_PARTITIONS` defaults to `8`.
- `OPENFDA_DEVICE_EVENT_PARTITION_FILTER` optionally filters bulk partitions by
  display name or URL.
- `OPENFDA_DEVICE_EVENT_BULK_URLS` optionally bypasses the index with explicit
  `.json.zip` bulk URLs.

Build knobs:
- `OPENFDA_DEVICE_EVENT_MIN_RETAINED_RECORDS` defaults to `5000`.
