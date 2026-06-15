# Tiny Standalone Extension Triage

Date: 2026-06-15

Scope: accepted non-family standalone recipes with `<= 500` primary values in
`reports/accepted_recipe_audit.tsv`.

This is a pre-removal triage. A recipe being tiny is not, by itself, proof that
the upstream source is useless. The question is whether the current recipe can be
extended into one coherent material without violating the protocol.

Initial count before this removal pass: `41`
Current pending count: `34`

## Summary

- repairable by straightforward pagination, cursoring, or bounded time windows: `23`
- repairable only as a redesign/replacement because current query is arbitrary, ranked, or too narrow: `12`
- removed or superseded so far: `7`
- remaining repairable by straightforward pagination, cursoring, or bounded time windows: `22`
- remaining redesign/replacement candidates because current query is arbitrary, ranked, or too narrow: `12`

## Removed In First Pass

- `figshare_articles`
- `crossref_funders`
- `npm_search_packages`
- `esco_occupations`
- `orcid_search`
- `steamspy_top100in2weeks`
- `internet_archive_metadata`

## Repaired So Far

- `internetarchive_advancedsearch`: extended to a bounded 10,000-row Internet Archive text metadata slice; now passes the floor.

## Per-Recipe Assessment

| recipe | current shape | extension path | recommendation |
|---|---|---|---|
| `gutendex_books` | Gutendex `science` search first page, 6 series, 192 values | Paginate a coherent catalog slice, preferably all books or a stable subject/language subset. | Repairable as redesigned catalog recipe. |
| `library_of_congress_items` | LOC item listing, first 100 records, 4 series, 232 values | Use LOC pagination for a stable collection/search with the same fields. | Repairable by pagination if the chosen collection is coherent. |
| `openbrewerydb_breweries` | Open Brewery DB first page, 3 series, 246 values | Page through brewery records. | Repairable by pagination, but numeric payload is weak. |
| `nasa_neows_feed` | NASA NeoWs 7-day feed, 6 series, 270 values | NeoWs feed is date-windowed; extend by multiple contiguous windows. | Repairable by bounded time range. |
| `anilist_media` | AniList popular anime first page, 6 series, 295 values | GraphQL supports paging, but current popularity ranking is a moving ranked feed. | Redesign or remove; do not keep as a shallow top list. |
| `gbif_occurrence` | GBIF occurrence search first page, 3 series, 298 values | Page through a coherent occurrence query or bounded taxon/geography subset. | Repairable by pagination if scope is explicit. |
| `nuget_search` | NuGet search for `data`, 3 series, 300 values | Search supports paging, but query term is arbitrary; better source is a package catalog or curated broad query. | Redesign before keeping. |
| `osf_preprints` | OSF preprints first page, 3 timestamp series, 300 values | API pagination can widen to a stable preprint corpus. | Repairable by pagination. |
| `weathergov_stations` | Weather.gov station listing first page, 3 series, 300 values | Station endpoint is paginated. | Repairable by pagination; review primary vs auxiliary coordinate semantics. |
| `musicbrainz_recordings` | MusicBrainz recording search for `love`, 4 series, 382 values | Query is arbitrary; MusicBrainz search paging exists but a keyword search is weak material. | Redesign or remove. |
| `arxiv_cs_recent` | arXiv `cs.LG` recent feed, 4 series, 400 values | Extend by `start`/`max_results` and/or bounded submitted-date windows. | Repairable by bounded category/time scope. |
| `chembl_molecules` | ChEMBL molecules first page, 4 series, 400 values | ChEMBL supports limit/offset pagination. | Repairable by pagination; review series after prior constant-column cleanup. |
| `cratesio_crates` | crates.io search for `data`, 4 series, 400 values | Search paging exists, but query is arbitrary. | Redesign as broader crates catalog or remove. |
| `datacite_dois` | DataCite DOI search for `machine learning`, 4 series, 400 values | DataCite supports pagination, but query term is arbitrary; a resource-type or provider scope would be cleaner. | Redesign before keeping. |
| `europe_pmc_search` | Europe PMC January 2024 search page, 4 series, 400 values | Extend date range and paginate. | Repairable by bounded publication-date window. |
| `gleif_lei_records` | GLEIF LEI records first page, 4 series, 400 values | LEI API is pageable. | Repairable by pagination, but review whether date/count fields are strong enough. |
| `hex_packages` | Hex package search for `data`, 4 series, 400 values | Current endpoint/query is narrow; full package listing may be possible but must be confirmed. | Redesign before keeping. |
| `ooni_measurements` | OONI measurements first page, 4 series, 400 values | Measurement API can be bounded by time/test/country and paged. | Repairable by explicit bounded scope. |
| `openalex_works_2024_sample` | OpenAlex works 2024 first page, 2 series, 400 values | OpenAlex has cursor pagination for the same 2024 filter. | Repairable by cursor pagination. |
| `osm_overpass_cafes` | Overpass cafes in one Berlin bounding box, 4 series, 400 values | Can widen to multiple tiles or a city/region, but current bbox is arbitrary and coordinates may be auxiliary. | Redesign before keeping. |
| `stackexchange_top_questions_jan_2024` | Stack Exchange top-voted January questions, 4 series, 400 values | API pages, but `top` ranking is a bounded leaderboard, not source material. | Remove or redesign as all questions in a bounded time window. |
| `treasury_avg_interest_rates` | Treasury fiscal API first page, 4 series, 400 values | Fiscal Data API supports pagination and stable table semantics. | Repairable by pagination. |
| `wger_exercises` | wger exercise listing first page, 4 series, 400 values | API pagination can cover the exercise corpus, but numeric density is weak. | Repairable but low priority. |
| `musicbrainz_release_groups` | MusicBrainz release-group search for tag `data`, 5 series, 491 values | Query/tag is arbitrary; paging exists but material is weak. | Redesign or remove. |
| `openfoodfacts_products` | Open Food Facts `chocolate` search first page, 5 series, 491 values | Product search is pageable; better as a stable category or full bounded product subset. | Repairable as redesigned category/catalog recipe. |
| `inaturalist_observations` | iNaturalist recent observations first page, 5 series, 495 values | Observation API is pageable and can be bounded by date/place/taxon. | Repairable by explicit bounded scope. |
| `openfda_drug_event` | openFDA drug event first page, 5 series, 495 values | openFDA supports `limit`/`skip`; can use bounded received-date windows. | Repairable by pagination/time scope. |
| `pokemontcg_cards` | Pokemon TCG cards first page, 6 series, 498 values | API is pageable but domain is entertainment/card catalog; numeric market fields may be unstable. | Low-priority redesign or remove. |
| `artic_artworks_search` | Art Institute search for `cat`, 5 series, 500 values | Search query is arbitrary; ArtIC artworks API can page all artworks with selected fields. | Repairable only as redesigned artworks catalog. |
| `gitlab_projects` | GitLab public projects first page, 5 series, 500 values | GitLab API supports pagination. | Repairable by pagination, but public-project listing is volatile. |
| `huggingface_datasets` | Hugging Face datasets first page, 5 series, 500 values | API has listing/pagination/cursor options, but volatility and license fields need review. | Repairable by pagination if reproducibility is controlled. |
| `medrxiv_details` | medRxiv January 2024 first page, 5 series, 500 values | medRxiv API supports interval/cursor; extend date window and cursor. | Repairable by bounded time range. |
| `nvd_cves_recent` | NVD CVEs January 2024 first page, 5 series, 500 values | NVD supports `resultsPerPage`, `startIndex`, and date windows. | Repairable by pagination/time scope. |
| `pride_projects_search` | PRIDE project search for `proteomics`, 5 series, 500 values | Search endpoint has page/pageSize; proteomics scope is plausible but still query-based. | Repairable with explicit scope and pagination. |

## Recommended Order

1. Repair high-confidence pageable/time-windowed sources:
   `nasa_neows_feed`, `arxiv_cs_recent`, `chembl_molecules`,
   `europe_pmc_search`, `openalex_works_2024_sample`,
   `treasury_avg_interest_rates`, `openfda_drug_event`, `medrxiv_details`,
   `nvd_cves_recent`.
2. Revisit medium-confidence catalog/search recipes only if the replacement
   scope can be made explicit and homogeneous.
