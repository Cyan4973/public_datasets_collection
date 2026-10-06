# CESNET-TimeSeries24 institution 10-minute traffic bytes uint64 development

## Outcome

Accepted `cesnet_ts24_institution_traffic_bytes_u64` from the CESNET-TimeSeries24 Zenodo release. The family contains one native little-endian uint64 time series per CESNET3 institution: `n_bytes`, the number of bytes carried by all of that institution's IP flows in each 10-minute window over 40 weeks (2023-10-09 to 2024-07-14).

This is the first ISP traffic-volume telemetry family in the local corpus, and nothing equivalent exists downstream. The nearest neighbours are different quantities:

- `wikimedia_pageviews_daily_u32` (downstream): web request counts.
- `zenodo_zeroswarm_tcp_sequence_u32` and `zenodo_zeroswarm_modbus_registers_u16` (local): packet header and register fields from a testbed.

## Source and rights

- Source: Zenodo record 13382427, DOI 10.5281/zenodo.13382427. Single version, published 2024-09-27 by CESNET authors Koumar, Hynek, Čejka and Šiška.
- Primary archive: `institutions.tar.gz`, 479,428,489 B
  - Published MD5: `ab3e15fb8dc9b7120ddb2318795b6812`
  - SHA-256: `f112548546ae8124dd62aa55c0628a5646dc72427f280c7cf27cfde658da6ff2`
- Time grid: `times.tar.gz`, 211,467 B
  - MD5: `a03813763e07646ca38f17ffd53e549e`
  - SHA-256: `f1b0c8e20127df0646379d583dd798f84b252c9e1c82595eed207c4a3d5e1280`
- License: CC BY 4.0. The record metadata declares `license.id = cc-by-4.0` and `access_right = open` for the whole record, including both files used.
- Citation: Koumar et al., *Sci Data* 12, 338 (2025), doi:10.1038/s41597-025-04603-x.
- Privacy: institutions are identified only by opaque integer ids, and no IP addresses or per-host records are emitted.

## Shape and conversion

Each natural record is one institution's 10-minute aggregation CSV, `institutions/agg_10_minutes/<id>.csv`.

The build reads the archive once as a stream (`tarfile` `r|gz`). It locates `id_time` and `n_bytes` by header name; all 283 members share one 19-column header. Each field is parsed as an exact decimal integer and packed `<Q`. The window index `id_time` goes to an aligned `<I` auxiliary series that does not count toward acceptance.

Missing windows are skipped, not imputed: 756,619 of 278 × 40,298 windows are absent (6.7%), mostly in small institutions.

Excluded on purpose:

- `agg_1_hour` and `agg_1_day`, which re-aggregate the same windows. The judge confirmed that hourly `n_bytes` equal exact sums of six 10-minute values.
- The institution-subnet and IP-address levels.
- Every other column.

Five institutions (148, 260, 267, 279, 283) have header-only upstream 10-minute files, although their hourly and daily files have rows. Build and verify both pin this set, and any other header-only member is fatal.

## Accepted output

- Institutions in `identifiers.csv`: 283; header-only upstream: 5
- Primary samples: 278
- Primary values: 10,446,225
- Primary bytes: 83,569,800
- Auxiliary (`id_time` u32) bytes: 41,784,900
- Values per sample: min 3,402 / p10 30,328 / median 40,270 / max 40,298
- Samples covering the full 40,298-window grid: 56; samples with fewer than 10,000 values: 8
- Value range: 72 to 346,677,537,304 (39 bits); no zeros
- Width use by byte length: 1 B 0.10%, 2 B 8.29%, 3 B 45.28%, 4 B 44.16%, 5 B 2.17%, 6 B and above 0%
- Overflow evidence: 166 of 278 institutions peak above 2^32
- Per-institution maximum: median 5.66e9, p90 2.18e10
- Aggregate SHA-256 of the primary samples, concatenated in sorted filename order: `492c4269eec96a85088a8a2ff9e1a4b933f5188f97f8cec2bff44f8025741515`

Width note: uint64 is the native counter type (summed IPFIX unsigned64 octet counts) and the narrowest standard integer type that holds the data, because uint32 would overflow for 60% of samples. Upper-byte use is modest, as in other accepted u64 counter families.

## Judge checks

- **Gate:** `gate.py` gives PASS with no warnings.
- **verify.sh:** I re-ran it; exit 0. The independent csv-module parser re-derived every sample byte for byte and matched the index, the manifest counts and all 278 pinned per-institution rows.
- **Pinned expectations:** `expected_samples.tsv` is byte-identical to the rebuild's copy.
- **Local-only build:** build.sh and verify.sh contain no network calls, and the Python scripts import no network modules. There are no credential strings.
- **Byte statistics:** I decoded all samples with `struct`. Lengths, sizes and the bit-length histogram match the builder's figures. The longest run of identical consecutive values is 2. Lag-1 autocorrelation of log values is 0.53 to 0.90, consistent with diurnal traffic. No sample is a duplicate, and hashing (id_time, value) pairs found only 10 isolated cross-institution coincidences.
- **Semantics:** for institutions 0 and 49, the upstream hourly `n_bytes` equal the sums of the corresponding 10-minute values in 6,717 of 6,717 hours. So the primary is the additive base-resolution byte count.
- **Rights:** I read the downloaded record JSON: cc-by-4.0, open access, DOI, and file sizes and MD5s as pinned.
- **Novelty:** `novelty.py` found only zenodo.org host and path-prefix matches. Term searches found no traffic, octet, netflow or bandwidth family locally, in the registry or downstream.
- **Homogeneity:** one unit, one 10-minute lattice, one entity level, one network and period, and one generation process. The 7-order magnitude spread is the natural institution size distribution, not a regime mix.
