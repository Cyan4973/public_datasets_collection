# Tiny Standalone Extension Triage

Date: 2026-06-15

Scope: accepted non-family standalone recipes with `<= 500` primary values in
`reports/accepted_recipe_audit.tsv`.

This is a pre-removal triage. A recipe being tiny is not, by itself, proof that
the upstream source is useless. The question is whether the current recipe can be
extended into one coherent material without violating the protocol.

Initial count before this removal pass: `41`
Current pending count: `6`

## Summary

- repairable by straightforward pagination, cursoring, or bounded time windows: `23`
- repairable only as a redesign/replacement because current query is arbitrary, ranked, or too narrow: `12`
- removed or superseded so far: `22`
- remaining repairable by straightforward pagination, cursoring, or bounded time windows: `6`
- remaining redesign/replacement candidates because current query is arbitrary, ranked, or too narrow: `0`

## Removed In First Pass

- `figshare_articles`
- `crossref_funders`
- `npm_search_packages`
- `esco_occupations`
- `orcid_search`
- `steamspy_top100in2weeks`
- `internet_archive_metadata`
- `nasa_neows_feed`
- `chembl_molecules`
- `openfda_drug_event`
- `treasury_avg_interest_rates`

## Removed In 2026-06-27 Cleanup

These current accepted recipe directories were removed because they remained
below floor and their committed shape was an arbitrary search, ranked page, or
one-off spatial slice. The source families can return only as redesigned,
coherent, materially sized recipes.

- `artic_artworks_search`
- `cratesio_crates`
- `datacite_dois`
- `hex_packages`
- `musicbrainz_recordings`
- `musicbrainz_release_groups`
- `nuget_search`
- `openfoodfacts_products`
- `osm_overpass_cafes`
- `pokemontcg_cards`
- `stackexchange_top_questions_jan_2024`

## Repaired So Far

- `internetarchive_advancedsearch`: extended to a bounded 10,000-row Internet Archive text metadata slice; now passes the floor.
- `openalex_works_2024_sample`: extended to a bounded 20,000-work 2024 cursor-paginated OpenAlex table; now passes the floor with 460,000 primary values and 1,160,000 primary bytes.
- `nvd_cves_recent`: extended to bounded full-year 2024 NVD API pagination; now passes the floor with 244,224 primary values and 651,264 primary bytes.
- `medrxiv_details`: extended to bounded full-year 2024 medRxiv details pagination; now passes the floor with 77,615 primary values and 186,276 primary bytes.
- `europe_pmc_search`: extended to a bounded January 2024 Europe PMC cursor-paginated search; now passes the floor with 1,127,748 primary values and 2,631,412 primary bytes.
- `arxiv_cs_recent`: replaced by `arxiv_cs_lg_2024q1_metadata`, a bounded arXiv `cs.LG` 2024 Q1 submitted-date window; now passes the floor with 38,360 primary values and 115,080 primary bytes.
- `gbif_occurrence`: replaced by `gbif_occurrence_2024_coordinate_sample`, a bounded January 2024 GBIF coordinate-bearing occurrence sample; now passes the floor with 95,952 primary values and 527,736 primary bytes.
- `gutendex_books`: replaced by `gutendex_catalog_books`, the full Gutendex catalog in ascending order; now passes the floor with 203,883 primary values and 565,180 primary bytes.
- `library_of_congress_items`: extended to a bounded 15,000-record LOC item result prefix; now passes the floor with 66,380 primary values and 264,316 primary bytes.
- `osf_preprints`: extended to a bounded 20,000-record OSF preprint corpus; now passes the floor with 59,997 primary values and 239,988 primary bytes.
- `ooni_measurements`: replaced the latest-page snapshot with a bounded January 2024 OONI `web_connectivity` measurement window; now passes the floor with 60,000 primary values and 240,000 primary bytes.
- `anilist_media`: extended from a tiny popular-media page into materially sized per-period numeric families; now passes the floor.
- `weathergov_stations`: extended from the first 100 stations into the bounded paginated weather.gov station catalog; now passes the floor with 146,184 primary values and 974,560 primary bytes.

## Per-Recipe Assessment

| recipe | current shape | extension path | recommendation |
|---|---|---|---|
| `openbrewerydb_breweries` | Open Brewery DB first page, 3 series, 246 values | Page through brewery records. | Repairable by pagination, but numeric payload is weak. |
| `gleif_lei_records` | GLEIF LEI records first page, 4 series, 400 values | LEI API is pageable. | Repairable by pagination, but review whether date/count fields are strong enough. |
| `wger_exercises` | wger exercise listing first page, 4 series, 400 values | API pagination can cover the exercise corpus, but numeric density is weak. | Repairable but low priority. |
| `gitlab_projects` | GitLab public projects first page, 5 series, 500 values | GitLab API supports pagination. | Repairable by pagination, but public-project listing is volatile. |
| `huggingface_datasets` | Hugging Face datasets first page, 5 series, 500 values | API has listing/pagination/cursor options, but volatility and license fields need review. | Repairable by pagination if reproducibility is controlled. |
| `pride_projects_search` | PRIDE project search for `proteomics`, 5 series, 500 values | Search endpoint has page/pageSize; proteomics scope is plausible but still query-based. | Repairable with explicit scope and pagination. |

## Recommended Order

1. Repair remaining high-confidence pageable/time-windowed sources such as
   `gleif_lei_records` and `pride_projects_search`.
2. Revisit medium-confidence catalog/search recipes only if the replacement
   scope can be made explicit and homogeneous.
