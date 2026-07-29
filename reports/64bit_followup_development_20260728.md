# 64-bit Domain-Diversity Follow-up — 2026-07-28

This follow-up develops the strongest remaining candidates from
`reports/64bit_domain_diversity_hunt_20260728.md`. No external dataset payloads
were downloaded by the agent.

The inventory was grounded on committed `datasets/*/manifest.toml`,
`attempts/dataset_status.tsv`, and `reports/accepted_recipe_audit.tsv`. Scratch
content was not used to infer corpus membership.

## Accepted: NOAA CORS RINEX GNSS Observations

Recipe: `datasets/noaa_cors_rinex_observations_f64/`

This recipe adds a genuinely new instrument process: raw satellite-navigation
receiver observations. It decodes RINEX 2 station-day files into four
unit-coherent float64 families:

- C*/P* pseudorange in meters
- L* carrier phase in cycles
- D* Doppler in hertz
- S* signal strength in the RINEX receiver convention

The natural sample is one station-day/observation-code stream. Blank fixed-width
fields are skipped as missing; malformed populated fields and non-finite values
are fatal. Sub-1,000-value natural samples are reported and excluded before the
global floors are enforced.

The user-run downloader uses the official `noaa-cors-pds` bucket, a fixed
historical `rinex/2024/001/` prefix, sorted object keys, a twelve-file default,
and hard byte caps. Exact selected URLs and SHA-256 values are retained locally.

Synthetic validation exercised four observation codes over 300 epochs and ten
satellites. Build and independent verification both passed with 12,000 float64
values across four samples.

The first user run reached the fixed NOAA bucket and produced a valid twelve-file
plan, but failed before acquisition because the shell loop treated the literal
characters `\\t` as delimiters and split `https` into `tps`. The downloader now
uses a real tab delimiter and prints the tail of its durable log on failure, so
the retry was both functional and visible.

The user reran the current downloader and local build/verification passed:

- source files / bytes: `12` / `24,974,679`
- primary samples / values / bytes: `115` / `4,574,236` / `36,593,888`
- median natural sample: `32,648` values
- retained families: pseudorange, carrier phase, signal strength
- excluded sub-floor station/code samples: `7`

User runbook:

```bash
bash datasets/noaa_cors_rinex_observations_f64/download.sh
bash datasets/noaa_cors_rinex_observations_f64/build.sh
bash datasets/noaa_cors_rinex_observations_f64/verify.sh
```

## Accepted: NASA Planetary Gravity Harmonics

Recipe: `datasets/nasa_pds_gravity_harmonics_f64/`

This recipe targets a high-degree lunar or planetary gravitational-potential
model. It emits the native dimensionless cosine and sine coefficient fields
(`Cnm` and `Snm`) as two float64 model arrays. Degree/order indices remain
structural metadata rather than primary series.

The decoder supports plain text, gzip, and ZIP wrappers and recognizes ICGEM
`gfc`, PDS `GRCOEF`/`RECOEF`, and numeric coefficient rows. It requires unique
degree/order pairs, at least 10,000 coefficient rows, maximum degree at least
100, finite nonconstant fields, and output below 1 GB.

The first user run selected the official NASA PDS GRAIL GRGM1200A Bouguer
coefficient table. The draft now pins that exact URL by default; `GRAVITY_URL`
remains an explicit override.

Synthetic validation exercised a ZIP-wrapped degree-150 ICGEM model. Build and
independent verification passed with 22,952 float64 values across the two
coefficient fields.

The realized product also passed local build and independent verification:

- source bytes: `88,059,844`
- SHA-256: `3ad34406cbfc22a32d1f9ecad47a12d3449ddb2c848ea62e6049be9472afbf95`
- coefficient rows / maximum degree: `721,800` / `1200`
- primary values / bytes: `1,443,600` / `11,548,800`
- primary samples: two multi-megabyte model fields (`Cnm`, `Snm`)

User runbook:

```bash
bash datasets/nasa_pds_gravity_harmonics_f64/download.sh
bash datasets/nasa_pds_gravity_harmonics_f64/build.sh
bash datasets/nasa_pds_gravity_harmonics_f64/verify.sh
```

## Not Yet Runnable: Profile-mode mzML

`proteomexchange_profile_mzml_f64` remains high-value. The decoder shape is
clear: parse mzML XML, base64-decode and optionally zlib-decompress binary data
arrays, require the `64-bit float` CV term, and emit one m/z or intensity array
per profile spectrum. The natural-record floor should be enforced per spectrum.

What is still missing is an exact, bounded ProteomeXchange project whose:

1. license/redistribution terms are explicit and permissive
2. official file inventory includes mzML rather than vendor-only raw files
3. spectra are profile-mode and usually exceed 1,000 points
4. selected files remain comfortably below the download and 1 GB output caps

Creating a generic URL-file downloader before those facts are pinned would not
be a reproducible dataset recipe, so no staging directory was created.

## Not Yet Runnable: Published genomic MinHash sketches

`sourmash_genbank_minhash_u64` is also structurally attractive: one published
genome signature would be a natural uint64 set-like sample. It remains deferred
until an official bounded precomputed collection has clear dataset licensing,
a stable exact artifact URL, and at least 1,000 stored minima for the median
signature. Locally generating hashes only to obtain uint64 payload is explicitly
out of scope.

## Recommended Execution Order

1. Continue source-level research for one profile-mode mzML project.
2. Revisit MinHash only if an upstream published signature artifact is found.
