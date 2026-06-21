# inaturalist_observations

- Date: 2026-06-20
- Status: rejected (removed; superseded as a slot by ChEMBL molecule properties)
- Candidate dataset: iNaturalist observations
- Source:
  - `https://api.inaturalist.org/v1/observations`
- Why it looked promising:
  - very large population (~356M observations)
  - per-observation numeric fields (lat/lon, dates, engagement counts, positional accuracy)
- Failure class:
  - low value-per-byte + duplicative + near-constant unique fields
- What happened:
  - Records are ~18 KB each and the API has no field projection, so a >1M
    single column would be ~18 GB and even modest per-cohort sampling ~5.5 GB.
  - The only reliably-varying fields are `longitude`/`latitude` (+ positional
    accuracy), which duplicate the existing `gbif_occurrence_2024_coordinate_sample`
    coordinate regime already in the corpus.
  - The fields unique to iNaturalist (`identifications_count`, `comments_count`,
    `faves_count`, `num_identification_agreements`, `cached_votes_total`) are
    near-constant (all 0) for obtainable recent observations; they only vary for
    older research-grade observations, still at ~18 KB/record.
- Decision:
  - Skip. Per homogeneity/value-first principles, this is low-value-per-download
    and largely duplicative of GBIF. Slot reassigned to a fresh ChEMBL molecule
    physicochemical-properties recipe.
