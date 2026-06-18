# OSF Preprints Timestamp Corpus

Bounded paginated OSF preprint metadata corpus. The recipe uses the public OSF
JSON:API preprints endpoint and emits one primary sample per timestamp field.

Pinned source pattern:

- `https://api.osf.io/v2/preprints/?page[size]=100`

Default download scope:

- follow OSF `links.next` pagination
- request up to `OSF_PREPRINTS_TARGET_RECORDS=20000` source records
- require at least `OSF_PREPRINTS_MIN_RECORDS=10000` records with all selected
  timestamp fields

Validated local run:

- source pages: 200
- source records: 20,000
- source bytes: 101,963,776
- duplicate records skipped during build: 1
- retained aligned preprint records: 19,999
- primary samples: 3
- primary values: 59,997
- primary sample bytes: 239,988
- primary sample size range: 19,999 values / 79,996 bytes for each sample

Selected primary series:

- `osf_created_unix_u32`
- `osf_modified_unix_u32`
- `osf_published_unix_u32`

Missing-value policy: records missing any selected timestamp are dropped as a
record unit so all three timestamp samples remain aligned over the same preprint
record axis.

Acceptance checks:

- at least 10,000 complete timestamp records
- at least 10,000 primary values
- at least 100 KB primary sample bytes
- median primary sample size at least 1,000 values
- no globally constant sample
