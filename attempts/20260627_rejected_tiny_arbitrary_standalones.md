# Tiny Arbitrary Standalone Recipes

- Date: 2026-06-27
- Status: rejected
- Candidate dataset: eleven previously accepted but below-floor standalone recipes:
  `nuget_search`, `musicbrainz_recordings`, `cratesio_crates`,
  `datacite_dois`, `hex_packages`, `osm_overpass_cafes`,
  `stackexchange_top_questions_jan_2024`, `musicbrainz_release_groups`,
  `openfoodfacts_products`, `pokemontcg_cards`, and `artic_artworks_search`
- Source: assorted public package, catalog, search, map, and question APIs
- Why it looked promising: each source exposed public numeric metadata fields
  such as counts, dates, coordinates, scores, lengths, or market values
- Failure class: below_floor; arbitrary query or ranked/sliced scope
- What happened: the current recipes emitted only tiny first-page, keyword,
  top-ranked, or one-bounding-box slices. They failed the current aggregate
  and median natural-sample floors and did not define coherent material broad
  enough to repair in place.
- Evidence: refreshed `reports/accepted_recipe_audit.tsv` classified all
  eleven as `below_floor`; `reports/tiny_standalone_extension_triage.md`
  classifies their current shapes as arbitrary search/ranked/sliced recipes
  requiring redesign rather than simple acceptance.
- Logs: not rerun during this cleanup; decision is based on existing audit
  indices under `.data/index/` and committed manifests.
- Decision: remove the current accepted recipe directories. The upstream
  sources are not permanently banned; future replacements must use explicit,
  coherent, materially sized scopes and homogeneous numeric series.
- Retry conditions: redesign as broad catalog/time-window/category recipes
  that pass floors without relying on arbitrary search terms, top lists, or
  local concatenation of tiny records.
