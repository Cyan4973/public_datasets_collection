# Protocol Case Law

This file is non-normative. The hard rules live in `collection_protocol.md`.

Use this file for examples, cleanup precedent, and recurring failure modes.

## Count Only Primary Payload

- Calendar helpers such as `obs_year_u16`, `obs_month_u8`, `obs_day_u8`, and `obs_hour_u8` are not meaningful payload and should not be emitted as dataset series.
- Alignment metadata, masks, bookkeeping arrays, and similar helper material must not help a recipe pass acceptance floors.

## Thin Scope Failures

Reject recipes whose documented identity is intrinsically tiny even after exhausting the same scope:

- one fixed entity
- one repo snapshot
- one package page
- one arbitrary search query
- one ranked-feed slice
- one year when the full historical corpus is still tiny

If "saving" the recipe would require changing from one entity to many entities, from one query to general crawling, or from one narrow slice to a different corpus definition, that is a different recipe, not an expansion.

## Aggregate-Only Salvage

Reject recipes that clear the aggregate floor mainly by multiplying trivial samples.

Some small samples are fine. A dataset is not fine when most samples are tiny and the only acceptance story is "there are many of them."

## Single-Sample Families

A family should contain multiple homogeneous natural samples with the same field
meaning. A one-sample family is weak training material unless the source sample
is large enough to shard confidently. Treat roughly-100KB or sub-MB table-column
samples as insufficient even when they pass the historical audit floor.

If the only available shape is one full table column per field, the recipe must
either:

- produce multi-MB single-field samples that can be deterministically sharded, or
- be reshaped into multiple homogeneous natural samples without concatenating
  different field meanings.

The following Macrostrat recipes were removed on 2026-07-02 despite passing the
audit because they were one-sample-per-field table-column families and their
per-family samples were far below a shardable size:

- `macrostrat_columns`
- `macrostrat_sections`

`macrostrat_units` was left in place for separate review. Its per-field samples
are still single-sample families, but the source is materially larger than
columns/sections and may deserve a better repair path before deletion.

## Rejected Short Indicator Time Series

Short annual, monthly, weekly, and daily indicator recipes are not acceptable
when their natural same-meaning samples remain tiny. Expanding from a few
countries to many countries, or from a few yearly shards to a full but still
small national series, is aggregate-only salvage unless each natural sample is
large enough to train on or shard confidently.

The following below-floor recipes were removed on 2026-07-03. Do not recreate
them as one-indicator-per-recipe country samples, one national FRED series, or
loosely bundled portal indicators:

- all below-floor `fred_*` single-indicator recipes present on that date
- all below-floor `world_bank_*` single-indicator country recipes present on that date
- all below-floor `imf_*` annual country-indicator recipes present on that date
- all below-floor `eurostat_*` monthly country-indicator recipes present on that date
- remaining below-floor `owid_*` annual country-indicator recipes present on that date

These sources may return only if the recipe produces genuinely large
same-measure natural samples, or if a different upstream product exposes dense
numeric material rather than short country/year indicator vectors.

## Rejected Residual Metadata Recipes

The final below-floor residuals were removed on 2026-07-03 because their
committed shape was metadata/search/catalog/event-list extraction, not strong
homogeneous numeric source material. Do not repair these by widening the same
metadata shape or by adding more deterministic text lengths/counts:

- `chembl_documents`
- `coinpaprika_exchanges`
- `crossref_funders_large`
- `ena_portal_search`
- `europepmc_grants`
- `geofabrik_index`
- `gwas_catalog_studies`
- `iris_seismon_events_fixed`
- `loc_photos_search_large`
- `npi_registry_ca`
- `openfda_food_enforcement`
- `plos_search`
- `pride_projects_search`
- `smithsonian_search_large`
- `wikimedia_mostread`

Some of these sources remain valid for new recipes if the replacement uses
actual dense numeric material. Examples: ChEMBL assay/activity measurements,
GWAS association statistics, ENA FASTQ quality or signal payloads, Wikimedia
pageview/clickstream series, or geospatial rasters/vectors with naturally large
numeric records.

## Homogeneity

Reject bundles that combine unrelated indicators merely because they share:

- the same portal
- the same API
- the same cadence
- the same country
- the same publisher

Accept only bundles whose material type, generation process, cadence, and unit semantics still read as one coherent dataset.

The following accepted-but-tiny NASA POWER mixed bundles were removed on
2026-07-06 after stronger homogeneous NASA POWER recipes had been expanded.
Do not recreate these mixed bundles: repair the corresponding homogeneous
single-field POWER recipe instead.

