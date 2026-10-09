# Autocollect Criteria

Shared reading for every autocollect role (scout, screener, builder, judge).

The authoritative rules are `collection_protocol.md`; worked examples live in
`reports/protocol_case_law.md` and `reports/family_homogeneity_policy.md`.
This file adds the judgment lessons accumulated in manual review sessions so
the automated roles apply the same taste. Apart from the protocol's explicit
numbers (floors, 1 GB cap), these are judgment calls with rationale, not
mechanical gates. `tools/autocollect/gate.py` checks only the mechanical part.

## What a new family is

- One accepted recipe collecting one coherent material, whose primary series
  sit at the target width (8, 16, 32 or 64 bits), and which is new to the
  local corpus.
- This repository **collects** material at natural record boundaries. It does
  not prepare training units: no sharding or tiling of large natural records.
  Big samples are not a defect. Downstream selection sub-samples roughly
  100 MB per family, so a bit above 100 MB is plenty; the 1 GB cap is
  headroom, not a target.

## Novelty is corpus-relative

Check all of these before calling anything new:

- local accepted recipes (`datasets/`) and drafts (`staging/`)
- the registry `attempts/dataset_status.tsv`, including `retry_condition`
- the pipeline ledger `pipeline/candidates.tsv`
- the downstream corpus (`numeric_datasets/<N>bit/datasets/`,
  `transformer/source_data/<width>/`)

`python3 tools/autocollect/novelty.py --url <source> --terms <words>` covers
all of them.

- The **same source file** already ingested at another width or column slice
  is not a new family (e.g. extracting age as u8 from the Census PUMS file a
  recipe already downloads for i64 columns). Grep manifests for the source
  host and path, not just the dataset id.
- Rank the kind of novelty honestly: new modality > new source > new quantity
  > new content in a known modality > width/representation only. The last is
  not new and usually violates protocol rule 2.
- A family the downstream corpus has but the local corpus lacks
  (`downstream_mirror_fill`) is legitimate and welcome; just label it as such.

## Breadth is measured on bytes

Diversity of the collection matters more than its size, and it is judged on
the bytes, not on names. Two families are similar when one existing family is
both:

- compression-equivalent: its trained OpenZL compressor compresses the
  candidate's held-out samples within 3% of the candidate's own compressor;
- statistically close: percentile distance at most 0.05 over the
  Transformer's numeric features plus order-0, order-1, delta and byte-lane
  entropies. Two copies of the same material typically sit within that
  distance; unrelated families almost never do.

`tools/autocollect/zlsim.py gate` measures this after the build, against
every baseline, downstream and accepted family of the same width. A recipe
whose primary series are all redundant is rejected automatically. Verdicts:
`STRONG` (nearest family at least 0.12 away, as far as unrelated material),
`OK` (novel), `WEAK` (redundant, rejected). Only `STRONG` and `OK` count toward
the per-width goal. History: `reports/autocollect_diversity_audit_20261006.md`
and `reports/autocollect_similarity_calibration_20261008.md`.

- The breadth keys (`measurement_type`, `instrument_line`,
  `archive_collection`) and `novelty.py --vocabulary` are descriptive aids
  for scouting, not a gate. Use them to avoid proposing obvious repeats: a
  redundant recipe costs a full build before the gate rejects it.
- A sample dominated by one value (fill or no-data) is flagged; the judge must
  justify it or ask for a repair.

## Genuine numeric quantity

- numN means a number with magnitude or ordering meaning that fits the width:
  intensities, ADC readings, quality scores, coordinates, amplitudes, fitted
  parameters, quantized weights, physical measurements.
- Not numeric: text bytes, network packet bytes, executable or bytecode
  bytes, container bytes.
- Proxy series are auxiliary metadata at best: text lengths, boolean flags,
  generic entity counts, opaque IDs, calendar decompositions. A recipe whose
  primary payload is proxies is out; a mixed one keeps only the genuine
  columns.
- Width honesty: prefer the native width. Widening (u16 codes stored as f32,
  integers stored as f64) is a gratuitous mirror. A "32-bit" family of small
  counts that never leave the u16 range is hollow; good 32-bit candidates use
  the upper bytes.

## Volume and shape

- Size to the population, not the floor. A pull sized to barely clear the
  floor reads as gaming the metric; take the whole natural population, capped
  only when it is huge, and prefer source-side field projection so the
  download stays close to what is kept.
- A thin absolute aggregate behind a huge raw download is out (the bike-share
  demand case: ~1.7 MB of counts behind tens of GB of trips). A poor
  extraction ratio alone is tolerable when the absolute kept signal is large
  and no leaner source exists.
- Diversity and entropy matter: dense cumulative curves, near-duplicate
  fixed-length series, and ranked top-N feeds are weak material even when they
  clear the floor.
- Sample-count guidance (soft): about 5 natural samples is a minimum, about 20
  is acceptable when sources are limited, 50+ is desirable when the source
  offers plenty.
  When the source offers plenty of natural records, a recipe well under ~20
  samples should take more of them rather than stop near the minimum; that is
  a repair request, not an acceptance.

## Homogeneity comes first

A family must be one compression regime: same unit, scale, tick lattice and
generation process. Never raise sample count by bundling different regimes.
The cautionary case: widening a Binance best-bid family from BTC+ETH to 20
symbols spanned ~5 orders of magnitude of price and tick size; sample count
went up and the family became incoherent. For tick-lattice data, different
scales are different families. Too few homogeneous samples is strictly better
than many mixed ones.

## Rights and access

- Require an explicit permissive license (or public-domain dedication) for
  the exact data objects. Code licenses do not cover separately hosted data
  (the Kubric MOVi case); public reachability is not a grant; free sample
  tiers often carry restrictive terms (the Tardis.dev case).
- No credentials, logins, API keys, requester-pays buckets, or captchas.
- No personal or sensitive data.

## Technical lessons for builders

- Network: the pipeline exports the `~/.curlrc` proxy to every process, but
  recipes must also run standalone for the user, where Python `urllib` cannot
  resolve hosts. Do network I/O in `download.sh` with curl; use Python only to
  parse what curl fetched.
- Big downloads: `curl -fL -C - --retry 10 --retry-delay 5 --speed-limit 1024
  --speed-time 120` into a `.part` file, then rename. Never bound big transfers
  with `--max-time` (fine for small probes). Liveness check: one-byte range
  GET with `-L`.
- Deep pagination silently caps on most search engines; use keyset
  pagination or shard the query, then sanity-check that value ranges span the
  expected domain.
- Probe first: confirm the bulk URL is live and the format is what you think
  before writing the whole recipe. Self-test binary parsers on small synthetic
  inputs.
- Compute index min/max from the stored dtype, not the float64 source value.
- LAZ point clouds: decode with `tools/laz/laszip.py` (pure stdlib, LAS point
  formats 0-3 and 6-8, byte-exact against reference LAS); import it from the
  repository instead of copying it.
- Pure standard-library Python; numpy is not available. If decoding needs a
  dependency that is not available, record `needs_tooling` instead of
  shipping container bytes.
- Pin versions, sizes and checksums; `download.sh` must reject semantically
  invalid payloads, not just transport failures.
- Throwaway scripts go in `/tmp`, never in the repository.
