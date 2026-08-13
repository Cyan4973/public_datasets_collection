# Blocked: Zenodo SigMF complex 8-bit RF recordings

- Date: 2026-08-13
- Status: blocked
- Candidate dataset ID: `zenodo_sigmf_ci8`
- Source catalog: <https://zenodo.org/>
- Intended material: complete native SigMF `ci8` or `cu8` software-defined-radio
  recordings, preserving each interleaved complex I/Q byte stream as one
  natural sample.

## Why it looked promising

Native complex 8-bit RF recordings would add high-rate ADC waveforms to the
8-bit corpus. SigMF is particularly suitable because its small JSON sidecar
declares the numeric datatype, sample rate, capture boundaries, and optional
center frequencies. A complete `ci8` or `cu8` data object can therefore be
validated as typed numeric values rather than treated as opaque file bytes.
Eight-bit components also have no byte-order ambiguity and already satisfy the
corpus little-endian requirement.

## Discovery performed

The user ran two metadata-only discovery passes. The final pass superseded the
first and searched nine queries covering `ci8`, `cu8`, int8/uint8, direct
`.sigmf-data` names, and broader SigMF/SDR terminology. It inspected as many as
four 25-result Zenodo pages per query and deduplicated records by stable Zenodo
record ID.

The search required:

- an explicit CC0 or CC BY license;
- a directly exposed, stem-matched `.sigmf-data`/`.sigmf-meta` pair;
- a raw data object between 10 MB and 900 MB;
- `core:datatype` equal to standard SigMF `ci8` or `cu8`;
- a positive declared sample rate and complete two-byte complex-I/Q framing.

Only small record JSON and `.sigmf-meta` files were fetched. No
`.sigmf-data` payload was downloaded.

## Result

The expanded pass examined 474 unique Zenodo search hits. Of those, 145 lacked
an explicitly allowed CC0/CC BY license and were excluded before payload
qualification. Six substantial, licensed, direct SigMF pairs reached metadata
datatype validation, but they declared `cf32_le` or `ci16_le`, not `ci8` or
`cu8`:

- two HADES-D recordings: `cf32_le`;
- one Crab giant-pulse recording: `ci16_le`;
- one generic IQ recording: `cf32_le`;
- two V16 NB-IoT recordings: `ci16_le` (already represented by the accepted
  `zenodo_v16_nb_iot_sigmf_ci16` recipe).

Qualified complex-8-bit pairs: **0**. Qualified data bytes: **0**.

Evidence is retained in ephemeral discovery output:

- `.data/discovery/zenodo_sigmf_ci8/summary.json`
- `.data/discovery/zenodo_sigmf_ci8/query_stats.json`
- `.data/discovery/zenodo_sigmf_ci8/candidates.tsv`
- `.data/logs/zenodo_sigmf_ci8/discover.20260813_014315.log`
- `.data/logs/zenodo_sigmf_ci8/discover.20260813_014732.log`

## Decision

Do not repeat this broad Zenodo search. The numeric representation remains a
good 8-bit target, but this acquisition route is blocked because it found no
substantial, clearly permissively licensed native `ci8`/`cu8` pair.

Retry only when an exact source is already known to expose a substantial
native SigMF `ci8` or `cu8` recording under explicit CC0 or CC BY terms.