- `nasa_power_daily_climate` mixed temperature, precipitation, and wind
- `nasa_power_daily_humidity_wind` mixed humidity and wind
- `nasa_power_daily_precip_solar` mixed precipitation, solar radiation, and humidity
- `nasa_power_daily_solar_temperature_extremes` mixed solar radiation and temperature
- `nasa_power_daily_solar_wind` mixed solar radiation and wind
- `nasa_power_daily_temp_precip_humidity` mixed temperature, precipitation, and humidity
- `nasa_power_daily_temperature_humidity` mixed temperature and humidity

## Claimed Scope Must Be Real

If a recipe claims `50` sites, `500` entities, or some other target scope, the accepted output must actually realize that scope or be narrowed before acceptance.

Do not leave aspirational scope text in the manifest or README.

## Rejected Thin Catalog/Search Shapes

The following below-floor recipes were removed on 2026-07-02 because their
committed shape was not worth repairing. They should not be reintroduced as
one-page, ranked-list, arbitrary-search, single-entity, or weak metadata-table
recipes. The source may be reconsidered only as a materially different,
homogeneous, reproducible, and sufficiently large recipe.

Superseded by stronger replacements:

- `eia_petroleum_prices` -> `eia_series_petroleum`
- `eurostat_female_unemployment_monthly` -> `eurostat_unemployment_monthly`
- `eurostat_male_unemployment_monthly` -> `eurostat_unemployment_monthly`
- `gleif_lei_records_api` -> `gleif_lei_records`
- `openml_dataset_61` -> broader OpenML recipes
- `openml_datasets` -> broader OpenML recipes
- `worldbank_gdp_constant` -> use the `world_bank_*` family only if repaired as a coherent bundle
- `worldbank_population_total` -> use the `world_bank_*` family only if repaired as a coherent bundle

Discarded as weak one-page/search/ranked/catalog metadata shapes:

- `arxiv_ai_recent`
- `coingecko_top_markets`
- `deezer_chart`
- `disease_sh_countries`
- `doaj_articles`
- `geoboundaries_all_adm0`
- `gitlab_projects`
- `huggingface_datasets`
- `itunes_search`
- `launchlibrary_upcoming`
- `marine_regions_gazetteer`
- `npm_search_packages_large`
- `openbrewerydb_breweries`
- `openlibrary_editions`
- `rubygems_versions_large`
- `scryfall_cards`
- `tvmaze_shows`
- `wger_exercises`

## Derived Numeric Representations

Accept only when the representation is:

- deterministic
- pinned
- machine-facing
- operationally real

Reject:

- arbitrary local remaps
- width mirrors
- helper overlays
- synthetic feature engineering
- duplicated views of the same underlying fact solely to inflate volume

## Opaque Container Bytes

Reject primary series that preserve file-format, container, or serialized record
bytes as a shortcut for real decoding.

To prevent repeats, every new or touched primary series must name the decoded
upstream `source_format` and `source_field`. The field must identify the actual
typed material being emitted, such as a NetCDF variable, Shapefile record member,
protobuf tensor field, image raster after container decode, table column, or
documented symbol stream. Names such as complete file, archive member, product
bytes, serialized payload, or raw container payload are rejection evidence, not
field documentation.

The following recipe was removed on 2026-07-21:

- `google_robotics_bridge_tfrecord_u8`
- `natural_earth_vector_shp_u8`
- `noaa_nexrad_level3_products_u8`

BridgeData V2 remains valuable, but TFRecord/protobuf payload bytes are not an
8-bit numeric series. A valid successor must decode documented source fields,
such as `steps/observation/image`, and emit the decoded typed values as natural
samples. TFRecord framing, protobuf structure, image container bytes, CRCs,
lengths, and source offsets may be auxiliary metadata only.

NEXRAD Level-III remains valuable, but NIDS product-message bytes are not an
8-bit radar series. A valid successor must parse the product message and emit
documented packet/product values, keeping WMO/AWIPS text, NIDS headers, block
wrappers, and packet metadata auxiliary only.
The accepted successor is `noaa_nexrad_level3_nids_radials_u8`, which decodes
packet-16 radial bins for a bounded N0Q selection.

Natural Earth vector geometry remains valuable, but Shapefile bytes are not an
8-bit geometry series. A valid successor must parse documented Shapefile records
and emit typed coordinate arrays. The accepted successor is
`natural_earth_10m_geometry_xy_f64`, which decodes polygon and polyline feature
coordinates as native float64 XY samples.
