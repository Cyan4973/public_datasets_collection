# OSM Daily Way References Int64 Development — 2026-07-29

`osm_daily_way_references_i64` adds graph-topology pointer sequences to the
64-bit corpus. Its primary values are node identifiers referenced by edited
OpenStreetMap ways, not hashes, serialized XML bytes, or compressed payloads.

The candidate was grounded against committed `datasets/*/manifest.toml`,
`attempts/dataset_status.tsv`, and `reports/accepted_recipe_audit.tsv`. Existing
OSM coverage consisted mainly of Taginfo statistics; no accepted decoded way
topology stream was present.

## Pinned source

An exploratory user run selected the latest three completed daily replication
sequences. The accepted recipe then froze those immutable objects:

| sequence | UTC day | source bytes | SHA-256 |
|---:|---|---:|---|
| `5066` | 2026-07-27 | `92,648,123` | `4e4330eda9c18a11d8648ba9497401e5b81102ad22f8aae06436094f914563c7` |
| `5067` | 2026-07-28 | `98,493,917` | `765b9dd66fc45ae9cfd6f5a27f230c2cc9c40706e79c7cddd5b4454e6f4667b5` |
| `5068` | 2026-07-29 | `97,949,914` | `fbe8f275940c4a6eb9e51a7bd36faaa1f5e38a44d80427c45430b306b6b6dd2d` |

The user reran the pinned downloader. It validated exact sequence-state files,
source sizes, hashes, gzip integrity, and decoded XML semantics.

## Decode and validation

The streaming SAX decoder visits created and modified ways and emits every
positive `way/nd/@ref` in diff, way, and within-way order. Deleted ways without
node lists contribute no values. Each daily diff is one natural sample.

The recipe requires every sample to contain at least 1,000 references and at
least one value greater than `2^32-1`. Observed maxima were
`14,052,548,871`, `14,055,127,327`, and `14,057,409,293`, confirming that the
64-bit width is material rather than gratuitous widening.

Build and independent XML-to-output verification passed:

- daily samples: `3`
- ways with reference lists: `464,131`, `555,348`, and `531,546`
- primary values: `21,307,666`
- primary bytes: `170,461,328`
- median sample: `6,908,370` values

The streams contain graph allocation/locality structure rather than hash-like
noise. Raw deflate ratios were `0.2353`, `0.2362`, and `0.2374`, for an
aggregate ratio of `0.2363`. Verification reparses every source diff and
compares all emitted signed-int64 bytes in order.
